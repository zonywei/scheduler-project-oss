# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Any


MODE_LABELS = {
    "hard": "硬规则",
    "soft": "软规则",
}

CATEGORY_LABELS = {
    "system": "系统默认",
    "course": "课程规则",
    "roster": "排班规则",
    "basic": "基础规则",
    "night": "晚自习",
    "day": "白天排课",
    "joint": "联合求解",
    "link": "白天晚自习联动",
    "shared": "共享规则",
    "hard": "硬性限制",
    "soft": "软性偏好",
    "hard_or_soft": "可切换规则",
    "base": "基础规则",
    "bans": "禁排",
    "teacher_limits": "教师次数上限",
    "binding": "绑定",
    "subject_special": "学科特殊规则",
    "date_mutex": "日期互斥",
    "period_split": "节次拆分",
    "checkin": "查寝",
    "objective": "优化目标",
    "personalized": "个性化",
    "weekend": "周末规则",
    "period_combo": "节次组合",
    "limits": "次数限制",
    "duty": "值班",
    "head_duty": "班主任值班",
    "noon_duty": "中午查寝",
    "pe": "体育/技术",
    "teacher_whitelist": "教师白名单",
    "fairness": "公平性",
    "load": "负荷",
    "subject_pref": "学科时段偏好",
    "fragmentation": "碎片化",
    "workload": "课时负荷",
    "continuity": "连续性",
    "balance": "均衡",
    "grade_group_duty": "年级组值班",
    "solver": "求解参数",
    "parameters": "参数应用",
}

RULE_TITLES = {
    "system.course.class_slot_unique": "同一班级同一时段只能有一项课程安排",
    "system.course.teacher_slot_unique": "同一教师同一时段只能承担一个教学任务",
    "system.course.subject_hours_exact": "班级学科课时必须与课时计划一致",
    "system.course.active_slots_only": "课程只能安排在已启用的作息时段",
    "system.course.fixed_activity_protected": "固定课程和固定事项不得被普通课程覆盖",
    "system.course.teacher_assignment_complete": "每个教学任务必须关联有效任课关系",
    "system.course.hard_bans_enforced": "已确认的禁排时段必须严格执行",
    "system.roster.person_slot_unique": "同一人员同一时段只能承担一个排班任务",
    "system.roster.staffing_satisfied": "每个启用班次必须满足岗位人数要求",
    "system.roster.candidate_eligibility": "排班人员必须来自有效候选范围",
    "night.hard_base": "晚自习基础排课规则",
    "night.hard_bans": "晚自习禁排清单",
    "night.hard_teacher_limits": "晚自习教师次数上限",
    "night.binding_8chem_9bio": "八班化学与九班生物同步绑定",
    "night.physics_math_special": "物理/数学晚自习特殊禁排",
    "night.fri_sun_mutex": "周五与周日晚自习互斥",
    "night.single_class_p1_p2_split": "单班教师晚自习节次拆开",
    "night.double_class_weekday_p1_p2_split": "双班教师工作日晚自习节次拆开",
    "night.checkin": "晚查寝安排规则",
    "night.soft_objective": "晚自习整体优化目标",
    "night.personalized_constraints": "晚自习个性化教师规则",
    "night.solver_parameters": "晚自习求解参数",
    "joint.day.one_subject_per_slot": "每个班每个白天时段只排一门课",
    "joint.day.subject_hour_constraints": "白天学科课时要求",
    "joint.day.teacher_no_conflict": "教师同一时段不能跨班冲突",
    "joint.day.morning_reading_constraints": "早自习规则",
    "joint.day.weekend_subject_whitelist": "周末允许学科白名单",
    "joint.day.weekend_double_period_same_class": "周末同班连排两节",
    "joint.day.weekend_one_day_only": "周末课程尽量集中到一天",
    "joint.day.weekend_cross_halfday_penalty": "周末跨半天惩罚",
    "joint.day.weekend_halfday_constraint": "周末半天集中规则",
    "joint.day.yjc_sunday_am12_pm12_rule": "指定教师周日 AM1/AM2/PM1/PM2 规则",
    "joint.day.binding_8chem_9bio": "白天八班化学与九班生物同步绑定",
    "joint.day.no_am1_am4": "同日 AM1 与 AM4 限制",
    "joint.day.core_subject_teacher_day_load_no_am1_am4": "核心学科教师日负荷上限",
    "joint.day.no_consecutive_same_teacher_same_class": "同班同教师不连续排课",
    "joint.day.head_pm1_min": "下午第一节班主任数量下限",
    "joint.day.teacher_weekday_am_pm_presence": "教师工作日上午下午都要出现",
    "joint.day.am1_pm1_mutex": "AM1 与 PM1 组合限制",
    "joint.day.two_class_am1_pm1_combo": "双班教师 AM1/PM1 组合限制",
    "joint.day.am1_pm1_exclusive": "AM1 与 PM1 互斥",
    "joint.day.single_class_weekly_am1_cap": "单班教师每周 AM1 上限",
    "joint.day.two_class_low_hours_max_empty_days": "双班低课时教师空天限制",
    "joint.day.low_weekday_subject_max1_per_day": "低课时学科每天最多一节",
    "joint.day.high_weekday_subject_min1_per_day": "高课时学科每天至少一节",
    "joint.day.head_duty_constraints": "班主任值班规则",
    "joint.day.noon_dorm_duty_constraints": "中午查寝规则",
    "joint.day.pe_time_window_hard": "体育可排时段硬限制",
    "joint.day.teacher_whitelist_hard": "教师白名单硬限制",
    "joint.day.multi_class_halfday_soft": "多班教师半天集中偏好",
    "joint.day.teacher_am4_pm1_threshold_penalty": "教师 AM4/PM1 阶梯惩罚",
    "joint.day.pref_lang_am": "语文/外语上午偏好",
    "joint.day.reduce_stem_am1": "数理化减少 AM1",
    "joint.day.teacher_am1_fragmentation": "教师 AM1 碎片化惩罚",
    "joint.day.two_class_daily_min_per_class": "双班教师当天两班都上",
    "joint.day.teacher_continuity_penalty": "教师半天连续性偏好",
    "joint.day.teacher_m1_cap_constraint": "教师上午第一节周上限",
    "joint.day.weekday_subject_balance": "工作日学科均衡",
    "joint.day.pe_reduce_am_soft": "体育减少上午偏好",
    "joint.day.pe_tech_compact_soft": "体育/技术课程紧凑偏好",
    "joint.link.duty_joint_constraints": "白天值班与晚查寝联动",
    "joint.link.grade_group_duty_constraints": "年级组值班联动",
    "joint.link.personalized_constraints": "联合求解个性化规则",
    "joint.solver_parameters": "联合求解参数",
    "shared.personalized_constraints": "个性化规则集合",
}


