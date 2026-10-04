# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Any


def solver_quality_fields(
    objective_value: Any,
    best_bound: Any,
    *,
    solver_status: str = "",
) -> dict[str, Any]:
    objective = _to_float(objective_value)
    bound = _to_float(best_bound)
    status = str(solver_status or "").strip().upper()
    if objective is None or bound is None:
        return {
            "objective_gap": None,
            "gap_percent": None,
            "optimality_status": "proven_optimal" if status == "OPTIMAL" else "unknown",
        }

    gap = max(0.0, objective - bound)
    if abs(gap) <= 1e-9:
        gap = 0.0
    if objective == 0:
        gap_percent = 0.0 if gap == 0.0 else None
    else:
        gap_percent = abs(gap / objective) * 100.0

    if status == "OPTIMAL" or gap == 0.0:
        optimality_status = "proven_optimal"
    elif status == "FEASIBLE":
        optimality_status = "gap_remaining"
    else:
        optimality_status = "unknown"
    return {
        "objective_gap": gap,
        "gap_percent": gap_percent,
        "optimality_status": optimality_status,
    }


def enrich_solver_overview(meta: dict[str, Any]) -> dict[str, Any]:
    out = dict(meta)
    out.update(
        solver_quality_fields(
            out.get("objective_value"),
            out.get("best_bound"),
            solver_status=str(out.get("solver_status") or ""),
        )
    )
    return out


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
