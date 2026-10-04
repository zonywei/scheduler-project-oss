# -*- coding: utf-8 -*-
from __future__ import annotations

import logging
import shutil
from copy import copy
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Tuple

from openpyxl import Workbook, load_workbook
from openpyxl.cell.cell import MergedCell
from openpyxl.styles import Alignment, Border, Font, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.pagebreak import Break
from ortools.sat.python import cp_model

from scheduler.data.day_rules_reader import DayInputData
from scheduler.model.day_variables import DayVars
from scheduler.output.value_maps import (
    EveningAssign,
    CheckinRows,
    build_class_value_map,
    build_teacher_value_map,
    build_evening_assign_from_solver,
    _format_class_name,
)
from scheduler.output.layout_writer import (
    CLASS_PERIODS,
    TEACHER_PERIODS,
    BLOCK_GAP_ROWS,
    TITLE_COL_L,
    TITLE_COL_R,
    setup_a4_page,
    apply_page_breaks,
    set_global_size,
    write_class_block,
    write_teacher_block,
    write_class_block_display_adjusted,
    write_teacher_block_display_adjusted,
)
from scheduler.output.constants import (
    SHEET_CLASS,
    SHEET_DAY_SUMMARY,
    SHEET_TEACHER,
    SHEET_DUTY_SUMMARY,
    SHEET_GRADE_DUTY_RESOURCE,
    SHEET_HEAD_TIMETABLE,
    SHEET_NIGHT_TIMETABLE,
    DAYS,
)
from scheduler.output.excel_style_utils import (
    apply_block_outline,
    apply_table_style,
    set_a4_portrait_print_layout,
    set_teacher_schedule_print_layout,
)

SUBJECT_ORDER = ["语文", "数学", "外语", "物理", "化学", "生物", "历史", "地理", "政治", "体育", "技术"]
SUMMARY_TEACHER_TOP_BLANK_ROWS = 4
SUMMARY_TEACHER_BLOCK_GAP_ROWS = 8


__all__ = [
    "save_day_class_and_teacher_summary_excel",
    "build_evening_assign_from_solver",
    "EveningAssign",
]

logger = logging.getLogger(__name__)


def _apply_simhei_to_all_text_cells(ws) -> None:
    """
    白天课表_汇总版：把所有“有文字内容”的单元格字体族统一为 SimHei（黑体），保留字号/加粗等其它属性。
    只改样式层，不改数据、不改布局。
    """
    max_row = int(ws.max_row or 1)
    max_col = int(ws.max_column or 1)
    for r in range(1, max_row + 1):
        for c in range(1, max_col + 1):
            cell = ws.cell(row=r, column=c)
            if isinstance(cell, MergedCell):
                continue
            v = cell.value
            if v is None or v == "":
                continue
            f = copy(cell.font)
            f.name = "SimHei"
            cell.font = f


def _apply_fixed_page_breaks_18x76(ws, rows_per_page: int = 76) -> None:
    """Only touches print pagination (page breaks / fit-to-page)."""
    target_cols_per_page = 18
    target_rows_per_page = int(rows_per_page)
    cols_per_page = target_cols_per_page
    rows_per_page = target_rows_per_page

    # Clear existing breaks first (some sheets already add block-based breaks).
    ws.row_breaks.brk = []
    ws.col_breaks.brk = []

    max_col = int(ws.max_column or 1)
    max_row = int(ws.max_row or 1)
    print_max_col = max(max_col, target_cols_per_page)

    # Keep a stable visible width in print preview: force print area to at least 18 columns.
    # This avoids merged-cell value anchors causing print_area to stop at column P (16 cols).
    if print_max_col > max_col:
        base_width = ws.column_dimensions[get_column_letter(max_col)].width or 8.11
        for col in range(max_col + 1, print_max_col + 1):
            ws.column_dimensions[get_column_letter(col)].width = base_width
        max_col = print_max_col
    ws.print_area = f"A1:{get_column_letter(max_col)}{max_row}"

    # Break ids are treated as "page ends" in Excel preview, so use
    # exact per-page boundaries (18/76) instead of +1 start offsets.
    for col in range(cols_per_page, max_col, cols_per_page):
        ws.col_breaks.append(Break(id=col))

    for row in range(rows_per_page, max_row, rows_per_page):
        ws.row_breaks.append(Break(id=row))

    # Recommended: keep width fixed, allow multi-page height.
    try:
        ws.page_setup.fitToPage = True
        ws.page_setup.fitToWidth = 1
        ws.page_setup.fitToHeight = 0
    except AttributeError:
        # Some loaded workbooks may miss pageSetUpPr; pagination still works via breaks + print_area.
        pass


