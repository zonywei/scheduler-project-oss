# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class LegacyRuleMigrationItem:
    rule_id: str
    operation_count: int
    operation_types: tuple[str, ...]
    candidate_generic_specs: tuple[str, ...]
    generic_contract_status: str
    migration_priority: int
    recommended_next_step: str


@dataclass(frozen=True)
class AgentMigrationTask:
    task_id: str
    rule_id: str
    owner_agent_role: str
    handoff_from: str
    target_generic_specs: tuple[str, ...]
    operation_types: tuple[str, ...]
    generic_contract_status: str
    migration_priority: int
    recommended_next_step: str
    acceptance_checks: tuple[str, ...]


def build_legacy_rule_migration_backlog(
    operation_summary_by_rule: Mapping[str, Mapping[str, Any]],
    *,
    generic_rule_ids: tuple[str, ...] = (),
) -> tuple[LegacyRuleMigrationItem, ...]:
    generic_ids = {str(rule_id) for rule_id in generic_rule_ids}
    items = tuple(
        _migration_item(rule_id, summary, generic_ids)
        for rule_id, summary in operation_summary_by_rule.items()
    )
    return tuple(
        sorted(
            items,
            key=lambda item: (-item.migration_priority, -item.operation_count, item.rule_id),
        )
    )


def build_agent_migration_task_plan(
    backlog: tuple[LegacyRuleMigrationItem, ...],
) -> tuple[AgentMigrationTask, ...]:
    return tuple(_agent_migration_task(index, item) for index, item in enumerate(backlog, start=1))


def _agent_migration_task(index: int, item: LegacyRuleMigrationItem) -> AgentMigrationTask:
    owner = _owner_agent_role(item)
    return AgentMigrationTask(
        task_id=f"migration-{index:03d}-{_task_slug(item.rule_id)}",
        rule_id=item.rule_id,
        owner_agent_role=owner,
        handoff_from=_handoff_from(owner),
        target_generic_specs=item.candidate_generic_specs,
        operation_types=item.operation_types,
        generic_contract_status=item.generic_contract_status,
        migration_priority=item.migration_priority,
        recommended_next_step=item.recommended_next_step,
        acceptance_checks=_acceptance_checks(item),
    )


def _migration_item(
    rule_id: str,
    summary: Mapping[str, Any],
    generic_ids: set[str],
) -> LegacyRuleMigrationItem:
    clean_rule_id = str(rule_id or "__unscoped__")
    operation_count = int(summary.get("operation_count") or 0)
    operations_raw = summary.get("operations") or {}
    operation_types = tuple(sorted(str(name) for name in operations_raw))
    status = _status(clean_rule_id, generic_ids)
    candidate_generic_specs = _candidate_generic_specs(operation_types)
    return LegacyRuleMigrationItem(
        rule_id=clean_rule_id,
        operation_count=operation_count,
        operation_types=operation_types,
        candidate_generic_specs=candidate_generic_specs,
        generic_contract_status=status,
        migration_priority=_priority(status, operation_count),
        recommended_next_step=_next_step(status, candidate_generic_specs),
    )


def _owner_agent_role(item: LegacyRuleMigrationItem) -> str:
    if item.generic_contract_status == "missing_rule_context":
        return "debug_diagnostics"
    if item.generic_contract_status == "covered_by_generic_contract":
        return "code_execution"
    if not item.candidate_generic_specs:
        return "chief_architect"
    if any(_is_solution_space_spec(spec) for spec in item.candidate_generic_specs):
        return "dimension_reduction_optimizer"
    return "mathematical_modeler"


def _handoff_from(owner_agent_role: str) -> str:
    if owner_agent_role in {"mathematical_modeler", "dimension_reduction_optimizer"}:
        return "chief_architect"
    if owner_agent_role == "debug_diagnostics":
        return "code_execution"
    if owner_agent_role == "code_execution":
        return "mathematical_modeler"
    return "business_expert"


def _acceptance_checks(item: LegacyRuleMigrationItem) -> tuple[str, ...]:
    if item.generic_contract_status == "missing_rule_context":
        return (
            "wrap legacy operations in scheduler rule runtime context",
            "prove rule id appears in operation trace",
            "run focused runtime snapshot tests",
        )
    if item.generic_contract_status == "covered_by_generic_contract":
        return (
            "keep parity test green for generic contract",
            "retire or isolate equivalent legacy operation path",
            "run focused tests plus AI OR acceptance audit",
        )
    if item.candidate_generic_specs:
        return (
            "convert rule to OptimizationProblemSpec using candidate generic specs",
            "add parity test against legacy rule behavior",
            "run focused tests plus AI OR acceptance audit",
        )
    return (
        "ask chief architect agent to classify CP-SAT operation intent",
        "add missing operation-to-spec mapping if needed",
        "run focused migration backlog tests",
    )


