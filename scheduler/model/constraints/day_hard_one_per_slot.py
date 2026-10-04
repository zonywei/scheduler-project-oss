# -*- coding: utf-8 -*-
"""
What：每班每槽唯一学科（hard）。
Why：避免同一班级同一时段出现多科或空缺。
How：对 x 按(班级,时段)聚合，强制 sum == 1。
Diagnostics：无专用报告（由模型可行性与硬约束检查间接体现）。
"""
from __future__ import annotations
from ortools.sat.python import cp_model

from scheduler.data.day_rules_reader import DayInputData
from scheduler.model.day_variables import DayVars


def apply_one_subject_per_slot(model: cp_model.CpModel, data: DayInputData, dv: DayVars) -> None:
    """
    对每个非固定槽：同一班同一槽恰好安排一门主科学科
    （固定槽不建变量，因此不在这里约束）
    """
    for (cls, slot), vars_list in dv.xs_by_cls_slot.items():
        # vars_list 为空说明该槽被禁排到没有候选，这种情况直接让模型不可行更好
        if not vars_list:
            raise ValueError(f"{cls} 在 {slot.day}{slot.block}{slot.period} 没有任何可排学科候选（数据或禁排规则有问题）")
        model.Add(sum(vars_list) == 1)
