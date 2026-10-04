from __future__ import annotations

import inspect
import sys
from pathlib import Path

from ortools.sat.python import cp_model


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


import scheduler.solver.solve as legacy_solver  # noqa: E402
from scheduler.solver.solve import solve_model  # noqa: E402
from scheduler.solver_params import (  # noqa: E402
    apply_joint_solver_parameters,
    apply_night_solver_parameters,
    build_scheduler_cp_sat_solve_config,
)


def test_joint_solver_parameters_apply_optional_quality_controls() -> None:
    solver = cp_model.CpSolver()

    apply_joint_solver_parameters(
        solver,
        {
            "time_limit_seconds": 45,
            "workers": 2,
            "random_seed": 77,
            "relative_gap_limit": 0.05,
            "absolute_gap_limit": 12,
            "log_search_progress": "true",
        },
        default_time_limit_seconds=300,
    )

    assert solver.parameters.max_time_in_seconds == 45
    assert solver.parameters.num_search_workers == 2
    assert solver.parameters.random_seed == 77
    assert solver.parameters.relative_gap_limit == 0.05
    assert solver.parameters.absolute_gap_limit == 12
    assert solver.parameters.log_search_progress is True


def test_night_solver_parameters_skip_blank_optional_quality_controls() -> None:
    solver = cp_model.CpSolver()

    apply_night_solver_parameters(
        solver,
        {
            "time_limit_seconds": 60,
            "workers": 1,
            "relative_gap_limit": "",
            "absolute_gap_limit": None,
            "log_search_progress": "false",
        },
        default_time_limit_seconds=3000,
    )

    assert solver.parameters.max_time_in_seconds == 60
    assert solver.parameters.num_search_workers == 1
    assert solver.parameters.relative_gap_limit == 0.0
    assert solver.parameters.absolute_gap_limit == 0.0001
    assert solver.parameters.log_search_progress is False


def test_legacy_solver_entry_uses_shared_solver_parameters() -> None:
    model = cp_model.CpModel()
    flag = model.NewBoolVar("flag")
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

    assert status in {cp_model.OPTIMAL, cp_model.FEASIBLE}
    assert solver.parameters.max_time_in_seconds == 10
    assert solver.parameters.num_search_workers == 1
    assert solver.parameters.relative_gap_limit == 0.1
    applied = getattr(solver, "ai_or_applied_solver_parameters")
    assert applied["max_time_in_seconds"] == 10.0
    assert applied["num_search_workers"] == 1
    assert applied["relative_gap_limit"] == 0.1


def test_legacy_solver_entry_delegates_execution_to_ai_or_adapter() -> None:
    source = inspect.getsource(legacy_solver.solve_model)

    assert "solve_existing_cp_model" in source
    assert "cp_model.CpSolver" not in source
    assert ".Solve(" not in source


def test_day_schedule_entry_delegates_solver_execution_to_ai_or_adapter() -> None:
    source = (REPO_ROOT / "scheduler" / "day_schedule_entry.py").read_text(encoding="utf-8")

    assert "solve_existing_cp_model" in source
    assert "cp_model.CpSolver()" not in source
    assert "solver.Solve(" not in source
    assert "solver.SolveWithSolutionCallback(" not in source


def test_night_entry_delegates_solver_execution_to_ai_or_adapter() -> None:
    source = (REPO_ROOT / "scheduler" / "main.py").read_text(encoding="utf-8")

    assert "solve_existing_cp_model" in source
    assert "cp_model.CpSolver()" not in source
    assert "solver.Solve(" not in source
    assert "solver.SolveWithSolutionCallback(" not in source


def test_joint_pipeline_delegates_solver_execution_to_ai_or_adapter() -> None:
    source = (REPO_ROOT / "scheduler" / "joint_pipeline.py").read_text(encoding="utf-8")

    assert "solve_existing_cp_model" in source
    assert "cp_model.CpSolver()" not in source
    assert "solver.Solve(" not in source
    assert "solver.SolveWithSolutionCallback(" not in source


