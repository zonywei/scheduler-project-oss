# -*- coding: utf-8 -*-
"""白天工作日约束的报告写出函数。"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Tuple

from ortools.sat.python import cp_model

from scheduler.data.day_rules_reader import DayInputData, Slot
from scheduler.calendar import WEEKDAY_DAYS

WEEKDAYS = WEEKDAY_DAYS


def _is_am1(slot: Slot) -> bool:
    return slot.block == "上午" and int(slot.period) == 1


def _is_am4(slot: Slot) -> bool:
    return slot.block == "上午" and int(slot.period) == 4


def write_low_weekday_subject_max1_report(
    out_dir: Path,
    data: DayInputData,
    max_weekday_hours: int,
) -> None:
    """输出低课时学科每日上限命中清单。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "day_low_weekday_subject_max1_report.txt"
    lines = ["[Low Weekday Subject Max1 Per Day]"]
    lines.append(f"Threshold={max_weekday_hours}")
    hits = []
    for (cls, subj), req in data.req_hours.items():
        if req is None:
            continue
        _req_e, req_w, _req_we = req
        if int(req_w) <= max_weekday_hours:
            hits.append((cls, subj, int(req_w)))
    hits.sort()
    for cls, subj, req_w in hits:
        lines.append(f"{cls} {subj}: weekday_hours={req_w}")
    lines.append(f"TotalHits={len(hits)}")
    path.write_text("\n".join(lines), encoding="utf-8")


def write_two_class_daily_min_report(
    out_dir: Path,
    solver: cp_model.CpSolver,
    details: Dict[Tuple[str, str, str], cp_model.IntVar],
    mode: str,
) -> None:
    """输出双班教师每日最小课时（soft/hard）诊断。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "day_two_class_daily_min_report.txt"
    lines = ["[Two-Class Daily Min Per Class]"]
    lines.append(f"Mode={mode}")
    total_viol = 0
    for (t, d, c), v in sorted(details.items()):
        val = solver.Value(v)
        total_viol += val
        lines.append(f"{t} {d} {c}: viol={val}")
    lines.append(f"TotalViolations={total_viol}")
    path.write_text("\n".join(lines), encoding="utf-8")


def write_day_soft_timepref_report(
    out_dir: Path,
    solver: cp_model.CpSolver,
    lang_am_vars: List[cp_model.IntVar],
    lang_pm_vars: List[cp_model.IntVar],
    lang_fixed: Tuple[int, int],
    stem_am1_vars: List[cp_model.IntVar],
    stem_am1_fixed: int,
    teacher_am1_details: Dict[str, Tuple[cp_model.IntVar, int, cp_model.IntVar, cp_model.IntVar]],
    weights: Tuple[int, int, int, int, int, int],
    top_n: int = 10,
) -> None:
    """输出白天软约束汇总（语文/外语/数理化/AM1碎片）。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "day_soft_timepref_report.txt"
    w_lang_pm, w_lang_am_reward, w_stem_am1, w_only_am1_day, k_am1_week, w_am1_excess = weights

    lang_am = sum(solver.Value(v) for v in lang_am_vars) + lang_fixed[0]
    lang_pm = sum(solver.Value(v) for v in lang_pm_vars) + lang_fixed[1]
    lang_pen = w_lang_pm * lang_pm - w_lang_am_reward * lang_am

    stem_am1 = sum(solver.Value(v) for v in stem_am1_vars) + stem_am1_fixed
    stem_pen = w_stem_am1 * stem_am1

    lines = ["[Day Soft Time Preference Report]"]
    lines.append(f"LangAMCount={lang_am}")
    lines.append(f"LangPMCount={lang_pm}")
    lines.append(f"LangPenalty={lang_pen}")
    lines.append(f"StemAM1Count={stem_am1}")
    lines.append(f"StemAM1Penalty={stem_pen}")
    lines.append(f"TeacherAM1WeekThreshold={k_am1_week}")
    lines.append("TeacherFragmentation=")

    frag_stats: List[Tuple[int, str, int, int]] = []
    for tch, (am1_cnt, am1_fixed, only_am1_days, excess) in sorted(teacher_am1_details.items()):
        am1_cnt_val = solver.Value(am1_cnt)
        only_days = solver.Value(only_am1_days)
        excess_val = solver.Value(excess)
        penalty = w_only_am1_day * only_days + w_am1_excess * excess_val
        lines.append(
            f"  {tch}: am1_cnt={am1_cnt_val} only_am1_days={only_days} excess={excess_val} penalty={penalty}"
        )
        frag_stats.append((only_days, tch, am1_cnt_val, penalty))

    frag_stats.sort(reverse=True)
    lines.append(f"Top{top_n}Fragmented=")
    for only_days, tch, am1_cnt_val, penalty in frag_stats[:top_n]:
        lines.append(f"  {tch}: only_am1_days={only_days} am1_cnt={am1_cnt_val} penalty={penalty}")

    path.write_text("\n".join(lines), encoding="utf-8")


