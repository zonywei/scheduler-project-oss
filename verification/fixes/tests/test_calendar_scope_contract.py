from __future__ import annotations

import sys
from pathlib import Path

from ortools.sat.python import cp_model


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


from scheduler.calendar import (  # noqa: E402
    ALL_DAYS,
    DAY_ORDER,
    DEFAULT_NIGHT_DAYS,
    SATURDAY,
    SUNDAY,
    WEEKDAY_DAYS,
    WEEKEND_DAYS,
    adjacent_day_pairs,
    day_rank,
    day_night_bridge_days,
    previous_day,
)
from scheduler.data import day_rules_reader  # noqa: E402
from scheduler.data.day_rules_reader import DayInputData, Slot  # noqa: E402
from scheduler.app import readiness  # noqa: E402
from scheduler.app.conflict_detection import DEFAULT_NIGHT_DAYS as CONFLICT_DEFAULT_NIGHT_DAYS  # noqa: E402
from scheduler.model.constraints import day_pairs  # noqa: E402
from scheduler.model.constraints.day_night_bridge import build_bridge_vars  # noqa: E402
from scheduler.model.day_variables import build_day_variables  # noqa: E402


def test_calendar_constants_back_legacy_day_reader_contracts() -> None:
    assert tuple(day_rules_reader.ALL_DAYS) == ALL_DAYS
    assert tuple(day_rules_reader.DAYS_WEEKDAY) == WEEKDAY_DAYS
    assert tuple(day_rules_reader.DAYS_WEEKEND) == WEEKEND_DAYS
    assert day_pairs.DAY_ORDER == DAY_ORDER
    assert DEFAULT_NIGHT_DAYS == (*WEEKDAY_DAYS, SUNDAY)
    assert readiness.DEFAULT_NIGHT_DAYS == list(DEFAULT_NIGHT_DAYS)
    assert CONFLICT_DEFAULT_NIGHT_DAYS == DEFAULT_NIGHT_DAYS


def test_adjacent_day_pairs_use_canonical_calendar_order() -> None:
    assert adjacent_day_pairs(["星期三", "星期一", "星期二"]) == [("星期一", "星期二"), ("星期二", "星期三")]
    assert adjacent_day_pairs([SUNDAY, "星期一"]) == [(SUNDAY, "星期一")]


def test_calendar_rank_and_previous_day_are_canonical() -> None:
    assert day_rank("星期一") == 1
    assert day_rank(SATURDAY) == 6
    assert day_rank("未知") == 99
    assert previous_day("星期一") == SUNDAY
    assert previous_day(SATURDAY) == "星期五"
    assert previous_day("未知") is None


def test_day_night_bridge_scope_tracks_enabled_weekend_night_days() -> None:
    assert SATURDAY not in day_night_bridge_days([SUNDAY])
    assert SUNDAY in day_night_bridge_days([SUNDAY])
    assert SATURDAY in day_night_bridge_days([SATURDAY, SUNDAY])


def test_day_night_bridge_collects_saturday_day_vars_when_saturday_night_exists() -> None:
    model = cp_model.CpModel()
    sat_pm = Slot(SATURDAY, "下午", 1)
    data = DayInputData(
        classes=["1班"],
        cls_subj_teacher={("1班", "数学"): "T"},
        available_slots=[sat_pm],
        fixed_assign={},
        req_hours={("1班", "数学"): (0, 0, 1)},
        subject_ban_slots={},
    )
    day_vars = build_day_variables(model, data)
    bridge = build_bridge_vars(
        model,
        data,
        day_vars,
        {"all_teachers": ["T"], "on_teacher_day": {}, "checkin_m": {}, "checkin_f": {}},
        {"days": [SATURDAY]},
    )

    model.Add(day_vars.x[("1班", "数学", sat_pm)] == 1)
    model.Add(bridge["day_has_pm"][("T", SATURDAY)] == 0)

    status = cp_model.CpSolver().Solve(model)
    assert status == cp_model.INFEASIBLE
