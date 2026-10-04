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
    # Rule 14: 指定教师
    # weight: personalized_constraints.w_hsm_no_fri_night
    if cfg.enable_hsm_no_fri_night and has_teacher(T_HSM):
        if "星期五" in night_days:
            fri = night_on.get((T_HSM, "星期五"), model.NewConstant(0))
            if norm_mode(cfg.hsm_no_fri_night_mode) == "hard":
                model.Add(fri == 0)
            else:
                penalties.append(cfg.w_hsm_no_fri_night * fri)
                stats.setdefault("rule14", {"vars": [], "w": cfg.w_hsm_no_fri_night})["vars"].append(fri)

    # Rule 35: 指定教师周一到周五若当天安排早自习，则不排上午1（soft/hard 可切换）
    if cfg.enable_hsm_weekday_early_no_am1 and has_teacher(T_HSM):
        hsm_early_mode = norm_mode(cfg.hsm_weekday_early_no_am1_mode)
        for d in ("星期一", "星期二", "星期三", "星期四", "星期五"):
            if d not in day_days:
                continue
            early = day_has_early1.get((T_HSM, d), model.NewConstant(0))
            am1 = day_has_am1.get((T_HSM, d), model.NewConstant(0))
            both = _and2(model, early, am1, f"hsm_weekday_early_am1_both[{d}]")
            if hsm_early_mode == "hard":
                model.Add(both == 0)
            else:
                penalties.append(cfg.w_hsm_weekday_early_no_am1 * both)
                stats.setdefault(
                    "rule35_hsm_weekday_early_no_am1",
                    {"vars": [], "w": cfg.w_hsm_weekday_early_no_am1, "days": []},
                )["vars"].append(both)
                stats["rule35_hsm_weekday_early_no_am1"]["days"].append(d)

    # Rule 36: 指定教师周一到周五若当天安排早自习，则不排上午1（soft/hard 可切换）
    if cfg.enable_wxl_weekday_early_no_am1 and has_teacher(T_WXL):
        wxl_early_mode = norm_mode(cfg.wxl_weekday_early_no_am1_mode)
        for d in ("星期一", "星期二", "星期三", "星期四", "星期五"):
            if d not in day_days:
                continue
            early = day_has_early1.get((T_WXL, d), model.NewConstant(0))
            am1 = day_has_am1.get((T_WXL, d), model.NewConstant(0))
            both = _and2(model, early, am1, f"wxl_weekday_early_am1_both[{d}]")
            if wxl_early_mode == "hard":
                model.Add(both == 0)
            else:
                penalties.append(cfg.w_wxl_weekday_early_no_am1 * both)
                stats.setdefault(
                    "rule36_wxl_weekday_early_no_am1",
                    {"vars": [], "w": cfg.w_wxl_weekday_early_no_am1, "days": []},
                )["vars"].append(both)
                stats["rule36_wxl_weekday_early_no_am1"]["days"].append(d)
    # Rule 39: 指定教师周一到周五不排上午1（soft/hard 可切换）
    if cfg.enable_dln_weekday_no_am1 and has_teacher(T_DLN):
        dln_mode = norm_mode(cfg.dln_weekday_no_am1_mode)
        for d in ("星期一", "星期二", "星期三", "星期四", "星期五"):
            if d not in day_days:
                continue
            am1_var = day_has_am1.get((T_DLN, d), model.NewConstant(0))
            if dln_mode == "hard":
                model.Add(am1_var == 0)
            else:
                penalties.append(cfg.w_dln_weekday_no_am1 * am1_var)
                st = stats.setdefault(
                    "rule39_dln_weekday_no_am1",
                    {"vars": [], "w": cfg.w_dln_weekday_no_am1, "days": []},
                )
                st["vars"].append(am1_var)
                st["days"].append(d)

    # Rule 41: 自定义教师名单周一到周五不排上午1（硬约束）
    if cfg.enable_custom_no_am1_teachers and day_data is not None:
        day_teacher_map = {_norm_name(t): t for t in day_teachers}
        seen_custom: Set[str] = set()
        for raw_name in cfg.custom_no_am1_teachers:
            n = _norm_name(raw_name)
            if not n or n in seen_custom:
                continue
            seen_custom.add(n)
            teacher_key = day_teacher_map.get(n)
            if teacher_key is None:
                hard_notes.append(f"Rule41: custom_no_am1_teachers 未找到教师：{raw_name}")
                continue
            for d in ("星期一", "星期二", "星期三", "星期四", "星期五"):
                if d not in day_days:
                    continue
                am1_var = day_has_am1.get((teacher_key, d), model.NewConstant(0))
                model.Add(am1_var == 0)

    # Rule 15: 指定教师硬约束（硬）
    if cfg.enable_zhoubo_hard and has_teacher(T_ZB):
        for d in day_days:
            if d in ("星期一", "星期二", "星期三", "星期四", "星期五"):
                model.Add(day_has_am4.get((T_ZB, d), model.NewConstant(0)) == 0)
                model.Add(day_has_pm1.get((T_ZB, d), model.NewConstant(0)) == 0)
        if "星期日" in day_days:
            model.Add(day_has_am1.get((T_ZB, "星期日"), model.NewConstant(0)) == 1)
            model.Add(day_has_am2.get((T_ZB, "星期日"), model.NewConstant(0)) == 1)
        else:
            hard_notes.append("Rule15: missing Sunday in day calendar")
            if day_data is not None:
                model.Add(0 == 1)
        if "星期日" in night_days:
            model.Add(night_on.get((T_ZB, "星期日"), model.NewConstant(0)) == 0)

    # Rule 15.1: 指定教师周一到周五上午1排课惩罚（软，高权重）
    # weight: personalized_constraints.w_zhoubo_weekday_am1_penalty
    if cfg.enable_zhoubo_weekday_am1_penalty and has_teacher(T_ZB):
        zb_am1_mode = norm_mode(cfg.zhoubo_weekday_am1_penalty_mode)
        for d in ("星期一", "星期二", "星期三", "星期四", "星期五"):
            if d not in day_days:
                continue
            am1_var = day_has_am1.get((T_ZB, d), model.NewConstant(0))
            if zb_am1_mode == "hard":
                model.Add(am1_var == 0)
            else:
                penalties.append(cfg.w_zhoubo_weekday_am1_penalty * am1_var)
                stats.setdefault(
                    "rule15_am1",
                    {"vars": [], "w": cfg.w_zhoubo_weekday_am1_penalty},
                )["vars"].append(am1_var)

    # Rule 15.2: 指定教师周日晚自习禁排（硬约束）
    if cfg.enable_liumeng_no_sunday and has_teacher(T_LM):
        if "星期日" in night_days:
            model.Add(night_on.get((T_LM, "星期日"), model.NewConstant(0)) == 0)

    # Rule 40: 指定教师周三晚自习禁排（硬约束）
    if has_teacher(T_DLN) and "星期三" in night_days:
        model.Add(night_on.get((T_DLN, "星期三"), model.NewConstant(0)) == 0)

    # Rule 16: 指定教师 & 指定教师 至少有一天同天上晚自习（硬约束）
    if cfg.enable_zhoubo_liumeng_same_night and T_ZB and T_LM:
        if not (has_teacher(T_ZB) and has_teacher(T_LM)):
            hard_notes.append("Rule16: missing teacher 指定教师/指定教师 for night overlap")
            if night_ctx is not None:
                model.Add(0 == 1)
        elif not night_days:
            hard_notes.append("Rule16: missing night days for overlap")
            if night_ctx is not None:
                model.Add(0 == 1)
        else:
            overlap_vars = []
            for d in night_days:
                a = night_on.get((T_ZB, d), model.NewConstant(0))
                b = night_on.get((T_LM, d), model.NewConstant(0))
                both = model.NewBoolVar(f"pers_zhoubo_liumeng_both[{d}]")
                model.Add(both <= a)
                model.Add(both <= b)
                model.Add(both >= a + b - 1)
                overlap_vars.append(both)
            if overlap_vars:
                any_overlap = model.NewBoolVar("pers_zhoubo_liumeng_any_overlap")
                model.AddMaxEquality(any_overlap, overlap_vars)
                model.Add(any_overlap == 1)

    # Rule 17: 指定教师 周一到周五 AM4+PM1 计数 >1 开始阶梯惩罚（软约束）
    # weight: personalized_constraints.w_xww_weekday_am4_pm1_e2/e3/e4
    if cfg.enable_xww_weekday_am4_pm1_stair and has_teacher(T_XWW):
        target_days = [d for d in ("星期一", "星期二", "星期三", "星期四", "星期五") if d in day_days]
        if target_days:
            xww_mode = norm_mode(cfg.xww_weekday_am4_pm1_stair_mode)
            cnt = model.NewIntVar(0, len(target_days) * 2, "xww_am4_pm1_cnt")
            model.Add(
                cnt
                == sum(day_has_am4.get((T_XWW, d), model.NewConstant(0)) for d in target_days)
                + sum(day_has_pm1.get((T_XWW, d), model.NewConstant(0)) for d in target_days)
            )
            if xww_mode == "hard":
                model.Add(cnt <= 1)
            else:
                e2 = model.NewIntVar(0, len(target_days) * 2, "xww_am4_pm1_e2")
                e3 = model.NewIntVar(0, len(target_days) * 2, "xww_am4_pm1_e3")
                e4 = model.NewIntVar(0, len(target_days) * 2, "xww_am4_pm1_e4")
                model.Add(e2 >= cnt - 1)
                model.Add(e3 >= cnt - 2)
                model.Add(e4 >= cnt - 3)
                penalties.append(cfg.w_xww_weekday_am4_pm1_e2 * e2)
                penalties.append(cfg.w_xww_weekday_am4_pm1_e3 * e3)
                penalties.append(cfg.w_xww_weekday_am4_pm1_e4 * e4)
                stats["rule17_xww_am4_pm1"] = {
                    "vars": [e2, e3, e4],
                    "w": 1,  # 分项权重不同，避免重复累计，详细权重写在附加字段
                    "weights": [
                        cfg.w_xww_weekday_am4_pm1_e2,
                        cfg.w_xww_weekday_am4_pm1_e3,
                        cfg.w_xww_weekday_am4_pm1_e4,
                    ],
                    "count_var": cnt,
                }

    # Rule 18: 指定教师不连续两天上晚自习（soft/hard 可切换；周日与周一视为连续）
    # soft weight: personalized_constraints.w_zfy_no_consecutive_night（建议 >=3000）
    if cfg.enable_zfy_no_consecutive_night and has_teacher(T_ZFY):
        zfy_mode = norm_mode(cfg.zfy_no_consecutive_night_mode)
        pairs: List[Tuple[str, str]] = adjacent_day_pairs(night_days, include_sun_mon=True)
        if zfy_mode == "hard":
            for d1, d2 in pairs:
                a = night_on.get((T_ZFY, d1), model.NewConstant(0))
                b = night_on.get((T_ZFY, d2), model.NewConstant(0))
                model.Add(a + b <= 1)
        else:
            viol_vars: List[cp_model.IntVar] = []
            pair_labels: List[str] = []
            for d1, d2 in pairs:
                a = night_on.get((T_ZFY, d1), model.NewConstant(0))
                b = night_on.get((T_ZFY, d2), model.NewConstant(0))
                viol = model.NewBoolVar(f"pers_zfy_consecutive_night[{d1},{d2}]")
                model.Add(viol <= a)
                model.Add(viol <= b)
                model.Add(viol >= a + b - 1)
                penalties.append(cfg.w_zfy_no_consecutive_night * viol)
                viol_vars.append(viol)
                pair_labels.append(f"{d1}->{d2}")

            if viol_vars:
                stats["rule18_zfy_consecutive_night"] = {
                    "vars": viol_vars,
                    "w": cfg.w_zfy_no_consecutive_night,
                    "pair_labels": pair_labels,
                    "teacher": T_ZFY,
                }

    # Rule 29: 指定教师晚自习不连续（soft/hard 可切换；周日与周一视为连续）
    if cfg.enable_zw_no_consecutive_night and has_teacher(T_ZW):
        zw_mode = norm_mode(cfg.zw_no_consecutive_night_mode)
        pairs: List[Tuple[str, str]] = adjacent_day_pairs(night_days, include_sun_mon=True)
        if zw_mode == "hard":
            for d1, d2 in pairs:
                a = night_on.get((T_ZW, d1), model.NewConstant(0))
                b = night_on.get((T_ZW, d2), model.NewConstant(0))
                model.Add(a + b <= 1)
        else:
            viol_vars: List[cp_model.IntVar] = []
            pair_labels: List[str] = []
            for d1, d2 in pairs:
                a = night_on.get((T_ZW, d1), model.NewConstant(0))
                b = night_on.get((T_ZW, d2), model.NewConstant(0))
                viol = model.NewBoolVar(f"pers_zw_consecutive_night[{d1},{d2}]")
                model.Add(viol <= a)
                model.Add(viol <= b)
                model.Add(viol >= a + b - 1)
                penalties.append(cfg.w_zw_no_consecutive_night * viol)
                viol_vars.append(viol)
                pair_labels.append(f"{d1}->{d2}")
            if viol_vars:
                stats["rule29_zw_no_consecutive_night"] = {
                    "vars": viol_vars,
                    "days": pair_labels,
                    "w": cfg.w_zw_no_consecutive_night,
                    "pair_labels": pair_labels,
                    "teacher": T_ZW,
                }

    # Rule 19: 指定教师周日晚自习禁排（soft/hard 可切换）
    if cfg.enable_zfy_no_sunday_night and has_teacher(T_ZFY) and "星期日" in night_days:
        z = night_on.get((T_ZFY, "星期日"), model.NewConstant(0))
        if norm_mode(cfg.zfy_no_sunday_night_mode) == "hard":
            model.Add(z == 0)
        else:
            penalties.append(cfg.w_zfy_no_sunday_night * z)
            stats.setdefault("rule19_zfy_no_sunday_night", {"vars": [], "w": cfg.w_zfy_no_sunday_night})["vars"].append(z)

    # Rule 20: 指定教师周日白天仅上午（soft/hard 可切换）
    if cfg.enable_sll_sun_am_only and has_teacher(T_SLL) and "星期日" in day_days:
        sun_pm = day_has_pm_any.get((T_SLL, "星期日"), model.NewConstant(0))
        if norm_mode(cfg.sll_sun_am_only_mode) == "hard":
            model.Add(sun_pm == 0)
        else:
            penalties.append(cfg.w_sll_sun_am_only * sun_pm)
            stats.setdefault("rule20_sll_sun_am_only", {"vars": [], "w": cfg.w_sll_sun_am_only})["vars"].append(sun_pm)

    # Rule 21: 指定教师周一到周五不排上午4（soft/hard 可切换）
    if cfg.enable_cc_weekday_no_am4 and has_teacher(T_CC):
        mode = norm_mode(cfg.cc_weekday_no_am4_mode)
        for d in ("星期一", "星期二", "星期三", "星期四", "星期五"):
            if d not in day_days:
                continue
            am4 = day_has_am4.get((T_CC, d), model.NewConstant(0))
            if mode == "hard":
                model.Add(am4 == 0)
            else:
                penalties.append(cfg.w_cc_weekday_no_am4 * am4)
                stats.setdefault("rule21_cc_weekday_no_am4", {"vars": [], "w": cfg.w_cc_weekday_no_am4})["vars"].append(am4)

    # Rule 22: 指定教师周六上午3/4若排课则排到17班（soft/hard 可切换）
    if cfg.enable_cc_sat_am34_class17 and T_SAT_TARGET_CLASS and has_teacher(T_CC) and "星期六" in day_days:
        mode = norm_mode(cfg.cc_sat_am34_class17_mode)
        misplaced_vars: List[cp_model.IntVar] = []
        for sk in ("上午3", "上午4"):
            misplaced = build_teacher_slot_misplaced_var(
                teacher=T_CC,
                day="星期六",
                slot_key=sk,
                target_cls=T_SAT_TARGET_CLASS,
                name_prefix=f"pers_cc_sat_{sk}",
            )
            misplaced_vars.append(misplaced)
        if mode == "hard":
            for mv in misplaced_vars:
                model.Add(mv == 0)
        else:
            for mv in misplaced_vars:
                penalties.append(cfg.w_cc_sat_am34_class17 * mv)
                stats.setdefault("rule22_cc_sat_am34_class17", {"vars": [], "w": cfg.w_cc_sat_am34_class17})["vars"].append(mv)

    # Rule 23: 指定教师周一上午不排课（soft/hard 可切换）
    if cfg.enable_sm_mon_no_am and has_teacher(T_SM) and "星期一" in day_days:
        mon_am = day_has_am_any.get((T_SM, "星期一"), model.NewConstant(0))
        if norm_mode(cfg.sm_mon_no_am_mode) == "hard":
            model.Add(mon_am == 0)
        else:
            penalties.append(cfg.w_sm_mon_no_am * mon_am)
            stats.setdefault("rule23_sm_mon_no_am", {"vars": [], "w": cfg.w_sm_mon_no_am})["vars"].append(mon_am)

    # Rule 24: 指定教师周一下午不排下午1（soft/hard 可切换）
    if cfg.enable_sm_mon_no_pm1 and has_teacher(T_SM) and "星期一" in day_days:
        mon_pm1 = day_has_pm1.get((T_SM, "星期一"), model.NewConstant(0))
        if norm_mode(cfg.sm_mon_no_pm1_mode) == "hard":
            model.Add(mon_pm1 == 0)
        else:
            penalties.append(cfg.w_sm_mon_no_pm1 * mon_pm1)
            stats.setdefault("rule24_sm_mon_no_pm1", {"vars": [], "w": cfg.w_sm_mon_no_pm1})["vars"].append(mon_pm1)

    # Rule 31: 指定教师/指定教师 周日白天课程固定在上午1和上午2（soft/hard 可切换）
    if cfg.enable_mrj_hsm_sun_am12_fixed and "星期日" in day_days:
        mode = norm_mode(cfg.mrj_hsm_sun_am12_fixed_mode)
        for t in (T_MRJ, T_HSM):
            if not has_teacher(t):
                continue
            sun_am1 = day_has_am1.get((t, "星期日"), model.NewConstant(0))
            sun_am2 = day_has_am2.get((t, "星期日"), model.NewConstant(0))
            miss_am1 = model.NewIntVar(0, 1, f"pers_rule31_miss_am1[{t}]")
            miss_am2 = model.NewIntVar(0, 1, f"pers_rule31_miss_am2[{t}]")
            model.Add(miss_am1 + sun_am1 == 1)
            model.Add(miss_am2 + sun_am2 == 1)
            if mode == "hard":
                model.Add(miss_am1 == 0)
                model.Add(miss_am2 == 0)
            else:
                penalties.append(cfg.w_mrj_hsm_sun_am12_fixed * miss_am1)
                penalties.append(cfg.w_mrj_hsm_sun_am12_fixed * miss_am2)
            st = stats.setdefault(
                "rule31_mrj_hsm_sun_am12_fixed",
                {"vars": [], "w": cfg.w_mrj_hsm_sun_am12_fixed, "mode": mode, "days": []},
            )
            st["vars"].extend([miss_am1, miss_am2])
            st["days"].extend(["星期日", "星期日"])

    # Rule 42: 指定教师周四下午不得安排课程（硬约束）
    if has_teacher(T_MRJ) and "星期四" in day_days:
        thu_pm_any = day_has_pm_any.get((T_MRJ, "星期四"), model.NewConstant(0))
        model.Add(thu_pm_any == 0)
