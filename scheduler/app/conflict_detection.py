# -*- coding: utf-8 -*-
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from ai_orchestrated_optimization import (
    CpSatSolveConfig,
    LinearConstraintSpec,
    LinearExpression,
    LinearTerm,
    OptimizationProblemSpec,
    RuleSpec,
    SolverParameterSpec,
    VariableSpec,
    solve_cp_sat_problem,
)

from scheduler.calendar import DEFAULT_NIGHT_DAYS
from scheduler.data.teacher_table_schema import configured_teacher_table_columns, teacher_subject_columns


def _as_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(x).strip() for x in value if str(x).strip()]


def _conflict(
    *,
    cid: str,
    severity: str,
    title: str,
    rules: list[str],
    detail: str,
    suggestion: str,
    rule_labels: dict[str, str] | None = None,
) -> dict[str, Any]:
    return {
        "id": cid,
        "severity": severity,
        "title": title,
        "rules": rules,
        "rule_labels": rule_labels or {},
        "detail": detail,
        "suggestion": suggestion,
        "certainty": "确定冲突",
    }


@dataclass(frozen=True)
class _AssumedRule:
    rule_id: str
    title: str
    constraints: tuple["_LinearRuleConstraint", ...]


@dataclass(frozen=True)
class _LinearRuleConstraint:
    name: str
    terms: tuple[tuple[tuple[str, str], int], ...]
    sense: str
    rhs: int


