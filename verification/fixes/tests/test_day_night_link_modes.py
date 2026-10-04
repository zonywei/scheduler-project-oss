from __future__ import annotations

import sys
from pathlib import Path

from ortools.sat.python import cp_model


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


from scheduler.model.constraints.day_night_bridge import LinkConfig, add_link_constraints


def _forced_true(model: cp_model.CpModel, name: str) -> cp_model.IntVar:
    var = model.NewBoolVar(name)
    model.Add(var == 1)
    return var


def _sun_pm_night_mon_am_bridge(model: cp_model.CpModel) -> dict:
    sun_pm = _forced_true(model, "sun_pm")
    sun_night = _forced_true(model, "sun_night")
    mon_am1 = _forced_true(model, "mon_am1")
    mon_am2 = _forced_true(model, "mon_am2")
    return {
        "teachers": ["T"],
        "days": ["星期日", "星期一"],
        "day_has_pm": {("T", "星期日"): sun_pm},
        "day_has_am1": {("T", "星期一"): mon_am1},
        "day_has_am2": {("T", "星期一"): mon_am2},
        "day_load": {},
        "day_load_am_pm": {},
        "sun_has_pm": {"T": sun_pm},
        "night_has": {("T", "星期日"): sun_night},
        "checkin_m": {},
        "checkin_f": {},
        "day_has_any_am_pm": {},
        "cls_subj_teacher": {},
        "req_hours": {},
    }


def _base_config(mode: str) -> LinkConfig:
    return LinkConfig(
        enable_night_requires_day=False,
        enable_sun_night_no_mon_am1=False,
        enable_sun_pm_night_no_mon_am=True,
        sun_pm_night_no_mon_am_mode=mode,
        enable_two_class_empty_day_no_night=False,
    )


def test_sun_pm_night_mon_am_combo_can_be_softened() -> None:
    hard_model = cp_model.CpModel()
    add_link_constraints(hard_model, _sun_pm_night_mon_am_bridge(hard_model), _base_config("hard"))
    hard_status = cp_model.CpSolver().Solve(hard_model)

    soft_model = cp_model.CpModel()
    penalties, stats = add_link_constraints(
        soft_model,
        _sun_pm_night_mon_am_bridge(soft_model),
        _base_config("soft"),
    )
    soft_status = cp_model.CpSolver().Solve(soft_model)

    assert hard_status == cp_model.INFEASIBLE
    assert soft_status in {cp_model.OPTIMAL, cp_model.FEASIBLE}
    assert stats["viol_sun_pm_night_no_mon_am"]
    assert penalties
