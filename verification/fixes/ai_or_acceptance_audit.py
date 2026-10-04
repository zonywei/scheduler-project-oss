from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


GENERATED_PREFIXES = ("tmp/", "outputs/", "scheduler/outputs/")
GENERATED_EXTENSIONS = (".xlsx", ".zip", ".png", ".jpg", ".jpeg", ".out", ".err", ".log")
PUBLIC_STATIC_IMAGE_PATHS = {
    "scheduler/app/static/assets/brand/courseorder-mark-v2.png",
    "scheduler/app/static/assets/formal-project-preview.png",
}


def _marker(*parts: str) -> str:
    return "".join(parts)


DEIDENTIFICATION_BLOCKLIST = (
    _marker("张", "三"),
    _marker("李", "四"),
    _marker("王", "五"),
    _marker("张", "老师"),
    _marker("李", "老师"),
    _marker("王", "老师"),
    _marker("赵", "老师"),
    _marker("陈", "老师"),
    _marker("刘", "老师"),
    _marker("孙", "老师"),
    _marker("周", "老师"),
    _marker("实验楼", "201"),
    _marker("实验楼", "302"),
    _marker("高一", "(3)班"),
    _marker("C:", "\\", "Users", "\\", "87", "859"),
    _marker("D:", "\\", "1", "\\", "github", "开源"),
)
DEIDENTIFICATION_PATTERNS = (
    ("windows_user_path", re.compile(r"\b[A-Za-z]:\\Users\\[^\s\\/:*?\"<>|]+")),
    ("escaped_windows_user_path", re.compile(r"\b[A-Za-z]:\\\\Users\\\\[^\s\\/:*?\"<>|]+")),
)
TEXT_SCAN_EXTENSIONS = (
    ".cfg",
    ".css",
    ".html",
    ".js",
    ".json",
    ".md",
    ".ps1",
    ".py",
    ".txt",
    ".yaml",
    ".yml",
)


@dataclass(frozen=True)
class FrameworkCheck:
    id: str
    requirement: str
    artifacts: tuple[str, ...]
    status: str
    evidence: tuple[str, ...]
    gap: str = ""


def _read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8-sig")


def _contains_all(text: str, needles: tuple[str, ...]) -> tuple[bool, tuple[str, ...]]:
    missing = tuple(needle for needle in needles if needle not in text)
    return not missing, missing


def _kernel_files_check(repo_root: Path) -> FrameworkCheck:
    files = (
        "ai_orchestrated_optimization/__init__.py",
        "ai_orchestrated_optimization/agents.py",
        "ai_orchestrated_optimization/contracts.py",
        "ai_orchestrated_optimization/planning.py",
        "ai_orchestrated_optimization/cp_sat_backend.py",
    )
    missing = tuple(path for path in files if not (repo_root / path).exists())
    if missing:
        return FrameworkCheck(
            "generic_kernel_files",
            "通用 AI 运筹优化内核必须作为独立包存在，不能只停留在 scheduler 示例目录里。",
            files,
            "fail",
            tuple(),
            gap=f"缺少文件：{', '.join(missing)}",
        )
    combined = "\n".join(_read_text(repo_root / path) for path in files)
    ok, missing_symbols = _contains_all(
        combined,
        (
            "RuleSpec",
            "OptimizationProblemSpec",
            "RuleFirstPlan",
            "solve_cp_sat_problem",
            "enforcement_literals",
            "AllDifferentConstraintSpec",
            "NoOverlapConstraintSpec",
            "CumulativeConstraintSpec",
            "AllowedAssignmentsConstraintSpec",
            "ElementConstraintSpec",
            "AutomatonConstraintSpec",
            "InverseConstraintSpec",
            "CircuitConstraintSpec",
            "NoOverlap2DConstraintSpec",
            "AbsEqualityConstraintSpec",
            "MultiplicationEqualityConstraintSpec",
            "DivisionEqualityConstraintSpec",
            "ModuloEqualityConstraintSpec",
            "MapDomainConstraintSpec",
            "MultipleCircuitConstraintSpec",
            "ReservoirConstraintSpec",
            "CpSatSolveConfig",
            "SolverParameterSpec",
            "SolutionHintSpec",
            "DecisionStrategySpec",
            "apply_cp_sat_solve_config",
            "AgentSolveRequest",
            "run_agent_solve_workflow",
        ),
    )
    return FrameworkCheck(
        "generic_kernel_files",
        "通用 AI 运筹优化内核必须提供规则、变量、约束、计划和 CP-SAT 后端合同。",
        files,
        "pass" if ok else "fail",
        ("通用内核文件存在，并公开多 Agent 编排、线性、reified/enforced 线性约束、布尔逻辑、表约束、Element、Automaton、Inverse、Circuit、MultipleCircuit、AllDifferent、NoOverlap、NoOverlap2D、Cumulative、Reservoir、算术、hint、assumption、decision strategy 和 solver parameter 等 CP-SAT 原语/控制面。",) if ok else tuple(),
        gap="" if ok else f"缺少公开原语：{', '.join(missing_symbols)}",
    )


def _agent_architecture_check() -> FrameworkCheck:
    try:
        from ai_orchestrated_optimization import build_default_agent_architecture

        architecture = build_default_agent_architecture()
        roles = tuple(agent.role_id for agent in architecture.agents)
        handoffs = set(architecture.handoffs)
    except Exception as exc:  # pragma: no cover - defensive audit output
        return FrameworkCheck(
            "agent_architecture_contract",
            "默认 Agent 拓扑必须固化用户要求的业务专家、首席架构、数学建模、降维优化、执行和诊断链路。",
            ("ai_orchestrated_optimization/agents.py",),
            "fail",
            tuple(),
            gap=f"无法加载默认 Agent 拓扑：{exc}",
        )

    required_roles = (
        "business_expert",
        "chief_architect",
        "mathematical_modeler",
        "dimension_reduction_optimizer",
        "code_execution",
        "debug_diagnostics",
    )
    required_handoffs = {
        ("business_expert", "chief_architect", "business_pain_description"),
        ("chief_architect", "mathematical_modeler", "task_decomposition"),
        ("chief_architect", "dimension_reduction_optimizer", "solution_space_analysis"),
        ("mathematical_modeler", "code_execution", "model_artifacts"),
        ("dimension_reduction_optimizer", "code_execution", "optimization_artifacts"),
        ("code_execution", "debug_diagnostics", "ortools_run_logs"),
    }
    missing_roles = tuple(role for role in required_roles if role not in roles)
    missing_handoffs = tuple(sorted(required_handoffs - handoffs))
    ok = not missing_roles and not missing_handoffs
    return FrameworkCheck(
        "agent_architecture_contract",
        "默认 Agent 拓扑必须固化用户要求的业务专家、首席架构、数学建模、降维优化、执行和诊断链路。",
        ("ai_orchestrated_optimization/agents.py",),
        "pass" if ok else "fail",
        (f"roles={','.join(roles)}",) if ok else tuple(),
        gap="" if ok else f"缺少 roles={missing_roles}; handoffs={missing_handoffs}",
    )


def _generic_solver_capabilities_check() -> FrameworkCheck:
    try:
        from ai_orchestrated_optimization import (
            AbsEqualityConstraintSpec,
            AllDifferentConstraintSpec,
            AllowedAssignmentsConstraintSpec,
            AutomatonConstraintSpec,
            CircuitArcSpec,
            CircuitConstraintSpec,
            CpSatSolveConfig,
            DecisionStrategySpec,
            CumulativeConstraintSpec,
            DivisionEqualityConstraintSpec,
            ElementConstraintSpec,
            ExactlyOneConstraintSpec,
            ForbiddenAssignmentsConstraintSpec,
            IntervalSpec,
            InverseConstraintSpec,
            LinearConstraintSpec,
            LinearExpressionInDomainConstraintSpec,
            LinearExpression,
            LinearTerm,
            MapDomainConstraintSpec,
            MaxEqualityConstraintSpec,
            MinEqualityConstraintSpec,
            ModuloEqualityConstraintSpec,
            MultipleCircuitConstraintSpec,
            MultiplicationEqualityConstraintSpec,
            NoOverlap2DConstraintSpec,
            NoOverlapConstraintSpec,
            ObjectiveSpec,
            OptimizationProblemSpec,
            ReservoirConstraintSpec,
            RuleSpec,
            SolutionHintSpec,
            SolverParameterSpec,
            VariableSpec,
            solve_cp_sat_problem,
        )

        resource_problem = OptimizationProblemSpec(
            problem_id="audit_generic_resource_problem",
            variables=(
                VariableSpec("slot_a", 1, 3),
                VariableSpec("slot_b", 1, 3),
                VariableSpec("start_a", 0, 5),
                VariableSpec("end_a", 0, 5),
                VariableSpec("start_b", 0, 5),
                VariableSpec("end_b", 0, 5),
            ),
            intervals=(
                IntervalSpec("task_a", start="start_a", size=2, end="end_a"),
                IntervalSpec("task_b", start="start_b", size=3, end="end_b"),
            ),
            rules=(
                RuleSpec("unique_choice", "generic items occupy unique choices", "hard", 10),
                RuleSpec("resource_capacity", "generic one-machine capacity", "hard", 20),
                RuleSpec("finish_b_early", "generic objective preference", "soft", 100),
            ),
            constraints=(
                AllDifferentConstraintSpec("unique_slots", ("slot_a", "slot_b"), "unique_choice"),
                NoOverlapConstraintSpec("machine_no_overlap", ("task_a", "task_b"), "resource_capacity"),
                CumulativeConstraintSpec("machine_capacity", ("task_a", "task_b"), (1, 1), 1, "resource_capacity"),
            ),
            objective=ObjectiveSpec("finish_b_early", "minimize", LinearExpression((LinearTerm("end_b", 1),))),
        )
        resource_solution = solve_cp_sat_problem(resource_problem, time_limit_seconds=5)
        table_problem = OptimizationProblemSpec(
            problem_id="audit_generic_table_element_automaton_problem",
            variables=(
                VariableSpec.bool("pick_a"),
                VariableSpec.bool("pick_b"),
                VariableSpec("item", 0, 1),
                VariableSpec("machine", 0, 1),
                VariableSpec("cost", 0, 10),
                VariableSpec("bit_0", 0, 1),
                VariableSpec("bit_1", 0, 1),
                VariableSpec("perm_0", 0, 1),
                VariableSpec("perm_1", 0, 1),
                VariableSpec("inv_0", 0, 1),
                VariableSpec("inv_1", 0, 1),
                VariableSpec.bool("arc_0_1"),
                VariableSpec.bool("arc_1_0"),
            ),
            rules=(
                RuleSpec("bool_choice", "exactly one candidate", "hard", 10),
                RuleSpec("table_pairing", "legal assignment table", "hard", 20),
                RuleSpec("indexed_cost", "lookup cost by selected item", "hard", 30),
                RuleSpec("state_machine", "state machine over activity bits", "hard", 40),
                RuleSpec("permutation", "inverse permutation consistency", "hard", 50),
                RuleSpec("route_cycle", "two-node circuit", "hard", 60),
                RuleSpec("minimize_cost", "generic objective", "soft", 100),
            ),
            constraints=(
                ExactlyOneConstraintSpec("exactly_one_pick", ("pick_a", "pick_b"), "bool_choice"),
                AllowedAssignmentsConstraintSpec("allowed_pairs", ("item", "machine"), ((0, 1), (1, 0)), "table_pairing"),
                ForbiddenAssignmentsConstraintSpec("blocked_pair", ("item", "machine"), ((0, 0),), "table_pairing"),
                ElementConstraintSpec("cost_lookup", "item", (5, 2), "cost", "indexed_cost"),
                AutomatonConstraintSpec(
                    "no_two_active_bits",
                    ("bit_0", "bit_1"),
                    0,
                    (0, 1),
                    ((0, 0, 0), (0, 1, 1), (1, 0, 0)),
                    "state_machine",
                ),
                InverseConstraintSpec("inverse_pair", ("perm_0", "perm_1"), ("inv_0", "inv_1"), "permutation"),
                CircuitConstraintSpec(
                    "two_node_cycle",
                    (CircuitArcSpec(0, 1, "arc_0_1"), CircuitArcSpec(1, 0, "arc_1_0")),
                    "route_cycle",
                ),
            ),
            objective=ObjectiveSpec("minimize_cost", "minimize", LinearExpression((LinearTerm("cost", 1),))),
        )
        table_solution = solve_cp_sat_problem(table_problem, time_limit_seconds=5)
        packing_problem = OptimizationProblemSpec(
            problem_id="audit_generic_no_overlap_2d_problem",
            variables=(
                VariableSpec("a_x_start", 0, 4),
                VariableSpec("a_x_end", 0, 6),
                VariableSpec("b_x_start", 0, 4),
                VariableSpec("b_x_end", 0, 6),
            ),
            intervals=(
                IntervalSpec("rect_a_x", "a_x_start", 2, "a_x_end"),
                IntervalSpec("rect_a_y", 0, 2, 2),
                IntervalSpec("rect_b_x", "b_x_start", 2, "b_x_end"),
                IntervalSpec("rect_b_y", 0, 2, 2),
            ),
            rules=(
                RuleSpec("packing", "2D rectangles cannot overlap", "hard", 10),
                RuleSpec("finish_early", "generic objective", "soft", 100),
            ),
            constraints=(NoOverlap2DConstraintSpec("pack_rectangles", ("rect_a_x", "rect_b_x"), ("rect_a_y", "rect_b_y"), "packing"),),
            objective=ObjectiveSpec("finish_early", "minimize", LinearExpression((LinearTerm("b_x_end", 1),))),
        )
        packing_solution = solve_cp_sat_problem(packing_problem, time_limit_seconds=5)
        arithmetic_problem = OptimizationProblemSpec(
            problem_id="audit_generic_arithmetic_reservoir_problem",
            variables=(
                VariableSpec("x", -5, 5),
                VariableSpec("abs_x", 0, 5),
                VariableSpec("y", 3, 3),
                VariableSpec("product", 0, 30),
                VariableSpec("quotient", 0, 10),
                VariableSpec("remainder", 0, 2),
                VariableSpec("max_value", 0, 10),
                VariableSpec("min_value", 0, 10),
            ),
            rules=(
                RuleSpec("domain", "disjoint integer domain", "hard", 10),
                RuleSpec("arithmetic", "derived arithmetic variables", "hard", 20),
                RuleSpec("inventory", "reservoir bounds", "hard", 30),
                RuleSpec("prefer_negative", "generic objective", "soft", 100),
            ),
            constraints=(
                LinearExpressionInDomainConstraintSpec("x_domain", LinearExpression((LinearTerm("x", 1),)), ((-2, -2), (2, 2)), "domain"),
                AbsEqualityConstraintSpec("abs_x_value", "abs_x", "x", "arithmetic"),
                MultiplicationEqualityConstraintSpec("product_value", "product", ("abs_x", "y"), "arithmetic"),
                DivisionEqualityConstraintSpec("quotient_value", "quotient", "product", "y", "arithmetic"),
                ModuloEqualityConstraintSpec("remainder_value", "remainder", "product", 3, "arithmetic"),
                MaxEqualityConstraintSpec("max_value_helper", "max_value", ("abs_x", "y"), "arithmetic"),
                MinEqualityConstraintSpec("min_value_helper", "min_value", ("abs_x", "y"), "arithmetic"),
                ReservoirConstraintSpec("inventory_bounds", (0, 1, 2), (3, -2, -1), 0, 3, "inventory"),
            ),
            objective=ObjectiveSpec("prefer_negative", "minimize", LinearExpression((LinearTerm("x", 1),))),
        )
        arithmetic_solution = solve_cp_sat_problem(arithmetic_problem, time_limit_seconds=5)
        map_route_problem = OptimizationProblemSpec(
            problem_id="audit_generic_map_multiple_circuit_problem",
            variables=(
                VariableSpec("route_choice", 0, 1),
                VariableSpec.bool("route_zero"),
                VariableSpec.bool("route_one"),
                VariableSpec.bool("arc_0_1"),
                VariableSpec.bool("arc_1_0"),
            ),
            rules=(
                RuleSpec("map_domain", "choice integer maps to bools", "hard", 10),
                RuleSpec("routing", "multi-route circuit", "hard", 20),
                RuleSpec("prefer_route_one", "generic objective", "soft", 100),
            ),
            constraints=(
                MapDomainConstraintSpec("choice_to_literals", "route_choice", ("route_zero", "route_one"), 0, "map_domain"),
                MultipleCircuitConstraintSpec(
                    "two_node_multi_circuit",
                    (CircuitArcSpec(0, 1, "arc_0_1"), CircuitArcSpec(1, 0, "arc_1_0")),
                    "routing",
                ),
            ),
            objective=ObjectiveSpec("prefer_route_one", "maximize", LinearExpression((LinearTerm("route_choice", 1),))),
        )
        map_route_solution = solve_cp_sat_problem(map_route_problem, time_limit_seconds=5)
        control_problem = OptimizationProblemSpec(
            problem_id="audit_generic_solver_control_problem",
            variables=(VariableSpec.bool("fast"), VariableSpec.bool("cheap")),
            rules=(
                RuleSpec("pick_one", "one option is selected", "hard", 10),
                RuleSpec("prefer_cheap", "cheap option is preferred", "soft", 100),
            ),
            constraints=(ExactlyOneConstraintSpec("exactly_one_option", ("fast", "cheap"), "pick_one"),),
            objective=ObjectiveSpec(
                "prefer_cheap",
                "minimize",
                LinearExpression((LinearTerm("fast", 3), LinearTerm("cheap", 1))),
            ),
            solve_config=CpSatSolveConfig(
                parameters=(
                    SolverParameterSpec("search_branching", "FIXED_SEARCH"),
                    SolverParameterSpec("num_search_workers", 1),
                ),
                hints=(SolutionHintSpec("fast", 1),),
                decision_strategies=(
                    DecisionStrategySpec(
                        ("fast", "cheap"),
                        "CHOOSE_FIRST",
                        "SELECT_MAX_VALUE",
                        "pick_one",
                    ),
                ),
            ),
        )
        control_solution = solve_cp_sat_problem(control_problem, time_limit_seconds=5)
        assumption_problem = OptimizationProblemSpec(
            problem_id="audit_generic_assumption_core_problem",
            variables=(VariableSpec.bool("forced_bad_choice"),),
            rules=(
                RuleSpec("hard_exclusion", "choice is disallowed", "hard", 10),
                RuleSpec("debug_assumption", "debug agent assumes it for diagnosis", "hard", 20),
            ),
            constraints=(
                LinearConstraintSpec(
                    "exclude_bad_choice",
                    LinearExpression((LinearTerm("forced_bad_choice", 1),)),
                    "==",
                    0,
                    "hard_exclusion",
                ),
            ),
            solve_config=CpSatSolveConfig(assumptions=("forced_bad_choice",)),
        )
        assumption_solution = solve_cp_sat_problem(assumption_problem, time_limit_seconds=5)
    except Exception as exc:  # pragma: no cover - defensive audit output
        return FrameworkCheck(
            "generic_solver_capabilities",
            "通用后端必须能证明非排课问题可经同一规则优先入口求解。",
            ("ai_orchestrated_optimization/cp_sat_backend.py", "verification/fixes/tests/test_ai_or_framework.py"),
            "fail",
            tuple(),
            gap=f"通用 CP-SAT smoke 运行失败：{exc}",
        )

    ok = (
        resource_solution.status_name in {"OPTIMAL", "FEASIBLE"}
        and resource_solution.values.get("end_b") == 3
        and table_solution.status_name in {"OPTIMAL", "FEASIBLE"}
        and table_solution.values.get("cost") == 2
        and packing_solution.status_name in {"OPTIMAL", "FEASIBLE"}
        and arithmetic_solution.status_name in {"OPTIMAL", "FEASIBLE"}
        and arithmetic_solution.values.get("product") == 6
        and map_route_solution.status_name in {"OPTIMAL", "FEASIBLE"}
        and map_route_solution.values.get("route_choice") == 1
        and control_solution.status_name in {"OPTIMAL", "FEASIBLE"}
        and control_solution.solver_parameters.get("search_branching") == "FIXED_SEARCH"
        and control_solution.decision_strategy_count == 1
        and control_solution.solution_hints == {"fast": 1}
        and assumption_solution.status_name == "INFEASIBLE"
        and assumption_solution.assumption_core == ("forced_bad_choice",)
    )
    return FrameworkCheck(
        "generic_solver_capabilities",
        "通用后端必须能证明非排课问题可经同一规则优先入口求解。",
        ("ai_orchestrated_optimization/cp_sat_backend.py", "verification/fixes/tests/test_ai_or_framework.py"),
        "pass" if ok else "fail",
        (
            f"resource_status={resource_solution.status_name}",
            f"resource_objective={resource_solution.objective_value}",
            f"table_element_status={table_solution.status_name}",
            f"table_element_cost={table_solution.values.get('cost')}",
            f"packing_status={packing_solution.status_name}",
            f"arithmetic_status={arithmetic_solution.status_name}",
            f"arithmetic_product={arithmetic_solution.values.get('product')}",
            f"map_route_status={map_route_solution.status_name}",
            f"control_status={control_solution.status_name}",
            f"control_search={control_solution.solver_parameters.get('search_branching')}",
            f"assumption_core={','.join(assumption_solution.assumption_core)}",
        )
        if ok
        else tuple(),
        gap="" if ok else (
            "非排课 smoke 未得到预期可行解："
            f"resource={resource_solution.status_name}/{resource_solution.values}; "
            f"table={table_solution.status_name}/{table_solution.values}; "
            f"packing={packing_solution.status_name}/{packing_solution.values}; "
            f"arithmetic={arithmetic_solution.status_name}/{arithmetic_solution.values}; "
            f"map_route={map_route_solution.status_name}/{map_route_solution.values}; "
            f"control={control_solution.status_name}/{control_solution.solver_parameters}; "
            f"assumption={assumption_solution.status_name}/{assumption_solution.assumption_core}"
        ),
    )


