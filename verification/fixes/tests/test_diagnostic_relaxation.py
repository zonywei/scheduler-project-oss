from __future__ import annotations

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


from scheduler.app import config_service
from scheduler.app.diagnostic_relaxation import active_relaxation_plans, apply_relaxation_plan, remove_relaxation_plan


def _plan() -> dict:
    return {
        "id": "relax.demo",
        "title": "诊断试跑",
        "domain": "联动规则",
        "rationale": "验证硬约束是否造成无解。",
        "risk": "只用于排障。",
        "patches": [
            {
                "target": "io",
                "operation": "set",
                "path": ["day_night_link", "night_requires_day_mode"],
                "value": "soft",
                "path_label": "day_night_link.night_requires_day_mode",
            },
            {
                "target": "rules",
                "operation": "set",
                "path": ["day_constraints", "weekend_halfday_mode"],
                "value": "soft",
                "path_label": "day_constraints.weekend_halfday_mode",
            },
        ],
    }


def _weekday_plan(plan_id: str, key: str, value: object) -> dict:
    return {
        "id": plan_id,
        "title": plan_id,
        "domain": "白天规则",
        "rationale": "验证叠加诊断方案的清理行为。",
        "risk": "只用于排障。",
        "patches": [
            {
                "target": "io",
                "operation": "set",
                "path": ["day", "weekday_constraints", key],
                "value": value,
                "path_label": f"day.weekday_constraints.{key}",
            }
        ],
    }


def test_relaxation_plan_apply_records_restore_and_remove_restores(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config_service, "WEB_OVERRIDES_PATH", tmp_path / "web_overrides.yaml")
    config_service.save_web_overrides(
        {
            "io": {"day_night_link": {"night_requires_day_mode": "hard"}},
            "rules": {},
            "temporary_rules": {"active": []},
        }
    )

    applied = apply_relaxation_plan(_plan())

    overrides = applied["overrides"]
    assert applied["applied"] is True
    assert overrides["io"]["day_night_link"]["night_requires_day_mode"] == "soft"
    assert overrides["rules"]["day_constraints"]["weekend_halfday_mode"] == "soft"
    active = overrides["temporary_rules"]["active"]
    assert len(active) == 1
    assert active[0]["kind"] == "diagnostic_relaxation"
    assert active[0]["restore"][0]["existed"] is True
    assert active[0]["restore"][0]["value"] == "hard"
    assert active[0]["restore"][1]["existed"] is False
    saved_text = config_service.WEB_OVERRIDES_PATH.read_text(encoding="utf-8")
    assert "&id" not in saved_text
    assert "*id" not in saved_text

    removed = remove_relaxation_plan("relax.demo")

    restored = removed["overrides"]
    assert removed["removed"] is True
    assert restored["io"]["day_night_link"]["night_requires_day_mode"] == "hard"
    assert "day_constraints" not in restored["rules"]
    assert restored["temporary_rules"]["active"] == []


def test_active_relaxation_plans_returns_only_active_diagnostic_items(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config_service, "WEB_OVERRIDES_PATH", tmp_path / "web_overrides.yaml")
    applied = apply_relaxation_plan(_plan())
    overrides = applied["overrides"]
    overrides["temporary_rules"]["active"].append(
        {"id": "tmp.nl.demo", "kind": "manual_rule", "status": "active"}
    )
    overrides["temporary_rules"]["active"].append(
        {"id": "relax.old", "kind": "diagnostic_relaxation", "status": "removed"}
    )

    plans = active_relaxation_plans(overrides)

    assert [plan["id"] for plan in plans] == ["relax.demo"]
    plans[0]["id"] = "mutated"
    assert overrides["temporary_rules"]["active"][0]["id"] == "relax.demo"


def test_relaxation_plan_apply_is_idempotent(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config_service, "WEB_OVERRIDES_PATH", tmp_path / "web_overrides.yaml")
    first = apply_relaxation_plan(_plan())
    second = apply_relaxation_plan(_plan())

    assert first["applied"] is True
    assert second["applied"] is False
    assert second["already_active"] is True
    assert len(second["overrides"]["temporary_rules"]["active"]) == 1


def test_relaxation_plan_remove_preserves_existing_empty_parent(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config_service, "WEB_OVERRIDES_PATH", tmp_path / "web_overrides.yaml")
    config_service.save_web_overrides(
        {
            "io": {"day_night_link": {}},
            "rules": {},
            "temporary_rules": {"active": []},
        }
    )

    apply_relaxation_plan(_plan())
    removed = remove_relaxation_plan("relax.demo")

    assert removed["removed"] is True
    assert removed["overrides"]["io"]["day_night_link"] == {}


def test_relaxation_plan_remove_prunes_shared_created_parent_after_last_plan(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(config_service, "WEB_OVERRIDES_PATH", tmp_path / "web_overrides.yaml")

    apply_relaxation_plan(_weekday_plan("relax.a", "enable_head_pm1_min", False))
    apply_relaxation_plan(_weekday_plan("relax.b", "enable_no_am1_am4", False))

    first_removed = remove_relaxation_plan("relax.a")
    assert first_removed["removed"] is True
    assert first_removed["overrides"]["io"]["day"]["weekday_constraints"] == {
        "enable_no_am1_am4": False
    }
    assert first_removed["overrides"]["temporary_rules"]["diagnostic_created_containers"]

    second_removed = remove_relaxation_plan("relax.b")
    assert second_removed["removed"] is True
    assert second_removed["overrides"]["io"] == {}
    assert "diagnostic_created_containers" not in second_removed["overrides"]["temporary_rules"]
