# -*- coding: utf-8 -*-
"""
What：白天周末约束模块（weekend hard/soft constraints）。
Why：周末课量与教师负担更敏感，需要白名单/成对/单日/跨半天等规则。
How：基于白天变量 x[(班级,学科,Slot)] 与固定课 fixed_assign 统计教师-班级-时段；
    通过布尔变量线性化（AND/OR、覆盖约束）实现硬约束与软惩罚。
Weights：
    - weekend_constraints.cross_halfday_penalty（建议 50/100/200/400）：
      越大越倾向于同一半天集中授课，但可能牺牲学科均匀/可行性。
Diagnostics：
    - outputs/诊断/白天_周末诊断.txt（day_diagnostic_weekend.txt）
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Tuple, List, Set

from ortools.sat.python import cp_model

from scheduler.data.day_rules_reader import DayInputData, Slot
from scheduler.model.day_variables import DayVars
from scheduler.diagnostics.penalty_registry import register
from scheduler.model.constraints.teacher_targets import teacher_name_set
from scheduler.calendar import WEEKEND_DAYS

logger = logging.getLogger(__name__)


SUBJ_ALIAS = {
    "英语": "外语",
    "外语": "外语",
    "语文": "语文",
    "数学": "数学",
    "物理": "物理",
    "历史": "历史",
    "地理": "地理",
    "政治": "政治",
}


WEEKEND_WHITELIST = {
    "星期六": {"数学", "物理", "历史"},
    "星期日": {"语文", "外语", "地理", "政治", "化学", "生物"},
}


@dataclass
class WeekendConfig:
    enable_weekend_subject_whitelist: bool = True
    enable_weekend_double_period_same_class: bool = True
    enable_weekend_one_day_only: bool = True
    enable_weekend_cross_halfday_penalty: bool = True
    cross_halfday_penalty: int = 200
    enable_yjc_sun_cross_halfday_exempt: bool = True
    enable_yjc_sun_am12_pm12_rule: bool = True
    yjc_sun_am12_pm12_mode: str = "hard"
    w_yjc_sun_am12_pm12: int = 1000
    sun_cross_halfday_exempt_teachers: List[str] = field(default_factory=list)
    sunday_am12_pm12_teachers: List[str] = field(default_factory=list)
    enable_weekend_halfday_constraint: bool = True
    weekend_halfday_mode: str = "hard"  # soft|hard
    w_weekend_halfday: int = 3000


@dataclass
class WeekendDiagnostics:
    days: List[str]
    whitelist: Dict[str, Set[str]]
    teacher_weekend_hours: Dict[str, int]
    teacher_weekend_hours_odd: Dict[str, int]


def normalize_subject(name: str) -> str:
    """学科归一化（用于周末白名单匹配）。"""
    return SUBJ_ALIAS.get(name, name)


def _slot_index(slot: Slot) -> int:
    """将 Slot 映射为可排序索引（早自习/上午/下午）。"""
    if slot.block == "早自习":
        return 0
    if slot.block == "上午":
        return 1 + int(slot.period) - 1
    if slot.block == "下午":
        return 4 + int(slot.period)
    raise ValueError(f"未知时段: {slot.block}")


def _is_weekend_day(day: str) -> bool:
    """是否周末（星期六/星期日）。"""
    return day in WEEKEND_DAYS


def _collect_weekend_slots(data: DayInputData) -> List[Slot]:
    """收集周末可用时段。"""
    return [s for s in data.available_slots if _is_weekend_day(s.day)]


def _build_teacher_class_slot_bools(
    model: cp_model.CpModel,
    data: DayInputData,
    dv: DayVars,
) -> Dict[Tuple[str, str, Slot], cp_model.IntVar]:
    """
    构造 teach[teacher, class, slot] 二元变量。
    口径：同一(教师,班级,时段)的所有学科变量之和 == teach。
    """
    tcs_vars: Dict[Tuple[str, str, Slot], List[cp_model.IntVar]] = {}
    for (cls, subj, slot), var in dv.x.items():
        teacher = data.cls_subj_teacher.get((cls, subj))
        if not teacher:
            continue
        tcs_vars.setdefault((teacher, cls, slot), []).append(var)

    tcs_bools: Dict[Tuple[str, str, Slot], cp_model.IntVar] = {}
    for key, vars_list in tcs_vars.items():
        b = model.NewBoolVar(f"teach[{key[0]},{key[1]},{key[2].day},{key[2].block}{key[2].period}]")
        model.Add(sum(vars_list) == b)
        tcs_bools[key] = b
    return tcs_bools


def apply_weekend_subject_whitelist(model: cp_model.CpModel, data: DayInputData, dv: DayVars) -> None:
    """
    周末学科白名单（硬约束）。
    形式：若 day ∈ 周末 且 学科不在白名单，则 x=0。
    """
    # 归一化映射表日志
    mapping: Dict[str, str] = {}
    for (cls, subj) in data.cls_subj_teacher.keys():
        norm = normalize_subject(subj)
        if subj != norm:
            mapping[subj] = norm
    if mapping:
        logger.info("周末白名单学科归一化映射: %s", mapping)

    for (cls, subj, slot), var in dv.x.items():
        if not _is_weekend_day(slot.day):
            continue
        norm = normalize_subject(subj)
        allowed = WEEKEND_WHITELIST.get(slot.day, set())
        if norm not in allowed:
            model.Add(var == 0)


def apply_weekend_double_period_same_class(model: cp_model.CpModel, data: DayInputData, dv: DayVars) -> None:
    """
    周末成对连堂（硬约束）。
    形式：教师周末任一节有课必须被相邻两节同班覆盖；同一节不被多个对覆盖。
    """
    tcs_bools = _build_teacher_class_slot_bools(model, data, dv)

    # 按 day+class 收集 slot，排序并构建相邻对
    slots_by_day_cls: Dict[Tuple[str, str], List[Slot]] = {}
    for slot in _collect_weekend_slots(data):
        for cls in data.classes:
            slots_by_day_cls.setdefault((slot.day, cls), []).append(slot)

    # 预排序
    for key in slots_by_day_cls:
        slots_by_day_cls[key].sort(key=_slot_index)

    # pair 覆盖约束
    for (day, cls), slots in slots_by_day_cls.items():
        # 相邻对
        pairs: List[Tuple[Slot, Slot]] = []
        for i in range(len(slots) - 1):
            s1, s2 = slots[i], slots[i + 1]
            if _slot_index(s2) == _slot_index(s1) + 1:
                pairs.append((s1, s2))

        if not pairs:
            continue

        # 对每位老师建立 pair 变量
        teachers = sorted({t for (t, c, s) in tcs_bools.keys() if c == cls and s.day == day})
        for t in teachers:
            pair_vars_by_slot: Dict[Slot, List[cp_model.IntVar]] = {}
            for s1, s2 in pairs:
                if (t, cls, s1) not in tcs_bools or (t, cls, s2) not in tcs_bools:
                    continue
                p = model.NewBoolVar(f"pair[{t},{cls},{day},{s1.block}{s1.period}]")
                model.Add(p <= tcs_bools[(t, cls, s1)])
                model.Add(p <= tcs_bools[(t, cls, s2)])
                pair_vars_by_slot.setdefault(s1, []).append(p)
                pair_vars_by_slot.setdefault(s2, []).append(p)

            # 每节被覆盖 + 不重叠
            for slot in slots:
                key = (t, cls, slot)
                if key not in tcs_bools:
                    continue
                cover = pair_vars_by_slot.get(slot, [])
                if not cover:
                    # 如果某节有课但没有可用相邻对，直接禁止该节上课
                    model.Add(tcs_bools[key] == 0)
                    continue
                model.Add(sum(cover) >= tcs_bools[key])
                model.Add(sum(cover) <= 1)


def apply_weekend_one_day_only(model: cp_model.CpModel, data: DayInputData, dv: DayVars) -> None:
    """
    周末同一教师不得跨两天（硬约束）。
    形式：teach_on_sat + teach_on_sun <= 1。
    """
    tcs_bools = _build_teacher_class_slot_bools(model, data, dv)
    teachers = sorted({t for (_c, _s), t in data.cls_subj_teacher.items() if t})

    for t in teachers:
        sat_vars = [b for (tt, _c, s), b in tcs_bools.items() if tt == t and s.day == "星期六"]
        sun_vars = [b for (tt, _c, s), b in tcs_bools.items() if tt == t and s.day == "星期日"]

        teach_sat = model.NewBoolVar(f"teach_on_sat[{t}]")
        teach_sun = model.NewBoolVar(f"teach_on_sun[{t}]")

        for v in sat_vars:
            model.Add(v <= teach_sat)
        for v in sun_vars:
            model.Add(v <= teach_sun)

        if sat_vars:
            model.Add(sum(sat_vars) >= teach_sat)
        else:
            model.Add(teach_sat == 0)

        if sun_vars:
            model.Add(sum(sun_vars) >= teach_sun)
        else:
            model.Add(teach_sun == 0)

        model.Add(teach_sat + teach_sun <= 1)


def apply_weekend_cross_halfday_penalty(
    model: cp_model.CpModel,
    data: DayInputData,
    dv: DayVars,
    penalty: int,
    yjc_sun_exempt: bool = True,
    sun_exempt_teachers: List[str] | None = None,
) -> List[cp_model.IntVar]:
    """
    周末跨半天惩罚（软约束）。
    cross=1 表示同日跨上午/下午；用于目标函数罚分。
    """
    tcs_bools = _build_teacher_class_slot_bools(model, data, dv)
    teachers = sorted({t for (_c, _s), t in data.cls_subj_teacher.items() if t})

    penalties: List[cp_model.IntVar] = []
    sunday_exempt = teacher_name_set(sun_exempt_teachers or [])

    for t in teachers:
        for day in WEEKEND_DAYS:
            if yjc_sun_exempt and day == "星期日" and t in sunday_exempt:
                continue
            am_vars = [
                b
                for (tt, _c, s), b in tcs_bools.items()
                if tt == t and s.day == day and s.block in ("早自习", "上午")
            ]
            pm_vars = [
                b
                for (tt, _c, s), b in tcs_bools.items()
                if tt == t and s.day == day and s.block == "下午"
            ]

            has_am = model.NewBoolVar(f"has_am[{t},{day}]")
            has_pm = model.NewBoolVar(f"has_pm[{t},{day}]")
            cross = model.NewBoolVar(f"cross_halfday[{t},{day}]")

            for v in am_vars:
                model.Add(v <= has_am)
            for v in pm_vars:
                model.Add(v <= has_pm)

            if am_vars:
                model.Add(sum(am_vars) >= has_am)
            else:
                model.Add(has_am == 0)

            if pm_vars:
                model.Add(sum(pm_vars) >= has_pm)
            else:
                model.Add(has_pm == 0)

            model.Add(cross >= has_am + has_pm - 1)
            penalties.append(cross)  # weight: weekend_constraints.cross_halfday_penalty（建议 50~400；越大越倾向同半天集中）

    return penalties


def apply_weekend_halfday_constraint(
    model: cp_model.CpModel,
    data: DayInputData,
    dv: DayVars,
    *,
    enabled: bool = True,
    mode: str = "hard",
    weight: int = 3000,
) -> List[cp_model.IntVar]:
    """
    周末教师课时需集中在半天（soft/hard 可切换）。
    - hard: 同一教师同一周末日不能同时上午有课且下午有课
    - soft: 每出现一次“上午+下午”组合计一次罚分
    """
    if not enabled:
        return []

    mode_norm = _normalize_mode(mode, "hard")
    tcs_bools = _build_teacher_class_slot_bools(model, data, dv)
    teachers = sorted({t for (_c, _s), t in data.cls_subj_teacher.items() if t})
    penalties: List[cp_model.IntVar] = []

    for t in teachers:
        for day in WEEKEND_DAYS:
            am_vars = [
                b
                for (tt, _c, s), b in tcs_bools.items()
                if tt == t and s.day == day and s.block == "上午"
            ]
            pm_vars = [
                b
                for (tt, _c, s), b in tcs_bools.items()
                if tt == t and s.day == day and s.block == "下午"
            ]
            fixed_am = any(
                slot.day == day and slot.block == "上午" and data.cls_subj_teacher.get((cls, subj)) == t
                for (cls, slot), subj in data.fixed_assign.items()
            )
            fixed_pm = any(
                slot.day == day and slot.block == "下午" and data.cls_subj_teacher.get((cls, subj)) == t
                for (cls, slot), subj in data.fixed_assign.items()
            )
            has_am = model.NewBoolVar(f"weekend_halfday_has_am[{t},{day}]")
            has_pm = model.NewBoolVar(f"weekend_halfday_has_pm[{t},{day}]")
            if fixed_am:
                model.Add(has_am == 1)
            elif am_vars:
                model.Add(sum(am_vars) >= has_am)
                for v in am_vars:
                    model.Add(v <= has_am)
            else:
                model.Add(has_am == 0)
            if fixed_pm:
                model.Add(has_pm == 1)
            elif pm_vars:
                model.Add(sum(pm_vars) >= has_pm)
                for v in pm_vars:
                    model.Add(v <= has_pm)
            else:
                model.Add(has_pm == 0)

            if mode_norm == "hard":
                model.Add(has_am + has_pm <= 1)
            else:
                viol = model.NewBoolVar(f"weekend_halfday_vio[{t},{day}]")
                model.Add(viol <= has_am)
                model.Add(viol <= has_pm)
                model.Add(viol >= has_am + has_pm - 1)
                penalties.append(viol)
                register(
                    "weekend_halfday_constraint",
                    "周末课程集中半天",
                    weight,
                    viol,
                    teacher=t,
                    day=day,
                    source_module="scheduler/model/constraints/day_weekend_constraints.py",
                    constraint_category="schedule_pattern",
                    mode="soft",
                    weight_key="day_constraints.w_weekend_halfday",
                )
    return penalties


def _normalize_mode(mode: str, default: str = "hard") -> str:
    m = str(mode or default).strip().lower()
    if m not in ("hard", "soft"):
        return default
    return m


def apply_yjc_sunday_am12_pm12_rule(
    model: cp_model.CpModel,
    data: DayInputData,
    dv: DayVars,
    *,
    enabled: bool = True,
    mode: str = "hard",
    teachers: List[str] | None = None,
) -> List[cp_model.IntVar]:
    """
    指定教师周日白天禁排组合：上午1+上午2+下午1+下午2。
    - hard: 禁止组合（combo == 0）
    - soft: combo 作为罚分变量（触发一次计一次）
    """
    if not enabled:
        return []

    day = "星期日"
    mode_norm = _normalize_mode(mode, "hard")
    all_teachers = {t for (_c, _s), t in data.cls_subj_teacher.items() if t}
    target_teachers = [t for t in teacher_name_set(teachers or []) if t in all_teachers]
    if not target_teachers:
        return []

    slot_defs = {
        "am1": ("上午", 1),
        "am2": ("上午", 2),
        "pm1": ("下午", 1),
        "pm2": ("下午", 2),
    }
    penalties: List[cp_model.IntVar] = []

    for teacher in target_teachers:
        has_slot_vars: Dict[str, cp_model.IntVar] = {}
        for tag, (block, period) in slot_defs.items():
            vars_list: List[cp_model.IntVar] = []
            fixed_hit = False
            for (cls, subj, slot), var in dv.x.items():
                if slot.day != day or slot.block != block or int(slot.period) != period:
                    continue
                if data.cls_subj_teacher.get((cls, subj)) == teacher:
                    vars_list.append(var)
            for (cls, slot), subj in data.fixed_assign.items():
                if slot.day != day or slot.block != block or int(slot.period) != period:
                    continue
                if data.cls_subj_teacher.get((cls, subj)) == teacher:
                    fixed_hit = True
                    break

            has_slot = model.NewBoolVar(f"target_sun_{tag}[{teacher},{day}]")
            if fixed_hit:
                model.Add(has_slot == 1)
            elif vars_list:
                model.Add(sum(vars_list) >= has_slot)
                for v in vars_list:
                    model.Add(v <= has_slot)
            else:
                model.Add(has_slot == 0)
            has_slot_vars[tag] = has_slot

        combo = model.NewBoolVar(f"target_sun_am12_pm12_combo[{teacher},{day}]")
        for v in has_slot_vars.values():
            model.Add(combo <= v)
        model.Add(combo >= sum(has_slot_vars.values()) - 3)

        if mode_norm == "soft":
            penalties.append(combo)
        else:
            model.Add(combo == 0)
    return penalties


def check_weekend_feasibility_inputs(data: DayInputData) -> WeekendDiagnostics:
    """周末可行性自检：统计每位教师周末课时与奇偶性。"""
    # 统计每位教师周末需求总课时数
    teacher_weekend_hours: Dict[str, int] = {}
    for (cls, subj), (req_e, req_w, req_we) in data.req_hours.items():
        teacher = data.cls_subj_teacher.get((cls, subj))
        if not teacher:
            continue
        teacher_weekend_hours[teacher] = teacher_weekend_hours.get(teacher, 0) + int(req_we)

    teacher_weekend_hours_odd = {t: h for t, h in teacher_weekend_hours.items() if h % 2 != 0 and h != 0}

    days = sorted({s.day for s in data.available_slots})
    return WeekendDiagnostics(
        days=days,
        whitelist=WEEKEND_WHITELIST,
        teacher_weekend_hours=teacher_weekend_hours,
        teacher_weekend_hours_odd=teacher_weekend_hours_odd,
    )


def write_weekend_diagnostic(
    out_dir: Path,
    diag: WeekendDiagnostics,
    status_name: str,
    suspected_conflicts: List[str],
) -> None:
    """输出周末诊断文件（供定位无解/冲突来源）。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "day_diagnostic_weekend.txt"
    lines: List[str] = []
    lines.append("[Weekend Diagnostic]")
    lines.append(f"DAYS={diag.days}")
    lines.append(f"Whitelist={diag.whitelist}")
    lines.append("TeacherWeekendHours=")
    for t, h in sorted(diag.teacher_weekend_hours.items()):
        lines.append(f"  {t}: {h} ({'odd' if h % 2 != 0 else 'even'})")
    if diag.teacher_weekend_hours_odd:
        lines.append("WARN: odd weekend hours teachers:")
        for t, h in sorted(diag.teacher_weekend_hours_odd.items()):
            lines.append(f"  {t}: {h}")
    lines.append(f"SolveStatus={status_name}")
    if suspected_conflicts:
        lines.append("PossibleConflicts=")
        for s in suspected_conflicts:
            lines.append(f"  - {s}")
    path.write_text("\n".join(lines), encoding="utf-8")
