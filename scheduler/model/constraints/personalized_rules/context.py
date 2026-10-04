# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

from ortools.sat.python import cp_model

from scheduler.data.day_rules_reader import DayInputData, Slot
from scheduler.model.day_variables import DayVars
from scheduler.model.constraints.teacher_targets import teacher_names


def _norm_name(s: object) -> str:
    return str(s or "").strip()


def _norm_mode(x: object, default: str = "soft") -> str:
    m = str(x or default).strip().lower()
    return m if m in {"soft", "hard"} else default


def _slot_key(slot: Slot) -> str:
    return f"{slot.block}{slot.period}"


def _and2(model: cp_model.CpModel, a, b, name: str) -> cp_model.IntVar:
    z = model.NewBoolVar(name)
    model.Add(z <= a)
    model.Add(z <= b)
    model.Add(z >= a + b - 1)
    return z


def _collect_day_teacher_vars(
    data: DayInputData,
    dv: DayVars,
) -> Dict[str, Dict[str, Dict[Slot, List[cp_model.IntVar]]]]:
    out: Dict[str, Dict[str, Dict[Slot, List[cp_model.IntVar]]]] = {}
    for (cls, subj, slot), var in dv.x.items():
        teacher = data.cls_subj_teacher.get((cls, subj))
        if not teacher:
            continue
        out.setdefault(teacher, {}).setdefault(slot.day, {}).setdefault(slot, []).append(var)
    return out


def _build_day_has_slot(
    model: cp_model.CpModel,
    data: DayInputData,
    dv: DayVars,
    teachers: Set[str],
    days: List[str],
    slot_key: str,
) -> Dict[Tuple[str, str], cp_model.IntVar]:
    out: Dict[Tuple[str, str], cp_model.IntVar] = {}
    teacher_vars = _collect_day_teacher_vars(data, dv)
    for t in teachers:
        for d in days:
            vars_list = []
            for s, lst in teacher_vars.get(t, {}).get(d, {}).items():
                if _slot_key(s) == slot_key:
                    vars_list.extend(lst)
            fixed = 0
            for (cls, slot), subj in data.fixed_assign.items():
                if slot.day != d:
                    continue
                if _slot_key(slot) != slot_key:
                    continue
                if data.cls_subj_teacher.get((cls, subj)) == t:
                    fixed += 1
            b = model.NewBoolVar(f"day_has[{t},{d},{slot_key}]")
            if fixed > 0:
                model.Add(b == 1)
            elif vars_list:
                model.Add(sum(vars_list) >= b)
                for v in vars_list:
                    model.Add(v <= b)
            else:
                model.Add(b == 0)
            out[(t, d)] = b
    return out


def _build_day_has_am_any(
    model: cp_model.CpModel,
    data: DayInputData,
    dv: DayVars,
    teachers: Set[str],
    days: List[str],
) -> Dict[Tuple[str, str], cp_model.IntVar]:
    out: Dict[Tuple[str, str], cp_model.IntVar] = {}
    teacher_vars = _collect_day_teacher_vars(data, dv)
    for t in teachers:
        for d in days:
            vars_list = []
            for s, lst in teacher_vars.get(t, {}).get(d, {}).items():
                if s.block == "上午":
                    vars_list.extend(lst)
            fixed = sum(
                1
                for (cls, slot), subj in data.fixed_assign.items()
                if slot.day == d and slot.block == "上午" and data.cls_subj_teacher.get((cls, subj)) == t
            )
            b = model.NewBoolVar(f"day_has_am_any[{t},{d}]")
            if fixed > 0:
                model.Add(b == 1)
            elif vars_list:
                model.Add(sum(vars_list) >= b)
                for v in vars_list:
                    model.Add(v <= b)
            else:
                model.Add(b == 0)
            out[(t, d)] = b
    return out


def _build_day_has_pm_any(
    model: cp_model.CpModel,
    data: DayInputData,
    dv: DayVars,
    teachers: Set[str],
    days: List[str],
) -> Dict[Tuple[str, str], cp_model.IntVar]:
    out: Dict[Tuple[str, str], cp_model.IntVar] = {}
    teacher_vars = _collect_day_teacher_vars(data, dv)
    for t in teachers:
        for d in days:
            vars_list = []
            for s, lst in teacher_vars.get(t, {}).get(d, {}).items():
                if s.block == "下午":
                    vars_list.extend(lst)
            fixed = sum(
                1
                for (cls, slot), subj in data.fixed_assign.items()
                if slot.day == d and slot.block == "下午" and data.cls_subj_teacher.get((cls, subj)) == t
            )
            b = model.NewBoolVar(f"day_has_pm_any[{t},{d}]")
            if fixed > 0:
                model.Add(b == 1)
            elif vars_list:
                model.Add(sum(vars_list) >= b)
                for v in vars_list:
                    model.Add(v <= b)
            else:
                model.Add(b == 0)
            out[(t, d)] = b
    return out


