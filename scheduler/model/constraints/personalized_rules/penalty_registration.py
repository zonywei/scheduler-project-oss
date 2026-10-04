# -*- coding: utf-8 -*-
from __future__ import annotations

from scheduler.diagnostics.penalty_registry import register
from scheduler.model.constraints.personalized_rules.context import PersonalizedRuleContext


def register_personalized_penalties(ctx: PersonalizedRuleContext) -> None:
    stats = ctx.stats
    T_XHD = ctx.T_XHD
    T_ZFY = ctx.T_ZFY
    T_ZW = ctx.T_ZW
    T_LM = ctx.T_LM
    T_YTT = ctx.T_YTT
    T_LD = ctx.T_LD
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
    # 统一登记个性化软约束到 penalty_registry（不改变目标，仅补充可追溯元数据）
    # 说明：
    # - 这里按 stats 中已经参与 objective 的变量登记，不新增任何约束/罚分。
    # - 个别规则含多级权重（weights 列表），按同索引逐项登记。
    weight_key_map = {
        "rule1": "personalized_constraints.w_xhd_night_no_pm3",
        "rule28_xhd_night_no_pm": "personalized_constraints.w_xhd_night_no_pm",
        "rule2_diff": "personalized_constraints.w_couple_diff_day",
        "rule2_overlap": "personalized_constraints.w_couple_need_overlap",
        "rule2_couple_overlap_soft": "personalized_constraints.w_couple_need_overlap",
        "rule3": "personalized_constraints.w_zw_night_need_pm",
        "rule25_zw_am1_cap": "personalized_constraints.w_zw_am1_cap",
        "rule26_zw_am2_cap": "personalized_constraints.w_zw_am2_cap",
        "rule27_zw_am4_cap": "personalized_constraints.w_zw_am4_cap",
        "rule37_zw_weekday_pm1_cap": "personalized_constraints.w_zw_weekday_pm1_cap",
        "rule4": "personalized_constraints.w_lm_sun_am12",
        "rule5_am": "personalized_constraints.w_ytt_sun_am_pref",
        "rule5_night": "personalized_constraints.w_ytt_no_sun_night",
        "rule7_cnt": "personalized_constraints.w_pol_sun_teacher_count",
        "rule7_super": "personalized_constraints.w_pol_sun_super",
        "rule8": "personalized_constraints.w_ld_reduce_pm",
        "rule32_ld_tue_fri_pm_each": "personalized_constraints.w_ld_tue_fri_pm_each",
        "rule33_ld_tue_fri_pm1_extra_each": "personalized_constraints.w_ld_tue_fri_pm1_extra_each",
        "rule16_zfj_night_checkin_penalty": "personalized_constraints.w_zfj_night_checkin_penalty",
        "rule10_mon_am1": "personalized_constraints.w_jxq_no_mon_am1",
        "rule10_sun_pm": "personalized_constraints.w_jxq_sun_pm_pref",
        "rule10_sun_night": "personalized_constraints.w_jxq_no_sun_night",
        "rule11_sun_am": "personalized_constraints.w_csqi_sun_am_pref",
        "rule11_outside": "personalized_constraints.w_csqi_night_outside_pen",
        "rule11_need": "personalized_constraints.w_csqi_need_sun_or_mon",
        "rule30_csqi_consecutive_night": "personalized_constraints.w_csqi_need_consecutive_night",
        "rule12_sun_night": "personalized_constraints.w_zzx_no_sun_night",
        "rule12_sun_am": "personalized_constraints.w_zzx_sun_am_pref",
        "rule12_am4": "personalized_constraints.w_zzx_reduce_am4",
        "rule34_zzx_no_sunday_night": "personalized_constraints.w_zzx_no_sunday_night",
        "rule38_xyx_night_days_only": "personalized_constraints.w_xyx_night_days_only",
        "rule13_need": "personalized_constraints.w_hwj_need_sun_mon",
        "rule13_consec": "personalized_constraints.w_hwj_need_consecutive",
        "rule13_hwj_sun_mon_assign": "personalized_constraints.w_hwj_night_sun_mon_assign",
        "rule14": "personalized_constraints.w_hsm_no_fri_night",
        "rule35_hsm_weekday_early_no_am1": "personalized_constraints.w_hsm_weekday_early_no_am1",
        "rule36_wxl_weekday_early_no_am1": "personalized_constraints.w_wxl_weekday_early_no_am1",
        "rule39_dln_weekday_no_am1": "personalized_constraints.w_dln_weekday_no_am1",
        "rule15_am1": "personalized_constraints.w_zhoubo_weekday_am1_penalty",
        "rule17_xww_am4_pm1": "personalized_constraints.w_xww_weekday_am4_pm1_e2/e3/e4",
        "rule18_zfy_consecutive_night": "personalized_constraints.w_zfy_no_consecutive_night",
        "rule19_zfy_no_sunday_night": "personalized_constraints.w_zfy_no_sunday_night",
        "rule20_sll_sun_am_only": "personalized_constraints.w_sll_sun_am_only",
        "rule21_cc_weekday_no_am4": "personalized_constraints.w_cc_weekday_no_am4",
        "rule22_cc_sat_am34_class17": "personalized_constraints.w_cc_sat_am34_class17",
        "rule23_sm_mon_no_am": "personalized_constraints.w_sm_mon_no_am",
        "rule24_sm_mon_no_pm1": "personalized_constraints.w_sm_mon_no_pm1",
        "rule29_zw_no_consecutive_night": "personalized_constraints.w_zw_no_consecutive_night",
        "rule31_mrj_hsm_sun_am12_fixed": "personalized_constraints.w_mrj_hsm_sun_am12_fixed",
    }
    teacher_map = {
        "rule1": T_XHD,
        "rule28_xhd_night_no_pm": T_XHD,
        "rule2_diff": f"{T_XHD}/{T_ZFY}",
        "rule2_overlap": f"{T_XHD}/{T_ZFY}",
        "rule2_couple_overlap_soft": f"{T_XHD}/{T_ZFY}",
        "rule3": T_ZW,
        "rule25_zw_am1_cap": T_ZW,
        "rule26_zw_am2_cap": T_ZW,
        "rule27_zw_am4_cap": T_ZW,
        "rule37_zw_weekday_pm1_cap": T_ZW,
        "rule4": T_LM,
        "rule5_am": T_YTT,
        "rule5_night": T_YTT,
        "rule8": T_LD,
        "rule32_ld_tue_fri_pm_each": T_LD,
        "rule33_ld_tue_fri_pm1_extra_each": T_LD,
        "rule16_zfj_night_checkin_penalty": T_ZFJ_CHECKIN,
        "rule10_mon_am1": T_JXQ,
        "rule10_sun_pm": T_JXQ,
        "rule10_sun_night": T_JXQ,
        "rule11_sun_am": T_CSQI,
        "rule11_outside": T_CSQI,
        "rule11_need": T_CSQI,
        "rule30_csqi_consecutive_night": T_CSQI,
        "rule12_sun_night": T_ZZX,
        "rule12_sun_am": T_ZZX,
        "rule12_am4": T_ZZX,
        "rule34_zzx_no_sunday_night": T_ZZX,
        "rule38_xyx_night_days_only": T_XYX,
        "rule13_need": T_HWJ,
        "rule13_consec": T_HWJ,
        "rule13_hwj_sun_mon_assign": T_HWJ,
        "rule14": T_HSM,
        "rule35_hsm_weekday_early_no_am1": T_HSM,
        "rule36_wxl_weekday_early_no_am1": T_WXL,
        "rule39_dln_weekday_no_am1": T_DLN,
        "rule15_am1": T_ZB,
        "rule17_xww_am4_pm1": T_XWW,
        "rule18_zfy_consecutive_night": T_ZFY,
        "rule19_zfy_no_sunday_night": T_ZFY,
        "rule20_sll_sun_am_only": T_SLL,
        "rule21_cc_weekday_no_am4": T_CC,
        "rule22_cc_sat_am34_class17": T_CC,
        "rule23_sm_mon_no_am": T_SM,
        "rule24_sm_mon_no_pm1": T_SM,
        "rule29_zw_no_consecutive_night": T_ZW,
        "rule31_mrj_hsm_sun_am12_fixed": f"{T_MRJ},{T_HSM}",
    }
    for skey, sinfo in stats.items():
        vars_list = list(sinfo.get("vars", []))
        if not vars_list:
            continue
        day_labels = list(sinfo.get("days", []))
        weights = sinfo.get("weights")
        if isinstance(weights, list) and len(weights) == len(vars_list):
            pairs = zip(vars_list, weights)
        else:
            pairs = ((v, sinfo.get("w", 0)) for v in vars_list)
        for i, (v, w) in enumerate(pairs):
            register(
                rule_id=f"personalized_{skey}",
                rule_name=f"个性化约束::{skey}",
                weight=int(w),
                var=v,
                teacher=teacher_map.get(skey, "GLOBAL"),
                day=day_labels[i] if i < len(day_labels) else "",
                constraint_category="preference",
                mode=str(sinfo.get("mode", "soft")),
                source_module="scheduler/model/constraints/personalized_constraints.py",
                weight_key=weight_key_map.get(skey, ""),
            )
