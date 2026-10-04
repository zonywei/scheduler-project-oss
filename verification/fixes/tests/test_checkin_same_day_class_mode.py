from __future__ import annotations

import sys
from pathlib import Path

from ortools.sat.python import cp_model


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


from scheduler.model.constraints.checkin import apply_checkin


def _solve_same_day_model(mode: str) -> tuple[int, float, int]:
    model = cp_model.CpModel()
    checkin = model.NewBoolVar("checkin_male")
    on = model.NewBoolVar("on_teacher_day")
    model.Add(on == 0)
    penalties = apply_checkin(
        model,
        {
            "checkin_m": {("男班主任", "星期一"): checkin},
            "checkin_f": {},
            "on_teacher_day": {("男班主任", "星期一"): on},
        },
        {
            "days": ["星期一"],
            "male_heads": ["男班主任"],
            "female_heads": [],
        },
        {
            "checkin": {
                "enabled": True,
                "per_day": {"male": 1, "female": 0},
                "per_teacher_max_times": 1,
                "require_teacher_has_class_that_day": True,
                "require_teacher_has_class_that_day_mode": mode,
                "w_require_teacher_has_class_that_day": 7,
            }
        },
    )
    if penalties:
        model.Minimize(sum(penalties))
    solver = cp_model.CpSolver()
    status = solver.Solve(model)
    objective = solver.ObjectiveValue() if status in {cp_model.OPTIMAL, cp_model.FEASIBLE} else 0.0
    return status, objective, len(penalties)


def test_checkin_same_day_class_hard_blocks_when_teacher_has_no_evening_class() -> None:
    status, _objective, penalty_count = _solve_same_day_model("hard")

    assert status == cp_model.INFEASIBLE
    assert penalty_count == 0


def test_checkin_same_day_class_soft_keeps_solution_and_records_penalty() -> None:
    status, objective, penalty_count = _solve_same_day_model("soft")

    assert status == cp_model.OPTIMAL
    assert penalty_count == 1
    assert int(objective) == 7


def test_checkin_extra_head_days_limit_candidate_to_configured_day() -> None:
    model = cp_model.CpModel()
    checkin_mon = model.NewBoolVar("checkin_mon")
    checkin_tue = model.NewBoolVar("checkin_tue")
    penalties = apply_checkin(
        model,
        {
            "checkin_m": {
                ("额外男候选", "星期一"): checkin_mon,
                ("额外男候选", "星期二"): checkin_tue,
            },
            "checkin_f": {},
            "on_teacher_day": {},
        },
        {
            "days": ["星期一", "星期二"],
            "male_heads": ["额外男候选"],
            "female_heads": [],
        },
        {
            "checkin": {
                "enabled": True,
                "per_day": {"male": 1, "female": 0},
                "per_teacher_max_times": 2,
                "require_teacher_has_class_that_day_mode": "off",
                "extra_heads": [{"name": "额外男候选", "gender": "男", "days": ["星期一"]}],
            }
        },
    )

    assert penalties == []
    status = cp_model.CpSolver().Solve(model)

    assert status == cp_model.INFEASIBLE
