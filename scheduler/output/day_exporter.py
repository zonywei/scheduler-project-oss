# -*- coding: utf-8 -*-
from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, Tuple, List

import pandas as pd
from ortools.sat.python import cp_model

from scheduler.data.day_rules_reader import DayInputData, Slot
from scheduler.model.day_variables import DayVars
from scheduler.output.excel_writer import create_excel_writer

logger = logging.getLogger(__name__)


def _slot_col_name(slot: Slot) -> str:
    # 统一列名格式：星期X_早自习1 / 星期X_上午2 / 星期X_下午4
    return f"{slot.day}_{slot.block}{slot.period}"


def export_day_schedule_df(data: DayInputData, dv: DayVars, solver: cp_model.CpSolver) -> pd.DataFrame:
    """
    输出白天课表 DataFrame：
    行=班级；列=slot；值=学科(教师) 或 固定槽(自习/班会)
    """
    # 1) 先确定所有列（按时间顺序）
    # 你 data.available_slots 已经是全局可排槽（包含早自习/上午/下午），我们按它排序输出列
    # ===== 人类可读的时间排序 =====
    day_order = {
    "星期一": 1, "星期二": 2, "星期三": 3,
    "星期四": 4, "星期五": 5,
    "星期六": 6, "星期日": 7,
    }
    block_order = {"早自习": 0, "上午": 1, "下午": 2}

    sorted_slots = sorted(
    data.available_slots,
    key=lambda s: (
        day_order.get(s.day, 99),
        block_order.get(s.block, 99),
        int(s.period),
    )
    )

    cols = [_slot_col_name(s) for s in sorted_slots]


    # 2) 建空表
    df = pd.DataFrame(index=data.classes, columns=cols, dtype=object)

    # 3) 先填固定槽
    for (cls, slot), subj in data.fixed_assign.items():
        df.loc[cls, _slot_col_name(slot)] = subj

    # 4) 再填求解结果（x=1 的学科）
    # dv.x 的 key 是 (cls, subj, slot)
    for (cls, subj, slot), var in dv.x.items():
        if solver.Value(var) == 1:
            teacher = data.cls_subj_teacher.get((cls, subj), "")
            cell = f"{subj}({teacher})" if teacher else subj
            df.loc[cls, _slot_col_name(slot)] = cell

    # 5) 最后做一个简单完整性检查：是否还有空
    # （允许固定槽和决策槽都填满后应无空）
    # 若你未来允许空课，再把这里放宽
    empties = df.isna().sum().sum()
    if empties != 0:
        logger.warning("导出表仍有空单元格数量=%s（可能是允许空槽，或固定槽列不在 available_slots）", empties)

    return df


def save_day_schedule_excel(
    wide_df: pd.DataFrame,
    grid_dfs: Dict[str, pd.DataFrame],
    out_path: str
) -> None:
    """
    保存 Excel：
    - Sheet1：白天课表_宽表
    - Sheet2+：每个班一个网格课表
    """
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    with create_excel_writer(out_path) as writer:
        wide_df.to_excel(writer, sheet_name="白天课表_宽表")

        for cls, gdf in grid_dfs.items():
            # sheet 名不能太长
            sheet_name = cls if len(cls) <= 31 else cls[:31]
            gdf.to_excel(writer, sheet_name=sheet_name)


def export_day_schedule_grid_df(data: DayInputData, dv: DayVars, solver: cp_model.CpSolver) -> Dict[str, pd.DataFrame]:
    """
    返回一个 dict：
    {
        班级名: DataFrame(行=节次, 列=星期)
    }
    """
    # 固定顺序
    days = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
    periods = [
        ("早自习", 1),
        ("上午", 1), ("上午", 2), ("上午", 3), ("上午", 4),
        ("下午", 1), ("下午", 2), ("下午", 3), ("下午", 4),
    ]

    # 先把解整理成 dict： (cls, day, block, period) -> 内容
    value_map = {}

    # 固定课位
    for (cls, slot), subj in data.fixed_assign.items():
        value_map[(cls, slot.day, slot.block, slot.period)] = subj

    # 求解结果
    for (cls, subj, slot), var in dv.x.items():
        if solver.Value(var) == 1:
            teacher = data.cls_subj_teacher.get((cls, subj), "")
            cell = f"{subj}({teacher})" if teacher else subj
            value_map[(cls, slot.day, slot.block, slot.period)] = cell

    # 为每个班生成一个网格 DataFrame
    grids = {}
    for cls in data.classes:
        df = pd.DataFrame(
            index=[f"{b}{p}" for b, p in periods],
            columns=days,
            dtype=object,
        )

        for (b, p) in periods:
            for d in days:
                df.loc[f"{b}{p}", d] = value_map.get((cls, d, b, p), "")

        grids[cls] = df

    return grids
