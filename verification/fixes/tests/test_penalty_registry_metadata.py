from __future__ import annotations

from ortools.sat.python import cp_model

from scheduler.diagnostics.penalty_registry import clear_registry, event_rows_with_values
from scheduler.model.constraints.soft_objective import apply_soft_objective


def test_subject_sync_event_log_keeps_subject_day_period() -> None:
    clear_registry()
    try:
        model = cp_model.CpModel()
        cst = {("1班", "语文"): "教师A", ("2班", "语文"): "教师B"}
        days = ["星期一"]
        periods = ["晚1"]
        y = {}
        for index, (cls, subj) in enumerate(cst, start=1):
            var = model.NewBoolVar(f"y_{index}")
            model.Add(var == 1)
            y[(cls, subj, "星期一", "晚1")] = var

        apply_soft_objective(
            model,
            {
                "y": y,
                "on_teacher_day": {},
                "all_teachers": [],
                "checkin_m": {},
                "checkin_f": {},
            },
            {
                "days": days,
                "periods": periods,
                "cst": cst,
                "male_heads": [],
                "female_heads": [],
            },
            {
                "soft": {"enabled": True},
                "evening_constraints": {"enable_subject_sync": True, "weights": {"subject_sync": 500}},
            },
            set_objective=False,
        )

        solver = cp_model.CpSolver()
        solver.parameters.num_search_workers = 1
        status = solver.Solve(model)
        assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)

        rows = event_rows_with_values(solver, solution_id="sol", snapshot_id="sol")
        hits = [row for row in rows if row["constraint_id"] == "night_subject_sync"]
        assert len(hits) == 1
        assert hits[0]["subject"] == "语文"
        assert hits[0]["day"] == "星期一"
        assert hits[0]["period"] == "晚1"
        assert hits[0]["teacher_name"] == "GLOBAL"
        assert hits[0]["penalty"] == 500.0
    finally:
        clear_registry()
