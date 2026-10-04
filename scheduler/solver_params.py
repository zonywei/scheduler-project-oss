# -*- coding: utf-8 -*-
from __future__ import annotations

from ortools.sat.python import cp_model

from ai_orchestrated_optimization import (
    CpSatSolveConfig,
    SolverParameterSpec,
    apply_cp_sat_solve_config,
)


OPTIONAL_SOLVER_PARAMETER_KEYS = (
    "relative_gap_limit",
    "absolute_gap_limit",
    "log_search_progress",
    "solver_profile",
    "optimization_profile",
    "linearization_level",
    "cp_model_presolve",
    "cp_model_probing_level",
    "symmetry_level",
    "randomize_search",
    "repair_hint",
    "hint_conflict_limit",
    "use_lns",
    "use_rins_lns",
    "search_branching",
    "optimize_with_core",
    "find_multiple_cores",
    "use_objective_lb_search",
)

SOLVER_PROFILE_ALIASES = {
    "": "balanced",
    "default": "balanced",
    "balanced": "balanced",
    "continue": "improve_incumbent",
    "incumbent": "improve_incumbent",
    "improve": "improve_incumbent",
    "improve_incumbent": "improve_incumbent",
    "prove": "prove_bound",
    "bound": "prove_bound",
    "prove_bound": "prove_bound",
}

SEARCH_BRANCHING_ALIASES = {
    "automatic": "AUTOMATIC_SEARCH",
    "automatic_search": "AUTOMATIC_SEARCH",
    "fixed": "FIXED_SEARCH",
    "fixed_search": "FIXED_SEARCH",
    "portfolio": "PORTFOLIO_SEARCH",
    "portfolio_search": "PORTFOLIO_SEARCH",
    "lp": "LP_SEARCH",
    "lp_search": "LP_SEARCH",
    "pseudo_cost": "PSEUDO_COST_SEARCH",
    "pseudo_cost_search": "PSEUDO_COST_SEARCH",
}


def apply_joint_solver_parameters(
    solver: cp_model.CpSolver,
    joint_cfg: dict,
    *,
    default_time_limit_seconds: int,
) -> None:
    apply_solver_parameters(solver, joint_cfg, default_time_limit_seconds=default_time_limit_seconds)


def apply_night_solver_parameters(
    solver: cp_model.CpSolver,
    solve_cfg: dict,
    *,
    default_time_limit_seconds: int,
) -> None:
    apply_solver_parameters(solver, solve_cfg, default_time_limit_seconds=default_time_limit_seconds)


def apply_solver_parameters(
    solver: cp_model.CpSolver,
    cfg: dict,
    *,
    default_time_limit_seconds: int,
) -> None:
    solve_config = build_scheduler_cp_sat_solve_config(
        cfg,
        default_time_limit_seconds=default_time_limit_seconds,
    )
    apply_cp_sat_solve_config(solver, solve_config)


def build_scheduler_cp_sat_solve_config(
    cfg: dict,
    *,
    default_time_limit_seconds: int,
) -> CpSatSolveConfig:
    cfg = cfg or {}
    profile = _solver_profile(cfg)
    parameter_specs: list[SolverParameterSpec] = []
    parameter_specs.extend(_solver_profile_parameter_specs(profile))
    if _has_value(cfg.get("time_limit_seconds")):
        parameter_specs.append(
            SolverParameterSpec(
                "max_time_in_seconds",
                float(cfg.get("time_limit_seconds", default_time_limit_seconds)),
            )
        )
    if _has_value(cfg.get("workers")):
        parameter_specs.append(SolverParameterSpec("num_search_workers", int(cfg.get("workers", 8))))
    if _has_value(cfg.get("random_seed")):
        parameter_specs.append(SolverParameterSpec("random_seed", int(cfg.get("random_seed", 0))))
    if _has_value(cfg.get("relative_gap_limit")):
        parameter_specs.append(SolverParameterSpec("relative_gap_limit", float(cfg.get("relative_gap_limit"))))
    if _has_value(cfg.get("absolute_gap_limit")):
        parameter_specs.append(SolverParameterSpec("absolute_gap_limit", float(cfg.get("absolute_gap_limit"))))
    if _has_value(cfg.get("log_search_progress")):
        parameter_specs.append(SolverParameterSpec("log_search_progress", _to_bool(cfg.get("log_search_progress"))))
    parameter_specs.extend(_explicit_advanced_parameter_specs(cfg))
    return CpSatSolveConfig(parameters=tuple(parameter_specs))