def localize_rule(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    rule_id = str(row.get("rule_id") or "")
    category_path = str(row.get("category_path") or "")
    mode = str(row.get("mode") or "")
    out["display_title"] = RULE_TITLES.get(rule_id) or _fallback_title(rule_id, category_path)
    out["display_category"] = _category_label(category_path)
    out["display_mode"] = MODE_LABELS.get(mode, mode or "未设置")
    out["display_enabled"] = "启用" if bool(row.get("enabled")) else "关闭"
    out["display_weight"] = _weight_label(row.get("weight"), mode)
    out["display_summary"] = _summary(out)
    return out


def _fallback_title(rule_id: str, category_path: str) -> str:
    label = _category_label(category_path)
    if label:
        return f"{label}规则"
    if rule_id:
        return rule_id.replace("_", " ").replace(".", " ")
    return "未命名规则"


def _category_label(category_path: str) -> str:
    parts = [x for x in str(category_path or "").split("/") if x]
    labels = [CATEGORY_LABELS.get(part, part) for part in parts]
    return " / ".join(labels)


def _weight_label(weight: Any, mode: str) -> str:
    if str(mode) != "soft":
        return "不使用罚分"
    if weight in (None, ""):
        return "未设置罚分"
    return f"罚分 {weight}"


def _summary(row: dict[str, Any]) -> str:
    mode = row.get("display_mode", "")
    enabled = row.get("display_enabled", "")
    weight = row.get("display_weight", "")
    category = row.get("display_category", "")
    parts = [enabled, mode]
    if category:
        parts.append(category)
    if weight:
        parts.append(weight)
    return "，".join(parts)
