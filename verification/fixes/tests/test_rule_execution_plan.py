from __future__ import annotations

import sys
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


from scheduler.config.loader import load_effective_config  # noqa: E402
from scheduler.domain.rule_instance import compile_rule_instances, rule_instances_from_mapping  # noqa: E402
from scheduler.domain.school_profile import profile_from_mapping  # noqa: E402
from scheduler.rules import (  # noqa: E402
    audit_rule_trace_against_plan,
    build_default_rule_registry,
    build_rule_execution_plan,
    rule_execution_plan_payload,
)


def _profile_data(profile_id: str) -> dict:
    return yaml.safe_load((REPO_ROOT / "profiles" / profile_id / "profile.yaml").read_text(encoding="utf-8"))


def _effective_cfg() -> dict:
    return load_effective_config(
        "joint",
        {
            "io_path": REPO_ROOT / "scheduler" / "config" / "io.yaml",
            "rules_path": REPO_ROOT / "scheduler" / "config" / "rules.yaml",
        },
    ).effective_cfg


def test_rule_execution_plan_maps_current_school_instances_to_registry_templates() -> None:
    profile_path = REPO_ROOT / "profiles" / "current_school" / "profile.yaml"
    data = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    profile = profile_from_mapping(data, source=profile_path.relative_to(REPO_ROOT).as_posix())
    instances = compile_rule_instances(rule_instances_from_mapping(data, source=profile.source))

    plan = build_rule_execution_plan(
        build_default_rule_registry(),
        _effective_cfg(),
        mode="joint",
        profile=profile,
        rule_instances=instances,
        only_enabled=True,
        source="profiles/current_school/profile.yaml",
    )

    assert plan.profile_id == "current_school"
    assert not plan.unplanned_rule_instances
    by_id = {item.rule_id: item for item in plan.items}
    assert "current.night.fri_sun_mutex" in by_id["night.fri_sun_mutex"].instance_ids
    assert "current.night.checkin" in by_id["night.checkin"].instance_ids
    assert "current.day.weekend_halfday" in by_id["day.weekend_halfday_constraint"].instance_ids
    assert "current.shared.personalized_constraints" in by_id["shared.personalized_constraints"].instance_ids
    assert "current_school_teacher_targets" in by_id["shared.personalized_constraints"].instance_target_scopes
    assert "current.personalized.xhd_night_no_pm3" in by_id["personalized.xhd_night_no_pm3"].instance_ids
    assert "current_school_teacher_targets" in by_id["personalized.xhd_night_no_pm3"].instance_target_scopes

    payload = rule_execution_plan_payload(plan)
    assert payload["mode"] == "joint"
    assert payload["profile_id"] == "current_school"
    assert any(item["instance_ids"] for item in payload["items"])


def test_rule_trace_audit_reports_missing_unexpected_and_error_rows_without_executing_rules() -> None:
    plan = build_rule_execution_plan(
        build_default_rule_registry(),
        _effective_cfg(),
        mode="joint",
        profile=profile_from_mapping(_profile_data("current_school")),
        only_enabled=True,
    )

    partial_trace = [
        {"rule_id": "night.hard_base", "status": "ok"},
        {"rule_id": "night.fri_sun_mutex", "status": "ok"},
        {"rule_id": "unknown.rule", "status": "ok"},
        {"rule_id": "night.checkin", "status": "error"},
    ]
    audit = audit_rule_trace_against_plan(plan, partial_trace, require_all_enabled=True)

    assert audit.ok is False
    assert "unknown.rule" in audit.unexpected_trace_rule_ids
    assert "night.checkin" in audit.errored_trace_rule_ids
    assert "night.hard_base" not in audit.missing_enabled_rule_ids
    assert "night.soft_objective" in audit.missing_enabled_rule_ids


def test_cross_school_rule_execution_plans_have_no_unplanned_rule_instances() -> None:
    registry = build_default_rule_registry()
    effective_cfg = _effective_cfg()

    for profile_id in ("base_high_school", "junior_day_school", "primary_after_school"):
        data = _profile_data(profile_id)
        profile = profile_from_mapping(data)
        instances = compile_rule_instances(rule_instances_from_mapping(data))
        plan = build_rule_execution_plan(
            registry,
            effective_cfg,
            mode="joint",
            profile=profile,
            rule_instances=instances,
            only_enabled=False,
        )

        assert plan.profile_id == profile_id
        assert not plan.unplanned_rule_instances
