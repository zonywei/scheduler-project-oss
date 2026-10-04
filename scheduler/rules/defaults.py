# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from scheduler.model.constraints.checkin import apply_checkin
from scheduler.model.constraints.day_weekday_constraints import (
    apply_am1_pm1_exclusive,
    apply_am1_pm1_mutex,
    apply_single_class_weekly_am1_cap,
    apply_two_class_am1_pm1_combo,
)
from scheduler.model.constraints.day_weekend_constraints import apply_weekend_halfday_constraint
from scheduler.model.constraints.global_binding_constraints import (
    apply_global_day_binding_8_chem_9_bio,
    apply_global_night_binding_8_chem_9_bio,
)
from scheduler.model.constraints.hard_bans import apply_hard_bans
from scheduler.model.constraints.hard_base import apply_hard_base
from scheduler.model.constraints.hard_teacher_limits import apply_hard_teacher_limits
from scheduler.model.constraints.night_single_class_period_split import (
    apply_double_class_teacher_weekday_alternate_p1_p2,
    apply_single_class_teacher_p1_p2_split,
)
from scheduler.model.constraints.night_special import (
    apply_fri_sun_mutex,
    apply_physics_math_hard_bans,
)
from scheduler.model.constraints.personalized_constraints import apply_personalized_constraints
from scheduler.model.constraints.soft_objective import apply_soft_objective
from scheduler.rules.personalized_legacy import PERSONALIZED_LEGACY_RULES, personalized_template_id
from scheduler.rules.mandatory import MANDATORY_DEFAULT_RULES
from scheduler.rules.registry import RuleRegistry
from scheduler.rules.spec import RuleSpec


@dataclass(frozen=True)
class RuleBinding:
    symbol: str
    rule_id: str
    stage: str
    order: int
    category_path: str
    config_key: str
    default_mode: str = "hard"
    default_weight: float | int | None = None
    tags: tuple[str, ...] = ()
    enabled_path: str | None = None
    mode_path: str | None = None
    weight_path: str | None = None
    explanation_template: str = ""


