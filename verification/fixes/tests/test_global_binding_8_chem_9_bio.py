from __future__ import annotations

import sys
from pathlib import Path

from ortools.sat.python import cp_model

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scheduler.data.day_rules_reader import DayInputData, Slot
from scheduler.model.day_variables import build_day_variables
from scheduler.model.variables import build_variables
from scheduler.model.constraints.global_binding_constraints import (
    apply_global_day_binding_8_chem_9_bio,
    apply_global_night_binding_8_chem_9_bio,
)


def _assert_infeasible(model: cp_model.CpModel) -> None:
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 1
    status = solver.Solve(model)
    assert status == cp_model.INFEASIBLE, solver.StatusName(status)


def _test_day_weekend_binding() -> None:
    sat = Slot("星期六", "上午", 1)
    sun = Slot("星期日", "下午", 1)
    data = DayInputData(
        classes=["8班", "9班"],
        cls_subj_teacher={("8班", "化学"): "化学教师", ("9班", "生物"): "生物教师"},
        available_slots=[Slot("星期一", "上午", 1), sat, sun],
        fixed_assign={},
        req_hours={},
        subject_ban_slots={},
    )
    model = cp_model.CpModel()
    dv = build_day_variables(model, data)
    apply_global_day_binding_8_chem_9_bio(model, data, dv)

    model.Add(dv.x[("8班", "化学", sat)] == 1)
    model.Add(dv.x[("9班", "生物", sat)] == 0)
    _assert_infeasible(model)


def _test_night_weekend_binding() -> None:
    model = cp_model.CpModel()
    classes = ["8班", "9班"]
    cst = {("8班", "化学"): "化学教师", ("9班", "生物"): "生物教师"}
    days = ["星期六", "星期日"]
    periods = ["晚自习1", "晚自习2"]
    vars = build_variables(model, classes, cst, days, periods)
    ctx = {"classes": classes, "cst": cst, "days": days, "periods": periods}
    apply_global_night_binding_8_chem_9_bio(model, vars, ctx, {})

    model.Add(vars["y"][("8班", "化学", "星期日", "晚自习1")] == 1)
    model.Add(vars["y"][("9班", "生物", "星期日", "晚自习1")] == 0)
    _assert_infeasible(model)


def main() -> None:
    _test_day_weekend_binding()
    _test_night_weekend_binding()
    print("test_global_binding_8_chem_9_bio: PASS")

if __name__ == "__main__":
    raise SystemExit(main())
