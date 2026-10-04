# -*- coding: utf-8 -*-
"""
What：白天学科课时守恒（hard）。
Why：满足需求表中早自习/周中/周末课时配额。
How：对 x 按(班级,学科)聚合，分别约束早自习/周中/周末总量。
Diagnostics：无专用报告（由可行性与硬约束检查间接体现）。
"""
from __future__ import annotations
from ortools.sat.python import cp_model

from scheduler.data.day_rules_reader import DayInputData, Slot
from scheduler.model.day_variables import DayVars
from scheduler.calendar import is_weekday_day


def apply_subject_hour_constraints(
    model: cp_model.CpModel,
    data: DayInputData,
    dv: DayVars,
) -> None:
    """
    对每个 (班级, 学科)，约束其在：
    - 早自习
    - 周中（周一~周五，非早自习）
    - 周末（周六~周日，非早自习）
    的上课次数，必须等于需求表给定的课时数
    """

    for (cls, subj), (req_e, req_w, req_we) in data.req_hours.items():

        vars_early = []
        vars_weekday = []
        vars_weekend = []

        for (c, s, slot), var in dv.x.items():
            if c != cls or s != subj:
                continue

            # 早自习
            if slot.block == "早自习":
                vars_early.append(var)

            # 周一~周五（非早自习）
            elif is_weekday_day(slot.day):
                vars_weekday.append(var)

            # 周六~周日（非早自习）
            else:
                vars_weekend.append(var)

        # 三段分别加等式约束
        model.Add(sum(vars_early) == req_e)
        model.Add(sum(vars_weekday) == req_w)
        model.Add(sum(vars_weekend) == req_we)