@dataclass
class PersonalizedRuleContext:
    model: cp_model.CpModel
    day_data: DayInputData | None
    day_vars: DayVars | None
    night_vars: dict | None
    night_ctx: dict | None
    bridge: dict
    cfg: Any
    out_dir: Path
    hard_notes: List[str]
    penalties: List[Any]
    stats: Dict[str, dict]
    day_days: List[str]
    night_days: List[str]
    night_periods: List[Any]
    day_teachers: Set[str]
    night_teachers: Set[str]
    all_teachers: List[str]
    night_on: dict
    day_has_pm_any: dict
    day_has_am1: dict
    day_has_am2: dict
    day_has_early1: dict
    day_has_am_any: dict
    day_has_am3: dict
    day_has_am4: dict
    day_has_pm1: dict
    day_has_pm3: dict
    all_teacher_norms: Set[str]
    T_XHD: str
    T_ZFY: str
    T_ZW: str
    T_LM: str
    T_YTT: str
    T_DYM: str
    T_POL_EXEMPT: str
    T_LD: str
    T_ZFJ_PM3: str
    T_ZFJ_CHECKIN: str
    T_JXQ: str
    T_CSQI: str
    T_ZZX: str
    T_XYX: str
    T_HWJ: str
    T_HSM: str
    T_WXL: str
    T_DLN: str
    T_ZB: str
    T_XWW: str
    T_SLL: str
    T_CC: str
    T_SM: str
    T_MRJ: str
    T_SAT_TARGET_CLASS: str

    def has_teacher(self, name: str) -> bool:
        return bool(name) and _norm_name(name) in self.all_teacher_norms

    def norm_mode(self, mode: str | None) -> str:
        m = str(mode or "soft").strip().lower()
        return m if m in {"soft", "hard"} else "soft"

    def build_teacher_slot_misplaced_var(
        self,
        teacher: str,
        day: str,
        slot_key: str,
        target_cls: str,
        name_prefix: str,
    ) -> cp_model.IntVar:
        target_vars: List[cp_model.IntVar] = []
        other_vars: List[cp_model.IntVar] = []
        fixed_target = 0
        fixed_other = 0

        if self.day_data and self.day_vars:
            for (cls, subj, slot), var in self.day_vars.x.items():
                if slot.day != day:
                    continue
                if _slot_key(slot) != slot_key:
                    continue
                if _norm_name(self.day_data.cls_subj_teacher.get((cls, subj), "")) != _norm_name(teacher):
                    continue
                if cls == target_cls:
                    target_vars.append(var)
                else:
                    other_vars.append(var)

            for (cls, slot), subj in self.day_data.fixed_assign.items():
                if slot.day != day:
                    continue
                if _slot_key(slot) != slot_key:
                    continue
                if _norm_name(self.day_data.cls_subj_teacher.get((cls, subj), "")) != _norm_name(teacher):
                    continue
                if cls == target_cls:
                    fixed_target += 1
                else:
                    fixed_other += 1

        has_any = self.model.NewBoolVar(f"{name_prefix}_has_any[{day},{slot_key}]")
        in_target = self.model.NewBoolVar(f"{name_prefix}_in_target[{day},{slot_key}]")

        if fixed_target + fixed_other > 0:
            self.model.Add(has_any == 1)
            if fixed_target > 0 and fixed_other == 0:
                self.model.Add(in_target == 1)
            elif fixed_other > 0 and fixed_target == 0:
                self.model.Add(in_target == 0)
            else:
                self.model.Add(in_target == 0)
        else:
            all_vars = target_vars + other_vars
            if all_vars:
                self.model.Add(sum(all_vars) >= has_any)
                for v in all_vars:
                    self.model.Add(v <= has_any)
            else:
                self.model.Add(has_any == 0)

            if target_vars:
                self.model.Add(sum(target_vars) >= in_target)
                for v in target_vars:
                    self.model.Add(v <= in_target)
            else:
                self.model.Add(in_target == 0)

        not_target = self.model.NewBoolVar(f"{name_prefix}_not_target[{day},{slot_key}]")
        self.model.Add(in_target + not_target == 1)
        return _and2(self.model, has_any, not_target, f"{name_prefix}_misplaced[{day},{slot_key}]")


