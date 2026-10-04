# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AgentRole:
    role_id: str
    title: str
    responsibility: str


@dataclass(frozen=True)
class AgentArchitecture:
    agents: tuple[AgentRole, ...]
    handoffs: tuple[tuple[str, str, str], ...]


def build_default_agent_architecture() -> AgentArchitecture:
    """Return the canonical human-to-OR-Tools agent workflow."""
    return AgentArchitecture(
        agents=(
            AgentRole(
                role_id="business_expert",
                title="Business Expert Agent",
                responsibility="Describe the operational pain in human language and approve rule intent.",
            ),
            AgentRole(
                role_id="chief_architect",
                title="Chief Architect Agent",
                responsibility="Decompose the business problem and choose the optimization architecture.",
            ),
            AgentRole(
                role_id="mathematical_modeler",
                title="Mathematical Modeling Agent",
                responsibility="Define variables, Big-M links, 0-1 decisions, constraints, and objective terms.",
            ),
            AgentRole(
                role_id="dimension_reduction_optimizer",
                title="Mathematical Reduction and Optimization Agent",
                responsibility="Analyze solution space and propose column generation, cuts, decomposition, and pruning.",
            ),
            AgentRole(
                role_id="code_execution",
                title="Code Generation and Execution Agent",
                responsibility="Generate runnable OR-Tools code, execute CP-SAT, and persist artifacts.",
            ),
            AgentRole(
                role_id="debug_diagnostics",
                title="Log Diagnostics Debug Agent",
                responsibility="Read solver logs, infeasibility evidence, and rule traces to recommend repairs.",
            ),
        ),
        handoffs=(
            ("business_expert", "chief_architect", "business_pain_description"),
            ("chief_architect", "mathematical_modeler", "task_decomposition"),
            ("chief_architect", "dimension_reduction_optimizer", "solution_space_analysis"),
            ("mathematical_modeler", "code_execution", "model_artifacts"),
            ("dimension_reduction_optimizer", "code_execution", "optimization_artifacts"),
            ("code_execution", "debug_diagnostics", "ortools_run_logs"),
        ),
    )
