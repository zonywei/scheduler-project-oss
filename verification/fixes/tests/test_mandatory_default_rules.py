from __future__ import annotations

from scheduler.app.business_rules import build_business_rule_domains, build_business_rule_groups
from scheduler.config.loader import _apply_default_only_rule_policy
from scheduler.rules.mandatory import MANDATORY_DEFAULT_RULES, MANDATORY_RULE_IDS


def test_mandatory_defaults_are_locked_hard_rules_with_solver_bindings() -> None:
    assert len(MANDATORY_DEFAULT_RULES) >= 10
    assert len(MANDATORY_RULE_IDS) == len(MANDATORY_DEFAULT_RULES)
    for rule in build_business_rule_groups({})[0]["rules"]:
        assert rule["mandatory"] is True
        assert rule["locked"] is True
        assert rule["editable"] is False
        assert rule["deletable"] is False
        assert rule["mode"] == "硬规则"
        assert rule["solver_bindings"]


def test_formal_rule_domains_have_the_same_three_sections() -> None:
    domains = build_business_rule_domains({"product_rules": {"defaults_only": True}})
    assert [domain["id"] for domain in domains] == ["course", "roster"]
    for domain in domains:
        assert [section["id"] for section in domain["sections"]] == ["basic", "teacher", "subject"]
    assert len(domains[0]["sections"][0]["rules"]) == 7
    assert len(domains[1]["sections"][0]["rules"]) == 3
    assert not domains[0]["sections"][1]["rules"]
    assert not domains[0]["sections"][2]["rules"]


def test_default_only_policy_disables_legacy_flags_but_preserves_new_rule_v2() -> None:
    io_cfg = {
        "pre_run_cleanup": {"enabled": True},
        "day": {
            "weekday_constraints": {"enable_pref_lang_am": True},
            "head_duty_constraints": {"enable_head_duty": True},
        },
    }
    rules_cfg = {
        "product_rules": {"defaults_only": True},
        "hard_bans": {"enabled": True, "subject_bans": [{"subject": "数学"}]},
        "personalized_constraints": {"enabled": True, "enable_example": True},
        "rule_v2": {"rules": [{"id": "custom-1"}]},
    }

    io_result, rules_result = _apply_default_only_rule_policy(io_cfg, rules_cfg)

    assert io_result["day"]["weekday_constraints"]["enable_pref_lang_am"] is False
    assert io_result["day"]["head_duty_constraints"]["enable_head_duty"] is False
    assert io_result["pre_run_cleanup"]["enabled"] is True
    assert rules_result["hard_bans"]["enabled"] is False
    assert rules_result["personalized_constraints"]["enable_example"] is False
    assert rules_result["global_binding"]["enable_8_chem_9_bio"] is False
    assert rules_result["rule_v2"]["rules"] == [{"id": "custom-1"}]
