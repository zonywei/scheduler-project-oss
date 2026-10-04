# -*- coding: utf-8 -*-
"""
What：体育/技术教师专属白天约束（PE/Tech constraints）。
Why：体育/技术课时段和教师负担有特殊安排，需要时间窗、紧凑性与白名单约束。
How：基于白天变量 x[(班级,学科,Slot)] 聚合教师授课布尔量，施加硬约束与软惩罚。
Weights：
    - pe_tech_constraints.w_pe_am_penalty（建议 50/100/200/400）：
      越大越减少体育教师上午授课，可能影响可行性。
    - pe_tech_constraints.w_pe_gap_penalty（建议 50/100/200/400）：
      越大越倾向当天半天内连续授课，可能牺牲均匀性。
Diagnostics：
    - outputs/诊断/白天_体技审计.txt
    - outputs/诊断/白天_体技约束检查.txt
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Set, Tuple

from ortools.sat.python import cp_model

from scheduler.data.day_rules_reader import DayInputData, Slot
from scheduler.model.day_variables import DayVars
from scheduler.calendar import WEEKDAY_DAYS, is_weekday_day

WEEKDAYS = WEEKDAY_DAYS

SUBJ_ALIAS = {
    "体育": "体育",
    "体育与健康": "体育",
    "技术": "技术",
    "信息技术": "技术",
    "通用技术": "技术",
}


@dataclass
class PeTechConfig:
    enable_pe_time_window_hard: bool = True
    enable_pe_reduce_am: bool = True
    enable_pe_tech_compact: bool = True
    w_pe_am_penalty: int = 200
    w_pe_gap_penalty: int = 200


def normalize_subject(name: str) -> str:
    """学科归一化（体育/技术别名）。"""
    return SUBJ_ALIAS.get(str(name).strip(), str(name).strip())


def is_pe_subject(name: str) -> bool:
    """是否体育学科。"""
    return normalize_subject(name) == "体育"


def is_pe_or_tech_subject(name: str) -> bool:
    """是否体育或技术学科。"""
    return normalize_subject(name) in ("体育", "技术")


def _slot_key(slot: Slot) -> str:
    """Slot 映射到字符串键（block+period）。"""
    return f"{slot.block}{slot.period}"


def _is_weekday(day: str) -> bool:
    """是否工作日（周一到周五）。"""
    return is_weekday_day(day)


def _slot_order_key(slot: Slot) -> Tuple[int, int]:
    """用于排序的时段键。"""
    if slot.block == "早自习":
        return (0, 0)
    if slot.block == "上午":
        return (1, int(slot.period))
    if slot.block == "下午":
        return (2, int(slot.period))
    return (99, int(slot.period))


def get_pe_tech_teachers(data: DayInputData) -> Set[str]:
    """返回体育/技术授课教师集合。"""
    teachers: Set[str] = set()
    for (cls, subj), tch in data.cls_subj_teacher.items():
        if is_pe_or_tech_subject(subj):
            teachers.add(tch)
    return teachers


def get_pe_teachers(data: DayInputData) -> Set[str]:
    """返回体育授课教师集合。"""
    teachers: Set[str] = set()
    for (cls, subj), tch in data.cls_subj_teacher.items():
        if is_pe_subject(subj):
            teachers.add(tch)
    return teachers


def build_slot_sets(data: DayInputData) -> Tuple[List[Slot], List[Slot], List[Slot]]:
    """构建 AM/PM/AM4 时段集合。"""
    am_all = [s for s in data.available_slots if s.block == "上午"]
    pm_all = [s for s in data.available_slots if s.block == "下午"]
    am4 = [s for s in data.available_slots if s.block == "上午" and int(s.period) == 4]
    return am_all, pm_all, am4


def write_pe_tech_audit(out_dir: Path, data: DayInputData, pe_tech_teachers: Set[str]) -> None:
    """输出体育/技术审计（学科映射、教师名单、时段集合）。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "day_pe_tech_audit.txt"
    am_all, pm_all, am4 = build_slot_sets(data)
    lines = ["[Day PE/Tech Audit]"]
    lines.append(f"SubjectMapping={SUBJ_ALIAS}")
    lines.append(f"PE_TECH_TEACHERS={sorted(pe_tech_teachers)}")
    lines.append(f"AM_all={[ _slot_key(s) for s in sorted(am_all, key=_slot_order_key) ]}")
    lines.append(f"PM_all={[ _slot_key(s) for s in sorted(pm_all, key=_slot_order_key) ]}")
    lines.append(f"AM4={[ _slot_key(s) for s in sorted(am4, key=_slot_order_key) ]}")
    path.write_text("\n".join(lines), encoding="utf-8")


