# -*- coding: utf-8 -*-
"""基于 event_log 的多解诊断 Excel 导出。"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pandas as pd
from openpyxl.styles import Border, Side

from scheduler.config.loader import load_effective_config
from scheduler.diagnostics.display_catalog import (
    DORM_RULE_NAME_FALLBACK,
    PERSONALIZED_RULE_DESC_CN,
    PERSONALIZED_RULE_NAME_CN,
    PERSONALIZED_RULE_TEACHERS,
    RULE_NAME_FALLBACK_CN,
)
from scheduler.diagnostics.rule_registry import (
    all_rule_meta,
    ensure_rule_meta,
    get_rule_meta,
    validate_rule_ids,
)
from scheduler.output.excel_writer import create_excel_writer
from scheduler.output.excel_style_utils import (
    apply_conditional_format_for_diagnostics,
    apply_table_style,
)

logger = logging.getLogger(__name__)


EVENT_COLUMNS = [
    "solution_id",
    "snapshot_id",
    "constraint_id",
    "constraint_name",
    "constraint_category",
    "mode",
    "teacher_name",
    "day",
    "period",
    "class_name",
    "subject",
    "penalty",
    "unit_penalty",
    "count_value",
    "weight_key",
    "rule_params",
    "source_module",
    "description",
]

# 软约束×老师名单摘要参数（仅影响诊断展示，不影响求解）
TOPK_HIGH_PENALTY_TEACHERS = 10
ABS_THRESHOLD = 500.0
RATIO_THRESHOLD = 0.10
MAX_NAMES = 20
TOPN_SOFT_PER_SOLUTION = 10
TOPN_TEACHERS_PER_SOLUTION = 20

# “每解TopN罚分老师”展示层过滤（仅影响报表可读性，不影响求解与原始event_log）
EXCLUDED_RULE_IDS_TOPN_TEACHERS = {
    "lang_pm_penalty",          # 语文外语下午惩罚
    "multi_class_halfday_split", # 多班教师半天拆分
    "pe_am_penalty",            # 体育教师上午惩罚
}

SHEET_EVENT_LOG = "事件日志"
SHEET_SOFT_SUMMARY = "软约束汇总"
SHEET_TEACHER_SUMMARY = "教师罚分汇总"
SHEET_SOLVER_OVERVIEW = "求解概览"
SHEET_RULE_CONFIG = "规则配置表"
SHEET_SOFT_TEACHER_LIST = "软约束-教师名单"
SHEET_TOPN = "每解TopN软约束"
SHEET_TOPN_TEACHERS = "每解TopN罚分老师"
SHEET_DASHBOARD = "仪表盘"
SHEET_PERSONALIZED_SOFT_DIAG = "个性化软约束诊断表"
SHEET_DORM_SOFT_UNMET = "查寝软约束未满足明细"
SHEET_HARD_DETAIL = "硬约束明细"
SHEET_SOFT_DETAIL = "软约束明细及罚分"

MODE_CN = {
    "soft": "软约束",
    "hard": "硬约束",
}

CATEGORY_CN = {
    "fairness": "公平性",
    "compactness": "紧凑性",
    "ban": "禁排/限制",
    "preference": "偏好",
    "linkage": "联动",
    "night-duty": "晚间值班",
    "teacher_load": "教师负载",
    "schedule_pattern": "排课形态",
}

WEEKDAY_ORDER = {
    "星期一": 1,
    "星期二": 2,
    "星期三": 3,
    "星期四": 4,
    "星期五": 5,
    "星期六": 6,
    "星期日": 7,
}

for _rule_key, _rule_name in PERSONALIZED_RULE_NAME_CN.items():
    ensure_rule_meta(
        f"personalized_{_rule_key}",
        name_cn=str(_rule_name),
        description=str(PERSONALIZED_RULE_DESC_CN.get(_rule_key, _rule_name)),
        mode="soft",
        source_module="scheduler/model/constraints/personalized_constraints.py",
    )

for _rule_key, _rule_name in RULE_NAME_FALLBACK_CN.items():
    ensure_rule_meta(
        str(_rule_key),
        name_cn=str(_rule_name),
        description=str(_rule_name),
        mode="soft",
        source_module="scheduler/model/constraints",
    )


def _extract_personalized_key(constraint_id: object, constraint_name: object) -> str:
    cid = str(constraint_id or "").strip()
    cname = str(constraint_name or "").strip()
    if cid.startswith("personalized_"):
        return cid.replace("personalized_", "", 1)
    if cname.startswith("个性化约束::"):
        return cname.split("::", 1)[1].strip()
    if cid.startswith("rule"):
        return cid
    if cname.startswith("rule"):
        return cname
    return ""


def _friendly_personalized_name(rule_key: str, fallback: str) -> str:
    key = str(rule_key or "").strip()
    if not key:
        return fallback
    meta = get_rule_meta(f"personalized_{key}") or get_rule_meta(key)
    if meta is not None and str(meta.name_cn).strip():
        return str(meta.name_cn)
    return PERSONALIZED_RULE_NAME_CN.get(key, f"个性化约束：{key}")


def _friendly_personalized_desc(rule_key: str, fallback_name: str) -> str:
    key = str(rule_key or "").strip()
    if not key:
        return fallback_name
    meta = get_rule_meta(f"personalized_{key}") or get_rule_meta(key)
    if meta is not None and str(meta.description).strip():
        return str(meta.description)
    return PERSONALIZED_RULE_DESC_CN.get(key, f"{_friendly_personalized_name(key, fallback_name)}。")


def _find_unmapped_personalized_rule_keys(event_log: pd.DataFrame) -> list[str]:
    missing: set[str] = set()
    if event_log.empty:
        return []
    for _, row in event_log.iterrows():
        rule_key = _extract_personalized_key(row.get("constraint_id", ""), row.get("constraint_name", ""))
        if not rule_key:
            continue
        if get_rule_meta(f"personalized_{rule_key}") is None and get_rule_meta(rule_key) is None:
            missing.add(rule_key)
    return sorted(missing)


def _friendly_constraint_name(constraint_id: object, constraint_name: object) -> str:
    cid = str(constraint_id or "").strip()
    cname = str(constraint_name or "").strip()
    meta = get_rule_meta(cid)
    if meta is not None and str(meta.name_cn).strip():
        return str(meta.name_cn)
    if cid in RULE_NAME_FALLBACK_CN:
        return RULE_NAME_FALLBACK_CN[cid]
    pkey = _extract_personalized_key(cid, cname)
    if pkey:
        return _friendly_personalized_name(pkey, cname or cid)
    if not cname or "?" in cname:
        return cid or cname
    return cname


def _friendly_constraint_desc(constraint_id: object, constraint_name: object, description: object) -> str:
    cid = str(constraint_id or "").strip()
    cname = str(constraint_name or "").strip()
    desc = str(description or "").strip()
    meta = get_rule_meta(cid)
    if meta is not None and str(meta.description).strip():
        return str(meta.description)
    pkey = _extract_personalized_key(cid, cname)
    if pkey:
        return _friendly_personalized_desc(pkey, _friendly_personalized_name(pkey, cname or cid))
    if not desc or "?" in desc:
        return _friendly_constraint_name(cid, cname)
    if desc.startswith("个性化约束::"):
        pkey2 = _extract_personalized_key(cid, desc)
        if pkey2:
            return _friendly_personalized_desc(pkey2, _friendly_personalized_name(pkey2, cname or cid))
    return desc

DETAIL_CATEGORY_ORDER = {
    "白天": 1,
    "晚自习": 2,
    "午查寝": 3,
    "晚查寝": 4,
    "联动": 5,
    "个性化": 6,
    "其他": 99,
}


def _detail_category(module_path: str, constraint_id: str = "") -> str:
    src = str(module_path or "").lower()
    cid = str(constraint_id or "").lower()
    text = f"{src} {cid}"
    if "personalized" in text:
        return "个性化"
    if "day_night_bridge" in text or "duty_joint" in text or "grade_group" in text:
        return "联动"
    if "noon" in text or "day_noon_dorm" in text:
        return "午查寝"
    if "checkin" in text:
        return "晚查寝"
    if "night" in text:
        return "晚自习"
    if "day_" in text or "weekday" in text or "weekend" in text or "head_duty" in text:
        return "白天"
    if cid.startswith("personalized_"):
        return "个性化"
    if cid.startswith("day_night_link_") or cid.startswith("duty_joint_") or cid.startswith("grade_duty_"):
        return "联动"
    if cid.startswith("noon_"):
        return "午查寝"
    if cid.startswith("night_") or cid.startswith("hard_"):
        return "晚自习"
    return "其他"


def _detail_sort_key(cat: str, name: str = "") -> tuple:
    c = str(cat or "其他")
    return (DETAIL_CATEGORY_ORDER.get(c, 999), c, str(name or ""))


def _find_project_root_from_output(root_out: Path) -> Path:
    candidates = [root_out.parent, Path.cwd()]
    for start in candidates:
        p = start.resolve()
        chain = [p] + list(p.parents)
        for c in chain:
            if (c / "scheduler" / "config" / "io.yaml").exists():
                return c
    return Path.cwd().resolve()


def _load_diagnostic_configs(root_out: Path) -> tuple[dict, dict]:
    project_root = _find_project_root_from_output(root_out)
    io_path = project_root / "scheduler" / "config" / "io.yaml"
    rules_path = project_root / "scheduler" / "config" / "rules.yaml"
    if not io_path.exists():
        return {}, {}
    try:
        eff = load_effective_config(
            "diagnostics",
            {"project_root": project_root, "io_path": io_path, "rules_path": rules_path},
        )
        return eff.io_cfg or {}, eff.rules_cfg or {}
    except Exception:
        return {}, {}


def _cfg_get(cfg: dict, dotted: str, default: Any = None) -> Any:
    cur: Any = cfg
    for key in str(dotted or "").split("."):
        if key == "":
            continue
        if not isinstance(cur, dict) or key not in cur:
            return default
        cur = cur[key]
    return cur


def _cfg_has(cfg: dict, dotted: str) -> bool:
    marker = object()
    return _cfg_get(cfg, dotted, marker) is not marker


def _cfg_resolve(io_cfg: dict, rules_cfg: dict, dotted: str, default: Any = None) -> Any:
    if _cfg_has(io_cfg, dotted):
        return _cfg_get(io_cfg, dotted, default)
    if _cfg_has(rules_cfg, dotted):
        return _cfg_get(rules_cfg, dotted, default)
    return default


def _fmt_weight(v: Any) -> str:
    try:
        fv = float(v)
    except Exception:
        return str(v) if v is not None else ""
    if abs(fv - round(fv)) < 1e-9:
        return str(int(round(fv)))
    return f"{fv:.2f}".rstrip("0").rstrip(".")


def _fmt_yaml_fields(paths: List[str], io_cfg: dict, rules_cfg: dict) -> str:
    items: List[str] = []
    for p in [str(x).strip() for x in (paths or []) if str(x).strip()]:
        exists = _cfg_has(io_cfg, p) or _cfg_has(rules_cfg, p)
        items.append(p if exists else f"{p}（默认）")
    return "；".join(items) if items else "（默认）"


def _pick_current_solution_id(event_log: pd.DataFrame) -> str:
    if event_log.empty or "solution_id" not in event_log.columns:
        return ""
    final_rows = event_log[event_log.get("snapshot_id", "").astype(str) == "最终解"]
    if not final_rows.empty:
        for sid in final_rows["solution_id"].astype(str).tolist():
            if sid.strip():
                return sid
    ordered = _order_solution_ids(event_log)
    return ordered[-1] if ordered else ""


PERSONALIZED_CFG_META: Dict[str, Dict[str, Any]] = {
    "rule1": {"enable": "personalized_constraints.enable_xhd_night_no_pm3", "mode": "personalized_constraints.xhd_night_no_pm3_mode", "weights": ["personalized_constraints.w_xhd_night_no_pm3"]},
    "rule28_xhd_night_no_pm": {"enable": "personalized_constraints.enable_xhd_night_no_pm", "mode": "personalized_constraints.xhd_night_no_pm_mode", "weights": ["personalized_constraints.w_xhd_night_no_pm"]},
    "rule2_diff": {"enable": "personalized_constraints.enable_couple_xhd_zfy", "mode": "personalized_constraints.couple_xhd_zfy_mode", "weights": ["personalized_constraints.w_couple_diff_day", "personalized_constraints.w_couple_need_overlap"]},
    "rule2_overlap": {"enable": "personalized_constraints.enable_couple_xhd_zfy", "mode": "personalized_constraints.couple_xhd_zfy_mode", "weights": ["personalized_constraints.w_couple_need_overlap"]},
    "rule2_couple_overlap_soft": {"enable": "personalized_constraints.enable_couple_xhd_zfy", "mode": "personalized_constraints.couple_xhd_zfy_mode", "weights": ["personalized_constraints.w_couple_need_overlap"]},
    "rule3": {"enable": "personalized_constraints.enable_zw_night_need_pm", "mode": "personalized_constraints.zw_night_need_pm_mode", "weights": ["personalized_constraints.w_zw_night_need_pm"]},
    "rule4": {"enable": "personalized_constraints.enable_lm_sun_am12", "mode": "personalized_constraints.lm_sun_am12_mode", "weights": ["personalized_constraints.w_lm_sun_am12"]},
    "rule5_am": {"enable": "personalized_constraints.enable_ytt_sun_pref", "mode": "personalized_constraints.ytt_sun_pref_mode", "weights": ["personalized_constraints.w_ytt_sun_am_pref"]},
    "rule5_night": {"enable": "personalized_constraints.enable_ytt_sun_pref", "mode": "personalized_constraints.ytt_sun_pref_mode", "weights": ["personalized_constraints.w_ytt_no_sun_night"]},
    "rule7_cnt": {"enable": "personalized_constraints.enable_pol_no_sun_night", "mode": "personalized_constraints.pol_no_sun_night_mode", "weights": ["personalized_constraints.w_pol_sun_teacher_count"]},
    "rule7_super": {"enable": "personalized_constraints.enable_pol_no_sun_night", "mode": "personalized_constraints.pol_no_sun_night_mode", "weights": ["personalized_constraints.w_pol_sun_super"]},
    "rule8": {"enable": "personalized_constraints.enable_ld_reduce_pm", "mode": "personalized_constraints.ld_reduce_pm_mode", "weights": ["personalized_constraints.w_ld_reduce_pm"]},
    "rule32_ld_tue_fri_pm_each": {"enable": "personalized_constraints.enable_ld_tue_fri_pm_penalty", "mode": "", "weights": ["personalized_constraints.w_ld_tue_fri_pm_each"]},
    "rule33_ld_tue_fri_pm1_extra_each": {"enable": "personalized_constraints.enable_ld_tue_fri_pm_penalty", "mode": "", "weights": ["personalized_constraints.w_ld_tue_fri_pm1_extra_each"]},
    "rule10_mon_am1": {"enable": "personalized_constraints.enable_jxq_prefs", "mode": "personalized_constraints.jxq_prefs_mode", "weights": ["personalized_constraints.w_jxq_no_mon_am1"]},
    "rule10_sun_pm": {"enable": "personalized_constraints.enable_jxq_prefs", "mode": "personalized_constraints.jxq_prefs_mode", "weights": ["personalized_constraints.w_jxq_sun_pm_pref"]},
    "rule10_sun_night": {"enable": "personalized_constraints.enable_jxq_prefs", "mode": "personalized_constraints.jxq_prefs_mode", "weights": ["personalized_constraints.w_jxq_no_sun_night"]},
    "rule11_sun_am": {"enable": "personalized_constraints.enable_csqi_prefs", "mode": "personalized_constraints.csqi_prefs_mode", "weights": ["personalized_constraints.w_csqi_sun_am_pref"]},
    "rule11_outside": {"enable": "personalized_constraints.enable_csqi_prefs", "mode": "personalized_constraints.csqi_prefs_mode", "weights": ["personalized_constraints.w_csqi_night_outside_pen"]},
    "rule11_need": {"enable": "personalized_constraints.enable_csqi_prefs", "mode": "personalized_constraints.csqi_prefs_mode", "weights": ["personalized_constraints.w_csqi_need_sun_or_mon"]},
    "rule30_csqi_consecutive_night": {"enable": "personalized_constraints.enable_csqi_need_consecutive_night", "mode": "personalized_constraints.csqi_need_consecutive_night_mode", "weights": ["personalized_constraints.w_csqi_need_consecutive_night"]},
    "rule12_sun_night": {"enable": "personalized_constraints.enable_zzx_prefs", "mode": "personalized_constraints.zzx_prefs_mode", "weights": ["personalized_constraints.w_zzx_no_sun_night"]},
    "rule12_sun_am": {"enable": "personalized_constraints.enable_zzx_prefs", "mode": "personalized_constraints.zzx_prefs_mode", "weights": ["personalized_constraints.w_zzx_sun_am_pref"]},
    "rule12_am4": {"enable": "personalized_constraints.enable_zzx_prefs", "mode": "personalized_constraints.zzx_prefs_mode", "weights": ["personalized_constraints.w_zzx_reduce_am4"]},
    "rule34_zzx_no_sunday_night": {"enable": "personalized_constraints.enable_zzx_no_sunday_night", "mode": "personalized_constraints.zzx_no_sunday_night_mode", "weights": ["personalized_constraints.w_zzx_no_sunday_night"]},
    "rule38_xyx_night_days_only": {"enable": "personalized_constraints.enable_xyx_night_days_only", "mode": "personalized_constraints.xyx_night_days_only_mode", "weights": ["personalized_constraints.w_xyx_night_days_only"]},
    "rule13_need": {"enable": "personalized_constraints.enable_hwj_prefs", "mode": "personalized_constraints.hwj_prefs_mode", "weights": ["personalized_constraints.w_hwj_need_sun_mon"]},
    "rule13_consec": {"enable": "personalized_constraints.enable_hwj_prefs", "mode": "personalized_constraints.hwj_prefs_mode", "weights": ["personalized_constraints.w_hwj_need_consecutive"]},
    "rule13_hwj_sun_mon_assign": {"enable": "personalized_constraints.enable_hwj_night_sun_mon_assign", "mode": "personalized_constraints.hwj_night_sun_mon_assign_mode", "weights": ["personalized_constraints.w_hwj_night_sun_mon_assign"]},
    "rule14": {"enable": "personalized_constraints.enable_hsm_no_fri_night", "mode": "personalized_constraints.hsm_no_fri_night_mode", "weights": ["personalized_constraints.w_hsm_no_fri_night"]},
    "rule35_hsm_weekday_early_no_am1": {"enable": "personalized_constraints.enable_hsm_weekday_early_no_am1", "mode": "personalized_constraints.hsm_weekday_early_no_am1_mode", "weights": ["personalized_constraints.w_hsm_weekday_early_no_am1"]},
    "rule36_wxl_weekday_early_no_am1": {"enable": "personalized_constraints.enable_wxl_weekday_early_no_am1", "mode": "personalized_constraints.wxl_weekday_early_no_am1_mode", "weights": ["personalized_constraints.w_wxl_weekday_early_no_am1"]},
    "rule15_am1": {"enable": "personalized_constraints.enable_zhoubo_weekday_am1_penalty", "mode": "personalized_constraints.zhoubo_weekday_am1_penalty_mode", "weights": ["personalized_constraints.w_zhoubo_weekday_am1_penalty"]},
    "rule17_xww_am4_pm1": {"enable": "personalized_constraints.enable_xww_weekday_am4_pm1_stair", "mode": "personalized_constraints.xww_weekday_am4_pm1_stair_mode", "weights": ["personalized_constraints.w_xww_weekday_am4_pm1_e2", "personalized_constraints.w_xww_weekday_am4_pm1_e3", "personalized_constraints.w_xww_weekday_am4_pm1_e4"]},
    "rule18_zfy_consecutive_night": {"enable": "personalized_constraints.enable_zfy_no_consecutive_night", "mode": "personalized_constraints.zfy_no_consecutive_night_mode", "weights": ["personalized_constraints.w_zfy_no_consecutive_night"]},
    "rule19_zfy_no_sunday_night": {"enable": "personalized_constraints.enable_zfy_no_sunday_night", "mode": "personalized_constraints.zfy_no_sunday_night_mode", "weights": ["personalized_constraints.w_zfy_no_sunday_night"]},
    "rule20_sll_sun_am_only": {"enable": "personalized_constraints.enable_sll_sun_am_only", "mode": "personalized_constraints.sll_sun_am_only_mode", "weights": ["personalized_constraints.w_sll_sun_am_only"]},
    "rule21_cc_weekday_no_am4": {"enable": "personalized_constraints.enable_cc_weekday_no_am4", "mode": "personalized_constraints.cc_weekday_no_am4_mode", "weights": ["personalized_constraints.w_cc_weekday_no_am4"]},
    "rule22_cc_sat_am34_class17": {"enable": "personalized_constraints.enable_cc_sat_am34_class17", "mode": "personalized_constraints.cc_sat_am34_class17_mode", "weights": ["personalized_constraints.w_cc_sat_am34_class17"]},
    "rule23_sm_mon_no_am": {"enable": "personalized_constraints.enable_sm_mon_no_am", "mode": "personalized_constraints.sm_mon_no_am_mode", "weights": ["personalized_constraints.w_sm_mon_no_am"]},
    "rule24_sm_mon_no_pm1": {"enable": "personalized_constraints.enable_sm_mon_no_pm1", "mode": "personalized_constraints.sm_mon_no_pm1_mode", "weights": ["personalized_constraints.w_sm_mon_no_pm1"]},
    "rule25_zw_am1_cap": {"enable": "personalized_constraints.enable_zw_am1_cap", "mode": "personalized_constraints.zw_am1_cap_mode", "weights": ["personalized_constraints.w_zw_am1_cap"]},
    "rule26_zw_am2_cap": {"enable": "personalized_constraints.enable_zw_am2_cap", "mode": "personalized_constraints.zw_am2_cap_mode", "weights": ["personalized_constraints.w_zw_am2_cap"]},
    "rule27_zw_am4_cap": {"enable": "personalized_constraints.enable_zw_am4_cap", "mode": "personalized_constraints.zw_am4_cap_mode", "weights": ["personalized_constraints.w_zw_am4_cap"]},
    "rule37_zw_weekday_pm1_cap": {"enable": "personalized_constraints.enable_zw_weekday_pm1_cap", "mode": "personalized_constraints.zw_weekday_pm1_cap_mode", "weights": ["personalized_constraints.w_zw_weekday_pm1_cap"]},
    "rule29_zw_no_consecutive_night": {"enable": "personalized_constraints.enable_zw_no_consecutive_night", "mode": "personalized_constraints.zw_no_consecutive_night_mode", "weights": ["personalized_constraints.w_zw_no_consecutive_night"]},
    "rule31_mrj_hsm_sun_am12_fixed": {"enable": "personalized_constraints.enable_mrj_hsm_sun_am12_fixed", "mode": "personalized_constraints.mrj_hsm_sun_am12_fixed_mode", "weights": ["personalized_constraints.w_mrj_hsm_sun_am12_fixed"]},
}

SWITCHABLE_CONSTRAINT_CATALOG: Dict[str, Dict[str, Any]] = {
    "duty_joint_female_min_noon_night": {
        "name": "女班主任每周午查+晚查至少1次",
        "module": "scheduler/model/constraints/duty_joint_constraints.py",
        "category": "联动",
        "enable": "day.duty_joint_constraints.enabled",
        "mode": "day.duty_joint_constraints.female_min_noon_night_mode",
        "weights": ["day.duty_joint_constraints.w_female_min_noon_night"],
    },
    "duty_joint_male_max_min_gap": {
        "name": "男班主任午查+晚查 max-min 超额",
        "module": "scheduler/model/constraints/duty_joint_constraints.py",
        "category": "联动",
        "enable": "day.duty_joint_constraints.enabled",
        "mode": "day.duty_joint_constraints.male_max_min_mode",
        "weights": ["day.duty_joint_constraints.w_male_max_min_gap"],
    },
    "duty_joint_male_total_target_over": {
        "name": "男班主任午查+晚查次数超过目标",
        "module": "scheduler/model/constraints/duty_joint_constraints.py",
        "category": "联动",
        "enable": "day.duty_joint_constraints.enabled",
        "mode": "day.duty_joint_constraints.male_total_target_mode",
        "weights": ["day.duty_joint_constraints.w_male_total_target_deviation"],
    },
    "duty_joint_male_total_target_under": {
        "name": "男班主任午查+晚查次数低于目标",
        "module": "scheduler/model/constraints/duty_joint_constraints.py",
        "category": "联动",
        "enable": "day.duty_joint_constraints.enabled",
        "mode": "day.duty_joint_constraints.male_total_target_mode",
        "weights": ["day.duty_joint_constraints.w_male_total_target_deviation"],
    },
    "duty_joint_pm_pre_class_no_consecutive": {
        "name": "下午课前值班不连续两天",
        "module": "scheduler/model/constraints/duty_joint_constraints.py",
        "category": "联动",
        "enable": "day.duty_joint_constraints.enabled",
        "mode": "day.duty_joint_constraints.pm_pre_class_no_consecutive_mode",
        "weights": ["day.duty_joint_constraints.w_pm_pre_class_no_consecutive"],
    },
    "noon_dorm_ban_lihuijiao_soft": {
        "name": "指定教师中午查寝禁排",
        "module": "scheduler/model/constraints/day_noon_dorm_duty_constraints.py",
        "category": "午查寝",
        "enable": "day.noon_dorm_duty.enabled",
        "mode": "day.noon_dorm_duty.lhj_noon_ban_mode",
        "weights": ["day.noon_dorm_duty.w_lhj_noon_ban"],
    },
    "noon_dorm_ban_zeng_soft": {
        "name": "指定教师中午查寝禁排",
        "module": "scheduler/model/constraints/day_noon_dorm_duty_constraints.py",
        "category": "午查寝",
        "enable": "day.noon_dorm_duty.enabled",
        "mode": "day.noon_dorm_duty.zeng_noon_ban_mode",
        "weights": ["day.noon_dorm_duty.w_zeng_noon_ban"],
    },
    "night_checkin_zeng_need_on": {
        "name": "指定教师晚查寝需当日有晚自习",
        "module": "scheduler/model/constraints/checkin.py",
        "category": "晚查寝",
        "enable": "checkin.enable_zeng_checkin_require_class_that_day",
        "mode": "checkin.zeng_checkin_require_class_mode",
        "weights": ["checkin.w_zeng_checkin_require_class_that_day"],
    },
    "night_checkin_need_same_day_class": {
        "name": "晚查寝教师需当日有晚自习",
        "module": "scheduler/model/constraints/checkin.py",
        "category": "晚查寝",
        "enable": "checkin.enabled",
        "mode": "checkin.require_teacher_has_class_that_day_mode",
        "weights": ["checkin.w_require_teacher_has_class_that_day"],
    },
    "night_checkin_zeng_penalty": {
        "name": "指定教师晚查寝惩罚",
        "module": "scheduler/model/constraints/checkin.py",
        "category": "晚查寝",
        "enable": "checkin.enable_zeng_checkin_require_class_that_day",
        "mode": "checkin.zeng_night_checkin_penalty_mode",
        "weights": ["checkin.w_zeng_night_checkin_penalty"],
    },
    "grade_duty_min_once": {
        "name": "年级组成员每周至少1次值班",
        "module": "scheduler/model/constraints/grade_group_duty_constraints.py",
        "category": "联动",
        "enable": "day.grade_group_duty.enabled",
        "mode": "day.grade_group_duty.min_once_mode",
        "weights": ["day.grade_group_duty.w_min_once"],
    },
    "grade_group_daily_need_night": {
        "name": "每天至少1位年级组成员有晚自习",
        "module": "scheduler/model/constraints/grade_group_duty_constraints.py",
        "category": "联动",
        "enable": "day.grade_group_duty.enabled",
        "mode": "day.grade_group_duty.daily_need_night_mode",
        "weights": ["day.grade_group_duty.w_daily_need_night"],
    },
    "day_night_link_night_requires_day": {
        "name": "白天无课不得安排晚自习/晚查寝",
        "module": "scheduler/model/constraints/day_night_bridge.py",
        "category": "联动",
        "enable": "day_night_link.enable_night_requires_day",
        "mode": "day_night_link.night_requires_day_mode",
        "weights": ["day_night_link.w_night_requires_day"],
    },
    "day_night_link_sun_night_no_mon_am1": {
        "name": "周日晚自习=>周一上午1禁排",
        "module": "scheduler/model/constraints/day_night_bridge.py",
        "category": "联动",
        "enable": "day_night_link.enable_sun_night_no_mon_am1",
        "mode": "day_night_link.sun_night_no_mon_am1_mode",
        "weights": ["day_night_link.w_sun_night_no_mon_am1"],
    },
    "day_night_link_sun_pm_night_no_mon_am": {
        "name": "周日白天+晚自习后周一上午禁排",
        "module": "scheduler/model/constraints/day_night_bridge.py",
        "category": "联动",
        "enable": "day_night_link.enable_sun_pm_night_no_mon_am",
        "mode": "day_night_link.sun_pm_night_no_mon_am_mode",
        "weights": ["day_night_link.w_sun_pm_night_no_mon_am"],
    },
    "night_fri_sun_mutex_soft": {
        "name": "周五周日晚自习互斥（软）",
        "module": "scheduler/model/constraints/soft_objective.py",
        "category": "晚自习",
        "enable": "evening_constraints.enable_fri_sun_mutex",
        "mode": "evening_constraints.fri_sun_mutex_mode",
        "weights": ["evening_constraints.fri_sun_mutex_weight"],
    },
    "night_yk_xxc_fri_mutex_soft": {
        "name": "指定教师与指定教师周五晚自习互斥（软）",
        "module": "scheduler/model/constraints/soft_objective.py",
        "category": "晚自习",
        "enable": "evening_constraints.enable_yk_xxc_fri_mutex",
        "mode": "evening_constraints.yk_xxc_fri_mutex_mode",
        "weights": ["evening_constraints.yk_xxc_fri_mutex_weight"],
    },
    "am1_pm1_mutex": {
        "name": "工作日AM1+PM1组合禁排",
        "module": "scheduler/model/constraints/day_weekday_constraints.py",
        "category": "白天",
        "enable": "day_constraints.enable_am1_pm1_mutex",
        "mode": "day_constraints.am1_pm1_mutex_mode",
        "weights": ["day_constraints.w_am1_pm1_mutex"],
    },
    "two_class_am1_pm1_combo": {
        "name": "双班教师AM1+PM1分散组合禁排",
        "module": "scheduler/model/constraints/day_weekday_constraints.py",
        "category": "白天",
        "enable": "day_constraints.enable_two_class_am1_pm1_combo",
        "mode": "day_constraints.two_class_am1_pm1_combo_mode",
        "weights": ["day_constraints.w_two_class_am1_pm1_combo"],
    },
    "am1_pm1_exclusive": {
        "name": "工作日AM1与PM1互斥",
        "module": "scheduler/model/constraints/day_weekday_constraints.py",
        "category": "白天",
        "enable": "day_constraints.enable_am1_pm1_exclusive",
        "mode": "day_constraints.am1_pm1_exclusive_mode",
        "weights": ["day_constraints.w_am1_pm1_exclusive"],
    },
    "weekend_halfday_constraint": {
        "name": "周末课程集中半天",
        "module": "scheduler/model/constraints/day_weekend_constraints.py",
        "category": "白天",
        "enable": "day_constraints.enable_weekend_halfday_constraint",
        "mode": "day_constraints.weekend_halfday_mode",
        "weights": ["day_constraints.w_weekend_halfday"],
    },
}

FIXED_SOFT_CONSTRAINT_CATALOG: Dict[str, Dict[str, Any]] = {
    "day_night_link_w1": {"name": "晚自习需当天下午有课", "module": "scheduler/model/constraints/day_night_bridge.py", "category": "联动", "weights": ["day_night_link.w1"]},
    "day_night_link_sun_night_no_mon_am1": {"name": "周日晚自习=>周一上午1禁排", "module": "scheduler/model/constraints/day_night_bridge.py", "category": "联动", "weights": ["day_night_link.w_sun_night_no_mon_am1"]},
    "day_night_link_sun_pm_night_no_mon_am": {"name": "周日白天+晚自习后周一上午禁排", "module": "scheduler/model/constraints/day_night_bridge.py", "category": "联动", "weights": ["day_night_link.w_sun_pm_night_no_mon_am"]},
    "day_night_link_w3": {"name": "晚自习后次日AM1惩罚", "module": "scheduler/model/constraints/day_night_bridge.py", "category": "联动", "weights": ["day_night_link.w3"]},
    "day_night_link_w4": {"name": "白天重负荷后晚自习惩罚", "module": "scheduler/model/constraints/day_night_bridge.py", "category": "联动", "weights": ["day_night_link.w4"]},
    "day_night_link_two_class_empty_day_no_night": {"name": "双班教师空整天仍排晚自习惩罚", "module": "scheduler/model/constraints/day_night_bridge.py", "category": "联动", "weights": ["day_night_link.w_two_class_empty_day_no_night"]},
    "head_duty_pm1_trigger": {"name": "班主任PM1单独惩罚", "module": "scheduler/model/constraints/day_head_teacher_duty_constraints.py", "category": "白天", "weights": ["day.head_duty_constraints.w_pm1_penalty"]},
    "head_duty_pm1_without_duty": {"name": "班主任PM1无同日值班惩罚", "module": "scheduler/model/constraints/day_head_teacher_duty_constraints.py", "category": "白天", "weights": ["day.head_duty_constraints.w_pm1_penalty"]},
    "lang_pm_penalty": {"name": "语文外语下午惩罚", "module": "scheduler/model/constraints/weekday_constraints.py", "category": "白天", "weights": ["day.weekday_constraints.w_lang_pm_penalty"]},
    "lang_am_reward": {"name": "语文外语上午偏好", "module": "scheduler/model/constraints/weekday_constraints.py", "category": "白天", "weights": ["day.weekday_constraints.w_lang_am_reward"]},
    "lang_tue_fri_am1_reward": {"name": "语文外语周二至周五上午1奖励", "module": "scheduler/model/constraints/day_weekday_constraints.py", "category": "白天", "weights": ["day.weekday_constraints.w_lang_tue_fri_am1_reward"]},
    "lang_tue_fri_pm1_penalty": {"name": "语文外语周二至周五下午1惩罚", "module": "scheduler/model/constraints/day_weekday_constraints.py", "category": "白天", "weights": ["day.weekday_constraints.w_lang_tue_fri_pm1_penalty"]},
    "lang_tue_fri_pm2_penalty": {"name": "语文外语周二至周五下午2惩罚", "module": "scheduler/model/constraints/day_weekday_constraints.py", "category": "白天", "weights": ["day.weekday_constraints.w_lang_tue_fri_pm2_penalty"]},
    "lang_tue_fri_pm3_penalty": {"name": "语文外语周二至周五下午3惩罚", "module": "scheduler/model/constraints/day_weekday_constraints.py", "category": "白天", "weights": ["day.weekday_constraints.w_lang_tue_fri_pm3_penalty"]},
    "stem_am1_penalty": {"name": "数理化AM1惩罚", "module": "scheduler/model/constraints/weekday_constraints.py", "category": "白天", "weights": ["day.weekday_constraints.w_stem_am1_penalty"]},
    "teacher_only_am1_day": {"name": "教师仅AM1当天惩罚", "module": "scheduler/model/constraints/weekday_constraints.py", "category": "白天", "weights": ["day.weekday_constraints.w_teacher_only_am1_day"]},
    "teacher_am1_excess": {"name": "教师AM1超额惩罚", "module": "scheduler/model/constraints/weekday_constraints.py", "category": "白天", "weights": ["day.weekday_constraints.w_teacher_am1_excess"]},
    "teacher_m1_hit_cap": {"name": "教师AM1命中上限惩罚", "module": "scheduler/model/constraints/weekday_constraints.py", "category": "白天", "weights": ["day.weekday_constraints.w_hit_m1_cap"]},
    "teacher_continuity_gap": {"name": "教师半天空档惩罚", "module": "scheduler/model/constraints/weekday_constraints.py", "category": "白天", "weights": ["day.weekday_constraints.teacher_continuity_gap_weight"]},
    "teacher_am4_pm1_w3": {"name": "AM4+PM1阈值阶梯w3", "module": "scheduler/model/constraints/weekday_constraints.py", "category": "白天", "weights": ["day.weekday_constraints.teacher_am4_pm1_w3"]},
    "teacher_am4_pm1_w4": {"name": "AM4+PM1阈值阶梯w4", "module": "scheduler/model/constraints/weekday_constraints.py", "category": "白天", "weights": ["day.weekday_constraints.teacher_am4_pm1_w4"]},
    "teacher_am4_pm1_w5": {"name": "AM4+PM1阈值阶梯w5", "module": "scheduler/model/constraints/weekday_constraints.py", "category": "白天", "weights": ["day.weekday_constraints.teacher_am4_pm1_w5"]},
    "teacher_am4_pm1_w6": {"name": "AM4+PM1阈值阶梯w6", "module": "scheduler/model/constraints/weekday_constraints.py", "category": "白天", "weights": ["day.weekday_constraints.teacher_am4_pm1_w6"]},
    "multi_class_halfday": {"name": "多班教师半天集中惩罚", "module": "scheduler/model/constraints/weekday_constraints.py", "category": "白天", "weights": ["day.weekday_constraints.weight_multi_class_halfday"]},
    "multi_class_halfday_cross": {"name": "多班跨半天惩罚", "module": "scheduler/model/constraints/weekday_constraints.py", "category": "白天", "weights": ["day.weekday_constraints.weight_multi_class_halfday"]},
    "multi_class_halfday_split": {"name": "多班同半天拆分惩罚", "module": "scheduler/model/constraints/weekday_constraints.py", "category": "白天", "weights": ["day.weekday_constraints.weight_multi_class_halfday"]},
    "weekday_subject_balance_over": {"name": "学科周中均衡超额惩罚", "module": "scheduler/model/constraints/weekday_constraints.py", "category": "白天", "weights": ["day.weekday_constraints.weight_balance_weekday_subject_hours"]},
    "pe_am_penalty": {"name": "体育上午惩罚", "module": "scheduler/model/constraints/pe_tech_constraints.py", "category": "白天", "weights": ["day.pe_tech_constraints.w_pe_am_penalty"]},
    "pe_gap_penalty": {"name": "体技空档惩罚", "module": "scheduler/model/constraints/pe_tech_constraints.py", "category": "白天", "weights": ["day.pe_tech_constraints.w_pe_gap_penalty"]},
    "weekend_cross_halfday": {"name": "周末跨半天惩罚", "module": "scheduler/model/constraints/weekend_constraints.py", "category": "白天", "weights": ["day.weekend_constraints.cross_halfday_penalty"]},
    "noon_dorm_need_am4_lvl3": {"name": "中午查寝优先上午4-L3", "module": "scheduler/model/constraints/day_noon_dorm_duty_constraints.py", "category": "午查寝", "weights": ["day.noon_dorm_duty.w_need_am4_lvl3"]},
    "noon_dorm_need_am4_lvl2": {"name": "中午查寝优先上午4-L2", "module": "scheduler/model/constraints/day_noon_dorm_duty_constraints.py", "category": "午查寝", "weights": ["day.noon_dorm_duty.w_need_am4_lvl2"]},
    "noon_dorm_need_am4_lvl1": {"name": "中午查寝优先上午4-L1", "module": "scheduler/model/constraints/day_noon_dorm_duty_constraints.py", "category": "午查寝", "weights": ["day.noon_dorm_duty.w_need_am4_lvl1"]},
    "noon_dorm_need_am4_lvl0": {"name": "中午查寝优先上午4-L0", "module": "scheduler/model/constraints/day_noon_dorm_duty_constraints.py", "category": "午查寝", "weights": ["day.noon_dorm_duty.w_need_am4_lvl0"]},
    "noon_dorm_avoid_pm1": {"name": "中午查寝当天尽量不排下午1", "module": "scheduler/model/constraints/day_noon_dorm_duty_constraints.py", "category": "午查寝", "weights": ["day.noon_dorm_duty.w_noon_with_pm1"]},
    "noon_female_with_night_checkin": {"name": "女教师同日午查+晚查惩罚", "module": "scheduler/model/constraints/day_noon_dorm_duty_constraints.py", "category": "联动", "weights": ["day.noon_dorm_duty.w_female_noon_night_checkin"]},
    "soft_male_duty_balance": {"name": "男班主任午查+晚查均衡", "module": "scheduler/model/constraints/duty_joint_constraints.py", "category": "联动", "weights": ["day.duty_joint_constraints.w_soft_male_duty_balance"]},
    "duty_joint_male_total_target_over": {"name": "男班主任查寝次数超过目标", "module": "scheduler/model/constraints/duty_joint_constraints.py", "category": "联动", "weights": ["day.duty_joint_constraints.w_male_total_target_deviation"]},
    "duty_joint_male_total_target_under": {"name": "男班主任查寝次数低于目标", "module": "scheduler/model/constraints/duty_joint_constraints.py", "category": "联动", "weights": ["day.duty_joint_constraints.w_male_total_target_deviation"]},
    "grade_duty_no_night": {"name": "年级组值班当晚无晚自习惩罚", "module": "scheduler/model/constraints/grade_group_duty_constraints.py", "category": "联动", "weights": ["day.grade_group_duty.w_no_night_penalty"]},
    "grade_duty_fairness_balance": {"name": "年级组值班次数均衡惩罚", "module": "scheduler/model/constraints/grade_group_duty_constraints.py", "category": "联动", "weights": ["day.grade_group_duty.w_fairness_balance"]},
    "personalized_rule16_zfj_night_checkin_penalty": {"name": "指定教师：晚查寝惩罚", "module": "scheduler/model/constraints/personalized_constraints.py", "category": "个性化", "weights": ["personalized_constraints.w_zfj_night_checkin_penalty"]},
    "night_adjacent_days": {"name": "晚自习相邻天连续惩罚", "module": "scheduler/model/constraints/soft_objective.py", "category": "晚自习", "weights": ["soft.weights.adj_teacher"]},
    "night_sun_mon": {"name": "周日周一连续晚自习惩罚", "module": "scheduler/model/constraints/soft_objective.py", "category": "晚自习", "weights": ["soft.weights.sun_mon"]},
    "night_checkin_repeat_male": {"name": "男晚查寝重复惩罚", "module": "scheduler/model/constraints/soft_objective.py", "category": "晚查寝", "weights": ["soft.weights.checkin_repeat"]},
    "night_checkin_repeat_female": {"name": "女晚查寝重复惩罚", "module": "scheduler/model/constraints/soft_objective.py", "category": "晚查寝", "weights": ["soft.weights.checkin_repeat"]},
    "night_subject_sync": {"name": "同学科晚自习同节集中惩罚", "module": "scheduler/model/constraints/soft_objective.py", "category": "晚自习", "weights": ["evening_constraints.weights.subject_sync"]},
    "night_physics_fri": {"name": "物理周五晚自习惩罚", "module": "scheduler/model/constraints/soft_objective.py", "category": "晚自习", "weights": ["evening_constraints.weights.physics_fri_penalty"]},
    "night_history_fri": {"name": "历史周五晚自习惩罚", "module": "scheduler/model/constraints/soft_objective.py", "category": "晚自习", "weights": ["evening_constraints.weights.history_fri_penalty"]},
    "night_math_zeng_fri_p1": {"name": "指定教师周五数学P1惩罚", "module": "scheduler/model/constraints/soft_objective.py", "category": "晚自习", "weights": ["evening_constraints.weights.math_zeng_fri_p1_penalty"]},
    "night_math_zeng_fri_p2": {"name": "指定教师周五数学P2惩罚", "module": "scheduler/model/constraints/soft_objective.py", "category": "晚自习", "weights": ["evening_constraints.weights.math_zeng_fri_p2_penalty"]},
}

HARD_CONSTRAINT_CATALOG: List[Dict[str, str]] = [
    {"category": "联动", "name": "周日白天+周日晚自习与周一上午组合禁排", "module": "scheduler/model/constraints/day_night_bridge.py", "id": "hard_link_sun_night_mon_am", "desc": "禁止同一教师出现周日晚与次日早课冲突组合。"},
    {"category": "白天", "name": "班主任值班日需有PM1", "module": "scheduler/model/constraints/day_head_teacher_duty_constraints.py", "id": "hard_head_duty_pm1", "desc": "值班老师当天必须有下午1。"},
    {"category": "晚自习", "name": "物理周日晚自习禁排", "module": "scheduler/model/constraints/night_special.py", "id": "hard_physics_sunday", "desc": "物理教师周日晚自习禁排。"},
    {"category": "晚自习", "name": "历史周日晚自习禁排", "module": "scheduler/model/constraints/night_special.py", "id": "hard_history_sunday", "desc": "历史教师周日晚自习禁排。"},
    {"category": "晚自习", "name": "数学周日晚自习禁排", "module": "scheduler/model/constraints/night_special.py", "id": "hard_math_sunday", "desc": "数学教师周日晚自习禁排。"},
    {"category": "晚自习", "name": "数学周五仅指定教师可排", "module": "scheduler/model/constraints/night_special.py", "id": "hard_math_fri_non_zeng", "desc": "周五数学晚自习非指定教师教师禁排。"},
    {"category": "晚查寝", "name": "晚查寝男寝/女寝性别匹配", "module": "scheduler/model/constraints/checkin.py", "id": "checkin_gender_match_hard", "desc": "男教师仅男寝、女教师仅女寝（按配置例外名单除外）。"},
    {"category": "午查寝", "name": "中午查寝每天男女各1人", "module": "scheduler/model/constraints/day_noon_dorm_duty_constraints.py", "id": "noon_daily_need_gender_hard", "desc": "中午查寝每天男寝/女寝各安排1名教师。"},
    {"category": "联动", "name": "中午查寝与下午课前值班同日互斥", "module": "scheduler/model/constraints/duty_joint_constraints.py", "id": "duty_joint_noon_pm_mutex_hard", "desc": "同一教师同日不能同时中午查寝和下午课前值班。"},
]


def _register_rule_meta_from_catalogs() -> None:
    for rule_id, meta in SWITCHABLE_CONSTRAINT_CATALOG.items():
        ensure_rule_meta(
            str(rule_id),
            name_cn=str(meta.get("name", rule_id)),
            description=str(meta.get("name", rule_id)),
            config_keys=[
                str(meta.get("enable", "") or ""),
                str(meta.get("mode", "") or ""),
                *[str(x) for x in (meta.get("weights", []) or [])],
            ],
            default_weight="",
            mode="switchable",
            source_module=str(meta.get("module", "")),
        )
    for rule_id, meta in FIXED_SOFT_CONSTRAINT_CATALOG.items():
        ensure_rule_meta(
            str(rule_id),
            name_cn=str(meta.get("name", rule_id)),
            description=str(meta.get("name", rule_id)),
            config_keys=[str(x) for x in (meta.get("weights", []) or [])],
            default_weight="",
            mode="soft",
            source_module=str(meta.get("module", "")),
        )
    for meta in HARD_CONSTRAINT_CATALOG:
        rule_id = str(meta.get("id", "") or "").strip()
        if not rule_id:
            continue
        ensure_rule_meta(
            rule_id,
            name_cn=str(meta.get("name", rule_id)),
            description=str(meta.get("desc", meta.get("name", rule_id))),
            config_keys=(),
            default_weight="",
            mode="hard",
            source_module=str(meta.get("module", "")),
        )


_register_rule_meta_from_catalogs()


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _read_txt(path: Path) -> List[str]:
    try:
        return path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return []


def _extract_kv(lines: List[str]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for ln in lines:
        if "=" in ln:
            k, v = ln.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def _pick_latest_file(base_dir: Path, patterns: List[str]) -> Path | None:
    if not base_dir.exists():
        return None
    candidates: List[Path] = []
    for pat in patterns:
        candidates.extend(base_dir.glob(pat))
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def _parse_personalized_checklist(base_dir: Path) -> Dict[str, dict]:
    """
    解析个性化检查清单（已随求解输出）。
    返回：key -> {count, weight, penalty, note}
    """
    latest = _pick_latest_file(
        base_dir,
        [
            "个性化_检查*.txt",
            "*个性化*检查*.txt",
            "personalized_checklist*.txt",
            "*personalized*checklist*.txt",
            "诊断_personalized_checklist*.txt",
        ],
    )
    if latest is None:
        return {}

    result: Dict[str, dict] = {}
    zfy_pairs = ""
    for raw in _read_txt(latest):
        line = str(raw).strip()
        if not line or line.startswith("["):
            continue
        m = re.match(
            r"^(?P<key>[A-Za-z0-9_]+):\s*count=(?P<count>[-+]?\d+(?:\.\d+)?)\s+weight=(?P<weight>[^\s]+)\s+penalty=(?P<penalty>[-+]?\d+(?:\.\d+)?)",
            line,
        )
        if m:
            key = m.group("key")
            result[key] = {
                "count": float(m.group("count")),
                "weight": m.group("weight"),
                "penalty": float(m.group("penalty")),
                "note": "",
            }
            continue
        if line.startswith("rule18_zfy_consecutive_night_violated_pairs="):
            zfy_pairs = line.split("=", 1)[1].strip()

    if zfy_pairs and "rule18_zfy_consecutive_night" in result and zfy_pairs not in {"", "None"}:
        result["rule18_zfy_consecutive_night"]["note"] = f"连续违规对：{zfy_pairs}"
    return result


def _to_int_like(v: float) -> int | float:
    try:
        fv = float(v)
    except Exception:
        return v
    if abs(fv - round(fv)) < 1e-9:
        return int(round(fv))
    return fv


def _build_personalized_soft_diag_sheet(event_log: pd.DataFrame, diag_base: Path) -> pd.DataFrame:
    columns = ["约束编号", "约束名称", "约束类型", "是否满足", "未满足教师", "触发次数", "罚分权重", "实际罚分", "备注"]
    if event_log.empty:
        return pd.DataFrame(columns=columns)

    soft_events = event_log[
        (event_log["mode"] == "soft")
        & event_log["constraint_id"].astype(str).str.startswith("personalized_")
    ].copy()
    if soft_events.empty:
        return pd.DataFrame(columns=columns)

    checklist_rows = _parse_personalized_checklist(diag_base)
    checklist_weight_map: Dict[str, str] = {}
    for key, info in checklist_rows.items():
        checklist_weight_map[f"personalized_{key}"] = str(info.get("weight", "") or "")

    all_solution_ids = _order_solution_ids(event_log)
    registry_rule_ids = {
        meta.id
        for meta in all_rule_meta()
        if str(meta.id).startswith("personalized_")
    }
    rule_ids = sorted(registry_rule_ids | set(soft_events["constraint_id"].astype(str).tolist()))

    def _weight_text_for_rule(rule_id: str) -> str:
        w_txt = checklist_weight_map.get(rule_id, "").strip()
        if w_txt:
            return w_txt
        g = soft_events[soft_events["constraint_id"].astype(str) == str(rule_id)]
        if g.empty:
            return ""
        vals = sorted({int(round(float(v))) for v in g["unit_penalty"].astype(float).tolist() if float(v) > 0})
        if not vals:
            return ""
        return "/".join(str(v) for v in vals)

    def _rule_name(rule_id: str, sample_name: str = "") -> str:
        meta = get_rule_meta(str(rule_id))
        if meta is not None and str(meta.name_cn).strip():
            return str(meta.name_cn)
        key = str(rule_id).replace("personalized_", "", 1)
        return PERSONALIZED_RULE_NAME_CN.get(key, sample_name or str(rule_id))

    rows: List[dict] = []
    for sid in all_solution_ids:
        sid_events = soft_events[soft_events["solution_id"].astype(str) == str(sid)]
        for rule_id in rule_ids:
            g = sid_events[sid_events["constraint_id"].astype(str) == str(rule_id)]
            penalty = float(g["penalty"].sum()) if not g.empty else 0.0
            cnt = float(g["count_value"].sum()) if not g.empty else 0.0
            sample_name = str(g["constraint_name"].iloc[0]) if not g.empty else ""
            teachers = sorted(
                {
                    str(t).strip()
                    for t in (g["teacher_name"].astype(str).tolist() if not g.empty else [])
                    if str(t).strip() and str(t).strip() != "GLOBAL"
                }
            )
            satisfied = abs(penalty) < 1e-9
            key = str(rule_id).replace("personalized_", "", 1)
            unmet_teachers = ""
            if not satisfied:
                unmet_teachers = ",".join(teachers) if teachers else PERSONALIZED_RULE_TEACHERS.get(key, "全局")
                if not str(unmet_teachers).strip():
                    unmet_teachers = "全局"
            note = f"解ID={sid}"
            if key in checklist_rows and checklist_rows[key].get("note"):
                note = f"{note}；{checklist_rows[key]['note']}"
            rows.append(
                {
                    "约束编号": str(rule_id),
                    "约束名称": _rule_name(str(rule_id), sample_name),
                    "约束类型": "个性化-人情",
                    "是否满足": "满足" if satisfied else "未满足",
                    "未满足教师": unmet_teachers,
                    "触发次数": _to_int_like(cnt),
                    "罚分权重": _weight_text_for_rule(str(rule_id)),
                    "实际罚分": _to_int_like(penalty),
                    "备注": note,
                }
            )

    out = pd.DataFrame(rows, columns=columns)
    if not out.empty:
        out["__sid_order"] = out["备注"].astype(str).map(lambda s: all_solution_ids.index(s.split("解ID=", 1)[1].split("；", 1)[0]) if "解ID=" in s and s.split("解ID=", 1)[1].split("；", 1)[0] in all_solution_ids else 9999)
        out = out.sort_values(["__sid_order", "是否满足", "实际罚分"], ascending=[True, True, False]).drop(columns=["__sid_order"]).reset_index(drop=True)
    return out


def _is_dorm_soft_event(row: pd.Series) -> bool:
    if str(row.get("mode", "")) != "soft":
        return False
    if float(_to_num(row.get("penalty"), 0.0) or 0.0) <= 0:
        return False
    src = str(row.get("source_module", "") or "")
    text = " ".join(
        [
            str(row.get("constraint_id", "") or ""),
            str(row.get("constraint_name", "") or ""),
            str(row.get("description", "") or ""),
            str(row.get("period", "") or ""),
            src,
        ]
    )
    if "day_noon_dorm_duty_constraints.py" in src:
        return True
    if "checkin.py" in src:
        return True
    if "duty_joint_constraints.py" in src and ("午查" in text or "查寝" in text):
        return True
    key_tokens = ("查寝", "checkin", "noon_dorm", "午查", "晚查")
    return any(tok in text for tok in key_tokens)


def _infer_dorm_type(row: pd.Series) -> str:
    text = " ".join(
        [
            str(row.get("constraint_id", "") or ""),
            str(row.get("constraint_name", "") or ""),
            str(row.get("description", "") or ""),
            str(row.get("period", "") or ""),
        ]
    )
    if "中午查寝" in text or "noon" in text or "午查" in text:
        return "中午查寝"
    return "晚查寝"


def _build_dorm_soft_unmet_sheet(event_log: pd.DataFrame) -> pd.DataFrame:
    columns = ["序号", "查寝类型", "日期", "星期", "软约束名称", "涉及教师", "触发原因", "罚分权重", "实际罚分", "备注"]
    if event_log.empty:
        return pd.DataFrame(columns=columns)

    rows: List[dict] = []
    soft_events = event_log[event_log.apply(_is_dorm_soft_event, axis=1)].copy()
    if soft_events.empty:
        return pd.DataFrame(columns=columns)

    solution_order = _order_solution_ids(event_log)

    def _day_ord(v: object) -> int:
        s = str(v or "")
        return WEEKDAY_ORDER.get(s, 99)

    def _sid_ord(v: object) -> int:
        s = str(v or "")
        return solution_order.index(s) if s in solution_order else 9999

    soft_events = soft_events.sort_values(
        by=["solution_id", "day", "penalty"],
        key=lambda col: col.map(_sid_ord) if col.name == "solution_id" else (col.map(_day_ord) if col.name == "day" else col),
        ascending=[True, True, False],
    )

    seq = 1
    for _, r in soft_events.iterrows():
        teacher = str(r.get("teacher_name", "") or "").strip()
        if not teacher or teacher == "GLOBAL":
            continue
        day = str(r.get("day", "") or "").strip()
        c_id = str(r.get("constraint_id", "") or "")
        c_name = str(r.get("constraint_name", "") or "").strip() or DORM_RULE_NAME_FALLBACK.get(c_id, c_id)
        c_name = DORM_RULE_NAME_FALLBACK.get(c_id, c_name)
        note = ""
        if "中午查寝+晚查寝" in str(r.get("period", "") or ""):
            note = "同日中午+晚查寝联动"
        if not day:
            note = (note + "；" if note else "") + "周汇总项，无具体日期"
        sid = str(r.get("solution_id", "") or "").strip()
        if sid:
            note = (note + "；" if note else "") + f"解ID={sid}"
        rows.append(
            {
                "序号": seq,
                "查寝类型": _infer_dorm_type(r),
                "日期": day,
                "星期": day,
                "软约束名称": c_name,
                "涉及教师": teacher,
                "触发原因": str(r.get("description", "") or c_name),
                "罚分权重": _to_int_like(float(_to_num(r.get("unit_penalty"), 0.0) or 0.0)),
                "实际罚分": _to_int_like(float(_to_num(r.get("penalty"), 0.0) or 0.0)),
                "备注": note,
            }
        )
        seq += 1

    return pd.DataFrame(rows, columns=columns)


def _to_num(v: object, default: float | None = 0.0) -> float | None:
    try:
        if v is None:
            return default
        return float(v)
    except Exception:
        return default


def _read_event_log(path: Path, solution_id: str, snapshot_id: str) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=EVENT_COLUMNS)
    try:
        df = pd.read_csv(path, encoding="utf-8-sig")
    except Exception:
        return pd.DataFrame(columns=EVENT_COLUMNS)

    for col in EVENT_COLUMNS:
        if col not in df.columns:
            df[col] = 0.0 if col in {"penalty", "unit_penalty", "count_value"} else ""
    for col in ("penalty", "unit_penalty", "count_value"):
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
    for col in EVENT_COLUMNS:
        if col not in ("penalty", "unit_penalty", "count_value"):
            df[col] = df[col].fillna("").astype(str)

    # 历史快照里若存在“规则名称乱码/占位问号”，按 rule_id 做无语义修复映射。
    if "constraint_id" in df.columns and "constraint_name" in df.columns:
        repaired_names: List[str] = []
        for rid, rname in zip(df["constraint_id"], df["constraint_name"]):
            rid_s = str(rid or "")
            rname_s = str(rname or "")
            if rid_s in RULE_NAME_FALLBACK_CN and (not rname_s.strip() or "?" in rname_s):
                repaired_names.append(RULE_NAME_FALLBACK_CN[rid_s])
            else:
                repaired_names.append(rname_s)
        df["constraint_name"] = repaired_names

    if (df["solution_id"] == "").all():
        df["solution_id"] = solution_id
    if (df["snapshot_id"] == "").all():
        df["snapshot_id"] = snapshot_id
    return df[EVENT_COLUMNS]


def _hard_event(
    *,
    solution_id: str,
    snapshot_id: str,
    constraint_id: str,
    constraint_name: str,
    count_value: int,
    description: str,
    source_module: str,
) -> dict:
    return {
        "solution_id": solution_id,
        "snapshot_id": snapshot_id,
        "constraint_id": constraint_id,
        "constraint_name": constraint_name,
        "constraint_category": "ban",
        "mode": "hard",
        "teacher_name": "GLOBAL",
        "day": "",
        "period": "",
        "class_name": "",
        "subject": "",
        "penalty": 0.0,
        "unit_penalty": 0.0,
        "count_value": float(count_value),
        "rule_params": "",
        "source_module": source_module,
        "description": description,
    }


def _collect_hard_events(solution_id: str, snapshot_id: str, base_dir: Path) -> List[dict]:
    out: List[dict] = []

    link_kv = _extract_kv(_read_txt(base_dir / "day_night_link_checklist.txt"))
    hard2 = int(_to_num(link_kv.get("Hard2Violations"), 0) or 0)
    if hard2 > 0:
        out.append(
            _hard_event(
                solution_id=solution_id,
                snapshot_id=snapshot_id,
                constraint_id="hard_link_sun_night_mon_am",
                constraint_name="联动硬约束#2",
                count_value=hard2,
                description="周日下午+周日晚自习+周一上午1/2 禁止组合",
                source_module="scheduler/model/constraints/day_night_bridge.py",
            )
        )

    duty_kv = _extract_kv(_read_txt(base_dir / "head_duty_hard_check.txt"))
    duty_viol = int(_to_num(duty_kv.get("DutyButNotPM1Violations"), 0) or 0)
    if duty_viol > 0:
        out.append(
            _hard_event(
                solution_id=solution_id,
                snapshot_id=snapshot_id,
                constraint_id="hard_head_duty_pm1",
                constraint_name="值班必须有PM1",
                count_value=duty_viol,
                description="班主任值班当天必须有PM1课",
                source_module="scheduler/model/constraints/day_head_teacher_duty_constraints.py",
            )
        )

    night_kv = _extract_kv(_read_txt(base_dir / "night_constraint_checklist.txt"))
    mapping = [
        ("PhysicsSundayCount", "hard_physics_sunday", "物理周日晚自习禁排"),
        ("HistorySundayCount", "hard_history_sunday", "历史周日晚自习禁排"),
        ("MathSundayCount", "hard_math_sunday", "数学周日晚自习禁排"),
        ("MathFridayNonZengCount", "hard_math_fri_non_zeng", "数学周五仅指定教师可排"),
    ]
    for key, cid, cname in mapping:
        cnt = int(_to_num(night_kv.get(key), 0) or 0)
        if cnt > 0:
            out.append(
                _hard_event(
                    solution_id=solution_id,
                    snapshot_id=snapshot_id,
                    constraint_id=cid,
                    constraint_name=cname,
                    count_value=cnt,
                    description=f"{cname}出现{cnt}次",
                    source_module="scheduler/model/constraints/night_special.py",
                )
            )
    return out


def _load_solver_meta(solution_id: str, snapshot_id: str, base_dir: Path, default_status: str = "") -> dict:
    if snapshot_id != "最终解":
        meta = _read_json(base_dir / "snapshot_meta.json")
        return {
            "solution_id": solution_id,
            "snapshot_id": snapshot_id,
            "solver_status": str(meta.get("status", default_status)),
            "objective_value": _to_num(meta.get("objective_value"), None),
            "best_bound": _to_num(meta.get("best_bound"), None),
            "time_limit": _to_num(meta.get("time_limit"), None),
            "num_conflicts": int(_to_num(meta.get("conflicts"), 0) or 0),
            "num_branches": int(_to_num(meta.get("branches"), 0) or 0),
            "elapsed_sec": _to_num(meta.get("elapsed_sec"), None),
            "solution_index": int(_to_num(meta.get("solution_count"), 0) or 0),
            "is_best_solution": False,
        }

    meta = _read_json(base_dir / "final_solver_overview.json")
    if not meta:
        meta = _read_json(base_dir / "meta" / "final_solver_overview.json")
    return {
        "solution_id": str(meta.get("solution_id", solution_id)),
        "snapshot_id": "最终解",
        "solver_status": str(meta.get("solver_status", default_status)),
        "objective_value": _to_num(meta.get("objective_value"), None),
        "best_bound": _to_num(meta.get("best_bound"), None),
        "time_limit": _to_num(meta.get("time_limit"), None),
        "num_conflicts": int(_to_num(meta.get("num_conflicts"), 0) or 0),
        "num_branches": int(_to_num(meta.get("num_branches"), 0) or 0),
        "elapsed_sec": _to_num(meta.get("wall_time"), None),
        "solution_index": int(_to_num(meta.get("solution_index"), 0) or 0),
        "is_best_solution": bool(meta.get("is_best_solution", True)),
    }


def _order_solution_ids(event_log: pd.DataFrame) -> List[str]:
    if event_log.empty:
        return []
    # 保持出现顺序
    seen: set[str] = set()
    order: List[str] = []
    for sid in event_log["solution_id"].astype(str).tolist():
        if sid not in seen:
            seen.add(sid)
            order.append(sid)
    return order


def _first_event_rows(event_log: pd.DataFrame) -> tuple[dict, dict, dict]:
    """返回 rule、teacher、(solution,rule) 到 event_log 行号的映射。"""
    first_by_rule: dict[str, int] = {}
    first_by_teacher: dict[str, int] = {}
    first_by_solution_rule: dict[Tuple[str, str], int] = {}
    for idx, row in event_log.reset_index(drop=True).iterrows():
        excel_row = idx + 2
        rid = str(row["constraint_id"])
        tch = str(row["teacher_name"])
        sid = str(row["solution_id"])
        if rid and rid not in first_by_rule:
            first_by_rule[rid] = excel_row
        if tch and tch not in first_by_teacher:
            first_by_teacher[tch] = excel_row
        key = (sid, rid)
        if rid and key not in first_by_solution_rule:
            first_by_solution_rule[key] = excel_row
    return first_by_rule, first_by_teacher, first_by_solution_rule


def _format_teacher_list(teacher_penalty: pd.Series, total_penalty: float) -> tuple[str, str, int]:
    """生成高罚分老师名单与全量名单字符串。"""
    if teacher_penalty.empty:
        return "", "", 0

    teacher_penalty = teacher_penalty.sort_values(ascending=False)
    all_names = [f"{name}({val:.0f})" for name, val in teacher_penalty.items()]

    threshold = max(ABS_THRESHOLD, float(total_penalty) * RATIO_THRESHOLD)
    topk_names = set(teacher_penalty.head(TOPK_HIGH_PENALTY_TEACHERS).index.tolist())
    threshold_names = set(teacher_penalty[teacher_penalty >= threshold].index.tolist())
    selected = topk_names | threshold_names

    selected_pairs = [(name, teacher_penalty[name]) for name in teacher_penalty.index if name in selected]
    selected_fmt = [f"{name}({val:.0f})" for name, val in selected_pairs]
    if len(selected_fmt) > MAX_NAMES:
        hidden = len(selected_fmt) - MAX_NAMES
        selected_fmt = selected_fmt[:MAX_NAMES] + [f"...(+{hidden})"]

    all_fmt = all_names
    if len(all_fmt) > MAX_NAMES:
        hidden = len(all_fmt) - MAX_NAMES
        all_fmt = all_fmt[:MAX_NAMES] + [f"...(+{hidden})"]

    return ", ".join(selected_fmt), ", ".join(all_fmt), int(len(teacher_penalty))


def _build_soft_constraint_teacher_list(event_log: pd.DataFrame, first_by_solution_rule: dict) -> pd.DataFrame:
    """构建 Sheet1：solution × constraint 的软约束老师名单摘要。"""
    soft_events = event_log[(event_log["mode"] == "soft") & (event_log["penalty"] > 0)].copy()
    if soft_events.empty:
        return pd.DataFrame(
            columns=[
                "solution_id",
                "constraint_id",
                "constraint_name",
                "total_penalty",
                "affected_teacher_count",
                "teacher_list_high_penalty",
                "teacher_list_all",
                "link_to_event_log",
            ]
        )

    rows = []
    grouped = soft_events.groupby(["solution_id", "constraint_id"], dropna=False)
    for (solution_id, constraint_id), g in grouped:
        solution_id = str(solution_id)
        constraint_id = str(constraint_id)
        total_penalty = float(g["penalty"].sum())
        teachers = g[
            (g["teacher_name"].astype(str) != "")
            & (g["teacher_name"].astype(str) != "GLOBAL")
        ]
        teacher_penalty = (
            teachers.groupby("teacher_name", dropna=False)["penalty"].sum().sort_values(ascending=False)
            if not teachers.empty
            else pd.Series(dtype=float)
        )
        high_list, all_list, affected_count = _format_teacher_list(teacher_penalty, total_penalty)
        link_row = first_by_solution_rule.get((solution_id, constraint_id), 2)
        rows.append(
            {
                "solution_id": solution_id,
                "constraint_id": constraint_id,
                "constraint_name": _friendly_constraint_name(
                    constraint_id,
                    str(g["constraint_name"].iloc[0]),
                ),
                "total_penalty": total_penalty,
                "affected_teacher_count": affected_count,
                "teacher_list_high_penalty": high_list,
                "teacher_list_all": all_list,
                "link_to_event_log": f"=HYPERLINK(\"#'{SHEET_EVENT_LOG}'!A{link_row}\",\"查看事件\")",
            }
        )

    out = pd.DataFrame(rows)
    out = out.sort_values(["solution_id", "total_penalty"], ascending=[True, False]).reset_index(drop=True)
    return out


def _build_solution_soft_topn(soft_teacher_list: pd.DataFrame) -> pd.DataFrame:
    """构建 Sheet2：按 solution 分块的 TopN 软约束。"""
    columns = [
        "solution_id",
        "rank_in_solution",
        "constraint_id",
        "constraint_name",
        "category",
        "total_penalty",
        "affected_teacher_count",
        "teacher_list_high_penalty",
        "link_to_event_log",
    ]
    if soft_teacher_list.empty:
        return pd.DataFrame(columns=columns)

    # category 先置空，后面由 constraint_id 映射填充
    rows: List[dict] = []
    for solution_id, g in soft_teacher_list.groupby("solution_id", sort=False):
        # 严格口径：仅按 total_penalty 降序取 TopN，不按 affected_teacher_count 二次筛选
        g = g[g["total_penalty"] > 0].sort_values("total_penalty", ascending=False).head(TOPN_SOFT_PER_SOLUTION)
        if g.empty:
            continue
        # solution 标题行
        rows.append(
            {
                "solution_id": solution_id,
                "rank_in_solution": "",
                "constraint_id": "",
                "constraint_name": f"=== {solution_id} ===",
                "category": "",
                "total_penalty": "",
                "affected_teacher_count": "",
                "teacher_list_high_penalty": "",
                "link_to_event_log": "",
            }
        )
        for idx, (_, row) in enumerate(g.iterrows(), start=1):
            rows.append(
                {
                    "solution_id": solution_id,
                    "rank_in_solution": idx,
                    "constraint_id": row["constraint_id"],
                    "constraint_name": row["constraint_name"],
                    "category": "",
                    "total_penalty": row["total_penalty"],
                    "affected_teacher_count": row["affected_teacher_count"],
                    "teacher_list_high_penalty": row["teacher_list_high_penalty"],
                    "link_to_event_log": row["link_to_event_log"],
                }
            )
        # solution 间空行
        rows.append({k: "" for k in columns})

    return pd.DataFrame(rows, columns=columns)


def _build_solution_topn_teachers(event_log: pd.DataFrame) -> pd.DataFrame:
    """按解统计教师总罚分 TopN，并展示每位教师的主要罚分来源。"""
    columns = [
        "解ID(solution_id)",
        "解内排名",
        "教师姓名",
        "教师总罚分",
        "主要罚分项目(Top1)",
        "Top1罚分",
        "主要罚分项目(Top3)",
        "跳转事件",
    ]

    soft_events = event_log[
        (event_log["mode"] == "soft")
        & (event_log["penalty"] > 0)
        & (event_log["teacher_name"].astype(str) != "")
        & (event_log["teacher_name"].astype(str) != "GLOBAL")
    ].copy()
    # 仅过滤展示层两个指定规则，避免主视图噪声过大。
    soft_events = soft_events[
        ~soft_events["constraint_id"].astype(str).isin(EXCLUDED_RULE_IDS_TOPN_TEACHERS)
    ]
    if soft_events.empty:
        return pd.DataFrame(columns=columns)

    soft_events = soft_events.reset_index(drop=True)
    soft_events["_excel_row"] = soft_events.index + 2

    rows: List[dict] = []
    for sid, g_sol in soft_events.groupby("solution_id", sort=False):
        teacher_total = (
            g_sol.groupby("teacher_name", dropna=False)["penalty"]
            .sum()
            .sort_values(ascending=False)
            .head(TOPN_TEACHERS_PER_SOLUTION)
        )
        if teacher_total.empty:
            continue

        for rank, (teacher, total_penalty) in enumerate(teacher_total.items(), start=1):
            g_t = g_sol[g_sol["teacher_name"] == teacher]
            g_t = g_t.copy()
            def _rule_display(rid: str, rname: str) -> str:
                return _friendly_constraint_name(rid, rname)

            g_t["_rule_display"] = [
                _rule_display(rid, rname)
                for rid, rname in zip(g_t["constraint_id"], g_t["constraint_name"])
            ]
            by_rule = (
                g_t.groupby("_rule_display", dropna=False)["penalty"]
                .sum()
                .sort_values(ascending=False)
            )
            top1_rule = str(by_rule.index[0]) if len(by_rule) > 0 else ""
            top1_pen = float(by_rule.iloc[0]) if len(by_rule) > 0 else 0.0
            top3_detail = "；".join([f"{k}({v:.0f})" for k, v in by_rule.head(3).items()])
            first_row = int(g_t["_excel_row"].min()) if len(g_t) > 0 else 2
            rows.append(
                {
                    "解ID(solution_id)": str(sid),
                    "解内排名": rank,
                    "教师姓名": str(teacher),
                    "教师总罚分": float(total_penalty),
                    "主要罚分项目(Top1)": top1_rule,
                    "Top1罚分": top1_pen,
                    "主要罚分项目(Top3)": top3_detail,
                    "跳转事件": f'=HYPERLINK("#\'{SHEET_EVENT_LOG}\'!A{first_row}","查看事件")',
                }
            )

    return pd.DataFrame(rows, columns=columns)
def _add_block_outer_borders(ws) -> None:
    """
    为“每解TopN罚分老师”按 solution_id 连续块添加黑色略粗外框。
    """
    if ws.max_row < 2 or ws.max_column < 1:
        return

    solution_col = 1  # A列：解ID(solution_id)
    first_col = 1
    last_col = ws.max_column
    medium_side = Side(style="medium", color="000000")

    def apply_block(r1: int, r2: int) -> None:
        if r1 > r2:
            return
        for r in range(r1, r2 + 1):
            for c in range(first_col, last_col + 1):
                cell = ws.cell(row=r, column=c)
                left = medium_side if c == first_col else cell.border.left
                right = medium_side if c == last_col else cell.border.right
                top = medium_side if r == r1 else cell.border.top
                bottom = medium_side if r == r2 else cell.border.bottom
                cell.border = Border(left=left, right=right, top=top, bottom=bottom)

    block_start = 2
    current_sid = str(ws.cell(row=2, column=solution_col).value or "")
    for r in range(3, ws.max_row + 1):
        sid = str(ws.cell(row=r, column=solution_col).value or "")
        if sid != current_sid:
            apply_block(block_start, r - 1)
            block_start = r
            current_sid = sid
    apply_block(block_start, ws.max_row)


def _build_dashboard_sheet(
    top_constraints: pd.DataFrame,
    top_teachers: pd.DataFrame,
    time_bottleneck: pd.DataFrame,
    category_share: pd.DataFrame,
) -> pd.DataFrame:
    """
    组装 dashboard 单表。

    注意：为避免同一个 ExcelWriter 里重复写同名 sheet，这里先把四个分区拼成一个 DataFrame，
    后续只调用一次 to_excel(sheet_name="dashboard")。
    """
    rows: List[dict] = []
    cols = ["分组", "名称", "数值1", "数值2"]

    def _push_section(title: str, df: pd.DataFrame, name_col: str, v1_col: str, v2_col: str | None) -> None:
        rows.append({"分组": title, "名称": "（标题）", "数值1": "", "数值2": ""})
        if df.empty:
            rows.append({"分组": title, "名称": "（无数据）", "数值1": "", "数值2": ""})
        else:
            for _, r in df.iterrows():
                row = {
                    "分组": title,
                    "名称": str(r.get(name_col, "")),
                    "数值1": r.get(v1_col, ""),
                    "数值2": r.get(v2_col, "") if v2_col else "",
                }
                rows.append(row)
        rows.append({c: "" for c in cols})

    _push_section("Top 10 软约束（按罚分）", top_constraints, "constraint_name", "total_penalty", "affected_teacher_count")
    _push_section("Top 20 教师（按罚分）", top_teachers, "teacher_name", "total_penalty", "hard_violation_count")

    if not time_bottleneck.empty:
        tb = time_bottleneck.copy()
        tb["name"] = tb["day"].astype(str) + " " + tb["period"].astype(str)
    else:
        tb = pd.DataFrame(columns=["name", "penalty"])
    _push_section("Top 时间瓶颈（星期+节次）", tb, "name", "penalty", None)
    _push_section("按类别罚分占比", category_share, "constraint_category", "penalty", None)

    return pd.DataFrame(rows, columns=cols)


def _to_cn_mode(v: object) -> str:
    s = str(v)
    return MODE_CN.get(s, s)


def _to_cn_category(v: object) -> str:
    s = str(v)
    return CATEGORY_CN.get(s, s)


def _switch_meta_for_constraint(constraint_id: str, constraint_name: str = "") -> Dict[str, Any] | None:
    cid = str(constraint_id or "").strip()
    if not cid:
        return None
    if cid in SWITCHABLE_CONSTRAINT_CATALOG:
        return SWITCHABLE_CONSTRAINT_CATALOG[cid]
    if cid.startswith("personalized_"):
        key = cid.replace("personalized_", "", 1)
        cfg = PERSONALIZED_CFG_META.get(key)
        if cfg:
            return {
                "name": PERSONALIZED_RULE_NAME_CN.get(key, constraint_name or cid),
                "module": "scheduler/model/constraints/personalized_constraints.py",
                "category": "个性化",
                "enable": cfg.get("enable", ""),
                "mode": cfg.get("mode", ""),
                "weights": cfg.get("weights", []),
            }
    return None


def _constraint_penalty_for_solution(event_log: pd.DataFrame, solution_id: str, constraint_id: str) -> float:
    if event_log.empty or not solution_id:
        return 0.0
    m = (
        (event_log["solution_id"].astype(str) == str(solution_id))
        & (event_log["constraint_id"].astype(str) == str(constraint_id))
        & (event_log["mode"].astype(str) == "soft")
    )
    if not m.any():
        return 0.0
    return float(pd.to_numeric(event_log.loc[m, "penalty"], errors="coerce").fillna(0.0).sum())


def _hard_constraint_remark(constraint_id: str, io_cfg: dict, rules_cfg: dict) -> str:
    cid = str(constraint_id or "").strip()
    if cid == "hard_physics_sunday":
        return "例外：指定教师（周日物理禁排不作用于指定教师）。"
    if cid == "hard_math_fri_non_zeng":
        return "唯一例外：指定教师可排周五数学晚自习。"
    if cid == "checkin_gender_match_hard":
        extra = _cfg_resolve(io_cfg, rules_cfg, "checkin.exclude_heads", [])
        if extra:
            names = "、".join(str(x) for x in extra if str(x).strip())
            return f"晚查寝排除名单：{names}"
        return "—"
    if cid == "noon_daily_need_gender_hard":
        return "周六女寝置空（不安排女寝中午查寝）。"
    if cid == "hard_history_sunday":
        return "—"
    if cid == "hard_head_duty_pm1":
        return "—"
    if cid == "hard_link_sun_night_mon_am":
        return "可临时将 day_night_link.sun_pm_night_no_mon_am_mode 改为 soft 试跑。"
    return "—"


def _build_hard_constraint_detail_sheet(event_log: pd.DataFrame, io_cfg: dict, rules_cfg: dict) -> pd.DataFrame:
    columns = ["分类", "约束名称", "Python模块路径", "英文 ID（如函数名或weight_key）", "中文功能解释", "备注"]
    rows: List[dict] = []

    switchable_ids = set(SWITCHABLE_CONSTRAINT_CATALOG.keys())
    for key in PERSONALIZED_CFG_META.keys():
        switchable_ids.add(f"personalized_{key}")

    for item in HARD_CONSTRAINT_CATALOG:
        cid = str(item.get("id", "") or "")
        rows.append(
            {
                "分类": item.get("category", "其他"),
                "约束名称": item.get("name", ""),
                "Python模块路径": item.get("module", ""),
                "英文 ID（如函数名或weight_key）": cid,
                "中文功能解释": item.get("desc", ""),
                "备注": _hard_constraint_remark(cid, io_cfg, rules_cfg),
            }
        )

    if not event_log.empty:
        hard_df = event_log[event_log["mode"].astype(str) == "hard"].copy()
        if not hard_df.empty:
            hard_df = hard_df.sort_values(["constraint_id", "constraint_name"])
            for cid, g in hard_df.groupby("constraint_id", dropna=False):
                cid_s = str(cid or "").strip()
                if not cid_s:
                    continue
                if cid_s in switchable_ids:
                    continue
                sample = g.iloc[0]
                rows.append(
                    {
                        "分类": _detail_category(str(sample.get("source_module", "")), cid_s),
                        "约束名称": str(sample.get("constraint_name", "") or cid_s),
                        "Python模块路径": str(sample.get("source_module", "") or ""),
                        "英文 ID（如函数名或weight_key）": cid_s,
                        "中文功能解释": str(sample.get("description", "") or str(sample.get("constraint_name", "") or cid_s)),
                        "备注": _hard_constraint_remark(cid_s, io_cfg, rules_cfg),
                    }
                )

    out = pd.DataFrame(rows, columns=columns)
    if out.empty:
        return out
    out = out.drop_duplicates(subset=["英文 ID（如函数名或weight_key）"], keep="first")
    out["__k"] = out.apply(lambda r: _detail_sort_key(r.get("分类", "其他"), r.get("约束名称", "")), axis=1)
    out = out.sort_values("__k").drop(columns="__k").reset_index(drop=True)
    return out


def _build_soft_constraint_detail_sheet(event_log: pd.DataFrame, io_cfg: dict, rules_cfg: dict) -> pd.DataFrame:
    columns = ["分类", "约束名称", "是否支持软硬切换", "当前状态", "YAML配置字段", "当前权重", "本解中罚分", "中文功能解释"]
    if event_log.empty and not SWITCHABLE_CONSTRAINT_CATALOG:
        return pd.DataFrame(columns=columns)

    current_solution_id = _pick_current_solution_id(event_log)
    candidate_ids: set[str] = set()
    if not event_log.empty:
        candidate_ids |= set(event_log[event_log["mode"].astype(str) == "soft"]["constraint_id"].astype(str).tolist())
        candidate_ids |= set(event_log[event_log["constraint_id"].astype(str).str.startswith("personalized_")]["constraint_id"].astype(str).tolist())
    candidate_ids |= set(SWITCHABLE_CONSTRAINT_CATALOG.keys())
    candidate_ids |= set(FIXED_SOFT_CONSTRAINT_CATALOG.keys())
    candidate_ids |= {f"personalized_{k}" for k in PERSONALIZED_CFG_META.keys()}

    rows: List[dict] = []
    for cid in sorted({c for c in candidate_ids if str(c).strip()}):
        sample_name = ""
        sample_module = ""
        sample_desc = ""
        sample_category = "其他"
        sample_weight = ""
        if not event_log.empty:
            g_all = event_log[event_log["constraint_id"].astype(str) == str(cid)]
            if not g_all.empty:
                s = g_all.iloc[0]
                sample_name = _friendly_constraint_name(
                    str(s.get("constraint_id", "") or cid),
                    str(s.get("constraint_name", "") or ""),
                )
                sample_module = str(s.get("source_module", "") or "")
                sample_desc = _friendly_constraint_desc(
                    str(s.get("constraint_id", "") or cid),
                    str(s.get("constraint_name", "") or ""),
                    str(s.get("description", "") or ""),
                )
                sample_category = _detail_category(sample_module, cid)
                unit_vals = pd.to_numeric(g_all.get("unit_penalty", pd.Series(dtype=float)), errors="coerce").fillna(0.0)
                unit_vals = sorted({float(v) for v in unit_vals.tolist() if float(v) > 0})
                if unit_vals:
                    sample_weight = "/".join(_fmt_weight(v) for v in unit_vals)

        meta = _switch_meta_for_constraint(cid, sample_name)
        if meta:
            support_switch = "是"
            enable_path = str(meta.get("enable", "") or "")
            mode_path = str(meta.get("mode", "") or "")
            weight_paths = [str(x) for x in (meta.get("weights", []) or []) if str(x)]
            enabled = True
            if enable_path:
                enabled = bool(_cfg_resolve(io_cfg, rules_cfg, enable_path, True))
            mode_now = str(_cfg_resolve(io_cfg, rules_cfg, mode_path, "soft") or "soft").strip().lower()
            if mode_now not in {"soft", "hard"}:
                mode_now = "soft"
            status = "disabled" if not enabled else mode_now
            yaml_fields = _fmt_yaml_fields(([enable_path] if enable_path else []) + ([mode_path] if mode_path else []) + weight_paths, io_cfg, rules_cfg)
            weight_show = ""
            vals: List[str] = []
            for wp in weight_paths:
                val = _cfg_resolve(io_cfg, rules_cfg, wp, None)
                if val is not None:
                    vals.append(_fmt_weight(val))
            if vals:
                weight_show = "/".join(vals)
            elif sample_weight:
                weight_show = sample_weight
            else:
                weight_show = "0"
            category = str(meta.get("category") or sample_category)
            name = str(meta.get("name") or sample_name or cid)
            module = str(meta.get("module") or sample_module)
            explain = _friendly_constraint_desc(cid, name, sample_desc or name)
        else:
            support_switch = "否"
            status = "soft"
            fixed_meta = FIXED_SOFT_CONSTRAINT_CATALOG.get(cid, {})
            weight_paths = [str(x) for x in (fixed_meta.get("weights", []) or []) if str(x)]
            yaml_fields = _fmt_yaml_fields(weight_paths, io_cfg, rules_cfg) if weight_paths else "（默认）"
            if weight_paths:
                vals: List[str] = []
                for wp in weight_paths:
                    v = _cfg_resolve(io_cfg, rules_cfg, wp, None)
                    if v is not None:
                        vals.append(_fmt_weight(v))
                weight_show = "/".join(vals) if vals else (sample_weight or "0")
            else:
                weight_show = sample_weight or "0"
            category = str(fixed_meta.get("category") or sample_category)
            name = str(fixed_meta.get("name") or sample_name or cid)
            module = str(fixed_meta.get("module") or sample_module)
            explain = _friendly_constraint_desc(cid, name, sample_desc or name)

        penalty_now = _constraint_penalty_for_solution(event_log, current_solution_id, cid)
        rows.append(
            {
                "分类": category,
                "约束名称": name,
                "是否支持软硬切换": support_switch,
                "当前状态": status,
                "YAML配置字段": yaml_fields,
                "当前权重": weight_show,
                "本解中罚分": _to_int_like(penalty_now),
                "中文功能解释": explain,
                "__module": module,
            }
        )

    out = pd.DataFrame(rows, columns=columns + ["__module"])
    if out.empty:
        return out
    out["__cat"] = out["分类"].astype(str).map(lambda x: DETAIL_CATEGORY_ORDER.get(x, 999))
    out["__pen"] = pd.to_numeric(out["本解中罚分"], errors="coerce").fillna(0.0)
    out["__name"] = out["约束名称"].astype(str)
    out = out.sort_values(["__cat", "__pen", "__name"], ascending=[True, False, True]).drop(columns=["__module", "__cat", "__pen", "__name"])
    return out.reset_index(drop=True)


def _cnize_event_log(event_log: pd.DataFrame) -> pd.DataFrame:
    df = event_log.copy()
    df["mode"] = df["mode"].map(_to_cn_mode)
    df["constraint_category"] = df["constraint_category"].map(_to_cn_category)
    df["is_global_event"] = df["teacher_name"].astype(str).map(lambda x: "是" if x == "GLOBAL" else "否")
    return df.rename(
        columns={
            "solution_id": "解ID(solution_id)",
            "snapshot_id": "快照ID(snapshot_id)",
            "constraint_id": "规则ID(constraint_id)",
            "constraint_name": "规则名称",
            "constraint_category": "规则类别",
            "mode": "模式",
            "teacher_name": "教师姓名",
            "is_global_event": "是否全局事件",
            "day": "星期",
            "period": "节次",
            "class_name": "班级",
            "subject": "学科",
            "penalty": "罚分",
            "unit_penalty": "单次罚分",
            "count_value": "触发次数",
            "rule_params": "参数",
            "source_module": "来源模块",
            "description": "说明",
        }
    )


def _cnize_soft_summary(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if "category" in out.columns:
        out["category"] = out["category"].map(_to_cn_category)
    return out.rename(
        columns={
            "constraint_id": "规则ID(constraint_id)",
            "constraint_name": "规则名称",
            "category": "类别",
            "unit_penalty": "单次罚分",
            "total_trigger_count": "总触发次数",
            "total_penalty": "总罚分",
            "affected_teacher_count": "涉及教师数",
            "trigger_granularity": "触发粒度",
            "parameters": "参数",
            "enabled": "是否启用",
            "source_module": "来源模块",
            "explain_text": "规则说明",
            "link_to_event_log": "跳转事件",
        }
    )


def _cnize_teacher_summary(df: pd.DataFrame) -> pd.DataFrame:
    return df.rename(
        columns={
            "teacher_name": "教师姓名",
            "total_penalty": "总罚分",
            "soft_penalty": "软约束罚分",
            "hard_violation_count": "硬约束违规次数",
            "top_3_constraints": "Top3规则来源",
            "top_3_penalty_sources": "Top3时间来源",
            "link_to_event_log": "跳转事件",
        }
    )


def _cnize_solver_overview(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if "solver_status" in out.columns:
        out["solver_status"] = out["solver_status"].replace(
            {"OPTIMAL": "最优", "FEASIBLE": "可行", "INFEASIBLE": "不可行", "UNKNOWN": "未知", "MODEL_INVALID": "模型无效"}
        )
    return out.rename(
        columns={
            "solution_id": "解ID(solution_id)",
            "snapshot_id": "快照ID(snapshot_id)",
            "solver_status": "求解状态",
            "objective_value": "目标值",
            "best_bound": "最优界",
            "gap_percent": "最优差距(%)",
            "time_limit": "时间上限(秒)",
            "num_conflicts": "冲突数",
            "num_branches": "分支数",
            "elapsed_sec": "已用时(秒)",
            "solution_index": "解序号",
            "is_best_solution": "是否最优快照",
            "hard_violation_count": "硬约束违规次数",
            "soft_total_penalty": "软约束总罚分",
        }
    )


def _cnize_rule_config(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if "category" in out.columns:
        out["category"] = out["category"].map(_to_cn_category)
    if "mode" in out.columns:
        out["mode"] = out["mode"].map(_to_cn_mode)
    return out.rename(
        columns={
            "constraint_id": "规则ID(constraint_id)",
            "constraint_name": "规则名称",
            "category": "类别",
            "mode": "模式",
            "unit_penalty": "单次罚分",
            "parameters": "参数",
            "enabled": "是否启用",
            "source_module": "来源模块",
            "explain_text": "规则说明",
            "link_to_event_log": "跳转事件",
        }
    )


def _cnize_soft_teacher_list(df: pd.DataFrame) -> pd.DataFrame:
    return df.rename(
        columns={
            "solution_id": "解ID(solution_id)",
            "constraint_id": "规则ID(constraint_id)",
            "constraint_name": "规则名称",
            "total_penalty": "总罚分",
            "affected_teacher_count": "涉及教师数",
            "teacher_list_high_penalty": "高罚分教师名单",
            "teacher_list_all": "全量教师名单",
            "link_to_event_log": "跳转事件",
        }
    )


def _cnize_solution_topn(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if "category" in out.columns:
        out["category"] = out["category"].map(_to_cn_category)
    return out.rename(
        columns={
            "solution_id": "解ID(solution_id)",
            "rank_in_solution": "解内排名",
            "constraint_id": "规则ID(constraint_id)",
            "constraint_name": "规则名称",
            "category": "类别",
            "total_penalty": "总罚分",
            "affected_teacher_count": "涉及教师数",
            "teacher_list_high_penalty": "高罚分教师名单",
            "link_to_event_log": "跳转事件",
        }
    )


def build_multi_solution_diagnostic(root_out: Path) -> Path:
    snapshots_root = root_out / "snapshots"
    root_out.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = root_out / f"多解诊断报告_{ts}.xlsx"

    all_events: List[pd.DataFrame] = []
    solver_rows: List[dict] = []

    # 快照解
    if snapshots_root.exists():
        for snap_dir in sorted([p for p in snapshots_root.iterdir() if p.is_dir()]):
            sid = snap_dir.name
            solution_id = f"snapshot_{sid}"
            event_df = _read_event_log(snap_dir / "event_log.csv", solution_id, sid)
            hard_rows = _collect_hard_events(solution_id, sid, snap_dir)
            if hard_rows:
                event_df = pd.concat([event_df, pd.DataFrame(hard_rows)], ignore_index=True)
            all_events.append(event_df)
            solver_rows.append(_load_solver_meta(solution_id, sid, snap_dir, default_status="FOUND_SOLUTION"))

    # 最终解
    final_solution_id = "final"
    final_snapshot_id = "最终解"
    final_event = _read_event_log(root_out / "event_log.csv", final_solution_id, final_snapshot_id)
    if final_event.empty:
        final_event = _read_event_log(root_out / "诊断" / "event_log.csv", final_solution_id, final_snapshot_id)
    if final_event.empty:
        final_event = _read_event_log(root_out / "meta" / "event_log.csv", final_solution_id, final_snapshot_id)
    hard_base = root_out / "诊断" if (root_out / "诊断").exists() else root_out
    final_hard = _collect_hard_events(final_solution_id, final_snapshot_id, hard_base)
    if final_hard:
        final_event = pd.concat([final_event, pd.DataFrame(final_hard)], ignore_index=True)
    all_events.append(final_event)
    solver_rows.append(_load_solver_meta(final_solution_id, final_snapshot_id, root_out))

    # event_log 事实层
    event_log = pd.concat(all_events, ignore_index=True) if all_events else pd.DataFrame(columns=EVENT_COLUMNS)
    for col in EVENT_COLUMNS:
        if col not in event_log.columns:
            event_log[col] = 0.0 if col in {"penalty", "unit_penalty", "count_value"} else ""
    event_log["penalty"] = pd.to_numeric(event_log["penalty"], errors="coerce").fillna(0.0)
    event_log["unit_penalty"] = pd.to_numeric(event_log["unit_penalty"], errors="coerce").fillna(0.0)
    event_log["count_value"] = pd.to_numeric(event_log["count_value"], errors="coerce").fillna(0.0)
    event_log = event_log[EVENT_COLUMNS].reset_index(drop=True)
    if not event_log.empty:
        for _, row in event_log.iterrows():
            rid = str(row.get("constraint_id", "") or "").strip()
            if not rid:
                continue
            ensure_rule_meta(
                rid,
                name_cn=str(row.get("constraint_name", "") or rid),
                description=str(row.get("description", "") or str(row.get("constraint_name", "") or rid)),
                default_weight=str(row.get("weight_key", "") or ""),
                mode=str(row.get("mode", "") or "soft"),
                source_module=str(row.get("source_module", "") or ""),
            )
        validate_rule_ids(
            event_log["constraint_id"].astype(str).tolist(),
            context="snapshot_diagnostics",
        )
    unmapped_personalized = _find_unmapped_personalized_rule_keys(event_log)
    if unmapped_personalized:
        logger.warning(
            "诊断映射缺失：以下个性化规则未配置中文映射，将使用默认名称。missing=%s",
            ",".join(unmapped_personalized),
        )
    io_cfg, rules_cfg = _load_diagnostic_configs(root_out)
    personalized_soft_diag_df = _build_personalized_soft_diag_sheet(event_log, hard_base)
    dorm_soft_unmet_df = _build_dorm_soft_unmet_sheet(event_log)
    hard_detail_df = _build_hard_constraint_detail_sheet(event_log, io_cfg, rules_cfg)
    soft_detail_df = _build_soft_constraint_detail_sheet(event_log, io_cfg, rules_cfg)

    first_by_rule, first_by_teacher, first_by_solution_rule = _first_event_rows(event_log)

    # 现有 soft_summary（基于 event_log）
    soft_df = event_log[event_log["mode"] == "soft"].copy()
    if soft_df.empty:
        soft_summary = pd.DataFrame(
            columns=[
                "constraint_id",
                "constraint_name",
                "category",
                "unit_penalty",
                "total_trigger_count",
                "total_penalty",
                "affected_teacher_count",
                "trigger_granularity",
                "parameters",
                "enabled",
                "source_module",
                "explain_text",
                "link_to_event_log",
            ]
        )
    else:
        rows = []
        for constraint_id, g in soft_df.groupby("constraint_id", dropna=False):
            teachers = g[(g["teacher_name"] != "GLOBAL") & (g["teacher_name"] != "")]
            granularity = "global"
            if not teachers.empty:
                granularity = "teacher-day"
                if (teachers["period"] != "").any():
                    granularity = "teacher-period"
            rows.append(
                {
                    "constraint_id": g["constraint_id"].iloc[0],
                    "constraint_name": g["constraint_name"].iloc[0],
                    "category": g["constraint_category"].iloc[0],
                    "unit_penalty": float(g["unit_penalty"].replace(0, pd.NA).dropna().iloc[0]) if g["unit_penalty"].replace(0, pd.NA).dropna().size else 0.0,
                    "total_trigger_count": float(g["count_value"].sum()),
                    "total_penalty": float(g["penalty"].sum()),
                    "affected_teacher_count": int(teachers["teacher_name"].nunique()),
                    "trigger_granularity": granularity,
                    "parameters": str(g["rule_params"].iloc[0]),
                    "enabled": True,
                    "source_module": str(g["source_module"].iloc[0]),
                    "explain_text": str(g["description"].iloc[0]),
                    "link_to_event_log": f"=HYPERLINK(\"#'{SHEET_EVENT_LOG}'!A{first_by_rule.get(str(constraint_id),2)}\",\"查看事件\")",
                }
            )
        soft_summary = pd.DataFrame(rows).sort_values("total_penalty", ascending=False).reset_index(drop=True)

    # 新增 Sheet1：soft_constraint_teacher_list
    soft_teacher_list = _build_soft_constraint_teacher_list(event_log, first_by_solution_rule)

    # 新增 Sheet2：solution_soft_topN（主阅读视图）
    solution_soft_topn = _build_solution_soft_topn(soft_teacher_list)
    if not solution_soft_topn.empty:
        # 从 event_log 映射 category（solution_id+constraint_id）
        cat_map = (
            event_log[event_log["mode"] == "soft"]
            .drop_duplicates(subset=["solution_id", "constraint_id"])
            .set_index(["solution_id", "constraint_id"])["constraint_category"]
            .to_dict()
        )
        for i in solution_soft_topn.index:
            sid = str(solution_soft_topn.at[i, "solution_id"])
            cid = str(solution_soft_topn.at[i, "constraint_id"])
            if sid and cid:
                solution_soft_topn.at[i, "category"] = cat_map.get((sid, cid), "")

    # 新增 Sheet：每解TopN罚分老师（解内老师总罚分TopN + 对应项目）
    solution_topn_teachers = _build_solution_topn_teachers(event_log)

    # 教师汇总（保留）
    if event_log.empty:
        teacher_summary = pd.DataFrame(
            columns=[
                "teacher_name",
                "total_penalty",
                "soft_penalty",
                "hard_violation_count",
                "top_3_constraints",
                "top_3_penalty_sources",
                "link_to_event_log",
            ]
        )
    else:
        rows = []
        for teacher, g in event_log.groupby("teacher_name", dropna=False):
            teacher = str(teacher)
            if not teacher or teacher == "GLOBAL":
                # teacher_penalty_summary 只保留真实教师，避免 GLOBAL/空值污染阅读
                continue
            penalty_by_rule = g.groupby("constraint_name", dropna=False)["penalty"].sum().sort_values(ascending=False).head(3)
            penalty_by_time = (
                g.assign(_tp=g["day"].astype(str) + " " + g["period"].astype(str))
                .groupby("_tp", dropna=False)["penalty"]
                .sum()
                .sort_values(ascending=False)
                .head(3)
            )
            rows.append(
                {
                    "teacher_name": teacher,
                    "total_penalty": float(g["penalty"].sum()),
                    "soft_penalty": float(g[g["mode"] == "soft"]["penalty"].sum()),
                    "hard_violation_count": int(g[g["mode"] == "hard"]["count_value"].sum()),
                    "top_3_constraints": "；".join([f"{k}:{v:.0f}" for k, v in penalty_by_rule.items()]),
                    "top_3_penalty_sources": "；".join([f"{k}:{v:.0f}" for k, v in penalty_by_time.items()]),
                    "link_to_event_log": f"=HYPERLINK(\"#'{SHEET_EVENT_LOG}'!A{first_by_teacher.get(teacher,2)}\",\"查看教师事件\")",
                }
            )
        if rows:
            teacher_summary = pd.DataFrame(rows).sort_values("total_penalty", ascending=False).reset_index(drop=True)
        else:
            teacher_summary = pd.DataFrame(
                columns=[
                    "teacher_name",
                    "total_penalty",
                    "soft_penalty",
                    "hard_violation_count",
                    "top_3_constraints",
                    "top_3_penalty_sources",
                    "link_to_event_log",
                ]
            )

    # solver_overview（保留）
    solver_overview = pd.DataFrame(solver_rows)
    if not solver_overview.empty:
        solver_overview["gap_percent"] = solver_overview.apply(
            lambda r: (
                abs((r["objective_value"] - r["best_bound"]) / r["objective_value"]) * 100.0
                if r.get("objective_value") not in (None, 0) and r.get("best_bound") is not None
                else None
            ),
            axis=1,
        )
        viol_map = event_log[event_log["mode"] == "hard"].groupby("snapshot_id")["count_value"].sum().to_dict()
        soft_map = event_log[event_log["mode"] == "soft"].groupby("snapshot_id")["penalty"].sum().to_dict()
        solver_overview["hard_violation_count"] = solver_overview["snapshot_id"].map(lambda x: float(viol_map.get(x, 0.0)))
        solver_overview["soft_total_penalty"] = solver_overview["snapshot_id"].map(lambda x: float(soft_map.get(x, 0.0)))
        solver_overview["is_best_solution"] = False
        candidates = solver_overview.sort_values(
            ["hard_violation_count", "soft_total_penalty", "objective_value"],
            ascending=[True, True, True],
            na_position="last",
        )
        if len(candidates) > 0:
            best_snapshot = candidates.iloc[0]["snapshot_id"]
            solver_overview.loc[solver_overview["snapshot_id"] == best_snapshot, "is_best_solution"] = True
    else:
        solver_overview = pd.DataFrame(
            columns=[
                "solution_id",
                "snapshot_id",
                "solver_status",
                "objective_value",
                "best_bound",
                "gap_percent",
                "time_limit",
                "num_conflicts",
                "num_branches",
                "solution_index",
                "is_best_solution",
                "hard_violation_count",
                "soft_total_penalty",
            ]
        )

    # dashboard（保留）
    top_constraints = (
        soft_summary[["constraint_name", "total_penalty", "affected_teacher_count"]].head(10)
        if not soft_summary.empty
        else pd.DataFrame(columns=["constraint_name", "total_penalty", "affected_teacher_count"])
    )
    top_teachers = (
        teacher_summary[["teacher_name", "total_penalty", "hard_violation_count"]].head(20)
        if not teacher_summary.empty
        else pd.DataFrame(columns=["teacher_name", "total_penalty", "hard_violation_count"])
    )
    time_bottleneck = (
        event_log.groupby(["day", "period"], dropna=False)["penalty"].sum().reset_index().sort_values("penalty", ascending=False).head(20)
        if not event_log.empty
        else pd.DataFrame(columns=["day", "period", "penalty"])
    )
    category_share = (
        event_log.groupby("constraint_category", dropna=False)["penalty"].sum().reset_index().sort_values("penalty", ascending=False)
        if not event_log.empty
        else pd.DataFrame(columns=["constraint_category", "penalty"])
    )
    dashboard_df = _build_dashboard_sheet(top_constraints, top_teachers, time_bottleneck, category_share)

    # rule_config_table（保留）
    if event_log.empty:
        rule_config = pd.DataFrame(
            columns=[
                "constraint_id",
                "constraint_name",
                "category",
                "mode",
                "unit_penalty",
                "parameters",
                "enabled",
                "source_module",
                "explain_text",
                "link_to_event_log",
            ]
        )
    else:
        rows = []
        for cid, g in event_log.groupby("constraint_id", dropna=False):
            rows.append(
                {
                    "constraint_id": g["constraint_id"].iloc[0],
                    "constraint_name": g["constraint_name"].iloc[0],
                    "category": g["constraint_category"].iloc[0],
                    "mode": g["mode"].iloc[0],
                    "unit_penalty": float(g["unit_penalty"].replace(0, pd.NA).dropna().iloc[0]) if g["unit_penalty"].replace(0, pd.NA).dropna().size else 0.0,
                    "parameters": g["rule_params"].iloc[0],
                    "enabled": True,
                    "source_module": g["source_module"].iloc[0],
                    "explain_text": g["description"].iloc[0],
                    "link_to_event_log": f"=HYPERLINK(\"#'{SHEET_EVENT_LOG}'!A{first_by_rule.get(str(cid),2)}\",\"查看事件\")",
                }
            )
        rule_config = pd.DataFrame(rows)

    # 中文展示 DataFrame（不影响内部计算口径）
    event_log_cn = _cnize_event_log(event_log).fillna("")
    soft_summary_cn = _cnize_soft_summary(soft_summary).fillna("")
    teacher_summary_cn = _cnize_teacher_summary(teacher_summary).fillna("")
    solver_overview_cn = _cnize_solver_overview(solver_overview).fillna("")
    rule_config_cn = _cnize_rule_config(rule_config).fillna("")
    soft_teacher_list_cn = _cnize_soft_teacher_list(soft_teacher_list).fillna("")
    solution_soft_topn_cn = _cnize_solution_topn(solution_soft_topn).fillna("")

    # 输出 Excel（文件名中文 + Sheet中文）
    with create_excel_writer(out_path) as writer:
        solver_overview_cn.to_excel(writer, sheet_name=SHEET_SOLVER_OVERVIEW, index=False)
        solution_soft_topn_cn.to_excel(writer, sheet_name=SHEET_TOPN, index=False)
        solution_topn_teachers.fillna("").to_excel(writer, sheet_name=SHEET_TOPN_TEACHERS, index=False)
        personalized_soft_diag_df.fillna("").to_excel(writer, sheet_name=SHEET_PERSONALIZED_SOFT_DIAG, index=False)
        dorm_soft_unmet_df.fillna("").to_excel(writer, sheet_name=SHEET_DORM_SOFT_UNMET, index=False)
        dashboard_df.fillna("").to_excel(writer, sheet_name=SHEET_DASHBOARD, index=False)
        hard_detail_df.fillna("").to_excel(writer, sheet_name=SHEET_HARD_DETAIL, index=False)
        soft_detail_df.fillna("").to_excel(writer, sheet_name=SHEET_SOFT_DETAIL, index=False)
        for ws in writer.book.worksheets:
            apply_table_style(ws, header_row=1, freeze_panes="auto", zoom=115)
            apply_conditional_format_for_diagnostics(ws, header_row=1)
        _add_block_outer_borders(writer.book[SHEET_TOPN_TEACHERS])

    # 最小自检：当存在软约束罚分事件时，新增摘要 sheet 必须有数据
    has_soft_penalty = bool(((event_log["mode"] == "soft") & (event_log["penalty"] > 0)).any())
    if has_soft_penalty:
        topn_data_rows = len(solution_soft_topn[solution_soft_topn["constraint_id"].astype(str) != ""])
        topn_teacher_rows = len(solution_topn_teachers)
        ok_soft_list = len(soft_teacher_list) > 0
        ok_topn = topn_data_rows > 0 and topn_teacher_rows > 0
        if ok_soft_list and ok_topn:
            logger.info("诊断自检：已在根目录生成摘要 sheet。")
        else:
            logger.warning(
                "诊断自检警告：存在软约束罚分但摘要sheet为空或行数不足，软约束-教师名单=%s, 每解TopN软约束数据行=%s, 每解TopN罚分老师=%s",
                len(soft_teacher_list),
                topn_data_rows,
                topn_teacher_rows,
            )
    else:
        logger.info("诊断自检：当前 event_log 无软约束罚分事件，摘要sheet允许为空。")

    return out_path

