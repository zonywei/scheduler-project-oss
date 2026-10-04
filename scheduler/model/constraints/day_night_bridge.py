# -*- coding: utf-8 -*-
"""
What：白天-晚自习联动（bridge constraints）。
Why：同一教师白天/晚自习负担需要联动协调，避免周末+次日过劳。
How：从 day_vars 聚合 day_has_*、day_load，与 night on_teacher_day 组成桥接变量，
    通过线性化(viol>=...)构造软约束；部分硬约束直接 Add。
Weights：
    - day_night_link.w1（建议 20/50/100/200）：晚自习⇒当天下午有课 违例惩罚
    - day_night_link.w3（建议 100/200/400）：晚自习⇒次日AM1 违例惩罚
    - day_night_link.w4（建议 80/120/200）：重负荷⇒晚自习 违例惩罚
    - day_night_link.w_two_class_empty_day_no_night（建议 100/200/400）：空整天晚自习违例惩罚
Diagnostics：
    - outputs/诊断/联动桥_审计.txt
    - outputs/诊断/联动约束_检查.txt
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Set, Tuple

from ortools.sat.python import cp_model

from scheduler.data.day_rules_reader import DayInputData, Slot
from scheduler.model.day_variables import DayVars
from scheduler.diagnostics.penalty_registry import register
from scheduler.model.constraints.teacher_targets import teacher_name_set
from scheduler.calendar import (
    FRIDAY,
    MONDAY,
    SUNDAY,
    WEEKDAY_DAYS,
    day_night_bridge_days,
    is_weekday_day,
)

WEEKDAYS = WEEKDAY_DAYS


@dataclass
class LinkConfig:
    enable_day_night_link: bool = True
    w1: int = 50
    enable_night_requires_day: bool = True
    night_requires_day_mode: str = "hard"  # hard|soft
    w_night_requires_day: int = 3000
    enable_sun_night_no_mon_am1: bool = True
    sun_night_no_mon_am1_mode: str = "hard"  # hard|soft
    w_sun_night_no_mon_am1: int = 2000
    enable_sun_pm_night_no_mon_am: bool = True
    sun_pm_night_no_mon_am_mode: str = "hard"  # hard|soft
    w_sun_pm_night_no_mon_am: int = 2000
    w3: int = 200
    heavy_load: int = 4
    w4: int = 120
    enable_two_class_empty_day_no_night: bool = True
    w_two_class_empty_day_no_night: int = 200
    weekday_load2_no_night_teachers: List[str] = field(default_factory=list)


def _slot_key(slot: Slot) -> str:
    """Slot 映射到字符串键（block+period）。"""
    return f"{slot.block}{slot.period}"


def _is_weekday(day: str) -> bool:
    """是否工作日（周一到周五）。"""
    return is_weekday_day(day)


def _is_am1(slot: Slot) -> bool:
    """是否上午第1节。"""
    return slot.block == "上午" and int(slot.period) == 1


def _is_am2(slot: Slot) -> bool:
    """是否上午第2节。"""
    return slot.block == "上午" and int(slot.period) == 2


def _is_pm(slot: Slot) -> bool:
    """是否下午节次。"""
    return slot.block == "下午"


def _collect_day_teacher_vars(
    data: DayInputData,
    dv: DayVars,
    bridge_days: Set[str],
) -> Dict[str, Dict[str, Dict[Slot, List[cp_model.IntVar]]]]:
    """聚合白天授课变量（按教师/日期/时段）。"""
    out: Dict[str, Dict[str, Dict[Slot, List[cp_model.IntVar]]]] = {}
    for (cls, subj, slot), var in dv.x.items():
        if slot.day not in bridge_days:
            continue
        teacher = data.cls_subj_teacher.get((cls, subj))
        if not teacher:
            continue
        out.setdefault(teacher, {}).setdefault(slot.day, {}).setdefault(slot, []).append(var)
    return out


def build_bridge_vars(
    model: cp_model.CpModel,
    day_data: DayInputData,
    day_vars: DayVars,
    night_vars: dict,
    night_ctx: dict,
) -> Dict[str, Dict]:
    """
    构建桥接变量：
    - day_has_pm/am1/am2, day_load, day_has_any_am_pm
    - sun_has_pm, night_has
    固定课 fixed_assign 计入。
    """
    days = night_ctx["days"]
    bridge_day_scope = set(day_night_bridge_days(days))
    teacher_vars = _collect_day_teacher_vars(day_data, day_vars, bridge_day_scope)
    day_teachers = set(teacher_vars.keys())
    night_teachers = set(night_vars.get("all_teachers", []))
    teachers = sorted(day_teachers | night_teachers)

    day_has_pm: Dict[Tuple[str, str], cp_model.IntVar] = {}
    day_has_am1: Dict[Tuple[str, str], cp_model.IntVar] = {}
    day_has_am2: Dict[Tuple[str, str], cp_model.IntVar] = {}
    day_load: Dict[Tuple[str, str], cp_model.IntVar] = {}
    day_load_am_pm: Dict[Tuple[str, str], cp_model.IntVar] = {}
    sun_has_pm: Dict[str, cp_model.IntVar] = {}

    night_has = night_vars.get("on_teacher_day", {})

    # fixed assign counts per teacher/day/slot
    fixed_by_teacher_day: Dict[Tuple[str, str], int] = {}
    fixed_by_teacher_day_slot: Dict[Tuple[str, str, str], int] = {}
    for (cls, slot), subj in day_data.fixed_assign.items():
        t = day_data.cls_subj_teacher.get((cls, subj))
        if not t:
            continue
        fixed_by_teacher_day[(t, slot.day)] = fixed_by_teacher_day.get((t, slot.day), 0) + 1
        fixed_by_teacher_day_slot[(t, slot.day, _slot_key(slot))] = (
            fixed_by_teacher_day_slot.get((t, slot.day, _slot_key(slot)), 0) + 1
        )

    # fixed assign maps
    fixed_by_teacher_day: Dict[Tuple[str, str], int] = {}
    fixed_by_teacher_day_slot: Dict[Tuple[str, str, str], int] = {}
    for (cls, slot), subj in day_data.fixed_assign.items():
        t = day_data.cls_subj_teacher.get((cls, subj))
        if not t:
            continue
        fixed_by_teacher_day[(t, slot.day)] = fixed_by_teacher_day.get((t, slot.day), 0) + 1
        fixed_by_teacher_day_slot[(t, slot.day, _slot_key(slot))] = (
            fixed_by_teacher_day_slot.get((t, slot.day, _slot_key(slot)), 0) + 1
        )

    day_has_any_am_pm: Dict[Tuple[str, str], cp_model.IntVar] = {}

    for t in teachers:
        for d in days:
            slots = teacher_vars.get(t, {}).get(d, {})
            am1_vars = [v for s, vars_list in slots.items() if _is_am1(s) for v in vars_list]
            am2_vars = [v for s, vars_list in slots.items() if _is_am2(s) for v in vars_list]
            pm_vars = [v for s, vars_list in slots.items() if _is_pm(s) for v in vars_list]
            all_vars = [v for vars_list in slots.values() for v in vars_list]

            am1_fixed = 1 if fixed_by_teacher_day_slot.get((t, d, "上午1"), 0) > 0 else 0
            am2_fixed = 1 if fixed_by_teacher_day_slot.get((t, d, "上午2"), 0) > 0 else 0
            pm_fixed = 1 if any(
                fixed_by_teacher_day_slot.get((t, d, f"下午{i}"), 0) > 0 for i in range(1, 10)
            ) else 0
            total_fixed = fixed_by_teacher_day.get((t, d), 0)

            am1 = model.NewBoolVar(f"day_has_am1[{t},{d}]")
            if am1_fixed > 0:
                model.Add(am1 == 1)
            elif am1_vars:
                for v in am1_vars:
                    model.Add(am1 >= v)
                model.Add(am1 <= sum(am1_vars))
            else:
                model.Add(am1 == 0)

            am2 = model.NewBoolVar(f"day_has_am2[{t},{d}]")
            if am2_fixed > 0:
                model.Add(am2 == 1)
            elif am2_vars:
                for v in am2_vars:
                    model.Add(am2 >= v)
                model.Add(am2 <= sum(am2_vars))
            else:
                model.Add(am2 == 0)

            pm = model.NewBoolVar(f"day_has_pm[{t},{d}]")
            if pm_fixed > 0:
                model.Add(pm == 1)
            elif pm_vars:
                for v in pm_vars:
                    model.Add(pm >= v)
                model.Add(pm <= sum(pm_vars))
            else:
                model.Add(pm == 0)

            load = model.NewIntVar(0, len(all_vars) + total_fixed, f"day_load[{t},{d}]")
            model.Add(load == sum(all_vars) + total_fixed)

            day_has_pm[(t, d)] = pm
            day_has_am1[(t, d)] = am1
            day_has_am2[(t, d)] = am2
            day_load[(t, d)] = load

            # day has any AM/PM (exclude early)
            has_any = model.NewBoolVar(f"day_has_any[{t},{d}]")
            ampm_vars = [v for s, vars_list in slots.items() if s.block in ("上午", "下午") for v in vars_list]
            ampm_fixed_cnt = sum(
                fixed_by_teacher_day_slot.get((t, d, f"上午{i}"), 0) for i in range(1, 10)
            ) + sum(
                fixed_by_teacher_day_slot.get((t, d, f"下午{i}"), 0) for i in range(1, 10)
            )
            ampm_load = model.NewIntVar(0, len(ampm_vars) + ampm_fixed_cnt, f"day_load_ampm[{t},{d}]")
            model.Add(ampm_load == sum(ampm_vars) + ampm_fixed_cnt)
            day_load_am_pm[(t, d)] = ampm_load
            ampm_fixed = 1 if any(
                fixed_by_teacher_day_slot.get((t, d, f"上午{i}"), 0) > 0 for i in range(1, 10)
            ) or any(
                fixed_by_teacher_day_slot.get((t, d, f"下午{i}"), 0) > 0 for i in range(1, 10)
            ) else 0
            if ampm_fixed > 0:
                model.Add(has_any == 1)
            elif ampm_vars:
                model.Add(sum(ampm_vars) >= has_any)
                for v in ampm_vars:
                    model.Add(v <= has_any)
            else:
                model.Add(has_any == 0)
            day_has_any_am_pm[(t, d)] = has_any

        if SUNDAY in days:
            sun_has_pm[t] = day_has_pm.get((t, SUNDAY), model.NewConstant(0))
        else:
            sun_has_pm[t] = model.NewConstant(0)

    return {
        "teachers": teachers,
        "days": days,
        "day_has_pm": day_has_pm,
        "day_has_am1": day_has_am1,
        "day_has_am2": day_has_am2,
        "day_load": day_load,
        "day_load_am_pm": day_load_am_pm,
        "sun_has_pm": sun_has_pm,
        "night_has": night_has,
        "checkin_m": night_vars.get("checkin_m", {}),
        "checkin_f": night_vars.get("checkin_f", {}),
        "day_has_any_am_pm": day_has_any_am_pm,
        "cls_subj_teacher": day_data.cls_subj_teacher,
        "req_hours": day_data.req_hours,
    }


def add_link_constraints(
    model: cp_model.CpModel,
    bridge: dict,
    cfg: LinkConfig,
) -> Tuple[List[cp_model.IntVar], Dict[str, dict]]:
    """
    添加联动约束（硬+软）。
    返回：penalties（软惩罚变量）与 stats（诊断统计）。
    """
    penalties: List[cp_model.IntVar] = []
    stats: Dict[str, dict] = {
        "viol1": [],
        "viol3": [],
        "viol4": [],
        "viol_sun_pm_night_no_mon_am": [],
        "viol_sun_night_no_mon_am1": [],
        "viol1_by_teacher": {},
        "viol3_by_teacher": {},
        "viol4_by_teacher": {},
        "viol_sun_pm_night_no_mon_am_by_teacher": {},
        "viol_sun_night_no_mon_am1_by_teacher": {},
        "viol5": [],
        "viol5_by_teacher": {},
        "viol_night_requires_day": [],
        "viol_night_requires_day_by_teacher": {},
    }

    if not cfg.enable_day_night_link:
        return penalties, stats

    teachers = bridge["teachers"]
    days = bridge["days"]
    day_has_pm = bridge["day_has_pm"]
    day_has_am1 = bridge["day_has_am1"]
    day_has_am2 = bridge["day_has_am2"]
    day_load = bridge["day_load"]
    sun_has_pm = bridge["sun_has_pm"]
    night_has = bridge["night_has"]
    checkin_m = bridge.get("checkin_m", {})
    checkin_f = bridge.get("checkin_f", {})
    day_has_any_am_pm = bridge.get("day_has_any_am_pm", {})
    day_load_am_pm = bridge.get("day_load_am_pm", {})

    # Night duty = evening class OR night dorm-checkin.
    night_duty: Dict[Tuple[str, str], cp_model.IntVar] = {}
    for t in teachers:
        for d in days:
            night = night_has.get((t, d), model.NewConstant(0))
            cm = checkin_m.get((t, d), model.NewConstant(0))
            cf = checkin_f.get((t, d), model.NewConstant(0))
            duty = model.NewBoolVar(f"night_duty[{t},{d}]")
            model.Add(duty >= night)
            model.Add(duty >= cm)
            model.Add(duty >= cf)
            model.Add(duty <= night + cm + cf)
            night_duty[(t, d)] = duty

    # 1) night => afternoon (soft)
    for t in teachers:
        for d in days:
            pm = day_has_pm.get((t, d), model.NewConstant(0))
            night = night_has.get((t, d), model.NewConstant(0))
            viol = model.NewBoolVar(f"link_viol1[{t},{d}]")
            model.Add(viol >= night - pm)
            stats["viol1"].append(viol)
            stats["viol1_by_teacher"].setdefault(t, []).append(viol)
            penalties.append(cfg.w1 * viol)
            register(
                rule_id="day_night_link_w1",
                rule_name="晚自习需当天下午有课",
                weight=cfg.w1,
                var=viol,
                teacher=t,
                day=d,
                constraint_category="linkage",
                source_module="scheduler/model/constraints/day_night_bridge.py",
                weight_key="day_night_link.w1",
                description="当日有晚自习但当天下午无课时触发罚分",
            )  # weight: day_night_link.w1（建议 20~200）

    # 1.5) no day class => no night duty (switchable hard/soft)
    if cfg.enable_night_requires_day:
        mode = str(cfg.night_requires_day_mode or "hard").strip().lower()
        mode = mode if mode in {"hard", "soft"} else "hard"
        for t in teachers:
            for d in days:
                has_day = day_has_any_am_pm.get((t, d), model.NewConstant(0))
                duty = night_duty.get((t, d), model.NewConstant(0))
                if mode == "hard":
                    model.Add(duty <= has_day)
                else:
                    viol = model.NewBoolVar(f"night_requires_day_vio[{t},{d}]")
                    model.Add(duty - has_day <= viol)
                    stats["viol_night_requires_day"].append(viol)
                    stats["viol_night_requires_day_by_teacher"].setdefault(t, []).append(viol)
                    penalties.append(cfg.w_night_requires_day * viol)
                    register(
                        rule_id="day_night_link_night_requires_day",
                        rule_name="白天无课不得安排晚自习/晚查寝",
                        weight=cfg.w_night_requires_day,
                        var=viol,
                        teacher=t,
                        day=d,
                        constraint_category="linkage",
                        source_module="scheduler/model/constraints/day_night_bridge.py",
                        weight_key="day_night_link.w_night_requires_day",
                        mode="soft",
                        description="当日白天无课但安排了晚自习或晚查寝时触发罚分",
                    )

    # 2) Sunday PM + Sunday night should not force Monday morning overload.
    if cfg.enable_sun_pm_night_no_mon_am and SUNDAY in days and MONDAY in days:
        mode = str(cfg.sun_pm_night_no_mon_am_mode or "hard").strip().lower()
        mode = mode if mode in {"hard", "soft"} else "hard"
        for t in teachers:
            sun_pm = sun_has_pm.get(t, model.NewConstant(0))
            sun_night = night_has.get((t, SUNDAY), model.NewConstant(0))
            mon_am1 = day_has_am1.get((t, MONDAY), model.NewConstant(0))
            mon_am2 = day_has_am2.get((t, MONDAY), model.NewConstant(0))
            if mode == "hard":
                model.Add(sun_pm + sun_night + mon_am1 <= 2)
                model.Add(sun_pm + sun_night + mon_am2 <= 2)
            else:
                for suffix, mon_am in (("am1", mon_am1), ("am2", mon_am2)):
                    viol = model.NewBoolVar(f"sun_pm_night_no_mon_{suffix}_vio[{t}]")
                    model.Add(viol >= sun_pm + sun_night + mon_am - 2)
                    stats["viol_sun_pm_night_no_mon_am"].append(viol)
                    stats["viol_sun_pm_night_no_mon_am_by_teacher"].setdefault(t, []).append(viol)
                    penalties.append(cfg.w_sun_pm_night_no_mon_am * viol)
                    register(
                        rule_id="day_night_link_sun_pm_night_no_mon_am",
                        rule_name="周日白天加晚自习后周一上午禁排",
                        weight=cfg.w_sun_pm_night_no_mon_am,
                        var=viol,
                        teacher=t,
                        day=SUNDAY,
                        constraint_category="linkage",
                        source_module="scheduler/model/constraints/day_night_bridge.py",
                        weight_key="day_night_link.w_sun_pm_night_no_mon_am",
                        mode="soft",
                        description="周日下午有课且周日晚自习后，周一上午1/2仍排课时触发罚分",
                    )

    # 2.1) Sunday night class => Monday AM1 no class (switchable hard/soft)
    sun_day = SUNDAY
    mon_day = MONDAY
    if cfg.enable_sun_night_no_mon_am1 and sun_day in days and mon_day in days:
        mode = str(cfg.sun_night_no_mon_am1_mode or "hard").strip().lower()
        mode = mode if mode in {"hard", "soft"} else "hard"
        for t in teachers:
            sun_night = night_has.get((t, sun_day), model.NewConstant(0))
            mon_am1 = day_has_am1.get((t, mon_day), model.NewConstant(0))
            if mode == "hard":
                model.Add(sun_night + mon_am1 <= 1)
            else:
                viol = model.NewBoolVar(f"sun_night_no_mon_am1_vio[{t}]")
                model.Add(viol >= sun_night + mon_am1 - 1)
                stats["viol_sun_night_no_mon_am1"].append(viol)
                stats["viol_sun_night_no_mon_am1_by_teacher"].setdefault(t, []).append(viol)
                penalties.append(cfg.w_sun_night_no_mon_am1 * viol)
                register(
                    rule_id="day_night_link_sun_night_no_mon_am1",
                    rule_name="周日晚自习=>周一上午1禁排",
                    weight=cfg.w_sun_night_no_mon_am1,
                    var=viol,
                    teacher=t,
                    day=sun_day,
                    constraint_category="linkage",
                    source_module="scheduler/model/constraints/day_night_bridge.py",
                    weight_key="day_night_link.w_sun_night_no_mon_am1",
                    mode="soft",
                    description="若周日有晚自习，则周一上午1不得排课",
                )

    # 2.2) weekday daytime load==2 (exclude early) => no night class (hard, configurable teachers)
    load2_no_night_teachers = teacher_name_set(cfg.weekday_load2_no_night_teachers)
    for t in teachers:
        if t not in load2_no_night_teachers:
            continue
        for d in WEEKDAYS:
            if d not in days:
                continue
            load_ampm = day_load_am_pm.get((t, d))
            if load_ampm is None:
                continue
            is_two = model.NewBoolVar(f"wd_day_load2_no_night[{t},{d}]")
            model.Add(load_ampm == 2).OnlyEnforceIf(is_two)
            model.Add(load_ampm != 2).OnlyEnforceIf(is_two.Not())
            night = night_has.get((t, d), model.NewConstant(0))
            model.Add(night == 0).OnlyEnforceIf(is_two)

    # 3) night => next day AM1 (soft, Mon..Thu)
    for i in range(len(days) - 1):
        d = days[i]
        d_next = days[i + 1]
        if d not in WEEKDAYS:
            continue
        if d_next not in WEEKDAYS:
            continue
        if d == FRIDAY:
            continue
        for t in teachers:
            night = night_has.get((t, d), model.NewConstant(0))
            am1 = day_has_am1.get((t, d_next), model.NewConstant(0))
            viol = model.NewBoolVar(f"link_viol3[{t},{d}]")
            model.Add(viol >= night + am1 - 1)
            stats["viol3"].append(viol)
            stats["viol3_by_teacher"].setdefault(t, []).append(viol)
            penalties.append(cfg.w3 * viol)
            register(
                rule_id="day_night_link_w3",
                rule_name="晚自习=>次日AM1",
                weight=cfg.w3,
                var=viol,
                teacher=t,
                day=d,
                constraint_category="linkage",
                source_module="scheduler/model/constraints/day_night_bridge.py",
                weight_key="day_night_link.w3",
            )  # weight: day_night_link.w3（建议 100~400）

    # 4) heavy day => night (soft)
    for t in teachers:
        for d in days:
            load = day_load.get((t, d), model.NewConstant(0))
            heavy = model.NewBoolVar(f"day_heavy[{t},{d}]")
            model.Add(load >= cfg.heavy_load).OnlyEnforceIf(heavy)
            model.Add(load <= cfg.heavy_load - 1).OnlyEnforceIf(heavy.Not())
            night = night_has.get((t, d), model.NewConstant(0))
            viol = model.NewBoolVar(f"link_viol4[{t},{d}]")
            model.Add(viol >= heavy + night - 1)
            stats["viol4"].append(viol)
            stats["viol4_by_teacher"].setdefault(t, []).append(viol)
            penalties.append(cfg.w4 * viol)
            register(
                rule_id="day_night_link_w4",
                rule_name="重负荷=>晚自习惩罚",
                weight=cfg.w4,
                var=viol,
                teacher=t,
                day=d,
                constraint_category="linkage",
                source_module="scheduler/model/constraints/day_night_bridge.py",
                weight_key="day_night_link.w4",
            )  # weight: day_night_link.w4（建议 80~200）

    # 5) two-class low-hour teacher: empty weekday -> no night (soft)
    if cfg.enable_two_class_empty_day_no_night:
        # teacher -> classes set
        teacher_classes: Dict[str, Set[str]] = {}
        for (cls, subj), tch in bridge.get("cls_subj_teacher", {}).items():
            teacher_classes.setdefault(tch, set()).add(cls)
        # weekday total hours (exclude early/night)
        teacher_weekday_hours: Dict[str, int] = {}
        for (cls, subj), tch in bridge.get("cls_subj_teacher", {}).items():
            req = bridge.get("req_hours", {}).get((cls, subj))
            if not req:
                continue
            _req_e, req_w, _req_we = req
            teacher_weekday_hours[tch] = teacher_weekday_hours.get(tch, 0) + int(req_w)

        for t in teachers:
            if len(teacher_classes.get(t, set())) != 2:
                continue
            if teacher_weekday_hours.get(t, 0) >= 5:
                continue
            for d in WEEKDAYS:
                if d not in days:
                    continue
                has_any = bridge.get("day_has_any_am_pm", {}).get((t, d))
                night = night_has.get((t, d), model.NewConstant(0))
                if has_any is None:
                    continue
                no_day = model.NewBoolVar(f"two_cls_no_day[{t},{d}]")
                model.Add(no_day + has_any == 1)
                viol = model.NewBoolVar(f"two_cls_no_day_night[{t},{d}]")
                model.Add(viol <= no_day)
                model.Add(viol <= night)
                model.Add(viol >= no_day + night - 1)
                stats["viol5"].append(viol)
                stats["viol5_by_teacher"].setdefault(t, []).append(viol)
                penalties.append(cfg.w_two_class_empty_day_no_night * viol)
                register(
                    rule_id="day_night_link_two_class_empty_day_no_night",
                    rule_name="双班空整天=>晚自习惩罚",
                    weight=cfg.w_two_class_empty_day_no_night,
                    var=viol,
                    teacher=t,
                    day=d,
                    constraint_category="linkage",
                    source_module="scheduler/model/constraints/day_night_bridge.py",
                    weight_key="day_night_link.w_two_class_empty_day_no_night",
                )  # weight: day_night_link.w_two_class_empty_day_no_night（建议 100~400）

    return penalties, stats


def write_link_audit(out_dir: Path, bridge: dict) -> None:
    """输出桥接变量口径审计（来源/天列表/教师列表）。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "link_bridge_audit.txt"
    lines = ["[Link Bridge Audit]"]
    lines.append("day_has_pm: from day vars by teacher/day, PM block")
    lines.append("day_has_am1: from day vars by teacher/day, AM1")
    lines.append("day_has_am2: from day vars by teacher/day, AM2")
    lines.append("day_load: sum of day vars + fixed")
    lines.append("sun_has_pm: day_has_pm on Sunday")
    lines.append("night_has: night on_teacher_day")
    lines.append("night_duty: night_has OR checkin_m OR checkin_f")
    lines.append(f"Teachers={bridge['teachers']}")
    lines.append(f"Days={bridge['days']}")
    path.write_text("\n".join(lines), encoding="utf-8")


