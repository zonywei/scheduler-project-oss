# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Dict, Tuple, Optional

from openpyxl.styles import Alignment, Font, Border
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.pagebreak import Break

from .constants import (
    COL_WIDTH,
    ROW_HEIGHT,
    BLOCK_GAP_ROWS,
    BLOCKS_PER_PAGE,
    DAYS,
    CLASS_PERIODS,
    TEACHER_PERIODS,
    DAY_COLS,
    TITLE_COL_L,
    TITLE_COL_R,
    FONT_SIMHEI,
    THIN,
    THICK,
)

BORDER_THIN = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
ALIGN_CENTER_WRAP = Alignment(horizontal="center", vertical="center", wrap_text=True)

FONT_TITLE = Font(name=FONT_SIMHEI, size=16, bold=True)
FONT_HDR = Font(name=FONT_SIMHEI, size=11, bold=True)
FONT_TAG = Font(name=FONT_SIMHEI, size=11, bold=True)
_WEEKEND_DAYS = {"星期六", "星期日"}


def apply_diagonal_corner_header(
    ws,
    row: int,
    col: int,
    text_top_right: str = "星期",
    text_bottom_left: str = "节次",
    diag: str = "\\",
):
    """
    Render diagonal corner header without image:
    - keep the merged corner region
    - add diagonal border
    - place two labels as two lines with stable offsets
    """
    anchor_cell = ws.cell(row=row, column=col)
    b = anchor_cell.border
    diagonal_down = (diag != "/")
    anchor_cell.border = Border(
        left=b.left,
        right=b.right,
        top=b.top,
        bottom=b.bottom,
        diagonal=THIN,
        diagonalDown=diagonal_down,
        diagonalUp=not diagonal_down,
    )
    # Use full-width spaces to push the first line near top-right and keep
    # the second line near bottom-left in a merged 2x2 corner cell.
    pad = "　" * 4
    bottom_pad = " " * 4
    anchor_cell.value = f"{pad}{text_top_right}\n{bottom_pad}{text_bottom_left}"
    anchor_cell.font = FONT_HDR
    anchor_cell.alignment = Alignment(
        horizontal="left",
        vertical="center",
        wrap_text=True,
    )


def setup_a4_page(ws):
    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    ws.page_setup.orientation = ws.ORIENTATION_PORTRAIT
    ws.page_setup.fitToPage = False


def apply_page_breaks(ws, block_rows: int, block_count: int):
    if block_count <= BLOCKS_PER_PAGE:
        return
    step = block_rows + BLOCK_GAP_ROWS
    for i in range(1, block_count + 1):
        if i % BLOCKS_PER_PAGE != 0:
            continue
        if i == block_count:
            break
        next_start_row = 1 + i * step
        ws.row_breaks.append(Break(id=next_start_row))


def set_global_size(ws, max_row: int):
    # 全局列宽（A~Q）
    for c in range(1, 18):
        ws.column_dimensions[get_column_letter(c)].width = COL_WIDTH
    # 全局行高
    for r in range(1, max_row + 1):
        ws.row_dimensions[r].height = ROW_HEIGHT


def _merge(ws, r1, c1, r2, c2):
    ws.merge_cells(start_row=r1, start_column=c1, end_row=r2, end_column=c2)


def _apply_cell_style(cell, font: Font | None = None, border: Border | None = None):
    cell.alignment = ALIGN_CENTER_WRAP
    if font is not None:
        cell.font = font
    if border is not None:
        cell.border = border


def _write_merged(ws, r1, c1, r2, c2, value, font: Font | None, border: Border | None):
    _merge(ws, r1, c1, r2, c2)
    tl = ws.cell(r1, c1, value=value)
    _apply_cell_style(tl, font=font, border=border)
    # 合并区域内其它格子也铺样式（保证黑框不断）
    for r in range(r1, r2 + 1):
        for c in range(c1, c2 + 1):
            cc = ws.cell(r, c)
            _apply_cell_style(cc, font=font, border=border)


def _draw_outer_border(ws, r1, c1, r2, c2):
    """
    给一个矩形区域画“外框粗线、内框细线”
    我们假设内框已经是 thin，这里只覆盖四周边框为 thick。
    """
    def _set_border_keep_diag(cell, *, left=None, right=None, top=None, bottom=None):
        b = cell.border
        cell.border = Border(
            left=b.left if left is None else left,
            right=b.right if right is None else right,
            top=b.top if top is None else top,
            bottom=b.bottom if bottom is None else bottom,
            diagonal=b.diagonal,
            diagonalUp=b.diagonalUp,
            diagonalDown=b.diagonalDown,
            diagonal_direction=getattr(b, "diagonal_direction", None),
            outline=b.outline,
            vertical=b.vertical,
            horizontal=b.horizontal,
            start=b.start,
            end=b.end,
        )

    for c in range(c1, c2 + 1):
        # top
        cell = ws.cell(r1, c)
        _set_border_keep_diag(cell, top=THICK)
        # bottom
        cell = ws.cell(r2, c)
        _set_border_keep_diag(cell, bottom=THICK)

    for r in range(r1, r2 + 1):
        # left
        cell = ws.cell(r, c1)
        _set_border_keep_diag(cell, left=THICK)
        # right
        cell = ws.cell(r, c2)
        _set_border_keep_diag(cell, right=THICK)