def detect_rule_conflicts(effective_cfg: dict[str, Any], teacher_rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    conflicts: list[dict[str, Any]] = []
    rules = effective_cfg or {}
    conflicts.extend(_detect_night_unsat_cores(rules, teacher_rows or []))

    temporary = rules.get("temporary_rules", {}) or {}
    active = temporary.get("active") if isinstance(temporary, dict) else []
    conflicts.extend(_detect_temporary_rule_conflicts(active if isinstance(active, list) else []))

    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []
    for item in conflicts:
        conflict_id = item["id"]
        nodes[conflict_id] = {"id": conflict_id, "label": item["title"], "kind": "conflict", "severity": item["severity"]}
        labels = item.get("rule_labels", {}) or {}
        for rule_id in item["rules"]:
            nodes.setdefault(rule_id, {"id": rule_id, "label": labels.get(rule_id, rule_id), "kind": "rule"})
            edges.append({"source": conflict_id, "target": rule_id, "severity": item["severity"]})

    return {
        "summary": {
            "total": len(conflicts),
            "errors": len([x for x in conflicts if x["severity"] == "error"]),
            "warnings": len([x for x in conflicts if x["severity"] == "warning"]),
            "certainty": "仅展示已被 OR-Tools 不可行核心或等价逻辑证明的确定冲突",
        },
        "conflicts": conflicts,
        "graph": {"nodes": list(nodes.values()), "edges": edges},
    }


def _detect_night_unsat_cores(rules: dict[str, Any], teacher_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    classes, cst = _night_class_subject_teacher_map(rules, teacher_rows)
    if not classes or not cst:
        return []

    calendar = rules.get("calendar", {}) or {}
    evening = rules.get("evening", {}) or {}
    days = _as_list(calendar.get("days")) or list(DEFAULT_NIGHT_DAYS)
    periods = _as_list(calendar.get("periods")) or _as_list(evening.get("periods")) or ["晚自习1", "晚自习2"]
    weekly_need = int(evening.get("weekly_occurrences_per_subject", 2) or 2)

    conflicts: list[dict[str, Any]] = []
    for (class_name, subject), teacher in sorted(cst.items()):
        assumed_rules = _night_assumed_rules(
            rules=rules,
            class_name=class_name,
            subject=subject,
            teacher=teacher,
            days=days,
            periods=periods,
            weekly_need=weekly_need,
        )
        core = _solve_assumed_night_rules(days, periods, assumed_rules)
        if not core:
            continue
        labels = {rule.rule_id: rule.title for rule in core}
        rule_titles = "、".join(labels.values())
        conflicts.append(
            _conflict(
                cid=f"night.unsat_core.{class_name}.{subject}.{teacher}",
                severity="error",
                title="晚自习硬规则互相冲突",
                rules=[rule.rule_id for rule in core],
                rule_labels=labels,
                detail=f"{class_name} 的 {subject} 由 {teacher} 任课；当前这些规则同时生效时，OR-Tools 证明该学科无法排够每周 {weekly_need} 次：{rule_titles}。",
                suggestion="只调整上述规则即可定位问题：减少禁排日期/节次，扩大允许日期，或降低该学科每周晚自习次数。",
            )
        )
    return _dedupe_conflicts(conflicts)


def _night_class_subject_teacher_map(rules: dict[str, Any], teacher_rows: list[dict[str, Any]]) -> tuple[list[str], dict[tuple[str, str], str]]:
    if not teacher_rows:
        return [], {}
    class_col, head_col, gender_col = configured_teacher_table_columns(rules)
    evening = rules.get("evening", {}) or {}
    subjects = _as_list(evening.get("subjects"))
    if not subjects:
        subjects = sorted(
            {
                key
                for row in teacher_rows
                for key in teacher_subject_columns(
                    row.keys(),
                    class_col=class_col,
                    head_col=head_col,
                    gender_col=gender_col,
                )
            }
        )

    classes: list[str] = []
    cst: dict[tuple[str, str], str] = {}
    for row in teacher_rows:
        if not isinstance(row, dict):
            continue
        class_name = str(row.get(class_col) or "").strip()
        if not class_name:
            continue
        classes.append(class_name)
        for subject in subjects:
            teacher = str(row.get(subject) or "").strip()
            if teacher:
                cst[(class_name, subject)] = teacher
    return classes, cst


def _night_assumed_rules(
    *,
    rules: dict[str, Any],
    class_name: str,
    subject: str,
    teacher: str,
    days: list[str],
    periods: list[str],
    weekly_need: int,
) -> list[_AssumedRule]:
    assumed: list[_AssumedRule] = [
        _AssumedRule(
            "night.base.weekly_occurrences_per_subject",
            f"{class_name}{subject}每周必须排 {weekly_need} 次",
            (
                _LinearRuleConstraint(
                    "weekly_occurrences_per_subject",
                    tuple(((day, period), 1) for day in days for period in periods),
                    "==",
                    weekly_need,
                ),
            ),
        ),
        _AssumedRule(
            "night.base.same_subject_once_per_day",
            f"{class_name}{subject}同一天最多排 1 次",
            tuple(
                _LinearRuleConstraint(
                    f"same_subject_once_per_day_{idx}",
                    tuple(((day, period), 1) for period in periods),
                    "<=",
                    1,
                )
                for idx, day in enumerate(days)
            ),
        ),
    ]

    hard_bans = rules.get("hard_bans", {}) or {}
    if bool(hard_bans.get("enabled", True)):
        for idx, item in enumerate(hard_bans.get("subject_bans", []) or []):
            if not isinstance(item, dict) or str(item.get("subject") or "").strip() != subject:
                continue
            ban_days = set(_as_list(item.get("days"))) & set(days)
            ban_periods = set(_as_list(item.get("periods")) or periods) & set(periods)
            if not ban_days or not ban_periods:
                continue
            assumed.append(
                _AssumedRule(
                    f"hard_bans.subject_bans[{idx}]",
                    f"{subject}在{_join_sorted(ban_days)}的{_join_sorted(ban_periods)}禁排",
                    _ban_cell_constraints(ban_days, ban_periods),
                )
            )
        teacher_day_bans = hard_bans.get("teacher_day_bans", {}) or {}
        if isinstance(teacher_day_bans, dict):
            for day, names in teacher_day_bans.items():
                if str(day) not in days or teacher not in _as_list(names):
                    continue
                assumed.append(
                    _AssumedRule(
                        f"hard_bans.teacher_day_bans.{day}.{teacher}",
                        f"{teacher}{day}晚自习禁排",
                        _ban_cell_constraints({str(day)}, set(periods)),
                    )
                )

    assumed.extend(_personalized_night_rules(rules, teacher, days, periods))
    return assumed


def _personalized_night_rules(
    rules: dict[str, Any],
    teacher: str,
    days: list[str],
    periods: list[str],
) -> list[_AssumedRule]:
    pcfg = rules.get("personalized_constraints", {}) or {}
    if not bool(pcfg.get("enabled", True)):
        return []
    targets = pcfg.get("teacher_targets", {}) or {}
    assumed: list[_AssumedRule] = []
    if bool(pcfg.get("enable_xyx_night_days_only")) and str(pcfg.get("xyx_night_days_only_mode", "hard")).lower() == "hard" and teacher in _as_list(targets.get("xyx")):
        allowed = set(_as_list(pcfg.get("xyx_night_allowed_days")))
        banned_days = set(days) - allowed
        if banned_days:
            assumed.append(
                _AssumedRule(
                    f"personalized_constraints.xyx_night_days_only.{teacher}",
                    f"{teacher}晚自习只允许在{_join_sorted(allowed)}",
                    _ban_cell_constraints(banned_days, set(periods)),
                )
            )
    for enable_key, target_key, mode_key, day, title in [
        ("enable_zfy_no_sunday_night", "zfy", "zfy_no_sunday_night_mode", "星期日", "周日晚自习禁排"),
        ("enable_zzx_no_sunday_night", "zzx", "zzx_no_sunday_night_mode", "星期日", "周日晚自习禁排"),
        ("enable_liumeng_no_sunday", "lm", None, "星期日", "周日晚自习禁排"),
        ("enable_dym_no_fri_sun_night", "dym", None, "星期日", "周日晚自习禁排"),
        ("enable_hsm_no_fri_night", "hsm", "hsm_no_fri_night_mode", "星期五", "周五晚自习禁排"),
    ]:
        if day not in days or not bool(pcfg.get(enable_key)) or teacher not in _as_list(targets.get(target_key)):
            continue
        if mode_key and str(pcfg.get(mode_key, "hard")).lower() != "hard":
            continue
        assumed.append(
            _AssumedRule(
                f"personalized_constraints.{enable_key}.{teacher}",
                f"{teacher}{title}",
                _ban_cell_constraints({day}, set(periods)),
            )
        )
    return assumed


def _ban_cell_constraints(ban_days: set[str], ban_periods: set[str]) -> tuple[_LinearRuleConstraint, ...]:
    return tuple(
        _LinearRuleConstraint(
            f"ban_cell_{idx}",
            (((day, period), 1),),
            "==",
            0,
        )
        for idx, (day, period) in enumerate(
            (day, period)
            for day in sorted(ban_days)
            for period in sorted(ban_periods)
        )
    )


def _solve_assumed_night_rules(days: list[str], periods: list[str], assumed_rules: list[_AssumedRule]) -> list[_AssumedRule]:
    problem, assumptions = _assumed_rules_problem(days, periods, assumed_rules)
    solution = solve_cp_sat_problem(problem, time_limit_seconds=3)
    if solution.status_name != "INFEASIBLE":
        return []
    core = [assumptions[name] for name in solution.assumption_core if name in assumptions]
    return _minimize_assumption_core(days, periods, core)


def _minimize_assumption_core(days: list[str], periods: list[str], core: list[_AssumedRule]) -> list[_AssumedRule]:
    minimal = list(core)
    changed = True
    while changed:
        changed = False
        for rule in list(minimal):
            trial = [item for item in minimal if item is not rule]
            if trial and _is_rule_set_infeasible(days, periods, trial):
                minimal = trial
                changed = True
                break
    return minimal


def _is_rule_set_infeasible(days: list[str], periods: list[str], rules: list[_AssumedRule]) -> bool:
    if not rules:
        return False
    problem, _assumptions = _assumed_rules_problem(days, periods, rules)
    solution = solve_cp_sat_problem(problem, time_limit_seconds=1)
    return solution.status_name == "INFEASIBLE"


def _assumed_rules_problem(
    days: list[str],
    periods: list[str],
    assumed_rules: list[_AssumedRule],
) -> tuple[OptimizationProblemSpec, dict[str, _AssumedRule]]:
    cell_vars = {
        (day, period): f"night_cell_{day_idx}_{period_idx}"
        for day_idx, day in enumerate(days)
        for period_idx, period in enumerate(periods)
    }
    variables = [VariableSpec.bool(name) for name in cell_vars.values()]
    rules: list[RuleSpec] = []
    constraints: list[LinearConstraintSpec] = []
    assumptions: dict[str, _AssumedRule] = {}
    for rule_idx, rule in enumerate(assumed_rules):
        assumption_name = f"assume_rule_{rule_idx}"
        variables.append(VariableSpec.bool(assumption_name))
        assumptions[assumption_name] = rule
        rules.append(
            RuleSpec(
                rule_id=rule.rule_id,
                description=rule.title,
                enforcement="hard",
                priority=rule_idx,
                source="scheduler.app.conflict_detection",
            )
        )
        for constraint_idx, constraint in enumerate(rule.constraints):
            constraints.append(
                LinearConstraintSpec(
                    name=f"{rule_idx}_{constraint_idx}_{constraint.name}",
                    expression=LinearExpression(
                        tuple(
                            LinearTerm(cell_vars[cell], coefficient)
                            for cell, coefficient in constraint.terms
                            if cell in cell_vars
                        )
                    ),
                    sense=constraint.sense,
                    rhs=constraint.rhs,
                    rule_id=rule.rule_id,
                    enforcement_literals=(assumption_name,),
                )
            )
    problem = OptimizationProblemSpec(
        problem_id="scheduler_night_conflict_detection",
        variables=tuple(variables),
        rules=tuple(rules),
        constraints=tuple(constraints),
        solve_config=CpSatSolveConfig(
            parameters=(SolverParameterSpec("num_search_workers", 1),),
            assumptions=tuple(assumptions.keys()),
        ),
    )
    return problem, assumptions


def _dedupe_conflicts(conflicts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, ...]] = set()
    out: list[dict[str, Any]] = []
    for item in conflicts:
        key = tuple(sorted(item.get("rules", [])))
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _join_sorted(values: set[str]) -> str:
    return "、".join(sorted(str(v) for v in values if str(v).strip())) or "未设置"


def _detect_temporary_rule_conflicts(active_rules: list[Any]) -> list[dict[str, Any]]:
    conflicts: list[dict[str, Any]] = []
    by_key: dict[tuple[str, str, str, str], dict[str, list[str]]] = defaultdict(lambda: {"ban": [], "require": []})
    for item in active_rules:
        if not isinstance(item, dict):
            continue
        action = str(item.get("action") or "")
        if action not in {"ban", "require"}:
            continue
        for teacher in _as_list(item.get("target_teachers")):
            key = (
                teacher,
                str(item.get("scope") or ""),
                str(item.get("day") or ""),
                str(item.get("slot") or ""),
            )
            by_key[key][action].append(str(item.get("id") or item.get("source") or "temporary_rule"))
    for (teacher, scope, day, slot), rows in by_key.items():
        if rows["ban"] and rows["require"]:
            conflicts.append(
                _conflict(
                    cid=f"temporary.ban_require.{teacher}.{scope}.{day}.{slot}",
                    severity="error",
                    title="临时规则同时要求与禁排",
                    rules=rows["ban"] + rows["require"],
                    detail=f"{teacher} 在 {day} {slot} 同时存在必须安排与禁排规则。",
                    suggestion="保留业务优先级更高的一条，另一条移出求解规则。",
                )
            )
    return conflicts