def _is_solution_space_spec(spec: str) -> bool:
    return spec in {
        "CircuitConstraintSpec",
        "CumulativeConstraintSpec",
        "MultipleCircuitConstraintSpec",
        "NoOverlap2DConstraintSpec",
        "NoOverlapConstraintSpec",
        "ReservoirConstraintSpec",
    }


def _task_slug(rule_id: str) -> str:
    slug = "".join(ch if ch.isalnum() else "-" for ch in str(rule_id).lower()).strip("-")
    return slug or "unscoped"


def _status(rule_id: str, generic_ids: set[str]) -> str:
    if rule_id == "__unscoped__":
        return "missing_rule_context"
    if rule_id in generic_ids:
        return "covered_by_generic_contract"
    return "missing_generic_contract"


def _priority(status: str, operation_count: int) -> int:
    status_weight = {
        "missing_generic_contract": 20_000,
        "missing_rule_context": 10_000,
        "covered_by_generic_contract": 0,
    }.get(status, 0)
    return status_weight + operation_count


def _candidate_generic_specs(operation_types: tuple[str, ...]) -> tuple[str, ...]:
    specs: set[str] = set()
    for operation in operation_types:
        specs.update(_GENERIC_SPEC_CANDIDATES_BY_OPERATION.get(operation, ()))
    return tuple(sorted(specs))


_GENERIC_SPEC_CANDIDATES_BY_OPERATION: dict[str, tuple[str, ...]] = {
    "Add": ("LinearConstraintSpec",),
    "AddAbsEquality": ("AbsEqualityConstraintSpec",),
    "AddAllDifferent": ("AllDifferentConstraintSpec",),
    "AddAllowedAssignments": ("AllowedAssignmentsConstraintSpec",),
    "AddAssumption": ("CpSatSolveConfig.assumptions",),
    "AddAssumptions": ("CpSatSolveConfig.assumptions",),
    "AddAtLeastOne": ("AtLeastOneConstraintSpec",),
    "AddAtMostOne": ("AtMostOneConstraintSpec",),
    "AddAutomaton": ("AutomatonConstraintSpec",),
    "AddBoolAnd": ("BoolAndConstraintSpec",),
    "AddBoolOr": ("BoolOrConstraintSpec",),
    "AddBoolXOr": ("BoolXorConstraintSpec",),
    "AddCircuit": ("CircuitConstraintSpec",),
    "AddCumulative": ("CumulativeConstraintSpec",),
    "AddDecisionStrategy": ("DecisionStrategySpec",),
    "AddDivisionEquality": ("DivisionEqualityConstraintSpec",),
    "AddElement": ("ElementConstraintSpec",),
    "AddExactlyOne": ("ExactlyOneConstraintSpec",),
    "AddForbiddenAssignments": ("ForbiddenAssignmentsConstraintSpec",),
    "AddHint": ("SolutionHintSpec",),
    "AddImplication": ("ImplicationConstraintSpec",),
    "AddInverse": ("InverseConstraintSpec",),
    "AddLinearConstraint": ("LinearConstraintSpec",),
    "AddLinearExpressionInDomain": ("LinearExpressionInDomainConstraintSpec",),
    "AddMapDomain": ("MapDomainConstraintSpec",),
    "AddMaxEquality": ("MaxEqualityConstraintSpec",),
    "AddMinEquality": ("MinEqualityConstraintSpec",),
    "AddModuloEquality": ("ModuloEqualityConstraintSpec",),
    "AddMultipleCircuit": ("MultipleCircuitConstraintSpec",),
    "AddMultiplicationEquality": ("MultiplicationEqualityConstraintSpec",),
    "AddNoOverlap": ("NoOverlapConstraintSpec",),
    "AddNoOverlap2D": ("NoOverlap2DConstraintSpec",),
    "AddReservoirConstraint": ("ReservoirConstraintSpec",),
    "AddReservoirConstraintWithActive": ("ReservoirConstraintSpec",),
    "ClearObjective": ("ObjectiveSpec",),
    "Maximize": ("ObjectiveSpec",),
    "Minimize": ("ObjectiveSpec",),
    "NewBoolVar": ("VariableSpec.bool",),
    "NewConstant": ("VariableSpec",),
    "NewFixedSizeIntervalVar": ("IntervalSpec",),
    "NewIntVar": ("VariableSpec",),
    "NewIntervalVar": ("IntervalSpec",),
    "NewOptionalFixedSizeIntervalVar": ("IntervalSpec", "VariableSpec.bool"),
    "NewOptionalIntervalVar": ("IntervalSpec", "VariableSpec.bool"),
}


def _next_step(status: str, candidate_generic_specs: tuple[str, ...]) -> str:
    if status == "missing_rule_context":
        return "wrap this legacy operation path in a scheduler rule context first"
    if status == "covered_by_generic_contract":
        return "keep parity tests and retire the legacy operation path when equivalent"
    if candidate_generic_specs:
        return f"convert this legacy rule into OptimizationProblemSpec constraints using {', '.join(candidate_generic_specs)}"
    return "convert this legacy rule into OptimizationProblemSpec constraints"
