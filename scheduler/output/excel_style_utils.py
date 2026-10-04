# -*- coding: utf-8 -*-
from __future__ import annotations

import math
import unicodedata
from typing import Iterable, Sequence

from openpyxl.cell.cell import MergedCell
from openpyxl.formatting.rule import CellIsRule, FormulaRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.page import PageMargins
from openpyxl.worksheet.pagebreak import Break
from openpyxl.worksheet.worksheet import Worksheet

THIN_SIDE = Side(style="thin", color="000000")
MEDIUM_SIDE = Side(style="medium", color="000000")

THIN_BORDER = Border(left=THIN_SIDE, right=THIN_SIDE, top=THIN_SIDE, bottom=THIN_SIDE)
HEADER_FILL = PatternFill(fill_type="solid", fgColor="EAF2FF")
HIGHLIGHT_FILL = PatternFill(fill_type="solid", fgColor="FFF2CC")
UNMET_FILL = PatternFill(fill_type="solid", fgColor="F8CBAD")
TITLE_FILL = PatternFill(fill_type="solid", fgColor="E2F0D9")

LONG_TEXT_KEYWORDS = (
    "解释",
    "说明",
    "模块",
    "路径",
    "原因",
    "教师名单",
    "名单",
    "备注",
    "项目",
)

KEY_COL_KEYWORDS = ("解ID", "序号", "分类")


def _is_wide_char(ch: str) -> bool:
    return unicodedata.east_asian_width(ch) in ("W", "F")


def _text_width(value: object) -> int:
    s = "" if value is None else str(value)
    max_line = 0
    for line in s.splitlines() or [""]:
        width = 0
        for ch in line:
            width += 2 if _is_wide_char(ch) else 1
        max_line = max(max_line, width)
    return max_line


def _max_data_col(ws: Worksheet) -> int:
    m = 1
    for row in ws.iter_rows(min_row=1, max_row=ws.max_row, min_col=1, max_col=ws.max_column):
        for c in row:
            if c.value not in (None, ""):
                m = max(m, c.column)
    return m


def _is_writable_cell(ws: Worksheet, row: int, col: int) -> bool:
    return not isinstance(ws.cell(row=row, column=col), MergedCell)


def _resolve_freeze(ws: Worksheet, freeze_panes: str | None) -> str | None:
    if freeze_panes in (None, ""):
        return None
    if freeze_panes != "auto":
        return freeze_panes
    head = str(ws.cell(row=1, column=1).value or "")
    if any(k in head for k in KEY_COL_KEYWORDS):
        return "B2"
    return "A2"


def autosize_columns(
    ws: Worksheet,
    sample_rows: int = 200,
    min_width: float = 8.0,
    max_width: float = 60.0,
    fixed_width_cols: dict[int, float] | None = None,
) -> None:
    max_col = _max_data_col(ws)
    max_row = min(ws.max_row, sample_rows)
    fixed = fixed_width_cols or {}

    for col in range(1, max_col + 1):
        if col in fixed:
            ws.column_dimensions[get_column_letter(col)].width = float(fixed[col])
            continue
        width = _text_width(ws.cell(row=1, column=col).value)
        for row in range(2, max_row + 1):
            width = max(width, _text_width(ws.cell(row=row, column=col).value))
        width = max(min_width, min(max_width, width * 0.9 + 2))
        ws.column_dimensions[get_column_letter(col)].width = float(width)


def autosize_rows_for_wrapped_cells(
    ws: Worksheet,
    wrap_cols: Iterable[int],
    header_row: int = 1,
    base_height: float = 19.0,
    max_height: float = 120.0,
) -> None:
    wrap_cols = list(set(int(c) for c in wrap_cols))
    ws.row_dimensions[header_row].height = max(base_height + 2, 21.0)

    for row in range(header_row + 1, ws.max_row + 1):
        max_lines = 1
        for col in wrap_cols:
            if col > ws.max_column:
                continue
            if not _is_writable_cell(ws, row, col):
                continue
            text = str(ws.cell(row=row, column=col).value or "")
            if not text:
                continue
            width = ws.column_dimensions[get_column_letter(col)].width or 10.0
            est_line_chars = max(1.0, width - 1.0)
            line_cnt = 0
            for line in text.splitlines() or [""]:
                line_cnt += max(1, math.ceil(_text_width(line) / est_line_chars))
            max_lines = max(max_lines, line_cnt)
        ws.row_dimensions[row].height = min(max_height, base_height * max_lines)


