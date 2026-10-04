# -*- coding: utf-8 -*-
"""
下午课前值班（独立建模版）

本模块只负责“下午课前值班”这一套变量与约束，不复用旧口径变量。

核心对象：
- 楼层: 3F / 4F / 5F
- 天: 白天规则中的全部天（周一到周日；周六有特例）
- 班主任分组:
  - T4: 1-7 班班主任（只能值 4F）
  - T5: 8-14 班班主任（只能值 5F）
  - T3: 15-17 班班主任（只能值 3F）

变量：
- x[t,d,f] ∈ {0,1}: 老师 t 在 d 天是否承担 f 楼值班
- duty_day[t,d] ∈ {0,1}: 老师 t 在 d 天是否承担任意楼层值班
- pm1[t,d] ∈ {0,1}: 老师 t 在 d 天是否有下午第一节课
- trigger_pm1_penalty[t,d] ∈ {0,1}: 仅当 pm1=1 且 duty_day=0 时触发 PM1 单独惩罚
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Set, Tuple

import pandas as pd
from ortools.sat.python import cp_model

from scheduler.data.day_rules_reader import DayInputData, Slot
from scheduler.data.teacher_table_schema import (
    configured_teacher_table_columns,
    load_teacher_table_frame,
)
from scheduler.model.day_variables import DayVars
from scheduler.diagnostics.penalty_registry import register
from scheduler.output_paths import resolve_output_dir
from scheduler.calendar import SATURDAY, day_rank


FLOORS: Tuple[str, str, str] = ("3F", "4F", "5F")
PM1_KEY = "下午1"
# 仅“下午课前值班”语义下，9班并入5F。
_DUTY_FLOOR_OVERRIDE_BY_CLASS_NO: Dict[int, str] = {9: "5F"}


@dataclass
class HeadDutyConfig:
    # 主开关
    enable_head_duty: bool = True
    # PM1 单独惩罚（当日值班则免罚）
    w_pm1_penalty: int = 120
    # 兼容旧调用字段（不再作为目标惩罚使用）
    w_excess_duty: int = 0
    w_excess_pm1: int = 120
    # 兼容旧配置字段（重建后不再使用）
    enable_pm1_min_if_missing: bool = True
    k_pm1_excess: int = 2
    # 工作日（周一到周五）PM1 仅允许出现在当日有下午课前值班时
    enable_weekday_pm1_requires_duty: bool = True
    weekday_pm1_requires_duty_mode: str = "hard"  # hard|soft
    w_weekday_pm1_requires_duty: int = 5000
    weekday_pm1_requires_duty_exempt_teachers: Tuple[str, ...] = ()


def _slot_key(slot: Slot) -> str:
    return f"{slot.block}{slot.period}"


def _norm_teacher(name: object) -> str:
    if pd.isna(name):
        return ""
    return str(name).strip()


def _parse_class_no(cls: object) -> int | None:
    s = str(cls).strip()
    m = re.search(r"(\d+)", s)
    if not m:
        return None
    try:
        return int(m.group(1))
    except Exception:
        return None


def _class_no_to_teaching_floor(class_no: int) -> str | None:
    if 1 <= class_no <= 7:
        return "5F"
    if 8 <= class_no <= 14:
        return "4F"
    if 15 <= class_no <= 17:
        return "3F"
    return None


def _class_no_to_duty_floor(class_no: int) -> str | None:
    """值班楼层口径：允许对特定班级覆盖默认教学楼层映射。"""
    if class_no in _DUTY_FLOOR_OVERRIDE_BY_CLASS_NO:
        return _DUTY_FLOOR_OVERRIDE_BY_CLASS_NO[class_no]
    return _class_no_to_teaching_floor(class_no)


def _day_order(day: str) -> int:
    return day_rank(day)


def _collect_days(data: DayInputData) -> List[str]:
    return sorted({s.day for s in data.available_slots}, key=_day_order)


def _collect_days_except_sat(data: DayInputData) -> List[str]:
    return [d for d in _collect_days(data) if d != SATURDAY]


def _build_floor_groups(
    io_cfg: dict,
    base_dir: Path,
    head_teachers: List[str],
) -> Tuple[
    Dict[str, str],            # teaching_floor_by_teacher
    Dict[str, str],            # duty_home_floor_by_teacher
    Dict[str, int],            # class_no_by_teacher
    List[str],                 # hints
]:
    """读取班主任楼层信息。

    - 教学楼层：保持原始班级楼层口径（不改教学语义）
    - 值班楼层：允许按班级进行值班口径覆盖（当前 9 班->5F）
    """
    class_col, head_col, _gender_col = configured_teacher_table_columns(io_cfg)

    hints: List[str] = []
    teaching_floor_by_teacher: Dict[str, str] = {}
    duty_home_floor_by_teacher: Dict[str, str] = {}
    class_no_by_teacher: Dict[str, int] = {}

    df = load_teacher_table_frame(io_cfg, base_dir)
    if df.empty:
        hints.append("教师定位表不存在或没有可用行")
        return teaching_floor_by_teacher, duty_home_floor_by_teacher, class_no_by_teacher, hints

    if class_col not in df.columns or head_col not in df.columns:
        hints.append(f"教师定位表缺少列: class={class_col}, head={head_col}")
        return teaching_floor_by_teacher, duty_home_floor_by_teacher, class_no_by_teacher, hints

    head_set = set(head_teachers)
    for _, row in df.iterrows():
        t = _norm_teacher(row.get(head_col, ""))
        if not t or t not in head_set:
            continue
        cno = _parse_class_no(row.get(class_col, ""))
        if cno is None:
            hints.append(f"班级编号无法解析: teacher={t}, class={row.get(class_col, '')}")
            continue
        teaching_floor = _class_no_to_teaching_floor(cno)
        duty_floor = _class_no_to_duty_floor(cno)
        if teaching_floor is None or duty_floor is None:
            hints.append(f"班级不在1-17范围: teacher={t}, class_no={cno}")
            continue

        old_teaching = teaching_floor_by_teacher.get(t)
        if old_teaching is not None and old_teaching != teaching_floor:
            # 同一老师不应跨分组；若出现冲突，记录提示并保留首次分组
            hints.append(f"班主任教学楼层冲突: teacher={t}, floor={old_teaching}/{teaching_floor}")
            continue
        old_duty = duty_home_floor_by_teacher.get(t)
        if old_duty is not None and old_duty != duty_floor:
            hints.append(f"班主任值班楼层冲突: teacher={t}, floor={old_duty}/{duty_floor}")
            continue
        teaching_floor_by_teacher[t] = teaching_floor
        duty_home_floor_by_teacher[t] = duty_floor
        class_no_by_teacher[t] = cno

    for t in head_teachers:
        if t not in duty_home_floor_by_teacher:
            hints.append(f"班主任未命中楼层分组: {t}")
    return teaching_floor_by_teacher, duty_home_floor_by_teacher, class_no_by_teacher, hints


def write_head_duty_audit_before(
    out_dir: Path,
    data: DayInputData,
    head_teachers: List[str],
    teaching_floor_by_teacher: Dict[str, str],
    duty_home_floor_by_teacher: Dict[str, str],
    h4_base: List[str],
    h5_base: List[str],
    t9_teacher: str,
    hints: List[str],
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "head_duty_audit_before.txt"
    lines = [
        "[Head Duty Audit Before]",
        f"Days={_collect_days(data)}",
        f"PM1Key={PM1_KEY}",
        f"HeadTeachersCount={len(head_teachers)}",
        "HeadTeachersTop20=" + ", ".join(head_teachers[:20]),
        f"H4_BASE={h4_base}",
        f"H5_BASE={h5_base}",
        f"T9_TEACHER={t9_teacher}",
        "TeachingFloorByTeacherSample="
        + str(dict(list(sorted(teaching_floor_by_teacher.items(), key=lambda kv: kv[0]))[:20])),
        "DutyHomeFloorByTeacherSample="
        + str(dict(list(sorted(duty_home_floor_by_teacher.items(), key=lambda kv: kv[0]))[:20])),
    ]
    if hints:
        lines.append("Hints=")
        lines.extend([f"  - {h}" for h in hints])
    path.write_text("\n".join(lines), encoding="utf-8")


def build_teach_pm1(
    model: cp_model.CpModel,
    data: DayInputData,
    dv: DayVars,
    head_teachers: List[str],
    days: List[str],
) -> Dict[Tuple[str, str], cp_model.IntVar]:
    """构造 pm1[t,d]。固定课位 fixed_assign 计入 1。"""
    teacher_vars: Dict[Tuple[str, str], List[cp_model.IntVar]] = {}
    for (cls, subj, slot), var in dv.x.items():
        if slot.day not in days:
            continue
        if not (slot.block == "下午" and int(slot.period) == 1):
            continue
        teacher = data.cls_subj_teacher.get((cls, subj))
        if not teacher or teacher not in head_teachers:
            continue
        teacher_vars.setdefault((teacher, slot.day), []).append(var)

    teach_pm1: Dict[Tuple[str, str], cp_model.IntVar] = {}
    for t in head_teachers:
        for d in days:
            fixed = 0
            for (cls, slot), subj in data.fixed_assign.items():
                if slot.day != d:
                    continue
                if not (slot.block == "下午" and int(slot.period) == 1):
                    continue
                t_fixed = data.cls_subj_teacher.get((cls, subj))
                if t_fixed == t:
                    fixed += 1

            b = model.NewBoolVar(f"teach_pm1[{t},{d}]")
            vars_list = teacher_vars.get((t, d), [])
            if fixed > 0:
                model.Add(b == 1)
            elif vars_list:
                for v in vars_list:
                    model.Add(b >= v)
                model.Add(b <= sum(vars_list))
            else:
                model.Add(b == 0)
            teach_pm1[(t, d)] = b
    return teach_pm1


def apply_head_duty_constraints(
    model: cp_model.CpModel,
    data: DayInputData,
    dv: DayVars,
    head_teachers: List[str],
    io_cfg: dict,
    base_dir: Path,
    cfg: HeadDutyConfig,
) -> Tuple[
    Dict[Tuple[str, str], cp_model.IntVar],       # duty_day
    Dict[Tuple[str, str], cp_model.IntVar],       # teach_pm1
    List[cp_model.IntVar],                        # penalty_terms
    Dict[str, cp_model.IntVar],                   # duty_count_by_teacher
    Dict[str, cp_model.IntVar],                   # trigger_count_by_teacher
    Dict[Tuple[str, str, str], cp_model.IntVar],  # duty_floor x[t,d,f]
    Dict[Tuple[str, str], cp_model.IntVar],       # trigger_pm1_penalty[t,d]
    Dict[str, str],                                # teaching_floor_by_teacher
    Dict[str, List[str]],                          # duty_home_groups
    Dict[str, Set[str]],                           # allowed_duty_floors_by_teacher
    Dict[str, cp_model.IntVar],                    # borrow_5_to_4
    Dict[str, cp_model.IntVar],                    # weekly_duty_count_45f
    List[str],                                     # h4_base
    List[str],                                     # h5_base
    str,                                           # t9_teacher
    List[str],                                     # hints
]:
    """Afternoon pre-class duty constraints with class-9 merge and hard 4F/5F weekly fairness."""
    days = _collect_days(data)
    required_days = {"\u661f\u671f\u4e00", "\u661f\u671f\u4e8c", "\u661f\u671f\u4e09", "\u661f\u671f\u56db", "\u661f\u671f\u4e94", "\u661f\u671f\u516d", "\u661f\u671f\u65e5"}
    if len(days) != 7 or set(days) != required_days:
        raise ValueError(f"Head duty requires full Monday-Sunday (7 days), got days={days}")

    teaching_floor_by_teacher, duty_home_floor_by_teacher, class_no_by_teacher, hints = _build_floor_groups(
        io_cfg, base_dir, head_teachers
    )

    duty_home_groups: Dict[str, List[str]] = {"3F": [], "4F": [], "5F": []}
    for t in head_teachers:
        f = duty_home_floor_by_teacher.get(t)
        if f in duty_home_groups:
            duty_home_groups[f].append(t)
    for f in FLOORS:
        duty_home_groups[f].sort()

    t9_list = sorted([t for t, cno in class_no_by_teacher.items() if cno == 9])
    if len(t9_list) != 1:
        raise ValueError(f"Expected exactly one class-9 head teacher, got {t9_list}")
    t9_teacher = t9_list[0]

    h4_base = sorted([t for t, f in duty_home_floor_by_teacher.items() if f == "4F"])
    h5_merged = sorted([t for t, f in duty_home_floor_by_teacher.items() if f == "5F"])
    h5_base = sorted([t for t, f in teaching_floor_by_teacher.items() if f == "5F"])

    if t9_teacher in h5_base:
        raise ValueError(f"Class-9 head teacher {t9_teacher} unexpectedly appears in pre-merge 5F set")
    if t9_teacher not in h5_merged:
        raise ValueError(f"Class-9 head teacher {t9_teacher} was not moved into merged 5F duty set")

    expected_h4_final = len(h4_base) + 1
    expected_h5_final = len(h5_merged) - 1
    if expected_h4_final != 7:
        raise ValueError(f"4F set size check failed: expected 7, got {expected_h4_final} (H4_BASE={len(h4_base)})")
    if expected_h5_final != 7:
        raise ValueError(f"5F set size check failed: expected 7, got {expected_h5_final} (H5_MERGED={len(h5_merged)})")
    if len(h5_base) != 7:
        raise ValueError(f"H5_BASE size check failed: expected 7, got {len(h5_base)}")

    allowed_duty_floors_by_teacher: Dict[str, Set[str]] = {}
    for t in head_teachers:
        if t == t9_teacher:
            allowed_duty_floors_by_teacher[t] = {"5F"}
        elif t in h4_base:
            allowed_duty_floors_by_teacher[t] = {"4F"}
        elif t in h5_base:
            allowed_duty_floors_by_teacher[t] = {"4F", "5F"}
        else:
            home = duty_home_floor_by_teacher.get(t)
            allowed_duty_floors_by_teacher[t] = {home} if home else set()

    write_head_duty_audit_before(
        resolve_output_dir(io_cfg, base_dir / "config" / "io.yaml"),
        data,
        head_teachers,
        teaching_floor_by_teacher,
        duty_home_floor_by_teacher,
        h4_base,
        h5_base,
        t9_teacher,
        hints,
    )

    teach_pm1 = build_teach_pm1(model, data, dv, head_teachers, days)

    duty_floor: Dict[Tuple[str, str, str], cp_model.IntVar] = {}
    duty_day: Dict[Tuple[str, str], cp_model.IntVar] = {}
    trigger_pm1: Dict[Tuple[str, str], cp_model.IntVar] = {}
    extra_penalty_terms: List[cp_model.IntVar] = []

    borrow_5_to_4: Dict[str, cp_model.IntVar] = {
        t: model.NewBoolVar(f"borrow_5_to_4[{t}]") for t in h5_base
    }
    model.Add(sum(borrow_5_to_4.values()) == 1)

    candidate_45 = set(h4_base) | set(h5_base) | {t9_teacher}

    for t in head_teachers:
        for d in days:
            floor_vars = []
            for f in FLOORS:
                x = model.NewBoolVar(f"duty_floor[{t},{d},{f}]")
                duty_floor[(t, d, f)] = x
                floor_vars.append(x)

                if t in candidate_45:
                    if f == "3F":
                        model.Add(x == 0)
                    elif t == t9_teacher:
                        if f != "5F":
                            model.Add(x == 0)
                    elif t in h4_base:
                        if f != "4F":
                            model.Add(x == 0)
                    elif t in h5_base:
                        b = borrow_5_to_4[t]
                        if f == "4F":
                            model.Add(x <= b)
                        elif f == "5F":
                            model.Add(x <= 1 - b)
                else:
                    teacher_floor = duty_home_floor_by_teacher.get(t)
                    if teacher_floor is None:
                        model.Add(x == 0)
                    elif teacher_floor != f:
                        model.Add(x == 0)

            model.Add(sum(floor_vars) <= 1)

            dd = model.NewBoolVar(f"duty_day[{t},{d}]")
            model.Add(dd == sum(floor_vars))
            duty_day[(t, d)] = dd

            if d != SATURDAY:
                for f in FLOORS:
                    model.Add(duty_floor[(t, d, f)] <= teach_pm1[(t, d)])

            trig = model.NewBoolVar(f"trigger_pm1_penalty[{t},{d}]")
            model.Add(trig <= teach_pm1[(t, d)])
            model.Add(trig <= 1 - duty_day[(t, d)])
            model.Add(trig >= teach_pm1[(t, d)] - duty_day[(t, d)])
            trigger_pm1[(t, d)] = trig

    if cfg.enable_weekday_pm1_requires_duty:
        mode = str(cfg.weekday_pm1_requires_duty_mode).strip().lower()
        if mode not in {"hard", "soft"}:
            mode = "hard"
        exempt_teachers = {
            str(t).strip()
            for t in cfg.weekday_pm1_requires_duty_exempt_teachers
            if str(t).strip()
        }
        weekday_days = [d for d in days if _day_order(d) <= 5]
        for t in head_teachers:
            if t in exempt_teachers:
                continue
            for d in weekday_days:
                pm1 = teach_pm1[(t, d)]
                duty = duty_day[(t, d)]
                if mode == "hard":
                    model.Add(pm1 <= duty)
                else:
                    viol = model.NewBoolVar(f"weekday_pm1_requires_duty_vio[{t},{d}]")
                    model.Add(viol == trigger_pm1[(t, d)])
                    extra_penalty_terms.append(viol)
                    register(
                        "head_weekday_pm1_requires_duty",
                        "Weekday PM1 requires same-day head duty (exempt list applied)",
                        cfg.w_weekday_pm1_requires_duty,
                        viol,
                        teacher=t,
                        day=d,
                        slot=PM1_KEY,
                    )

    for d in days:
        model.Add(sum(duty_floor[(t, d, "4F")] for t in candidate_45) == 1)
        model.Add(sum(duty_floor[(t, d, "5F")] for t in candidate_45) == 1)

    for d in days:
        if d == SATURDAY:
            continue
        members3f = duty_home_groups.get("3F", [])
        if not members3f:
            model.Add(0 == 1)
            hints.append(f"{d} 3F has no eligible duty teacher; model infeasible")
            continue
        model.Add(sum(duty_floor[(t, d, "3F")] for t in members3f) == 1)

    if SATURDAY in days:
        sat_3f = duty_floor.get(("\u5f20\u950b\u5251", SATURDAY, "3F"))
        if sat_3f is None:
            model.Add(0 == 1)
            hints.append("Saturday fixed 3F teacher missing duty_floor variable")
        else:
            model.Add(sat_3f == 1)
            model.Add(sum(duty_floor[(t, SATURDAY, "3F")] for t in head_teachers) == 1)

        sat_5f_teacher = "\u5f90\u5ef6\u5174"
        if sat_5f_teacher not in candidate_45:
            raise ValueError(f"Saturday fixed 5F teacher {sat_5f_teacher} is outside 4F/5F weekly-fair set")
        if sat_5f_teacher in h5_base:
            model.Add(borrow_5_to_4[sat_5f_teacher] == 0)
        elif sat_5f_teacher != t9_teacher:
            raise ValueError(f"Saturday fixed 5F teacher {sat_5f_teacher} cannot belong to final 5F set")
        sat_5f = duty_floor.get((sat_5f_teacher, SATURDAY, "5F"))
        if sat_5f is None:
            model.Add(0 == 1)
            hints.append(f"Saturday fixed 5F teacher missing duty_floor variable for {sat_5f_teacher}")
        else:
            model.Add(sat_5f == 1)
            model.Add(sum(duty_floor[(t, SATURDAY, "5F")] for t in candidate_45) == 1)

        sat_4f_candidates = []
        for teacher in ("\u674e\u653f", "\u4e25\u6606"):
            if teacher not in candidate_45:
                raise ValueError(f"Saturday 4F fixed candidate {teacher} is outside 4F/5F weekly-fair set")
            var = duty_floor.get((teacher, SATURDAY, "4F"))
            if var is not None:
                sat_4f_candidates.append(var)
        if not sat_4f_candidates:
            model.Add(0 == 1)
            hints.append("Saturday fixed 4F candidates missing duty_floor variables")
        else:
            model.Add(sum(sat_4f_candidates) == 1)
            model.Add(sum(duty_floor[(t, SATURDAY, "4F")] for t in candidate_45) == 1)

    weekly_duty_count_45f: Dict[str, cp_model.IntVar] = {}
    for t in candidate_45:
        cnt = model.NewIntVar(0, len(days), f"weekly_duty_count_45f[{t}]")
        model.Add(cnt == sum(duty_day[(t, d)] for d in days))
        weekly_duty_count_45f[t] = cnt

    for t in h4_base:
        c4 = model.NewIntVar(0, len(days), f"weekly_4f_count[{t}]")
        c5 = model.NewIntVar(0, len(days), f"weekly_5f_count[{t}]")
        model.Add(c4 == sum(duty_floor[(t, d, "4F")] for d in days))
        model.Add(c5 == sum(duty_floor[(t, d, "5F")] for d in days))
        model.Add(c4 == 1)
        model.Add(c5 == 0)
        model.Add(weekly_duty_count_45f[t] == 1)

    c4_t9 = model.NewIntVar(0, len(days), f"weekly_4f_count[{t9_teacher}]")
    c5_t9 = model.NewIntVar(0, len(days), f"weekly_5f_count[{t9_teacher}]")
    model.Add(c4_t9 == sum(duty_floor[(t9_teacher, d, "4F")] for d in days))
    model.Add(c5_t9 == sum(duty_floor[(t9_teacher, d, "5F")] for d in days))
    model.Add(c4_t9 == 0)
    model.Add(c5_t9 == 1)
    model.Add(weekly_duty_count_45f[t9_teacher] == 1)

    for t in h5_base:
        b = borrow_5_to_4[t]
        c4 = model.NewIntVar(0, len(days), f"weekly_4f_count[{t}]")
        c5 = model.NewIntVar(0, len(days), f"weekly_5f_count[{t}]")
        model.Add(c4 == sum(duty_floor[(t, d, "4F")] for d in days))
        model.Add(c5 == sum(duty_floor[(t, d, "5F")] for d in days))
        model.Add(c4 == 1).OnlyEnforceIf(b)
        model.Add(c5 == 0).OnlyEnforceIf(b)
        model.Add(c4 == 0).OnlyEnforceIf(b.Not())
        model.Add(c5 == 1).OnlyEnforceIf(b.Not())
        model.Add(weekly_duty_count_45f[t] == 1)

    days_except_sat = [d for d in days if d != SATURDAY]
    for t in duty_home_groups.get("3F", []):
        model.Add(sum(duty_floor[(t, d, "3F")] for d in days_except_sat) >= 2)

    duty_count_by_teacher: Dict[str, cp_model.IntVar] = {}
    trigger_count_by_teacher: Dict[str, cp_model.IntVar] = {}
    penalties: List[cp_model.IntVar] = list(extra_penalty_terms)

    for t in head_teachers:
        d_cnt = model.NewIntVar(0, len(days), f"duty_count[{t}]")
        model.Add(d_cnt == sum(duty_day[(t, d)] for d in days))
        duty_count_by_teacher[t] = d_cnt

        t_cnt = model.NewIntVar(0, len(days), f"trigger_count[{t}]")
        model.Add(t_cnt == sum(trigger_pm1[(t, d)] for d in days))
        trigger_count_by_teacher[t] = t_cnt

    return (
        duty_day,
        teach_pm1,
        penalties,
        duty_count_by_teacher,
        trigger_count_by_teacher,
        duty_floor,
        trigger_pm1,
        teaching_floor_by_teacher,
        duty_home_groups,
        allowed_duty_floors_by_teacher,
        borrow_5_to_4,
        weekly_duty_count_45f,
        h4_base,
        h5_base,
        t9_teacher,
        hints,
    )

def write_head_duty_vars_count(
    out_dir: Path,
    duty_day: Dict[Tuple[str, str], cp_model.IntVar],
    teach_pm1: Dict[Tuple[str, str], cp_model.IntVar],
    duty_floor: Dict[Tuple[str, str, str], cp_model.IntVar] | None = None,
    trigger_pm1: Dict[Tuple[str, str], cp_model.IntVar] | None = None,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "head_duty_vars_count.txt"
    lines = [
        "[Head Duty Vars Count]",
        f"DutyDayVars={len(duty_day)}",
        f"TeachPM1Vars={len(teach_pm1)}",
        f"DutyFloorVars={len(duty_floor or {})}",
        f"TriggerPM1Vars={len(trigger_pm1 or {})}",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def write_head_duty_hard_check(
    out_dir: Path,
    val: cp_model.CpSolver | cp_model.CpSolverSolutionCallback,
    duty_day: Dict[Tuple[str, str], cp_model.IntVar],
    teach_pm1: Dict[Tuple[str, str], cp_model.IntVar],
    head_teachers: List[str],
    days: List[str],
    duty_floor: Dict[Tuple[str, str, str], cp_model.IntVar] | None = None,
    floor_groups: Dict[str, List[str]] | None = None,
    floor_by_teacher: Dict[str, str] | None = None,
    allowed_duty_floors_by_teacher: Dict[str, Set[str]] | None = None,
    weekly_duty_count_45f: Dict[str, cp_model.IntVar] | None = None,
    borrow_5_to_4: Dict[str, cp_model.IntVar] | None = None,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "head_duty_hard_check.txt"

    floor_groups = floor_groups or {}
    floor_by_teacher = floor_by_teacher or {}
    allowed_duty_floors_by_teacher = allowed_duty_floors_by_teacher or {}
    weekly_duty_count_45f = weekly_duty_count_45f or {}
    borrow_5_to_4 = borrow_5_to_4 or {}
    duty_floor = duty_floor or {}

    lines = ["[Head Duty Hard Check]"]
    floor_bad = 0
    duty_without_pm1_non_sat = 0
    day_floor_not_exact = 0
    t45_not_eq_one = 0
    t3_under_two = 0

    for d in days:
        duty_cnt = sum(val.Value(duty_day[(t, d)]) for t in head_teachers if (t, d) in duty_day)
        pm1_cnt = sum(val.Value(teach_pm1[(t, d)]) for t in head_teachers if (t, d) in teach_pm1)
        lines.append(f"{d}: duty_day={duty_cnt} pm1={pm1_cnt}")

        for f in FLOORS:
            if not duty_floor:
                continue
            c = sum(val.Value(duty_floor[(t, d, f)]) for t in head_teachers if (t, d, f) in duty_floor)
            lines.append(f"  {f}: {c}")
            if c != 1:
                day_floor_not_exact += 1

    for t in head_teachers:
        for d in days:
            if d == SATURDAY:
                continue
            if (t, d) not in duty_day or (t, d) not in teach_pm1:
                continue
            if val.Value(duty_day[(t, d)]) == 1 and val.Value(teach_pm1[(t, d)]) == 0:
                duty_without_pm1_non_sat += 1

    if duty_floor:
        for (t, _d, f), x in duty_floor.items():
            if val.Value(x) != 1:
                continue
            allowed = allowed_duty_floors_by_teacher.get(t)
            if allowed:
                if f not in allowed:
                    floor_bad += 1
            else:
                tf = floor_by_teacher.get(t)
                if tf is not None and tf != f:
                    floor_bad += 1

    for t, v in weekly_duty_count_45f.items():
        if val.Value(v) != 1:
            t45_not_eq_one += 1

    for t in floor_groups.get("3F", []):
        c = sum(
            val.Value(duty_floor[(t, d, "3F")])
            for d in days
            if d != SATURDAY and (t, d, "3F") in duty_floor
        )
        if c < 2:
            t3_under_two += 1

    lines.append(f"IllegalFloorAssign={floor_bad}")
    lines.append(f"DutyWithoutPM1NonSat={duty_without_pm1_non_sat}")
    lines.append(f"DayFloorNotExact1={day_floor_not_exact}")
    lines.append(f"T4T5WeeklyNotEq1={t45_not_eq_one}")
    lines.append(f"T3NonSatLess2={t3_under_two}")
    if borrow_5_to_4:
        selected = [t for t, b in borrow_5_to_4.items() if val.Value(b) == 1]
        lines.append(f"Borrow5To4Selected={selected}")
    path.write_text("\n".join(lines), encoding="utf-8")

def write_head_duty_soft_report(
    out_dir: Path,
    val: cp_model.CpSolver | cp_model.CpSolverSolutionCallback,
    duty_day: Dict[Tuple[str, str], cp_model.IntVar],
    teach_pm1: Dict[Tuple[str, str], cp_model.IntVar],
    head_teachers: List[str],
    days: List[str],
    duty_count_by_teacher: Dict[str, cp_model.IntVar],
    trigger_count_by_teacher: Dict[str, cp_model.IntVar],
    _unused_w_excess_duty: int,
    w_pm1_penalty: int,
    weekly_duty_count_45f: Dict[str, cp_model.IntVar] | None = None,
    borrow_5_to_4: Dict[str, cp_model.IntVar] | None = None,
    h4_base: List[str] | None = None,
    h5_base: List[str] | None = None,
    t9_teacher: str = "",
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "head_duty_soft_report.txt"
    lines = ["[Head Duty Soft Report]"]

    total_trigger = 0
    for t in head_teachers:
        duty_cnt = sum(val.Value(duty_day[(t, d)]) for d in days if (t, d) in duty_day)
        pm1_cnt = sum(val.Value(teach_pm1[(t, d)]) for d in days if (t, d) in teach_pm1)
        d_cnt = val.Value(duty_count_by_teacher[t]) if t in duty_count_by_teacher else duty_cnt
        trig_cnt = val.Value(trigger_count_by_teacher[t]) if t in trigger_count_by_teacher else 0
        total_trigger += trig_cnt
        lines.append(
            f"{t}: duty_count={d_cnt} pm1_count={pm1_cnt} trigger_pm1_penalty_count={trig_cnt}"
        )

    lines.append(f"TriggerTotal={total_trigger}")
    lines.append(f"PM1PenaltyWeight={w_pm1_penalty}")
    lines.append(f"PM1PenaltyTotal={total_trigger * w_pm1_penalty}")

    weekly_duty_count_45f = weekly_duty_count_45f or {}
    borrow_5_to_4 = borrow_5_to_4 or {}
    h4_base = h4_base or []
    h5_base = h5_base or []

    if weekly_duty_count_45f:
        lines.append("WeeklyDutyCount45F=")
        for t in sorted(weekly_duty_count_45f):
            cnt = val.Value(weekly_duty_count_45f[t])
            lines.append(f"  {t}: weekly_count={cnt}")

    if borrow_5_to_4:
        selected = [t for t, b in borrow_5_to_4.items() if val.Value(b) == 1]
        lines.append(f"Borrow5To4Selected={selected}")

    if h4_base or h5_base:
        lines.append(f"H4_BASE={sorted(h4_base)}")
        lines.append(f"H5_BASE={sorted(h5_base)}")

    if t9_teacher:
        lines.append(f"T9_TEACHER={t9_teacher}")

    path.write_text("\n".join(lines), encoding="utf-8")

def write_head_duty_infeasible_hints(
    out_dir: Path,
    data: DayInputData,
    head_teachers: List[str],
    teach_pm1: Dict[Tuple[str, str], cp_model.IntVar],
    floor_groups: Dict[str, List[str]] | None = None,
    extra_hints: List[str] | None = None,
    cfg: HeadDutyConfig | None = None,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "head_duty_infeasible_hints.txt"
    days = _collect_days(data)
    lines = ["[Head Duty Infeasible Hints]"]

    if not head_teachers:
        lines.append("- HEAD_TEACHERS 为空")
    if SATURDAY not in days:
        lines.append("- 白天日历不含周六，周六特例未触发（可忽略）")
    if not teach_pm1:
        lines.append("- teach_pm1 为空，请检查 PM1 口径（下午1）是否匹配")

    fg = floor_groups or {}
    for f in FLOORS:
        if not fg.get(f):
            lines.append(f"- {f} 分组为空，无法满足“每天每楼层恰好1人”")

    if extra_hints:
        for h in extra_hints:
            lines.append(f"- {h}")

    pm1_requires_duty_hard = (
        cfg is None
        or (
            cfg.enable_weekday_pm1_requires_duty
            and str(cfg.weekday_pm1_requires_duty_mode or "hard").strip().lower() == "hard"
        )
    )
    if pm1_requires_duty_hard:
        lines.append("- 重点检查：每天每楼层=1 与 非周六 duty<=pm1 是否冲突")
    elif len(lines) == 1:
        lines.append("- 已将非周六 duty<=pm1 降为软约束；若仍不可行，请检查每天每楼层=1、楼层候选人和其他白天硬约束。")
    path.write_text("\n".join(lines), encoding="utf-8")


def extract_duty_results(
    val: cp_model.CpSolver | cp_model.CpSolverSolutionCallback,
    duty_day: Dict[Tuple[str, str], cp_model.IntVar],
    head_teachers: List[str],
    days: List[str],
) -> Dict[str, List[str]]:
    results: Dict[str, List[str]] = {}
    for d in days:
        names = []
        for t in head_teachers:
            v = duty_day.get((t, d))
            if v is not None and val.Value(v) == 1:
                names.append(t)
        results[d] = names
    return results
