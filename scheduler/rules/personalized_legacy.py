# -*- coding: utf-8 -*-
"""Single source of truth for legacy personalized rule metadata.

These records are migration metadata. Solver execution still happens through
the existing personalized constraint call sites.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PersonalizedTargetSlot:
    slot_id: str
    label: str
    config_path: str
    value_kind: str = "teacher_list"


@dataclass(frozen=True)
class PersonalizedLegacyRule:
    rule_key: str
    target_slots: tuple[str, ...]
    title: str
    mode_key: str | None = None
    weight_key: str | None = None


def personalized_template_id(rule_key: str) -> str:
    """Return the audit template id for one legacy personalized rule."""
    key = str(rule_key or "").strip()
    if key.startswith("enable_"):
        key = key[len("enable_"):]
    return f"personalized.{key}"


PERSONALIZED_TARGET_SLOTS = (
    PersonalizedTargetSlot("xhd", "晚自习-白天下午联动目标教师", "personalized_constraints.teacher_targets.xhd"),
    PersonalizedTargetSlot("zfy", "连续晚自习与周日禁排目标教师", "personalized_constraints.teacher_targets.zfy"),
    PersonalizedTargetSlot("zw", "晚自习联动与节次上限目标教师", "personalized_constraints.teacher_targets.zw"),
    PersonalizedTargetSlot("lm", "周日白天与周日晚自习目标教师", "personalized_constraints.teacher_targets.lm"),
    PersonalizedTargetSlot("ytt", "周日偏好目标教师", "personalized_constraints.teacher_targets.ytt"),
    PersonalizedTargetSlot("dym", "周日晚自习禁排目标教师", "personalized_constraints.teacher_targets.dym"),
    PersonalizedTargetSlot(
        "pol_sunday_exempt",
        "政治组周日禁排例外教师",
        "personalized_constraints.teacher_targets.pol_sunday_exempt",
    ),
    PersonalizedTargetSlot("ld", "下午课减少与禁排目标教师", "personalized_constraints.teacher_targets.ld"),
    PersonalizedTargetSlot("zfj_pm3", "周一周五下午3禁排目标教师", "personalized_constraints.teacher_targets.zfj_pm3"),
    PersonalizedTargetSlot(
        "zfj_checkin",
        "晚查寝惩罚目标教师",
        "personalized_constraints.teacher_targets.zfj_checkin",
    ),
    PersonalizedTargetSlot("jxq", "周一上午1与周日偏好目标教师", "personalized_constraints.teacher_targets.jxq"),
    PersonalizedTargetSlot("csqi", "周日周一晚自习偏好目标教师", "personalized_constraints.teacher_targets.csqi"),
    PersonalizedTargetSlot("zzx", "周日与上午4偏好目标教师", "personalized_constraints.teacher_targets.zzx"),
    PersonalizedTargetSlot("xyx", "晚自习日期白名单目标教师", "personalized_constraints.teacher_targets.xyx"),
    PersonalizedTargetSlot("hwj", "周日周一晚自习目标教师", "personalized_constraints.teacher_targets.hwj"),
    PersonalizedTargetSlot("hsm", "周五晚自习与早自习联动目标教师", "personalized_constraints.teacher_targets.hsm"),
    PersonalizedTargetSlot("wxl", "早自习联动目标教师", "personalized_constraints.teacher_targets.wxl"),
    PersonalizedTargetSlot("dln", "上午1与周三晚自习目标教师", "personalized_constraints.teacher_targets.dln"),
    PersonalizedTargetSlot("zb", "硬性个人组合规则目标教师", "personalized_constraints.teacher_targets.zb"),
    PersonalizedTargetSlot("xww", "工作日 AM4/PM1 阶梯惩罚目标教师", "personalized_constraints.teacher_targets.xww"),
    PersonalizedTargetSlot("sll", "周日只排上午目标教师", "personalized_constraints.teacher_targets.sll"),
    PersonalizedTargetSlot("cc", "周六指定班级规则目标教师", "personalized_constraints.teacher_targets.cc"),
    PersonalizedTargetSlot(
        "cc_sat_am34_target_class",
        "周六上午3/4目标班级",
        "personalized_constraints.teacher_targets.cc_sat_am34_target_class",
        "class_id",
    ),
    PersonalizedTargetSlot("sm", "周一上午/下午1禁排目标教师", "personalized_constraints.teacher_targets.sm"),
    PersonalizedTargetSlot("mrj", "周日固定上午1+2目标教师", "personalized_constraints.teacher_targets.mrj"),
    PersonalizedTargetSlot(
        "custom_no_am1_teachers",
        "自定义上午1禁排名单",
        "personalized_constraints.custom_no_am1_teachers",
    ),
)


PERSONALIZED_LEGACY_RULES = (
    PersonalizedLegacyRule("enable_xhd_night_no_pm3", ("xhd",), "晚自习当天不排下午3", "xhd_night_no_pm3_mode", "w_xhd_night_no_pm3"),
    PersonalizedLegacyRule("enable_xhd_night_no_pm", ("xhd",), "晚自习当天不排下午课", "xhd_night_no_pm_mode", "w_xhd_night_no_pm"),
    PersonalizedLegacyRule("enable_couple_xhd_zfy", ("xhd", "zfy"), "两位教师至少同一天晚自习", "couple_xhd_zfy_mode", "w_couple_need_overlap"),
    PersonalizedLegacyRule("enable_zw_night_need_pm", ("zw",), "晚自习需要当天有下午课", "zw_night_need_pm_mode", "w_zw_night_need_pm"),
    PersonalizedLegacyRule("enable_zw_am1_cap", ("zw",), "上午1周次数上限", "zw_am1_cap_mode", "w_zw_am1_cap"),
    PersonalizedLegacyRule("enable_zw_am2_cap", ("zw",), "上午2周次数上限", "zw_am2_cap_mode", "w_zw_am2_cap"),
    PersonalizedLegacyRule("enable_zw_am4_cap", ("zw",), "上午4周次数上限", "zw_am4_cap_mode", "w_zw_am4_cap"),
    PersonalizedLegacyRule("enable_zw_weekday_pm1_cap", ("zw",), "工作日下午1次数上限", "zw_weekday_pm1_cap_mode", "w_zw_weekday_pm1_cap"),
    PersonalizedLegacyRule("enable_lm_sun_am12", ("lm",), "周日上午1和上午2偏好", "lm_sun_am12_mode", "w_lm_sun_am12"),
    PersonalizedLegacyRule("enable_ytt_sun_pref", ("ytt",), "周日上午偏好且减少周日晚自习", "ytt_sun_pref_mode", "w_ytt_no_sun_night"),
    PersonalizedLegacyRule("enable_dym_no_fri_sun_night", ("dym",), "周日晚自习禁排"),
    PersonalizedLegacyRule("enable_ld_reduce_pm", ("ld",), "减少下午课", "ld_reduce_pm_mode", "w_ld_reduce_pm"),
    PersonalizedLegacyRule("enable_ld_no_mon_pm", ("ld",), "周一/二/四/五下午禁排"),
    PersonalizedLegacyRule("enable_zfj_ban_mon_fri_pm3", ("zfj_pm3",), "周一和周五下午3禁排"),
    PersonalizedLegacyRule("enable_zfj_night_checkin_penalty", ("zfj_checkin",), "晚查寝惩罚", "zfj_night_checkin_penalty_mode", "w_zfj_night_checkin_penalty"),
    PersonalizedLegacyRule("enable_jxq_prefs", ("jxq",), "周一上午1与周日偏好", "jxq_prefs_mode", "w_jxq_no_mon_am1"),
    PersonalizedLegacyRule("enable_csqi_prefs", ("csqi",), "周日/周一晚自习偏好", "csqi_prefs_mode", "w_csqi_need_sun_or_mon"),
    PersonalizedLegacyRule("enable_csqi_need_consecutive_night", ("csqi",), "晚自习需要连续两天", "csqi_need_consecutive_night_mode", "w_csqi_need_consecutive_night"),
    PersonalizedLegacyRule("enable_zzx_prefs", ("zzx",), "周日与上午4偏好", "zzx_prefs_mode", "w_zzx_no_sun_night"),
    PersonalizedLegacyRule("enable_zzx_no_sunday_night", ("zzx",), "周日晚自习禁排", "zzx_no_sunday_night_mode", "w_zzx_no_sunday_night"),
    PersonalizedLegacyRule("enable_xyx_night_days_only", ("xyx",), "晚自习仅允许指定日期", "xyx_night_days_only_mode", "w_xyx_night_days_only"),
    PersonalizedLegacyRule("enable_hwj_prefs", ("hwj",), "周日周一与连续晚自习偏好", "hwj_prefs_mode", "w_hwj_need_sun_mon"),
    PersonalizedLegacyRule("enable_hwj_night_sun_mon_assign", ("hwj",), "晚自习安排在周日和周一", "hwj_night_sun_mon_assign_mode", "w_hwj_night_sun_mon_assign"),
    PersonalizedLegacyRule("enable_hsm_no_fri_night", ("hsm",), "周五晚自习禁排/减少", "hsm_no_fri_night_mode", "w_hsm_no_fri_night"),
    PersonalizedLegacyRule("enable_hsm_weekday_early_no_am1", ("hsm",), "有早自习则不排上午1", "hsm_weekday_early_no_am1_mode", "w_hsm_weekday_early_no_am1"),
    PersonalizedLegacyRule("enable_wxl_weekday_early_no_am1", ("wxl",), "有早自习则不排上午1", "wxl_weekday_early_no_am1_mode", "w_wxl_weekday_early_no_am1"),
    PersonalizedLegacyRule("enable_dln_weekday_no_am1", ("dln",), "工作日上午1禁排", "dln_weekday_no_am1_mode", "w_dln_weekday_no_am1"),
    PersonalizedLegacyRule("enable_custom_no_am1_teachers", ("custom_no_am1_teachers",), "自定义上午1禁排名单"),
    PersonalizedLegacyRule("enable_mrj_hsm_sun_am12_fixed", ("mrj", "hsm"), "周日固定上午1和上午2", "mrj_hsm_sun_am12_fixed_mode", "w_mrj_hsm_sun_am12_fixed"),
    PersonalizedLegacyRule("enable_zhoubo_hard", ("zb",), "硬性个人组合规则"),
    PersonalizedLegacyRule("enable_zhoubo_liumeng_same_night", ("zb", "lm"), "两位教师同天晚自习"),
    PersonalizedLegacyRule("enable_zhoubo_weekday_am1_penalty", ("zb",), "工作日上午1惩罚", "zhoubo_weekday_am1_penalty_mode", "w_zhoubo_weekday_am1_penalty"),
    PersonalizedLegacyRule("enable_liumeng_no_sunday", ("lm",), "周日晚自习禁排"),
    PersonalizedLegacyRule("enable_xww_weekday_am4_pm1_stair", ("xww",), "工作日 AM4/PM1 阶梯惩罚", "xww_weekday_am4_pm1_stair_mode", "w_xww_weekday_am4_pm1_e2"),
    PersonalizedLegacyRule("enable_zfy_no_consecutive_night", ("zfy",), "晚自习不连续两天", "zfy_no_consecutive_night_mode", "w_zfy_no_consecutive_night"),
    PersonalizedLegacyRule("enable_zw_no_consecutive_night", ("zw",), "晚自习不连续两天", "zw_no_consecutive_night_mode", "w_zw_no_consecutive_night"),
    PersonalizedLegacyRule("enable_zfy_no_sunday_night", ("zfy",), "周日晚自习禁排", "zfy_no_sunday_night_mode", "w_zfy_no_sunday_night"),
    PersonalizedLegacyRule("enable_sll_sun_am_only", ("sll",), "周日只排上午", "sll_sun_am_only_mode", "w_sll_sun_am_only"),
    PersonalizedLegacyRule("enable_cc_weekday_no_am4", ("cc",), "工作日上午4禁排", "cc_weekday_no_am4_mode", "w_cc_weekday_no_am4"),
    PersonalizedLegacyRule("enable_cc_sat_am34_class17", ("cc", "cc_sat_am34_target_class"), "周六上午3/4指定班级", "cc_sat_am34_class17_mode", "w_cc_sat_am34_class17"),
    PersonalizedLegacyRule("enable_sm_mon_no_am", ("sm",), "周一上午禁排", "sm_mon_no_am_mode", "w_sm_mon_no_am"),
    PersonalizedLegacyRule("enable_sm_mon_no_pm1", ("sm",), "周一下午1禁排", "sm_mon_no_pm1_mode", "w_sm_mon_no_pm1"),
)


PERSONALIZED_RULE_INSTANCE_TEMPLATE_IDS = (
    "shared.personalized_constraints",
    "day.personalized_constraints",
    "night.personalized_constraints",
    "joint.link.personalized_constraints",
) + tuple(personalized_template_id(rule.rule_key) for rule in PERSONALIZED_LEGACY_RULES)