def apply_table_style(
    ws: Worksheet,
    header_row: int = 1,
    freeze_panes: str | None = "auto",
    zoom: int = 115,
    sample_rows: int = 200,
    min_width: float = 8.0,
    max_width: float = 60.0,
) -> None:
    max_col = _max_data_col(ws)
    max_row = ws.max_row
    if max_row < header_row or max_col < 1:
        return

    ws.sheet_view.showGridLines = False
    ws.sheet_view.zoomScale = zoom
    freeze = _resolve_freeze(ws, freeze_panes)
    if freeze:
        ws.freeze_panes = freeze

    for col in range(1, max_col + 1):
        if not _is_writable_cell(ws, header_row, col):
            continue
        cell = ws.cell(row=header_row, column=col)
        cell.font = Font(bold=True)
        cell.fill = HEADER_FILL
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

    if max_row >= header_row + 1:
        ws.auto_filter.ref = f"{get_column_letter(1)}{header_row}:{get_column_letter(max_col)}{max_row}"

    wrap_cols: list[int] = []
    fixed_cols: dict[int, float] = {}
    for col in range(1, max_col + 1):
        head = str(ws.cell(row=header_row, column=col).value or "")
        if any(k in head for k in LONG_TEXT_KEYWORDS):
            wrap_cols.append(col)
            fixed_cols[col] = 48.0 if "模块" in head or "路径" in head else 40.0

    # 边框：先全部 thin，再覆盖外框 medium
    for row in range(header_row, max_row + 1):
        for col in range(1, max_col + 1):
            if not _is_writable_cell(ws, row, col):
                continue
            ws.cell(row=row, column=col).border = THIN_BORDER

    for col in range(1, max_col + 1):
        if _is_writable_cell(ws, header_row, col):
            c = ws.cell(row=header_row, column=col)
            c.border = Border(left=c.border.left, right=c.border.right, top=MEDIUM_SIDE, bottom=c.border.bottom)
        if _is_writable_cell(ws, max_row, col):
            c = ws.cell(row=max_row, column=col)
            c.border = Border(left=c.border.left, right=c.border.right, top=c.border.top, bottom=MEDIUM_SIDE)
    for row in range(header_row, max_row + 1):
        if _is_writable_cell(ws, row, 1):
            c = ws.cell(row=row, column=1)
            c.border = Border(left=MEDIUM_SIDE, right=c.border.right, top=c.border.top, bottom=c.border.bottom)
        if _is_writable_cell(ws, row, max_col):
            c = ws.cell(row=row, column=max_col)
            c.border = Border(left=c.border.left, right=MEDIUM_SIDE, top=c.border.top, bottom=c.border.bottom)

    for row in range(header_row + 1, max_row + 1):
        for col in wrap_cols:
            if col > max_col or not _is_writable_cell(ws, row, col):
                continue
            cell = ws.cell(row=row, column=col)
            cell.alignment = Alignment(horizontal=cell.alignment.horizontal or "left", vertical="top", wrap_text=True)

    autosize_columns(
        ws,
        sample_rows=sample_rows,
        min_width=min_width,
        max_width=max_width,
        fixed_width_cols=fixed_cols if fixed_cols else None,
    )
    autosize_rows_for_wrapped_cells(ws, wrap_cols=wrap_cols, header_row=header_row)


def apply_conditional_format_for_diagnostics(ws: Worksheet, header_row: int = 1) -> None:
    if ws.max_row <= header_row:
        return
    max_col = _max_data_col(ws)
    max_row = ws.max_row

    for col in range(1, max_col + 1):
        head = str(ws.cell(row=header_row, column=col).value or "")
        col_letter = get_column_letter(col)
        data_ref = f"{col_letter}{header_row + 1}:{col_letter}{max_row}"

        if "罚分" in head:
            ws.conditional_formatting.add(
                data_ref,
                CellIsRule(operator="greaterThan", formula=["0"], fill=HIGHLIGHT_FILL),
            )
        if "次数" in head:
            ws.conditional_formatting.add(
                data_ref,
                CellIsRule(operator="greaterThan", formula=["0"], fill=HIGHLIGHT_FILL),
            )
        if "是否满足" in head:
            ws.conditional_formatting.add(
                data_ref,
                FormulaRule(
                    formula=[
                        f'OR({col_letter}{header_row + 1}="否",{col_letter}{header_row + 1}="未满足")'
                    ],
                    fill=UNMET_FILL,
                ),
            )


