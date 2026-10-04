from __future__ import annotations

import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ai_orchestrated_optimization import (  # noqa: E402
    ai_or_model_rule_context,
    create_existing_cp_model,
    solve_cp_sat_problem,
    summarize_existing_cp_model_operations_by_rule,
)
from scheduler.config.loader import load_effective_config  # noqa: E402
from scheduler.data.day_rules_reader import DayInputData, Slot  # noqa: E402
from scheduler.day_constraints_morning_reading import apply_morning_reading_constraints  # noqa: E402
from scheduler.domain.rule_instance import compile_rule_instances, rule_instances_from_mapping  # noqa: E402
from scheduler.domain.school_profile import profile_from_mapping  # noqa: E402
from scheduler.model.constraints.day_hard_one_per_slot import apply_one_subject_per_slot  # noqa: E402
from scheduler.model.constraints.day_hard_subject_hours import apply_subject_hour_constraints  # noqa: E402
from scheduler.model.constraints.day_hard_teacher_conflict import apply_teacher_no_conflict  # noqa: E402
from scheduler.model.constraints.day_weekday_constraints import (  # noqa: E402
    apply_am1_pm1_exclusive,
    apply_am1_pm1_mutex,
    apply_core_subject_teacher_day_load_and_no_am1_am4,
    apply_head_pm1_min,
    apply_high_weekday_subject_min1_per_day,
    apply_low_weekday_subject_max1_per_day,
    apply_multi_class_halfday_soft,
    apply_no_am1_am4,
    apply_no_consecutive_same_teacher_same_class,
    apply_pref_lang_am,
    apply_single_class_weekly_am1_cap,
    apply_teacher_am1_fragmentation,
    apply_teacher_continuity_penalty,
    apply_teacher_am4_pm1_threshold_penalty,
    apply_teacher_m1_cap_constraint,
    apply_teacher_weekday_am_pm_presence,
    apply_reduce_stem_am1,
    apply_two_class_daily_min_per_class,
    apply_two_class_am1_pm1_combo,
    apply_two_class_low_hours_max_empty_days,
    apply_weekday_subject_balance,
)
from scheduler.model.constraints.day_pe_tech_constraints import (  # noqa: E402
    apply_pe_tech_compact_soft,
    apply_pe_reduce_am_soft,
    apply_pe_time_window_hard,
    apply_teacher_whitelist_hard,
)
from scheduler.model.constraints.day_weekend_constraints import (  # noqa: E402
    apply_yjc_sunday_am12_pm12_rule,
    apply_weekend_cross_halfday_penalty,
    apply_weekend_double_period_same_class,
    apply_weekend_halfday_constraint,
    apply_weekend_one_day_only,
    apply_weekend_subject_whitelist,
)
from scheduler.model.constraints.global_binding_constraints import (  # noqa: E402
    apply_global_day_binding_8_chem_9_bio,
    apply_global_night_binding_8_chem_9_bio,
)
from scheduler.model.constraints.duty_joint_constraints import (  # noqa: E402
    DutyJointConfig,
    add_duty_joint_constraints,
)
from scheduler.model.constraints.grade_group_duty_constraints import (  # noqa: E402
    GradeGroupDutyConfig,
    apply_grade_group_duty_constraints,
)
from scheduler.model.constraints.checkin import apply_checkin  # noqa: E402
from scheduler.model.constraints.hard_base import apply_hard_base  # noqa: E402
from scheduler.model.constraints.hard_bans import apply_hard_bans  # noqa: E402
from scheduler.model.constraints.hard_teacher_limits import apply_hard_teacher_limits  # noqa: E402
from scheduler.model.constraints.night_single_class_period_split import (  # noqa: E402
    apply_double_class_teacher_weekday_alternate_p1_p2,
    apply_single_class_teacher_p1_p2_split,
)
from scheduler.model.constraints.night_special import apply_fri_sun_mutex, apply_physics_math_hard_bans  # noqa: E402
from scheduler.model.constraints.soft_objective import apply_soft_objective  # noqa: E402
from scheduler.model.day_variables import build_day_variables  # noqa: E402
from scheduler.model.variables import build_checkin_variables, build_variables  # noqa: E402
from scheduler.rules import build_default_rule_registry, build_rule_execution_plan  # noqa: E402
from scheduler.rules.generic_bridge import (  # noqa: E402
    day_am1_pm1_exclusive_to_ai_or_problem,
    day_am1_pm1_mutex_to_ai_or_problem,
    day_binding_8chem_9bio_to_ai_or_problem,
    day_core_subject_teacher_day_load_no_am1_am4_to_ai_or_problem,
    day_head_pm1_min_to_ai_or_problem,
    day_high_weekday_subject_min1_per_day_to_ai_or_problem,
    day_low_weekday_subject_max1_per_day_to_ai_or_problem,
    day_morning_reading_to_ai_or_problem,
    day_multi_class_halfday_soft_to_ai_or_problem,
    day_no_consecutive_same_teacher_same_class_to_ai_or_problem,
    day_no_am1_am4_to_ai_or_problem,
    day_one_subject_per_slot_to_ai_or_problem,
    day_pe_tech_compact_soft_to_ai_or_problem,
    day_pe_reduce_am_soft_to_ai_or_problem,
    day_pe_time_window_hard_to_ai_or_problem,
    day_pref_lang_am_to_ai_or_problem,
    day_reduce_stem_am1_to_ai_or_problem,
    day_single_class_weekly_am1_cap_to_ai_or_problem,
    day_subject_hours_to_ai_or_problem,
    day_teacher_no_conflict_to_ai_or_problem,
    day_teacher_am1_fragmentation_to_ai_or_problem,
    day_teacher_continuity_penalty_to_ai_or_problem,
    day_teacher_am4_pm1_threshold_penalty_to_ai_or_problem,
    day_teacher_m1_cap_constraint_to_ai_or_problem,
    day_teacher_weekday_am_pm_presence_to_ai_or_problem,
    day_two_class_am1_pm1_combo_to_ai_or_problem,
    day_two_class_daily_min_per_class_to_ai_or_problem,
    day_two_class_low_hours_max_empty_days_to_ai_or_problem,
    day_special_duty_catalog_to_ai_or_problem,
    day_teacher_whitelist_hard_to_ai_or_problem,
    day_weekday_subject_balance_to_ai_or_problem,
    day_weekend_cross_halfday_penalty_to_ai_or_problem,
    day_weekend_double_period_same_class_to_ai_or_problem,
    day_weekend_halfday_constraint_to_ai_or_problem,
    day_weekend_one_day_only_to_ai_or_problem,
    day_weekend_subject_whitelist_to_ai_or_problem,
    day_yjc_sunday_am12_pm12_to_ai_or_problem,
    duty_joint_to_ai_or_problem,
    generic_scheduler_rule_contract_scopes,
    generic_scheduler_rule_contract_summary,
    generic_scheduler_rule_ids,
    grade_group_duty_to_ai_or_problem,
    night_binding_8chem_9bio_to_ai_or_problem,
    night_checkin_to_ai_or_problem,
    night_double_class_weekday_p1_p2_split_to_ai_or_problem,
    night_fri_sun_mutex_to_ai_or_problem,
    night_hard_base_to_ai_or_problem,
    night_hard_bans_to_ai_or_problem,
    night_hard_teacher_limits_to_ai_or_problem,
    night_physics_math_special_to_ai_or_problem,
    night_single_class_p1_p2_split_to_ai_or_problem,
    night_soft_objective_to_ai_or_problem,
    personalized_legacy_catalog_to_ai_or_problem,
    scheduler_execution_plan_to_ai_or_problem,
)
from scheduler.rules.personalized_legacy import PERSONALIZED_RULE_INSTANCE_TEMPLATE_IDS  # noqa: E402


def _effective_cfg() -> dict:
    return load_effective_config(
        "joint",
        {
            "io_path": REPO_ROOT / "scheduler" / "config" / "io.yaml",
            "rules_path": REPO_ROOT / "scheduler" / "config" / "rules.yaml",
        },
    ).effective_cfg


def _current_school_plan():
    profile_path = REPO_ROOT / "profiles" / "current_school" / "profile.yaml"
    profile_data = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    profile = profile_from_mapping(profile_data, source=profile_path.relative_to(REPO_ROOT).as_posix())
    instances = compile_rule_instances(rule_instances_from_mapping(profile_data, source=profile.source))
    return build_rule_execution_plan(
        build_default_rule_registry(),
        _effective_cfg(),
        mode="joint",
        profile=profile,
        rule_instances=instances,
        only_enabled=True,
        source="profiles/current_school/profile.yaml",
    )


def test_scheduler_rule_execution_plan_can_be_lifted_into_generic_rule_first_problem() -> None:
    plan = _current_school_plan()

    bridge = scheduler_execution_plan_to_ai_or_problem(plan)

    assert bridge.problem.problem_id == "scheduler_rule_execution_plan:current_school:joint"
    assert len(bridge.problem.rules) == len(plan.items)
    assert len(bridge.problem.constraints) == len(plan.items)
    assert bridge.rule_first_plan.rule_order[0].rule.enforcement == "hard"
    assert bridge.rule_first_plan.rule_order[-1].rule.enforcement == "soft"
    assert bridge.metadata_by_rule["scheduler__joint__night__fri_sun_mutex"]["scheduler_rule_id"] == "night.fri_sun_mutex"
    assert bridge.metadata_by_rule["scheduler__joint__night__fri_sun_mutex"]["instance_ids"] == ("current.night.fri_sun_mutex",)
    assert bridge.metadata_by_rule["scheduler__joint__night__soft_objective"]["stage"] == "objective_post"
    assert bridge.problem.objective is not None
    assert bridge.problem.objective.rule_id == "scheduler__joint__night__soft_objective"


def test_personalized_legacy_catalog_generic_contract_tracks_all_templates() -> None:
    cfg = {
        "personalized_constraints": {
            "enabled": True,
            "teacher_targets": {"xhd": ["teacher_alpha"], "zfy": []},
            "enable_xhd_night_no_pm3": True,
            "xhd_night_no_pm3_mode": "soft",
            "w_xhd_night_no_pm3": 7,
            "enable_couple_xhd_zfy": True,
            "couple_xhd_zfy_mode": "hard",
            "w_couple_need_overlap": 11,
        }
    }

    bridge = personalized_legacy_catalog_to_ai_or_problem(cfg)

    assert bridge.problem.problem_id == "scheduler_personalized_legacy_catalog"
    assert tuple(rule.rule_id for rule in bridge.problem.rules) == PERSONALIZED_RULE_INSTANCE_TEMPLATE_IDS
    assert len(bridge.problem.variables) == len(PERSONALIZED_RULE_INSTANCE_TEMPLATE_IDS)
    assert len(bridge.problem.constraints) == len(PERSONALIZED_RULE_INSTANCE_TEMPLATE_IDS)
    assert set(bridge.metadata_by_rule) == set(PERSONALIZED_RULE_INSTANCE_TEMPLATE_IDS)
    solution = solve_cp_sat_problem(bridge.problem)
    assert solution.status_name == "OPTIMAL"

    shared = bridge.metadata_by_rule["shared.personalized_constraints"]
    assert shared["template_kind"] == "collection"
    assert shared["enabled"] is True
    assert shared["legacy_contract_scope"] == "personalized_registry_and_config_catalog"
    assert shared["solver_effect"] == "shadow_catalog_not_constraint_shape"

    xhd = bridge.metadata_by_rule["personalized.xhd_night_no_pm3"]
    assert xhd["template_kind"] == "legacy_personalized_rule"
    assert xhd["enabled"] is True
    assert xhd["mode"] == "soft"
    assert xhd["weight"] == 7
    assert xhd["target_slots"] == ("xhd",)
    assert xhd["targets"] == ("teacher_alpha",)
    assert xhd["target_status"] == "configured"
    assert xhd["constraint_family_counts"] == {"personalized_catalog_state_constraints": 1}

    couple = bridge.metadata_by_rule["personalized.couple_xhd_zfy"]
    assert couple["enabled"] is True
    assert couple["mode"] == "hard"
    assert couple["weight"] == 11
    assert couple["target_slots"] == ("xhd", "zfy")
    assert couple["missing_target_slots"] == ("zfy",)
    assert couple["target_status"] == "missing_required_targets"


def test_generic_scheduler_rule_ids_exposes_personalized_legacy_catalog_coverage() -> None:
    covered_rule_ids = set(generic_scheduler_rule_ids())

    assert set(PERSONALIZED_RULE_INSTANCE_TEMPLATE_IDS) <= covered_rule_ids


def test_day_special_duty_catalog_generic_contract_tracks_head_and_noon_rules() -> None:
    cfg = {
        "day": {
            "head_duty_constraints": {
                "enable_head_duty": True,
                "weekday_pm1_requires_duty_mode": "soft",
                "w_weekday_pm1_requires_duty": 33,
            },
            "noon_dorm_duty": {
                "enabled": False,
                "lhj_noon_ban_mode": "hard",
                "w_noon_with_pm1": 44,
            },
        }
    }

    bridge = day_special_duty_catalog_to_ai_or_problem(cfg)

    assert bridge.problem.problem_id == "scheduler_day_special_duty_catalog"
    assert tuple(rule.rule_id for rule in bridge.problem.rules) == (
        "joint.day.head_duty_constraints",
        "joint.day.noon_dorm_duty_constraints",
    )
    assert len(bridge.problem.variables) == 2
    assert len(bridge.problem.constraints) == 2
    solution = solve_cp_sat_problem(bridge.problem)
    assert solution.status_name == "OPTIMAL"

    head = bridge.metadata_by_rule["joint.day.head_duty_constraints"]
    assert head["enabled"] is True
    assert head["mode"] == "soft"
    assert head["weight"] == 33
    assert head["legacy_contract_scope"] == "day_special_duty_registry_and_config_catalog"
    assert head["solver_effect"] == "shadow_catalog_not_constraint_shape"
    assert head["constraint_family_counts"] == {"day_special_duty_catalog_state_constraints": 1}

    noon = bridge.metadata_by_rule["joint.day.noon_dorm_duty_constraints"]
    assert noon["enabled"] is False
    assert noon["mode"] == "hard"
    assert noon["weight"] == 44


def test_generic_scheduler_rule_ids_exposes_day_special_duty_catalog_coverage() -> None:
    covered_rule_ids = set(generic_scheduler_rule_ids())

    assert "joint.day.head_duty_constraints" in covered_rule_ids
    assert "joint.day.noon_dorm_duty_constraints" in covered_rule_ids


def test_generic_scheduler_rule_contract_summary_separates_catalog_from_exact_shape() -> None:
    scopes = generic_scheduler_rule_contract_scopes()
    catalog_rule_ids = set(PERSONALIZED_RULE_INSTANCE_TEMPLATE_IDS) | {
        "joint.day.head_duty_constraints",
        "joint.day.noon_dorm_duty_constraints",
    }
    summary = generic_scheduler_rule_contract_summary()

    assert set(scopes) == set(generic_scheduler_rule_ids())
    assert {rule_id for rule_id, scope in scopes.items() if scope == "catalog_contract"} == catalog_rule_ids
    assert scopes["joint.day.one_subject_per_slot"] == "exact_cp_sat_shape_contract"
    assert summary["catalog_contract"] == len(catalog_rule_ids)
    assert summary["exact_cp_sat_shape_contract"] == len(scopes) - len(catalog_rule_ids)


def test_scheduler_generic_rule_bridge_is_executable_and_keeps_every_enabled_rule_active() -> None:
    bridge = scheduler_execution_plan_to_ai_or_problem(_current_school_plan())

    solution = solve_cp_sat_problem(bridge.problem, time_limit_seconds=5)

    assert solution.status_name == "OPTIMAL"
    assert all(value == 1 for value in solution.values.values())
    assert solution.applied_constraints[0].startswith("activate__scheduler__joint__")
    assert set(solution.rule_application_order) >= set(bridge.metadata_by_rule)


def test_night_hard_base_generic_contract_matches_legacy_h1_h2_h3_shape() -> None:
    classes = ("class_a", "class_b")
    cst = {
        ("class_a", "math"): "teacher_1",
        ("class_a", "science"): "teacher_2",
        ("class_b", "math"): "teacher_1",
        ("class_b", "science"): "teacher_3",
    }
    days = ("day_1", "day_2")
    periods = ("night_1",)
    rules = {"evening": {"weekly_occurrences_per_subject": 1}}

    bridge = night_hard_base_to_ai_or_problem(
        classes=classes,
        cst=cst,
        days=days,
        periods=periods,
        rules=rules,
    )

    assert bridge.problem.problem_id == "scheduler_night_hard_base"
    assert tuple(rule.rule_id for rule in bridge.problem.rules) == ("night.hard_base",)
    assert len(bridge.problem.variables) == len(cst) * len(days) * len(periods)
    assert len(bridge.problem.constraints) == (
        len(classes) * len(days) * len(periods)
        + len(cst)
        + len(cst) * len(days)
    )
    assert bridge.metadata_by_rule["night.hard_base"]["generic_contract_status"] == "covered_by_generic_contract"

    legacy_model = create_existing_cp_model("night.hard_base.parity")
    legacy_vars = build_variables(legacy_model, classes, cst, days, periods)
    with ai_or_model_rule_context("night.hard_base", source="scheduler.model.constraints.hard_base"):
        apply_hard_base(
            legacy_model,
            legacy_vars,
            {"classes": classes, "cst": cst, "days": days, "periods": periods},
            rules,
        )
    legacy_summary = summarize_existing_cp_model_operations_by_rule(legacy_model)
    assert legacy_summary["night.hard_base"]["operations"] == {"Add": len(bridge.problem.constraints)}

    solution = solve_cp_sat_problem(bridge.problem, time_limit_seconds=5)

    assert solution.status_name == "OPTIMAL"
    assignments = bridge.metadata_by_rule["night.hard_base"]["assignment_variable_names"]
    for cls in classes:
        for day in days:
            for period in periods:
                assert sum(solution.values[assignments[f"{cls}|{subj}|{day}|{period}"]] for c, subj in cst if c == cls) == 1
    for cls, subj in cst:
        assert sum(solution.values[assignments[f"{cls}|{subj}|{day}|{period}"]] for day in days for period in periods) == 1


def test_generic_scheduler_rule_ids_exposes_real_night_hard_base_coverage() -> None:
    covered_rule_ids = generic_scheduler_rule_ids()

    assert "night.hard_base" in covered_rule_ids
    assert "joint.night.hard_base" in covered_rule_ids


def _night_hard_bans_sample() -> tuple[tuple[str, ...], dict[tuple[str, str], str], tuple[str, ...], tuple[str, ...], dict]:
    return (
        ("class_a", "class_b"),
        {
            ("class_a", "math"): "teacher_1",
            ("class_a", "science"): "teacher_2",
            ("class_b", "math"): "teacher_1",
            ("class_b", "science"): "teacher_3",
        },
        ("星期五", "星期日"),
        ("晚自习1", "晚自习2"),
        {
            "hard_bans": {
                "enabled": True,
                "subject_bans": [
                    {"subject": "math", "days": ["星期五"], "periods": ["晚自习1"]},
                    {"subject": "science", "days": ["星期日"]},
                    {"subject": "", "days": ["星期日"]},
                    {"subject": "missing", "days": ["星期五"]},
                ],
                "teacher_day_bans": {
                    "星期日": ["teacher_1"],
                    "星期五": [],
                    "星期一": ["teacher_2"],
                },
            }
        },
    )


def test_night_hard_bans_generic_contract_matches_legacy_subject_and_teacher_day_bans() -> None:
    classes, cst, days, periods, rules = _night_hard_bans_sample()

    bridge = night_hard_bans_to_ai_or_problem(
        classes=classes,
        cst=cst,
        days=days,
        periods=periods,
        rules=rules,
    )

    assert bridge.problem.problem_id == "scheduler_night_hard_bans"
    assert tuple(rule.rule_id for rule in bridge.problem.rules) == ("night.hard_bans",)
    assert len(bridge.problem.variables) == len(cst) * len(days) * len(periods)
    assert len(bridge.problem.constraints) == 10
    metadata = bridge.metadata_by_rule["night.hard_bans"]
    assert metadata["generic_contract_status"] == "covered_by_generic_contract"
    assert metadata["constraint_family_counts"] == {
        "subject_bans": 6,
        "teacher_day_bans": 4,
    }

    legacy_model = create_existing_cp_model("night.hard_bans.parity")
    legacy_vars = build_variables(legacy_model, classes, cst, days, periods)
    with ai_or_model_rule_context("night.hard_bans", source="scheduler.model.constraints.hard_bans"):
        apply_hard_bans(
            legacy_model,
            legacy_vars,
            {"classes": classes, "cst": cst, "days": days, "periods": periods},
            rules,
        )
    legacy_summary = summarize_existing_cp_model_operations_by_rule(legacy_model)
    assert legacy_summary["night.hard_bans"]["operations"] == {"Add": len(bridge.problem.constraints)}

    solution = solve_cp_sat_problem(bridge.problem, time_limit_seconds=5)

    assert solution.status_name == "OPTIMAL"
    assignment_names = metadata["assignment_variable_names"]
    blocked_names = set(metadata["blocked_assignment_variable_names"])
    assert blocked_names == {
        assignment_names["class_a|math|星期五|晚自习1"],
        assignment_names["class_b|math|星期五|晚自习1"],
        assignment_names["class_a|science|星期日|晚自习1"],
        assignment_names["class_a|science|星期日|晚自习2"],
        assignment_names["class_b|science|星期日|晚自习1"],
        assignment_names["class_b|science|星期日|晚自习2"],
        assignment_names["class_a|math|星期日|晚自习1"],
        assignment_names["class_a|math|星期日|晚自习2"],
        assignment_names["class_b|math|星期日|晚自习1"],
        assignment_names["class_b|math|星期日|晚自习2"],
    }
    assert all(solution.values[name] == 0 for name in blocked_names)


def test_generic_scheduler_rule_ids_exposes_real_night_hard_bans_coverage() -> None:
    covered_rule_ids = generic_scheduler_rule_ids()

    assert "night.hard_bans" in covered_rule_ids
    assert "joint.night.hard_bans" in covered_rule_ids


def _night_hard_teacher_limits_sample() -> tuple[tuple[str, ...], dict[tuple[str, str], str], tuple[str, ...], tuple[str, ...], dict]:
    return (
        ("class_a", "class_b"),
        {
            ("class_a", "math"): "teacher_1",
            ("class_a", "science"): "teacher_2",
            ("class_b", "math"): "teacher_1",
        },
        ("day_1", "day_2", "day_3"),
        ("night_1", "night_2"),
        {"hard_teacher_limits": {"enabled": True}},
    )


def test_night_hard_teacher_limits_generic_contract_matches_legacy_teacher_conflict_and_day_cap() -> None:
    classes, cst, days, periods, rules = _night_hard_teacher_limits_sample()

    bridge = night_hard_teacher_limits_to_ai_or_problem(
        classes=classes,
        cst=cst,
        days=days,
        periods=periods,
        rules=rules,
    )

    assert bridge.problem.problem_id == "scheduler_night_hard_teacher_limits"
    assert tuple(rule.rule_id for rule in bridge.problem.rules) == ("night.hard_teacher_limits",)
    assert len(bridge.problem.variables) == (len(cst) * len(days) * len(periods)) + (2 * len(days))
    assert len(bridge.problem.constraints) == 8
    metadata = bridge.metadata_by_rule["night.hard_teacher_limits"]
    assert metadata["generic_contract_status"] == "covered_by_generic_contract"
    assert metadata["constraint_family_counts"] == {
        "teacher_period_no_conflict": 6,
        "teacher_weekly_day_cap": 2,
    }

    legacy_model = create_existing_cp_model("night.hard_teacher_limits.parity")
    legacy_vars = build_variables(legacy_model, classes, cst, days, periods)
    with ai_or_model_rule_context(
        "night.hard_teacher_limits",
        source="scheduler.model.constraints.hard_teacher_limits",
    ):
        apply_hard_teacher_limits(
            legacy_model,
            legacy_vars,
            {"classes": classes, "cst": cst, "days": days, "periods": periods},
            rules,
        )
    legacy_summary = summarize_existing_cp_model_operations_by_rule(legacy_model)
    assert legacy_summary["night.hard_teacher_limits"]["operations"] == {"Add": len(bridge.problem.constraints)}

    solution = solve_cp_sat_problem(bridge.problem, time_limit_seconds=5)

    assert solution.status_name == "OPTIMAL"
    assert set(metadata["teacher_day_variable_names"]) == {
        "teacher_1|day_1",
        "teacher_1|day_2",
        "teacher_1|day_3",
        "teacher_2|day_1",
        "teacher_2|day_2",
        "teacher_2|day_3",
    }


def test_generic_scheduler_rule_ids_exposes_real_night_hard_teacher_limits_coverage() -> None:
    covered_rule_ids = generic_scheduler_rule_ids()

    assert "night.hard_teacher_limits" in covered_rule_ids
    assert "joint.night.hard_teacher_limits" in covered_rule_ids


