from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scheduler.platform.auth import AuthenticationError
from scheduler.platform.backup import (
    create_database_backup,
    inspect_database_backup,
    restore_database_backup,
)
from scheduler.platform.database import PlatformDatabase, PlatformDatabaseSettings
from scheduler.platform.health import platform_health, record_service_heartbeat
from scheduler.platform.login_rate_limit import LoginRateLimiter, LoginRateLimitPolicy
from scheduler.platform.store import PlatformStore


def _store(database_path: Path) -> PlatformStore:
    store = PlatformStore(PlatformDatabase(PlatformDatabaseSettings(path=database_path)))
    assert store.initialize() == (1, 2, 3, 4, 5, 6)
    return store


def _school(store: PlatformStore) -> str:
    organization = store.create_organization(slug="school-a", name="学校 A")
    store.save_workspace(
        organization.id,
        {"rules": {"version": 1}, "io": {}},
        expected_revision=0,
        actor_user_id="bootstrap",
    )
    return organization.id


def test_login_rate_limit_is_persistent_bounded_and_cleared_on_success(tmp_path: Path) -> None:
    store = _store(tmp_path / "scheduler.db")
    _school(store)
    clock = [datetime(2026, 7, 26, 12, 0, tzinfo=timezone.utc)]
    limiter = LoginRateLimiter(
        store,
        policy=LoginRateLimitPolicy(max_failures=3, window_seconds=300, block_seconds=600),
        now=lambda: clock[0],
        key_secret="test-secret",
    )
    key = limiter.key(organization_slug="school-a", username="admin", client_ip="127.0.0.1")

    for _ in range(3):
        limiter.assert_allowed(key)
        limiter.record_failure(key)
    with pytest.raises(AuthenticationError, match="登录尝试过多"):
        limiter.assert_allowed(key)

    clock[0] += timedelta(seconds=601)
    limiter.assert_allowed(key)
    limiter.record_failure(key)
    limiter.record_success(key)
    limiter.assert_allowed(key)


def test_platform_health_reports_database_workspace_and_worker_heartbeat(tmp_path: Path) -> None:
    store = _store(tmp_path / "scheduler.db")
    organization_id = _school(store)
    now = datetime(2026, 7, 26, 12, 0, tzinfo=timezone.utc)

    before = platform_health(store, organization_id, now=now)
    assert before["ready"] is True
    assert before["checks"]["worker"] == "unavailable"
    assert before["checks"]["migrations"] == [1, 2, 3, 4, 5, 6]

    record_service_heartbeat(
        store,
        organization_id,
        service_kind="solve-worker",
        instance_id="worker-1",
        metadata={"status": "idle"},
        now=now,
    )
    healthy = platform_health(store, organization_id, now=now + timedelta(seconds=20))
    stale = platform_health(store, organization_id, now=now + timedelta(seconds=90))
    assert healthy["checks"]["worker"] == "healthy"
    assert stale["checks"]["worker"] == "unavailable"


def test_online_backup_verify_and_guarded_restore_round_trip(tmp_path: Path) -> None:
    database_path = tmp_path / "scheduler.db"
    store = _store(database_path)
    organization_id = _school(store)
    backup_path = tmp_path / "backups" / "scheduler.db"

    created = create_database_backup(database_path, backup_path)
    assert created["integrity"] == "ok"
    assert created["migration_versions"] == [1, 2, 3, 4, 5, 6]
    assert inspect_database_backup(backup_path)["workspace_count"] == 1

    store.save_workspace(
        organization_id,
        {"rules": {"version": 2}, "io": {}},
        expected_revision=1,
        actor_user_id="admin",
    )
    assert store.load_workspace(organization_id).revision == 2  # type: ignore[union-attr]

    restored = restore_database_backup(
        backup_path,
        database_path,
        recovery_directory=tmp_path / "recovery",
    )
    assert Path(restored["recovery_backup"]).exists()
    restored_store = _store(database_path)
    restored_workspace = restored_store.load_workspace(organization_id)
    assert restored_workspace is not None
    assert restored_workspace.revision == 1
    assert restored_workspace.payload["rules"]["version"] == 1


def test_backup_refuses_overwrite_and_restore_refuses_same_source(tmp_path: Path) -> None:
    database_path = tmp_path / "scheduler.db"
    store = _store(database_path)
    _school(store)
    backup_path = tmp_path / "backup.db"
    create_database_backup(database_path, backup_path)

    with pytest.raises(FileExistsError):
        create_database_backup(database_path, backup_path)
    with pytest.raises(ValueError, match="must differ"):
        restore_database_backup(database_path, database_path)