def _write_block_common_header(ws, top_row: int, title: str):
    """
    标题（两行合并，黑体16，无边框）
    表头（星期/节次/周一..周日，黑体11，有细框）
    """
    # 1) 标题：无框线
    _write_merged(ws, top_row, TITLE_COL_L, top_row + 1, TITLE_COL_R, title, font=FONT_TITLE, border=None)

    # 2) 表头：两行
    hdr_r = top_row + 2

    # “星期/节次”这个斜线格子你截图是对角线，我们不强行画斜线（Excel可做但文本定位难）
    _write_merged(ws, hdr_r, 2, hdr_r + 1, 3, "", font=FONT_HDR, border=BORDER_THIN)
    apply_diagonal_corner_header(ws, row=hdr_r, col=2, text_top_right="星期", text_bottom_left="节次", diag="\\")

    for d in DAYS:
        c1, c2 = DAY_COLS[d]
        day_short = d.replace("星期", "周")
        _write_merged(ws, hdr_r, c1, hdr_r + 1, c2, day_short, font=FONT_HDR, border=BORDER_THIN)


def write_class_block(
    ws,
    start_row: int,
    cls: str,
    title: str,
    vmap: Dict[Tuple[str, str, str, int], object],
):
    """
    每个班块高度固定（标题2行+表头2行+每节2行）。
    """
    _write_block_common_header(ws, start_row, title)

    # 内容起始行
    r = start_row + 4

    # 逐节写：每节占 2 行、每个星期占 2 列
    for block, p, label in CLASS_PERIODS:

        # 1) 早餐：整行横向合并 B~Q，两行高（格式与午休一致）
        if block == "早餐":
            _write_merged(ws, r, 2, r + 1, 17, "早餐", font=FONT_TAG, border=BORDER_THIN)

        # 2) 午间休息：整行横向合并 B~Q，两行高
        elif block == "午休":
            _write_merged(ws, r, 2, r + 1, 17, "午休", font=FONT_TAG, border=BORDER_THIN)

        # 3) 下午到晚自习之间：整行横向合并
        elif block == "晚休":
            _write_merged(ws, r, 2, r + 1, 17, "晚餐", font=FONT_TAG, border=BORDER_THIN)

        # 4) 正常节次：左侧节次名 + 周一到周日填课
        else:
            _write_merged(ws, r, 2, r + 1, 3, label, font=FONT_TAG, border=BORDER_THIN)

            for d in DAYS:
                c1, c2 = DAY_COLS[d]
                val = vmap.get((cls, d, block, p), "")
                _write_merged(ws, r, c1, r + 1, c2, "", font=None, border=BORDER_THIN)
                ws.cell(r, c1).value = val
                ws.cell(r, c1).alignment = ALIGN_CENTER_WRAP

        # 每个“节块”写完后，统一推进 2 行
        r += 2

    # 给块的表格区域画外框粗线（不包含标题）
    table_top = start_row + 2
    table_bottom = start_row + 3 + len(CLASS_PERIODS) * 2
    _draw_outer_border(ws, table_top, 2, table_bottom, 17)


def write_teacher_block(ws, start_row: int, teacher: str, tmap: Dict[Tuple[str, str, int], object]):
    _write_block_common_header(ws, start_row, f"{teacher}课表")

    r = start_row + 4
    for block, p, lab in TEACHER_PERIODS:
        if block in ("早餐", "午休", "晚休"):
            _write_merged(ws, r, 2, r + 1, 17, lab, font=FONT_TAG, border=BORDER_THIN)
            r += 2
            continue

        _write_merged(ws, r, 2, r + 1, 3, lab, font=FONT_TAG, border=BORDER_THIN)
        for d in DAYS:
            c1, c2 = DAY_COLS[d]
            val = tmap.get((teacher, d, p), "")
            _write_merged(ws, r, c1, r + 1, c2, "", font=None, border=BORDER_THIN)
            ws.cell(r, c1).value = val
            ws.cell(r, c1).alignment = ALIGN_CENTER_WRAP
        r += 2

    table_top = start_row + 2
    table_bottom = start_row + 3 + len(TEACHER_PERIODS) * 2
    _draw_outer_border(ws, table_top, 2, table_bottom, 17)