def _night_binding_sample() -> tuple[tuple[str, ...], dict[tuple[str, str], str], tuple[str, ...], tuple[str, ...]]:
    return (
        ("初二8班", "初二9班", "初二10班"),
        {
            ("初二8班", "化学"): "chem_teacher",
            ("初二8班", "数学"): "math_teacher",
            ("初二9班", "生物"): "bio_teacher",
            ("初二10班", "化学"): "other_teacher",
        },
        ("星期五", "星期日"),
        ("晚自习1", "晚自习2"),
    )


def test_night_binding_8chem_9bio_generic_contract_matches_legacy_shape() -> None:
    classes, cst, days, periods = _night_binding_sample()

    bridge = night_binding_8chem_9bio_to_ai_or_problem(
        classes=classes,
        cst=cst,
        days=days,
        periods=periods,
        rules={},
    )

    assert bridge.problem.problem_id == "scheduler_night_binding_8chem_9bio"
    assert tuple(rule.rule_id for rule in bridge.problem.rules) == ("night.binding_8chem_9bio",)
    assert len(bridge.problem.variables) == len(cst) * len(days) * len(periods)
    assert len(bridge.problem.constraints) == len(days) * len(periods)
    metadata = bridge.metadata_by_rule["night.binding_8chem_9bio"]
    assert metadata["generic_contract_status"] == "covered_by_generic_contract"
    assert metadata["constraint_family_counts"] == {"8chem_9bio_equalities": 4}

    legacy_model = create_existing_cp_model("night.binding_8chem_9bio.parity")
    legacy_vars = build_variables(legacy_model, classes, cst, days, periods)
    with ai_or_model_rule_context(
        "night.binding_8chem_9bio",
        source="scheduler.model.constraints.global_binding_constraints",
    ):
        apply_global_night_binding_8_chem_9_bio(
            legacy_model,
            legacy_vars,
            {"classes": classes, "cst": cst, "days": days, "periods": periods},
            {},
        )
    legacy_summary = summarize_existing_cp_model_operations_by_rule(legacy_model)
    assert legacy_summary["night.binding_8chem_9bio"]["operations"] == {"Add": len(bridge.problem.constraints)}

    solution = solve_cp_sat_problem(bridge.problem, time_limit_seconds=5)

    assert solution.status_name == "OPTIMAL"
    assignment_names = metadata["assignment_variable_names"]
    for day in days:
        for period in periods:
            assert (
                solution.values[assignment_names[f"初二8班|化学|{day}|{period}"]]
                == solution.values[assignment_names[f"初二9班|生物|{day}|{period}"]]
            )


def test_generic_scheduler_rule_ids_exposes_real_night_binding_coverage() -> None:
    covered_rule_ids = generic_scheduler_rule_ids()

    assert "night.binding_8chem_9bio" in covered_rule_ids
    assert "joint.night.binding_8chem_9bio" in covered_rule_ids


def _night_physics_math_special_sample() -> tuple[
    tuple[str, ...],
    dict[tuple[str, str], str],
    tuple[str, ...],
    tuple[str, ...],
    dict,
]:
    return (
        ("class_a", "class_b"),
        {
            ("class_a", "物理"): "physics_teacher",
            ("class_a", "历史"): "history_teacher",
            ("class_a", "数学"): "math_teacher",
            ("class_b", "物理"): "physics_exempt_teacher",
            ("class_b", "数学"): "math_allowed_teacher",
            ("class_b", "语文"): "language_teacher",
        },
        ("星期五", "星期日", "星期一"),
        ("晚自习1", "晚自习2"),
        {
            "evening_constraints": {
                "enabled": True,
                "enable_physics_math_special": True,
                "physics_fri_mode": "hard",
                "history_fri_mode": "hard",
                "physics_sunday_exempt_teachers": ["physics_exempt_teacher"],
                "physics_friday_exempt_teachers": ["physics_exempt_teacher"],
                "history_friday_exempt_teachers": [],
                "math_friday_allowed_teachers": ["math_allowed_teacher"],
            }
        },
    )


def test_night_physics_math_special_generic_contract_matches_legacy_hard_bans() -> None:
    classes, cst, days, periods, rules = _night_physics_math_special_sample()

    bridge = night_physics_math_special_to_ai_or_problem(
        classes=classes,
        cst=cst,
        days=days,
        periods=periods,
        rules=rules,
    )

    assert bridge.problem.problem_id == "scheduler_night_physics_math_special"
    assert tuple(rule.rule_id for rule in bridge.problem.rules) == ("night.physics_math_special",)
    assert len(bridge.problem.variables) == len(cst) * len(days) * len(periods)
    assert len(bridge.problem.constraints) == 14
    metadata = bridge.metadata_by_rule["night.physics_math_special"]
    assert metadata["generic_contract_status"] == "covered_by_generic_contract"
    assert metadata["constraint_family_counts"] == {
        "physics_sunday": 2,
        "physics_friday_hard": 2,
        "history_sunday": 2,
        "history_friday_hard": 2,
        "math_sunday": 4,
        "math_friday_forbidden": 2,
    }

    legacy_model = create_existing_cp_model("night.physics_math_special.parity")
    legacy_vars = build_variables(legacy_model, classes, cst, days, periods)
    with ai_or_model_rule_context(
        "night.physics_math_special",
        source="scheduler.model.constraints.night_special",
    ):
        apply_physics_math_hard_bans(
            legacy_model,
            legacy_vars,
            {"classes": classes, "cst": cst, "days": days, "periods": periods},
            rules,
        )
    legacy_summary = summarize_existing_cp_model_operations_by_rule(legacy_model)
    assert legacy_summary["night.physics_math_special"]["operations"] == {
        "Add": len(bridge.problem.constraints),
    }

    solution = solve_cp_sat_problem(bridge.problem, time_limit_seconds=5)

    assert solution.status_name == "OPTIMAL"
    assignment_names = metadata["assignment_variable_names"]
    blocked_names = set(metadata["blocked_assignment_variable_names"])
    assert assignment_names["class_b|物理|星期五|晚自习1"] not in blocked_names
    assert assignment_names["class_b|数学|星期五|晚自习1"] not in blocked_names
    assert assignment_names["class_a|物理|星期日|晚自习1"] in blocked_names
    assert assignment_names["class_a|历史|星期五|晚自习2"] in blocked_names
    assert assignment_names["class_a|数学|星期五|晚自习1"] in blocked_names
    assert all(solution.values[name] == 0 for name in blocked_names)


def test_generic_scheduler_rule_ids_exposes_real_night_physics_math_special_coverage() -> None:
    covered_rule_ids = generic_scheduler_rule_ids()

    assert "night.physics_math_special" in covered_rule_ids
    assert "joint.night.physics_math_special" in covered_rule_ids


def _night_fri_sun_mutex_sample() -> tuple[tuple[str, ...], dict[tuple[str, str], str], tuple[str, ...], tuple[str, ...], dict]:
    return (
        ("class_a", "class_b", "class_c", "class_d"),
        {
            ("class_a", "math"): "teacher_1",
            ("class_b", "science"): "teacher_2",
            ("class_c", "history"): "teacher_3",
            ("class_d", "physics"): "teacher_exempt",
        },
        ("星期五", "星期日", "星期一"),
        ("晚自习1",),
        {
            "evening_constraints": {
                "enabled": True,
                "enable_fri_sun_mutex": True,
                "fri_sun_mutex_mode": "hard",
                "fri_sun_mutex_exempt_teachers": ["teacher_exempt"],
                "enable_yk_xxc_fri_mutex": True,
                "yk_xxc_fri_mutex_mode": "hard",
                "yk_xxc_fri_mutex_teachers": ["teacher_1", "teacher_3"],
            }
        },
    )


def test_night_fri_sun_mutex_generic_contract_matches_legacy_teacher_day_mutexes() -> None:
    classes, cst, days, periods, rules = _night_fri_sun_mutex_sample()

    bridge = night_fri_sun_mutex_to_ai_or_problem(
        classes=classes,
        cst=cst,
        days=days,
        periods=periods,
        rules=rules,
    )

    assert bridge.problem.problem_id == "scheduler_night_fri_sun_mutex"
    assert tuple(rule.rule_id for rule in bridge.problem.rules) == ("night.fri_sun_mutex",)
    assert len(bridge.problem.variables) == 4 * len(days)
    assert len(bridge.problem.constraints) == 4
    metadata = bridge.metadata_by_rule["night.fri_sun_mutex"]
    assert metadata["generic_contract_status"] == "covered_by_generic_contract"
    assert metadata["constraint_family_counts"] == {
        "fri_sun_teacher_mutex": 3,
        "configured_friday_pair_mutex": 1,
    }

    legacy_model = create_existing_cp_model("night.fri_sun_mutex.parity")
    legacy_vars = build_variables(legacy_model, classes, cst, days, periods)
    with ai_or_model_rule_context("night.fri_sun_mutex", source="scheduler.model.constraints.night_special"):
        apply_fri_sun_mutex(
            legacy_model,
            legacy_vars,
            {"classes": classes, "cst": cst, "days": days, "periods": periods},
            rules,
        )
    legacy_summary = summarize_existing_cp_model_operations_by_rule(legacy_model)
    assert legacy_summary["night.fri_sun_mutex"]["operations"] == {
        "Add": len(bridge.problem.constraints),
    }

    solution = solve_cp_sat_problem(bridge.problem, time_limit_seconds=5)

    assert solution.status_name == "OPTIMAL"
    teacher_day_names = metadata["teacher_day_variable_names"]
    assert "teacher_exempt|星期五" in teacher_day_names
    assert "teacher_exempt|星期日" in teacher_day_names
    assert set(metadata["fri_sun_mutex_teacher_keys"]) == {"teacher_1", "teacher_2", "teacher_3"}
    assert metadata["configured_friday_pair"] == ("teacher_1", "teacher_3")


def test_generic_scheduler_rule_ids_exposes_real_night_fri_sun_mutex_coverage() -> None:
    covered_rule_ids = generic_scheduler_rule_ids()

    assert "night.fri_sun_mutex" in covered_rule_ids
    assert "joint.night.fri_sun_mutex" in covered_rule_ids


def _night_single_class_p1_p2_split_sample() -> tuple[tuple[str, ...], dict[tuple[str, str], str], tuple[str, ...], tuple[str, ...], dict]:
    return (
        ("class_a", "class_b", "class_c"),
        {
            ("class_a", "math"): "teacher_single_multi_subject",
            ("class_a", "history"): "teacher_single_multi_subject",
            ("class_b", "science"): "teacher_single_one_subject",
            ("class_b", "math"): "teacher_double_class",
            ("class_c", "math"): "teacher_double_class",
        },
        ("星期一", "星期二", "星期三"),
        ("晚自习1", "晚自习2"),
        {
            "evening": {"weekly_occurrences_per_subject": 2},
            "evening_constraints": {"enable_single_class_p1_p2_split": True},
        },
    )


def test_night_single_class_p1_p2_split_generic_contract_matches_legacy_period_exactly_one_shape() -> None:
    classes, cst, days, periods, rules = _night_single_class_p1_p2_split_sample()

    bridge = night_single_class_p1_p2_split_to_ai_or_problem(
        classes=classes,
        cst=cst,
        days=days,
        periods=periods,
        rules=rules,
    )

    assert bridge.problem.problem_id == "scheduler_night_single_class_p1_p2_split"
    assert tuple(rule.rule_id for rule in bridge.problem.rules) == ("night.single_class_p1_p2_split",)
    assert len(bridge.problem.variables) == len(cst) * len(days) * len(periods)
    assert len(bridge.problem.constraints) == 6
    metadata = bridge.metadata_by_rule["night.single_class_p1_p2_split"]
    assert metadata["generic_contract_status"] == "covered_by_generic_contract"
    assert metadata["constraint_family_counts"] == {
        "single_class_teacher_period_p1_exactly_one": 3,
        "single_class_teacher_period_p2_exactly_one": 3,
    }

    legacy_model = create_existing_cp_model("night.single_class_p1_p2_split.parity")
    legacy_vars = build_variables(legacy_model, classes, cst, days, periods)
    with ai_or_model_rule_context(
        "night.single_class_p1_p2_split",
        source="scheduler.model.constraints.night_single_class_period_split",
    ):
        apply_single_class_teacher_p1_p2_split(
            legacy_model,
            legacy_vars,
            {"classes": classes, "cst": cst, "days": days, "periods": periods},
            rules,
        )
    legacy_summary = summarize_existing_cp_model_operations_by_rule(legacy_model)
    assert legacy_summary["night.single_class_p1_p2_split"]["operations"] == {
        "Add": len(bridge.problem.constraints),
    }

    solution = solve_cp_sat_problem(bridge.problem, time_limit_seconds=5)

    assert solution.status_name == "OPTIMAL"
    assignment_names = metadata["assignment_variable_names"]
    for key in (
        "class_a|math|星期一|晚自习1",
        "class_a|history|星期二|晚自习2",
        "class_b|science|星期三|晚自习1",
    ):
        assert key in assignment_names
    assert set(metadata["single_class_teacher_keys"]) == {
        "teacher_single_multi_subject",
        "teacher_single_one_subject",
    }
    assert set(metadata["double_or_multi_class_teacher_keys"]) == {"teacher_double_class"}


def test_generic_scheduler_rule_ids_exposes_real_night_single_class_p1_p2_split_coverage() -> None:
    covered_rule_ids = generic_scheduler_rule_ids()

    assert "night.single_class_p1_p2_split" in covered_rule_ids
    assert "joint.night.single_class_p1_p2_split" in covered_rule_ids


def _night_double_class_weekday_p1_p2_split_sample() -> tuple[tuple[str, ...], dict[tuple[str, str], str], tuple[str, ...], tuple[str, ...], dict]:
    return (
        ("class_a", "class_b", "class_c", "class_d"),
        {
            ("class_a", "math"): "teacher_single_class",
            ("class_b", "math"): "teacher_double_class",
            ("class_c", "math"): "teacher_double_class",
            ("class_d", "history"): "teacher_three_class",
            ("class_b", "history"): "teacher_three_class",
            ("class_c", "history"): "teacher_three_class",
        },
        ("星期一", "星期六", "星期日"),
        ("晚自习1", "晚自习2"),
        {
            "evening": {"weekly_occurrences_per_subject": 2},
            "evening_constraints": {
                "enable_double_class_weekday_p1_p2_split": True,
                "double_class_weekday_p1_p2_mode": "hard",
            },
        },
    )


def test_night_double_class_weekday_p1_p2_split_generic_contract_matches_legacy_triggered_period_split_shape() -> None:
    classes, cst, days, periods, rules = _night_double_class_weekday_p1_p2_split_sample()

    bridge = night_double_class_weekday_p1_p2_split_to_ai_or_problem(
        classes=classes,
        cst=cst,
        days=days,
        periods=periods,
        rules=rules,
    )

    assert bridge.problem.problem_id == "scheduler_night_double_class_weekday_p1_p2_split"
    assert tuple(rule.rule_id for rule in bridge.problem.rules) == ("night.double_class_weekday_p1_p2_split",)
    assert len(bridge.problem.constraints) == 8
    metadata = bridge.metadata_by_rule["night.double_class_weekday_p1_p2_split"]
    assert metadata["generic_contract_status"] == "covered_by_generic_contract"
    assert metadata["constraint_family_counts"] == {
        "double_class_split_total_link": 2,
        "double_class_split_total_map_domain": 2,
        "double_class_period_p1_exactly_one_if_split_two": 2,
        "double_class_period_p2_exactly_one_if_split_two": 2,
    }

    legacy_model = create_existing_cp_model("night.double_class_weekday_p1_p2_split.parity")
    legacy_vars = build_variables(legacy_model, classes, cst, days, periods)
    with ai_or_model_rule_context(
        "night.double_class_weekday_p1_p2_split",
        source="scheduler.model.constraints.night_single_class_period_split",
    ):
        apply_double_class_teacher_weekday_alternate_p1_p2(
            legacy_model,
            legacy_vars,
            {"classes": classes, "cst": cst, "days": days, "periods": periods},
            rules,
        )
    legacy_summary = summarize_existing_cp_model_operations_by_rule(legacy_model)
    assert legacy_summary["night.double_class_weekday_p1_p2_split"]["operations"] == {
        "NewBoolVar": 2,
        "Add": len(bridge.problem.constraints),
    }

    solution = solve_cp_sat_problem(bridge.problem, time_limit_seconds=5)

    assert solution.status_name == "OPTIMAL"
    assert metadata["split_days"] == ("星期一", "星期日")
    assert set(metadata["double_class_teacher_keys"]) == {"teacher_double_class"}
    assert set(metadata["ignored_teacher_keys"]) == {"teacher_single_class", "teacher_three_class"}
    assert set(metadata["trigger_variable_names"]) == {
        "class_b|math",
        "class_c|math",
    }


def test_generic_scheduler_rule_ids_exposes_real_night_double_class_weekday_p1_p2_split_coverage() -> None:
    covered_rule_ids = generic_scheduler_rule_ids()

    assert "night.double_class_weekday_p1_p2_split" in covered_rule_ids
    assert "joint.night.double_class_weekday_p1_p2_split" in covered_rule_ids


def _night_checkin_hard_sample() -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...], dict]:
    return (
        ("male_a", "male_b", "male_excluded", "extra_m"),
        ("female_a", "female_b"),
        ("星期一", "星期二"),
        {
            "checkin": {
                "enabled": True,
                "per_day": {"male": 1, "female": 1},
                "per_teacher_max_times": 1,
                "require_teacher_has_class_that_day_mode": "hard",
                "exclude_heads": ["male_excluded"],
                "extra_heads": [{"name": "extra_m", "gender": "男", "days": ["星期一"]}],
            }
        },
    )


def test_night_checkin_generic_contract_matches_legacy_hard_staffing_and_same_day_shape() -> None:
    male_heads, female_heads, days, rules = _night_checkin_hard_sample()

    bridge = night_checkin_to_ai_or_problem(
        male_heads=male_heads,
        female_heads=female_heads,
        days=days,
        rules=rules,
    )

    assert bridge.problem.problem_id == "scheduler_night_checkin"
    assert tuple(rule.rule_id for rule in bridge.problem.rules) == ("night.checkin",)
    assert len(bridge.problem.constraints) == 29
    metadata = bridge.metadata_by_rule["night.checkin"]
    assert metadata["generic_contract_status"] == "covered_by_generic_contract"
    assert metadata["constraint_family_counts"] == {
        "same_day_on_coverage_male": 2,
        "same_day_on_coverage_female": 2,
        "excluded_male_checkin_zero": 2,
        "excluded_female_checkin_zero": 0,
        "extra_head_allowed_day_zero_male": 1,
        "extra_head_allowed_day_zero_female": 0,
        "daily_staffing_male": 2,
        "daily_staffing_female": 2,
        "weekly_max_male": 4,
        "weekly_max_female": 2,
        "same_day_class_male_hard": 8,
        "same_day_class_female_hard": 4,
    }

    legacy_model = create_existing_cp_model("night.checkin.parity")
    legacy_vars = build_checkin_variables(legacy_model, male_heads, female_heads, days)
    legacy_vars["on_teacher_day"] = {
        (teacher, day): legacy_model.NewBoolVar(f"on__{teacher}__{day}")
        for teacher in (*male_heads, *female_heads)
        for day in days
    }
    with ai_or_model_rule_context("night.checkin", source="scheduler.model.constraints.checkin"):
        penalties = apply_checkin(
            legacy_model,
            legacy_vars,
            {
                "days": days,
                "male_heads": male_heads,
                "female_heads": female_heads,
            },
            rules,
        )
    legacy_summary = summarize_existing_cp_model_operations_by_rule(legacy_model)
    assert penalties == []
    assert legacy_summary["night.checkin"]["operations"] == {
        "Add": len(bridge.problem.constraints),
    }

    solution = solve_cp_sat_problem(bridge.problem, time_limit_seconds=5)

    assert solution.status_name == "OPTIMAL"
    assert metadata["excluded_heads"] == ("male_excluded",)
    assert metadata["extra_head_allowed_days"] == {"extra_m|男": ("星期一",)}
    assert "male_excluded|星期一" in metadata["checkin_m_variable_names"]
    assert "female_b|星期二" in metadata["checkin_f_variable_names"]
    assert "male_a|星期一" in metadata["on_teacher_day_variable_names"]


def test_generic_scheduler_rule_ids_exposes_real_night_checkin_coverage() -> None:
    covered_rule_ids = generic_scheduler_rule_ids()

    assert "night.checkin" in covered_rule_ids
    assert "joint.night.checkin" in covered_rule_ids


def _weekend_double_period_day_input() -> DayInputData:
    slot_1 = Slot(day="星期六", block="上午", period=1)
    slot_2 = Slot(day="星期六", block="上午", period=2)
    slot_3 = Slot(day="星期六", block="上午", period=3)
    return DayInputData(
        classes=["class_a"],
        cls_subj_teacher={
            ("class_a", "math"): "teacher_1",
            ("class_a", "science"): "teacher_2",
        },
        available_slots=[slot_1, slot_2, slot_3],
        fixed_assign={},
        req_hours={},
        subject_ban_slots={},
    )


def test_day_weekend_double_period_same_class_generic_contract_matches_legacy_pair_cover_shape() -> None:
    data = _weekend_double_period_day_input()

    bridge = day_weekend_double_period_same_class_to_ai_or_problem(data)

    assert bridge.problem.problem_id == "scheduler_day_weekend_double_period_same_class"
    assert tuple(rule.rule_id for rule in bridge.problem.rules) == ("joint.day.weekend_double_period_same_class",)
    assert len(bridge.problem.constraints) == 26
    metadata = bridge.metadata_by_rule["joint.day.weekend_double_period_same_class"]
    assert metadata["generic_contract_status"] == "covered_by_generic_contract"
    assert metadata["constraint_family_counts"] == {
        "teacher_class_slot_bool_equalities": 6,
        "adjacent_pair_left_implications": 4,
        "adjacent_pair_right_implications": 4,
        "slot_pair_cover_lower_bounds": 6,
        "slot_pair_cover_overlap_caps": 6,
        "slot_without_adjacent_pair_zero": 0,
    }

    legacy_model = create_existing_cp_model("day.weekend_double_period_same_class.parity")
    legacy_vars = build_day_variables(legacy_model, data)
    with ai_or_model_rule_context(
        "joint.day.weekend_double_period_same_class",
        source="scheduler.model.constraints.day_weekend_constraints",
    ):
        apply_weekend_double_period_same_class(legacy_model, data, legacy_vars)
    legacy_summary = summarize_existing_cp_model_operations_by_rule(legacy_model)
    assert legacy_summary["joint.day.weekend_double_period_same_class"]["operations"] == {
        "NewBoolVar": 10,
        "Add": len(bridge.problem.constraints),
    }

    solution = solve_cp_sat_problem(bridge.problem, time_limit_seconds=5)

    assert solution.status_name == "OPTIMAL"
    assert len(metadata["teacher_class_slot_variable_names"]) == 6
    assert len(metadata["adjacent_pair_variable_names"]) == 4
    assert "teacher_1|class_a|星期六|上午1+上午2" in metadata["adjacent_pair_variable_names"]
    assert "teacher_2|class_a|星期六|上午2+上午3" in metadata["adjacent_pair_variable_names"]


def test_generic_scheduler_rule_ids_exposes_real_day_weekend_double_period_same_class_coverage() -> None:
    covered_rule_ids = generic_scheduler_rule_ids()

    assert "joint.day.weekend_double_period_same_class" in covered_rule_ids


def _weekend_cross_halfday_day_input() -> DayInputData:
    saturday_am = Slot(day="星期六", block="上午", period=1)
    saturday_pm = Slot(day="星期六", block="下午", period=1)
    return DayInputData(
        classes=["class_a"],
        cls_subj_teacher={
            ("class_a", "math"): "teacher_1",
            ("class_a", "science"): "teacher_2",
        },
        available_slots=[saturday_am, saturday_pm],
        fixed_assign={},
        req_hours={},
        subject_ban_slots={},
    )