def write_teacher_continuity_report(
    out_dir: Path,
    solver: cp_model.CpSolver,
    gap_details: Dict[Tuple[str, str, str], List[cp_model.IntVar]],
    top_n: int = 10,
) -> None:
    """输出教师连贯性 gap 明细。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "day_teacher_continuity_report.txt"

    lines = ["[Day Teacher Continuity Report]"]
    gap_counts: List[Tuple[int, str, str, str]] = []
    for (t, day, tag), vars_list in gap_details.items():
        cnt = sum(solver.Value(v) for v in vars_list)
        lines.append(f"{t} {day} {tag}: gaps={cnt}")
        gap_counts.append((cnt, t, day, tag))

    gap_counts.sort(reverse=True)
    lines.append(f"Top{top_n}Gaps=")
    for cnt, t, day, tag in gap_counts[:top_n]:
        lines.append(f"  {t} {day} {tag}: {cnt}")

    path.write_text("\n".join(lines), encoding="utf-8")


def write_teacher_am4_pm1_penalty_report(
    out_dir: Path,
    solver: cp_model.CpSolver,
    details: Dict[str, Tuple[int, cp_model.IntVar, cp_model.IntVar, cp_model.IntVar, cp_model.IntVar, cp_model.IntVar]],
    weights: Tuple[int, int, int, int],
) -> None:
    """输出 AM4+PM1 阶梯惩罚分解报告。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "day_teacher_am4_pm1_penalty_report.txt"
    w3, w4, w5, w6 = weights

    lines = ["[Day Teacher AM4+PM1 Penalty Report]"]
    over6 = 0
    for tch, (total_max, cnt, e3, e4, e5, e6) in sorted(details.items()):
        cnt_val = solver.Value(cnt)
        e3v = solver.Value(e3)
        e4v = solver.Value(e4)
        e5v = solver.Value(e5)
        e6v = solver.Value(e6)
        penalty = w3 * e3v + w4 * e4v + w5 * e5v + w6 * e6v
        if cnt_val > 6:
            over6 += 1
        lines.append(
            f"{tch}: cnt={cnt_val} e3={e3v} e4={e4v} e5={e5v} e6={e6v} penalty={penalty}"
        )

    lines.append(f"OverLimitCount(>6)={over6}")
    path.write_text("\n".join(lines), encoding="utf-8")


def write_teacher_m1_cap_report(
    out_dir: Path,
    solver: cp_model.CpSolver | cp_model.CpSolverSolutionCallback,
    details: Dict[str, Tuple[cp_model.IntVar, cp_model.IntVar, Dict[str, cp_model.IntVar], int]],
    max_m1: int,
    weight: int,
) -> None:
    """输出教师周中上午1统计与是否触发上限罚分。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "day_teacher_m1_cap_report.txt"
    lines = [
        "[Day Teacher M1 Cap Report]",
        "Scope=周一到周五 + 上午1",
        f"HardCap={max_m1}",
        f"SoftWeight(w_hit_m1_cap)={weight}",
    ]

    for teacher, (m1_total, hit_cap, occ_by_day, fixed_total) in sorted(details.items()):
        total_val = solver.Value(m1_total)
        hit_val = solver.Value(hit_cap)
        days_str = ", ".join([f"{d}:{solver.Value(v)}" for d, v in occ_by_day.items()])
        lines.append(
            f"{teacher}: m1_total={total_val} hit_cap={hit_val} fixed_am1_lb={fixed_total} | {days_str}"
        )
    path.write_text("\n".join(lines), encoding="utf-8")


def write_teacher_m1_cap_infeasible_hint(
    out_dir: Path,
    structural_impossible: Dict[str, int],
    max_m1: int,
) -> None:
    """不可行提示：固定课位导致上午1最小需求超过上限。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "day_teacher_m1_cap_infeasible_hint.txt"
    lines = [
        "[Day Teacher M1 Cap Infeasible Hint]",
        f"HardCap={max_m1}",
        "结构性不可行（固定上午1下界已超过上限）的教师：",
    ]
    if not structural_impossible:
        lines.append("  无（若仍不可行，请检查其他硬约束叠加）")
    else:
        for teacher, lb in sorted(structural_impossible.items(), key=lambda kv: (-kv[1], kv[0])):
            lines.append(f"  {teacher}: fixed_am1_lb={lb} > {max_m1}")
    path.write_text("\n".join(lines), encoding="utf-8")