def _agent_orchestration_workflow_check() -> FrameworkCheck:
    try:
        from ai_orchestrated_optimization import (
            AgentHandoffArtifact,
            AgentSolveRequest,
            BusinessBrief,
            LinearConstraintSpec,
            LinearExpression,
            LinearTerm,
            ObjectiveSpec,
            OptimizationProblemSpec,
            RuleSpec,
            VariableSpec,
            run_agent_solve_workflow,
        )

        problem = OptimizationProblemSpec(
            problem_id="audit_agent_orchestration_assignment",
            variables=(
                VariableSpec.bool("alice_a"),
                VariableSpec.bool("alice_b"),
                VariableSpec.bool("bob_a"),
                VariableSpec.bool("bob_b"),
            ),
            rules=(
                RuleSpec("coverage", "each task assigned once", "hard", 10),
                RuleSpec("capacity", "each worker handles one task", "hard", 20),
                RuleSpec("cost", "minimize assignment cost", "soft", 100),
            ),
            constraints=(
                LinearConstraintSpec("cover_a", LinearExpression((LinearTerm("alice_a", 1), LinearTerm("bob_a", 1))), "==", 1, "coverage"),
                LinearConstraintSpec("cover_b", LinearExpression((LinearTerm("alice_b", 1), LinearTerm("bob_b", 1))), "==", 1, "coverage"),
                LinearConstraintSpec("cap_alice", LinearExpression((LinearTerm("alice_a", 1), LinearTerm("alice_b", 1))), "<=", 1, "capacity"),
                LinearConstraintSpec("cap_bob", LinearExpression((LinearTerm("bob_a", 1), LinearTerm("bob_b", 1))), "<=", 1, "capacity"),
            ),
            objective=ObjectiveSpec(
                "cost",
                "minimize",
                LinearExpression(
                    (
                        LinearTerm("alice_a", 4),
                        LinearTerm("alice_b", 1),
                        LinearTerm("bob_a", 1),
                        LinearTerm("bob_b", 4),
                    )
                ),
            ),
        )
        report = run_agent_solve_workflow(
            AgentSolveRequest(
                brief=BusinessBrief("audit-brief", "人类用自然语言描述两个任务和两个人的分配痛点。"),
                handoff_artifacts=(
                    AgentHandoffArtifact("business_expert", "business_pain_description", "two tasks, two workers, minimize cost"),
                    AgentHandoffArtifact("chief_architect", "task_decomposition", "binary assignment model"),
                    AgentHandoffArtifact("chief_architect", "solution_space_analysis", "small exact CP-SAT solve"),
                    AgentHandoffArtifact("mathematical_modeler", "model_artifacts", "coverage and capacity constraints"),
                    AgentHandoffArtifact("dimension_reduction_optimizer", "optimization_artifacts", "no decomposition needed"),
                ),
                problem=problem,
            ),
            time_limit_seconds=5,
        )
    except Exception as exc:  # pragma: no cover - defensive audit output
        return FrameworkCheck(
            "agent_orchestration_workflow",
            "框架必须把人类自然语言 brief、多 Agent 交接物、规则优先求解和 Debug 诊断报告连成可执行链路。",
            ("ai_orchestrated_optimization/orchestration.py", "verification/fixes/tests/test_ai_or_orchestration.py"),
            "fail",
            tuple(),
            gap=f"Agent 编排 smoke 运行失败：{exc}",
        )

    ok = (
        report.solution.status_name == "OPTIMAL"
        and report.solution.objective_value == 2
        and report.missing_handoffs == ()
        and report.generated_handoff.artifact_type == "ortools_run_logs"
        and report.debug_summary.get("constraint_count") == 4
    )
    return FrameworkCheck(
        "agent_orchestration_workflow",
        "框架必须把人类自然语言 brief、多 Agent 交接物、规则优先求解和 Debug 诊断报告连成可执行链路。",
        ("ai_orchestrated_optimization/orchestration.py", "verification/fixes/tests/test_ai_or_orchestration.py"),
        "pass" if ok else "fail",
        (
            f"workflow_status={report.solution.status_name}",
            f"workflow_objective={report.solution.objective_value}",
            f"generated_handoff={report.generated_handoff.artifact_type}",
            f"debug_constraint_count={report.debug_summary.get('constraint_count')}",
        )
        if ok
        else tuple(),
        gap="" if ok else f"Agent 编排报告不符合预期：{report}",
    )


def _scheduler_generic_rule_bridge_check(repo_root: Path) -> FrameworkCheck:
    try:
        import yaml

        from ai_orchestrated_optimization import solve_cp_sat_problem
        from scheduler.config.loader import load_effective_config
        from scheduler.domain.rule_instance import compile_rule_instances, rule_instances_from_mapping
        from scheduler.domain.school_profile import profile_from_mapping
        from scheduler.rules import build_default_rule_registry, build_rule_execution_plan
        from scheduler.rules.generic_bridge import (
            generic_scheduler_rule_contract_summary,
            scheduler_execution_plan_to_ai_or_problem,
        )

        profile_path = repo_root / "profiles" / "current_school" / "profile.yaml"
        profile_data = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
        profile = profile_from_mapping(profile_data, source=profile_path.relative_to(repo_root).as_posix())
        instances = compile_rule_instances(rule_instances_from_mapping(profile_data, source=profile.source))
        effective_cfg = load_effective_config(
            "joint",
            {
                "io_path": repo_root / "scheduler" / "config" / "io.yaml",
                "rules_path": repo_root / "scheduler" / "config" / "rules.yaml",
            },
        ).effective_cfg
        plan = build_rule_execution_plan(
            build_default_rule_registry(),
            effective_cfg,
            mode="joint",
            profile=profile,
            rule_instances=instances,
            only_enabled=True,
            source="profiles/current_school/profile.yaml",
        )
        bridge = scheduler_execution_plan_to_ai_or_problem(plan)
        contract_summary = generic_scheduler_rule_contract_summary()
        solution = solve_cp_sat_problem(bridge.problem, time_limit_seconds=5)
    except Exception as exc:  # pragma: no cover - defensive audit output
        return FrameworkCheck(
            "scheduler_generic_rule_bridge",
            "旧 scheduler 示例层必须能把现有 RuleExecutionPlan 提升为通用 RuleSpec/RuleFirstPlan/OptimizationProblemSpec，以证明规则优先迁移不是只停留在新包。",
            ("scheduler/rules/generic_bridge.py", "verification/fixes/tests/test_scheduler_generic_rule_bridge.py"),
            "fail",
            tuple(),
            gap=f"scheduler generic bridge smoke 运行失败：{exc}",
        )

    ok = (
        solution.status_name == "OPTIMAL"
        and len(bridge.problem.rules) == len(plan.items)
        and len(bridge.problem.constraints) == len(plan.items)
        and "scheduler__joint__night__fri_sun_mutex" in bridge.metadata_by_rule
        and "scheduler__joint__night__soft_objective" in bridge.metadata_by_rule
    )
    return FrameworkCheck(
        "scheduler_generic_rule_bridge",
        "旧 scheduler 示例层必须能把现有 RuleExecutionPlan 提升为通用 RuleSpec/RuleFirstPlan/OptimizationProblemSpec，以证明规则优先迁移不是只停留在新包。",
        ("scheduler/rules/generic_bridge.py", "verification/fixes/tests/test_scheduler_generic_rule_bridge.py"),
        "pass" if ok else "fail",
        (
            f"scheduler_bridge_status={solution.status_name}",
            f"scheduler_bridge_rules={len(bridge.problem.rules)}",
            f"scheduler_bridge_constraints={len(bridge.problem.constraints)}",
            f"scheduler_bridge_profile={plan.profile_id}",
            f"scheduler_bridge_contract_scope_exact_cp_sat_shape={contract_summary.get('exact_cp_sat_shape_contract', 0)}",
            f"scheduler_bridge_contract_scope_catalog={contract_summary.get('catalog_contract', 0)}",
        )
        if ok
        else tuple(),
        gap="" if ok else f"scheduler generic bridge 未得到预期结果：status={solution.status_name}, rules={len(bridge.problem.rules)}",
    )


