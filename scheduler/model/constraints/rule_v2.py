# -*- coding: utf-8 -*-
"""Allowlisted Rule V2 -> CP-SAT compiler.

The compiler deliberately accepts only normalized, confirmed rules. It never
executes model-provided source code or arbitrary expressions.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from ortools.sat.python import cp_model

from scheduler.data.day_rules_reader import DayInputData, Slot
from scheduler.domain.rule_v2 import RULE_V2_COMPILER, validate_rule_v2
from scheduler.model.day_variables import DayVars
from scheduler.rules.mandatory import MANDATORY_DEFAULT_RULES, MANDATORY_RULE_IDS


MODELED_CATALOG_RULE_IDS = frozenset(
    binding
    for item in MANDATORY_DEFAULT_RULES
    for binding in item.get("solver_bindings", [])
) | MANDATORY_RULE_IDS


@dataclass
class RuleV2CompileResult:
    objective_terms: list[Any] = field(default_factory=list)
    applied_rule_ids: list[str] = field(default_factory=list)
    skipped_rule_ids: list[str] = field(default_factory=list)
    diagnostics: list[dict[str, Any]] = field(default_factory=list)


def apply_rule_v2_constraints(
    model: cp_model.CpModel,
    data: DayInputData,
    dv: DayVars,
    rules_cfg: Mapping[str, Any] | None,
    *,
    grade_prefix: str = "",
    catalog_evidence: Mapping[str, int] | None = None,
) -> RuleV2CompileResult:
    """Compile active Rule V2 items and return their soft objective terms."""
    result = RuleV2CompileResult()
    section = (rules_cfg or {}).get("rule_v2") if isinstance(rules_cfg, Mapping) else None
    rules = section.get("rules") if isinstance(section, Mapping) else []
    for raw in rules if isinstance(rules, list) else []:
        if not isinstance(raw, Mapping):
            continue
        rule_id = str(raw.get("id") or "unknown")
        reason = _ineligible_reason(raw)
        if reason:
            result.skipped_rule_ids.append(rule_id)
            result.diagnostics.append({"rule_id": rule_id, "status": "skipped", "message": reason})
            continue
        constraint = raw.get("constraint") if isinstance(raw.get("constraint"), Mapping) else {}
        constraint_type = str(constraint.get("type") or "")
        before = len(result.objective_terms)
        if constraint_type == "catalog_ref":
            catalog_id = str(constraint.get("catalog_id") or "")
            evidence = int((catalog_evidence or {}).get(catalog_id, 0) or 0)
            if catalog_id not in MODELED_CATALOG_RULE_IDS and evidence <= 0:
                result.skipped_rule_ids.append(rule_id)
                result.diagnostics.append({
                    "rule_id": rule_id,
                    "status": "skipped",
                    "constraint_units": 0,
                    "objective_terms_added": 0,
                    "message": "目录规则没有实际建模证据",
                })
                continue
            result.applied_rule_ids.append(rule_id)
            result.diagnostics.append({
                "rule_id": rule_id,
                "status": "delegated",
                "constraint_units": max(1, evidence),
                "objective_terms_added": 0,
                "catalog_id": catalog_id,
                "message": "已复用具有实际约束证据的系统规则",
            })
            continue
        if constraint_type == "teacher_unavailable":
            affected = _compile_teacher_unavailable(model, data, dv, raw, result, grade_prefix)
        elif constraint_type == "prefer_period":
            affected = _compile_prefer_period(model, data, dv, raw, result, grade_prefix)
        elif constraint_type == "max_daily_lessons":
            affected = _compile_max_daily(model, data, dv, raw, result, grade_prefix)
        else:
            result.skipped_rule_ids.append(rule_id)
            result.diagnostics.append({"rule_id": rule_id, "status": "skipped", "message": "约束类型不在白名单中"})
            continue
        result.applied_rule_ids.append(rule_id)
        result.diagnostics.append({
            "rule_id": rule_id,
            "status": "applied",
            "constraint_units": int(affected),
            "objective_terms_added": len(result.objective_terms) - before,
            "message": f"已编译 {affected} 个约束单元，新增 {len(result.objective_terms) - before} 个目标项",
        })
    return result


def _ineligible_reason(rule: Mapping[str, Any]) -> str:
    if not bool(rule.get("enabled", True)):
        return "规则未启用"
    if str(rule.get("status") or "") != "active":
        return "规则尚未激活"
    confirmation = rule.get("confirmation") if isinstance(rule.get("confirmation"), Mapping) else {}
    if confirmation.get("confirmed") is not True:
        return "规则尚未由教务确认"
    support = rule.get("solver_support") if isinstance(rule.get("solver_support"), Mapping) else {}
    if str(support.get("status") or "") != "supported" or str(support.get("compiler") or "") != RULE_V2_COMPILER:
        return "规则未获得完整求解支持"
    validation = validate_rule_v2(rule)
    if not validation.valid:
        return "规则校验失败：" + "；".join(validation.errors)
    return ""


def _compile_teacher_unavailable(
    model: cp_model.CpModel,
    data: DayInputData,
    dv: DayVars,
    rule: Mapping[str, Any],
    result: RuleV2CompileResult,
    grade_prefix: str,
) -> int:
    affected = 0
    weight = _weight(rule)
    strength = str(rule.get("strength") or "hard")
    for cls, subj, slot, var, teacher in _iter_matching_variables(data, dv, rule, grade_prefix):
        exception = _exception_mode(rule, cls, subj, teacher, slot, grade_prefix)
        if exception == "exclude":
            continue
        if strength == "hard" and exception != "soften":
            model.Add(var == 0)
        else:
            result.objective_terms.append(weight * var)
        affected += 1
    return affected


def _compile_prefer_period(
    model: cp_model.CpModel,
    data: DayInputData,
    dv: DayVars,
    rule: Mapping[str, Any],
    result: RuleV2CompileResult,
    grade_prefix: str,
) -> int:
    params = (rule.get("constraint") or {}).get("params") or {}
    period = str(params.get("period") or "").lower()
    affected = 0
    weight = _weight(rule)
    strength = str(rule.get("strength") or "soft")
    slots_by_day = _ordered_slots_by_day(data.available_slots)
    for cls, subj, slot, var, teacher in _iter_matching_variables(data, dv, rule, grade_prefix):
        if _is_preferred_slot(slot, period, slots_by_day.get(slot.day, [])):
            continue
        exception = _exception_mode(rule, cls, subj, teacher, slot, grade_prefix)
        if exception == "exclude":
            continue
        if strength == "hard" and exception != "soften":
            model.Add(var == 0)
        else:
            result.objective_terms.append(weight * var)
        affected += 1
    return affected


def _compile_max_daily(
    model: cp_model.CpModel,
    data: DayInputData,
    dv: DayVars,
    rule: Mapping[str, Any],
    result: RuleV2CompileResult,
    grade_prefix: str,
) -> int:
    params = (rule.get("constraint") or {}).get("params") or {}
    maximum = int(params.get("max") or 0)
    strength = str(rule.get("strength") or "hard")
    weight = _weight(rule)
    groups: dict[tuple[str, str], list[Any]] = {}
    softened: set[tuple[str, str]] = set()
    fixed_counts: dict[tuple[str, str], int] = {}

    for cls, subj, slot, var, teacher in _iter_matching_variables(data, dv, rule, grade_prefix):
        exception = _exception_mode(rule, cls, subj, teacher, slot, grade_prefix)
        if exception == "exclude":
            continue
        group = (_daily_group(rule, cls, subj, teacher), slot.day)
        groups.setdefault(group, []).append(var)
        if exception == "soften":
            softened.add(group)

    for (cls, slot), subj in data.fixed_assign.items():
        teacher = str(data.cls_subj_teacher.get((cls, subj), ""))
        if not _matches_rule_context(rule, cls, subj, teacher, slot, grade_prefix):
            continue
        exception = _exception_mode(rule, cls, subj, teacher, slot, grade_prefix)
        if exception == "exclude":
            continue
        group = (_daily_group(rule, cls, subj, teacher), slot.day)
        fixed_counts[group] = fixed_counts.get(group, 0) + 1
        if exception == "soften":
            softened.add(group)

    affected = 0
    for group in sorted(set(groups) | set(fixed_counts)):
        variables = groups.get(group, [])
        fixed = fixed_counts.get(group, 0)
        total_upper = len(variables) + fixed
        if strength == "hard" and group not in softened:
            model.Add(sum(variables) + fixed <= maximum)
        elif total_upper > maximum:
            tag = _safe_tag(str(rule.get("id") or "rule"), "max", *group)
            excess = model.NewIntVar(0, total_upper - maximum, f"rule_v2_excess__{tag}")
            model.Add(excess >= sum(variables) + fixed - maximum)
            result.objective_terms.append(weight * excess)
        affected += 1
    return affected


def _iter_matching_variables(
    data: DayInputData,
    dv: DayVars,
    rule: Mapping[str, Any],
    grade_prefix: str,
) -> Iterable[tuple[str, str, Slot, Any, str]]:
    for (cls, subj, slot), var in dv.x.items():
        teacher = str(data.cls_subj_teacher.get((cls, subj), ""))
        if _matches_rule_context(rule, cls, subj, teacher, slot, grade_prefix):
            yield cls, subj, slot, var, teacher


def _matches_rule_context(
    rule: Mapping[str, Any],
    cls: str,
    subj: str,
    teacher: str,
    slot: Slot,
    grade_prefix: str,
) -> bool:
    scope = rule.get("scope") if isinstance(rule.get("scope"), Mapping) else {}
    if not _scope_matches(scope, cls, subj, teacher, grade_prefix):
        return False
    effective = rule.get("effective_time") if isinstance(rule.get("effective_time"), Mapping) else {}
    days = {str(value) for value in effective.get("days", []) if str(value)}
    if days and slot.day not in days:
        return False
    slot_filters = [str(value).strip() for value in effective.get("slots", []) if str(value).strip()]
    if slot_filters and not any(_slot_matches_label(slot, label, []) for label in slot_filters):
        return False
    return True


def _scope_matches(scope: Mapping[str, Any], cls: str, subj: str, teacher: str, grade_prefix: str) -> bool:
    values = {
        "grades": str(grade_prefix or ""),
        "classes": cls,
        "subjects": subj,
        "teachers": teacher,
    }
    for key, actual in values.items():
        selected = {str(value).strip() for value in scope.get(key, []) if str(value).strip()}
        if selected and not _value_matches(actual, selected, key=key, cls=cls):
            return False
    excluded = scope.get("exclude") if isinstance(scope.get("exclude"), Mapping) else {}
    for key, actual in values.items():
        selected = {str(value).strip() for value in excluded.get(key, []) if str(value).strip()}
        if selected and _value_matches(actual, selected, key=key, cls=cls):
            return False
    return True


def _value_matches(actual: str, selected: set[str], *, key: str, cls: str) -> bool:
    actual_norm = str(actual or "").replace(" ", "").strip()
    selected_norm = {value.replace(" ", "").strip() for value in selected}
    if actual_norm in selected_norm:
        return True
    if key == "grades":
        return any(str(cls).replace(" ", "").startswith(value) for value in selected_norm)
    return False


def _exception_mode(
    rule: Mapping[str, Any],
    cls: str,
    subj: str,
    teacher: str,
    slot: Slot,
    grade_prefix: str,
) -> str:
    selected = ""
    for item in rule.get("exceptions", []) if isinstance(rule.get("exceptions"), list) else []:
        if not isinstance(item, Mapping):
            continue
        days = {str(value) for value in item.get("days", []) if str(value)}
        if days and slot.day not in days:
            continue
        slots = [str(value).strip() for value in item.get("slots", []) if str(value).strip()]
        if slots and not any(_slot_matches_label(slot, label, []) for label in slots):
            continue
        scope = item.get("scope") if isinstance(item.get("scope"), Mapping) else {}
        if not _scope_matches(scope, cls, subj, teacher, grade_prefix):
            continue
        mode = str(item.get("mode") or "")
        if mode == "exclude":
            return mode
        if mode == "soften":
            selected = mode
    return selected


def _daily_group(rule: Mapping[str, Any], cls: str, subj: str, teacher: str) -> str:
    scope = rule.get("scope") if isinstance(rule.get("scope"), Mapping) else {}
    if scope.get("teachers"):
        return f"teacher:{teacher}"
    if scope.get("classes"):
        return f"class:{cls}"
    if scope.get("subjects"):
        return f"class-subject:{cls}:{subj}"
    return f"class:{cls}"


def _weight(rule: Mapping[str, Any]) -> int:
    try:
        return max(1, min(100_000, int(rule.get("weight") or 300)))
    except (TypeError, ValueError):
        return 300


def _ordered_slots_by_day(slots: Iterable[Slot]) -> dict[str, list[Slot]]:
    order = {"早自习": 0, "上午": 1, "下午": 2}
    result: dict[str, list[Slot]] = {}
    for slot in slots:
        result.setdefault(slot.day, []).append(slot)
    for day in result:
        result[day] = sorted(result[day], key=lambda item: (order.get(item.block, 9), item.period))
    return result


def _is_preferred_slot(slot: Slot, period: str, ordered: list[Slot]) -> bool:
    if period == "morning":
        return slot.block == "上午"
    if period == "afternoon":
        return slot.block == "下午"
    if period == "early":
        return slot.block == "早自习"
    regular = [item for item in ordered if item.block != "早自习"]
    if period == "first":
        return bool(regular) and slot == regular[0]
    if period == "last":
        return bool(regular) and slot == regular[-1]
    return False


def _slot_matches_label(slot: Slot, label: str, ordered: list[Slot]) -> bool:
    text = str(label or "").replace(" ", "").strip()
    if text in {f"{slot.block}{slot.period}", f"{slot.block}第{slot.period}节"}:
        return True
    if text in {"上午", "下午", "早自习"}:
        return slot.block == text
    if text.startswith("第") and text.endswith("节"):
        try:
            target = int(text[1:-1])
        except ValueError:
            return False
        if ordered:
            regular = [item for item in ordered if item.block != "早自习"]
            return 1 <= target <= len(regular) and slot == regular[target - 1]
        if slot.block == "上午":
            return slot.period == target
        if slot.block == "下午":
            return slot.period + 4 == target
    return False


def _safe_tag(*parts: str) -> str:
    raw = "|".join(str(value) for value in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]
