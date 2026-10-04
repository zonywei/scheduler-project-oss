# -*- coding: utf-8 -*-
"""教师定位表的共享结构推断。

教师定位表是一个宽表：第一列提供班级，其他非结构列就是用户实际提供的
学科/任课教师关系。这里不维护学校学科名单，也不把班主任字段当作课程
排课的必需字段；班主任和性别只在对应的值班/查寝模块具备数据时使用。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd


ROW_INDEX_COLUMN = "row_index"
DEFAULT_CLASS_COLUMN = "班级"
DEFAULT_HEAD_COLUMN = "班主任"
DEFAULT_HEAD_GENDER_COLUMN = "班主任性别"


def configured_teacher_table_columns(io_cfg: dict[str, Any] | None = None) -> tuple[str, str, str]:
    """返回结构列配置；班主任和性别名称只是可选元数据列。"""
    teacher_cfg = (io_cfg or {}).get("teacher_table", {})
    columns = teacher_cfg.get("columns", {}) if isinstance(teacher_cfg, dict) else {}
    columns = columns if isinstance(columns, dict) else {}
    return (
        _header(columns.get("class"), DEFAULT_CLASS_COLUMN),
        _header(columns.get("head"), DEFAULT_HEAD_COLUMN),
        _header(columns.get("head_gender"), DEFAULT_HEAD_GENDER_COLUMN),
    )


def normalize_header(value: Any) -> str:
    """清理 Excel/CSV 表头中的 BOM 和首尾空白。"""
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).replace("\ufeff", "").strip()


def normalize_teacher_table_frame(df: pd.DataFrame) -> pd.DataFrame:
    """复制并规范教师定位表表头，拒绝会造成数据丢失的重复表头。"""
    if not isinstance(df, pd.DataFrame):
        return pd.DataFrame()

    frame = df.copy()
    headers = [normalize_header(value) for value in frame.columns]
    blank_headers = [index + 1 for index, header in enumerate(headers) if not header]
    if blank_headers:
        raise ValueError("教师定位表存在空列名：第 " + ", ".join(map(str, blank_headers)) + " 列")
    duplicates = sorted({header for header in headers if headers.count(header) > 1})
    if duplicates:
        raise ValueError("教师定位表存在重复列名：" + "、".join(duplicates))
    frame.columns = headers
    return frame


def teacher_subject_columns(
    columns: Any,
    *,
    class_col: str = DEFAULT_CLASS_COLUMN,
    head_col: str = DEFAULT_HEAD_COLUMN,
    gender_col: str = DEFAULT_HEAD_GENDER_COLUMN,
) -> list[str]:
    """从实际表头推断学科列，保持用户表格中的列顺序。"""
    structural = {
        ROW_INDEX_COLUMN,
        normalize_header(class_col),
        normalize_header(head_col),
        normalize_header(gender_col),
        # 兼容默认中文结构列，即使调用方配置了别名，也不误当成学科。
        DEFAULT_CLASS_COLUMN,
        DEFAULT_HEAD_COLUMN,
        DEFAULT_HEAD_GENDER_COLUMN,
    }
    result: list[str] = []
    values = [] if columns is None else list(columns)
    for raw in values:
        column = normalize_header(raw)
        if column and column not in structural and column not in result:
            result.append(column)
    return result


def load_teacher_table_frame(io_cfg: dict[str, Any], base_dir: Path) -> pd.DataFrame:
    """优先读取 Web 保存的表格，否则读取物理 Excel 文件。"""
    web_rows = (((io_cfg.get("web_tables", {}) or {}).get("teacher_subjects")) or [])
    if isinstance(web_rows, list) and web_rows:
        return normalize_teacher_table_frame(
            pd.DataFrame([row for row in web_rows if isinstance(row, dict)])
        )

    teacher_cfg = io_cfg.get("teacher_table", {}) or {}
    path = Path(str(teacher_cfg.get("path") or "教师定位表.xlsx"))
    if not path.is_absolute():
        path = (base_dir / path).resolve()
    if not path.exists():
        return pd.DataFrame()
    return normalize_teacher_table_frame(
        pd.read_excel(path, sheet_name=teacher_cfg.get("sheet_name", 0))
    )


def head_gender_pools(
    df: pd.DataFrame,
    *,
    head_col: str = DEFAULT_HEAD_COLUMN,
    gender_col: str = DEFAULT_HEAD_GENDER_COLUMN,
    strict_gender: bool = True,
) -> tuple[list[str], list[str]]:
    """从可选班主任元数据中读取男女候选池。"""
    if df.empty or head_col not in df.columns or gender_col not in df.columns:
        return [], []

    male: list[str] = []
    female: list[str] = []
    for _, row in df.iterrows():
        head = _cell_text(row.get(head_col, ""))
        gender = _cell_text(row.get(gender_col, ""))
        if not head:
            continue
        if gender == "男":
            male.append(head)
        elif gender == "女":
            female.append(head)
        elif strict_gender and gender:
            raise ValueError(f"班主任性别必须为 男/女：班主任={head} 性别={gender}")
    return sorted(set(male)), sorted(set(female))


def _header(value: Any, fallback: str) -> str:
    text = normalize_header(value)
    return text or fallback


def _cell_text(value: Any) -> str:
    if pd.isna(value):
        return ""
    return str(value).strip()
