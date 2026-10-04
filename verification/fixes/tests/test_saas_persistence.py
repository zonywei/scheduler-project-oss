from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from scheduler.app.nl_rules import parse_natural_language_rule
from scheduler.app import config_service
from scheduler.config.loader import load_effective_config
from scheduler.platform import (
    PlatformDatabase,
    PlatformDatabaseSettings,
    PlatformStore,
    RevisionConflict,
    TenantNotFound,
)
from scheduler.platform.migration import import_yaml_workspace


def _store(tmp_path: Path) -> PlatformStore:
    database = PlatformDatabase(PlatformDatabaseSettings(path=tmp_path / "scheduler.db"))
    store = PlatformStore(database)
    assert store.initialize() == (1, 2, 3, 4, 5, 6)
    return store


def test_schema_migration_is_idempotent_and_database_is_healthy(tmp_path: Path) -> None:
    store = _store(tmp_path)

    assert store.initialize() == (1, 2, 3, 4, 5, 6)
    assert store.database.integrity_check() == "ok"

    with store.database.connect() as connection:
        tables = {
            str(row["name"])
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        user_columns = {
            str(row["name"])
            for row in connection.execute("PRAGMA table_info(users)")
        }
    assert {
        "organizations",
        "users",
        "sessions",
        "workspace_snapshots",
        "workspace_versions",
        "rule_drafts",
        "audit_events",
        "solve_jobs",
        "model_usage_events",
        "model_quotas",
        "model_provider_health",
        "auth_login_limits",
        "service_heartbeats",
        "conversation_sessions",
        "conversation_messages",
        "conversation_files",
    } <= tables
    assert "expires_at" in user_columns


def test_workspace_versions_use_optimistic_concurrency_and_atomic_audit(tmp_path: Path) -> None:
    store = _store(tmp_path)
    organization = store.create_organization(slug="school-a", name="学校A")

    first = store.save_workspace(
        organization.id,
        {"rules": {"calendar": {"days": ["星期一"]}}},
        expected_revision=0,
        actor_user_id="admin-a",
        reason="初始化",
    )
    second = store.save_workspace(
        organization.id,
        {"rules": {"calendar": {"days": ["星期一", "星期二"]}}},
        expected_revision=1,
        actor_user_id="admin-a",
        reason="增加星期二",
    )

    assert first.revision == 1
    assert second.revision == 2
    assert store.load_workspace(organization.id) == second
    assert [item["revision"] for item in store.list_workspace_versions(organization.id)] == [2, 1]
    events = store.list_audit_events(organization.id)
    assert [event["event_type"] for event in events] == ["workspace.saved", "workspace.saved"]
    assert events[0]["payload"] == {"reason": "增加星期二", "revision": 2}

    with pytest.raises(RevisionConflict, match="expected 1, current 2"):
        store.save_workspace(
            organization.id,
            {"rules": {}},
            expected_revision=1,
            actor_user_id="stale-client",
        )
    assert len(store.list_audit_events(organization.id)) == 2


def test_all_repository_reads_are_scoped_to_organization(tmp_path: Path) -> None:
    store = _store(tmp_path)
    school_a = store.create_organization(slug="school-a", name="学校A")
    school_b = store.create_organization(slug="school-b", name="学校B")
    store.save_workspace(school_a.id, {"secret": "A"}, expected_revision=0, actor_user_id="admin-a")
    store.save_workspace(school_b.id, {"secret": "B"}, expected_revision=0, actor_user_id="admin-b")

    assert store.load_workspace(school_a.id).payload == {"secret": "A"}  # type: ignore[union-attr]
    assert store.load_workspace(school_b.id).payload == {"secret": "B"}  # type: ignore[union-attr]
    assert all(event["actor_user_id"] == "admin-a" for event in store.list_audit_events(school_a.id))
    assert all(event["actor_user_id"] == "admin-b" for event in store.list_audit_events(school_b.id))

    with pytest.raises(TenantNotFound):
        store.load_workspace("missing-tenant")


def test_rule_drafts_are_validated_versioned_and_tenant_scoped(tmp_path: Path) -> None:
    store = _store(tmp_path)
    school_a = store.create_organization(slug="school-a", name="学校A")
    school_b = store.create_organization(slug="school-b", name="学校B")
    rule = parse_natural_language_rule("教师A 周日晚自习禁排", known_teachers=["教师A"])

    first = store.save_rule_draft(school_a.id, rule, actor_user_id="admin-a")
    second = store.save_rule_draft(school_a.id, rule, actor_user_id="admin-a")

    assert first["version"] == 1
    assert second["version"] == 2
    assert store.get_rule_draft(school_a.id, rule["id"])["rule"]["source"] == rule["source"]  # type: ignore[index]
    assert store.get_rule_draft(school_b.id, rule["id"]) is None
    assert len(store.list_rule_drafts(school_a.id)) == 1
    assert store.list_rule_drafts(school_b.id) == []

    invalid = dict(rule)
    invalid["patches"] = [{"target": "rules", "path": ["runtime", "command"], "operation": "set", "value": "x"}]
    with pytest.raises(ValueError, match="invalid rule draft"):
        store.save_rule_draft(school_a.id, invalid, actor_user_id="admin-a")


def test_yaml_migration_is_non_destructive_and_requires_force_for_new_revision(tmp_path: Path) -> None:
    database_path = tmp_path / "platform.db"
    yaml_path = tmp_path / "web_overrides.yaml"
    source = {
        "io": {"web_tables": {"teacher_subjects": [{"班级": "1班", "语文": "教师A"}]}},
        "rules": {"hard_bans": {"teacher_day_bans": {"星期日": ["教师A"]}}},
        "temporary_rules": {"active": []},
    }
    source_text = json.dumps(source, ensure_ascii=False)
    yaml_path.write_text(source_text, encoding="utf-8")

    first = import_yaml_workspace(
        database_path=database_path,
        yaml_path=yaml_path,
        organization_slug="school-a",
        organization_name="学校A",
    )
    second = import_yaml_workspace(
        database_path=database_path,
        yaml_path=yaml_path,
        organization_slug="school-a",
        organization_name="学校A",
    )
    forced = import_yaml_workspace(
        database_path=database_path,
        yaml_path=yaml_path,
        organization_slug="school-a",
        organization_name="学校A",
        force=True,
    )

    assert first["imported"] is True and first["revision"] == 1
    assert second["imported"] is False and second["revision"] == 1
    assert forced["imported"] is True and forced["revision"] == 2
    assert yaml_path.read_text(encoding="utf-8") == source_text


def test_sqlite_runtime_backend_drives_config_loader_and_detects_stale_saves(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "platform.db"
    store = PlatformStore(PlatformDatabase(PlatformDatabaseSettings(path=database_path)))
    store.initialize()
    organization = store.create_organization(slug="school-a", name="学校A")
    initial = {
        "io": {},
        "rules": {"hard_bans": {"teacher_day_bans": {"星期日": ["教师A"]}}},
        "temporary_rules": {"active": []},
        "academic_affairs": {},
        "change_audit": {"entries": []},
    }
    store.save_workspace(organization.id, initial, expected_revision=0, actor_user_id="migration")
    legacy_path = tmp_path / "legacy-web-overrides.yaml"
    legacy_text = json.dumps({"rules": {"legacy_only": True}}, ensure_ascii=False)
    legacy_path.write_text(legacy_text, encoding="utf-8")

    monkeypatch.setenv("SCHEDULER_STATE_BACKEND", "sqlite")
    monkeypatch.setenv("SCHEDULER_DATABASE_PATH", str(database_path))
    monkeypatch.setenv("SCHEDULER_ORGANIZATION_ID", organization.id)
    monkeypatch.setattr(config_service, "WEB_OVERRIDES_PATH", legacy_path)

    loaded = config_service.load_web_overrides()
    stale = copy.deepcopy(loaded)
    loaded["rules"]["new_setting"] = {"enabled": True}
    saved = config_service.save_web_overrides(
        loaded,
        actor_user_id="admin-a",
        reason="数据库运行模式测试",
    )

    assert loaded["_meta"]["revision"] == 1
    assert saved["_meta"]["revision"] == 2
    assert store.load_workspace(organization.id).payload["rules"]["new_setting"] == {"enabled": True}  # type: ignore[union-attr]
    assert legacy_path.read_text(encoding="utf-8") == legacy_text
    with pytest.raises(RevisionConflict):
        config_service.save_web_overrides(stale, actor_user_id="stale-client")

    io_path = tmp_path / "io.yaml"
    rules_path = tmp_path / "rules.yaml"
    io_path.write_text("{}", encoding="utf-8")
    rules_path.write_text("{}", encoding="utf-8")
    effective = load_effective_config("joint", {"io_path": io_path, "rules_path": rules_path})
    assert effective.rules_cfg["hard_bans"]["teacher_day_bans"]["星期日"] == ["教师A"]
    assert effective.rules_cfg["new_setting"] == {"enabled": True}