def test_day_weekend_cross_halfday_penalty_generic_contract_matches_legacy_soft_shape() -> None:
    data = _weekend_cross_halfday_day_input()

    bridge = day_weekend_cross_halfday_penalty_to_ai_or_problem(data, penalty=200)

    assert bridge.problem.problem_id == "scheduler_day_weekend_cross_halfday_penalty"
    assert tuple(rule.rule_id for rule in bridge.problem.rules) == ("joint.day.weekend_cross_halfday_penalty",)
    assert bridge.problem.objective is not None
    assert bridge.problem.objective.rule_id == "joint.day.weekend_cross_halfday_penalty"
    assert {term.coefficient for term in bridge.problem.objective.expression.terms} == {200}
    assert len(bridge.problem.constraints) == 20
    metadata = bridge.metadata_by_rule["joint.day.weekend_cross_halfday_penalty"]
    assert metadata["generic_contract_status"] == "covered_by_generic_contract"
    assert metadata["constraint_family_counts"] == {
        "teacher_class_slot_bool_equalities": 4,
        "teacher_slot_implies_has_am": 2,
        "teacher_slot_implies_has_pm": 2,
        "has_am_lower_bounds": 2,
        "has_am_zero_constraints": 2,
        "has_pm_lower_bounds": 2,
        "has_pm_zero_constraints": 2,
        "cross_halfday_lower_bounds": 4,
    }

    legacy_model = create_existing_cp_model("day.weekend_cross_halfday_penalty.parity")
    legacy_vars = build_day_variables(legacy_model, data)
    with ai_or_model_rule_context(
        "joint.day.weekend_cross_halfday_penalty",
        source="scheduler.model.constraints.day_weekend_constraints",
    ):
        penalties = apply_weekend_cross_halfday_penalty(legacy_model, data, legacy_vars, penalty=200)
    legacy_summary = summarize_existing_cp_model_operations_by_rule(legacy_model)
    assert len(penalties) == 4
    assert legacy_summary["joint.day.weekend_cross_halfday_penalty"]["operations"] == {
        "NewBoolVar": 16,
        "Add": len(bridge.problem.constraints),
    }

    solution = solve_cp_sat_problem(bridge.problem, time_limit_seconds=5)

    assert solution.status_name == "OPTIMAL"
    assert solution.objective_value == 0
    assert len(metadata["teacher_class_slot_variable_names"]) == 4
    assert len(metadata["teacher_halfday_variable_names"]) == 8
    assert len(metadata["cross_halfday_variable_names"]) == 4


def test_generic_scheduler_rule_ids_exposes_real_day_weekend_cross_halfday_penalty_coverage() -> None:
    covered_rule_ids = generic_scheduler_rule_ids()

    assert "joint.day.weekend_cross_halfday_penalty" in covered_rule_ids


def _yjc_sunday_am12_pm12_day_input() -> DayInputData:
    slots = [
        Slot(day="星期日", block="上午", period=1),
        Slot(day="星期日", block="上午", period=2),
        Slot(day="星期日", block="下午", period=1),
        Slot(day="星期日", block="下午", period=2),
    ]
    return DayInputData(
        classes=["class_a"],
        cls_subj_teacher={
            ("class_a", "math"): "teacher_target",
            ("class_a", "science"): "teacher_other",
        },
        available_slots=slots,
        fixed_assign={},
        req_hours={},
        subject_ban_slots={},
    )


def test_day_yjc_sunday_am12_pm12_generic_contract_matches_legacy_hard_shape() -> None:
    data = _yjc_sunday_am12_pm12_day_input()

    bridge = day_yjc_sunday_am12_pm12_to_ai_or_problem(data, teachers=["teacher_target"])

    assert bridge.problem.problem_id == "scheduler_day_yjc_sunday_am12_pm12_rule"
    assert tuple(rule.rule_id for rule in bridge.problem.rules) == ("joint.day.yjc_sunday_am12_pm12_rule",)
    assert bridge.problem.objective is None
    assert len(bridge.problem.constraints) == 14
    metadata = bridge.metadata_by_rule["joint.day.yjc_sunday_am12_pm12_rule"]
    assert metadata["generic_contract_status"] == "covered_by_generic_contract"
    assert metadata["constraint_family_counts"] == {
        "target_slot_fixed_one": 0,
        "target_slot_lower_bounds": 4,
        "target_slot_implies": 4,
        "target_slot_zero": 0,
        "combo_upper_bounds": 4,
        "combo_lower_bounds": 1,
        "combo_hard_zero": 1,
    }

    legacy_model = create_existing_cp_model("day.yjc_sunday_am12_pm12.parity")
    legacy_vars = build_day_variables(legacy_model, data)
    with ai_or_model_rule_context(
        "joint.day.yjc_sunday_am12_pm12_rule",
        source="scheduler.model.constraints.day_weekend_constraints",
    ):
        penalties = apply_yjc_sunday_am12_pm12_rule(
            legacy_model,
            data,
            legacy_vars,
            teachers=["teacher_target"],
        )
    legacy_summary = summarize_existing_cp_model_operations_by_rule(legacy_model)
    assert penalties == []
    assert legacy_summary["joint.day.yjc_sunday_am12_pm12_rule"]["operations"] == {
        "NewBoolVar": 5,
        "Add": len(bridge.problem.constraints),
    }

    solution = solve_cp_sat_problem(bridge.problem, time_limit_seconds=5)

    assert solution.status_name == "OPTIMAL"
    assert len(metadata["target_slot_variable_names"]) == 4
    assert len(metadata["combo_variable_names"]) == 1
    assert "teacher_target|星期日|am1" in metadata["target_slot_variable_names"]
    assert "teacher_target|星期日" in metadata["combo_variable_names"]


def test_day_yjc_sunday_am12_pm12_generic_contract_supports_soft_objective() -> None:
    data = _yjc_sunday_am12_pm12_day_input()

    bridge = day_yjc_sunday_am12_pm12_to_ai_or_problem(
        data,
        mode="soft",
        weight=1000,
        teachers=["teacher_target"],
    )

    assert len(bridge.problem.constraints) == 13
    assert bridge.problem.objective is not None
    assert bridge.problem.objective.rule_id == "joint.day.yjc_sunday_am12_pm12_rule"
    assert tuple(term.coefficient for term in bridge.problem.objective.expression.terms) == (1000,)
    metadata = bridge.metadata_by_rule["joint.day.yjc_sunday_am12_pm12_rule"]
    assert metadata["constraint_family_counts"]["combo_hard_zero"] == 0
    assert metadata["mode"] == "soft"

    legacy_model = create_existing_cp_model("day.yjc_sunday_am12_pm12.soft.parity")
    legacy_vars = build_day_variables(legacy_model, data)
    with ai_or_model_rule_context(
        "joint.day.yjc_sunday_am12_pm12_rule",
        source="scheduler.model.constraints.day_weekend_constraints",
    ):
        penalties = apply_yjc_sunday_am12_pm12_rule(
            legacy_model,
            data,
            legacy_vars,
            mode="soft",
            teachers=["teacher_target"],
        )
    legacy_summary = summarize_existing_cp_model_operations_by_rule(legacy_model)
    assert len(penalties) == 1
    assert legacy_summary["joint.day.yjc_sunday_am12_pm12_rule"]["operations"] == {
        "NewBoolVar": 5,
        "Add": len(bridge.problem.constraints),
    }

    solution = solve_cp_sat_problem(bridge.problem, time_limit_seconds=5)

    assert solution.status_name == "OPTIMAL"
    assert solution.objective_value == 0


def test_generic_scheduler_rule_ids_exposes_real_day_yjc_sunday_am12_pm12_coverage() -> None:
    covered_rule_ids = generic_scheduler_rule_ids()

    assert "joint.day.yjc_sunday_am12_pm12_rule" in covered_rule_ids


def _day_binding_8chem_9bio_input() -> DayInputData:
    slot_1 = Slot(day="星期一", block="上午", period=1)
    slot_2 = Slot(day="星期六", block="下午", period=1)
    return DayInputData(
        classes=["初二8班", "初二9班", "初二10班"],
        cls_subj_teacher={
            ("初二8班", "化学"): "chem_teacher",
            ("初二8班", "数学"): "math_teacher",
            ("初二9班", "生物"): "bio_teacher",
            ("初二10班", "化学"): "other_teacher",
        },
        available_slots=[slot_1, slot_2],
        fixed_assign={},
        req_hours={},
        subject_ban_slots={},
    )


def test_day_binding_8chem_9bio_generic_contract_matches_legacy_shape() -> None:
    data = _day_binding_8chem_9bio_input()

    bridge = day_binding_8chem_9bio_to_ai_or_problem(data)

    assert bridge.problem.problem_id == "scheduler_day_binding_8chem_9bio"
    assert tuple(rule.rule_id for rule in bridge.problem.rules) == ("joint.day.binding_8chem_9bio",)
    assert len(bridge.problem.variables) == len(data.cls_subj_teacher) * len(data.available_slots)
    assert len(bridge.problem.constraints) == len(data.available_slots)
    metadata = bridge.metadata_by_rule["joint.day.binding_8chem_9bio"]
    assert metadata["generic_contract_status"] == "covered_by_generic_contract"
    assert metadata["constraint_family_counts"] == {"8chem_9bio_equalities": 2}
    assert metadata["binding_classes"] == {
        "chemistry_class": "初二8班",
        "biology_class": "初二9班",
    }

    legacy_model = create_existing_cp_model("day.binding_8chem_9bio.parity")
    legacy_vars = build_day_variables(legacy_model, data)
    with ai_or_model_rule_context(
        "joint.day.binding_8chem_9bio",
        source="scheduler.model.constraints.global_binding_constraints",
    ):
        apply_global_day_binding_8_chem_9_bio(legacy_model, data, legacy_vars)
    legacy_summary = summarize_existing_cp_model_operations_by_rule(legacy_model)
    assert legacy_summary["joint.day.binding_8chem_9bio"]["operations"] == {
        "Add": len(bridge.problem.constraints)
    }

    solution = solve_cp_sat_problem(bridge.problem, time_limit_seconds=5)

    assert solution.status_name == "OPTIMAL"
    assignment_names = metadata["assignment_variable_names"]
    for slot in data.available_slots:
        slot_label = f"{slot.block}{slot.period}"
        assert (
            solution.values[assignment_names[f"初二8班|化学|{slot.day}|{slot_label}"]]
            == solution.values[assignment_names[f"初二9班|生物|{slot.day}|{slot_label}"]]
        )


def test_generic_scheduler_rule_ids_exposes_real_day_binding_8chem_9bio_coverage() -> None:
    covered_rule_ids = generic_scheduler_rule_ids()

    assert "joint.day.binding_8chem_9bio" in covered_rule_ids


def _small_day_input() -> DayInputData:
    slot_1 = Slot(day="day_1", block="上午", period=1)
    slot_2 = Slot(day="day_1", block="上午", period=2)
    return DayInputData(
        classes=["class_a", "class_b"],
        cls_subj_teacher={
            ("class_a", "math"): "teacher_1",
            ("class_a", "science"): "teacher_2",
            ("class_b", "math"): "teacher_1",
            ("class_b", "science"): "teacher_3",
        },
        available_slots=[slot_1, slot_2],
        fixed_assign={},
        req_hours={
            ("class_a", "math"): (0, 1, 0),
            ("class_a", "science"): (0, 1, 0),
            ("class_b", "math"): (0, 1, 0),
            ("class_b", "science"): (0, 1, 0),
        },
        subject_ban_slots={},
    )


def test_day_one_subject_per_slot_generic_contract_matches_legacy_shape() -> None:
    data = _small_day_input()

    bridge = day_one_subject_per_slot_to_ai_or_problem(data)

    assert bridge.problem.problem_id == "scheduler_day_one_subject_per_slot"
    assert tuple(rule.rule_id for rule in bridge.problem.rules) == ("joint.day.one_subject_per_slot",)
    assert len(bridge.problem.variables) == len(data.cls_subj_teacher) * len(data.available_slots)
    assert len(bridge.problem.constraints) == len(data.classes) * len(data.available_slots)
    assert (
        bridge.metadata_by_rule["joint.day.one_subject_per_slot"]["generic_contract_status"]
        == "covered_by_generic_contract"
    )

    legacy_model = create_existing_cp_model("day.one_subject_per_slot.parity")
    legacy_vars = build_day_variables(legacy_model, data)
    with ai_or_model_rule_context(
        "joint.day.one_subject_per_slot",
        source="scheduler.model.constraints.day_hard_one_per_slot",
    ):
        apply_one_subject_per_slot(legacy_model, data, legacy_vars)
    legacy_summary = summarize_existing_cp_model_operations_by_rule(legacy_model)
    assert legacy_summary["joint.day.one_subject_per_slot"]["operations"] == {
        "Add": len(bridge.problem.constraints),
    }

    solution = solve_cp_sat_problem(bridge.problem, time_limit_seconds=5)

    assert solution.status_name == "OPTIMAL"
    assignments = bridge.metadata_by_rule["joint.day.one_subject_per_slot"]["assignment_variable_names"]
    for cls in data.classes:
        for slot in data.available_slots:
            assert (
                sum(
                    solution.values[assignments[f"{cls}|{subj}|{slot.day}|{slot.block}{slot.period}"]]
                    for c, subj in data.cls_subj_teacher
                    if c == cls
                )
                == 1
            )


def test_generic_scheduler_rule_ids_exposes_real_day_one_subject_coverage() -> None:
    covered_rule_ids = generic_scheduler_rule_ids()

    assert "joint.day.one_subject_per_slot" in covered_rule_ids


def _subject_hours_day_input() -> DayInputData:
    early = Slot(day="星期一", block="早自习", period=1)
    weekday = Slot(day="星期一", block="上午", period=1)
    weekend = Slot(day="星期六", block="上午", period=1)
    return DayInputData(
        classes=["class_a"],
        cls_subj_teacher={
            ("class_a", "math"): "teacher_1",
            ("class_a", "science"): "teacher_2",
        },
        available_slots=[early, weekday, weekend],
        fixed_assign={},
        req_hours={
            ("class_a", "math"): (1, 1, 0),
            ("class_a", "science"): (0, 0, 1),
        },
        subject_ban_slots={},
    )


def test_day_subject_hours_generic_contract_matches_legacy_shape() -> None:
    data = _subject_hours_day_input()

    bridge = day_subject_hours_to_ai_or_problem(data)

    assert bridge.problem.problem_id == "scheduler_day_subject_hour_constraints"
    assert tuple(rule.rule_id for rule in bridge.problem.rules) == ("joint.day.subject_hour_constraints",)
    assert len(bridge.problem.variables) == len(data.cls_subj_teacher) * len(data.available_slots)
    assert len(bridge.problem.constraints) == len(data.req_hours) * 3
    assert (
        bridge.metadata_by_rule["joint.day.subject_hour_constraints"]["generic_contract_status"]
        == "covered_by_generic_contract"
    )

    legacy_model = create_existing_cp_model("day.subject_hours.parity")
    legacy_vars = build_day_variables(legacy_model, data)
    with ai_or_model_rule_context(
        "joint.day.subject_hour_constraints",
        source="scheduler.model.constraints.day_hard_subject_hours",
    ):
        apply_subject_hour_constraints(legacy_model, data, legacy_vars)
    legacy_summary = summarize_existing_cp_model_operations_by_rule(legacy_model)
    assert legacy_summary["joint.day.subject_hour_constraints"]["operations"] == {
        "Add": len(bridge.problem.constraints),
    }

    solution = solve_cp_sat_problem(bridge.problem, time_limit_seconds=5)

    assert solution.status_name == "OPTIMAL"
    assignments = bridge.metadata_by_rule["joint.day.subject_hour_constraints"]["assignment_variable_names"]
    for cls, subj in data.req_hours:
        early = sum(
            solution.values[assignments[f"{cls}|{subj}|{slot.day}|{slot.block}{slot.period}"]]
            for slot in data.available_slots
            if slot.block == "早自习"
        )
        weekday = sum(
            solution.values[assignments[f"{cls}|{subj}|{slot.day}|{slot.block}{slot.period}"]]
            for slot in data.available_slots
            if slot.block != "早自习" and slot.day == "星期一"
        )
        weekend = sum(
            solution.values[assignments[f"{cls}|{subj}|{slot.day}|{slot.block}{slot.period}"]]
            for slot in data.available_slots
            if slot.block != "早自习" and slot.day == "星期六"
        )
        assert (early, weekday, weekend) == data.req_hours[(cls, subj)]


def test_generic_scheduler_rule_ids_exposes_real_day_subject_hours_coverage() -> None:
    covered_rule_ids = generic_scheduler_rule_ids()

    assert "joint.day.subject_hour_constraints" in covered_rule_ids


def _teacher_conflict_day_input() -> DayInputData:
    slot_1 = Slot(day="星期一", block="上午", period=1)
    slot_2 = Slot(day="星期一", block="上午", period=2)
    return DayInputData(
        classes=["class_a", "class_b"],
        cls_subj_teacher={
            ("class_a", "math"): "teacher_1",
            ("class_a", "science"): "teacher_2",
            ("class_b", "math"): "teacher_1",
            ("class_b", "science"): "teacher_3",
        },
        available_slots=[slot_1, slot_2],
        fixed_assign={},
        req_hours={
            ("class_a", "math"): (0, 1, 0),
            ("class_a", "science"): (0, 1, 0),
            ("class_b", "math"): (0, 1, 0),
            ("class_b", "science"): (0, 1, 0),
        },
        subject_ban_slots={},
    )


def test_day_teacher_no_conflict_generic_contract_matches_legacy_shape() -> None:
    data = _teacher_conflict_day_input()

    bridge = day_teacher_no_conflict_to_ai_or_problem(data)

    assert bridge.problem.problem_id == "scheduler_day_teacher_no_conflict"
    assert tuple(rule.rule_id for rule in bridge.problem.rules) == ("joint.day.teacher_no_conflict",)
    assert len(bridge.problem.variables) == len(data.cls_subj_teacher) * len(data.available_slots)
    assert len(bridge.problem.constraints) == len(data.available_slots)
    assert (
        bridge.metadata_by_rule["joint.day.teacher_no_conflict"]["generic_contract_status"]
        == "covered_by_generic_contract"
    )
    assert all(constraint.sense == "<=" and constraint.rhs == 1 for constraint in bridge.problem.constraints)
    assert all(len(constraint.expression.terms) == 2 for constraint in bridge.problem.constraints)

    teacher_slot_names = bridge.metadata_by_rule["joint.day.teacher_no_conflict"]["teacher_slot_variable_names"]
    for slot in data.available_slots:
        assert len(teacher_slot_names[f"teacher_1|{slot.day}|{slot.block}{slot.period}"]) == 2

    legacy_model = create_existing_cp_model("day.teacher_no_conflict.parity")
    legacy_vars = build_day_variables(legacy_model, data)
    with ai_or_model_rule_context(
        "joint.day.teacher_no_conflict",
        source="scheduler.model.constraints.day_hard_teacher_conflict",
    ):
        apply_teacher_no_conflict(legacy_model, data, legacy_vars)
    legacy_summary = summarize_existing_cp_model_operations_by_rule(legacy_model)
    assert legacy_summary["joint.day.teacher_no_conflict"]["operations"] == {
        "Add": len(bridge.problem.constraints),
    }

    solution = solve_cp_sat_problem(bridge.problem, time_limit_seconds=5)

    assert solution.status_name == "OPTIMAL"
    for variable_names in teacher_slot_names.values():
        assert sum(solution.values[name] for name in variable_names) <= 1


def test_generic_scheduler_rule_ids_exposes_real_day_teacher_no_conflict_coverage() -> None:
    covered_rule_ids = generic_scheduler_rule_ids()

    assert "joint.day.teacher_no_conflict" in covered_rule_ids


def _no_consecutive_teacher_class_day_input() -> DayInputData:
    am1 = Slot(day="星期一", block="上午", period=1)
    am2 = Slot(day="星期一", block="上午", period=2)
    weekend = Slot(day="星期六", block="上午", period=1)
    return DayInputData(
        classes=["class_a"],
        cls_subj_teacher={
            ("class_a", "math"): "teacher_1",
            ("class_a", "science"): "teacher_1",
            ("class_a", "history"): "teacher_2",
        },
        available_slots=[am1, am2, weekend],
        fixed_assign={("class_a", am1): "math"},
        req_hours={
            ("class_a", "math"): (0, 1, 0),
            ("class_a", "science"): (0, 1, 0),
            ("class_a", "history"): (0, 1, 0),
        },
        subject_ban_slots={},
    )


def test_day_no_consecutive_same_teacher_same_class_generic_contract_matches_legacy_shape() -> None:
    data = _no_consecutive_teacher_class_day_input()

    bridge = day_no_consecutive_same_teacher_same_class_to_ai_or_problem(data)

    assert bridge.problem.problem_id == "scheduler_day_no_consecutive_same_teacher_same_class"
    assert tuple(rule.rule_id for rule in bridge.problem.rules) == (
        "joint.day.no_consecutive_same_teacher_same_class",
    )
    assert len(bridge.problem.variables) == len(data.cls_subj_teacher) * 2
    assert len(bridge.problem.constraints) == 2
    assert (
        bridge.metadata_by_rule["joint.day.no_consecutive_same_teacher_same_class"]["generic_contract_status"]
        == "covered_by_generic_contract"
    )
    assert all(constraint.sense == "<=" and constraint.rhs == 1 for constraint in bridge.problem.constraints)

    adjacency_names = bridge.metadata_by_rule["joint.day.no_consecutive_same_teacher_same_class"][
        "teacher_class_adjacent_variable_names"
    ]
    fixed_counts = bridge.metadata_by_rule["joint.day.no_consecutive_same_teacher_same_class"][
        "teacher_class_adjacent_fixed_counts"
    ]
    assert set(adjacency_names) == {
        "class_a|teacher_1|星期一|上午1__上午2",
        "class_a|teacher_2|星期一|上午1__上午2",
    }
    assert len(adjacency_names["class_a|teacher_1|星期一|上午1__上午2"]) == 2
    assert len(adjacency_names["class_a|teacher_2|星期一|上午1__上午2"]) == 1
    assert fixed_counts["class_a|teacher_1|星期一|上午1__上午2"] == 1
    assert fixed_counts["class_a|teacher_2|星期一|上午1__上午2"] == 0

    legacy_model = create_existing_cp_model("day.no_consecutive_same_teacher_same_class.parity")
    legacy_vars = build_day_variables(legacy_model, data)
    with ai_or_model_rule_context(
        "joint.day.no_consecutive_same_teacher_same_class",
        source="scheduler.model.constraints.day_weekday_constraints",
    ):
        apply_no_consecutive_same_teacher_same_class(legacy_model, data, legacy_vars)
    legacy_summary = summarize_existing_cp_model_operations_by_rule(legacy_model)
    assert legacy_summary["joint.day.no_consecutive_same_teacher_same_class"]["operations"] == {
        "Add": len(bridge.problem.constraints),
    }

    solution = solve_cp_sat_problem(bridge.problem, time_limit_seconds=5)

    assert solution.status_name == "OPTIMAL"
    for variable_name in adjacency_names["class_a|teacher_1|星期一|上午1__上午2"]:
        assert solution.values[variable_name] == 0


def test_generic_scheduler_rule_ids_exposes_real_day_no_consecutive_same_teacher_same_class_coverage() -> None:
    covered_rule_ids = generic_scheduler_rule_ids()

    assert "joint.day.no_consecutive_same_teacher_same_class" in covered_rule_ids


def _core_subject_teacher_day_load_day_input() -> DayInputData:
    early = Slot(day="星期一", block="早自习", period=1)
    mon_am1 = Slot(day="星期一", block="上午", period=1)
    mon_am2 = Slot(day="星期一", block="上午", period=2)
    mon_am4 = Slot(day="星期一", block="上午", period=4)
    mon_pm1 = Slot(day="星期一", block="下午", period=1)
    tue_am1 = Slot(day="星期二", block="上午", period=1)
    weekend = Slot(day="星期六", block="上午", period=1)
    return DayInputData(
        classes=["class_a", "class_b"],
        cls_subj_teacher={
            ("class_a", "数学"): "teacher_core",
            ("class_a", "英语"): "teacher_core",
            ("class_b", "体育"): "pe_teacher",
        },
        available_slots=[early, mon_am1, mon_am2, mon_am4, mon_pm1, tue_am1, weekend],
        fixed_assign={("class_a", mon_pm1): "数学"},
        req_hours={
            ("class_a", "数学"): (1, 3, 1),
            ("class_a", "英语"): (0, 2, 1),
            ("class_b", "体育"): (0, 1, 1),
        },
        subject_ban_slots={},
    )


def test_day_core_subject_teacher_day_load_generic_contract_matches_legacy_shape() -> None:
    data = _core_subject_teacher_day_load_day_input()

    bridge = day_core_subject_teacher_day_load_no_am1_am4_to_ai_or_problem(data, max_per_day=3)

    assert bridge.problem.problem_id == "scheduler_day_core_subject_teacher_day_load_no_am1_am4"
    assert tuple(rule.rule_id for rule in bridge.problem.rules) == (
        "joint.day.core_subject_teacher_day_load_no_am1_am4",
    )
    metadata = bridge.metadata_by_rule["joint.day.core_subject_teacher_day_load_no_am1_am4"]
    assert metadata["generic_contract_status"] == "covered_by_generic_contract"
    assert metadata["legacy_apply_fn"] == "apply_core_subject_teacher_day_load_and_no_am1_am4"
    assert metadata["target_teachers"] == ("teacher_core",)
    assert metadata["constraint_family_counts"] == {
        "core_teacher_daily_load_caps": 5,
        "core_teacher_am1_am4_mutexes": 5,
    }
    assert len(bridge.problem.constraints) == 10

    legacy_model = create_existing_cp_model("day.core_subject_teacher_day_load.parity")
    legacy_vars = build_day_variables(legacy_model, data)
    with ai_or_model_rule_context(
        "joint.day.core_subject_teacher_day_load_no_am1_am4",
        source="scheduler.model.constraints.day_weekday_constraints",
    ):
        apply_core_subject_teacher_day_load_and_no_am1_am4(legacy_model, data, legacy_vars, max_per_day=3)
    legacy_summary = summarize_existing_cp_model_operations_by_rule(legacy_model)
    assert legacy_summary["joint.day.core_subject_teacher_day_load_no_am1_am4"]["operations"] == {
        "Add": len(bridge.problem.constraints),
    }

    solution = solve_cp_sat_problem(bridge.problem, time_limit_seconds=5)

    assert solution.status_name == "OPTIMAL"