def _apply_day_summary_block_font_sizes(ws, *, top_row: int) -> None:
    """Only adjusts fonts inside one class block in 白天课表_汇总版."""
    # Title (2 rows): 18pt bold
    for r in (top_row, top_row + 1):
        for c in range(int(TITLE_COL_L), int(TITLE_COL_R) + 1):
            cell = ws.cell(row=r, column=c)
            if isinstance(cell, MergedCell):
                continue
            f = copy(cell.font)
            f.size = 18
            f.bold = True
            cell.font = f

    # Table area (header + periods + values): 14pt, preserve existing bold flag.
    table_top = top_row + 2
    table_bottom = top_row + 3 + len(CLASS_PERIODS) * 2
    for r in range(table_top, table_bottom + 1):
        for c in range(int(TITLE_COL_L), int(TITLE_COL_R) + 1):
            cell = ws.cell(row=r, column=c)
            if isinstance(cell, MergedCell):
                continue
            f = copy(cell.font)
            f.size = 14
            cell.font = f


def _display_adjusted_path(out_path: Path) -> Path:
    return out_path.with_name(f"{out_path.stem}_显示节次调整版{out_path.suffix}")


def _should_export_display_adjusted(out_path: Path) -> bool:
    return "snapshots" not in {part.lower() for part in out_path.parts}


