# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

from ai_orchestrated_optimization import create_existing_cp_model, solve_existing_cp_model
from scheduler.data.day_rules_reader import DayInputData, Slot
from scheduler.model.day_variables import build_day_variables
from scheduler.model.constraints.day_hard_one_per_slot import apply_one_subject_per_slot
from scheduler.day_constraints_morning_reading import (
    apply_morning_reading_constraints,
    extract_morning_reading_results,
    check_morning_reading_inputs,
    write_morning_reading_diagnostic,
)
from scheduler.output_paths import project_output_dir


def build_min_data() -> DayInputData:
    classes = ["1班", "2班"]
    cls_subj_teacher = {
        ("1班", "语文"): "T1",
        ("1班", "英语"): "T2",
        ("1班", "数学"): "T5",
        ("2班", "语文"): "T3",
        ("2班", "英语"): "T4",
        ("2班", "数学"): "T6",
    }
    slots = []
    for day in ("星期一", "星期二", "星期三", "星期四"):
        slots.append(Slot(day=day, block="早自习", period=1))

    req_hours = {
        ("1班", "语文"): (0, 0, 0),
        ("1班", "英语"): (0, 0, 0),
        ("1班", "数学"): (0, 0, 0),
        ("2班", "语文"): (0, 0, 0),
        ("2班", "英语"): (0, 0, 0),
        ("2班", "数学"): (0, 0, 0),
    }

    return DayInputData(
        classes=classes,
        cls_subj_teacher=cls_subj_teacher,
        available_slots=slots,
        fixed_assign={},
        req_hours=req_hours,
        subject_ban_slots={},
    )


def main():
    data = build_min_data()
    model = create_existing_cp_model("scheduler.day_morning_reading_smoke")
    dv = build_day_variables(model, data)
    apply_one_subject_per_slot(model, data, dv)

    ctx, errs = check_morning_reading_inputs(data)
    if errs:
        write_morning_reading_diagnostic(project_output_dir(), ctx, "INVALID_INPUT", errors=errs)
        raise ValueError("; ".join(errs))

    apply_morning_reading_constraints(model, data, dv)

    solve_result = solve_existing_cp_model(model)
    solver = solve_result.solver
    status_name = solve_result.status_name
    print("status=", status_name)

    results = extract_morning_reading_results(data, dv, solver)
    write_morning_reading_diagnostic(project_output_dir(), ctx, status_name, results=results)

    for cls in data.classes:
        row = results.get(cls, {})
        print(
            cls,
            "周一=", row.get("星期一"),
            "周二=", row.get("星期二"),
            "周三=", row.get("星期三"),
            "周四=", row.get("星期四"),
        )


if __name__ == "__main__":
    main()