def _no_am1_am4_day_input() -> DayInputData:
    am1 = Slot(day="星期一", block="上午", period=1)
    am2 = Slot(day="星期一", block="上午", period=2)
    am4 = Slot(day="星期一", block="上午", period=4)
    weekend = Slot(day="星期六", block="上午", period=1)
    return DayInputData(
        classes=["class_a", "class_b"],
        cls_subj_teacher={
            ("class_a", "math"): "teacher_1",
            ("class_a", "science"): "teacher_1",
            ("class_b", "体育"): "pe_teacher_subject",
            ("class_b", "history"): "pe_teacher_param",
        },
        available_slots=[am1, am2, am4, weekend],
        fixed_assign={},
        req_hours={
            ("class_a", "math"): (0, 2, 0),
            ("class_a", "science"): (0, 1, 1),
            ("class_b", "体育"): (0, 1, 0),
            ("class_b", "history"): (0, 1, 1),
        },
        subject_ban_slots={},
    )


def test_day_no_am1_am4_generic_contract_matches_legacy_shape() -> None:
    data = _no_am1_am4_day_input()
    pe_teachers = {"pe_teacher_param"}

    bridge = day_no_am1_am4_to_ai_or_problem(data, pe_teachers=pe_teachers)

    assert bridge.problem.problem_id == "scheduler_day_no_am1_am4"
    assert tuple(rule.rule_id for rule in bridge.problem.rules) == ("joint.day.no_am1_am4",)
    assert len(bridge.problem.variables) == len(data.cls_subj_teacher) * len(data.available_slots)
    assert len(bridge.problem.constraints) == 1
    assert bridge.metadata_by_rule["joint.day.no_am1_am4"]["generic_contract_status"] == "covered_by_generic_contract"
    assert all(constraint.sense == "<=" and constraint.rhs == 1 for constraint in bridge.problem.constraints)
    assert len(bridge.problem.constraints[0].expression.terms) == 4

    teacher_day_names = bridge.metadata_by_rule["joint.day.no_am1_am4"]["teacher_day_variable_names"]
    assert set(teacher_day_names) == {"teacher_1|星期一"}
    assert len(teacher_day_names["teacher_1|星期一"]) == 4

    legacy_model = create_existing_cp_model("day.no_am1_am4.parity")
    legacy_vars = build_day_variables(legacy_model, data)
    with ai_or_model_rule_context(
        "joint.day.no_am1_am4",
        source="scheduler.model.constraints.day_weekday_constraints",
    ):
        apply_no_am1_am4(legacy_model, data, legacy_vars, pe_teachers)
    legacy_summary = summarize_existing_cp_model_operations_by_rule(legacy_model)
    assert legacy_summary["joint.day.no_am1_am4"]["operations"] == {
        "Add": len(bridge.problem.constraints),
    }

    solution = solve_cp_sat_problem(bridge.problem, time_limit_seconds=5)

    assert solution.status_name == "OPTIMAL"
    for variable_names in teacher_day_names.values():
        assert sum(solution.values[name] for name in variable_names) <= 1


def test_generic_scheduler_rule_ids_exposes_real_day_no_am1_am4_coverage() -> None:
    covered_rule_ids = generic_scheduler_rule_ids()

    assert "joint.day.no_am1_am4" in covered_rule_ids


def _head_pm1_min_day_input() -> DayInputData:
    slots = [
        Slot(day="星期一", block="下午", period=1),
        Slot(day="星期二", block="下午", period=1),
        Slot(day="星期三", block="下午", period=1),
        Slot(day="星期四", block="下午", period=1),
        Slot(day="星期五", block="下午", period=1),
    ]
    return DayInputData(
        classes=["class_a", "class_b", "class_c", "class_d"],
        cls_subj_teacher={
            ("class_a", "math"): "head_1",
            ("class_b", "science"): "head_2",
            ("class_c", "history"): "head_3",
            ("class_d", "体育"): "head_pe_subject",
        },
        available_slots=slots,
        fixed_assign={},
        req_hours={
            ("class_a", "math"): (0, 5, 0),
            ("class_b", "science"): (0, 5, 0),
            ("class_c", "history"): (0, 5, 0),
            ("class_d", "体育"): (0, 5, 0),
        },
        subject_ban_slots={},
    )


def test_day_head_pm1_min_generic_contract_matches_legacy_shape() -> None:
    data = _head_pm1_min_day_input()
    head_teachers = ["head_1", "head_2", "head_3", "head_pe_subject"]

    bridge = day_head_pm1_min_to_ai_or_problem(data, head_teachers=head_teachers, min_required=3)

    assert bridge.problem.problem_id == "scheduler_day_head_pm1_min"
    assert tuple(rule.rule_id for rule in bridge.problem.rules) == ("joint.day.head_pm1_min",)
    metadata = bridge.metadata_by_rule["joint.day.head_pm1_min"]
    assert metadata["generic_contract_status"] == "covered_by_generic_contract"
    assert metadata["legacy_apply_fn"] == "apply_head_pm1_min"
    assert metadata["head_teachers"] == ("head_1", "head_2", "head_3", "head_pe_subject")
    assert metadata["constraint_family_counts"] == {"head_pm1_minimums": 5}
    assert len(bridge.problem.constraints) == 5
    assert all(len(names) == 3 for names in metadata["day_pm1_variable_names"].values())

    legacy_model = create_existing_cp_model("day.head_pm1_min.parity")
    legacy_vars = build_day_variables(legacy_model, data)
    with ai_or_model_rule_context(
        "joint.day.head_pm1_min",
        source="scheduler.model.constraints.day_weekday_constraints",
    ):
        apply_head_pm1_min(legacy_model, data, legacy_vars, head_teachers)
    legacy_summary = summarize_existing_cp_model_operations_by_rule(legacy_model)
    assert legacy_summary["joint.day.head_pm1_min"]["operations"] == {
        "Add": len(bridge.problem.constraints),
    }

    solution = solve_cp_sat_problem(bridge.problem, time_limit_seconds=5)

    assert solution.status_name == "OPTIMAL"
    for variable_names in metadata["day_pm1_variable_names"].values():
        assert sum(solution.values[name] for name in variable_names) >= 3


def test_generic_scheduler_rule_ids_exposes_real_day_head_pm1_min_coverage() -> None:
    covered_rule_ids = generic_scheduler_rule_ids()

    assert "joint.day.head_pm1_min" in covered_rule_ids


def _teacher_weekday_am_pm_presence_day_input() -> DayInputData:
    early = Slot(day="星期一", block="早自习", period=1)
    am1 = Slot(day="星期一", block="上午", period=1)
    pm1 = Slot(day="星期一", block="下午", period=1)
    weekend = Slot(day="星期六", block="下午", period=1)
    return DayInputData(
        classes=["class_a", "class_b", "class_c", "class_d"],
        cls_subj_teacher={
            ("class_a", "math"): "teacher_main",
            ("class_a", "science"): "teacher_main",
            ("class_b", "history"): "teacher_fixed",
            ("class_c", "体育"): "pe_subject_teacher",
            ("class_d", "art"): "pe_param_teacher",
        },
        available_slots=[early, am1, pm1, weekend],
        fixed_assign={("class_b", pm1): "history"},
        req_hours={
            ("class_a", "math"): (0, 1, 1),
            ("class_a", "science"): (0, 1, 1),
            ("class_b", "history"): (0, 1, 1),
            ("class_c", "体育"): (0, 1, 1),
            ("class_d", "art"): (0, 1, 1),
        },
        subject_ban_slots={},
    )


def test_day_teacher_weekday_am_pm_presence_generic_contract_matches_legacy_shape() -> None:
    data = _teacher_weekday_am_pm_presence_day_input()
    pe_teachers = {"pe_param_teacher"}

    bridge = day_teacher_weekday_am_pm_presence_to_ai_or_problem(data, pe_teachers=pe_teachers)

    assert bridge.problem.problem_id == "scheduler_day_teacher_weekday_am_pm_presence"
    assert tuple(rule.rule_id for rule in bridge.problem.rules) == ("joint.day.teacher_weekday_am_pm_presence",)
    metadata = bridge.metadata_by_rule["joint.day.teacher_weekday_am_pm_presence"]
    assert metadata["generic_contract_status"] == "covered_by_generic_contract"
    assert metadata["legacy_apply_fn"] == "apply_teacher_weekday_am_pm_presence"
    assert metadata["constrained_teachers"] == ("teacher_fixed", "teacher_main")
    assert metadata["constraint_family_counts"] == {
        "teacher_weekday_am_presence_minimums": 2,
        "teacher_weekday_pm_presence_minimums": 2,
    }
    assert len(bridge.problem.constraints) == 4

    legacy_model = create_existing_cp_model("day.teacher_weekday_am_pm_presence.parity")
    legacy_vars = build_day_variables(legacy_model, data)
    with ai_or_model_rule_context(
        "joint.day.teacher_weekday_am_pm_presence",
        source="scheduler.model.constraints.day_weekday_constraints",
    ):
        apply_teacher_weekday_am_pm_presence(legacy_model, data, legacy_vars, pe_teachers)
    legacy_summary = summarize_existing_cp_model_operations_by_rule(legacy_model)
    assert legacy_summary["joint.day.teacher_weekday_am_pm_presence"]["operations"] == {
        "Add": len(bridge.problem.constraints),
    }

    solution = solve_cp_sat_problem(bridge.problem, time_limit_seconds=5)

    assert solution.status_name == "OPTIMAL"
    assignment_names = metadata["assignment_variable_names"]
    assert (
        solution.values[assignment_names["class_b|history|星期一|早自习1"]]
        + solution.values[assignment_names["class_b|history|星期一|上午1"]]
        >= 1
    )


def test_generic_scheduler_rule_ids_exposes_real_day_teacher_weekday_am_pm_presence_coverage() -> None:
    covered_rule_ids = generic_scheduler_rule_ids()

    assert "joint.day.teacher_weekday_am_pm_presence" in covered_rule_ids


def _am1_pm1_mutex_day_input() -> DayInputData:
    am1 = Slot(day="星期一", block="上午", period=1)
    am2 = Slot(day="星期一", block="上午", period=2)
    pm1 = Slot(day="星期一", block="下午", period=1)
    weekend = Slot(day="星期六", block="上午", period=1)
    return DayInputData(
        classes=["class_a", "class_b"],
        cls_subj_teacher={
            ("class_a", "math"): "teacher_1",
            ("class_a", "science"): "teacher_1",
            ("class_b", "history"): "teacher_2",
            ("class_b", "art"): "teacher_3",
        },
        available_slots=[am1, am2, pm1, weekend],
        fixed_assign={("class_b", pm1): "history"},
        req_hours={
            ("class_a", "math"): (0, 1, 1),
            ("class_a", "science"): (0, 1, 1),
            ("class_b", "history"): (0, 1, 0),
            ("class_b", "art"): (0, 1, 0),
        },
        subject_ban_slots={},
    )


def test_day_am1_pm1_mutex_generic_contract_matches_legacy_hard_shape() -> None:
    data = _am1_pm1_mutex_day_input()

    bridge = day_am1_pm1_mutex_to_ai_or_problem(data)

    assert bridge.problem.problem_id == "scheduler_day_am1_pm1_mutex"
    assert tuple(rule.rule_id for rule in bridge.problem.rules) == ("joint.day.am1_pm1_mutex",)
    metadata = bridge.metadata_by_rule["joint.day.am1_pm1_mutex"]
    assert metadata["generic_contract_status"] == "covered_by_generic_contract"
    assert metadata["constraint_family_counts"] == {
        "presence_fixed_one": 1,
        "presence_lower_bounds": 4,
        "presence_implies": 6,
        "presence_zero": 1,
        "teacher_day_am1_pm1_mutex": 3,
        "violation_upper_bounds": 0,
        "violation_lower_bounds": 0,
    }
    assert len(metadata["teacher_day_slot_presence_variable_names"]) == 6
    assert len(bridge.problem.constraints) == 15

    legacy_model = create_existing_cp_model("day.am1_pm1_mutex.parity")
    legacy_vars = build_day_variables(legacy_model, data)
    with ai_or_model_rule_context(
        "joint.day.am1_pm1_mutex",
        source="scheduler.model.constraints.day_weekday_constraints",
    ):
        apply_am1_pm1_mutex(legacy_model, data, legacy_vars, mode="hard")
    legacy_summary = summarize_existing_cp_model_operations_by_rule(legacy_model)
    assert legacy_summary["joint.day.am1_pm1_mutex"]["operations"] == {
        "Add": len(bridge.problem.constraints),
        "NewBoolVar": len(metadata["teacher_day_slot_presence_variable_names"]),
    }

    solution = solve_cp_sat_problem(bridge.problem, time_limit_seconds=5)

    assert solution.status_name == "OPTIMAL"
    assignment_names = metadata["assignment_variable_names"]
    assert solution.values[assignment_names["class_b|history|星期一|上午1"]] == 0


def test_day_am1_pm1_mutex_generic_contract_models_soft_objective() -> None:
    data = _am1_pm1_mutex_day_input()

    bridge = day_am1_pm1_mutex_to_ai_or_problem(data, mode="soft", weight=7)

    metadata = bridge.metadata_by_rule["joint.day.am1_pm1_mutex"]
    assert bridge.problem.objective is not None
    assert bridge.problem.objective.rule_id == "joint.day.am1_pm1_mutex"
    assert {term.coefficient for term in bridge.problem.objective.expression.terms} == {7}
    assert metadata["constraint_family_counts"]["violation_upper_bounds"] == 6
    assert metadata["constraint_family_counts"]["violation_lower_bounds"] == 3
    assert len(metadata["violation_variable_names"]) == 3

    legacy_model = create_existing_cp_model("day.am1_pm1_mutex.soft.parity")
    legacy_vars = build_day_variables(legacy_model, data)
    with ai_or_model_rule_context(
        "joint.day.am1_pm1_mutex",
        source="scheduler.model.constraints.day_weekday_constraints",
    ):
        penalties = apply_am1_pm1_mutex(legacy_model, data, legacy_vars, mode="soft", weight=7)
    legacy_summary = summarize_existing_cp_model_operations_by_rule(legacy_model)
    assert len(penalties) == len(metadata["violation_variable_names"])
    assert legacy_summary["joint.day.am1_pm1_mutex"]["operations"] == {
        "Add": len(bridge.problem.constraints),
        "NewBoolVar": len(metadata["teacher_day_slot_presence_variable_names"])
        + len(metadata["violation_variable_names"]),
    }


def test_generic_scheduler_rule_ids_exposes_real_day_am1_pm1_mutex_coverage() -> None:
    covered_rule_ids = generic_scheduler_rule_ids()

    assert "day.am1_pm1_mutex" in covered_rule_ids
    assert "joint.day.am1_pm1_mutex" in covered_rule_ids


def test_day_am1_pm1_exclusive_generic_contract_matches_legacy_hard_shape() -> None:
    data = _am1_pm1_mutex_day_input()

    bridge = day_am1_pm1_exclusive_to_ai_or_problem(data)

    assert bridge.problem.problem_id == "scheduler_day_am1_pm1_exclusive"
    assert tuple(rule.rule_id for rule in bridge.problem.rules) == ("joint.day.am1_pm1_exclusive",)
    metadata = bridge.metadata_by_rule["joint.day.am1_pm1_exclusive"]
    assert metadata["generic_contract_status"] == "covered_by_generic_contract"
    assert metadata["legacy_apply_fn"] == "apply_am1_pm1_exclusive"
    assert metadata["constraint_family_counts"] == {
        "presence_fixed_one": 1,
        "presence_lower_bounds": 4,
        "presence_implies": 6,
        "presence_zero": 1,
        "teacher_day_am1_pm1_mutex": 3,
        "violation_upper_bounds": 0,
        "violation_lower_bounds": 0,
    }
    assert len(metadata["teacher_day_slot_presence_variable_names"]) == 6
    assert len(bridge.problem.constraints) == 15

    legacy_model = create_existing_cp_model("day.am1_pm1_exclusive.parity")
    legacy_vars = build_day_variables(legacy_model, data)
    with ai_or_model_rule_context(
        "joint.day.am1_pm1_exclusive",
        source="scheduler.model.constraints.day_weekday_constraints",
    ):
        apply_am1_pm1_exclusive(legacy_model, data, legacy_vars, mode="hard")
    legacy_summary = summarize_existing_cp_model_operations_by_rule(legacy_model)
    assert legacy_summary["joint.day.am1_pm1_exclusive"]["operations"] == {
        "Add": len(bridge.problem.constraints),
        "NewBoolVar": len(metadata["teacher_day_slot_presence_variable_names"]),
    }

    solution = solve_cp_sat_problem(bridge.problem, time_limit_seconds=5)

    assert solution.status_name == "OPTIMAL"
    assignment_names = metadata["assignment_variable_names"]
    assert solution.values[assignment_names["class_b|history|星期一|上午1"]] == 0


def test_day_am1_pm1_exclusive_generic_contract_models_soft_objective() -> None:
    data = _am1_pm1_mutex_day_input()

    bridge = day_am1_pm1_exclusive_to_ai_or_problem(data, mode="soft", weight=13)

    metadata = bridge.metadata_by_rule["joint.day.am1_pm1_exclusive"]
    assert bridge.problem.objective is not None
    assert bridge.problem.objective.rule_id == "joint.day.am1_pm1_exclusive"
    assert {term.coefficient for term in bridge.problem.objective.expression.terms} == {13}
    assert metadata["constraint_family_counts"]["violation_upper_bounds"] == 6
    assert metadata["constraint_family_counts"]["violation_lower_bounds"] == 3
    assert len(metadata["violation_variable_names"]) == 3

    legacy_model = create_existing_cp_model("day.am1_pm1_exclusive.soft.parity")
    legacy_vars = build_day_variables(legacy_model, data)
    with ai_or_model_rule_context(
        "joint.day.am1_pm1_exclusive",
        source="scheduler.model.constraints.day_weekday_constraints",
    ):
        penalties = apply_am1_pm1_exclusive(legacy_model, data, legacy_vars, mode="soft", weight=13)
    legacy_summary = summarize_existing_cp_model_operations_by_rule(legacy_model)
    assert len(penalties) == len(metadata["violation_variable_names"])
    assert legacy_summary["joint.day.am1_pm1_exclusive"]["operations"] == {
        "Add": len(bridge.problem.constraints),
        "NewBoolVar": len(metadata["teacher_day_slot_presence_variable_names"])
        + len(metadata["violation_variable_names"]),
    }


def test_generic_scheduler_rule_ids_exposes_real_day_am1_pm1_exclusive_coverage() -> None:
    covered_rule_ids = generic_scheduler_rule_ids()

    assert "day.am1_pm1_exclusive" in covered_rule_ids
    assert "joint.day.am1_pm1_exclusive" in covered_rule_ids


def _single_class_weekly_am1_cap_day_input() -> DayInputData:
    mon_am1 = Slot(day="星期一", block="上午", period=1)
    mon_am2 = Slot(day="星期一", block="上午", period=2)
    tue_am1 = Slot(day="星期二", block="上午", period=1)
    sun_am1 = Slot(day="星期日", block="上午", period=1)
    return DayInputData(
        classes=["class_a", "class_b", "class_c"],
        cls_subj_teacher={
            ("class_a", "math"): "teacher_single",
            ("class_a", "science"): "teacher_single",
            ("class_b", "history"): "teacher_double",
            ("class_c", "history"): "teacher_double",
            ("class_b", "art"): "teacher_fixed",
        },
        available_slots=[mon_am1, mon_am2, tue_am1, sun_am1],
        fixed_assign={("class_b", sun_am1): "art"},
        req_hours={
            ("class_a", "math"): (0, 1, 1),
            ("class_a", "science"): (0, 1, 1),
            ("class_b", "history"): (0, 1, 1),
            ("class_c", "history"): (0, 1, 1),
            ("class_b", "art"): (0, 1, 1),
        },
        subject_ban_slots={},
    )


def test_day_single_class_weekly_am1_cap_generic_contract_matches_legacy_shape() -> None:
    data = _single_class_weekly_am1_cap_day_input()

    bridge = day_single_class_weekly_am1_cap_to_ai_or_problem(data, max_occurrences=1)

    assert bridge.problem.problem_id == "scheduler_day_single_class_weekly_am1_cap"
    assert tuple(rule.rule_id for rule in bridge.problem.rules) == ("joint.day.single_class_weekly_am1_cap",)
    metadata = bridge.metadata_by_rule["joint.day.single_class_weekly_am1_cap"]
    assert metadata["generic_contract_status"] == "covered_by_generic_contract"
    assert metadata["legacy_apply_fn"] == "apply_single_class_weekly_am1_cap"
    assert metadata["single_class_teachers"] == ("teacher_fixed", "teacher_single")
    assert metadata["active_days"] == ("星期一", "星期二", "星期日")
    assert metadata["constraint_family_counts"] == {
        "presence_fixed_one": 1,
        "presence_lower_bounds": 8,
        "presence_implies": 13,
        "presence_zero": 0,
        "weekly_count_equalities": 2,
        "weekly_count_caps": 2,
    }
    assert len(metadata["teacher_day_presence_variable_names"]) == 9
    assert len(metadata["weekly_count_variable_names"]) == 2
    assert len(bridge.problem.constraints) == 26

    legacy_model = create_existing_cp_model("day.single_class_weekly_am1_cap.parity")
    legacy_vars = build_day_variables(legacy_model, data)
    with ai_or_model_rule_context(
        "joint.day.single_class_weekly_am1_cap",
        source="scheduler.model.constraints.day_weekday_constraints",
    ):
        apply_single_class_weekly_am1_cap(legacy_model, data, legacy_vars, max_occurrences=1)
    legacy_summary = summarize_existing_cp_model_operations_by_rule(legacy_model)
    assert legacy_summary["joint.day.single_class_weekly_am1_cap"]["operations"] == {
        "Add": len(bridge.problem.constraints),
        "NewBoolVar": len(metadata["teacher_day_presence_variable_names"]),
        "NewIntVar": len(metadata["weekly_count_variable_names"]),
    }

    solution = solve_cp_sat_problem(bridge.problem, time_limit_seconds=5)

    assert solution.status_name == "OPTIMAL"
    weekly_names = metadata["weekly_count_variable_names"]
    assert solution.values[weekly_names["teacher_fixed"]] <= 1
    assert solution.values[weekly_names["teacher_single"]] <= 1


def test_generic_scheduler_rule_ids_exposes_real_day_single_class_weekly_am1_cap_coverage() -> None:
    covered_rule_ids = generic_scheduler_rule_ids()

    assert "day.single_class_weekly_am1_cap" in covered_rule_ids
    assert "joint.day.single_class_weekly_am1_cap" in covered_rule_ids


def _two_class_am1_pm1_combo_day_input() -> DayInputData:
    am1 = Slot(day="星期一", block="上午", period=1)
    am2 = Slot(day="星期一", block="上午", period=2)
    pm1 = Slot(day="星期一", block="下午", period=1)
    pm2 = Slot(day="星期一", block="下午", period=2)
    weekend = Slot(day="星期六", block="上午", period=1)
    return DayInputData(
        classes=["class_a", "class_b", "class_c"],
        cls_subj_teacher={
            ("class_a", "math"): "teacher_two",
            ("class_b", "math"): "teacher_two",
            ("class_c", "science"): "teacher_one",
            ("class_a", "体育"): "pe_subject_teacher",
            ("class_b", "history"): "pe_param_teacher",
            ("class_c", "history"): "pe_param_teacher",
        },
        available_slots=[am1, am2, pm1, pm2, weekend],
        fixed_assign={
            ("class_a", am2): "math",
            ("class_b", pm1): "math",
        },
        req_hours={
            ("class_a", "math"): (0, 2, 1),
            ("class_b", "math"): (0, 2, 1),
            ("class_c", "science"): (0, 1, 1),
            ("class_a", "体育"): (0, 1, 0),
            ("class_b", "history"): (0, 1, 0),
            ("class_c", "history"): (0, 1, 0),
        },
        subject_ban_slots={},
    )


