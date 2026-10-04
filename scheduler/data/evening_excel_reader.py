# -*- coding: utf-8 -*-
from __future__ import annotations

import re
from typing import Dict, Optional, Tuple

import pandas as pd

EveningAssign = Dict[Tuple[str, str, int], Tuple[str, str]]
CheckinRows = list[dict[str, str]]


def _norm_str(x) -> str:
    if pd.isna(x):
        return ""
    return str(x).strip()


def _parse_day_col(col: str) -> Optional[Tuple[str, int]]:
    """解析“星期几(.0/.1)”列名，返回 (day, evening_period=1/2)。"""
    col = _norm_str(col)
    if not col or col in ("班级", "学科"):
        return None
    if "." in col:
        day, suffix = col.split(".", 1)
        day = _norm_str(day)
        try:
            period = int(_norm_str(suffix)) + 1
        except ValueError:
            return None
        return day, period
    return col, 1


def _split_subject_teacher(text: str) -> Tuple[str, str]:
    """解析单元格内容“学科-教师”或“学科(教师)”。"""
    text = _norm_str(text)
    if not text:
        return "", ""
    m = re.match(r"^(.+?)[-—–](.+)$", text)
    if m:
        return _norm_str(m.group(1)), _norm_str(m.group(2))
    m = re.match(r"^(.+?)\((.+)\)$", text)
    if m:
        return _norm_str(m.group(1)), _norm_str(m.group(2))
    return text, ""


def _read_first_available_sheet(xlsx_path: str, names: list[str]) -> pd.DataFrame:
    last_err = None
    for name in names:
        try:
            return pd.read_excel(xlsx_path, sheet_name=name)
        except Exception as exc:
            last_err = exc
    if last_err is not None:
        raise last_err
    raise ValueError("未找到可读取的 sheet")


def _pick_column(columns: list[str], exact: list[str], contains: list[str]) -> Optional[str]:
    for key in exact:
        if key in columns:
            return key
    for col in columns:
        if any(token in col for token in contains):
            return col
    return None


def read_evening_assignments(xlsx_path: str, sheet_name: str = "排课") -> EveningAssign:
    """读取晚自习排课 sheet，返回 {(class, day, period): (subject, teacher)}。"""
    df = _read_first_available_sheet(xlsx_path, [sheet_name, "排课"])
    columns = [_norm_str(c) for c in df.columns]
    class_col = _pick_column(columns, ["班级"], ["班级"])
    if not class_col:
        raise ValueError(f"[{sheet_name}] 缺少列：班级")

    col_map: Dict[str, Tuple[str, int]] = {}
    for col in columns:
        parsed = _parse_day_col(col)
        if parsed:
            col_map[col] = parsed

    assigns: EveningAssign = {}
    for _, row in df.iterrows():
        cls = _norm_str(row.get(class_col, ""))
        if not cls:
            continue
        for col, (day, period) in col_map.items():
            subj, teacher = _split_subject_teacher(row.get(col, ""))
            if not subj:
                continue
            assigns[(cls, day, period)] = (subj, teacher)
    return assigns


def read_evening_checkin_rows(xlsx_path: str, sheet_name: str = "晚查寝安排") -> CheckinRows:
    """读取晚自习结果中的“晚查寝安排”sheet。"""
    df = _read_first_available_sheet(xlsx_path, [sheet_name, "晚查寝安排", "查寝安排"])
    columns = [_norm_str(c) for c in df.columns]
    day_key = _pick_column(columns, ["日期"], ["日期", "星期"])
    male_key = _pick_column(columns, ["男晚查寝", "男查寝"], ["男晚查寝", "男查寝"])
    female_key = _pick_column(columns, ["女晚查寝", "女查寝"], ["女晚查寝", "女查寝"])
    if not day_key or not male_key or not female_key:
        raise ValueError(f"[{sheet_name}] 缺少列：日期/男晚查寝/女晚查寝")

    rows: CheckinRows = []
    for _, row in df.iterrows():
        day = _norm_str(row.get(day_key, ""))
        if not day:
            continue
        rows.append(
            {
                "日期": day,
                "男晚查寝": _norm_str(row.get(male_key, "")),
                "女晚查寝": _norm_str(row.get(female_key, "")),
            }
        )
    return rows