def write_class_block_display_adjusted(
    ws,
    start_row: int,
    cls: str,
    title: str,
    vmap: Dict[Tuple[str, str, str, int], object],
):
    _write_block_common_header(ws, start_row, title)
    r = start_row + 4

    def _write_period_row(label: str, value_getter):
        nonlocal r
        _write_merged(ws, r, 2, r + 1, 3, label, font=FONT_TAG, border=BORDER_THIN)
        for d in DAYS:
            c1, c2 = DAY_COLS[d]
            val = value_getter(d)
            _write_merged(ws, r, c1, r + 1, c2, "", font=None, border=BORDER_THIN)
            ws.cell(r, c1).value = val
            ws.cell(r, c1).alignment = ALIGN_CENTER_WRAP
            if val == "自习":
                ws.cell(r, c1).font = Font(name=FONT_SIMHEI, size=11)
        r += 2

    _write_period_row("早自习", lambda d: vmap.get((cls, d, "早自习", 1), ""))
    _write_merged(ws, r, 2, r + 1, 17, "早餐", font=FONT_TAG, border=BORDER_THIN)
    r += 2
    _write_period_row("上午1", lambda d: vmap.get((cls, d, "上午", 1), ""))
    _write_period_row("上午2", lambda d: vmap.get((cls, d, "上午", 2), ""))
    _write_period_row("上午3", lambda d: vmap.get((cls, d, "上午", 3), "") if d not in _WEEKEND_DAYS else "自习")
    _write_period_row("上午4", lambda d: "自习" if d not in _WEEKEND_DAYS else vmap.get((cls, d, "上午", 3), ""))
    _write_period_row("上午5", lambda d: vmap.get((cls, d, "上午", 4), ""))

    _write_merged(ws, r, 2, r + 1, 17, "午休", font=FONT_TAG, border=BORDER_THIN)
    r += 2
    _write_period_row("下午1", lambda d: vmap.get((cls, d, "下午", 1), ""))
    _write_period_row("下午2", lambda d: vmap.get((cls, d, "下午", 2), ""))
    _write_period_row("下午3", lambda d: vmap.get((cls, d, "下午", 3), ""))
    _write_period_row("下午4", lambda d: vmap.get((cls, d, "下午", 4), ""))
    _write_merged(ws, r, 2, r + 1, 17, "晚餐", font=FONT_TAG, border=BORDER_THIN)
    r += 2
    _write_period_row("晚自习1", lambda d: vmap.get((cls, d, "晚自习", 1), ""))
    _write_period_row("晚自习2", lambda d: vmap.get((cls, d, "晚自习", 2), ""))

    table_top = start_row + 2
    table_bottom = start_row + 3 + (len(CLASS_PERIODS) + 1) * 2
    _draw_outer_border(ws, table_top, 2, table_bottom, 17)


def write_teacher_block_display_adjusted(
    ws,
    start_row: int,
    teacher: str,
    tmap: Dict[Tuple[str, str, int], object],
):
    _write_block_common_header(ws, start_row, f"{teacher}课表")
    r = start_row + 4

    def _write_period_row(label: str, value_getter):
        nonlocal r
        _write_merged(ws, r, 2, r + 1, 3, label, font=FONT_TAG, border=BORDER_THIN)
        for d in DAYS:
            c1, c2 = DAY_COLS[d]
            val = value_getter(d)
            _write_merged(ws, r, c1, r + 1, c2, "", font=None, border=BORDER_THIN)
            ws.cell(r, c1).value = val
            ws.cell(r, c1).alignment = ALIGN_CENTER_WRAP
        r += 2

    _write_period_row("早自习", lambda d: tmap.get((teacher, d, 1), ""))
    _write_merged(ws, r, 2, r + 1, 17, "早餐", font=FONT_TAG, border=BORDER_THIN)
    r += 2
    _write_period_row("上午1", lambda d: tmap.get((teacher, d, 2), ""))
    _write_period_row("上午2", lambda d: tmap.get((teacher, d, 3), ""))
    _write_period_row("上午3", lambda d: tmap.get((teacher, d, 4), "") if d not in _WEEKEND_DAYS else "")
    _write_period_row("上午4", lambda d: "" if d not in _WEEKEND_DAYS else tmap.get((teacher, d, 4), ""))
    _write_period_row("上午5", lambda d: tmap.get((teacher, d, 5), ""))

    _write_merged(ws, r, 2, r + 1, 17, "午休", font=FONT_TAG, border=BORDER_THIN)
    r += 2
    _write_period_row("下午1", lambda d: tmap.get((teacher, d, 6), ""))
    _write_period_row("下午2", lambda d: tmap.get((teacher, d, 7), ""))
    _write_period_row("下午3", lambda d: tmap.get((teacher, d, 8), ""))
    _write_period_row("下午4", lambda d: tmap.get((teacher, d, 9), ""))
    _write_merged(ws, r, 2, r + 1, 17, "晚餐", font=FONT_TAG, border=BORDER_THIN)
    r += 2
    _write_period_row("晚自习1", lambda d: tmap.get((teacher, d, 10), ""))
    _write_period_row("晚自习2", lambda d: tmap.get((teacher, d, 11), ""))

    table_top = start_row + 2
    table_bottom = start_row + 3 + (len(TEACHER_PERIODS) + 1) * 2
    _draw_outer_border(ws, table_top, 2, table_bottom, 17)