def test_day_two_class_am1_pm1_combo_generic_contract_matches_legacy_hard_semantics() -> None:
    data = _two_class_am1_pm1_combo_day_input()
    pe_teachers = {"pe_param_teacher"}

    bridge = day_two_class_am1_pm1_combo_to_ai_or_problem(data, pe_teachers=pe_teachers)

    assert bridge.problem.problem_id == "scheduler_day_two_class_am1_pm1_combo"
    assert tuple(rule.rule_id for rule in bridge.problem.rules) == ("joint.day.two_class_am1_pm1_combo",)
    metadata = bridge.metadata_by_rule["joint.day.two_class_am1_pm1_combo"]
    assert metadata["generic_contract_status"] == "covered_by_generic_contract"
    assert metadata["two_class_teachers"] == ("teacher_two",)
    assert metadata["pe_teachers"] == ("pe_param_teacher",)
    assert metadata["constraint_family_counts"] == {
        "teacher_day_count_equalities": 10,
        "teacher_day_hard_forbidden_combos": 5,
        "teacher_day_soft_allowed_violation_maps": 0,
    }
    assert len(metadata["teacher_day_count_variable_names"]) == 10
    assert metadata["fixed_count_constants"]["teacher_two|星期一|am"] == 1
    assert metadata["fixed_count_constants"]["teacher_two|星期一|pm"] == 1

    legacy_model = create_existing_cp_model("day.two_class_am1_pm1_combo.parity")
    legacy_vars = build_day_variables(legacy_model, data)
    with ai_or_model_rule_context(
        "joint.day.two_class_am1_pm1_combo",
        source="scheduler.model.constraints.day_weekday_constraints",
    ):
        apply_two_class_am1_pm1_combo(legacy_model, data, legacy_vars, pe_teachers, mode="hard")
    legacy_summary = summarize_existing_cp_model_operations_by_rule(legacy_model)
    assert legacy_summary["joint.day.two_class_am1_pm1_combo"]["operations"] == {
        "Add": 50,
        "NewBoolVar": 15,
        "NewIntVar": 10,
    }

    solution = solve_cp_sat_problem(bridge.problem, time_limit_seconds=5)

    assert solution.status_name == "OPTIMAL"
    count_names = metadata["teacher_day_count_variable_names"]
    assert not (
        solution.values[count_names["teacher_two|星期一|am"]] == 1
        and solution.values[count_names["teacher_two|星期一|pm"]] == 1
    )


def test_day_two_class_am1_pm1_combo_generic_contract_models_soft_objective() -> None:
    data = _two_class_am1_pm1_combo_day_input()
    pe_teachers = {"pe_param_teacher"}

    bridge = day_two_class_am1_pm1_combo_to_ai_or_problem(
        data,
        pe_teachers=pe_teachers,
        mode="soft",
        weight=11,
    )

    metadata = bridge.metadata_by_rule["joint.day.two_class_am1_pm1_combo"]
    assert bridge.problem.objective is not None
    assert bridge.problem.objective.rule_id == "joint.day.two_class_am1_pm1_combo"
    assert {term.coefficient for term in bridge.problem.objective.expression.terms} == {11}
    assert metadata["constraint_family_counts"] == {
        "teacher_day_count_equalities": 10,
        "teacher_day_hard_forbidden_combos": 0,
        "teacher_day_soft_allowed_violation_maps": 5,
    }
    assert len(metadata["violation_variable_names"]) == 5

    legacy_model = create_existing_cp_model("day.two_class_am1_pm1_combo.soft.parity")
    legacy_vars = build_day_variables(legacy_model, data)
    with ai_or_model_rule_context(
        "joint.day.two_class_am1_pm1_combo",
        source="scheduler.model.constraints.day_weekday_constraints",
    ):
        penalties = apply_two_class_am1_pm1_combo(legacy_model, data, legacy_vars, pe_teachers, mode="soft", weight=11)
    legacy_summary = summarize_existing_cp_model_operations_by_rule(legacy_model)
    assert len(penalties) == len(metadata["violation_variable_names"])
    assert legacy_summary["joint.day.two_class_am1_pm1_combo"]["operations"] == {
        "Add": 45,
        "NewBoolVar": 15,
        "NewIntVar": 10,
    }


def test_generic_scheduler_rule_ids_exposes_real_day_two_class_am1_pm1_combo_coverage() -> None:
    covered_rule_ids = generic_scheduler_rule_ids()

    assert "day.two_class_am1_pm1_combo" in covered_rule_ids
    assert "joint.day.two_class_am1_pm1_combo" in covered_rule_ids


def _two_class_low_hours_max_empty_days_day_input() -> DayInputData:
    mon_am1 = Slot(day="星期一", block="上午", period=1)
    tue_am1 = Slot(day="星期二", block="上午", period=1)
    wed_pm1 = Slot(day="星期三", block="下午", period=1)
    thu_am1 = Slot(day="星期四", block="上午", period=1)
    weekend = Slot(day="星期六", block="上午", period=1)
    return DayInputData(
        classes=["class_a", "class_b", "class_c", "class_d", "class_e"],
        cls_subj_teacher={
            ("class_a", "math"): "teacher_low",
            ("class_b", "math"): "teacher_low",
            ("class_c", "history"): "teacher_high",
            ("class_d", "history"): "teacher_high",
            ("class_e", "art"): "teacher_pe_param",
            ("class_a", "体育"): "pe_subject_teacher",
        },
        available_slots=[mon_am1, tue_am1, wed_pm1, thu_am1, weekend],
        fixed_assign={("class_a", mon_am1): "math"},
        req_hours={
            ("class_a", "math"): (0, 2, 1),
            ("class_b", "math"): (0, 2, 1),
            ("class_c", "history"): (0, 3, 1),
            ("class_d", "history"): (0, 3, 1),
            ("class_e", "art"): (0, 2, 1),
            ("class_a", "体育"): (0, 1, 1),
        },
        subject_ban_slots={},
    )


def test_day_two_class_low_hours_max_empty_days_generic_contract_matches_legacy_shape() -> None:
    data = _two_class_low_hours_max_empty_days_day_input()
    pe_teachers = {"teacher_pe_param"}

    bridge = day_two_class_low_hours_max_empty_days_to_ai_or_problem(
        data,
        pe_teachers=pe_teachers,
        threshold=5,
        max_empty_days=1,
    )

    assert bridge.problem.problem_id == "scheduler_day_two_class_low_hours_max_empty_days"
    assert tuple(rule.rule_id for rule in bridge.problem.rules) == ("joint.day.two_class_low_hours_max_empty_days",)
    metadata = bridge.metadata_by_rule["joint.day.two_class_low_hours_max_empty_days"]
    assert metadata["generic_contract_status"] == "covered_by_generic_contract"
    assert metadata["legacy_apply_fn"] == "apply_two_class_low_hours_max_empty_days"
    assert metadata["two_class_low_hour_teachers"] == ("teacher_low",)
    assert metadata["constraint_family_counts"] == {
        "has_any_fixed_one": 1,
        "has_any_lower_bounds": 3,
        "has_any_implies": 6,
        "has_any_zero": 1,
        "empty_complements": 5,
        "empty_day_caps": 1,
    }
    assert len(metadata["has_any_variable_names"]) == 5
    assert len(metadata["empty_variable_names"]) == 5
    assert len(bridge.problem.constraints) == 17

    legacy_model = create_existing_cp_model("day.two_class_low_hours_max_empty_days.parity")
    legacy_vars = build_day_variables(legacy_model, data)
    with ai_or_model_rule_context(
        "joint.day.two_class_low_hours_max_empty_days",
        source="scheduler.model.constraints.day_weekday_constraints",
    ):
        apply_two_class_low_hours_max_empty_days(
            legacy_model,
            data,
            legacy_vars,
            pe_teachers,
            threshold=5,
            max_empty_days=1,
        )
    legacy_summary = summarize_existing_cp_model_operations_by_rule(legacy_model)
    assert legacy_summary["joint.day.two_class_low_hours_max_empty_days"]["operations"] == {
        "Add": len(bridge.problem.constraints),
        "NewBoolVar": len(metadata["has_any_variable_names"]) + len(metadata["empty_variable_names"]),
    }

    solution = solve_cp_sat_problem(bridge.problem, time_limit_seconds=5)

    assert solution.status_name == "OPTIMAL"
    empty_names = metadata["empty_variable_names"]
    assert sum(solution.values[name] for name in empty_names.values()) <= 1


def test_generic_scheduler_rule_ids_exposes_real_day_two_class_low_hours_coverage() -> None:
    covered_rule_ids = generic_scheduler_rule_ids()

    assert "joint.day.two_class_low_hours_max_empty_days" in covered_rule_ids


def _low_weekday_subject_max1_day_input() -> DayInputData:
    mon_am1 = Slot(day="星期一", block="上午", period=1)
    mon_pm1 = Slot(day="星期一", block="下午", period=1)
    tue_am1 = Slot(day="星期二", block="上午", period=1)
    wed_am1 = Slot(day="星期三", block="上午", period=1)
    thu_am1 = Slot(day="星期四", block="上午", period=1)
    fri_am1 = Slot(day="星期五", block="上午", period=1)
    weekend = Slot(day="星期六", block="上午", period=1)
    return DayInputData(
        classes=["class_a"],
        cls_subj_teacher={
            ("class_a", "art"): "teacher_low",
            ("class_a", "math"): "teacher_high",
        },
        available_slots=[mon_am1, mon_pm1, tue_am1, wed_am1, thu_am1, fri_am1, weekend],
        fixed_assign={("class_a", mon_am1): "art"},
        req_hours={
            ("class_a", "art"): (0, 4, 1),
            ("class_a", "math"): (0, 5, 1),
        },
        subject_ban_slots={},
    )


def test_day_low_weekday_subject_max1_generic_contract_matches_legacy_shape() -> None:
    data = _low_weekday_subject_max1_day_input()

    bridge = day_low_weekday_subject_max1_per_day_to_ai_or_problem(data, max_weekday_hours=4)

    assert bridge.problem.problem_id == "scheduler_day_low_weekday_subject_max1_per_day"
    assert tuple(rule.rule_id for rule in bridge.problem.rules) == ("joint.day.low_weekday_subject_max1_per_day",)
    metadata = bridge.metadata_by_rule["joint.day.low_weekday_subject_max1_per_day"]
    assert metadata["generic_contract_status"] == "covered_by_generic_contract"
    assert metadata["legacy_apply_fn"] == "apply_low_weekday_subject_max1_per_day"
    assert metadata["target_class_subjects"] == ("class_a|art",)
    assert metadata["constraint_family_counts"] == {"low_subject_daily_max_constraints": 5}
    assert metadata["fixed_count_constants"]["class_a|art|星期一"] == 1
    assert len(bridge.problem.constraints) == 5

    legacy_model = create_existing_cp_model("day.low_weekday_subject_max1.parity")
    legacy_vars = build_day_variables(legacy_model, data)
    with ai_or_model_rule_context(
        "joint.day.low_weekday_subject_max1_per_day",
        source="scheduler.model.constraints.day_weekday_constraints",
    ):
        apply_low_weekday_subject_max1_per_day(legacy_model, data, legacy_vars, max_weekday_hours=4)
    legacy_summary = summarize_existing_cp_model_operations_by_rule(legacy_model)
    assert legacy_summary["joint.day.low_weekday_subject_max1_per_day"]["operations"] == {
        "Add": len(bridge.problem.constraints),
    }

    solution = solve_cp_sat_problem(bridge.problem, time_limit_seconds=5)

    assert solution.status_name == "OPTIMAL"
    assignment_names = metadata["assignment_variable_names"]
    assert solution.values[assignment_names["class_a|art|星期一|下午1"]] == 0


def test_generic_scheduler_rule_ids_exposes_real_day_low_weekday_subject_coverage() -> None:
    covered_rule_ids = generic_scheduler_rule_ids()

    assert "joint.day.low_weekday_subject_max1_per_day" in covered_rule_ids


def _high_weekday_subject_min1_day_input() -> DayInputData:
    mon_am1 = Slot(day="星期一", block="上午", period=1)
    tue_am1 = Slot(day="星期二", block="上午", period=1)
    tue_pm1 = Slot(day="星期二", block="下午", period=1)
    wed_am1 = Slot(day="星期三", block="上午", period=1)
    thu_am1 = Slot(day="星期四", block="上午", period=1)
    fri_am1 = Slot(day="星期五", block="上午", period=1)
    weekend = Slot(day="星期六", block="上午", period=1)
    return DayInputData(
        classes=["class_a"],
        cls_subj_teacher={
            ("class_a", "math"): "teacher_high",
            ("class_a", "art"): "teacher_low",
        },
        available_slots=[mon_am1, tue_am1, tue_pm1, wed_am1, thu_am1, fri_am1, weekend],
        fixed_assign={("class_a", tue_am1): "math"},
        req_hours={
            ("class_a", "math"): (0, 5, 1),
            ("class_a", "art"): (0, 4, 1),
        },
        subject_ban_slots={},
    )


def test_day_high_weekday_subject_min1_generic_contract_matches_legacy_shape() -> None:
    data = _high_weekday_subject_min1_day_input()

    bridge = day_high_weekday_subject_min1_per_day_to_ai_or_problem(data, min_weekday_hours=5)

    assert bridge.problem.problem_id == "scheduler_day_high_weekday_subject_min1_per_day"
    assert tuple(rule.rule_id for rule in bridge.problem.rules) == ("joint.day.high_weekday_subject_min1_per_day",)
    metadata = bridge.metadata_by_rule["joint.day.high_weekday_subject_min1_per_day"]
    assert metadata["generic_contract_status"] == "covered_by_generic_contract"
    assert metadata["legacy_apply_fn"] == "apply_high_weekday_subject_min1_per_day"
    assert metadata["target_class_subjects"] == ("class_a|math",)
    assert metadata["constraint_family_counts"] == {"high_subject_daily_min_constraints": 5}
    assert metadata["fixed_count_constants"]["class_a|math|星期二"] == 1
    assert len(bridge.problem.constraints) == 5

    legacy_model = create_existing_cp_model("day.high_weekday_subject_min1.parity")
    legacy_vars = build_day_variables(legacy_model, data)
    with ai_or_model_rule_context(
        "joint.day.high_weekday_subject_min1_per_day",
        source="scheduler.model.constraints.day_weekday_constraints",
    ):
        apply_high_weekday_subject_min1_per_day(legacy_model, data, legacy_vars, min_weekday_hours=5)
    legacy_summary = summarize_existing_cp_model_operations_by_rule(legacy_model)
    assert legacy_summary["joint.day.high_weekday_subject_min1_per_day"]["operations"] == {
        "Add": len(bridge.problem.constraints),
    }

    solution = solve_cp_sat_problem(bridge.problem, time_limit_seconds=5)

    assert solution.status_name == "OPTIMAL"
    assignment_names = metadata["assignment_variable_names"]
    for key in (
        "class_a|math|星期一|上午1",
        "class_a|math|星期三|上午1",
        "class_a|math|星期四|上午1",
        "class_a|math|星期五|上午1",
    ):
        assert solution.values[assignment_names[key]] == 1


def test_generic_scheduler_rule_ids_exposes_real_day_high_weekday_subject_coverage() -> None:
    covered_rule_ids = generic_scheduler_rule_ids()

    assert "joint.day.high_weekday_subject_min1_per_day" in covered_rule_ids


def _pe_time_window_day_input() -> DayInputData:
    mon_am1 = Slot(day="星期一", block="上午", period=1)
    mon_pm1 = Slot(day="星期一", block="下午", period=1)
    wed_am4 = Slot(day="星期三", block="上午", period=4)
    sat_am1 = Slot(day="星期六", block="上午", period=1)
    return DayInputData(
        classes=["class_a", "class_b"],
        cls_subj_teacher={
            ("class_a", "体育"): "pe_teacher",
            ("class_a", "math"): "math_teacher",
            ("class_b", "体育"): "pe_teacher_fixed",
        },
        available_slots=[mon_am1, mon_pm1, wed_am4, sat_am1],
        fixed_assign={("class_b", mon_am1): "体育"},
        req_hours={
            ("class_a", "体育"): (0, 2, 1),
            ("class_a", "math"): (0, 2, 1),
            ("class_b", "体育"): (0, 2, 1),
        },
        subject_ban_slots={},
    )


def test_day_pe_time_window_hard_generic_contract_matches_legacy_shape() -> None:
    data = _pe_time_window_day_input()

    bridge = day_pe_time_window_hard_to_ai_or_problem(data)

    assert bridge.problem.problem_id == "scheduler_day_pe_time_window_hard"
    assert tuple(rule.rule_id for rule in bridge.problem.rules) == ("joint.day.pe_time_window_hard",)
    metadata = bridge.metadata_by_rule["joint.day.pe_time_window_hard"]
    assert metadata["generic_contract_status"] == "covered_by_generic_contract"
    assert metadata["legacy_apply_fn"] == "apply_pe_time_window_hard"
    assert metadata["constraint_family_counts"] == {"pe_illegal_time_window_zeroes": 3}
    assert metadata["illegal_fixed_count"] == 1
    assert len(bridge.problem.constraints) == 3

    legacy_model = create_existing_cp_model("day.pe_time_window.parity")
    legacy_vars = build_day_variables(legacy_model, data)
    with ai_or_model_rule_context(
        "joint.day.pe_time_window_hard",
        source="scheduler.model.constraints.day_pe_tech_constraints",
    ):
        illegal_fixed = apply_pe_time_window_hard(legacy_model, data, legacy_vars)
    legacy_summary = summarize_existing_cp_model_operations_by_rule(legacy_model)
    assert illegal_fixed == metadata["illegal_fixed_count"]
    assert legacy_summary["joint.day.pe_time_window_hard"]["operations"] == {
        "Add": len(bridge.problem.constraints),
    }

    solution = solve_cp_sat_problem(bridge.problem, time_limit_seconds=5)

    assert solution.status_name == "OPTIMAL"
    assignment_names = metadata["assignment_variable_names"]
    for key in (
        "class_a|体育|星期一|上午1",
        "class_a|体育|星期六|上午1",
        "class_b|体育|星期六|上午1",
    ):
        assert solution.values[assignment_names[key]] == 0


def test_generic_scheduler_rule_ids_exposes_real_day_pe_time_window_coverage() -> None:
    covered_rule_ids = generic_scheduler_rule_ids()

    assert "joint.day.pe_time_window_hard" in covered_rule_ids


def _teacher_whitelist_day_input() -> DayInputData:
    mon_am1 = Slot(day="星期一", block="上午", period=1)
    mon_pm1 = Slot(day="星期一", block="下午", period=1)
    tue_pm1 = Slot(day="星期二", block="下午", period=1)
    return DayInputData(
        classes=["class_a", "class_b"],
        cls_subj_teacher={
            ("class_a", "体育"): "coach_1",
            ("class_a", "技术"): "coach_1",
            ("class_b", "体育"): "coach_fixed",
            ("class_b", "math"): "math_teacher",
        },
        available_slots=[mon_am1, mon_pm1, tue_pm1],
        fixed_assign={("class_b", tue_pm1): "体育"},
        req_hours={
            ("class_a", "体育"): (0, 2, 0),
            ("class_a", "技术"): (0, 1, 0),
            ("class_b", "体育"): (0, 2, 0),
            ("class_b", "math"): (0, 2, 0),
        },
        subject_ban_slots={},
    )


def test_day_teacher_whitelist_hard_generic_contract_matches_legacy_shape() -> None:
    data = _teacher_whitelist_day_input()
    allowed = {("星期一", "下午1")}

    bridge = day_teacher_whitelist_hard_to_ai_or_problem(data, teacher_name="coach_1", allowed=allowed)

    assert bridge.problem.problem_id == "scheduler_day_teacher_whitelist_hard"
    assert tuple(rule.rule_id for rule in bridge.problem.rules) == ("joint.day.teacher_whitelist_hard",)
    metadata = bridge.metadata_by_rule["joint.day.teacher_whitelist_hard"]
    assert metadata["generic_contract_status"] == "covered_by_generic_contract"
    assert metadata["legacy_apply_fn"] == "apply_teacher_whitelist_hard"
    assert metadata["teacher_name"] == "coach_1"
    assert metadata["allowed_slots"] == ("星期一|下午1",)
    assert metadata["constraint_family_counts"] == {"teacher_whitelist_illegal_zeroes": 4}
    assert metadata["illegal_fixed_count"] == 0
    assert len(bridge.problem.constraints) == 4

    legacy_model = create_existing_cp_model("day.teacher_whitelist.parity")
    legacy_vars = build_day_variables(legacy_model, data)
    with ai_or_model_rule_context(
        "joint.day.teacher_whitelist_hard",
        source="scheduler.model.constraints.day_pe_tech_constraints",
    ):
        illegal_fixed = apply_teacher_whitelist_hard(legacy_model, data, legacy_vars, "coach_1", allowed)
    legacy_summary = summarize_existing_cp_model_operations_by_rule(legacy_model)
    assert illegal_fixed == metadata["illegal_fixed_count"]
    assert legacy_summary["joint.day.teacher_whitelist_hard"]["operations"] == {
        "Add": len(bridge.problem.constraints),
    }

    solution = solve_cp_sat_problem(bridge.problem, time_limit_seconds=5)

    assert solution.status_name == "OPTIMAL"
    assignment_names = metadata["assignment_variable_names"]
    for key in (
        "class_a|体育|星期一|上午1",
        "class_a|技术|星期一|上午1",
        "class_a|体育|星期二|下午1",
        "class_a|技术|星期二|下午1",
    ):
        assert solution.values[assignment_names[key]] == 0


def test_generic_scheduler_rule_ids_exposes_real_day_teacher_whitelist_coverage() -> None:
    covered_rule_ids = generic_scheduler_rule_ids()

    assert "joint.day.teacher_whitelist_hard" in covered_rule_ids


def _soft_preference_day_input() -> DayInputData:
    mon_am1 = Slot(day="星期一", block="上午", period=1)
    mon_am2 = Slot(day="星期一", block="上午", period=2)
    mon_pm1 = Slot(day="星期一", block="下午", period=1)
    tue_am1 = Slot(day="星期二", block="上午", period=1)
    sat_am1 = Slot(day="星期六", block="上午", period=1)
    return DayInputData(
        classes=["class_a", "class_b"],
        cls_subj_teacher={
            ("class_a", "体育"): "pe_teacher",
            ("class_a", "数学"): "math_teacher",
            ("class_a", "化学"): "chem_teacher",
            ("class_b", "技术"): "tech_teacher",
            ("class_b", "物理"): "physics_teacher",
        },
        available_slots=[mon_am1, mon_am2, mon_pm1, tue_am1, sat_am1],
        fixed_assign={("class_b", tue_am1): "物理"},
        req_hours={
            ("class_a", "体育"): (0, 3, 1),
            ("class_a", "数学"): (0, 2, 1),
            ("class_a", "化学"): (0, 2, 1),
            ("class_b", "技术"): (0, 2, 1),
            ("class_b", "物理"): (0, 2, 1),
        },
        subject_ban_slots={},
    )


def test_day_reduce_stem_am1_generic_contract_matches_legacy_soft_terms() -> None:
    data = _soft_preference_day_input()

    bridge = day_reduce_stem_am1_to_ai_or_problem(data, weight=37)

    assert bridge.problem.problem_id == "scheduler_day_reduce_stem_am1"
    assert tuple(rule.rule_id for rule in bridge.problem.rules) == ("joint.day.reduce_stem_am1",)
    assert bridge.problem.objective is not None
    assert bridge.problem.objective.rule_id == "joint.day.reduce_stem_am1"
    metadata = bridge.metadata_by_rule["joint.day.reduce_stem_am1"]
    assert metadata["generic_contract_status"] == "covered_by_generic_contract"
    assert metadata["legacy_apply_fn"] == "apply_reduce_stem_am1"
    assert metadata["constraint_family_counts"] == {"stem_am1_penalty_terms": 5}
    assert metadata["fixed_penalty_count"] == 1
    assert metadata["weight"] == 37
    assert len(bridge.problem.constraints) == 0

    legacy_model = create_existing_cp_model("day.reduce_stem_am1.parity")
    legacy_vars = build_day_variables(legacy_model, data)
    with ai_or_model_rule_context(
        "joint.day.reduce_stem_am1",
        source="scheduler.model.constraints.day_weekday_constraints",
    ):
        legacy_penalties, legacy_fixed = apply_reduce_stem_am1(legacy_model, data, legacy_vars, weight=37)
    assert len(legacy_penalties) == metadata["constraint_family_counts"]["stem_am1_penalty_terms"]
    assert legacy_fixed == metadata["fixed_penalty_count"]

    assignment_names = metadata["assignment_variable_names"]
    expected_terms = {
        assignment_names["class_a|数学|星期一|上午1"],
        assignment_names["class_a|化学|星期一|上午1"],
        assignment_names["class_a|数学|星期二|上午1"],
        assignment_names["class_a|化学|星期二|上午1"],
        assignment_names["class_b|物理|星期一|上午1"],
    }
    assert set(metadata["penalty_variable_names"]) == expected_terms
    assert {
        (term.variable, term.coefficient)
        for term in bridge.problem.objective.expression.terms
    } == {(name, 37) for name in expected_terms}

    solution = solve_cp_sat_problem(bridge.problem, time_limit_seconds=5)

    assert solution.status_name == "OPTIMAL"
    assert all(solution.values[name] == 0 for name in expected_terms)


def test_generic_scheduler_rule_ids_exposes_real_day_reduce_stem_am1_coverage() -> None:
    covered_rule_ids = generic_scheduler_rule_ids()

    assert "joint.day.reduce_stem_am1" in covered_rule_ids


