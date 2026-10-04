# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Iterable, Mapping, Sequence

from ai_orchestrated_optimization import (
    AllowedAssignmentsConstraintSpec,
    BoolLiteralSpec,
    ConstraintSpec,
    ForbiddenAssignmentsConstraintSpec,
    LinearConstraintSpec,
    LinearExpression,
    LinearTerm,
    MapDomainConstraintSpec,
    MaxEqualityConstraintSpec,
    ObjectiveSpec,
    OptimizationProblemSpec,
    RuleFirstPlan,
    RuleSpec as AiRuleSpec,
    VariableSpec,
    build_rule_first_plan,
)

from scheduler.calendar import (
    ALL_DAYS,
    TUESDAY_TO_FRIDAY,
    WEEKDAY_DAYS,
    WEEKEND_DAYS,
    adjacent_day_pairs as calendar_adjacent_day_pairs,
    is_weekday_day,
)
from scheduler.day_constraints_morning_reading import ADJ_PAIRS
from scheduler.model.constraints.day_pe_tech_constraints import is_pe_subject as is_day_pe_subject
from scheduler.model.constraints.day_weekday_constraints import (
    CORE_SUBJECTS,
    is_lang_subject,
    is_pe_or_tech_subject,
    is_stem_subject,
    normalize_subject,
)
from scheduler.model.constraints.day_weekend_constraints import WEEKEND_WHITELIST, normalize_subject
from scheduler.rules.execution_plan import RuleExecutionPlan, RulePlanItem
from scheduler.rules.personalized_legacy import (
    PERSONALIZED_LEGACY_RULES,
    PERSONALIZED_RULE_INSTANCE_TEMPLATE_IDS,
    PERSONALIZED_TARGET_SLOTS,
    personalized_template_id,
)


@dataclass(frozen=True)
class SchedulerGenericRuleBridge:
    problem: OptimizationProblemSpec
    rule_first_plan: RuleFirstPlan
    metadata_by_rule: dict[str, dict[str, Any]]


_GENERIC_SCHEDULER_RULE_IDS = (
    "joint.day.one_subject_per_slot",
    "joint.day.subject_hour_constraints",
    "joint.day.teacher_no_conflict",
    "joint.day.core_subject_teacher_day_load_no_am1_am4",
    "joint.day.no_consecutive_same_teacher_same_class",
    "joint.day.no_am1_am4",
    "joint.day.head_pm1_min",
    "joint.day.teacher_weekday_am_pm_presence",
    "day.am1_pm1_mutex",
    "joint.day.am1_pm1_mutex",
    "day.two_class_am1_pm1_combo",
    "joint.day.two_class_am1_pm1_combo",
    "joint.day.two_class_low_hours_max_empty_days",
    "joint.day.low_weekday_subject_max1_per_day",
    "joint.day.high_weekday_subject_min1_per_day",
    "joint.day.pe_time_window_hard",
    "joint.day.teacher_whitelist_hard",
    "joint.day.reduce_stem_am1",
    "joint.day.pe_reduce_am_soft",
    "joint.day.pref_lang_am",
    "joint.day.pe_tech_compact_soft",
    "joint.day.teacher_am4_pm1_threshold_penalty",
    "joint.day.weekday_subject_balance",
    "joint.day.teacher_continuity_penalty",
    "joint.day.two_class_daily_min_per_class",
    "joint.day.teacher_m1_cap_constraint",
    "joint.day.teacher_am1_fragmentation",
    "joint.day.multi_class_halfday_soft",
    "joint.day.head_duty_constraints",
    "joint.day.noon_dorm_duty_constraints",
    "day.am1_pm1_exclusive",
    "joint.day.am1_pm1_exclusive",
    "day.single_class_weekly_am1_cap",
    "joint.day.single_class_weekly_am1_cap",
    "joint.day.morning_reading_constraints",
    "day.weekend_halfday_constraint",
    "joint.day.weekend_halfday_constraint",
    "joint.day.weekend_one_day_only",
    "joint.day.weekend_subject_whitelist",
    "joint.day.weekend_cross_halfday_penalty",
    "joint.day.weekend_double_period_same_class",
    "joint.day.yjc_sunday_am12_pm12_rule",
    "joint.day.binding_8chem_9bio",
    "day.solver_parameters",
    "night.solver_parameters",
    "joint.solver_parameters",
    "day.duty_joint_constraints",
    "joint.link.duty_joint_constraints",
    "joint.link.grade_group_duty_constraints",
    "night.soft_objective",
    "joint.night.soft_objective",
    *PERSONALIZED_RULE_INSTANCE_TEMPLATE_IDS,
    "night.hard_base",
    "joint.night.hard_base",
    "night.hard_bans",
    "joint.night.hard_bans",
    "night.hard_teacher_limits",
    "joint.night.hard_teacher_limits",
    "night.binding_8chem_9bio",
    "joint.night.binding_8chem_9bio",
    "night.physics_math_special",
    "joint.night.physics_math_special",
    "night.fri_sun_mutex",
    "joint.night.fri_sun_mutex",
    "night.single_class_p1_p2_split",
    "joint.night.single_class_p1_p2_split",
    "night.double_class_weekday_p1_p2_split",
    "joint.night.double_class_weekday_p1_p2_split",
    "night.checkin",
    "joint.night.checkin",
)
_CATALOG_GENERIC_SCHEDULER_RULE_IDS = frozenset(
    (
        *PERSONALIZED_RULE_INSTANCE_TEMPLATE_IDS,
        "joint.day.head_duty_constraints",
        "joint.day.noon_dorm_duty_constraints",
    )
)
_EXACT_CONTRACT_SCOPE = "exact_cp_sat_shape_contract"
_CATALOG_CONTRACT_SCOPE = "catalog_contract"


def generic_scheduler_rule_ids() -> tuple[str, ...]:
    """Runtime rule ids that already have first-class generic contracts."""
    return _GENERIC_SCHEDULER_RULE_IDS


def generic_scheduler_rule_contract_scopes() -> dict[str, str]:
    """Classify covered scheduler rule ids by the strength of their generic contract."""
    scopes = {rule_id: _EXACT_CONTRACT_SCOPE for rule_id in _GENERIC_SCHEDULER_RULE_IDS}
    for rule_id in _CATALOG_GENERIC_SCHEDULER_RULE_IDS:
        if rule_id in scopes:
            scopes[rule_id] = _CATALOG_CONTRACT_SCOPE
    return scopes


def generic_scheduler_rule_contract_summary() -> dict[str, int]:
    """Count exact-shape and catalog-only generic contracts for release audits."""
    summary = {_EXACT_CONTRACT_SCOPE: 0, _CATALOG_CONTRACT_SCOPE: 0}
    for scope in generic_scheduler_rule_contract_scopes().values():
        summary[scope] = summary.get(scope, 0) + 1
    return summary


def day_one_subject_per_slot_to_ai_or_problem(
    data: Any,
    *,
    rule_id: str = "joint.day.one_subject_per_slot",
) -> SchedulerGenericRuleBridge:
    """Compile the day one-subject-per-slot hard rule into OptimizationProblemSpec."""
    assignments = _day_candidate_assignment_names(data)
    variables = tuple(VariableSpec.bool(name) for (_cls, _subj, _slot, name) in assignments)
    names_by_cls_slot: dict[tuple[str, Any], list[str]] = {}
    assignment_names: dict[str, str] = {}
    for cls, subj, slot, name in assignments:
        names_by_cls_slot.setdefault((cls, slot), []).append(name)
        assignment_names[_assignment_key(cls, subj, str(slot.day), _slot_label(slot))] = name

    constraints: list[LinearConstraintSpec] = []
    constraint_index = 1
    for cls in _text_tuple(data.classes):
        for slot in tuple(data.available_slots):
            if (cls, slot) in getattr(data, "fixed_assign", {}):
                continue
            vars_list = names_by_cls_slot.get((cls, slot), [])
            if not vars_list:
                raise ValueError(f"{cls} has no schedulable subject candidates for {_slot_label(slot)}")
            constraints.append(
                LinearConstraintSpec(
                    name=f"day_one_subject_per_slot__{constraint_index:04d}__{_safe_identifier(cls)}__{_safe_identifier(str(slot.day))}__{_safe_identifier(_slot_label(slot))}",
                    expression=_sum_expr(vars_list),
                    sense="==",
                    rhs=1,
                    rule_id=rule_id,
                )
            )
            constraint_index += 1

    ai_rule = AiRuleSpec(
        rule_id=rule_id,
        description="Day hard rule: each class-slot selects exactly one subject candidate.",
        enforcement="hard",
        priority=1,
        source="scheduler.model.constraints.day_hard_one_per_slot:apply_one_subject_per_slot",
    )
    problem = OptimizationProblemSpec(
        problem_id="scheduler_day_one_subject_per_slot",
        variables=variables,
        rules=(ai_rule,),
        constraints=tuple(constraints),
    )
    rule_first_plan = build_rule_first_plan(
        rules=problem.rules,
        constraints=problem.constraints,
        objective_rule_id=None,
    )
    return SchedulerGenericRuleBridge(
        problem=problem,
        rule_first_plan=rule_first_plan,
        metadata_by_rule={
            rule_id: {
                "scheduler_rule_id": rule_id,
                "legacy_apply_fn": "apply_one_subject_per_slot",
                "generic_contract_status": "covered_by_generic_contract",
                "runtime_rule_ids": generic_scheduler_rule_ids(),
                "constraint_family_counts": {
                    "class_slot_exactly_one": len(constraints),
                },
                "assignment_variable_names": assignment_names,
            }
        },
    )


def day_subject_hours_to_ai_or_problem(
    data: Any,
    *,
    rule_id: str = "joint.day.subject_hour_constraints",
) -> SchedulerGenericRuleBridge:
    """Compile the day subject-hour conservation rule into OptimizationProblemSpec."""
    assignments = _day_candidate_assignment_names(data)
    variables = tuple(VariableSpec.bool(name) for (_cls, _subj, _slot, name) in assignments)
    names_by_cls_subj_bucket: dict[tuple[str, str, str], list[str]] = {}
    assignment_names: dict[str, str] = {}
    for cls, subj, slot, name in assignments:
        names_by_cls_subj_bucket.setdefault((cls, subj, _day_hour_bucket(slot)), []).append(name)
        assignment_names[_assignment_key(cls, subj, str(slot.day), _slot_label(slot))] = name

    constraints: list[LinearConstraintSpec] = []
    bucket_defs = (
        ("early", 0),
        ("weekday", 1),
        ("weekend", 2),
    )
    constraint_index = 1
    for raw_key, raw_reqs in getattr(data, "req_hours", {}).items():
        cls, subj = (str(raw_key[0]), str(raw_key[1]))
        reqs = tuple(int(value) for value in raw_reqs)
        for bucket, req_index in bucket_defs:
            constraints.append(
                LinearConstraintSpec(
                    name=f"day_subject_hours__{constraint_index:04d}__{_safe_identifier(cls)}__{_safe_identifier(subj)}__{bucket}",
                    expression=_sum_expr(names_by_cls_subj_bucket.get((cls, subj, bucket), ())),
                    sense="==",
                    rhs=reqs[req_index],
                    rule_id=rule_id,
                )
            )
            constraint_index += 1

    ai_rule = AiRuleSpec(
        rule_id=rule_id,
        description="Day hard rule: each class-subject satisfies early, weekday, and weekend hour quotas.",
        enforcement="hard",
        priority=2,
        source="scheduler.model.constraints.day_hard_subject_hours:apply_subject_hour_constraints",
    )
    problem = OptimizationProblemSpec(
        problem_id="scheduler_day_subject_hour_constraints",
        variables=variables,
        rules=(ai_rule,),
        constraints=tuple(constraints),
    )
    rule_first_plan = build_rule_first_plan(
        rules=problem.rules,
        constraints=problem.constraints,
        objective_rule_id=None,
    )
    return SchedulerGenericRuleBridge(
        problem=problem,
        rule_first_plan=rule_first_plan,
        metadata_by_rule={
            rule_id: {
                "scheduler_rule_id": rule_id,
                "legacy_apply_fn": "apply_subject_hour_constraints",
                "generic_contract_status": "covered_by_generic_contract",
                "runtime_rule_ids": generic_scheduler_rule_ids(),
                "constraint_family_counts": {
                    "subject_hour_bucket_equalities": len(constraints),
                },
                "assignment_variable_names": assignment_names,
            }
        },
    )


def day_teacher_no_conflict_to_ai_or_problem(
    data: Any,
    *,
    rule_id: str = "joint.day.teacher_no_conflict",
) -> SchedulerGenericRuleBridge:
    """Compile the day teacher-slot no-conflict hard rule into OptimizationProblemSpec."""
    assignments = _day_candidate_assignment_names(data)
    variables = tuple(VariableSpec.bool(name) for (_cls, _subj, _slot, name) in assignments)
    names_by_teacher_slot: dict[tuple[str, Any], list[str]] = {}
    assignment_names: dict[str, str] = {}
    for cls, subj, slot, name in assignments:
        teacher = getattr(data, "cls_subj_teacher", {}).get((cls, subj))
        if teacher is None:
            continue
        teacher_text = str(teacher)
        names_by_teacher_slot.setdefault((teacher_text, slot), []).append(name)
        assignment_names[_assignment_key(cls, subj, str(slot.day), _slot_label(slot))] = name

    constrained_teacher_slots = {
        _teacher_slot_key(teacher, slot): tuple(names)
        for (teacher, slot), names in names_by_teacher_slot.items()
        if len(names) > 1
    }
    constraints = tuple(
        LinearConstraintSpec(
            name=f"day_teacher_no_conflict__{index:04d}__{_safe_identifier(key)}",
            expression=_sum_expr(variable_names),
            sense="<=",
            rhs=1,
            rule_id=rule_id,
        )
        for index, (key, variable_names) in enumerate(constrained_teacher_slots.items(), start=1)
    )

    ai_rule = AiRuleSpec(
        rule_id=rule_id,
        description="Day hard rule: each teacher can teach at most one class in the same slot.",
        enforcement="hard",
        priority=3,
        source="scheduler.model.constraints.day_hard_teacher_conflict:apply_teacher_no_conflict",
    )
    problem = OptimizationProblemSpec(
        problem_id="scheduler_day_teacher_no_conflict",
        variables=variables,
        rules=(ai_rule,),
        constraints=constraints,
    )
    rule_first_plan = build_rule_first_plan(
        rules=problem.rules,
        constraints=problem.constraints,
        objective_rule_id=None,
    )
    return SchedulerGenericRuleBridge(
        problem=problem,
        rule_first_plan=rule_first_plan,
        metadata_by_rule={
            rule_id: {
                "scheduler_rule_id": rule_id,
                "legacy_apply_fn": "apply_teacher_no_conflict",
                "generic_contract_status": "covered_by_generic_contract",
                "runtime_rule_ids": generic_scheduler_rule_ids(),
                "constraint_family_counts": {
                    "teacher_slot_at_most_one": len(constraints),
                },
                "assignment_variable_names": assignment_names,
                "teacher_slot_variable_names": constrained_teacher_slots,
            }
        },
    )


def day_no_am1_am4_to_ai_or_problem(
    data: Any,
    *,
    pe_teachers: Iterable[Any] = (),
    rule_id: str = "joint.day.no_am1_am4",
) -> SchedulerGenericRuleBridge:
    """Compile the weekday teacher AM1+AM4 mutex rule into OptimizationProblemSpec."""
    assignments = _day_candidate_assignment_names(data)
    variables = tuple(VariableSpec.bool(name) for (_cls, _subj, _slot, name) in assignments)
    pe_teacher_ids = {str(teacher) for teacher in pe_teachers}
    teacher_days: set[tuple[str, str]] = set()
    am_edge_names_by_teacher_day: dict[tuple[str, str], list[str]] = {}
    assignment_names: dict[str, str] = {}

    for cls, subj, slot, name in assignments:
        assignment_names[_assignment_key(cls, subj, str(slot.day), _slot_label(slot))] = name
        if not is_weekday_day(str(slot.day)):
            continue
        if is_pe_or_tech_subject(subj):
            continue
        teacher = getattr(data, "cls_subj_teacher", {}).get((cls, subj))
        if teacher is None:
            continue
        teacher_text = str(teacher)
        if teacher_text in pe_teacher_ids:
            continue
        teacher_day_key = (teacher_text, str(slot.day))
        teacher_days.add(teacher_day_key)
        if _is_am1(slot) or _is_am4(slot):
            am_edge_names_by_teacher_day.setdefault(teacher_day_key, []).append(name)

    constraints = tuple(
        LinearConstraintSpec(
            name=f"day_no_am1_am4__{index:04d}__{_safe_identifier(teacher)}__{_safe_identifier(day)}",
            expression=_sum_expr(am_edge_names_by_teacher_day.get((teacher, day), ())),
            sense="<=",
            rhs=1,
            rule_id=rule_id,
        )
        for index, (teacher, day) in enumerate(sorted(teacher_days), start=1)
    )
    teacher_day_variable_names = {
        _teacher_day_key(teacher, day): tuple(am_edge_names_by_teacher_day.get((teacher, day), ()))
        for teacher, day in sorted(teacher_days)
    }

    ai_rule = AiRuleSpec(
        rule_id=rule_id,
        description="Day hard rule: non-PE/tech teachers cannot teach both AM1 and AM4 on the same weekday.",
        enforcement="hard",
        priority=4,
        source="scheduler.model.constraints.day_weekday_constraints:apply_no_am1_am4",
    )
    problem = OptimizationProblemSpec(
        problem_id="scheduler_day_no_am1_am4",
        variables=variables,
        rules=(ai_rule,),
        constraints=constraints,
    )
    rule_first_plan = build_rule_first_plan(
        rules=problem.rules,
        constraints=problem.constraints,
        objective_rule_id=None,
    )
    return SchedulerGenericRuleBridge(
        problem=problem,
        rule_first_plan=rule_first_plan,
        metadata_by_rule={
            rule_id: {
                "scheduler_rule_id": rule_id,
                "legacy_apply_fn": "apply_no_am1_am4",
                "generic_contract_status": "covered_by_generic_contract",
                "runtime_rule_ids": generic_scheduler_rule_ids(),
                "constraint_family_counts": {
                    "teacher_day_no_am1_am4": len(constraints),
                },
                "assignment_variable_names": assignment_names,
                "teacher_day_variable_names": teacher_day_variable_names,
                "pe_teachers": tuple(sorted(pe_teacher_ids)),
            }
        },
    )


def day_core_subject_teacher_day_load_no_am1_am4_to_ai_or_problem(
    data: Any,
    *,
    max_per_day: int = 3,
    rule_id: str = "joint.day.core_subject_teacher_day_load_no_am1_am4",
) -> SchedulerGenericRuleBridge:
    """Compile the core-subject teacher day-load and AM1+AM4 hard rule."""
    max_per_day = int(max_per_day)
    assignments = _day_candidate_assignment_names(data)
    variables = tuple(VariableSpec.bool(name) for (_cls, _subj, _slot, name) in assignments)
    assignment_names: dict[str, str] = {}

    target_teachers = tuple(
        sorted(
            {
                str(teacher)
                for (_cls, subj), teacher in getattr(data, "cls_subj_teacher", {}).items()
                if teacher and normalize_subject(str(subj)) in CORE_SUBJECTS
            }
        )
    )
    target_teacher_set = set(target_teachers)

    variable_names_by_teacher_day: dict[tuple[str, str], list[str]] = {}
    am1_am4_names_by_teacher_day: dict[tuple[str, str], list[str]] = {}
    for cls, subj, slot, name in assignments:
        assignment_names[_assignment_key(cls, subj, str(slot.day), _slot_label(slot))] = name
        if not is_weekday_day(str(slot.day)) or not _is_daytime(slot):
            continue
        teacher = getattr(data, "cls_subj_teacher", {}).get((cls, subj))
        if teacher is None or str(teacher) not in target_teacher_set:
            continue
        key = (str(teacher), str(slot.day))
        variable_names_by_teacher_day.setdefault(key, []).append(name)
        if _is_am1(slot) or _is_am4(slot):
            am1_am4_names_by_teacher_day.setdefault(key, []).append(name)

    fixed_counts_by_teacher_day: dict[tuple[str, str], int] = {}
    fixed_am1_am4_counts_by_teacher_day: dict[tuple[str, str], int] = {}
    for (cls, slot), subj in (getattr(data, "fixed_assign", {}) or {}).items():
        if not is_weekday_day(str(slot.day)) or not _is_daytime(slot):
            continue
        teacher = getattr(data, "cls_subj_teacher", {}).get((cls, subj))
        if teacher is None or str(teacher) not in target_teacher_set:
            continue
        key = (str(teacher), str(slot.day))
        fixed_counts_by_teacher_day[key] = fixed_counts_by_teacher_day.get(key, 0) + 1
        if _is_am1(slot) or _is_am4(slot):
            fixed_am1_am4_counts_by_teacher_day[key] = fixed_am1_am4_counts_by_teacher_day.get(key, 0) + 1

    required_hours = {teacher: 0 for teacher in target_teachers}
    for (cls, subj), teacher in getattr(data, "cls_subj_teacher", {}).items():
        if not teacher or str(teacher) not in target_teacher_set:
            continue
        if normalize_subject(str(subj)) not in CORE_SUBJECTS:
            continue
        _early, weekday_hours, _weekend = getattr(data, "req_hours", {}).get((cls, subj), (0, 0, 0))
        required_hours[str(teacher)] = required_hours.get(str(teacher), 0) + int(weekday_hours)
    impossible_teachers = tuple(
        sorted(
            (teacher for teacher, hours in required_hours.items() if hours > max_per_day * len(WEEKDAY_DAYS)),
            key=lambda teacher: (-required_hours[teacher], teacher),
        )
    )

    constraints: list[LinearConstraintSpec] = []
    counts = {
        "core_teacher_daily_load_caps": 0,
        "core_teacher_am1_am4_mutexes": 0,
    }
    constraint_index = 1
    for teacher in target_teachers:
        for day in WEEKDAY_DAYS:
            day_text = str(day)
            raw_key = (teacher, day_text)
            constraints.append(
                LinearConstraintSpec(
                    name=f"day_core_subject_teacher_load__daily_cap__{constraint_index:04d}__{_safe_identifier(teacher)}__{_safe_identifier(day_text)}",
                    expression=_sum_expr(tuple(sorted(variable_names_by_teacher_day.get(raw_key, ())))),
                    sense="<=",
                    rhs=max_per_day - int(fixed_counts_by_teacher_day.get(raw_key, 0)),
                    rule_id=rule_id,
                )
            )
            counts["core_teacher_daily_load_caps"] += 1
            constraint_index += 1
            constraints.append(
                LinearConstraintSpec(
                    name=f"day_core_subject_teacher_load__am1_am4_mutex__{constraint_index:04d}__{_safe_identifier(teacher)}__{_safe_identifier(day_text)}",
                    expression=_sum_expr(tuple(sorted(am1_am4_names_by_teacher_day.get(raw_key, ())))),
                    sense="<=",
                    rhs=1 - int(fixed_am1_am4_counts_by_teacher_day.get(raw_key, 0)),
                    rule_id=rule_id,
                )
            )
            counts["core_teacher_am1_am4_mutexes"] += 1
            constraint_index += 1

    ai_rule = AiRuleSpec(
        rule_id=rule_id,
        description="Day hard rule: core-subject teachers have weekday daily load caps and cannot hit AM1 plus AM4.",
        enforcement="hard",
        priority=13,
        source="scheduler.model.constraints.day_weekday_constraints:apply_core_subject_teacher_day_load_and_no_am1_am4",
    )
    problem = OptimizationProblemSpec(
        problem_id="scheduler_day_core_subject_teacher_day_load_no_am1_am4",
        variables=variables,
        rules=(ai_rule,),
        constraints=tuple(constraints),
    )
    rule_first_plan = build_rule_first_plan(
        rules=problem.rules,
        constraints=problem.constraints,
        objective_rule_id=None,
    )
    return SchedulerGenericRuleBridge(
        problem=problem,
        rule_first_plan=rule_first_plan,
        metadata_by_rule={
            rule_id: {
                "scheduler_rule_id": rule_id,
                "legacy_apply_fn": "apply_core_subject_teacher_day_load_and_no_am1_am4",
                "generic_contract_status": "covered_by_generic_contract",
                "runtime_rule_ids": generic_scheduler_rule_ids(),
                "constraint_family_counts": counts,
                "assignment_variable_names": assignment_names,
                "target_teachers": target_teachers,
                "teacher_day_load_assignment_variable_names": {
                    _teacher_day_key(teacher, day): tuple(sorted(names))
                    for (teacher, day), names in sorted(variable_names_by_teacher_day.items())
                },
                "teacher_day_am1_am4_assignment_variable_names": {
                    _teacher_day_key(teacher, day): tuple(sorted(names))
                    for (teacher, day), names in sorted(am1_am4_names_by_teacher_day.items())
                },
                "fixed_load_counts": {
                    _teacher_day_key(teacher, day): int(count)
                    for (teacher, day), count in sorted(fixed_counts_by_teacher_day.items())
                },
                "fixed_am1_am4_counts": {
                    _teacher_day_key(teacher, day): int(count)
                    for (teacher, day), count in sorted(fixed_am1_am4_counts_by_teacher_day.items())
                },
                "required_hours": required_hours,
                "impossible_teachers": impossible_teachers,
                "max_per_day": max_per_day,
            }
        },
    )


def day_head_pm1_min_to_ai_or_problem(
    data: Any,
    *,
    head_teachers: Iterable[Any],
    min_required: int = 3,
    rule_id: str = "joint.day.head_pm1_min",
) -> SchedulerGenericRuleBridge:
    """Compile the weekday PM1 minimum for head teachers into OptimizationProblemSpec."""
    min_required = int(min_required)
    assignments = _day_candidate_assignment_names(data)
    variables = tuple(VariableSpec.bool(name) for (_cls, _subj, _slot, name) in assignments)
    assignment_names: dict[str, str] = {}
    head_teacher_ids = tuple(str(teacher) for teacher in head_teachers if str(teacher))
    head_teacher_set = set(head_teacher_ids)
    names_by_day: dict[str, list[str]] = {str(day): [] for day in WEEKDAY_DAYS}

    for cls, subj, slot, name in assignments:
        assignment_names[_assignment_key(cls, subj, str(slot.day), _slot_label(slot))] = name
        day = str(slot.day)
        if day not in names_by_day or not _is_pm1(slot) or is_pe_or_tech_subject(str(subj)):
            continue
        teacher = getattr(data, "cls_subj_teacher", {}).get((cls, subj))
        if teacher is None or str(teacher) not in head_teacher_set:
            continue
        names_by_day[day].append(name)

    constraints = tuple(
        LinearConstraintSpec(
            name=f"day_head_pm1_min__{index:04d}__{_safe_identifier(str(day))}",
            expression=_sum_expr(tuple(sorted(names_by_day[str(day)]))),
            sense=">=",
            rhs=min_required,
            rule_id=rule_id,
        )
        for index, day in enumerate(WEEKDAY_DAYS, start=1)
    )

    ai_rule = AiRuleSpec(
        rule_id=rule_id,
        description="Day hard rule: each weekday PM1 has at least the configured number of head teachers teaching.",
        enforcement="hard",
        priority=15,
        source="scheduler.model.constraints.day_weekday_constraints:apply_head_pm1_min",
    )
    problem = OptimizationProblemSpec(
        problem_id="scheduler_day_head_pm1_min",
        variables=variables,
        rules=(ai_rule,),
        constraints=constraints,
    )
    rule_first_plan = build_rule_first_plan(
        rules=problem.rules,
        constraints=problem.constraints,
        objective_rule_id=None,
    )
    return SchedulerGenericRuleBridge(
        problem=problem,
        rule_first_plan=rule_first_plan,
        metadata_by_rule={
            rule_id: {
                "scheduler_rule_id": rule_id,
                "legacy_apply_fn": "apply_head_pm1_min",
                "generic_contract_status": "covered_by_generic_contract",
                "runtime_rule_ids": generic_scheduler_rule_ids(),
                "constraint_family_counts": {
                    "head_pm1_minimums": len(constraints),
                },
                "assignment_variable_names": assignment_names,
                "day_pm1_variable_names": {
                    str(day): tuple(sorted(names_by_day[str(day)]))
                    for day in WEEKDAY_DAYS
                },
                "head_teachers": head_teacher_ids,
                "min_required": min_required,
            }
        },
    )


def day_teacher_weekday_am_pm_presence_to_ai_or_problem(
    data: Any,
    *,
    pe_teachers: Iterable[Any] = (),
    rule_id: str = "joint.day.teacher_weekday_am_pm_presence",
) -> SchedulerGenericRuleBridge:
    """Compile the weekday teacher AM/PM presence hard rule into OptimizationProblemSpec."""
    assignments = _day_candidate_assignment_names(data)
    variables = tuple(VariableSpec.bool(name) for (_cls, _subj, _slot, name) in assignments)
    assignment_names: dict[str, str] = {}
    pe_teacher_ids = {str(teacher) for teacher in pe_teachers}

    teachers: set[str] = set()
    variable_names_by_teacher_halfday: dict[tuple[str, str], list[str]] = {}
    for cls, subj, slot, name in assignments:
        assignment_names[_assignment_key(cls, subj, str(slot.day), _slot_label(slot))] = name
        if not is_weekday_day(str(slot.day)) or is_pe_or_tech_subject(str(subj)):
            continue
        teacher = getattr(data, "cls_subj_teacher", {}).get((cls, subj))
        if teacher is None:
            continue
        teacher_text = str(teacher)
        teachers.add(teacher_text)
        if _is_am(slot):
            variable_names_by_teacher_halfday.setdefault((teacher_text, "am"), []).append(name)
        if _is_pm(slot):
            variable_names_by_teacher_halfday.setdefault((teacher_text, "pm"), []).append(name)

    fixed_counts_by_teacher_halfday: dict[tuple[str, str], int] = {}
    for (cls, slot), subj in (getattr(data, "fixed_assign", {}) or {}).items():
        if not is_weekday_day(str(slot.day)):
            continue
        teacher = getattr(data, "cls_subj_teacher", {}).get((cls, subj))
        if teacher is None:
            continue
        teacher_text = str(teacher)
        teachers.add(teacher_text)
        if _is_am(slot):
            key = (teacher_text, "am")
            fixed_counts_by_teacher_halfday[key] = fixed_counts_by_teacher_halfday.get(key, 0) + 1
        if _is_pm(slot):
            key = (teacher_text, "pm")
            fixed_counts_by_teacher_halfday[key] = fixed_counts_by_teacher_halfday.get(key, 0) + 1

    constraints: list[LinearConstraintSpec] = []
    constrained_teachers: list[str] = []
    counts = {
        "teacher_weekday_am_presence_minimums": 0,
        "teacher_weekday_pm_presence_minimums": 0,
    }
    constraint_index = 1
    for teacher in sorted(teachers):
        if teacher in pe_teacher_ids:
            continue
        am_vars = tuple(sorted(variable_names_by_teacher_halfday.get((teacher, "am"), ())))
        pm_vars = tuple(sorted(variable_names_by_teacher_halfday.get((teacher, "pm"), ())))
        am_fixed = int(fixed_counts_by_teacher_halfday.get((teacher, "am"), 0))
        pm_fixed = int(fixed_counts_by_teacher_halfday.get((teacher, "pm"), 0))
        if len(am_vars) + len(pm_vars) + am_fixed + pm_fixed == 0:
            continue
        constrained_teachers.append(teacher)
        constraints.append(
            LinearConstraintSpec(
                name=f"day_teacher_weekday_am_pm_presence__am_min__{constraint_index:04d}__{_safe_identifier(teacher)}",
                expression=_sum_expr(am_vars),
                sense=">=",
                rhs=1 - am_fixed,
                rule_id=rule_id,
            )
        )
        counts["teacher_weekday_am_presence_minimums"] += 1
        constraint_index += 1
        constraints.append(
            LinearConstraintSpec(
                name=f"day_teacher_weekday_am_pm_presence__pm_min__{constraint_index:04d}__{_safe_identifier(teacher)}",
                expression=_sum_expr(pm_vars),
                sense=">=",
                rhs=1 - pm_fixed,
                rule_id=rule_id,
            )
        )
        counts["teacher_weekday_pm_presence_minimums"] += 1
        constraint_index += 1

    ai_rule = AiRuleSpec(
        rule_id=rule_id,
        description="Day hard rule: each non-exempt weekday teacher must appear at least once in AM and once in PM.",
        enforcement="hard",
        priority=16,
        source="scheduler.model.constraints.day_weekday_constraints:apply_teacher_weekday_am_pm_presence",
    )
    problem = OptimizationProblemSpec(
        problem_id="scheduler_day_teacher_weekday_am_pm_presence",
        variables=variables,
        rules=(ai_rule,),
        constraints=tuple(constraints),
    )
    rule_first_plan = build_rule_first_plan(
        rules=problem.rules,
        constraints=problem.constraints,
        objective_rule_id=None,
    )
    return SchedulerGenericRuleBridge(
        problem=problem,
        rule_first_plan=rule_first_plan,
        metadata_by_rule={
            rule_id: {
                "scheduler_rule_id": rule_id,
                "legacy_apply_fn": "apply_teacher_weekday_am_pm_presence",
                "generic_contract_status": "covered_by_generic_contract",
                "runtime_rule_ids": generic_scheduler_rule_ids(),
                "constraint_family_counts": counts,
                "assignment_variable_names": assignment_names,
                "constrained_teachers": tuple(constrained_teachers),
                "teacher_halfday_assignment_variable_names": {
                    f"{teacher}|{halfday}": tuple(sorted(names))
                    for (teacher, halfday), names in sorted(variable_names_by_teacher_halfday.items())
                },
                "fixed_presence_counts": {
                    f"{teacher}|{halfday}": int(count)
                    for (teacher, halfday), count in sorted(fixed_counts_by_teacher_halfday.items())
                },
                "pe_teachers": tuple(sorted(pe_teacher_ids)),
            }
        },
    )


def day_am1_pm1_mutex_to_ai_or_problem(
    data: Any,
    *,
    mode: str = "hard",
    weight: int = 3000,
    rule_id: str = "joint.day.am1_pm1_mutex",
    problem_id: str = "scheduler_day_am1_pm1_mutex",
    legacy_apply_fn: str = "apply_am1_pm1_mutex",
    priority: int = 17,
    source: str = "scheduler.model.constraints.day_weekday_constraints:apply_am1_pm1_mutex",
    description: str = "Day rule: a teacher cannot or should not hit both AM1 and PM1 on the same weekday.",
    constraint_name_prefix: str = "day_am1_pm1_mutex",
) -> SchedulerGenericRuleBridge:
    """Compile the weekday teacher AM1/PM1 same-day mutex into OptimizationProblemSpec."""
    mode_norm = str(mode or "hard").strip().lower()
    if mode_norm not in {"hard", "soft"}:
        mode_norm = "hard"

    assignments = _day_candidate_assignment_names(data)
    assignment_variables = tuple(VariableSpec.bool(name) for (_cls, _subj, _slot, name) in assignments)
    assignment_names: dict[str, str] = {}
    variable_names_by_teacher_day_period: dict[tuple[str, str, str], list[str]] = {}
    for cls, subj, slot, name in assignments:
        assignment_names[_assignment_key(cls, subj, str(slot.day), _slot_label(slot))] = name
        if not is_weekday_day(str(slot.day)):
            continue
        tag = "am1" if _is_am1(slot) else "pm1" if _is_pm1(slot) else None
        if tag is None:
            continue
        teacher = getattr(data, "cls_subj_teacher", {}).get((cls, subj))
        if teacher is None:
            continue
        variable_names_by_teacher_day_period.setdefault((str(teacher), str(slot.day), tag), []).append(name)

    days = tuple(
        day
        for day in WEEKDAY_DAYS
        if any(str(slot.day) == str(day) for slot in tuple(getattr(data, "available_slots", ())))
    )
    teachers = tuple(sorted({str(teacher) for teacher in getattr(data, "cls_subj_teacher", {}).values() if teacher}))
    teacher_days = tuple((teacher, str(day)) for teacher in teachers for day in days)

    fixed_counts_by_teacher_day_period: dict[tuple[str, str, str], int] = {}
    for (cls, slot), subj in (getattr(data, "fixed_assign", {}) or {}).items():
        if str(slot.day) not in days:
            continue
        tag = "am1" if _is_am1(slot) else "pm1" if _is_pm1(slot) else None
        if tag is None:
            continue
        teacher = getattr(data, "cls_subj_teacher", {}).get((cls, subj))
        if teacher is None:
            continue
        key = (str(teacher), str(slot.day), tag)
        fixed_counts_by_teacher_day_period[key] = fixed_counts_by_teacher_day_period.get(key, 0) + 1

    presence_variable_names: dict[str, str] = {}
    presence_by_raw_key: dict[tuple[str, str, str], str] = {}
    presence_index = 1
    for teacher, day in teacher_days:
        for tag in ("am1", "pm1"):
            key = (teacher, day, tag)
            name = _teacher_day_period_bool_name(presence_index, teacher, day, tag)
            presence_index += 1
            presence_by_raw_key[key] = name
            presence_variable_names[_teacher_day_period_key(teacher, day, tag)] = name

    presence_variables = tuple(VariableSpec.bool(name) for name in presence_variable_names.values())
    constraints: list[LinearConstraintSpec] = []
    counts = {
        "presence_fixed_one": 0,
        "presence_lower_bounds": 0,
        "presence_implies": 0,
        "presence_zero": 0,
        "teacher_day_am1_pm1_mutex": 0,
        "violation_upper_bounds": 0,
        "violation_lower_bounds": 0,
    }
    constraint_index = 1

    for teacher, day in teacher_days:
        for tag in ("am1", "pm1"):
            raw_key = (teacher, day, tag)
            presence_name = presence_by_raw_key[raw_key]
            fixed_count = int(fixed_counts_by_teacher_day_period.get(raw_key, 0))
            var_names = tuple(sorted(variable_names_by_teacher_day_period.get(raw_key, ())))
            if fixed_count > 0:
                constraints.append(
                    _bool_value_constraint(
                        f"{constraint_name_prefix}__fixed_{tag}__{constraint_index:04d}__{_safe_identifier(teacher)}__{_safe_identifier(day)}",
                        presence_name,
                        1,
                        rule_id,
                    )
                )
                counts["presence_fixed_one"] += 1
                constraint_index += 1
            elif var_names:
                constraints.append(
                    LinearConstraintSpec(
                        name=f"{constraint_name_prefix}__has_{tag}_lower__{constraint_index:04d}__{_safe_identifier(teacher)}__{_safe_identifier(day)}",
                        expression=LinearExpression(
                            (
                                *(LinearTerm(name, 1) for name in var_names),
                                LinearTerm(presence_name, -1),
                            )
                        ),
                        sense=">=",
                        rhs=0,
                        rule_id=rule_id,
                    )
                )
                counts["presence_lower_bounds"] += 1
                constraint_index += 1
                for var_name in var_names:
                    constraints.append(
                        LinearConstraintSpec(
                            name=f"{constraint_name_prefix}__{tag}_implies__{constraint_index:04d}__{_safe_identifier(var_name)}",
                            expression=LinearExpression((LinearTerm(var_name, 1), LinearTerm(presence_name, -1))),
                            sense="<=",
                            rhs=0,
                            rule_id=rule_id,
                        )
                    )
                    counts["presence_implies"] += 1
                    constraint_index += 1
            else:
                constraints.append(
                    _bool_value_constraint(
                        f"{constraint_name_prefix}__no_{tag}__{constraint_index:04d}__{_safe_identifier(teacher)}__{_safe_identifier(day)}",
                        presence_name,
                        0,
                        rule_id,
                    )
                )
                counts["presence_zero"] += 1
                constraint_index += 1

    violation_variable_names: dict[str, str] = {}
    violation_variables: list[VariableSpec] = []
    violation_index = 1
    for teacher, day in teacher_days:
        am1_name = presence_by_raw_key[(teacher, day, "am1")]
        pm1_name = presence_by_raw_key[(teacher, day, "pm1")]
        if mode_norm == "hard":
            constraints.append(
                LinearConstraintSpec(
                    name=f"{constraint_name_prefix}__hard_mutex__{constraint_index:04d}__{_safe_identifier(teacher)}__{_safe_identifier(day)}",
                    expression=LinearExpression((LinearTerm(am1_name, 1), LinearTerm(pm1_name, 1))),
                    sense="<=",
                    rhs=1,
                    rule_id=rule_id,
                )
            )
            counts["teacher_day_am1_pm1_mutex"] += 1
            constraint_index += 1
            continue

        violation_name = _teacher_day_violation_bool_name(violation_index, teacher, day, "am1_pm1")
        violation_index += 1
        violation_variable_names[_teacher_day_key(teacher, day)] = violation_name
        violation_variables.append(VariableSpec.bool(violation_name))
        for presence_name in (am1_name, pm1_name):
            constraints.append(
                LinearConstraintSpec(
                    name=f"{constraint_name_prefix}__violation_upper__{constraint_index:04d}__{_safe_identifier(violation_name)}",
                    expression=LinearExpression((LinearTerm(violation_name, 1), LinearTerm(presence_name, -1))),
                    sense="<=",
                    rhs=0,
                    rule_id=rule_id,
                )
            )
            counts["violation_upper_bounds"] += 1
            constraint_index += 1
        constraints.append(
            LinearConstraintSpec(
                name=f"{constraint_name_prefix}__violation_lower__{constraint_index:04d}__{_safe_identifier(violation_name)}",
                expression=LinearExpression(
                    (
                        LinearTerm(violation_name, 1),
                        LinearTerm(am1_name, -1),
                        LinearTerm(pm1_name, -1),
                    )
                ),
                sense=">=",
                rhs=-1,
                rule_id=rule_id,
            )
        )
        counts["violation_lower_bounds"] += 1
        constraint_index += 1

    objective = None
    if mode_norm == "soft" and violation_variable_names:
        objective = ObjectiveSpec(
            rule_id=rule_id,
            sense="minimize",
            expression=LinearExpression(
                tuple(LinearTerm(name, int(weight)) for name in violation_variable_names.values())
            ),
        )
    ai_rule = AiRuleSpec(
        rule_id=rule_id,
        description=description,
        enforcement=mode_norm,
        priority=int(priority),
        source=source,
    )
    problem = OptimizationProblemSpec(
        problem_id=problem_id,
        variables=(*assignment_variables, *presence_variables, *tuple(violation_variables)),
        rules=(ai_rule,),
        constraints=tuple(constraints),
        objective=objective,
    )
    rule_first_plan = build_rule_first_plan(
        rules=problem.rules,
        constraints=problem.constraints,
        objective_rule_id=objective.rule_id if objective is not None else None,
    )
    return SchedulerGenericRuleBridge(
        problem=problem,
        rule_first_plan=rule_first_plan,
        metadata_by_rule={
            rule_id: {
                "scheduler_rule_id": rule_id,
                "legacy_apply_fn": legacy_apply_fn,
                "generic_contract_status": "covered_by_generic_contract",
                "runtime_rule_ids": generic_scheduler_rule_ids(),
                "constraint_family_counts": counts,
                "assignment_variable_names": assignment_names,
                "teacher_day_slot_assignment_variable_names": {
                    _teacher_day_period_key(teacher, day, tag): tuple(sorted(names))
                    for (teacher, day, tag), names in sorted(variable_names_by_teacher_day_period.items())
                },
                "teacher_day_slot_presence_variable_names": presence_variable_names,
                "fixed_presence_counts": {
                    _teacher_day_period_key(teacher, day, tag): int(count)
                    for (teacher, day, tag), count in sorted(fixed_counts_by_teacher_day_period.items())
                },
                "violation_variable_names": violation_variable_names,
                "mode": mode_norm,
                "weight": int(weight),
            }
        },
    )


def day_am1_pm1_exclusive_to_ai_or_problem(
    data: Any,
    *,
    mode: str = "hard",
    weight: int = 3000,
    rule_id: str = "joint.day.am1_pm1_exclusive",
) -> SchedulerGenericRuleBridge:
    """Compile the weekday teacher AM1/PM1 exclusive rule into OptimizationProblemSpec."""
    return day_am1_pm1_mutex_to_ai_or_problem(
        data,
        mode=mode,
        weight=weight,
        rule_id=rule_id,
        problem_id="scheduler_day_am1_pm1_exclusive",
        legacy_apply_fn="apply_am1_pm1_exclusive",
        priority=19,
        source="scheduler.model.constraints.day_weekday_constraints:apply_am1_pm1_exclusive",
        description="Day rule: AM1 and PM1 are mutually exclusive for a teacher on the same weekday.",
        constraint_name_prefix="day_am1_pm1_exclusive",
    )


def day_single_class_weekly_am1_cap_to_ai_or_problem(
    data: Any,
    *,
    max_occurrences: int = 2,
    rule_id: str = "joint.day.single_class_weekly_am1_cap",
) -> SchedulerGenericRuleBridge:
    """Compile the single-class teacher weekly AM1 cap into OptimizationProblemSpec."""
    max_occurrences = max(0, int(max_occurrences))
    assignments = _day_candidate_assignment_names(data)
    assignment_variables = tuple(VariableSpec.bool(name) for (_cls, _subj, _slot, name) in assignments)
    assignment_names: dict[str, str] = {}

    active_days = tuple(
        str(day)
        for day in ALL_DAYS
        if any(str(slot.day) == str(day) for slot in tuple(getattr(data, "available_slots", ())))
    )
    teachers = tuple(sorted({str(teacher) for teacher in getattr(data, "cls_subj_teacher", {}).values() if teacher}))

    teacher_to_classes: dict[str, set[str]] = {}
    for (cls, _subj), teacher in getattr(data, "cls_subj_teacher", {}).items():
        if not teacher:
            continue
        teacher_to_classes.setdefault(str(teacher), set()).add(str(cls))
    single_class_teachers = tuple(
        sorted(teacher for teacher, class_set in teacher_to_classes.items() if len(class_set) == 1)
    )

    variable_names_by_teacher_day: dict[tuple[str, str], list[str]] = {}
    for cls, subj, slot, name in assignments:
        assignment_names[_assignment_key(cls, subj, str(slot.day), _slot_label(slot))] = name
        if str(slot.day) not in active_days or not _is_am1(slot):
            continue
        teacher = getattr(data, "cls_subj_teacher", {}).get((cls, subj))
        if teacher is None:
            continue
        variable_names_by_teacher_day.setdefault((str(teacher), str(slot.day)), []).append(name)

    fixed_counts_by_teacher_day: dict[tuple[str, str], int] = {}
    for (cls, slot), subj in (getattr(data, "fixed_assign", {}) or {}).items():
        if str(slot.day) not in active_days or not _is_am1(slot):
            continue
        teacher = getattr(data, "cls_subj_teacher", {}).get((cls, subj))
        if teacher is None:
            continue
        key = (str(teacher), str(slot.day))
        fixed_counts_by_teacher_day[key] = fixed_counts_by_teacher_day.get(key, 0) + 1

    presence_variable_names: dict[str, str] = {}
    presence_by_raw_key: dict[tuple[str, str], str] = {}
    presence_index = 1
    for teacher in teachers:
        for day in active_days:
            key = (teacher, day)
            name = _teacher_day_period_bool_name(presence_index, teacher, day, "am1")
            presence_index += 1
            presence_by_raw_key[key] = name
            presence_variable_names[_teacher_day_key(teacher, day)] = name

    weekly_count_variable_names: dict[str, str] = {}
    weekly_count_variables: list[VariableSpec] = []
    for index, teacher in enumerate(single_class_teachers, start=1):
        name = _teacher_weekly_count_var_name(index, teacher, "am1")
        weekly_count_variable_names[teacher] = name
        weekly_count_variables.append(
            VariableSpec(name=name, lower_bound=0, upper_bound=len(active_days), kind="int")
        )

    constraints: list[LinearConstraintSpec] = []
    counts = {
        "presence_fixed_one": 0,
        "presence_lower_bounds": 0,
        "presence_implies": 0,
        "presence_zero": 0,
        "weekly_count_equalities": 0,
        "weekly_count_caps": 0,
    }
    constraint_index = 1

    for teacher in teachers:
        for day in active_days:
            raw_key = (teacher, day)
            presence_name = presence_by_raw_key[raw_key]
            fixed_count = int(fixed_counts_by_teacher_day.get(raw_key, 0))
            var_names = tuple(sorted(variable_names_by_teacher_day.get(raw_key, ())))
            if fixed_count > 0:
                constraints.append(
                    _bool_value_constraint(
                        f"day_single_class_weekly_am1_cap__fixed_am1__{constraint_index:04d}__{_safe_identifier(teacher)}__{_safe_identifier(day)}",
                        presence_name,
                        1,
                        rule_id,
                    )
                )
                counts["presence_fixed_one"] += 1
                constraint_index += 1
            elif var_names:
                constraints.append(
                    LinearConstraintSpec(
                        name=f"day_single_class_weekly_am1_cap__has_am1_lower__{constraint_index:04d}__{_safe_identifier(teacher)}__{_safe_identifier(day)}",
                        expression=LinearExpression(
                            (
                                *(LinearTerm(name, 1) for name in var_names),
                                LinearTerm(presence_name, -1),
                            )
                        ),
                        sense=">=",
                        rhs=0,
                        rule_id=rule_id,
                    )
                )
                counts["presence_lower_bounds"] += 1
                constraint_index += 1
                for var_name in var_names:
                    constraints.append(
                        LinearConstraintSpec(
                            name=f"day_single_class_weekly_am1_cap__am1_implies__{constraint_index:04d}__{_safe_identifier(var_name)}",
                            expression=LinearExpression((LinearTerm(var_name, 1), LinearTerm(presence_name, -1))),
                            sense="<=",
                            rhs=0,
                            rule_id=rule_id,
                        )
                    )
                    counts["presence_implies"] += 1
                    constraint_index += 1
            else:
                constraints.append(
                    _bool_value_constraint(
                        f"day_single_class_weekly_am1_cap__no_am1__{constraint_index:04d}__{_safe_identifier(teacher)}__{_safe_identifier(day)}",
                        presence_name,
                        0,
                        rule_id,
                    )
                )
                counts["presence_zero"] += 1
                constraint_index += 1

    for teacher in single_class_teachers:
        count_name = weekly_count_variable_names[teacher]
        presence_names = tuple(presence_by_raw_key[(teacher, day)] for day in active_days)
        constraints.append(
            LinearConstraintSpec(
                name=f"day_single_class_weekly_am1_cap__weekly_count__{constraint_index:04d}__{_safe_identifier(teacher)}",
                expression=LinearExpression(
                    (
                        LinearTerm(count_name, 1),
                        *(LinearTerm(name, -1) for name in presence_names),
                    )
                ),
                sense="==",
                rhs=0,
                rule_id=rule_id,
            )
        )
        counts["weekly_count_equalities"] += 1
        constraint_index += 1
        constraints.append(
            LinearConstraintSpec(
                name=f"day_single_class_weekly_am1_cap__weekly_cap__{constraint_index:04d}__{_safe_identifier(teacher)}",
                expression=LinearExpression((LinearTerm(count_name, 1),)),
                sense="<=",
                rhs=max_occurrences,
                rule_id=rule_id,
            )
        )
        counts["weekly_count_caps"] += 1
        constraint_index += 1

    ai_rule = AiRuleSpec(
        rule_id=rule_id,
        description="Day hard rule: single-class teachers have a weekly cap on AM1 appearances.",
        enforcement="hard",
        priority=20,
        source="scheduler.model.constraints.day_weekday_constraints:apply_single_class_weekly_am1_cap",
    )
    problem = OptimizationProblemSpec(
        problem_id="scheduler_day_single_class_weekly_am1_cap",
        variables=(*assignment_variables, *tuple(VariableSpec.bool(name) for name in presence_variable_names.values()), *tuple(weekly_count_variables)),
        rules=(ai_rule,),
        constraints=tuple(constraints),
    )
    rule_first_plan = build_rule_first_plan(
        rules=problem.rules,
        constraints=problem.constraints,
        objective_rule_id=None,
    )
    return SchedulerGenericRuleBridge(
        problem=problem,
        rule_first_plan=rule_first_plan,
        metadata_by_rule={
            rule_id: {
                "scheduler_rule_id": rule_id,
                "legacy_apply_fn": "apply_single_class_weekly_am1_cap",
                "generic_contract_status": "covered_by_generic_contract",
                "runtime_rule_ids": generic_scheduler_rule_ids(),
                "constraint_family_counts": counts,
                "assignment_variable_names": assignment_names,
                "teacher_day_am1_assignment_variable_names": {
                    _teacher_day_key(teacher, day): tuple(sorted(names))
                    for (teacher, day), names in sorted(variable_names_by_teacher_day.items())
                },
                "teacher_day_presence_variable_names": presence_variable_names,
                "fixed_presence_counts": {
                    _teacher_day_key(teacher, day): int(count)
                    for (teacher, day), count in sorted(fixed_counts_by_teacher_day.items())
                },
                "weekly_count_variable_names": weekly_count_variable_names,
                "single_class_teachers": single_class_teachers,
                "active_days": active_days,
                "max_occurrences": max_occurrences,
            }
        },
    )


def day_two_class_am1_pm1_combo_to_ai_or_problem(
    data: Any,
    *,
    pe_teachers: Iterable[Any] = (),
    mode: str = "hard",
    weight: int = 3000,
    rule_id: str = "joint.day.two_class_am1_pm1_combo",
) -> SchedulerGenericRuleBridge:
    """Compile the two-class teacher AM-count/PM-count combo rule into OptimizationProblemSpec."""
    mode_norm = str(mode or "hard").strip().lower()
    if mode_norm not in {"hard", "soft"}:
        mode_norm = "hard"

    assignments = _day_candidate_assignment_names(data)
    assignment_variables = tuple(VariableSpec.bool(name) for (_cls, _subj, _slot, name) in assignments)
    assignment_names: dict[str, str] = {}
    pe_teacher_ids = {str(teacher) for teacher in pe_teachers}

    teacher_classes: dict[str, set[str]] = {}
    for (cls, subj), teacher in getattr(data, "cls_subj_teacher", {}).items():
        if is_pe_or_tech_subject(str(subj)):
            continue
        if teacher is None:
            continue
        teacher_classes.setdefault(str(teacher), set()).add(str(cls))
    two_class_teachers = tuple(
        sorted(
            teacher
            for teacher, class_set in teacher_classes.items()
            if len(class_set) == 2 and teacher not in pe_teacher_ids
        )
    )

    variable_names_by_teacher_day_halfday: dict[tuple[str, str, str], list[str]] = {}
    for cls, subj, slot, name in assignments:
        assignment_names[_assignment_key(cls, subj, str(slot.day), _slot_label(slot))] = name
        day = str(slot.day)
        if day not in WEEKDAY_DAYS:
            continue
        halfday = "am" if str(slot.block) == "上午" else "pm" if str(slot.block) == "下午" else None
        if halfday is None:
            continue
        teacher = getattr(data, "cls_subj_teacher", {}).get((cls, subj))
        if teacher is None or str(teacher) not in two_class_teachers:
            continue
        variable_names_by_teacher_day_halfday.setdefault((str(teacher), day, halfday), []).append(name)

    fixed_counts_by_teacher_day_halfday: dict[tuple[str, str, str], int] = {}
    for (cls, slot), subj in (getattr(data, "fixed_assign", {}) or {}).items():
        day = str(slot.day)
        if day not in WEEKDAY_DAYS:
            continue
        halfday = "am" if str(slot.block) == "上午" else "pm" if str(slot.block) == "下午" else None
        if halfday is None:
            continue
        teacher = getattr(data, "cls_subj_teacher", {}).get((cls, subj))
        if teacher is None or str(teacher) not in two_class_teachers:
            continue
        key = (str(teacher), day, halfday)
        fixed_counts_by_teacher_day_halfday[key] = fixed_counts_by_teacher_day_halfday.get(key, 0) + 1

    count_variable_names: dict[str, str] = {}
    count_bounds: dict[str, int] = {}
    count_variables: list[VariableSpec] = []
    count_index = 1
    for teacher in two_class_teachers:
        for day in WEEKDAY_DAYS:
            for halfday in ("am", "pm"):
                key = (teacher, str(day), halfday)
                metadata_key = _teacher_day_period_key(teacher, str(day), halfday)
                max_count = len(variable_names_by_teacher_day_halfday.get(key, ())) + int(
                    fixed_counts_by_teacher_day_halfday.get(key, 0)
                )
                name = _teacher_day_count_var_name(count_index, teacher, str(day), halfday)
                count_index += 1
                count_variable_names[metadata_key] = name
                count_bounds[metadata_key] = max_count
                count_variables.append(VariableSpec(name=name, lower_bound=0, upper_bound=max_count, kind="int"))

    constraints: list[ConstraintSpec] = []
    counts = {
        "teacher_day_count_equalities": 0,
        "teacher_day_hard_forbidden_combos": 0,
        "teacher_day_soft_allowed_violation_maps": 0,
    }
    constraint_index = 1
    for teacher in two_class_teachers:
        for day in WEEKDAY_DAYS:
            for halfday in ("am", "pm"):
                metadata_key = _teacher_day_period_key(teacher, str(day), halfday)
                raw_key = (teacher, str(day), halfday)
                fixed_count = int(fixed_counts_by_teacher_day_halfday.get(raw_key, 0))
                var_names = tuple(sorted(variable_names_by_teacher_day_halfday.get(raw_key, ())))
                constraints.append(
                    LinearConstraintSpec(
                        name=f"day_two_class_am1_pm1_combo__count_{halfday}__{constraint_index:04d}__{_safe_identifier(teacher)}__{_safe_identifier(str(day))}",
                        expression=LinearExpression(
                            (
                                LinearTerm(count_variable_names[metadata_key], 1),
                                *(LinearTerm(name, -1) for name in var_names),
                            )
                        ),
                        sense="==",
                        rhs=fixed_count,
                        rule_id=rule_id,
                    )
                )
                counts["teacher_day_count_equalities"] += 1
                constraint_index += 1

    violation_variable_names: dict[str, str] = {}
    violation_variables: list[VariableSpec] = []
    violation_index = 1
    for teacher in two_class_teachers:
        for day in WEEKDAY_DAYS:
            day_text = str(day)
            am_key = _teacher_day_period_key(teacher, day_text, "am")
            pm_key = _teacher_day_period_key(teacher, day_text, "pm")
            if mode_norm == "hard":
                constraints.append(
                    ForbiddenAssignmentsConstraintSpec(
                        name=f"day_two_class_am1_pm1_combo__hard_forbid__{constraint_index:04d}__{_safe_identifier(teacher)}__{_safe_identifier(day_text)}",
                        variables=(count_variable_names[am_key], count_variable_names[pm_key]),
                        tuples=((1, 1),),
                        rule_id=rule_id,
                    )
                )
                counts["teacher_day_hard_forbidden_combos"] += 1
                constraint_index += 1
                continue

            violation_name = _teacher_day_violation_bool_name(violation_index, teacher, day_text, "two_class_am1_pm1")
            violation_index += 1
            violation_variable_names[_teacher_day_key(teacher, day_text)] = violation_name
            violation_variables.append(VariableSpec.bool(violation_name))
            allowed_tuples = tuple(
                (am_count, pm_count, 1 if am_count == 1 and pm_count == 1 else 0)
                for am_count in range(0, count_bounds[am_key] + 1)
                for pm_count in range(0, count_bounds[pm_key] + 1)
            )
            constraints.append(
                AllowedAssignmentsConstraintSpec(
                    name=f"day_two_class_am1_pm1_combo__soft_map__{constraint_index:04d}__{_safe_identifier(teacher)}__{_safe_identifier(day_text)}",
                    variables=(count_variable_names[am_key], count_variable_names[pm_key], violation_name),
                    tuples=allowed_tuples,
                    rule_id=rule_id,
                )
            )
            counts["teacher_day_soft_allowed_violation_maps"] += 1
            constraint_index += 1

    objective = None
    if mode_norm == "soft" and violation_variable_names:
        objective = ObjectiveSpec(
            rule_id=rule_id,
            sense="minimize",
            expression=LinearExpression(
                tuple(LinearTerm(name, int(weight)) for name in violation_variable_names.values())
            ),
        )
    ai_rule = AiRuleSpec(
        rule_id=rule_id,
        description="Day rule: two-class non-PE/tech teachers cannot or should not have exactly one AM class and exactly one PM class on the same weekday.",
        enforcement=mode_norm,
        priority=18,
        source="scheduler.model.constraints.day_weekday_constraints:apply_two_class_am1_pm1_combo",
    )
    problem = OptimizationProblemSpec(
        problem_id="scheduler_day_two_class_am1_pm1_combo",
        variables=(*assignment_variables, *tuple(count_variables), *tuple(violation_variables)),
        rules=(ai_rule,),
        constraints=tuple(constraints),
        objective=objective,
    )
    rule_first_plan = build_rule_first_plan(
        rules=problem.rules,
        constraints=problem.constraints,
        objective_rule_id=objective.rule_id if objective is not None else None,
    )
    return SchedulerGenericRuleBridge(
        problem=problem,
        rule_first_plan=rule_first_plan,
        metadata_by_rule={
            rule_id: {
                "scheduler_rule_id": rule_id,
                "legacy_apply_fn": "apply_two_class_am1_pm1_combo",
                "generic_contract_status": "covered_by_generic_contract",
                "runtime_rule_ids": generic_scheduler_rule_ids(),
                "constraint_family_counts": counts,
                "assignment_variable_names": assignment_names,
                "two_class_teachers": two_class_teachers,
                "pe_teachers": tuple(sorted(pe_teacher_ids)),
                "teacher_day_count_assignment_variable_names": {
                    _teacher_day_period_key(teacher, day, halfday): tuple(sorted(names))
                    for (teacher, day, halfday), names in sorted(variable_names_by_teacher_day_halfday.items())
                },
                "teacher_day_count_variable_names": count_variable_names,
                "fixed_count_constants": {
                    _teacher_day_period_key(teacher, day, halfday): int(count)
                    for (teacher, day, halfday), count in sorted(fixed_counts_by_teacher_day_halfday.items())
                },
                "max_count_bounds": count_bounds,
                "violation_variable_names": violation_variable_names,
                "mode": mode_norm,
                "weight": int(weight),
            }
        },
    )


def day_two_class_low_hours_max_empty_days_to_ai_or_problem(
    data: Any,
    *,
    pe_teachers: Iterable[Any] = (),
    threshold: int,
    max_empty_days: int,
    rule_id: str = "joint.day.two_class_low_hours_max_empty_days",
) -> SchedulerGenericRuleBridge:
    """Compile the two-class low-hours teacher max-empty-weekdays hard rule."""
    threshold = int(threshold)
    max_empty_days = int(max_empty_days)
    assignments = _day_candidate_assignment_names(data)
    assignment_variables = tuple(VariableSpec.bool(name) for (_cls, _subj, _slot, name) in assignments)
    assignment_names: dict[str, str] = {}
    pe_teacher_ids = {str(teacher) for teacher in pe_teachers}

    teacher_classes: dict[str, set[str]] = {}
    for (cls, subj), teacher in getattr(data, "cls_subj_teacher", {}).items():
        if is_pe_or_tech_subject(str(subj)) or not teacher:
            continue
        teacher_classes.setdefault(str(teacher), set()).add(str(cls))

    teacher_weekday_hours: dict[str, int] = {}
    for (cls, subj), teacher in getattr(data, "cls_subj_teacher", {}).items():
        if is_pe_or_tech_subject(str(subj)) or not teacher:
            continue
        req = getattr(data, "req_hours", {}).get((cls, subj))
        if not req:
            continue
        _early, weekday_hours, _weekend = req
        teacher_weekday_hours[str(teacher)] = teacher_weekday_hours.get(str(teacher), 0) + int(weekday_hours)

    target_teachers = tuple(
        sorted(
            teacher
            for teacher, class_set in teacher_classes.items()
            if teacher not in pe_teacher_ids
            and len(class_set) == 2
            and teacher_weekday_hours.get(teacher, 0) < threshold
        )
    )
    target_teacher_set = set(target_teachers)

    variable_names_by_teacher_day: dict[tuple[str, str], list[str]] = {}
    for cls, subj, slot, name in assignments:
        assignment_names[_assignment_key(cls, subj, str(slot.day), _slot_label(slot))] = name
        day = str(slot.day)
        if day not in WEEKDAY_DAYS or not _is_daytime(slot):
            continue
        teacher = getattr(data, "cls_subj_teacher", {}).get((cls, subj))
        if teacher is None or str(teacher) not in target_teacher_set:
            continue
        variable_names_by_teacher_day.setdefault((str(teacher), day), []).append(name)

    fixed_counts_by_teacher_day: dict[tuple[str, str], int] = {}
    for (cls, slot), subj in (getattr(data, "fixed_assign", {}) or {}).items():
        day = str(slot.day)
        if day not in WEEKDAY_DAYS or not _is_daytime(slot):
            continue
        teacher = getattr(data, "cls_subj_teacher", {}).get((cls, subj))
        if teacher is None or str(teacher) not in target_teacher_set:
            continue
        key = (str(teacher), day)
        fixed_counts_by_teacher_day[key] = fixed_counts_by_teacher_day.get(key, 0) + 1

    has_any_variable_names: dict[str, str] = {}
    empty_variable_names: dict[str, str] = {}
    has_any_variables: list[VariableSpec] = []
    empty_variables: list[VariableSpec] = []
    bool_index = 1
    for teacher in target_teachers:
        for day in WEEKDAY_DAYS:
            key = _teacher_day_key(teacher, str(day))
            has_any_name = f"two_class_low_has__{bool_index:04d}__{_safe_identifier(teacher)}__{_safe_identifier(str(day))}"
            bool_index += 1
            empty_name = f"two_class_low_empty__{bool_index:04d}__{_safe_identifier(teacher)}__{_safe_identifier(str(day))}"
            bool_index += 1
            has_any_variable_names[key] = has_any_name
            empty_variable_names[key] = empty_name
            has_any_variables.append(VariableSpec.bool(has_any_name))
            empty_variables.append(VariableSpec.bool(empty_name))

    constraints: list[LinearConstraintSpec] = []
    counts = {
        "has_any_fixed_one": 0,
        "has_any_lower_bounds": 0,
        "has_any_implies": 0,
        "has_any_zero": 0,
        "empty_complements": 0,
        "empty_day_caps": 0,
    }
    constraint_index = 1
    for teacher in target_teachers:
        empty_names_for_teacher: list[str] = []
        for day in WEEKDAY_DAYS:
            day_text = str(day)
            raw_key = (teacher, day_text)
            metadata_key = _teacher_day_key(teacher, day_text)
            has_any_name = has_any_variable_names[metadata_key]
            empty_name = empty_variable_names[metadata_key]
            empty_names_for_teacher.append(empty_name)
            fixed_count = int(fixed_counts_by_teacher_day.get(raw_key, 0))
            var_names = tuple(sorted(variable_names_by_teacher_day.get(raw_key, ())))
            if fixed_count > 0:
                constraints.append(
                    _bool_value_constraint(
                        f"day_two_class_low_hours__has_any_fixed__{constraint_index:04d}__{_safe_identifier(teacher)}__{_safe_identifier(day_text)}",
                        has_any_name,
                        1,
                        rule_id,
                    )
                )
                counts["has_any_fixed_one"] += 1
                constraint_index += 1
            elif var_names:
                constraints.append(
                    LinearConstraintSpec(
                        name=f"day_two_class_low_hours__has_any_lower__{constraint_index:04d}__{_safe_identifier(teacher)}__{_safe_identifier(day_text)}",
                        expression=LinearExpression(
                            (
                                *(LinearTerm(name, 1) for name in var_names),
                                LinearTerm(has_any_name, -1),
                            )
                        ),
                        sense=">=",
                        rhs=0,
                        rule_id=rule_id,
                    )
                )
                counts["has_any_lower_bounds"] += 1
                constraint_index += 1
                for var_name in var_names:
                    constraints.append(
                        LinearConstraintSpec(
                            name=f"day_two_class_low_hours__assignment_implies_has__{constraint_index:04d}__{_safe_identifier(var_name)}",
                            expression=LinearExpression((LinearTerm(var_name, 1), LinearTerm(has_any_name, -1))),
                            sense="<=",
                            rhs=0,
                            rule_id=rule_id,
                        )
                    )
                    counts["has_any_implies"] += 1
                    constraint_index += 1
            else:
                constraints.append(
                    _bool_value_constraint(
                        f"day_two_class_low_hours__has_any_zero__{constraint_index:04d}__{_safe_identifier(teacher)}__{_safe_identifier(day_text)}",
                        has_any_name,
                        0,
                        rule_id,
                    )
                )
                counts["has_any_zero"] += 1
                constraint_index += 1

            constraints.append(
                LinearConstraintSpec(
                    name=f"day_two_class_low_hours__empty_complement__{constraint_index:04d}__{_safe_identifier(teacher)}__{_safe_identifier(day_text)}",
                    expression=LinearExpression((LinearTerm(empty_name, 1), LinearTerm(has_any_name, 1))),
                    sense="==",
                    rhs=1,
                    rule_id=rule_id,
                )
            )
            counts["empty_complements"] += 1
            constraint_index += 1

        if empty_names_for_teacher:
            constraints.append(
                LinearConstraintSpec(
                    name=f"day_two_class_low_hours__empty_day_cap__{constraint_index:04d}__{_safe_identifier(teacher)}",
                    expression=_sum_expr(empty_names_for_teacher),
                    sense="<=",
                    rhs=max_empty_days,
                    rule_id=rule_id,
                )
            )
            counts["empty_day_caps"] += 1
            constraint_index += 1

    ai_rule = AiRuleSpec(
        rule_id=rule_id,
        description="Day hard rule: two-class non-PE/tech low-hours teachers have a cap on empty weekdays.",
        enforcement="hard",
        priority=21,
        source="scheduler.model.constraints.day_weekday_constraints:apply_two_class_low_hours_max_empty_days",
    )
    problem = OptimizationProblemSpec(
        problem_id="scheduler_day_two_class_low_hours_max_empty_days",
        variables=(*assignment_variables, *tuple(has_any_variables), *tuple(empty_variables)),
        rules=(ai_rule,),
        constraints=tuple(constraints),
    )
    rule_first_plan = build_rule_first_plan(
        rules=problem.rules,
        constraints=problem.constraints,
        objective_rule_id=None,
    )
    return SchedulerGenericRuleBridge(
        problem=problem,
        rule_first_plan=rule_first_plan,
        metadata_by_rule={
            rule_id: {
                "scheduler_rule_id": rule_id,
                "legacy_apply_fn": "apply_two_class_low_hours_max_empty_days",
                "generic_contract_status": "covered_by_generic_contract",
                "runtime_rule_ids": generic_scheduler_rule_ids(),
                "constraint_family_counts": counts,
                "assignment_variable_names": assignment_names,
                "two_class_low_hour_teachers": target_teachers,
                "pe_teachers": tuple(sorted(pe_teacher_ids)),
                "teacher_classes": {
                    teacher: tuple(sorted(classes))
                    for teacher, classes in sorted(teacher_classes.items())
                },
                "teacher_weekday_hours": teacher_weekday_hours,
                "teacher_day_assignment_variable_names": {
                    _teacher_day_key(teacher, day): tuple(sorted(names))
                    for (teacher, day), names in sorted(variable_names_by_teacher_day.items())
                },
                "fixed_count_constants": {
                    _teacher_day_key(teacher, day): int(count)
                    for (teacher, day), count in sorted(fixed_counts_by_teacher_day.items())
                },
                "has_any_variable_names": has_any_variable_names,
                "empty_variable_names": empty_variable_names,
                "threshold": threshold,
                "max_empty_days": max_empty_days,
            }
        },
    )


def day_low_weekday_subject_max1_per_day_to_ai_or_problem(
    data: Any,
    *,
    max_weekday_hours: int,
    rule_id: str = "joint.day.low_weekday_subject_max1_per_day",
) -> SchedulerGenericRuleBridge:
    """Compile low-weekday-hour class-subject daily max-one constraints."""
    return _weekday_subject_daily_limit_to_ai_or_problem(
        data,
        threshold=int(max_weekday_hours),
        threshold_direction="low",
        sense="<=",
        rhs=1,
        rule_id=rule_id,
        problem_id="scheduler_day_low_weekday_subject_max1_per_day",
        legacy_apply_fn="apply_low_weekday_subject_max1_per_day",
        priority=22,
        source="scheduler.model.constraints.day_weekday_constraints:apply_low_weekday_subject_max1_per_day",
        description="Day hard rule: class-subjects with low weekday hour quotas can appear at most once per weekday.",
        constraint_family_name="low_subject_daily_max_constraints",
    )


def day_high_weekday_subject_min1_per_day_to_ai_or_problem(
    data: Any,
    *,
    min_weekday_hours: int,
    rule_id: str = "joint.day.high_weekday_subject_min1_per_day",
) -> SchedulerGenericRuleBridge:
    """Compile high-weekday-hour class-subject daily min-one constraints."""
    return _weekday_subject_daily_limit_to_ai_or_problem(
        data,
        threshold=int(min_weekday_hours),
        threshold_direction="high",
        sense=">=",
        rhs=1,
        rule_id=rule_id,
        problem_id="scheduler_day_high_weekday_subject_min1_per_day",
        legacy_apply_fn="apply_high_weekday_subject_min1_per_day",
        priority=23,
        source="scheduler.model.constraints.day_weekday_constraints:apply_high_weekday_subject_min1_per_day",
        description="Day hard rule: class-subjects with high weekday hour quotas appear at least once per weekday.",
        constraint_family_name="high_subject_daily_min_constraints",
    )


def day_pe_time_window_hard_to_ai_or_problem(
    data: Any,
    *,
    rule_id: str = "joint.day.pe_time_window_hard",
) -> SchedulerGenericRuleBridge:
    """Compile PE time-window hard zero constraints into OptimizationProblemSpec."""
    assignments = _day_candidate_assignment_names(data)
    variables = tuple(VariableSpec.bool(name) for (_cls, _subj, _slot, name) in assignments)
    assignment_names: dict[str, str] = {}
    illegal_variable_names: dict[str, str] = {}
    for cls, subj, slot, name in assignments:
        assignment_names[_assignment_key(cls, subj, str(slot.day), _slot_label(slot))] = name
        if not is_day_pe_subject(str(subj)):
            continue
        if _is_pe_time_window_allowed(slot):
            continue
        illegal_variable_names[_assignment_key(cls, subj, str(slot.day), _slot_label(slot))] = name

    illegal_fixed_count = 0
    for (_cls, slot), subj in (getattr(data, "fixed_assign", {}) or {}).items():
        if is_day_pe_subject(str(subj)) and not _is_pe_time_window_allowed(slot):
            illegal_fixed_count += 1

    constraints = tuple(
        _bool_value_constraint(
            f"day_pe_time_window_hard__{index:04d}__{_safe_identifier(key)}",
            var_name,
            0,
            rule_id,
        )
        for index, (key, var_name) in enumerate(sorted(illegal_variable_names.items()), start=1)
    )

    ai_rule = AiRuleSpec(
        rule_id=rule_id,
        description="Day hard rule: PE subjects can only use weekday PM slots or Wednesday-Friday AM4.",
        enforcement="hard",
        priority=26,
        source="scheduler.model.constraints.day_pe_tech_constraints:apply_pe_time_window_hard",
    )
    problem = OptimizationProblemSpec(
        problem_id="scheduler_day_pe_time_window_hard",
        variables=variables,
        rules=(ai_rule,),
        constraints=constraints,
    )
    rule_first_plan = build_rule_first_plan(
        rules=problem.rules,
        constraints=problem.constraints,
        objective_rule_id=None,
    )
    return SchedulerGenericRuleBridge(
        problem=problem,
        rule_first_plan=rule_first_plan,
        metadata_by_rule={
            rule_id: {
                "scheduler_rule_id": rule_id,
                "legacy_apply_fn": "apply_pe_time_window_hard",
                "generic_contract_status": "covered_by_generic_contract",
                "runtime_rule_ids": generic_scheduler_rule_ids(),
                "constraint_family_counts": {
                    "pe_illegal_time_window_zeroes": len(constraints),
                },
                "assignment_variable_names": assignment_names,
                "illegal_assignment_variable_names": illegal_variable_names,
                "illegal_fixed_count": illegal_fixed_count,
            }
        },
    )


def day_teacher_whitelist_hard_to_ai_or_problem(
    data: Any,
    *,
    teacher_name: str,
    allowed: Iterable[tuple[Any, Any]],
    rule_id: str = "joint.day.teacher_whitelist_hard",
) -> SchedulerGenericRuleBridge:
    """Compile a PE/tech teacher allowed-slot whitelist into hard zero constraints."""
    teacher_text = str(teacher_name)
    allowed_slots = {
        (str(day), str(slot_key))
        for day, slot_key in allowed
    }
    assignments = _day_candidate_assignment_names(data)
    variables = tuple(VariableSpec.bool(name) for (_cls, _subj, _slot, name) in assignments)
    assignment_names: dict[str, str] = {}
    illegal_variable_names: dict[str, str] = {}
    for cls, subj, slot, name in assignments:
        assignment_names[_assignment_key(cls, subj, str(slot.day), _slot_label(slot))] = name
        if not is_pe_or_tech_subject(str(subj)):
            continue
        teacher = getattr(data, "cls_subj_teacher", {}).get((cls, subj))
        if str(teacher) != teacher_text:
            continue
        if (str(slot.day), _slot_label(slot)) in allowed_slots:
            continue
        illegal_variable_names[_assignment_key(cls, subj, str(slot.day), _slot_label(slot))] = name

    illegal_fixed_count = 0
    for (cls, slot), subj in (getattr(data, "fixed_assign", {}) or {}).items():
        if not is_pe_or_tech_subject(str(subj)):
            continue
        teacher = getattr(data, "cls_subj_teacher", {}).get((cls, subj))
        if str(teacher) == teacher_text and (str(slot.day), _slot_label(slot)) not in allowed_slots:
            illegal_fixed_count += 1

    constraints = tuple(
        _bool_value_constraint(
            f"day_teacher_whitelist_hard__{index:04d}__{_safe_identifier(key)}",
            var_name,
            0,
            rule_id,
        )
        for index, (key, var_name) in enumerate(sorted(illegal_variable_names.items()), start=1)
    )

    ai_rule = AiRuleSpec(
        rule_id=rule_id,
        description="Day hard rule: a named PE/tech teacher can only teach in whitelisted slots.",
        enforcement="hard",
        priority=27,
        source="scheduler.model.constraints.day_pe_tech_constraints:apply_teacher_whitelist_hard",
    )
    problem = OptimizationProblemSpec(
        problem_id="scheduler_day_teacher_whitelist_hard",
        variables=variables,
        rules=(ai_rule,),
        constraints=constraints,
    )
    rule_first_plan = build_rule_first_plan(
        rules=problem.rules,
        constraints=problem.constraints,
        objective_rule_id=None,
    )
    return SchedulerGenericRuleBridge(
        problem=problem,
        rule_first_plan=rule_first_plan,
        metadata_by_rule={
            rule_id: {
                "scheduler_rule_id": rule_id,
                "legacy_apply_fn": "apply_teacher_whitelist_hard",
                "generic_contract_status": "covered_by_generic_contract",
                "runtime_rule_ids": generic_scheduler_rule_ids(),
                "constraint_family_counts": {
                    "teacher_whitelist_illegal_zeroes": len(constraints),
                },
                "assignment_variable_names": assignment_names,
                "illegal_assignment_variable_names": illegal_variable_names,
                "illegal_fixed_count": illegal_fixed_count,
                "teacher_name": teacher_text,
                "allowed_slots": tuple(f"{day}|{slot_key}" for day, slot_key in sorted(allowed_slots)),
            }
        },
    )


def day_reduce_stem_am1_to_ai_or_problem(
    data: Any,
    *,
    weight: int = 150,
    rule_id: str = "joint.day.reduce_stem_am1",
) -> SchedulerGenericRuleBridge:
    """Compile the STEM AM1 reduction soft preference into OptimizationProblemSpec."""
    assignments = _day_candidate_assignment_names(data)
    assignment_variables = tuple(VariableSpec.bool(name) for (_cls, _subj, _slot, name) in assignments)
    assignment_names: dict[str, str] = {}
    penalty_variable_names: dict[str, str] = {}
    for cls, subj, slot, name in assignments:
        key = _assignment_key(cls, subj, str(slot.day), _slot_label(slot))
        assignment_names[key] = name
        if is_weekday_day(str(slot.day)) and is_stem_subject(str(subj)) and _is_am1(slot):
            penalty_variable_names[key] = name

    fixed_penalty_count = 0
    for (cls, slot), subj in getattr(data, "fixed_assign", {}).items():
        if is_weekday_day(str(slot.day)) and is_stem_subject(str(subj)) and _is_am1(slot):
            fixed_penalty_count += 1

    objective = ObjectiveSpec(
        rule_id=rule_id,
        sense="minimize",
        expression=LinearExpression(
            tuple(LinearTerm(name, int(weight)) for name in penalty_variable_names.values())
        ),
    )
    ai_rule = AiRuleSpec(
        rule_id=rule_id,
        description="Day soft rule: penalize math, physics, and chemistry assignments in weekday AM1 slots.",
        enforcement="soft",
        priority=32,
        source="scheduler.model.constraints.day_weekday_constraints:apply_reduce_stem_am1",
    )
    problem = OptimizationProblemSpec(
        problem_id="scheduler_day_reduce_stem_am1",
        variables=assignment_variables,
        rules=(ai_rule,),
        constraints=(),
        objective=objective,
    )
    rule_first_plan = build_rule_first_plan(
        rules=problem.rules,
        constraints=problem.constraints,
        objective_rule_id=objective.rule_id,
    )
    return SchedulerGenericRuleBridge(
        problem=problem,
        rule_first_plan=rule_first_plan,
        metadata_by_rule={
            rule_id: {
                "scheduler_rule_id": rule_id,
                "legacy_apply_fn": "apply_reduce_stem_am1",
                "generic_contract_status": "covered_by_generic_contract",
                "runtime_rule_ids": generic_scheduler_rule_ids(),
                "constraint_family_counts": {
                    "stem_am1_penalty_terms": len(penalty_variable_names),
                },
                "assignment_variable_names": assignment_names,
                "penalty_variable_names": tuple(penalty_variable_names.values()),
                "fixed_penalty_count": fixed_penalty_count,
                "weight": int(weight),
            }
        },
    )


def day_pe_reduce_am_soft_to_ai_or_problem(
    data: Any,
    *,
    pe_teachers: Iterable[Any],
    weight: int = 100,
    rule_id: str = "joint.day.pe_reduce_am_soft",
) -> SchedulerGenericRuleBridge:
    """Compile the PE-teacher weekday morning soft preference into OptimizationProblemSpec."""
    target_teachers = tuple(sorted(set(_teacher_names(pe_teachers))))
    target_teacher_set = set(target_teachers)
    assignments = _day_candidate_assignment_names(data)
    assignment_variables = tuple(VariableSpec.bool(name) for (_cls, _subj, _slot, name) in assignments)
    assignment_names: dict[str, str] = {}
    penalty_variable_names: dict[str, str] = {}
    for cls, subj, slot, name in assignments:
        key = _assignment_key(cls, subj, str(slot.day), _slot_label(slot))
        assignment_names[key] = name
        teacher = getattr(data, "cls_subj_teacher", {}).get((cls, subj))
        if (
            str(teacher) in target_teacher_set
            and is_weekday_day(str(slot.day))
            and str(slot.block) == "上午"
            and is_pe_or_tech_subject(str(subj))
        ):
            penalty_variable_names[key] = name

    objective = ObjectiveSpec(
        rule_id=rule_id,
        sense="minimize",
        expression=LinearExpression(
            tuple(LinearTerm(name, int(weight)) for name in penalty_variable_names.values())
        ),
    )
    ai_rule = AiRuleSpec(
        rule_id=rule_id,
        description="Day soft rule: penalize PE/tech assignments taught by PE teachers in weekday morning slots.",
        enforcement="soft",
        priority=38,
        source="scheduler.model.constraints.day_pe_tech_constraints:apply_pe_reduce_am_soft",
    )
    problem = OptimizationProblemSpec(
        problem_id="scheduler_day_pe_reduce_am_soft",
        variables=assignment_variables,
        rules=(ai_rule,),
        constraints=(),
        objective=objective,
    )
    rule_first_plan = build_rule_first_plan(
        rules=problem.rules,
        constraints=problem.constraints,
        objective_rule_id=objective.rule_id,
    )
    return SchedulerGenericRuleBridge(
        problem=problem,
        rule_first_plan=rule_first_plan,
        metadata_by_rule={
            rule_id: {
                "scheduler_rule_id": rule_id,
                "legacy_apply_fn": "apply_pe_reduce_am_soft",
                "generic_contract_status": "covered_by_generic_contract",
                "runtime_rule_ids": generic_scheduler_rule_ids(),
                "constraint_family_counts": {
                    "pe_weekday_morning_penalty_terms": len(penalty_variable_names),
                },
                "assignment_variable_names": assignment_names,
                "penalty_variable_names": tuple(penalty_variable_names.values()),
                "pe_teachers": target_teachers,
                "weight": int(weight),
            }
        },
    )


def day_pref_lang_am_to_ai_or_problem(
    data: Any,
    *,
    enabled: bool = True,
    target_teachers: Iterable[Any] | None = None,
    am1_reward: int = 200,
    pm1_penalty: int = 4500,
    pm2_penalty: int = 3000,
    pm3_penalty: int = 2000,
    rule_id: str = "joint.day.pref_lang_am",
) -> SchedulerGenericRuleBridge:
    """Compile the Tuesday-Friday language AM preference and PM penalties into OptimizationProblemSpec."""
    assignments = _day_candidate_assignment_names(data)
    assignment_variables = tuple(VariableSpec.bool(name) for (_cls, _subj, _slot, name) in assignments)
    assignment_names: dict[str, str] = {}
    bucket_names: dict[str, dict[str, str]] = {
        "am1": {},
        "pm1": {},
        "pm2": {},
        "pm3": {},
    }
    targets = tuple(sorted(set(_teacher_names(target_teachers or ()))))
    target_set = set(targets)
    for cls, subj, slot, name in assignments:
        key = _assignment_key(cls, subj, str(slot.day), _slot_label(slot))
        assignment_names[key] = name
        if not enabled or str(slot.day) not in TUESDAY_TO_FRIDAY or not is_lang_subject(str(subj)):
            continue
        teacher = str(getattr(data, "cls_subj_teacher", {}).get((cls, subj), "")).strip()
        if target_set and teacher not in target_set:
            continue
        if _is_am1(slot):
            bucket_names["am1"][key] = name
        elif str(slot.block) == "下午" and int(slot.period) == 1:
            bucket_names["pm1"][key] = name
        elif str(slot.block) == "下午" and int(slot.period) == 2:
            bucket_names["pm2"][key] = name
        elif str(slot.block) == "下午" and int(slot.period) == 3:
            bucket_names["pm3"][key] = name

    objective_terms = (
        *(LinearTerm(name, -int(am1_reward)) for name in bucket_names["am1"].values() if int(am1_reward) > 0),
        *(LinearTerm(name, int(pm1_penalty)) for name in bucket_names["pm1"].values() if int(pm1_penalty) > 0),
        *(LinearTerm(name, int(pm2_penalty)) for name in bucket_names["pm2"].values() if int(pm2_penalty) > 0),
        *(LinearTerm(name, int(pm3_penalty)) for name in bucket_names["pm3"].values() if int(pm3_penalty) > 0),
    )
    objective = ObjectiveSpec(
        rule_id=rule_id,
        sense="minimize",
        expression=LinearExpression(tuple(objective_terms)),
    )
    ai_rule = AiRuleSpec(
        rule_id=rule_id,
        description="Day soft rule: reward language assignments in Tue-Fri AM1 and penalize Tue-Fri PM slots.",
        enforcement="soft",
        priority=31,
        source="scheduler.model.constraints.day_weekday_constraints:apply_pref_lang_am",
    )
    problem = OptimizationProblemSpec(
        problem_id="scheduler_day_pref_lang_am",
        variables=assignment_variables,
        rules=(ai_rule,),
        constraints=(),
        objective=objective,
    )
    rule_first_plan = build_rule_first_plan(
        rules=problem.rules,
        constraints=problem.constraints,
        objective_rule_id=objective.rule_id,
    )
    return SchedulerGenericRuleBridge(
        problem=problem,
        rule_first_plan=rule_first_plan,
        metadata_by_rule={
            rule_id: {
                "scheduler_rule_id": rule_id,
                "legacy_apply_fn": "apply_pref_lang_am",
                "generic_contract_status": "covered_by_generic_contract",
                "runtime_rule_ids": generic_scheduler_rule_ids(),
                "constraint_family_counts": {
                    "lang_tue_fri_am1_reward_terms": len(bucket_names["am1"]),
                    "lang_tue_fri_pm1_penalty_terms": len(bucket_names["pm1"]),
                    "lang_tue_fri_pm2_penalty_terms": len(bucket_names["pm2"]),
                    "lang_tue_fri_pm3_penalty_terms": len(bucket_names["pm3"]),
                },
                "assignment_variable_names": assignment_names,
                "bucket_variable_names": {bucket: dict(names) for bucket, names in bucket_names.items()},
                "target_teachers": targets,
                "weights": {
                    "am1_reward": int(am1_reward),
                    "pm1_penalty": int(pm1_penalty),
                    "pm2_penalty": int(pm2_penalty),
                    "pm3_penalty": int(pm3_penalty),
                },
            }
        },
    )


def day_pe_tech_compact_soft_to_ai_or_problem(
    data: Any,
    *,
    pe_tech_teachers: Iterable[Any],
    weight: int = 200,
    rule_id: str = "joint.day.pe_tech_compact_soft",
) -> SchedulerGenericRuleBridge:
    """Compile PE/tech halfday compactness gap penalties into OptimizationProblemSpec."""
    target_teachers = tuple(sorted(set(_teacher_names(pe_tech_teachers))))
    target_teacher_set = set(target_teachers)
    assignments = _day_candidate_assignment_names(data)
    assignment_variables = tuple(VariableSpec.bool(name) for (_cls, _subj, _slot, name) in assignments)
    assignment_names: dict[str, str] = {}
    names_by_teacher_day_slot: dict[tuple[str, str, Any], list[str]] = {}
    for cls, subj, slot, name in assignments:
        key = _assignment_key(cls, subj, str(slot.day), _slot_label(slot))
        assignment_names[key] = name
        teacher = str(getattr(data, "cls_subj_teacher", {}).get((cls, subj), "")).strip()
        if (
            teacher in target_teacher_set
            and is_weekday_day(str(slot.day))
            and is_pe_or_tech_subject(str(subj))
        ):
            names_by_teacher_day_slot.setdefault((teacher, str(slot.day), slot), []).append(name)

    raw_busy_keys = tuple(
        sorted(
            names_by_teacher_day_slot,
            key=lambda item: (item[0], WEEKDAY_DAYS.index(item[1]), _slot_order_key(item[2])),
        )
    )
    busy_variable_names = {
        _teacher_day_period_key(teacher, day, _slot_label(slot)): _pe_tech_busy_bool_name(
            index,
            teacher,
            day,
            slot,
        )
        for index, (teacher, day, slot) in enumerate(raw_busy_keys, start=1)
    }
    busy_by_raw_key = {
        (teacher, day, slot): busy_variable_names[_teacher_day_period_key(teacher, day, _slot_label(slot))]
        for teacher, day, slot in raw_busy_keys
    }
    busy_variables = tuple(VariableSpec.bool(name) for name in busy_variable_names.values())

    constraints: list[LinearConstraintSpec] = []
    gap_variable_names: dict[str, str] = {}
    gap_variables: list[VariableSpec] = []
    counts = {
        "pe_tech_busy_equalities": 0,
        "pe_tech_101_gap_constraints": 0,
        "pe_tech_adjacent_gap_constraints": 0,
        "pe_tech_gap_penalty_terms": 0,
    }
    constraint_index = 1

    for raw_key in raw_busy_keys:
        teacher, day, slot = raw_key
        busy_name = busy_by_raw_key[raw_key]
        assignment_var_names = tuple(sorted(names_by_teacher_day_slot[raw_key]))
        constraints.append(
            LinearConstraintSpec(
                name=f"day_pe_tech_compact__busy__{constraint_index:04d}__{_safe_identifier(busy_name)}",
                expression=LinearExpression(
                    (
                        *(LinearTerm(name, 1) for name in assignment_var_names),
                        LinearTerm(busy_name, -1),
                    )
                ),
                sense="==",
                rhs=0,
                rule_id=rule_id,
            )
        )
        counts["pe_tech_busy_equalities"] += 1
        constraint_index += 1

    def build_gap_constraints(teacher: str, day: str, slots: tuple[Any, ...], tag: str) -> None:
        nonlocal constraint_index
        if not slots:
            return
        busy_names = tuple(busy_by_raw_key[(teacher, day, slot)] for slot in slots)
        if len(busy_names) >= 3:
            for index in range(len(busy_names) - 2):
                b1, b2, b3 = busy_names[index], busy_names[index + 1], busy_names[index + 2]
                gap_key = f"{teacher}|{day}|{tag}|{index}"
                gap_name = _pe_tech_gap_bool_name(len(gap_variable_names) + 1, teacher, day, tag, index)
                gap_variable_names[gap_key] = gap_name
                gap_variables.append(VariableSpec.bool(gap_name))
                for suffix, terms, sense, rhs in (
                    ("upper_left", (LinearTerm(gap_name, 1), LinearTerm(b1, -1)), "<=", 0),
                    ("upper_right", (LinearTerm(gap_name, 1), LinearTerm(b3, -1)), "<=", 0),
                    ("upper_middle_empty", (LinearTerm(gap_name, 1), LinearTerm(b2, 1)), "<=", 1),
                    (
                        "lower_101",
                        (
                            LinearTerm(gap_name, 1),
                            LinearTerm(b1, -1),
                            LinearTerm(b3, -1),
                            LinearTerm(b2, 1),
                        ),
                        ">=",
                        -1,
                    ),
                ):
                    constraints.append(
                        LinearConstraintSpec(
                            name=f"day_pe_tech_compact__gap_{suffix}__{constraint_index:04d}__{_safe_identifier(gap_name)}",
                            expression=LinearExpression(tuple(terms)),
                            sense=sense,
                            rhs=rhs,
                            rule_id=rule_id,
                        )
                    )
                    counts["pe_tech_101_gap_constraints"] += 1
                    constraint_index += 1
                counts["pe_tech_gap_penalty_terms"] += 1
            return
        for index in range(len(busy_names) - 1):
            b1, b2 = busy_names[index], busy_names[index + 1]
            gap_key = f"{teacher}|{day}|{tag}|{index}"
            gap_name = _pe_tech_gap_bool_name(len(gap_variable_names) + 1, teacher, day, tag, index)
            gap_variable_names[gap_key] = gap_name
            gap_variables.append(VariableSpec.bool(gap_name))
            for suffix, terms, sense, rhs in (
                ("adj_upper_left", (LinearTerm(gap_name, 1), LinearTerm(b1, -1)), "<=", 0),
                ("adj_upper_right_empty", (LinearTerm(gap_name, 1), LinearTerm(b2, 1)), "<=", 1),
                (
                    "adj_lower",
                    (LinearTerm(gap_name, 1), LinearTerm(b1, -1), LinearTerm(b2, 1)),
                    ">=",
                    0,
                ),
            ):
                constraints.append(
                    LinearConstraintSpec(
                        name=f"day_pe_tech_compact__gap_{suffix}__{constraint_index:04d}__{_safe_identifier(gap_name)}",
                        expression=LinearExpression(tuple(terms)),
                        sense=sense,
                        rhs=rhs,
                        rule_id=rule_id,
                    )
                )
                counts["pe_tech_adjacent_gap_constraints"] += 1
                constraint_index += 1
            counts["pe_tech_gap_penalty_terms"] += 1

    slots_by_teacher_day: dict[tuple[str, str], list[Any]] = {}
    for teacher, day, slot in raw_busy_keys:
        slots_by_teacher_day.setdefault((teacher, day), []).append(slot)
    for teacher in target_teachers:
        for day in WEEKDAY_DAYS:
            slots = tuple(sorted(slots_by_teacher_day.get((teacher, day), ()), key=_slot_order_key))
            am_slots = tuple(slot for slot in slots if str(slot.block) == "上午")
            pm_slots = tuple(slot for slot in slots if str(slot.block) == "下午")
            build_gap_constraints(teacher, day, am_slots, "AM")
            build_gap_constraints(teacher, day, pm_slots, "PM")

    objective = ObjectiveSpec(
        rule_id=rule_id,
        sense="minimize",
        expression=LinearExpression(
            tuple(LinearTerm(name, int(weight)) for name in gap_variable_names.values())
        ),
    )
    ai_rule = AiRuleSpec(
        rule_id=rule_id,
        description="Day soft rule: penalize PE/tech teacher halfday gaps and non-compact adjacent patterns.",
        enforcement="soft",
        priority=39,
        source="scheduler.model.constraints.day_pe_tech_constraints:apply_pe_tech_compact_soft",
    )
    problem = OptimizationProblemSpec(
        problem_id="scheduler_day_pe_tech_compact_soft",
        variables=(*assignment_variables, *busy_variables, *tuple(gap_variables)),
        rules=(ai_rule,),
        constraints=tuple(constraints),
        objective=objective,
    )
    rule_first_plan = build_rule_first_plan(
        rules=problem.rules,
        constraints=problem.constraints,
        objective_rule_id=objective.rule_id,
    )
    return SchedulerGenericRuleBridge(
        problem=problem,
        rule_first_plan=rule_first_plan,
        metadata_by_rule={
            rule_id: {
                "scheduler_rule_id": rule_id,
                "legacy_apply_fn": "apply_pe_tech_compact_soft",
                "generic_contract_status": "covered_by_generic_contract",
                "runtime_rule_ids": generic_scheduler_rule_ids(),
                "constraint_family_counts": counts,
                "assignment_variable_names": assignment_names,
                "teacher_day_slot_assignment_variable_names": {
                    _teacher_day_period_key(teacher, day, _slot_label(slot)): tuple(sorted(names))
                    for (teacher, day, slot), names in sorted(
                        names_by_teacher_day_slot.items(),
                        key=lambda item: (item[0][0], WEEKDAY_DAYS.index(item[0][1]), _slot_order_key(item[0][2])),
                    )
                },
                "busy_variable_names": busy_variable_names,
                "gap_variable_names": gap_variable_names,
                "pe_tech_teachers": target_teachers,
                "weight": int(weight),
            }
        },
    )


def day_teacher_am4_pm1_threshold_penalty_to_ai_or_problem(
    data: Any,
    *,
    pe_teachers: Iterable[Any] = (),
    weights: Sequence[int] = (100, 200, 400, 800),
    rule_id: str = "joint.day.teacher_am4_pm1_threshold_penalty",
) -> SchedulerGenericRuleBridge:
    """Compile the non-PE teacher AM4+PM1 threshold penalty into OptimizationProblemSpec."""
    weight_values = tuple(int(weight) for weight in weights)
    if len(weight_values) != 4:
        raise ValueError("teacher AM4+PM1 threshold weights must contain four integers")

    excluded_teachers = set(_teacher_names(pe_teachers))
    assignments = _day_candidate_assignment_names(data)
    assignment_variables = tuple(VariableSpec.bool(name) for (_cls, _subj, _slot, name) in assignments)
    assignment_names: dict[str, str] = {}
    names_by_teacher: dict[str, list[str]] = {}
    for cls, subj, slot, name in assignments:
        key = _assignment_key(cls, subj, str(slot.day), _slot_label(slot))
        assignment_names[key] = name
        if not is_weekday_day(str(slot.day)):
            continue
        if not (_is_am4(slot) or _is_pm1(slot)):
            continue
        if is_pe_or_tech_subject(str(subj)):
            continue
        teacher = str(getattr(data, "cls_subj_teacher", {}).get((cls, subj), "")).strip()
        if not teacher or teacher in excluded_teachers:
            continue
        names_by_teacher.setdefault(teacher, []).append(name)

    target_teachers = tuple(sorted(teacher for teacher, names in names_by_teacher.items() if names))
    variables: list[VariableSpec] = list(assignment_variables)
    constraints: list[LinearConstraintSpec] = []
    objective_terms: list[LinearTerm] = []
    count_variable_names_by_teacher: dict[str, str] = {}
    penalty_variable_names_by_teacher: dict[str, dict[str, str]] = {}
    teacher_assignment_variable_names: dict[str, tuple[str, ...]] = {}
    teacher_total_assignment_count_by_teacher: dict[str, int] = {}
    counts = {
        "teacher_am4_pm1_count_equalities": 0,
        "teacher_am4_pm1_weekly_caps": 0,
        "teacher_am4_pm1_threshold_penalty_constraints": 0,
        "teacher_am4_pm1_penalty_terms": 0,
    }
    constraint_index = 1

    for teacher_index, teacher in enumerate(target_teachers, start=1):
        assignment_var_names = tuple(sorted(names_by_teacher[teacher]))
        teacher_assignment_variable_names[teacher] = assignment_var_names
        teacher_total_assignment_count_by_teacher[teacher] = len(assignment_var_names)

        count_name = _teacher_am4_pm1_count_var_name(teacher_index, teacher)
        variables.append(VariableSpec(count_name, 0, len(assignment_var_names)))
        count_variable_names_by_teacher[teacher] = count_name
        constraints.append(
            LinearConstraintSpec(
                name=f"day_teacher_am4_pm1_threshold__count__{constraint_index:04d}__{_safe_identifier(teacher)}",
                expression=LinearExpression(
                    (
                        LinearTerm(count_name, 1),
                        *(LinearTerm(name, -1) for name in assignment_var_names),
                    )
                ),
                sense="==",
                rhs=0,
                rule_id=rule_id,
            )
        )
        counts["teacher_am4_pm1_count_equalities"] += 1
        constraint_index += 1
        constraints.append(
            LinearConstraintSpec(
                name=f"day_teacher_am4_pm1_threshold__cap__{constraint_index:04d}__{_safe_identifier(teacher)}",
                expression=LinearExpression((LinearTerm(count_name, 1),)),
                sense="<=",
                rhs=6,
                rule_id=rule_id,
            )
        )
        counts["teacher_am4_pm1_weekly_caps"] += 1
        constraint_index += 1

        teacher_penalty_names: dict[str, str] = {}
        for tag, threshold_offset, coefficient in (
            ("e3", 2, weight_values[0]),
            ("e4", 3, weight_values[1]),
            ("e5", 4, weight_values[2]),
            ("e6", 5, weight_values[3]),
        ):
            penalty_name = _teacher_am4_pm1_penalty_var_name(teacher_index, teacher, tag)
            variables.append(VariableSpec(penalty_name, 0, 10))
            teacher_penalty_names[tag] = penalty_name
            constraints.append(
                LinearConstraintSpec(
                    name=f"day_teacher_am4_pm1_threshold__{tag}__{constraint_index:04d}__{_safe_identifier(teacher)}",
                    expression=LinearExpression((LinearTerm(penalty_name, 1), LinearTerm(count_name, -1))),
                    sense=">=",
                    rhs=-int(threshold_offset),
                    rule_id=rule_id,
                )
            )
            objective_terms.append(LinearTerm(penalty_name, int(coefficient)))
            counts["teacher_am4_pm1_threshold_penalty_constraints"] += 1
            counts["teacher_am4_pm1_penalty_terms"] += 1
            constraint_index += 1
        penalty_variable_names_by_teacher[teacher] = teacher_penalty_names

    objective = ObjectiveSpec(
        rule_id=rule_id,
        sense="minimize",
        expression=LinearExpression(tuple(objective_terms)),
    )
    ai_rule = AiRuleSpec(
        rule_id=rule_id,
        description="Day soft rule: penalize non-PE/tech teachers with too many weekday AM4 and PM1 assignments.",
        enforcement="soft",
        priority=30,
        source="scheduler.model.constraints.day_weekday_constraints:apply_teacher_am4_pm1_threshold_penalty",
    )
    problem = OptimizationProblemSpec(
        problem_id="scheduler_day_teacher_am4_pm1_threshold_penalty",
        variables=tuple(variables),
        rules=(ai_rule,),
        constraints=tuple(constraints),
        objective=objective,
    )
    rule_first_plan = build_rule_first_plan(
        rules=problem.rules,
        constraints=problem.constraints,
        objective_rule_id=objective.rule_id,
    )
    return SchedulerGenericRuleBridge(
        problem=problem,
        rule_first_plan=rule_first_plan,
        metadata_by_rule={
            rule_id: {
                "scheduler_rule_id": rule_id,
                "legacy_apply_fn": "apply_teacher_am4_pm1_threshold_penalty",
                "generic_contract_status": "covered_by_generic_contract",
                "runtime_rule_ids": generic_scheduler_rule_ids(),
                "constraint_family_counts": counts,
                "assignment_variable_names": assignment_names,
                "constrained_teachers": target_teachers,
                "teacher_assignment_variable_names": teacher_assignment_variable_names,
                "teacher_total_assignment_count_by_teacher": teacher_total_assignment_count_by_teacher,
                "count_variable_names_by_teacher": count_variable_names_by_teacher,
                "penalty_variable_names_by_teacher": penalty_variable_names_by_teacher,
                "pe_teachers": tuple(sorted(excluded_teachers)),
                "weights": weight_values,
            }
        },
    )


def day_weekday_subject_balance_to_ai_or_problem(
    data: Any,
    *,
    mode: str = "soft",
    weight: int = 1,
    rule_id: str = "joint.day.weekday_subject_balance",
) -> SchedulerGenericRuleBridge:
    """Compile weekday subject balance hard/soft rules into OptimizationProblemSpec."""
    mode_norm = str(mode or "soft").strip().lower()
    if mode_norm not in {"hard", "soft"}:
        raise ValueError(f"unsupported weekday subject balance mode {mode!r}")

    assignments = _day_candidate_assignment_names(data)
    assignment_variables = tuple(VariableSpec.bool(name) for (_cls, _subj, _slot, name) in assignments)
    assignment_names: dict[str, str] = {}
    names_by_class_subject_day: dict[tuple[str, str, str], list[str]] = {}
    for cls, subj, slot, name in assignments:
        key = _assignment_key(cls, subj, str(slot.day), _slot_label(slot))
        assignment_names[key] = name
        day = str(slot.day)
        if day not in WEEKDAY_DAYS:
            continue
        names_by_class_subject_day.setdefault((cls, subj, day), []).append(name)

    target_pairs: list[tuple[str, str, int, int]] = []
    for raw_key, raw_reqs in getattr(data, "req_hours", {}).items():
        cls, subj = (str(raw_key[0]), str(raw_key[1]))
        if is_pe_or_tech_subject(subj):
            continue
        _early, weekday_hours, _weekend = raw_reqs
        weekday_hours_int = int(weekday_hours)
        if weekday_hours_int == 0:
            continue
        target_pairs.append((cls, subj, weekday_hours_int, weekday_hours_int // 5))
    target_pairs = sorted(set(target_pairs), key=lambda item: (item[0], item[1]))
    target_pair_keys = {(cls, subj) for cls, subj, _total, _base in target_pairs}

    fixed_counts_by_class_subject_day: dict[tuple[str, str, str], int] = {}
    for (cls, slot), subj in (getattr(data, "fixed_assign", {}) or {}).items():
        day = str(slot.day)
        raw_key = (str(cls), str(subj), day)
        if day not in WEEKDAY_DAYS or (str(cls), str(subj)) not in target_pair_keys:
            continue
        fixed_counts_by_class_subject_day[raw_key] = fixed_counts_by_class_subject_day.get(raw_key, 0) + 1

    variables: list[VariableSpec] = list(assignment_variables)
    constraints: list[LinearConstraintSpec] = []
    objective_terms: list[LinearTerm] = []
    day_hour_variable_names: dict[str, str] = {}
    penalty_variable_names_by_class_subject_day: dict[str, dict[str, str]] = {}
    counts = {"weekday_subject_day_hour_equalities": 0}
    if mode_norm == "hard":
        counts["weekday_subject_balance_hard_bounds"] = 0
    else:
        counts["weekday_subject_balance_over_under_constraints"] = 0
        counts["weekday_subject_balance_penalty_terms"] = 0
    constraint_index = 1
    variable_index = 1

    for cls, subj, _total_weekday, base in target_pairs:
        for day in WEEKDAY_DAYS:
            day_text = str(day)
            raw_key = (cls, subj, day_text)
            metadata_key = _class_subject_day_key(cls, subj, day_text)
            assignment_var_names = tuple(sorted(names_by_class_subject_day.get(raw_key, ())))
            fixed_count = int(fixed_counts_by_class_subject_day.get(raw_key, 0))
            day_hour_name = _weekday_subject_balance_day_hours_var_name(variable_index, cls, subj, day_text)
            variable_index += 1
            variables.append(VariableSpec(day_hour_name, 0, 10))
            day_hour_variable_names[metadata_key] = day_hour_name
            constraints.append(
                LinearConstraintSpec(
                    name=f"day_weekday_subject_balance__day_hours__{constraint_index:04d}__{_safe_identifier(metadata_key)}",
                    expression=LinearExpression(
                        (
                            LinearTerm(day_hour_name, 1),
                            *(LinearTerm(name, -1) for name in assignment_var_names),
                        )
                    ),
                    sense="==",
                    rhs=fixed_count,
                    rule_id=rule_id,
                )
            )
            counts["weekday_subject_day_hour_equalities"] += 1
            constraint_index += 1

            if mode_norm == "hard":
                constraints.append(
                    LinearConstraintSpec(
                        name=f"day_weekday_subject_balance__hard_lower__{constraint_index:04d}__{_safe_identifier(metadata_key)}",
                        expression=LinearExpression((LinearTerm(day_hour_name, 1),)),
                        sense=">=",
                        rhs=int(base),
                        rule_id=rule_id,
                    )
                )
                counts["weekday_subject_balance_hard_bounds"] += 1
                constraint_index += 1
                constraints.append(
                    LinearConstraintSpec(
                        name=f"day_weekday_subject_balance__hard_upper__{constraint_index:04d}__{_safe_identifier(metadata_key)}",
                        expression=LinearExpression((LinearTerm(day_hour_name, 1),)),
                        sense="<=",
                        rhs=int(base) + 1,
                        rule_id=rule_id,
                    )
                )
                counts["weekday_subject_balance_hard_bounds"] += 1
                constraint_index += 1
                continue

            over_name = _weekday_subject_balance_penalty_var_name(variable_index, cls, subj, day_text, "over")
            variable_index += 1
            under_name = _weekday_subject_balance_penalty_var_name(variable_index, cls, subj, day_text, "under")
            variable_index += 1
            variables.append(VariableSpec(over_name, 0, 10))
            variables.append(VariableSpec(under_name, 0, 10))
            penalty_variable_names_by_class_subject_day[metadata_key] = {
                "over": over_name,
                "under": under_name,
            }
            constraints.append(
                LinearConstraintSpec(
                    name=f"day_weekday_subject_balance__over__{constraint_index:04d}__{_safe_identifier(metadata_key)}",
                    expression=LinearExpression((LinearTerm(over_name, 1), LinearTerm(day_hour_name, -1))),
                    sense=">=",
                    rhs=-(int(base) + 1),
                    rule_id=rule_id,
                )
            )
            counts["weekday_subject_balance_over_under_constraints"] += 1
            constraint_index += 1
            constraints.append(
                LinearConstraintSpec(
                    name=f"day_weekday_subject_balance__under__{constraint_index:04d}__{_safe_identifier(metadata_key)}",
                    expression=LinearExpression((LinearTerm(under_name, 1), LinearTerm(day_hour_name, 1))),
                    sense=">=",
                    rhs=int(base),
                    rule_id=rule_id,
                )
            )
            counts["weekday_subject_balance_over_under_constraints"] += 1
            constraint_index += 1
            objective_terms.append(LinearTerm(over_name, int(weight)))
            objective_terms.append(LinearTerm(under_name, int(weight)))
            counts["weekday_subject_balance_penalty_terms"] += 2

    objective = None
    if mode_norm == "soft":
        objective = ObjectiveSpec(
            rule_id=rule_id,
            sense="minimize",
            expression=LinearExpression(tuple(objective_terms)),
        )
    ai_rule = AiRuleSpec(
        rule_id=rule_id,
        description="Day rule: keep non-PE/tech subject hours balanced across weekdays.",
        enforcement=mode_norm,
        priority=37,
        source="scheduler.model.constraints.day_weekday_constraints:apply_weekday_subject_balance",
    )
    problem = OptimizationProblemSpec(
        problem_id="scheduler_day_weekday_subject_balance",
        variables=tuple(variables),
        rules=(ai_rule,),
        constraints=tuple(constraints),
        objective=objective,
    )
    rule_first_plan = build_rule_first_plan(
        rules=problem.rules,
        constraints=problem.constraints,
        objective_rule_id=objective.rule_id if objective is not None else None,
    )
    return SchedulerGenericRuleBridge(
        problem=problem,
        rule_first_plan=rule_first_plan,
        metadata_by_rule={
            rule_id: {
                "scheduler_rule_id": rule_id,
                "legacy_apply_fn": "apply_weekday_subject_balance",
                "generic_contract_status": "covered_by_generic_contract",
                "runtime_rule_ids": generic_scheduler_rule_ids(),
                "constraint_family_counts": counts,
                "assignment_variable_names": assignment_names,
                "target_class_subjects": tuple(_class_subject_key(cls, subj) for cls, subj, _total, _base in target_pairs),
                "weekday_base_targets": {
                    _class_subject_key(cls, subj): int(base)
                    for cls, subj, _total, base in target_pairs
                },
                "day_hour_variable_names": day_hour_variable_names,
                "class_subject_day_assignment_variable_names": {
                    _class_subject_day_key(cls, subj, day): tuple(sorted(names))
                    for (cls, subj, day), names in sorted(names_by_class_subject_day.items())
                    if (cls, subj) in target_pair_keys
                },
                "fixed_count_constants": {
                    _class_subject_day_key(cls, subj, day): int(count)
                    for (cls, subj, day), count in sorted(fixed_counts_by_class_subject_day.items())
                    if count and (cls, subj) in target_pair_keys
                },
                "penalty_variable_names_by_class_subject_day": penalty_variable_names_by_class_subject_day,
                "mode": mode_norm,
                "weight": int(weight),
            }
        },
    )


def day_no_consecutive_same_teacher_same_class_to_ai_or_problem(
    data: Any,
    *,
    rule_id: str = "joint.day.no_consecutive_same_teacher_same_class",
) -> SchedulerGenericRuleBridge:
    """Compile the same teacher/class adjacent-slot mutex into OptimizationProblemSpec."""
    assignments = _day_candidate_assignment_names(data)
    variables = tuple(VariableSpec.bool(name) for (_cls, _subj, _slot, name) in assignments)
    names_by_teacher_class_slot: dict[tuple[str, str, Any], list[str]] = {}
    assignment_names: dict[str, str] = {}
    for cls, subj, slot, name in assignments:
        teacher = getattr(data, "cls_subj_teacher", {}).get((cls, subj))
        if teacher is None:
            continue
        teacher_text = str(teacher)
        names_by_teacher_class_slot.setdefault((teacher_text, cls, slot), []).append(name)
        assignment_names[_assignment_key(cls, subj, str(slot.day), _slot_label(slot))] = name

    fixed_assign = getattr(data, "fixed_assign", {}) or {}
    constraints: list[LinearConstraintSpec] = []
    adjacency_variable_names: dict[str, tuple[str, ...]] = {}
    adjacency_fixed_counts: dict[str, int] = {}
    constraint_index = 1

    for cls in _text_tuple(data.classes):
        teachers = sorted(
            {
                str(teacher)
                for (candidate_cls, _subj), teacher in getattr(data, "cls_subj_teacher", {}).items()
                if str(candidate_cls) == cls
            }
        )
        for day in WEEKDAY_DAYS:
            slots = [
                slot
                for slot in tuple(data.available_slots)
                if str(slot.day) == str(day) and str(slot.block) in ("上午", "下午")
            ]
            slots.sort(key=_slot_order_key)
            if len(slots) < 2:
                continue
            for teacher in teachers:
                for pair_index in range(len(slots) - 1):
                    slot_1, slot_2 = slots[pair_index], slots[pair_index + 1]
                    slot_1_names, slot_1_fixed = _teacher_class_slot_expr_parts(
                        data,
                        fixed_assign,
                        names_by_teacher_class_slot,
                        teacher,
                        cls,
                        slot_1,
                    )
                    slot_2_names, slot_2_fixed = _teacher_class_slot_expr_parts(
                        data,
                        fixed_assign,
                        names_by_teacher_class_slot,
                        teacher,
                        cls,
                        slot_2,
                    )
                    variable_names = (*slot_1_names, *slot_2_names)
                    fixed_count = int(slot_1_fixed + slot_2_fixed)
                    pair_key = _teacher_class_adjacent_key(teacher, cls, str(day), slot_1, slot_2)
                    adjacency_variable_names[pair_key] = tuple(variable_names)
                    adjacency_fixed_counts[pair_key] = fixed_count
                    constraints.append(
                        LinearConstraintSpec(
                            name=f"day_no_consecutive_same_teacher_same_class__{constraint_index:04d}__{_safe_identifier(cls)}__{_safe_identifier(teacher)}__{_safe_identifier(str(day))}__{_safe_identifier(_slot_label(slot_1))}__{_safe_identifier(_slot_label(slot_2))}",
                            expression=LinearExpression(
                                tuple(LinearTerm(name, 1) for name in variable_names),
                                constant=fixed_count,
                            ),
                            sense="<=",
                            rhs=1,
                            rule_id=rule_id,
                        )
                    )
                    constraint_index += 1

    ai_rule = AiRuleSpec(
        rule_id=rule_id,
        description="Day hard rule: the same teacher cannot teach adjacent slots in the same class.",
        enforcement="hard",
        priority=4,
        source="scheduler.model.constraints.day_weekday_constraints:apply_no_consecutive_same_teacher_same_class",
    )
    problem = OptimizationProblemSpec(
        problem_id="scheduler_day_no_consecutive_same_teacher_same_class",
        variables=variables,
        rules=(ai_rule,),
        constraints=tuple(constraints),
    )
    rule_first_plan = build_rule_first_plan(
        rules=problem.rules,
        constraints=problem.constraints,
        objective_rule_id=None,
    )
    return SchedulerGenericRuleBridge(
        problem=problem,
        rule_first_plan=rule_first_plan,
        metadata_by_rule={
            rule_id: {
                "scheduler_rule_id": rule_id,
                "legacy_apply_fn": "apply_no_consecutive_same_teacher_same_class",
                "generic_contract_status": "covered_by_generic_contract",
                "runtime_rule_ids": generic_scheduler_rule_ids(),
                "constraint_family_counts": {
                    "teacher_class_adjacent_slot_mutex": len(constraints),
                },
                "assignment_variable_names": assignment_names,
                "teacher_class_adjacent_variable_names": adjacency_variable_names,
                "teacher_class_adjacent_fixed_counts": adjacency_fixed_counts,
            }
        },
    )


def day_morning_reading_to_ai_or_problem(
    data: Any,
    *,
    rule_id: str = "joint.day.morning_reading_constraints",
) -> SchedulerGenericRuleBridge:
    """Compile morning-reading adjacent-day subject alternation into OptimizationProblemSpec."""
    assignments = _day_candidate_assignment_names(data)
    variables = tuple(VariableSpec.bool(name) for (_cls, _subj, _slot, name) in assignments)
    names_by_cls_subj_day: dict[tuple[str, str, str], list[str]] = {}
    assignment_names: dict[str, str] = {}
    for cls, subj, slot, name in assignments:
        assignment_names[_assignment_key(cls, subj, str(slot.day), _slot_label(slot))] = name
        if str(slot.block) != "早自习":
            continue
        names_by_cls_subj_day.setdefault((cls, subj, str(slot.day)), []).append(name)

    constraints: list[LinearConstraintSpec] = []
    constraint_index = 1
    for cls in _text_tuple(data.classes):
        for d1, d2 in ADJ_PAIRS:
            subjects = sorted(
                {
                    subj
                    for c, subj, day in names_by_cls_subj_day
                    if c == cls and day in {str(d1), str(d2)}
                }
            )
            for subj in subjects:
                d1_vars = names_by_cls_subj_day.get((cls, subj, str(d1)), [])
                d2_vars = names_by_cls_subj_day.get((cls, subj, str(d2)), [])
                if not d1_vars or not d2_vars:
                    continue
                constraints.append(
                    LinearConstraintSpec(
                        name=f"day_morning_reading__{constraint_index:04d}__{_safe_identifier(cls)}__{_safe_identifier(subj)}__{_safe_identifier(str(d1))}__{_safe_identifier(str(d2))}",
                        expression=_sum_expr((*d1_vars, *d2_vars)),
                        sense="<=",
                        rhs=1,
                        rule_id=rule_id,
                    )
                )
                constraint_index += 1

    ai_rule = AiRuleSpec(
        rule_id=rule_id,
        description="Day hard rule: the same class-subject cannot occupy adjacent morning-reading days.",
        enforcement="hard",
        priority=4,
        source="scheduler.day_constraints_morning_reading:apply_morning_reading_constraints",
    )
    problem = OptimizationProblemSpec(
        problem_id="scheduler_day_morning_reading_constraints",
        variables=variables,
        rules=(ai_rule,),
        constraints=tuple(constraints),
    )
    rule_first_plan = build_rule_first_plan(
        rules=problem.rules,
        constraints=problem.constraints,
        objective_rule_id=None,
    )
    return SchedulerGenericRuleBridge(
        problem=problem,
        rule_first_plan=rule_first_plan,
        metadata_by_rule={
            rule_id: {
                "scheduler_rule_id": rule_id,
                "legacy_apply_fn": "apply_morning_reading_constraints",
                "generic_contract_status": "covered_by_generic_contract",
                "runtime_rule_ids": generic_scheduler_rule_ids(),
                "constraint_family_counts": {
                    "adjacent_morning_reading_subject_mutex": len(constraints),
                },
                "assignment_variable_names": assignment_names,
            }
        },
    )


def day_weekend_subject_whitelist_to_ai_or_problem(
    data: Any,
    *,
    rule_id: str = "joint.day.weekend_subject_whitelist",
) -> SchedulerGenericRuleBridge:
    """Compile weekend subject whitelist bans into OptimizationProblemSpec."""
    assignments = _day_candidate_assignment_names(data)
    variables = tuple(VariableSpec.bool(name) for (_cls, _subj, _slot, name) in assignments)
    assignment_names: dict[str, str] = {}
    blocked_assignment_names: dict[str, str] = {}
    constraints: list[LinearConstraintSpec] = []
    constraint_index = 1

    for cls, subj, slot, name in assignments:
        key = _assignment_key(cls, subj, str(slot.day), _slot_label(slot))
        assignment_names[key] = name
        if str(slot.day) not in WEEKEND_WHITELIST:
            continue
        if normalize_subject(subj) in WEEKEND_WHITELIST.get(str(slot.day), set()):
            continue
        blocked_assignment_names[key] = name
        constraints.append(
            LinearConstraintSpec(
                name=f"day_weekend_subject_whitelist__{constraint_index:04d}__{_safe_identifier(cls)}__{_safe_identifier(subj)}__{_safe_identifier(str(slot.day))}__{_safe_identifier(_slot_label(slot))}",
                expression=LinearExpression((LinearTerm(name, 1),)),
                sense="==",
                rhs=0,
                rule_id=rule_id,
            )
        )
        constraint_index += 1

    ai_rule = AiRuleSpec(
        rule_id=rule_id,
        description="Day hard rule: weekend assignments must use subjects allowed by each weekend-day whitelist.",
        enforcement="hard",
        priority=5,
        source="scheduler.model.constraints.day_weekend_constraints:apply_weekend_subject_whitelist",
    )
    problem = OptimizationProblemSpec(
        problem_id="scheduler_day_weekend_subject_whitelist",
        variables=variables,
        rules=(ai_rule,),
        constraints=tuple(constraints),
    )
    rule_first_plan = build_rule_first_plan(
        rules=problem.rules,
        constraints=problem.constraints,
        objective_rule_id=None,
    )
    return SchedulerGenericRuleBridge(
        problem=problem,
        rule_first_plan=rule_first_plan,
        metadata_by_rule={
            rule_id: {
                "scheduler_rule_id": rule_id,
                "legacy_apply_fn": "apply_weekend_subject_whitelist",
                "generic_contract_status": "covered_by_generic_contract",
                "runtime_rule_ids": generic_scheduler_rule_ids(),
                "constraint_family_counts": {
                    "weekend_subject_whitelist_zero_bans": len(constraints),
                },
                "assignment_variable_names": assignment_names,
                "blocked_assignment_variable_names": blocked_assignment_names,
            }
        },
    )


def day_weekend_one_day_only_to_ai_or_problem(
    data: Any,
    *,
    rule_id: str = "joint.day.weekend_one_day_only",
) -> SchedulerGenericRuleBridge:
    """Compile the weekend one-day-only teacher rule into OptimizationProblemSpec."""
    assignments = _day_candidate_assignment_names(data)
    assignment_variables = tuple(VariableSpec.bool(name) for (_cls, _subj, _slot, name) in assignments)
    assignment_names: dict[str, str] = {}
    names_by_teacher_class_slot: dict[tuple[str, str, Any], list[str]] = {}
    for cls, subj, slot, name in assignments:
        assignment_names[_assignment_key(cls, subj, str(slot.day), _slot_label(slot))] = name
        teacher = getattr(data, "cls_subj_teacher", {}).get((cls, subj))
        if teacher is None:
            continue
        names_by_teacher_class_slot.setdefault((str(teacher), cls, slot), []).append(name)

    sorted_teacher_class_slots = tuple(
        sorted(
            names_by_teacher_class_slot,
            key=lambda item: (item[0], item[1], str(item[2].day), _slot_order_key(item[2])),
        )
    )
    teacher_class_slot_bool_names = {
        _teacher_class_slot_key(teacher, cls, slot): _teacher_class_slot_bool_name(index, teacher, cls, slot)
        for index, (teacher, cls, slot) in enumerate(sorted_teacher_class_slots, start=1)
    }
    tcs_bool_variables = tuple(VariableSpec.bool(name) for name in teacher_class_slot_bool_names.values())
    tcs_bool_by_raw_key = {
        (teacher, cls, slot): teacher_class_slot_bool_names[_teacher_class_slot_key(teacher, cls, slot)]
        for teacher, cls, slot in names_by_teacher_class_slot
    }

    teachers = sorted({str(teacher) for (_cls, _subj), teacher in getattr(data, "cls_subj_teacher", {}).items() if teacher})
    teacher_weekend_day_variable_names = {
        _teacher_day_key(teacher, day): _teacher_weekend_day_bool_name(index, teacher, day)
        for index, (teacher, day) in enumerate(
            ((teacher, day) for teacher in teachers for day in WEEKEND_DAYS),
            start=1,
        )
    }
    teacher_day_variables = tuple(VariableSpec.bool(name) for name in teacher_weekend_day_variable_names.values())

    constraints: list[LinearConstraintSpec] = []
    counts = {
        "teacher_class_slot_bool_equalities": 0,
        "teacher_slot_implies_weekend_day": 0,
        "weekend_day_bool_lower_bounds": 0,
        "teacher_weekend_one_day_only": 0,
    }
    constraint_index = 1

    for raw_key, assignment_var_names in sorted(
        names_by_teacher_class_slot.items(),
        key=lambda item: (item[0][0], item[0][1], str(item[0][2].day), _slot_order_key(item[0][2])),
    ):
        bool_name = tcs_bool_by_raw_key[raw_key]
        constraints.append(
            LinearConstraintSpec(
                name=f"weekend_one_day_only__tcs_bool__{constraint_index:04d}__{_safe_identifier(bool_name)}",
                expression=LinearExpression(
                    (
                        *(LinearTerm(name, 1) for name in assignment_var_names),
                        LinearTerm(bool_name, -1),
                    )
                ),
                sense="==",
                rhs=0,
                rule_id=rule_id,
            )
        )
        counts["teacher_class_slot_bool_equalities"] += 1
        constraint_index += 1

    tcs_bools_by_teacher_day: dict[tuple[str, str], list[str]] = {}
    for (teacher, _cls, slot), bool_name in tcs_bool_by_raw_key.items():
        if str(slot.day) in WEEKEND_DAYS:
            tcs_bools_by_teacher_day.setdefault((teacher, str(slot.day)), []).append(bool_name)

    for teacher in teachers:
        sat_name = teacher_weekend_day_variable_names[_teacher_day_key(teacher, "星期六")]
        sun_name = teacher_weekend_day_variable_names[_teacher_day_key(teacher, "星期日")]
        for day, day_bool_name in (("星期六", sat_name), ("星期日", sun_name)):
            slot_bool_names = tuple(tcs_bools_by_teacher_day.get((teacher, day), ()))
            for slot_bool_name in slot_bool_names:
                constraints.append(
                    LinearConstraintSpec(
                        name=f"weekend_one_day_only__implies_day__{constraint_index:04d}__{_safe_identifier(teacher)}__{_safe_identifier(day)}__{_safe_identifier(slot_bool_name)}",
                        expression=LinearExpression((LinearTerm(slot_bool_name, 1), LinearTerm(day_bool_name, -1))),
                        sense="<=",
                        rhs=0,
                        rule_id=rule_id,
                    )
                )
                counts["teacher_slot_implies_weekend_day"] += 1
                constraint_index += 1
            if slot_bool_names:
                expression = LinearExpression(
                    (
                        *(LinearTerm(name, 1) for name in slot_bool_names),
                        LinearTerm(day_bool_name, -1),
                    )
                )
                sense = ">="
            else:
                expression = LinearExpression((LinearTerm(day_bool_name, 1),))
                sense = "=="
            constraints.append(
                LinearConstraintSpec(
                    name=f"weekend_one_day_only__day_lower_bound__{constraint_index:04d}__{_safe_identifier(teacher)}__{_safe_identifier(day)}",
                    expression=expression,
                    sense=sense,
                    rhs=0,
                    rule_id=rule_id,
                )
            )
            counts["weekend_day_bool_lower_bounds"] += 1
            constraint_index += 1

        constraints.append(
            LinearConstraintSpec(
                name=f"weekend_one_day_only__teacher_day_mutex__{constraint_index:04d}__{_safe_identifier(teacher)}",
                expression=LinearExpression((LinearTerm(sat_name, 1), LinearTerm(sun_name, 1))),
                sense="<=",
                rhs=1,
                rule_id=rule_id,
            )
        )
        counts["teacher_weekend_one_day_only"] += 1
        constraint_index += 1

    ai_rule = AiRuleSpec(
        rule_id=rule_id,
        description="Day hard rule: a teacher's weekend assignments may occur on Saturday or Sunday, not both.",
        enforcement="hard",
        priority=6,
        source="scheduler.model.constraints.day_weekend_constraints:apply_weekend_one_day_only",
    )
    problem = OptimizationProblemSpec(
        problem_id="scheduler_day_weekend_one_day_only",
        variables=(*assignment_variables, *tcs_bool_variables, *teacher_day_variables),
        rules=(ai_rule,),
        constraints=tuple(constraints),
    )
    rule_first_plan = build_rule_first_plan(
        rules=problem.rules,
        constraints=problem.constraints,
        objective_rule_id=None,
    )
    return SchedulerGenericRuleBridge(
        problem=problem,
        rule_first_plan=rule_first_plan,
        metadata_by_rule={
            rule_id: {
                "scheduler_rule_id": rule_id,
                "legacy_apply_fn": "apply_weekend_one_day_only",
                "generic_contract_status": "covered_by_generic_contract",
                "runtime_rule_ids": generic_scheduler_rule_ids(),
                "constraint_family_counts": counts,
                "assignment_variable_names": assignment_names,
                "teacher_class_slot_variable_names": teacher_class_slot_bool_names,
                "teacher_weekend_day_variable_names": teacher_weekend_day_variable_names,
            }
        },
    )


def day_weekend_double_period_same_class_to_ai_or_problem(
    data: Any,
    *,
    rule_id: str = "joint.day.weekend_double_period_same_class",
) -> SchedulerGenericRuleBridge:
    """Compile the weekend adjacent double-period same-class hard rule."""
    assignments = _day_candidate_assignment_names(data)
    assignment_variables = tuple(VariableSpec.bool(name) for (_cls, _subj, _slot, name) in assignments)
    assignment_names: dict[str, str] = {}
    names_by_teacher_class_slot: dict[tuple[str, str, Any], list[str]] = {}
    for cls, subj, slot, name in assignments:
        assignment_names[_assignment_key(cls, subj, str(slot.day), _slot_label(slot))] = name
        teacher = getattr(data, "cls_subj_teacher", {}).get((cls, subj))
        if teacher is None:
            continue
        names_by_teacher_class_slot.setdefault((str(teacher), cls, slot), []).append(name)

    sorted_teacher_class_slots = tuple(
        sorted(
            names_by_teacher_class_slot,
            key=lambda item: (item[0], item[1], str(item[2].day), _day_weekend_slot_index(item[2])),
        )
    )
    teacher_class_slot_bool_names = {
        _teacher_class_slot_key(teacher, cls, slot): _teacher_class_slot_bool_name(index, teacher, cls, slot)
        for index, (teacher, cls, slot) in enumerate(sorted_teacher_class_slots, start=1)
    }
    tcs_bool_by_raw_key = {
        (teacher, cls, slot): teacher_class_slot_bool_names[_teacher_class_slot_key(teacher, cls, slot)]
        for teacher, cls, slot in names_by_teacher_class_slot
    }
    tcs_bool_variables = tuple(VariableSpec.bool(name) for name in teacher_class_slot_bool_names.values())

    slots_by_day_class: dict[tuple[str, str], list[Any]] = {}
    for slot in tuple(getattr(data, "available_slots", ())):
        if str(slot.day) not in WEEKEND_DAYS:
            continue
        for cls in _text_tuple(getattr(data, "classes", ())):
            slots_by_day_class.setdefault((str(slot.day), cls), []).append(slot)
    for key in slots_by_day_class:
        slots_by_day_class[key].sort(key=_day_weekend_slot_index)

    constraints: list[LinearConstraintSpec] = []
    counts = {
        "teacher_class_slot_bool_equalities": 0,
        "adjacent_pair_left_implications": 0,
        "adjacent_pair_right_implications": 0,
        "slot_pair_cover_lower_bounds": 0,
        "slot_pair_cover_overlap_caps": 0,
        "slot_without_adjacent_pair_zero": 0,
    }
    adjacent_pair_variable_names: dict[str, str] = {}
    pair_variables: list[VariableSpec] = []
    constraint_index = 1
    pair_index = 1

    for raw_key, assignment_var_names in sorted(
        names_by_teacher_class_slot.items(),
        key=lambda item: (item[0][0], item[0][1], str(item[0][2].day), _day_weekend_slot_index(item[0][2])),
    ):
        bool_name = tcs_bool_by_raw_key[raw_key]
        constraints.append(
            LinearConstraintSpec(
                name=f"weekend_double_period__tcs_bool__{constraint_index:04d}__{_safe_identifier(bool_name)}",
                expression=LinearExpression(
                    (
                        *(LinearTerm(name, 1) for name in assignment_var_names),
                        LinearTerm(bool_name, -1),
                    )
                ),
                sense="==",
                rhs=0,
                rule_id=rule_id,
            )
        )
        counts["teacher_class_slot_bool_equalities"] += 1
        constraint_index += 1

    for (day, cls), slots in sorted(slots_by_day_class.items()):
        adjacent_pairs = tuple(
            (left, right)
            for left, right in zip(slots, slots[1:])
            if _day_weekend_slot_index(right) == _day_weekend_slot_index(left) + 1
        )
        if not adjacent_pairs:
            continue
        teachers = tuple(
            sorted({teacher for (teacher, raw_cls, slot) in tcs_bool_by_raw_key if raw_cls == cls and str(slot.day) == day})
        )
        for teacher in teachers:
            pair_vars_by_slot: dict[Any, list[str]] = {}
            for left, right in adjacent_pairs:
                left_name = tcs_bool_by_raw_key.get((teacher, cls, left))
                right_name = tcs_bool_by_raw_key.get((teacher, cls, right))
                if left_name is None or right_name is None:
                    continue
                pair_name = _teacher_class_slot_pair_bool_name(pair_index, teacher, cls, day, left, right)
                pair_index += 1
                pair_variables.append(VariableSpec.bool(pair_name))
                adjacent_pair_variable_names[_teacher_class_slot_pair_key(teacher, cls, day, left, right)] = pair_name
                constraints.append(
                    LinearConstraintSpec(
                        name=f"weekend_double_period__pair_left__{constraint_index:04d}__{_safe_identifier(pair_name)}",
                        expression=LinearExpression((LinearTerm(pair_name, 1), LinearTerm(left_name, -1))),
                        sense="<=",
                        rhs=0,
                        rule_id=rule_id,
                    )
                )
                counts["adjacent_pair_left_implications"] += 1
                constraint_index += 1
                constraints.append(
                    LinearConstraintSpec(
                        name=f"weekend_double_period__pair_right__{constraint_index:04d}__{_safe_identifier(pair_name)}",
                        expression=LinearExpression((LinearTerm(pair_name, 1), LinearTerm(right_name, -1))),
                        sense="<=",
                        rhs=0,
                        rule_id=rule_id,
                    )
                )
                counts["adjacent_pair_right_implications"] += 1
                constraint_index += 1
                pair_vars_by_slot.setdefault(left, []).append(pair_name)
                pair_vars_by_slot.setdefault(right, []).append(pair_name)

            for slot in slots:
                tcs_name = tcs_bool_by_raw_key.get((teacher, cls, slot))
                if tcs_name is None:
                    continue
                cover_names = tuple(pair_vars_by_slot.get(slot, ()))
                if not cover_names:
                    constraints.append(
                        _bool_value_constraint(
                            f"weekend_double_period__slot_without_pair_zero__{constraint_index:04d}__{_safe_identifier(tcs_name)}",
                            tcs_name,
                            0,
                            rule_id,
                        )
                    )
                    counts["slot_without_adjacent_pair_zero"] += 1
                    constraint_index += 1
                    continue
                constraints.append(
                    LinearConstraintSpec(
                        name=f"weekend_double_period__cover_lower__{constraint_index:04d}__{_safe_identifier(tcs_name)}",
                        expression=LinearExpression(
                            (
                                *(LinearTerm(name, 1) for name in cover_names),
                                LinearTerm(tcs_name, -1),
                            )
                        ),
                        sense=">=",
                        rhs=0,
                        rule_id=rule_id,
                    )
                )
                counts["slot_pair_cover_lower_bounds"] += 1
                constraint_index += 1
                constraints.append(
                    LinearConstraintSpec(
                        name=f"weekend_double_period__cover_cap__{constraint_index:04d}__{_safe_identifier(tcs_name)}",
                        expression=_sum_expr(cover_names),
                        sense="<=",
                        rhs=1,
                        rule_id=rule_id,
                    )
                )
                counts["slot_pair_cover_overlap_caps"] += 1
                constraint_index += 1

    ai_rule = AiRuleSpec(
        rule_id=rule_id,
        description="Day hard rule: weekend assignments must be covered by an adjacent same-class double period.",
        enforcement="hard",
        priority=6,
        source="scheduler.model.constraints.day_weekend_constraints:apply_weekend_double_period_same_class",
    )
    problem = OptimizationProblemSpec(
        problem_id="scheduler_day_weekend_double_period_same_class",
        variables=(*assignment_variables, *tcs_bool_variables, *tuple(pair_variables)),
        rules=(ai_rule,),
        constraints=tuple(constraints),
    )
    rule_first_plan = build_rule_first_plan(
        rules=problem.rules,
        constraints=problem.constraints,
        objective_rule_id=None,
    )
    return SchedulerGenericRuleBridge(
        problem=problem,
        rule_first_plan=rule_first_plan,
        metadata_by_rule={
            rule_id: {
                "scheduler_rule_id": rule_id,
                "legacy_apply_fn": "apply_weekend_double_period_same_class",
                "generic_contract_status": "covered_by_generic_contract",
                "runtime_rule_ids": generic_scheduler_rule_ids(),
                "constraint_family_counts": counts,
                "assignment_variable_names": assignment_names,
                "teacher_class_slot_variable_names": teacher_class_slot_bool_names,
                "adjacent_pair_variable_names": adjacent_pair_variable_names,
            }
        },
    )


def day_weekend_cross_halfday_penalty_to_ai_or_problem(
    data: Any,
    *,
    penalty: int = 200,
    yjc_sun_exempt: bool = True,
    sun_exempt_teachers: Sequence[str] | None = None,
    rule_id: str = "joint.day.weekend_cross_halfday_penalty",
) -> SchedulerGenericRuleBridge:
    """Compile the weekend cross-halfday soft penalty into OptimizationProblemSpec."""
    assignments = _day_candidate_assignment_names(data)
    assignment_variables = tuple(VariableSpec.bool(name) for (_cls, _subj, _slot, name) in assignments)
    assignment_names: dict[str, str] = {}
    names_by_teacher_class_slot: dict[tuple[str, str, Any], list[str]] = {}
    for cls, subj, slot, name in assignments:
        assignment_names[_assignment_key(cls, subj, str(slot.day), _slot_label(slot))] = name
        teacher = getattr(data, "cls_subj_teacher", {}).get((cls, subj))
        if teacher is None:
            continue
        names_by_teacher_class_slot.setdefault((str(teacher), cls, slot), []).append(name)

    sorted_teacher_class_slots = tuple(
        sorted(
            names_by_teacher_class_slot,
            key=lambda item: (item[0], item[1], str(item[2].day), _slot_order_key(item[2])),
        )
    )
    teacher_class_slot_bool_names = {
        _teacher_class_slot_key(teacher, cls, slot): _teacher_class_slot_bool_name(index, teacher, cls, slot)
        for index, (teacher, cls, slot) in enumerate(sorted_teacher_class_slots, start=1)
    }
    tcs_bool_by_raw_key = {
        (teacher, cls, slot): teacher_class_slot_bool_names[_teacher_class_slot_key(teacher, cls, slot)]
        for teacher, cls, slot in names_by_teacher_class_slot
    }
    tcs_bool_variables = tuple(VariableSpec.bool(name) for name in teacher_class_slot_bool_names.values())

    teachers = sorted({str(teacher) for (_cls, _subj), teacher in getattr(data, "cls_subj_teacher", {}).items() if teacher})
    sunday_exempt = set(_teacher_names(sun_exempt_teachers or ()))
    active_teacher_days = tuple(
        (teacher, day)
        for teacher in teachers
        for day in WEEKEND_DAYS
        if not (yjc_sun_exempt and day == "星期日" and teacher in sunday_exempt)
    )
    teacher_halfday_variable_names = {
        _teacher_halfday_key(teacher, day, halfday): _teacher_weekend_cross_halfday_bool_name(
            index, teacher, day, halfday
        )
        for index, (teacher, day, halfday) in enumerate(
            ((teacher, day, halfday) for teacher, day in active_teacher_days for halfday in ("am", "pm")),
            start=1,
        )
    }
    cross_halfday_variable_names = {
        _teacher_day_key(teacher, day): _teacher_weekend_cross_bool_name(index, teacher, day)
        for index, (teacher, day) in enumerate(active_teacher_days, start=1)
    }
    halfday_variables = tuple(VariableSpec.bool(name) for name in teacher_halfday_variable_names.values())
    cross_variables = tuple(VariableSpec.bool(name) for name in cross_halfday_variable_names.values())

    constraints: list[LinearConstraintSpec] = []
    counts = {
        "teacher_class_slot_bool_equalities": 0,
        "teacher_slot_implies_has_am": 0,
        "teacher_slot_implies_has_pm": 0,
        "has_am_lower_bounds": 0,
        "has_am_zero_constraints": 0,
        "has_pm_lower_bounds": 0,
        "has_pm_zero_constraints": 0,
        "cross_halfday_lower_bounds": 0,
    }
    constraint_index = 1

    for raw_key, assignment_var_names in sorted(
        names_by_teacher_class_slot.items(),
        key=lambda item: (item[0][0], item[0][1], str(item[0][2].day), _slot_order_key(item[0][2])),
    ):
        bool_name = tcs_bool_by_raw_key[raw_key]
        constraints.append(
            LinearConstraintSpec(
                name=f"weekend_cross_halfday__tcs_bool__{constraint_index:04d}__{_safe_identifier(bool_name)}",
                expression=LinearExpression(
                    (
                        *(LinearTerm(name, 1) for name in assignment_var_names),
                        LinearTerm(bool_name, -1),
                    )
                ),
                sense="==",
                rhs=0,
                rule_id=rule_id,
            )
        )
        counts["teacher_class_slot_bool_equalities"] += 1
        constraint_index += 1

    tcs_bools_by_teacher_day_block: dict[tuple[str, str, str], list[str]] = {}
    for (teacher, _cls, slot), bool_name in tcs_bool_by_raw_key.items():
        if str(slot.day) in WEEKEND_DAYS:
            tcs_bools_by_teacher_day_block.setdefault((teacher, str(slot.day), str(slot.block)), []).append(bool_name)

    for teacher, day in active_teacher_days:
        has_am_name = teacher_halfday_variable_names[_teacher_halfday_key(teacher, day, "am")]
        has_pm_name = teacher_halfday_variable_names[_teacher_halfday_key(teacher, day, "pm")]
        cross_name = cross_halfday_variable_names[_teacher_day_key(teacher, day)]
        am_bool_names = tuple(
            sorted(
                (
                    *tcs_bools_by_teacher_day_block.get((teacher, day, "早自习"), ()),
                    *tcs_bools_by_teacher_day_block.get((teacher, day, "上午"), ()),
                )
            )
        )
        pm_bool_names = tuple(sorted(tcs_bools_by_teacher_day_block.get((teacher, day, "下午"), ())))

        for slot_bool_name in am_bool_names:
            constraints.append(
                LinearConstraintSpec(
                    name=f"weekend_cross_halfday__am_implies__{constraint_index:04d}__{_safe_identifier(slot_bool_name)}",
                    expression=LinearExpression((LinearTerm(slot_bool_name, 1), LinearTerm(has_am_name, -1))),
                    sense="<=",
                    rhs=0,
                    rule_id=rule_id,
                )
            )
            counts["teacher_slot_implies_has_am"] += 1
            constraint_index += 1
        for slot_bool_name in pm_bool_names:
            constraints.append(
                LinearConstraintSpec(
                    name=f"weekend_cross_halfday__pm_implies__{constraint_index:04d}__{_safe_identifier(slot_bool_name)}",
                    expression=LinearExpression((LinearTerm(slot_bool_name, 1), LinearTerm(has_pm_name, -1))),
                    sense="<=",
                    rhs=0,
                    rule_id=rule_id,
                )
            )
            counts["teacher_slot_implies_has_pm"] += 1
            constraint_index += 1

        if am_bool_names:
            constraints.append(
                LinearConstraintSpec(
                    name=f"weekend_cross_halfday__has_am_lower__{constraint_index:04d}__{_safe_identifier(teacher)}__{_safe_identifier(day)}",
                    expression=LinearExpression(
                        (
                            *(LinearTerm(name, 1) for name in am_bool_names),
                            LinearTerm(has_am_name, -1),
                        )
                    ),
                    sense=">=",
                    rhs=0,
                    rule_id=rule_id,
                )
            )
            counts["has_am_lower_bounds"] += 1
            constraint_index += 1
        else:
            constraints.append(
                _bool_value_constraint(
                    f"weekend_cross_halfday__no_am__{constraint_index:04d}__{_safe_identifier(teacher)}__{_safe_identifier(day)}",
                    has_am_name,
                    0,
                    rule_id,
                )
            )
            counts["has_am_zero_constraints"] += 1
            constraint_index += 1

        if pm_bool_names:
            constraints.append(
                LinearConstraintSpec(
                    name=f"weekend_cross_halfday__has_pm_lower__{constraint_index:04d}__{_safe_identifier(teacher)}__{_safe_identifier(day)}",
                    expression=LinearExpression(
                        (
                            *(LinearTerm(name, 1) for name in pm_bool_names),
                            LinearTerm(has_pm_name, -1),
                        )
                    ),
                    sense=">=",
                    rhs=0,
                    rule_id=rule_id,
                )
            )
            counts["has_pm_lower_bounds"] += 1
            constraint_index += 1
        else:
            constraints.append(
                _bool_value_constraint(
                    f"weekend_cross_halfday__no_pm__{constraint_index:04d}__{_safe_identifier(teacher)}__{_safe_identifier(day)}",
                    has_pm_name,
                    0,
                    rule_id,
                )
            )
            counts["has_pm_zero_constraints"] += 1
            constraint_index += 1

        constraints.append(
            LinearConstraintSpec(
                name=f"weekend_cross_halfday__cross_lower__{constraint_index:04d}__{_safe_identifier(teacher)}__{_safe_identifier(day)}",
                expression=LinearExpression(
                    (
                        LinearTerm(cross_name, 1),
                        LinearTerm(has_am_name, -1),
                        LinearTerm(has_pm_name, -1),
                    )
                ),
                sense=">=",
                rhs=-1,
                rule_id=rule_id,
            )
        )
        counts["cross_halfday_lower_bounds"] += 1
        constraint_index += 1

    objective = ObjectiveSpec(
        rule_id=rule_id,
        sense="minimize",
        expression=LinearExpression(
            tuple(LinearTerm(name, int(penalty)) for name in cross_halfday_variable_names.values())
        ),
    )
    ai_rule = AiRuleSpec(
        rule_id=rule_id,
        description="Day soft rule: penalize a teacher teaching both weekend morning and afternoon on the same day.",
        enforcement="soft",
        priority=8,
        source="scheduler.model.constraints.day_weekend_constraints:apply_weekend_cross_halfday_penalty",
    )
    problem = OptimizationProblemSpec(
        problem_id="scheduler_day_weekend_cross_halfday_penalty",
        variables=(*assignment_variables, *tcs_bool_variables, *halfday_variables, *cross_variables),
        rules=(ai_rule,),
        constraints=tuple(constraints),
        objective=objective,
    )
    rule_first_plan = build_rule_first_plan(
        rules=problem.rules,
        constraints=problem.constraints,
        objective_rule_id=objective.rule_id,
    )
    return SchedulerGenericRuleBridge(
        problem=problem,
        rule_first_plan=rule_first_plan,
        metadata_by_rule={
            rule_id: {
                "scheduler_rule_id": rule_id,
                "legacy_apply_fn": "apply_weekend_cross_halfday_penalty",
                "generic_contract_status": "covered_by_generic_contract",
                "runtime_rule_ids": generic_scheduler_rule_ids(),
                "constraint_family_counts": counts,
                "assignment_variable_names": assignment_names,
                "teacher_class_slot_variable_names": teacher_class_slot_bool_names,
                "teacher_halfday_variable_names": teacher_halfday_variable_names,
                "cross_halfday_variable_names": cross_halfday_variable_names,
                "penalty": int(penalty),
                "sunday_exempt_teachers": tuple(sorted(sunday_exempt)),
            }
        },
    )


def day_yjc_sunday_am12_pm12_to_ai_or_problem(
    data: Any,
    *,
    enabled: bool = True,
    mode: str = "hard",
    weight: int = 1000,
    teachers: Sequence[str] | None = None,
    rule_id: str = "joint.day.yjc_sunday_am12_pm12_rule",
) -> SchedulerGenericRuleBridge:
    """Compile the targeted Sunday AM1/AM2/PM1/PM2 combination rule into OptimizationProblemSpec."""
    if not enabled:
        return _empty_scheduler_rule_bridge(
            problem_id="scheduler_day_yjc_sunday_am12_pm12_rule",
            rule_id=rule_id,
            legacy_apply_fn="apply_yjc_sunday_am12_pm12_rule",
        )

    mode_norm = str(mode or "hard").strip().lower()
    if mode_norm not in {"hard", "soft"}:
        mode_norm = "hard"

    assignments = _day_candidate_assignment_names(data)
    assignment_variables = tuple(VariableSpec.bool(name) for (_cls, _subj, _slot, name) in assignments)
    assignment_names: dict[str, str] = {}
    names_by_teacher_slot: dict[tuple[str, str, str, int], list[str]] = {}
    for cls, subj, slot, name in assignments:
        assignment_names[_assignment_key(cls, subj, str(slot.day), _slot_label(slot))] = name
        teacher = getattr(data, "cls_subj_teacher", {}).get((cls, subj))
        if teacher is None:
            continue
        names_by_teacher_slot.setdefault((str(teacher), str(slot.day), str(slot.block), int(slot.period)), []).append(name)

    all_teachers = {str(teacher) for (_cls, _subj), teacher in getattr(data, "cls_subj_teacher", {}).items() if teacher}
    target_teachers = tuple(sorted({teacher for teacher in _teacher_names(teachers or ()) if teacher in all_teachers}))
    slot_defs = (
        ("am1", "上午", 1),
        ("am2", "上午", 2),
        ("pm1", "下午", 1),
        ("pm2", "下午", 2),
    )
    slot_variable_names: dict[str, str] = {}
    combo_variable_names: dict[str, str] = {}
    slot_var_index = 1
    combo_var_index = 1
    for teacher in target_teachers:
        for tag, _block, _period in slot_defs:
            slot_variable_names[_teacher_target_slot_key(teacher, "星期日", tag)] = _teacher_target_slot_bool_name(
                slot_var_index,
                teacher,
                "星期日",
                tag,
            )
            slot_var_index += 1
        combo_variable_names[_teacher_day_key(teacher, "星期日")] = _teacher_target_combo_bool_name(
            combo_var_index,
            teacher,
            "星期日",
        )
        combo_var_index += 1

    slot_variables = tuple(VariableSpec.bool(name) for name in slot_variable_names.values())
    combo_variables = tuple(VariableSpec.bool(name) for name in combo_variable_names.values())
    constraints: list[LinearConstraintSpec] = []
    counts = {
        "target_slot_fixed_one": 0,
        "target_slot_lower_bounds": 0,
        "target_slot_implies": 0,
        "target_slot_zero": 0,
        "combo_upper_bounds": 0,
        "combo_lower_bounds": 0,
        "combo_hard_zero": 0,
    }
    constraint_index = 1
    fixed_assign = getattr(data, "fixed_assign", {}) or {}

    for teacher in target_teachers:
        has_slot_names: list[str] = []
        for tag, block, period in slot_defs:
            has_slot_name = slot_variable_names[_teacher_target_slot_key(teacher, "星期日", tag)]
            has_slot_names.append(has_slot_name)
            fixed_hit = _has_fixed_teacher_slot(data, fixed_assign, teacher, "星期日", block, period)
            var_names = tuple(sorted(names_by_teacher_slot.get((teacher, "星期日", block, int(period)), ())))
            if fixed_hit:
                constraints.append(
                    _bool_value_constraint(
                        f"yjc_sunday_am12_pm12__fixed_{tag}__{constraint_index:04d}__{_safe_identifier(teacher)}",
                        has_slot_name,
                        1,
                        rule_id,
                    )
                )
                counts["target_slot_fixed_one"] += 1
                constraint_index += 1
            elif var_names:
                constraints.append(
                    LinearConstraintSpec(
                        name=f"yjc_sunday_am12_pm12__has_{tag}_lower__{constraint_index:04d}__{_safe_identifier(teacher)}",
                        expression=LinearExpression(
                            (
                                *(LinearTerm(name, 1) for name in var_names),
                                LinearTerm(has_slot_name, -1),
                            )
                        ),
                        sense=">=",
                        rhs=0,
                        rule_id=rule_id,
                    )
                )
                counts["target_slot_lower_bounds"] += 1
                constraint_index += 1
                for var_name in var_names:
                    constraints.append(
                        LinearConstraintSpec(
                            name=f"yjc_sunday_am12_pm12__{tag}_implies__{constraint_index:04d}__{_safe_identifier(var_name)}",
                            expression=LinearExpression((LinearTerm(var_name, 1), LinearTerm(has_slot_name, -1))),
                            sense="<=",
                            rhs=0,
                            rule_id=rule_id,
                        )
                    )
                    counts["target_slot_implies"] += 1
                    constraint_index += 1
            else:
                constraints.append(
                    _bool_value_constraint(
                        f"yjc_sunday_am12_pm12__no_{tag}__{constraint_index:04d}__{_safe_identifier(teacher)}",
                        has_slot_name,
                        0,
                        rule_id,
                    )
                )
                counts["target_slot_zero"] += 1
                constraint_index += 1

        combo_name = combo_variable_names[_teacher_day_key(teacher, "星期日")]
        for has_slot_name in has_slot_names:
            constraints.append(
                LinearConstraintSpec(
                    name=f"yjc_sunday_am12_pm12__combo_upper__{constraint_index:04d}__{_safe_identifier(combo_name)}",
                    expression=LinearExpression((LinearTerm(combo_name, 1), LinearTerm(has_slot_name, -1))),
                    sense="<=",
                    rhs=0,
                    rule_id=rule_id,
                )
            )
            counts["combo_upper_bounds"] += 1
            constraint_index += 1
        constraints.append(
            LinearConstraintSpec(
                name=f"yjc_sunday_am12_pm12__combo_lower__{constraint_index:04d}__{_safe_identifier(combo_name)}",
                expression=LinearExpression(
                    (
                        LinearTerm(combo_name, 1),
                        *(LinearTerm(name, -1) for name in has_slot_names),
                    )
                ),
                sense=">=",
                rhs=-3,
                rule_id=rule_id,
            )
        )
        counts["combo_lower_bounds"] += 1
        constraint_index += 1
        if mode_norm == "hard":
            constraints.append(
                _bool_value_constraint(
                    f"yjc_sunday_am12_pm12__combo_hard_zero__{constraint_index:04d}__{_safe_identifier(combo_name)}",
                    combo_name,
                    0,
                    rule_id,
                )
            )
            counts["combo_hard_zero"] += 1
            constraint_index += 1

    objective = None
    if mode_norm == "soft" and combo_variable_names:
        objective = ObjectiveSpec(
            rule_id=rule_id,
            sense="minimize",
            expression=LinearExpression(tuple(LinearTerm(name, int(weight)) for name in combo_variable_names.values())),
        )
    ai_rule = AiRuleSpec(
        rule_id=rule_id,
        description="Day targeted rule: Sunday AM1/AM2/PM1/PM2 combination is forbidden or penalized for configured teachers.",
        enforcement=mode_norm,
        priority=10,
        source="scheduler.model.constraints.day_weekend_constraints:apply_yjc_sunday_am12_pm12_rule",
    )
    problem = OptimizationProblemSpec(
        problem_id="scheduler_day_yjc_sunday_am12_pm12_rule",
        variables=(*assignment_variables, *slot_variables, *combo_variables),
        rules=(ai_rule,),
        constraints=tuple(constraints),
        objective=objective,
    )
    rule_first_plan = build_rule_first_plan(
        rules=problem.rules,
        constraints=problem.constraints,
        objective_rule_id=objective.rule_id if objective is not None else None,
    )
    return SchedulerGenericRuleBridge(
        problem=problem,
        rule_first_plan=rule_first_plan,
        metadata_by_rule={
            rule_id: {
                "scheduler_rule_id": rule_id,
                "legacy_apply_fn": "apply_yjc_sunday_am12_pm12_rule",
                "generic_contract_status": "covered_by_generic_contract",
                "runtime_rule_ids": generic_scheduler_rule_ids(),
                "constraint_family_counts": counts,
                "assignment_variable_names": assignment_names,
                "target_slot_variable_names": slot_variable_names,
                "combo_variable_names": combo_variable_names,
                "target_teachers": target_teachers,
                "mode": mode_norm,
                "weight": int(weight),
            }
        },
    )


def day_binding_8chem_9bio_to_ai_or_problem(
    data: Any,
    *,
    rule_id: str = "joint.day.binding_8chem_9bio",
) -> SchedulerGenericRuleBridge:
    """Compile the day 8-class chemistry / 9-class biology binding rule."""
    assignments = _day_candidate_assignment_names(data)
    variables = tuple(VariableSpec.bool(name) for (_cls, _subj, _slot, name) in assignments)
    assignment_names: dict[str, str] = {}
    names_by_class_subject_slot: dict[tuple[str, str, Any], list[str]] = {}
    for cls, subj, slot, name in assignments:
        assignment_names[_assignment_key(cls, subj, str(slot.day), _slot_label(slot))] = name
        names_by_class_subject_slot.setdefault((cls, subj, slot), []).append(name)

    class_list = _text_tuple(data.classes)
    class_8 = _find_class_by_marker(class_list, "8班")
    class_9 = _find_class_by_marker(class_list, "9班")
    fixed_assign = getattr(data, "fixed_assign", {}) or {}
    constraints: list[LinearConstraintSpec] = []
    constraint_index = 1
    if class_8 is not None and class_9 is not None:
        for slot in tuple(data.available_slots):
            left_names, left_const = _day_class_subject_slot_expr_parts(
                fixed_assign,
                names_by_class_subject_slot,
                class_8,
                "化学",
                slot,
            )
            right_names, right_const = _day_class_subject_slot_expr_parts(
                fixed_assign,
                names_by_class_subject_slot,
                class_9,
                "生物",
                slot,
            )
            constraints.append(
                LinearConstraintSpec(
                    name=f"day_binding_8chem_9bio__{constraint_index:04d}__{_safe_identifier(str(slot.day))}__{_safe_identifier(_slot_label(slot))}",
                    expression=LinearExpression(
                        (
                            *(LinearTerm(name, 1) for name in left_names),
                            *(LinearTerm(name, -1) for name in right_names),
                        ),
                        constant=int(left_const) - int(right_const),
                    ),
                    sense="==",
                    rhs=0,
                    rule_id=rule_id,
                )
            )
            constraint_index += 1

    ai_rule = AiRuleSpec(
        rule_id=rule_id,
        description="Day hard binding: class containing 8班 chemistry equals class containing 9班 biology at every day slot.",
        enforcement="hard",
        priority=11,
        source="scheduler.model.constraints.global_binding_constraints:apply_global_day_binding_8_chem_9_bio",
    )
    problem = OptimizationProblemSpec(
        problem_id="scheduler_day_binding_8chem_9bio",
        variables=variables,
        rules=(ai_rule,),
        constraints=tuple(constraints),
    )
    rule_first_plan = build_rule_first_plan(
        rules=problem.rules,
        constraints=problem.constraints,
        objective_rule_id=None,
    )
    return SchedulerGenericRuleBridge(
        problem=problem,
        rule_first_plan=rule_first_plan,
        metadata_by_rule={
            rule_id: {
                "scheduler_rule_id": rule_id,
                "legacy_apply_fn": "apply_global_day_binding_8_chem_9_bio",
                "generic_contract_status": "covered_by_generic_contract",
                "runtime_rule_ids": generic_scheduler_rule_ids(),
                "constraint_family_counts": {
                    "8chem_9bio_equalities": len(constraints),
                },
                "binding_classes": {
                    "chemistry_class": class_8,
                    "biology_class": class_9,
                },
                "assignment_variable_names": assignment_names,
            }
        },
    )


def day_weekend_halfday_constraint_to_ai_or_problem(
    data: Any,
    *,
    enabled: bool = True,
    mode: str = "hard",
    rule_id: str = "joint.day.weekend_halfday_constraint",
) -> SchedulerGenericRuleBridge:
    """Compile the weekend half-day hard concentration rule into OptimizationProblemSpec."""
    if not enabled:
        return _empty_scheduler_rule_bridge(
            problem_id="scheduler_day_weekend_halfday_constraint",
            rule_id=rule_id,
            legacy_apply_fn="apply_weekend_halfday_constraint",
        )
    if str(mode or "hard").strip().lower() != "hard":
        raise ValueError("day_weekend_halfday_constraint_to_ai_or_problem currently supports mode='hard'")

    assignments = _day_candidate_assignment_names(data)
    assignment_variables = tuple(VariableSpec.bool(name) for (_cls, _subj, _slot, name) in assignments)
    assignment_names: dict[str, str] = {}
    names_by_teacher_class_slot: dict[tuple[str, str, Any], list[str]] = {}
    for cls, subj, slot, name in assignments:
        assignment_names[_assignment_key(cls, subj, str(slot.day), _slot_label(slot))] = name
        teacher = getattr(data, "cls_subj_teacher", {}).get((cls, subj))
        if teacher is None:
            continue
        names_by_teacher_class_slot.setdefault((str(teacher), cls, slot), []).append(name)

    sorted_teacher_class_slots = tuple(
        sorted(
            names_by_teacher_class_slot,
            key=lambda item: (item[0], item[1], str(item[2].day), _slot_order_key(item[2])),
        )
    )
    teacher_class_slot_bool_names = {
        _teacher_class_slot_key(teacher, cls, slot): _teacher_class_slot_bool_name(index, teacher, cls, slot)
        for index, (teacher, cls, slot) in enumerate(sorted_teacher_class_slots, start=1)
    }
    tcs_bool_by_raw_key = {
        (teacher, cls, slot): teacher_class_slot_bool_names[_teacher_class_slot_key(teacher, cls, slot)]
        for teacher, cls, slot in names_by_teacher_class_slot
    }
    tcs_bool_variables = tuple(VariableSpec.bool(name) for name in teacher_class_slot_bool_names.values())

    teachers = sorted({str(teacher) for (_cls, _subj), teacher in getattr(data, "cls_subj_teacher", {}).items() if teacher})
    teacher_halfday_variable_names = {
        _teacher_halfday_key(teacher, day, halfday): _teacher_weekend_halfday_bool_name(index, teacher, day, halfday)
        for index, (teacher, day, halfday) in enumerate(
            ((teacher, day, halfday) for teacher in teachers for day in WEEKEND_DAYS for halfday in ("am", "pm")),
            start=1,
        )
    }
    halfday_variables = tuple(VariableSpec.bool(name) for name in teacher_halfday_variable_names.values())

    constraints: list[LinearConstraintSpec] = []
    counts = {
        "teacher_class_slot_bool_equalities": 0,
        "has_am_lower_bounds": 0,
        "teacher_slot_implies_has_am": 0,
        "has_pm_fixed_or_zero_or_lower_bounds": 0,
        "teacher_weekend_halfday_hard_mutex": 0,
    }
    constraint_index = 1

    for raw_key, assignment_var_names in sorted(
        names_by_teacher_class_slot.items(),
        key=lambda item: (item[0][0], item[0][1], str(item[0][2].day), _slot_order_key(item[0][2])),
    ):
        bool_name = tcs_bool_by_raw_key[raw_key]
        constraints.append(
            LinearConstraintSpec(
                name=f"weekend_halfday__tcs_bool__{constraint_index:04d}__{_safe_identifier(bool_name)}",
                expression=LinearExpression(
                    (
                        *(LinearTerm(name, 1) for name in assignment_var_names),
                        LinearTerm(bool_name, -1),
                    )
                ),
                sense="==",
                rhs=0,
                rule_id=rule_id,
            )
        )
        counts["teacher_class_slot_bool_equalities"] += 1
        constraint_index += 1

    tcs_bools_by_teacher_day_block: dict[tuple[str, str, str], list[str]] = {}
    for (teacher, _cls, slot), bool_name in tcs_bool_by_raw_key.items():
        if str(slot.day) in WEEKEND_DAYS:
            tcs_bools_by_teacher_day_block.setdefault((teacher, str(slot.day), str(slot.block)), []).append(bool_name)

    fixed_assign = getattr(data, "fixed_assign", {}) or {}
    for teacher in teachers:
        for day in WEEKEND_DAYS:
            has_am_name = teacher_halfday_variable_names[_teacher_halfday_key(teacher, day, "am")]
            has_pm_name = teacher_halfday_variable_names[_teacher_halfday_key(teacher, day, "pm")]
            am_bool_names = tuple(tcs_bools_by_teacher_day_block.get((teacher, day, "上午"), ()))
            pm_bool_names = tuple(tcs_bools_by_teacher_day_block.get((teacher, day, "下午"), ()))
            fixed_am = _has_fixed_teacher_halfday(data, fixed_assign, teacher, day, "上午")
            fixed_pm = _has_fixed_teacher_halfday(data, fixed_assign, teacher, day, "下午")

            if fixed_am:
                constraints.append(_bool_value_constraint(
                    f"weekend_halfday__fixed_am__{constraint_index:04d}__{_safe_identifier(teacher)}__{_safe_identifier(day)}",
                    has_am_name,
                    1,
                    rule_id,
                ))
                constraint_index += 1
            elif am_bool_names:
                constraints.append(
                    LinearConstraintSpec(
                        name=f"weekend_halfday__has_am_lower__{constraint_index:04d}__{_safe_identifier(teacher)}__{_safe_identifier(day)}",
                        expression=LinearExpression(
                            (
                                *(LinearTerm(name, 1) for name in am_bool_names),
                                LinearTerm(has_am_name, -1),
                            )
                        ),
                        sense=">=",
                        rhs=0,
                        rule_id=rule_id,
                    )
                )
                counts["has_am_lower_bounds"] += 1
                constraint_index += 1
                for slot_bool_name in am_bool_names:
                    constraints.append(
                        LinearConstraintSpec(
                            name=f"weekend_halfday__am_implies__{constraint_index:04d}__{_safe_identifier(slot_bool_name)}",
                            expression=LinearExpression((LinearTerm(slot_bool_name, 1), LinearTerm(has_am_name, -1))),
                            sense="<=",
                            rhs=0,
                            rule_id=rule_id,
                        )
                    )
                    counts["teacher_slot_implies_has_am"] += 1
                    constraint_index += 1
            else:
                constraints.append(_bool_value_constraint(
                    f"weekend_halfday__no_am__{constraint_index:04d}__{_safe_identifier(teacher)}__{_safe_identifier(day)}",
                    has_am_name,
                    0,
                    rule_id,
                ))
                constraint_index += 1

            if fixed_pm:
                constraints.append(_bool_value_constraint(
                    f"weekend_halfday__fixed_pm__{constraint_index:04d}__{_safe_identifier(teacher)}__{_safe_identifier(day)}",
                    has_pm_name,
                    1,
                    rule_id,
                ))
                counts["has_pm_fixed_or_zero_or_lower_bounds"] += 1
                constraint_index += 1
            elif pm_bool_names:
                constraints.append(
                    LinearConstraintSpec(
                        name=f"weekend_halfday__has_pm_lower__{constraint_index:04d}__{_safe_identifier(teacher)}__{_safe_identifier(day)}",
                        expression=LinearExpression(
                            (
                                *(LinearTerm(name, 1) for name in pm_bool_names),
                                LinearTerm(has_pm_name, -1),
                            )
                        ),
                        sense=">=",
                        rhs=0,
                        rule_id=rule_id,
                    )
                )
                counts["has_pm_fixed_or_zero_or_lower_bounds"] += 1
                constraint_index += 1
                for slot_bool_name in pm_bool_names:
                    constraints.append(
                        LinearConstraintSpec(
                            name=f"weekend_halfday__pm_implies__{constraint_index:04d}__{_safe_identifier(slot_bool_name)}",
                            expression=LinearExpression((LinearTerm(slot_bool_name, 1), LinearTerm(has_pm_name, -1))),
                            sense="<=",
                            rhs=0,
                            rule_id=rule_id,
                        )
                    )
                    constraint_index += 1
            else:
                constraints.append(_bool_value_constraint(
                    f"weekend_halfday__no_pm__{constraint_index:04d}__{_safe_identifier(teacher)}__{_safe_identifier(day)}",
                    has_pm_name,
                    0,
                    rule_id,
                ))
                counts["has_pm_fixed_or_zero_or_lower_bounds"] += 1
                constraint_index += 1

            constraints.append(
                LinearConstraintSpec(
                    name=f"weekend_halfday__hard_mutex__{constraint_index:04d}__{_safe_identifier(teacher)}__{_safe_identifier(day)}",
                    expression=LinearExpression((LinearTerm(has_am_name, 1), LinearTerm(has_pm_name, 1))),
                    sense="<=",
                    rhs=1,
                    rule_id=rule_id,
                )
            )
            counts["teacher_weekend_halfday_hard_mutex"] += 1
            constraint_index += 1

    ai_rule = AiRuleSpec(
        rule_id=rule_id,
        description="Day hard rule: weekend teaching for each teacher must stay within one half-day.",
        enforcement="hard",
        priority=7,
        source="scheduler.model.constraints.day_weekend_constraints:apply_weekend_halfday_constraint",
    )
    problem = OptimizationProblemSpec(
        problem_id="scheduler_day_weekend_halfday_constraint",
        variables=(*assignment_variables, *tcs_bool_variables, *halfday_variables),
        rules=(ai_rule,),
        constraints=tuple(constraints),
    )
    rule_first_plan = build_rule_first_plan(
        rules=problem.rules,
        constraints=problem.constraints,
        objective_rule_id=None,
    )
    return SchedulerGenericRuleBridge(
        problem=problem,
        rule_first_plan=rule_first_plan,
        metadata_by_rule={
            rule_id: {
                "scheduler_rule_id": rule_id,
                "legacy_apply_fn": "apply_weekend_halfday_constraint",
                "generic_contract_status": "covered_by_generic_contract",
                "runtime_rule_ids": generic_scheduler_rule_ids(),
                "constraint_family_counts": counts,
                "assignment_variable_names": assignment_names,
                "teacher_class_slot_variable_names": teacher_class_slot_bool_names,
                "teacher_halfday_variable_names": teacher_halfday_variable_names,
            }
        },
    )


def night_hard_base_to_ai_or_problem(
    *,
    classes: Sequence[Any],
    cst: Mapping[tuple[Any, Any], Any],
    days: Sequence[Any],
    periods: Sequence[Any],
    rules: Mapping[str, Any],
    rule_id: str = "night.hard_base",
) -> SchedulerGenericRuleBridge:
    """Compile the legacy night hard-base H1/H2/H3 rule into OptimizationProblemSpec."""
    class_list = _text_tuple(classes)
    day_list = _text_tuple(days)
    period_list = _text_tuple(periods)
    cst_keys = tuple((str(cls), str(subj)) for cls, subj in cst.keys())
    weekly_k = int(((rules.get("evening") if isinstance(rules, Mapping) else {}) or {}).get(
        "weekly_occurrences_per_subject",
        2,
    ))

    assignment_names: dict[tuple[str, str, str, str], str] = {}
    variables: list[VariableSpec] = []
    for index, (cls, subj, day, period) in enumerate(
        (
            (cls, subj, day, period)
            for cls, subj in cst_keys
            for day in day_list
            for period in period_list
        ),
        start=1,
    ):
        name = _night_assignment_var_name(index, cls, subj, day, period)
        assignment_names[(cls, subj, day, period)] = name
        variables.append(VariableSpec.bool(name))

    constraints: list[LinearConstraintSpec] = []

    for cls in class_list:
        subj_list = tuple(subj for c, subj in cst_keys if c == cls)
        for day in day_list:
            for period in period_list:
                constraints.append(
                    LinearConstraintSpec(
                        name=f"hard_base_h1_exactly_one__{_safe_identifier(cls)}__{_safe_identifier(day)}__{_safe_identifier(period)}",
                        expression=_sum_expr(
                            assignment_names[(cls, subj, day, period)]
                            for subj in subj_list
                        ),
                        sense="==",
                        rhs=1,
                        rule_id=rule_id,
                    )
                )

    for cls, subj in cst_keys:
        constraints.append(
            LinearConstraintSpec(
                name=f"hard_base_h2_weekly_count__{_safe_identifier(cls)}__{_safe_identifier(subj)}",
                expression=_sum_expr(
                    assignment_names[(cls, subj, day, period)]
                    for day in day_list
                    for period in period_list
                ),
                sense="==",
                rhs=weekly_k,
                rule_id=rule_id,
            )
        )

    for cls, subj in cst_keys:
        for day in day_list:
            constraints.append(
                LinearConstraintSpec(
                    name=f"hard_base_h3_daily_subject_cap__{_safe_identifier(cls)}__{_safe_identifier(subj)}__{_safe_identifier(day)}",
                    expression=_sum_expr(
                        assignment_names[(cls, subj, day, period)]
                        for period in period_list
                    ),
                    sense="<=",
                    rhs=1,
                    rule_id=rule_id,
                )
            )

    ai_rule = AiRuleSpec(
        rule_id=rule_id,
        description="Night hard-base H1 exactly-one, H2 weekly count, and H3 daily subject cap.",
        enforcement="hard",
        priority=1,
        source="scheduler.model.constraints.hard_base:apply_hard_base",
    )
    problem = OptimizationProblemSpec(
        problem_id="scheduler_night_hard_base",
        variables=tuple(variables),
        rules=(ai_rule,),
        constraints=tuple(constraints),
    )
    rule_first_plan = build_rule_first_plan(
        rules=problem.rules,
        constraints=problem.constraints,
        objective_rule_id=None,
    )
    return SchedulerGenericRuleBridge(
        problem=problem,
        rule_first_plan=rule_first_plan,
        metadata_by_rule={
            rule_id: {
                "scheduler_rule_id": rule_id,
                "legacy_apply_fn": "apply_hard_base",
                "generic_contract_status": "covered_by_generic_contract",
                "runtime_rule_ids": generic_scheduler_rule_ids(),
                "constraint_family_counts": {
                    "h1_exactly_one": len(class_list) * len(day_list) * len(period_list),
                    "h2_weekly_count": len(cst_keys),
                    "h3_daily_subject_cap": len(cst_keys) * len(day_list),
                },
                "assignment_variable_names": {
                    _assignment_key(cls, subj, day, period): name
                    for (cls, subj, day, period), name in assignment_names.items()
                },
            }
        },
    )


def night_hard_bans_to_ai_or_problem(
    *,
    classes: Sequence[Any],
    cst: Mapping[tuple[Any, Any], Any],
    days: Sequence[Any],
    periods: Sequence[Any],
    rules: Mapping[str, Any],
    rule_id: str = "night.hard_bans",
) -> SchedulerGenericRuleBridge:
    """Compile the legacy night subject/teacher-day hard bans into OptimizationProblemSpec."""
    _ = classes
    cfg = ((rules.get("hard_bans") if isinstance(rules, Mapping) else {}) or {})
    if not cfg.get("enabled", False):
        return _empty_scheduler_rule_bridge("scheduler_night_hard_bans", rule_id, "apply_hard_bans")

    day_list = _text_tuple(days)
    period_list = _text_tuple(periods)
    cst_entries = tuple((str(cls), str(subj), str(tch)) for (cls, subj), tch in cst.items())

    assignment_names: dict[tuple[str, str, str, str], str] = {}
    variables: list[VariableSpec] = []
    for index, (cls, subj, _teacher, day, period) in enumerate(
        (
            (cls, subj, teacher, day, period)
            for cls, subj, teacher in cst_entries
            for day in day_list
            for period in period_list
        ),
        start=1,
    ):
        name = _night_assignment_var_name(index, cls, subj, day, period)
        assignment_names[(cls, subj, day, period)] = name
        variables.append(VariableSpec.bool(name))

    constraints: list[LinearConstraintSpec] = []
    blocked_assignment_names: list[str] = []
    counts = {
        "subject_bans": 0,
        "teacher_day_bans": 0,
    }
    constraint_index = 1

    for item in cfg.get("subject_bans", []) or []:
        if not isinstance(item, Mapping):
            continue
        raw_subject = item.get("subject")
        if not raw_subject:
            continue
        subject = str(raw_subject)
        ban_days = {str(day) for day in (item.get("days", []) or [])}
        raw_ban_periods = item.get("periods", []) or []
        ban_periods = {str(period) for period in raw_ban_periods} if raw_ban_periods else set(period_list)
        for cls, subj, _teacher in cst_entries:
            if subj != subject:
                continue
            for day in day_list:
                if day not in ban_days:
                    continue
                for period in period_list:
                    if period not in ban_periods:
                        continue
                    variable_name = assignment_names[(cls, subj, day, period)]
                    constraints.append(
                        _bool_value_constraint(
                            f"hard_bans_subject__{constraint_index:04d}__{_safe_identifier(cls)}__{_safe_identifier(subj)}__{_safe_identifier(day)}__{_safe_identifier(period)}",
                            variable_name,
                            0,
                            rule_id,
                        )
                    )
                    blocked_assignment_names.append(variable_name)
                    counts["subject_bans"] += 1
                    constraint_index += 1

    for raw_day, ban_teachers in (cfg.get("teacher_day_bans", {}) or {}).items():
        day = str(raw_day)
        if day not in day_list:
            continue
        ban_set = {str(teacher) for teacher in (ban_teachers or [])}
        for cls, subj, teacher in cst_entries:
            if teacher not in ban_set:
                continue
            for period in period_list:
                variable_name = assignment_names[(cls, subj, day, period)]
                constraints.append(
                    _bool_value_constraint(
                        f"hard_bans_teacher_day__{constraint_index:04d}__{_safe_identifier(teacher)}__{_safe_identifier(day)}__{_safe_identifier(cls)}__{_safe_identifier(subj)}__{_safe_identifier(period)}",
                        variable_name,
                        0,
                        rule_id,
                    )
                )
                blocked_assignment_names.append(variable_name)
                counts["teacher_day_bans"] += 1
                constraint_index += 1

    ai_rule = AiRuleSpec(
        rule_id=rule_id,
        description="Night hard bans: subject-day-period and teacher-day assignments are forced to zero.",
        enforcement="hard",
        priority=2,
        source="scheduler.model.constraints.hard_bans:apply_hard_bans",
    )
    problem = OptimizationProblemSpec(
        problem_id="scheduler_night_hard_bans",
        variables=tuple(variables),
        rules=(ai_rule,),
        constraints=tuple(constraints),
    )
    rule_first_plan = build_rule_first_plan(
        rules=problem.rules,
        constraints=problem.constraints,
        objective_rule_id=None,
    )
    return SchedulerGenericRuleBridge(
        problem=problem,
        rule_first_plan=rule_first_plan,
        metadata_by_rule={
            rule_id: {
                "scheduler_rule_id": rule_id,
                "legacy_apply_fn": "apply_hard_bans",
                "generic_contract_status": "covered_by_generic_contract",
                "runtime_rule_ids": generic_scheduler_rule_ids(),
                "constraint_family_counts": counts,
                "assignment_variable_names": {
                    _assignment_key(cls, subj, day, period): name
                    for (cls, subj, day, period), name in assignment_names.items()
                },
                "blocked_assignment_variable_names": tuple(blocked_assignment_names),
            }
        },
    )


def night_hard_teacher_limits_to_ai_or_problem(
    *,
    classes: Sequence[Any],
    cst: Mapping[tuple[Any, Any], Any],
    days: Sequence[Any],
    periods: Sequence[Any],
    rules: Mapping[str, Any],
    rule_id: str = "night.hard_teacher_limits",
) -> SchedulerGenericRuleBridge:
    """Compile the legacy night teacher conflict and weekly day-cap hard rules."""
    _ = (classes, rules)
    day_list = _text_tuple(days)
    period_list = _text_tuple(periods)
    cst_entries = tuple((str(cls), str(subj), str(tch)) for (cls, subj), tch in cst.items())
    teacher_list = tuple(sorted({teacher for _cls, _subj, teacher in cst_entries}))

    assignment_names: dict[tuple[str, str, str, str], str] = {}
    assignment_variables: list[VariableSpec] = []
    for index, (cls, subj, _teacher, day, period) in enumerate(
        (
            (cls, subj, teacher, day, period)
            for cls, subj, teacher in cst_entries
            for day in day_list
            for period in period_list
        ),
        start=1,
    ):
        name = _night_assignment_var_name(index, cls, subj, day, period)
        assignment_names[(cls, subj, day, period)] = name
        assignment_variables.append(VariableSpec.bool(name))

    teacher_day_variable_names: dict[tuple[str, str], str] = {}
    teacher_day_variables: list[VariableSpec] = []
    for index, (teacher, day) in enumerate(
        ((teacher, day) for teacher in teacher_list for day in day_list),
        start=1,
    ):
        name = _night_teacher_day_var_name(index, teacher, day)
        teacher_day_variable_names[(teacher, day)] = name
        teacher_day_variables.append(VariableSpec.bool(name))

    names_by_teacher_day_period: dict[tuple[str, str, str], list[str]] = {}
    for cls, subj, teacher in cst_entries:
        for day in day_list:
            for period in period_list:
                names_by_teacher_day_period.setdefault((teacher, day, period), []).append(
                    assignment_names[(cls, subj, day, period)]
                )

    constraints: list[LinearConstraintSpec] = []
    counts = {
        "teacher_period_no_conflict": 0,
        "teacher_weekly_day_cap": 0,
    }
    constraint_index = 1

    for teacher in teacher_list:
        for day in day_list:
            for period in period_list:
                names = names_by_teacher_day_period.get((teacher, day, period), [])
                if len(names) < 2:
                    continue
                constraints.append(
                    LinearConstraintSpec(
                        name=f"hard_teacher_limits_t1_no_conflict__{constraint_index:04d}__{_safe_identifier(teacher)}__{_safe_identifier(day)}__{_safe_identifier(period)}",
                        expression=_sum_expr(names),
                        sense="<=",
                        rhs=1,
                        rule_id=rule_id,
                    )
                )
                counts["teacher_period_no_conflict"] += 1
                constraint_index += 1

    for teacher in teacher_list:
        names = [
            teacher_day_variable_names[(teacher, day)]
            for day in day_list
            if (teacher, day) in teacher_day_variable_names
        ]
        if not names:
            continue
        constraints.append(
            LinearConstraintSpec(
                name=f"hard_teacher_limits_t2_weekly_day_cap__{constraint_index:04d}__{_safe_identifier(teacher)}",
                expression=_sum_expr(names),
                sense="<=",
                rhs=2,
                rule_id=rule_id,
            )
        )
        counts["teacher_weekly_day_cap"] += 1
        constraint_index += 1

    ai_rule = AiRuleSpec(
        rule_id=rule_id,
        description="Night hard teacher limits: no teacher conflict in a period and max two teaching days.",
        enforcement="hard",
        priority=3,
        source="scheduler.model.constraints.hard_teacher_limits:apply_hard_teacher_limits",
    )
    problem = OptimizationProblemSpec(
        problem_id="scheduler_night_hard_teacher_limits",
        variables=(*assignment_variables, *teacher_day_variables),
        rules=(ai_rule,),
        constraints=tuple(constraints),
    )
    rule_first_plan = build_rule_first_plan(
        rules=problem.rules,
        constraints=problem.constraints,
        objective_rule_id=None,
    )
    return SchedulerGenericRuleBridge(
        problem=problem,
        rule_first_plan=rule_first_plan,
        metadata_by_rule={
            rule_id: {
                "scheduler_rule_id": rule_id,
                "legacy_apply_fn": "apply_hard_teacher_limits",
                "generic_contract_status": "covered_by_generic_contract",
                "runtime_rule_ids": generic_scheduler_rule_ids(),
                "constraint_family_counts": counts,
                "assignment_variable_names": {
                    _assignment_key(cls, subj, day, period): name
                    for (cls, subj, day, period), name in assignment_names.items()
                },
                "teacher_day_variable_names": {
                    _teacher_day_key(teacher, day): name
                    for (teacher, day), name in teacher_day_variable_names.items()
                },
            }
        },
    )


def night_binding_8chem_9bio_to_ai_or_problem(
    *,
    classes: Sequence[Any],
    cst: Mapping[tuple[Any, Any], Any],
    days: Sequence[Any],
    periods: Sequence[Any],
    rules: Mapping[str, Any] | None = None,
    rule_id: str = "night.binding_8chem_9bio",
) -> SchedulerGenericRuleBridge:
    """Compile the legacy night 8-class chemistry / 9-class biology binding rule."""
    _ = rules
    class_list = _text_tuple(classes)
    day_list = _text_tuple(days)
    period_list = _text_tuple(periods)
    cst_entries = tuple((str(cls), str(subj), str(tch)) for (cls, subj), tch in cst.items())

    assignment_names: dict[tuple[str, str, str, str], str] = {}
    variables: list[VariableSpec] = []
    for index, (cls, subj, _teacher, day, period) in enumerate(
        (
            (cls, subj, teacher, day, period)
            for cls, subj, teacher in cst_entries
            for day in day_list
            for period in period_list
        ),
        start=1,
    ):
        name = _night_assignment_var_name(index, cls, subj, day, period)
        assignment_names[(cls, subj, day, period)] = name
        variables.append(VariableSpec.bool(name))

    class_8 = _find_class_by_marker(class_list, "8班")
    class_9 = _find_class_by_marker(class_list, "9班")
    constraints: list[LinearConstraintSpec] = []
    constraint_index = 1
    if (
        class_8 is not None
        and class_9 is not None
        and (class_8, "化学") in {(cls, subj) for cls, subj, _teacher in cst_entries}
        and (class_9, "生物") in {(cls, subj) for cls, subj, _teacher in cst_entries}
    ):
        for day in day_list:
            for period in period_list:
                left_name = assignment_names.get((class_8, "化学", day, period))
                right_name = assignment_names.get((class_9, "生物", day, period))
                if left_name is None or right_name is None:
                    continue
                constraints.append(
                    LinearConstraintSpec(
                        name=f"night_binding_8chem_9bio__{constraint_index:04d}__{_safe_identifier(day)}__{_safe_identifier(period)}",
                        expression=LinearExpression(
                            (
                                LinearTerm(left_name, 1),
                                LinearTerm(right_name, -1),
                            )
                        ),
                        sense="==",
                        rhs=0,
                        rule_id=rule_id,
                    )
                )
                constraint_index += 1

    ai_rule = AiRuleSpec(
        rule_id=rule_id,
        description="Night hard binding: class containing 8班 chemistry equals class containing 9班 biology at every night slot.",
        enforcement="hard",
        priority=4,
        source="scheduler.model.constraints.global_binding_constraints:apply_global_night_binding_8_chem_9_bio",
    )
    problem = OptimizationProblemSpec(
        problem_id="scheduler_night_binding_8chem_9bio",
        variables=tuple(variables),
        rules=(ai_rule,),
        constraints=tuple(constraints),
    )
    rule_first_plan = build_rule_first_plan(
        rules=problem.rules,
        constraints=problem.constraints,
        objective_rule_id=None,
    )
    return SchedulerGenericRuleBridge(
        problem=problem,
        rule_first_plan=rule_first_plan,
        metadata_by_rule={
            rule_id: {
                "scheduler_rule_id": rule_id,
                "legacy_apply_fn": "apply_global_night_binding_8_chem_9_bio",
                "generic_contract_status": "covered_by_generic_contract",
                "runtime_rule_ids": generic_scheduler_rule_ids(),
                "constraint_family_counts": {
                    "8chem_9bio_equalities": len(constraints),
                },
                "binding_classes": {
                    "chemistry_class": class_8,
                    "biology_class": class_9,
                },
                "assignment_variable_names": {
                    _assignment_key(cls, subj, day, period): name
                    for (cls, subj, day, period), name in assignment_names.items()
                },
            }
        },
    )


def night_physics_math_special_to_ai_or_problem(
    *,
    classes: Sequence[Any],
    cst: Mapping[tuple[Any, Any], Any],
    days: Sequence[Any],
    periods: Sequence[Any],
    rules: Mapping[str, Any],
    rule_id: str = "night.physics_math_special",
) -> SchedulerGenericRuleBridge:
    """Compile the legacy night physics/history/math hard-ban special rule."""
    _ = classes
    cfg = ((rules.get("evening_constraints") if isinstance(rules, Mapping) else {}) or {})
    if cfg.get("enabled", True) is False or cfg.get("enable_physics_math_special", True) is False:
        return _empty_scheduler_rule_bridge(
            "scheduler_night_physics_math_special",
            rule_id,
            "apply_physics_math_hard_bans",
        )

    day_list = _text_tuple(days)
    period_list = _text_tuple(periods)
    cst_entries = tuple((str(cls), str(subj), str(tch)) for (cls, subj), tch in cst.items())
    physics_fri_mode = str(cfg.get("physics_fri_mode", "soft")).lower()
    history_fri_mode = str(cfg.get("history_fri_mode", "soft")).lower()
    physics_sun_exceptions = _teacher_norm_set(cfg.get("physics_sunday_exempt_teachers", []))
    physics_fri_exceptions = _teacher_norm_set(cfg.get("physics_friday_exempt_teachers", []))
    history_fri_exceptions = _teacher_norm_set(cfg.get("history_friday_exempt_teachers", []))
    math_friday_allowed = _teacher_norm_set(cfg.get("math_friday_allowed_teachers", []))

    assignment_names: dict[tuple[str, str, str, str], str] = {}
    variables: list[VariableSpec] = []
    for index, (cls, subj, _teacher, day, period) in enumerate(
        (
            (cls, subj, teacher, day, period)
            for cls, subj, teacher in cst_entries
            for day in day_list
            for period in period_list
        ),
        start=1,
    ):
        name = _night_assignment_var_name(index, cls, subj, day, period)
        assignment_names[(cls, subj, day, period)] = name
        variables.append(VariableSpec.bool(name))

    constraints: list[LinearConstraintSpec] = []
    blocked_assignment_names: list[str] = []
    counts = {
        "physics_sunday": 0,
        "physics_friday_hard": 0,
        "history_sunday": 0,
        "history_friday_hard": 0,
        "math_sunday": 0,
        "math_friday_forbidden": 0,
    }
    constraint_index = 1

    def add_block(cls: str, subj: str, teacher: str, day: str, period: str, family: str) -> None:
        nonlocal constraint_index
        variable_name = assignment_names[(cls, subj, day, period)]
        constraints.append(
            _bool_value_constraint(
                f"physics_math_special__{constraint_index:04d}__{family}__{_safe_identifier(cls)}__{_safe_identifier(subj)}__{_safe_identifier(day)}__{_safe_identifier(period)}",
                variable_name,
                0,
                rule_id,
            )
        )
        blocked_assignment_names.append(variable_name)
        counts[family] += 1
        constraint_index += 1
        _ = teacher

    for cls, subj, teacher in cst_entries:
        subj_norm = _subject_norm(subj)
        teacher_norm = _teacher_norm(teacher)
        for day in day_list:
            for period in period_list:
                if _is_physics_subject(subj_norm) and day == "星期日" and teacher_norm not in physics_sun_exceptions:
                    add_block(cls, subj, teacher, day, period, "physics_sunday")
                if (
                    _is_physics_subject(subj_norm)
                    and day == "星期五"
                    and physics_fri_mode == "hard"
                    and teacher_norm not in physics_fri_exceptions
                ):
                    add_block(cls, subj, teacher, day, period, "physics_friday_hard")
                if _is_history_subject(subj_norm) and day == "星期日":
                    add_block(cls, subj, teacher, day, period, "history_sunday")
                if (
                    _is_history_subject(subj_norm)
                    and day == "星期五"
                    and history_fri_mode == "hard"
                    and teacher_norm not in history_fri_exceptions
                ):
                    add_block(cls, subj, teacher, day, period, "history_friday_hard")
                if _is_math_subject(subj_norm) and day == "星期日":
                    add_block(cls, subj, teacher, day, period, "math_sunday")
                if _is_math_subject(subj_norm) and day == "星期五" and teacher_norm not in math_friday_allowed:
                    add_block(cls, subj, teacher, day, period, "math_friday_forbidden")

    ai_rule = AiRuleSpec(
        rule_id=rule_id,
        description="Night hard special rule: physics/history/math Friday and Sunday bans with teacher exceptions.",
        enforcement="hard",
        priority=5,
        source="scheduler.model.constraints.night_special:apply_physics_math_hard_bans",
    )
    problem = OptimizationProblemSpec(
        problem_id="scheduler_night_physics_math_special",
        variables=tuple(variables),
        rules=(ai_rule,),
        constraints=tuple(constraints),
    )
    rule_first_plan = build_rule_first_plan(
        rules=problem.rules,
        constraints=problem.constraints,
        objective_rule_id=None,
    )
    return SchedulerGenericRuleBridge(
        problem=problem,
        rule_first_plan=rule_first_plan,
        metadata_by_rule={
            rule_id: {
                "scheduler_rule_id": rule_id,
                "legacy_apply_fn": "apply_physics_math_hard_bans",
                "generic_contract_status": "covered_by_generic_contract",
                "runtime_rule_ids": generic_scheduler_rule_ids(),
                "constraint_family_counts": counts,
                "assignment_variable_names": {
                    _assignment_key(cls, subj, day, period): name
                    for (cls, subj, day, period), name in assignment_names.items()
                },
                "blocked_assignment_variable_names": tuple(blocked_assignment_names),
            }
        },
    )


def night_fri_sun_mutex_to_ai_or_problem(
    *,
    classes: Sequence[Any],
    cst: Mapping[tuple[Any, Any], Any],
    days: Sequence[Any],
    periods: Sequence[Any],
    rules: Mapping[str, Any],
    rule_id: str = "night.fri_sun_mutex",
) -> SchedulerGenericRuleBridge:
    """Compile the legacy night Friday/Sunday teacher-day mutex hard rule."""
    _ = (classes, periods)
    cfg = ((rules.get("evening_constraints") if isinstance(rules, Mapping) else {}) or {})
    if cfg.get("enabled", True) is False:
        return _empty_scheduler_rule_bridge("scheduler_night_fri_sun_mutex", rule_id, "apply_fri_sun_mutex")

    day_list = _text_tuple(days)
    teacher_list = tuple(sorted({str(teacher) for teacher in cst.values()}))
    teacher_day_variable_names: dict[tuple[str, str], str] = {}
    variables: list[VariableSpec] = []
    for index, (teacher, day) in enumerate(
        ((teacher, day) for teacher in teacher_list for day in day_list),
        start=1,
    ):
        name = _night_teacher_day_var_name(index, teacher, day)
        teacher_day_variable_names[(teacher, day)] = name
        variables.append(VariableSpec.bool(name))

    constraints: list[LinearConstraintSpec] = []
    counts = {
        "fri_sun_teacher_mutex": 0,
        "configured_friday_pair_mutex": 0,
    }
    fri_sun_mutex_teacher_keys: list[str] = []
    configured_friday_pair: tuple[str, str] | tuple[()] = ()
    constraint_index = 1
    fri_sun_exempt = _teacher_norm_set(cfg.get("fri_sun_mutex_exempt_teachers", []))

    if cfg.get("enable_fri_sun_mutex", False) and str(cfg.get("fri_sun_mutex_mode", "soft")).lower() == "hard":
        if "星期五" in day_list and "星期日" in day_list:
            for teacher in teacher_list:
                if _teacher_norm(teacher) in fri_sun_exempt:
                    continue
                friday_name = teacher_day_variable_names.get((teacher, "星期五"))
                sunday_name = teacher_day_variable_names.get((teacher, "星期日"))
                if friday_name is None or sunday_name is None:
                    continue
                constraints.append(
                    LinearConstraintSpec(
                        name=f"fri_sun_mutex__{constraint_index:04d}__{_safe_identifier(teacher)}",
                        expression=LinearExpression((LinearTerm(friday_name, 1), LinearTerm(sunday_name, 1))),
                        sense="<=",
                        rhs=1,
                        rule_id=rule_id,
                    )
                )
                counts["fri_sun_teacher_mutex"] += 1
                fri_sun_mutex_teacher_keys.append(teacher)
                constraint_index += 1

    if cfg.get("enable_yk_xxc_fri_mutex", True) and str(cfg.get("yk_xxc_fri_mutex_mode", "hard")).lower() == "hard":
        if "星期五" in day_list:
            pair = _teacher_names(cfg.get("yk_xxc_fri_mutex_teachers", []))
            if len(pair) >= 2:
                left = _find_teacher_key_by_norm(teacher_list, pair[0])
                right = _find_teacher_key_by_norm(teacher_list, pair[1])
                if left and right:
                    left_name = teacher_day_variable_names.get((left, "星期五"))
                    right_name = teacher_day_variable_names.get((right, "星期五"))
                    if left_name is not None and right_name is not None:
                        constraints.append(
                            LinearConstraintSpec(
                                name=f"configured_friday_pair_mutex__{constraint_index:04d}__{_safe_identifier(left)}__{_safe_identifier(right)}",
                                expression=LinearExpression((LinearTerm(left_name, 1), LinearTerm(right_name, 1))),
                                sense="<=",
                                rhs=1,
                                rule_id=rule_id,
                            )
                        )
                        counts["configured_friday_pair_mutex"] += 1
                        configured_friday_pair = (left, right)
                        constraint_index += 1

    ai_rule = AiRuleSpec(
        rule_id=rule_id,
        description="Night hard rule: teacher Friday/Sunday mutex and configured Friday pair mutex.",
        enforcement="hard",
        priority=6,
        source="scheduler.model.constraints.night_special:apply_fri_sun_mutex",
    )
    problem = OptimizationProblemSpec(
        problem_id="scheduler_night_fri_sun_mutex",
        variables=tuple(variables),
        rules=(ai_rule,),
        constraints=tuple(constraints),
    )
    rule_first_plan = build_rule_first_plan(
        rules=problem.rules,
        constraints=problem.constraints,
        objective_rule_id=None,
    )
    return SchedulerGenericRuleBridge(
        problem=problem,
        rule_first_plan=rule_first_plan,
        metadata_by_rule={
            rule_id: {
                "scheduler_rule_id": rule_id,
                "legacy_apply_fn": "apply_fri_sun_mutex",
                "generic_contract_status": "covered_by_generic_contract",
                "runtime_rule_ids": generic_scheduler_rule_ids(),
                "constraint_family_counts": counts,
                "teacher_day_variable_names": {
                    _teacher_day_key(teacher, day): name
                    for (teacher, day), name in teacher_day_variable_names.items()
                },
                "fri_sun_mutex_teacher_keys": tuple(fri_sun_mutex_teacher_keys),
                "configured_friday_pair": configured_friday_pair,
            }
        },
    )


def night_single_class_p1_p2_split_to_ai_or_problem(
    *,
    classes: Sequence[Any],
    cst: Mapping[tuple[Any, Any], Any],
    days: Sequence[Any],
    periods: Sequence[Any],
    rules: Mapping[str, Any],
    rule_id: str = "night.single_class_p1_p2_split",
) -> SchedulerGenericRuleBridge:
    """Compile the legacy night single-class-teacher P1/P2 split hard rule."""
    _ = classes
    cfg = ((rules.get("evening_constraints") if isinstance(rules, Mapping) else {}) or {})
    if cfg.get("enable_single_class_p1_p2_split", True) is False:
        return _empty_scheduler_rule_bridge(
            "scheduler_night_single_class_p1_p2_split",
            rule_id,
            "apply_single_class_teacher_p1_p2_split",
        )

    day_list = _text_tuple(days)
    period_list = _text_tuple(periods)
    cst_entries = tuple((str(cls), str(subj), str(tch)) for (cls, subj), tch in cst.items())
    weekly_k = int(((rules.get("evening") if isinstance(rules, Mapping) else {}) or {}).get(
        "weekly_occurrences_per_subject",
        2,
    ))

    assignment_names: dict[tuple[str, str, str, str], str] = {}
    variables: list[VariableSpec] = []
    for index, (cls, subj, _teacher, day, period) in enumerate(
        (
            (cls, subj, teacher, day, period)
            for cls, subj, teacher in cst_entries
            for day in day_list
            for period in period_list
        ),
        start=1,
    ):
        name = _night_assignment_var_name(index, cls, subj, day, period)
        assignment_names[(cls, subj, day, period)] = name
        variables.append(VariableSpec.bool(name))

    teacher_classes: dict[str, set[str]] = {}
    for cls, _subj, teacher in cst_entries:
        teacher_classes.setdefault(teacher, set()).add(cls)

    constraints: list[LinearConstraintSpec] = []
    counts = {
        "single_class_teacher_period_p1_exactly_one": 0,
        "single_class_teacher_period_p2_exactly_one": 0,
    }
    single_class_teacher_keys: set[str] = set()
    double_or_multi_class_teacher_keys: set[str] = set()

    if weekly_k == 2 and len(period_list) == 2:
        p1, p2 = period_list[0], period_list[1]
        constraint_index = 1
        for cls, subj, teacher in cst_entries:
            if len(teacher_classes.get(teacher, set())) != 1:
                double_or_multi_class_teacher_keys.add(teacher)
                continue
            single_class_teacher_keys.add(teacher)
            constraints.append(
                LinearConstraintSpec(
                    name=f"single_class_p1_p2_split__{constraint_index:04d}__p1__{_safe_identifier(cls)}__{_safe_identifier(subj)}",
                    expression=_sum_expr(assignment_names[(cls, subj, day, p1)] for day in day_list),
                    sense="==",
                    rhs=1,
                    rule_id=rule_id,
                )
            )
            counts["single_class_teacher_period_p1_exactly_one"] += 1
            constraint_index += 1
            constraints.append(
                LinearConstraintSpec(
                    name=f"single_class_p1_p2_split__{constraint_index:04d}__p2__{_safe_identifier(cls)}__{_safe_identifier(subj)}",
                    expression=_sum_expr(assignment_names[(cls, subj, day, p2)] for day in day_list),
                    sense="==",
                    rhs=1,
                    rule_id=rule_id,
                )
            )
            counts["single_class_teacher_period_p2_exactly_one"] += 1
            constraint_index += 1

    ai_rule = AiRuleSpec(
        rule_id=rule_id,
        description="Night hard rule: single-class teachers must split two weekly evening assignments across P1 and P2.",
        enforcement="hard",
        priority=7,
        source="scheduler.model.constraints.night_single_class_period_split:apply_single_class_teacher_p1_p2_split",
    )
    problem = OptimizationProblemSpec(
        problem_id="scheduler_night_single_class_p1_p2_split",
        variables=tuple(variables),
        rules=(ai_rule,),
        constraints=tuple(constraints),
    )
    rule_first_plan = build_rule_first_plan(
        rules=problem.rules,
        constraints=problem.constraints,
        objective_rule_id=None,
    )
    return SchedulerGenericRuleBridge(
        problem=problem,
        rule_first_plan=rule_first_plan,
        metadata_by_rule={
            rule_id: {
                "scheduler_rule_id": rule_id,
                "legacy_apply_fn": "apply_single_class_teacher_p1_p2_split",
                "generic_contract_status": "covered_by_generic_contract",
                "runtime_rule_ids": generic_scheduler_rule_ids(),
                "constraint_family_counts": counts,
                "assignment_variable_names": {
                    _assignment_key(cls, subj, day, period): name
                    for (cls, subj, day, period), name in assignment_names.items()
                },
                "single_class_teacher_keys": tuple(sorted(single_class_teacher_keys)),
                "double_or_multi_class_teacher_keys": tuple(sorted(double_or_multi_class_teacher_keys)),
            }
        },
    )


def night_double_class_weekday_p1_p2_split_to_ai_or_problem(
    *,
    classes: Sequence[Any],
    cst: Mapping[tuple[Any, Any], Any],
    days: Sequence[Any],
    periods: Sequence[Any],
    rules: Mapping[str, Any],
    rule_id: str = "night.double_class_weekday_p1_p2_split",
) -> SchedulerGenericRuleBridge:
    """Compile the legacy night double-class weekday/Sunday triggered P1/P2 split rule."""
    _ = classes
    cfg = ((rules.get("evening_constraints") if isinstance(rules, Mapping) else {}) or {})
    if cfg.get("enable_double_class_weekday_p1_p2_split", True) is False:
        return _empty_scheduler_rule_bridge(
            "scheduler_night_double_class_weekday_p1_p2_split",
            rule_id,
            "apply_double_class_teacher_weekday_alternate_p1_p2",
        )
    if str(cfg.get("double_class_weekday_p1_p2_mode", "hard")).lower() != "hard":
        return _empty_scheduler_rule_bridge(
            "scheduler_night_double_class_weekday_p1_p2_split",
            rule_id,
            "apply_double_class_teacher_weekday_alternate_p1_p2",
        )

    day_list = _text_tuple(days)
    period_list = _text_tuple(periods)
    cst_entries = tuple((str(cls), str(subj), str(tch)) for (cls, subj), tch in cst.items())
    weekly_k = int(((rules.get("evening") if isinstance(rules, Mapping) else {}) or {}).get(
        "weekly_occurrences_per_subject",
        2,
    ))
    split_days = tuple(day for day in day_list if day in WEEKDAY_DAYS or day == "星期日")

    assignment_names: dict[tuple[str, str, str, str], str] = {}
    variables: list[VariableSpec] = []
    for index, (cls, subj, _teacher, day, period) in enumerate(
        (
            (cls, subj, teacher, day, period)
            for cls, subj, teacher in cst_entries
            for day in day_list
            for period in period_list
        ),
        start=1,
    ):
        name = _night_assignment_var_name(index, cls, subj, day, period)
        assignment_names[(cls, subj, day, period)] = name
        variables.append(VariableSpec.bool(name))

    teacher_classes: dict[str, set[str]] = {}
    for cls, _subj, teacher in cst_entries:
        teacher_classes.setdefault(teacher, set()).add(cls)

    constraints: list[Any] = []
    counts = {
        "double_class_split_total_link": 0,
        "double_class_split_total_map_domain": 0,
        "double_class_period_p1_exactly_one_if_split_two": 0,
        "double_class_period_p2_exactly_one_if_split_two": 0,
    }
    double_class_teacher_keys: set[str] = set()
    ignored_teacher_keys: set[str] = set()
    split_total_variable_names: dict[str, str] = {}
    trigger_variable_names: dict[str, str] = {}

    if weekly_k == 2 and len(period_list) == 2 and split_days:
        p1, p2 = period_list[0], period_list[1]
        max_split_total = len(split_days) * len(period_list)
        constraint_index = 1
        extra_var_index = 1
        for cls, subj, teacher in cst_entries:
            key = _assignment_key(cls, subj, "", "").rstrip("|")
            if len(teacher_classes.get(teacher, set())) != 2:
                ignored_teacher_keys.add(teacher)
                continue
            double_class_teacher_keys.add(teacher)

            total_name = "__".join(
                (
                    "double_class_split_total",
                    f"{extra_var_index:04d}",
                    _safe_identifier(cls),
                    _safe_identifier(subj),
                )
            )
            split_total_variable_names[key] = total_name
            variables.append(VariableSpec(total_name, 0, max_split_total))
            extra_var_index += 1

            value_bool_names: list[str] = []
            for value in range(max_split_total + 1):
                value_bool_name = "__".join(
                    (
                        "double_class_split_total_is",
                        f"{extra_var_index:04d}",
                        str(value),
                        _safe_identifier(cls),
                        _safe_identifier(subj),
                    )
                )
                value_bool_names.append(value_bool_name)
                variables.append(VariableSpec.bool(value_bool_name))
                extra_var_index += 1

            split_two_name = value_bool_names[2]
            trigger_variable_names[key] = split_two_name
            constraints.append(
                LinearConstraintSpec(
                    name=f"double_class_p1_p2_split__{constraint_index:04d}__split_total_link__{_safe_identifier(cls)}__{_safe_identifier(subj)}",
                    expression=LinearExpression(
                        (
                            *(
                                LinearTerm(assignment_names[(cls, subj, day, period)], 1)
                                for day in split_days
                                for period in period_list
                            ),
                            LinearTerm(total_name, -1),
                        )
                    ),
                    sense="==",
                    rhs=0,
                    rule_id=rule_id,
                )
            )
            counts["double_class_split_total_link"] += 1
            constraint_index += 1
            constraints.append(
                MapDomainConstraintSpec(
                    name=f"double_class_p1_p2_split__{constraint_index:04d}__split_total_map_domain__{_safe_identifier(cls)}__{_safe_identifier(subj)}",
                    variable=total_name,
                    bool_variables=tuple(value_bool_names),
                    offset=0,
                    rule_id=rule_id,
                )
            )
            counts["double_class_split_total_map_domain"] += 1
            constraint_index += 1
            constraints.append(
                LinearConstraintSpec(
                    name=f"double_class_p1_p2_split__{constraint_index:04d}__p1_if_split_two__{_safe_identifier(cls)}__{_safe_identifier(subj)}",
                    expression=_sum_expr(assignment_names[(cls, subj, day, p1)] for day in split_days),
                    sense="==",
                    rhs=1,
                    rule_id=rule_id,
                    enforcement_literals=(split_two_name,),
                )
            )
            counts["double_class_period_p1_exactly_one_if_split_two"] += 1
            constraint_index += 1
            constraints.append(
                LinearConstraintSpec(
                    name=f"double_class_p1_p2_split__{constraint_index:04d}__p2_if_split_two__{_safe_identifier(cls)}__{_safe_identifier(subj)}",
                    expression=_sum_expr(assignment_names[(cls, subj, day, p2)] for day in split_days),
                    sense="==",
                    rhs=1,
                    rule_id=rule_id,
                    enforcement_literals=(split_two_name,),
                )
            )
            counts["double_class_period_p2_exactly_one_if_split_two"] += 1
            constraint_index += 1

    ai_rule = AiRuleSpec(
        rule_id=rule_id,
        description="Night hard rule: double-class teachers split P1/P2 when weekday/Sunday assignments total two.",
        enforcement="hard",
        priority=8,
        source="scheduler.model.constraints.night_single_class_period_split:apply_double_class_teacher_weekday_alternate_p1_p2",
    )
    problem = OptimizationProblemSpec(
        problem_id="scheduler_night_double_class_weekday_p1_p2_split",
        variables=tuple(variables),
        rules=(ai_rule,),
        constraints=tuple(constraints),
    )
    rule_first_plan = build_rule_first_plan(
        rules=problem.rules,
        constraints=problem.constraints,
        objective_rule_id=None,
    )
    return SchedulerGenericRuleBridge(
        problem=problem,
        rule_first_plan=rule_first_plan,
        metadata_by_rule={
            rule_id: {
                "scheduler_rule_id": rule_id,
                "legacy_apply_fn": "apply_double_class_teacher_weekday_alternate_p1_p2",
                "generic_contract_status": "covered_by_generic_contract",
                "runtime_rule_ids": generic_scheduler_rule_ids(),
                "constraint_family_counts": counts,
                "split_days": split_days,
                "assignment_variable_names": {
                    _assignment_key(cls, subj, day, period): name
                    for (cls, subj, day, period), name in assignment_names.items()
                },
                "split_total_variable_names": split_total_variable_names,
                "trigger_variable_names": trigger_variable_names,
                "double_class_teacher_keys": tuple(sorted(double_class_teacher_keys)),
                "ignored_teacher_keys": tuple(sorted(ignored_teacher_keys)),
            }
        },
    )


def night_checkin_to_ai_or_problem(
    *,
    male_heads: Sequence[Any],
    female_heads: Sequence[Any],
    days: Sequence[Any],
    rules: Mapping[str, Any],
    rule_id: str = "night.checkin",
) -> SchedulerGenericRuleBridge:
    """Compile the legacy night checkin hard staffing/same-day-class rule."""
    cfg = ((rules.get("checkin") if isinstance(rules, Mapping) else {}) or {})
    if not cfg.get("enabled", False):
        return _empty_scheduler_rule_bridge("scheduler_night_checkin", rule_id, "apply_checkin")

    male_list = _text_tuple(male_heads)
    female_list = _text_tuple(female_heads)
    day_list = _text_tuple(days)
    male_need = int(((cfg.get("per_day") if isinstance(cfg.get("per_day"), Mapping) else {}) or {}).get("male", 1))
    female_need = int(((cfg.get("per_day") if isinstance(cfg.get("per_day"), Mapping) else {}) or {}).get("female", 1))
    per_teacher_max = int(cfg.get("per_teacher_max_times", 1))
    same_day_class_mode = _checkin_same_day_class_mode(cfg)
    require_on_hard = same_day_class_mode == "hard"
    exclude_heads = {str(item).strip() for item in (cfg.get("exclude_heads", []) or []) if str(item).strip()}
    extra_head_allowed_days = _checkin_extra_head_allowed_days(cfg, day_list)
    require_class_teacher_norms = _teacher_norm_set(
        _teacher_names(cfg.get("require_class_teacher_names", cfg.get("zeng_checkin_teacher_name", [])))
    )
    enable_zeng_rule = bool(cfg.get("enable_zeng_checkin_require_class_that_day", True))

    variables: list[VariableSpec] = []
    checkin_m_variable_names: dict[tuple[str, str], str] = {}
    checkin_f_variable_names: dict[tuple[str, str], str] = {}
    on_teacher_day_variable_names: dict[tuple[str, str], str] = {}
    var_index = 1
    for teacher in male_list:
        for day in day_list:
            name = _checkin_var_name("checkin_m", var_index, teacher, day)
            checkin_m_variable_names[(teacher, day)] = name
            variables.append(VariableSpec.bool(name))
            var_index += 1
    for teacher in female_list:
        for day in day_list:
            name = _checkin_var_name("checkin_f", var_index, teacher, day)
            checkin_f_variable_names[(teacher, day)] = name
            variables.append(VariableSpec.bool(name))
            var_index += 1
    for teacher in tuple(dict.fromkeys((*male_list, *female_list))):
        for day in day_list:
            name = _checkin_var_name("on_teacher_day", var_index, teacher, day)
            on_teacher_day_variable_names[(teacher, day)] = name
            variables.append(VariableSpec.bool(name))
            var_index += 1

    constraints: list[LinearConstraintSpec] = []
    counts = {
        "same_day_on_coverage_male": 0,
        "same_day_on_coverage_female": 0,
        "excluded_male_checkin_zero": 0,
        "excluded_female_checkin_zero": 0,
        "extra_head_allowed_day_zero_male": 0,
        "extra_head_allowed_day_zero_female": 0,
        "daily_staffing_male": 0,
        "daily_staffing_female": 0,
        "weekly_max_male": 0,
        "weekly_max_female": 0,
        "same_day_class_male_hard": 0,
        "same_day_class_female_hard": 0,
    }
    constraint_index = 1

    def add_constraint(name: str, expression: LinearExpression, sense: str, rhs: int, family: str) -> None:
        nonlocal constraint_index
        constraints.append(
            LinearConstraintSpec(
                name=f"night_checkin__{constraint_index:04d}__{name}",
                expression=expression,
                sense=sense,
                rhs=rhs,
                rule_id=rule_id,
            )
        )
        counts[family] += 1
        constraint_index += 1

    if require_on_hard:
        for day in day_list:
            add_constraint(
                f"same_day_on_coverage_male__{_safe_identifier(day)}",
                _sum_expr(on_teacher_day_variable_names[(teacher, day)] for teacher in male_list),
                ">=",
                male_need,
                "same_day_on_coverage_male",
            )
            add_constraint(
                f"same_day_on_coverage_female__{_safe_identifier(day)}",
                _sum_expr(on_teacher_day_variable_names[(teacher, day)] for teacher in female_list),
                ">=",
                female_need,
                "same_day_on_coverage_female",
            )

    for day in day_list:
        for teacher in male_list:
            if teacher in exclude_heads:
                add_constraint(
                    f"excluded_male_zero__{_safe_identifier(teacher)}__{_safe_identifier(day)}",
                    _sum_expr((checkin_m_variable_names[(teacher, day)],)),
                    "==",
                    0,
                    "excluded_male_checkin_zero",
                )
        for teacher in female_list:
            if teacher in exclude_heads:
                add_constraint(
                    f"excluded_female_zero__{_safe_identifier(teacher)}__{_safe_identifier(day)}",
                    _sum_expr((checkin_f_variable_names[(teacher, day)],)),
                    "==",
                    0,
                    "excluded_female_checkin_zero",
                )

    for (teacher, gender), allowed_days in extra_head_allowed_days.items():
        if gender == "男":
            for day in day_list:
                if day not in allowed_days and (teacher, day) in checkin_m_variable_names:
                    add_constraint(
                        f"extra_male_day_zero__{_safe_identifier(teacher)}__{_safe_identifier(day)}",
                        _sum_expr((checkin_m_variable_names[(teacher, day)],)),
                        "==",
                        0,
                        "extra_head_allowed_day_zero_male",
                    )
        if gender == "女":
            for day in day_list:
                if day not in allowed_days and (teacher, day) in checkin_f_variable_names:
                    add_constraint(
                        f"extra_female_day_zero__{_safe_identifier(teacher)}__{_safe_identifier(day)}",
                        _sum_expr((checkin_f_variable_names[(teacher, day)],)),
                        "==",
                        0,
                        "extra_head_allowed_day_zero_female",
                    )

    for day in day_list:
        add_constraint(
            f"daily_staffing_male__{_safe_identifier(day)}",
            _sum_expr(checkin_m_variable_names[(teacher, day)] for teacher in male_list),
            "==",
            male_need,
            "daily_staffing_male",
        )
        add_constraint(
            f"daily_staffing_female__{_safe_identifier(day)}",
            _sum_expr(checkin_f_variable_names[(teacher, day)] for teacher in female_list),
            "==",
            female_need,
            "daily_staffing_female",
        )

    for teacher in male_list:
        add_constraint(
            f"weekly_max_male__{_safe_identifier(teacher)}",
            _sum_expr(checkin_m_variable_names[(teacher, day)] for day in day_list),
            "<=",
            per_teacher_max,
            "weekly_max_male",
        )
    for teacher in female_list:
        add_constraint(
            f"weekly_max_female__{_safe_identifier(teacher)}",
            _sum_expr(checkin_f_variable_names[(teacher, day)] for day in day_list),
            "<=",
            per_teacher_max,
            "weekly_max_female",
        )

    if require_on_hard:
        for teacher in male_list:
            if enable_zeng_rule and _teacher_norm(teacher) in require_class_teacher_norms:
                continue
            for day in day_list:
                add_constraint(
                    f"same_day_class_male_hard__{_safe_identifier(teacher)}__{_safe_identifier(day)}",
                    LinearExpression(
                        (
                            LinearTerm(checkin_m_variable_names[(teacher, day)], 1),
                            LinearTerm(on_teacher_day_variable_names[(teacher, day)], -1),
                        )
                    ),
                    "<=",
                    0,
                    "same_day_class_male_hard",
                )
        for teacher in female_list:
            if enable_zeng_rule and _teacher_norm(teacher) in require_class_teacher_norms:
                continue
            for day in day_list:
                add_constraint(
                    f"same_day_class_female_hard__{_safe_identifier(teacher)}__{_safe_identifier(day)}",
                    LinearExpression(
                        (
                            LinearTerm(checkin_f_variable_names[(teacher, day)], 1),
                            LinearTerm(on_teacher_day_variable_names[(teacher, day)], -1),
                        )
                    ),
                    "<=",
                    0,
                    "same_day_class_female_hard",
                )

    ai_rule = AiRuleSpec(
        rule_id=rule_id,
        description="Night hard rule: checkin staffing, exclusions, weekly caps, and same-day evening-class linkage.",
        enforcement="hard",
        priority=9,
        source="scheduler.model.constraints.checkin:apply_checkin",
    )
    problem = OptimizationProblemSpec(
        problem_id="scheduler_night_checkin",
        variables=tuple(variables),
        rules=(ai_rule,),
        constraints=tuple(constraints),
    )
    rule_first_plan = build_rule_first_plan(
        rules=problem.rules,
        constraints=problem.constraints,
        objective_rule_id=None,
    )
    return SchedulerGenericRuleBridge(
        problem=problem,
        rule_first_plan=rule_first_plan,
        metadata_by_rule={
            rule_id: {
                "scheduler_rule_id": rule_id,
                "legacy_apply_fn": "apply_checkin",
                "generic_contract_status": "covered_by_generic_contract",
                "runtime_rule_ids": generic_scheduler_rule_ids(),
                "constraint_family_counts": counts,
                "excluded_heads": tuple(sorted(exclude_heads)),
                "extra_head_allowed_days": {
                    _teacher_day_key(teacher, gender): tuple(sorted(allowed_days))
                    for (teacher, gender), allowed_days in extra_head_allowed_days.items()
                },
                "checkin_m_variable_names": {
                    _teacher_day_key(teacher, day): name for (teacher, day), name in checkin_m_variable_names.items()
                },
                "checkin_f_variable_names": {
                    _teacher_day_key(teacher, day): name for (teacher, day), name in checkin_f_variable_names.items()
                },
                "on_teacher_day_variable_names": {
                    _teacher_day_key(teacher, day): name for (teacher, day), name in on_teacher_day_variable_names.items()
                },
            }
        },
    )


def scheduler_execution_plan_to_ai_or_problem(plan: RuleExecutionPlan) -> SchedulerGenericRuleBridge:
    """Lift the scheduler audit plan into the generic rule-first contract.

    This bridge is deliberately a shadow model: each enabled scheduler rule is
    represented by an activation variable and a traceable hard constraint. It
    lets the scheduler example participate in the generic AI OR workflow before
    the legacy solver call sites are fully migrated.
    """
    selected_items = tuple(item for item in plan.items if item.enabled)
    rules = tuple(_to_ai_rule(plan, item) for item in selected_items)
    variables = tuple(VariableSpec.bool(_activation_var_name(plan, item)) for item in selected_items)
    constraints = tuple(
        LinearConstraintSpec(
            name=f"activate__{_generic_rule_id(plan, item)}",
            expression=LinearExpression((LinearTerm(_activation_var_name(plan, item), 1),)),
            sense="==",
            rhs=1,
            rule_id=_generic_rule_id(plan, item),
        )
        for item in selected_items
    )
    objective = _objective_for_enabled_rules(plan, selected_items)
    problem = OptimizationProblemSpec(
        problem_id=f"scheduler_rule_execution_plan:{plan.profile_id}:{plan.mode}",
        variables=variables,
        rules=rules,
        constraints=constraints,
        objective=objective,
    )
    rule_first_plan = build_rule_first_plan(
        rules=problem.rules,
        constraints=problem.constraints,
        objective_rule_id=objective.rule_id if objective is not None else None,
    )
    return SchedulerGenericRuleBridge(
        problem=problem,
        rule_first_plan=rule_first_plan,
        metadata_by_rule={_generic_rule_id(plan, item): _metadata(plan, item) for item in selected_items},
    )


def personalized_legacy_catalog_to_ai_or_problem(
    effective_cfg: Mapping[str, Any] | None,
    *,
    include_disabled: bool = True,
) -> SchedulerGenericRuleBridge:
    """Compile legacy personalized rule metadata into a generic rule-first catalog.

    This is a migration contract, not a claim that every legacy personalized
    branch has been shape-matched to CP-SAT operations. It makes each legacy
    personalized template a first-class OptimizationProblemSpec rule so AI
    agents can reason about enablement, targets, modes and weights before the
    remaining call-site-specific solver migration.
    """
    cfg = _mapping_value((effective_cfg or {}).get("personalized_constraints"))
    target_cfg = _mapping_value(cfg.get("teacher_targets"))
    target_slots = {slot.slot_id: slot for slot in PERSONALIZED_TARGET_SLOTS}
    legacy_by_template = {personalized_template_id(rule.rule_key): rule for rule in PERSONALIZED_LEGACY_RULES}

    rules: list[AiRuleSpec] = []
    variables: list[VariableSpec] = []
    constraints: list[ConstraintSpec] = []
    metadata_by_rule: dict[str, dict[str, Any]] = {}

    for index, template_id in enumerate(PERSONALIZED_RULE_INSTANCE_TEMPLATE_IDS, start=1):
        legacy_rule = legacy_by_template.get(template_id)
        if legacy_rule is None:
            metadata = _personalized_collection_metadata(template_id, cfg)
            order = 200 + index
        else:
            metadata = _personalized_legacy_rule_metadata(legacy_rule, cfg, target_cfg, target_slots)
            order = 500 + index

        enabled = bool(metadata["enabled"])
        if not include_disabled and not enabled:
            continue

        mode = str(metadata["mode"]).strip().lower()
        variable_name = _personalized_catalog_var_name(template_id)
        variables.append(VariableSpec.bool(variable_name))
        constraints.append(
            _bool_value_constraint(
                f"personalized_catalog_state__{index:04d}__{_safe_identifier(template_id)}",
                variable_name,
                1 if enabled else 0,
                template_id,
            )
        )
        rules.append(
            AiRuleSpec(
                rule_id=template_id,
                description=str(metadata["title"]),
                enforcement="soft" if mode == "soft" else "hard",
                priority=order,
                source="scheduler.rules.personalized_legacy",
            )
        )
        metadata_by_rule[template_id] = {
            **metadata,
            "scheduler_rule_id": template_id,
            "legacy_apply_fn": "apply_personalized_constraints",
            "legacy_contract_scope": "personalized_registry_and_config_catalog",
            "generic_contract_status": "covered_by_generic_contract",
            "solver_effect": "shadow_catalog_not_constraint_shape",
            "can_block_solver": False,
            "state_variable_name": variable_name,
            "constraint_family_counts": {"personalized_catalog_state_constraints": 1},
            "runtime_rule_ids": generic_scheduler_rule_ids(),
        }

    problem = OptimizationProblemSpec(
        problem_id="scheduler_personalized_legacy_catalog",
        variables=tuple(variables),
        rules=tuple(rules),
        constraints=tuple(constraints),
    )
    rule_first_plan = build_rule_first_plan(
        rules=problem.rules,
        constraints=problem.constraints,
        objective_rule_id=None,
    )
    return SchedulerGenericRuleBridge(
        problem=problem,
        rule_first_plan=rule_first_plan,
        metadata_by_rule=metadata_by_rule,
    )


def day_special_duty_catalog_to_ai_or_problem(
    effective_cfg: Mapping[str, Any] | None,
) -> SchedulerGenericRuleBridge:
    """Compile head-duty and noon-dorm legacy switches into a rule-first catalog."""
    cfg = _mapping_value(effective_cfg or {})
    day_cfg = _mapping_value(cfg.get("day"))
    head_cfg = _mapping_value(day_cfg.get("head_duty_constraints"))
    noon_cfg = _mapping_value(day_cfg.get("noon_dorm_duty"))
    entries = (
        {
            "rule_id": "joint.day.head_duty_constraints",
            "title": "班主任下午课前值班约束",
            "legacy_apply_fn": "apply_head_duty_constraints",
            "config_path": "day.head_duty_constraints",
            "enabled": _config_bool(head_cfg.get("enable_head_duty"), True),
            "mode": _personalized_mode(head_cfg.get("weekday_pm1_requires_duty_mode"), "hard"),
            "weight": head_cfg.get("w_weekday_pm1_requires_duty"),
        },
        {
            "rule_id": "joint.day.noon_dorm_duty_constraints",
            "title": "中午查寝值班约束",
            "legacy_apply_fn": "apply_noon_dorm_duty_constraints",
            "config_path": "day.noon_dorm_duty",
            "enabled": _config_bool(noon_cfg.get("enabled"), True),
            "mode": _personalized_mode(noon_cfg.get("lhj_noon_ban_mode"), "hard"),
            "weight": noon_cfg.get("w_noon_with_pm1"),
        },
    )

    rules: list[AiRuleSpec] = []
    variables: list[VariableSpec] = []
    constraints: list[ConstraintSpec] = []
    metadata_by_rule: dict[str, dict[str, Any]] = {}
    for index, entry in enumerate(entries, start=1):
        rule_id = str(entry["rule_id"])
        enabled = bool(entry["enabled"])
        mode = str(entry["mode"]).strip().lower()
        variable_name = f"day_special_duty_catalog_active__{_safe_identifier(rule_id)}"
        variables.append(VariableSpec.bool(variable_name))
        constraints.append(
            _bool_value_constraint(
                f"day_special_duty_catalog_state__{index:04d}__{_safe_identifier(rule_id)}",
                variable_name,
                1 if enabled else 0,
                rule_id,
            )
        )
        rules.append(
            AiRuleSpec(
                rule_id=rule_id,
                description=str(entry["title"]),
                enforcement="soft" if mode == "soft" else "hard",
                priority=400 + index,
                source="scheduler.model.constraints.day_head_teacher_duty_constraints",
            )
        )
        metadata_by_rule[rule_id] = {
            "scheduler_rule_id": rule_id,
            "template_kind": "legacy_day_special_duty_rule",
            "title": str(entry["title"]),
            "enabled": enabled,
            "mode": mode,
            "weight": entry["weight"],
            "config_path": str(entry["config_path"]),
            "legacy_apply_fn": str(entry["legacy_apply_fn"]),
            "legacy_contract_scope": "day_special_duty_registry_and_config_catalog",
            "generic_contract_status": "covered_by_generic_contract",
            "solver_effect": "shadow_catalog_not_constraint_shape",
            "can_block_solver": False,
            "state_variable_name": variable_name,
            "constraint_family_counts": {"day_special_duty_catalog_state_constraints": 1},
            "runtime_rule_ids": generic_scheduler_rule_ids(),
        }

    problem = OptimizationProblemSpec(
        problem_id="scheduler_day_special_duty_catalog",
        variables=tuple(variables),
        rules=tuple(rules),
        constraints=tuple(constraints),
    )
    rule_first_plan = build_rule_first_plan(
        rules=problem.rules,
        constraints=problem.constraints,
        objective_rule_id=None,
    )
    return SchedulerGenericRuleBridge(
        problem=problem,
        rule_first_plan=rule_first_plan,
        metadata_by_rule=metadata_by_rule,
    )


def _to_ai_rule(plan: RuleExecutionPlan, item: RulePlanItem) -> AiRuleSpec:
    return AiRuleSpec(
        rule_id=_generic_rule_id(plan, item),
        description=f"{item.name} ({item.category_path})",
        enforcement=_enforcement(item),
        priority=_priority(item),
        source=f"scheduler.rule_execution_plan:{plan.mode}:{item.rule_id}",
    )


def _objective_for_enabled_rules(plan: RuleExecutionPlan, items: tuple[RulePlanItem, ...]) -> ObjectiveSpec | None:
    if not items:
        return None
    objective_item = next(
        (
            item
            for item in items
            if _enforcement(item) == "soft" and str(item.stage) == "objective_post"
        ),
        next((item for item in items if _enforcement(item) == "soft"), items[-1]),
    )
    return ObjectiveSpec(
        rule_id=_generic_rule_id(plan, objective_item),
        sense="maximize",
        expression=LinearExpression(tuple(LinearTerm(_activation_var_name(plan, item), 1) for item in items)),
    )


def _metadata(plan: RuleExecutionPlan, item: RulePlanItem) -> dict[str, Any]:
    return {
        "scheduler_rule_id": item.rule_id,
        "scheduler_mode": plan.mode,
        "profile_id": plan.profile_id,
        "name": item.name,
        "category_path": item.category_path,
        "stage": item.stage,
        "enabled": item.enabled,
        "mode": item.mode,
        "weight": item.weight,
        "config_key": item.config_key,
        "apply_fn_name": item.apply_fn_name,
        "instance_ids": tuple(item.instance_ids),
        "instance_target_scopes": tuple(item.instance_target_scopes),
    }


def _generic_rule_id(plan: RuleExecutionPlan, item: RulePlanItem) -> str:
    return _safe_identifier(f"scheduler__{plan.mode}__{item.rule_id}")


def _activation_var_name(plan: RuleExecutionPlan, item: RulePlanItem) -> str:
    return f"active__{_generic_rule_id(plan, item)}"


def _enforcement(item: RulePlanItem) -> str:
    return "soft" if str(item.mode or "").strip().lower() == "soft" else "hard"


def _priority(item: RulePlanItem) -> int:
    tier = 100_000 if _enforcement(item) == "soft" else 0
    return tier + int(item.order)


def _personalized_collection_metadata(template_id: str, cfg: Mapping[str, Any]) -> dict[str, Any]:
    collection_titles = {
        "shared.personalized_constraints": "个性化约束集合",
        "day.personalized_constraints": "白天个性化约束集合",
        "night.personalized_constraints": "晚自习个性化约束集合",
        "joint.link.personalized_constraints": "联动个性化约束集合",
    }
    return {
        "template_kind": "collection",
        "title": collection_titles.get(template_id, template_id),
        "enabled": _config_bool(cfg.get("enabled"), True),
        "mode": "hard",
        "weight": None,
        "target_slots": tuple(),
        "targets": tuple(),
        "missing_target_slots": tuple(),
        "target_status": "collection",
    }


def _personalized_legacy_rule_metadata(
    rule: Any,
    cfg: Mapping[str, Any],
    target_cfg: Mapping[str, Any],
    target_slots: Mapping[str, Any],
) -> dict[str, Any]:
    slot_values = {
        slot_id: _personalized_target_values(slot_id, cfg, target_cfg, target_slots)
        for slot_id in tuple(rule.target_slots)
    }
    missing = tuple(slot_id for slot_id, values in slot_values.items() if not values)
    targets = tuple(value for values in slot_values.values() for value in values)
    mode = _personalized_mode(cfg.get(rule.mode_key) if rule.mode_key else None, "hard")
    return {
        "template_kind": "legacy_personalized_rule",
        "title": str(rule.title),
        "rule_key": str(rule.rule_key),
        "enabled": _config_bool(cfg.get(rule.rule_key), False),
        "mode": mode,
        "weight": cfg.get(rule.weight_key) if rule.weight_key else None,
        "target_slots": tuple(rule.target_slots),
        "targets": targets,
        "missing_target_slots": missing,
        "target_status": "configured" if not missing else "missing_required_targets",
        "mode_path": f"personalized_constraints.{rule.mode_key}" if rule.mode_key else None,
        "weight_path": f"personalized_constraints.{rule.weight_key}" if rule.weight_key else None,
    }


def _personalized_target_values(
    slot_id: str,
    cfg: Mapping[str, Any],
    target_cfg: Mapping[str, Any],
    target_slots: Mapping[str, Any],
) -> tuple[str, ...]:
    slot = target_slots.get(slot_id)
    if slot is not None and str(slot.config_path).startswith("personalized_constraints.teacher_targets."):
        raw = target_cfg.get(slot_id)
    else:
        raw = cfg.get(slot_id)
    return tuple(_teacher_names(raw))


def _personalized_mode(value: Any, default: str) -> str:
    mode = str(value or default).strip().lower()
    return mode if mode in {"hard", "soft"} else default


def _config_bool(value: Any, default: bool) -> bool:
    if value is None:
        return bool(default)
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return bool(value)


def _mapping_value(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _personalized_catalog_var_name(rule_id: str) -> str:
    return f"personalized_catalog_active__{_safe_identifier(rule_id)}"


def _text_tuple(values: Sequence[Any]) -> tuple[str, ...]:
    return tuple(str(value) for value in values)


def _find_class_by_marker(classes: Sequence[str], marker: str) -> str | None:
    return next((cls for cls in classes if marker in str(cls)), None)


def _teacher_norm(value: Any) -> str:
    return "".join(str(value).split())


def _teacher_norm_set(values: Any) -> set[str]:
    if values is None:
        return set()
    if isinstance(values, str):
        raw_values = tuple(part.strip() for part in values.replace("，", ",").replace("、", ",").split(","))
    else:
        try:
            raw_values = tuple(values)
        except TypeError:
            raw_values = (values,)
    return {_teacher_norm(value) for value in raw_values if str(value).strip()}


def _teacher_names(values: Any) -> list[str]:
    if values is None:
        return []
    if isinstance(values, str):
        return [part.strip() for part in values.replace("，", ",").replace("、", ",").split(",") if part.strip()]
    try:
        raw_values = tuple(values)
    except TypeError:
        text = str(values).strip()
        return [text] if text else []
    out: list[str] = []
    for value in raw_values:
        out.extend(_teacher_names(value))
    return out


def _find_teacher_key_by_norm(teachers: Sequence[str], target: Any) -> str | None:
    target_norm = _teacher_norm(target)
    return next((teacher for teacher in teachers if _teacher_norm(teacher) == target_norm), None)


def _checkin_same_day_class_mode(cfg: Mapping[str, Any]) -> str:
    raw_mode = cfg.get("require_teacher_has_class_that_day_mode")
    if raw_mode is not None:
        mode = str(raw_mode or "").strip().lower()
        if mode in {"hard", "soft", "off"}:
            return mode
    return "hard" if bool(cfg.get("require_teacher_has_class_that_day", True)) else "off"


def _checkin_extra_head_allowed_days(cfg: Mapping[str, Any], days: Sequence[str]) -> dict[tuple[str, str], set[str]]:
    out: dict[tuple[str, str], set[str]] = {}
    valid_days = {str(day).strip() for day in days}
    for item in cfg.get("extra_heads", []) or []:
        if not isinstance(item, Mapping):
            continue
        name = str(item.get("name") or "").strip()
        gender = str(item.get("gender") or "").strip()
        if not name or gender not in {"男", "女"}:
            continue
        scoped_days = _coerce_day_set(item.get("days", item.get("day", item.get("available_days"))))
        scoped_days = {day for day in scoped_days if day in valid_days}
        if scoped_days:
            out[(name, gender)] = scoped_days
    return out


def _coerce_day_set(value: Any) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, (list, tuple, set)):
        raw_values = value
    else:
        raw_values = str(value).replace("，", ",").replace("、", ",").replace("/", ",").split(",")
    return {str(day).strip() for day in raw_values if str(day).strip()}


def _subject_norm(value: Any) -> str:
    return str(value).strip()


def _is_physics_subject(value: str) -> bool:
    return _subject_norm(value) == "物理"


def _is_history_subject(value: str) -> bool:
    return _subject_norm(value) == "历史"


def _is_math_subject(value: str) -> bool:
    return _subject_norm(value) == "数学"


def _sum_expr(variable_names: Iterable[str]) -> LinearExpression:
    return LinearExpression(tuple(LinearTerm(str(name), 1) for name in variable_names))


def _weekday_subject_daily_limit_to_ai_or_problem(
    data: Any,
    *,
    threshold: int,
    threshold_direction: str,
    sense: str,
    rhs: int,
    rule_id: str,
    problem_id: str,
    legacy_apply_fn: str,
    priority: int,
    source: str,
    description: str,
    constraint_family_name: str,
) -> SchedulerGenericRuleBridge:
    assignments = _day_candidate_assignment_names(data)
    variables = tuple(VariableSpec.bool(name) for (_cls, _subj, _slot, name) in assignments)
    assignment_names: dict[str, str] = {}
    names_by_class_subject_day: dict[tuple[str, str, str], list[str]] = {}
    for cls, subj, slot, name in assignments:
        assignment_names[_assignment_key(cls, subj, str(slot.day), _slot_label(slot))] = name
        if str(slot.day) not in WEEKDAY_DAYS or not _is_daytime(slot):
            continue
        names_by_class_subject_day.setdefault((cls, subj, str(slot.day)), []).append(name)

    target_pairs: list[tuple[str, str]] = []
    for raw_key, req in getattr(data, "req_hours", {}).items():
        if req is None:
            continue
        cls, subj = (str(raw_key[0]), str(raw_key[1]))
        _early, weekday_hours, _weekend = req
        weekday_hours_int = int(weekday_hours)
        if threshold_direction == "low" and weekday_hours_int > threshold:
            continue
        if threshold_direction == "high" and weekday_hours_int < threshold:
            continue
        target_pairs.append((cls, subj))
    target_pairs = sorted(set(target_pairs))

    fixed_counts_by_class_subject_day: dict[tuple[str, str, str], int] = {}
    for (cls, slot), subj in (getattr(data, "fixed_assign", {}) or {}).items():
        day = str(slot.day)
        if day not in WEEKDAY_DAYS or not _is_daytime(slot):
            continue
        key = (str(cls), str(subj), day)
        fixed_counts_by_class_subject_day[key] = fixed_counts_by_class_subject_day.get(key, 0) + 1

    constraints: list[LinearConstraintSpec] = []
    constraint_index = 1
    for cls, subj in target_pairs:
        for day in WEEKDAY_DAYS:
            day_text = str(day)
            raw_key = (cls, subj, day_text)
            var_names = tuple(sorted(names_by_class_subject_day.get(raw_key, ())))
            fixed_count = int(fixed_counts_by_class_subject_day.get(raw_key, 0))
            constraints.append(
                LinearConstraintSpec(
                    name=f"{_safe_identifier(rule_id)}__{constraint_index:04d}__{_safe_identifier(cls)}__{_safe_identifier(subj)}__{_safe_identifier(day_text)}",
                    expression=LinearExpression(
                        tuple(LinearTerm(name, 1) for name in var_names),
                        constant=fixed_count,
                    ),
                    sense=sense,
                    rhs=int(rhs),
                    rule_id=rule_id,
                )
            )
            constraint_index += 1

    ai_rule = AiRuleSpec(
        rule_id=rule_id,
        description=description,
        enforcement="hard",
        priority=int(priority),
        source=source,
    )
    problem = OptimizationProblemSpec(
        problem_id=problem_id,
        variables=variables,
        rules=(ai_rule,),
        constraints=tuple(constraints),
    )
    rule_first_plan = build_rule_first_plan(
        rules=problem.rules,
        constraints=problem.constraints,
        objective_rule_id=None,
    )
    return SchedulerGenericRuleBridge(
        problem=problem,
        rule_first_plan=rule_first_plan,
        metadata_by_rule={
            rule_id: {
                "scheduler_rule_id": rule_id,
                "legacy_apply_fn": legacy_apply_fn,
                "generic_contract_status": "covered_by_generic_contract",
                "runtime_rule_ids": generic_scheduler_rule_ids(),
                "constraint_family_counts": {constraint_family_name: len(constraints)},
                "assignment_variable_names": assignment_names,
                "target_class_subjects": tuple(_class_subject_key(cls, subj) for cls, subj in target_pairs),
                "class_subject_day_assignment_variable_names": {
                    _class_subject_day_key(cls, subj, day): tuple(sorted(names))
                    for (cls, subj, day), names in sorted(names_by_class_subject_day.items())
                    if (cls, subj) in target_pairs
                },
                "fixed_count_constants": {
                    _class_subject_day_key(cls, subj, day): int(count)
                    for (cls, subj, day), count in sorted(fixed_counts_by_class_subject_day.items())
                    if (cls, subj) in target_pairs
                },
                "threshold": threshold,
                "threshold_direction": threshold_direction,
                "sense": sense,
                "rhs": int(rhs),
            }
        },
    )


def day_teacher_continuity_penalty_to_ai_or_problem(
    data: Any,
    *,
    pe_teachers: Iterable[Any] = (),
    weight: int = 1,
    rule_id: str = "joint.day.teacher_continuity_penalty",
) -> SchedulerGenericRuleBridge:
    """Compile non-PE teacher halfday 1-0-1/adjacent continuity penalties into OptimizationProblemSpec."""
    excluded_teachers = set(_teacher_names(pe_teachers))
    assignments = _day_candidate_assignment_names(data)
    assignment_variables = tuple(VariableSpec.bool(name) for (_cls, _subj, _slot, name) in assignments)
    assignment_names: dict[str, str] = {}
    names_by_teacher_day_slot: dict[tuple[str, str, Any], list[str]] = {}
    for cls, subj, slot, name in assignments:
        assignment_names[_assignment_key(cls, subj, str(slot.day), _slot_label(slot))] = name
        if not is_weekday_day(str(slot.day)) or is_pe_or_tech_subject(str(subj)):
            continue
        teacher = str(getattr(data, "cls_subj_teacher", {}).get((cls, subj), "")).strip()
        if not teacher or teacher in excluded_teachers:
            continue
        names_by_teacher_day_slot.setdefault((teacher, str(slot.day), slot), []).append(name)

    target_teachers = tuple(sorted({teacher for teacher, _day, _slot in names_by_teacher_day_slot}))
    variables: list[VariableSpec] = list(assignment_variables)
    constraints: list[LinearConstraintSpec] = []
    objective_terms: list[LinearTerm] = []
    busy_variable_names: dict[str, str] = {}
    busy_by_raw_key: dict[tuple[str, str, Any], str] = {}
    gap_variable_names: dict[str, str] = {}
    counts = {
        "teacher_continuity_busy_equalities": 0,
        "teacher_continuity_101_gap_constraints": 0,
        "teacher_continuity_adjacent_gap_constraints": 0,
        "teacher_continuity_gap_penalty_terms": 0,
    }
    constraint_index = 1
    variable_index = 1

    raw_busy_keys = tuple(
        sorted(
            names_by_teacher_day_slot,
            key=lambda item: (item[0], WEEKDAY_DAYS.index(item[1]), _slot_order_key(item[2])),
        )
    )
    for raw_key in raw_busy_keys:
        teacher, day, slot = raw_key
        busy_key = _teacher_day_period_key(teacher, day, _slot_label(slot))
        busy_name = _teacher_continuity_busy_bool_name(variable_index, teacher, day, slot)
        variable_index += 1
        busy_variable_names[busy_key] = busy_name
        busy_by_raw_key[raw_key] = busy_name
        variables.append(VariableSpec.bool(busy_name))
        assignment_var_names = tuple(sorted(names_by_teacher_day_slot[raw_key]))
        constraints.append(
            LinearConstraintSpec(
                name=f"day_teacher_continuity__busy__{constraint_index:04d}__{_safe_identifier(busy_key)}",
                expression=LinearExpression(
                    (
                        *(LinearTerm(name, 1) for name in assignment_var_names),
                        LinearTerm(busy_name, -1),
                    )
                ),
                sense="==",
                rhs=0,
                rule_id=rule_id,
            )
        )
        counts["teacher_continuity_busy_equalities"] += 1
        constraint_index += 1

    slots_by_teacher_day: dict[tuple[str, str], list[Any]] = {}
    for teacher, day, slot in raw_busy_keys:
        slots_by_teacher_day.setdefault((teacher, day), []).append(slot)

    def build_gap_constraints(teacher: str, day: str, half_slots: tuple[Any, ...], tag: str) -> None:
        nonlocal constraint_index, variable_index
        if not half_slots:
            return
        busy_names = tuple(busy_by_raw_key[(teacher, day, slot)] for slot in half_slots)
        if len(busy_names) >= 3:
            for index in range(len(busy_names) - 2):
                b1, b2, b3 = busy_names[index], busy_names[index + 1], busy_names[index + 2]
                gap_key = f"{teacher}|{day}|{tag}|{index}"
                gap_name = _teacher_continuity_gap_bool_name(variable_index, teacher, day, tag, index)
                variable_index += 1
                gap_variable_names[gap_key] = gap_name
                variables.append(VariableSpec.bool(gap_name))
                for suffix, terms, sense, rhs in (
                    ("upper_left", (LinearTerm(gap_name, 1), LinearTerm(b1, -1)), "<=", 0),
                    ("upper_right", (LinearTerm(gap_name, 1), LinearTerm(b3, -1)), "<=", 0),
                    ("upper_middle_empty", (LinearTerm(gap_name, 1), LinearTerm(b2, 1)), "<=", 1),
                    (
                        "lower_101",
                        (
                            LinearTerm(gap_name, 1),
                            LinearTerm(b1, -1),
                            LinearTerm(b3, -1),
                            LinearTerm(b2, 1),
                        ),
                        ">=",
                        -1,
                    ),
                ):
                    constraints.append(
                        LinearConstraintSpec(
                            name=f"day_teacher_continuity__gap_{suffix}__{constraint_index:04d}__{_safe_identifier(gap_name)}",
                            expression=LinearExpression(tuple(terms)),
                            sense=sense,
                            rhs=rhs,
                            rule_id=rule_id,
                        )
                    )
                    counts["teacher_continuity_101_gap_constraints"] += 1
                    constraint_index += 1
                objective_terms.append(LinearTerm(gap_name, int(weight)))
                counts["teacher_continuity_gap_penalty_terms"] += 1
            return
        for index in range(len(busy_names) - 1):
            b1, b2 = busy_names[index], busy_names[index + 1]
            gap_key = f"{teacher}|{day}|{tag}|{index}"
            gap_name = _teacher_continuity_gap_bool_name(variable_index, teacher, day, tag, index)
            variable_index += 1
            gap_variable_names[gap_key] = gap_name
            variables.append(VariableSpec.bool(gap_name))
            for suffix, terms, sense, rhs in (
                ("adj_upper_left", (LinearTerm(gap_name, 1), LinearTerm(b1, -1)), "<=", 0),
                ("adj_upper_right_empty", (LinearTerm(gap_name, 1), LinearTerm(b2, 1)), "<=", 1),
                ("adj_lower", (LinearTerm(gap_name, 1), LinearTerm(b1, -1), LinearTerm(b2, 1)), ">=", 0),
            ):
                constraints.append(
                    LinearConstraintSpec(
                        name=f"day_teacher_continuity__gap_{suffix}__{constraint_index:04d}__{_safe_identifier(gap_name)}",
                        expression=LinearExpression(tuple(terms)),
                        sense=sense,
                        rhs=rhs,
                        rule_id=rule_id,
                    )
                )
                counts["teacher_continuity_adjacent_gap_constraints"] += 1
                constraint_index += 1
            objective_terms.append(LinearTerm(gap_name, int(weight)))
            counts["teacher_continuity_gap_penalty_terms"] += 1

    for teacher in target_teachers:
        for day in WEEKDAY_DAYS:
            slots = tuple(sorted(slots_by_teacher_day.get((teacher, str(day)), ()), key=_slot_order_key))
            if not slots:
                continue
            build_gap_constraints(teacher, str(day), tuple(slot for slot in slots if _is_am(slot)), "AM")
            build_gap_constraints(teacher, str(day), tuple(slot for slot in slots if _is_pm(slot)), "PM")

    objective = ObjectiveSpec(
        rule_id=rule_id,
        sense="minimize",
        expression=LinearExpression(tuple(objective_terms)),
    )
    ai_rule = AiRuleSpec(
        rule_id=rule_id,
        description="Day soft rule: penalize non-PE/tech teacher halfday gaps and adjacent fragmentation.",
        enforcement="soft",
        priority=35,
        source="scheduler.model.constraints.day_weekday_constraints:apply_teacher_continuity_penalty",
    )
    problem = OptimizationProblemSpec(
        problem_id="scheduler_day_teacher_continuity_penalty",
        variables=tuple(variables),
        rules=(ai_rule,),
        constraints=tuple(constraints),
        objective=objective,
    )
    rule_first_plan = build_rule_first_plan(
        rules=problem.rules,
        constraints=problem.constraints,
        objective_rule_id=objective.rule_id,
    )
    return SchedulerGenericRuleBridge(
        problem=problem,
        rule_first_plan=rule_first_plan,
        metadata_by_rule={
            rule_id: {
                "scheduler_rule_id": rule_id,
                "legacy_apply_fn": "apply_teacher_continuity_penalty",
                "generic_contract_status": "covered_by_generic_contract",
                "runtime_rule_ids": generic_scheduler_rule_ids(),
                "constraint_family_counts": counts,
                "assignment_variable_names": assignment_names,
                "constrained_teachers": target_teachers,
                "teacher_day_slot_assignment_variable_names": {
                    _teacher_day_period_key(teacher, day, _slot_label(slot)): tuple(sorted(names))
                    for (teacher, day, slot), names in sorted(
                        names_by_teacher_day_slot.items(),
                        key=lambda item: (item[0][0], WEEKDAY_DAYS.index(item[0][1]), _slot_order_key(item[0][2])),
                    )
                },
                "busy_variable_names": busy_variable_names,
                "gap_variable_names": gap_variable_names,
                "pe_teachers": tuple(sorted(excluded_teachers)),
                "weight": int(weight),
            }
        },
    )


def day_two_class_daily_min_per_class_to_ai_or_problem(
    data: Any,
    *,
    pe_teachers: Iterable[Any] = (),
    mode: str = "soft",
    w_soft: int = 300,
    rule_id: str = "joint.day.two_class_daily_min_per_class",
) -> SchedulerGenericRuleBridge:
    """Compile two-class teacher same-day per-class minimum rules into OptimizationProblemSpec."""
    mode_norm = str(mode or "soft").strip().lower()
    if mode_norm not in {"hard", "soft"}:
        raise ValueError(f"unsupported two-class daily minimum mode {mode!r}")

    excluded_teachers = set(_teacher_names(pe_teachers))
    teacher_classes: dict[str, set[str]] = {}
    for (cls, subj), teacher in getattr(data, "cls_subj_teacher", {}).items():
        if is_pe_or_tech_subject(str(subj)):
            continue
        teacher_text = str(teacher).strip()
        if not teacher_text:
            continue
        teacher_classes.setdefault(teacher_text, set()).add(str(cls))
    target_teacher_classes = {
        teacher: tuple(sorted(classes))
        for teacher, classes in sorted(teacher_classes.items())
        if teacher not in excluded_teachers and len(classes) == 2
    }

    assignments = _day_candidate_assignment_names(data)
    assignment_variables = tuple(VariableSpec.bool(name) for (_cls, _subj, _slot, name) in assignments)
    assignment_names: dict[str, str] = {}
    names_by_teacher_day_class: dict[tuple[str, str, str], list[str]] = {}
    for cls, subj, slot, name in assignments:
        assignment_names[_assignment_key(cls, subj, str(slot.day), _slot_label(slot))] = name
        day = str(slot.day)
        if day not in WEEKDAY_DAYS:
            continue
        teacher = str(getattr(data, "cls_subj_teacher", {}).get((cls, subj), "")).strip()
        if teacher not in target_teacher_classes:
            continue
        names_by_teacher_day_class.setdefault((teacher, day, cls), []).append(name)

    variables: list[VariableSpec] = list(assignment_variables)
    constraints: list[LinearConstraintSpec] = []
    objective_terms: list[LinearTerm] = []
    has_any_variable_names: dict[str, str] = {}
    has_class_variable_names: dict[str, str] = {}
    violation_variable_names: dict[str, str] = {}
    counts = {
        "two_class_daily_min_class_presence_constraints": 0,
        "two_class_daily_min_any_presence_constraints": 0,
    }
    if mode_norm == "hard":
        counts["two_class_daily_min_hard_class_requirements"] = 0
    else:
        counts["two_class_daily_min_violation_constraints"] = 0
        counts["two_class_daily_min_penalty_terms"] = 0
    constraint_index = 1
    variable_index = 1

    for teacher, classes in target_teacher_classes.items():
        for day in WEEKDAY_DAYS:
            day_text = str(day)
            teacher_day_key = _teacher_day_key(teacher, day_text)
            has_any_name = _two_class_daily_min_bool_name(variable_index, "any", teacher, day_text)
            variable_index += 1
            variables.append(VariableSpec.bool(has_any_name))
            has_any_variable_names[teacher_day_key] = has_any_name
            any_var_names: list[str] = []

            for cls in classes:
                class_key = _teacher_class_day_key(teacher, cls, day_text)
                has_cls_name = _two_class_daily_min_bool_name(variable_index, "has_class", teacher, day_text, cls)
                variable_index += 1
                variables.append(VariableSpec.bool(has_cls_name))
                has_class_variable_names[class_key] = has_cls_name
                class_var_names = tuple(sorted(names_by_teacher_day_class.get((teacher, day_text, cls), ())))
                if class_var_names:
                    constraints.append(
                        LinearConstraintSpec(
                            name=f"day_two_class_daily_min__class_lower__{constraint_index:04d}__{_safe_identifier(class_key)}",
                            expression=LinearExpression(
                                (
                                    *(LinearTerm(name, 1) for name in class_var_names),
                                    LinearTerm(has_cls_name, -1),
                                )
                            ),
                            sense=">=",
                            rhs=0,
                            rule_id=rule_id,
                        )
                    )
                    counts["two_class_daily_min_class_presence_constraints"] += 1
                    constraint_index += 1
                    for name in class_var_names:
                        constraints.append(
                            LinearConstraintSpec(
                                name=f"day_two_class_daily_min__class_upper__{constraint_index:04d}__{_safe_identifier(has_cls_name)}",
                                expression=LinearExpression((LinearTerm(name, 1), LinearTerm(has_cls_name, -1))),
                                sense="<=",
                                rhs=0,
                                rule_id=rule_id,
                            )
                        )
                        counts["two_class_daily_min_class_presence_constraints"] += 1
                        constraint_index += 1
                    any_var_names.extend(class_var_names)
                else:
                    constraints.append(
                        LinearConstraintSpec(
                            name=f"day_two_class_daily_min__class_zero__{constraint_index:04d}__{_safe_identifier(class_key)}",
                            expression=LinearExpression((LinearTerm(has_cls_name, 1),)),
                            sense="==",
                            rhs=0,
                            rule_id=rule_id,
                        )
                    )
                    counts["two_class_daily_min_class_presence_constraints"] += 1
                    constraint_index += 1

                if mode_norm == "hard":
                    constraints.append(
                        LinearConstraintSpec(
                            name=f"day_two_class_daily_min__hard__{constraint_index:04d}__{_safe_identifier(class_key)}",
                            expression=LinearExpression((LinearTerm(has_cls_name, 1), LinearTerm(has_any_name, -1))),
                            sense=">=",
                            rhs=0,
                            rule_id=rule_id,
                        )
                    )
                    counts["two_class_daily_min_hard_class_requirements"] += 1
                    constraint_index += 1
                    continue

                violation_name = _two_class_daily_min_bool_name(variable_index, "vio", teacher, day_text, cls)
                variable_index += 1
                variables.append(VariableSpec.bool(violation_name))
                violation_variable_names[class_key] = violation_name
                for suffix, terms, sense, rhs in (
                    ("upper_any", (LinearTerm(violation_name, 1), LinearTerm(has_any_name, -1)), "<=", 0),
                    ("upper_missing_class", (LinearTerm(violation_name, 1), LinearTerm(has_cls_name, 1)), "<=", 1),
                    (
                        "lower",
                        (LinearTerm(violation_name, 1), LinearTerm(has_any_name, -1), LinearTerm(has_cls_name, 1)),
                        ">=",
                        0,
                    ),
                ):
                    constraints.append(
                        LinearConstraintSpec(
                            name=f"day_two_class_daily_min__{suffix}__{constraint_index:04d}__{_safe_identifier(violation_name)}",
                            expression=LinearExpression(tuple(terms)),
                            sense=sense,
                            rhs=rhs,
                            rule_id=rule_id,
                        )
                    )
                    counts["two_class_daily_min_violation_constraints"] += 1
                    constraint_index += 1
                objective_terms.append(LinearTerm(violation_name, int(w_soft)))
                counts["two_class_daily_min_penalty_terms"] += 1

            if any_var_names:
                sorted_any_var_names = tuple(sorted(any_var_names))
                constraints.append(
                    LinearConstraintSpec(
                        name=f"day_two_class_daily_min__any_lower__{constraint_index:04d}__{_safe_identifier(teacher_day_key)}",
                        expression=LinearExpression(
                            (
                                *(LinearTerm(name, 1) for name in sorted_any_var_names),
                                LinearTerm(has_any_name, -1),
                            )
                        ),
                        sense=">=",
                        rhs=0,
                        rule_id=rule_id,
                    )
                )
                counts["two_class_daily_min_any_presence_constraints"] += 1
                constraint_index += 1
                for name in sorted_any_var_names:
                    constraints.append(
                        LinearConstraintSpec(
                            name=f"day_two_class_daily_min__any_upper__{constraint_index:04d}__{_safe_identifier(has_any_name)}",
                            expression=LinearExpression((LinearTerm(name, 1), LinearTerm(has_any_name, -1))),
                            sense="<=",
                            rhs=0,
                            rule_id=rule_id,
                        )
                    )
                    counts["two_class_daily_min_any_presence_constraints"] += 1
                    constraint_index += 1
            else:
                constraints.append(
                    LinearConstraintSpec(
                        name=f"day_two_class_daily_min__any_zero__{constraint_index:04d}__{_safe_identifier(teacher_day_key)}",
                        expression=LinearExpression((LinearTerm(has_any_name, 1),)),
                        sense="==",
                        rhs=0,
                        rule_id=rule_id,
                    )
                )
                counts["two_class_daily_min_any_presence_constraints"] += 1
                constraint_index += 1

    objective = None
    if mode_norm == "soft":
        objective = ObjectiveSpec(
            rule_id=rule_id,
            sense="minimize",
            expression=LinearExpression(tuple(objective_terms)),
        )
    ai_rule = AiRuleSpec(
        rule_id=rule_id,
        description="Day rule: if a two-class teacher teaches that day, each class should receive at least one lesson.",
        enforcement=mode_norm,
        priority=34,
        source="scheduler.model.constraints.day_weekday_constraints:apply_two_class_daily_min_per_class",
    )
    problem = OptimizationProblemSpec(
        problem_id="scheduler_day_two_class_daily_min_per_class",
        variables=tuple(variables),
        rules=(ai_rule,),
        constraints=tuple(constraints),
        objective=objective,
    )
    rule_first_plan = build_rule_first_plan(
        rules=problem.rules,
        constraints=problem.constraints,
        objective_rule_id=objective.rule_id if objective is not None else None,
    )
    return SchedulerGenericRuleBridge(
        problem=problem,
        rule_first_plan=rule_first_plan,
        metadata_by_rule={
            rule_id: {
                "scheduler_rule_id": rule_id,
                "legacy_apply_fn": "apply_two_class_daily_min_per_class",
                "generic_contract_status": "covered_by_generic_contract",
                "runtime_rule_ids": generic_scheduler_rule_ids(),
                "constraint_family_counts": counts,
                "assignment_variable_names": assignment_names,
                "constrained_teachers": tuple(target_teacher_classes),
                "teacher_classes": target_teacher_classes,
                "teacher_day_class_assignment_variable_names": {
                    _teacher_class_day_key(teacher, cls, day): tuple(sorted(names))
                    for (teacher, day, cls), names in sorted(names_by_teacher_day_class.items())
                },
                "has_any_variable_names": has_any_variable_names,
                "has_class_variable_names": has_class_variable_names,
                "violation_variable_names": violation_variable_names,
                "mode": mode_norm,
                "w_soft": int(w_soft),
                "pe_teachers": tuple(sorted(excluded_teachers)),
            }
        },
    )


def day_teacher_m1_cap_constraint_to_ai_or_problem(
    data: Any,
    *,
    max_m1: int = 3,
    weight: int = 1,
    am1_penalty_exempt_teacher_days: Iterable[tuple[Any, Any]] | None = None,
    rule_id: str = "joint.day.teacher_m1_cap_constraint",
) -> SchedulerGenericRuleBridge:
    """Compile teacher weekday AM1 cap and hit-cap penalty into OptimizationProblemSpec."""
    max_m1_int = max(0, int(max_m1))
    exempt_teacher_days = {
        (str(teacher).strip(), str(day).strip())
        for teacher, day in (am1_penalty_exempt_teacher_days or ())
        if str(teacher).strip() and str(day).strip()
    }
    assignments = _day_candidate_assignment_names(data)
    assignment_variables = tuple(VariableSpec.bool(name) for (_cls, _subj, _slot, name) in assignments)
    assignment_names: dict[str, str] = {}
    names_by_teacher_day: dict[tuple[str, str], list[str]] = {}
    for cls, subj, slot, name in assignments:
        assignment_names[_assignment_key(cls, subj, str(slot.day), _slot_label(slot))] = name
        day = str(slot.day)
        if day not in WEEKDAY_DAYS or not _is_am1(slot):
            continue
        teacher = str(getattr(data, "cls_subj_teacher", {}).get((cls, subj), "")).strip()
        if not teacher:
            continue
        names_by_teacher_day.setdefault((teacher, day), []).append(name)

    fixed_by_teacher_day: dict[tuple[str, str], int] = {}
    fixed_total_by_teacher: dict[str, int] = {}
    for (cls, slot), subj in (getattr(data, "fixed_assign", {}) or {}).items():
        day = str(slot.day)
        if day not in WEEKDAY_DAYS or not _is_am1(slot):
            continue
        teacher = str(getattr(data, "cls_subj_teacher", {}).get((cls, subj), "")).strip()
        if not teacher:
            continue
        fixed_by_teacher_day[(teacher, day)] = fixed_by_teacher_day.get((teacher, day), 0) + 1
        fixed_total_by_teacher[teacher] = fixed_total_by_teacher.get(teacher, 0) + 1

    teachers = tuple(
        sorted(
            {
                str(teacher).strip()
                for teacher in getattr(data, "cls_subj_teacher", {}).values()
                if str(teacher).strip()
            }
        )
    )
    variables: list[VariableSpec] = list(assignment_variables)
    constraints: list[LinearConstraintSpec] = []
    objective_terms: list[LinearTerm] = []
    occ_variable_names: dict[str, str] = {}
    m1_total_variable_names: dict[str, str] = {}
    hit_cap_variable_names: dict[str, str] = {}
    penalty_total_variable_names: dict[str, str] = {}
    counts = {
        "teacher_m1_day_occurrence_constraints": 0,
        "teacher_m1_weekly_total_constraints": 0,
        "teacher_m1_penalty_total_constraints": 0,
        "teacher_m1_hit_cap_penalty_terms": 0,
    }
    constraint_index = 1
    variable_index = 1

    for teacher in teachers:
        occ_names_by_day: dict[str, str] = {}
        for day in WEEKDAY_DAYS:
            day_text = str(day)
            teacher_day_key = _teacher_day_key(teacher, day_text)
            occ_name = _teacher_m1_occ_bool_name(variable_index, teacher, day_text)
            variable_index += 1
            variables.append(VariableSpec.bool(occ_name))
            occ_variable_names[teacher_day_key] = occ_name
            occ_names_by_day[day_text] = occ_name
            fixed_count = fixed_by_teacher_day.get((teacher, day_text), 0)
            var_names = tuple(sorted(names_by_teacher_day.get((teacher, day_text), ())))
            if fixed_count > 0:
                constraints.append(
                    LinearConstraintSpec(
                        name=f"day_teacher_m1_cap__occ_fixed__{constraint_index:04d}__{_safe_identifier(teacher_day_key)}",
                        expression=LinearExpression((LinearTerm(occ_name, 1),)),
                        sense="==",
                        rhs=1,
                        rule_id=rule_id,
                    )
                )
                counts["teacher_m1_day_occurrence_constraints"] += 1
                constraint_index += 1
                continue
            if var_names:
                for name in var_names:
                    constraints.append(
                        LinearConstraintSpec(
                            name=f"day_teacher_m1_cap__occ_lower__{constraint_index:04d}__{_safe_identifier(name)}",
                            expression=LinearExpression((LinearTerm(name, 1), LinearTerm(occ_name, -1))),
                            sense="<=",
                            rhs=0,
                            rule_id=rule_id,
                        )
                    )
                    counts["teacher_m1_day_occurrence_constraints"] += 1
                    constraint_index += 1
                constraints.append(
                    LinearConstraintSpec(
                        name=f"day_teacher_m1_cap__occ_upper__{constraint_index:04d}__{_safe_identifier(teacher_day_key)}",
                        expression=LinearExpression(
                            (
                                LinearTerm(occ_name, 1),
                                *(LinearTerm(name, -1) for name in var_names),
                            )
                        ),
                        sense="<=",
                        rhs=0,
                        rule_id=rule_id,
                    )
                )
                counts["teacher_m1_day_occurrence_constraints"] += 1
                constraint_index += 1
                continue
            constraints.append(
                LinearConstraintSpec(
                    name=f"day_teacher_m1_cap__occ_zero__{constraint_index:04d}__{_safe_identifier(teacher_day_key)}",
                    expression=LinearExpression((LinearTerm(occ_name, 1),)),
                    sense="==",
                    rhs=0,
                    rule_id=rule_id,
                )
            )
            counts["teacher_m1_day_occurrence_constraints"] += 1
            constraint_index += 1

        m1_total_name = _teacher_m1_total_var_name(variable_index, teacher)
        variable_index += 1
        variables.append(VariableSpec(m1_total_name, 0, len(WEEKDAY_DAYS)))
        m1_total_variable_names[teacher] = m1_total_name
        ordered_occ_names = tuple(occ_names_by_day[str(day)] for day in WEEKDAY_DAYS)
        constraints.append(
            LinearConstraintSpec(
                name=f"day_teacher_m1_cap__weekly_total_eq__{constraint_index:04d}__{_safe_identifier(teacher)}",
                expression=LinearExpression(
                    (
                        LinearTerm(m1_total_name, 1),
                        *(LinearTerm(name, -1) for name in ordered_occ_names),
                    )
                ),
                sense="==",
                rhs=0,
                rule_id=rule_id,
            )
        )
        counts["teacher_m1_weekly_total_constraints"] += 1
        constraint_index += 1
        constraints.append(
            LinearConstraintSpec(
                name=f"day_teacher_m1_cap__weekly_total_cap__{constraint_index:04d}__{_safe_identifier(teacher)}",
                expression=LinearExpression((LinearTerm(m1_total_name, 1),)),
                sense="<=",
                rhs=max_m1_int,
                rule_id=rule_id,
            )
        )
        counts["teacher_m1_weekly_total_constraints"] += 1
        constraint_index += 1

        hit_name = _teacher_m1_hit_bool_name(variable_index, teacher)
        variable_index += 1
        variables.append(VariableSpec.bool(hit_name))
        hit_cap_variable_names[teacher] = hit_name
        penalty_days = tuple(str(day) for day in WEEKDAY_DAYS if (teacher, str(day)) not in exempt_teacher_days)
        if penalty_days:
            penalty_total_name = _teacher_m1_penalty_total_var_name(variable_index, teacher)
            variable_index += 1
            variables.append(VariableSpec(penalty_total_name, 0, len(penalty_days)))
            penalty_total_variable_names[teacher] = penalty_total_name
            constraints.append(
                LinearConstraintSpec(
                    name=f"day_teacher_m1_cap__penalty_total_eq__{constraint_index:04d}__{_safe_identifier(teacher)}",
                    expression=LinearExpression(
                        (
                            LinearTerm(penalty_total_name, 1),
                            *(LinearTerm(occ_names_by_day[day], -1) for day in penalty_days),
                        )
                    ),
                    sense="==",
                    rhs=0,
                    rule_id=rule_id,
                )
            )
            counts["teacher_m1_penalty_total_constraints"] += 1
            constraint_index += 1
            constraints.append(
                LinearConstraintSpec(
                    name=f"day_teacher_m1_cap__hit_lower__{constraint_index:04d}__{_safe_identifier(teacher)}",
                    expression=LinearExpression((LinearTerm(hit_name, max_m1_int), LinearTerm(penalty_total_name, -1))),
                    sense="<=",
                    rhs=0,
                    rule_id=rule_id,
                )
            )
            counts["teacher_m1_penalty_total_constraints"] += 1
            constraint_index += 1
            constraints.append(
                LinearConstraintSpec(
                    name=f"day_teacher_m1_cap__hit_upper__{constraint_index:04d}__{_safe_identifier(teacher)}",
                    expression=LinearExpression((LinearTerm(penalty_total_name, 1), LinearTerm(hit_name, -1))),
                    sense="<=",
                    rhs=max_m1_int - 1,
                    rule_id=rule_id,
                )
            )
            counts["teacher_m1_penalty_total_constraints"] += 1
            constraint_index += 1
        else:
            constraints.append(
                LinearConstraintSpec(
                    name=f"day_teacher_m1_cap__hit_zero__{constraint_index:04d}__{_safe_identifier(teacher)}",
                    expression=LinearExpression((LinearTerm(hit_name, 1),)),
                    sense="==",
                    rhs=0,
                    rule_id=rule_id,
                )
            )
            counts["teacher_m1_penalty_total_constraints"] += 1
            constraint_index += 1
        objective_terms.append(LinearTerm(hit_name, int(weight)))
        counts["teacher_m1_hit_cap_penalty_terms"] += 1

    structural_impossible = {
        teacher: fixed_total
        for teacher, fixed_total in sorted(fixed_total_by_teacher.items())
        if int(fixed_total) > max_m1_int
    }
    objective = ObjectiveSpec(
        rule_id=rule_id,
        sense="minimize",
        expression=LinearExpression(tuple(objective_terms)),
    )
    ai_rule = AiRuleSpec(
        rule_id=rule_id,
        description="Day soft rule: cap weekday AM1 occurrences per teacher and penalize hitting the cap.",
        enforcement="soft",
        priority=36,
        source="scheduler.model.constraints.day_weekday_constraints:apply_teacher_m1_cap_constraint",
    )
    problem = OptimizationProblemSpec(
        problem_id="scheduler_day_teacher_m1_cap_constraint",
        variables=tuple(variables),
        rules=(ai_rule,),
        constraints=tuple(constraints),
        objective=objective,
    )
    rule_first_plan = build_rule_first_plan(
        rules=problem.rules,
        constraints=problem.constraints,
        objective_rule_id=objective.rule_id,
    )
    return SchedulerGenericRuleBridge(
        problem=problem,
        rule_first_plan=rule_first_plan,
        metadata_by_rule={
            rule_id: {
                "scheduler_rule_id": rule_id,
                "legacy_apply_fn": "apply_teacher_m1_cap_constraint",
                "generic_contract_status": "covered_by_generic_contract",
                "runtime_rule_ids": generic_scheduler_rule_ids(),
                "constraint_family_counts": counts,
                "assignment_variable_names": assignment_names,
                "teacher_day_am1_assignment_variable_names": {
                    _teacher_day_key(teacher, day): tuple(sorted(names))
                    for (teacher, day), names in sorted(names_by_teacher_day.items())
                },
                "occ_variable_names": occ_variable_names,
                "m1_total_variable_names": m1_total_variable_names,
                "hit_cap_variable_names": hit_cap_variable_names,
                "m1_penalty_total_variable_names": penalty_total_variable_names,
                "fixed_by_teacher_day": {
                    _teacher_day_key(teacher, day): int(count)
                    for (teacher, day), count in sorted(fixed_by_teacher_day.items())
                },
                "fixed_total_by_teacher": {
                    teacher: int(fixed_total_by_teacher.get(teacher, 0))
                    for teacher in teachers
                    if int(fixed_total_by_teacher.get(teacher, 0)) > 0
                },
                "structural_impossible": structural_impossible,
                "constrained_teachers": teachers,
                "max_m1": max_m1_int,
                "weight": int(weight),
                "am1_penalty_exempt_teacher_days": tuple(
                    f"{teacher}|{day}" for teacher, day in sorted(exempt_teacher_days)
                ),
            }
        },
    )


def day_teacher_am1_fragmentation_to_ai_or_problem(
    data: Any,
    *,
    pe_teachers: Iterable[Any] = (),
    k_week: int = 2,
    w_only_am1: int = 1,
    w_am1_excess: int = 1,
    am1_penalty_exempt_teacher_days: Iterable[tuple[Any, Any]] | None = None,
    rule_id: str = "joint.day.teacher_am1_fragmentation",
) -> SchedulerGenericRuleBridge:
    """Compile teacher AM1-only day and weekly AM1 excess penalties into OptimizationProblemSpec."""
    excluded_teachers = set(_teacher_names(pe_teachers))
    exempt_teacher_days = {
        (str(teacher).strip(), str(day).strip())
        for teacher, day in (am1_penalty_exempt_teacher_days or ())
        if str(teacher).strip() and str(day).strip()
    }
    assignments = _day_candidate_assignment_names(data)
    assignment_variables = tuple(VariableSpec.bool(name) for (_cls, _subj, _slot, name) in assignments)
    assignment_names: dict[str, str] = {}
    names_by_teacher_day_am1: dict[tuple[str, str], list[str]] = {}
    names_by_teacher_day_non_am1: dict[tuple[str, str], list[str]] = {}
    teachers: set[str] = set()
    for cls, subj, slot, name in assignments:
        assignment_names[_assignment_key(cls, subj, str(slot.day), _slot_label(slot))] = name
        day = str(slot.day)
        if day not in WEEKDAY_DAYS or is_pe_or_tech_subject(str(subj)):
            continue
        teacher = str(getattr(data, "cls_subj_teacher", {}).get((cls, subj), "")).strip()
        if not teacher:
            continue
        teachers.add(teacher)
        if _is_am1(slot):
            names_by_teacher_day_am1.setdefault((teacher, day), []).append(name)
        elif _is_daytime(slot):
            names_by_teacher_day_non_am1.setdefault((teacher, day), []).append(name)

    fixed_am1_by_teacher_day: dict[tuple[str, str], int] = {}
    fixed_non_am1_by_teacher_day: dict[tuple[str, str], int] = {}
    for (cls, slot), subj in (getattr(data, "fixed_assign", {}) or {}).items():
        day = str(slot.day)
        if day not in WEEKDAY_DAYS:
            continue
        teacher = str(getattr(data, "cls_subj_teacher", {}).get((cls, subj), "")).strip()
        if not teacher:
            continue
        teachers.add(teacher)
        if _is_am1(slot):
            fixed_am1_by_teacher_day[(teacher, day)] = fixed_am1_by_teacher_day.get((teacher, day), 0) + 1
        elif _is_daytime(slot):
            fixed_non_am1_by_teacher_day[(teacher, day)] = fixed_non_am1_by_teacher_day.get((teacher, day), 0) + 1

    target_teachers = tuple(sorted(teacher for teacher in teachers if teacher not in excluded_teachers))
    variables: list[VariableSpec] = list(assignment_variables)
    constraints: list[LinearConstraintSpec] = []
    objective_terms: list[LinearTerm] = []
    am1_busy_variable_names: dict[str, str] = {}
    has_non_am1_variable_names: dict[str, str] = {}
    only_am1_variable_names: dict[str, str] = {}
    only_am1_count_variable_names: dict[str, str] = {}
    am1_count_variable_names: dict[str, str] = {}
    excess_variable_names: dict[str, str] = {}
    fixed_am1_penalty_week_by_teacher: dict[str, int] = {}
    counts = {
        "teacher_am1_fragmentation_am1_busy_constraints": 0,
        "teacher_am1_fragmentation_non_am1_busy_constraints": 0,
        "teacher_am1_fragmentation_only_am1_constraints": 0,
        "teacher_am1_fragmentation_only_am1_count_equalities": 0,
        "teacher_am1_fragmentation_excess_count_constraints": 0,
        "teacher_am1_fragmentation_only_am1_penalty_terms": 0,
        "teacher_am1_fragmentation_excess_penalty_terms": 0,
    }
    constraint_index = 1
    variable_index = 1

    for teacher in target_teachers:
        only_day_names: list[str] = []
        penalty_am1_names: list[str] = []
        fixed_am1_penalty_week = 0
        only_count_name = _teacher_am1_fragmentation_count_var_name(variable_index, "only_am1_days", teacher)
        variable_index += 1
        variables.append(VariableSpec(only_count_name, 0, len(WEEKDAY_DAYS)))
        only_am1_count_variable_names[teacher] = only_count_name

        for day in WEEKDAY_DAYS:
            day_text = str(day)
            teacher_day_key = _teacher_day_key(teacher, day_text)
            am1_names = tuple(sorted(names_by_teacher_day_am1.get((teacher, day_text), ())))
            non_am1_names = tuple(sorted(names_by_teacher_day_non_am1.get((teacher, day_text), ())))
            fixed_am1 = int(fixed_am1_by_teacher_day.get((teacher, day_text), 0))
            fixed_non_am1 = int(fixed_non_am1_by_teacher_day.get((teacher, day_text), 0))
            if (teacher, day_text) not in exempt_teacher_days:
                penalty_am1_names.extend(am1_names)
                fixed_am1_penalty_week += fixed_am1

            am1_busy_name = _teacher_am1_fragmentation_bool_name(variable_index, "am1_busy", teacher, day_text)
            variable_index += 1
            variables.append(VariableSpec.bool(am1_busy_name))
            am1_busy_variable_names[teacher_day_key] = am1_busy_name
            if fixed_am1 > 0:
                constraints.append(
                    LinearConstraintSpec(
                        name=f"day_teacher_am1_fragmentation__am1_busy_fixed__{constraint_index:04d}__{_safe_identifier(teacher_day_key)}",
                        expression=LinearExpression((LinearTerm(am1_busy_name, 1),)),
                        sense="==",
                        rhs=1,
                        rule_id=rule_id,
                    )
                )
                counts["teacher_am1_fragmentation_am1_busy_constraints"] += 1
                constraint_index += 1
            elif am1_names:
                constraints.append(
                    LinearConstraintSpec(
                        name=f"day_teacher_am1_fragmentation__am1_busy_lower__{constraint_index:04d}__{_safe_identifier(teacher_day_key)}",
                        expression=LinearExpression(
                            (
                                *(LinearTerm(name, 1) for name in am1_names),
                                LinearTerm(am1_busy_name, -1),
                            )
                        ),
                        sense=">=",
                        rhs=0,
                        rule_id=rule_id,
                    )
                )
                counts["teacher_am1_fragmentation_am1_busy_constraints"] += 1
                constraint_index += 1
                for name in am1_names:
                    constraints.append(
                        LinearConstraintSpec(
                            name=f"day_teacher_am1_fragmentation__am1_busy_upper__{constraint_index:04d}__{_safe_identifier(name)}",
                            expression=LinearExpression((LinearTerm(name, 1), LinearTerm(am1_busy_name, -1))),
                            sense="<=",
                            rhs=0,
                            rule_id=rule_id,
                        )
                    )
                    counts["teacher_am1_fragmentation_am1_busy_constraints"] += 1
                    constraint_index += 1
            else:
                constraints.append(
                    LinearConstraintSpec(
                        name=f"day_teacher_am1_fragmentation__am1_busy_zero__{constraint_index:04d}__{_safe_identifier(teacher_day_key)}",
                        expression=LinearExpression((LinearTerm(am1_busy_name, 1),)),
                        sense="==",
                        rhs=0,
                        rule_id=rule_id,
                    )
                )
                counts["teacher_am1_fragmentation_am1_busy_constraints"] += 1
                constraint_index += 1

            has_non_name = _teacher_am1_fragmentation_bool_name(variable_index, "has_non_am1", teacher, day_text)
            variable_index += 1
            variables.append(VariableSpec.bool(has_non_name))
            has_non_am1_variable_names[teacher_day_key] = has_non_name
            if fixed_non_am1 > 0:
                constraints.append(
                    LinearConstraintSpec(
                        name=f"day_teacher_am1_fragmentation__non_am1_fixed__{constraint_index:04d}__{_safe_identifier(teacher_day_key)}",
                        expression=LinearExpression((LinearTerm(has_non_name, 1),)),
                        sense="==",
                        rhs=1,
                        rule_id=rule_id,
                    )
                )
                counts["teacher_am1_fragmentation_non_am1_busy_constraints"] += 1
                constraint_index += 1
            elif non_am1_names:
                constraints.append(
                    LinearConstraintSpec(
                        name=f"day_teacher_am1_fragmentation__non_am1_lower__{constraint_index:04d}__{_safe_identifier(teacher_day_key)}",
                        expression=LinearExpression(
                            (
                                *(LinearTerm(name, 1) for name in non_am1_names),
                                LinearTerm(has_non_name, -1),
                            )
                        ),
                        sense=">=",
                        rhs=0,
                        rule_id=rule_id,
                    )
                )
                counts["teacher_am1_fragmentation_non_am1_busy_constraints"] += 1
                constraint_index += 1
                for name in non_am1_names:
                    constraints.append(
                        LinearConstraintSpec(
                            name=f"day_teacher_am1_fragmentation__non_am1_upper__{constraint_index:04d}__{_safe_identifier(name)}",
                            expression=LinearExpression((LinearTerm(name, 1), LinearTerm(has_non_name, -1))),
                            sense="<=",
                            rhs=0,
                            rule_id=rule_id,
                        )
                    )
                    counts["teacher_am1_fragmentation_non_am1_busy_constraints"] += 1
                    constraint_index += 1
            else:
                constraints.append(
                    LinearConstraintSpec(
                        name=f"day_teacher_am1_fragmentation__non_am1_zero__{constraint_index:04d}__{_safe_identifier(teacher_day_key)}",
                        expression=LinearExpression((LinearTerm(has_non_name, 1),)),
                        sense="==",
                        rhs=0,
                        rule_id=rule_id,
                    )
                )
                counts["teacher_am1_fragmentation_non_am1_busy_constraints"] += 1
                constraint_index += 1

            only_name = _teacher_am1_fragmentation_bool_name(variable_index, "only_am1", teacher, day_text)
            variable_index += 1
            variables.append(VariableSpec.bool(only_name))
            only_am1_variable_names[teacher_day_key] = only_name
            only_day_names.append(only_name)
            for suffix, terms, sense, rhs in (
                ("upper_am1", (LinearTerm(only_name, 1), LinearTerm(am1_busy_name, -1)), "<=", 0),
                ("upper_non", (LinearTerm(only_name, 1), LinearTerm(has_non_name, 1)), "<=", 1),
                (
                    "lower",
                    (LinearTerm(only_name, 1), LinearTerm(am1_busy_name, -1), LinearTerm(has_non_name, 1)),
                    ">=",
                    0,
                ),
            ):
                constraints.append(
                    LinearConstraintSpec(
                        name=f"day_teacher_am1_fragmentation__only_am1_{suffix}__{constraint_index:04d}__{_safe_identifier(teacher_day_key)}",
                        expression=LinearExpression(tuple(terms)),
                        sense=sense,
                        rhs=rhs,
                        rule_id=rule_id,
                    )
                )
                counts["teacher_am1_fragmentation_only_am1_constraints"] += 1
                constraint_index += 1
            if (teacher, day_text) not in exempt_teacher_days:
                objective_terms.append(LinearTerm(only_name, int(w_only_am1)))
                counts["teacher_am1_fragmentation_only_am1_penalty_terms"] += 1

        constraints.append(
            LinearConstraintSpec(
                name=f"day_teacher_am1_fragmentation__only_count_eq__{constraint_index:04d}__{_safe_identifier(teacher)}",
                expression=LinearExpression(
                    (
                        LinearTerm(only_count_name, 1),
                        *(LinearTerm(name, -1) for name in only_day_names),
                    )
                ),
                sense="==",
                rhs=0,
                rule_id=rule_id,
            )
        )
        counts["teacher_am1_fragmentation_only_am1_count_equalities"] += 1
        constraint_index += 1

        fixed_am1_penalty_week_by_teacher[teacher] = fixed_am1_penalty_week
        max_am1 = len(penalty_am1_names) + fixed_am1_penalty_week
        if max_am1 > 0:
            am1_count_name = _teacher_am1_fragmentation_count_var_name(variable_index, "am1_cnt", teacher)
            variable_index += 1
            variables.append(VariableSpec(am1_count_name, 0, max_am1))
            am1_count_variable_names[teacher] = am1_count_name
            constraints.append(
                LinearConstraintSpec(
                    name=f"day_teacher_am1_fragmentation__am1_count_eq__{constraint_index:04d}__{_safe_identifier(teacher)}",
                    expression=LinearExpression(
                        (
                            LinearTerm(am1_count_name, 1),
                            *(LinearTerm(name, -1) for name in sorted(penalty_am1_names)),
                        )
                    ),
                    sense="==",
                    rhs=fixed_am1_penalty_week,
                    rule_id=rule_id,
                )
            )
            counts["teacher_am1_fragmentation_excess_count_constraints"] += 1
            constraint_index += 1
            excess_name = _teacher_am1_fragmentation_count_var_name(variable_index, "am1_excess", teacher)
            variable_index += 1
            variables.append(VariableSpec(excess_name, 0, max_am1))
            excess_variable_names[teacher] = excess_name
            constraints.append(
                LinearConstraintSpec(
                    name=f"day_teacher_am1_fragmentation__excess_lower__{constraint_index:04d}__{_safe_identifier(teacher)}",
                    expression=LinearExpression((LinearTerm(excess_name, 1), LinearTerm(am1_count_name, -1))),
                    sense=">=",
                    rhs=-int(k_week),
                    rule_id=rule_id,
                )
            )
            counts["teacher_am1_fragmentation_excess_count_constraints"] += 1
            constraint_index += 1
            objective_terms.append(LinearTerm(excess_name, int(w_am1_excess)))
            counts["teacher_am1_fragmentation_excess_penalty_terms"] += 1

    objective = ObjectiveSpec(
        rule_id=rule_id,
        sense="minimize",
        expression=LinearExpression(tuple(objective_terms)),
    )
    ai_rule = AiRuleSpec(
        rule_id=rule_id,
        description="Day soft rule: penalize AM1-only teacher days and weekly AM1 excess.",
        enforcement="soft",
        priority=37,
        source="scheduler.model.constraints.day_weekday_constraints:apply_teacher_am1_fragmentation",
    )
    problem = OptimizationProblemSpec(
        problem_id="scheduler_day_teacher_am1_fragmentation",
        variables=tuple(variables),
        rules=(ai_rule,),
        constraints=tuple(constraints),
        objective=objective,
    )
    rule_first_plan = build_rule_first_plan(
        rules=problem.rules,
        constraints=problem.constraints,
        objective_rule_id=objective.rule_id,
    )
    return SchedulerGenericRuleBridge(
        problem=problem,
        rule_first_plan=rule_first_plan,
        metadata_by_rule={
            rule_id: {
                "scheduler_rule_id": rule_id,
                "legacy_apply_fn": "apply_teacher_am1_fragmentation",
                "generic_contract_status": "covered_by_generic_contract",
                "runtime_rule_ids": generic_scheduler_rule_ids(),
                "constraint_family_counts": counts,
                "assignment_variable_names": assignment_names,
                "teacher_day_am1_assignment_variable_names": {
                    _teacher_day_key(teacher, day): tuple(sorted(names))
                    for (teacher, day), names in sorted(names_by_teacher_day_am1.items())
                    if teacher in target_teachers
                },
                "teacher_day_non_am1_assignment_variable_names": {
                    _teacher_day_key(teacher, day): tuple(sorted(names))
                    for (teacher, day), names in sorted(names_by_teacher_day_non_am1.items())
                    if teacher in target_teachers
                },
                "am1_busy_variable_names": am1_busy_variable_names,
                "has_non_am1_variable_names": has_non_am1_variable_names,
                "only_am1_variable_names": only_am1_variable_names,
                "only_am1_count_variable_names": only_am1_count_variable_names,
                "am1_count_variable_names": am1_count_variable_names,
                "excess_variable_names": excess_variable_names,
                "fixed_am1_by_teacher_day": {
                    _teacher_day_key(teacher, day): int(count)
                    for (teacher, day), count in sorted(fixed_am1_by_teacher_day.items())
                    if teacher in target_teachers
                },
                "fixed_non_am1_by_teacher_day": {
                    _teacher_day_key(teacher, day): int(count)
                    for (teacher, day), count in sorted(fixed_non_am1_by_teacher_day.items())
                    if teacher in target_teachers
                },
                "fixed_am1_penalty_week_by_teacher": fixed_am1_penalty_week_by_teacher,
                "constrained_teachers": target_teachers,
                "pe_teachers": tuple(sorted(excluded_teachers)),
                "k_week": int(k_week),
                "w_only_am1": int(w_only_am1),
                "w_am1_excess": int(w_am1_excess),
                "am1_penalty_exempt_teacher_days": tuple(
                    f"{teacher}|{day}" for teacher, day in sorted(exempt_teacher_days)
                ),
            }
        },
    )


def day_multi_class_halfday_soft_to_ai_or_problem(
    data: Any,
    *,
    pe_teachers: Iterable[Any] = (),
    weight: int = 1,
    rule_id: str = "joint.day.multi_class_halfday_soft",
) -> SchedulerGenericRuleBridge:
    """Compile multi-class teacher halfday split/cross-halfday penalties into OptimizationProblemSpec."""
    excluded_teachers = set(_teacher_names(pe_teachers))
    teacher_classes: dict[str, set[str]] = {}
    for (cls, subj), teacher in getattr(data, "cls_subj_teacher", {}).items():
        if is_pe_or_tech_subject(str(subj)):
            continue
        teacher_text = str(teacher).strip()
        if not teacher_text:
            continue
        teacher_classes.setdefault(teacher_text, set()).add(str(cls))
    target_teacher_classes = {
        teacher: tuple(sorted(classes))
        for teacher, classes in sorted(teacher_classes.items())
        if teacher not in excluded_teachers and len(classes) >= 2
    }

    assignments = _day_candidate_assignment_names(data)
    assignment_variables = tuple(VariableSpec.bool(name) for (_cls, _subj, _slot, name) in assignments)
    assignment_names: dict[str, str] = {}
    names_by_teacher_day_class: dict[tuple[str, str, str], list[str]] = {}
    am_names_by_teacher_day_class: dict[tuple[str, str, str], list[str]] = {}
    pm_names_by_teacher_day_class: dict[tuple[str, str, str], list[str]] = {}
    for cls, subj, slot, name in assignments:
        assignment_names[_assignment_key(cls, subj, str(slot.day), _slot_label(slot))] = name
        day = str(slot.day)
        if day not in WEEKDAY_DAYS:
            continue
        teacher = str(getattr(data, "cls_subj_teacher", {}).get((cls, subj), "")).strip()
        if teacher not in target_teacher_classes or is_pe_or_tech_subject(str(subj)):
            continue
        key = (teacher, day, cls)
        names_by_teacher_day_class.setdefault(key, []).append(name)
        if _is_am(slot):
            am_names_by_teacher_day_class.setdefault(key, []).append(name)
        if _is_pm(slot):
            pm_names_by_teacher_day_class.setdefault(key, []).append(name)

    variables: list[VariableSpec] = list(assignment_variables)
    constraints: list[ConstraintSpec] = []
    objective_terms: list[LinearTerm] = []
    has_any_am_variable_names: dict[str, str] = {}
    has_any_pm_variable_names: dict[str, str] = {}
    class_count_variable_names: dict[str, str] = {}
    class_has_am_variable_names: dict[str, str] = {}
    class_has_pm_variable_names: dict[str, str] = {}
    class_count_ge2_variable_names: dict[str, str] = {}
    split_ok_variable_names: dict[str, str] = {}
    not_split_variable_names: dict[str, str] = {}
    split_violation_variable_names: dict[str, str] = {}
    split_forced_variable_names: dict[str, str] = {}
    cross_halfday_variable_names: dict[str, str] = {}
    not_forced_variable_names: dict[str, str] = {}
    cross_penalty_variable_names: dict[str, str] = {}
    counts = {
        "multi_class_halfday_class_count_equalities": 0,
        "multi_class_halfday_class_am_presence_constraints": 0,
        "multi_class_halfday_class_pm_presence_constraints": 0,
        "multi_class_halfday_cnt_ge2_constraints": 0,
        "multi_class_halfday_split_ok_constraints": 0,
        "multi_class_halfday_not_split_constraints": 0,
        "multi_class_halfday_split_vio_constraints": 0,
        "multi_class_halfday_any_am_presence_constraints": 0,
        "multi_class_halfday_any_pm_presence_constraints": 0,
        "multi_class_halfday_split_forced_max_constraints": 0,
        "multi_class_halfday_cross_halfday_constraints": 0,
        "multi_class_halfday_not_forced_constraints": 0,
        "multi_class_halfday_cross_penalty_constraints": 0,
        "multi_class_halfday_penalty_terms": 0,
    }
    linear_constraint_count = 0
    constraint_index = 1
    variable_index = 1

    def add_linear(
        family: str,
        name: str,
        terms: Sequence[LinearTerm],
        sense: str,
        rhs: int,
        enforcement_literals: tuple[Any, ...] = (),
    ) -> None:
        nonlocal constraint_index, linear_constraint_count
        constraints.append(
            LinearConstraintSpec(
                name=f"{name}__{constraint_index:04d}",
                expression=LinearExpression(tuple(terms)),
                sense=sense,
                rhs=int(rhs),
                rule_id=rule_id,
                enforcement_literals=enforcement_literals,
            )
        )
        counts[family] += 1
        linear_constraint_count += 1
        constraint_index += 1

    def add_and2_constraints(family: str, prefix: str, output: str, left: str, right: str) -> None:
        add_linear(
            family,
            f"{prefix}__upper_left__{_safe_identifier(output)}",
            (LinearTerm(output, 1), LinearTerm(left, -1)),
            "<=",
            0,
        )
        add_linear(
            family,
            f"{prefix}__upper_right__{_safe_identifier(output)}",
            (LinearTerm(output, 1), LinearTerm(right, -1)),
            "<=",
            0,
        )
        add_linear(
            family,
            f"{prefix}__lower__{_safe_identifier(output)}",
            (LinearTerm(output, 1), LinearTerm(left, -1), LinearTerm(right, -1)),
            ">=",
            -1,
        )

    for teacher, classes in target_teacher_classes.items():
        for day in WEEKDAY_DAYS:
            day_text = str(day)
            teacher_day_key = _teacher_day_key(teacher, day_text)
            has_any_am_name = _multi_class_halfday_bool_name(variable_index, "has_any_am", teacher, day_text)
            variable_index += 1
            has_any_pm_name = _multi_class_halfday_bool_name(variable_index, "has_any_pm", teacher, day_text)
            variable_index += 1
            variables.append(VariableSpec.bool(has_any_am_name))
            variables.append(VariableSpec.bool(has_any_pm_name))
            has_any_am_variable_names[teacher_day_key] = has_any_am_name
            has_any_pm_variable_names[teacher_day_key] = has_any_pm_name
            split_forced_candidates: list[str] = []
            am_names_all: list[str] = []
            pm_names_all: list[str] = []

            for cls in classes:
                class_key = _teacher_class_day_key(teacher, cls, day_text)
                all_names = tuple(sorted(names_by_teacher_day_class.get((teacher, day_text, cls), ())))
                if not all_names:
                    continue
                am_names = tuple(sorted(am_names_by_teacher_day_class.get((teacher, day_text, cls), ())))
                pm_names = tuple(sorted(pm_names_by_teacher_day_class.get((teacher, day_text, cls), ())))
                am_names_all.extend(am_names)
                pm_names_all.extend(pm_names)

                count_name = _multi_class_halfday_count_var_name(variable_index, teacher, day_text, cls)
                variable_index += 1
                variables.append(VariableSpec(count_name, 0, len(all_names)))
                class_count_variable_names[class_key] = count_name
                add_linear(
                    "multi_class_halfday_class_count_equalities",
                    f"day_multi_class_halfday__count_eq__{_safe_identifier(class_key)}",
                    (LinearTerm(count_name, 1), *(LinearTerm(name, -1) for name in all_names)),
                    "==",
                    0,
                )

                has_am_name = _multi_class_halfday_bool_name(variable_index, "has_am", teacher, day_text, cls)
                variable_index += 1
                variables.append(VariableSpec.bool(has_am_name))
                class_has_am_variable_names[class_key] = has_am_name
                if am_names:
                    add_linear(
                        "multi_class_halfday_class_am_presence_constraints",
                        f"day_multi_class_halfday__has_am_lower__{_safe_identifier(class_key)}",
                        (*(LinearTerm(name, 1) for name in am_names), LinearTerm(has_am_name, -1)),
                        ">=",
                        0,
                    )
                    for name in am_names:
                        add_linear(
                            "multi_class_halfday_class_am_presence_constraints",
                            f"day_multi_class_halfday__has_am_upper__{_safe_identifier(name)}",
                            (LinearTerm(name, 1), LinearTerm(has_am_name, -1)),
                            "<=",
                            0,
                        )
                else:
                    add_linear(
                        "multi_class_halfday_class_am_presence_constraints",
                        f"day_multi_class_halfday__has_am_zero__{_safe_identifier(class_key)}",
                        (LinearTerm(has_am_name, 1),),
                        "==",
                        0,
                    )

                has_pm_name = _multi_class_halfday_bool_name(variable_index, "has_pm", teacher, day_text, cls)
                variable_index += 1
                variables.append(VariableSpec.bool(has_pm_name))
                class_has_pm_variable_names[class_key] = has_pm_name
                if pm_names:
                    add_linear(
                        "multi_class_halfday_class_pm_presence_constraints",
                        f"day_multi_class_halfday__has_pm_lower__{_safe_identifier(class_key)}",
                        (*(LinearTerm(name, 1) for name in pm_names), LinearTerm(has_pm_name, -1)),
                        ">=",
                        0,
                    )
                    for name in pm_names:
                        add_linear(
                            "multi_class_halfday_class_pm_presence_constraints",
                            f"day_multi_class_halfday__has_pm_upper__{_safe_identifier(name)}",
                            (LinearTerm(name, 1), LinearTerm(has_pm_name, -1)),
                            "<=",
                            0,
                        )
                else:
                    add_linear(
                        "multi_class_halfday_class_pm_presence_constraints",
                        f"day_multi_class_halfday__has_pm_zero__{_safe_identifier(class_key)}",
                        (LinearTerm(has_pm_name, 1),),
                        "==",
                        0,
                    )

                count_ge2_name = _multi_class_halfday_bool_name(variable_index, "cnt_ge2", teacher, day_text, cls)
                variable_index += 1
                variables.append(VariableSpec.bool(count_ge2_name))
                class_count_ge2_variable_names[class_key] = count_ge2_name
                add_linear(
                    "multi_class_halfday_cnt_ge2_constraints",
                    f"day_multi_class_halfday__cnt_ge2_true__{_safe_identifier(class_key)}",
                    (LinearTerm(count_name, 1),),
                    ">=",
                    2,
                    (count_ge2_name,),
                )
                add_linear(
                    "multi_class_halfday_cnt_ge2_constraints",
                    f"day_multi_class_halfday__cnt_ge2_false__{_safe_identifier(class_key)}",
                    (LinearTerm(count_name, 1),),
                    "<=",
                    1,
                    (BoolLiteralSpec(count_ge2_name, negated=True),),
                )

                split_ok_name = _multi_class_halfday_bool_name(variable_index, "split_ok", teacher, day_text, cls)
                variable_index += 1
                variables.append(VariableSpec.bool(split_ok_name))
                split_ok_variable_names[class_key] = split_ok_name
                add_and2_constraints(
                    "multi_class_halfday_split_ok_constraints",
                    "day_multi_class_halfday__split_ok",
                    split_ok_name,
                    has_am_name,
                    has_pm_name,
                )

                not_split_name = _multi_class_halfday_bool_name(variable_index, "not_split", teacher, day_text, cls)
                variable_index += 1
                variables.append(VariableSpec.bool(not_split_name))
                not_split_variable_names[class_key] = not_split_name
                add_linear(
                    "multi_class_halfday_not_split_constraints",
                    f"day_multi_class_halfday__not_split_eq__{_safe_identifier(class_key)}",
                    (LinearTerm(split_ok_name, 1), LinearTerm(not_split_name, 1)),
                    "==",
                    1,
                )

                violation_name = _multi_class_halfday_bool_name(variable_index, "split_vio", teacher, day_text, cls)
                variable_index += 1
                variables.append(VariableSpec.bool(violation_name))
                split_violation_variable_names[class_key] = violation_name
                add_and2_constraints(
                    "multi_class_halfday_split_vio_constraints",
                    "day_multi_class_halfday__split_vio",
                    violation_name,
                    count_ge2_name,
                    not_split_name,
                )
                objective_terms.append(LinearTerm(violation_name, int(weight)))
                counts["multi_class_halfday_penalty_terms"] += 1
                split_forced_candidates.append(count_ge2_name)

            if not split_forced_candidates:
                continue

            for name in sorted(am_names_all):
                add_linear(
                    "multi_class_halfday_any_am_presence_constraints",
                    f"day_multi_class_halfday__has_any_am_upper__{_safe_identifier(name)}",
                    (LinearTerm(name, 1), LinearTerm(has_any_am_name, -1)),
                    "<=",
                    0,
                )
            if am_names_all:
                add_linear(
                    "multi_class_halfday_any_am_presence_constraints",
                    f"day_multi_class_halfday__has_any_am_lower__{_safe_identifier(teacher_day_key)}",
                    (*(LinearTerm(name, 1) for name in sorted(am_names_all)), LinearTerm(has_any_am_name, -1)),
                    ">=",
                    0,
                )
            else:
                add_linear(
                    "multi_class_halfday_any_am_presence_constraints",
                    f"day_multi_class_halfday__has_any_am_zero__{_safe_identifier(teacher_day_key)}",
                    (LinearTerm(has_any_am_name, 1),),
                    "==",
                    0,
                )

            for name in sorted(pm_names_all):
                add_linear(
                    "multi_class_halfday_any_pm_presence_constraints",
                    f"day_multi_class_halfday__has_any_pm_upper__{_safe_identifier(name)}",
                    (LinearTerm(name, 1), LinearTerm(has_any_pm_name, -1)),
                    "<=",
                    0,
                )
            if pm_names_all:
                add_linear(
                    "multi_class_halfday_any_pm_presence_constraints",
                    f"day_multi_class_halfday__has_any_pm_lower__{_safe_identifier(teacher_day_key)}",
                    (*(LinearTerm(name, 1) for name in sorted(pm_names_all)), LinearTerm(has_any_pm_name, -1)),
                    ">=",
                    0,
                )
            else:
                add_linear(
                    "multi_class_halfday_any_pm_presence_constraints",
                    f"day_multi_class_halfday__has_any_pm_zero__{_safe_identifier(teacher_day_key)}",
                    (LinearTerm(has_any_pm_name, 1),),
                    "==",
                    0,
                )

            split_forced_name = _multi_class_halfday_bool_name(variable_index, "split_forced", teacher, day_text)
            variable_index += 1
            variables.append(VariableSpec.bool(split_forced_name))
            split_forced_variable_names[teacher_day_key] = split_forced_name
            constraints.append(
                MaxEqualityConstraintSpec(
                    name=f"day_multi_class_halfday__split_forced_max__{constraint_index:04d}__{_safe_identifier(teacher_day_key)}",
                    target=split_forced_name,
                    expressions=tuple(split_forced_candidates),
                    rule_id=rule_id,
                )
            )
            counts["multi_class_halfday_split_forced_max_constraints"] += 1
            constraint_index += 1

            cross_name = _multi_class_halfday_bool_name(variable_index, "cross_halfday", teacher, day_text)
            variable_index += 1
            variables.append(VariableSpec.bool(cross_name))
            cross_halfday_variable_names[teacher_day_key] = cross_name
            add_and2_constraints(
                "multi_class_halfday_cross_halfday_constraints",
                "day_multi_class_halfday__cross_halfday",
                cross_name,
                has_any_am_name,
                has_any_pm_name,
            )

            not_forced_name = _multi_class_halfday_bool_name(variable_index, "not_forced", teacher, day_text)
            variable_index += 1
            variables.append(VariableSpec.bool(not_forced_name))
            not_forced_variable_names[teacher_day_key] = not_forced_name
            add_linear(
                "multi_class_halfday_not_forced_constraints",
                f"day_multi_class_halfday__not_forced_eq__{_safe_identifier(teacher_day_key)}",
                (LinearTerm(split_forced_name, 1), LinearTerm(not_forced_name, 1)),
                "==",
                1,
            )

            cross_penalty_name = _multi_class_halfday_bool_name(variable_index, "cross_penalty", teacher, day_text)
            variable_index += 1
            variables.append(VariableSpec.bool(cross_penalty_name))
            cross_penalty_variable_names[teacher_day_key] = cross_penalty_name
            add_and2_constraints(
                "multi_class_halfday_cross_penalty_constraints",
                "day_multi_class_halfday__cross_penalty",
                cross_penalty_name,
                cross_name,
                not_forced_name,
            )
            objective_terms.append(LinearTerm(cross_penalty_name, int(weight)))
            counts["multi_class_halfday_penalty_terms"] += 1

    objective = ObjectiveSpec(
        rule_id=rule_id,
        sense="minimize",
        expression=LinearExpression(tuple(objective_terms)),
    )
    ai_rule = AiRuleSpec(
        rule_id=rule_id,
        description="Day soft rule: penalize multi-class teacher split violations and unnecessary cross-halfday teaching.",
        enforcement="soft",
        priority=38,
        source="scheduler.model.constraints.day_weekday_constraints:apply_multi_class_halfday_soft",
    )
    problem = OptimizationProblemSpec(
        problem_id="scheduler_day_multi_class_halfday_soft",
        variables=tuple(variables),
        rules=(ai_rule,),
        constraints=tuple(constraints),
        objective=objective,
    )
    rule_first_plan = build_rule_first_plan(
        rules=problem.rules,
        constraints=problem.constraints,
        objective_rule_id=objective.rule_id,
    )
    return SchedulerGenericRuleBridge(
        problem=problem,
        rule_first_plan=rule_first_plan,
        metadata_by_rule={
            rule_id: {
                "scheduler_rule_id": rule_id,
                "legacy_apply_fn": "apply_multi_class_halfday_soft",
                "generic_contract_status": "covered_by_generic_contract",
                "runtime_rule_ids": generic_scheduler_rule_ids(),
                "constraint_family_counts": counts,
                "linear_constraint_count": linear_constraint_count,
                "assignment_variable_names": assignment_names,
                "teacher_classes": target_teacher_classes,
                "constrained_teachers": tuple(target_teacher_classes),
                "teacher_day_class_assignment_variable_names": {
                    _teacher_class_day_key(teacher, cls, day): tuple(sorted(names))
                    for (teacher, day, cls), names in sorted(names_by_teacher_day_class.items())
                },
                "teacher_day_class_am_assignment_variable_names": {
                    _teacher_class_day_key(teacher, cls, day): tuple(sorted(names))
                    for (teacher, day, cls), names in sorted(am_names_by_teacher_day_class.items())
                },
                "teacher_day_class_pm_assignment_variable_names": {
                    _teacher_class_day_key(teacher, cls, day): tuple(sorted(names))
                    for (teacher, day, cls), names in sorted(pm_names_by_teacher_day_class.items())
                },
                "has_any_am_variable_names": has_any_am_variable_names,
                "has_any_pm_variable_names": has_any_pm_variable_names,
                "class_count_variable_names": class_count_variable_names,
                "class_has_am_variable_names": class_has_am_variable_names,
                "class_has_pm_variable_names": class_has_pm_variable_names,
                "class_count_ge2_variable_names": class_count_ge2_variable_names,
                "split_ok_variable_names": split_ok_variable_names,
                "not_split_variable_names": not_split_variable_names,
                "split_violation_variable_names": split_violation_variable_names,
                "split_forced_variable_names": split_forced_variable_names,
                "cross_halfday_variable_names": cross_halfday_variable_names,
                "not_forced_variable_names": not_forced_variable_names,
                "cross_penalty_variable_names": cross_penalty_variable_names,
                "pe_teachers": tuple(sorted(excluded_teachers)),
                "weight": int(weight),
            }
        },
    )


def night_soft_objective_to_ai_or_problem(
    *,
    days: Sequence[Any],
    periods: Sequence[Any],
    cst: Mapping[tuple[Any, Any], Any],
    all_teachers: Sequence[Any],
    male_heads: Sequence[Any],
    female_heads: Sequence[Any],
    rules: Mapping[str, Any] | None = None,
    on_teacher_day_variable_names: Mapping[tuple[Any, Any], str] | None = None,
    y_variable_names: Mapping[tuple[Any, Any, Any, Any], str] | None = None,
    checkin_m_variable_names: Mapping[tuple[Any, Any], str] | None = None,
    checkin_f_variable_names: Mapping[tuple[Any, Any], str] | None = None,
    rule_id: str = "joint.night.soft_objective",
) -> SchedulerGenericRuleBridge:
    """Compile the night soft objective into a generic rule-first problem."""
    day_names = tuple(str(day) for day in days)
    period_names = tuple(str(period) for period in periods)
    cst_names = {
        (str(cls), str(subj)): str(teacher).strip()
        for (cls, subj), teacher in cst.items()
        if str(cls).strip() and str(subj).strip() and str(teacher).strip()
    }
    teacher_names = tuple(str(teacher).strip() for teacher in all_teachers if str(teacher).strip())
    male_head_names = tuple(str(teacher).strip() for teacher in male_heads if str(teacher).strip())
    female_head_names = tuple(str(teacher).strip() for teacher in female_heads if str(teacher).strip())
    rule_cfg = dict(rules or {})
    soft_cfg = dict(rule_cfg.get("soft", {}) or {})
    eve_cfg = dict(rule_cfg.get("evening_constraints", {}) or {})
    enabled = soft_cfg.get("enabled", True) is not False

    def _map_teacher_day(raw: Mapping[tuple[Any, Any], str] | None) -> dict[tuple[str, str], str]:
        return {
            (str(teacher).strip(), str(day).strip()): str(name)
            for (teacher, day), name in (raw or {}).items()
            if str(teacher).strip() and str(day).strip() and str(name).strip()
        }

    def _map_y(raw: Mapping[tuple[Any, Any, Any, Any], str] | None) -> dict[tuple[str, str, str, str], str]:
        return {
            (str(cls), str(subj), str(day), str(period)): str(name)
            for (cls, subj, day, period), name in (raw or {}).items()
            if str(cls).strip() and str(subj).strip() and str(day).strip() and str(period).strip() and str(name).strip()
        }

    on_names = _map_teacher_day(on_teacher_day_variable_names)
    y_names = _map_y(y_variable_names)
    checkin_m_names = _map_teacher_day(checkin_m_variable_names)
    checkin_f_names = _map_teacher_day(checkin_f_variable_names)

    variables: list[VariableSpec] = []
    seen_variables: set[str] = set()
    constraints: list[LinearConstraintSpec] = []
    objective_terms: list[LinearTerm] = []
    variable_index = 1
    constraint_index = 1
    linear_constraint_count = 0
    counts = {
        "night_soft_miss_head_constraints": 0,
        "night_soft_adjacent_teacher_constraints": 0,
        "night_soft_sun_mon_constraints": 0,
        "night_soft_fri_sun_mutex_constraints": 0,
        "night_soft_yk_xxc_fri_mutex_constraints": 0,
        "night_soft_checkin_repeat_constraints": 0,
        "night_soft_subject_sync_constraints": 0,
        "night_soft_penalty_terms": 0,
    }

    def add_variable(name: str, lb: int = 0, ub: int = 1, *, kind: str = "bool") -> str:
        if name not in seen_variables:
            variables.append(VariableSpec(str(name), int(lb), int(ub), kind=kind))
            seen_variables.add(name)
        return name

    for name in sorted({*on_names.values(), *y_names.values(), *checkin_m_names.values(), *checkin_f_names.values()}):
        add_variable(name)

    def next_bool(tag: str, *parts: Any) -> str:
        nonlocal variable_index
        name = _night_soft_var_name(variable_index, tag, *parts)
        variable_index += 1
        return add_variable(name)

    def add_linear(
        family: str,
        name: str,
        terms: Sequence[LinearTerm],
        sense: str,
        rhs: int,
        *,
        enforcement_literals: Sequence[BoolLiteralSpec | str] = (),
    ) -> None:
        nonlocal constraint_index, linear_constraint_count
        constraints.append(
            LinearConstraintSpec(
                name=f"{name}__{constraint_index:04d}",
                expression=LinearExpression(tuple(terms)),
                sense=sense,
                rhs=int(rhs),
                rule_id=rule_id,
                enforcement_literals=tuple(enforcement_literals),
            )
        )
        counts[family] += 1
        linear_constraint_count += 1
        constraint_index += 1

    def add_penalty(name: str, weight: int) -> None:
        objective_terms.append(LinearTerm(name, int(weight)))
        counts["night_soft_penalty_terms"] += 1

    def add_and2(family: str, prefix: str, output: str, left: str, right: str) -> None:
        add_linear(
            family,
            f"{prefix}__upper_left__{_safe_identifier(output)}",
            (LinearTerm(output, 1), LinearTerm(left, -1)),
            "<=",
            0,
        )
        add_linear(
            family,
            f"{prefix}__upper_right__{_safe_identifier(output)}",
            (LinearTerm(output, 1), LinearTerm(right, -1)),
            "<=",
            0,
        )
        add_linear(
            family,
            f"{prefix}__lower__{_safe_identifier(output)}",
            (LinearTerm(output, 1), LinearTerm(left, -1), LinearTerm(right, -1)),
            ">=",
            -1,
        )

    w_cfg = dict(soft_cfg.get("weights", {}) or {})
    w_miss_head_on = int(w_cfg.get("miss_head_on", 50))
    w_adj_teacher = int(w_cfg.get("adjacent_teacher", 5))
    w_checkin_repeat = int(w_cfg.get("checkin_repeat", 20))
    w_sun_mon = int(w_cfg.get("sun_mon_teacher", 4))
    adj_exempt = _teacher_norm_set(soft_cfg.get("adjacent_teacher_exempt_teachers", ()))
    extra_weights = dict(eve_cfg.get("weights", {}) or {})
    w_subject_sync = int(extra_weights.get("subject_sync", 20))
    w_physics_fri = int(extra_weights.get("physics_fri_penalty", 120))
    w_history_fri = int(extra_weights.get("history_fri_penalty", 120))
    w_math_fri_p1 = int(extra_weights.get("math_zeng_fri_p1_penalty", extra_weights.get("math_zeng_fri_penalty", 500)))
    w_math_fri_p2 = int(extra_weights.get("math_zeng_fri_p2_penalty", extra_weights.get("math_zeng_fri_penalty", 500)))

    miss_head_names: dict[str, str] = {}
    adjacent_names: dict[str, str] = {}
    sun_mon_names: dict[str, str] = {}
    fri_sun_names: dict[str, str] = {}
    yk_xxc_names: dict[str, str] = {}
    checkin_repeat_names: dict[str, str] = {}
    subject_sync_names: dict[str, str] = {}
    physics_math_terms: dict[str, int] = {}

    if enabled:
        for day in day_names:
            miss_m_name = next_bool("miss_male_head_on", day)
            miss_head_names[f"male|{day}"] = miss_m_name
            male_on_terms = tuple(
                LinearTerm(name, 1)
                for teacher in male_head_names
                for name in (on_names.get((teacher, day)),)
                if name
            )
            big_m = max(1, len(male_head_names))
            add_linear(
                "night_soft_miss_head_constraints",
                f"night_soft__miss_male_lower__{_safe_identifier(day)}",
                (*male_on_terms, LinearTerm(miss_m_name, big_m)),
                ">=",
                1,
            )
            add_linear(
                "night_soft_miss_head_constraints",
                f"night_soft__miss_male_upper__{_safe_identifier(day)}",
                (*male_on_terms, LinearTerm(miss_m_name, big_m)),
                "<=",
                big_m,
            )
            add_penalty(miss_m_name, w_miss_head_on)

            miss_f_name = next_bool("miss_female_head_on", day)
            miss_head_names[f"female|{day}"] = miss_f_name
            female_on_terms = tuple(
                LinearTerm(name, 1)
                for teacher in female_head_names
                for name in (on_names.get((teacher, day)),)
                if name
            )
            big_f = max(1, len(female_head_names))
            add_linear(
                "night_soft_miss_head_constraints",
                f"night_soft__miss_female_lower__{_safe_identifier(day)}",
                (*female_on_terms, LinearTerm(miss_f_name, big_f)),
                ">=",
                1,
            )
            add_linear(
                "night_soft_miss_head_constraints",
                f"night_soft__miss_female_upper__{_safe_identifier(day)}",
                (*female_on_terms, LinearTerm(miss_f_name, big_f)),
                "<=",
                big_f,
            )
            add_penalty(miss_f_name, w_miss_head_on)

        for index in range(len(day_names) - 1):
            day_1 = day_names[index]
            day_2 = day_names[index + 1]
            for teacher in teacher_names:
                if _teacher_norm(teacher) in adj_exempt:
                    continue
                left = on_names.get((teacher, day_1))
                right = on_names.get((teacher, day_2))
                if not left or not right:
                    continue
                adj_name = next_bool("adj_on", teacher, day_1, day_2)
                adjacent_names[f"{teacher}|{day_1}->{day_2}"] = adj_name
                add_and2("night_soft_adjacent_teacher_constraints", "night_soft__adjacent", adj_name, left, right)
                add_penalty(adj_name, w_adj_teacher)

        if "星期日" in day_names and "星期一" in day_names:
            for teacher in teacher_names:
                if _teacher_norm(teacher) in adj_exempt:
                    continue
                left = on_names.get((teacher, "星期日"))
                right = on_names.get((teacher, "星期一"))
                if not left or not right:
                    continue
                sun_mon_name = next_bool("sun_mon", teacher)
                sun_mon_names[teacher] = sun_mon_name
                add_and2("night_soft_sun_mon_constraints", "night_soft__sun_mon", sun_mon_name, left, right)
                add_penalty(sun_mon_name, w_sun_mon)

        if (
            eve_cfg.get("enable_fri_sun_mutex", False)
            and str(eve_cfg.get("fri_sun_mutex_mode", "soft")).lower() == "soft"
            and "星期五" in day_names
            and "星期日" in day_names
        ):
            fri_sun_weight = int(eve_cfg.get("fri_sun_mutex_weight", w_cfg.get("fri_sun_teacher", 10)))
            fri_sun_exempt = _teacher_norm_set(eve_cfg.get("fri_sun_mutex_exempt_teachers", ()))
            for teacher in teacher_names:
                if _teacher_norm(teacher) in fri_sun_exempt:
                    continue
                left = on_names.get((teacher, "星期五"))
                right = on_names.get((teacher, "星期日"))
                if not left or not right:
                    continue
                fri_sun_name = next_bool("fri_sun", teacher)
                fri_sun_names[teacher] = fri_sun_name
                add_and2("night_soft_fri_sun_mutex_constraints", "night_soft__fri_sun", fri_sun_name, left, right)
                add_penalty(fri_sun_name, fri_sun_weight)

        if (
            eve_cfg.get("enable_yk_xxc_fri_mutex", True)
            and str(eve_cfg.get("yk_xxc_fri_mutex_mode", "hard")).lower() == "soft"
            and "星期五" in day_names
        ):
            pair = _teacher_names(eve_cfg.get("yk_xxc_fri_mutex_teachers", ()))
            left_teacher = _find_teacher_key_by_norm(teacher_names, pair[0]) if len(pair) >= 1 else None
            right_teacher = _find_teacher_key_by_norm(teacher_names, pair[1]) if len(pair) >= 2 else None
            if left_teacher and right_teacher:
                left = on_names.get((left_teacher, "星期五"))
                right = on_names.get((right_teacher, "星期五"))
                if left and right:
                    yk_name = next_bool("fri_mutex", left_teacher, right_teacher)
                    yk_xxc_names[f"{left_teacher}|{right_teacher}|星期五"] = yk_name
                    add_and2("night_soft_yk_xxc_fri_mutex_constraints", "night_soft__yk_xxc_fri", yk_name, left, right)
                    add_penalty(yk_name, int(eve_cfg.get("yk_xxc_fri_mutex_weight", 2000)))

        if checkin_m_names and checkin_f_names:
            for teacher in male_head_names:
                names = tuple(name for day in day_names for name in (checkin_m_names.get((teacher, day)),) if name)
                repeat_name = next_bool("checkin_repeat_m", teacher)
                checkin_repeat_names[f"male|{teacher}"] = repeat_name
                add_linear(
                    "night_soft_checkin_repeat_constraints",
                    f"night_soft__checkin_m_repeat_lower__{_safe_identifier(teacher)}",
                    tuple(LinearTerm(name, 1) for name in names),
                    ">=",
                    2,
                    enforcement_literals=(repeat_name,),
                )
                add_linear(
                    "night_soft_checkin_repeat_constraints",
                    f"night_soft__checkin_m_repeat_upper__{_safe_identifier(teacher)}",
                    tuple(LinearTerm(name, 1) for name in names),
                    "<=",
                    1,
                    enforcement_literals=(BoolLiteralSpec(repeat_name, negated=True),),
                )
                add_penalty(repeat_name, w_checkin_repeat)
            for teacher in female_head_names:
                names = tuple(name for day in day_names for name in (checkin_f_names.get((teacher, day)),) if name)
                repeat_name = next_bool("checkin_repeat_f", teacher)
                checkin_repeat_names[f"female|{teacher}"] = repeat_name
                add_linear(
                    "night_soft_checkin_repeat_constraints",
                    f"night_soft__checkin_f_repeat_lower__{_safe_identifier(teacher)}",
                    tuple(LinearTerm(name, 1) for name in names),
                    ">=",
                    2,
                    enforcement_literals=(repeat_name,),
                )
                add_linear(
                    "night_soft_checkin_repeat_constraints",
                    f"night_soft__checkin_f_repeat_upper__{_safe_identifier(teacher)}",
                    tuple(LinearTerm(name, 1) for name in names),
                    "<=",
                    1,
                    enforcement_literals=(BoolLiteralSpec(repeat_name, negated=True),),
                )
                add_penalty(repeat_name, w_checkin_repeat)

        if eve_cfg.get("enabled", True) is not False and eve_cfg.get("enable_subject_sync", True) is not False:
            subjects = tuple(sorted({subj for _cls, subj in cst_names}))
            for subj in subjects:
                for day in day_names:
                    for period in period_names:
                        related = tuple(
                            name
                            for (cls, cst_subj), _teacher in sorted(cst_names.items())
                            for name in (y_names.get((cls, cst_subj, day, period)),)
                            if cst_subj == subj and name
                        )
                        active_name = next_bool("subj_active", subj, day, period)
                        subject_sync_names[f"{subj}|{day}|{period}"] = active_name
                        if related:
                            m = len(related)
                            add_linear(
                                "night_soft_subject_sync_constraints",
                                f"night_soft__subject_active_lower__{_safe_identifier(subj)}__{_safe_identifier(day)}__{_safe_identifier(period)}",
                                (*(LinearTerm(name, 1) for name in related), LinearTerm(active_name, -1)),
                                ">=",
                                0,
                            )
                            add_linear(
                                "night_soft_subject_sync_constraints",
                                f"night_soft__subject_active_upper__{_safe_identifier(subj)}__{_safe_identifier(day)}__{_safe_identifier(period)}",
                                (*(LinearTerm(name, 1) for name in related), LinearTerm(active_name, -m)),
                                "<=",
                                0,
                            )
                        else:
                            add_linear(
                                "night_soft_subject_sync_constraints",
                                f"night_soft__subject_active_zero__{_safe_identifier(subj)}__{_safe_identifier(day)}__{_safe_identifier(period)}",
                                (LinearTerm(active_name, 1),),
                                "==",
                                0,
                            )
                        add_penalty(active_name, w_subject_sync)

        if eve_cfg.get("enabled", True) is not False and eve_cfg.get("enable_physics_math_special", True) is not False:
            physics_mode = str(eve_cfg.get("physics_fri_mode", "soft")).lower()
            history_mode = str(eve_cfg.get("history_fri_mode", "soft")).lower()
            physics_exempt = _teacher_norm_set(eve_cfg.get("physics_friday_exempt_teachers", ()))
            history_exempt = _teacher_norm_set(eve_cfg.get("history_friday_exempt_teachers", ()))
            math_allowed = _teacher_norm_set(eve_cfg.get("math_friday_allowed_teachers", ()))
            p1 = period_names[0] if period_names else "晚自习1"
            p2 = period_names[1] if len(period_names) > 1 else "晚自习2"
            for (cls, subj), teacher in sorted(cst_names.items()):
                subj_norm = _night_soft_subject_norm(subj)
                teacher_norm = _teacher_norm(teacher)
                for day in day_names:
                    for period in period_names:
                        y_name = y_names.get((cls, subj, day, period))
                        if not y_name:
                            continue
                        if subj_norm == "物理" and day == "星期五" and physics_mode == "soft" and teacher_norm not in physics_exempt:
                            physics_math_terms[y_name] = w_physics_fri
                        if subj_norm == "历史" and day == "星期五" and history_mode == "soft" and teacher_norm not in history_exempt:
                            physics_math_terms[y_name] = w_history_fri
                        if subj_norm == "数学" and day == "星期五" and teacher_norm in math_allowed:
                            physics_math_terms[y_name] = w_math_fri_p1 if period == p1 else w_math_fri_p2
            for name, weight in sorted(physics_math_terms.items()):
                add_penalty(name, weight)

    objective = ObjectiveSpec(
        rule_id=rule_id,
        sense="minimize",
        expression=LinearExpression(tuple(objective_terms)),
    )
    ai_rule = AiRuleSpec(
        rule_id=rule_id,
        description="Night soft objective: head coverage, continuity, checkin repeat, subject sync, and Friday subject penalties.",
        enforcement="soft",
        priority=41,
        source="scheduler.model.constraints.soft_objective:apply_soft_objective",
    )
    problem = OptimizationProblemSpec(
        problem_id="scheduler_night_soft_objective",
        variables=tuple(variables),
        rules=(ai_rule,),
        constraints=tuple(constraints),
        objective=objective,
    )
    rule_first_plan = build_rule_first_plan(
        rules=problem.rules,
        constraints=problem.constraints,
        objective_rule_id=objective.rule_id,
    )
    return SchedulerGenericRuleBridge(
        problem=problem,
        rule_first_plan=rule_first_plan,
        metadata_by_rule={
            rule_id: {
                "scheduler_rule_id": rule_id,
                "legacy_apply_fn": "apply_soft_objective",
                "generic_contract_status": "covered_by_generic_contract",
                "runtime_rule_ids": generic_scheduler_rule_ids(),
                "constraint_family_counts": counts,
                "linear_constraint_count": linear_constraint_count,
                "enabled": enabled,
                "days": day_names,
                "periods": period_names,
                "cst": cst_names,
                "all_teachers": teacher_names,
                "male_heads": male_head_names,
                "female_heads": female_head_names,
                "on_teacher_day_variable_names": on_names,
                "y_variable_names": y_names,
                "checkin_m_variable_names": checkin_m_names,
                "checkin_f_variable_names": checkin_f_names,
                "miss_head_variable_names": miss_head_names,
                "adjacent_teacher_variable_names": adjacent_names,
                "sun_mon_variable_names": sun_mon_names,
                "fri_sun_mutex_variable_names": fri_sun_names,
                "yk_xxc_fri_mutex_variable_names": yk_xxc_names,
                "checkin_repeat_variable_names": checkin_repeat_names,
                "subject_sync_variable_names": subject_sync_names,
                "physics_math_direct_penalty_terms": physics_math_terms,
            }
        },
    )


def duty_joint_to_ai_or_problem(
    *,
    days: Sequence[Any],
    noon_male_duty_variable_names: Mapping[tuple[Any, Any], str] | None = None,
    noon_female_duty_variable_names: Mapping[tuple[Any, Any], str] | None = None,
    pm_pre_class_duty_variable_names: Mapping[tuple[Any, Any], str] | None = None,
    night_dorm_duty_male_variable_names: Mapping[tuple[Any, Any], str] | None = None,
    night_dorm_duty_female_variable_names: Mapping[tuple[Any, Any], str] | None = None,
    male_heads: Sequence[Any] = (),
    female_heads: Sequence[Any] = (),
    cfg: Any | None = None,
    rule_id: str = "joint.link.duty_joint_constraints",
) -> SchedulerGenericRuleBridge:
    """Compile cross-duty noon/pre-class/night linkage rules into OptimizationProblemSpec."""
    day_names = tuple(str(day) for day in days)
    male_head_names = tuple(str(teacher).strip() for teacher in male_heads if str(teacher).strip())
    female_head_names = tuple(str(teacher).strip() for teacher in female_heads if str(teacher).strip())
    enabled = bool(getattr(cfg, "enabled", True))

    def _map_names(raw: Mapping[tuple[Any, Any], str] | None) -> dict[tuple[str, str], str]:
        return {
            (str(teacher).strip(), str(day).strip()): str(name)
            for (teacher, day), name in (raw or {}).items()
            if str(teacher).strip() and str(day).strip() and str(name).strip()
        }

    noon_male_names = _map_names(noon_male_duty_variable_names)
    noon_female_names = _map_names(noon_female_duty_variable_names)
    pm_pre_names = _map_names(pm_pre_class_duty_variable_names)
    night_male_names = _map_names(night_dorm_duty_male_variable_names)
    night_female_names = _map_names(night_dorm_duty_female_variable_names)

    variables: list[VariableSpec] = []
    seen_variables: set[str] = set()
    constraints: list[LinearConstraintSpec] = []
    objective_terms: list[LinearTerm] = []
    variable_index = 1
    constraint_index = 1
    linear_constraint_count = 0
    constant_variable_count = 0
    counts = {
        "duty_joint_count_equalities": 0,
        "duty_joint_head_min_constraints": 0,
        "duty_joint_female_extra_total_constraints": 0,
        "duty_joint_noon_max_constraints": 0,
        "duty_joint_total_noon_night_max_constraints": 0,
        "duty_joint_male_target_constraints": 0,
        "duty_joint_male_no_night_constraints": 0,
        "duty_joint_female_min_constraints": 0,
        "duty_joint_female_two_duty_constraints": 0,
        "duty_joint_male_gap_constraints": 0,
        "duty_joint_male_balance_constraints": 0,
        "duty_joint_noon_pm_mutex_constraints": 0,
        "duty_joint_noon_night_mutex_constraints": 0,
        "duty_joint_pm_consecutive_constraints": 0,
        "duty_joint_penalty_terms": 0,
    }

    def add_variable(name: str, lb: int, ub: int, *, kind: str = "int") -> str:
        if name not in seen_variables:
            variables.append(VariableSpec(str(name), int(lb), int(ub), kind=kind))
            seen_variables.add(name)
        return name

    for name in sorted(
        {
            *noon_male_names.values(),
            *noon_female_names.values(),
            *pm_pre_names.values(),
            *night_male_names.values(),
            *night_female_names.values(),
        }
    ):
        add_variable(name, 0, 1, kind="bool")

    def next_var(tag: str, *parts: Any, lb: int = 0, ub: int = 1, kind: str = "int") -> str:
        nonlocal variable_index
        name = _duty_joint_var_name(variable_index, tag, *parts)
        variable_index += 1
        return add_variable(name, lb, ub, kind=kind)

    def add_linear(
        family: str,
        name: str,
        terms: Sequence[LinearTerm],
        sense: str,
        rhs: int,
        *,
        constant: int = 0,
        enforcement_literals: Sequence[BoolLiteralSpec | str] = (),
    ) -> None:
        nonlocal constraint_index, linear_constraint_count
        constraints.append(
            LinearConstraintSpec(
                name=f"{name}__{constraint_index:04d}",
                expression=LinearExpression(tuple(terms), int(constant)),
                sense=sense,
                rhs=int(rhs),
                rule_id=rule_id,
                enforcement_literals=tuple(enforcement_literals),
            )
        )
        counts[family] += 1
        linear_constraint_count += 1
        constraint_index += 1

    def add_penalty(name: str, weight: int) -> None:
        objective_terms.append(LinearTerm(name, int(weight)))
        counts["duty_joint_penalty_terms"] += 1

    def norm_mode(value: Any, default: str = "soft") -> str:
        mode = str(value or default).strip().lower()
        return mode if mode in {"hard", "soft"} else default

    def teacher_set(attr: str) -> set[str]:
        return set(_teacher_names(getattr(cfg, attr, ())))

    noon_count_names: dict[str, str] = {}
    night_count_names: dict[str, str] = {}
    total_count_names: dict[str, str] = {}
    female_extra_total_names: dict[str, str] = {}
    male_target_over_names: dict[str, str] = {}
    male_target_under_names: dict[str, str] = {}
    male_no_night_names: dict[str, str] = {}
    female_min_miss_names: dict[str, str] = {}
    female_two_duty_hit_names: dict[str, str] = {}
    male_gap_names: dict[str, str] = {}
    male_gap_excess_name = ""
    male_balance_dev_names: dict[str, str] = {}
    noon_any_names: dict[str, str] = {}
    night_any_names: dict[str, str] = {}
    pm_consecutive_violation_names: dict[str, str] = {}

    if enabled:
        f_except_cfg = teacher_set("female_total_limit_extra_teachers")
        m_balance_exclude = teacher_set("male_balance_exclude_teachers")
        m_total_eq2_exclude = teacher_set("male_total_eq2_exclude_teachers")
        noon_max1_teachers = teacher_set("noon_max1_teachers")
        total_noon_night_max1_teachers = teacher_set("total_noon_night_max1_teachers")
        male_noon_rule_exempt = teacher_set("male_noon_rule_exempt_teachers") | noon_max1_teachers
        f_main = tuple(sorted(set(female_head_names) - f_except_cfg))
        f_except = tuple(sorted(set(female_head_names) & f_except_cfg))
        m_main = tuple(sorted(set(male_head_names) - m_balance_exclude))
        all_teachers = tuple(
            sorted(
                {
                    *female_head_names,
                    *male_head_names,
                    *(teacher for teacher, _day in noon_male_names),
                    *(teacher for teacher, _day in noon_female_names),
                }
            )
        )

        for teacher in all_teachers:
            noon_terms = tuple(
                LinearTerm(name, 1)
                for day in day_names
                for name in (
                    noon_male_names.get((teacher, day)),
                    noon_female_names.get((teacher, day)),
                )
                if name
            )
            night_terms = tuple(
                LinearTerm(name, 1)
                for day in day_names
                for name in (
                    night_male_names.get((teacher, day)),
                    night_female_names.get((teacher, day)),
                )
                if name
            )
            noon_name = next_var("noon_count", teacher, lb=0, ub=max(0, len(noon_terms)))
            night_name = next_var("night_count", teacher, lb=0, ub=max(0, len(night_terms)))
            total_name = next_var("total_count", teacher, lb=0, ub=len(day_names) * 4)
            noon_count_names[teacher] = noon_name
            night_count_names[teacher] = night_name
            total_count_names[teacher] = total_name
            add_linear(
                "duty_joint_count_equalities",
                f"duty_joint__noon_count__{_safe_identifier(teacher)}",
                (LinearTerm(noon_name, 1), *(LinearTerm(term.variable, -term.coefficient) for term in noon_terms)),
                "==",
                0,
            )
            add_linear(
                "duty_joint_count_equalities",
                f"duty_joint__night_count__{_safe_identifier(teacher)}",
                (LinearTerm(night_name, 1), *(LinearTerm(term.variable, -term.coefficient) for term in night_terms)),
                "==",
                0,
            )
            add_linear(
                "duty_joint_count_equalities",
                f"duty_joint__total_count__{_safe_identifier(teacher)}",
                (LinearTerm(total_name, 1), LinearTerm(noon_name, -1), LinearTerm(night_name, -1)),
                "==",
                0,
            )

        for teacher in tuple(sorted(set(male_head_names) | set(female_head_names))):
            total_name = total_count_names.get(teacher)
            if total_name:
                add_linear(
                    "duty_joint_head_min_constraints",
                    f"duty_joint__head_min__{_safe_identifier(teacher)}",
                    (LinearTerm(total_name, 1),),
                    ">=",
                    1,
                )

        female_extra_mode = norm_mode(getattr(cfg, "female_head_extra_noon_mode", "hard"), "hard")
        enable_female_extra = bool(getattr(cfg, "enable_female_head_extra_noon_if_no_night", True)) and female_extra_mode == "hard"
        if not enable_female_extra:
            for teacher in f_main:
                total_name = total_count_names.get(teacher)
                if total_name:
                    add_linear(
                        "duty_joint_female_extra_total_constraints",
                        f"duty_joint__female_main_upper__{_safe_identifier(teacher)}",
                        (LinearTerm(total_name, 1),),
                        "<=",
                        1,
                    )
            for teacher in f_except:
                total_name = total_count_names.get(teacher)
                if total_name:
                    add_linear(
                        "duty_joint_female_extra_total_constraints",
                        f"duty_joint__female_except_upper__{_safe_identifier(teacher)}",
                        (LinearTerm(total_name, 1),),
                        "<=",
                        2,
                    )
        else:
            for teacher in tuple(sorted(set(female_head_names))):
                noon_terms = tuple(
                    LinearTerm(name, 1)
                    for (candidate, _day), name in sorted(noon_female_names.items())
                    if candidate == teacher
                )
                night_terms = tuple(
                    LinearTerm(name, 1)
                    for (candidate, _day), name in sorted(night_female_names.items())
                    if candidate == teacher
                )
                total_name = next_var("female_noon_night_total", teacher, lb=0, ub=len(day_names) * 2)
                female_extra_total_names[teacher] = total_name
                add_linear(
                    "duty_joint_female_extra_total_constraints",
                    f"duty_joint__female_extra_total__{_safe_identifier(teacher)}",
                    (
                        LinearTerm(total_name, 1),
                        *(LinearTerm(term.variable, -term.coefficient) for term in (*noon_terms, *night_terms)),
                    ),
                    "==",
                    0,
                )
                add_linear(
                    "duty_joint_female_extra_total_constraints",
                    f"duty_joint__female_extra_upper__{_safe_identifier(teacher)}",
                    (LinearTerm(total_name, 1),),
                    "<=",
                    2,
                )

        for teacher in tuple(sorted(noon_max1_teachers)):
            noon_name = noon_count_names.get(teacher)
            if noon_name:
                add_linear(
                    "duty_joint_noon_max_constraints",
                    f"duty_joint__noon_max1__{_safe_identifier(teacher)}",
                    (LinearTerm(noon_name, 1),),
                    "<=",
                    1,
                )

        for teacher in tuple(sorted(total_noon_night_max1_teachers)):
            total_name = total_count_names.get(teacher)
            if total_name:
                add_linear(
                    "duty_joint_total_noon_night_max_constraints",
                    f"duty_joint__total_noon_night_max1__{_safe_identifier(teacher)}",
                    (LinearTerm(total_name, 1),),
                    "<=",
                    1,
                )

        male_total_target = max(0, int(getattr(cfg, "male_total_target", 2)))
        male_total_target_mode = norm_mode(getattr(cfg, "male_total_target_mode", "hard"), "hard")
        for teacher in tuple(sorted(set(male_head_names) - m_total_eq2_exclude)):
            total_name = total_count_names.get(teacher)
            if not total_name:
                continue
            if male_total_target_mode == "hard":
                add_linear(
                    "duty_joint_male_target_constraints",
                    f"duty_joint__male_target_eq__{_safe_identifier(teacher)}",
                    (LinearTerm(total_name, 1),),
                    "==",
                    male_total_target,
                )
            else:
                ub = len(day_names) * 4
                over_name = next_var("male_total_over_target", teacher, lb=0, ub=ub)
                under_name = next_var("male_total_under_target", teacher, lb=0, ub=ub)
                male_target_over_names[teacher] = over_name
                male_target_under_names[teacher] = under_name
                add_linear(
                    "duty_joint_male_target_constraints",
                    f"duty_joint__male_target_over__{_safe_identifier(teacher)}",
                    (LinearTerm(over_name, 1), LinearTerm(total_name, -1)),
                    ">=",
                    -male_total_target,
                )
                add_linear(
                    "duty_joint_male_target_constraints",
                    f"duty_joint__male_target_under__{_safe_identifier(teacher)}",
                    (LinearTerm(under_name, 1), LinearTerm(total_name, 1)),
                    ">=",
                    male_total_target,
                )
                add_penalty(over_name, int(getattr(cfg, "w_male_total_target_deviation", 2500)))
                add_penalty(under_name, int(getattr(cfg, "w_male_total_target_deviation", 2500)))

        noon_teachers = {teacher for teacher, _day in noon_male_names} | {teacher for teacher, _day in noon_female_names}
        for teacher in tuple(sorted(set(male_head_names))):
            if teacher not in noon_teachers or teacher in male_noon_rule_exempt:
                continue
            noon_name = noon_count_names.get(teacher)
            night_name = night_count_names.get(teacher)
            if not noon_name or not night_name:
                continue
            no_night_name = next_var("male_no_night", teacher, lb=0, ub=1, kind="bool")
            male_no_night_names[teacher] = no_night_name
            add_linear(
                "duty_joint_male_no_night_constraints",
                f"duty_joint__male_no_night_eq_zero__{_safe_identifier(teacher)}",
                (LinearTerm(night_name, 1),),
                "==",
                0,
                enforcement_literals=(no_night_name,),
            )
            add_linear(
                "duty_joint_male_no_night_constraints",
                f"duty_joint__male_has_night__{_safe_identifier(teacher)}",
                (LinearTerm(night_name, 1),),
                ">=",
                1,
                enforcement_literals=(BoolLiteralSpec(no_night_name, negated=True),),
            )
            add_linear(
                "duty_joint_male_no_night_constraints",
                f"duty_joint__male_no_night_noon_eq_two__{_safe_identifier(teacher)}",
                (LinearTerm(noon_name, 1),),
                "==",
                2,
                enforcement_literals=(no_night_name,),
            )
            add_linear(
                "duty_joint_male_no_night_constraints",
                f"duty_joint__male_has_night_noon_le_one__{_safe_identifier(teacher)}",
                (LinearTerm(noon_name, 1),),
                "<=",
                1,
                enforcement_literals=(BoolLiteralSpec(no_night_name, negated=True),),
            )

        female_min_mode = norm_mode(getattr(cfg, "female_min_noon_night_mode", "soft"), "soft")
        for teacher in tuple(sorted(set(female_head_names))):
            total_name = total_count_names.get(teacher)
            if not total_name:
                continue
            if female_min_mode == "hard":
                add_linear(
                    "duty_joint_female_min_constraints",
                    f"duty_joint__female_min_hard__{_safe_identifier(teacher)}",
                    (LinearTerm(total_name, 1),),
                    ">=",
                    1,
                )
            else:
                miss_name = next_var("female_min_noon_night_miss", teacher, lb=0, ub=1)
                female_min_miss_names[teacher] = miss_name
                add_linear(
                    "duty_joint_female_min_constraints",
                    f"duty_joint__female_min_miss__{_safe_identifier(teacher)}",
                    (LinearTerm(miss_name, 1), LinearTerm(total_name, 1)),
                    ">=",
                    1,
                )
                add_penalty(miss_name, int(getattr(cfg, "w_female_min_noon_night", 2000)))

        if bool(getattr(cfg, "enable_female_two_duty_penalty", True)):
            for teacher in tuple(sorted(set(female_head_names))):
                total_name = total_count_names.get(teacher)
                if not total_name:
                    continue
                hit_name = next_var("female_two_duty_hit", teacher, lb=0, ub=1, kind="bool")
                female_two_duty_hit_names[teacher] = hit_name
                add_linear(
                    "duty_joint_female_two_duty_constraints",
                    f"duty_joint__female_two_hit_lower__{_safe_identifier(teacher)}",
                    (LinearTerm(total_name, 1),),
                    ">=",
                    2,
                    enforcement_literals=(hit_name,),
                )
                add_linear(
                    "duty_joint_female_two_duty_constraints",
                    f"duty_joint__female_two_hit_upper__{_safe_identifier(teacher)}",
                    (LinearTerm(total_name, 1),),
                    "<=",
                    1,
                    enforcement_literals=(BoolLiteralSpec(hit_name, negated=True),),
                )
                add_penalty(hit_name, int(getattr(cfg, "w_female_two_duty_penalty", 3000)))

        male_max_min_mode = norm_mode(getattr(cfg, "male_max_min_mode", "soft"), "soft")
        if m_main:
            ub = len(day_names) * 4
            min_total_name = next_var("male_min_total", lb=0, ub=ub)
            max_total_name = next_var("male_max_total", lb=0, ub=ub)
            gap_name = next_var("male_gap", lb=0, ub=ub)
            male_gap_names["min_total"] = min_total_name
            male_gap_names["max_total"] = max_total_name
            male_gap_names["gap"] = gap_name
            for teacher in m_main:
                total_name = total_count_names.get(teacher)
                if not total_name:
                    continue
                add_linear(
                    "duty_joint_male_gap_constraints",
                    f"duty_joint__male_total_ge_min__{_safe_identifier(teacher)}",
                    (LinearTerm(total_name, 1), LinearTerm(min_total_name, -1)),
                    ">=",
                    0,
                )
                add_linear(
                    "duty_joint_male_gap_constraints",
                    f"duty_joint__male_total_le_max__{_safe_identifier(teacher)}",
                    (LinearTerm(total_name, 1), LinearTerm(max_total_name, -1)),
                    "<=",
                    0,
                )
            add_linear(
                "duty_joint_male_gap_constraints",
                "duty_joint__male_gap_eq",
                (LinearTerm(gap_name, 1), LinearTerm(max_total_name, -1), LinearTerm(min_total_name, 1)),
                "==",
                0,
            )
            if male_max_min_mode == "hard":
                add_linear(
                    "duty_joint_male_gap_constraints",
                    "duty_joint__male_gap_hard",
                    (LinearTerm(gap_name, 1),),
                    "<=",
                    1,
                )
            else:
                male_gap_excess_name = next_var("male_gap_excess", lb=0, ub=ub)
                male_gap_names["gap_excess"] = male_gap_excess_name
                add_linear(
                    "duty_joint_male_gap_constraints",
                    "duty_joint__male_gap_excess",
                    (LinearTerm(male_gap_excess_name, 1), LinearTerm(gap_name, -1)),
                    ">=",
                    -1,
                )
                add_penalty(male_gap_excess_name, int(getattr(cfg, "w_male_max_min_gap", 600)))

            if bool(getattr(cfg, "enable_soft_male_duty_balance", True)):
                for teacher in m_main:
                    total_name = total_count_names.get(teacher)
                    if not total_name:
                        continue
                    dev_name = next_var("male_dev", teacher, lb=0, ub=len(day_names) * 4)
                    male_balance_dev_names[teacher] = dev_name
                    add_linear(
                        "duty_joint_male_balance_constraints",
                        f"duty_joint__male_dev__{_safe_identifier(teacher)}",
                        (LinearTerm(dev_name, 1), LinearTerm(total_name, -1), LinearTerm(min_total_name, 1)),
                        "==",
                        0,
                    )
                    add_penalty(dev_name, int(getattr(cfg, "w_soft_male_duty_balance", 60)))

        union_teachers = tuple(sorted(set(all_teachers) | {teacher for teacher, _day in pm_pre_names}))
        for teacher in union_teachers:
            for day in day_names:
                noon_terms = tuple(
                    name
                    for name in (
                        noon_male_names.get((teacher, day)),
                        noon_female_names.get((teacher, day)),
                    )
                    if name
                )
                if noon_terms:
                    noon_any_name = next_var("noon_any", teacher, day, lb=0, ub=len(noon_terms))
                    noon_any_names[_teacher_day_key(teacher, day)] = noon_any_name
                    add_linear(
                        "duty_joint_noon_pm_mutex_constraints",
                        f"duty_joint__noon_any__{_safe_identifier(teacher)}__{_safe_identifier(day)}",
                        (LinearTerm(noon_any_name, 1), *(LinearTerm(name, -1) for name in noon_terms)),
                        "==",
                        0,
                    )
                    noon_any_terms = (LinearTerm(noon_any_name, 1),)
                else:
                    constant_variable_count += 1
                    noon_any_terms = ()
                pm_name = pm_pre_names.get((teacher, day))
                if pm_name:
                    pm_terms = (LinearTerm(pm_name, 1),)
                else:
                    constant_variable_count += 1
                    pm_terms = ()
                add_linear(
                    "duty_joint_noon_pm_mutex_constraints",
                    f"duty_joint__noon_pm_mutex__{_safe_identifier(teacher)}__{_safe_identifier(day)}",
                    (*noon_any_terms, *pm_terms),
                    "<=",
                    1,
                )

                night_terms = tuple(
                    name
                    for name in (
                        night_male_names.get((teacher, day)),
                        night_female_names.get((teacher, day)),
                    )
                    if name
                )
                if night_terms:
                    night_any_name = next_var("night_any", teacher, day, lb=0, ub=len(night_terms))
                    night_any_names[_teacher_day_key(teacher, day)] = night_any_name
                    add_linear(
                        "duty_joint_noon_night_mutex_constraints",
                        f"duty_joint__night_any__{_safe_identifier(teacher)}__{_safe_identifier(day)}",
                        (LinearTerm(night_any_name, 1), *(LinearTerm(name, -1) for name in night_terms)),
                        "==",
                        0,
                    )
                    night_any_terms = (LinearTerm(night_any_name, 1),)
                else:
                    constant_variable_count += 1
                    night_any_terms = ()
                add_linear(
                    "duty_joint_noon_night_mutex_constraints",
                    f"duty_joint__noon_night_mutex__{_safe_identifier(teacher)}__{_safe_identifier(day)}",
                    (*noon_any_terms, *night_any_terms),
                    "<=",
                    1,
                )

        pm_consecutive_mode = norm_mode(getattr(cfg, "pm_pre_class_no_consecutive_mode", "hard"), "hard")
        pm_teachers = tuple(sorted({teacher for teacher, _day in pm_pre_names}))
        for teacher in pm_teachers:
            for day_1, day_2 in calendar_adjacent_day_pairs(day_names, include_sun_mon=True):
                left = pm_pre_names.get((teacher, day_1))
                right = pm_pre_names.get((teacher, day_2))
                if not left or not right:
                    continue
                if pm_consecutive_mode == "hard":
                    add_linear(
                        "duty_joint_pm_consecutive_constraints",
                        f"duty_joint__pm_no_consecutive__{_safe_identifier(teacher)}__{_safe_identifier(day_1)}__{_safe_identifier(day_2)}",
                        (LinearTerm(left, 1), LinearTerm(right, 1)),
                        "<=",
                        1,
                    )
                else:
                    violation_name = next_var("pm_pre_consecutive", teacher, day_1, day_2, lb=0, ub=1, kind="bool")
                    pm_consecutive_violation_names[_teacher_day_key(teacher, f"{day_1}->{day_2}")] = violation_name
                    add_linear(
                        "duty_joint_pm_consecutive_constraints",
                        f"duty_joint__pm_consecutive_upper_left__{_safe_identifier(teacher)}__{_safe_identifier(day_1)}__{_safe_identifier(day_2)}",
                        (LinearTerm(violation_name, 1), LinearTerm(left, -1)),
                        "<=",
                        0,
                    )
                    add_linear(
                        "duty_joint_pm_consecutive_constraints",
                        f"duty_joint__pm_consecutive_upper_right__{_safe_identifier(teacher)}__{_safe_identifier(day_1)}__{_safe_identifier(day_2)}",
                        (LinearTerm(violation_name, 1), LinearTerm(right, -1)),
                        "<=",
                        0,
                    )
                    add_linear(
                        "duty_joint_pm_consecutive_constraints",
                        f"duty_joint__pm_consecutive_lower__{_safe_identifier(teacher)}__{_safe_identifier(day_1)}__{_safe_identifier(day_2)}",
                        (LinearTerm(violation_name, 1), LinearTerm(left, -1), LinearTerm(right, -1)),
                        ">=",
                        -1,
                    )
                    add_penalty(violation_name, int(getattr(cfg, "w_pm_pre_class_no_consecutive", 2000)))
    else:
        f_main = ()
        f_except = ()
        m_main = ()

    objective = ObjectiveSpec(
        rule_id=rule_id,
        sense="minimize",
        expression=LinearExpression(tuple(objective_terms)),
    )
    ai_rule = AiRuleSpec(
        rule_id=rule_id,
        description="Joint rule: link noon dorm duty, pre-class duty, and night dorm duty through shared teachers.",
        enforcement="soft",
        priority=40,
        source="scheduler.model.constraints.duty_joint_constraints:add_duty_joint_constraints",
    )
    problem = OptimizationProblemSpec(
        problem_id="scheduler_duty_joint_constraints",
        variables=tuple(variables),
        rules=(ai_rule,),
        constraints=tuple(constraints),
        objective=objective,
    )
    rule_first_plan = build_rule_first_plan(
        rules=problem.rules,
        constraints=problem.constraints,
        objective_rule_id=objective.rule_id,
    )
    return SchedulerGenericRuleBridge(
        problem=problem,
        rule_first_plan=rule_first_plan,
        metadata_by_rule={
            rule_id: {
                "scheduler_rule_id": rule_id,
                "legacy_apply_fn": "add_duty_joint_constraints",
                "generic_contract_status": "covered_by_generic_contract",
                "runtime_rule_ids": generic_scheduler_rule_ids(),
                "constraint_family_counts": counts,
                "linear_constraint_count": linear_constraint_count,
                "constant_variable_count": constant_variable_count,
                "enabled": enabled,
                "days": day_names,
                "male_heads": male_head_names,
                "female_heads": female_head_names,
                "M_MAIN": m_main,
                "F_MAIN": f_main,
                "F_EXCEPT": f_except,
                "noon_male_duty_variable_names": noon_male_names,
                "noon_female_duty_variable_names": noon_female_names,
                "pm_pre_class_duty_variable_names": pm_pre_names,
                "night_dorm_duty_male_variable_names": night_male_names,
                "night_dorm_duty_female_variable_names": night_female_names,
                "noon_count_variable_names": noon_count_names,
                "night_count_variable_names": night_count_names,
                "total_count_variable_names": total_count_names,
                "female_extra_total_variable_names": female_extra_total_names,
                "male_target_over_variable_names": male_target_over_names,
                "male_target_under_variable_names": male_target_under_names,
                "male_no_night_variable_names": male_no_night_names,
                "female_min_miss_variable_names": female_min_miss_names,
                "female_two_duty_hit_variable_names": female_two_duty_hit_names,
                "male_gap_variable_names": male_gap_names,
                "male_gap_excess_variable_name": male_gap_excess_name,
                "male_balance_dev_variable_names": male_balance_dev_names,
                "noon_any_variable_names": noon_any_names,
                "night_any_variable_names": night_any_names,
                "pm_consecutive_violation_variable_names": pm_consecutive_violation_names,
            }
        },
    )


def grade_group_duty_to_ai_or_problem(
    *,
    days: Sequence[Any],
    members: Sequence[Any],
    all_teachers: Sequence[Any],
    cfg: Any | None = None,
    on_teacher_day_variable_names: Mapping[tuple[Any, Any], str] | None = None,
    rule_id: str = "joint.link.grade_group_duty_constraints",
) -> SchedulerGenericRuleBridge:
    """Compile grade-group duty assignment and soft linkage rules into OptimizationProblemSpec."""
    day_names = tuple(str(day) for day in days)
    member_names = tuple(str(member).strip() for member in members if str(member).strip())
    all_teacher_names = tuple(str(teacher).strip() for teacher in all_teachers if str(teacher).strip())
    enabled = bool(getattr(cfg, "enabled", True))
    min_once_mode = str(getattr(cfg, "min_once_mode", "hard") or "hard").strip().lower()
    if min_once_mode not in {"hard", "soft"}:
        min_once_mode = "hard"
    daily_need_night_mode = str(getattr(cfg, "daily_need_night_mode", "soft") or "soft").strip().lower()
    if daily_need_night_mode not in {"hard", "soft"}:
        daily_need_night_mode = "soft"
    w_daily_need_night = int(getattr(cfg, "w_daily_need_night", 2000))
    w_min_once = int(getattr(cfg, "w_min_once", 1000))
    w_no_night_penalty = int(getattr(cfg, "w_no_night_penalty", 1000))
    enable_fairness = bool(getattr(cfg, "enable_fairness", True))
    w_fairness_balance = int(getattr(cfg, "w_fairness_balance", 100))

    variables: list[VariableSpec] = []
    constraints: list[LinearConstraintSpec] = []
    objective_terms: list[LinearTerm] = []
    on_teacher_day_names: dict[str, str] = {}
    variable_index = 1
    for teacher in all_teacher_names:
        for day in day_names:
            key = _teacher_day_key(teacher, day)
            supplied_name = None
            if on_teacher_day_variable_names is not None:
                supplied_name = on_teacher_day_variable_names.get((teacher, day))
            name = str(supplied_name or _grade_group_var_name(variable_index, "on_teacher_day", teacher, day))
            variable_index += 1
            on_teacher_day_names[key] = name
            variables.append(VariableSpec.bool(name))

    counts = {
        "grade_group_daily_need_night_presence_constraints": 0,
        "grade_group_daily_need_night_miss_constraints": 0,
        "grade_group_duty_assignment_constraints": 0,
        "grade_group_min_once_count_constraints": 0,
        "grade_group_min_once_miss_constraints": 0,
        "grade_group_no_night_constraints": 0,
        "grade_group_no_night_violation_constraints": 0,
        "grade_group_fairness_constraints": 0,
        "grade_group_penalty_terms": 0,
    }
    linear_constraint_count = 0
    constraint_index = 1

    def add_linear(family: str, name: str, terms: Sequence[LinearTerm], sense: str, rhs: int) -> None:
        nonlocal constraint_index, linear_constraint_count
        constraints.append(
            LinearConstraintSpec(
                name=f"{name}__{constraint_index:04d}",
                expression=LinearExpression(tuple(terms)),
                sense=sense,
                rhs=int(rhs),
                rule_id=rule_id,
            )
        )
        counts[family] += 1
        linear_constraint_count += 1
        constraint_index += 1

    def add_and2(family: str, prefix: str, output: str, left: str, right: str) -> None:
        add_linear(
            family,
            f"{prefix}__upper_left__{_safe_identifier(output)}",
            (LinearTerm(output, 1), LinearTerm(left, -1)),
            "<=",
            0,
        )
        add_linear(
            family,
            f"{prefix}__upper_right__{_safe_identifier(output)}",
            (LinearTerm(output, 1), LinearTerm(right, -1)),
            "<=",
            0,
        )
        add_linear(
            family,
            f"{prefix}__lower__{_safe_identifier(output)}",
            (LinearTerm(output, 1), LinearTerm(left, -1), LinearTerm(right, -1)),
            ">=",
            -1,
        )

    group_has_night_names: dict[str, str] = {}
    daily_need_miss_names: dict[str, str] = {}
    grade_duty_names: dict[str, str] = {}
    week_count_names: dict[str, str] = {}
    min_once_miss_names: dict[str, str] = {}
    no_night_names: dict[str, str] = {}
    no_night_violation_names: dict[str, str] = {}
    fairness_count_names: dict[str, str] = {}
    fairness_dev_names: dict[str, str] = {}
    fairness_min_count_name = ""
    member_night_key = {
        member: _find_teacher_key_by_norm(all_teacher_names, member)
        for member in member_names
    }

    if enabled and member_names and day_names:
        daily_need_days = tuple(day for day in day_names if day not in {"星期六", "星期日"})
        for day in daily_need_days:
            group_key = str(day)
            group_name = _grade_group_var_name(variable_index, "group_has_night", day)
            variable_index += 1
            variables.append(VariableSpec.bool(group_name))
            group_has_night_names[group_key] = group_name
            has_night_names = tuple(
                on_teacher_day_names[_teacher_day_key(night_key, day)]
                for member in member_names
                for night_key in (member_night_key.get(member),)
                if night_key and _teacher_day_key(night_key, day) in on_teacher_day_names
            )
            if has_night_names:
                add_linear(
                    "grade_group_daily_need_night_presence_constraints",
                    f"grade_group_duty__daily_has_lower__{_safe_identifier(day)}",
                    (*(LinearTerm(name, 1) for name in has_night_names), LinearTerm(group_name, -1)),
                    ">=",
                    0,
                )
                for name in has_night_names:
                    add_linear(
                        "grade_group_daily_need_night_presence_constraints",
                        f"grade_group_duty__daily_has_upper__{_safe_identifier(name)}",
                        (LinearTerm(name, 1), LinearTerm(group_name, -1)),
                        "<=",
                        0,
                    )
            else:
                add_linear(
                    "grade_group_daily_need_night_presence_constraints",
                    f"grade_group_duty__daily_has_zero__{_safe_identifier(day)}",
                    (LinearTerm(group_name, 1),),
                    "==",
                    0,
                )
            if daily_need_night_mode == "hard":
                add_linear(
                    "grade_group_daily_need_night_miss_constraints",
                    f"grade_group_duty__daily_has_hard__{_safe_identifier(day)}",
                    (LinearTerm(group_name, 1),),
                    "==",
                    1,
                )
            else:
                miss_name = _grade_group_var_name(variable_index, "daily_need_miss", day)
                variable_index += 1
                variables.append(VariableSpec.bool(miss_name))
                daily_need_miss_names[group_key] = miss_name
                add_linear(
                    "grade_group_daily_need_night_miss_constraints",
                    f"grade_group_duty__daily_miss_eq__{_safe_identifier(day)}",
                    (LinearTerm(miss_name, 1), LinearTerm(group_name, 1)),
                    "==",
                    1,
                )
                objective_terms.append(LinearTerm(miss_name, w_daily_need_night))
                counts["grade_group_penalty_terms"] += 1

        for member in member_names:
            for day in day_names:
                duty_key = _teacher_day_key(member, day)
                duty_name = _grade_group_var_name(variable_index, "grade_duty", member, day)
                variable_index += 1
                variables.append(VariableSpec.bool(duty_name))
                grade_duty_names[duty_key] = duty_name

        no_duty_days = {"星期六", "星期日"}
        for day in day_names:
            duty_names = tuple(grade_duty_names[_teacher_day_key(member, day)] for member in member_names)
            if day in no_duty_days:
                for name in duty_names:
                    add_linear(
                        "grade_group_duty_assignment_constraints",
                        f"grade_group_duty__no_duty_day__{_safe_identifier(name)}",
                        (LinearTerm(name, 1),),
                        "==",
                        0,
                    )
            else:
                add_linear(
                    "grade_group_duty_assignment_constraints",
                    f"grade_group_duty__daily_exactly_one__{_safe_identifier(day)}",
                    tuple(LinearTerm(name, 1) for name in duty_names),
                    "==",
                    1,
                )

        active_days = tuple(day for day in day_names if day not in no_duty_days)
        for member in member_names:
            if not active_days:
                break
            count_name = _grade_group_var_name(variable_index, "week_count", member)
            variable_index += 1
            variables.append(VariableSpec(count_name, 0, len(active_days)))
            week_count_names[member] = count_name
            add_linear(
                "grade_group_min_once_count_constraints",
                f"grade_group_duty__min_once_count__{_safe_identifier(member)}",
                (
                    LinearTerm(count_name, 1),
                    *(LinearTerm(grade_duty_names[_teacher_day_key(member, day)], -1) for day in active_days),
                ),
                "==",
                0,
            )
            if min_once_mode == "hard":
                add_linear(
                    "grade_group_min_once_miss_constraints",
                    f"grade_group_duty__min_once_hard__{_safe_identifier(member)}",
                    (LinearTerm(count_name, 1),),
                    ">=",
                    1,
                )
            else:
                miss_name = _grade_group_var_name(variable_index, "min_once_miss", member)
                variable_index += 1
                variables.append(VariableSpec.bool(miss_name))
                min_once_miss_names[member] = miss_name
                add_linear(
                    "grade_group_min_once_miss_constraints",
                    f"grade_group_duty__min_once_miss__{_safe_identifier(member)}",
                    (LinearTerm(miss_name, 1), LinearTerm(count_name, 1)),
                    ">=",
                    1,
                )
                objective_terms.append(LinearTerm(miss_name, w_min_once))
                counts["grade_group_penalty_terms"] += 1

        for member in member_names:
            night_key = member_night_key.get(member)
            for day in day_names:
                duty_name = grade_duty_names[_teacher_day_key(member, day)]
                has_night_name = (
                    on_teacher_day_names.get(_teacher_day_key(night_key, day))
                    if night_key is not None
                    else None
                )
                no_night_name = _grade_group_var_name(variable_index, "no_night", member, day)
                variable_index += 1
                variables.append(VariableSpec.bool(no_night_name))
                no_night_names[_teacher_day_key(member, day)] = no_night_name
                if has_night_name:
                    add_linear(
                        "grade_group_no_night_constraints",
                        f"grade_group_duty__no_night_eq__{_safe_identifier(member)}__{_safe_identifier(day)}",
                        (LinearTerm(no_night_name, 1), LinearTerm(has_night_name, 1)),
                        "==",
                        1,
                    )
                else:
                    add_linear(
                        "grade_group_no_night_constraints",
                        f"grade_group_duty__no_night_const__{_safe_identifier(member)}__{_safe_identifier(day)}",
                        (LinearTerm(no_night_name, 1),),
                        "==",
                        1,
                    )
                violation_name = _grade_group_var_name(variable_index, "no_night_viol", member, day)
                variable_index += 1
                variables.append(VariableSpec.bool(violation_name))
                no_night_violation_names[_teacher_day_key(member, day)] = violation_name
                add_and2(
                    "grade_group_no_night_violation_constraints",
                    "grade_group_duty__no_night_viol",
                    violation_name,
                    duty_name,
                    no_night_name,
                )
                objective_terms.append(LinearTerm(violation_name, w_no_night_penalty))
                counts["grade_group_penalty_terms"] += 1

        if enable_fairness and active_days:
            ub = len(active_days)
            fairness_min_count_name = _grade_group_var_name(variable_index, "min_count")
            variable_index += 1
            variables.append(VariableSpec(fairness_min_count_name, 0, ub))
            for member in member_names:
                count_name = _grade_group_var_name(variable_index, "fairness_count", member)
                variable_index += 1
                variables.append(VariableSpec(count_name, 0, ub))
                fairness_count_names[member] = count_name
                add_linear(
                    "grade_group_fairness_constraints",
                    f"grade_group_duty__fairness_count__{_safe_identifier(member)}",
                    (
                        LinearTerm(count_name, 1),
                        *(LinearTerm(grade_duty_names[_teacher_day_key(member, day)], -1) for day in active_days),
                    ),
                    "==",
                    0,
                )
                add_linear(
                    "grade_group_fairness_constraints",
                    f"grade_group_duty__fairness_min__{_safe_identifier(member)}",
                    (LinearTerm(count_name, 1), LinearTerm(fairness_min_count_name, -1)),
                    ">=",
                    0,
                )
                dev_name = _grade_group_var_name(variable_index, "fairness_dev", member)
                variable_index += 1
                variables.append(VariableSpec(dev_name, 0, ub))
                fairness_dev_names[member] = dev_name
                add_linear(
                    "grade_group_fairness_constraints",
                    f"grade_group_duty__fairness_dev__{_safe_identifier(member)}",
                    (
                        LinearTerm(dev_name, 1),
                        LinearTerm(count_name, -1),
                        LinearTerm(fairness_min_count_name, 1),
                    ),
                    "==",
                    0,
                )
                objective_terms.append(LinearTerm(dev_name, w_fairness_balance))
                counts["grade_group_penalty_terms"] += 1

    objective = ObjectiveSpec(
        rule_id=rule_id,
        sense="minimize",
        expression=LinearExpression(tuple(objective_terms)),
    )
    ai_rule = AiRuleSpec(
        rule_id=rule_id,
        description="Joint rule: assign grade-group duty and penalize missing night-duty linkage and imbalance.",
        enforcement="soft",
        priority=39,
        source="scheduler.model.constraints.grade_group_duty_constraints:apply_grade_group_duty_constraints",
    )
    problem = OptimizationProblemSpec(
        problem_id="scheduler_grade_group_duty_constraints",
        variables=tuple(variables),
        rules=(ai_rule,),
        constraints=tuple(constraints),
        objective=objective,
    )
    rule_first_plan = build_rule_first_plan(
        rules=problem.rules,
        constraints=problem.constraints,
        objective_rule_id=objective.rule_id,
    )
    return SchedulerGenericRuleBridge(
        problem=problem,
        rule_first_plan=rule_first_plan,
        metadata_by_rule={
            rule_id: {
                "scheduler_rule_id": rule_id,
                "legacy_apply_fn": "apply_grade_group_duty_constraints",
                "generic_contract_status": "covered_by_generic_contract",
                "runtime_rule_ids": generic_scheduler_rule_ids(),
                "constraint_family_counts": counts,
                "linear_constraint_count": linear_constraint_count,
                "enabled": enabled,
                "members": member_names,
                "days": day_names,
                "member_night_key": member_night_key,
                "on_teacher_day_variable_names": on_teacher_day_names,
                "group_has_night_variable_names": group_has_night_names,
                "daily_need_miss_variable_names": daily_need_miss_names,
                "grade_duty_variable_names": grade_duty_names,
                "week_count_variable_names": week_count_names,
                "min_once_miss_variable_names": min_once_miss_names,
                "no_night_variable_names": no_night_names,
                "no_night_violation_variable_names": no_night_violation_names,
                "fairness_count_variable_names": fairness_count_names,
                "fairness_dev_variable_names": fairness_dev_names,
                "fairness_min_count_variable_name": fairness_min_count_name,
                "min_once_mode": min_once_mode,
                "daily_need_night_mode": daily_need_night_mode,
                "enable_fairness": enable_fairness,
                "w_daily_need_night": w_daily_need_night,
                "w_min_once": w_min_once,
                "w_no_night_penalty": w_no_night_penalty,
                "w_fairness_balance": w_fairness_balance,
            }
        },
    )


def _day_candidate_assignment_names(data: Any) -> tuple[tuple[str, str, Any, str], ...]:
    fixed_by_cls = {
        str(cls): {slot for (fixed_cls, slot), _subj in getattr(data, "fixed_assign", {}).items() if str(fixed_cls) == str(cls)}
        for cls in _text_tuple(data.classes)
    }
    subjects_by_cls: dict[str, tuple[str, ...]] = {}
    for cls, subj in getattr(data, "cls_subj_teacher", {}).keys():
        subjects_by_cls.setdefault(str(cls), tuple())
        subjects_by_cls[str(cls)] = tuple(sorted({*subjects_by_cls[str(cls)], str(subj)}))

    out: list[tuple[str, str, Any, str]] = []
    index = 1
    for cls in _text_tuple(data.classes):
        for slot in tuple(data.available_slots):
            if slot in fixed_by_cls.get(cls, set()):
                continue
            for subj in subjects_by_cls.get(cls, ()):
                if _is_day_subject_banned(data, cls, subj, slot):
                    continue
                name = _day_assignment_var_name(index, cls, subj, str(slot.day), _slot_label(slot))
                out.append((cls, subj, slot, name))
                index += 1
    return tuple(out)


def _is_day_subject_banned(data: Any, cls: str, subj: str, slot: Any) -> bool:
    subject_ban_slots = getattr(data, "subject_ban_slots", {}) or {}
    banned_slots = subject_ban_slots.get(subj, set())
    if slot not in banned_slots:
        return False
    return _is_day_teacher_slot_ban_exemption(data, cls, subj, slot)


def _is_day_teacher_slot_ban_exemption(data: Any, cls: str, subj: str, slot: Any) -> bool:
    teacher = str(getattr(data, "cls_subj_teacher", {}).get((cls, subj), "")).replace(" ", "")
    subj_norm = str(subj).strip()
    for item in getattr(data, "teacher_slot_ban_exemptions", []) or []:
        if not isinstance(item, dict):
            continue
        target_teacher = str(item.get("teacher", "")).replace(" ", "")
        subjects = {str(x).strip() for x in (item.get("subjects", []) or []) if str(x).strip()}
        if teacher != target_teacher or (subjects and subj_norm not in subjects):
            continue
        if str(slot.day) != str(item.get("day", "")).strip():
            continue
        if str(slot.block) != str(item.get("block", "")).strip():
            continue
        if int(slot.period) != int(item.get("period", 0)):
            continue
        return True
    return False


def _assignment_key(cls: str, subj: str, day: str, period: str) -> str:
    return f"{cls}|{subj}|{day}|{period}"


def _slot_label(slot: Any) -> str:
    return f"{slot.block}{int(slot.period)}"


def _day_hour_bucket(slot: Any) -> str:
    if str(slot.block) == "早自习":
        return "early"
    if is_weekday_day(str(slot.day)):
        return "weekday"
    return "weekend"


def _teacher_slot_key(teacher: str, slot: Any) -> str:
    return f"{teacher}|{slot.day}|{_slot_label(slot)}"


def _teacher_class_slot_key(teacher: str, cls: str, slot: Any) -> str:
    return f"{teacher}|{cls}|{slot.day}|{_slot_label(slot)}"


def _teacher_class_day_key(teacher: str, cls: str, day: str) -> str:
    return f"{teacher}|{cls}|{day}"


def _teacher_class_adjacent_key(teacher: str, cls: str, day: str, slot_1: Any, slot_2: Any) -> str:
    return f"{cls}|{teacher}|{day}|{_slot_label(slot_1)}__{_slot_label(slot_2)}"


def _teacher_class_slot_expr_parts(
    data: Any,
    fixed_assign: Mapping[Any, Any],
    names_by_teacher_class_slot: Mapping[tuple[str, str, Any], Sequence[str]],
    teacher: str,
    cls: str,
    slot: Any,
) -> tuple[tuple[str, ...], int]:
    fixed_subj = fixed_assign.get((cls, slot))
    if fixed_subj is not None:
        fixed_teacher = getattr(data, "cls_subj_teacher", {}).get((cls, fixed_subj))
        return (), 1 if str(fixed_teacher) == teacher else 0
    return tuple(names_by_teacher_class_slot.get((teacher, cls, slot), ())), 0


def _day_class_subject_slot_expr_parts(
    fixed_assign: Mapping[Any, Any],
    names_by_class_subject_slot: Mapping[tuple[str, str, Any], Sequence[str]],
    cls: str,
    subj: str,
    slot: Any,
) -> tuple[tuple[str, ...], int]:
    fixed_subj = fixed_assign.get((cls, slot))
    if fixed_subj is not None:
        return (), 1 if str(fixed_subj) == str(subj) else 0
    return tuple(names_by_class_subject_slot.get((cls, subj, slot), ())), 0


def _teacher_day_key(teacher: str, day: str) -> str:
    return f"{teacher}|{day}"


def _class_subject_key(cls: str, subj: str) -> str:
    return f"{cls}|{subj}"


def _class_subject_day_key(cls: str, subj: str, day: str) -> str:
    return f"{cls}|{subj}|{day}"


def _teacher_day_period_key(teacher: str, day: str, tag: str) -> str:
    return f"{teacher}|{day}|{tag}"


def _teacher_continuity_busy_bool_name(index: int, teacher: str, day: str, slot: Any) -> str:
    return "__".join(
        (
            "teacher_continuity_busy",
            f"{index:04d}",
            _safe_identifier(teacher),
            _safe_identifier(day),
            _safe_identifier(_slot_label(slot)),
        )
    )


def _teacher_continuity_gap_bool_name(index: int, teacher: str, day: str, tag: str, gap_index: int) -> str:
    return "__".join(
        (
            "teacher_continuity_gap",
            f"{index:04d}",
            _safe_identifier(teacher),
            _safe_identifier(day),
            _safe_identifier(tag),
            str(int(gap_index)),
        )
    )


def _two_class_daily_min_bool_name(index: int, tag: str, teacher: str, day: str, cls: str | None = None) -> str:
    parts = [
        "two_class_daily_min",
        f"{index:04d}",
        _safe_identifier(tag),
        _safe_identifier(teacher),
        _safe_identifier(day),
    ]
    if cls is not None:
        parts.append(_safe_identifier(cls))
    return "__".join(parts)


def _teacher_m1_occ_bool_name(index: int, teacher: str, day: str) -> str:
    return "__".join(
        (
            "teacher_m1_occ",
            f"{index:04d}",
            _safe_identifier(teacher),
            _safe_identifier(day),
        )
    )


def _teacher_m1_total_var_name(index: int, teacher: str) -> str:
    return "__".join(
        (
            "teacher_m1_total",
            f"{index:04d}",
            _safe_identifier(teacher),
        )
    )


def _teacher_m1_hit_bool_name(index: int, teacher: str) -> str:
    return "__".join(
        (
            "teacher_m1_hit_cap",
            f"{index:04d}",
            _safe_identifier(teacher),
        )
    )


def _teacher_m1_penalty_total_var_name(index: int, teacher: str) -> str:
    return "__".join(
        (
            "teacher_m1_penalty_total",
            f"{index:04d}",
            _safe_identifier(teacher),
        )
    )


def _teacher_am1_fragmentation_bool_name(index: int, tag: str, teacher: str, day: str) -> str:
    return "__".join(
        (
            "teacher_am1_fragmentation",
            f"{index:04d}",
            _safe_identifier(tag),
            _safe_identifier(teacher),
            _safe_identifier(day),
        )
    )


def _teacher_am1_fragmentation_count_var_name(index: int, tag: str, teacher: str) -> str:
    return "__".join(
        (
            "teacher_am1_fragmentation",
            f"{index:04d}",
            _safe_identifier(tag),
            _safe_identifier(teacher),
        )
    )


def _multi_class_halfday_bool_name(
    index: int,
    tag: str,
    teacher: str,
    day: str,
    cls: str | None = None,
) -> str:
    parts = [
        "multi_class_halfday",
        f"{index:04d}",
        _safe_identifier(tag),
        _safe_identifier(teacher),
        _safe_identifier(day),
    ]
    if cls is not None:
        parts.append(_safe_identifier(cls))
    return "__".join(parts)


def _multi_class_halfday_count_var_name(index: int, teacher: str, day: str, cls: str) -> str:
    return "__".join(
        (
            "multi_class_halfday",
            f"{index:04d}",
            "count",
            _safe_identifier(teacher),
            _safe_identifier(day),
            _safe_identifier(cls),
        )
    )


def _grade_group_var_name(index: int, tag: str, *parts: Any) -> str:
    return "__".join(
        (
            "grade_group_duty",
            f"{index:04d}",
            _safe_identifier(tag),
            *(_safe_identifier(str(part)) for part in parts),
        )
    )


def _duty_joint_var_name(index: int, tag: str, *parts: Any) -> str:
    return "__".join(
        (
            "duty_joint",
            f"{index:04d}",
            _safe_identifier(tag),
            *(_safe_identifier(str(part)) for part in parts),
        )
    )


def _night_soft_var_name(index: int, tag: str, *parts: Any) -> str:
    return "__".join(
        (
            "night_soft",
            f"{index:04d}",
            _safe_identifier(tag),
            *(_safe_identifier(str(part)) for part in parts),
        )
    )


def _night_soft_subject_norm(value: Any) -> str:
    return str(value or "").strip().replace(" ", "")


def _teacher_am4_pm1_count_var_name(index: int, teacher: str) -> str:
    return "__".join(
        (
            "am4_pm1_cnt",
            f"{index:04d}",
            _safe_identifier(teacher),
        )
    )


def _teacher_am4_pm1_penalty_var_name(index: int, teacher: str, tag: str) -> str:
    return "__".join(
        (
            "am4_pm1_penalty",
            f"{index:04d}",
            _safe_identifier(teacher),
            _safe_identifier(tag),
        )
    )


def _weekday_subject_balance_day_hours_var_name(index: int, cls: str, subj: str, day: str) -> str:
    return "__".join(
        (
            "weekday_subject_day_hours",
            f"{index:04d}",
            _safe_identifier(cls),
            _safe_identifier(subj),
            _safe_identifier(day),
        )
    )


def _weekday_subject_balance_penalty_var_name(index: int, cls: str, subj: str, day: str, tag: str) -> str:
    return "__".join(
        (
            "weekday_subject_balance",
            f"{index:04d}",
            _safe_identifier(cls),
            _safe_identifier(subj),
            _safe_identifier(day),
            _safe_identifier(tag),
        )
    )


def _pe_tech_busy_bool_name(index: int, teacher: str, day: str, slot: Any) -> str:
    return "__".join(
        (
            "day_pe_tech_busy",
            f"{index:04d}",
            _safe_identifier(teacher),
            _safe_identifier(day),
            _safe_identifier(_slot_label(slot)),
        )
    )


def _pe_tech_gap_bool_name(index: int, teacher: str, day: str, tag: str, gap_index: int) -> str:
    return "__".join(
        (
            "day_pe_tech_gap",
            f"{index:04d}",
            _safe_identifier(teacher),
            _safe_identifier(day),
            _safe_identifier(tag),
            str(int(gap_index)),
        )
    )


def _teacher_halfday_key(teacher: str, day: str, halfday: str) -> str:
    return f"{teacher}|{day}|{halfday}"


def _teacher_target_slot_key(teacher: str, day: str, tag: str) -> str:
    return f"{teacher}|{day}|{tag}"


def _teacher_class_slot_bool_name(index: int, teacher: str, cls: str, slot: Any) -> str:
    return "__".join(
        (
            "weekend_teach",
            f"{index:04d}",
            _safe_identifier(teacher),
            _safe_identifier(cls),
            _safe_identifier(str(slot.day)),
            _safe_identifier(_slot_label(slot)),
        )
    )


def _teacher_class_slot_pair_key(teacher: str, cls: str, day: str, left: Any, right: Any) -> str:
    return f"{teacher}|{cls}|{day}|{_slot_label(left)}+{_slot_label(right)}"


def _teacher_class_slot_pair_bool_name(index: int, teacher: str, cls: str, day: str, left: Any, right: Any) -> str:
    return "__".join(
        (
            "weekend_pair",
            f"{index:04d}",
            _safe_identifier(teacher),
            _safe_identifier(cls),
            _safe_identifier(day),
            _safe_identifier(_slot_label(left)),
            _safe_identifier(_slot_label(right)),
        )
    )


def _teacher_weekend_day_bool_name(index: int, teacher: str, day: str) -> str:
    return "__".join(
        (
            "weekend_teacher_day",
            f"{index:04d}",
            _safe_identifier(teacher),
            _safe_identifier(day),
        )
    )


def _teacher_weekend_halfday_bool_name(index: int, teacher: str, day: str, halfday: str) -> str:
    return "__".join(
        (
            "weekend_halfday",
            f"{index:04d}",
            _safe_identifier(teacher),
            _safe_identifier(day),
            _safe_identifier(halfday),
        )
    )


def _teacher_weekend_cross_halfday_bool_name(index: int, teacher: str, day: str, halfday: str) -> str:
    return "__".join(
        (
            "weekend_cross_halfday",
            f"{index:04d}",
            _safe_identifier(teacher),
            _safe_identifier(day),
            _safe_identifier(halfday),
        )
    )


def _teacher_weekend_cross_bool_name(index: int, teacher: str, day: str) -> str:
    return "__".join(
        (
            "weekend_cross",
            f"{index:04d}",
            _safe_identifier(teacher),
            _safe_identifier(day),
        )
    )


def _teacher_target_slot_bool_name(index: int, teacher: str, day: str, tag: str) -> str:
    return "__".join(
        (
            "target_sunday_slot",
            f"{index:04d}",
            _safe_identifier(teacher),
            _safe_identifier(day),
            _safe_identifier(tag),
        )
    )


def _teacher_day_period_bool_name(index: int, teacher: str, day: str, tag: str) -> str:
    return "__".join(
        (
            "weekday_period_presence",
            f"{index:04d}",
            _safe_identifier(teacher),
            _safe_identifier(day),
            _safe_identifier(tag),
        )
    )


def _teacher_day_violation_bool_name(index: int, teacher: str, day: str, tag: str) -> str:
    return "__".join(
        (
            "weekday_violation",
            f"{index:04d}",
            _safe_identifier(teacher),
            _safe_identifier(day),
            _safe_identifier(tag),
        )
    )


def _teacher_day_count_var_name(index: int, teacher: str, day: str, halfday: str) -> str:
    return "__".join(
        (
            "weekday_count",
            f"{index:04d}",
            _safe_identifier(teacher),
            _safe_identifier(day),
            _safe_identifier(halfday),
        )
    )


def _teacher_weekly_count_var_name(index: int, teacher: str, tag: str) -> str:
    return "__".join(
        (
            "weekly_count",
            f"{index:04d}",
            _safe_identifier(teacher),
            _safe_identifier(tag),
        )
    )


def _teacher_target_combo_bool_name(index: int, teacher: str, day: str) -> str:
    return "__".join(
        (
            "target_sunday_combo",
            f"{index:04d}",
            _safe_identifier(teacher),
            _safe_identifier(day),
        )
    )


def _slot_order_key(slot: Any) -> tuple[int, int]:
    if str(slot.block) == "早自习":
        return (0, 0)
    if str(slot.block) == "上午":
        return (1, int(slot.period))
    if str(slot.block) == "下午":
        return (2, int(slot.period))
    return (99, int(slot.period))


def _day_weekend_slot_index(slot: Any) -> int:
    if str(slot.block) == "早自习":
        return 0
    if str(slot.block) == "上午":
        return int(slot.period)
    if str(slot.block) == "下午":
        return 4 + int(slot.period)
    return 99 + int(slot.period)


def _is_am(slot: Any) -> bool:
    return str(slot.block) in {"早自习", "上午"}


def _is_pm(slot: Any) -> bool:
    return str(slot.block) == "下午"


def _is_daytime(slot: Any) -> bool:
    return str(slot.block) in {"上午", "下午"}


def _is_pe_time_window_allowed(slot: Any) -> bool:
    if not is_weekday_day(str(slot.day)):
        return False
    if str(slot.block) == "下午":
        return True
    return str(slot.block) == "上午" and int(slot.period) == 4 and str(slot.day) in {"星期三", "星期四", "星期五"}


def _is_am1(slot: Any) -> bool:
    return str(slot.block) == "上午" and int(slot.period) == 1


def _is_am4(slot: Any) -> bool:
    return str(slot.block) == "上午" and int(slot.period) == 4


def _is_pm1(slot: Any) -> bool:
    return str(slot.block) == "下午" and int(slot.period) == 1


def _bool_value_constraint(name: str, variable_name: str, value: int, rule_id: str) -> LinearConstraintSpec:
    return LinearConstraintSpec(
        name=name,
        expression=LinearExpression((LinearTerm(variable_name, 1),)),
        sense="==",
        rhs=int(value),
        rule_id=rule_id,
    )


def _has_fixed_teacher_halfday(
    data: Any,
    fixed_assign: Mapping[Any, Any],
    teacher: str,
    day: str,
    block: str,
) -> bool:
    for (cls, slot), subj in fixed_assign.items():
        if str(slot.day) != str(day) or str(slot.block) != str(block):
            continue
        fixed_teacher = getattr(data, "cls_subj_teacher", {}).get((cls, subj))
        if str(fixed_teacher) == str(teacher):
            return True
    return False


def _has_fixed_teacher_slot(
    data: Any,
    fixed_assign: Mapping[Any, Any],
    teacher: str,
    day: str,
    block: str,
    period: int,
) -> bool:
    for (cls, slot), subj in fixed_assign.items():
        if str(slot.day) != str(day) or str(slot.block) != str(block) or int(slot.period) != int(period):
            continue
        fixed_teacher = getattr(data, "cls_subj_teacher", {}).get((cls, subj))
        if str(fixed_teacher) == str(teacher):
            return True
    return False


def _day_assignment_var_name(index: int, cls: str, subj: str, day: str, slot_label: str) -> str:
    return "__".join(
        (
            "day_x",
            f"{index:04d}",
            _safe_identifier(cls),
            _safe_identifier(subj),
            _safe_identifier(day),
            _safe_identifier(slot_label),
        )
    )


def _night_assignment_var_name(index: int, cls: str, subj: str, day: str, period: str) -> str:
    return "__".join(
        (
            "night_y",
            f"{index:04d}",
            _safe_identifier(cls),
            _safe_identifier(subj),
            _safe_identifier(day),
            _safe_identifier(period),
        )
    )


def _night_teacher_day_var_name(index: int, teacher: str, day: str) -> str:
    return "__".join(
        (
            "night_on",
            f"{index:04d}",
            _safe_identifier(teacher),
            _safe_identifier(day),
        )
    )


def _checkin_var_name(prefix: str, index: int, teacher: str, day: str) -> str:
    return "__".join(
        (
            prefix,
            f"{index:04d}",
            _safe_identifier(teacher),
            _safe_identifier(day),
        )
    )


def _safe_identifier(value: str) -> str:
    text = re.sub(r"[^0-9A-Za-z_]+", "__", str(value).strip())
    text = re.sub(r"__+", "__", text).strip("_")
    return text or "scheduler_rule"


def _empty_scheduler_rule_bridge(problem_id: str, rule_id: str, legacy_apply_fn: str) -> SchedulerGenericRuleBridge:
    ai_rule = AiRuleSpec(
        rule_id=rule_id,
        description=f"Disabled scheduler rule bridge for {legacy_apply_fn}.",
        enforcement="hard",
        priority=100,
        source=f"scheduler.disabled:{legacy_apply_fn}",
    )
    problem = OptimizationProblemSpec(
        problem_id=problem_id,
        variables=(),
        rules=(ai_rule,),
        constraints=(),
    )
    rule_first_plan = build_rule_first_plan(
        rules=problem.rules,
        constraints=problem.constraints,
        objective_rule_id=None,
    )
    return SchedulerGenericRuleBridge(
        problem=problem,
        rule_first_plan=rule_first_plan,
        metadata_by_rule={
            rule_id: {
                "scheduler_rule_id": rule_id,
                "legacy_apply_fn": legacy_apply_fn,
                "generic_contract_status": "covered_by_generic_contract",
                "runtime_rule_ids": generic_scheduler_rule_ids(),
                "constraint_family_counts": {},
            }
        },
    )