def _collect_teacher_vars(
    data: DayInputData,
    dv: DayVars,
    only_pe_tech: bool = True,
) -> Dict[str, Dict[str, Dict[Slot, List[cp_model.IntVar]]]]:
    """聚合教师授课变量（按教师/日期/时段）。"""
    out: Dict[str, Dict[str, Dict[Slot, List[cp_model.IntVar]]]] = {}
    for (cls, subj, slot), var in dv.x.items():
        if not _is_weekday(slot.day):
            continue
        if only_pe_tech and not is_pe_or_tech_subject(subj):
            continue
        teacher = data.cls_subj_teacher.get((cls, subj))
        if not teacher:
            continue
        out.setdefault(teacher, {}).setdefault(slot.day, {}).setdefault(slot, []).append(var)
    return out


def apply_pe_time_window_hard(
    model: cp_model.CpModel,
    data: DayInputData,
    dv: DayVars,
) -> int:
    """
    体育课程时间窗硬约束：仅允许工作日 PM + 周三/四/五 AM4。
    返回非法固定课数量（诊断用）。
    """
    am_all, pm_all, am4 = build_slot_sets(data)
    pm_set = set(pm_all)
    am4_set = set([s for s in am4 if s.day in ("星期三", "星期四", "星期五")])
    allowed = pm_set | am4_set

    illegal_fixed = 0
    for (cls, subj, slot), var in dv.x.items():
        if not is_pe_subject(subj):
            continue
        if not _is_weekday(slot.day):
            model.Add(var == 0)
            continue
        if slot not in allowed:
            model.Add(var == 0)

    for (cls, slot), subj in data.fixed_assign.items():
        if not is_pe_subject(subj):
            continue
        if not _is_weekday(slot.day) or slot not in allowed:
            illegal_fixed += 1

    return illegal_fixed


def apply_teacher_whitelist_hard(
    model: cp_model.CpModel,
    data: DayInputData,
    dv: DayVars,
    teacher_name: str,
    allowed: Set[Tuple[str, str]],
) -> int:
    """
    指定教师白名单硬约束（仅体育/技术课）。
    返回固定课违规数（诊断用）。
    """
    violations_fixed = 0
    for (cls, subj, slot), var in dv.x.items():
        if not is_pe_or_tech_subject(subj):
            continue
        teacher = data.cls_subj_teacher.get((cls, subj))
        if teacher != teacher_name:
            continue
        if (slot.day, _slot_key(slot)) not in allowed:
            model.Add(var == 0)

    for (cls, slot), subj in data.fixed_assign.items():
        if not is_pe_or_tech_subject(subj):
            continue
        teacher = data.cls_subj_teacher.get((cls, subj))
        if teacher != teacher_name:
            continue
        if (slot.day, _slot_key(slot)) not in allowed:
            violations_fixed += 1
    return violations_fixed


def apply_pe_reduce_am_soft(
    data: DayInputData,
    dv: DayVars,
    pe_teachers: Set[str],
) -> List[cp_model.IntVar]:
    """
    体育教师上午授课惩罚（软约束）。
    罚分权重在目标函数处应用：pe_tech_constraints.w_pe_am_penalty。
    """
    penalties: List[cp_model.IntVar] = []
    teacher_vars = _collect_teacher_vars(data, dv, only_pe_tech=True)
    for t in pe_teachers:
        days = teacher_vars.get(t, {})
        for day in WEEKDAYS:
            slots = days.get(day, {})
            for s, vars_list in slots.items():
                if s.block == "上午":
                    penalties.extend(vars_list)
    return penalties