def test_day_pe_reduce_am_soft_generic_contract_matches_legacy_soft_terms() -> None:
    data = _soft_preference_day_input()

    bridge = day_pe_reduce_am_soft_to_ai_or_problem(data, pe_teachers={"pe_teacher"}, weight=41)

    assert bridge.problem.problem_id == "scheduler_day_pe_reduce_am_soft"
    assert tuple(rule.rule_id for rule in bridge.problem.rules) == ("joint.day.pe_reduce_am_soft",)
    assert bridge.problem.objective is not None
    assert bridge.problem.objective.rule_id == "joint.day.pe_reduce_am_soft"
    metadata = bridge.metadata_by_rule["joint.day.pe_reduce_am_soft"]
    assert metadata["generic_contract_status"] == "covered_by_generic_contract"
    assert metadata["legacy_apply_fn"] == "apply_pe_reduce_am_soft"
    assert metadata["constraint_family_counts"] == {"pe_weekday_morning_penalty_terms": 3}
    assert metadata["pe_teachers"] == ("pe_teacher",)
    assert metadata["weight"] == 41
    assert len(bridge.problem.constraints) == 0

    legacy_model = create_existing_cp_model("day.pe_reduce_am_soft.parity")
    legacy_vars = build_day_variables(legacy_model, data)
    with ai_or_model_rule_context(
        "joint.day.pe_reduce_am_soft",
        source="scheduler.model.constraints.day_pe_tech_constraints",
    ):
        legacy_penalties = apply_pe_reduce_am_soft(data, legacy_vars, {"pe_teacher"})
    assert len(legacy_penalties) == metadata["constraint_family_counts"]["pe_weekday_morning_penalty_terms"]

    assignment_names = metadata["assignment_variable_names"]
    expected_terms = {
        assignment_names["class_a|体育|星期一|上午1"],
        assignment_names["class_a|体育|星期一|上午2"],
        assignment_names["class_a|体育|星期二|上午1"],
    }
    assert set(metadata["penalty_variable_names"]) == expected_terms
    assert {
        (term.variable, term.coefficient)
        for term in bridge.problem.objective.expression.terms
    } == {(name, 41) for name in expected_terms}

    solution = solve_cp_sat_problem(bridge.problem, time_limit_seconds=5)

    assert solution.status_name == "OPTIMAL"
    assert all(solution.values[name] == 0 for name in expected_terms)


def test_generic_scheduler_rule_ids_exposes_real_day_pe_reduce_am_soft_coverage() -> None:
    covered_rule_ids = generic_scheduler_rule_ids()

    assert "joint.day.pe_reduce_am_soft" in covered_rule_ids


def _lang_preference_day_input() -> DayInputData:
    mon_am1 = Slot(day="星期一", block="上午", period=1)
    tue_am1 = Slot(day="星期二", block="上午", period=1)
    tue_pm1 = Slot(day="星期二", block="下午", period=1)
    wed_pm2 = Slot(day="星期三", block="下午", period=2)
    thu_pm3 = Slot(day="星期四", block="下午", period=3)
    sat_pm1 = Slot(day="星期六", block="下午", period=1)
    return DayInputData(
        classes=["class_a"],
        cls_subj_teacher={
            ("class_a", "语文"): "teacher_lang",
            ("class_a", "外语"): "teacher_other",
            ("class_a", "数学"): "math_teacher",
        },
        available_slots=[mon_am1, tue_am1, tue_pm1, wed_pm2, thu_pm3, sat_pm1],
        fixed_assign={},
        req_hours={
            ("class_a", "语文"): (0, 4, 1),
            ("class_a", "外语"): (0, 4, 1),
            ("class_a", "数学"): (0, 4, 1),
        },
        subject_ban_slots={},
    )


def test_day_pref_lang_am_generic_contract_matches_legacy_soft_terms() -> None:
    data = _lang_preference_day_input()

    bridge = day_pref_lang_am_to_ai_or_problem(
        data,
        target_teachers={"teacher_lang"},
        am1_reward=11,
        pm1_penalty=13,
        pm2_penalty=17,
        pm3_penalty=19,
    )

    assert bridge.problem.problem_id == "scheduler_day_pref_lang_am"
    assert tuple(rule.rule_id for rule in bridge.problem.rules) == ("joint.day.pref_lang_am",)
    assert bridge.problem.objective is not None
    metadata = bridge.metadata_by_rule["joint.day.pref_lang_am"]
    assert metadata["generic_contract_status"] == "covered_by_generic_contract"
    assert metadata["legacy_apply_fn"] == "apply_pref_lang_am"
    assert metadata["target_teachers"] == ("teacher_lang",)
    assert metadata["constraint_family_counts"] == {
        "lang_tue_fri_am1_reward_terms": 1,
        "lang_tue_fri_pm1_penalty_terms": 1,
        "lang_tue_fri_pm2_penalty_terms": 1,
        "lang_tue_fri_pm3_penalty_terms": 1,
    }
    assert len(bridge.problem.constraints) == 0

    legacy_model = create_existing_cp_model("day.pref_lang_am.parity")
    legacy_vars = build_day_variables(legacy_model, data)
    with ai_or_model_rule_context(
        "joint.day.pref_lang_am",
        source="scheduler.model.constraints.day_weekday_constraints",
    ):
        legacy_am1, legacy_pm1, legacy_pm2, legacy_pm3 = apply_pref_lang_am(
            legacy_model,
            data,
            legacy_vars,
            enabled=True,
            target_teachers={"teacher_lang"},
        )
    assert [len(legacy_am1), len(legacy_pm1), len(legacy_pm2), len(legacy_pm3)] == [1, 1, 1, 1]

    assignment_names = metadata["assignment_variable_names"]
    expected_coefficients = {
        assignment_names["class_a|语文|星期二|上午1"]: -11,
        assignment_names["class_a|语文|星期二|下午1"]: 13,
        assignment_names["class_a|语文|星期三|下午2"]: 17,
        assignment_names["class_a|语文|星期四|下午3"]: 19,
    }
    assert {
        (term.variable, term.coefficient)
        for term in bridge.problem.objective.expression.terms
    } == set(expected_coefficients.items())

    solution = solve_cp_sat_problem(bridge.problem, time_limit_seconds=5)

    assert solution.status_name == "OPTIMAL"
    assert solution.values[assignment_names["class_a|语文|星期二|上午1"]] == 1
    assert solution.values[assignment_names["class_a|语文|星期二|下午1"]] == 0


def test_generic_scheduler_rule_ids_exposes_real_day_pref_lang_am_coverage() -> None:
    covered_rule_ids = generic_scheduler_rule_ids()

    assert "joint.day.pref_lang_am" in covered_rule_ids


def _pe_tech_compact_day_input() -> DayInputData:
    mon_am1 = Slot(day="星期一", block="上午", period=1)
    mon_am2 = Slot(day="星期一", block="上午", period=2)
    mon_am3 = Slot(day="星期一", block="上午", period=3)
    mon_pm1 = Slot(day="星期一", block="下午", period=1)
    mon_pm2 = Slot(day="星期一", block="下午", period=2)
    return DayInputData(
        classes=["class_a", "class_b"],
        cls_subj_teacher={
            ("class_a", "体育"): "coach",
            ("class_a", "技术"): "coach",
            ("class_b", "体育"): "other_coach",
        },
        available_slots=[mon_am1, mon_am2, mon_am3, mon_pm1, mon_pm2],
        fixed_assign={},
        req_hours={
            ("class_a", "体育"): (0, 3, 0),
            ("class_a", "技术"): (0, 2, 0),
            ("class_b", "体育"): (0, 2, 0),
        },
        subject_ban_slots={},
    )


def test_day_pe_tech_compact_soft_generic_contract_matches_legacy_gap_shape() -> None:
    data = _pe_tech_compact_day_input()

    bridge = day_pe_tech_compact_soft_to_ai_or_problem(data, pe_tech_teachers={"coach"}, weight=23)

    assert bridge.problem.problem_id == "scheduler_day_pe_tech_compact_soft"
    assert tuple(rule.rule_id for rule in bridge.problem.rules) == ("joint.day.pe_tech_compact_soft",)
    assert bridge.problem.objective is not None
    metadata = bridge.metadata_by_rule["joint.day.pe_tech_compact_soft"]
    assert metadata["generic_contract_status"] == "covered_by_generic_contract"
    assert metadata["legacy_apply_fn"] == "apply_pe_tech_compact_soft"
    assert metadata["constraint_family_counts"] == {
        "pe_tech_busy_equalities": 5,
        "pe_tech_101_gap_constraints": 4,
        "pe_tech_adjacent_gap_constraints": 3,
        "pe_tech_gap_penalty_terms": 2,
    }
    assert len(metadata["busy_variable_names"]) == 5
    assert len(metadata["gap_variable_names"]) == 2
    assert len(bridge.problem.constraints) == 12

    legacy_model = create_existing_cp_model("day.pe_tech_compact.parity")
    legacy_vars = build_day_variables(legacy_model, data)
    with ai_or_model_rule_context(
        "joint.day.pe_tech_compact_soft",
        source="scheduler.model.constraints.day_pe_tech_constraints",
    ):
        legacy_penalties, legacy_details = apply_pe_tech_compact_soft(legacy_model, data, legacy_vars, {"coach"})
    legacy_summary = summarize_existing_cp_model_operations_by_rule(legacy_model)
    assert len(legacy_penalties) == metadata["constraint_family_counts"]["pe_tech_gap_penalty_terms"]
    assert set(legacy_details) == {("coach", "星期一", "AM"), ("coach", "星期一", "PM")}
    assert legacy_summary["joint.day.pe_tech_compact_soft"]["operations"] == {
        "Add": len(bridge.problem.constraints),
        "NewBoolVar": len(metadata["busy_variable_names"]) + len(metadata["gap_variable_names"]),
    }

    assert {
        (term.variable, term.coefficient)
        for term in bridge.problem.objective.expression.terms
    } == {(name, 23) for name in metadata["gap_variable_names"].values()}

    solution = solve_cp_sat_problem(bridge.problem, time_limit_seconds=5)

    assert solution.status_name == "OPTIMAL"
    assert all(solution.values[name] == 0 for name in metadata["gap_variable_names"].values())


def test_generic_scheduler_rule_ids_exposes_real_day_pe_tech_compact_soft_coverage() -> None:
    covered_rule_ids = generic_scheduler_rule_ids()

    assert "joint.day.pe_tech_compact_soft" in covered_rule_ids


def _teacher_am4_pm1_threshold_day_input() -> DayInputData:
    mon_am4 = Slot(day="星期一", block="上午", period=4)
    mon_pm1 = Slot(day="星期一", block="下午", period=1)
    tue_am4 = Slot(day="星期二", block="上午", period=4)
    tue_pm1 = Slot(day="星期二", block="下午", period=1)
    wed_am4 = Slot(day="星期三", block="上午", period=4)
    thu_pm1 = Slot(day="星期四", block="下午", period=1)
    return DayInputData(
        classes=["class_a"],
        cls_subj_teacher={
            ("class_a", "math"): "teacher_main",
            ("class_a", "science"): "teacher_main",
            ("class_a", "体育"): "pe_teacher",
        },
        available_slots=[mon_am4, mon_pm1, tue_am4, tue_pm1, wed_am4, thu_pm1],
        fixed_assign={},
        req_hours={
            ("class_a", "math"): (0, 3, 0),
            ("class_a", "science"): (0, 3, 0),
            ("class_a", "体育"): (0, 3, 0),
        },
        subject_ban_slots={},
    )


def test_day_teacher_am4_pm1_threshold_generic_contract_matches_legacy_soft_shape() -> None:
    data = _teacher_am4_pm1_threshold_day_input()

    bridge = day_teacher_am4_pm1_threshold_penalty_to_ai_or_problem(
        data,
        pe_teachers={"pe_teacher"},
        weights=(3, 5, 7, 11),
    )

    assert bridge.problem.problem_id == "scheduler_day_teacher_am4_pm1_threshold_penalty"
    assert tuple(rule.rule_id for rule in bridge.problem.rules) == ("joint.day.teacher_am4_pm1_threshold_penalty",)
    assert bridge.problem.objective is not None
    metadata = bridge.metadata_by_rule["joint.day.teacher_am4_pm1_threshold_penalty"]
    assert metadata["generic_contract_status"] == "covered_by_generic_contract"
    assert metadata["legacy_apply_fn"] == "apply_teacher_am4_pm1_threshold_penalty"
    assert metadata["constrained_teachers"] == ("teacher_main",)
    assert metadata["teacher_total_assignment_count_by_teacher"] == {"teacher_main": 12}
    assert metadata["constraint_family_counts"] == {
        "teacher_am4_pm1_count_equalities": 1,
        "teacher_am4_pm1_weekly_caps": 1,
        "teacher_am4_pm1_threshold_penalty_constraints": 4,
        "teacher_am4_pm1_penalty_terms": 4,
    }
    assert len(metadata["teacher_assignment_variable_names"]["teacher_main"]) == 12
    assert len(bridge.problem.constraints) == 6

    legacy_model = create_existing_cp_model("day.teacher_am4_pm1_threshold.parity")
    legacy_vars = build_day_variables(legacy_model, data)
    with ai_or_model_rule_context(
        "joint.day.teacher_am4_pm1_threshold_penalty",
        source="scheduler.model.constraints.day_weekday_constraints",
    ):
        legacy_penalties, legacy_details = apply_teacher_am4_pm1_threshold_penalty(
            legacy_model,
            data,
            legacy_vars,
            {"pe_teacher"},
            (3, 5, 7, 11),
        )
    legacy_summary = summarize_existing_cp_model_operations_by_rule(legacy_model)
    assert len(legacy_penalties) == metadata["constraint_family_counts"]["teacher_am4_pm1_penalty_terms"]
    assert set(legacy_details) == {"teacher_main"}
    assert legacy_details["teacher_main"][0] == 12
    assert legacy_summary["joint.day.teacher_am4_pm1_threshold_penalty"]["operations"] == {
        "Add": len(bridge.problem.constraints),
        "NewIntVar": 5,
    }

    expected_penalties = metadata["penalty_variable_names_by_teacher"]["teacher_main"]
    assert {
        (term.variable, term.coefficient)
        for term in bridge.problem.objective.expression.terms
    } == {
        (expected_penalties["e3"], 3),
        (expected_penalties["e4"], 5),
        (expected_penalties["e5"], 7),
        (expected_penalties["e6"], 11),
    }

    solution = solve_cp_sat_problem(bridge.problem, time_limit_seconds=5)

    assert solution.status_name == "OPTIMAL"
    assert solution.values[metadata["count_variable_names_by_teacher"]["teacher_main"]] == 0
    assert all(solution.values[name] == 0 for name in expected_penalties.values())


def test_generic_scheduler_rule_ids_exposes_real_day_teacher_am4_pm1_threshold_coverage() -> None:
    covered_rule_ids = generic_scheduler_rule_ids()

    assert "joint.day.teacher_am4_pm1_threshold_penalty" in covered_rule_ids


def _weekday_subject_balance_day_input() -> DayInputData:
    mon_am1 = Slot(day="星期一", block="上午", period=1)
    tue_am1 = Slot(day="星期二", block="上午", period=1)
    wed_am1 = Slot(day="星期三", block="上午", period=1)
    thu_am1 = Slot(day="星期四", block="上午", period=1)
    fri_am1 = Slot(day="星期五", block="上午", period=1)
    return DayInputData(
        classes=["class_a"],
        cls_subj_teacher={
            ("class_a", "math"): "math_teacher",
            ("class_a", "体育"): "pe_teacher",
        },
        available_slots=[mon_am1, tue_am1, wed_am1, thu_am1, fri_am1],
        fixed_assign={("class_a", tue_am1): "math"},
        req_hours={
            ("class_a", "math"): (0, 7, 0),
            ("class_a", "体育"): (0, 5, 0),
        },
        subject_ban_slots={},
    )


def test_day_weekday_subject_balance_generic_contract_matches_legacy_soft_shape() -> None:
    data = _weekday_subject_balance_day_input()

    bridge = day_weekday_subject_balance_to_ai_or_problem(data, mode="soft", weight=29)

    assert bridge.problem.problem_id == "scheduler_day_weekday_subject_balance"
    assert tuple(rule.rule_id for rule in bridge.problem.rules) == ("joint.day.weekday_subject_balance",)
    assert bridge.problem.objective is not None
    metadata = bridge.metadata_by_rule["joint.day.weekday_subject_balance"]
    assert metadata["generic_contract_status"] == "covered_by_generic_contract"
    assert metadata["legacy_apply_fn"] == "apply_weekday_subject_balance"
    assert metadata["mode"] == "soft"
    assert metadata["target_class_subjects"] == ("class_a|math",)
    assert metadata["weekday_base_targets"] == {"class_a|math": 1}
    assert metadata["fixed_count_constants"] == {"class_a|math|星期二": 1}
    assert metadata["constraint_family_counts"] == {
        "weekday_subject_day_hour_equalities": 5,
        "weekday_subject_balance_over_under_constraints": 10,
        "weekday_subject_balance_penalty_terms": 10,
    }
    assert len(metadata["day_hour_variable_names"]) == 5
    assert sum(len(names) for names in metadata["penalty_variable_names_by_class_subject_day"].values()) == 10
    assert len(bridge.problem.constraints) == 15

    legacy_model = create_existing_cp_model("day.weekday_subject_balance.parity")
    legacy_vars = build_day_variables(legacy_model, data)
    with ai_or_model_rule_context(
        "joint.day.weekday_subject_balance",
        source="scheduler.model.constraints.day_weekday_constraints",
    ):
        legacy_penalties = apply_weekday_subject_balance(
            legacy_model,
            data,
            legacy_vars,
            mode="soft",
            weight=29,
        )
    legacy_summary = summarize_existing_cp_model_operations_by_rule(legacy_model)
    assert len(legacy_penalties) == metadata["constraint_family_counts"]["weekday_subject_balance_penalty_terms"]
    assert legacy_summary["joint.day.weekday_subject_balance"]["operations"] == {
        "Add": len(bridge.problem.constraints),
        "NewIntVar": 15,
    }

    expected_penalty_names = {
        name
        for names in metadata["penalty_variable_names_by_class_subject_day"].values()
        for name in names.values()
    }
    assert {
        (term.variable, term.coefficient)
        for term in bridge.problem.objective.expression.terms
    } == {(name, 29) for name in expected_penalty_names}

    solution = solve_cp_sat_problem(bridge.problem, time_limit_seconds=5)

    assert solution.status_name == "OPTIMAL"
    assert all(solution.values[name] == 0 for name in expected_penalty_names)


def test_generic_scheduler_rule_ids_exposes_real_day_weekday_subject_balance_coverage() -> None:
    covered_rule_ids = generic_scheduler_rule_ids()

    assert "joint.day.weekday_subject_balance" in covered_rule_ids


def _teacher_continuity_day_input() -> DayInputData:
    mon_am1 = Slot(day="星期一", block="上午", period=1)
    mon_am2 = Slot(day="星期一", block="上午", period=2)
    mon_am3 = Slot(day="星期一", block="上午", period=3)
    mon_pm1 = Slot(day="星期一", block="下午", period=1)
    mon_pm2 = Slot(day="星期一", block="下午", period=2)
    return DayInputData(
        classes=["class_a"],
        cls_subj_teacher={
            ("class_a", "math"): "teacher_main",
            ("class_a", "science"): "teacher_main",
            ("class_a", "体育"): "coach",
        },
        available_slots=[mon_am1, mon_am2, mon_am3, mon_pm1, mon_pm2],
        fixed_assign={},
        req_hours={
            ("class_a", "math"): (0, 3, 0),
            ("class_a", "science"): (0, 2, 0),
            ("class_a", "体育"): (0, 2, 0),
        },
        subject_ban_slots={},
    )


def test_day_teacher_continuity_penalty_generic_contract_matches_legacy_gap_shape() -> None:
    data = _teacher_continuity_day_input()

    bridge = day_teacher_continuity_penalty_to_ai_or_problem(data, pe_teachers={"coach"}, weight=17)

    assert bridge.problem.problem_id == "scheduler_day_teacher_continuity_penalty"
    assert tuple(rule.rule_id for rule in bridge.problem.rules) == ("joint.day.teacher_continuity_penalty",)
    assert bridge.problem.objective is not None
    metadata = bridge.metadata_by_rule["joint.day.teacher_continuity_penalty"]
    assert metadata["generic_contract_status"] == "covered_by_generic_contract"
    assert metadata["legacy_apply_fn"] == "apply_teacher_continuity_penalty"
    assert metadata["constrained_teachers"] == ("teacher_main",)
    assert metadata["constraint_family_counts"] == {
        "teacher_continuity_busy_equalities": 5,
        "teacher_continuity_101_gap_constraints": 4,
        "teacher_continuity_adjacent_gap_constraints": 3,
        "teacher_continuity_gap_penalty_terms": 2,
    }
    assert len(metadata["busy_variable_names"]) == 5
    assert len(metadata["gap_variable_names"]) == 2
    assert len(bridge.problem.constraints) == 12

    legacy_model = create_existing_cp_model("day.teacher_continuity.parity")
    legacy_vars = build_day_variables(legacy_model, data)
    with ai_or_model_rule_context(
        "joint.day.teacher_continuity_penalty",
        source="scheduler.model.constraints.day_weekday_constraints",
    ):
        legacy_penalties, legacy_details = apply_teacher_continuity_penalty(
            legacy_model,
            data,
            legacy_vars,
            {"coach"},
            weight=17,
        )
    legacy_summary = summarize_existing_cp_model_operations_by_rule(legacy_model)
    assert len(legacy_penalties) == metadata["constraint_family_counts"]["teacher_continuity_gap_penalty_terms"]
    assert set(legacy_details) == {("teacher_main", "星期一", "AM"), ("teacher_main", "星期一", "PM")}
    assert legacy_summary["joint.day.teacher_continuity_penalty"]["operations"] == {
        "Add": len(bridge.problem.constraints),
        "NewBoolVar": len(metadata["busy_variable_names"]) + len(metadata["gap_variable_names"]),
    }

    assert {
        (term.variable, term.coefficient)
        for term in bridge.problem.objective.expression.terms
    } == {(name, 17) for name in metadata["gap_variable_names"].values()}

    solution = solve_cp_sat_problem(bridge.problem, time_limit_seconds=5)

    assert solution.status_name == "OPTIMAL"
    assert all(solution.values[name] == 0 for name in metadata["gap_variable_names"].values())


def test_generic_scheduler_rule_ids_exposes_real_day_teacher_continuity_coverage() -> None:
    covered_rule_ids = generic_scheduler_rule_ids()

    assert "joint.day.teacher_continuity_penalty" in covered_rule_ids


def _two_class_daily_min_day_input() -> DayInputData:
    mon_am1 = Slot(day="星期一", block="上午", period=1)
    mon_pm1 = Slot(day="星期一", block="下午", period=1)
    return DayInputData(
        classes=["class_a", "class_b"],
        cls_subj_teacher={
            ("class_a", "math"): "teacher_shared",
            ("class_b", "math"): "teacher_shared",
        },
        available_slots=[mon_am1, mon_pm1],
        fixed_assign={},
        req_hours={
            ("class_a", "math"): (0, 2, 0),
            ("class_b", "math"): (0, 2, 0),
        },
        subject_ban_slots={},
    )


def test_day_two_class_daily_min_generic_contract_matches_legacy_soft_shape() -> None:
    data = _two_class_daily_min_day_input()

    bridge = day_two_class_daily_min_per_class_to_ai_or_problem(
        data,
        pe_teachers=set(),
        mode="soft",
        w_soft=31,
    )

    assert bridge.problem.problem_id == "scheduler_day_two_class_daily_min_per_class"
    assert tuple(rule.rule_id for rule in bridge.problem.rules) == ("joint.day.two_class_daily_min_per_class",)
    assert bridge.problem.objective is not None
    metadata = bridge.metadata_by_rule["joint.day.two_class_daily_min_per_class"]
    assert metadata["generic_contract_status"] == "covered_by_generic_contract"
    assert metadata["legacy_apply_fn"] == "apply_two_class_daily_min_per_class"
    assert metadata["constrained_teachers"] == ("teacher_shared",)
    assert metadata["teacher_classes"] == {"teacher_shared": ("class_a", "class_b")}
    assert metadata["constraint_family_counts"] == {
        "two_class_daily_min_class_presence_constraints": 14,
        "two_class_daily_min_any_presence_constraints": 9,
        "two_class_daily_min_violation_constraints": 30,
        "two_class_daily_min_penalty_terms": 10,
    }
    assert len(metadata["has_any_variable_names"]) == 5
    assert len(metadata["has_class_variable_names"]) == 10
    assert len(metadata["violation_variable_names"]) == 10
    assert len(bridge.problem.constraints) == 53

    legacy_model = create_existing_cp_model("day.two_class_daily_min.parity")
    legacy_vars = build_day_variables(legacy_model, data)
    with ai_or_model_rule_context(
        "joint.day.two_class_daily_min_per_class",
        source="scheduler.model.constraints.day_weekday_constraints",
    ):
        legacy_penalties, legacy_details = apply_two_class_daily_min_per_class(
            legacy_model,
            data,
            legacy_vars,
            set(),
            mode="soft",
            w_soft=31,
        )
    legacy_summary = summarize_existing_cp_model_operations_by_rule(legacy_model)
    assert len(legacy_penalties) == metadata["constraint_family_counts"]["two_class_daily_min_penalty_terms"]
    assert len(legacy_details) == metadata["constraint_family_counts"]["two_class_daily_min_penalty_terms"]
    assert legacy_summary["joint.day.two_class_daily_min_per_class"]["operations"] == {
        "Add": len(bridge.problem.constraints),
        "NewBoolVar": 25,
    }

    assert {
        (term.variable, term.coefficient)
        for term in bridge.problem.objective.expression.terms
    } == {(name, 31) for name in metadata["violation_variable_names"].values()}

    solution = solve_cp_sat_problem(bridge.problem, time_limit_seconds=5)

    assert solution.status_name == "OPTIMAL"
    assert all(solution.values[name] == 0 for name in metadata["violation_variable_names"].values())


