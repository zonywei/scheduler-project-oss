# -*- coding: utf-8 -*-
"""
What：晚自习教师硬约束模块。
Why：防止教师同一时段分身，并限制单周晚自习出勤天数上限。
How：基于 `y[(班级,学科,日,节)]` 与 `on_teacher_day[(教师,日)]` 添加线性硬约束。
Diagnostics：违例会直接导致模型不可行，由上层统一输出不可行提示。
"""
# model/constraints/hard_teacher_limits.py
"""
教师层面的硬约束（必须满足，否则不可行）：

T1：老师不能分身
    同一老师在同一天同一节晚自习，最多只能在一个班出现。

T2：每位老师一周内最多上 2 天晚自习（你提出的硬制度）
"""

def apply_hard_teacher_limits(model, vars, ctx, rules):
    """晚自习教师硬约束入口。

    变量口径：
    - y[(班级,学科,日,节)]：晚自习主变量。
    - on_teacher_day：教师当天是否上晚自习的布尔量。
    """
    y = vars["y"]
    on = vars.get("on_teacher_day", {})
    days = ctx["days"]
    periods = ctx["periods"]
    cst = ctx["cst"]

    # -----------------------------
    # T1：老师不能分身（同天同节最多一个班）
    # -----------------------------
    # 为每个 (teacher, day, period) 汇总相关 y 变量
    tdp_map = {}  # (tch, d, p) -> [y vars...]
    for (cls, subj), tch in cst.items():
        for d in days:
            for p in periods:
                tdp_map.setdefault((tch, d, p), []).append(y[(cls, subj, d, p)])

    for (tch, d, p), L in tdp_map.items():
        if len(L) >= 2:
            model.Add(sum(L) <= 1)  # 同一老师同一时段最多一个班

    # -----------------------------
    # T2：每位老师一周内最多上 2 天晚自习
    # -----------------------------
    # 注意：on_teacher_day 是由 y 推出来的（你变量模块已经绑定好了）
    # 这里直接限制 sum_d on(t,d) <= 2
    for tch in set(cst.values()):
        # 如果该老师没有 on 变量（理论上不会），跳过
        L = [on[(tch, d)] for d in days if (tch, d) in on]
        if L:
            model.Add(sum(L) <= 2)