def _scheduler_solver_controls_bridge_check() -> FrameworkCheck:
    try:
        from ortools.sat.python import cp_model

        from ai_orchestrated_optimization import (
            create_existing_cp_model,
            build_legacy_rule_migration_backlog,
            get_existing_cp_model_operation_trace,
            solve_cp_sat_problem,
            summarize_existing_cp_model_operations_by_rule,
        )
        from scheduler.solver.solve import solve_model
        from scheduler.data.day_rules_reader import DayInputData, Slot
        from scheduler.rules.generic_bridge import (
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
            day_teacher_whitelist_hard_to_ai_or_problem,
            day_two_class_am1_pm1_combo_to_ai_or_problem,
            day_two_class_daily_min_per_class_to_ai_or_problem,
            day_two_class_low_hours_max_empty_days_to_ai_or_problem,
            day_weekday_subject_balance_to_ai_or_problem,
            day_weekend_cross_halfday_penalty_to_ai_or_problem,
            day_weekend_double_period_same_class_to_ai_or_problem,
            day_weekend_halfday_constraint_to_ai_or_problem,
            day_weekend_one_day_only_to_ai_or_problem,
            day_weekend_subject_whitelist_to_ai_or_problem,
            day_yjc_sunday_am12_pm12_to_ai_or_problem,
            day_special_duty_catalog_to_ai_or_problem,
            duty_joint_to_ai_or_problem,
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
        )
        from scheduler.model.constraints.duty_joint_constraints import DutyJointConfig
        from scheduler.model.constraints.grade_group_duty_constraints import GradeGroupDutyConfig
        from scheduler.rules.personalized_legacy import PERSONALIZED_RULE_INSTANCE_TEMPLATE_IDS
        from scheduler.rules.registry import RuleRegistry
        from scheduler.rules.runtime import _make_rule_wrapper, rule_runtime_context, runtime_trace_payload
        from scheduler.rules.spec import RuleSpec as SchedulerRuleSpec
        from scheduler.solver_params import build_scheduler_cp_sat_solve_config

        def _audit_rule(model):
            audit_var = model.NewBoolVar("scheduler_runtime_rule_trace_smoke")
            model.Add(audit_var == 1)
            return audit_var

        runtime_registry = RuleRegistry()
        runtime_registry.register(
            SchedulerRuleSpec(
                rule_id="audit.rule_trace",
                name="Audit rule trace",
                category_path="audit",
                stage="constraints",
                order=1,
                tags=("audit",),
                apply_fn=_audit_rule,
            )
        )
        runtime_trace_rows: list[dict] = []
        runtime_trace_model = create_existing_cp_model("scheduler.runtime_rule_trace.audit")
        wrapped_audit_rule = _make_rule_wrapper(
            rule_id="audit.rule_trace",
            fn_name="_audit_rule",
            fn=_audit_rule,
        )
        with rule_runtime_context(
            mode="audit",
            run_id="audit",
            effective_cfg={},
            registry=runtime_registry,
            trace=runtime_trace_rows,
        ):
            wrapped_audit_rule(runtime_trace_model)
        runtime_operation_trace = get_existing_cp_model_operation_trace(runtime_trace_model)
        scheduler_rule_operation_trace = (
            len(runtime_operation_trace) == 2
            and {item.rule_id for item in runtime_operation_trace} == {"audit.rule_trace"}
            and runtime_trace_rows
            and runtime_trace_rows[0].get("ai_or_operation_delta") == 2
        )
        runtime_operation_summary = summarize_existing_cp_model_operations_by_rule(runtime_trace_model)
        runtime_trace_snapshot = runtime_trace_payload(
            mode="audit",
            run_id="audit",
            git_commit=None,
            trace=runtime_trace_rows,
        )
        scheduler_rule_operation_summary = (
            runtime_operation_summary
            == {
                "audit.rule_trace": {
                    "operation_count": 2,
                    "operations": {"Add": 1, "NewBoolVar": 1},
                }
            }
            and runtime_trace_snapshot["ai_or_operation_summary"]["total_operation_delta"] == 2
            and runtime_trace_snapshot["ai_or_operation_summary"]["rules"]["audit.rule_trace"]["operation_delta"] == 2
            and runtime_trace_snapshot["ai_or_operation_summary"]["rules"]["audit.rule_trace"]["operations"] == {
                "Add": 1,
                "NewBoolVar": 1,
            }
        )
        migration_backlog = build_legacy_rule_migration_backlog(
            {
                **runtime_operation_summary,
                "audit.generic_ready": {"operation_count": 1, "operations": {"Add": 1}},
            },
            generic_rule_ids=("audit.generic_ready",),
        )
        scheduler_rule_migration_backlog = (
            tuple(item.rule_id for item in migration_backlog) == (
                "audit.rule_trace",
                "audit.generic_ready",
            )
            and migration_backlog[0].generic_contract_status == "missing_generic_contract"
            and migration_backlog[0].candidate_generic_specs == ("LinearConstraintSpec", "VariableSpec.bool")
            and migration_backlog[1].generic_contract_status == "covered_by_generic_contract"
        )
        runtime_migration_snapshot = runtime_trace_payload(
            mode="audit",
            run_id="audit",
            git_commit=None,
            trace=[*runtime_trace_rows, {"rule_id": "audit.generic_ready", "ai_or_operation_delta": 1}],
            generic_rule_ids=("audit.generic_ready",),
        )
        runtime_snapshot_backlog = runtime_migration_snapshot["ai_or_migration_backlog"]
        scheduler_runtime_snapshot_migration_backlog = (
            tuple(item["rule_id"] for item in runtime_snapshot_backlog) == (
                "audit.rule_trace",
                "audit.generic_ready",
            )
            and runtime_snapshot_backlog[0]["generic_contract_status"] == "missing_generic_contract"
            and runtime_snapshot_backlog[1]["generic_contract_status"] == "covered_by_generic_contract"
        )
        scheduler_runtime_snapshot_operation_types = (
            runtime_trace_rows[0].get("ai_or_operations_by_type") == {"Add": 1, "NewBoolVar": 1}
            and tuple(runtime_snapshot_backlog[0]["operation_types"]) == ("Add", "NewBoolVar")
            and tuple(runtime_snapshot_backlog[1]["operation_types"]) == ()
        )
        scheduler_runtime_snapshot_candidate_specs = (
            tuple(runtime_snapshot_backlog[0]["candidate_generic_specs"]) == (
                "LinearConstraintSpec",
                "VariableSpec.bool",
            )
            and tuple(runtime_snapshot_backlog[1]["candidate_generic_specs"]) == ()
        )
        runtime_agent_plan = runtime_migration_snapshot["ai_or_agent_migration_plan"]
        scheduler_agent_migration_plan_roles = (
            tuple(item["rule_id"] for item in runtime_agent_plan) == (
                "audit.rule_trace",
                "audit.generic_ready",
            )
            and runtime_agent_plan[0]["owner_agent_role"] == "mathematical_modeler"
            and runtime_agent_plan[0]["handoff_from"] == "chief_architect"
            and runtime_agent_plan[1]["owner_agent_role"] == "code_execution"
        )
        hard_base_bridge = night_hard_base_to_ai_or_problem(
            classes=("class_a", "class_b"),
            cst={
                ("class_a", "math"): "teacher_1",
                ("class_a", "science"): "teacher_2",
                ("class_b", "math"): "teacher_1",
                ("class_b", "science"): "teacher_3",
            },
            days=("day_1", "day_2"),
            periods=("night_1",),
            rules={"evening": {"weekly_occurrences_per_subject": 1}},
        )
        hard_base_solution = solve_cp_sat_problem(hard_base_bridge.problem, time_limit_seconds=5)
        hard_base_runtime_snapshot = runtime_trace_payload(
            mode="joint",
            run_id="audit",
            git_commit=None,
            trace=[
                {
                    "rule_id": "joint.night.hard_base",
                    "ai_or_operation_delta": 3,
                    "ai_or_operations_by_type": {"Add": 3},
                }
            ],
            generic_rule_ids=generic_scheduler_rule_ids(),
        )
        service_source = _read_text(REPO_ROOT / "scheduler" / "app" / "service.py")
        scheduler_real_rule_generic_contract = (
            hard_base_solution.status_name == "OPTIMAL"
            and hard_base_bridge.metadata_by_rule["night.hard_base"]["generic_contract_status"] == "covered_by_generic_contract"
            and "joint.night.hard_base" in generic_scheduler_rule_ids()
            and hard_base_runtime_snapshot["ai_or_migration_backlog"][0]["generic_contract_status"] == "covered_by_generic_contract"
            and hard_base_runtime_snapshot["ai_or_agent_migration_plan"][0]["owner_agent_role"] == "code_execution"
            and "generic_rule_ids=generic_scheduler_rule_ids()" in service_source
        )
        hard_bans_bridge = night_hard_bans_to_ai_or_problem(
            classes=("class_a", "class_b"),
            cst={
                ("class_a", "math"): "teacher_1",
                ("class_a", "science"): "teacher_2",
                ("class_b", "math"): "teacher_1",
                ("class_b", "science"): "teacher_3",
            },
            days=("星期五", "星期日"),
            periods=("晚自习1", "晚自习2"),
            rules={
                "hard_bans": {
                    "enabled": True,
                    "subject_bans": [
                        {"subject": "math", "days": ["星期五"], "periods": ["晚自习1"]},
                        {"subject": "science", "days": ["星期日"]},
                    ],
                    "teacher_day_bans": {"星期日": ["teacher_1"]},
                }
            },
        )
        hard_bans_solution = solve_cp_sat_problem(hard_bans_bridge.problem, time_limit_seconds=5)
        hard_bans_runtime_snapshot = runtime_trace_payload(
            mode="joint",
            run_id="audit",
            git_commit=None,
            trace=[
                {
                    "rule_id": "joint.night.hard_bans",
                    "ai_or_operation_delta": 10,
                    "ai_or_operations_by_type": {"Add": 10},
                }
            ],
            generic_rule_ids=generic_scheduler_rule_ids(),
        )
        scheduler_night_hard_bans_generic_contract = (
            hard_bans_solution.status_name == "OPTIMAL"
            and hard_bans_bridge.metadata_by_rule["night.hard_bans"]["generic_contract_status"]
            == "covered_by_generic_contract"
            and hard_bans_bridge.metadata_by_rule["night.hard_bans"]["constraint_family_counts"]
            == {"subject_bans": 6, "teacher_day_bans": 4}
            and "night.hard_bans" in generic_scheduler_rule_ids()
            and "joint.night.hard_bans" in generic_scheduler_rule_ids()
            and hard_bans_runtime_snapshot["ai_or_migration_backlog"][0]["generic_contract_status"]
            == "covered_by_generic_contract"
            and hard_bans_runtime_snapshot["ai_or_agent_migration_plan"][0]["owner_agent_role"]
            == "code_execution"
        )
        hard_teacher_limits_bridge = night_hard_teacher_limits_to_ai_or_problem(
            classes=("class_a", "class_b"),
            cst={
                ("class_a", "math"): "teacher_1",
                ("class_a", "science"): "teacher_2",
                ("class_b", "math"): "teacher_1",
            },
            days=("day_1", "day_2", "day_3"),
            periods=("night_1", "night_2"),
            rules={"hard_teacher_limits": {"enabled": True}},
        )
        hard_teacher_limits_solution = solve_cp_sat_problem(
            hard_teacher_limits_bridge.problem,
            time_limit_seconds=5,
        )
        hard_teacher_limits_runtime_snapshot = runtime_trace_payload(
            mode="joint",
            run_id="audit",
            git_commit=None,
            trace=[
                {
                    "rule_id": "joint.night.hard_teacher_limits",
                    "ai_or_operation_delta": 8,
                    "ai_or_operations_by_type": {"Add": 8},
                }
            ],
            generic_rule_ids=generic_scheduler_rule_ids(),
        )
        scheduler_night_hard_teacher_limits_generic_contract = (
            hard_teacher_limits_solution.status_name == "OPTIMAL"
            and hard_teacher_limits_bridge.metadata_by_rule["night.hard_teacher_limits"]["generic_contract_status"]
            == "covered_by_generic_contract"
            and hard_teacher_limits_bridge.metadata_by_rule["night.hard_teacher_limits"]["constraint_family_counts"]
            == {"teacher_period_no_conflict": 6, "teacher_weekly_day_cap": 2}
            and "night.hard_teacher_limits" in generic_scheduler_rule_ids()
            and "joint.night.hard_teacher_limits" in generic_scheduler_rule_ids()
            and hard_teacher_limits_runtime_snapshot["ai_or_migration_backlog"][0]["generic_contract_status"]
            == "covered_by_generic_contract"
            and hard_teacher_limits_runtime_snapshot["ai_or_agent_migration_plan"][0]["owner_agent_role"]
            == "code_execution"
        )
        night_binding_bridge = night_binding_8chem_9bio_to_ai_or_problem(
            classes=("初二8班", "初二9班", "初二10班"),
            cst={
                ("初二8班", "化学"): "chem_teacher",
                ("初二8班", "数学"): "math_teacher",
                ("初二9班", "生物"): "bio_teacher",
                ("初二10班", "化学"): "other_teacher",
            },
            days=("星期五", "星期日"),
            periods=("晚自习1", "晚自习2"),
            rules={},
        )
        night_binding_solution = solve_cp_sat_problem(night_binding_bridge.problem, time_limit_seconds=5)
        night_binding_runtime_snapshot = runtime_trace_payload(
            mode="joint",
            run_id="audit",
            git_commit=None,
            trace=[
                {
                    "rule_id": "joint.night.binding_8chem_9bio",
                    "ai_or_operation_delta": 4,
                    "ai_or_operations_by_type": {"Add": 4},
                }
            ],
            generic_rule_ids=generic_scheduler_rule_ids(),
        )
        scheduler_night_binding_generic_contract = (
            night_binding_solution.status_name == "OPTIMAL"
            and night_binding_bridge.metadata_by_rule["night.binding_8chem_9bio"]["generic_contract_status"]
            == "covered_by_generic_contract"
            and night_binding_bridge.metadata_by_rule["night.binding_8chem_9bio"]["constraint_family_counts"]
            == {"8chem_9bio_equalities": 4}
            and "night.binding_8chem_9bio" in generic_scheduler_rule_ids()
            and "joint.night.binding_8chem_9bio" in generic_scheduler_rule_ids()
            and night_binding_runtime_snapshot["ai_or_migration_backlog"][0]["generic_contract_status"]
            == "covered_by_generic_contract"
            and night_binding_runtime_snapshot["ai_or_agent_migration_plan"][0]["owner_agent_role"]
            == "code_execution"
        )
        physics_math_bridge = night_physics_math_special_to_ai_or_problem(
            classes=("class_a", "class_b"),
            cst={
                ("class_a", "物理"): "physics_teacher",
                ("class_a", "历史"): "history_teacher",
                ("class_a", "数学"): "math_teacher",
                ("class_b", "物理"): "physics_exempt_teacher",
                ("class_b", "数学"): "math_allowed_teacher",
                ("class_b", "语文"): "language_teacher",
            },
            days=("星期五", "星期日", "星期一"),
            periods=("晚自习1", "晚自习2"),
            rules={
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
        physics_math_solution = solve_cp_sat_problem(physics_math_bridge.problem, time_limit_seconds=5)
        physics_math_runtime_snapshot = runtime_trace_payload(
            mode="joint",
            run_id="audit",
            git_commit=None,
            trace=[
                {
                    "rule_id": "joint.night.physics_math_special",
                    "ai_or_operation_delta": 14,
                    "ai_or_operations_by_type": {"Add": 14},
                }
            ],
            generic_rule_ids=generic_scheduler_rule_ids(),
        )
        scheduler_night_physics_math_special_generic_contract = (
            physics_math_solution.status_name == "OPTIMAL"
            and physics_math_bridge.metadata_by_rule["night.physics_math_special"]["generic_contract_status"]
            == "covered_by_generic_contract"
            and physics_math_bridge.metadata_by_rule["night.physics_math_special"]["constraint_family_counts"]
            == {
                "physics_sunday": 2,
                "physics_friday_hard": 2,
                "history_sunday": 2,
                "history_friday_hard": 2,
                "math_sunday": 4,
                "math_friday_forbidden": 2,
            }
            and "night.physics_math_special" in generic_scheduler_rule_ids()
            and "joint.night.physics_math_special" in generic_scheduler_rule_ids()
            and physics_math_runtime_snapshot["ai_or_migration_backlog"][0]["generic_contract_status"]
            == "covered_by_generic_contract"
            and physics_math_runtime_snapshot["ai_or_agent_migration_plan"][0]["owner_agent_role"]
            == "code_execution"
        )
        fri_sun_mutex_bridge = night_fri_sun_mutex_to_ai_or_problem(
            classes=("class_a", "class_b", "class_c", "class_d"),
            cst={
                ("class_a", "math"): "teacher_1",
                ("class_b", "science"): "teacher_2",
                ("class_c", "history"): "teacher_3",
                ("class_d", "physics"): "teacher_exempt",
            },
            days=("星期五", "星期日", "星期一"),
            periods=("晚自习1",),
            rules={
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
        fri_sun_mutex_solution = solve_cp_sat_problem(fri_sun_mutex_bridge.problem, time_limit_seconds=5)
        fri_sun_mutex_runtime_snapshot = runtime_trace_payload(
            mode="joint",
            run_id="audit",
            git_commit=None,
            trace=[
                {
                    "rule_id": "joint.night.fri_sun_mutex",
                    "ai_or_operation_delta": 4,
                    "ai_or_operations_by_type": {"Add": 4},
                }
            ],
            generic_rule_ids=generic_scheduler_rule_ids(),
        )
        scheduler_night_fri_sun_mutex_generic_contract = (
            fri_sun_mutex_solution.status_name == "OPTIMAL"
            and fri_sun_mutex_bridge.metadata_by_rule["night.fri_sun_mutex"]["generic_contract_status"]
            == "covered_by_generic_contract"
            and fri_sun_mutex_bridge.metadata_by_rule["night.fri_sun_mutex"]["constraint_family_counts"]
            == {"fri_sun_teacher_mutex": 3, "configured_friday_pair_mutex": 1}
            and "night.fri_sun_mutex" in generic_scheduler_rule_ids()
            and "joint.night.fri_sun_mutex" in generic_scheduler_rule_ids()
            and fri_sun_mutex_runtime_snapshot["ai_or_migration_backlog"][0]["generic_contract_status"]
            == "covered_by_generic_contract"
            and fri_sun_mutex_runtime_snapshot["ai_or_agent_migration_plan"][0]["owner_agent_role"]
            == "code_execution"
        )
        single_class_p1_p2_bridge = night_single_class_p1_p2_split_to_ai_or_problem(
            classes=("class_a", "class_b", "class_c"),
            cst={
                ("class_a", "math"): "teacher_single_multi_subject",
                ("class_a", "history"): "teacher_single_multi_subject",
                ("class_b", "science"): "teacher_single_one_subject",
                ("class_b", "math"): "teacher_double_class",
                ("class_c", "math"): "teacher_double_class",
            },
            days=("星期一", "星期二", "星期三"),
            periods=("晚自习1", "晚自习2"),
            rules={
                "evening": {"weekly_occurrences_per_subject": 2},
                "evening_constraints": {"enable_single_class_p1_p2_split": True},
            },
        )
        single_class_p1_p2_solution = solve_cp_sat_problem(single_class_p1_p2_bridge.problem, time_limit_seconds=5)
        single_class_p1_p2_runtime_snapshot = runtime_trace_payload(
            mode="joint",
            run_id="audit",
            git_commit=None,
            trace=[
                {
                    "rule_id": "joint.night.single_class_p1_p2_split",
                    "ai_or_operation_delta": 6,
                    "ai_or_operations_by_type": {"Add": 6},
                }
            ],
            generic_rule_ids=generic_scheduler_rule_ids(),
        )
        scheduler_night_single_class_p1_p2_split_generic_contract = (
            single_class_p1_p2_solution.status_name == "OPTIMAL"
            and single_class_p1_p2_bridge.metadata_by_rule["night.single_class_p1_p2_split"][
                "generic_contract_status"
            ]
            == "covered_by_generic_contract"
            and single_class_p1_p2_bridge.metadata_by_rule["night.single_class_p1_p2_split"][
                "constraint_family_counts"
            ]
            == {
                "single_class_teacher_period_p1_exactly_one": 3,
                "single_class_teacher_period_p2_exactly_one": 3,
            }
            and "night.single_class_p1_p2_split" in generic_scheduler_rule_ids()
            and "joint.night.single_class_p1_p2_split" in generic_scheduler_rule_ids()
            and single_class_p1_p2_runtime_snapshot["ai_or_migration_backlog"][0]["generic_contract_status"]
            == "covered_by_generic_contract"
            and single_class_p1_p2_runtime_snapshot["ai_or_agent_migration_plan"][0]["owner_agent_role"]
            == "code_execution"
        )
        double_class_weekday_p1_p2_bridge = night_double_class_weekday_p1_p2_split_to_ai_or_problem(
            classes=("class_a", "class_b", "class_c", "class_d"),
            cst={
                ("class_a", "math"): "teacher_single_class",
                ("class_b", "math"): "teacher_double_class",
                ("class_c", "math"): "teacher_double_class",
                ("class_d", "history"): "teacher_three_class",
                ("class_b", "history"): "teacher_three_class",
                ("class_c", "history"): "teacher_three_class",
            },
            days=("星期一", "星期六", "星期日"),
            periods=("晚自习1", "晚自习2"),
            rules={
                "evening": {"weekly_occurrences_per_subject": 2},
                "evening_constraints": {
                    "enable_double_class_weekday_p1_p2_split": True,
                    "double_class_weekday_p1_p2_mode": "hard",
                },
            },
        )
        double_class_weekday_p1_p2_solution = solve_cp_sat_problem(
            double_class_weekday_p1_p2_bridge.problem,
            time_limit_seconds=5,
        )
        double_class_weekday_p1_p2_runtime_snapshot = runtime_trace_payload(
            mode="joint",
            run_id="audit",
            git_commit=None,
            trace=[
                {
                    "rule_id": "joint.night.double_class_weekday_p1_p2_split",
                    "ai_or_operation_delta": 10,
                    "ai_or_operations_by_type": {"NewBoolVar": 2, "Add": 8},
                }
            ],
            generic_rule_ids=generic_scheduler_rule_ids(),
        )
        scheduler_night_double_class_weekday_p1_p2_split_generic_contract = (
            double_class_weekday_p1_p2_solution.status_name == "OPTIMAL"
            and double_class_weekday_p1_p2_bridge.metadata_by_rule[
                "night.double_class_weekday_p1_p2_split"
            ]["generic_contract_status"]
            == "covered_by_generic_contract"
            and double_class_weekday_p1_p2_bridge.metadata_by_rule[
                "night.double_class_weekday_p1_p2_split"
            ]["constraint_family_counts"]
            == {
                "double_class_split_total_link": 2,
                "double_class_split_total_map_domain": 2,
                "double_class_period_p1_exactly_one_if_split_two": 2,
                "double_class_period_p2_exactly_one_if_split_two": 2,
            }
            and "night.double_class_weekday_p1_p2_split" in generic_scheduler_rule_ids()
            and "joint.night.double_class_weekday_p1_p2_split" in generic_scheduler_rule_ids()
            and double_class_weekday_p1_p2_runtime_snapshot["ai_or_migration_backlog"][0][
                "generic_contract_status"
            ]
            == "covered_by_generic_contract"
            and double_class_weekday_p1_p2_runtime_snapshot["ai_or_agent_migration_plan"][0][
                "owner_agent_role"
            ]
            == "code_execution"
        )
        checkin_bridge = night_checkin_to_ai_or_problem(
            male_heads=("male_a", "male_b", "male_excluded", "extra_m"),
            female_heads=("female_a", "female_b"),
            days=("星期一", "星期二"),
            rules={
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
        checkin_solution = solve_cp_sat_problem(checkin_bridge.problem, time_limit_seconds=5)
        checkin_runtime_snapshot = runtime_trace_payload(
            mode="joint",
            run_id="audit",
            git_commit=None,
            trace=[
                {
                    "rule_id": "joint.night.checkin",
                    "ai_or_operation_delta": 29,
                    "ai_or_operations_by_type": {"Add": 29},
                }
            ],
            generic_rule_ids=generic_scheduler_rule_ids(),
        )
        scheduler_night_checkin_generic_contract = (
            checkin_solution.status_name == "OPTIMAL"
            and checkin_bridge.metadata_by_rule["night.checkin"]["generic_contract_status"]
            == "covered_by_generic_contract"
            and checkin_bridge.metadata_by_rule["night.checkin"]["constraint_family_counts"]
            == {
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
            and "night.checkin" in generic_scheduler_rule_ids()
            and "joint.night.checkin" in generic_scheduler_rule_ids()
            and checkin_runtime_snapshot["ai_or_migration_backlog"][0]["generic_contract_status"]
            == "covered_by_generic_contract"
            and checkin_runtime_snapshot["ai_or_agent_migration_plan"][0]["owner_agent_role"]
            == "code_execution"
        )
        day_slot_1 = Slot(day="day_1", block="上午", period=1)
        day_slot_2 = Slot(day="day_1", block="上午", period=2)
        day_bridge = day_one_subject_per_slot_to_ai_or_problem(
            DayInputData(
                classes=["class_a", "class_b"],
                cls_subj_teacher={
                    ("class_a", "math"): "teacher_1",
                    ("class_a", "science"): "teacher_2",
                    ("class_b", "math"): "teacher_1",
                    ("class_b", "science"): "teacher_3",
                },
                available_slots=[day_slot_1, day_slot_2],
                fixed_assign={},
                req_hours={
                    ("class_a", "math"): (0, 1, 0),
                    ("class_a", "science"): (0, 1, 0),
                    ("class_b", "math"): (0, 1, 0),
                    ("class_b", "science"): (0, 1, 0),
                },
                subject_ban_slots={},
            )
        )
        day_solution = solve_cp_sat_problem(day_bridge.problem, time_limit_seconds=5)
        day_runtime_snapshot = runtime_trace_payload(
            mode="joint",
            run_id="audit",
            git_commit=None,
            trace=[
                {
                    "rule_id": "joint.day.one_subject_per_slot",
                    "ai_or_operation_delta": 6,
                    "ai_or_operations_by_type": {"Add": 2, "NewBoolVar": 4},
                }
            ],
            generic_rule_ids=generic_scheduler_rule_ids(),
        )
        scheduler_day_one_subject_generic_contract = (
            day_solution.status_name == "OPTIMAL"
            and day_bridge.metadata_by_rule["joint.day.one_subject_per_slot"]["generic_contract_status"]
            == "covered_by_generic_contract"
            and "joint.day.one_subject_per_slot" in generic_scheduler_rule_ids()
            and day_runtime_snapshot["ai_or_migration_backlog"][0]["generic_contract_status"]
            == "covered_by_generic_contract"
            and day_runtime_snapshot["ai_or_agent_migration_plan"][0]["owner_agent_role"] == "code_execution"
        )
        subject_early = Slot(day="星期一", block="早自习", period=1)
        subject_weekday = Slot(day="星期一", block="上午", period=1)
        subject_weekend = Slot(day="星期六", block="上午", period=1)
        subject_hours_bridge = day_subject_hours_to_ai_or_problem(
            DayInputData(
                classes=["class_a"],
                cls_subj_teacher={
                    ("class_a", "math"): "teacher_1",
                    ("class_a", "science"): "teacher_2",
                },
                available_slots=[subject_early, subject_weekday, subject_weekend],
                fixed_assign={},
                req_hours={
                    ("class_a", "math"): (1, 1, 0),
                    ("class_a", "science"): (0, 0, 1),
                },
                subject_ban_slots={},
            )
        )
        subject_hours_solution = solve_cp_sat_problem(subject_hours_bridge.problem, time_limit_seconds=5)
        subject_hours_runtime_snapshot = runtime_trace_payload(
            mode="joint",
            run_id="audit",
            git_commit=None,
            trace=[
                {
                    "rule_id": "joint.day.subject_hour_constraints",
                    "ai_or_operation_delta": 6,
                    "ai_or_operations_by_type": {"Add": 6},
                }
            ],
            generic_rule_ids=generic_scheduler_rule_ids(),
        )
        scheduler_day_subject_hours_generic_contract = (
            subject_hours_solution.status_name == "OPTIMAL"
            and subject_hours_bridge.metadata_by_rule["joint.day.subject_hour_constraints"]["generic_contract_status"]
            == "covered_by_generic_contract"
            and "joint.day.subject_hour_constraints" in generic_scheduler_rule_ids()
            and subject_hours_runtime_snapshot["ai_or_migration_backlog"][0]["generic_contract_status"]
            == "covered_by_generic_contract"
            and subject_hours_runtime_snapshot["ai_or_agent_migration_plan"][0]["owner_agent_role"] == "code_execution"
        )
        teacher_conflict_bridge = day_teacher_no_conflict_to_ai_or_problem(
            DayInputData(
                classes=["class_a", "class_b"],
                cls_subj_teacher={
                    ("class_a", "math"): "teacher_1",
                    ("class_a", "science"): "teacher_2",
                    ("class_b", "math"): "teacher_1",
                    ("class_b", "science"): "teacher_3",
                },
                available_slots=[day_slot_1, day_slot_2],
                fixed_assign={},
                req_hours={
                    ("class_a", "math"): (0, 1, 0),
                    ("class_a", "science"): (0, 1, 0),
                    ("class_b", "math"): (0, 1, 0),
                    ("class_b", "science"): (0, 1, 0),
                },
                subject_ban_slots={},
            )
        )
        teacher_conflict_solution = solve_cp_sat_problem(teacher_conflict_bridge.problem, time_limit_seconds=5)
        teacher_conflict_runtime_snapshot = runtime_trace_payload(
            mode="joint",
            run_id="audit",
            git_commit=None,
            trace=[
                {
                    "rule_id": "joint.day.teacher_no_conflict",
                    "ai_or_operation_delta": 2,
                    "ai_or_operations_by_type": {"Add": 2},
                }
            ],
            generic_rule_ids=generic_scheduler_rule_ids(),
        )
        scheduler_day_teacher_no_conflict_generic_contract = (
            teacher_conflict_solution.status_name == "OPTIMAL"
            and teacher_conflict_bridge.metadata_by_rule["joint.day.teacher_no_conflict"]["generic_contract_status"]
            == "covered_by_generic_contract"
            and "joint.day.teacher_no_conflict" in generic_scheduler_rule_ids()
            and teacher_conflict_runtime_snapshot["ai_or_migration_backlog"][0]["generic_contract_status"]
            == "covered_by_generic_contract"
            and teacher_conflict_runtime_snapshot["ai_or_agent_migration_plan"][0]["owner_agent_role"] == "code_execution"
        )
        no_consecutive_slot_1 = Slot(day="星期一", block="上午", period=1)
        no_consecutive_slot_2 = Slot(day="星期一", block="上午", period=2)
        no_consecutive_weekend = Slot(day="星期六", block="上午", period=1)
        no_consecutive_bridge = day_no_consecutive_same_teacher_same_class_to_ai_or_problem(
            DayInputData(
                classes=["class_a"],
                cls_subj_teacher={
                    ("class_a", "math"): "teacher_1",
                    ("class_a", "science"): "teacher_1",
                    ("class_a", "history"): "teacher_2",
                },
                available_slots=[no_consecutive_slot_1, no_consecutive_slot_2, no_consecutive_weekend],
                fixed_assign={("class_a", no_consecutive_slot_1): "math"},
                req_hours={
                    ("class_a", "math"): (0, 1, 0),
                    ("class_a", "science"): (0, 1, 0),
                    ("class_a", "history"): (0, 1, 0),
                },
                subject_ban_slots={},
            )
        )
        no_consecutive_solution = solve_cp_sat_problem(no_consecutive_bridge.problem, time_limit_seconds=5)
        no_consecutive_runtime_snapshot = runtime_trace_payload(
            mode="joint",
            run_id="audit",
            git_commit=None,
            trace=[
                {
                    "rule_id": "joint.day.no_consecutive_same_teacher_same_class",
                    "ai_or_operation_delta": 2,
                    "ai_or_operations_by_type": {"Add": 2},
                }
            ],
            generic_rule_ids=generic_scheduler_rule_ids(),
        )
        scheduler_day_no_consecutive_same_teacher_same_class_generic_contract = (
            no_consecutive_solution.status_name == "OPTIMAL"
            and no_consecutive_bridge.metadata_by_rule["joint.day.no_consecutive_same_teacher_same_class"][
                "generic_contract_status"
            ]
            == "covered_by_generic_contract"
            and "joint.day.no_consecutive_same_teacher_same_class" in generic_scheduler_rule_ids()
            and no_consecutive_runtime_snapshot["ai_or_migration_backlog"][0]["generic_contract_status"]
            == "covered_by_generic_contract"
            and no_consecutive_runtime_snapshot["ai_or_agent_migration_plan"][0]["owner_agent_role"]
            == "code_execution"
        )
        core_early = Slot(day="星期一", block="早自习", period=1)
        core_mon_am1 = Slot(day="星期一", block="上午", period=1)
        core_mon_am2 = Slot(day="星期一", block="上午", period=2)
        core_mon_am4 = Slot(day="星期一", block="上午", period=4)
        core_mon_pm1 = Slot(day="星期一", block="下午", period=1)
        core_tue_am1 = Slot(day="星期二", block="上午", period=1)
        core_weekend = Slot(day="星期六", block="上午", period=1)
        core_bridge = day_core_subject_teacher_day_load_no_am1_am4_to_ai_or_problem(
            DayInputData(
                classes=["class_a", "class_b"],
                cls_subj_teacher={
                    ("class_a", "数学"): "teacher_core",
                    ("class_a", "英语"): "teacher_core",
                    ("class_b", "体育"): "pe_teacher",
                },
                available_slots=[
                    core_early,
                    core_mon_am1,
                    core_mon_am2,
                    core_mon_am4,
                    core_mon_pm1,
                    core_tue_am1,
                    core_weekend,
                ],
                fixed_assign={("class_a", core_mon_pm1): "数学"},
                req_hours={
                    ("class_a", "数学"): (1, 3, 1),
                    ("class_a", "英语"): (0, 2, 1),
                    ("class_b", "体育"): (0, 1, 1),
                },
                subject_ban_slots={},
            ),
            max_per_day=3,
        )
        core_solution = solve_cp_sat_problem(core_bridge.problem, time_limit_seconds=5)
        core_runtime_snapshot = runtime_trace_payload(
            mode="joint",
            run_id="audit",
            git_commit=None,
            trace=[
                {
                    "rule_id": "joint.day.core_subject_teacher_day_load_no_am1_am4",
                    "ai_or_operation_delta": 10,
                    "ai_or_operations_by_type": {"Add": 10},
                }
            ],
            generic_rule_ids=generic_scheduler_rule_ids(),
        )
        scheduler_day_core_subject_teacher_day_load_generic_contract = (
            core_solution.status_name == "OPTIMAL"
            and core_bridge.metadata_by_rule["joint.day.core_subject_teacher_day_load_no_am1_am4"][
                "generic_contract_status"
            ]
            == "covered_by_generic_contract"
            and core_bridge.metadata_by_rule["joint.day.core_subject_teacher_day_load_no_am1_am4"][
                "constraint_family_counts"
            ]["core_teacher_daily_load_caps"]
            == 5
            and "joint.day.core_subject_teacher_day_load_no_am1_am4" in generic_scheduler_rule_ids()
            and core_runtime_snapshot["ai_or_migration_backlog"][0]["generic_contract_status"]
            == "covered_by_generic_contract"
            and core_runtime_snapshot["ai_or_agent_migration_plan"][0]["owner_agent_role"] == "code_execution"
        )
        no_am1_am4_slot_1 = Slot(day="星期一", block="上午", period=1)
        no_am1_am4_slot_2 = Slot(day="星期一", block="上午", period=2)
        no_am1_am4_slot_4 = Slot(day="星期一", block="上午", period=4)
        no_am1_am4_weekend = Slot(day="星期六", block="上午", period=1)
        no_am1_am4_bridge = day_no_am1_am4_to_ai_or_problem(
            DayInputData(
                classes=["class_a", "class_b"],
                cls_subj_teacher={
                    ("class_a", "math"): "teacher_1",
                    ("class_a", "science"): "teacher_1",
                    ("class_b", "体育"): "pe_teacher_subject",
                    ("class_b", "history"): "pe_teacher_param",
                },
                available_slots=[
                    no_am1_am4_slot_1,
                    no_am1_am4_slot_2,
                    no_am1_am4_slot_4,
                    no_am1_am4_weekend,
                ],
                fixed_assign={},
                req_hours={
                    ("class_a", "math"): (0, 2, 0),
                    ("class_a", "science"): (0, 1, 1),
                    ("class_b", "体育"): (0, 1, 0),
                    ("class_b", "history"): (0, 1, 1),
                },
                subject_ban_slots={},
            ),
            pe_teachers={"pe_teacher_param"},
        )
        no_am1_am4_solution = solve_cp_sat_problem(no_am1_am4_bridge.problem, time_limit_seconds=5)
        no_am1_am4_runtime_snapshot = runtime_trace_payload(
            mode="joint",
            run_id="audit",
            git_commit=None,
            trace=[
                {
                    "rule_id": "joint.day.no_am1_am4",
                    "ai_or_operation_delta": 1,
                    "ai_or_operations_by_type": {"Add": 1},
                }
            ],
            generic_rule_ids=generic_scheduler_rule_ids(),
        )
        scheduler_day_no_am1_am4_generic_contract = (
            no_am1_am4_solution.status_name == "OPTIMAL"
            and no_am1_am4_bridge.metadata_by_rule["joint.day.no_am1_am4"]["generic_contract_status"]
            == "covered_by_generic_contract"
            and "joint.day.no_am1_am4" in generic_scheduler_rule_ids()
            and no_am1_am4_runtime_snapshot["ai_or_migration_backlog"][0]["generic_contract_status"]
            == "covered_by_generic_contract"
            and no_am1_am4_runtime_snapshot["ai_or_agent_migration_plan"][0]["owner_agent_role"] == "code_execution"
        )
        teacher_presence_early = Slot(day="星期一", block="早自习", period=1)
        teacher_presence_am1 = Slot(day="星期一", block="上午", period=1)
        teacher_presence_pm1 = Slot(day="星期一", block="下午", period=1)
        teacher_presence_weekend = Slot(day="星期六", block="下午", period=1)
        teacher_presence_bridge = day_teacher_weekday_am_pm_presence_to_ai_or_problem(
            DayInputData(
                classes=["class_a", "class_b", "class_c", "class_d"],
                cls_subj_teacher={
                    ("class_a", "math"): "teacher_main",
                    ("class_a", "science"): "teacher_main",
                    ("class_b", "history"): "teacher_fixed",
                    ("class_c", "体育"): "pe_subject_teacher",
                    ("class_d", "art"): "pe_param_teacher",
                },
                available_slots=[
                    teacher_presence_early,
                    teacher_presence_am1,
                    teacher_presence_pm1,
                    teacher_presence_weekend,
                ],
                fixed_assign={("class_b", teacher_presence_pm1): "history"},
                req_hours={
                    ("class_a", "math"): (0, 1, 1),
                    ("class_a", "science"): (0, 1, 1),
                    ("class_b", "history"): (0, 1, 1),
                    ("class_c", "体育"): (0, 1, 1),
                    ("class_d", "art"): (0, 1, 1),
                },
                subject_ban_slots={},
            ),
            pe_teachers={"pe_param_teacher"},
        )
        teacher_presence_solution = solve_cp_sat_problem(teacher_presence_bridge.problem, time_limit_seconds=5)
        teacher_presence_runtime_snapshot = runtime_trace_payload(
            mode="joint",
            run_id="audit",
            git_commit=None,
            trace=[
                {
                    "rule_id": "joint.day.teacher_weekday_am_pm_presence",
                    "ai_or_operation_delta": 4,
                    "ai_or_operations_by_type": {"Add": 4},
                }
            ],
            generic_rule_ids=generic_scheduler_rule_ids(),
        )
        scheduler_day_teacher_weekday_am_pm_presence_generic_contract = (
            teacher_presence_solution.status_name == "OPTIMAL"
            and teacher_presence_bridge.metadata_by_rule["joint.day.teacher_weekday_am_pm_presence"][
                "generic_contract_status"
            ]
            == "covered_by_generic_contract"
            and teacher_presence_bridge.metadata_by_rule["joint.day.teacher_weekday_am_pm_presence"][
                "constraint_family_counts"
            ]["teacher_weekday_am_presence_minimums"]
            == 2
            and "joint.day.teacher_weekday_am_pm_presence" in generic_scheduler_rule_ids()
            and teacher_presence_runtime_snapshot["ai_or_migration_backlog"][0]["generic_contract_status"]
            == "covered_by_generic_contract"
            and teacher_presence_runtime_snapshot["ai_or_agent_migration_plan"][0]["owner_agent_role"]
            == "code_execution"
        )
        head_pm1_slots = [
            Slot(day="星期一", block="下午", period=1),
            Slot(day="星期二", block="下午", period=1),
            Slot(day="星期三", block="下午", period=1),
            Slot(day="星期四", block="下午", period=1),
            Slot(day="星期五", block="下午", period=1),
        ]
        head_pm1_bridge = day_head_pm1_min_to_ai_or_problem(
            DayInputData(
                classes=["class_a", "class_b", "class_c", "class_d"],
                cls_subj_teacher={
                    ("class_a", "math"): "head_1",
                    ("class_b", "science"): "head_2",
                    ("class_c", "history"): "head_3",
                    ("class_d", "体育"): "head_pe_subject",
                },
                available_slots=head_pm1_slots,
                fixed_assign={},
                req_hours={
                    ("class_a", "math"): (0, 5, 0),
                    ("class_b", "science"): (0, 5, 0),
                    ("class_c", "history"): (0, 5, 0),
                    ("class_d", "体育"): (0, 5, 0),
                },
                subject_ban_slots={},
            ),
            head_teachers=["head_1", "head_2", "head_3", "head_pe_subject"],
            min_required=3,
        )
        head_pm1_solution = solve_cp_sat_problem(head_pm1_bridge.problem, time_limit_seconds=5)
        head_pm1_runtime_snapshot = runtime_trace_payload(
            mode="joint",
            run_id="audit",
            git_commit=None,
            trace=[
                {
                    "rule_id": "joint.day.head_pm1_min",
                    "ai_or_operation_delta": 5,
                    "ai_or_operations_by_type": {"Add": 5},
                }
            ],
            generic_rule_ids=generic_scheduler_rule_ids(),
        )
        scheduler_day_head_pm1_min_generic_contract = (
            head_pm1_solution.status_name == "OPTIMAL"
            and head_pm1_bridge.metadata_by_rule["joint.day.head_pm1_min"]["generic_contract_status"]
            == "covered_by_generic_contract"
            and head_pm1_bridge.metadata_by_rule["joint.day.head_pm1_min"]["constraint_family_counts"][
                "head_pm1_minimums"
            ]
            == 5
            and "joint.day.head_pm1_min" in generic_scheduler_rule_ids()
            and head_pm1_runtime_snapshot["ai_or_migration_backlog"][0]["generic_contract_status"]
            == "covered_by_generic_contract"
            and head_pm1_runtime_snapshot["ai_or_agent_migration_plan"][0]["owner_agent_role"] == "code_execution"
        )
        am1_pm1_slot_am1 = Slot(day="星期一", block="上午", period=1)
        am1_pm1_slot_am2 = Slot(day="星期一", block="上午", period=2)
        am1_pm1_slot_pm1 = Slot(day="星期一", block="下午", period=1)
        am1_pm1_weekend = Slot(day="星期六", block="上午", period=1)
        am1_pm1_bridge = day_am1_pm1_mutex_to_ai_or_problem(
            DayInputData(
                classes=["class_a", "class_b"],
                cls_subj_teacher={
                    ("class_a", "math"): "teacher_1",
                    ("class_a", "science"): "teacher_1",
                    ("class_b", "history"): "teacher_2",
                    ("class_b", "art"): "teacher_3",
                },
                available_slots=[
                    am1_pm1_slot_am1,
                    am1_pm1_slot_am2,
                    am1_pm1_slot_pm1,
                    am1_pm1_weekend,
                ],
                fixed_assign={("class_b", am1_pm1_slot_pm1): "history"},
                req_hours={
                    ("class_a", "math"): (0, 1, 1),
                    ("class_a", "science"): (0, 1, 1),
                    ("class_b", "history"): (0, 1, 0),
                    ("class_b", "art"): (0, 1, 0),
                },
                subject_ban_slots={},
            )
        )
        am1_pm1_solution = solve_cp_sat_problem(am1_pm1_bridge.problem, time_limit_seconds=5)
        am1_pm1_runtime_snapshot = runtime_trace_payload(
            mode="joint",
            run_id="audit",
            git_commit=None,
            trace=[
                {
                    "rule_id": "joint.day.am1_pm1_mutex",
                    "ai_or_operation_delta": 21,
                    "ai_or_operations_by_type": {"NewBoolVar": 6, "Add": 15},
                }
            ],
            generic_rule_ids=generic_scheduler_rule_ids(),
        )
        scheduler_day_am1_pm1_mutex_generic_contract = (
            am1_pm1_solution.status_name == "OPTIMAL"
            and am1_pm1_bridge.metadata_by_rule["joint.day.am1_pm1_mutex"]["generic_contract_status"]
            == "covered_by_generic_contract"
            and "day.am1_pm1_mutex" in generic_scheduler_rule_ids()
            and "joint.day.am1_pm1_mutex" in generic_scheduler_rule_ids()
            and am1_pm1_runtime_snapshot["ai_or_migration_backlog"][0]["generic_contract_status"]
            == "covered_by_generic_contract"
            and am1_pm1_runtime_snapshot["ai_or_agent_migration_plan"][0]["owner_agent_role"] == "code_execution"
        )
        am1_pm1_exclusive_bridge = day_am1_pm1_exclusive_to_ai_or_problem(
            DayInputData(
                classes=["class_a", "class_b"],
                cls_subj_teacher={
                    ("class_a", "math"): "teacher_1",
                    ("class_a", "science"): "teacher_1",
                    ("class_b", "history"): "teacher_2",
                    ("class_b", "art"): "teacher_3",
                },
                available_slots=[
                    am1_pm1_slot_am1,
                    am1_pm1_slot_am2,
                    am1_pm1_slot_pm1,
                    am1_pm1_weekend,
                ],
                fixed_assign={("class_b", am1_pm1_slot_pm1): "history"},
                req_hours={
                    ("class_a", "math"): (0, 1, 1),
                    ("class_a", "science"): (0, 1, 1),
                    ("class_b", "history"): (0, 1, 0),
                    ("class_b", "art"): (0, 1, 0),
                },
                subject_ban_slots={},
            )
        )
        am1_pm1_exclusive_solution = solve_cp_sat_problem(
            am1_pm1_exclusive_bridge.problem,
            time_limit_seconds=5,
        )
        am1_pm1_exclusive_runtime_snapshot = runtime_trace_payload(
            mode="joint",
            run_id="audit",
            git_commit=None,
            trace=[
                {
                    "rule_id": "joint.day.am1_pm1_exclusive",
                    "ai_or_operation_delta": 21,
                    "ai_or_operations_by_type": {"NewBoolVar": 6, "Add": 15},
                }
            ],
            generic_rule_ids=generic_scheduler_rule_ids(),
        )
        scheduler_day_am1_pm1_exclusive_generic_contract = (
            am1_pm1_exclusive_solution.status_name == "OPTIMAL"
            and am1_pm1_exclusive_bridge.metadata_by_rule["joint.day.am1_pm1_exclusive"][
                "generic_contract_status"
            ]
            == "covered_by_generic_contract"
            and "day.am1_pm1_exclusive" in generic_scheduler_rule_ids()
            and "joint.day.am1_pm1_exclusive" in generic_scheduler_rule_ids()
            and am1_pm1_exclusive_runtime_snapshot["ai_or_migration_backlog"][0]["generic_contract_status"]
            == "covered_by_generic_contract"
            and am1_pm1_exclusive_runtime_snapshot["ai_or_agent_migration_plan"][0]["owner_agent_role"]
            == "code_execution"
        )
        single_cap_mon_am1 = Slot(day="星期一", block="上午", period=1)
        single_cap_mon_am2 = Slot(day="星期一", block="上午", period=2)
        single_cap_tue_am1 = Slot(day="星期二", block="上午", period=1)
        single_cap_sun_am1 = Slot(day="星期日", block="上午", period=1)
        single_cap_bridge = day_single_class_weekly_am1_cap_to_ai_or_problem(
            DayInputData(
                classes=["class_a", "class_b", "class_c"],
                cls_subj_teacher={
                    ("class_a", "math"): "teacher_single",
                    ("class_a", "science"): "teacher_single",
                    ("class_b", "history"): "teacher_double",
                    ("class_c", "history"): "teacher_double",
                    ("class_b", "art"): "teacher_fixed",
                },
                available_slots=[single_cap_mon_am1, single_cap_mon_am2, single_cap_tue_am1, single_cap_sun_am1],
                fixed_assign={("class_b", single_cap_sun_am1): "art"},
                req_hours={
                    ("class_a", "math"): (0, 1, 1),
                    ("class_a", "science"): (0, 1, 1),
                    ("class_b", "history"): (0, 1, 1),
                    ("class_c", "history"): (0, 1, 1),
                    ("class_b", "art"): (0, 1, 1),
                },
                subject_ban_slots={},
            ),
            max_occurrences=1,
        )
        single_cap_solution = solve_cp_sat_problem(single_cap_bridge.problem, time_limit_seconds=5)
        single_cap_runtime_snapshot = runtime_trace_payload(
            mode="joint",
            run_id="audit",
            git_commit=None,
            trace=[
                {
                    "rule_id": "joint.day.single_class_weekly_am1_cap",
                    "ai_or_operation_delta": 37,
                    "ai_or_operations_by_type": {"NewBoolVar": 9, "NewIntVar": 2, "Add": 26},
                }
            ],
            generic_rule_ids=generic_scheduler_rule_ids(),
        )
        scheduler_day_single_class_weekly_am1_cap_generic_contract = (
            single_cap_solution.status_name == "OPTIMAL"
            and single_cap_bridge.metadata_by_rule["joint.day.single_class_weekly_am1_cap"][
                "generic_contract_status"
            ]
            == "covered_by_generic_contract"
            and single_cap_bridge.metadata_by_rule["joint.day.single_class_weekly_am1_cap"][
                "constraint_family_counts"
            ]["weekly_count_caps"]
            == 2
            and "day.single_class_weekly_am1_cap" in generic_scheduler_rule_ids()
            and "joint.day.single_class_weekly_am1_cap" in generic_scheduler_rule_ids()
            and single_cap_runtime_snapshot["ai_or_migration_backlog"][0]["generic_contract_status"]
            == "covered_by_generic_contract"
            and single_cap_runtime_snapshot["ai_or_agent_migration_plan"][0]["owner_agent_role"]
            == "code_execution"
        )
        two_class_slot_am1 = Slot(day="星期一", block="上午", period=1)
        two_class_slot_am2 = Slot(day="星期一", block="上午", period=2)
        two_class_slot_pm1 = Slot(day="星期一", block="下午", period=1)
        two_class_slot_pm2 = Slot(day="星期一", block="下午", period=2)
        two_class_weekend = Slot(day="星期六", block="上午", period=1)
        two_class_bridge = day_two_class_am1_pm1_combo_to_ai_or_problem(
            DayInputData(
                classes=["class_a", "class_b", "class_c"],
                cls_subj_teacher={
                    ("class_a", "math"): "teacher_two",
                    ("class_b", "math"): "teacher_two",
                    ("class_c", "science"): "teacher_one",
                    ("class_a", "体育"): "pe_subject_teacher",
                    ("class_b", "history"): "pe_param_teacher",
                    ("class_c", "history"): "pe_param_teacher",
                },
                available_slots=[
                    two_class_slot_am1,
                    two_class_slot_am2,
                    two_class_slot_pm1,
                    two_class_slot_pm2,
                    two_class_weekend,
                ],
                fixed_assign={
                    ("class_a", two_class_slot_am2): "math",
                    ("class_b", two_class_slot_pm1): "math",
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
            ),
            pe_teachers={"pe_param_teacher"},
        )
        two_class_solution = solve_cp_sat_problem(two_class_bridge.problem, time_limit_seconds=5)
        two_class_runtime_snapshot = runtime_trace_payload(
            mode="joint",
            run_id="audit",
            git_commit=None,
            trace=[
                {
                    "rule_id": "joint.day.two_class_am1_pm1_combo",
                    "ai_or_operation_delta": 15,
                    "ai_or_operations_by_type": {
                        "NewIntVar": 10,
                        "Add": 10,
                        "AddForbiddenAssignments": 5,
                    },
                }
            ],
            generic_rule_ids=generic_scheduler_rule_ids(),
        )
        scheduler_day_two_class_am1_pm1_combo_generic_contract = (
            two_class_solution.status_name == "OPTIMAL"
            and two_class_bridge.metadata_by_rule["joint.day.two_class_am1_pm1_combo"]["generic_contract_status"]
            == "covered_by_generic_contract"
            and "day.two_class_am1_pm1_combo" in generic_scheduler_rule_ids()
            and "joint.day.two_class_am1_pm1_combo" in generic_scheduler_rule_ids()
            and two_class_runtime_snapshot["ai_or_migration_backlog"][0]["generic_contract_status"]
            == "covered_by_generic_contract"
            and two_class_runtime_snapshot["ai_or_agent_migration_plan"][0]["owner_agent_role"] == "code_execution"
        )
        low_hours_mon_am1 = Slot(day="星期一", block="上午", period=1)
        low_hours_tue_am1 = Slot(day="星期二", block="上午", period=1)
        low_hours_wed_pm1 = Slot(day="星期三", block="下午", period=1)
        low_hours_thu_am1 = Slot(day="星期四", block="上午", period=1)
        low_hours_weekend = Slot(day="星期六", block="上午", period=1)
        low_hours_bridge = day_two_class_low_hours_max_empty_days_to_ai_or_problem(
            DayInputData(
                classes=["class_a", "class_b", "class_c", "class_d", "class_e"],
                cls_subj_teacher={
                    ("class_a", "math"): "teacher_low",
                    ("class_b", "math"): "teacher_low",
                    ("class_c", "history"): "teacher_high",
                    ("class_d", "history"): "teacher_high",
                    ("class_e", "art"): "teacher_pe_param",
                    ("class_a", "体育"): "pe_subject_teacher",
                },
                available_slots=[
                    low_hours_mon_am1,
                    low_hours_tue_am1,
                    low_hours_wed_pm1,
                    low_hours_thu_am1,
                    low_hours_weekend,
                ],
                fixed_assign={("class_a", low_hours_mon_am1): "math"},
                req_hours={
                    ("class_a", "math"): (0, 2, 1),
                    ("class_b", "math"): (0, 2, 1),
                    ("class_c", "history"): (0, 3, 1),
                    ("class_d", "history"): (0, 3, 1),
                    ("class_e", "art"): (0, 2, 1),
                    ("class_a", "体育"): (0, 1, 1),
                },
                subject_ban_slots={},
            ),
            pe_teachers={"teacher_pe_param"},
            threshold=5,
            max_empty_days=1,
        )
        low_hours_solution = solve_cp_sat_problem(low_hours_bridge.problem, time_limit_seconds=5)
        low_hours_runtime_snapshot = runtime_trace_payload(
            mode="joint",
            run_id="audit",
            git_commit=None,
            trace=[
                {
                    "rule_id": "joint.day.two_class_low_hours_max_empty_days",
                    "ai_or_operation_delta": 27,
                    "ai_or_operations_by_type": {"NewBoolVar": 10, "Add": 17},
                }
            ],
            generic_rule_ids=generic_scheduler_rule_ids(),
        )
        scheduler_day_two_class_low_hours_generic_contract = (
            low_hours_solution.status_name == "OPTIMAL"
            and low_hours_bridge.metadata_by_rule["joint.day.two_class_low_hours_max_empty_days"][
                "generic_contract_status"
            ]
            == "covered_by_generic_contract"
            and low_hours_bridge.metadata_by_rule["joint.day.two_class_low_hours_max_empty_days"][
                "constraint_family_counts"
            ]["empty_day_caps"]
            == 1
            and "joint.day.two_class_low_hours_max_empty_days" in generic_scheduler_rule_ids()
            and low_hours_runtime_snapshot["ai_or_migration_backlog"][0]["generic_contract_status"]
            == "covered_by_generic_contract"
            and low_hours_runtime_snapshot["ai_or_agent_migration_plan"][0]["owner_agent_role"] == "code_execution"
        )
        low_subject_mon_am1 = Slot(day="星期一", block="上午", period=1)
        low_subject_mon_pm1 = Slot(day="星期一", block="下午", period=1)
        low_subject_tue_am1 = Slot(day="星期二", block="上午", period=1)
        low_subject_wed_am1 = Slot(day="星期三", block="上午", period=1)
        low_subject_thu_am1 = Slot(day="星期四", block="上午", period=1)
        low_subject_fri_am1 = Slot(day="星期五", block="上午", period=1)
        low_subject_weekend = Slot(day="星期六", block="上午", period=1)
        low_subject_bridge = day_low_weekday_subject_max1_per_day_to_ai_or_problem(
            DayInputData(
                classes=["class_a"],
                cls_subj_teacher={
                    ("class_a", "art"): "teacher_low",
                    ("class_a", "math"): "teacher_high",
                },
                available_slots=[
                    low_subject_mon_am1,
                    low_subject_mon_pm1,
                    low_subject_tue_am1,
                    low_subject_wed_am1,
                    low_subject_thu_am1,
                    low_subject_fri_am1,
                    low_subject_weekend,
                ],
                fixed_assign={("class_a", low_subject_mon_am1): "art"},
                req_hours={
                    ("class_a", "art"): (0, 4, 1),
                    ("class_a", "math"): (0, 5, 1),
                },
                subject_ban_slots={},
            ),
            max_weekday_hours=4,
        )
        low_subject_solution = solve_cp_sat_problem(low_subject_bridge.problem, time_limit_seconds=5)
        low_subject_runtime_snapshot = runtime_trace_payload(
            mode="joint",
            run_id="audit",
            git_commit=None,
            trace=[
                {
                    "rule_id": "joint.day.low_weekday_subject_max1_per_day",
                    "ai_or_operation_delta": 5,
                    "ai_or_operations_by_type": {"Add": 5},
                }
            ],
            generic_rule_ids=generic_scheduler_rule_ids(),
        )
        scheduler_day_low_weekday_subject_generic_contract = (
            low_subject_solution.status_name == "OPTIMAL"
            and low_subject_bridge.metadata_by_rule["joint.day.low_weekday_subject_max1_per_day"][
                "generic_contract_status"
            ]
            == "covered_by_generic_contract"
            and low_subject_bridge.metadata_by_rule["joint.day.low_weekday_subject_max1_per_day"][
                "constraint_family_counts"
            ]["low_subject_daily_max_constraints"]
            == 5
            and "joint.day.low_weekday_subject_max1_per_day" in generic_scheduler_rule_ids()
            and low_subject_runtime_snapshot["ai_or_migration_backlog"][0]["generic_contract_status"]
            == "covered_by_generic_contract"
            and low_subject_runtime_snapshot["ai_or_agent_migration_plan"][0]["owner_agent_role"]
            == "code_execution"
        )
        high_subject_mon_am1 = Slot(day="星期一", block="上午", period=1)
        high_subject_tue_am1 = Slot(day="星期二", block="上午", period=1)
        high_subject_tue_pm1 = Slot(day="星期二", block="下午", period=1)
        high_subject_wed_am1 = Slot(day="星期三", block="上午", period=1)
        high_subject_thu_am1 = Slot(day="星期四", block="上午", period=1)
        high_subject_fri_am1 = Slot(day="星期五", block="上午", period=1)
        high_subject_weekend = Slot(day="星期六", block="上午", period=1)
        high_subject_bridge = day_high_weekday_subject_min1_per_day_to_ai_or_problem(
            DayInputData(
                classes=["class_a"],
                cls_subj_teacher={
                    ("class_a", "math"): "teacher_high",
                    ("class_a", "art"): "teacher_low",
                },
                available_slots=[
                    high_subject_mon_am1,
                    high_subject_tue_am1,
                    high_subject_tue_pm1,
                    high_subject_wed_am1,
                    high_subject_thu_am1,
                    high_subject_fri_am1,
                    high_subject_weekend,
                ],
                fixed_assign={("class_a", high_subject_tue_am1): "math"},
                req_hours={
                    ("class_a", "math"): (0, 5, 1),
                    ("class_a", "art"): (0, 4, 1),
                },
                subject_ban_slots={},
            ),
            min_weekday_hours=5,
        )
        high_subject_solution = solve_cp_sat_problem(high_subject_bridge.problem, time_limit_seconds=5)
        high_subject_runtime_snapshot = runtime_trace_payload(
            mode="joint",
            run_id="audit",
            git_commit=None,
            trace=[
                {
                    "rule_id": "joint.day.high_weekday_subject_min1_per_day",
                    "ai_or_operation_delta": 5,
                    "ai_or_operations_by_type": {"Add": 5},
                }
            ],
            generic_rule_ids=generic_scheduler_rule_ids(),
        )
        scheduler_day_high_weekday_subject_generic_contract = (
            high_subject_solution.status_name == "OPTIMAL"
            and high_subject_bridge.metadata_by_rule["joint.day.high_weekday_subject_min1_per_day"][
                "generic_contract_status"
            ]
            == "covered_by_generic_contract"
            and high_subject_bridge.metadata_by_rule["joint.day.high_weekday_subject_min1_per_day"][
                "constraint_family_counts"
            ]["high_subject_daily_min_constraints"]
            == 5
            and "joint.day.high_weekday_subject_min1_per_day" in generic_scheduler_rule_ids()
            and high_subject_runtime_snapshot["ai_or_migration_backlog"][0]["generic_contract_status"]
            == "covered_by_generic_contract"
            and high_subject_runtime_snapshot["ai_or_agent_migration_plan"][0]["owner_agent_role"]
            == "code_execution"
        )
        pe_window_mon_am1 = Slot(day="星期一", block="上午", period=1)
        pe_window_mon_pm1 = Slot(day="星期一", block="下午", period=1)
        pe_window_wed_am4 = Slot(day="星期三", block="上午", period=4)
        pe_window_sat_am1 = Slot(day="星期六", block="上午", period=1)
        pe_window_bridge = day_pe_time_window_hard_to_ai_or_problem(
            DayInputData(
                classes=["class_a", "class_b"],
                cls_subj_teacher={
                    ("class_a", "体育"): "pe_teacher",
                    ("class_a", "math"): "math_teacher",
                    ("class_b", "体育"): "pe_teacher_fixed",
                },
                available_slots=[pe_window_mon_am1, pe_window_mon_pm1, pe_window_wed_am4, pe_window_sat_am1],
                fixed_assign={("class_b", pe_window_mon_am1): "体育"},
                req_hours={
                    ("class_a", "体育"): (0, 2, 1),
                    ("class_a", "math"): (0, 2, 1),
                    ("class_b", "体育"): (0, 2, 1),
                },
                subject_ban_slots={},
            )
        )
        pe_window_solution = solve_cp_sat_problem(pe_window_bridge.problem, time_limit_seconds=5)
        pe_window_runtime_snapshot = runtime_trace_payload(
            mode="joint",
            run_id="audit",
            git_commit=None,
            trace=[
                {
                    "rule_id": "joint.day.pe_time_window_hard",
                    "ai_or_operation_delta": 3,
                    "ai_or_operations_by_type": {"Add": 3},
                }
            ],
            generic_rule_ids=generic_scheduler_rule_ids(),
        )
        scheduler_day_pe_time_window_generic_contract = (
            pe_window_solution.status_name == "OPTIMAL"
            and pe_window_bridge.metadata_by_rule["joint.day.pe_time_window_hard"]["generic_contract_status"]
            == "covered_by_generic_contract"
            and pe_window_bridge.metadata_by_rule["joint.day.pe_time_window_hard"]["constraint_family_counts"][
                "pe_illegal_time_window_zeroes"
            ]
            == 3
            and "joint.day.pe_time_window_hard" in generic_scheduler_rule_ids()
            and pe_window_runtime_snapshot["ai_or_migration_backlog"][0]["generic_contract_status"]
            == "covered_by_generic_contract"
            and pe_window_runtime_snapshot["ai_or_agent_migration_plan"][0]["owner_agent_role"] == "code_execution"
        )
        whitelist_mon_am1 = Slot(day="星期一", block="上午", period=1)
        whitelist_mon_pm1 = Slot(day="星期一", block="下午", period=1)
        whitelist_tue_pm1 = Slot(day="星期二", block="下午", period=1)
        whitelist_bridge = day_teacher_whitelist_hard_to_ai_or_problem(
            DayInputData(
                classes=["class_a", "class_b"],
                cls_subj_teacher={
                    ("class_a", "体育"): "coach_1",
                    ("class_a", "技术"): "coach_1",
                    ("class_b", "体育"): "coach_fixed",
                    ("class_b", "math"): "math_teacher",
                },
                available_slots=[whitelist_mon_am1, whitelist_mon_pm1, whitelist_tue_pm1],
                fixed_assign={("class_b", whitelist_tue_pm1): "体育"},
                req_hours={
                    ("class_a", "体育"): (0, 2, 0),
                    ("class_a", "技术"): (0, 1, 0),
                    ("class_b", "体育"): (0, 2, 0),
                    ("class_b", "math"): (0, 2, 0),
                },
                subject_ban_slots={},
            ),
            teacher_name="coach_1",
            allowed={("星期一", "下午1")},
        )
        whitelist_solution = solve_cp_sat_problem(whitelist_bridge.problem, time_limit_seconds=5)
        whitelist_runtime_snapshot = runtime_trace_payload(
            mode="joint",
            run_id="audit",
            git_commit=None,
            trace=[
                {
                    "rule_id": "joint.day.teacher_whitelist_hard",
                    "ai_or_operation_delta": 4,
                    "ai_or_operations_by_type": {"Add": 4},
                }
            ],
            generic_rule_ids=generic_scheduler_rule_ids(),
        )
        scheduler_day_teacher_whitelist_generic_contract = (
            whitelist_solution.status_name == "OPTIMAL"
            and whitelist_bridge.metadata_by_rule["joint.day.teacher_whitelist_hard"]["generic_contract_status"]
            == "covered_by_generic_contract"
            and whitelist_bridge.metadata_by_rule["joint.day.teacher_whitelist_hard"]["constraint_family_counts"][
                "teacher_whitelist_illegal_zeroes"
            ]
            == 4
            and "joint.day.teacher_whitelist_hard" in generic_scheduler_rule_ids()
            and whitelist_runtime_snapshot["ai_or_migration_backlog"][0]["generic_contract_status"]
            == "covered_by_generic_contract"
            and whitelist_runtime_snapshot["ai_or_agent_migration_plan"][0]["owner_agent_role"] == "code_execution"
        )
        soft_pref_mon_am1 = Slot(day="星期一", block="上午", period=1)
        soft_pref_mon_am2 = Slot(day="星期一", block="上午", period=2)
        soft_pref_mon_pm1 = Slot(day="星期一", block="下午", period=1)
        soft_pref_tue_am1 = Slot(day="星期二", block="上午", period=1)
        soft_pref_sat_am1 = Slot(day="星期六", block="上午", period=1)
        soft_pref_data = DayInputData(
            classes=["class_a", "class_b"],
            cls_subj_teacher={
                ("class_a", "体育"): "pe_teacher",
                ("class_a", "数学"): "math_teacher",
                ("class_a", "化学"): "chem_teacher",
                ("class_b", "技术"): "tech_teacher",
                ("class_b", "物理"): "physics_teacher",
            },
            available_slots=[
                soft_pref_mon_am1,
                soft_pref_mon_am2,
                soft_pref_mon_pm1,
                soft_pref_tue_am1,
                soft_pref_sat_am1,
            ],
            fixed_assign={("class_b", soft_pref_tue_am1): "物理"},
            req_hours={
                ("class_a", "体育"): (0, 3, 1),
                ("class_a", "数学"): (0, 2, 1),
                ("class_a", "化学"): (0, 2, 1),
                ("class_b", "技术"): (0, 2, 1),
                ("class_b", "物理"): (0, 2, 1),
            },
            subject_ban_slots={},
        )
        reduce_stem_bridge = day_reduce_stem_am1_to_ai_or_problem(soft_pref_data, weight=37)
        reduce_stem_solution = solve_cp_sat_problem(reduce_stem_bridge.problem, time_limit_seconds=5)
        reduce_stem_runtime_snapshot = runtime_trace_payload(
            mode="joint",
            run_id="audit",
            git_commit=None,
            trace=[
                {
                    "rule_id": "joint.day.reduce_stem_am1",
                    "ai_or_operation_delta": 5,
                    "ai_or_operations_by_type": {"ObjectiveTerm": 5},
                }
            ],
            generic_rule_ids=generic_scheduler_rule_ids(),
        )
        scheduler_day_reduce_stem_am1_generic_contract = (
            reduce_stem_solution.status_name == "OPTIMAL"
            and reduce_stem_bridge.metadata_by_rule["joint.day.reduce_stem_am1"]["generic_contract_status"]
            == "covered_by_generic_contract"
            and reduce_stem_bridge.metadata_by_rule["joint.day.reduce_stem_am1"]["constraint_family_counts"][
                "stem_am1_penalty_terms"
            ]
            == 5
            and reduce_stem_bridge.metadata_by_rule["joint.day.reduce_stem_am1"]["fixed_penalty_count"] == 1
            and reduce_stem_bridge.problem.objective is not None
            and "joint.day.reduce_stem_am1" in generic_scheduler_rule_ids()
            and reduce_stem_runtime_snapshot["ai_or_migration_backlog"][0]["generic_contract_status"]
            == "covered_by_generic_contract"
            and reduce_stem_runtime_snapshot["ai_or_agent_migration_plan"][0]["owner_agent_role"] == "code_execution"
        )
        pe_reduce_bridge = day_pe_reduce_am_soft_to_ai_or_problem(
            soft_pref_data,
            pe_teachers={"pe_teacher"},
            weight=41,
        )
        pe_reduce_solution = solve_cp_sat_problem(pe_reduce_bridge.problem, time_limit_seconds=5)
        pe_reduce_runtime_snapshot = runtime_trace_payload(
            mode="joint",
            run_id="audit",
            git_commit=None,
            trace=[
                {
                    "rule_id": "joint.day.pe_reduce_am_soft",
                    "ai_or_operation_delta": 3,
                    "ai_or_operations_by_type": {"ObjectiveTerm": 3},
                }
            ],
            generic_rule_ids=generic_scheduler_rule_ids(),
        )
        scheduler_day_pe_reduce_am_soft_generic_contract = (
            pe_reduce_solution.status_name == "OPTIMAL"
            and pe_reduce_bridge.metadata_by_rule["joint.day.pe_reduce_am_soft"]["generic_contract_status"]
            == "covered_by_generic_contract"
            and pe_reduce_bridge.metadata_by_rule["joint.day.pe_reduce_am_soft"]["constraint_family_counts"][
                "pe_weekday_morning_penalty_terms"
            ]
            == 3
            and pe_reduce_bridge.problem.objective is not None
            and "joint.day.pe_reduce_am_soft" in generic_scheduler_rule_ids()
            and pe_reduce_runtime_snapshot["ai_or_migration_backlog"][0]["generic_contract_status"]
            == "covered_by_generic_contract"
            and pe_reduce_runtime_snapshot["ai_or_agent_migration_plan"][0]["owner_agent_role"] == "code_execution"
        )
        lang_pref_mon_am1 = Slot(day="星期一", block="上午", period=1)
        lang_pref_tue_am1 = Slot(day="星期二", block="上午", period=1)
        lang_pref_tue_pm1 = Slot(day="星期二", block="下午", period=1)
        lang_pref_wed_pm2 = Slot(day="星期三", block="下午", period=2)
        lang_pref_thu_pm3 = Slot(day="星期四", block="下午", period=3)
        lang_pref_sat_pm1 = Slot(day="星期六", block="下午", period=1)
        lang_pref_data = DayInputData(
            classes=["class_a"],
            cls_subj_teacher={
                ("class_a", "语文"): "teacher_lang",
                ("class_a", "外语"): "teacher_other",
                ("class_a", "数学"): "math_teacher",
            },
            available_slots=[
                lang_pref_mon_am1,
                lang_pref_tue_am1,
                lang_pref_tue_pm1,
                lang_pref_wed_pm2,
                lang_pref_thu_pm3,
                lang_pref_sat_pm1,
            ],
            fixed_assign={},
            req_hours={
                ("class_a", "语文"): (0, 4, 1),
                ("class_a", "外语"): (0, 4, 1),
                ("class_a", "数学"): (0, 4, 1),
            },
            subject_ban_slots={},
        )
        lang_pref_bridge = day_pref_lang_am_to_ai_or_problem(
            lang_pref_data,
            target_teachers={"teacher_lang"},
            am1_reward=11,
            pm1_penalty=13,
            pm2_penalty=17,
            pm3_penalty=19,
        )
        lang_pref_solution = solve_cp_sat_problem(lang_pref_bridge.problem, time_limit_seconds=5)
        lang_pref_runtime_snapshot = runtime_trace_payload(
            mode="joint",
            run_id="audit",
            git_commit=None,
            trace=[
                {
                    "rule_id": "joint.day.pref_lang_am",
                    "ai_or_operation_delta": 4,
                    "ai_or_operations_by_type": {"ObjectiveTerm": 4},
                }
            ],
            generic_rule_ids=generic_scheduler_rule_ids(),
        )
        scheduler_day_pref_lang_am_generic_contract = (
            lang_pref_solution.status_name == "OPTIMAL"
            and lang_pref_bridge.metadata_by_rule["joint.day.pref_lang_am"]["generic_contract_status"]
            == "covered_by_generic_contract"
            and lang_pref_bridge.metadata_by_rule["joint.day.pref_lang_am"]["constraint_family_counts"][
                "lang_tue_fri_am1_reward_terms"
            ]
            == 1
            and lang_pref_bridge.problem.objective is not None
            and "joint.day.pref_lang_am" in generic_scheduler_rule_ids()
            and lang_pref_runtime_snapshot["ai_or_migration_backlog"][0]["generic_contract_status"]
            == "covered_by_generic_contract"
            and lang_pref_runtime_snapshot["ai_or_agent_migration_plan"][0]["owner_agent_role"] == "code_execution"
        )
        pe_compact_mon_am1 = Slot(day="星期一", block="上午", period=1)
        pe_compact_mon_am2 = Slot(day="星期一", block="上午", period=2)
        pe_compact_mon_am3 = Slot(day="星期一", block="上午", period=3)
        pe_compact_mon_pm1 = Slot(day="星期一", block="下午", period=1)
        pe_compact_mon_pm2 = Slot(day="星期一", block="下午", period=2)
        pe_compact_bridge = day_pe_tech_compact_soft_to_ai_or_problem(
            DayInputData(
                classes=["class_a", "class_b"],
                cls_subj_teacher={
                    ("class_a", "体育"): "coach",
                    ("class_a", "技术"): "coach",
                    ("class_b", "体育"): "other_coach",
                },
                available_slots=[
                    pe_compact_mon_am1,
                    pe_compact_mon_am2,
                    pe_compact_mon_am3,
                    pe_compact_mon_pm1,
                    pe_compact_mon_pm2,
                ],
                fixed_assign={},
                req_hours={
                    ("class_a", "体育"): (0, 3, 0),
                    ("class_a", "技术"): (0, 2, 0),
                    ("class_b", "体育"): (0, 2, 0),
                },
                subject_ban_slots={},
            ),
            pe_tech_teachers={"coach"},
            weight=23,
        )
        pe_compact_solution = solve_cp_sat_problem(pe_compact_bridge.problem, time_limit_seconds=5)
        pe_compact_runtime_snapshot = runtime_trace_payload(
            mode="joint",
            run_id="audit",
            git_commit=None,
            trace=[
                {
                    "rule_id": "joint.day.pe_tech_compact_soft",
                    "ai_or_operation_delta": 19,
                    "ai_or_operations_by_type": {"Add": 12, "NewBoolVar": 7},
                }
            ],
            generic_rule_ids=generic_scheduler_rule_ids(),
        )
        scheduler_day_pe_tech_compact_soft_generic_contract = (
            pe_compact_solution.status_name == "OPTIMAL"
            and pe_compact_bridge.metadata_by_rule["joint.day.pe_tech_compact_soft"]["generic_contract_status"]
            == "covered_by_generic_contract"
            and pe_compact_bridge.metadata_by_rule["joint.day.pe_tech_compact_soft"]["constraint_family_counts"][
                "pe_tech_gap_penalty_terms"
            ]
            == 2
            and len(pe_compact_bridge.problem.constraints) == 12
            and "joint.day.pe_tech_compact_soft" in generic_scheduler_rule_ids()
            and pe_compact_runtime_snapshot["ai_or_migration_backlog"][0]["generic_contract_status"]
            == "covered_by_generic_contract"
            and pe_compact_runtime_snapshot["ai_or_agent_migration_plan"][0]["owner_agent_role"] == "code_execution"
        )
        threshold_mon_am4 = Slot(day="星期一", block="上午", period=4)
        threshold_mon_pm1 = Slot(day="星期一", block="下午", period=1)
        threshold_tue_am4 = Slot(day="星期二", block="上午", period=4)
        threshold_tue_pm1 = Slot(day="星期二", block="下午", period=1)
        threshold_wed_am4 = Slot(day="星期三", block="上午", period=4)
        threshold_thu_pm1 = Slot(day="星期四", block="下午", period=1)
        threshold_bridge = day_teacher_am4_pm1_threshold_penalty_to_ai_or_problem(
            DayInputData(
                classes=["class_a"],
                cls_subj_teacher={
                    ("class_a", "math"): "teacher_main",
                    ("class_a", "science"): "teacher_main",
                    ("class_a", "体育"): "pe_teacher",
                },
                available_slots=[
                    threshold_mon_am4,
                    threshold_mon_pm1,
                    threshold_tue_am4,
                    threshold_tue_pm1,
                    threshold_wed_am4,
                    threshold_thu_pm1,
                ],
                fixed_assign={},
                req_hours={
                    ("class_a", "math"): (0, 3, 0),
                    ("class_a", "science"): (0, 3, 0),
                    ("class_a", "体育"): (0, 3, 0),
                },
                subject_ban_slots={},
            ),
            pe_teachers={"pe_teacher"},
            weights=(3, 5, 7, 11),
        )
        threshold_solution = solve_cp_sat_problem(threshold_bridge.problem, time_limit_seconds=5)
        threshold_runtime_snapshot = runtime_trace_payload(
            mode="joint",
            run_id="audit",
            git_commit=None,
            trace=[
                {
                    "rule_id": "joint.day.teacher_am4_pm1_threshold_penalty",
                    "ai_or_operation_delta": 11,
                    "ai_or_operations_by_type": {"Add": 6, "NewIntVar": 5},
                }
            ],
            generic_rule_ids=generic_scheduler_rule_ids(),
        )
        scheduler_day_teacher_am4_pm1_threshold_generic_contract = (
            threshold_solution.status_name == "OPTIMAL"
            and threshold_bridge.metadata_by_rule["joint.day.teacher_am4_pm1_threshold_penalty"][
                "generic_contract_status"
            ]
            == "covered_by_generic_contract"
            and threshold_bridge.metadata_by_rule["joint.day.teacher_am4_pm1_threshold_penalty"][
                "constraint_family_counts"
            ]["teacher_am4_pm1_penalty_terms"]
            == 4
            and threshold_bridge.metadata_by_rule["joint.day.teacher_am4_pm1_threshold_penalty"][
                "teacher_total_assignment_count_by_teacher"
            ]
            == {"teacher_main": 12}
            and len(threshold_bridge.problem.constraints) == 6
            and threshold_bridge.problem.objective is not None
            and "joint.day.teacher_am4_pm1_threshold_penalty" in generic_scheduler_rule_ids()
            and threshold_runtime_snapshot["ai_or_migration_backlog"][0]["generic_contract_status"]
            == "covered_by_generic_contract"
            and threshold_runtime_snapshot["ai_or_agent_migration_plan"][0]["owner_agent_role"] == "code_execution"
        )
        balance_mon_am1 = Slot(day="星期一", block="上午", period=1)
        balance_tue_am1 = Slot(day="星期二", block="上午", period=1)
        balance_wed_am1 = Slot(day="星期三", block="上午", period=1)
        balance_thu_am1 = Slot(day="星期四", block="上午", period=1)
        balance_fri_am1 = Slot(day="星期五", block="上午", period=1)
        balance_bridge = day_weekday_subject_balance_to_ai_or_problem(
            DayInputData(
                classes=["class_a"],
                cls_subj_teacher={
                    ("class_a", "math"): "math_teacher",
                    ("class_a", "体育"): "pe_teacher",
                },
                available_slots=[
                    balance_mon_am1,
                    balance_tue_am1,
                    balance_wed_am1,
                    balance_thu_am1,
                    balance_fri_am1,
                ],
                fixed_assign={("class_a", balance_tue_am1): "math"},
                req_hours={
                    ("class_a", "math"): (0, 7, 0),
                    ("class_a", "体育"): (0, 5, 0),
                },
                subject_ban_slots={},
            ),
            mode="soft",
            weight=29,
        )
        balance_solution = solve_cp_sat_problem(balance_bridge.problem, time_limit_seconds=5)
        balance_runtime_snapshot = runtime_trace_payload(
            mode="joint",
            run_id="audit",
            git_commit=None,
            trace=[
                {
                    "rule_id": "joint.day.weekday_subject_balance",
                    "ai_or_operation_delta": 30,
                    "ai_or_operations_by_type": {"Add": 15, "NewIntVar": 15},
                }
            ],
            generic_rule_ids=generic_scheduler_rule_ids(),
        )
        scheduler_day_weekday_subject_balance_generic_contract = (
            balance_solution.status_name == "OPTIMAL"
            and balance_bridge.metadata_by_rule["joint.day.weekday_subject_balance"]["generic_contract_status"]
            == "covered_by_generic_contract"
            and balance_bridge.metadata_by_rule["joint.day.weekday_subject_balance"]["constraint_family_counts"][
                "weekday_subject_balance_penalty_terms"
            ]
            == 10
            and balance_bridge.metadata_by_rule["joint.day.weekday_subject_balance"]["fixed_count_constants"]
            == {"class_a|math|星期二": 1}
            and len(balance_bridge.problem.constraints) == 15
            and balance_bridge.problem.objective is not None
            and "joint.day.weekday_subject_balance" in generic_scheduler_rule_ids()
            and balance_runtime_snapshot["ai_or_migration_backlog"][0]["generic_contract_status"]
            == "covered_by_generic_contract"
            and balance_runtime_snapshot["ai_or_agent_migration_plan"][0]["owner_agent_role"] == "code_execution"
        )
        continuity_mon_am1 = Slot(day="星期一", block="上午", period=1)
        continuity_mon_am2 = Slot(day="星期一", block="上午", period=2)
        continuity_mon_am3 = Slot(day="星期一", block="上午", period=3)
        continuity_mon_pm1 = Slot(day="星期一", block="下午", period=1)
        continuity_mon_pm2 = Slot(day="星期一", block="下午", period=2)
        continuity_bridge = day_teacher_continuity_penalty_to_ai_or_problem(
            DayInputData(
                classes=["class_a"],
                cls_subj_teacher={
                    ("class_a", "math"): "teacher_main",
                    ("class_a", "science"): "teacher_main",
                    ("class_a", "体育"): "coach",
                },
                available_slots=[
                    continuity_mon_am1,
                    continuity_mon_am2,
                    continuity_mon_am3,
                    continuity_mon_pm1,
                    continuity_mon_pm2,
                ],
                fixed_assign={},
                req_hours={
                    ("class_a", "math"): (0, 3, 0),
                    ("class_a", "science"): (0, 2, 0),
                    ("class_a", "体育"): (0, 2, 0),
                },
                subject_ban_slots={},
            ),
            pe_teachers={"coach"},
            weight=17,
        )
        continuity_solution = solve_cp_sat_problem(continuity_bridge.problem, time_limit_seconds=5)
        continuity_runtime_snapshot = runtime_trace_payload(
            mode="joint",
            run_id="audit",
            git_commit=None,
            trace=[
                {
                    "rule_id": "joint.day.teacher_continuity_penalty",
                    "ai_or_operation_delta": 19,
                    "ai_or_operations_by_type": {"Add": 12, "NewBoolVar": 7},
                }
            ],
            generic_rule_ids=generic_scheduler_rule_ids(),
        )
        scheduler_day_teacher_continuity_generic_contract = (
            continuity_solution.status_name == "OPTIMAL"
            and continuity_bridge.metadata_by_rule["joint.day.teacher_continuity_penalty"]["generic_contract_status"]
            == "covered_by_generic_contract"
            and continuity_bridge.metadata_by_rule["joint.day.teacher_continuity_penalty"]["constraint_family_counts"][
                "teacher_continuity_gap_penalty_terms"
            ]
            == 2
            and len(continuity_bridge.problem.constraints) == 12
            and continuity_bridge.problem.objective is not None
            and "joint.day.teacher_continuity_penalty" in generic_scheduler_rule_ids()
            and continuity_runtime_snapshot["ai_or_migration_backlog"][0]["generic_contract_status"]
            == "covered_by_generic_contract"
            and continuity_runtime_snapshot["ai_or_agent_migration_plan"][0]["owner_agent_role"] == "code_execution"
        )
        daily_min_mon_am1 = Slot(day="星期一", block="上午", period=1)
        daily_min_mon_pm1 = Slot(day="星期一", block="下午", period=1)
        daily_min_bridge = day_two_class_daily_min_per_class_to_ai_or_problem(
            DayInputData(
                classes=["class_a", "class_b"],
                cls_subj_teacher={
                    ("class_a", "math"): "teacher_shared",
                    ("class_b", "math"): "teacher_shared",
                },
                available_slots=[daily_min_mon_am1, daily_min_mon_pm1],
                fixed_assign={},
                req_hours={
                    ("class_a", "math"): (0, 2, 0),
                    ("class_b", "math"): (0, 2, 0),
                },
                subject_ban_slots={},
            ),
            pe_teachers=set(),
            mode="soft",
            w_soft=31,
        )
        daily_min_solution = solve_cp_sat_problem(daily_min_bridge.problem, time_limit_seconds=5)
        daily_min_runtime_snapshot = runtime_trace_payload(
            mode="joint",
            run_id="audit",
            git_commit=None,
            trace=[
                {
                    "rule_id": "joint.day.two_class_daily_min_per_class",
                    "ai_or_operation_delta": 78,
                    "ai_or_operations_by_type": {"Add": 53, "NewBoolVar": 25},
                }
            ],
            generic_rule_ids=generic_scheduler_rule_ids(),
        )
        scheduler_day_two_class_daily_min_generic_contract = (
            daily_min_solution.status_name == "OPTIMAL"
            and daily_min_bridge.metadata_by_rule["joint.day.two_class_daily_min_per_class"]["generic_contract_status"]
            == "covered_by_generic_contract"
            and daily_min_bridge.metadata_by_rule["joint.day.two_class_daily_min_per_class"]["constraint_family_counts"][
                "two_class_daily_min_penalty_terms"
            ]
            == 10
            and len(daily_min_bridge.problem.constraints) == 53
            and daily_min_bridge.problem.objective is not None
            and "joint.day.two_class_daily_min_per_class" in generic_scheduler_rule_ids()
            and daily_min_runtime_snapshot["ai_or_migration_backlog"][0]["generic_contract_status"]
            == "covered_by_generic_contract"
            and daily_min_runtime_snapshot["ai_or_agent_migration_plan"][0]["owner_agent_role"] == "code_execution"
        )
        m1_mon_am1 = Slot(day="星期一", block="上午", period=1)
        m1_tue_am1 = Slot(day="星期二", block="上午", period=1)
        m1_wed_am1 = Slot(day="星期三", block="上午", period=1)
        m1_bridge = day_teacher_m1_cap_constraint_to_ai_or_problem(
            DayInputData(
                classes=["class_a"],
                cls_subj_teacher={("class_a", "math"): "teacher_main"},
                available_slots=[m1_mon_am1, m1_tue_am1, m1_wed_am1],
                fixed_assign={("class_a", m1_wed_am1): "math"},
                req_hours={("class_a", "math"): (0, 2, 0)},
                subject_ban_slots={},
            ),
            max_m1=2,
            weight=23,
        )
        m1_solution = solve_cp_sat_problem(m1_bridge.problem, time_limit_seconds=5)
        m1_runtime_snapshot = runtime_trace_payload(
            mode="joint",
            run_id="audit",
            git_commit=None,
            trace=[
                {
                    "rule_id": "joint.day.teacher_m1_cap_constraint",
                    "ai_or_operation_delta": 20,
                    "ai_or_operations_by_type": {"Add": 12, "NewBoolVar": 6, "NewIntVar": 2},
                }
            ],
            generic_rule_ids=generic_scheduler_rule_ids(),
        )
        scheduler_day_teacher_m1_cap_generic_contract = (
            m1_solution.status_name == "OPTIMAL"
            and m1_bridge.metadata_by_rule["joint.day.teacher_m1_cap_constraint"]["generic_contract_status"]
            == "covered_by_generic_contract"
            and m1_bridge.metadata_by_rule["joint.day.teacher_m1_cap_constraint"]["constraint_family_counts"][
                "teacher_m1_hit_cap_penalty_terms"
            ]
            == 1
            and m1_bridge.metadata_by_rule["joint.day.teacher_m1_cap_constraint"]["fixed_total_by_teacher"]
            == {"teacher_main": 1}
            and len(m1_bridge.problem.constraints) == 12
            and m1_bridge.problem.objective is not None
            and "joint.day.teacher_m1_cap_constraint" in generic_scheduler_rule_ids()
            and m1_runtime_snapshot["ai_or_migration_backlog"][0]["generic_contract_status"]
            == "covered_by_generic_contract"
            and m1_runtime_snapshot["ai_or_agent_migration_plan"][0]["owner_agent_role"] == "code_execution"
        )
        fragment_mon_am1 = Slot(day="星期一", block="上午", period=1)
        fragment_mon_am2 = Slot(day="星期一", block="上午", period=2)
        fragment_tue_am1 = Slot(day="星期二", block="上午", period=1)
        fragment_wed_am1 = Slot(day="星期三", block="上午", period=1)
        fragment_bridge = day_teacher_am1_fragmentation_to_ai_or_problem(
            DayInputData(
                classes=["class_a"],
                cls_subj_teacher={("class_a", "math"): "teacher_main"},
                available_slots=[fragment_mon_am1, fragment_mon_am2, fragment_tue_am1, fragment_wed_am1],
                fixed_assign={("class_a", fragment_wed_am1): "math"},
                req_hours={("class_a", "math"): (0, 3, 0)},
                subject_ban_slots={},
            ),
            pe_teachers=set(),
            k_week=2,
            w_only_am1=13,
            w_am1_excess=17,
            am1_penalty_exempt_teacher_days={("teacher_main", "星期三")},
        )
        fragment_solution = solve_cp_sat_problem(fragment_bridge.problem, time_limit_seconds=5)
        fragment_runtime_snapshot = runtime_trace_payload(
            mode="joint",
            run_id="audit",
            git_commit=None,
            trace=[
                {
                    "rule_id": "joint.day.teacher_am1_fragmentation",
                    "ai_or_operation_delta": 49,
                    "ai_or_operations_by_type": {"Add": 31, "NewBoolVar": 15, "NewIntVar": 3},
                }
            ],
            generic_rule_ids=generic_scheduler_rule_ids(),
        )
        scheduler_day_teacher_am1_fragmentation_generic_contract = (
            fragment_solution.status_name == "OPTIMAL"
            and fragment_bridge.metadata_by_rule["joint.day.teacher_am1_fragmentation"]["generic_contract_status"]
            == "covered_by_generic_contract"
            and fragment_bridge.metadata_by_rule["joint.day.teacher_am1_fragmentation"]["constraint_family_counts"][
                "teacher_am1_fragmentation_only_am1_penalty_terms"
            ]
            == 4
            and fragment_bridge.metadata_by_rule["joint.day.teacher_am1_fragmentation"][
                "fixed_am1_penalty_week_by_teacher"
            ]
            == {"teacher_main": 0}
            and len(fragment_bridge.problem.constraints) == 31
            and fragment_bridge.problem.objective is not None
            and "joint.day.teacher_am1_fragmentation" in generic_scheduler_rule_ids()
            and fragment_runtime_snapshot["ai_or_migration_backlog"][0]["generic_contract_status"]
            == "covered_by_generic_contract"
            and fragment_runtime_snapshot["ai_or_agent_migration_plan"][0]["owner_agent_role"] == "code_execution"
        )
        multi_mon_am1 = Slot(day="星期一", block="上午", period=1)
        multi_mon_am2 = Slot(day="星期一", block="上午", period=2)
        multi_mon_pm1 = Slot(day="星期一", block="下午", period=1)
        multi_class_bridge = day_multi_class_halfday_soft_to_ai_or_problem(
            DayInputData(
                classes=["class_a", "class_b"],
                cls_subj_teacher={
                    ("class_a", "math"): "teacher_main",
                    ("class_b", "math"): "teacher_main",
                },
                available_slots=[multi_mon_am1, multi_mon_am2, multi_mon_pm1],
                fixed_assign={},
                req_hours={
                    ("class_a", "math"): (0, 3, 0),
                    ("class_b", "math"): (0, 3, 0),
                },
                subject_ban_slots={},
            ),
            pe_teachers=set(),
            weight=19,
        )
        multi_class_solution = solve_cp_sat_problem(multi_class_bridge.problem, time_limit_seconds=5)
        multi_class_runtime_snapshot = runtime_trace_payload(
            mode="joint",
            run_id="audit",
            git_commit=None,
            trace=[
                {
                    "rule_id": "joint.day.multi_class_halfday_soft",
                    "ai_or_operation_delta": 74,
                    "ai_or_operations_by_type": {
                        "Add": 45,
                        "AddMaxEquality": 1,
                        "NewBoolVar": 26,
                        "NewIntVar": 2,
                    },
                }
            ],
            generic_rule_ids=generic_scheduler_rule_ids(),
        )
        scheduler_day_multi_class_halfday_generic_contract = (
            multi_class_solution.status_name == "OPTIMAL"
            and multi_class_bridge.metadata_by_rule["joint.day.multi_class_halfday_soft"]["generic_contract_status"]
            == "covered_by_generic_contract"
            and multi_class_bridge.metadata_by_rule["joint.day.multi_class_halfday_soft"]["constraint_family_counts"][
                "multi_class_halfday_penalty_terms"
            ]
            == 3
            and multi_class_bridge.metadata_by_rule["joint.day.multi_class_halfday_soft"]["linear_constraint_count"]
            == 45
            and len(multi_class_bridge.problem.constraints) == 46
            and multi_class_bridge.problem.objective is not None
            and "joint.day.multi_class_halfday_soft" in generic_scheduler_rule_ids()
            and multi_class_runtime_snapshot["ai_or_migration_backlog"][0]["generic_contract_status"]
            == "covered_by_generic_contract"
            and multi_class_runtime_snapshot["ai_or_agent_migration_plan"][0]["owner_agent_role"] == "code_execution"
        )
        morning_slots = [
            Slot(day="星期一", block="早自习", period=1),
            Slot(day="星期二", block="早自习", period=1),
            Slot(day="星期三", block="早自习", period=1),
            Slot(day="星期四", block="早自习", period=1),
        ]
        morning_reading_bridge = day_morning_reading_to_ai_or_problem(
            DayInputData(
                classes=["class_a"],
                cls_subj_teacher={
                    ("class_a", "math"): "teacher_1",
                    ("class_a", "reading"): "teacher_2",
                },
                available_slots=morning_slots,
                fixed_assign={},
                req_hours={
                    ("class_a", "math"): (2, 0, 0),
                    ("class_a", "reading"): (2, 0, 0),
                },
                subject_ban_slots={},
            )
        )
        morning_reading_solution = solve_cp_sat_problem(morning_reading_bridge.problem, time_limit_seconds=5)
        morning_reading_runtime_snapshot = runtime_trace_payload(
            mode="joint",
            run_id="audit",
            git_commit=None,
            trace=[
                {
                    "rule_id": "joint.day.morning_reading_constraints",
                    "ai_or_operation_delta": 6,
                    "ai_or_operations_by_type": {"Add": 6},
                }
            ],
            generic_rule_ids=generic_scheduler_rule_ids(),
        )
        scheduler_day_morning_reading_generic_contract = (
            morning_reading_solution.status_name == "OPTIMAL"
            and morning_reading_bridge.metadata_by_rule["joint.day.morning_reading_constraints"]["generic_contract_status"]
            == "covered_by_generic_contract"
            and "joint.day.morning_reading_constraints" in generic_scheduler_rule_ids()
            and morning_reading_runtime_snapshot["ai_or_migration_backlog"][0]["generic_contract_status"]
            == "covered_by_generic_contract"
            and morning_reading_runtime_snapshot["ai_or_agent_migration_plan"][0]["owner_agent_role"] == "code_execution"
        )
        weekend_weekday = Slot(day="星期一", block="上午", period=1)
        weekend_saturday = Slot(day="星期六", block="上午", period=1)
        weekend_sunday = Slot(day="星期日", block="上午", period=1)
        weekend_subject_whitelist_bridge = day_weekend_subject_whitelist_to_ai_or_problem(
            DayInputData(
                classes=["class_a"],
                cls_subj_teacher={
                    ("class_a", "语文"): "teacher_1",
                    ("class_a", "数学"): "teacher_2",
                    ("class_a", "外语"): "teacher_3",
                },
                available_slots=[weekend_weekday, weekend_saturday, weekend_sunday],
                fixed_assign={},
                req_hours={
                    ("class_a", "语文"): (0, 1, 1),
                    ("class_a", "数学"): (0, 1, 1),
                    ("class_a", "外语"): (0, 1, 1),
                },
                subject_ban_slots={},
            )
        )
        weekend_subject_whitelist_solution = solve_cp_sat_problem(
            weekend_subject_whitelist_bridge.problem,
            time_limit_seconds=5,
        )
        weekend_subject_whitelist_runtime_snapshot = runtime_trace_payload(
            mode="joint",
            run_id="audit",
            git_commit=None,
            trace=[
                {
                    "rule_id": "joint.day.weekend_subject_whitelist",
                    "ai_or_operation_delta": 3,
                    "ai_or_operations_by_type": {"Add": 3},
                }
            ],
            generic_rule_ids=generic_scheduler_rule_ids(),
        )
        scheduler_day_weekend_subject_whitelist_generic_contract = (
            weekend_subject_whitelist_solution.status_name == "OPTIMAL"
            and weekend_subject_whitelist_bridge.metadata_by_rule["joint.day.weekend_subject_whitelist"]["generic_contract_status"]
            == "covered_by_generic_contract"
            and "joint.day.weekend_subject_whitelist" in generic_scheduler_rule_ids()
            and weekend_subject_whitelist_runtime_snapshot["ai_or_migration_backlog"][0]["generic_contract_status"]
            == "covered_by_generic_contract"
            and weekend_subject_whitelist_runtime_snapshot["ai_or_agent_migration_plan"][0]["owner_agent_role"]
            == "code_execution"
        )
        weekend_double_slot_1 = Slot(day="星期六", block="上午", period=1)
        weekend_double_slot_2 = Slot(day="星期六", block="上午", period=2)
        weekend_double_slot_3 = Slot(day="星期六", block="上午", period=3)
        weekend_double_bridge = day_weekend_double_period_same_class_to_ai_or_problem(
            DayInputData(
                classes=["class_a"],
                cls_subj_teacher={
                    ("class_a", "math"): "teacher_1",
                    ("class_a", "science"): "teacher_2",
                },
                available_slots=[weekend_double_slot_1, weekend_double_slot_2, weekend_double_slot_3],
                fixed_assign={},
                req_hours={},
                subject_ban_slots={},
            )
        )
        weekend_double_solution = solve_cp_sat_problem(weekend_double_bridge.problem, time_limit_seconds=5)
        weekend_double_runtime_snapshot = runtime_trace_payload(
            mode="joint",
            run_id="audit",
            git_commit=None,
            trace=[
                {
                    "rule_id": "joint.day.weekend_double_period_same_class",
                    "ai_or_operation_delta": 36,
                    "ai_or_operations_by_type": {"NewBoolVar": 10, "Add": 26},
                }
            ],
            generic_rule_ids=generic_scheduler_rule_ids(),
        )
        scheduler_day_weekend_double_period_generic_contract = (
            weekend_double_solution.status_name == "OPTIMAL"
            and weekend_double_bridge.metadata_by_rule["joint.day.weekend_double_period_same_class"][
                "generic_contract_status"
            ]
            == "covered_by_generic_contract"
            and weekend_double_bridge.metadata_by_rule["joint.day.weekend_double_period_same_class"][
                "constraint_family_counts"
            ]
            == {
                "teacher_class_slot_bool_equalities": 6,
                "adjacent_pair_left_implications": 4,
                "adjacent_pair_right_implications": 4,
                "slot_pair_cover_lower_bounds": 6,
                "slot_pair_cover_overlap_caps": 6,
                "slot_without_adjacent_pair_zero": 0,
            }
            and "joint.day.weekend_double_period_same_class" in generic_scheduler_rule_ids()
            and weekend_double_runtime_snapshot["ai_or_migration_backlog"][0]["generic_contract_status"]
            == "covered_by_generic_contract"
            and weekend_double_runtime_snapshot["ai_or_agent_migration_plan"][0]["owner_agent_role"]
            == "code_execution"
        )
        weekend_cross_saturday_am = Slot(day="星期六", block="上午", period=1)
        weekend_cross_saturday_pm = Slot(day="星期六", block="下午", period=1)
        weekend_cross_bridge = day_weekend_cross_halfday_penalty_to_ai_or_problem(
            DayInputData(
                classes=["class_a"],
                cls_subj_teacher={
                    ("class_a", "math"): "teacher_1",
                    ("class_a", "science"): "teacher_2",
                },
                available_slots=[weekend_cross_saturday_am, weekend_cross_saturday_pm],
                fixed_assign={},
                req_hours={},
                subject_ban_slots={},
            ),
            penalty=200,
        )
        weekend_cross_solution = solve_cp_sat_problem(weekend_cross_bridge.problem, time_limit_seconds=5)
        weekend_cross_runtime_snapshot = runtime_trace_payload(
            mode="joint",
            run_id="audit",
            git_commit=None,
            trace=[
                {
                    "rule_id": "joint.day.weekend_cross_halfday_penalty",
                    "ai_or_operation_delta": 36,
                    "ai_or_operations_by_type": {"NewBoolVar": 16, "Add": 20},
                }
            ],
            generic_rule_ids=generic_scheduler_rule_ids(),
        )
        scheduler_day_weekend_cross_halfday_generic_contract = (
            weekend_cross_solution.status_name == "OPTIMAL"
            and weekend_cross_solution.objective_value == 0
            and weekend_cross_bridge.problem.objective is not None
            and len(weekend_cross_bridge.problem.objective.expression.terms) == 4
            and weekend_cross_bridge.metadata_by_rule["joint.day.weekend_cross_halfday_penalty"][
                "generic_contract_status"
            ]
            == "covered_by_generic_contract"
            and weekend_cross_bridge.metadata_by_rule["joint.day.weekend_cross_halfday_penalty"][
                "constraint_family_counts"
            ]
            == {
                "teacher_class_slot_bool_equalities": 4,
                "teacher_slot_implies_has_am": 2,
                "teacher_slot_implies_has_pm": 2,
                "has_am_lower_bounds": 2,
                "has_am_zero_constraints": 2,
                "has_pm_lower_bounds": 2,
                "has_pm_zero_constraints": 2,
                "cross_halfday_lower_bounds": 4,
            }
            and "joint.day.weekend_cross_halfday_penalty" in generic_scheduler_rule_ids()
            and weekend_cross_runtime_snapshot["ai_or_migration_backlog"][0]["generic_contract_status"]
            == "covered_by_generic_contract"
            and weekend_cross_runtime_snapshot["ai_or_agent_migration_plan"][0]["owner_agent_role"]
            == "code_execution"
        )
        yjc_sunday_slots = [
            Slot(day="星期日", block="上午", period=1),
            Slot(day="星期日", block="上午", period=2),
            Slot(day="星期日", block="下午", period=1),
            Slot(day="星期日", block="下午", period=2),
        ]
        yjc_sunday_bridge = day_yjc_sunday_am12_pm12_to_ai_or_problem(
            DayInputData(
                classes=["class_a"],
                cls_subj_teacher={
                    ("class_a", "math"): "teacher_target",
                    ("class_a", "science"): "teacher_other",
                },
                available_slots=yjc_sunday_slots,
                fixed_assign={},
                req_hours={},
                subject_ban_slots={},
            ),
            teachers=["teacher_target"],
        )
        yjc_sunday_solution = solve_cp_sat_problem(yjc_sunday_bridge.problem, time_limit_seconds=5)
        yjc_sunday_runtime_snapshot = runtime_trace_payload(
            mode="joint",
            run_id="audit",
            git_commit=None,
            trace=[
                {
                    "rule_id": "joint.day.yjc_sunday_am12_pm12_rule",
                    "ai_or_operation_delta": 19,
                    "ai_or_operations_by_type": {"NewBoolVar": 5, "Add": 14},
                }
            ],
            generic_rule_ids=generic_scheduler_rule_ids(),
        )
        scheduler_day_yjc_sunday_am12_pm12_generic_contract = (
            yjc_sunday_solution.status_name == "OPTIMAL"
            and yjc_sunday_bridge.problem.objective is None
            and yjc_sunday_bridge.metadata_by_rule["joint.day.yjc_sunday_am12_pm12_rule"][
                "generic_contract_status"
            ]
            == "covered_by_generic_contract"
            and yjc_sunday_bridge.metadata_by_rule["joint.day.yjc_sunday_am12_pm12_rule"][
                "constraint_family_counts"
            ]
            == {
                "target_slot_fixed_one": 0,
                "target_slot_lower_bounds": 4,
                "target_slot_implies": 4,
                "target_slot_zero": 0,
                "combo_upper_bounds": 4,
                "combo_lower_bounds": 1,
                "combo_hard_zero": 1,
            }
            and "joint.day.yjc_sunday_am12_pm12_rule" in generic_scheduler_rule_ids()
            and yjc_sunday_runtime_snapshot["ai_or_migration_backlog"][0]["generic_contract_status"]
            == "covered_by_generic_contract"
            and yjc_sunday_runtime_snapshot["ai_or_agent_migration_plan"][0]["owner_agent_role"]
            == "code_execution"
        )
        day_binding_slot_1 = Slot(day="星期一", block="上午", period=1)
        day_binding_slot_2 = Slot(day="星期六", block="下午", period=1)
        day_binding_bridge = day_binding_8chem_9bio_to_ai_or_problem(
            DayInputData(
                classes=["初二8班", "初二9班", "初二10班"],
                cls_subj_teacher={
                    ("初二8班", "化学"): "chem_teacher",
                    ("初二8班", "数学"): "math_teacher",
                    ("初二9班", "生物"): "bio_teacher",
                    ("初二10班", "化学"): "other_teacher",
                },
                available_slots=[day_binding_slot_1, day_binding_slot_2],
                fixed_assign={},
                req_hours={},
                subject_ban_slots={},
            )
        )
        day_binding_solution = solve_cp_sat_problem(day_binding_bridge.problem, time_limit_seconds=5)
        day_binding_runtime_snapshot = runtime_trace_payload(
            mode="joint",
            run_id="audit",
            git_commit=None,
            trace=[
                {
                    "rule_id": "joint.day.binding_8chem_9bio",
                    "ai_or_operation_delta": 2,
                    "ai_or_operations_by_type": {"Add": 2},
                }
            ],
            generic_rule_ids=generic_scheduler_rule_ids(),
        )
        scheduler_day_binding_generic_contract = (
            day_binding_solution.status_name == "OPTIMAL"
            and day_binding_bridge.metadata_by_rule["joint.day.binding_8chem_9bio"]["generic_contract_status"]
            == "covered_by_generic_contract"
            and day_binding_bridge.metadata_by_rule["joint.day.binding_8chem_9bio"]["constraint_family_counts"]
            == {"8chem_9bio_equalities": 2}
            and "joint.day.binding_8chem_9bio" in generic_scheduler_rule_ids()
            and day_binding_runtime_snapshot["ai_or_migration_backlog"][0]["generic_contract_status"]
            == "covered_by_generic_contract"
            and day_binding_runtime_snapshot["ai_or_agent_migration_plan"][0]["owner_agent_role"]
            == "code_execution"
        )
        weekend_one_day_saturday = Slot(day="星期六", block="上午", period=1)
        weekend_one_day_sunday = Slot(day="星期日", block="上午", period=1)
        weekend_one_day_bridge = day_weekend_one_day_only_to_ai_or_problem(
            DayInputData(
                classes=["class_a", "class_b"],
                cls_subj_teacher={
                    ("class_a", "math"): "teacher_1",
                    ("class_a", "science"): "teacher_2",
                    ("class_b", "math"): "teacher_1",
                },
                available_slots=[weekend_one_day_saturday, weekend_one_day_sunday],
                fixed_assign={},
                req_hours={
                    ("class_a", "math"): (0, 0, 1),
                    ("class_a", "science"): (0, 0, 1),
                    ("class_b", "math"): (0, 0, 1),
                },
                subject_ban_slots={},
            )
        )
        weekend_one_day_solution = solve_cp_sat_problem(weekend_one_day_bridge.problem, time_limit_seconds=5)
        weekend_one_day_runtime_snapshot = runtime_trace_payload(
            mode="joint",
            run_id="audit",
            git_commit=None,
            trace=[
                {
                    "rule_id": "joint.day.weekend_one_day_only",
                    "ai_or_operation_delta": 28,
                    "ai_or_operations_by_type": {"Add": 18, "NewBoolVar": 10},
                }
            ],
            generic_rule_ids=generic_scheduler_rule_ids(),
        )
        scheduler_day_weekend_one_day_only_generic_contract = (
            weekend_one_day_solution.status_name == "OPTIMAL"
            and weekend_one_day_bridge.metadata_by_rule["joint.day.weekend_one_day_only"]["generic_contract_status"]
            == "covered_by_generic_contract"
            and "joint.day.weekend_one_day_only" in generic_scheduler_rule_ids()
            and weekend_one_day_runtime_snapshot["ai_or_migration_backlog"][0]["generic_contract_status"]
            == "covered_by_generic_contract"
            and weekend_one_day_runtime_snapshot["ai_or_agent_migration_plan"][0]["owner_agent_role"]
            == "code_execution"
        )
        weekend_halfday_saturday_am = Slot(day="星期六", block="上午", period=1)
        weekend_halfday_saturday_pm = Slot(day="星期六", block="下午", period=1)
        weekend_halfday_sunday_am = Slot(day="星期日", block="上午", period=1)
        weekend_halfday_bridge = day_weekend_halfday_constraint_to_ai_or_problem(
            DayInputData(
                classes=["class_a"],
                cls_subj_teacher={
                    ("class_a", "math"): "teacher_1",
                    ("class_a", "science"): "teacher_2",
                },
                available_slots=[
                    weekend_halfday_saturday_am,
                    weekend_halfday_saturday_pm,
                    weekend_halfday_sunday_am,
                ],
                fixed_assign={("class_a", weekend_halfday_saturday_pm): "science"},
                req_hours={
                    ("class_a", "math"): (0, 0, 1),
                    ("class_a", "science"): (0, 0, 1),
                },
                subject_ban_slots={},
            )
        )
        weekend_halfday_solution = solve_cp_sat_problem(weekend_halfday_bridge.problem, time_limit_seconds=5)
        weekend_halfday_runtime_snapshot = runtime_trace_payload(
            mode="joint",
            run_id="audit",
            git_commit=None,
            trace=[
                {
                    "rule_id": "joint.day.weekend_halfday_constraint",
                    "ai_or_operation_delta": 32,
                    "ai_or_operations_by_type": {"Add": 20, "NewBoolVar": 12},
                }
            ],
            generic_rule_ids=generic_scheduler_rule_ids(),
        )
        scheduler_day_weekend_halfday_generic_contract = (
            weekend_halfday_solution.status_name == "OPTIMAL"
            and weekend_halfday_bridge.metadata_by_rule["joint.day.weekend_halfday_constraint"]["generic_contract_status"]
            == "covered_by_generic_contract"
            and "joint.day.weekend_halfday_constraint" in generic_scheduler_rule_ids()
            and "day.weekend_halfday_constraint" in generic_scheduler_rule_ids()
            and weekend_halfday_runtime_snapshot["ai_or_migration_backlog"][0]["generic_contract_status"]
            == "covered_by_generic_contract"
            and weekend_halfday_runtime_snapshot["ai_or_agent_migration_plan"][0]["owner_agent_role"]
            == "code_execution"
        )

        soft_objective_days = ("星期五", "星期日", "星期一")
        soft_objective_periods = ("晚自习1", "晚自习2")
        soft_objective_cst = {
            ("class_a", "数学"): "teacher_m1",
            ("class_b", "物理"): "teacher_m2",
            ("class_c", "历史"): "teacher_f1",
        }
        soft_objective_all_teachers = ["teacher_m1", "teacher_m2", "teacher_f1"]
        soft_objective_male_heads = ["teacher_m1", "teacher_m2"]
        soft_objective_female_heads = ["teacher_f1"]
        soft_objective_rules = {
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
        soft_objective_bridge = night_soft_objective_to_ai_or_problem(
            days=soft_objective_days,
            periods=soft_objective_periods,
            cst=soft_objective_cst,
            all_teachers=soft_objective_all_teachers,
            male_heads=soft_objective_male_heads,
            female_heads=soft_objective_female_heads,
            rules=soft_objective_rules,
            on_teacher_day_variable_names={
                (teacher, day): f"on[{teacher},{day}]"
                for teacher in soft_objective_all_teachers
                for day in soft_objective_days
            },
            y_variable_names={
                (cls, subj, day, period): f"y[{cls},{subj},{day},{period}]"
                for (cls, subj) in soft_objective_cst
                for day in soft_objective_days
                for period in soft_objective_periods
            },
            checkin_m_variable_names={
                (teacher, day): f"checkin_m[{teacher},{day}]"
                for teacher in soft_objective_male_heads
                for day in soft_objective_days
            },
            checkin_f_variable_names={
                (teacher, day): f"checkin_f[{teacher},{day}]"
                for teacher in soft_objective_female_heads
                for day in soft_objective_days
            },
        )
        soft_objective_solution = solve_cp_sat_problem(soft_objective_bridge.problem, time_limit_seconds=5)
        soft_objective_runtime_snapshot = runtime_trace_payload(
            mode="joint",
            run_id="audit",
            git_commit=None,
            trace=[
                {
                    "rule_id": "joint.night.soft_objective",
                    "ai_or_operation_delta": 133,
                    "ai_or_operations_by_type": {"Add": 93, "NewBoolVar": 40},
                },
                {
                    "rule_id": "night.soft_objective",
                    "ai_or_operation_delta": 133,
                    "ai_or_operations_by_type": {"Add": 93, "NewBoolVar": 40},
                },
            ],
            generic_rule_ids=generic_scheduler_rule_ids(),
        )
        soft_objective_backlog = {
            item["rule_id"]: item
            for item in soft_objective_runtime_snapshot["ai_or_migration_backlog"]
        }
        scheduler_night_soft_objective_generic_contract = (
            soft_objective_solution.status_name == "OPTIMAL"
            and soft_objective_bridge.metadata_by_rule["joint.night.soft_objective"]["generic_contract_status"]
            == "covered_by_generic_contract"
            and soft_objective_bridge.metadata_by_rule["joint.night.soft_objective"]["linear_constraint_count"] == 93
            and soft_objective_bridge.metadata_by_rule["joint.night.soft_objective"]["constraint_family_counts"][
                "night_soft_penalty_terms"
            ]
            == 46
            and len(soft_objective_bridge.problem.constraints) == 93
            and soft_objective_bridge.problem.objective is not None
            and "joint.night.soft_objective" in generic_scheduler_rule_ids()
            and "night.soft_objective" in generic_scheduler_rule_ids()
            and soft_objective_backlog["joint.night.soft_objective"]["generic_contract_status"]
            == "covered_by_generic_contract"
            and soft_objective_backlog["night.soft_objective"]["generic_contract_status"] == "covered_by_generic_contract"
            and {item["owner_agent_role"] for item in soft_objective_runtime_snapshot["ai_or_agent_migration_plan"]}
            == {"code_execution"}
        )

        duty_joint_days = ["星期一", "星期二", "星期日"]
        duty_joint_male_heads = ["teacher_m1", "teacher_m2"]
        duty_joint_female_heads = ["teacher_f1"]
        duty_joint_noon_male_names = {
            (teacher, day): f"noon_m[{teacher},{day}]"
            for teacher in duty_joint_male_heads
            for day in duty_joint_days
        }
        duty_joint_noon_female_names = {
            (teacher, day): f"noon_f[{teacher},{day}]"
            for teacher in duty_joint_female_heads
            for day in duty_joint_days
        }
        duty_joint_pm_names = {
            (teacher, day): f"pm_pre[{teacher},{day}]"
            for teacher in [*duty_joint_male_heads, *duty_joint_female_heads]
            for day in duty_joint_days
        }
        duty_joint_night_male_names = {
            (teacher, day): f"night_m[{teacher},{day}]"
            for teacher in duty_joint_male_heads
            for day in duty_joint_days
        }
        duty_joint_night_female_names = {
            (teacher, day): f"night_f[{teacher},{day}]"
            for teacher in duty_joint_female_heads
            for day in duty_joint_days
        }
        duty_joint_bridge = duty_joint_to_ai_or_problem(
            days=duty_joint_days,
            noon_male_duty_variable_names=duty_joint_noon_male_names,
            noon_female_duty_variable_names=duty_joint_noon_female_names,
            pm_pre_class_duty_variable_names=duty_joint_pm_names,
            night_dorm_duty_male_variable_names=duty_joint_night_male_names,
            night_dorm_duty_female_variable_names=duty_joint_night_female_names,
            male_heads=duty_joint_male_heads,
            female_heads=duty_joint_female_heads,
            cfg=DutyJointConfig(
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
            ),
        )
        duty_joint_solution = solve_cp_sat_problem(duty_joint_bridge.problem, time_limit_seconds=5)
        duty_joint_runtime_snapshot = runtime_trace_payload(
            mode="joint",
            run_id="audit",
            git_commit=None,
            trace=[
                {
                    "rule_id": "joint.link.duty_joint_constraints",
                    "ai_or_operation_delta": 136,
                    "ai_or_operations_by_type": {"Add": 89, "NewBoolVar": 8, "NewIntVar": 39},
                },
                {
                    "rule_id": "day.duty_joint_constraints",
                    "ai_or_operation_delta": 136,
                    "ai_or_operations_by_type": {"Add": 89, "NewBoolVar": 8, "NewIntVar": 39},
                },
            ],
            generic_rule_ids=generic_scheduler_rule_ids(),
        )
        duty_joint_backlog = {
            item["rule_id"]: item
            for item in duty_joint_runtime_snapshot["ai_or_migration_backlog"]
        }
        scheduler_duty_joint_generic_contract = (
            duty_joint_solution.status_name in {"OPTIMAL", "FEASIBLE"}
            and duty_joint_bridge.metadata_by_rule["joint.link.duty_joint_constraints"]["generic_contract_status"]
            == "covered_by_generic_contract"
            and duty_joint_bridge.metadata_by_rule["joint.link.duty_joint_constraints"]["linear_constraint_count"] == 89
            and duty_joint_bridge.metadata_by_rule["joint.link.duty_joint_constraints"]["constraint_family_counts"][
                "duty_joint_penalty_terms"
            ]
            == 15
            and len(duty_joint_bridge.problem.constraints) == 89
            and duty_joint_bridge.problem.objective is not None
            and "joint.link.duty_joint_constraints" in generic_scheduler_rule_ids()
            and "day.duty_joint_constraints" in generic_scheduler_rule_ids()
            and duty_joint_backlog["joint.link.duty_joint_constraints"]["generic_contract_status"]
            == "covered_by_generic_contract"
            and duty_joint_backlog["day.duty_joint_constraints"]["generic_contract_status"]
            == "covered_by_generic_contract"
            and {item["owner_agent_role"] for item in duty_joint_runtime_snapshot["ai_or_agent_migration_plan"]}
            == {"code_execution"}
        )

        grade_group_bridge = grade_group_duty_to_ai_or_problem(
            days=["星期一", "星期二", "星期六", "星期日"],
            members=["teacher_a", "teacher_b"],
            all_teachers=["teacher_a", "teacher_b"],
            cfg=GradeGroupDutyConfig(
                members=["teacher_a", "teacher_b"],
                min_once_mode="soft",
                daily_need_night_mode="soft",
                enable_fairness=True,
                w_daily_need_night=11,
                w_min_once=13,
                w_no_night_penalty=17,
                w_fairness_balance=19,
            ),
        )
        grade_group_solution = solve_cp_sat_problem(grade_group_bridge.problem, time_limit_seconds=5)
        grade_group_runtime_snapshot = runtime_trace_payload(
            mode="joint",
            run_id="audit",
            git_commit=None,
            trace=[
                {
                    "rule_id": "joint.link.grade_group_duty_constraints",
                    "ai_or_operation_delta": 105,
                    "ai_or_operations_by_type": {
                        "Add": 56,
                        "NewBoolVar": 30,
                        "NewConstant": 12,
                        "NewIntVar": 7,
                    },
                }
            ],
            generic_rule_ids=generic_scheduler_rule_ids(),
        )
        scheduler_grade_group_duty_generic_contract = (
            grade_group_solution.status_name == "OPTIMAL"
            and grade_group_bridge.metadata_by_rule["joint.link.grade_group_duty_constraints"]["generic_contract_status"]
            == "covered_by_generic_contract"
            and grade_group_bridge.metadata_by_rule["joint.link.grade_group_duty_constraints"][
                "linear_constraint_count"
            ]
            == 56
            and grade_group_bridge.metadata_by_rule["joint.link.grade_group_duty_constraints"][
                "constraint_family_counts"
            ]["grade_group_penalty_terms"]
            == 14
            and len(grade_group_bridge.problem.constraints) == 56
            and grade_group_bridge.problem.objective is not None
            and "joint.link.grade_group_duty_constraints" in generic_scheduler_rule_ids()
            and grade_group_runtime_snapshot["ai_or_migration_backlog"][0]["generic_contract_status"]
            == "covered_by_generic_contract"
            and grade_group_runtime_snapshot["ai_or_agent_migration_plan"][0]["owner_agent_role"] == "code_execution"
        )

        personalized_bridge = personalized_legacy_catalog_to_ai_or_problem(
            {
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
        )
        personalized_solution = solve_cp_sat_problem(personalized_bridge.problem, time_limit_seconds=5)
        scheduler_personalized_legacy_catalog_generic_contract = (
            personalized_solution.status_name == "OPTIMAL"
            and tuple(rule.rule_id for rule in personalized_bridge.problem.rules)
            == PERSONALIZED_RULE_INSTANCE_TEMPLATE_IDS
            and len(personalized_bridge.problem.constraints) == len(PERSONALIZED_RULE_INSTANCE_TEMPLATE_IDS)
            and personalized_bridge.metadata_by_rule["shared.personalized_constraints"]["template_kind"] == "collection"
            and personalized_bridge.metadata_by_rule["personalized.xhd_night_no_pm3"]["mode"] == "soft"
            and personalized_bridge.metadata_by_rule["personalized.xhd_night_no_pm3"]["targets"]
            == ("teacher_alpha",)
            and personalized_bridge.metadata_by_rule["personalized.couple_xhd_zfy"]["missing_target_slots"]
            == ("zfy",)
            and set(PERSONALIZED_RULE_INSTANCE_TEMPLATE_IDS).issubset(set(generic_scheduler_rule_ids()))
        )
        day_special_duty_bridge = day_special_duty_catalog_to_ai_or_problem(
            {
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
        )
        day_special_duty_solution = solve_cp_sat_problem(day_special_duty_bridge.problem, time_limit_seconds=5)
        scheduler_day_special_duty_catalog_generic_contract = (
            day_special_duty_solution.status_name == "OPTIMAL"
            and tuple(rule.rule_id for rule in day_special_duty_bridge.problem.rules)
            == ("joint.day.head_duty_constraints", "joint.day.noon_dorm_duty_constraints")
            and day_special_duty_bridge.metadata_by_rule["joint.day.head_duty_constraints"]["mode"] == "soft"
            and day_special_duty_bridge.metadata_by_rule["joint.day.head_duty_constraints"]["weight"] == 33
            and day_special_duty_bridge.metadata_by_rule["joint.day.noon_dorm_duty_constraints"]["enabled"] is False
            and day_special_duty_bridge.metadata_by_rule["joint.day.noon_dorm_duty_constraints"]["mode"] == "hard"
            and {"joint.day.head_duty_constraints", "joint.day.noon_dorm_duty_constraints"}.issubset(
                set(generic_scheduler_rule_ids())
            )
        )

        solve_config = build_scheduler_cp_sat_solve_config(
            {
                "solver_profile": "prove_bound",
                "time_limit_seconds": 15,
                "workers": 1,
                "search_branching": "fixed",
            },
            default_time_limit_seconds=300,
        )
        parameters = {spec.name: spec.value for spec in solve_config.parameters}
        scheduler_solver_parameter_rules_generic_contract = (
            parameters.get("search_branching") == "FIXED_SEARCH"
            and parameters.get("max_time_in_seconds") == 15.0
            and {
                "day.solver_parameters",
                "night.solver_parameters",
                "joint.solver_parameters",
            }.issubset(set(generic_scheduler_rule_ids()))
        )
        model = create_existing_cp_model("scheduler.solver_controls.audit")
        flag = model.NewBoolVar("ai_or_scheduler_control_smoke")
        model.Maximize(flag)
        solver, status = solve_model(
            model,
            {
                "solve": {
                    "time_limit_seconds": 10,
                    "workers": 1,
                    "relative_gap_limit": 0.1,
                }
            },
        )
        applied = getattr(solver, "ai_or_applied_solver_parameters", {})
        adapter = getattr(solver, "ai_or_execution_adapter", "")
        legacy_solver_source = _read_text(REPO_ROOT / "scheduler" / "solver" / "solve.py")
        day_entry_source = _read_text(REPO_ROOT / "scheduler" / "day_schedule_entry.py")
        day_entry_ai_or_adapter = (
            "solve_existing_cp_model" in day_entry_source
            and "cp_model.CpSolver()" not in day_entry_source
            and "solver.Solve(" not in day_entry_source
            and "solver.SolveWithSolutionCallback(" not in day_entry_source
        )
        night_entry_source = _read_text(REPO_ROOT / "scheduler" / "main.py")
        night_entry_ai_or_adapter = (
            "solve_existing_cp_model" in night_entry_source
            and "cp_model.CpSolver()" not in night_entry_source
            and "solver.Solve(" not in night_entry_source
            and "solver.SolveWithSolutionCallback(" not in night_entry_source
        )
        joint_pipeline_source = _read_text(REPO_ROOT / "scheduler" / "joint_pipeline.py")
        joint_pipeline_ai_or_adapter = (
            "solve_existing_cp_model" in joint_pipeline_source
            and "cp_model.CpSolver()" not in joint_pipeline_source
            and "solver.Solve(" not in joint_pipeline_source
            and "solver.SolveWithSolutionCallback(" not in joint_pipeline_source
        )
        model_factory_sources = {
            rel_path: _read_text(REPO_ROOT / rel_path)
            for rel_path in (
                "scheduler/day_schedule_entry.py",
                "scheduler/main.py",
                "scheduler/joint_solver.py",
                "scheduler/day_morning_reading_smoke_test.py",
                "scheduler/day_weekend_smoke_test.py",
            )
        }
        scheduler_model_factory_adapter = all(
            "create_existing_cp_model" in source and "cp_model.CpModel()" not in source
            for source in model_factory_sources.values()
        )
    except Exception as exc:  # pragma: no cover - defensive audit output
        return FrameworkCheck(
            "scheduler_solver_controls_bridge",
            "真实 scheduler 求解参数必须先编译为通用 CpSatSolveConfig，再应用到 CpSolver，不能只在新包 smoke 中使用 AI OR 控制面。",
            ("scheduler/solver_params.py", "verification/fixes/tests/test_solver_params.py"),
            "fail",
            tuple(),
            gap=f"scheduler solver controls bridge smoke 运行失败：{exc}",
        )

    ok = (
        parameters.get("search_branching") == "FIXED_SEARCH"
        and parameters.get("optimize_with_core") is True
        and status in {cp_model.OPTIMAL, cp_model.FEASIBLE}
        and applied.get("max_time_in_seconds") == 10.0
        and applied.get("relative_gap_limit") == 0.1
        and adapter == "existing_cp_model"
        and "cp_model.CpSolver" not in legacy_solver_source
        and ".Solve(" not in legacy_solver_source
        and day_entry_ai_or_adapter
        and night_entry_ai_or_adapter
        and joint_pipeline_ai_or_adapter
        and scheduler_model_factory_adapter
        and scheduler_rule_operation_trace
        and scheduler_rule_operation_summary
        and scheduler_rule_migration_backlog
        and scheduler_runtime_snapshot_migration_backlog
        and scheduler_runtime_snapshot_operation_types
        and scheduler_runtime_snapshot_candidate_specs
        and scheduler_agent_migration_plan_roles
        and scheduler_real_rule_generic_contract
        and scheduler_day_one_subject_generic_contract
        and scheduler_day_subject_hours_generic_contract
        and scheduler_day_teacher_no_conflict_generic_contract
        and scheduler_day_core_subject_teacher_day_load_generic_contract
        and scheduler_day_no_consecutive_same_teacher_same_class_generic_contract
        and scheduler_day_no_am1_am4_generic_contract
        and scheduler_day_teacher_weekday_am_pm_presence_generic_contract
        and scheduler_day_head_pm1_min_generic_contract
        and scheduler_day_am1_pm1_mutex_generic_contract
        and scheduler_day_two_class_am1_pm1_combo_generic_contract
        and scheduler_day_two_class_low_hours_generic_contract
        and scheduler_day_low_weekday_subject_generic_contract
        and scheduler_day_high_weekday_subject_generic_contract
        and scheduler_day_pe_time_window_generic_contract
        and scheduler_day_teacher_whitelist_generic_contract
        and scheduler_day_reduce_stem_am1_generic_contract
        and scheduler_day_pe_reduce_am_soft_generic_contract
        and scheduler_day_pref_lang_am_generic_contract
        and scheduler_day_pe_tech_compact_soft_generic_contract
        and scheduler_day_teacher_am4_pm1_threshold_generic_contract
        and scheduler_day_weekday_subject_balance_generic_contract
        and scheduler_day_teacher_continuity_generic_contract
        and scheduler_day_two_class_daily_min_generic_contract
        and scheduler_day_teacher_m1_cap_generic_contract
        and scheduler_day_teacher_am1_fragmentation_generic_contract
        and scheduler_day_multi_class_halfday_generic_contract
        and scheduler_solver_parameter_rules_generic_contract
        and scheduler_duty_joint_generic_contract
        and scheduler_night_soft_objective_generic_contract
        and scheduler_personalized_legacy_catalog_generic_contract
        and scheduler_day_special_duty_catalog_generic_contract
        and scheduler_grade_group_duty_generic_contract
        and scheduler_day_am1_pm1_exclusive_generic_contract
        and scheduler_day_single_class_weekly_am1_cap_generic_contract
        and scheduler_day_morning_reading_generic_contract
        and scheduler_day_weekend_subject_whitelist_generic_contract
        and scheduler_day_weekend_double_period_generic_contract
        and scheduler_day_weekend_cross_halfday_generic_contract
        and scheduler_day_yjc_sunday_am12_pm12_generic_contract
        and scheduler_day_binding_generic_contract
        and scheduler_day_weekend_one_day_only_generic_contract
        and scheduler_day_weekend_halfday_generic_contract
        and scheduler_night_hard_bans_generic_contract
        and scheduler_night_hard_teacher_limits_generic_contract
        and scheduler_night_binding_generic_contract
        and scheduler_night_physics_math_special_generic_contract
        and scheduler_night_fri_sun_mutex_generic_contract
        and scheduler_night_single_class_p1_p2_split_generic_contract
        and scheduler_night_double_class_weekday_p1_p2_split_generic_contract
        and scheduler_night_checkin_generic_contract
    )
    return FrameworkCheck(
        "scheduler_solver_controls_bridge",
        "真实 scheduler 求解参数必须先编译为通用 CpSatSolveConfig，再应用到 CpSolver，不能只在新包 smoke 中使用 AI OR 控制面。",
        ("scheduler/solver_params.py", "verification/fixes/tests/test_solver_params.py"),
        "pass" if ok else "fail",
        (
            f"scheduler_control_search={parameters.get('search_branching')}",
            f"scheduler_control_core={parameters.get('optimize_with_core')}",
            f"legacy_solver_ai_or_parameters={bool(applied)}",
            f"legacy_solver_ai_or_adapter={adapter}",
            f"day_entry_ai_or_adapter={day_entry_ai_or_adapter}",
            f"night_entry_ai_or_adapter={night_entry_ai_or_adapter}",
            f"joint_pipeline_ai_or_adapter={joint_pipeline_ai_or_adapter}",
            f"scheduler_model_factory_adapter={scheduler_model_factory_adapter}",
            f"scheduler_rule_operation_trace={scheduler_rule_operation_trace}",
            f"scheduler_rule_operation_summary={scheduler_rule_operation_summary}",
            f"scheduler_rule_migration_backlog={scheduler_rule_migration_backlog}",
            f"scheduler_runtime_snapshot_migration_backlog={scheduler_runtime_snapshot_migration_backlog}",
            f"scheduler_runtime_snapshot_operation_types={scheduler_runtime_snapshot_operation_types}",
            f"scheduler_runtime_snapshot_candidate_specs={scheduler_runtime_snapshot_candidate_specs}",
            f"scheduler_agent_migration_plan_roles={scheduler_agent_migration_plan_roles}",
            f"scheduler_real_rule_generic_contract={scheduler_real_rule_generic_contract}",
            f"scheduler_day_one_subject_generic_contract={scheduler_day_one_subject_generic_contract}",
            f"scheduler_day_subject_hours_generic_contract={scheduler_day_subject_hours_generic_contract}",
            f"scheduler_day_teacher_no_conflict_generic_contract={scheduler_day_teacher_no_conflict_generic_contract}",
            f"scheduler_day_core_subject_teacher_day_load_generic_contract={scheduler_day_core_subject_teacher_day_load_generic_contract}",
            f"scheduler_day_no_consecutive_same_teacher_same_class_generic_contract={scheduler_day_no_consecutive_same_teacher_same_class_generic_contract}",
            f"scheduler_day_no_am1_am4_generic_contract={scheduler_day_no_am1_am4_generic_contract}",
            f"scheduler_day_teacher_weekday_am_pm_presence_generic_contract={scheduler_day_teacher_weekday_am_pm_presence_generic_contract}",
            f"scheduler_day_head_pm1_min_generic_contract={scheduler_day_head_pm1_min_generic_contract}",
            f"scheduler_day_am1_pm1_mutex_generic_contract={scheduler_day_am1_pm1_mutex_generic_contract}",
            f"scheduler_day_two_class_am1_pm1_combo_generic_contract={scheduler_day_two_class_am1_pm1_combo_generic_contract}",
            f"scheduler_day_two_class_low_hours_generic_contract={scheduler_day_two_class_low_hours_generic_contract}",
            f"scheduler_day_low_weekday_subject_generic_contract={scheduler_day_low_weekday_subject_generic_contract}",
            f"scheduler_day_high_weekday_subject_generic_contract={scheduler_day_high_weekday_subject_generic_contract}",
            f"scheduler_day_pe_time_window_generic_contract={scheduler_day_pe_time_window_generic_contract}",
            f"scheduler_day_teacher_whitelist_generic_contract={scheduler_day_teacher_whitelist_generic_contract}",
            f"scheduler_day_reduce_stem_am1_generic_contract={scheduler_day_reduce_stem_am1_generic_contract}",
            f"scheduler_day_pe_reduce_am_soft_generic_contract={scheduler_day_pe_reduce_am_soft_generic_contract}",
            f"scheduler_day_pref_lang_am_generic_contract={scheduler_day_pref_lang_am_generic_contract}",
            f"scheduler_day_pe_tech_compact_soft_generic_contract={scheduler_day_pe_tech_compact_soft_generic_contract}",
            f"scheduler_day_teacher_am4_pm1_threshold_generic_contract={scheduler_day_teacher_am4_pm1_threshold_generic_contract}",
            f"scheduler_day_weekday_subject_balance_generic_contract={scheduler_day_weekday_subject_balance_generic_contract}",
            f"scheduler_day_teacher_continuity_generic_contract={scheduler_day_teacher_continuity_generic_contract}",
            f"scheduler_day_two_class_daily_min_generic_contract={scheduler_day_two_class_daily_min_generic_contract}",
            f"scheduler_day_teacher_m1_cap_generic_contract={scheduler_day_teacher_m1_cap_generic_contract}",
            f"scheduler_day_teacher_am1_fragmentation_generic_contract={scheduler_day_teacher_am1_fragmentation_generic_contract}",
            f"scheduler_day_multi_class_halfday_generic_contract={scheduler_day_multi_class_halfday_generic_contract}",
            f"scheduler_solver_parameter_rules_generic_contract={scheduler_solver_parameter_rules_generic_contract}",
            f"scheduler_duty_joint_generic_contract={scheduler_duty_joint_generic_contract}",
            f"scheduler_night_soft_objective_generic_contract={scheduler_night_soft_objective_generic_contract}",
            f"scheduler_personalized_legacy_catalog_generic_contract={scheduler_personalized_legacy_catalog_generic_contract}",
            f"scheduler_day_special_duty_catalog_generic_contract={scheduler_day_special_duty_catalog_generic_contract}",
            f"scheduler_grade_group_duty_generic_contract={scheduler_grade_group_duty_generic_contract}",
            f"scheduler_day_am1_pm1_exclusive_generic_contract={scheduler_day_am1_pm1_exclusive_generic_contract}",
            f"scheduler_day_single_class_weekly_am1_cap_generic_contract={scheduler_day_single_class_weekly_am1_cap_generic_contract}",
            f"scheduler_day_morning_reading_generic_contract={scheduler_day_morning_reading_generic_contract}",
            f"scheduler_day_weekend_subject_whitelist_generic_contract={scheduler_day_weekend_subject_whitelist_generic_contract}",
            f"scheduler_day_weekend_double_period_generic_contract={scheduler_day_weekend_double_period_generic_contract}",
            f"scheduler_day_weekend_cross_halfday_generic_contract={scheduler_day_weekend_cross_halfday_generic_contract}",
            f"scheduler_day_yjc_sunday_am12_pm12_generic_contract={scheduler_day_yjc_sunday_am12_pm12_generic_contract}",
            f"scheduler_day_binding_generic_contract={scheduler_day_binding_generic_contract}",
            f"scheduler_day_weekend_one_day_only_generic_contract={scheduler_day_weekend_one_day_only_generic_contract}",
            f"scheduler_day_weekend_halfday_generic_contract={scheduler_day_weekend_halfday_generic_contract}",
            f"scheduler_night_hard_bans_generic_contract={scheduler_night_hard_bans_generic_contract}",
            f"scheduler_night_hard_teacher_limits_generic_contract={scheduler_night_hard_teacher_limits_generic_contract}",
            f"scheduler_night_binding_generic_contract={scheduler_night_binding_generic_contract}",
            f"scheduler_night_physics_math_special_generic_contract={scheduler_night_physics_math_special_generic_contract}",
            f"scheduler_night_fri_sun_mutex_generic_contract={scheduler_night_fri_sun_mutex_generic_contract}",
            f"scheduler_night_single_class_p1_p2_split_generic_contract={scheduler_night_single_class_p1_p2_split_generic_contract}",
            f"scheduler_night_double_class_weekday_p1_p2_split_generic_contract={scheduler_night_double_class_weekday_p1_p2_split_generic_contract}",
            f"scheduler_night_checkin_generic_contract={scheduler_night_checkin_generic_contract}",
        )
        if ok
        else tuple(),
        gap="" if ok else f"scheduler solver controls 未得到预期迁移证据：parameters={parameters}, applied={applied}, adapter={adapter}, day_entry_ai_or_adapter={day_entry_ai_or_adapter}, night_entry_ai_or_adapter={night_entry_ai_or_adapter}, joint_pipeline_ai_or_adapter={joint_pipeline_ai_or_adapter}, scheduler_model_factory_adapter={scheduler_model_factory_adapter}, scheduler_rule_operation_trace={scheduler_rule_operation_trace}, scheduler_rule_operation_summary={scheduler_rule_operation_summary}, scheduler_rule_migration_backlog={scheduler_rule_migration_backlog}, scheduler_runtime_snapshot_migration_backlog={scheduler_runtime_snapshot_migration_backlog}, scheduler_runtime_snapshot_operation_types={scheduler_runtime_snapshot_operation_types}, scheduler_runtime_snapshot_candidate_specs={scheduler_runtime_snapshot_candidate_specs}, scheduler_agent_migration_plan_roles={scheduler_agent_migration_plan_roles}, scheduler_real_rule_generic_contract={scheduler_real_rule_generic_contract}, scheduler_day_one_subject_generic_contract={scheduler_day_one_subject_generic_contract}, scheduler_day_subject_hours_generic_contract={scheduler_day_subject_hours_generic_contract}, scheduler_day_teacher_no_conflict_generic_contract={scheduler_day_teacher_no_conflict_generic_contract}, scheduler_day_core_subject_teacher_day_load_generic_contract={scheduler_day_core_subject_teacher_day_load_generic_contract}, scheduler_day_no_consecutive_same_teacher_same_class_generic_contract={scheduler_day_no_consecutive_same_teacher_same_class_generic_contract}, scheduler_day_no_am1_am4_generic_contract={scheduler_day_no_am1_am4_generic_contract}, scheduler_day_teacher_weekday_am_pm_presence_generic_contract={scheduler_day_teacher_weekday_am_pm_presence_generic_contract}, scheduler_day_head_pm1_min_generic_contract={scheduler_day_head_pm1_min_generic_contract}, scheduler_day_am1_pm1_mutex_generic_contract={scheduler_day_am1_pm1_mutex_generic_contract}, scheduler_day_two_class_am1_pm1_combo_generic_contract={scheduler_day_two_class_am1_pm1_combo_generic_contract}, scheduler_day_two_class_low_hours_generic_contract={scheduler_day_two_class_low_hours_generic_contract}, scheduler_day_low_weekday_subject_generic_contract={scheduler_day_low_weekday_subject_generic_contract}, scheduler_day_high_weekday_subject_generic_contract={scheduler_day_high_weekday_subject_generic_contract}, scheduler_day_pe_time_window_generic_contract={scheduler_day_pe_time_window_generic_contract}, scheduler_day_teacher_whitelist_generic_contract={scheduler_day_teacher_whitelist_generic_contract}, scheduler_day_reduce_stem_am1_generic_contract={scheduler_day_reduce_stem_am1_generic_contract}, scheduler_day_pe_reduce_am_soft_generic_contract={scheduler_day_pe_reduce_am_soft_generic_contract}, scheduler_day_pref_lang_am_generic_contract={scheduler_day_pref_lang_am_generic_contract}, scheduler_day_pe_tech_compact_soft_generic_contract={scheduler_day_pe_tech_compact_soft_generic_contract}, scheduler_day_teacher_am4_pm1_threshold_generic_contract={scheduler_day_teacher_am4_pm1_threshold_generic_contract}, scheduler_day_weekday_subject_balance_generic_contract={scheduler_day_weekday_subject_balance_generic_contract}, scheduler_day_teacher_continuity_generic_contract={scheduler_day_teacher_continuity_generic_contract}, scheduler_day_two_class_daily_min_generic_contract={scheduler_day_two_class_daily_min_generic_contract}, scheduler_day_teacher_m1_cap_generic_contract={scheduler_day_teacher_m1_cap_generic_contract}, scheduler_day_teacher_am1_fragmentation_generic_contract={scheduler_day_teacher_am1_fragmentation_generic_contract}, scheduler_day_multi_class_halfday_generic_contract={scheduler_day_multi_class_halfday_generic_contract}, scheduler_solver_parameter_rules_generic_contract={scheduler_solver_parameter_rules_generic_contract}, scheduler_duty_joint_generic_contract={scheduler_duty_joint_generic_contract}, scheduler_night_soft_objective_generic_contract={scheduler_night_soft_objective_generic_contract}, scheduler_grade_group_duty_generic_contract={scheduler_grade_group_duty_generic_contract}, scheduler_day_am1_pm1_exclusive_generic_contract={scheduler_day_am1_pm1_exclusive_generic_contract}, scheduler_day_single_class_weekly_am1_cap_generic_contract={scheduler_day_single_class_weekly_am1_cap_generic_contract}, scheduler_day_morning_reading_generic_contract={scheduler_day_morning_reading_generic_contract}, scheduler_day_weekend_subject_whitelist_generic_contract={scheduler_day_weekend_subject_whitelist_generic_contract}, scheduler_day_weekend_double_period_generic_contract={scheduler_day_weekend_double_period_generic_contract}, scheduler_day_weekend_cross_halfday_generic_contract={scheduler_day_weekend_cross_halfday_generic_contract}, scheduler_day_yjc_sunday_am12_pm12_generic_contract={scheduler_day_yjc_sunday_am12_pm12_generic_contract}, scheduler_day_binding_generic_contract={scheduler_day_binding_generic_contract}, scheduler_day_weekend_one_day_only_generic_contract={scheduler_day_weekend_one_day_only_generic_contract}, scheduler_day_weekend_halfday_generic_contract={scheduler_day_weekend_halfday_generic_contract}, scheduler_night_hard_bans_generic_contract={scheduler_night_hard_bans_generic_contract}, scheduler_night_hard_teacher_limits_generic_contract={scheduler_night_hard_teacher_limits_generic_contract}, scheduler_night_binding_generic_contract={scheduler_night_binding_generic_contract}, scheduler_night_physics_math_special_generic_contract={scheduler_night_physics_math_special_generic_contract}, scheduler_night_fri_sun_mutex_generic_contract={scheduler_night_fri_sun_mutex_generic_contract}, scheduler_night_single_class_p1_p2_split_generic_contract={scheduler_night_single_class_p1_p2_split_generic_contract}, scheduler_night_double_class_weekday_p1_p2_split_generic_contract={scheduler_night_double_class_weekday_p1_p2_split_generic_contract}, scheduler_night_checkin_generic_contract={scheduler_night_checkin_generic_contract}, status={status}",
    )


def _scheduler_conflict_detection_generic_backend_check(repo_root: Path) -> FrameworkCheck:
    source_path = repo_root / "scheduler" / "app" / "conflict_detection.py"
    try:
        from scheduler.app.conflict_detection import detect_rule_conflicts

        cfg = {
            "calendar": {"days": ["星期一", "星期日"], "periods": ["晚自习1"]},
            "teacher_table": {"columns": {"class": "班级"}},
            "evening": {"subjects": ["语文"], "weekly_occurrences_per_subject": 1},
            "hard_bans": {
                "teacher_day_bans": {
                    "星期一": ["教师A"],
                    "星期日": ["教师A"],
                }
            },
        }
        result = detect_rule_conflicts(cfg, [{"班级": "1班", "语文": "教师A"}])
        source = _read_text(source_path)
    except Exception as exc:  # pragma: no cover - defensive audit output
        return FrameworkCheck(
            "scheduler_conflict_detection_generic_backend",
            "小型 scheduler 冲突诊断子系统必须通过通用 OptimizationProblemSpec/solve_cp_sat_problem 执行 assumption-core 求解。",
            ("scheduler/app/conflict_detection.py", "verification/fixes/tests/test_web_rule_workspace.py"),
            "fail",
            tuple(),
            gap=f"scheduler conflict detection smoke 运行失败：{exc}",
        )

    direct_cp_model = "cp_model.CpModel" in source or "cp_model.CpSolver" in source
    ok = (
        not direct_cp_model
        and "OptimizationProblemSpec" in source
        and "solve_cp_sat_problem" in source
        and result.get("summary", {}).get("errors") == 1
        and result.get("conflicts")
    )
    return FrameworkCheck(
        "scheduler_conflict_detection_generic_backend",
        "小型 scheduler 冲突诊断子系统必须通过通用 OptimizationProblemSpec/solve_cp_sat_problem 执行 assumption-core 求解。",
        ("scheduler/app/conflict_detection.py", "verification/fixes/tests/test_web_rule_workspace.py"),
        "pass" if ok else "fail",
        (
            "conflict_detection_backend=ai_or",
            f"conflict_detection_errors={result.get('summary', {}).get('errors')}",
        )
        if ok
        else tuple(),
        gap="" if ok else f"conflict detection backend 证据不足：direct_cp_model={direct_cp_model}, result={result}",
    )


def _scheduler_exam_review_generic_backend_check(repo_root: Path) -> FrameworkCheck:
    source_path = repo_root / "scheduler" / "exam_review_schedule.py"
    try:
        from scheduler.exam_review_schedule import build_review_schedule_problem, solve_review_schedule

        classes = ("1班", "2班")
        courses_by_class = {
            "1班": {
                "语文": "语文教师1",
                "数学": "共享数学",
                "外语": "外语教师1",
                "物理": "物理教师1",
                "化学": "化学教师1",
                "生物": "生物教师1",
            },
            "2班": {
                "语文": "语文教师2",
                "数学": "共享数学",
                "外语": "外语教师2",
                "物理": "物理教师2",
                "化学": "化学教师2",
                "生物": "生物教师2",
            },
        }
        compiled = build_review_schedule_problem(classes, courses_by_class)
        result = solve_review_schedule(classes, courses_by_class, time_limit_seconds=5)
        source = _read_text(source_path)
    except Exception as exc:  # pragma: no cover - defensive audit output
        return FrameworkCheck(
            "scheduler_exam_review_generic_backend",
            "临时考前复习排课子系统必须编译为通用 OptimizationProblemSpec，并经 solve_cp_sat_problem 求解。",
            ("scheduler/exam_review_schedule.py", "scheduler/tests/test_exam_review_schedule.py"),
            "fail",
            tuple(),
            gap=f"scheduler exam review generic backend smoke 运行失败：{exc}",
        )

    direct_cp_model = "cp_model.CpModel" in source or "cp_model.CpSolver" in source
    ok = (
        not direct_cp_model
        and "OptimizationProblemSpec" in source
        and "solve_cp_sat_problem" in source
        and compiled.problem.problem_id == "exam_review_schedule"
        and len(compiled.assignment_by_variable) == 40
        and result.solver_status in {"OPTIMAL", "FEASIBLE"}
        and not result.validation_errors
        and len(result.assignments) == 12
    )
    return FrameworkCheck(
        "scheduler_exam_review_generic_backend",
        "临时考前复习排课子系统必须编译为通用 OptimizationProblemSpec，并经 solve_cp_sat_problem 求解。",
        ("scheduler/exam_review_schedule.py", "scheduler/tests/test_exam_review_schedule.py"),
        "pass" if ok else "fail",
        (
            "exam_review_backend=ai_or",
            f"exam_review_status={result.solver_status}",
            f"exam_review_variables={len(compiled.problem.variables)}",
            f"exam_review_assignments={len(result.assignments)}",
        )
        if ok
        else tuple(),
        gap="" if ok else f"exam review backend 证据不足：direct_cp_model={direct_cp_model}, result={result}",
    )


def _tracked_files(repo_root: Path) -> tuple[bool, tuple[str, ...], str]:
    proc = subprocess.run(
        ["git", "-c", f"safe.directory={repo_root.as_posix()}", "ls-files"],
        cwd=repo_root,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if proc.returncode != 0:
        return False, tuple(), proc.stdout.strip()
    return True, tuple(path.strip().replace("\\", "/") for path in proc.stdout.splitlines() if path.strip()), ""


def _release_boundary_hygiene_check(repo_root: Path) -> FrameworkCheck:
    ok, files, error = _tracked_files(repo_root)
    if not ok:
        return FrameworkCheck(
            "release_boundary_hygiene",
            "开源发布边界必须由 Git 跟踪文件证明，不能把临时输出、截图、日志或结果包发布出去。",
            ("verification/fixes/tests/test_engineering_hygiene.py",),
            "fail",
            tuple(),
            gap=f"无法读取 Git 跟踪清单：{error}",
        )
    blocked = tuple(
        path
        for path in files
        if path.startswith(GENERATED_PREFIXES)
        or (path.lower().endswith(GENERATED_EXTENSIONS) and path not in PUBLIC_STATIC_IMAGE_PATHS)
    )
    return FrameworkCheck(
        "release_boundary_hygiene",
        "开源发布边界必须由 Git 跟踪文件证明，不能把临时输出、截图、日志或结果包发布出去。",
        ("verification/fixes/tests/test_engineering_hygiene.py", "docs/open_source_release_audit.md"),
        "pass" if not blocked else "fail",
        (f"tracked_files={len(files)}", "tracked_generated_artifacts=0") if not blocked else tuple(),
        gap="" if not blocked else f"仍被跟踪的生成物：{', '.join(blocked[:20])}",
    )


def _open_source_deidentification_check(repo_root: Path) -> FrameworkCheck:
    ok, files, error = _tracked_files(repo_root)
    if not ok:
        return FrameworkCheck(
            "open_source_deidentification",
            "开源发布边界必须阻止样例教师/班级/场地名和本机绝对路径重新进入 Git 跟踪文本。",
            ("verification/fixes/ai_or_acceptance_audit.py", "profiles/current_school/profile.yaml"),
            "fail",
            tuple(),
            gap=f"无法读取 Git 跟踪清单：{error}",
        )
    scanned = 0
    hits: list[str] = []
    for rel_path in files:
        path = repo_root / rel_path
        if path.suffix.lower() not in TEXT_SCAN_EXTENSIONS:
            continue
        scanned += 1
        text = _read_text(path)
        for marker in DEIDENTIFICATION_BLOCKLIST:
            if marker in text:
                hits.append(f"{rel_path}:{marker}")
        for label, pattern in DEIDENTIFICATION_PATTERNS:
            if pattern.search(text):
                hits.append(f"{rel_path}:{label}")
    return FrameworkCheck(
        "open_source_deidentification",
        "开源发布边界必须阻止样例教师/班级/场地名和本机绝对路径重新进入 Git 跟踪文本。",
        ("verification/fixes/ai_or_acceptance_audit.py", "profiles/current_school/profile.yaml"),
        "pass" if not hits else "fail",
        (f"scanned_tracked_text_files={scanned}", "blocked_markers=0") if not hits else tuple(),
        gap="" if not hits else f"疑似未脱敏文本：{', '.join(hits[:20])}",
    )


def _documentation_positioning_check(repo_root: Path) -> FrameworkCheck:
    combined = "\n".join(
        _read_text(repo_root / path)
        for path in (
            "README.md",
            "ARCHITECTURE.md",
            "docs/ai_or_framework_architecture.md",
            "docs/open_source_release_audit.md",
        )
    )
    ok, missing = _contains_all(
        combined,
        (
            "AI-Orchestrated Optimization",
            "通用中小学排课系统",
            "规则第一",
            "通用 CP-SAT",
            "产品主线围绕学校需求",
            "open_source_release_audit",
            "exact_cp_sat_shape_contract",
            "catalog_contract",
        ),
    )
    return FrameworkCheck(
        "documentation_positioning",
        "文档必须区分通用中小学排课产品主线与内部通用优化内核，保持规则优先和匿名开源边界。",
        (
            "README.md",
            "ARCHITECTURE.md",
            "docs/ai_or_framework_architecture.md",
            "docs/open_source_release_audit.md",
        ),
        "pass" if ok else "fail",
        ("README/ARCHITECTURE/docs 均声明通用框架、规则优先和匿名开源边界。",) if ok else tuple(),
        gap="" if ok else f"文档定位缺少：{', '.join(missing)}",
    )


def build_audit(repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    checks = [
        _kernel_files_check(repo_root),
        _agent_architecture_check(),
        _generic_solver_capabilities_check(),
        _agent_orchestration_workflow_check(),
        _scheduler_generic_rule_bridge_check(repo_root),
        _scheduler_solver_controls_bridge_check(),
        _scheduler_conflict_detection_generic_backend_check(repo_root),
        _scheduler_exam_review_generic_backend_check(repo_root),
        _release_boundary_hygiene_check(repo_root),
        _open_source_deidentification_check(repo_root),
        _documentation_positioning_check(repo_root),
    ]
    failures = [check for check in checks if check.status != "pass"]
    return {
        "overall": "fail" if failures else "pass",
        "summary": {
            "total": len(checks),
            "pass": sum(1 for check in checks if check.status == "pass"),
            "fail": len(failures),
        },
        "checks": [asdict(check) for check in checks],
    }


def _format_text(report: dict[str, Any]) -> str:
    lines = [
        "# AI OR Framework Acceptance Audit",
        f"overall: {report['overall']}",
        f"summary: {report['summary']['pass']} pass, {report['summary']['fail']} fail",
        "",
    ]
    for check in report["checks"]:
        lines.append(f"- [{check['status']}] {check['id']}")
        lines.append(f"  requirement: {check['requirement']}")
        if check["evidence"]:
            lines.append(f"  evidence: {'; '.join(check['evidence'])}")
        if check["gap"]:
            lines.append(f"  gap: {check['gap']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit the generic AI OR framework release boundary.")
    parser.add_argument("--json", action="store_true", help="Print JSON instead of text.")
    args = parser.parse_args(argv)
    report = build_audit(REPO_ROOT)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(_format_text(report))
    return 0 if report["overall"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