def apply_block_outline(
    ws: Worksheet,
    block_ranges: Sequence[tuple[int, int, int, int]],
    title_rows: Sequence[int] | None = None,
) -> None:
    for r1, c1, r2, c2 in block_ranges:
        for row in range(r1, r2 + 1):
            for col in range(c1, c2 + 1):
                if not _is_writable_cell(ws, row, col):
                    continue
                ws.cell(row=row, column=col).border = THIN_BORDER
        for col in range(c1, c2 + 1):
            if _is_writable_cell(ws, r1, col):
                c = ws.cell(row=r1, column=col)
                c.border = Border(left=c.border.left, right=c.border.right, top=MEDIUM_SIDE, bottom=c.border.bottom)
            if _is_writable_cell(ws, r2, col):
                c = ws.cell(row=r2, column=col)
                c.border = Border(left=c.border.left, right=c.border.right, top=c.border.top, bottom=MEDIUM_SIDE)
        for row in range(r1, r2 + 1):
            if _is_writable_cell(ws, row, c1):
                c = ws.cell(row=row, column=c1)
                c.border = Border(left=MEDIUM_SIDE, right=c.border.right, top=c.border.top, bottom=c.border.bottom)
            if _is_writable_cell(ws, row, c2):
                c = ws.cell(row=row, column=c2)
                c.border = Border(left=c.border.left, right=MEDIUM_SIDE, top=c.border.top, bottom=c.border.bottom)

    for row in title_rows or []:
        for col in range(1, _max_data_col(ws) + 1):
            if not _is_writable_cell(ws, row, col):
                continue
            cell = ws.cell(row=row, column=col)
            cell.font = Font(bold=True)
            cell.fill = TITLE_FILL
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)


def set_a4_portrait_print_layout(
    ws: Worksheet,
    fit_to_width: int = 1,
    fit_to_height: int = 0,
    margin_cm: float = 1.5,
) -> None:
    margin_inch = margin_cm / 2.54
    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    ws.page_setup.orientation = ws.ORIENTATION_PORTRAIT
    ws.page_setup.fitToPage = True
    ws.page_setup.fitToWidth = fit_to_width
    ws.page_setup.fitToHeight = fit_to_height
    ws.page_margins = PageMargins(
        left=margin_inch,
        right=margin_inch,
        top=margin_inch,
        bottom=margin_inch,
        header=0.3,
        footer=0.3,
    )
    ws.print_area = f"A1:{get_column_letter(_max_data_col(ws))}{ws.max_row}"


def set_teacher_schedule_print_layout(
    ws: Worksheet,
    block_height_rows: int,
    block_gap_rows: int = 0,
    blocks_per_page: int = 2,
    first_block_start_row: int = 1,
    block_count: int | None = None,
) -> None:
    """
    老师课表分页策略：
    - 每位老师块高度固定（block_height_rows）
    - 块间固定空白（block_gap_rows）
    - 每页固定 blocks_per_page 个块
    - 在“下一页第一块起始行”插入水平分页符，避免老师块跨页
    """
    set_a4_portrait_print_layout(ws, fit_to_width=1, fit_to_height=0, margin_cm=1.4)
    ws.sheet_view.showGridLines = False
    ws.sheet_view.zoomScale = 115

    step = block_height_rows + block_gap_rows
    if step <= 0:
        return
    if block_count is None:
        usable_rows = max(0, ws.max_row - first_block_start_row + 1)
        block_count = math.ceil(usable_rows / step) if usable_rows else 0

    ws.row_breaks.brk = []
    for i in range(blocks_per_page, block_count, blocks_per_page):
        next_start_row = first_block_start_row + i * step
        ws.row_breaks.append(Break(id=next_start_row))
