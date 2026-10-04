# solver/solve.py
from ai_orchestrated_optimization import solve_existing_cp_model

from scheduler.solver_params import build_scheduler_cp_sat_solve_config


def solve_model(model, rules):
    solve_config = build_scheduler_cp_sat_solve_config(
        (rules or {}).get("solve", {}) or {},
        default_time_limit_seconds=60,
    )
    result = solve_existing_cp_model(model, solve_config)
    return result.solver, result.status