def write_day_infeasible_hints(out_dir: Path, cfg: Any | None = None) -> None:
    """输出白天不可行提示（常见冲突来源）。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "day_infeasible_hints.txt"
    lines = [
        "[Day Infeasible Hints]",
        "可能冲突来源:",
    ]
    if cfg is None or cfg.enable_binding_chem_bio:
        lines.append("- 8班化学与9班生物跨班绑定")
    if cfg is None or cfg.enable_head_pm1_min:
        lines.append("- 工作日下午第一节班主任人数下限")
    if cfg is None or cfg.enable_no_am1_am4:
        lines.append("- 上午1与上午4同教师禁排")
    if len(lines) == 2:
        lines.append("- 已关闭当前已知白天核心硬阻断；若仍不可行，请继续检查教师冲突、固定课位、每日课时下限或值班硬约束。")
    path.write_text("\n".join(lines), encoding="utf-8")


def write_core_teacher_day_load_sanity(
    out_dir: Path,
    solver: cp_model.CpSolver,
    details: Dict[str, object],
    sample_n: int = 3,
) -> None:
    """约束15/16自检：抽样教师输出工作日白天课时与AM1+AM4触发情况。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "day_core_teacher_day_load_sanity.txt"

    target_teachers: List[str] = list(details.get("target_teachers", []))
    teacher_slots: Dict[str, Dict[str, Dict[Slot, List[cp_model.IntVar]]]] = details.get("teacher_slots", {})  # type: ignore[assignment]
    fixed_counts: Dict[Tuple[str, str, str], int] = details.get("fixed_counts", {})  # type: ignore[assignment]
    required_hours: Dict[str, int] = details.get("required_hours", {})  # type: ignore[assignment]
    max_per_day = int(details.get("max_per_day", 3))
    impossible_teachers: List[str] = list(details.get("impossible_teachers", []))

    lines = [
        "[Core Teacher Day Load Sanity]",
        "Scope=周一到周五 + 上午/下午（不含早自习与晚自习）",
        f"TeacherCount={len(target_teachers)}",
        f"MaxPerDay={max_per_day}",
        f"ImpossibleByDemand(> {max_per_day*len(WEEKDAYS)})={impossible_teachers}",
    ]

    for teacher in target_teachers[:sample_n]:
        lines.append(f"Teacher={teacher} RequiredWeekdayHours={required_hours.get(teacher, 0)}")
        for day in WEEKDAYS:
            slots = teacher_slots.get(teacher, {}).get(day, {})
            day_vars = [v for vars_list in slots.values() for v in vars_list]
            day_fixed = sum(v for (t, d, _k), v in fixed_counts.items() if t == teacher and d == day)
            load = sum(solver.Value(v) for v in day_vars) + day_fixed
            am1 = (
                sum(solver.Value(v) for s, vars_list in slots.items() if _is_am1(s) for v in vars_list)
                + sum(v for (t, d, k), v in fixed_counts.items() if t == teacher and d == day and k == "上午1")
            )
            am4 = (
                sum(solver.Value(v) for s, vars_list in slots.items() if _is_am4(s) for v in vars_list)
                + sum(v for (t, d, k), v in fixed_counts.items() if t == teacher and d == day and k == "上午4")
            )
            lines.append(f"  {day}: load={load} am1={am1} am4={am4} am1_and_am4={'Y' if am1>0 and am4>0 else 'N'}")

    path.write_text("\n".join(lines), encoding="utf-8")


def write_core_teacher_day_load_infeasible_hint(
    out_dir: Path,
    details: Dict[str, object],
) -> None:
    """若不可行，提示是否存在“原始需求已必然超过每天上限”教师。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "day_core_teacher_day_load_infeasible_hint.txt"
    required_hours: Dict[str, int] = details.get("required_hours", {})  # type: ignore[assignment]
    max_per_day = int(details.get("max_per_day", 3))
    impossible_teachers: List[str] = list(details.get("impossible_teachers", []))

    lines = [
        "[Core Teacher Day Load Infeasible Hint]",
        f"Rule: 周一到周五白天每天最多{max_per_day}节 + 禁止同日上午1/上午4同现",
        f"ImpossibleByDemand(> {max_per_day*len(WEEKDAYS)})={len(impossible_teachers)}",
    ]
    for t in impossible_teachers:
        lines.append(f"  {t}: required_weekday_hours={required_hours.get(t, 0)}")
    if not impossible_teachers:
        lines.append("  未发现“需求总量必然超上限”的教师，请检查固定课位冲突或其他硬约束叠加。")
    path.write_text("\n".join(lines), encoding="utf-8")
