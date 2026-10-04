# -*- coding: utf-8 -*-
"""Audit-only rule execution plans.

Execution plans are migration/audit artifacts. They summarize what the registry
would consider enabled for a mode and how school-specific rule instances map to
generic templates. They do not execute constraints and do not decide solver
enablement.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any, Mapping, Sequence

from scheduler.rules.registry import RuleRegistry, enumerate_effective_rules

if TYPE_CHECKING:
    from scheduler.domain.rule_instance import CompiledRuleInstance
    from scheduler.domain.school_profile import SchoolProfile


@dataclass(frozen=True)
class RulePlanItem:
    rule_id: str
    name: str
    category_path: str
    stage: str
    order: int
    enabled: bool
    mode: str
    weight: float | int | None
    config_key: str
    apply_fn_name: str
    instance_ids: tuple[str, ...] = ()
    instance_target_scopes: tuple[str, ...] = ()


@dataclass(frozen=True)
class UnplannedRuleInstance:
    instance_id: str
    template_id: str
    reason: str


@dataclass(frozen=True)
class RuleExecutionPlan:
    mode: str
    profile_id: str
    items: tuple[RulePlanItem, ...]
    unplanned_rule_instances: tuple[UnplannedRuleInstance, ...] = ()
    source: str = "registry"


@dataclass(frozen=True)
class RuleTraceAudit:
    planned_rule_ids: tuple[str, ...]
    traced_rule_ids: tuple[str, ...]
    missing_enabled_rule_ids: tuple[str, ...]
    unexpected_trace_rule_ids: tuple[str, ...]
    errored_trace_rule_ids: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.missing_enabled_rule_ids and not self.unexpected_trace_rule_ids and not self.errored_trace_rule_ids


def build_rule_execution_plan(
    registry: RuleRegistry,
    effective_cfg: dict[str, Any],
    *,
    mode: str,
    profile: "SchoolProfile | None" = None,
    rule_instances: "Sequence[CompiledRuleInstance]" = (),
    only_enabled: bool = False,
    source: str = "registry",
) -> RuleExecutionPlan:
    all_rows = enumerate_effective_rules(
        registry,
        effective_cfg,
        mode=mode,
        only_enabled=False,
    )
    rows = tuple(row for row in all_rows if row.enabled) if only_enabled else tuple(all_rows)
    instances_by_template: dict[str, list[CompiledRuleInstance]] = {}
    for instance in rule_instances:
        instances_by_template.setdefault(instance.template_id, []).append(instance)

    planned_rule_ids = {row.rule_id for row in all_rows}
    unplanned = tuple(
        UnplannedRuleInstance(
            instance_id=instance.instance_id,
            template_id=instance.template_id,
            reason=f"template is not in {mode} registry plan",
        )
        for instance in rule_instances
        if instance.template_id not in planned_rule_ids
    )
    items = tuple(
        RulePlanItem(
            rule_id=row.rule_id,
            name=row.name,
            category_path=row.category_path,
            stage=row.stage,
            order=int(row.order),
            enabled=bool(row.enabled),
            mode=str(row.mode),
            weight=row.weight,
            config_key=row.config_key,
            apply_fn_name=row.apply_fn_name,
            instance_ids=tuple(instance.instance_id for instance in instances_by_template.get(row.rule_id, ())),
            instance_target_scopes=tuple(instance.target_scope for instance in instances_by_template.get(row.rule_id, ())),
        )
        for row in rows
    )
    return RuleExecutionPlan(
        mode=str(mode),
        profile_id=profile.profile_id if profile is not None else "",
        items=items,
        unplanned_rule_instances=unplanned,
        source=source,
    )


def audit_rule_trace_against_plan(
    plan: RuleExecutionPlan,
    trace: Sequence[Mapping[str, Any]],
    *,
    require_all_enabled: bool = False,
) -> RuleTraceAudit:
    all_plan_ids = {item.rule_id for item in plan.items}
    enabled_plan_ids = {item.rule_id for item in plan.items if item.enabled}
    traced_ids = {
        str(row.get("rule_id") or "").strip()
        for row in trace
        if str(row.get("rule_id") or "").strip()
    }
    errored = {
        str(row.get("rule_id") or "").strip()
        for row in trace
        if str(row.get("rule_id") or "").strip() and str(row.get("status") or "ok") == "error"
    }
    missing = enabled_plan_ids - traced_ids if require_all_enabled else set()
    return RuleTraceAudit(
        planned_rule_ids=tuple(sorted(all_plan_ids)),
        traced_rule_ids=tuple(sorted(traced_ids)),
        missing_enabled_rule_ids=tuple(sorted(missing)),
        unexpected_trace_rule_ids=tuple(sorted(traced_ids - all_plan_ids)),
        errored_trace_rule_ids=tuple(sorted(errored)),
    )


def rule_execution_plan_payload(plan: RuleExecutionPlan) -> dict[str, Any]:
    return {
        "mode": plan.mode,
        "profile_id": plan.profile_id,
        "source": plan.source,
        "items": [asdict(item) for item in plan.items],
        "unplanned_rule_instances": [asdict(item) for item in plan.unplanned_rule_instances],
    }