def apply_pe_tech_compact_soft(
    model: cp_model.CpModel,
    data: DayInputData,
    dv: DayVars,
    pe_tech_teachers: Set[str],
) -> Tuple[List[cp_model.IntVar], Dict[Tuple[str, str, str], List[cp_model.IntVar]]]:
    """
    体育/技术教师半天内紧凑性惩罚（软约束）。
    采用 1-0-1 gap 线性化，权重在目标函数处应用：pe_tech_constraints.w_pe_gap_penalty。
    """
    penalties: List[cp_model.IntVar] = []
    details: Dict[Tuple[str, str, str], List[cp_model.IntVar]] = {}
    teacher_vars = _collect_teacher_vars(data, dv, only_pe_tech=True)

    for t in pe_tech_teachers:
        days = teacher_vars.get(t, {})
        for day in WEEKDAYS:
            slots = days.get(day, {})
            am_slots = sorted([s for s in slots.keys() if s.block == "上午"], key=_slot_order_key)
            pm_slots = sorted([s for s in slots.keys() if s.block == "下午"], key=_slot_order_key)

            def build_gap(half_slots: List[Slot], tag: str) -> None:
                if not half_slots:
                    return
                busy = []
                for s in half_slots:
                    vars_list = slots.get(s, [])
                    if vars_list:
                        b = model.NewBoolVar(f"pe_busy[{t},{day},{_slot_key(s)}]")
                        model.Add(sum(vars_list) == b)
                    else:
                        b = model.NewBoolVar(f"pe_busy[{t},{day},{_slot_key(s)}]")
                        model.Add(b == 0)
                    busy.append(b)

                gap_vars: List[cp_model.IntVar] = []
                if len(busy) >= 3:
                    for i in range(len(busy) - 2):
                        b1, b2, b3 = busy[i], busy[i + 1], busy[i + 2]
                        gap = model.NewBoolVar(f"pe_gap[{t},{day},{tag},{i}]")
                        model.Add(gap <= b1)
                        model.Add(gap <= b3)
                        model.Add(gap <= 1 - b2)
                        model.Add(gap >= b1 + b3 - b2 - 1)
                        gap_vars.append(gap)
                        penalties.append(gap)  # weight: day.pe_tech_constraints.w_pe_gap_penalty（建议 50~400）
                else:
                    for i in range(len(busy) - 1):
                        b1, b2 = busy[i], busy[i + 1]
                        gap = model.NewBoolVar(f"pe_gap_adj[{t},{day},{tag},{i}]")
                        model.Add(gap <= b1)
                        model.Add(gap <= 1 - b2)
                        model.Add(gap >= b1 - b2)
                        gap_vars.append(gap)
                        penalties.append(gap)  # weight: day.pe_tech_constraints.w_pe_gap_penalty（建议 50~400）

                if gap_vars:
                    details[(t, day, tag)] = gap_vars

            build_gap(am_slots, "AM")
            build_gap(pm_slots, "PM")

    return penalties, details


def write_pe_tech_checklist(
    out_dir: Path,
    data: DayInputData,
    dv: DayVars,
    solver: cp_model.CpSolver,
    pe_teachers: Set[str],
    pe_tech_teachers: Set[str],
    liu_allowed: Set[Tuple[str, str]],
    tao_allowed: Set[Tuple[str, str]],
    liu_viol_fixed: int,
    tao_viol_fixed: int,
    pe_illegal_fixed: int,
    pe_am_penalties: List[cp_model.IntVar],
    gap_details: Dict[Tuple[str, str, str], List[cp_model.IntVar]],
    weights: Tuple[int, int],
) -> None:
    """输出体育/技术约束检查清单（违规数与软罚分）。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "day_pe_tech_checklist.txt"
    w_pe_am, w_gap = weights

    pe_illegal = pe_illegal_fixed
    for (cls, subj, slot), var in dv.x.items():
        if not is_pe_subject(subj):
            continue
        if not _is_weekday(slot.day):
            if solver.Value(var) == 1:
                pe_illegal += 1
            continue
        if slot.block == "下午":
            continue
        if slot.block == "上午" and int(slot.period) == 4 and slot.day in ("星期三", "星期四", "星期五"):
            continue
        if solver.Value(var) == 1:
            pe_illegal += 1

    whitelist_viol = int(liu_viol_fixed) + int(tao_viol_fixed)

    pe_am_count = sum(solver.Value(v) for v in pe_am_penalties)

    lines = ["[Day PE/Tech Checklist]"]
    lines.append(f"PEIllegalSlotCount={pe_illegal}")
    lines.append(f"TeacherWhitelistViolations={whitelist_viol}")
    lines.append(f"PEAMCount={pe_am_count}")
    lines.append(f"PEAMPenalty={w_pe_am * pe_am_count}")
    lines.append("PE/TechGaps=")

    gap_total = 0
    for (t, day, tag), vars_list in sorted(gap_details.items()):
        cnt = sum(solver.Value(v) for v in vars_list)
        gap_total += cnt
        lines.append(f"  {t} {day} {tag}: gaps={cnt}")
    lines.append(f"PEGapsPenalty={w_gap * gap_total}")

    path.write_text("\n".join(lines), encoding="utf-8")
