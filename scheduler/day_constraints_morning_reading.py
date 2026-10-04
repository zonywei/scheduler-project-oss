# -*- coding: utf-8 -*-
"""
What：早自习交替约束模块。
Why：保证周一到周四同班早自习学科不过度连排，提升排课多样性。
How：对同一班级在相邻日期（周一-周二、周二-周三、周三-周四）的同一学科施加互斥约束。
Diagnostics：输出 `outputs/day_diagnostic_morning_reading.txt` 记录输入检查与求解结果。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

from ortools.sat.python import cp_model

from scheduler.data.day_rules_reader import DayInputData, Slot
from scheduler.model.day_variables import DayVars

logger = logging.getLogger(__name__)

WEEKDAYS_MON_THU = ("星期一", "星期二", "星期三", "星期四")
ADJ_PAIRS = ("星期一", "星期二"), ("星期二", "星期三"), ("星期三", "星期四")


@dataclass
class MorningReadingContext:
    early_subjects: List[str]


def _collect_early_subjects(data: DayInputData) -> MorningReadingContext:
    """统计早自习相关学科列表。"""
    subjects: List[str] = []
    for (_cls, subj) in data.cls_subj_teacher.keys():
        subjects.append(subj)
    return MorningReadingContext(early_subjects=sorted(set(subjects)))


def _early_slot_exists(data: DayInputData) -> bool:
    """检查是否存在早自习时段。"""
    return any(s.block == "早自习" for s in data.available_slots)


def check_morning_reading_inputs(data: DayInputData) -> Tuple[MorningReadingContext, List[str]]:
    """输入检查与上下文构建。"""
    ctx = _collect_early_subjects(data)
    errors: List[str] = []

    if not _early_slot_exists(data):
        errors.append("未发现早自习时段（block=早自习），请检查白天规则时间格子。")

    return ctx, errors


def apply_morning_reading_constraints(
    model: cp_model.CpModel,
    data: DayInputData,
    dv: DayVars,
) -> MorningReadingContext:
    """早自习交替硬约束入口。"""
    ctx, errors = check_morning_reading_inputs(data)
    if errors:
        # 交给上层写诊断并抛错
        raise ValueError("; ".join(errors))

    # 相邻天互斥（同一学科不能连续）
    for cls in data.classes:
        for d1, d2 in ADJ_PAIRS:
            by_subj_d1: Dict[str, List[cp_model.IntVar]] = {}
            by_subj_d2: Dict[str, List[cp_model.IntVar]] = {}
            for (c, subj, slot), var in dv.x.items():
                if c != cls or slot.block != "早自习":
                    continue
                if slot.day == d1:
                    by_subj_d1.setdefault(subj, []).append(var)
                elif slot.day == d2:
                    by_subj_d2.setdefault(subj, []).append(var)

            all_subj = set(by_subj_d1.keys()) | set(by_subj_d2.keys())
            for subj in all_subj:
                v1 = by_subj_d1.get(subj, [])
                v2 = by_subj_d2.get(subj, [])
                if v1 and v2:
                    model.Add(sum(v1) + sum(v2) <= 1)

    return ctx


def extract_morning_reading_results(
    data: DayInputData,
    dv: DayVars,
    solver: cp_model.CpSolver,
) -> Dict[str, Dict[str, str]]:
    """提取早自习求解结果，按班级/日输出学科。"""
    result: Dict[str, Dict[str, str]] = {c: {} for c in data.classes}
    for (cls, subj, slot), var in dv.x.items():
        if slot.block != "早自习" or slot.day not in WEEKDAYS_MON_THU:
            continue
        if solver.Value(var) == 1:
            result[cls][slot.day] = subj
    return result


def write_morning_reading_diagnostic(
    out_dir: Path,
    ctx: MorningReadingContext,
    status_name: str,
    results: Dict[str, Dict[str, str]] | None = None,
    errors: List[str] | None = None,
) -> None:
    """写出早自习交替诊断文件。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "day_diagnostic_morning_reading.txt"
    lines: List[str] = []
    lines.append("[Morning Reading Diagnostic]")
    lines.append("EarlySlot=早自习")
    lines.append(f"EarlySubjects={ctx.early_subjects}")
    lines.append(f"SolveStatus={status_name}")
    if errors:
        lines.append("Errors=")
        for e in errors:
            lines.append(f"  - {e}")
    if results:
        lines.append("Results(Mon-Thu)=")
        for cls in sorted(results.keys()):
            row = results[cls]
            lines.append(
                f"  {cls}: 周一={row.get('星期一','')} 周二={row.get('星期二','')} "
                f"周三={row.get('星期三','')} 周四={row.get('星期四','')}"
            )
    path.write_text("\n".join(lines), encoding="utf-8")