def test_generic_scheduler_rule_ids_exposes_real_day_two_class_daily_min_coverage() -> None:
    covered_rule_ids = generic_scheduler_rule_ids()

    assert "joint.day.two_class_daily_min_per_class" in covered_rule_ids


def _teacher_m1_cap_day_input() -> DayInputData:
    mon_am1 = Slot(day="星期一", block="上午", period=1)
    tue_am1 = Slot(day="星期二", block="上午", period=1)
    wed_am1 = Slot(day="星期三", block="上午", period=1)
    return DayInputData(
        classes=["class_a"],
        cls_subj_teacher={("class_a", "math"): "teacher_main"},
        available_slots=[mon_am1, tue_am1, wed_am1],
        fixed_assign={("class_a", wed_am1): "math"},
        req_hours={("class_a", "math"): (0, 2, 0)},
        subject_ban_slots={},
    )


def test_day_teacher_m1_cap_constraint_generic_contract_matches_legacy_soft_cap_shape() -> None:
    data = _teacher_m1_cap_day_input()

    bridge = day_teacher_m1_cap_constraint_to_ai_or_problem(data, max_m1=2, weight=23)

    assert bridge.problem.problem_id == "scheduler_day_teacher_m1_cap_constraint"
    assert tuple(rule.rule_id for rule in bridge.problem.rules) == ("joint.day.teacher_m1_cap_constraint",)
    assert bridge.problem.objective is not None
    metadata = bridge.metadata_by_rule["joint.day.teacher_m1_cap_constraint"]
    assert metadata["generic_contract_status"] == "covered_by_generic_contract"
    assert metadata["legacy_apply_fn"] == "apply_teacher_m1_cap_constraint"
    assert metadata["constrained_teachers"] == ("teacher_main",)
    assert metadata["fixed_total_by_teacher"] == {"teacher_main": 1}
    assert metadata["structural_impossible"] == {}
    assert metadata["constraint_family_counts"] == {
        "teacher_m1_day_occurrence_constraints": 7,
        "teacher_m1_weekly_total_constraints": 2,
        "teacher_m1_penalty_total_constraints": 3,
        "teacher_m1_hit_cap_penalty_terms": 1,
    }
    assert len(metadata["occ_variable_names"]) == 5
    assert len(metadata["m1_total_variable_names"]) == 1
    assert len(metadata["hit_cap_variable_names"]) == 1
    assert len(metadata["m1_penalty_total_variable_names"]) == 1
    assert len(bridge.problem.constraints) == 12

    legacy_model = create_existing_cp_model("day.teacher_m1_cap.parity")
    legacy_vars = build_day_variables(legacy_model, data)
    with ai_or_model_rule_context(
        "joint.day.teacher_m1_cap_constraint",
        source="scheduler.model.constraints.day_weekday_constraints",
    ):
        legacy_penalties, legacy_details, structural_impossible = apply_teacher_m1_cap_constraint(
            legacy_model,
            data,
            legacy_vars,
            max_m1=2,
            weight=23,
        )
    legacy_summary = summarize_existing_cp_model_operations_by_rule(legacy_model)
    assert len(legacy_penalties) == metadata["constraint_family_counts"]["teacher_m1_hit_cap_penalty_terms"]
    assert set(legacy_details) == {"teacher_main"}
    assert structural_impossible == metadata["structural_impossible"]
    assert legacy_summary["joint.day.teacher_m1_cap_constraint"]["operations"] == {
        "Add": len(bridge.problem.constraints),
        "NewBoolVar": len(metadata["occ_variable_names"]) + len(metadata["hit_cap_variable_names"]),
        "NewIntVar": len(metadata["m1_total_variable_names"]) + len(metadata["m1_penalty_total_variable_names"]),
    }

    assert {
        (term.variable, term.coefficient)
        for term in bridge.problem.objective.expression.terms
    } == {(next(iter(metadata["hit_cap_variable_names"].values())), 23)}

    solution = solve_cp_sat_problem(bridge.problem, time_limit_seconds=5)

    assert solution.status_name == "OPTIMAL"
    assert all(solution.values[name] == 0 for name in metadata["hit_cap_variable_names"].values())


def test_generic_scheduler_rule_ids_exposes_real_day_teacher_m1_cap_coverage() -> None:
    covered_rule_ids = generic_scheduler_rule_ids()

    assert "joint.day.teacher_m1_cap_constraint" in covered_rule_ids


def _teacher_am1_fragmentation_day_input() -> DayInputData:
    mon_am1 = Slot(day="星期一", block="上午", period=1)
    mon_am2 = Slot(day="星期一", block="上午", period=2)
    tue_am1 = Slot(day="星期二", block="上午", period=1)
    wed_am1 = Slot(day="星期三", block="上午", period=1)
    return DayInputData(
        classes=["class_a"],
        cls_subj_teacher={("class_a", "math"): "teacher_main"},
        available_slots=[mon_am1, mon_am2, tue_am1, wed_am1],
        fixed_assign={("class_a", wed_am1): "math"},
        req_hours={("class_a", "math"): (0, 3, 0)},
        subject_ban_slots={},
    )


def test_day_teacher_am1_fragmentation_generic_contract_matches_legacy_penalty_shape() -> None:
    data = _teacher_am1_fragmentation_day_input()
    exempt_days = {("teacher_main", "星期三")}

    bridge = day_teacher_am1_fragmentation_to_ai_or_problem(
        data,
        pe_teachers=set(),
        k_week=2,
        w_only_am1=13,
        w_am1_excess=17,
        am1_penalty_exempt_teacher_days=exempt_days,
    )

    assert bridge.problem.problem_id == "scheduler_day_teacher_am1_fragmentation"
    assert tuple(rule.rule_id for rule in bridge.problem.rules) == ("joint.day.teacher_am1_fragmentation",)
    assert bridge.problem.objective is not None
    metadata = bridge.metadata_by_rule["joint.day.teacher_am1_fragmentation"]
    assert metadata["generic_contract_status"] == "covered_by_generic_contract"
    assert metadata["legacy_apply_fn"] == "apply_teacher_am1_fragmentation"
    assert metadata["constrained_teachers"] == ("teacher_main",)
    assert metadata["fixed_am1_penalty_week_by_teacher"] == {"teacher_main": 0}
    assert metadata["am1_penalty_exempt_teacher_days"] == ("teacher_main|星期三",)
    assert metadata["constraint_family_counts"] == {
        "teacher_am1_fragmentation_am1_busy_constraints": 7,
        "teacher_am1_fragmentation_non_am1_busy_constraints": 6,
        "teacher_am1_fragmentation_only_am1_constraints": 15,
        "teacher_am1_fragmentation_only_am1_count_equalities": 1,
        "teacher_am1_fragmentation_excess_count_constraints": 2,
        "teacher_am1_fragmentation_only_am1_penalty_terms": 4,
        "teacher_am1_fragmentation_excess_penalty_terms": 1,
    }
    assert len(metadata["am1_busy_variable_names"]) == 5
    assert len(metadata["has_non_am1_variable_names"]) == 5
    assert len(metadata["only_am1_variable_names"]) == 5
    assert len(metadata["only_am1_count_variable_names"]) == 1
    assert len(metadata["am1_count_variable_names"]) == 1
    assert len(metadata["excess_variable_names"]) == 1
    assert len(bridge.problem.constraints) == 31

    legacy_model = create_existing_cp_model("day.teacher_am1_fragmentation.parity")
    legacy_vars = build_day_variables(legacy_model, data)
    with ai_or_model_rule_context(
        "joint.day.teacher_am1_fragmentation",
        source="scheduler.model.constraints.day_weekday_constraints",
    ):
        legacy_only_am1_penalties, legacy_excess_penalties, legacy_details = apply_teacher_am1_fragmentation(
            legacy_model,
            data,
            legacy_vars,
            set(),
            k_week=2,
            w_only_am1=13,
            w_am1_excess=17,
            am1_penalty_exempt_teacher_days=exempt_days,
        )
    legacy_summary = summarize_existing_cp_model_operations_by_rule(legacy_model)
    assert len(legacy_only_am1_penalties) == metadata["constraint_family_counts"][
        "teacher_am1_fragmentation_only_am1_penalty_terms"
    ]
    assert len(legacy_excess_penalties) == metadata["constraint_family_counts"][
        "teacher_am1_fragmentation_excess_penalty_terms"
    ]
    assert set(legacy_details) == {"teacher_main"}
    assert legacy_summary["joint.day.teacher_am1_fragmentation"]["operations"] == {
        "Add": len(bridge.problem.constraints),
        "NewBoolVar": (
            len(metadata["am1_busy_variable_names"])
            + len(metadata["has_non_am1_variable_names"])
            + len(metadata["only_am1_variable_names"])
        ),
        "NewIntVar": (
            len(metadata["only_am1_count_variable_names"])
            + len(metadata["am1_count_variable_names"])
            + len(metadata["excess_variable_names"])
        ),
    }

    expected_objective_terms = {
        (name, 13)
        for key, name in metadata["only_am1_variable_names"].items()
        if key not in {"teacher_main|星期三"}
    }
    expected_objective_terms.update((name, 17) for name in metadata["excess_variable_names"].values())
    assert {
        (term.variable, term.coefficient)
        for term in bridge.problem.objective.expression.terms
    } == expected_objective_terms

    solution = solve_cp_sat_problem(bridge.problem, time_limit_seconds=5)

    assert solution.status_name == "OPTIMAL"
    for variable, _weight in expected_objective_terms:
        assert solution.values[variable] == 0


def test_generic_scheduler_rule_ids_exposes_real_day_teacher_am1_fragmentation_coverage() -> None:
    covered_rule_ids = generic_scheduler_rule_ids()

    assert "joint.day.teacher_am1_fragmentation" in covered_rule_ids


def _multi_class_halfday_day_input() -> DayInputData:
    mon_am1 = Slot(day="星期一", block="上午", period=1)
    mon_am2 = Slot(day="星期一", block="上午", period=2)
    mon_pm1 = Slot(day="星期一", block="下午", period=1)
    return DayInputData(
        classes=["class_a", "class_b"],
        cls_subj_teacher={
            ("class_a", "math"): "teacher_main",
            ("class_b", "math"): "teacher_main",
        },
        available_slots=[mon_am1, mon_am2, mon_pm1],
        fixed_assign={},
        req_hours={
            ("class_a", "math"): (0, 3, 0),
            ("class_b", "math"): (0, 3, 0),
        },
        subject_ban_slots={},
    )


def test_day_multi_class_halfday_soft_generic_contract_matches_legacy_split_shape() -> None:
    data = _multi_class_halfday_day_input()

    bridge = day_multi_class_halfday_soft_to_ai_or_problem(data, pe_teachers=set(), weight=19)

    assert bridge.problem.problem_id == "scheduler_day_multi_class_halfday_soft"
    assert tuple(rule.rule_id for rule in bridge.problem.rules) == ("joint.day.multi_class_halfday_soft",)
    assert bridge.problem.objective is not None
    metadata = bridge.metadata_by_rule["joint.day.multi_class_halfday_soft"]
    assert metadata["generic_contract_status"] == "covered_by_generic_contract"
    assert metadata["legacy_apply_fn"] == "apply_multi_class_halfday_soft"
    assert metadata["constrained_teachers"] == ("teacher_main",)
    assert metadata["teacher_classes"] == {"teacher_main": ("class_a", "class_b")}
    assert metadata["constraint_family_counts"] == {
        "multi_class_halfday_class_count_equalities": 2,
        "multi_class_halfday_class_am_presence_constraints": 6,
        "multi_class_halfday_class_pm_presence_constraints": 4,
        "multi_class_halfday_cnt_ge2_constraints": 4,
        "multi_class_halfday_split_ok_constraints": 6,
        "multi_class_halfday_not_split_constraints": 2,
        "multi_class_halfday_split_vio_constraints": 6,
        "multi_class_halfday_any_am_presence_constraints": 5,
        "multi_class_halfday_any_pm_presence_constraints": 3,
        "multi_class_halfday_split_forced_max_constraints": 1,
        "multi_class_halfday_cross_halfday_constraints": 3,
        "multi_class_halfday_not_forced_constraints": 1,
        "multi_class_halfday_cross_penalty_constraints": 3,
        "multi_class_halfday_penalty_terms": 3,
    }
    assert metadata["linear_constraint_count"] == 45
    assert len(bridge.problem.constraints) == 46
    assert len(metadata["has_any_am_variable_names"]) == 5
    assert len(metadata["has_any_pm_variable_names"]) == 5
    assert len(metadata["class_count_variable_names"]) == 2
    assert len(metadata["class_has_am_variable_names"]) == 2
    assert len(metadata["class_has_pm_variable_names"]) == 2
    assert len(metadata["class_count_ge2_variable_names"]) == 2
    assert len(metadata["split_ok_variable_names"]) == 2
    assert len(metadata["not_split_variable_names"]) == 2
    assert len(metadata["split_violation_variable_names"]) == 2
    assert len(metadata["split_forced_variable_names"]) == 1
    assert len(metadata["cross_halfday_variable_names"]) == 1
    assert len(metadata["not_forced_variable_names"]) == 1
    assert len(metadata["cross_penalty_variable_names"]) == 1

    legacy_model = create_existing_cp_model("day.multi_class_halfday.parity")
    legacy_vars = build_day_variables(legacy_model, data)
    with ai_or_model_rule_context(
        "joint.day.multi_class_halfday_soft",
        source="scheduler.model.constraints.day_weekday_constraints",
    ):
        legacy_penalties, legacy_details = apply_multi_class_halfday_soft(
            legacy_model,
            data,
            legacy_vars,
            set(),
            weight=19,
        )
    legacy_summary = summarize_existing_cp_model_operations_by_rule(legacy_model)
    assert len(legacy_penalties) == metadata["constraint_family_counts"]["multi_class_halfday_penalty_terms"]
    assert set(legacy_details) == {
        ("teacher_main", "星期一", "class_a"),
        ("teacher_main", "星期一", "class_b"),
    }
    assert legacy_summary["joint.day.multi_class_halfday_soft"]["operations"] == {
        "Add": metadata["linear_constraint_count"],
        "AddMaxEquality": metadata["constraint_family_counts"]["multi_class_halfday_split_forced_max_constraints"],
        "NewBoolVar": (
            len(metadata["has_any_am_variable_names"])
            + len(metadata["has_any_pm_variable_names"])
            + len(metadata["class_has_am_variable_names"])
            + len(metadata["class_has_pm_variable_names"])
            + len(metadata["class_count_ge2_variable_names"])
            + len(metadata["split_ok_variable_names"])
            + len(metadata["not_split_variable_names"])
            + len(metadata["split_violation_variable_names"])
            + len(metadata["split_forced_variable_names"])
            + len(metadata["cross_halfday_variable_names"])
            + len(metadata["not_forced_variable_names"])
            + len(metadata["cross_penalty_variable_names"])
        ),
        "NewIntVar": len(metadata["class_count_variable_names"]),
    }

    expected_penalties = {
        *metadata["split_violation_variable_names"].values(),
        *metadata["cross_penalty_variable_names"].values(),
    }
    assert {
        (term.variable, term.coefficient)
        for term in bridge.problem.objective.expression.terms
    } == {(name, 19) for name in expected_penalties}

    solution = solve_cp_sat_problem(bridge.problem, time_limit_seconds=5)

    assert solution.status_name == "OPTIMAL"
    assert all(solution.values[name] == 0 for name in expected_penalties)


def test_generic_scheduler_rule_ids_exposes_real_day_multi_class_halfday_coverage() -> None:
    covered_rule_ids = generic_scheduler_rule_ids()

    assert "joint.day.multi_class_halfday_soft" in covered_rule_ids


def test_generic_scheduler_rule_ids_exposes_solver_parameter_rule_coverage() -> None:
    covered_rule_ids = generic_scheduler_rule_ids()

    assert "day.solver_parameters" in covered_rule_ids
    assert "night.solver_parameters" in covered_rule_ids
    assert "joint.solver_parameters" in covered_rule_ids


def test_grade_group_duty_generic_contract_matches_legacy_duty_shape() -> None:
    days = ["星期一", "星期二", "星期六", "星期日"]
    members = ["teacher_a", "teacher_b"]
    bridge = grade_group_duty_to_ai_or_problem(
        days=days,
        members=members,
        all_teachers=members,
        cfg=GradeGroupDutyConfig(
            members=members,
            min_once_mode="soft",
            daily_need_night_mode="soft",
            enable_fairness=True,
            w_daily_need_night=11,
            w_min_once=13,
            w_no_night_penalty=17,
            w_fairness_balance=19,
        ),
    )

    assert bridge.problem.problem_id == "scheduler_grade_group_duty_constraints"
    assert tuple(rule.rule_id for rule in bridge.problem.rules) == ("joint.link.grade_group_duty_constraints",)
    assert bridge.problem.objective is not None
    metadata = bridge.metadata_by_rule["joint.link.grade_group_duty_constraints"]
    assert metadata["generic_contract_status"] == "covered_by_generic_contract"
    assert metadata["legacy_apply_fn"] == "apply_grade_group_duty_constraints"
    assert metadata["members"] == tuple(members)
    assert metadata["days"] == tuple(days)
    assert metadata["constraint_family_counts"] == {
        "grade_group_daily_need_night_presence_constraints": 6,
        "grade_group_daily_need_night_miss_constraints": 2,
        "grade_group_duty_assignment_constraints": 6,
        "grade_group_min_once_count_constraints": 2,
        "grade_group_min_once_miss_constraints": 2,
        "grade_group_no_night_constraints": 8,
        "grade_group_no_night_violation_constraints": 24,
        "grade_group_fairness_constraints": 6,
        "grade_group_penalty_terms": 14,
    }
    assert metadata["linear_constraint_count"] == 56
    assert len(metadata["on_teacher_day_variable_names"]) == 8
    assert len(metadata["group_has_night_variable_names"]) == 2
    assert len(metadata["daily_need_miss_variable_names"]) == 2
    assert len(metadata["grade_duty_variable_names"]) == 8
    assert len(metadata["week_count_variable_names"]) == 2
    assert len(metadata["min_once_miss_variable_names"]) == 2
    assert len(metadata["no_night_variable_names"]) == 8
    assert len(metadata["no_night_violation_variable_names"]) == 8
    assert len(metadata["fairness_count_variable_names"]) == 2
    assert len(metadata["fairness_dev_variable_names"]) == 2
    assert metadata["fairness_min_count_variable_name"]

    legacy_model = create_existing_cp_model("grade_group_duty.parity")
    legacy_on_teacher_day = {
        (teacher, day): legacy_model.NewBoolVar(f"on[{teacher},{day}]")
        for teacher in members
        for day in days
    }
    with ai_or_model_rule_context(
        "joint.link.grade_group_duty_constraints",
        source="scheduler.model.constraints.grade_group_duty_constraints",
    ):
        legacy_penalties, legacy_grade_duty, legacy_info = apply_grade_group_duty_constraints(
            legacy_model,
            days=days,
            on_teacher_day=legacy_on_teacher_day,
            all_teachers=members,
            cfg=GradeGroupDutyConfig(
                members=members,
                min_once_mode="soft",
                daily_need_night_mode="soft",
                enable_fairness=True,
                w_daily_need_night=11,
                w_min_once=13,
                w_no_night_penalty=17,
                w_fairness_balance=19,
            ),
        )
    legacy_summary = summarize_existing_cp_model_operations_by_rule(legacy_model)
    assert len(legacy_penalties) == metadata["constraint_family_counts"]["grade_group_penalty_terms"]
    assert len(legacy_grade_duty) == len(metadata["grade_duty_variable_names"])
    assert legacy_info["member_night_key"] == {"teacher_a": "teacher_a", "teacher_b": "teacher_b"}
    assert legacy_summary["joint.link.grade_group_duty_constraints"]["operations"] == {
        "Add": metadata["linear_constraint_count"],
        "NewBoolVar": (
            len(metadata["group_has_night_variable_names"])
            + len(metadata["daily_need_miss_variable_names"])
            + len(metadata["grade_duty_variable_names"])
            + len(metadata["min_once_miss_variable_names"])
            + len(metadata["no_night_variable_names"])
            + len(metadata["no_night_violation_variable_names"])
        ),
        "NewConstant": 12,
        "NewIntVar": (
            len(metadata["week_count_variable_names"])
            + len(metadata["fairness_count_variable_names"])
            + len(metadata["fairness_dev_variable_names"])
            + 1
        ),
    }

    expected_terms = {
        **{name: 11 for name in metadata["daily_need_miss_variable_names"].values()},
        **{name: 13 for name in metadata["min_once_miss_variable_names"].values()},
        **{name: 17 for name in metadata["no_night_violation_variable_names"].values()},
        **{name: 19 for name in metadata["fairness_dev_variable_names"].values()},
    }
    assert {
        (term.variable, term.coefficient)
        for term in bridge.problem.objective.expression.terms
    } == set(expected_terms.items())

    solution = solve_cp_sat_problem(bridge.problem, time_limit_seconds=5)

    assert solution.status_name == "OPTIMAL"
    assert all(solution.values[name] == 0 for name in expected_terms)


def test_generic_scheduler_rule_ids_exposes_real_grade_group_duty_coverage() -> None:
    covered_rule_ids = generic_scheduler_rule_ids()

    assert "joint.link.grade_group_duty_constraints" in covered_rule_ids