def _export_display_adjusted_workbook(
    out_path: Path,
    data: DayInputData,
    vmap_summary: Dict[Tuple[str, str, str, int], object],
    tmap: Dict[Tuple[str, str, int], object],
    teachers: list[str],
    grade_prefix: Optional[str],
) -> None:
    adjusted_path = _display_adjusted_path(out_path)
    target_path = adjusted_path
    try:
        shutil.copy2(out_path, target_path)
    except PermissionError:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        target_path = adjusted_path.with_name(f"{adjusted_path.stem}_{ts}{adjusted_path.suffix}")
        shutil.copy2(out_path, target_path)
        logger.warning("显示节次调整版目标文件被占用，改为新文件：%s", target_path.name)
    # Keep rich-text runs (subject/teacher dual-font cells) when round-tripping
    # the copied workbook, otherwise class-sheet cells may degrade to plain text.
    try:
        wb_adj = load_workbook(target_path, rich_text=True)
    except TypeError:
        # Compatibility fallback for older openpyxl versions without rich_text arg.
        wb_adj = load_workbook(target_path)

    if SHEET_DAY_SUMMARY in wb_adj.sheetnames:
        idx_s = wb_adj.sheetnames.index(SHEET_DAY_SUMMARY)
        del wb_adj[SHEET_DAY_SUMMARY]
    else:
        idx_s = len(wb_adj.sheetnames)
    ws_s = wb_adj.create_sheet(SHEET_DAY_SUMMARY, idx_s)
    setup_a4_page(ws_s)
    class_block_rows = 4 + (len(CLASS_PERIODS) + 1) * 2
    start = 1 + SUMMARY_TEACHER_TOP_BLANK_ROWS
    for i, cls in enumerate(data.classes):
        if i > 0:
            start += SUMMARY_TEACHER_BLOCK_GAP_ROWS
        cls_display = _format_class_name(cls, grade_prefix)
        write_class_block_display_adjusted(ws_s, start, cls, f"{cls_display}课表", vmap_summary)
        _apply_day_summary_block_font_sizes(ws_s, top_row=start)
        start += class_block_rows
    _apply_simhei_to_all_text_cells(ws_s)
    apply_page_breaks(ws_s, class_block_rows, len(data.classes))
    set_global_size(ws_s, max_row=start - 1)
    set_a4_portrait_print_layout(ws_s, fit_to_width=1, fit_to_height=0, margin_cm=1.4)
    _apply_fixed_page_breaks_18x76(ws_s, rows_per_page=84)

    if SHEET_TEACHER in wb_adj.sheetnames:
        idx_t = wb_adj.sheetnames.index(SHEET_TEACHER)
        del wb_adj[SHEET_TEACHER]
    else:
        idx_t = len(wb_adj.sheetnames)
    ws_t = wb_adj.create_sheet(SHEET_TEACHER, idx_t)
    setup_a4_page(ws_t)
    teacher_block_rows = 4 + (len(TEACHER_PERIODS) + 1) * 2
    start = 1 + SUMMARY_TEACHER_TOP_BLANK_ROWS
    for i, teacher in enumerate(teachers):
        if i > 0:
            start += SUMMARY_TEACHER_BLOCK_GAP_ROWS
        write_teacher_block_display_adjusted(ws_t, start, teacher, tmap)
        start += teacher_block_rows
    apply_page_breaks(ws_t, teacher_block_rows, len(teachers))
    set_global_size(ws_t, max_row=start - 1)
    set_teacher_schedule_print_layout(
        ws_t,
        block_height_rows=teacher_block_rows,
        block_gap_rows=BLOCK_GAP_ROWS,
        blocks_per_page=2,
        first_block_start_row=1,
        block_count=len(teachers),
    )
    _apply_fixed_page_breaks_18x76(ws_t, rows_per_page=84)

    try:
        wb_adj.save(target_path)
    except PermissionError:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        fallback = target_path.with_name(f"{target_path.stem}_{ts}{target_path.suffix}")
        wb_adj.save(fallback)
        logger.warning("显示节次调整版保存时文件被占用，改为新文件：%s", fallback.name)
        target_path = fallback
    logger.info("已导出显示节次调整版：%s", target_path.name)



def _build_night_sheet_rows(
    classes: list[str],
    days: list[str],
    evening_assign: EveningAssign,
) -> tuple[list[str], list[dict[str, str]]]:
    cols = ["班级"]
    for d in days:
        cols += [d, f"{d}.1"]

    rows: list[dict[str, str]] = []
    for cls in classes:
        row: dict[str, str] = {"班级": cls}
        for d in days:
            row[d] = ""
            row[f"{d}.1"] = ""
            for ep in (1, 2):
                subj, teacher = evening_assign.get((cls, d, ep), ("", ""))
                if subj or teacher:
                    col = d if ep == 1 else f"{d}.1"
                    row[col] = f"{subj}-{teacher}" if teacher else str(subj)
        rows.append(row)
    return cols, rows