def _solver_profile(cfg: dict) -> str:
    raw = cfg.get("solver_profile", cfg.get("optimization_profile", "balanced"))
    key = str(raw or "").strip().lower().replace("-", "_")
    if key not in SOLVER_PROFILE_ALIASES:
        raise ValueError(f"unknown solver profile: {raw!r}")
    return SOLVER_PROFILE_ALIASES[key]


def _solver_profile_parameter_specs(profile: str) -> tuple[SolverParameterSpec, ...]:
    if profile == "balanced":
        return ()
    if profile == "improve_incumbent":
        return (
            SolverParameterSpec("search_branching", "PORTFOLIO_SEARCH"),
            SolverParameterSpec("use_lns", True),
            SolverParameterSpec("use_rins_lns", True),
            SolverParameterSpec("randomize_search", True),
            SolverParameterSpec("repair_hint", True),
            SolverParameterSpec("hint_conflict_limit", 500),
        )
    if profile == "prove_bound":
        return (
            SolverParameterSpec("linearization_level", 2),
            SolverParameterSpec("cp_model_presolve", True),
            SolverParameterSpec("cp_model_probing_level", 2),
            SolverParameterSpec("symmetry_level", 2),
            SolverParameterSpec("repair_hint", True),
            SolverParameterSpec("hint_conflict_limit", 500),
            SolverParameterSpec("optimize_with_core", True),
            SolverParameterSpec("find_multiple_cores", True),
            SolverParameterSpec("use_objective_lb_search", True),
        )
    raise ValueError(f"unsupported solver profile: {profile!r}")


def _explicit_advanced_parameter_specs(cfg: dict) -> tuple[SolverParameterSpec, ...]:
    specs: list[SolverParameterSpec] = []
    int_fields = {
        "linearization_level",
        "cp_model_probing_level",
        "symmetry_level",
        "hint_conflict_limit",
    }
    bool_fields = {
        "cp_model_presolve",
        "randomize_search",
        "repair_hint",
        "use_lns",
        "use_rins_lns",
        "optimize_with_core",
        "find_multiple_cores",
        "use_objective_lb_search",
    }
    for field in int_fields:
        if _has_value(cfg.get(field)):
            specs.append(SolverParameterSpec(field, int(float(cfg[field]))))
    for field in bool_fields:
        if _has_value(cfg.get(field)):
            specs.append(SolverParameterSpec(field, _to_bool(cfg[field])))
    if _has_value(cfg.get("search_branching")):
        specs.append(SolverParameterSpec("search_branching", _search_branching_value(cfg["search_branching"])))
    return tuple(specs)


def _search_branching_value(value: object) -> int:
    if isinstance(value, int):
        return value
    text = str(value or "").strip().lower().replace("-", "_")
    if text in SEARCH_BRANCHING_ALIASES:
        return SEARCH_BRANCHING_ALIASES[text]
    if text.isdigit():
        return int(text)
    raise ValueError(f"invalid search_branching solver parameter: {value!r}")


def _has_value(value: object) -> bool:
    return value is not None and str(value).strip() != ""


def _to_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on", "y"}:
        return True
    if text in {"0", "false", "no", "off", "n"}:
        return False
    raise ValueError(f"invalid boolean solver parameter: {value!r}")