MODULE_RULE_BINDINGS: dict[str, tuple[RuleBinding, ...]] = {
    "scheduler.main": (
        RuleBinding("apply_hard_base", "night.hard_base", "constraints", 1, "night/hard/base", "calendar,evening", tags=("night", "joint"), explanation_template="Night hard base constraints."),
        RuleBinding("apply_hard_bans", "night.hard_bans", "constraints", 2, "night/hard/bans", "hard_bans", tags=("night", "joint"), enabled_path="hard_bans.enabled", explanation_template="Night hard bans."),
        RuleBinding("apply_hard_teacher_limits", "night.hard_teacher_limits", "constraints", 3, "night/hard/teacher_limits", "hard_teacher_limits", tags=("night", "joint"), explanation_template="Night teacher hard limits."),
        RuleBinding("apply_global_night_binding_8_chem_9_bio", "night.binding_8chem_9bio", "constraints", 4, "night/hard/binding", "evening_constraints", tags=("night", "joint"), explanation_template="Night binding rule for class/subject."),
        RuleBinding("apply_physics_math_hard_bans", "night.physics_math_special", "constraints", 5, "night/hard_or_soft/subject_special", "evening_constraints", tags=("night", "joint"), enabled_path="evening_constraints.enable_physics_math_special", explanation_template="Night physics/math special rule."),
        RuleBinding("apply_fri_sun_mutex", "night.fri_sun_mutex", "constraints", 6, "night/hard_or_soft/date_mutex", "evening_constraints", tags=("night", "joint"), enabled_path="evening_constraints.enable_fri_sun_mutex", mode_path="evening_constraints.fri_sun_mutex_mode", weight_path="evening_constraints.fri_sun_mutex_weight", default_weight=20000, explanation_template="Night Fri/Sun mutex."),
        RuleBinding("apply_single_class_teacher_p1_p2_split", "night.single_class_p1_p2_split", "constraints", 7, "night/hard_or_soft/period_split", "evening_constraints", tags=("night", "joint"), enabled_path="evening_constraints.enable_single_class_p1_p2_split", explanation_template="Night single-class p1/p2 split."),
        RuleBinding("apply_double_class_teacher_weekday_alternate_p1_p2", "night.double_class_weekday_p1_p2_split", "constraints", 8, "night/hard_or_soft/period_split", "evening_constraints", tags=("night", "joint"), enabled_path="evening_constraints.enable_double_class_weekday_p1_p2_split", mode_path="evening_constraints.double_class_weekday_p1_p2_mode", weight_path="evening_constraints.double_class_weekday_p1_p2_weight", default_weight=1000, explanation_template="Night double-class weekday p1/p2 split."),
        RuleBinding("apply_checkin", "night.checkin", "constraints", 9, "night/hard_or_soft/checkin", "checkin", tags=("night", "joint"), enabled_path="checkin.enabled", explanation_template="Night checkin constraints."),
        RuleBinding("apply_soft_objective", "night.soft_objective", "objective_post", 10, "night/soft/objective", "soft,evening_constraints", tags=("night", "joint"), default_mode="soft", enabled_path="soft.enabled", explanation_template="Night soft objective."),
        RuleBinding("apply_personalized_constraints", "night.personalized_constraints", "constraints", 11, "shared/personalized", "personalized_constraints", tags=("night", "day", "joint"), enabled_path="personalized_constraints.enabled", explanation_template="Night personalized constraints."),
        RuleBinding("apply_night_solver_parameters", "night.solver_parameters", "objective_post", 12, "night/solver/parameters", "solve", tags=("night", "joint"), explanation_template="Night solver parameter application."),
    ),
    "scheduler.day_schedule_entry": (
        RuleBinding("apply_personalized_constraints", "day.personalized_constraints", "constraints", 1, "shared/personalized", "personalized_constraints", tags=("day", "joint", "night"), enabled_path="personalized_constraints.enabled", explanation_template="Day personalized constraints."),
        RuleBinding("add_duty_joint_constraints", "day.duty_joint_constraints", "constraints", 2, "day/duty/joint", "day.duty_joint_constraints", tags=("day", "joint"), explanation_template="Day duty joint constraints."),
        RuleBinding("apply_joint_solver_parameters", "day.solver_parameters", "objective_post", 3, "day/solver/parameters", "joint_solve", tags=("day", "joint"), explanation_template="Day solver parameter application."),
    ),
    "scheduler.joint_solver": (
        RuleBinding("apply_one_subject_per_slot", "joint.day.one_subject_per_slot", "constraints", 1, "joint/day/hard", "day_constraints", tags=("joint", "day")),
        RuleBinding("apply_subject_hour_constraints", "joint.day.subject_hour_constraints", "constraints", 2, "joint/day/hard", "day_constraints", tags=("joint", "day")),
        RuleBinding("apply_teacher_no_conflict", "joint.day.teacher_no_conflict", "constraints", 3, "joint/day/hard", "day_constraints", tags=("joint", "day")),
        RuleBinding("apply_morning_reading_constraints", "joint.day.morning_reading_constraints", "constraints", 4, "joint/day/hard", "day_constraints", tags=("joint", "day")),
        RuleBinding("apply_weekend_subject_whitelist", "joint.day.weekend_subject_whitelist", "constraints", 5, "joint/day/weekend", "day_constraints", tags=("joint", "day")),
        RuleBinding("apply_weekend_double_period_same_class", "joint.day.weekend_double_period_same_class", "constraints", 6, "joint/day/weekend", "day_constraints", tags=("joint", "day")),
        RuleBinding("apply_weekend_one_day_only", "joint.day.weekend_one_day_only", "constraints", 7, "joint/day/weekend", "day_constraints", tags=("joint", "day")),
        RuleBinding("apply_weekend_cross_halfday_penalty", "joint.day.weekend_cross_halfday_penalty", "constraints", 8, "joint/day/weekend", "day_constraints", default_mode="soft", tags=("joint", "day")),
        RuleBinding("apply_weekend_halfday_constraint", "joint.day.weekend_halfday_constraint", "constraints", 9, "joint/day/weekend", "day_constraints", tags=("joint", "day"), enabled_path="day_constraints.enable_weekend_halfday_constraint", mode_path="day_constraints.weekend_halfday_mode", weight_path="day_constraints.w_weekend_halfday", default_weight=3000),
        RuleBinding("apply_yjc_sunday_am12_pm12_rule", "joint.day.yjc_sunday_am12_pm12_rule", "constraints", 10, "joint/day/weekend", "day_constraints", tags=("joint", "day")),
        RuleBinding("apply_global_day_binding_8_chem_9_bio", "joint.day.binding_8chem_9bio", "constraints", 11, "joint/day/hard", "day_constraints", tags=("joint", "day")),
        RuleBinding("apply_no_am1_am4", "joint.day.no_am1_am4", "constraints", 12, "joint/day/hard", "day_constraints", tags=("joint", "day")),
        RuleBinding("apply_core_subject_teacher_day_load_and_no_am1_am4", "joint.day.core_subject_teacher_day_load_no_am1_am4", "constraints", 13, "joint/day/hard", "day_constraints", tags=("joint", "day")),
        RuleBinding("apply_no_consecutive_same_teacher_same_class", "joint.day.no_consecutive_same_teacher_same_class", "constraints", 14, "joint/day/hard", "day_constraints", tags=("joint", "day")),
        RuleBinding("apply_head_pm1_min", "joint.day.head_pm1_min", "constraints", 15, "joint/day/head_duty", "day_constraints", tags=("joint", "day")),
        RuleBinding("apply_teacher_weekday_am_pm_presence", "joint.day.teacher_weekday_am_pm_presence", "constraints", 16, "joint/day/head_duty", "day_constraints", tags=("joint", "day")),
        RuleBinding("apply_am1_pm1_mutex", "joint.day.am1_pm1_mutex", "constraints", 17, "joint/day/period_combo", "day_constraints", tags=("joint", "day"), enabled_path="day_constraints.enable_am1_pm1_mutex", mode_path="day_constraints.am1_pm1_mutex_mode", weight_path="day_constraints.w_am1_pm1_mutex", default_weight=3000),
        RuleBinding("apply_two_class_am1_pm1_combo", "joint.day.two_class_am1_pm1_combo", "constraints", 18, "joint/day/period_combo", "day_constraints", tags=("joint", "day"), enabled_path="day_constraints.enable_two_class_am1_pm1_combo", mode_path="day_constraints.two_class_am1_pm1_combo_mode", weight_path="day_constraints.w_two_class_am1_pm1_combo", default_weight=3000),
        RuleBinding("apply_am1_pm1_exclusive", "joint.day.am1_pm1_exclusive", "constraints", 19, "joint/day/period_combo", "day_constraints", tags=("joint", "day"), enabled_path="day_constraints.enable_am1_pm1_exclusive", mode_path="day_constraints.am1_pm1_exclusive_mode", weight_path="day_constraints.w_am1_pm1_exclusive", default_weight=3000),
        RuleBinding("apply_single_class_weekly_am1_cap", "joint.day.single_class_weekly_am1_cap", "constraints", 20, "joint/day/limits", "day_constraints", tags=("joint", "day"), enabled_path="day_constraints.enable_single_class_weekly_am1_cap"),
        RuleBinding("apply_two_class_low_hours_max_empty_days", "joint.day.two_class_low_hours_max_empty_days", "constraints", 21, "joint/day/workload", "day_constraints", tags=("joint", "day")),
        RuleBinding("apply_low_weekday_subject_max1_per_day", "joint.day.low_weekday_subject_max1_per_day", "constraints", 22, "joint/day/workload", "day_constraints", tags=("joint", "day")),
        RuleBinding("apply_high_weekday_subject_min1_per_day", "joint.day.high_weekday_subject_min1_per_day", "constraints", 23, "joint/day/workload", "day_constraints", tags=("joint", "day")),
        RuleBinding("apply_head_duty_constraints", "joint.day.head_duty_constraints", "constraints", 24, "joint/day/head_duty", "day.head_duty", tags=("joint", "day")),
        RuleBinding("apply_noon_dorm_duty_constraints", "joint.day.noon_dorm_duty_constraints", "constraints", 25, "joint/day/noon_duty", "day.noon_dorm_duty", tags=("joint", "day")),
        RuleBinding("apply_pe_time_window_hard", "joint.day.pe_time_window_hard", "constraints", 26, "joint/day/pe", "day.pe", tags=("joint", "day")),
        RuleBinding("apply_teacher_whitelist_hard", "joint.day.teacher_whitelist_hard", "constraints", 27, "joint/day/teacher_whitelist", "day.pe", tags=("joint", "day")),
        RuleBinding("apply_multi_class_halfday_soft", "joint.day.multi_class_halfday_soft", "constraints", 29, "joint/day/soft/fairness", "day_constraints", default_mode="soft", tags=("joint", "day")),
        RuleBinding("apply_teacher_am4_pm1_threshold_penalty", "joint.day.teacher_am4_pm1_threshold_penalty", "constraints", 30, "joint/day/soft/load", "day_constraints", default_mode="soft", tags=("joint", "day")),
        RuleBinding("apply_pref_lang_am", "joint.day.pref_lang_am", "constraints", 31, "joint/day/soft/subject_pref", "day_constraints", default_mode="soft", tags=("joint", "day")),
        RuleBinding("apply_reduce_stem_am1", "joint.day.reduce_stem_am1", "constraints", 32, "joint/day/soft/subject_pref", "day_constraints", default_mode="soft", tags=("joint", "day")),
        RuleBinding("apply_teacher_am1_fragmentation", "joint.day.teacher_am1_fragmentation", "constraints", 33, "joint/day/soft/fragmentation", "day_constraints", default_mode="soft", tags=("joint", "day")),
        RuleBinding("apply_two_class_daily_min_per_class", "joint.day.two_class_daily_min_per_class", "constraints", 34, "joint/day/soft/workload", "day_constraints", default_mode="soft", tags=("joint", "day")),
        RuleBinding("apply_teacher_continuity_penalty", "joint.day.teacher_continuity_penalty", "constraints", 35, "joint/day/soft/continuity", "day_constraints", default_mode="soft", tags=("joint", "day")),
        RuleBinding("apply_teacher_m1_cap_constraint", "joint.day.teacher_m1_cap_constraint", "constraints", 36, "joint/day/soft/limits", "day_constraints", default_mode="soft", tags=("joint", "day")),
        RuleBinding("apply_weekday_subject_balance", "joint.day.weekday_subject_balance", "constraints", 37, "joint/day/soft/balance", "day_constraints", default_mode="soft", tags=("joint", "day")),
        RuleBinding("apply_pe_reduce_am_soft", "joint.day.pe_reduce_am_soft", "constraints", 38, "joint/day/soft/pe", "day_constraints", default_mode="soft", tags=("joint", "day")),
        RuleBinding("apply_pe_tech_compact_soft", "joint.day.pe_tech_compact_soft", "constraints", 39, "joint/day/soft/pe", "day_constraints", default_mode="soft", tags=("joint", "day")),
        RuleBinding("apply_hard_base", "joint.night.hard_base", "constraints", 101, "joint/night/hard/base", "calendar,evening", tags=("joint", "night")),
        RuleBinding("apply_hard_bans", "joint.night.hard_bans", "constraints", 102, "joint/night/hard/bans", "hard_bans", tags=("joint", "night")),
        RuleBinding("apply_hard_teacher_limits", "joint.night.hard_teacher_limits", "constraints", 103, "joint/night/hard/teacher_limits", "hard_teacher_limits", tags=("joint", "night")),
        RuleBinding("apply_global_night_binding_8_chem_9_bio", "joint.night.binding_8chem_9bio", "constraints", 104, "joint/night/hard/binding", "evening_constraints", tags=("joint", "night")),
        RuleBinding("apply_physics_math_hard_bans", "joint.night.physics_math_special", "constraints", 105, "joint/night/hard_or_soft/subject_special", "evening_constraints", tags=("joint", "night")),
        RuleBinding("apply_fri_sun_mutex", "joint.night.fri_sun_mutex", "constraints", 106, "joint/night/hard_or_soft/date_mutex", "evening_constraints", tags=("joint", "night")),
        RuleBinding("apply_single_class_teacher_p1_p2_split", "joint.night.single_class_p1_p2_split", "constraints", 107, "joint/night/hard_or_soft/period_split", "evening_constraints", tags=("joint", "night")),
        RuleBinding("apply_double_class_teacher_weekday_alternate_p1_p2", "joint.night.double_class_weekday_p1_p2_split", "constraints", 108, "joint/night/hard_or_soft/period_split", "evening_constraints", tags=("joint", "night")),
        RuleBinding("apply_checkin", "joint.night.checkin", "constraints", 109, "joint/night/hard_or_soft/checkin", "checkin", tags=("joint", "night")),
        RuleBinding("apply_soft_objective", "joint.night.soft_objective", "objective_post", 110, "joint/night/soft/objective", "soft,evening_constraints", default_mode="soft", tags=("joint", "night")),
        RuleBinding("add_duty_joint_constraints", "joint.link.duty_joint_constraints", "constraints", 201, "joint/link/duty", "day.duty_joint_constraints", tags=("joint",)),
        RuleBinding("apply_grade_group_duty_constraints", "joint.link.grade_group_duty_constraints", "constraints", 202, "joint/link/grade_group_duty", "day.grade_group_duty", tags=("joint",)),
        RuleBinding("apply_personalized_constraints", "joint.link.personalized_constraints", "constraints", 203, "joint/link/personalized", "personalized_constraints", tags=("joint",), enabled_path="personalized_constraints.enabled"),
        RuleBinding("apply_joint_solver_parameters", "joint.solver_parameters", "objective_post", 204, "joint/solver/parameters", "joint_solve", tags=("joint",)),
    ),
}


