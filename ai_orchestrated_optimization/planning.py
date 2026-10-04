# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass

from ai_orchestrated_optimization.contracts import ConstraintSpec, RuleSpec


@dataclass(frozen=True)
class RuleFirstRuleItem:
    rule: RuleSpec

    @property
    def rule_id(self) -> str:
        return self.rule.rule_id


@dataclass(frozen=True)
class RuleFirstConstraintItem:
    rule: RuleSpec
    constraint: ConstraintSpec


@dataclass(frozen=True)
class RuleFirstPlan:
    rule_order: tuple[RuleFirstRuleItem, ...]
    constraint_order: tuple[RuleFirstConstraintItem, ...]
    objective_rule_id: str | None


def build_rule_first_plan(
    *,
    rules: tuple[RuleSpec, ...],
    constraints: tuple[ConstraintSpec, ...],
    objective_rule_id: str | None,
) -> RuleFirstPlan:
    rules_by_id = _rules_by_id(rules)
    for constraint in constraints:
        if constraint.rule_id not in rules_by_id:
            raise ValueError(f"constraint {constraint.name!r} references unknown rule_id {constraint.rule_id!r}")
    if objective_rule_id is not None and objective_rule_id not in rules_by_id:
        raise ValueError(f"objective references unknown rule_id {objective_rule_id!r}")

    ordered_rules = tuple(sorted(rules, key=_rule_sort_key))
    rule_rank = {rule.rule_id: index for index, rule in enumerate(ordered_rules)}
    ordered_constraints = tuple(
        RuleFirstConstraintItem(rule=rules_by_id[constraint.rule_id], constraint=constraint)
        for constraint in sorted(
            constraints,
            key=lambda item: (rule_rank[item.rule_id], item.name),
        )
    )
    return RuleFirstPlan(
        rule_order=tuple(RuleFirstRuleItem(rule=rule) for rule in ordered_rules),
        constraint_order=ordered_constraints,
        objective_rule_id=objective_rule_id,
    )


def _rules_by_id(rules: tuple[RuleSpec, ...]) -> dict[str, RuleSpec]:
    out: dict[str, RuleSpec] = {}
    for rule in rules:
        rid = str(rule.rule_id or "").strip()
        if not rid:
            raise ValueError("rule_id is required")
        if rid in out:
            raise ValueError(f"duplicate rule_id {rid!r}")
        out[rid] = rule
    return out


def _rule_sort_key(rule: RuleSpec) -> tuple[int, int, str]:
    enforcement = str(rule.enforcement or "hard").strip().lower()
    tier = 0 if enforcement == "hard" else 1
    return (tier, int(rule.priority), str(rule.rule_id))
