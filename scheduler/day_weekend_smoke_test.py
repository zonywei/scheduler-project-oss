# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

from ai_orchestrated_optimization import create_existing_cp_model, solve_existing_cp_model
from scheduler.data.day_rules_reader import DayInputData, Slot
from scheduler.model.day_variables import build_day_variables
from scheduler.model.constraints.day_hard_one_per_slot import apply_one_subject_per_slot
from scheduler.model.constraints.day_weekend_constraints import (
    apply_weekend_subject_whitelist,
    apply_weekend_double_period_same_class,
    apply_weekend_one_day_only,
    apply_weekend_cross_halfday_penalty,
    check_weekend_feasibility_inputs,
    write_weekend_diagnostic,
)
from scheduler.output_paths import project_output_dir


def _build_min_data(req_we: int) -> DayInputData:
    classes = ["1班", "2班"]
    subjects = ["数学", "物理"]
    cls_subj_teacher = {
        ("1班", "数学"): "T1",
        ("1班", "物理"): "T1",
        ("2班", "数学"): "T2",
        ("2班", "物理"): "T2",
    }

    # 仅周六上午两节
    slots = [
        Slot(day="星期六", block="上午", period=1),
        Slot(day="星期六", block="上午", period=2),
    ]

    fixed_assign = {}
    subject_ban_slots = {}

    req_hours = {}
    for cls in classes:
        for subj in subjects:
            req_hours[(cls, subj)] = (0, 0, req_we)

    return DayInputData(
        classes=classes,
        cls_subj_teacher=cls_subj_teacher,
        available_slots=slots,
        fixed_assign=fixed_assign,
        req_hours=req_hours,
        subject_ban_slots=subject_ban_slots,
    )


def case_feasible():
    data = _build_min_data(req_we=2)
    model = create_existing_cp_model("scheduler.day_weekend_smoke")
    dv = build_day_variables(model, data)
    apply_one_subject_per_slot(model, data, dv)
    apply_weekend_subject_whitelist(model, data, dv)
    apply_weekend_double_period_same_class(model, data, dv)
    apply_weekend_one_day_only(model, data, dv)
    apply_weekend_cross_halfday_penalty(model, data, dv, 200)

    solve_result = solve_existing_cp_model(model)
    status_name = solve_result.status_name
    print("case_feasible status=", status_name)

    diag = check_weekend_feasibility_inputs(data)
    write_weekend_diagnostic(project_output_dir(), diag, status_name, [])


def case_odd_warning():
    classes = ["1班"]
    subjects = ["数学"]
    cls_subj_teacher = {
        ("1班", "数学"): "T1",
    }
    slots = [
        Slot(day="星期六", block="上午", period=1),
        Slot(day="星期六", block="上午", period=2),
    ]
    data = DayInputData(
        classes=classes,
        cls_subj_teacher=cls_subj_teacher,
        available_slots=slots,
        fixed_assign={},
        req_hours={("1班", "数学"): (0, 0, 1)},
        subject_ban_slots={},
    )
    diag = check_weekend_feasibility_inputs(data)
    if diag.teacher_weekend_hours_odd:
        print("case_odd_warning ok: odd teachers=", diag.teacher_weekend_hours_odd)
    else:
        print("case_odd_warning FAILED: no odd teacher detected")


def main():
    project_output_dir().mkdir(parents=True, exist_ok=True)
    case_feasible()
    case_odd_warning()


if __name__ == "__main__":
    main()