def test_smoke_scripts_delegate_solver_execution_to_ai_or_adapter() -> None:
    for rel_path in (
        "scheduler/day_morning_reading_smoke_test.py",
        "scheduler/day_weekend_smoke_test.py",
    ):
        source = (REPO_ROOT / rel_path).read_text(encoding="utf-8")

        assert "solve_existing_cp_model" in source, rel_path
        assert "cp_model.CpSolver()" not in source, rel_path
        assert "solver.Solve(" not in source, rel_path


def test_scheduler_model_construction_goes_through_ai_or_factory() -> None:
    for rel_path in (
        "scheduler/day_schedule_entry.py",
        "scheduler/main.py",
        "scheduler/joint_solver.py",
        "scheduler/day_morning_reading_smoke_test.py",
        "scheduler/day_weekend_smoke_test.py",
    ):
        source = (REPO_ROOT / rel_path).read_text(encoding="utf-8")

        assert "create_existing_cp_model" in source, rel_path
        assert "cp_model.CpModel()" not in source, rel_path


def test_scheduler_solver_parameters_compile_to_ai_or_solve_config() -> None:
    solve_config = build_scheduler_cp_sat_solve_config(
        {
            "solver_profile": "prove_bound",
            "time_limit_seconds": 45,
            "workers": 2,
            "random_seed": 77,
            "search_branching": "fixed",
            "use_lns": "true",
        },
        default_time_limit_seconds=300,
    )

    parameters = {spec.name: spec.value for spec in solve_config.parameters}

    assert parameters["max_time_in_seconds"] == 45.0
    assert parameters["num_search_workers"] == 2
    assert parameters["random_seed"] == 77
    assert parameters["search_branching"] == "FIXED_SEARCH"
    assert parameters["optimize_with_core"] is True
    assert parameters["find_multiple_cores"] is True
    assert parameters["use_objective_lb_search"] is True
    assert parameters["use_lns"] is True


def test_continue_solver_profile_enables_incumbent_improvement_settings() -> None:
    solver = cp_model.CpSolver()

    apply_joint_solver_parameters(
        solver,
        {
            "solver_profile": "improve_incumbent",
            "time_limit_seconds": 90,
            "workers": 4,
        },
        default_time_limit_seconds=300,
    )

    assert solver.parameters.max_time_in_seconds == 90
    assert solver.parameters.num_search_workers == 4
    assert solver.parameters.search_branching == cp_model.PORTFOLIO_SEARCH
    assert solver.parameters.use_lns is True
    assert solver.parameters.use_rins_lns is True
    assert solver.parameters.randomize_search is True
    assert solver.parameters.repair_hint is True
    assert solver.parameters.hint_conflict_limit == 500


def test_solver_profile_can_be_overridden_by_explicit_advanced_parameters() -> None:
    solver = cp_model.CpSolver()

    apply_joint_solver_parameters(
        solver,
        {
            "optimization_profile": "prove_bound",
            "search_branching": "fixed",
            "use_lns": "true",
            "linearization_level": 1,
        },
        default_time_limit_seconds=300,
    )

    assert solver.parameters.optimize_with_core is True
    assert solver.parameters.find_multiple_cores is True
    assert solver.parameters.use_objective_lb_search is True
    assert solver.parameters.search_branching == cp_model.FIXED_SEARCH
    assert solver.parameters.use_lns is True
    assert solver.parameters.linearization_level == 1


def test_prove_bound_profile_repairs_warm_start_hint() -> None:
    solver = cp_model.CpSolver()

    apply_joint_solver_parameters(
        solver,
        {"solver_profile": "prove_bound"},
        default_time_limit_seconds=300,
    )

    assert solver.parameters.optimize_with_core is True
    assert solver.parameters.use_objective_lb_search is True
    assert solver.parameters.repair_hint is True
    assert solver.parameters.hint_conflict_limit == 500
