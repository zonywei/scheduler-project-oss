# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Any

from scheduler.model.constraints.teacher_targets import teacher_names
from scheduler.rules.mandatory import mandatory_default_rules


TARGET_SCOPE_OPTIONS = [
    {"value": "all_teachers", "label": "全体教师"},
    {"value": "selected_teachers", "label": "指定教师"},
    {"value": "subject_group", "label": "学科组"},
    {"value": "homeroom_teachers", "label": "全体班主任"},
    {"value": "duty_candidates", "label": "值班/查寝候选人"},
]

EXCEPTION_MODE_OPTIONS = [
    {"value": "exclude", "label": "例外对象不参与本规则"},
    {"value": "soften", "label": "例外对象改为软约束"},
    {"value": "note", "label": "仅记录例外说明"},
]

GROUPS = [
    {"id": "system_core", "title": "系统基础规则", "description": "决定课表是否合法的底层硬规则，不可关闭、删除或软化。"},
    {"id": "teacher_personal", "title": "教师个人约束", "description": "某位或多位教师的禁排、偏好、节次上限、连续性等要求。"},
    {"id": "night", "title": "晚自习约束", "description": "晚自习学科、教师、日期、节次和查寝相关规则。"},
    {"id": "day", "title": "白天排课约束", "description": "白天课时、周末、上午下午、学科均衡、教师冲突等规则。"},
    {"id": "duty", "title": "值班/查寝约束", "description": "班主任值班、中午查寝、晚查寝、年级组值班等规则。"},
    {"id": "link", "title": "白天晚自习联动", "description": "白天课程与晚自习、查寝之间的跨模块联动规则。"},
    {"id": "temporary", "title": "临时规则", "description": "用户通过自然语言或 Web 临时加入的规则。"},
]


PERSONAL_RULES = [
    ("enable_xhd_night_no_pm3", "xhd", "晚自习当天不排下午3", "如果目标教师当天有晚自习，则下午3不再排课。", "xhd_night_no_pm3_mode", "w_xhd_night_no_pm3"),
    ("enable_xhd_night_no_pm", "xhd", "晚自习当天不排下午课", "如果目标教师当天有晚自习，则当天尽量/必须不排下午课。", "xhd_night_no_pm_mode", "w_xhd_night_no_pm"),
    ("enable_couple_xhd_zfy", "xhd,zfy", "两位教师至少同一天晚自习", "两位目标教师整周至少有一天同时上晚自习。", "couple_xhd_zfy_mode", "w_couple_need_overlap"),
    ("enable_zw_night_need_pm", "zw", "晚自习需要当天有下午课", "目标教师如果上晚自习，当天下午也需要有课。", "zw_night_need_pm_mode", "w_zw_night_need_pm"),
    ("enable_zw_am1_cap", "zw", "上午1周次数上限", "目标教师每周上午1次数不超过配置上限。", "zw_am1_cap_mode", "w_zw_am1_cap"),
    ("enable_zw_am2_cap", "zw", "上午2周次数上限", "目标教师每周上午2次数不超过配置上限。", "zw_am2_cap_mode", "w_zw_am2_cap"),
    ("enable_zw_am4_cap", "zw", "上午4周次数上限", "目标教师每周上午4次数不超过配置上限。", "zw_am4_cap_mode", "w_zw_am4_cap"),
    ("enable_zw_weekday_pm1_cap", "zw", "工作日下午1次数上限", "目标教师周一到周五下午1次数不超过配置上限。", "zw_weekday_pm1_cap_mode", "w_zw_weekday_pm1_cap"),
    ("enable_lm_sun_am12", "lm", "周日上午1和上午2偏好", "目标教师周日倾向安排上午1和上午2。", "lm_sun_am12_mode", "w_lm_sun_am12"),
    ("enable_ytt_sun_pref", "ytt", "周日上午偏好且减少周日晚自习", "目标教师周日上午优先安排，周日晚自习尽量不排。", "ytt_sun_pref_mode", "w_ytt_no_sun_night"),
    ("enable_dym_no_fri_sun_night", "dym", "周日晚自习禁排", "目标教师周日晚自习不排。", None, None),
    ("enable_ld_reduce_pm", "ld", "减少下午课", "目标教师下午课尽量减少。", "ld_reduce_pm_mode", "w_ld_reduce_pm"),
    ("enable_ld_no_mon_pm", "ld", "周一/二/四/五下午禁排", "目标教师周一、周二、周四、周五下午不排课。", None, None),
    ("enable_zfj_ban_mon_fri_pm3", "zfj_pm3", "周一和周五下午3禁排", "目标教师周一、周五下午3不排课。", None, None),
    ("enable_zfj_night_checkin_penalty", "zfj_checkin", "晚查寝惩罚", "目标教师安排晚查寝时计入较高惩罚。", "zeng_night_checkin_penalty_mode", "w_zfj_night_checkin_penalty"),
    ("enable_jxq_prefs", "jxq", "周一上午1与周日偏好", "目标教师周一上午1尽量不排，周日下午优先，周日晚自习减少。", "jxq_prefs_mode", "w_jxq_no_mon_am1"),
    ("enable_csqi_prefs", "csqi", "周日/周一晚自习偏好", "目标教师晚自习尽量安排在周日或周一。", "csqi_prefs_mode", "w_csqi_need_sun_or_mon"),
    ("enable_csqi_need_consecutive_night", "csqi", "晚自习需要连续两天", "目标教师晚自习尽量/必须形成连续两天。", "csqi_need_consecutive_night_mode", "w_csqi_need_consecutive_night"),
    ("enable_zzx_prefs", "zzx", "周日与上午4偏好", "目标教师减少周日晚自习、周日上午优先，并减少上午4。", "zzx_prefs_mode", "w_zzx_no_sun_night"),
    ("enable_zzx_no_sunday_night", "zzx", "周日晚自习禁排", "目标教师周日晚自习不排。", "zzx_no_sunday_night_mode", "w_zzx_no_sunday_night"),
    ("enable_xyx_night_days_only", "xyx", "晚自习仅允许指定日期", "目标教师晚自习只能安排在配置允许日期。", "xyx_night_days_only_mode", "w_xyx_night_days_only"),
    ("enable_hwj_prefs", "hwj", "周日周一与连续晚自习偏好", "目标教师晚自习偏向周日/周一，并尽量连续。", "hwj_prefs_mode", "w_hwj_need_sun_mon"),
    ("enable_hwj_night_sun_mon_assign", "hwj", "晚自习安排在周日和周一", "目标教师晚自习必须/尽量安排在周日和周一。", "hwj_night_sun_mon_assign_mode", "w_hwj_night_sun_mon_assign"),
    ("enable_hsm_no_fri_night", "hsm", "周五晚自习禁排/减少", "目标教师周五晚自习不排或尽量不排。", "hsm_no_fri_night_mode", "w_hsm_no_fri_night"),
    ("enable_hsm_weekday_early_no_am1", "hsm", "有早自习则不排上午1", "目标教师工作日有早自习时，当天上午1不排课。", "hsm_weekday_early_no_am1_mode", "w_hsm_weekday_early_no_am1"),
    ("enable_wxl_weekday_early_no_am1", "wxl", "有早自习则不排上午1", "目标教师工作日有早自习时，当天上午1不排课。", "wxl_weekday_early_no_am1_mode", "w_wxl_weekday_early_no_am1"),
    ("enable_dln_weekday_no_am1", "dln", "工作日上午1禁排", "目标教师周一到周五上午1不排课。", "dln_weekday_no_am1_mode", "w_dln_weekday_no_am1"),
    ("enable_custom_no_am1_teachers", "custom_no_am1_teachers", "自定义上午1禁排名单", "名单内教师上午1不排课。", None, None),
    ("enable_mrj_hsm_sun_am12_fixed", "mrj,hsm", "周日固定上午1和上午2", "目标教师周日固定安排上午1和上午2。", "mrj_hsm_sun_am12_fixed_mode", "w_mrj_hsm_sun_am12_fixed"),
    ("enable_zhoubo_hard", "zb", "硬性个人组合规则", "目标教师启用一组硬性个人安排要求。", None, None),
    ("enable_zhoubo_liumeng_same_night", "zb,lm", "两位教师同天晚自习", "两位目标教师需要同一天上晚自习。", None, None),
    ("enable_zhoubo_weekday_am1_penalty", "zb", "工作日上午1惩罚", "目标教师周一到周五上午1尽量少排。", "zhoubo_weekday_am1_penalty_mode", "w_zhoubo_weekday_am1_penalty"),
    ("enable_liumeng_no_sunday", "lm", "周日晚自习禁排", "目标教师周日晚自习不排。", None, None),
    ("enable_xww_weekday_am4_pm1_stair", "xww", "工作日 AM4/PM1 阶梯惩罚", "目标教师周一到周五上午4和下午1合计越多，惩罚越高。", "xww_weekday_am4_pm1_stair_mode", "w_xww_weekday_am4_pm1_e2"),
    ("enable_zfy_no_consecutive_night", "zfy", "晚自习不连续两天", "目标教师晚自习不连续两天，周日到周一也算连续。", "zfy_no_consecutive_night_mode", "w_zfy_no_consecutive_night"),
    ("enable_zw_no_consecutive_night", "zw", "晚自习不连续两天", "目标教师晚自习不连续两天。", "zw_no_consecutive_night_mode", "w_zw_no_consecutive_night"),
    ("enable_zfy_no_sunday_night", "zfy", "周日晚自习禁排", "目标教师周日晚自习不排。", "zfy_no_sunday_night_mode", "w_zfy_no_sunday_night"),
    ("enable_sll_sun_am_only", "sll", "周日只排上午", "目标教师周日白天只排上午，不排下午。", "sll_sun_am_only_mode", "w_sll_sun_am_only"),
    ("enable_cc_weekday_no_am4", "cc", "工作日上午4禁排", "目标教师周一到周五上午4不排课。", "cc_weekday_no_am4_mode", "w_cc_weekday_no_am4"),
    ("enable_cc_sat_am34_class17", "cc", "周六上午3/4指定班级", "目标教师周六上午3/4如排课，则排到指定班级。", "cc_sat_am34_class17_mode", "w_cc_sat_am34_class17"),
    ("enable_sm_mon_no_am", "sm", "周一上午禁排", "目标教师周一上午不排课。", "sm_mon_no_am_mode", "w_sm_mon_no_am"),
    ("enable_sm_mon_no_pm1", "sm", "周一下午1禁排", "目标教师周一下午1不排课。", "sm_mon_no_pm1_mode", "w_sm_mon_no_pm1"),
]