def write_link_checklist(
    out_dir: Path,
    solver: cp_model.CpSolver,
    bridge: dict,
    stats: Dict[str, dict],
    cfg: LinkConfig,
) -> None:
    """输出联动约束检查清单（软违例计数与硬约束检测）。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "day_night_link_checklist.txt"
    teachers = bridge["teachers"]
    days = bridge["days"]
    day_has_pm = bridge["day_has_pm"]
    day_has_am1 = bridge["day_has_am1"]
    day_has_am2 = bridge["day_has_am2"]
    sun_has_pm = bridge["sun_has_pm"]
    night_has = bridge["night_has"]
    checkin_m = bridge.get("checkin_m", {})
    checkin_f = bridge.get("checkin_f", {})
    day_has_any_am_pm = bridge.get("day_has_any_am_pm", {})

    lines = ["[Day Night Link Checklist]"]
    lines.append(f"Viol1Count={sum(solver.Value(v) for v in stats.get('viol1', []))}")
    lines.append(
        f"ViolSunNightNoMonAM1Count={sum(solver.Value(v) for v in stats.get('viol_sun_night_no_mon_am1', []))}"
    )
    lines.append(
        f"ViolSunPmNightNoMonAMCount={sum(solver.Value(v) for v in stats.get('viol_sun_pm_night_no_mon_am', []))}"
    )
    lines.append(f"Viol3Count={sum(solver.Value(v) for v in stats.get('viol3', []))}")
    lines.append(f"Viol4Count={sum(solver.Value(v) for v in stats.get('viol4', []))}")
    lines.append(f"Viol5Count={sum(solver.Value(v) for v in stats.get('viol5', []))}")
    lines.append(f"ViolNightRequiresDayCount={sum(solver.Value(v) for v in stats.get('viol_night_requires_day', []))}")
    # Hard constraint #2 check. In soft mode it is reported through soft violation vars.
    hard2_viol = 0
    hard2_active = (
        cfg.enable_sun_pm_night_no_mon_am
        and str(cfg.sun_pm_night_no_mon_am_mode or "hard").strip().lower() == "hard"
    )
    if hard2_active and "星期日" in days and "星期一" in days:
        for t in teachers:
            sun_pm = solver.Value(sun_has_pm.get(t, 0))
            sun_night = solver.Value(night_has.get((t, "星期日"), 0))
            mon_am1 = solver.Value(day_has_am1.get((t, "星期一"), 0))
            mon_am2 = solver.Value(day_has_am2.get((t, "星期一"), 0))
            if sun_pm + sun_night + mon_am1 > 2:
                hard2_viol += 1
            if sun_pm + sun_night + mon_am2 > 2:
                hard2_viol += 1
    lines.append(f"Hard2Violations={hard2_viol}")
    hard_sun_night_no_mon_am1_viol = 0
    hard_sun_night_active = (
        cfg.enable_sun_night_no_mon_am1
        and str(cfg.sun_night_no_mon_am1_mode or "hard").strip().lower() == "hard"
    )
    if hard_sun_night_active and "星期日" in days and "星期一" in days:
        for t in teachers:
            sun_night = solver.Value(night_has.get((t, "星期日"), 0))
            mon_am1 = solver.Value(day_has_am1.get((t, "星期一"), 0))
            if sun_night + mon_am1 > 1:
                hard_sun_night_no_mon_am1_viol += 1
    lines.append(f"HardSunNightNoMonAM1Violations={hard_sun_night_no_mon_am1_viol}")
    hard_night_requires_day_viol = 0
    hard_night_requires_day_active = (
        cfg.enable_night_requires_day
        and str(cfg.night_requires_day_mode or "hard").strip().lower() == "hard"
    )
    if hard_night_requires_day_active:
        for t in teachers:
            for d in days:
                has_day = solver.Value(day_has_any_am_pm.get((t, d), 0))
                has_night_duty = max(
                    solver.Value(night_has.get((t, d), 0)),
                    solver.Value(checkin_m.get((t, d), 0)),
                    solver.Value(checkin_f.get((t, d), 0)),
                )
                if has_night_duty > has_day:
                    hard_night_requires_day_viol += 1
    lines.append(f"HardNightRequiresDayViolations={hard_night_requires_day_viol}")
    lines.append("TopViolations=")
    for key in (
        "viol1_by_teacher",
        "viol_sun_pm_night_no_mon_am_by_teacher",
        "viol_sun_night_no_mon_am1_by_teacher",
        "viol3_by_teacher",
        "viol4_by_teacher",
        "viol5_by_teacher",
        "viol_night_requires_day_by_teacher",
    ):
        items = []
        for t, vars_list in stats.get(key, {}).items():
            cnt = sum(solver.Value(v) for v in vars_list)
            items.append((cnt, t))
        items.sort(reverse=True)
        top = ", ".join([f"{t}:{cnt}" for cnt, t in items[:10] if cnt > 0])
        lines.append(f"  {key}={top}")
    lines.append("SunMonKey=")
    if "星期日" in days and "星期一" in days:
        for t in teachers:
            sun_pm = solver.Value(sun_has_pm.get(t, 0))
            sun_night = solver.Value(night_has.get((t, "星期日"), 0))
            mon_am1 = solver.Value(day_has_am1.get((t, "星期一"), 0))
            mon_am2 = solver.Value(day_has_am2.get((t, "星期一"), 0))
            lines.append(f"  {t}: sun_pm={sun_pm} sun_night={sun_night} mon_am1={mon_am1} mon_am2={mon_am2}")
    path.write_text("\n".join(lines), encoding="utf-8")

