# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Dict, Tuple, Optional

from openpyxl.cell.rich_text import CellRichText, TextBlock, InlineFont
from ortools.sat.python import cp_model

from scheduler.data.day_rules_reader import DayInputData, Slot
from scheduler.model.day_variables import DayVars
from scheduler.output.constants import FONT_SIMHEI, FONT_KAITI

EveningAssign = Dict[Tuple[str, str, int], Tuple[str, str]]
CheckinRows = list[dict[str, str]]


def build_evening_assign_from_solver(y, solver, teacher_map) -> EveningAssign:
    """
    返回：
    {(cls, day, ep): (subject, teacher)}
    """
    m: EveningAssign = {}
    for (cls, subj, day, ep), var in y.items():
        if solver.Value(var) == 1:
            teacher = teacher_map.get((cls, subj), "")
            m[(cls, day, ep)] = (subj, teacher)
    return m


def build_checkin_rows_from_solver(
    checkin_m: dict,
    checkin_f: dict,
    days: list[str],
    male_heads: list[str],
    female_heads: list[str],
    solver: cp_model.CpSolver,
) -> CheckinRows:
    """从晚自习查寝变量提取“日期/男晚查寝/女晚查寝”行数据。"""
    rows: CheckinRows = []
    for day in days:
        male = ""
        female = ""
        for tch in male_heads:
            var = checkin_m.get((tch, day))
            if var is not None and solver.Value(var) == 1:
                male = tch
                break
        for tch in female_heads:
            var = checkin_f.get((tch, day))
            if var is not None and solver.Value(var) == 1:
                female = tch
                break
        rows.append({"日期": day, "男晚查寝": male, "女晚查寝": female})
    return rows


def _rt_two_lines(top_text: str, bottom_text: str) -> CellRichText:
    """
    一格两行不同字体：
    - 上：黑体11加粗
    - 下：楷体11
    """
    rt = CellRichText()
    rt.append(TextBlock(InlineFont(rFont=FONT_SIMHEI, b=False, sz=11), top_text))
    rt.append(TextBlock(InlineFont(rFont=FONT_KAITI, sz=11), "\n" + bottom_text))
    return rt


def _rt_single_line(text: str) -> CellRichText:
    """
    单行富文本：黑体 11（用于 自习 / 班会 等固定课位）
    """
    rt = CellRichText()
    rt.append(
        TextBlock(
            InlineFont(rFont=FONT_SIMHEI, sz=11),
            text
        )
    )
    return rt


def _rt_subject_only(text: str) -> CellRichText:
    """
    单行富文本：仅学科（黑体11）
    """
    rt = CellRichText()
    rt.append(
        TextBlock(
            InlineFont(rFont=FONT_SIMHEI, sz=11),
            text
        )
    )
    return rt


def _slot_key(cls: str, day: str, block: str, period: int):
    return (cls, day, block, period)


def _format_class_name(cls: str, grade_prefix: Optional[str]) -> str:
    if not grade_prefix:
        return cls
    for token in ("高一", "高二", "高三", "高四"):
        if token in cls:
            return cls
    if cls.startswith(grade_prefix):
        return cls
    return f"{grade_prefix}{cls}"


def build_class_value_map(
    data: DayInputData,
    dv: DayVars,
    solver: cp_model.CpSolver,
    evening_assign: Optional[EveningAssign] = None,
    summary_mode: bool = False,
) -> Dict[Tuple[str, str, str, int], object]:
    """
    (cls, day, block, period) -> 单元格值
    固定：自习/班会（普通字符串）
    非固定：CellRichText（学科黑体，教师楷体）
    """
    m: Dict[Tuple[str, str, str, int], object] = {}

    for (cls, slot), subj in data.fixed_assign.items():
        m[_slot_key(cls, slot.day, slot.block, int(slot.period))] = _rt_single_line(str(subj))

    for (cls, subj, slot), var in dv.x.items():
        if solver.Value(var) == 1:
            teacher = data.cls_subj_teacher.get((cls, subj), "")
            if teacher:
                if summary_mode:
                    m[_slot_key(cls, slot.day, slot.block, int(slot.period))] = _rt_subject_only(subj)
                else:
                    m[_slot_key(cls, slot.day, slot.block, int(slot.period))] = _rt_two_lines(subj, teacher)
            else:
                m[_slot_key(cls, slot.day, slot.block, int(slot.period))] = subj

    if evening_assign:
        for (cls, day, ep), (subj, teacher) in evening_assign.items():
            # ep=1/2 对应 晚自习1/2
            if summary_mode:
                cell = _rt_subject_only(subj)
            else:
                if teacher:
                    cell = _rt_two_lines(subj, teacher)
                else:
                    cell = subj
            m[_slot_key(cls, day, "晚自习", int(ep))] = cell

    return m


def build_teacher_value_map(
    data: DayInputData,
    dv: DayVars,
    solver: cp_model.CpSolver,
    evening_assign: Optional[EveningAssign] = None,
    grade_prefix: Optional[str] = None,
) -> Dict[Tuple[str, str, int], object]:
    """
    (teacher, day, idx_1to11) -> CellRichText（学科黑体，班级楷体）
    """
    def idx_from_slot(slot: Slot) -> int:
        if slot.block == "早自习":
            return 1
        if slot.block == "上午":
            return 1 + int(slot.period)      # 上午1->2 ... 上午4->5
        if slot.block == "下午":
            return 5 + int(slot.period)      # 下午1->6 ... 下午4->9
        raise ValueError(f"未知block: {slot.block}")

    m: Dict[Tuple[str, str, int], object] = {}
    for (cls, subj, slot), var in dv.x.items():
        if solver.Value(var) != 1:
            continue
        teacher = data.cls_subj_teacher.get((cls, subj))
        if not teacher:
            continue
        idx = idx_from_slot(slot)
        cls_display = _format_class_name(cls, grade_prefix)
        m[(teacher, slot.day, idx)] = _rt_two_lines(subj, cls_display)

    if evening_assign:
        for (cls, day, ep), (subj, teacher) in evening_assign.items():
            if not teacher:
                continue
            idx = 9 + int(ep)  # 晚自习1/2 -> 第10/11节
            cls_display = _format_class_name(cls, grade_prefix)
            m[(teacher, day, idx)] = _rt_two_lines(subj, cls_display)
    return m
