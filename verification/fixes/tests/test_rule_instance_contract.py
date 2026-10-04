from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


from scheduler.domain.rule_instance import (  # noqa: E402
    RuleInstance,
    compile_rule_instances,
    rule_instances_from_mapping,
    validate_rule_instances,
)
from scheduler.domain.personalized_rule_catalog import (  # noqa: E402
    PERSONALIZED_LEGACY_RULES,
    personalized_rule_catalog_payload,
    personalized_template_id,
)
from scheduler.rules.personalized_legacy import PERSONALIZED_LEGACY_RULES as RULES_PERSONALIZED_LEGACY_RULES  # noqa: E402
from scheduler.rules import build_default_rule_registry  # noqa: E402


def _profile_data(profile_id: str) -> dict:
    return yaml.safe_load((REPO_ROOT / "profiles" / profile_id / "profile.yaml").read_text(encoding="utf-8"))


def test_current_school_rule_instances_compile_against_registry_without_execution_side_effects() -> None:
    source = "profiles/current_school/profile.yaml"
    data = _profile_data("current_school")
    instances = rule_instances_from_mapping(data, source=source)
    registry = build_default_rule_registry()

    assert validate_rule_instances(instances, registry=registry) == ()
    compiled = compile_rule_instances(instances, registry=registry)

    assert [item.instance_id for item in compiled[:4]] == [
        "current.night.fri_sun_mutex",
        "current.night.checkin",
        "current.day.weekend_halfday",
        "current.shared.personalized_constraints",
    ]
    assert len(compiled) == 4 + len(PERSONALIZED_LEGACY_RULES)
    mutex = compiled[0]
    assert mutex.template_id == "night.fri_sun_mutex"
    assert mutex.rule_name == "周五周日晚自习互斥"
    assert mutex.enabled is True
    assert mutex.mode == "hard"
    assert mutex.weight == 20000
    assert mutex.params["days"] == ["星期五", "星期日"]
    assert mutex.source == source
    personalized = compiled[3]
    assert personalized.template_id == "shared.personalized_constraints"
    assert personalized.rule_name == "个性化约束集合"
    assert personalized.target_scope == "current_school_teacher_targets"
    assert personalized.params == {
        "legacy_group": "personalized_constraints",
        "teacher_targets_path": "personalized_constraints.teacher_targets",
        "solver_effect": "none",
    }
    xhd = next(item for item in compiled if item.instance_id == "current.personalized.xhd_night_no_pm3")
    assert xhd.template_id == "personalized.xhd_night_no_pm3"
    assert xhd.rule_name == "晚自习当天不排下午3"
    assert xhd.target_scope == "current_school_teacher_targets"
    assert xhd.params["legacy_rule"] == "enable_xhd_night_no_pm3"
    assert xhd.params["target_slots"] == ["xhd"]
    assert xhd.params["solver_effect"] == "none"


def test_anonymous_profile_rule_instances_cover_multiple_school_shapes() -> None:
    registry = build_default_rule_registry()
    compiled_by_profile = {}
    for profile_id in ("base_high_school", "junior_day_school", "primary_after_school"):
        source = f"profiles/{profile_id}/profile.yaml"
        instances = rule_instances_from_mapping(_profile_data(profile_id), source=source)
        assert validate_rule_instances(instances, registry=registry) == ()
        compiled_by_profile[profile_id] = compile_rule_instances(instances, registry=registry)

    assert compiled_by_profile["base_high_school"][0].template_id == "night.fri_sun_mutex"
    assert compiled_by_profile["base_high_school"][0].mode == "soft"
    assert compiled_by_profile["junior_day_school"][0].template_id == "day.am1_pm1_mutex"
    assert compiled_by_profile["primary_after_school"][0].enabled is False


def test_rule_instance_validation_rejects_unknown_templates_and_bad_modes() -> None:
    errors = validate_rule_instances(
        (
            RuleInstance(instance_id="bad.unknown", template_id="missing.template"),
            RuleInstance(instance_id="bad.mode", template_id="night.checkin", mode="maybe"),
        ),
        registry=build_default_rule_registry(),
    )

    assert "bad.unknown: unknown template_id: missing.template" in errors
    assert "bad.mode: unsupported mode: maybe" in errors
    with pytest.raises(ValueError):
        compile_rule_instances((RuleInstance(instance_id="bad.unknown", template_id="missing.template"),))


def test_personalized_rule_catalog_is_visibility_only_migration_contract() -> None:
    payload = personalized_rule_catalog_payload(
        {
            "personalized_constraints": {
                "teacher_targets": {
                    "xhd": ["教师A"],
                    "zfy": ["教师B"],
                    "cc": ["教师C"],
                    "cc_sat_am34_target_class": "高一1班",
                },
                "enable_couple_xhd_zfy": True,
                "couple_xhd_zfy_mode": "soft",
                "w_couple_need_overlap": 5000,
                "enable_cc_sat_am34_class17": True,
                "cc_sat_am34_class17_mode": "hard",
                "w_cc_sat_am34_class17": 600,
            }
        },
        rule_instances=(
            RuleInstance(
                instance_id="current.personalized",
                template_id="shared.personalized_constraints",
            ),
        ),
        profile_data={"rule_instance_sources": {"groups": ["personalized_constraints"]}},
        source="unit",
    )

    assert payload["schema_version"] == "scheduler.personalized_rule_catalog.v1"
    assert payload["solver_effect"] == "none"
    assert payload["can_block_solver"] is False
    assert payload["summary"]["configured_target_slots"] == 4
    assert payload["summary"]["profile_rule_instances"] == 1
    assert payload["migration_status"] == "profile_rule_instance_present"
    by_rule = {item["rule_key"]: item for item in payload["legacy_rules"]}
    assert by_rule["enable_couple_xhd_zfy"]["targets"] == ["教师A", "教师B"]
    assert by_rule["enable_cc_sat_am34_class17"]["targets"] == ["教师C", "高一1班"]
    assert by_rule["enable_cc_sat_am34_class17"]["migration_status"] == "profile_rule_instance_present"


def test_personalized_legacy_rules_have_audit_only_registry_templates() -> None:
    registry = build_default_rule_registry()

    assert PERSONALIZED_LEGACY_RULES is RULES_PERSONALIZED_LEGACY_RULES
    for rule in PERSONALIZED_LEGACY_RULES:
        spec = registry.get(personalized_template_id(rule.rule_key))
        assert spec is not None
        assert spec.apply_fn is None
        assert spec.apply_fn_ref == "apply_personalized_constraints"
        assert spec.enabled_path == f"personalized_constraints.{rule.rule_key}"
        assert spec.mode_path == (f"personalized_constraints.{rule.mode_key}" if rule.mode_key else None)
        assert spec.weight_path == (f"personalized_constraints.{rule.weight_key}" if rule.weight_key else None)