def build_personalized_rule_context(
    *,
    model: cp_model.CpModel,
    day_data: DayInputData | None,
    day_vars: DayVars | None,
    night_vars: dict | None,
    night_ctx: dict | None,
    bridge: dict | None,
    cfg: Any,
    out_dir: Path,
    hard_notes: List[str],
    penalties: List[Any],
    stats: Dict[str, dict],
    day_days: List[str],
    night_days: List[str],
    night_periods: List[Any],
    day_teachers: Set[str],
    night_teachers: Set[str],
    all_teachers: List[str],
) -> PersonalizedRuleContext:
    bridge = bridge or {}
    night_on = (night_vars or {}).get("on_teacher_day", {})

    day_has_pm = bridge.get("day_has_pm", {})
    if not day_has_pm and day_data and day_vars:
        day_has_pm = _build_day_has_pm_any(model, day_data, day_vars, set(day_teachers), day_days)

    day_has_am1 = bridge.get("day_has_am1", {})
    day_has_am2 = bridge.get("day_has_am2", {})
    if not day_has_am1 and day_data and day_vars:
        day_has_am1 = _build_day_has_slot(model, day_data, day_vars, set(day_teachers), day_days, "上午1")
    if not day_has_am2 and day_data and day_vars:
        day_has_am2 = _build_day_has_slot(model, day_data, day_vars, set(day_teachers), day_days, "上午2")

    def target_teacher(slot: str) -> str:
        names = teacher_names((cfg.teacher_targets or {}).get(slot, []))
        return names[0] if names else ""

    return PersonalizedRuleContext(
        model=model,
        day_data=day_data,
        day_vars=day_vars,
        night_vars=night_vars,
        night_ctx=night_ctx,
        bridge=bridge,
        cfg=cfg,
        out_dir=out_dir,
        hard_notes=hard_notes,
        penalties=penalties,
        stats=stats,
        day_days=day_days,
        night_days=night_days,
        night_periods=night_periods,
        day_teachers=day_teachers,
        night_teachers=night_teachers,
        all_teachers=all_teachers,
        night_on=night_on,
        day_has_pm_any=day_has_pm,
        day_has_am1=day_has_am1,
        day_has_am2=day_has_am2,
        day_has_early1=_build_day_has_slot(model, day_data, day_vars, set(day_teachers), day_days, "早自习1") if day_data else {},
        day_has_am_any=_build_day_has_am_any(model, day_data, day_vars, set(day_teachers), day_days) if day_data else {},
        day_has_am3=_build_day_has_slot(model, day_data, day_vars, set(day_teachers), day_days, "上午3") if day_data else {},
        day_has_am4=_build_day_has_slot(model, day_data, day_vars, set(day_teachers), day_days, "上午4") if day_data else {},
        day_has_pm1=_build_day_has_slot(model, day_data, day_vars, set(day_teachers), day_days, "下午1") if day_data else {},
        day_has_pm3=_build_day_has_slot(model, day_data, day_vars, set(day_teachers), day_days, "下午3") if day_data else {},
        all_teacher_norms={_norm_name(t) for t in all_teachers},
        T_XHD=target_teacher("xhd"),
        T_ZFY=target_teacher("zfy"),
        T_ZW=target_teacher("zw"),
        T_LM=target_teacher("lm"),
        T_YTT=target_teacher("ytt"),
        T_DYM=target_teacher("dym"),
        T_POL_EXEMPT=target_teacher("pol_sunday_exempt"),
        T_LD=target_teacher("ld"),
        T_ZFJ_PM3=target_teacher("zfj_pm3"),
        T_ZFJ_CHECKIN=target_teacher("zfj_checkin"),
        T_JXQ=target_teacher("jxq"),
        T_CSQI=target_teacher("csqi"),
        T_ZZX=target_teacher("zzx"),
        T_XYX=target_teacher("xyx"),
        T_HWJ=target_teacher("hwj"),
        T_HSM=target_teacher("hsm"),
        T_WXL=target_teacher("wxl"),
        T_DLN=target_teacher("dln"),
        T_ZB=target_teacher("zb"),
        T_XWW=target_teacher("xww"),
        T_SLL=target_teacher("sll"),
        T_CC=target_teacher("cc"),
        T_SM=target_teacher("sm"),
        T_MRJ=target_teacher("mrj"),
        T_SAT_TARGET_CLASS=str((cfg.teacher_targets or {}).get("cc_sat_am34_target_class", "") or ""),
    )
