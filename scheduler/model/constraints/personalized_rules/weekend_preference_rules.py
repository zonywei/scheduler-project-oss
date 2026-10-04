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
    # Rule 4: 指定教师 周日 AM1+AM2
    # weight: personalized_constraints.w_lm_sun_am12（建议 200/400/800）
    if cfg.enable_lm_sun_am12 and has_teacher(T_LM):
        lm_mode = norm_mode(cfg.lm_sun_am12_mode)
        if "星期日" in day_days:
            sun_am1 = day_has_am1.get((T_LM, "星期日"), model.NewConstant(0))
            sun_am2 = day_has_am2.get((T_LM, "星期日"), model.NewConstant(0))
            if lm_mode == "hard":
                model.Add(sun_am1 == 1)
                model.Add(sun_am2 == 1)
            else:
                inv1 = model.NewIntVar(0, 1, "pers_lm_sun_am1")
                inv2 = model.NewIntVar(0, 1, "pers_lm_sun_am2")
                model.Add(inv1 + sun_am1 == 1)
                model.Add(inv2 + sun_am2 == 1)
                penalties.append(cfg.w_lm_sun_am12 * inv1)
                penalties.append(cfg.w_lm_sun_am12 * inv2)
                stats.setdefault("rule4", {"vars": [], "w": cfg.w_lm_sun_am12})["vars"].extend([inv1, inv2])
        else:
            if lm_mode == "hard":
                logger.warning("Rule4(hard) skipped: missing Sunday in day calendar")
                hard_notes.append("Rule4(hard): missing Sunday in day calendar")
            else:
                hard_notes.append("Rule4: missing Sunday in day calendar")

    # Rule 5: 指定教师 周日 AM + 不要周日晚
    # weight: personalized_constraints.w_ytt_sun_am_pref / w_ytt_no_sun_night（建议 60/80/150）
    if cfg.enable_ytt_sun_pref and has_teacher(T_YTT):
        ytt_mode = norm_mode(cfg.ytt_sun_pref_mode)
        if "星期日" in day_days:
            sun_am_any = day_has_am_any.get((T_YTT, "星期日"), model.NewConstant(0))
            if ytt_mode == "hard":
                model.Add(sun_am_any == 1)
            else:
                inv = model.NewIntVar(0, 1, "pers_ytt_sun_am_inv")
                model.Add(inv + sun_am_any == 1)
                penalties.append(cfg.w_ytt_sun_am_pref * inv)
                stats.setdefault("rule5_am", {"vars": [], "w": cfg.w_ytt_sun_am_pref})["vars"].append(inv)
        elif ytt_mode == "hard":
            logger.warning("Rule5(hard) AM skipped: missing Sunday in day calendar")
            hard_notes.append("Rule5(hard): missing Sunday in day calendar for AM rule")
        if "星期日" in night_days:
            sun_night = night_on.get((T_YTT, "星期日"), model.NewConstant(0))
            if ytt_mode == "hard":
                model.Add(sun_night == 0)
            else:
                penalties.append(cfg.w_ytt_no_sun_night * sun_night)
                stats.setdefault("rule5_night", {"vars": [], "w": cfg.w_ytt_no_sun_night})["vars"].append(sun_night)
        elif ytt_mode == "hard":
            logger.warning("Rule5(hard) night skipped: missing Sunday in night calendar")
            hard_notes.append("Rule5(hard): missing Sunday in night calendar for night rule")

    # Rule 6: 指定教师 仅周日禁排晚自习（硬）
    if cfg.enable_dym_no_fri_sun_night and has_teacher(T_DYM):
        if "星期日" in night_days:
            model.Add(night_on.get((T_DYM, "星期日"), model.NewConstant(0)) == 0)

    # Rule 7: 政治周日晚自习禁排（soft/hard 可切换；指定教师例外）
    # soft weight: personalized_constraints.w_pol_sun_teacher_count / w_pol_sun_super（建议 300/600）
    if cfg.enable_pol_no_sun_night and night_ctx:
        pol_mode = _norm_mode(cfg.pol_no_sun_night_mode, "soft")
        pol_teachers = {tch for (cls, subj), tch in night_ctx["cst"].items() if subj == "政治"}
        pol_teachers = {t for t in pol_teachers if t != T_POL_EXEMPT}
        if "星期日" in night_days:
            if pol_mode == "hard":
                for t in pol_teachers:
                    model.Add(night_on.get((t, "星期日"), model.NewConstant(0)) == 0)
            else:
                count_pol = model.NewIntVar(0, len(pol_teachers), "pol_sun_count")
                model.Add(count_pol == sum(night_on.get((t, "星期日"), model.NewConstant(0)) for t in pol_teachers))
                penalties.append(cfg.w_pol_sun_teacher_count * count_pol)
                penalties.append(cfg.w_pol_sun_super * count_pol)
                stats.setdefault("rule7_cnt", {"vars": [], "w": cfg.w_pol_sun_teacher_count})["vars"].append(count_pol)
                stats.setdefault("rule7_super", {"vars": [], "w": cfg.w_pol_sun_super})["vars"].append(count_pol)

    # Rule 8: 指定教师 少排下午
    # weight: personalized_constraints.w_ld_reduce_pm（建议 60/80/150）
    if cfg.enable_ld_reduce_pm and has_teacher(T_LD):
        ld_mode = norm_mode(cfg.ld_reduce_pm_mode)
        count_pm = model.NewIntVar(0, len(day_days), "ld_pm_count")
        model.Add(count_pm == sum(day_has_pm_any.get((T_LD, d), model.NewConstant(0)) for d in day_days))
        if ld_mode == "hard":
            model.Add(count_pm == 0)
        else:
            penalties.append(cfg.w_ld_reduce_pm * count_pm)
            stats.setdefault("rule8", {"vars": [], "w": cfg.w_ld_reduce_pm})["vars"].append(count_pm)

    # Rule 32/33: 指定教师周二到周五下午课惩罚（固定软约束）
    # - 周二到周五下午每排一节：w_ld_tue_fri_pm_each
    # - 周二到周五下午1每排一节额外：w_ld_tue_fri_pm1_extra_each
    if cfg.enable_ld_tue_fri_pm_penalty and has_teacher(T_LD) and day_data is not None and day_vars is not None:
        target_days = {"星期二", "星期三", "星期四", "星期五"}
        pm_stats = stats.setdefault(
            "rule32_ld_tue_fri_pm_each",
            {"vars": [], "w": cfg.w_ld_tue_fri_pm_each, "days": []},
        )
        pm1_stats = stats.setdefault(
            "rule33_ld_tue_fri_pm1_extra_each",
            {"vars": [], "w": cfg.w_ld_tue_fri_pm1_extra_each, "days": []},
        )
        for (cls, subj, slot), var in day_vars.x.items():
            if slot.day not in target_days or slot.block != "下午":
                continue
            if _norm_name(day_data.cls_subj_teacher.get((cls, subj), "")) != _norm_name(T_LD):
                continue
            penalties.append(cfg.w_ld_tue_fri_pm_each * var)
            pm_stats["vars"].append(var)
            pm_stats["days"].append(slot.day)
            if _slot_key(slot) == "下午1":
                penalties.append(cfg.w_ld_tue_fri_pm1_extra_each * var)
                pm1_stats["vars"].append(var)
                pm1_stats["days"].append(slot.day)
        # 固排课同样计入该软约束罚分（常数项，不改变可行域）
        for (cls, slot), subj in day_data.fixed_assign.items():
            if slot.day not in target_days or slot.block != "下午":
                continue
            if _norm_name(day_data.cls_subj_teacher.get((cls, subj), "")) != _norm_name(T_LD):
                continue
            one = model.NewConstant(1)
            penalties.append(cfg.w_ld_tue_fri_pm_each * one)
            pm_stats["vars"].append(one)
            pm_stats["days"].append(slot.day)
            if _slot_key(slot) == "下午1":
                penalties.append(cfg.w_ld_tue_fri_pm1_extra_each * one)
                pm1_stats["vars"].append(one)
                pm1_stats["days"].append(slot.day)

    # Rule 40: 指定教师周一/周二/周四/周五下午不允许排课（硬约束）
    if cfg.enable_ld_no_mon_pm and has_teacher(T_LD):
        for d in ("星期一", "星期二", "星期四", "星期五"):
            if d not in day_days:
                continue
            pm_any = day_has_pm_any.get((T_LD, d), model.NewConstant(0))
            model.Add(pm_any == 0)

    # Rule 9: 指定教师 周一/周五 下午3 禁排（硬）
    if cfg.enable_zfj_ban_mon_fri_pm3 and has_teacher(T_ZFJ_PM3):
        if "星期一" in day_days:
            model.Add(day_has_pm3.get((T_ZFJ_PM3, "星期一"), model.NewConstant(0)) == 0)
        if "星期五" in day_days:
            model.Add(day_has_pm3.get((T_ZFJ_PM3, "星期五"), model.NewConstant(0)) == 0)

    # Rule 16: 指定教师晚查寝惩罚（固定软约束）
    # weight: personalized_constraints.w_zfj_night_checkin_penalty（建议 500/1000/2000）
    if cfg.enable_zfj_night_checkin_penalty:
        zfj_name = T_ZFJ_CHECKIN
        checkin_m = (night_vars or {}).get("checkin_m", {}) or {}
        zfj_vars: List[cp_model.IntVar] = []
        zfj_days: List[str] = []
        for (teacher, day), var in checkin_m.items():
            if _norm_name(teacher) == _norm_name(zfj_name):
                penalties.append(cfg.w_zfj_night_checkin_penalty * var)
                zfj_vars.append(var)
                zfj_days.append(str(day))
        if zfj_vars:
            stats.setdefault(
                "rule16_zfj_night_checkin_penalty",
                {"vars": [], "days": [], "w": cfg.w_zfj_night_checkin_penalty},
            )["vars"].extend(zfj_vars)
            stats["rule16_zfj_night_checkin_penalty"]["days"].extend(zfj_days)

    # Rule 10: 指定教师
    # weight: personalized_constraints.w_jxq_no_mon_am1 / w_jxq_sun_pm_pref / w_jxq_no_sun_night
    if cfg.enable_jxq_prefs and has_teacher(T_JXQ):
        jxq_mode = norm_mode(cfg.jxq_prefs_mode)
        if "星期一" in day_days:
            mon_am1 = day_has_am1.get((T_JXQ, "星期一"), model.NewConstant(0))
            if jxq_mode == "hard":
                model.Add(mon_am1 == 0)
            else:
                penalties.append(cfg.w_jxq_no_mon_am1 * mon_am1)
                stats.setdefault("rule10_mon_am1", {"vars": [], "w": cfg.w_jxq_no_mon_am1})["vars"].append(mon_am1)
        if "星期日" in day_days:
            sun_pm_any = day_has_pm_any.get((T_JXQ, "星期日"), model.NewConstant(0))
            if jxq_mode == "hard":
                model.Add(sun_pm_any == 1)
            else:
                inv = model.NewIntVar(0, 1, "jxq_sun_pm_inv")
                model.Add(inv + sun_pm_any == 1)
                penalties.append(cfg.w_jxq_sun_pm_pref * inv)
                stats.setdefault("rule10_sun_pm", {"vars": [], "w": cfg.w_jxq_sun_pm_pref})["vars"].append(inv)
        if "星期日" in night_days:
            sun_night = night_on.get((T_JXQ, "星期日"), model.NewConstant(0))
            if jxq_mode == "hard":
                model.Add(sun_night == 0)
            else:
                penalties.append(cfg.w_jxq_no_sun_night * sun_night)
                stats.setdefault("rule10_sun_night", {"vars": [], "w": cfg.w_jxq_no_sun_night})["vars"].append(sun_night)

    # Rule 11: 指定教师
    # weight: personalized_constraints.w_csqi_sun_am_pref / w_csqi_night_outside_pen / w_csqi_need_sun_or_mon
    if cfg.enable_csqi_prefs and has_teacher(T_CSQI):
        csqi_mode = norm_mode(cfg.csqi_prefs_mode)
        if "星期日" in day_days:
            sun_am_any = day_has_am_any.get((T_CSQI, "星期日"), model.NewConstant(0))
            if csqi_mode == "hard":
                model.Add(sun_am_any == 1)
            else:
                inv = model.NewIntVar(0, 1, "csqi_sun_am_inv")
                model.Add(inv + sun_am_any == 1)
                penalties.append(cfg.w_csqi_sun_am_pref * inv)
                stats.setdefault("rule11_sun_am", {"vars": [], "w": cfg.w_csqi_sun_am_pref})["vars"].append(inv)
        outside = [d for d in night_days if d not in ("星期日", "星期一")]
        if outside:
            count_out = model.NewIntVar(0, len(outside), "csqi_outside_count")
            model.Add(count_out == sum(night_on.get((T_CSQI, d), model.NewConstant(0)) for d in outside))
            if csqi_mode == "hard":
                model.Add(count_out == 0)
            else:
                penalties.append(cfg.w_csqi_night_outside_pen * count_out)
                stats.setdefault("rule11_outside", {"vars": [], "w": cfg.w_csqi_night_outside_pen})["vars"].append(count_out)
        if "星期日" in night_days or "星期一" in night_days:
            ok = model.NewBoolVar("csqi_need_sun_or_mon")
            cand = []
            if "星期日" in night_days:
                cand.append(night_on.get((T_CSQI, "星期日"), model.NewConstant(0)))
            if "星期一" in night_days:
                cand.append(night_on.get((T_CSQI, "星期一"), model.NewConstant(0)))
            if cand:
                model.AddMaxEquality(ok, cand)
                if csqi_mode == "hard":
                    model.Add(ok == 1)
                else:
                    inv = model.NewIntVar(0, 1, "csqi_need_sun_or_mon_inv")
                    model.Add(inv + ok == 1)
                    penalties.append(cfg.w_csqi_need_sun_or_mon * inv)
                    stats.setdefault("rule11_need", {"vars": [], "w": cfg.w_csqi_need_sun_or_mon})["vars"].append(inv)

    # Rule 30: 指定教师晚自习需连续两天（soft/hard 可切换；周日→周一视为连续）
    if cfg.enable_csqi_need_consecutive_night and has_teacher(T_CSQI):
        csqi_consec_mode = norm_mode(cfg.csqi_need_consecutive_night_mode)
        if len(night_days) >= 2:
            pairs: List[Tuple[str, str]] = adjacent_day_pairs(night_days, include_sun_mon=True)
            consec_vars: List[cp_model.IntVar] = []
            for d1, d2 in pairs:
                a = night_on.get((T_CSQI, d1), model.NewConstant(0))
                b = night_on.get((T_CSQI, d2), model.NewConstant(0))
                z = model.NewBoolVar(f"csqi_consec[{d1},{d2}]")
                model.Add(z <= a)
                model.Add(z <= b)
                model.Add(z >= a + b - 1)
                consec_vars.append(z)
            if consec_vars:
                any_consec = model.NewBoolVar("csqi_any_consec")
                model.AddMaxEquality(any_consec, consec_vars)
                if csqi_consec_mode == "hard":
                    model.Add(any_consec == 1)
                else:
                    inv = model.NewIntVar(0, 1, "csqi_consec_inv")
                    model.Add(inv + any_consec == 1)
                    penalties.append(cfg.w_csqi_need_consecutive_night * inv)
                    stats.setdefault("rule30_csqi_consecutive_night", {"vars": [], "w": cfg.w_csqi_need_consecutive_night})["vars"].append(inv)
        elif csqi_consec_mode == "hard":
            logger.warning("Rule30(hard) consecutive skipped: night day count < 2")
            hard_notes.append("Rule30(hard): night day count < 2 for csqi consecutive requirement")

    # Rule 12: 指定教师
    # weight: personalized_constraints.w_zzx_no_sun_night / w_zzx_sun_am_pref / w_zzx_reduce_am4
    if cfg.enable_zzx_prefs and has_teacher(T_ZZX):
        zzx_mode = norm_mode(cfg.zzx_prefs_mode)
        if "星期日" in night_days and not cfg.enable_zzx_no_sunday_night:
            sun_night = night_on.get((T_ZZX, "星期日"), model.NewConstant(0))
            if zzx_mode == "hard":
                model.Add(sun_night == 0)
            else:
                penalties.append(cfg.w_zzx_no_sun_night * sun_night)
                stats.setdefault("rule12_sun_night", {"vars": [], "w": cfg.w_zzx_no_sun_night})["vars"].append(sun_night)
        if "星期日" in day_days:
            sun_am_any = day_has_am_any.get((T_ZZX, "星期日"), model.NewConstant(0))
            if zzx_mode == "hard":
                model.Add(sun_am_any == 1)
            else:
                inv = model.NewIntVar(0, 1, "zzx_sun_am_inv")
                model.Add(inv + sun_am_any == 1)
                penalties.append(cfg.w_zzx_sun_am_pref * inv)
                stats.setdefault("rule12_sun_am", {"vars": [], "w": cfg.w_zzx_sun_am_pref})["vars"].append(inv)
        count_am4 = model.NewIntVar(0, len(day_days), "zzx_am4_cnt")
        model.Add(count_am4 == sum(day_has_am4.get((T_ZZX, d), model.NewConstant(0)) for d in day_days))
        if zzx_mode == "hard":
            model.Add(count_am4 == 0)
        else:
            penalties.append(cfg.w_zzx_reduce_am4 * count_am4)
            stats.setdefault("rule12_am4", {"vars": [], "w": cfg.w_zzx_reduce_am4})["vars"].append(count_am4)

    # Rule 34: 指定教师不排周日晚自习（soft/hard 可切换）
    if cfg.enable_zzx_no_sunday_night and has_teacher(T_ZZX) and "星期日" in night_days:
        sun_night = night_on.get((T_ZZX, "星期日"), model.NewConstant(0))
        if norm_mode(cfg.zzx_no_sunday_night_mode) == "hard":
            model.Add(sun_night == 0)
        else:
            penalties.append(cfg.w_zzx_no_sunday_night * sun_night)
            stats.setdefault("rule34_zzx_no_sunday_night", {"vars": [], "w": cfg.w_zzx_no_sunday_night})["vars"].append(sun_night)

    # Rule 38: 指定教师晚自习仅允许排在指定日期（soft/hard 可切换）
    if cfg.enable_xyx_night_days_only and has_teacher(T_XYX) and night_days:
        xyx_mode = norm_mode(cfg.xyx_night_days_only_mode)
        allowed_days = {str(d).strip() for d in (cfg.xyx_night_allowed_days or []) if str(d).strip()}
        if not allowed_days:
            allowed_days = {"星期五", "星期日"}
        for d in night_days:
            if d in allowed_days:
                continue
            z = night_on.get((T_XYX, d), model.NewConstant(0))
            if xyx_mode == "hard":
                model.Add(z == 0)
            else:
                penalties.append(cfg.w_xyx_night_days_only * z)
                st = stats.setdefault(
                    "rule38_xyx_night_days_only",
                    {"vars": [], "w": cfg.w_xyx_night_days_only, "mode": "soft", "days": []},
                )
                st["vars"].append(z)
                st["days"].append(d)

    # Rule 13: 指定教师
    # weight: personalized_constraints.w_hwj_need_sun_mon / w_hwj_need_consecutive
    if cfg.enable_hwj_prefs and has_teacher(T_HWJ):
        hwj_pref_mode = norm_mode(cfg.hwj_prefs_mode)
        if "星期日" in night_days and "星期一" in night_days:
            sun = night_on.get((T_HWJ, "星期日"), model.NewConstant(0))
            mon = night_on.get((T_HWJ, "星期一"), model.NewConstant(0))
            if hwj_pref_mode == "hard":
                model.Add(sun == 1)
                model.Add(mon == 1)
            else:
                inv1 = model.NewIntVar(0, 1, "hwj_sun_inv")
                inv2 = model.NewIntVar(0, 1, "hwj_mon_inv")
                model.Add(inv1 + sun == 1)
                model.Add(inv2 + mon == 1)
                penalties.append(cfg.w_hwj_need_sun_mon * inv1)
                penalties.append(cfg.w_hwj_need_sun_mon * inv2)
                stats.setdefault("rule13_need", {"vars": [], "w": cfg.w_hwj_need_sun_mon})["vars"].extend([inv1, inv2])
        elif hwj_pref_mode == "hard":
            logger.warning("Rule13(hard) need_sun_mon skipped: missing Sunday or Monday in night calendar")
            hard_notes.append("Rule13(hard): missing Sunday or Monday in night calendar for sun/mon requirement")
        if len(night_days) >= 2:
            consec_list = []
            pairs = adjacent_day_pairs(night_days, include_sun_mon=True)
            for d1, d2 in pairs:
                a = night_on.get((T_HWJ, d1), model.NewConstant(0))
                b = night_on.get((T_HWJ, d2), model.NewConstant(0))
                z = model.NewBoolVar(f"hwj_consec[{d1},{d2}]")
                model.Add(z <= a)
                model.Add(z <= b)
                model.Add(z >= a + b - 1)
                consec_list.append(z)
            if consec_list:
                any_consec = model.NewBoolVar("hwj_any_consec")
                model.AddMaxEquality(any_consec, consec_list)
                if hwj_pref_mode == "hard":
                    model.Add(any_consec == 1)
                else:
                    inv = model.NewIntVar(0, 1, "hwj_consec_inv")
                    model.Add(inv + any_consec == 1)
                    penalties.append(cfg.w_hwj_need_consecutive * inv)
                    stats.setdefault("rule13_consec", {"vars": [], "w": cfg.w_hwj_need_consecutive})["vars"].append(inv)
        elif hwj_pref_mode == "hard":
            logger.warning("Rule13(hard) consecutive skipped: night day count < 2")
            hard_notes.append("Rule13(hard): night day count < 2 for consecutive requirement")

    # Rule 13.1: 指定教师晚自习安排在周日与周一（soft/hard 可切换）
    # soft weight: personalized_constraints.w_hwj_night_sun_mon_assign（默认 2000）
    if cfg.enable_hwj_night_sun_mon_assign and has_teacher(T_HWJ):
        hwj_mode = _norm_mode(cfg.hwj_night_sun_mon_assign_mode, "hard")
        if "星期日" in night_days:
            sun = night_on.get((T_HWJ, "星期日"), model.NewConstant(0))
            miss_sun = model.NewIntVar(0, 1, "hwj_need_sun_miss")
            model.Add(miss_sun + sun == 1)
            if hwj_mode == "hard":
                model.Add(miss_sun == 0)
                stats.setdefault(
                    "rule13_hwj_sun_mon_assign",
                    {"vars": [], "w": cfg.w_hwj_night_sun_mon_assign, "mode": "hard"},
                )["vars"].append(miss_sun)
            else:
                penalties.append(cfg.w_hwj_night_sun_mon_assign * miss_sun)
                stats.setdefault(
                    "rule13_hwj_sun_mon_assign",
                    {"vars": [], "w": cfg.w_hwj_night_sun_mon_assign, "mode": "soft"},
                )["vars"].append(miss_sun)
        if "星期一" in night_days:
            mon = night_on.get((T_HWJ, "星期一"), model.NewConstant(0))
            miss_mon = model.NewIntVar(0, 1, "hwj_need_mon_miss")
            model.Add(miss_mon + mon == 1)
            if hwj_mode == "hard":
                model.Add(miss_mon == 0)
                stats.setdefault(
                    "rule13_hwj_sun_mon_assign",
                    {"vars": [], "w": cfg.w_hwj_night_sun_mon_assign, "mode": "hard"},
                )["vars"].append(miss_mon)
            else:
                penalties.append(cfg.w_hwj_night_sun_mon_assign * miss_mon)
                stats.setdefault(
                    "rule13_hwj_sun_mon_assign",
                    {"vars": [], "w": cfg.w_hwj_night_sun_mon_assign, "mode": "soft"},
                )["vars"].append(miss_mon)
