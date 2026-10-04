# -*- coding: utf-8 -*-
"""
What：教师同槽不冲突（hard）。
Why：同一教师同一时段不可在多个班级出现。
How：对 x 按(教师,Slot)聚合，约束 sum <= 1。
Diagnostics：无专用报告（由可行性与硬约束检查间接体现）。
"""
from __future__ import annotations
from collections import defaultdict
from ortools.sat.python import cp_model

from scheduler.data.day_rules_reader import DayInputData, Slot
from scheduler.model.day_variables import DayVars


def apply_teacher_no_conflict(model: cp_model.CpModel, data: DayInputData, dv: DayVars) -> None:
    """
    同一时间槽，同一位老师最多只能在一个班上课（硬约束）
    """

    # 反向索引：teacher -> list of (cls, subj)
    pairs_by_teacher = defaultdict(list)
    for (cls, subj), teacher in data.cls_subj_teacher.items():
        pairs_by_teacher[teacher].append((cls, subj))

    # 对每个 slot，按 teacher 聚合当槽相关变量
    # teacher_slot_vars[(teacher, slot)] = [x[cls,subj,slot], ...]
    teacher_slot_vars = defaultdict(list)

    for (cls, subj, slot), var in dv.x.items():
        teacher = data.cls_subj_teacher.get((cls, subj))
        # 理论上一定存在；为了稳健加一层保护
        if teacher is None:
            continue
        teacher_slot_vars[(teacher, slot)].append(var)

    # 加约束：sum <= 1
    for (teacher, slot), vars_list in teacher_slot_vars.items():
        if len(vars_list) <= 1:
            continue
        model.Add(sum(vars_list) <= 1)
