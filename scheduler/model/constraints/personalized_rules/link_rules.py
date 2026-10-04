# -*- coding: utf-8 -*-
from __future__ import annotations

import logging
from typing import Dict, List, Set, Tuple

from ortools.sat.python import cp_model

from scheduler.model.constraints.day_pairs import adjacent_day_pairs
from scheduler.model.constraints.personalized_rules.context import (
    PersonalizedRuleContext,
    _and2,
    _build_day_has_slot,
    _norm_mode,
    _norm_name,
    _slot_key,
)

logger = logging.getLogger(__name__)


def apply(ctx: PersonalizedRuleContext) -> None:
    model = ctx.model
    cfg = ctx.cfg
    day_data = ctx.day_data
    day_vars = ctx.day_vars
    night_vars = ctx.night_vars
    night_ctx = ctx.night_ctx
    day_days = ctx.day_days
    night_days = ctx.night_days
    day_teachers = ctx.day_teachers
    night_on = ctx.night_on
    day_has_pm_any = ctx.day_has_pm_any
    day_has_am1 = ctx.day_has_am1
    day_has_am2 = ctx.day_has_am2
    day_has_early1 = ctx.day_has_early1
    day_has_am_any = ctx.day_has_am_any
    day_has_am3 = ctx.day_has_am3
    day_has_am4 = ctx.day_has_am4
    day_has_pm1 = ctx.day_has_pm1
    day_has_pm3 = ctx.day_has_pm3
    hard_notes = ctx.hard_notes
    penalties = ctx.penalties
    stats = ctx.stats
    has_teacher = ctx.has_teacher
    norm_mode = ctx.norm_mode
    build_teacher_slot_misplaced_var = ctx.build_teacher_slot_misplaced_var
    T_XHD = ctx.T_XHD
    T_ZFY = ctx.T_ZFY
    T_ZW = ctx.T_ZW
    T_LM = ctx.T_LM
    T_YTT = ctx.T_YTT
    T_DYM = ctx.T_DYM
    T_POL_EXEMPT = ctx.T_POL_EXEMPT
    T_LD = ctx.T_LD
    T_ZFJ_PM3 = ctx.T_ZFJ_PM3
    T_ZFJ_CHECKIN = ctx.T_ZFJ_CHECKIN
    T_JXQ = ctx.T_JXQ
    T_CSQI = ctx.T_CSQI
    T_ZZX = ctx.T_ZZX
    T_XYX = ctx.T_XYX
    T_HWJ = ctx.T_HWJ
    T_HSM = ctx.T_HSM
    T_WXL = ctx.T_WXL
    T_DLN = ctx.T_DLN
    T_ZB = ctx.T_ZB
    T_XWW = ctx.T_XWW
    T_SLL = ctx.T_SLL
    T_CC = ctx.T_CC
    T_SM = ctx.T_SM
    T_MRJ = ctx.T_MRJ
    T_SAT_TARGET_CLASS = ctx.T_SAT_TARGET_CLASS
    # Rule 1: 指定教师夜→不排下午3
    # weight: personalized_constraints.w_xhd_night_no_pm3（建议 80/150/300）
    if cfg.enable_xhd_night_no_pm3 and has_teacher(T_XHD):
        xhd_mode = norm_mode(cfg.xhd_night_no_pm3_mode)
        for d in night_days:
            night = night_on.get((T_XHD, d), model.NewConstant(0))
            pm3 = day_has_pm3.get((T_XHD, d), model.NewConstant(0))
            if xhd_mode == "hard":
                model.Add(night + pm3 <= 1)
            else:
                viol = model.NewBoolVar(f"pers_xhd_pm3[{d}]")
                model.Add(viol <= night)
                model.Add(viol <= pm3)
                model.Add(viol >= night + pm3 - 1)
                penalties.append(cfg.w_xhd_night_no_pm3 * viol)
                stats.setdefault("rule1", {"vars": [], "w": cfg.w_xhd_night_no_pm3})["vars"].append(viol)

    # Rule 28: 指定教师晚自习当天下午尽量不排课（soft/hard 可切换）
    # weight: personalized_constraints.w_xhd_night_no_pm（建议 >=3000）
    if cfg.enable_xhd_night_no_pm and has_teacher(T_XHD):
        xhd_pm_mode = norm_mode(cfg.xhd_night_no_pm_mode)
        for d in night_days:
            night = night_on.get((T_XHD, d), model.NewConstant(0))
            pm_any = day_has_pm_any.get((T_XHD, d), model.NewConstant(0))
            if xhd_pm_mode == "hard":
                model.Add(night + pm_any <= 1)
            else:
                viol = model.NewBoolVar(f"pers_xhd_night_no_pm[{d}]")
                model.Add(viol <= night)
                model.Add(viol <= pm_any)
                model.Add(viol >= night + pm_any - 1)
                penalties.append(cfg.w_xhd_night_no_pm * viol)
                stats.setdefault("rule28_xhd_night_no_pm", {"vars": [], "days": [], "w": cfg.w_xhd_night_no_pm})["vars"].append(viol)
                stats["rule28_xhd_night_no_pm"]["days"].append(d)

    # Rule 2: 指定教师 & 指定教师至少同一天上晚自习（soft/hard 可切换）
    # soft weight: personalized_constraints.w_couple_need_overlap（建议 >=5000）
    if cfg.enable_couple_xhd_zfy and T_XHD and T_ZFY:
        couple_mode = norm_mode(cfg.couple_xhd_zfy_mode)
        if couple_mode == "hard":
            if not (has_teacher(T_XHD) and has_teacher(T_ZFY)):
                hard_mode = str(cfg.couple_xhd_zfy_mode or "soft")
                hard_notes.append(f"Rule2(hard): missing configured teacher pair for night overlap mode={hard_mode}")
                if night_ctx is not None:
                    model.Add(0 == 1)
            elif not night_days:
                hard_mode = str(cfg.couple_xhd_zfy_mode or "soft")
                hard_notes.append(f"Rule2(hard): missing night days for overlap mode={hard_mode}")
                if night_ctx is not None:
                    model.Add(0 == 1)
            else:
                overlap_vars = []
                for d in night_days:
                    a = night_on.get((T_XHD, d), model.NewConstant(0))
                    b = night_on.get((T_ZFY, d), model.NewConstant(0))
                    both = model.NewBoolVar(f"pers_couple_both[{d}]")
                    model.Add(both <= a)
                    model.Add(both <= b)
                    model.Add(both >= a + b - 1)
                    overlap_vars.append(both)
                any_overlap = model.NewBoolVar("pers_couple_any_overlap")
                model.AddMaxEquality(any_overlap, overlap_vars)
                model.Add(any_overlap == 1)
        else:
            no_overlap = model.NewBoolVar("pers_couple_no_overlap")
            if not (has_teacher(T_XHD) and has_teacher(T_ZFY)) or not night_days:
                model.Add(no_overlap == 1)
            else:
                overlap_vars = []
                for d in night_days:
                    a = night_on.get((T_XHD, d), model.NewConstant(0))
                    b = night_on.get((T_ZFY, d), model.NewConstant(0))
                    both = model.NewBoolVar(f"pers_couple_both[{d}]")
                    model.Add(both <= a)
                    model.Add(both <= b)
                    model.Add(both >= a + b - 1)
                    overlap_vars.append(both)
                any_overlap = model.NewBoolVar("pers_couple_any_overlap")
                model.AddMaxEquality(any_overlap, overlap_vars)
                model.Add(any_overlap + no_overlap == 1)
            penalties.append(cfg.w_couple_need_overlap * no_overlap)
            stats.setdefault(
                "rule2_couple_overlap_soft",
                {"vars": [], "w": cfg.w_couple_need_overlap, "teacher": f"{T_XHD},{T_ZFY}"},
            )["vars"].append(no_overlap)

    # Rule 3: 指定教师 夜→白天下午（soft/hard 可切换）
    # weight: personalized_constraints.w_zw_night_need_pm（建议 >=3000）
    if cfg.enable_zw_night_need_pm and has_teacher(T_ZW):
        zw_pm_mode = norm_mode(cfg.zw_night_need_pm_mode)
        for d in night_days:
            night = night_on.get((T_ZW, d), model.NewConstant(0))
            pm = day_has_pm_any.get((T_ZW, d), model.NewConstant(0))
            if zw_pm_mode == "hard":
                model.Add(night <= pm)
            else:
                viol = model.NewBoolVar(f"pers_zw_pm[{d}]")
                model.Add(viol <= night)
                model.Add(viol <= 1 - pm)
                model.Add(viol >= night - pm)
                penalties.append(cfg.w_zw_night_need_pm * viol)
                stats.setdefault("rule3", {"vars": [], "w": cfg.w_zw_night_need_pm})["vars"].append(viol)

    # Rule 25/26/27/37: 指定教师节次周累计上限（soft/hard 可切换）
    if has_teacher(T_ZW):
        def _slot_map(slot_key: str) -> Dict[Tuple[str, str], cp_model.IntVar]:
            if slot_key == "上午1":
                return day_has_am1
            if slot_key == "上午2":
                return day_has_am2
            if slot_key == "上午4":
                return day_has_am4
            if day_data and day_vars:
                return _build_day_has_slot(model, day_data, day_vars, set(day_teachers), day_days, slot_key)
            return {}

        def _apply_zw_slot_cap(
            *,
            enabled: bool,
            mode: str,
            slot_key: str,
            cap_max: int,
            weight: int,
            rule_key: str,
            var_prefix: str,
            target_days: List[str] | None = None,
        ) -> None:
            if not enabled:
                return
            slot_map = _slot_map(str(slot_key))
            cap = max(0, int(cap_max))
            mode_norm = norm_mode(mode)
            scoped_days = list(target_days) if target_days else list(day_days)
            cnt = model.NewIntVar(0, len(scoped_days), f"{var_prefix}_cnt")
            model.Add(cnt == sum(slot_map.get((T_ZW, d), model.NewConstant(0)) for d in scoped_days))
            if mode_norm == "hard":
                model.Add(cnt <= cap)
            else:
                excess = model.NewIntVar(0, len(scoped_days), f"{var_prefix}_excess")
                model.Add(excess >= cnt - cap)
                penalties.append(int(weight) * excess)
                stats.setdefault(rule_key, {"vars": [], "w": int(weight), "count_var": cnt})["vars"].append(excess)

        _apply_zw_slot_cap(
            enabled=cfg.enable_zw_am1_cap,
            mode=cfg.zw_am1_cap_mode,
            slot_key=cfg.zw_am1_slot_key,
            cap_max=cfg.zw_am1_cap_max,
            weight=cfg.w_zw_am1_cap,
            rule_key="rule25_zw_am1_cap",
            var_prefix="zw_am1_cap",
        )
        _apply_zw_slot_cap(
            enabled=cfg.enable_zw_am2_cap,
            mode=cfg.zw_am2_cap_mode,
            slot_key=cfg.zw_am2_slot_key,
            cap_max=cfg.zw_am2_cap_max,
            weight=cfg.w_zw_am2_cap,
            rule_key="rule26_zw_am2_cap",
            var_prefix="zw_am2_cap",
        )
        _apply_zw_slot_cap(
            enabled=cfg.enable_zw_am4_cap,
            mode=cfg.zw_am4_cap_mode,
            slot_key=cfg.zw_am4_slot_key,
            cap_max=cfg.zw_am4_cap_max,
            weight=cfg.w_zw_am4_cap,
            rule_key="rule27_zw_am4_cap",
            var_prefix="zw_am4_cap",
        )
        _apply_zw_slot_cap(
            enabled=cfg.enable_zw_weekday_pm1_cap,
            mode=cfg.zw_weekday_pm1_cap_mode,
            slot_key=cfg.zw_weekday_pm1_slot_key,
            cap_max=cfg.zw_weekday_pm1_cap_max,
            weight=cfg.w_zw_weekday_pm1_cap,
            rule_key="rule37_zw_weekday_pm1_cap",
            var_prefix="zw_weekday_pm1_cap",
            target_days=[d for d in ("星期一", "星期二", "星期三", "星期四", "星期五") if d in day_days],
        )
