from __future__ import annotations

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


def _assignment_problem() -> OptimizationProblemSpec:
    return OptimizationProblemSpec(
        problem_id="brief_to_solver_assignment",
        variables=(
            VariableSpec.bool("alice_task_a"),
            VariableSpec.bool("alice_task_b"),
            VariableSpec.bool("bob_task_a"),
            VariableSpec.bool("bob_task_b"),
        ),
        rules=(
            RuleSpec("coverage", "each task must be assigned exactly once", "hard", 10),
            RuleSpec("capacity", "each worker takes at most one task", "hard", 20),
            RuleSpec("cost", "minimize weighted assignment cost", "soft", 100),
        ),
        constraints=(
            LinearConstraintSpec("cover_task_a", LinearExpression((LinearTerm("alice_task_a", 1), LinearTerm("bob_task_a", 1))), "==", 1, "coverage"),
            LinearConstraintSpec("cover_task_b", LinearExpression((LinearTerm("alice_task_b", 1), LinearTerm("bob_task_b", 1))), "==", 1, "coverage"),
            LinearConstraintSpec("cap_alice", LinearExpression((LinearTerm("alice_task_a", 1), LinearTerm("alice_task_b", 1))), "<=", 1, "capacity"),
            LinearConstraintSpec("cap_bob", LinearExpression((LinearTerm("bob_task_a", 1), LinearTerm("bob_task_b", 1))), "<=", 1, "capacity"),
        ),
        objective=ObjectiveSpec(
            "cost",
            "minimize",
            LinearExpression(
                (
                    LinearTerm("alice_task_a", 4),
                    LinearTerm("alice_task_b", 1),
                    LinearTerm("bob_task_a", 1),
                    LinearTerm("bob_task_b", 4),
                )
            ),
        ),
    )


def test_agent_solve_workflow_runs_human_brief_through_rule_first_solver_and_debug_report() -> None:
    request = AgentSolveRequest(
        brief=BusinessBrief(
            brief_id="dispatch-pain-001",
            natural_language="请把两个紧急任务分给两个人，必须每个任务有人做，每个人最多一个任务，并尽量降低成本。",
        ),
        handoff_artifacts=(
            AgentHandoffArtifact("business_expert", "business_pain_description", "two urgent tasks, two workers, cost matters"),
            AgentHandoffArtifact("chief_architect", "task_decomposition", "model as a binary assignment problem"),
            AgentHandoffArtifact("chief_architect", "solution_space_analysis", "small exact CP-SAT model; no decomposition needed"),
            AgentHandoffArtifact("mathematical_modeler", "model_artifacts", "binary x_worker_task variables plus coverage and capacity rules"),
            AgentHandoffArtifact("dimension_reduction_optimizer", "optimization_artifacts", "symmetry is negligible for this tiny instance"),
        ),
        problem=_assignment_problem(),
    )

    report = run_agent_solve_workflow(request, time_limit_seconds=5)

    assert report.brief.natural_language.startswith("请把两个紧急任务")
    assert report.missing_handoffs == ()
    assert report.solution.status_name == "OPTIMAL"
    assert report.solution.objective_value == 2
    assert report.solution.values == {
        "alice_task_a": 0,
        "alice_task_b": 1,
        "bob_task_a": 1,
        "bob_task_b": 0,
    }
    assert [item.rule_id for item in report.rule_trace] == ["coverage", "capacity", "cost"]
    assert report.rule_trace[0].constraints == ("cover_task_a", "cover_task_b")
    assert report.generated_handoff.artifact_type == "ortools_run_logs"
    assert "status=OPTIMAL" in report.generated_handoff.content
    assert report.debug_summary["status_name"] == "OPTIMAL"
    assert report.debug_summary["rule_count"] == 3
    assert report.debug_summary["constraint_count"] == 4


def test_agent_solve_workflow_blocks_execution_when_required_agent_handoffs_are_missing() -> None:
    request = AgentSolveRequest(
        brief=BusinessBrief("missing-handoff", "只给自然语言，不给建模和优化交接物。"),
        handoff_artifacts=(AgentHandoffArtifact("business_expert", "business_pain_description", "raw pain only"),),
        problem=_assignment_problem(),
    )

    report = run_agent_solve_workflow(request, time_limit_seconds=5)

    assert report.solution.status_name == "NOT_RUN"
    assert report.solution.values == {}
    assert report.missing_handoffs == (
        "task_decomposition",
        "solution_space_analysis",
        "model_artifacts",
        "optimization_artifacts",
    )
    assert report.debug_summary["blocked"] is True