def get_module_rule_bindings(module_name: str) -> tuple[RuleBinding, ...]:
    return MODULE_RULE_BINDINGS.get(str(module_name), ())


def _register_core_specs(registry: RuleRegistry) -> None:
    core = [
        RuleSpec(
            rule_id="night.hard_base",
            name="晚自习基础硬约束",
            category_path="night/hard/base",
            stage="constraints",
            order=1,
            tags=("night", "joint"),
            default_mode="hard",
            config_key="calendar,evening",
            explanation_template="Night hard base constraints.",
            apply_fn=apply_hard_base,
        ),
        RuleSpec(
            rule_id="night.hard_bans",
            name="晚自习硬禁排",
            category_path="night/hard/bans",
            stage="constraints",
            order=2,
            tags=("night", "joint"),
            default_mode="hard",
            config_key="hard_bans",
            explanation_template="Night hard bans.",
            apply_fn=apply_hard_bans,
            enabled_path="hard_bans.enabled",
        ),
        RuleSpec(
            rule_id="night.hard_teacher_limits",
            name="晚自习教师上限",
            category_path="night/hard/teacher_limits",
            stage="constraints",
            order=3,
            tags=("night", "joint"),
            default_mode="hard",
            config_key="hard_teacher_limits",
            explanation_template="Night teacher hard limits.",
            apply_fn=apply_hard_teacher_limits,
        ),
        RuleSpec(
            rule_id="night.checkin",
            name="晚查寝约束",
            category_path="night/hard_or_soft/checkin",
            stage="constraints",
            order=9,
            tags=("night", "joint"),
            default_mode="hard",
            config_key="checkin",
            explanation_template="Night checkin constraints.",
            apply_fn=apply_checkin,
            enabled_path="checkin.enabled",
        ),
        RuleSpec(
            rule_id="night.soft_objective",
            name="晚自习软目标",
            category_path="night/soft/objective",
            stage="objective_post",
            order=10,
            tags=("night", "joint"),
            default_mode="soft",
            config_key="soft,evening_constraints",
            explanation_template="Night soft objective.",
            apply_fn=apply_soft_objective,
            enabled_path="soft.enabled",
        ),
        RuleSpec(
            rule_id="night.physics_math_special",
            name="物理数学特殊规则",
            category_path="night/hard_or_soft/subject_special",
            stage="constraints",
            order=5,
            tags=("night", "joint"),
            default_mode="hard",
            config_key="evening_constraints",
            explanation_template="Night physics/math special rule.",
            apply_fn=apply_physics_math_hard_bans,
            enabled_path="evening_constraints.enable_physics_math_special",
        ),
        RuleSpec(
            rule_id="night.fri_sun_mutex",
            name="周五周日晚自习互斥",
            category_path="night/hard_or_soft/date_mutex",
            stage="constraints",
            order=6,
            tags=("night", "joint"),
            default_mode="hard",
            default_weight=20000,
            config_key="evening_constraints",
            explanation_template="Night Fri/Sun mutex.",
            apply_fn=apply_fri_sun_mutex,
            enabled_path="evening_constraints.enable_fri_sun_mutex",
            mode_path="evening_constraints.fri_sun_mutex_mode",
            weight_path="evening_constraints.fri_sun_mutex_weight",
        ),
        RuleSpec(
            rule_id="night.binding_8chem_9bio",
            name="八化学九生物绑定",
            category_path="night/hard/binding",
            stage="constraints",
            order=4,
            tags=("night", "joint"),
            default_mode="hard",
            config_key="evening_constraints",
            explanation_template="Night binding rule for class/subject.",
            apply_fn=apply_global_night_binding_8_chem_9_bio,
        ),
        RuleSpec(
            rule_id="night.single_class_p1_p2_split",
            name="单班晚自习节次拆分",
            category_path="night/hard_or_soft/period_split",
            stage="constraints",
            order=7,
            tags=("night", "joint"),
            default_mode="hard",
            config_key="evening_constraints",
            explanation_template="Night single-class p1/p2 split.",
            apply_fn=apply_single_class_teacher_p1_p2_split,
            enabled_path="evening_constraints.enable_single_class_p1_p2_split",
        ),
        RuleSpec(
            rule_id="night.double_class_weekday_p1_p2_split",
            name="双班工作日节次拆分",
            category_path="night/hard_or_soft/period_split",
            stage="constraints",
            order=8,
            tags=("night", "joint"),
            default_mode="hard",
            default_weight=1000,
            config_key="evening_constraints",
            explanation_template="Night double-class weekday p1/p2 split.",
            apply_fn=apply_double_class_teacher_weekday_alternate_p1_p2,
            enabled_path="evening_constraints.enable_double_class_weekday_p1_p2_split",
            mode_path="evening_constraints.double_class_weekday_p1_p2_mode",
            weight_path="evening_constraints.double_class_weekday_p1_p2_weight",
        ),
        RuleSpec(
            rule_id="day.weekend_halfday_constraint",
            name="白天周末半天集中",
            category_path="day/hard_or_soft/weekend",
            stage="constraints",
            order=9,
            tags=("day", "joint"),
            default_mode="hard",
            default_weight=3000,
            config_key="day_constraints",
            explanation_template="Weekend halfday concentration.",
            apply_fn=apply_weekend_halfday_constraint,
            enabled_path="day_constraints.enable_weekend_halfday_constraint",
            mode_path="day_constraints.weekend_halfday_mode",
            weight_path="day_constraints.w_weekend_halfday",
        ),
        RuleSpec(
            rule_id="day.am1_pm1_mutex",
            name="AM1 PM1 组合约束",
            category_path="day/hard_or_soft/period_combo",
            stage="constraints",
            order=17,
            tags=("day", "joint"),
            default_mode="hard",
            default_weight=3000,
            config_key="day_constraints",
            explanation_template="AM1 PM1 mutex.",
            apply_fn=apply_am1_pm1_mutex,
            enabled_path="day_constraints.enable_am1_pm1_mutex",
            mode_path="day_constraints.am1_pm1_mutex_mode",
            weight_path="day_constraints.w_am1_pm1_mutex",
        ),
        RuleSpec(
            rule_id="day.two_class_am1_pm1_combo",
            name="双班 AM1 PM1 组合约束",
            category_path="day/hard_or_soft/period_combo",
            stage="constraints",
            order=18,
            tags=("day", "joint"),
            default_mode="hard",
            default_weight=3000,
            config_key="day_constraints",
            explanation_template="Two-class AM1 PM1 combo.",
            apply_fn=apply_two_class_am1_pm1_combo,
            enabled_path="day_constraints.enable_two_class_am1_pm1_combo",
            mode_path="day_constraints.two_class_am1_pm1_combo_mode",
            weight_path="day_constraints.w_two_class_am1_pm1_combo",
        ),
        RuleSpec(
            rule_id="day.am1_pm1_exclusive",
            name="AM1 PM1 互斥",
            category_path="day/hard_or_soft/period_combo",
            stage="constraints",
            order=19,
            tags=("day", "joint"),
            default_mode="hard",
            default_weight=3000,
            config_key="day_constraints",
            explanation_template="AM1 PM1 exclusive.",
            apply_fn=apply_am1_pm1_exclusive,
            enabled_path="day_constraints.enable_am1_pm1_exclusive",
            mode_path="day_constraints.am1_pm1_exclusive_mode",
            weight_path="day_constraints.w_am1_pm1_exclusive",
        ),
        RuleSpec(
            rule_id="day.single_class_weekly_am1_cap",
            name="单班每周 AM1 上限",
            category_path="day/hard/limits",
            stage="constraints",
            order=20,
            tags=("day", "joint"),
            default_mode="hard",
            config_key="day_constraints",
            explanation_template="Single-class weekly AM1 cap.",
            apply_fn=apply_single_class_weekly_am1_cap,
            enabled_path="day_constraints.enable_single_class_weekly_am1_cap",
        ),
        RuleSpec(
            rule_id="shared.personalized_constraints",
            name="个性化约束集合",
            category_path="shared/hard_or_soft/personalized",
            stage="constraints",
            order=200,
            tags=("day", "night", "joint"),
            default_mode="hard",
            config_key="personalized_constraints",
            explanation_template="Personalized constraints.",
            apply_fn=apply_personalized_constraints,
            enabled_path="personalized_constraints.enabled",
        ),
    ]
    for spec in core:
        registry.register(spec, overwrite=False)
    for offset, item in enumerate(MANDATORY_DEFAULT_RULES, start=1):
        registry.register(
            RuleSpec(
                rule_id=str(item["id"]),
                name=str(item["title"]),
                category_path=f"system/{item['business_domain']}/{item['rule_category']}",
                stage="input_validation" if item["enforcement"] == "input_validation" else "constraints",
                order=-100 + offset,
                tags=("joint", "day", "night"),
                default_mode="hard",
                config_key="system.mandatory_defaults",
                explanation_template=str(item["explanation"]),
                apply_fn=None,
                apply_fn_ref=" + ".join(item.get("solver_bindings") or ("mandatory_model_gate",)),
            ),
            overwrite=False,
        )