def save_day_class_and_teacher_summary_excel(
    data: DayInputData,
    dv: DayVars,
    solver: cp_model.CpSolver,
    out_path: str,
    evening_assign: Optional[EveningAssign] = None,
    grade_prefix: Optional[str] = None,
    head_teachers: Optional[list[str]] = None,
    male_head_teachers: Optional[list[str]] = None,
    female_head_teachers: Optional[list[str]] = None,
    head_duty_result: Optional[dict[str, list[str]]] = None,
    duty_floor_vars: Optional[Dict[Tuple[str, str, str], cp_model.IntVar]] = None,
    head_floor_groups: Optional[dict[str, list[str]]] = None,
    checkin_rows: Optional[CheckinRows] = None,
    noon_dorm_rows: Optional[list[dict[str, str]]] = None,
    grade_group_duty_map: Optional[dict[str, str]] = None,
    grade_group_available_map: Optional[dict[str, str]] = None,
) -> None:
    """
    输出：
    - 班级课表（所有班堆叠在一个sheet）
    - 白天课表_汇总版（仅显示学科）
    - 老师课表（所有老师堆叠在一个sheet）
    - 班主任课表（男/女两块上下布局）
    - 查寝值班总表
    - 年级值班可用资源（复制查寝值班总表结构作为模板）
    - 如提供 evening_assign，则合并晚自习1/2
    并应用你指定的字体/线框/列宽/行高样式
    """
    wb = Workbook()
    wb.remove(wb.active)

    # 班级课表
    ws_c = wb.create_sheet(SHEET_CLASS)
    setup_a4_page(ws_c)
    vmap = build_class_value_map(data, dv, solver, evening_assign=evening_assign)

    class_block_rows = 4 + len(CLASS_PERIODS) * 2
    start = 1
    for cls in data.classes:
        cls_display = _format_class_name(cls, grade_prefix)
        write_class_block(ws_c, start, cls, f"{cls_display}课表", vmap)
        start += class_block_rows + BLOCK_GAP_ROWS
    apply_page_breaks(ws_c, class_block_rows, len(data.classes))
    set_global_size(ws_c, max_row=start - 1)

    # 白天课表_汇总版
    ws_s = wb.create_sheet(SHEET_DAY_SUMMARY)
    setup_a4_page(ws_s)
    vmap_summary = build_class_value_map(
        data,
        dv,
        solver,
        evening_assign=evening_assign,
        summary_mode=True,
    )

    start = 1 + SUMMARY_TEACHER_TOP_BLANK_ROWS
    for i, cls in enumerate(data.classes):
        if i > 0:
            start += SUMMARY_TEACHER_BLOCK_GAP_ROWS
        cls_display = _format_class_name(cls, grade_prefix)
        write_class_block(ws_s, start, cls, f"{cls_display}课表", vmap_summary)
        _apply_day_summary_block_font_sizes(ws_s, top_row=start)
        start += class_block_rows
    _apply_simhei_to_all_text_cells(ws_s)
    apply_page_breaks(ws_s, class_block_rows, len(data.classes))
    set_global_size(ws_s, max_row=start - 1)
    set_a4_portrait_print_layout(ws_s, fit_to_width=1, fit_to_height=0, margin_cm=1.4)

    # 老师课表
    ws_t = wb.create_sheet(SHEET_TEACHER)
    setup_a4_page(ws_t)
    tmap = build_teacher_value_map(
        data,
        dv,
        solver,
        evening_assign=evening_assign,
        grade_prefix=grade_prefix,
    )

    teachers = sorted({t for t in data.cls_subj_teacher.values() if t})
    subject_rank = {s: i for i, s in enumerate(SUBJECT_ORDER)}
    teacher_min_rank = {}
    for (cls, subj), teacher in data.cls_subj_teacher.items():
        if not teacher:
            continue
        rank = subject_rank.get(subj, len(SUBJECT_ORDER))
        teacher_min_rank[teacher] = min(teacher_min_rank.get(teacher, len(SUBJECT_ORDER)), rank)

    teachers = sorted(teachers, key=lambda t: (teacher_min_rank.get(t, len(SUBJECT_ORDER)), t))
    teacher_block_rows = 4 + len(TEACHER_PERIODS) * 2
    start = 1 + SUMMARY_TEACHER_TOP_BLANK_ROWS
    for i, t in enumerate(teachers):
        if i > 0:
            start += SUMMARY_TEACHER_BLOCK_GAP_ROWS
        write_teacher_block(ws_t, start, t, tmap)
        start += teacher_block_rows
    apply_page_breaks(ws_t, teacher_block_rows, len(teachers))
    set_global_size(ws_t, max_row=start - 1)
    set_teacher_schedule_print_layout(
        ws_t,
        block_height_rows=teacher_block_rows,
        block_gap_rows=BLOCK_GAP_ROWS,
        blocks_per_page=2,
        first_block_start_row=1,
        block_count=len(teachers),
    )

    # 晚自习课表（并入白天课表_汇总版文件，不再单独导出结果_MVP）
    if evening_assign:
        ws_n = wb.create_sheet(SHEET_NIGHT_TIMETABLE)
        night_cols, night_rows = _build_night_sheet_rows(data.classes, DAYS, evening_assign)
        ws_n.append(night_cols)
        for row in night_rows:
            ws_n.append([row.get(c, "") for c in night_cols])
        apply_table_style(ws_n, header_row=1, freeze_panes="A2", zoom=115)

    # 班主任课表（男/女分块，上下布局）
    male_head_teachers = male_head_teachers or []
    female_head_teachers = female_head_teachers or []
    ws_ht = wb.create_sheet(SHEET_HEAD_TIMETABLE)
    thin = Side(style="thin", color="000000")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    center = Alignment(horizontal="center", vertical="center", wrap_text=True)

    def _build_head_slot_map(heads: list[str]) -> Dict[Tuple[str, str, int], str]:
        head_set = set(heads or [])
        names_map: Dict[Tuple[str, str, int], set[str]] = {}
        if not head_set:
            return {}
        for (cls, subj, slot), var in dv.x.items():
            if solver.Value(var) != 1:
                continue
            teacher = data.cls_subj_teacher.get((cls, subj), "")
            if teacher in head_set:
                names_map.setdefault((slot.day, slot.block, int(slot.period)), set()).add(teacher)
        for (cls, slot), subj in data.fixed_assign.items():
            teacher = data.cls_subj_teacher.get((cls, subj), "")
            if teacher in head_set:
                names_map.setdefault((slot.day, slot.block, int(slot.period)), set()).add(teacher)
        # 补充晚自习（来自联合求解/晚自习结果），否则班主任课表的“晚自习1/2”会为空
        for (_cls, day, ep), (_subj, teacher) in (evening_assign or {}).items():
            if teacher in head_set:
                names_map.setdefault((str(day), "晚自习", int(ep)), set()).add(teacher)
        return {k: "，".join(sorted(v)) for k, v in names_map.items()}

    def _write_head_block(top_row: int, left_col: int, title: str, value_map: Dict[Tuple[str, str, int], str]) -> int:
        end_col = left_col + 7
        ws_ht.merge_cells(start_row=top_row, start_column=left_col, end_row=top_row, end_column=end_col)
        title_cell = ws_ht.cell(row=top_row, column=left_col, value=title)
        title_cell.font = Font(bold=True, size=14)
        title_cell.alignment = center
        title_cell.border = border
        for c in range(left_col, end_col + 1):
            ws_ht.cell(row=top_row, column=c).border = border

        headers = ["节次"] + DAYS
        for i, h in enumerate(headers):
            c = left_col + i
            cell = ws_ht.cell(row=top_row + 1, column=c, value=h)
            cell.font = Font(bold=True)
            cell.alignment = center
            cell.border = border

        r = top_row + 2
        for block, p, label in CLASS_PERIODS:
            l_cell = ws_ht.cell(row=r, column=left_col, value=label)
            l_cell.alignment = center
            l_cell.border = border
            l_cell.font = Font(bold=True) if block in ("早餐", "午休", "晚休") else Font(bold=False)
            if block in ("早餐", "午休", "晚休"):
                ws_ht.merge_cells(start_row=r, start_column=left_col + 1, end_row=r, end_column=end_col)
                c0 = ws_ht.cell(row=r, column=left_col + 1, value=label)
                c0.alignment = center
                c0.border = border
                for c in range(left_col + 1, end_col + 1):
                    ws_ht.cell(row=r, column=c).border = border
            else:
                for i, d in enumerate(DAYS):
                    c = left_col + 1 + i
                    cell = ws_ht.cell(row=r, column=c, value=value_map.get((d, block, int(p)), ""))
                    cell.alignment = center
                    cell.border = border
            r += 1
        return r - 1

    male_map = _build_head_slot_map(male_head_teachers)
    female_map = _build_head_slot_map(female_head_teachers)
    male_start_row = 1
    male_end_row = _write_head_block(male_start_row, 1, "男班主任课表", male_map)
    head_block_gap_rows = 3
    female_start_row = male_end_row + head_block_gap_rows + 1
    female_end_row = _write_head_block(female_start_row, 1, "女班主任课表", female_map)
    last_row_ht = female_end_row
    for c in range(1, 9):
        col = get_column_letter(c)
        ws_ht.column_dimensions[col].width = 10
    for r in range(1, last_row_ht + 1):
        ws_ht.row_dimensions[r].height = 20

    # 查寝值班总表（聚合：巡视 + 中午查寝 + 晚查寝）
    ws_h = wb.create_sheet(SHEET_DUTY_SUMMARY)
    ws_h.merge_cells("A1:I1")
    ws_h["A1"] = "查寝值班总表"
    ws_h["A1"].font = Font(bold=True, size=16)
    ws_h["A1"].alignment = Alignment(horizontal="center", vertical="center")

    header = ["值班项目", "值班区域", "星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
    ws_h.append(header)

    floors: list[str] = []
    if head_floor_groups:
        floors = list(head_floor_groups.keys())
    if not floors and duty_floor_vars:
        floors = sorted({f for (_t, _d, f) in duty_floor_vars.keys()})
    if not floors:
        floors = ["3F", "4F", "5F"]

    def _floor_label(f: str) -> str:
        s = str(f).strip()
        if s.endswith("F") and s[:-1].isdigit():
            return f"{s[:-1]}楼"
        return s

    duty_floor_vars = duty_floor_vars or {}
    grade_group_duty_map = grade_group_duty_map or {}
    grade_group_available_map = grade_group_available_map or {}
    noon_map_m: dict[str, str] = {}
    noon_map_f: dict[str, str] = {}
    for row in noon_dorm_rows or []:
        day = str(row.get("星期", "")).strip()
        if day:
            noon_map_m[day] = str(row.get("男寝教师", "")).strip()
            noon_map_f[day] = str(row.get("女寝教师", "")).strip()
    night_map_m: dict[str, str] = {}
    night_map_f: dict[str, str] = {}
    for row in checkin_rows or []:
        day = str(row.get("日期", "")).strip()
        if day:
            night_map_m[day] = str(row.get("男晚查寝", row.get("男查寝", ""))).strip()
            night_map_f[day] = str(row.get("女晚查寝", row.get("女查寝", ""))).strip()

    start_row = 3

    am4_patrol_start = start_row
    ws_h.append(["", "三、四楼"] + [""] * len(DAYS))
    ws_h.append(["", "五楼"] + [""] * len(DAYS))
    ws_h.merge_cells(start_row=am4_patrol_start, start_column=1, end_row=am4_patrol_start + 1, end_column=1)
    ws_h.cell(row=am4_patrol_start, column=1, value="上午4巡视")
    start_row += 2

    afternoon_start = start_row
    for f in floors:
        row = ["", _floor_label(f)]
        for d in DAYS:
            names = [
                t
                for (t, dd, ff), v in duty_floor_vars.items()
                if dd == d and ff == f and solver.Value(v) == 1
            ]
            row.append(names[0] if names else "")
        ws_h.append(row)
    ws_h.merge_cells(
        start_row=afternoon_start,
        start_column=1,
        end_row=afternoon_start + len(floors) - 1,
        end_column=1,
    )
    ws_h.cell(row=afternoon_start, column=1, value="下午课前值班")
    start_row += len(floors)

    noon_start = start_row
    ws_h.append(["", "男寝"] + [noon_map_m.get(d, "") for d in DAYS])
    ws_h.append(["", "女寝"] + [noon_map_f.get(d, "") for d in DAYS])
    ws_h.merge_cells(start_row=noon_start, start_column=1, end_row=noon_start + 1, end_column=1)
    ws_h.cell(row=noon_start, column=1, value="中午查寝")
    start_row += 2

    pm4_patrol_start = start_row
    ws_h.append(["", "三、四楼"] + [""] * len(DAYS))
    ws_h.append(["", "五楼"] + [""] * len(DAYS))
    ws_h.merge_cells(start_row=pm4_patrol_start, start_column=1, end_row=pm4_patrol_start + 1, end_column=1)
    ws_h.cell(row=pm4_patrol_start, column=1, value="下午4巡视")
    start_row += 2

    night_start = start_row
    ws_h.append(["", "男寝"] + [night_map_m.get(d, "") for d in DAYS])
    ws_h.append(["", "女寝"] + [night_map_f.get(d, "") for d in DAYS])
    ws_h.merge_cells(start_row=night_start, start_column=1, end_row=night_start + 1, end_column=1)
    ws_h.cell(row=night_start, column=1, value="晚查寝")
    start_row += 2

    # 年级组值班（新增）
    grade_group_duty_map_display = dict(grade_group_duty_map)
    ws_h.append(["年级组值班", "年级组"] + [grade_group_duty_map_display.get(d, "") for d in DAYS])
    start_row += 1

    thin = Side(style="thin", color="000000")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    center = Alignment(horizontal="center", vertical="center")
    last_row = start_row - 1
    for r in range(2, last_row + 1):
        for c in range(1, 10):
            cell = ws_h.cell(row=r, column=c)
            cell.alignment = center
            cell.border = border
            if r == 2:
                cell.font = Font(bold=True)

    # 年级值班可用资源（复制“查寝值班总表”结构作为模板，仅填内容）
    ws_g = wb.copy_worksheet(ws_h)
    ws_g.title = SHEET_GRADE_DUTY_RESOURCE
    ws_g["A1"] = "年级值班可用资源"
    ws_g.merge_cells("A1:I1")

    merged_anchor = {}
    for m in ws_g.merged_cells.ranges:
        anchor = (m.min_row, m.min_col)
        for rr in range(m.min_row, m.max_row + 1):
            for cc in range(m.min_col, m.max_col + 1):
                merged_anchor[(rr, cc)] = anchor

    for r in range(3, last_row + 1):
        for c in range(1, 10):
            anchor = merged_anchor.get((r, c), (r, c))
            if anchor != (r, c):
                continue
            ws_g.cell(row=r, column=c, value="")

    # 结构不变，仅填充一个“按天可用资源”结果行
    ws_g.cell(row=3, column=1, value="年级组可用资源")
    ws_g.cell(row=3, column=2, value="年级组")
    for idx, d in enumerate(DAYS, start=3):
        ws_g.cell(row=3, column=idx, value=grade_group_available_map.get(d, ""))

    # 统一后置样式（仅导出表现层；不影响数据）
    apply_table_style(ws_h, header_row=2, freeze_panes="A3", zoom=115)
    apply_table_style(ws_g, header_row=2, freeze_panes="A3", zoom=115)
    ws_ht.sheet_view.showGridLines = False
    ws_ht.sheet_view.zoomScale = 115
    apply_block_outline(
        ws_ht,
        block_ranges=[
            (male_start_row, 1, male_end_row, 8),
            (female_start_row, 1, female_end_row, 8),
        ],
        title_rows=[male_start_row, female_start_row],
    )

    # Only adjust print pagination for the two printing sheets:
    # - 白天课表_汇总版
    # - 老师课表
    _apply_fixed_page_breaks_18x76(ws_s)
    _apply_fixed_page_breaks_18x76(ws_t)

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out_path)
    logger.info("已设置分页：白天课表_汇总版/老师课表 每页18列×76行")
    if _should_export_display_adjusted(out):
        _export_display_adjusted_workbook(
            out,
            data=data,
            vmap_summary=vmap_summary,
            tmap=tmap,
            teachers=teachers,
            grade_prefix=grade_prefix,
        )
