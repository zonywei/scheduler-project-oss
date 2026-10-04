from __future__ import annotations

import sys
from pathlib import Path

from ortools.sat.python import cp_model


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


from scheduler.data.day_rules_reader import DayInputData, Slot
from scheduler.model.constraints.day_head_teacher_duty_constraints import (
    HeadDutyConfig,
    write_head_duty_infeasible_hints,
)
from scheduler.model.constraints.day_weekday_constraints import (
    WeekdayConfig,
    write_day_infeasible_hints,
)


def test_day_infeasible_hints_hide_disabled_core_blockers(tmp_path: Path) -> None:
    write_day_infeasible_hints(
        tmp_path,
        WeekdayConfig(
            enable_binding_chem_bio=False,
            enable_head_pm1_min=False,
            enable_no_am1_am4=False,
        ),
    )

    text = (tmp_path / "day_infeasible_hints.txt").read_text(encoding="utf-8")
    assert "8班化学与9班生物跨班绑定" not in text
    assert "工作日下午第一节班主任人数下限" not in text
    assert "上午1与上午4同教师禁排" not in text
    assert "已关闭当前已知白天核心硬阻断" in text


def test_head_duty_infeasible_hints_hide_softened_pm1_gate(tmp_path: Path) -> None:
    model = cp_model.CpModel()
    data = DayInputData(
        classes=[],
        cls_subj_teacher={},
        available_slots=[Slot("星期一", "下午", 1), Slot("星期六", "下午", 1)],
        fixed_assign={},
        req_hours={},
        subject_ban_slots={},
    )

    write_head_duty_infeasible_hints(
        tmp_path,
        data,
        head_teachers=["甲", "乙", "丙"],
        teach_pm1={("甲", "星期一"): model.NewBoolVar("pm1")},
        floor_groups={"3F": ["甲"], "4F": ["乙"], "5F": ["丙"]},
        cfg=HeadDutyConfig(weekday_pm1_requires_duty_mode="soft"),
    )

    text = (tmp_path / "head_duty_infeasible_hints.txt").read_text(encoding="utf-8")
    assert "每天每楼层=1 与 非周六 duty<=pm1" not in text
    assert "已将非周六 duty<=pm1 降为软约束" in text