def _register_binding_specs(registry: RuleRegistry) -> None:
    for module_name, bindings in MODULE_RULE_BINDINGS.items():
        for b in bindings:
            if registry.get(b.rule_id) is not None:
                continue
            registry.register(
                RuleSpec(
                    rule_id=b.rule_id,
                    name=b.rule_id,
                    category_path=b.category_path,
                    stage=b.stage,
                    order=b.order,
                    tags=tuple(b.tags),
                    default_mode=b.default_mode,
                    default_weight=b.default_weight,
                    config_key=b.config_key,
                    explanation_template=b.explanation_template or b.rule_id,
                    apply_fn=None,
                    apply_fn_ref=b.symbol,
                    enabled_path=b.enabled_path,
                    mode_path=b.mode_path,
                    weight_path=b.weight_path,
                ),
                overwrite=False,
            )


def _register_personalized_legacy_specs(registry: RuleRegistry) -> None:
    for offset, rule in enumerate(PERSONALIZED_LEGACY_RULES, start=1):
        registry.register(
            RuleSpec(
                rule_id=personalized_template_id(rule.rule_key),
                name=rule.title,
                category_path="shared/personalized/legacy",
                stage="constraints",
                order=500 + offset,
                tags=("day", "night", "joint"),
                default_mode="hard",
                config_key="personalized_constraints",
                explanation_template=rule.title,
                apply_fn=None,
                apply_fn_ref="apply_personalized_constraints",
                enabled_path=f"personalized_constraints.{rule.rule_key}",
                mode_path=f"personalized_constraints.{rule.mode_key}" if rule.mode_key else None,
                weight_path=f"personalized_constraints.{rule.weight_key}" if rule.weight_key else None,
            ),
            overwrite=False,
        )


@lru_cache(maxsize=1)
def build_default_rule_registry() -> RuleRegistry:
    registry = RuleRegistry()
    _register_core_specs(registry)
    _register_binding_specs(registry)
    _register_personalized_legacy_specs(registry)
    return registry
