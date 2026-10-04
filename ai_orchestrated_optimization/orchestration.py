# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ai_orchestrated_optimization.agents import build_default_agent_architecture
from ai_orchestrated_optimization.contracts import OptimizationProblemSpec
from ai_orchestrated_optimization.cp_sat_backend import CpSatSolution, solve_cp_sat_problem
from ai_orchestrated_optimization.planning import build_rule_first_plan


REQUIRED_PRE_SOLVE_HANDOFFS = (
    "business_pain_description",
    "task_decomposition",
    "solution_space_analysis",
    "model_artifacts",
    "optimization_artifacts",
)


@dataclass(frozen=True)
class BusinessBrief:
    brief_id: str
    natural_language: str
    source: str = "human"


@dataclass(frozen=True)
class AgentHandoffArtifact:
    agent_role_id: str
    artifact_type: str
    content: str


@dataclass(frozen=True)
class AgentSolveRequest:
    brief: BusinessBrief
    handoff_artifacts: tuple[AgentHandoffArtifact, ...]
    problem: OptimizationProblemSpec


@dataclass(frozen=True)
class RuleTraceItem:
    rule_id: str
    rule_description: str
    enforcement: str
    priority: int
    constraints: tuple[str, ...]


@dataclass(frozen=True)
class AgentSolveReport:
    brief: BusinessBrief
    handoff_artifacts: tuple[AgentHandoffArtifact, ...]
    generated_handoff: AgentHandoffArtifact
    missing_handoffs: tuple[str, ...]
    rule_trace: tuple[RuleTraceItem, ...]
    solution: CpSatSolution
    debug_summary: dict[str, Any]


def run_agent_solve_workflow(
    request: AgentSolveRequest,
    *,
    time_limit_seconds: int | float = 30,
) -> AgentSolveReport:
    architecture = build_default_agent_architecture()
    _validate_agent_roles(request.handoff_artifacts, architecture_role_ids={agent.role_id for agent in architecture.agents})
    missing_handoffs = _missing_handoffs(request.handoff_artifacts)
    rule_trace = _build_rule_trace(request.problem)
    if missing_handoffs:
        solution = CpSatSolution(
            status_name="NOT_RUN",
            objective_value=None,
            values={},
            applied_constraints=(),
            rule_application_order=tuple(item.rule_id for item in rule_trace),
        )
        generated_handoff = AgentHandoffArtifact(
            "code_execution",
            "ortools_run_logs",
            "blocked_before_solve missing_handoffs=" + ",".join(missing_handoffs),
        )
        return AgentSolveReport(
            brief=request.brief,
            handoff_artifacts=request.handoff_artifacts,
            generated_handoff=generated_handoff,
            missing_handoffs=missing_handoffs,
            rule_trace=rule_trace,
            solution=solution,
            debug_summary=_debug_summary(solution, rule_trace, blocked=True, missing_handoffs=missing_handoffs),
        )

    solution = solve_cp_sat_problem(request.problem, time_limit_seconds=time_limit_seconds)
    generated_handoff = AgentHandoffArtifact(
        "code_execution",
        "ortools_run_logs",
        _solver_log_summary(solution),
    )
    return AgentSolveReport(
        brief=request.brief,
        handoff_artifacts=request.handoff_artifacts,
        generated_handoff=generated_handoff,
        missing_handoffs=(),
        rule_trace=rule_trace,
        solution=solution,
        debug_summary=_debug_summary(solution, rule_trace, blocked=False, missing_handoffs=()),
    )


def _validate_agent_roles(artifacts: tuple[AgentHandoffArtifact, ...], *, architecture_role_ids: set[str]) -> None:
    for artifact in artifacts:
        role_id = str(artifact.agent_role_id or "").strip()
        if role_id not in architecture_role_ids:
            raise ValueError(f"unknown agent role {role_id!r}")


def _missing_handoffs(artifacts: tuple[AgentHandoffArtifact, ...]) -> tuple[str, ...]:
    present = {str(artifact.artifact_type or "").strip() for artifact in artifacts}
    return tuple(handoff for handoff in REQUIRED_PRE_SOLVE_HANDOFFS if handoff not in present)


def _build_rule_trace(problem: OptimizationProblemSpec) -> tuple[RuleTraceItem, ...]:
    objective_rule_id = problem.objective.rule_id if problem.objective is not None else None
    plan = build_rule_first_plan(
        rules=problem.rules,
        constraints=problem.constraints,
        objective_rule_id=objective_rule_id,
    )
    constraints_by_rule: dict[str, list[str]] = {item.rule_id: [] for item in plan.rule_order}
    for item in plan.constraint_order:
        constraints_by_rule.setdefault(item.rule.rule_id, []).append(item.constraint.name)
    return tuple(
        RuleTraceItem(
            rule_id=item.rule.rule_id,
            rule_description=item.rule.description,
            enforcement=item.rule.enforcement,
            priority=int(item.rule.priority),
            constraints=tuple(constraints_by_rule.get(item.rule.rule_id, ())),
        )
        for item in plan.rule_order
    )


def _solver_log_summary(solution: CpSatSolution) -> str:
    parts = [
        f"status={solution.status_name}",
        f"objective={solution.objective_value}",
        f"applied_constraints={len(solution.applied_constraints)}",
        "rule_order=" + ",".join(solution.rule_application_order),
    ]
    return " ".join(parts)


def _debug_summary(
    solution: CpSatSolution,
    rule_trace: tuple[RuleTraceItem, ...],
    *,
    blocked: bool,
    missing_handoffs: tuple[str, ...],
) -> dict[str, Any]:
    return {
        "blocked": blocked,
        "missing_handoffs": missing_handoffs,
        "status_name": solution.status_name,
        "objective_value": solution.objective_value,
        "rule_count": len(rule_trace),
        "constraint_count": sum(len(item.constraints) for item in rule_trace),
        "next_action": _next_action(solution.status_name, blocked=blocked),
    }


def _next_action(status_name: str, *, blocked: bool) -> str:
    if blocked:
        return "complete required agent handoffs before running OR-Tools"
    if status_name in {"OPTIMAL", "FEASIBLE"}:
        return "debug agent should review rule priorities, objective value, and business acceptability"
    return "debug agent should inspect infeasible rules, missing variables, or contradictory constraints"
