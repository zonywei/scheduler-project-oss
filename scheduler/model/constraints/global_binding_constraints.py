# -*- coding: utf-8 -*-
"""全局跨班绑定约束。

本模块只承载需要跨白天/周末/晚自习统一生效的绑定类硬约束。
"""
from __future__ import annotations

import logging
from typing import Any

from ortools.sat.python import cp_model

from scheduler.data.day_rules_reader import DayInputData, Slot
from scheduler.model.day_variables import DayVars

logger = logging.getLogger(__name__)


def _find_class(classes: list[str], marker: str) -> str | None:
    matches = [c for c in classes if marker in str(c)]
    return matches[0] if matches else None


def _day_slot_expr(data: DayInputData, dv: DayVars, cls: str, subj: str, slot: Slot) -> Any:
    if (cls, slot) in data.fixed_assign:
        return 1 if data.fixed_assign[(cls, slot)] == subj else 0
    vars_list = [v for (c, s, sl), v in dv.x.items() if c == cls and s == subj and sl == slot]
    return sum(vars_list)


def apply_global_day_binding_8_chem_9_bio(
    model: cp_model.CpModel,
    data: DayInputData,
    dv: DayVars,
) -> None:
    """白天全局硬约束：8班化学与9班生物在所有白天可排时段同步。

    范围包含周一到周日的 available_slots；不再把周六、周日排除在外。
    """
    c8 = _find_class(data.classes, "8班")
    c9 = _find_class(data.classes, "9班")
    if not c8 or not c9:
        logger.warning("未找到8班或9班，跳过白天全局8化学-9生物绑定约束")
        return

    for slot in data.available_slots:
        left = _day_slot_expr(data, dv, c8, "化学", slot)
        right = _day_slot_expr(data, dv, c9, "生物", slot)
        model.Add(left == right)


def apply_global_night_binding_8_chem_9_bio(
    model: cp_model.CpModel,
    vars: dict,
    ctx: dict,
    rules: dict | None = None,
) -> None:
    """晚自习全局硬约束：8班化学与9班生物同天同节次绑定。"""
    if ((rules or {}).get("global_binding") or {}).get("enable_8_chem_9_bio", True) is False:
        return
    y = vars.get("y", {})
    classes = ctx.get("classes", []) or []
    cst = ctx.get("cst", {}) or {}
    days = ctx.get("days", []) or []
    periods = ctx.get("periods", []) or []

    c8 = _find_class(classes, "8班")
    c9 = _find_class(classes, "9班")
    if not c8 or not c9:
        logger.warning("未找到8班或9班，跳过晚自习全局8化学-9生物绑定约束")
        return

    if (c8, "化学") not in cst or (c9, "生物") not in cst:
        logger.warning("8班化学或9班生物不在晚自习学科映射中，跳过全局绑定约束")
        return

    for d in days:
        for p in periods:
            key8 = (c8, "化学", d, p)
            key9 = (c9, "生物", d, p)
            if key8 not in y or key9 not in y:
                continue
            model.Add(y[key8] == y[key9])