def build_business_rule_groups(effective_cfg: dict[str, Any]) -> list[dict[str, Any]]:
    cfg = effective_cfg or {}
    groups = {item["id"]: {**item, "rules": []} for item in GROUPS}
    groups["system_core"]["rules"] = mandatory_default_rules()
    _add_teacher_personal(groups["teacher_personal"], cfg)
    _add_night(groups["night"], cfg)
    _add_day(groups["day"], cfg)
    _add_duty(groups["duty"], cfg)
    _add_link(groups["link"], cfg)
    _add_temporary(groups["temporary"], cfg)
    _attach_default_editors(groups, cfg)
    _attach_application_editors(groups, cfg)
    return [groups[item["id"]] for item in GROUPS]


def build_business_rule_domains(
    effective_cfg: dict[str, Any],
    groups: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Return the formal course/roster information architecture.

    Disabled legacy catalog rows are intentionally omitted.  They are not
    current rules and should not look like editable business requirements.
    """
    rows = groups if groups is not None else build_business_rule_groups(effective_cfg)
    by_group = {str(group.get("id") or ""): group for group in rows}
    system_rules = [dict(rule) for rule in (by_group.get("system_core", {}).get("rules") or [])]
    course_core = [rule for rule in system_rules if rule.get("business_domain") == "course"]
    roster_core = [rule for rule in system_rules if rule.get("business_domain") == "roster"]

    defaults_only = bool(((effective_cfg.get("product_rules") or {}) if isinstance(effective_cfg, dict) else {}).get("defaults_only"))
    enabled_teacher = [
        dict(rule)
        for rule in (by_group.get("teacher_personal", {}).get("rules") or [])
        if rule.get("enabled") is not False
    ]
    enabled_course = [
        dict(rule)
        for group_id in ("day", "night", "link")
        for rule in (by_group.get(group_id, {}).get("rules") or [])
        if rule.get("enabled") is not False
    ]
    enabled_roster = [
        dict(rule)
        for rule in (by_group.get("duty", {}).get("rules") or [])
        if rule.get("enabled") is not False
    ]

    if defaults_only:
        enabled_teacher = []
        enabled_course = []
        enabled_roster = []

    subject_tokens = ("学科", "语文", "数学", "外语", "英语", "物理", "化学", "生物", "政治", "历史", "地理", "体育", "技术")
    course_subject = [rule for rule in enabled_course if any(token in str(rule.get("title") or "") for token in subject_tokens)]
    course_basic = [rule for rule in enabled_course if rule not in course_subject]

    roster_subject: list[dict[str, Any]] = []
    roster_teacher: list[dict[str, Any]] = []
    roster_basic: list[dict[str, Any]] = []
    for rule in enabled_roster:
        application = rule.get("application") if isinstance(rule.get("application"), dict) else {}
        if application.get("subject_groups") or application.get("subject_group_teachers"):
            roster_subject.append(rule)
        elif application.get("target_scope") == "selected_teachers" or _has_named_targets(rule):
            roster_teacher.append(rule)
        else:
            roster_basic.append(rule)

    return [
        _domain("course", "课程规则", course_core + course_basic, enabled_teacher, course_subject),
        _domain("roster", "排班规则", roster_core + roster_basic, roster_teacher, roster_subject),
    ]


def _domain(
    domain_id: str,
    title: str,
    basic: list[dict[str, Any]],
    teacher: list[dict[str, Any]],
    subject: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "id": domain_id,
        "title": title,
        "sections": [
            {"id": "basic", "title": "基础规则", "rules": basic},
            {"id": "teacher", "title": "教师个性规则", "rules": teacher},
            {"id": "subject", "title": "学科个性规则", "rules": subject},
        ],
    }


def _has_named_targets(rule: dict[str, Any]) -> bool:
    generic = {"全体适用", "全体教师", "全体班主任", "男班主任", "女班主任", "值班/查寝候选人", "待填写教师"}
    return any(str(value).strip() not in generic for value in (rule.get("targets") or []))


def _add_rule(group: dict[str, Any], **kwargs: Any) -> None:
    group["rules"].append(
        {
            "id": kwargs.get("id", f"{group['id']}.{len(group['rules']) + 1}"),
            "title": _plain_text(kwargs.get("title", "未命名规则")),
            "explanation": _plain_text(kwargs.get("explanation", "")),
            "targets": kwargs.get("targets", []),
            "scope": _plain_text(kwargs.get("scope", "")),
            "mode": _mode_label(kwargs.get("mode")),
            "weight": kwargs.get("weight"),
            "enabled": bool(kwargs.get("enabled", True)),
            "config_path": kwargs.get("config_path", ""),
            "editor": {"fields": kwargs.get("fields") or []},
        }
    )


def _add_teacher_personal(group: dict[str, Any], cfg: dict[str, Any]) -> None:
    pcfg = cfg.get("personalized_constraints", {}) or {}
    targets_cfg = pcfg.get("teacher_targets", {}) or {}
    for enable_key, target_keys, title, explanation, mode_key, weight_key in PERSONAL_RULES:
        enabled = bool(pcfg.get(enable_key, False))
        target_names: list[str] = []
        for target_key in str(target_keys).split(","):
            target_names.extend(teacher_names(targets_cfg.get(target_key.strip(), pcfg.get(target_key.strip()))))
        if not target_names:
            target_names = ["待填写教师"]
        _add_rule(
            group,
            id=f"personal.{enable_key}",
            title=title,
            explanation=explanation,
            targets=target_names,
            scope="教师个人",
            mode=pcfg.get(mode_key) if mode_key else "hard",
            weight=pcfg.get(weight_key) if weight_key else None,
            enabled=enabled,
            config_path=f"personalized_constraints.{enable_key}",
            fields=_personal_rule_fields(pcfg, enable_key, target_keys, mode_key, weight_key),
        )


def _add_night(group: dict[str, Any], cfg: dict[str, Any]) -> None:
    hard_bans = cfg.get("hard_bans", {}) or {}
    for item in hard_bans.get("subject_bans", []) or []:
        if not isinstance(item, dict):
            continue
        _add_rule(
            group,
            id=f"night.subject_ban.{item.get('subject')}",
            title=f"{item.get('subject') or '某学科'}晚自习禁排",
            explanation=f"{item.get('subject') or '该学科'}在 {', '.join(item.get('days', []) or ['未设置日期'])} 的 {', '.join(item.get('periods', []) or ['全部晚自习'])} 不安排。",
            targets=[str(item.get("subject") or "待填写学科")],
            scope="晚自习",
            mode="hard",
            enabled=bool(hard_bans.get("enabled", True)),
            config_path="hard_bans.subject_bans",
        )
    for day, names in (hard_bans.get("teacher_day_bans", {}) or {}).items():
        clean_names = teacher_names(names)
        if not clean_names:
            continue
        _add_rule(
            group,
            id=f"night.teacher_day_ban.{day}",
            title=f"{day}教师晚自习禁排",
            explanation=f"名单内教师在 {day} 晚自习不安排。",
            targets=clean_names,
            scope=f"晚自习 / {day}",
            mode="hard",
            enabled=bool(hard_bans.get("enabled", True)),
            config_path=f"hard_bans.teacher_day_bans.{day}",
        )
    evening_constraints = cfg.get("evening_constraints", {}) or {}
    _add_toggle_rule(group, evening_constraints, "enable_fri_sun_mutex", "周五与周日晚自习互斥", "同一教师周五和周日不同时安排晚自习，避免间隔过短。", "晚自习", "fri_sun_mutex_mode", "fri_sun_mutex_weight", "evening_constraints")
    _add_toggle_rule(group, evening_constraints, "enable_single_class_p1_p2_split", "单班教师晚自习节次拆开", "单班教师两次晚自习尽量/必须分布在不同节次。", "晚自习", None, None, "evening_constraints")
    _add_toggle_rule(group, evening_constraints, "enable_double_class_weekday_p1_p2_split", "双班教师工作日晚自习节次拆开", "双班教师工作日晚自习不总挤在同一节。", "晚自习", "double_class_weekday_p1_p2_mode", "double_class_weekday_p1_p2_weight", "evening_constraints")


def _add_day(group: dict[str, Any], cfg: dict[str, Any]) -> None:
    day_cfg = cfg.get("day", {}) or {}
    weekend = day_cfg.get("weekend_constraints", {}) or {}
    weekday = day_cfg.get("weekday_constraints", {}) or {}
    day_constraints = cfg.get("day_constraints", {}) or {}
    for key, title, explanation in [
        ("enable_weekend_subject_whitelist", "周末学科白名单", "周末只允许指定学科排课。"),
        ("enable_weekend_double_period_same_class", "周末同班连排两节", "周末课程按同班连续两节组织。"),
        ("enable_weekend_one_day_only", "周末尽量集中一天", "同一班周末课程尽量不跨周六和周日。"),
    ]:
        _add_toggle_rule(group, weekend, key, title, explanation, "白天 / 周末", None, None, "day.weekend_constraints")
    for key, title, explanation in [
        ("enable_no_am1_am4", "避免同日 AM1 和 AM4 同时出现", "减少教师同一天上午头尾两节拉得太开。"),
        ("enable_core_teacher_day_load_limit", "核心学科教师日课时上限", "核心学科教师周一到周五每天课时不超过配置上限。"),
        ("enable_no_consecutive_same_teacher_same_class", "同班同教师不连续排课", "同一个班同一教师尽量避免相邻连续排课。"),
        ("enable_pref_lang_am", "语文/外语上午偏好", "语文和外语更倾向安排在上午。"),
        ("enable_reduce_stem_am1", "数理化减少上午1", "数理化尽量少排在上午1。"),
        ("enable_balance_weekday_subject_hours", "工作日学科均衡", "同一学科在工作日尽量均匀分布。"),
    ]:
        _add_toggle_rule(group, weekday, key, title, explanation, "白天 / 工作日", None, None, "day.weekday_constraints")
    for key, title, explanation, mode_key, weight_key in [
        ("enable_am1_pm1_mutex", "AM1 与 PM1 组合限制", "限制同一教师或同一班出现上午1与下午1组合。", "am1_pm1_mutex_mode", "w_am1_pm1_mutex"),
        ("enable_two_class_am1_pm1_combo", "双班教师 AM1/PM1 组合限制", "双班教师上午1和下午1组合受限。", "two_class_am1_pm1_combo_mode", "w_two_class_am1_pm1_combo"),
        ("enable_am1_pm1_exclusive", "AM1 与 PM1 互斥", "上午1和下午1不能同时命中同一约束对象。", "am1_pm1_exclusive_mode", "w_am1_pm1_exclusive"),
        ("enable_single_class_weekly_am1_cap", "单班教师每周 AM1 上限", "单班教师每周上午1次数不超过配置上限。", None, None),
        ("enable_weekend_halfday_constraint", "周末半天集中", "周末课程尽量/必须集中在半天内。", "weekend_halfday_mode", "w_weekend_halfday"),
    ]:
        _add_toggle_rule(group, day_constraints, key, title, explanation, "白天", mode_key, weight_key, "day_constraints")


def _add_duty(group: dict[str, Any], cfg: dict[str, Any]) -> None:
    day_cfg = cfg.get("day", {}) or {}
    checkin = cfg.get("checkin", {}) or {}
    head = day_cfg.get("head_duty_constraints", {}) or {}
    noon = day_cfg.get("noon_dorm_duty", {}) or {}
    joint = day_cfg.get("duty_joint_constraints", {}) or {}
    grade = day_cfg.get("grade_group_duty", {}) or {}

    checkin_enabled = bool(checkin.get("enabled", False))
    same_day_mode = _checkin_same_day_class_mode(checkin)
    _add_rule(
        group,
        id="duty.night_checkin.daily_staffing",
        title="晚查寝每天按性别安排人数",
        explanation=(
            f"每天晚查寝从班主任池里安排男教师 {int((checkin.get('per_day', {}) or {}).get('male', 1) or 0)} 人、"
            f"女教师 {int((checkin.get('per_day', {}) or {}).get('female', 1) or 0)} 人。"
            "如果某个性别没有足够候选人，排课会直接提示不可行。"
        ),
        targets=["男班主任", "女班主任"],
        scope="晚查寝",
        mode="hard",
        enabled=checkin_enabled,
        config_path="checkin.per_day",
    )
    _add_rule(
        group,
        id="duty.night_checkin.weekly_max",
        title="晚查寝每位班主任周次数上限",
        explanation=f"同一位班主任一周最多安排 {int(checkin.get('per_teacher_max_times', 1) or 1)} 次晚查寝，避免晚查寝集中到少数人身上。",
        targets=["全体班主任"],
        scope="晚查寝",
        mode="hard",
        enabled=checkin_enabled,
        config_path="checkin.per_teacher_max_times",
    )
    _add_rule(
        group,
        id="duty.night_checkin.exclude",
        title="晚查寝不参与名单",
        explanation="名单内班主任不安排晚查寝。这个规则适合处理请假、长期不参与宿舍管理、或学校明确不参与晚查寝的人员。",
        targets=teacher_names(checkin.get("exclude_heads")) or ["待填写教师"],
        scope="晚查寝",
        mode="hard",
        enabled=checkin_enabled and bool(teacher_names(checkin.get("exclude_heads"))),
        config_path="checkin.exclude_heads",
    )
    extra_heads = _extra_head_items(checkin.get("extra_heads"))
    _add_rule(
        group,
        id="duty.night_checkin.extra_heads",
        title="额外晚查寝候选人",
        explanation="用于把非班主任但经学校确认可参与晚查寝的教师加入候选池，或临时补足某个性别的查寝人次缺口。",
        targets=_extra_head_labels(extra_heads) or ["待补充候选人"],
        scope="晚查寝 / 候选池补充",
        mode="hard",
        enabled=checkin_enabled and bool(extra_heads),
        config_path="checkin.extra_heads",
        fields=[
            _field(
                "额外候选名单",
                "checkin.extra_heads",
                "checkin_extra_heads",
                extra_heads,
                "维护姓名、性别和可选适用日期；留空日期表示整周可参与，填写日期则只在这些日期进入候选池。",
                section="执行参数",
                ui="checkin-extra-heads",
            )
        ],
    )
    _add_rule(
        group,
        id="duty.night_checkin.requires_evening_class",
        title="晚查寝教师当天要有晚自习",
        explanation="如果班主任被安排晚查寝，系统会尽量让他/她当天也有晚自习课，避免教师专门为了查寝返校或空跑。",
        targets=["全体晚查寝候选班主任"],
        scope="晚查寝 / 晚自习联动",
        mode=same_day_mode,
        weight=checkin.get("w_require_teacher_has_class_that_day"),
        enabled=checkin_enabled and same_day_mode != "off",
        config_path="checkin.require_teacher_has_class_that_day_mode",
    )
    _add_rule(
        group,
        id="duty.night_checkin.target_requires_class",
        title="指定教师晚查寝也要当天有课",
        explanation="名单内教师如果被安排晚查寝，也要检查当天是否有晚自习；如果没有晚自习，按当前执行方式禁止或扣分。",
        targets=teacher_names(checkin.get("require_class_teacher_names")) or ["待填写教师"],
        scope="晚查寝 / 指定教师",
        mode=checkin.get("zeng_checkin_require_class_mode", "hard"),
        weight=checkin.get("w_zeng_checkin_require_class_that_day"),
        enabled=checkin_enabled and bool(checkin.get("enable_zeng_checkin_require_class_that_day", True)),
        config_path="checkin.enable_zeng_checkin_require_class_that_day",
    )
    _add_rule(
        group,
        id="duty.night_checkin.target_penalty",
        title="指定教师尽量少排晚查寝",
        explanation="名单内教师不是绝对不能晚查寝，但系统会把这件事视为不理想安排，只有在确实需要时才排。",
        targets=teacher_names(checkin.get("night_checkin_penalty_teachers")) or ["待填写教师"],
        scope="晚查寝 / 指定教师",
        mode=checkin.get("zeng_night_checkin_penalty_mode", "soft"),
        weight=checkin.get("w_zeng_night_checkin_penalty"),
        enabled=checkin_enabled and bool(teacher_names(checkin.get("night_checkin_penalty_teachers"))),
        config_path="checkin.night_checkin_penalty_teachers",
    )

    head_enabled = bool(head.get("enable_head_duty", True))
    _add_rule(
        group,
        id="duty.head.floor_staffing",
        title="下午课前按楼层安排班主任值班",
        explanation="下午课前值班按楼层分配：低楼层、中楼层、高楼层各有对应班主任候选池。系统每天为需要值班的楼层安排班主任，保证课前管理有人负责。",
        targets=["各楼层对应班主任"],
        scope="下午课前值班",
        mode="hard",
        enabled=head_enabled,
        config_path="day.head_duty_constraints.enable_head_duty",
    )
    _add_rule(
        group,
        id="duty.head.pm1_requires_duty",
        title="工作日下午第1节有课则当天要值班",
        explanation="周一到周五，如果班主任下午第1节有课，系统要求他/她当天同时承担下午课前值班。这样可以把课前管理和本来就在校的教师绑定起来。",
        targets=teacher_names(head.get("weekday_pm1_requires_duty_exempt_teachers")) or ["全体班主任"],
        scope="下午课前值班 / 白天课程",
        mode=head.get("weekday_pm1_requires_duty_mode", "hard"),
        weight=head.get("w_weekday_pm1_requires_duty"),
        enabled=head_enabled and bool(head.get("enable_weekday_pm1_requires_duty", True)),
        config_path="day.head_duty_constraints.enable_weekday_pm1_requires_duty",
    )
    _add_rule(
        group,
        id="duty.head.pm1_penalty",
        title="下午第1节课尽量和课前值班合并",
        explanation="如果班主任下午第1节有课但当天没有课前值班，系统会认为这不是理想安排；有值班则不扣分。这个规则用于减少额外到岗成本。",
        targets=["全体班主任"],
        scope="下午课前值班 / 白天课程",
        mode="soft",
        weight=head.get("w_pm1_penalty"),
        enabled=head_enabled,
        config_path="day.head_duty_constraints.w_pm1_penalty",
    )

    noon_enabled = bool(noon.get("enabled", True))
    _add_rule(
        group,
        id="duty.noon.daily_staffing",
        title="中午查寝每天安排男女寝教师",
        explanation="中午查寝按男寝、女寝分别安排。通常非周日男寝安排1人，非周六女寝安排1人；周六女寝如果没有固定名单则不排，周日男寝不排。",
        targets=["男班主任", "女班主任"],
        scope="中午查寝",
        mode="hard",
        enabled=noon_enabled,
        config_path="day.noon_dorm_duty.enabled",
    )
    _add_rule(
        group,
        id="duty.noon.candidates",
        title="中午查寝候选人与排除名单",
        explanation="中午查寝候选人来自教师定位表里的班主任性别。排除名单中的教师不会参与；额外男寝候选名单可把特定教师加入男寝候选池。",
        targets=_merge_targets(noon.get("noon_exclude_teachers"), noon.get("male_candidate_extra_teachers"), noon.get("noon_disallow_teachers")) or ["全体班主任"],
        scope="中午查寝",
        mode="hard",
        enabled=noon_enabled,
        config_path="day.noon_dorm_duty.noon_exclude_teachers",
    )
    _add_rule(
        group,
        id="duty.noon.weekly_limits",
        title="中午查寝周次数控制",
        explanation="女班主任一周中午查寝最多一次；配置名单内的男寝教师一周男寝中午查寝最多一次。男班主任更复杂的周次数由“午查/晚查联动”统一控制。",
        targets=teacher_names(noon.get("special_male_noon_max1_teachers")) or ["女班主任", "配置名单教师"],
        scope="中午查寝",
        mode="hard",
        enabled=noon_enabled,
        config_path="day.noon_dorm_duty.special_male_noon_max1_teachers",
    )
    _add_rule(
        group,
        id="duty.noon.prefer_am4",
        title="中午查寝优先安排上午第4节有课的教师",
        explanation="中午查寝尽量安排当天上午第4节有课的教师；如果只能安排上午第3节、第2节、第1节或上午没课的教师，系统会按离中午越远越不理想的方式扣分。",
        targets=["中午查寝候选教师"],
        scope="中午查寝 / 白天课程",
        mode="soft",
        weight=noon.get("w_need_am4_lvl0"),
        enabled=noon_enabled,
        config_path="day.noon_dorm_duty.w_need_am4_lvl0",
    )
    _add_rule(
        group,
        id="duty.noon.avoid_pm1",
        title="中午查寝当天尽量不排下午第1节",
        explanation="如果教师中午查寝，当天下午第1节再上课会比较赶；系统会尽量避免这种组合。",
        targets=["中午查寝候选教师"],
        scope="中午查寝 / 白天课程",
        mode="soft",
        weight=noon.get("w_noon_with_pm1"),
        enabled=noon_enabled,
        config_path="day.noon_dorm_duty.w_noon_with_pm1",
    )
    _add_rule(
        group,
        id="duty.noon.target_bans",
        title="指定教师中午查寝禁排或少排",
        explanation="名单内教师中午查寝按当前执行方式处理：硬约束时不安排，软约束时只有在确实需要时才安排并计入扣分。",
        targets=_merge_targets(noon.get("lhj_noon_ban_teachers"), noon.get("zeng_noon_ban_teachers")) or ["待填写教师"],
        scope="中午查寝 / 指定教师",
        mode=noon.get("lhj_noon_ban_mode", noon.get("zeng_noon_ban_mode", "hard")),
        weight=noon.get("w_lhj_noon_ban") or noon.get("w_zeng_noon_ban"),
        enabled=noon_enabled and bool(_merge_targets(noon.get("lhj_noon_ban_teachers"), noon.get("zeng_noon_ban_teachers"))),
        config_path="day.noon_dorm_duty.lhj_noon_ban_teachers",
    )
    _add_rule(
        group,
        id="duty.noon.am_link_teachers",
        title="指定教师中午查寝必须贴近上午课",
        explanation="名单内教师如果中午查寝，当天上午必须有课；按当前规则，这类教师中午查寝时不放在上午第4节有课的当天，并尽量选择上午课离中午更近的安排。",
        targets=teacher_names(noon.get("noon_am_link_teachers")) or ["待填写教师"],
        scope="中午查寝 / 指定教师",
        mode="hard",
        enabled=noon_enabled and bool(teacher_names(noon.get("noon_am_link_teachers"))),
        config_path="day.noon_dorm_duty.noon_am_link_teachers",
    )
    _add_rule(
        group,
        id="duty.noon.female_night_penalty",
        title="女教师同日中午查寝和晚查寝尽量不叠加",
        explanation="同一位女教师同一天既中午查寝又晚查寝负担太重；系统会尽量避免这种安排。",
        targets=["女班主任"],
        scope="中午查寝 / 晚查寝联动",
        mode="soft",
        weight=noon.get("w_female_noon_night_checkin"),
        enabled=noon_enabled,
        config_path="day.noon_dorm_duty.w_female_noon_night_checkin",
    )

    joint_enabled = bool(joint.get("enabled", True))
    _add_rule(
        group,
        id="duty.joint.heads_min_once",
        title="每位班主任每周至少承担一次查寝类任务",
        explanation="午查和晚查合并统计，每位班主任每周至少要承担一次查寝相关任务，避免有人完全没有宿舍管理任务。",
        targets=["全体班主任"],
        scope="午查 / 晚查联动",
        mode="hard",
        enabled=joint_enabled,
        config_path="day.duty_joint_constraints.enabled",
    )
    _add_rule(
        group,
        id="duty.joint.male_total_rules",
        title="男班主任午查和晚查周次数联动",
        explanation="男班主任一周午查+晚查总次数以配置目标为准；当总需求超过人均目标时，可改为软约束并在结果中审计超额教师。",
        targets=teacher_names(joint.get("male_total_eq2_exclude_teachers")) or ["男班主任"],
        scope="午查 / 晚查联动",
        mode=joint.get("male_total_target_mode", "hard"),
        weight=joint.get("w_male_total_target_deviation"),
        enabled=joint_enabled,
        config_path="day.duty_joint_constraints.male_total_target_mode",
    )
    _add_rule(
        group,
        id="duty.joint.female_total_rules",
        title="女班主任午查和晚查周次数联动",
        explanation="女班主任午查+晚查合计最多2次；如果没有晚查寝，中午查寝可以到2次，否则一般控制在较低负担。系统也会尽量保证女班主任每周至少有一次查寝类任务。",
        targets=teacher_names(joint.get("female_total_limit_extra_teachers")) or ["女班主任"],
        scope="午查 / 晚查联动",
        mode=joint.get("female_head_extra_noon_mode", "hard"),
        weight=joint.get("w_female_min_noon_night"),
        enabled=joint_enabled and bool(joint.get("enable_female_head_extra_noon_if_no_night", True)),
        config_path="day.duty_joint_constraints.enable_female_head_extra_noon_if_no_night",
    )
    _add_rule(
        group,
        id="duty.joint.same_day_mutex",
        title="同一天不同时叠加多类值班查寝",
        explanation="同一位教师同一天不能既中午查寝又下午课前值班，也不能既中午查寝又晚查寝，避免一天内任务过重。",
        targets=["全体参与值班/查寝教师"],
        scope="午查 / 晚查 / 课前值班联动",
        mode="hard",
        enabled=joint_enabled,
        config_path="day.duty_joint_constraints.enabled",
    )
    _add_rule(
        group,
        id="duty.joint.pm_pre_no_consecutive",
        title="下午课前值班不连续两天",
        explanation="同一位教师不连续两天承担下午课前值班，避免课前管理任务连续压在同一个人身上。",
        targets=["下午课前值班教师"],
        scope="下午课前值班",
        mode=joint.get("pm_pre_class_no_consecutive_mode", "hard"),
        weight=joint.get("w_pm_pre_class_no_consecutive"),
        enabled=joint_enabled,
        config_path="day.duty_joint_constraints.pm_pre_class_no_consecutive_mode",
    )
    _add_rule(
        group,
        id="duty.joint.balance",
        title="男班主任查寝次数尽量均衡",
        explanation="系统会比较男班主任一周午查+晚查总次数，尽量让大家次数接近，避免某几个人明显多。",
        targets=teacher_names(joint.get("male_balance_exclude_teachers")) or ["男班主任"],
        scope="午查 / 晚查公平性",
        mode=joint.get("male_max_min_mode", "soft"),
        weight=joint.get("w_male_max_min_gap"),
        enabled=joint_enabled and bool(joint.get("enable_soft_male_duty_balance", True)),
        config_path="day.duty_joint_constraints.enable_soft_male_duty_balance",
    )

    grade_enabled = bool(grade.get("enabled", True))
    _add_rule(
        group,
        id="duty.grade.daily_one",
        title="年级组工作日每天安排1人值班",
        explanation="年级组成员在周一到周五每天安排1人值班；周六、周日不安排年级组值班。",
        targets=teacher_names(grade.get("members")) or ["待填写年级组成员"],
        scope="年级组值班",
        mode="hard",
        enabled=grade_enabled and bool(teacher_names(grade.get("members"))),
        config_path="day.grade_group_duty.members",
    )
    _add_rule(
        group,
        id="duty.grade.min_once",
        title="年级组成员每周至少值班一次",
        explanation="每位年级组成员每周至少安排一次值班，避免值班任务只落在少数成员身上。",
        targets=teacher_names(grade.get("members")) or ["待填写年级组成员"],
        scope="年级组值班",
        mode=grade.get("min_once_mode", "hard"),
        weight=grade.get("w_min_once"),
        enabled=grade_enabled and bool(teacher_names(grade.get("members"))),
        config_path="day.grade_group_duty.min_once_mode",
    )
    _add_rule(
        group,
        id="duty.grade.need_night",
        title="年级组每天尽量有人有晚自习",
        explanation="周一到周五每天尽量保证至少一位年级组成员当晚有晚自习，便于晚间处理年级事务；如果没有，会按当前执行方式禁止或扣分。",
        targets=teacher_names(grade.get("members")) or ["待填写年级组成员"],
        scope="年级组值班 / 晚自习联动",
        mode=grade.get("daily_need_night_mode", "hard"),
        weight=grade.get("w_daily_need_night"),
        enabled=grade_enabled and bool(teacher_names(grade.get("members"))),
        config_path="day.grade_group_duty.daily_need_night_mode",
    )
    _add_rule(
        group,
        id="duty.grade.fairness",
        title="年级组值班次数尽量均衡",
        explanation="系统会让年级组成员的周值班次数尽量接近，超过组内最少次数越多，越不优先采用。",
        targets=teacher_names(grade.get("members")) or ["待填写年级组成员"],
        scope="年级组值班公平性",
        mode="soft",
        weight=grade.get("w_fairness_balance"),
        enabled=grade_enabled and bool(grade.get("enable_fairness", True)) and bool(teacher_names(grade.get("members"))),
        config_path="day.grade_group_duty.enable_fairness",
    )


def _add_link(group: dict[str, Any], cfg: dict[str, Any]) -> None:
    link = cfg.get("day_night_link", {}) or {}
    for key, title, explanation, mode_key, weight_key in [
        ("enable_day_night_link", "白天与晚自习负荷联动", "下午课和晚自习之间进行负荷控制。", None, "w1"),
        ("enable_night_requires_day", "晚自习要求当天白天有课", "教师当天无白天课时，不安排晚自习或计入惩罚。", "night_requires_day_mode", "w_night_requires_day"),
        ("enable_sun_night_no_mon_am1", "周日晚自习后周一上午1禁排", "教师周日晚自习后，周一上午1不排课。", "sun_night_no_mon_am1_mode", "w_sun_night_no_mon_am1"),
        ("enable_sun_pm_night_no_mon_am", "周日下午晚自习后周一上午禁排", "教师周日下午已有课且周日晚自习后，周一上午1/2不排课或计入惩罚。", "sun_pm_night_no_mon_am_mode", "w_sun_pm_night_no_mon_am"),
        ("enable_two_class_empty_day_no_night", "双班空整天不排晚自习", "双班教师如果当天白天完全无课，则不安排晚自习或计入惩罚。", None, "w_two_class_empty_day_no_night"),
    ]:
        _add_toggle_rule(group, link, key, title, explanation, "白天晚自习联动", mode_key, weight_key, "day_night_link")


def _add_temporary(group: dict[str, Any], cfg: dict[str, Any]) -> None:
    active = ((cfg.get("temporary_rules", {}) or {}).get("active") or [])
    for item in active:
        if not isinstance(item, dict):
            continue
        _add_rule(
            group,
            id=str(item.get("id") or item.get("source") or "temporary"),
            title=str(item.get("description") or item.get("source") or "临时规则"),
            explanation=str(item.get("source") or "用户临时加入的规则。"),
            targets=teacher_names(item.get("target_teachers")) or ["待确认对象"],
            scope=str(item.get("scope") or "临时"),
            mode="hard" if item.get("action") == "ban" else "soft",
            enabled=str(item.get("status") or "") == "active",
            config_path="temporary_rules.active",
        )


def _add_toggle_rule(
    group: dict[str, Any],
    section: dict[str, Any],
    enable_key: str,
    title: str,
    explanation: str,
    scope: str,
    mode_key: str | None,
    weight_key: str | None,
    config_prefix: str,
) -> None:
    _add_rule(
        group,
        id=f"{config_prefix}.{enable_key}",
        title=title,
        explanation=explanation,
        targets=_section_targets(section),
        scope=scope,
        mode=section.get(mode_key) if mode_key else "hard",
        weight=section.get(weight_key) if weight_key else None,
        enabled=bool(section.get(enable_key, False)),
        config_path=f"{config_prefix}.{enable_key}",
        fields=_toggle_rule_fields(section, config_prefix, enable_key, mode_key, weight_key),
    )


def _section_targets(section: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for key, value in section.items():
        if "teacher" in str(key) or "member" in str(key):
            out.extend(teacher_names(value))
    return out or ["全体适用"]


def _merge_targets(*values: Any) -> list[str]:
    out: list[str] = []
    for value in values:
        out.extend(teacher_names(value))
    return list(dict.fromkeys(out))


def _extra_head_items(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    out: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        gender = str(item.get("gender") or "").strip()
        if not name:
            continue
        if gender not in {"男", "女"}:
            gender = ""
        entry: dict[str, Any] = {"name": name, "gender": gender}
        days = _extra_head_days(item)
        if days:
            entry["days"] = days
        out.append(entry)
    return out


def _extra_head_days(item: dict[str, Any]) -> list[str]:
    raw = item.get("days", item.get("day", item.get("available_days")))
    if raw is None:
        return []
    if isinstance(raw, (list, tuple, set)):
        parts = raw
    else:
        parts = str(raw).replace("，", ",").replace("、", ",").replace("/", ",").split(",")
    return list(dict.fromkeys(str(day).strip() for day in parts if str(day).strip()))


def _extra_head_labels(value: list[dict[str, Any]]) -> list[str]:
    labels: list[str] = []
    for item in value:
        if not item.get("name"):
            continue
        day_label = f"/{'、'.join(item.get('days') or [])}" if item.get("days") else ""
        labels.append(f"{item['name']}({item.get('gender') or '未填性别'}{day_label})")
    return labels


def _personal_rule_fields(
    pcfg: dict[str, Any],
    enable_key: str,
    target_keys: str,
    mode_key: str | None,
    weight_key: str | None,
) -> list[dict[str, Any]]:
    fields = [
        _field("是否启用", f"personalized_constraints.{enable_key}", "bool", bool(pcfg.get(enable_key, False))),
    ]
    targets_cfg = pcfg.get("teacher_targets", {}) or {}
    keys = [item.strip() for item in str(target_keys).split(",") if item.strip()]
    for target_key in keys:
        path = f"personalized_constraints.teacher_targets.{target_key}"
        fields.append(_field("教师名单" if len(keys) == 1 else f"教师名单（{target_key}）", path, "list", teacher_names(targets_cfg.get(target_key, pcfg.get(target_key)))))
    if mode_key:
        fields.append(_field("要求类型", f"personalized_constraints.{mode_key}", "mode", pcfg.get(mode_key, "hard")))
    if weight_key:
        fields.append(_field("软约束优先级", f"personalized_constraints.{weight_key}", "int", pcfg.get(weight_key, 0)))
    return fields


def _toggle_rule_fields(
    section: dict[str, Any],
    config_prefix: str,
    enable_key: str,
    mode_key: str | None,
    weight_key: str | None,
) -> list[dict[str, Any]]:
    fields = [_field("是否启用", f"{config_prefix}.{enable_key}", "bool", bool(section.get(enable_key, False)))]
    if mode_key:
        fields.append(_field("要求类型", f"{config_prefix}.{mode_key}", "mode", section.get(mode_key, "hard")))
    if weight_key:
        fields.append(_field("软约束优先级", f"{config_prefix}.{weight_key}", "int", section.get(weight_key, 0)))
    return fields


def _attach_default_editors(groups: dict[str, dict[str, Any]], cfg: dict[str, Any]) -> None:
    for group in groups.values():
        for rule in group.get("rules", []):
            if rule.get("locked") is True:
                continue
            editor = rule.setdefault("editor", {"fields": []})
            fields = editor.setdefault("fields", [])
            if fields:
                continue
            path = str(rule.get("config_path") or "").strip()
            if not path:
                continue
            value = _path_get(cfg, path)
            fields.append(_field(_default_field_label(path, value), path, _field_type(value), value))


def _attach_application_editors(groups: dict[str, dict[str, Any]], cfg: dict[str, Any]) -> None:
    for group in groups.values():
        for rule in group.get("rules", []):
            if rule.get("locked") is True:
                continue
            rid = str(rule.get("id") or "")
            if not rid:
                continue
            prefix = f"rule_application.{rid}"
            app_cfg = _path_get(cfg, prefix)
            if not isinstance(app_cfg, dict):
                app_cfg = {}
            default_teachers = _editable_target_names(rule)
            target_scope = str(app_cfg.get("target_scope") or _default_target_scope(rule))
            app_teachers = teacher_names(app_cfg.get("teacher_names")) or default_teachers
            subject_groups = _clean_list(app_cfg.get("subject_groups"))
            subject_group_teachers = teacher_names(app_cfg.get("subject_group_teachers"))
            exception_teachers = teacher_names(app_cfg.get("exception_teachers"))
            exception_subject_groups = _clean_list(app_cfg.get("exception_subject_groups"))
            exception_mode = str(app_cfg.get("exception_mode") or "exclude")
            exception_note = str(app_cfg.get("exception_note") or "")
            rule["application"] = {
                "target_scope": target_scope,
                "teacher_names": app_teachers,
                "subject_groups": subject_groups,
                "subject_group_teachers": subject_group_teachers,
                "exception_teachers": exception_teachers,
                "exception_subject_groups": exception_subject_groups,
                "exception_mode": exception_mode,
                "exception_note": exception_note,
            }
            target_fields: list[dict[str, Any]] = []
            existing: list[dict[str, Any]] = []
            for field in ((rule.get("editor") or {}).get("fields") or []):
                if _is_solver_target_field(field):
                    target_fields.append(_as_application_target_field(field))
                else:
                    existing.append(_with_section(field, "执行参数"))
            application_fields = [
                _field(
                    "作用对象",
                    f"{prefix}.target_scope",
                    "choice",
                    target_scope,
                    "选择这条规则默认作用到谁。指定教师和学科组名单可以继续逐个添加。",
                    options=TARGET_SCOPE_OPTIONS,
                    section="作用对象",
                ),
            ]
            if target_fields:
                application_fields.extend(target_fields)
            else:
                application_fields.extend([
                    _field(
                        "指定教师名单",
                        f"{prefix}.teacher_names",
                        "list",
                        app_teachers,
                        "选择“指定教师”时填写，可添加 1 个或多个教师。",
                        section="作用对象",
                        ui="chips",
                    ),
                ])
            application_fields.extend([
                _field(
                    "学科组",
                    f"{prefix}.subject_groups",
                    "list",
                    subject_groups,
                    "选择“学科组”时填写，例如语文组、数学组、物理组。",
                    section="作用对象",
                    ui="chips",
                ),
                _field(
                    "学科组教师名单",
                    f"{prefix}.subject_group_teachers",
                    "list",
                    subject_group_teachers,
                    "选择“学科组”时，可把该组教师逐个添加进来。",
                    section="作用对象",
                    ui="chips",
                ),
                _field(
                    "例外教师",
                    f"{prefix}.exception_teachers",
                    "list",
                    exception_teachers,
                    "这些教师不按本规则的普通口径处理。",
                    section="例外规则",
                    ui="chips",
                ),
                _field(
                    "例外学科组",
                    f"{prefix}.exception_subject_groups",
                    "list",
                    exception_subject_groups,
                    "这些学科组不按本规则的普通口径处理。",
                    section="例外规则",
                    ui="chips",
                ),
                _field(
                    "例外处理方式",
                    f"{prefix}.exception_mode",
                    "choice",
                    exception_mode,
                    "选择例外对象遇到本规则时怎么处理。",
                    options=EXCEPTION_MODE_OPTIONS,
                    section="例外规则",
                ),
                _field(
                    "例外说明",
                    f"{prefix}.exception_note",
                    "text",
                    exception_note,
                    "记录为什么要设置例外，方便教务后续复查。",
                    section="例外规则",
                ),
            ])
            rule["editor"] = {"fields": application_fields + existing}


def _field(
    label: str,
    path: str,
    field_type: str,
    value: Any,
    help_text: str = "",
    *,
    options: list[dict[str, str]] | None = None,
    section: str = "",
    ui: str = "",
) -> dict[str, Any]:
    field = {
        "label": label,
        "path": path,
        "store": _infer_store(path),
        "type": field_type,
        "value": value,
        "help": help_text,
    }
    if options:
        field["options"] = options
    if section:
        field["section"] = section
    if ui:
        field["ui"] = ui
    return field


def _with_section(field: dict[str, Any], section: str) -> dict[str, Any]:
    out = dict(field)
    out.setdefault("section", section)
    return out


def _is_solver_target_field(field: dict[str, Any]) -> bool:
    path = str(field.get("path") or "")
    label = str(field.get("label") or "")
    return (
        str(field.get("type") or "") == "list"
        and (
            "teacher_targets" in path
            or label.startswith("教师名单")
        )
    )


def _as_application_target_field(field: dict[str, Any]) -> dict[str, Any]:
    out = dict(field)
    out["section"] = "作用对象"
    out["ui"] = "chips"
    out["help"] = out.get("help") or "这里的名单会直接写入求解配置，可添加 1 个或多个教师。"
    return out


def _default_target_scope(rule: dict[str, Any]) -> str:
    text = f"{rule.get('title', '')} {rule.get('scope', '')} {' '.join(rule.get('targets') or [])}"
    if "学科" in text or "语文" in text or "数学" in text or "物理" in text or "化学" in text:
        return "subject_group"
    if "班主任" in text:
        return "homeroom_teachers"
    if "候选" in text or "值班" in text or "查寝" in text:
        return "duty_candidates"
    if any(str(item).startswith("全体") for item in (rule.get("targets") or [])):
        return "all_teachers"
    return "selected_teachers"


def _editable_target_names(rule: dict[str, Any]) -> list[str]:
    blocked = ("全体", "待填写", "候选", "班主任", "教师", "学科", "成员", "男", "女", "配置名单")
    out: list[str] = []
    for item in rule.get("targets") or []:
        text = str(item).strip()
        if not text:
            continue
        if any(token in text for token in blocked):
            continue
        out.append(text)
    return list(dict.fromkeys(out))


def _clean_list(value: Any) -> list[str]:
    if isinstance(value, list):
        raw = value
    else:
        raw = str(value or "").replace("，", ",").replace("、", ",").split(",")
    return [str(item).strip() for item in raw if str(item).strip()]


def _infer_store(path: str) -> str:
    root = str(path).split(".", 1)[0]
    return "io" if root in {"teacher_table", "joint_solve", "warm_start", "pre_run_cleanup", "multi_solution_output", "snapshot_export", "day"} else "rules"


def _path_get(cfg: dict[str, Any], path: str) -> Any:
    cur: Any = cfg
    for part in str(path).split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
    return cur


def _field_type(value: Any) -> str:
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, (list, dict)):
        return "json"
    return "text"


def _default_field_label(path: str, value: Any) -> str:
    if isinstance(value, bool):
        return "是否启用"
    if str(path).endswith("_mode"):
        return "要求类型"
    if isinstance(value, (list, dict)):
        return "配置内容"
    return "配置值"


def _mode_label(value: Any) -> str:
    text = str(value or "hard").lower()
    if text == "soft":
        return "软约束"
    if text == "hard":
        return "硬约束"
    if text == "off":
        return "关闭"
    return _plain_text(str(value or "未设置"))


def _checkin_same_day_class_mode(checkin: dict[str, Any]) -> str:
    raw_mode = checkin.get("require_teacher_has_class_that_day_mode")
    if raw_mode is not None:
        mode = str(raw_mode or "").strip().lower()
        if mode in {"hard", "soft", "off"}:
            return mode
    return "hard" if bool(checkin.get("require_teacher_has_class_that_day", True)) else "off"


def _plain_text(value: Any) -> str:
    text = str(value or "")
    replacements = {
        "AM1": "上午第1节",
        "AM2": "上午第2节",
        "AM3": "上午第3节",
        "AM4": "上午第4节",
        "PM1": "下午第1节",
        "PM2": "下午第2节",
        "PM3": "下午第3节",
        "上午1": "上午第1节",
        "上午2": "上午第2节",
        "上午3": "上午第3节",
        "上午4": "上午第4节",
        "下午1": "下午第1节",
        "下午2": "下午第2节",
        "下午3": "下午第3节",
        "尽量/必须": "按当前执行方式",
        "hard": "硬约束",
        "soft": "软约束",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text
