from __future__ import annotations

import sys
from pathlib import Path

from ortools.sat.python import cp_model


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


from scheduler.model.constraints.duty_joint_constraints import DutyJointConfig, add_duty_joint_constraints


def _fixed_bool(model: cp_model.CpModel, name: str, value: int):
    var = model.NewBoolVar(name)
    model.Add(var == value)
    return var


def test_male_total_target_hard_keeps_legacy_exact_total() -> None:
    model = cp_model.CpModel()
    days = ["星期一", "星期二"]
    noon = {("严昆", "星期一"): _fixed_bool(model, "noon", 1)}
    night = {("严昆", "星期二"): _fixed_bool(model, "night", 1)}

    add_duty_joint_constraints(
        model,
        days=days,
        noon_male_duty=noon,
        noon_female_duty={},
        pm_pre_class_duty={},
        night_dorm_duty_male=night,
        night_dorm_duty_female={},
        male_heads=["严昆"],
        female_heads=[],
        cfg=DutyJointConfig(male_total_target=1, male_total_target_mode="hard"),
    )

    assert cp_model.CpSolver().Solve(model) == cp_model.INFEASIBLE


def test_male_total_target_soft_records_deviation_instead_of_blocking() -> None:
    model = cp_model.CpModel()
    days = ["星期一", "星期二"]
    noon = {("严昆", "星期一"): _fixed_bool(model, "noon", 1)}
    night = {("严昆", "星期二"): _fixed_bool(model, "night", 1)}

    penalties, info = add_duty_joint_constraints(
        model,
        days=days,
        noon_male_duty=noon,
        noon_female_duty={},
        pm_pre_class_duty={},
        night_dorm_duty_male=night,
        night_dorm_duty_female={},
        male_heads=["严昆"],
        female_heads=[],
        cfg=DutyJointConfig(male_total_target=1, male_total_target_mode="soft"),
    )
    model.Minimize(sum(penalties))
    solver = cp_model.CpSolver()

    assert solver.Solve(model) in {cp_model.OPTIMAL, cp_model.FEASIBLE}
    assert info["male_total_target_mode"] == "soft"
    assert solver.Value(info["male_total_target_deviation"]["严昆"]["over"]) == 1