def test_duty_joint_generic_contract_matches_legacy_joint_shape() -> None:
    days = ["星期一", "星期二", "星期日"]
    male_heads = ["teacher_m1", "teacher_m2"]
    female_heads = ["teacher_f1"]
    noon_male_names = {(teacher, day): f"noon_m[{teacher},{day}]" for teacher in male_heads for day in days}
    noon_female_names = {(teacher, day): f"noon_f[{teacher},{day}]" for teacher in female_heads for day in days}
    pm_names = {
        (teacher, day): f"pm_pre[{teacher},{day}]"
        for teacher in [*male_heads, *female_heads]
        for day in days
    }
    night_male_names = {(teacher, day): f"night_m[{teacher},{day}]" for teacher in male_heads for day in days}
    night_female_names = {(teacher, day): f"night_f[{teacher},{day}]" for teacher in female_heads for day in days}
    cfg = DutyJointConfig(
        male_total_target_mode="soft",
        male_total_target=2,
        w_male_total_target_deviation=23,
        female_min_noon_night_mode="soft",
        w_female_min_noon_night=29,
        enable_female_two_duty_penalty=True,
        w_female_two_duty_penalty=31,
        male_max_min_mode="soft",
        w_male_max_min_gap=37,
        enable_soft_male_duty_balance=True,
        w_soft_male_duty_balance=41,
        pm_pre_class_no_consecutive_mode="soft",
        w_pm_pre_class_no_consecutive=43,
        noon_max1_teachers=["teacher_m2"],
        total_noon_night_max1_teachers=["teacher_f1"],
    )

    bridge = duty_joint_to_ai_or_problem(
        days=days,
        noon_male_duty_variable_names=noon_male_names,
        noon_female_duty_variable_names=noon_female_names,
        pm_pre_class_duty_variable_names=pm_names,
        night_dorm_duty_male_variable_names=night_male_names,
        night_dorm_duty_female_variable_names=night_female_names,
        male_heads=male_heads,
        female_heads=female_heads,
        cfg=cfg,
    )

    assert bridge.problem.problem_id == "scheduler_duty_joint_constraints"
    assert tuple(rule.rule_id for rule in bridge.problem.rules) == ("joint.link.duty_joint_constraints",)
    assert bridge.problem.objective is not None
    metadata = bridge.metadata_by_rule["joint.link.duty_joint_constraints"]
    assert metadata["generic_contract_status"] == "covered_by_generic_contract"
    assert metadata["legacy_apply_fn"] == "add_duty_joint_constraints"
    assert metadata["constraint_family_counts"] == {
        "duty_joint_count_equalities": 9,
        "duty_joint_head_min_constraints": 3,
        "duty_joint_female_extra_total_constraints": 2,
        "duty_joint_noon_max_constraints": 1,
        "duty_joint_total_noon_night_max_constraints": 1,
        "duty_joint_male_target_constraints": 4,
        "duty_joint_male_no_night_constraints": 4,
        "duty_joint_female_min_constraints": 1,
        "duty_joint_female_two_duty_constraints": 2,
        "duty_joint_male_gap_constraints": 6,
        "duty_joint_male_balance_constraints": 2,
        "duty_joint_noon_pm_mutex_constraints": 18,
        "duty_joint_noon_night_mutex_constraints": 18,
        "duty_joint_pm_consecutive_constraints": 18,
        "duty_joint_penalty_terms": 15,
    }
    assert metadata["linear_constraint_count"] == 89
    assert len(metadata["noon_count_variable_names"]) == 3
    assert len(metadata["night_count_variable_names"]) == 3
    assert len(metadata["total_count_variable_names"]) == 3
    assert len(metadata["female_extra_total_variable_names"]) == 1
    assert len(metadata["male_target_over_variable_names"]) == 2
    assert len(metadata["male_target_under_variable_names"]) == 2
    assert len(metadata["male_no_night_variable_names"]) == 1
    assert len(metadata["female_min_miss_variable_names"]) == 1
    assert len(metadata["female_two_duty_hit_variable_names"]) == 1
    assert len(metadata["male_balance_dev_variable_names"]) == 2
    assert len(metadata["noon_any_variable_names"]) == 9
    assert len(metadata["night_any_variable_names"]) == 9
    assert len(metadata["pm_consecutive_violation_variable_names"]) == 6

    legacy_model = create_existing_cp_model("duty_joint.parity")
    legacy_noon_male = {
        key: legacy_model.NewBoolVar(name)
        for key, name in noon_male_names.items()
    }
    legacy_noon_female = {
        key: legacy_model.NewBoolVar(name)
        for key, name in noon_female_names.items()
    }
    legacy_pm = {key: legacy_model.NewBoolVar(name) for key, name in pm_names.items()}
    legacy_night_male = {
        key: legacy_model.NewBoolVar(name)
        for key, name in night_male_names.items()
    }
    legacy_night_female = {
        key: legacy_model.NewBoolVar(name)
        for key, name in night_female_names.items()
    }
    with ai_or_model_rule_context(
        "joint.link.duty_joint_constraints",
        source="scheduler.model.constraints.duty_joint_constraints",
    ):
        legacy_penalties, legacy_info = add_duty_joint_constraints(
            legacy_model,
            days=days,
            noon_male_duty=legacy_noon_male,
            noon_female_duty=legacy_noon_female,
            pm_pre_class_duty=legacy_pm,
            night_dorm_duty_male=legacy_night_male,
            night_dorm_duty_female=legacy_night_female,
            male_heads=male_heads,
            female_heads=female_heads,
            cfg=cfg,
        )
    legacy_summary = summarize_existing_cp_model_operations_by_rule(legacy_model)
    assert legacy_info["M_MAIN"] == male_heads
    assert legacy_info["F_MAIN"] == female_heads
    assert len(legacy_penalties) == metadata["constraint_family_counts"]["duty_joint_penalty_terms"]
    expected_operations = {
        "Add": metadata["linear_constraint_count"],
        "NewBoolVar": (
            len(metadata["male_no_night_variable_names"])
            + len(metadata["female_two_duty_hit_variable_names"])
            + len(metadata["pm_consecutive_violation_variable_names"])
        ),
        "NewIntVar": (
            len(metadata["noon_count_variable_names"])
            + len(metadata["night_count_variable_names"])
            + len(metadata["total_count_variable_names"])
            + len(metadata["female_extra_total_variable_names"])
            + len(metadata["male_target_over_variable_names"])
            + len(metadata["male_target_under_variable_names"])
            + len(metadata["female_min_miss_variable_names"])
            + len(metadata["male_gap_variable_names"])
            + len(metadata["male_balance_dev_variable_names"])
            + len(metadata["noon_any_variable_names"])
            + len(metadata["night_any_variable_names"])
        ),
    }
    if metadata["constant_variable_count"]:
        expected_operations["NewConstant"] = metadata["constant_variable_count"]
    assert legacy_summary["joint.link.duty_joint_constraints"]["operations"] == expected_operations

    expected_terms = {
        **{name: 23 for name in metadata["male_target_over_variable_names"].values()},
        **{name: 23 for name in metadata["male_target_under_variable_names"].values()},
        **{name: 29 for name in metadata["female_min_miss_variable_names"].values()},
        **{name: 31 for name in metadata["female_two_duty_hit_variable_names"].values()},
        metadata["male_gap_excess_variable_name"]: 37,
        **{name: 41 for name in metadata["male_balance_dev_variable_names"].values()},
        **{name: 43 for name in metadata["pm_consecutive_violation_variable_names"].values()},
    }
    assert {
        (term.variable, term.coefficient)
        for term in bridge.problem.objective.expression.terms
    } == set(expected_terms.items())

    solution = solve_cp_sat_problem(bridge.problem, time_limit_seconds=5)

    assert solution.status_name in {"OPTIMAL", "FEASIBLE"}


def test_generic_scheduler_rule_ids_exposes_real_duty_joint_coverage() -> None:
    covered_rule_ids = generic_scheduler_rule_ids()

    assert "day.duty_joint_constraints" in covered_rule_ids
    assert "joint.link.duty_joint_constraints" in covered_rule_ids


def _soft_objective_fixture() -> tuple[tuple[str, ...], tuple[str, ...], dict, list[str], list[str], list[str], dict]:
    days = ("星期五", "星期日", "星期一")
    periods = ("晚自习1", "晚自习2")
    cst = {
        ("class_a", "数学"): "teacher_m1",
        ("class_b", "物理"): "teacher_m2",
        ("class_c", "历史"): "teacher_f1",
    }
    all_teachers = ["teacher_m1", "teacher_m2", "teacher_f1"]
    male_heads = ["teacher_m1", "teacher_m2"]
    female_heads = ["teacher_f1"]
    rules = {
        "soft": {
            "enabled": True,
            "weights": {
                "miss_head_on": 7,
                "adjacent_teacher": 11,
                "checkin_repeat": 13,
                "sun_mon_teacher": 17,
            },
        },
        "evening_constraints": {
            "enabled": True,
            "enable_fri_sun_mutex": True,
            "fri_sun_mutex_mode": "soft",
            "fri_sun_mutex_weight": 19,
            "enable_yk_xxc_fri_mutex": True,
            "yk_xxc_fri_mutex_mode": "soft",
            "yk_xxc_fri_mutex_teachers": ["teacher_m1", "teacher_f1"],
            "yk_xxc_fri_mutex_weight": 23,
            "enable_double_class_weekday_p1_p2_split": False,
            "enable_subject_sync": True,
            "enable_physics_math_special": True,
            "weights": {
                "subject_sync": 29,
                "physics_fri_penalty": 31,
                "history_fri_penalty": 37,
                "math_zeng_fri_p1_penalty": 41,
                "math_zeng_fri_p2_penalty": 43,
            },
            "math_friday_allowed_teachers": ["teacher_m1"],
        },
    }
    return days, periods, cst, all_teachers, male_heads, female_heads, rules


def test_night_soft_objective_generic_contract_matches_legacy_penalty_shape() -> None:
    days, periods, cst, all_teachers, male_heads, female_heads, rules = _soft_objective_fixture()
    on_names = {(teacher, day): f"on[{teacher},{day}]" for teacher in all_teachers for day in days}
    y_names = {
        (cls, subj, day, period): f"y[{cls},{subj},{day},{period}]"
        for (cls, subj) in cst
        for day in days
        for period in periods
    }
    checkin_m_names = {(teacher, day): f"checkin_m[{teacher},{day}]" for teacher in male_heads for day in days}
    checkin_f_names = {(teacher, day): f"checkin_f[{teacher},{day}]" for teacher in female_heads for day in days}

    bridge = night_soft_objective_to_ai_or_problem(
        days=days,
        periods=periods,
        cst=cst,
        all_teachers=all_teachers,
        male_heads=male_heads,
        female_heads=female_heads,
        rules=rules,
        on_teacher_day_variable_names=on_names,
        y_variable_names=y_names,
        checkin_m_variable_names=checkin_m_names,
        checkin_f_variable_names=checkin_f_names,
    )

    assert bridge.problem.problem_id == "scheduler_night_soft_objective"
    assert tuple(rule.rule_id for rule in bridge.problem.rules) == ("joint.night.soft_objective",)
    assert bridge.problem.objective is not None
    metadata = bridge.metadata_by_rule["joint.night.soft_objective"]
    assert metadata["generic_contract_status"] == "covered_by_generic_contract"
    assert metadata["legacy_apply_fn"] == "apply_soft_objective"
    assert metadata["constraint_family_counts"] == {
        "night_soft_miss_head_constraints": 12,
        "night_soft_adjacent_teacher_constraints": 18,
        "night_soft_sun_mon_constraints": 9,
        "night_soft_fri_sun_mutex_constraints": 9,
        "night_soft_yk_xxc_fri_mutex_constraints": 3,
        "night_soft_checkin_repeat_constraints": 6,
        "night_soft_subject_sync_constraints": 36,
        "night_soft_penalty_terms": 46,
    }
    assert metadata["linear_constraint_count"] == 93
    assert len(metadata["miss_head_variable_names"]) == 6
    assert len(metadata["adjacent_teacher_variable_names"]) == 6
    assert len(metadata["sun_mon_variable_names"]) == 3
    assert len(metadata["fri_sun_mutex_variable_names"]) == 3
    assert len(metadata["yk_xxc_fri_mutex_variable_names"]) == 1
    assert len(metadata["checkin_repeat_variable_names"]) == 3
    assert len(metadata["subject_sync_variable_names"]) == 18
    assert len(metadata["physics_math_direct_penalty_terms"]) == 6

    legacy_model = create_existing_cp_model("night.soft_objective.parity")
    legacy_on = {key: legacy_model.NewBoolVar(name) for key, name in on_names.items()}
    legacy_y = {key: legacy_model.NewBoolVar(name) for key, name in y_names.items()}
    legacy_checkin_m = {key: legacy_model.NewBoolVar(name) for key, name in checkin_m_names.items()}
    legacy_checkin_f = {key: legacy_model.NewBoolVar(name) for key, name in checkin_f_names.items()}
    with ai_or_model_rule_context(
        "joint.night.soft_objective",
        source="scheduler.model.constraints.soft_objective",
    ):
        legacy_penalties = apply_soft_objective(
            legacy_model,
            {
                "on_teacher_day": legacy_on,
                "y": legacy_y,
                "all_teachers": all_teachers,
                "checkin_m": legacy_checkin_m,
                "checkin_f": legacy_checkin_f,
            },
            {
                "days": list(days),
                "periods": list(periods),
                "cst": cst,
                "male_heads": male_heads,
                "female_heads": female_heads,
            },
            rules,
            set_objective=False,
        )
    legacy_summary = summarize_existing_cp_model_operations_by_rule(legacy_model)
    assert len(legacy_penalties) == metadata["constraint_family_counts"]["night_soft_penalty_terms"]
    assert legacy_summary["joint.night.soft_objective"]["operations"] == {
        "Add": metadata["linear_constraint_count"],
        "NewBoolVar": (
            len(metadata["miss_head_variable_names"])
            + len(metadata["adjacent_teacher_variable_names"])
            + len(metadata["sun_mon_variable_names"])
            + len(metadata["fri_sun_mutex_variable_names"])
            + len(metadata["yk_xxc_fri_mutex_variable_names"])
            + len(metadata["checkin_repeat_variable_names"])
            + len(metadata["subject_sync_variable_names"])
        ),
    }

    expected_terms = {
        **{name: 7 for name in metadata["miss_head_variable_names"].values()},
        **{name: 11 for name in metadata["adjacent_teacher_variable_names"].values()},
        **{name: 17 for name in metadata["sun_mon_variable_names"].values()},
        **{name: 19 for name in metadata["fri_sun_mutex_variable_names"].values()},
        **{name: 23 for name in metadata["yk_xxc_fri_mutex_variable_names"].values()},
        **{name: 13 for name in metadata["checkin_repeat_variable_names"].values()},
        **{name: 29 for name in metadata["subject_sync_variable_names"].values()},
        **metadata["physics_math_direct_penalty_terms"],
    }
    assert {
        (term.variable, term.coefficient)
        for term in bridge.problem.objective.expression.terms
    } == set(expected_terms.items())

    solution = solve_cp_sat_problem(bridge.problem, time_limit_seconds=5)

    assert solution.status_name == "OPTIMAL"


def test_generic_scheduler_rule_ids_exposes_real_night_soft_objective_coverage() -> None:
    covered_rule_ids = generic_scheduler_rule_ids()

    assert "night.soft_objective" in covered_rule_ids
    assert "joint.night.soft_objective" in covered_rule_ids


def _morning_reading_day_input() -> DayInputData:
    slots = [
        Slot(day="星期一", block="早自习", period=1),
        Slot(day="星期二", block="早自习", period=1),
        Slot(day="星期三", block="早自习", period=1),
        Slot(day="星期四", block="早自习", period=1),
    ]
    return DayInputData(
        classes=["class_a"],
        cls_subj_teacher={
            ("class_a", "math"): "teacher_1",
            ("class_a", "reading"): "teacher_2",
        },
        available_slots=slots,
        fixed_assign={},
        req_hours={
            ("class_a", "math"): (2, 0, 0),
            ("class_a", "reading"): (2, 0, 0),
        },
        subject_ban_slots={},
    )


def test_day_morning_reading_generic_contract_matches_legacy_shape() -> None:
    data = _morning_reading_day_input()

    bridge = day_morning_reading_to_ai_or_problem(data)

    assert bridge.problem.problem_id == "scheduler_day_morning_reading_constraints"
    assert tuple(rule.rule_id for rule in bridge.problem.rules) == ("joint.day.morning_reading_constraints",)
    assert len(bridge.problem.variables) == len(data.cls_subj_teacher) * len(data.available_slots)
    assert len(bridge.problem.constraints) == 6
    assert (
        bridge.metadata_by_rule["joint.day.morning_reading_constraints"]["generic_contract_status"]
        == "covered_by_generic_contract"
    )
    assert all(constraint.sense == "<=" and constraint.rhs == 1 for constraint in bridge.problem.constraints)
    assert all(len(constraint.expression.terms) == 2 for constraint in bridge.problem.constraints)

    legacy_model = create_existing_cp_model("day.morning_reading.parity")
    legacy_vars = build_day_variables(legacy_model, data)
    with ai_or_model_rule_context(
        "joint.day.morning_reading_constraints",
        source="scheduler.day_constraints_morning_reading",
    ):
        apply_morning_reading_constraints(legacy_model, data, legacy_vars)
    legacy_summary = summarize_existing_cp_model_operations_by_rule(legacy_model)
    assert legacy_summary["joint.day.morning_reading_constraints"]["operations"] == {
        "Add": len(bridge.problem.constraints),
    }

    solution = solve_cp_sat_problem(bridge.problem, time_limit_seconds=5)

    assert solution.status_name == "OPTIMAL"


def test_generic_scheduler_rule_ids_exposes_real_day_morning_reading_coverage() -> None:
    covered_rule_ids = generic_scheduler_rule_ids()

    assert "joint.day.morning_reading_constraints" in covered_rule_ids


def _weekend_whitelist_day_input() -> DayInputData:
    weekday = Slot(day="星期一", block="上午", period=1)
    saturday = Slot(day="星期六", block="上午", period=1)
    sunday = Slot(day="星期日", block="上午", period=1)
    return DayInputData(
        classes=["class_a"],
        cls_subj_teacher={
            ("class_a", "语文"): "teacher_1",
            ("class_a", "数学"): "teacher_2",
            ("class_a", "外语"): "teacher_3",
        },
        available_slots=[weekday, saturday, sunday],
        fixed_assign={},
        req_hours={
            ("class_a", "语文"): (0, 1, 1),
            ("class_a", "数学"): (0, 1, 1),
            ("class_a", "外语"): (0, 1, 1),
        },
        subject_ban_slots={},
    )


def test_day_weekend_subject_whitelist_generic_contract_matches_legacy_shape() -> None:
    data = _weekend_whitelist_day_input()

    bridge = day_weekend_subject_whitelist_to_ai_or_problem(data)

    assert bridge.problem.problem_id == "scheduler_day_weekend_subject_whitelist"
    assert tuple(rule.rule_id for rule in bridge.problem.rules) == ("joint.day.weekend_subject_whitelist",)
    assert len(bridge.problem.variables) == len(data.cls_subj_teacher) * len(data.available_slots)
    assert len(bridge.problem.constraints) == 3
    assert (
        bridge.metadata_by_rule["joint.day.weekend_subject_whitelist"]["generic_contract_status"]
        == "covered_by_generic_contract"
    )
    assert all(constraint.sense == "==" and constraint.rhs == 0 for constraint in bridge.problem.constraints)
    assert all(len(constraint.expression.terms) == 1 for constraint in bridge.problem.constraints)

    legacy_model = create_existing_cp_model("day.weekend_subject_whitelist.parity")
    legacy_vars = build_day_variables(legacy_model, data)
    with ai_or_model_rule_context(
        "joint.day.weekend_subject_whitelist",
        source="scheduler.model.constraints.day_weekend_constraints",
    ):
        apply_weekend_subject_whitelist(legacy_model, data, legacy_vars)
    legacy_summary = summarize_existing_cp_model_operations_by_rule(legacy_model)
    assert legacy_summary["joint.day.weekend_subject_whitelist"]["operations"] == {
        "Add": len(bridge.problem.constraints),
    }

    solution = solve_cp_sat_problem(bridge.problem, time_limit_seconds=5)

    assert solution.status_name == "OPTIMAL"
    blocked = bridge.metadata_by_rule["joint.day.weekend_subject_whitelist"]["blocked_assignment_variable_names"]
    assert set(blocked) == {
        "class_a|语文|星期六|上午1",
        "class_a|外语|星期六|上午1",
        "class_a|数学|星期日|上午1",
    }
    assert all(solution.values[name] == 0 for name in blocked.values())


def test_generic_scheduler_rule_ids_exposes_real_day_weekend_subject_whitelist_coverage() -> None:
    covered_rule_ids = generic_scheduler_rule_ids()

    assert "joint.day.weekend_subject_whitelist" in covered_rule_ids


def _weekend_one_day_only_day_input() -> DayInputData:
    saturday = Slot(day="星期六", block="上午", period=1)
    sunday = Slot(day="星期日", block="上午", period=1)
    return DayInputData(
        classes=["class_a", "class_b"],
        cls_subj_teacher={
            ("class_a", "math"): "teacher_1",
            ("class_a", "science"): "teacher_2",
            ("class_b", "math"): "teacher_1",
        },
        available_slots=[saturday, sunday],
        fixed_assign={},
        req_hours={
            ("class_a", "math"): (0, 0, 1),
            ("class_a", "science"): (0, 0, 1),
            ("class_b", "math"): (0, 0, 1),
        },
        subject_ban_slots={},
    )


def test_day_weekend_one_day_only_generic_contract_matches_legacy_shape() -> None:
    data = _weekend_one_day_only_day_input()

    bridge = day_weekend_one_day_only_to_ai_or_problem(data)

    assert bridge.problem.problem_id == "scheduler_day_weekend_one_day_only"
    assert tuple(rule.rule_id for rule in bridge.problem.rules) == ("joint.day.weekend_one_day_only",)
    assert len(bridge.problem.variables) == 16
    assert len(bridge.problem.constraints) == 18
    assert (
        bridge.metadata_by_rule["joint.day.weekend_one_day_only"]["generic_contract_status"]
        == "covered_by_generic_contract"
    )

    metadata = bridge.metadata_by_rule["joint.day.weekend_one_day_only"]
    assert len(metadata["teacher_class_slot_variable_names"]) == 6
    assert set(metadata["teacher_weekend_day_variable_names"]) == {
        "teacher_1|星期六",
        "teacher_1|星期日",
        "teacher_2|星期六",
        "teacher_2|星期日",
    }
    assert metadata["constraint_family_counts"] == {
        "teacher_class_slot_bool_equalities": 6,
        "teacher_slot_implies_weekend_day": 6,
        "weekend_day_bool_lower_bounds": 4,
        "teacher_weekend_one_day_only": 2,
    }

    legacy_model = create_existing_cp_model("day.weekend_one_day_only.parity")
    legacy_vars = build_day_variables(legacy_model, data)
    with ai_or_model_rule_context(
        "joint.day.weekend_one_day_only",
        source="scheduler.model.constraints.day_weekend_constraints",
    ):
        apply_weekend_one_day_only(legacy_model, data, legacy_vars)
    legacy_summary = summarize_existing_cp_model_operations_by_rule(legacy_model)
    assert legacy_summary["joint.day.weekend_one_day_only"]["operations"] == {
        "Add": len(bridge.problem.constraints),
        "NewBoolVar": 10,
    }

    solution = solve_cp_sat_problem(bridge.problem, time_limit_seconds=5)

    assert solution.status_name == "OPTIMAL"
    day_names = metadata["teacher_weekend_day_variable_names"]
    for teacher in ("teacher_1", "teacher_2"):
        assert (
            solution.values[day_names[f"{teacher}|星期六"]]
            + solution.values[day_names[f"{teacher}|星期日"]]
            <= 1
        )


def test_generic_scheduler_rule_ids_exposes_real_day_weekend_one_day_only_coverage() -> None:
    covered_rule_ids = generic_scheduler_rule_ids()

    assert "joint.day.weekend_one_day_only" in covered_rule_ids


def _weekend_halfday_day_input() -> DayInputData:
    saturday_am = Slot(day="星期六", block="上午", period=1)
    saturday_pm = Slot(day="星期六", block="下午", period=1)
    sunday_am = Slot(day="星期日", block="上午", period=1)
    return DayInputData(
        classes=["class_a"],
        cls_subj_teacher={
            ("class_a", "math"): "teacher_1",
            ("class_a", "science"): "teacher_2",
        },
        available_slots=[saturday_am, saturday_pm, sunday_am],
        fixed_assign={("class_a", saturday_pm): "science"},
        req_hours={
            ("class_a", "math"): (0, 0, 1),
            ("class_a", "science"): (0, 0, 1),
        },
        subject_ban_slots={},
    )


def test_day_weekend_halfday_generic_contract_matches_legacy_shape() -> None:
    data = _weekend_halfday_day_input()

    bridge = day_weekend_halfday_constraint_to_ai_or_problem(data)

    assert bridge.problem.problem_id == "scheduler_day_weekend_halfday_constraint"
    assert tuple(rule.rule_id for rule in bridge.problem.rules) == ("joint.day.weekend_halfday_constraint",)
    assert len(bridge.problem.variables) == 16
    assert len(bridge.problem.constraints) == 20
    assert (
        bridge.metadata_by_rule["joint.day.weekend_halfday_constraint"]["generic_contract_status"]
        == "covered_by_generic_contract"
    )

    metadata = bridge.metadata_by_rule["joint.day.weekend_halfday_constraint"]
    assert metadata["constraint_family_counts"] == {
        "teacher_class_slot_bool_equalities": 4,
        "has_am_lower_bounds": 4,
        "teacher_slot_implies_has_am": 4,
        "has_pm_fixed_or_zero_or_lower_bounds": 4,
        "teacher_weekend_halfday_hard_mutex": 4,
    }
    assert len(metadata["teacher_class_slot_variable_names"]) == 4
    assert set(metadata["teacher_halfday_variable_names"]) == {
        "teacher_1|星期六|am",
        "teacher_1|星期六|pm",
        "teacher_1|星期日|am",
        "teacher_1|星期日|pm",
        "teacher_2|星期六|am",
        "teacher_2|星期六|pm",
        "teacher_2|星期日|am",
        "teacher_2|星期日|pm",
    }

    legacy_model = create_existing_cp_model("day.weekend_halfday.parity")
    legacy_vars = build_day_variables(legacy_model, data)
    with ai_or_model_rule_context(
        "joint.day.weekend_halfday_constraint",
        source="scheduler.model.constraints.day_weekend_constraints",
    ):
        apply_weekend_halfday_constraint(legacy_model, data, legacy_vars, mode="hard")
    legacy_summary = summarize_existing_cp_model_operations_by_rule(legacy_model)
    assert legacy_summary["joint.day.weekend_halfday_constraint"]["operations"] == {
        "Add": len(bridge.problem.constraints),
        "NewBoolVar": 12,
    }

    solution = solve_cp_sat_problem(bridge.problem, time_limit_seconds=5)

    assert solution.status_name == "OPTIMAL"
    assignment_names = metadata["assignment_variable_names"]
    assert solution.values[assignment_names["class_a|science|星期六|上午1"]] == 0


def test_generic_scheduler_rule_ids_exposes_real_day_weekend_halfday_coverage() -> None:
    covered_rule_ids = generic_scheduler_rule_ids()

    assert "day.weekend_halfday_constraint" in covered_rule_ids
    assert "joint.day.weekend_halfday_constraint" in covered_rule_ids
