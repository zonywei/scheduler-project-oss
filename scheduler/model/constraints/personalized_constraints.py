# -*- coding: utf-8 -*-
"""
What：个性化约束模块（Personalized constraints）。
Why：满足教师个人偏好/临时需求，不影响通用规则结构。
How：复用 day/night/bridge 变量口径，按教师与日期组合构造硬/软约束；
     软约束以 penalties 返回，由上层统一加入 objective。
Weights：见 io.yaml -> personalized_constraints.*（建议 60/120/200/400 级）
Diagnostics：
    - outputs/诊断/个性化_审计.txt
    - outputs/诊断/个性化_检查.txt
    - outputs/诊断/个性化_不可行提示.txt
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Tuple, Set, Any

from ortools.sat.python import cp_model

from scheduler.data.day_rules_reader import DayInputData, Slot
from scheduler.model.day_variables import DayVars
from scheduler.diagnostics.penalty_registry import register
from scheduler.model.constraints.day_pairs import adjacent_day_pairs
from scheduler.model.constraints.teacher_targets import teacher_names
from scheduler.model.constraints.personalized_rules import PERSONALIZED_RULE_MODULES
from scheduler.model.constraints.personalized_rules.context import build_personalized_rule_context
from scheduler.model.constraints.personalized_rules.penalty_registration import register_personalized_penalties

logger = logging.getLogger(__name__)


@dataclass
class PersonalizedConfig:
    enabled: bool = True
    teacher_targets: Dict[str, Any] = field(default_factory=dict)
    enable_xhd_night_no_pm3: bool = True
    xhd_night_no_pm3_mode: str = "soft"  # soft|hard
    w_xhd_night_no_pm3: int = 150
    enable_xhd_night_no_pm: bool = True
    xhd_night_no_pm_mode: str = "hard"  # soft|hard
    w_xhd_night_no_pm: int = 3000
    enable_couple_xhd_zfy: bool = True
    couple_xhd_zfy_mode: str = "soft"  # soft|hard
    w_couple_diff_day: int = 200
    w_couple_need_overlap: int = 5000
    enable_zw_night_need_pm: bool = True
    zw_night_need_pm_mode: str = "hard"  # soft|hard
    w_zw_night_need_pm: int = 3000
    enable_zw_am1_cap: bool = True
    zw_am1_cap_mode: str = "hard"  # soft|hard
    zw_am1_slot_key: str = "上午1"
    zw_am1_cap_max: int = 1
    w_zw_am1_cap: int = 3000
    enable_zw_am2_cap: bool = True
    zw_am2_cap_mode: str = "hard"  # soft|hard
    zw_am2_slot_key: str = "上午2"
    zw_am2_cap_max: int = 2
    w_zw_am2_cap: int = 3000
    enable_zw_am4_cap: bool = True
    zw_am4_cap_mode: str = "hard"  # soft|hard
    zw_am4_slot_key: str = "上午4"
    zw_am4_cap_max: int = 1
    w_zw_am4_cap: int = 3000
    enable_zw_weekday_pm1_cap: bool = True
    zw_weekday_pm1_cap_mode: str = "hard"  # soft|hard
    zw_weekday_pm1_slot_key: str = "下午1"
    zw_weekday_pm1_cap_max: int = 2
    w_zw_weekday_pm1_cap: int = 3000
    enable_lm_sun_am12: bool = True
    lm_sun_am12_mode: str = "soft"  # soft|hard
    w_lm_sun_am12: int = 400
    enable_ytt_sun_pref: bool = True
    ytt_sun_pref_mode: str = "soft"  # soft|hard
    w_ytt_sun_am_pref: int = 60
    w_ytt_no_sun_night: int = 80
    enable_dym_no_fri_sun_night: bool = True
    enable_pol_no_sun_night: bool = True
    pol_no_sun_night_mode: str = "soft"  # soft|hard
    w_pol_sun_teacher_count: int = 300
    w_pol_sun_super: int = 600
    enable_ld_reduce_pm: bool = True
    ld_reduce_pm_mode: str = "soft"  # soft|hard
    w_ld_reduce_pm: int = 80
    enable_ld_tue_fri_pm_penalty: bool = True
    w_ld_tue_fri_pm_each: int = 5000
    w_ld_tue_fri_pm1_extra_each: int = 6000
    enable_ld_no_mon_pm: bool = True
    enable_zfj_ban_mon_fri_pm3: bool = True
    enable_zfj_night_checkin_penalty: bool = True
    w_zfj_night_checkin_penalty: int = 1000
    enable_jxq_prefs: bool = True
    jxq_prefs_mode: str = "soft"  # soft|hard
    w_jxq_no_mon_am1: int = 80
    w_jxq_sun_pm_pref: int = 60
    w_jxq_no_sun_night: int = 150
    enable_csqi_prefs: bool = True
    csqi_prefs_mode: str = "soft"  # soft|hard
    w_csqi_sun_am_pref: int = 60
    w_csqi_night_outside_pen: int = 120
    w_csqi_need_sun_or_mon: int = 80
    enable_csqi_need_consecutive_night: bool = True
    csqi_need_consecutive_night_mode: str = "hard"  # soft|hard
    w_csqi_need_consecutive_night: int = 3000
    enable_zzx_prefs: bool = True
    zzx_prefs_mode: str = "soft"  # soft|hard
    w_zzx_no_sun_night: int = 220
    w_zzx_sun_am_pref: int = 70
    w_zzx_reduce_am4: int = 60
    enable_zzx_no_sunday_night: bool = True
    zzx_no_sunday_night_mode: str = "hard"  # soft|hard
    w_zzx_no_sunday_night: int = 3000
    enable_xyx_night_days_only: bool = True
    xyx_night_days_only_mode: str = "hard"  # soft|hard
    xyx_night_allowed_days: List[str] = field(default_factory=lambda: ["星期五", "星期日"])
    w_xyx_night_days_only: int = 2000
    enable_hwj_prefs: bool = True
    hwj_prefs_mode: str = "soft"  # soft|hard
    w_hwj_need_sun_mon: int = 220
    w_hwj_need_consecutive: int = 120
    enable_hwj_night_sun_mon_assign: bool = True
    hwj_night_sun_mon_assign_mode: str = "hard"  # soft|hard
    w_hwj_night_sun_mon_assign: int = 2000
    enable_hsm_no_fri_night: bool = True
    hsm_no_fri_night_mode: str = "soft"  # soft|hard
    w_hsm_no_fri_night: int = 80
    enable_hsm_weekday_early_no_am1: bool = True
    hsm_weekday_early_no_am1_mode: str = "hard"  # soft|hard
    w_hsm_weekday_early_no_am1: int = 2000
    enable_wxl_weekday_early_no_am1: bool = True
    wxl_weekday_early_no_am1_mode: str = "hard"  # soft|hard
    w_wxl_weekday_early_no_am1: int = 2000
    enable_dln_weekday_no_am1: bool = True
    dln_weekday_no_am1_mode: str = "hard"  # soft|hard
    w_dln_weekday_no_am1: int = 2000
    enable_custom_no_am1_teachers: bool = True
    custom_no_am1_teachers: List[str] = field(default_factory=list)
    enable_mrj_hsm_sun_am12_fixed: bool = True
    mrj_hsm_sun_am12_fixed_mode: str = "hard"  # soft|hard
    w_mrj_hsm_sun_am12_fixed: int = 3000
    enable_zhoubo_hard: bool = True
    enable_zhoubo_liumeng_same_night: bool = True
    enable_zhoubo_weekday_am1_penalty: bool = True
    zhoubo_weekday_am1_penalty_mode: str = "soft"  # soft|hard
    w_zhoubo_weekday_am1_penalty: int = 300
    enable_liumeng_no_sunday: bool = True
    enable_xww_weekday_am4_pm1_stair: bool = True
    xww_weekday_am4_pm1_stair_mode: str = "soft"  # soft|hard
    w_xww_weekday_am4_pm1_e2: int = 80
    w_xww_weekday_am4_pm1_e3: int = 160
    w_xww_weekday_am4_pm1_e4: int = 320
    enable_zfy_no_consecutive_night: bool = True
    zfy_no_consecutive_night_mode: str = "soft"  # soft|hard
    w_zfy_no_consecutive_night: int = 3000
    enable_zw_no_consecutive_night: bool = True
    zw_no_consecutive_night_mode: str = "hard"  # soft|hard
    w_zw_no_consecutive_night: int = 3000
    enable_zfy_no_sunday_night: bool = True
    zfy_no_sunday_night_mode: str = "soft"  # soft|hard
    w_zfy_no_sunday_night: int = 500
    enable_sll_sun_am_only: bool = True
    sll_sun_am_only_mode: str = "soft"  # soft|hard
    w_sll_sun_am_only: int = 300
    enable_cc_weekday_no_am4: bool = True
    cc_weekday_no_am4_mode: str = "soft"  # soft|hard
    w_cc_weekday_no_am4: int = 300
    enable_cc_sat_am34_class17: bool = True
    cc_sat_am34_class17_mode: str = "soft"  # soft|hard
    w_cc_sat_am34_class17: int = 600
    enable_sm_mon_no_am: bool = True
    sm_mon_no_am_mode: str = "soft"  # soft|hard
    w_sm_mon_no_am: int = 300
    enable_sm_mon_no_pm1: bool = True
    sm_mon_no_pm1_mode: str = "soft"  # soft|hard
    w_sm_mon_no_pm1: int = 300


def _norm_name(s: str) -> str:
    """教师名归一化（去空格）。"""
    return str(s or "").strip()



def _norm_mode(x: object, default: str = "soft") -> str:
    m = str(x or default).strip().lower()
    return m if m in {"soft", "hard"} else default

def _slot_key(slot: Slot) -> str:
    """Slot 映射到字符串键（block+period）。"""
    return f"{slot.block}{slot.period}"


def _and2(model: cp_model.CpModel, a, b, name: str) -> cp_model.IntVar:
    """z = a AND b 线性化。"""
    z = model.NewBoolVar(name)
    model.Add(z <= a)
    model.Add(z <= b)
    model.Add(z >= a + b - 1)
    return z


def _collect_day_teacher_vars(
    data: DayInputData,
    dv: DayVars,
) -> Dict[str, Dict[str, Dict[Slot, List[cp_model.IntVar]]]]:
    """按教师/日期/时段聚合白天变量。"""
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
    """构造 day_has_slot[t,d]：教师 t 在 d 日某个时段是否上课。"""
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
    """构造 day_has_am_any[t,d]：上午任意课是否存在（含固定课）。"""
    out: Dict[Tuple[str, str], cp_model.IntVar] = {}
    teacher_vars = _collect_day_teacher_vars(data, dv)
    for t in teachers:
        for d in days:
            vars_list = []
            for s, lst in teacher_vars.get(t, {}).get(d, {}).items():
                if s.block == "上午":
                    vars_list.extend(lst)
            fixed = 0
            for (cls, slot), subj in data.fixed_assign.items():
                if slot.day != d:
                    continue
                if slot.block != "上午":
                    continue
                if data.cls_subj_teacher.get((cls, subj)) == t:
                    fixed += 1
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
    """构造 day_has_pm_any[t,d]：下午任意课是否存在（含固定课）。"""
    out: Dict[Tuple[str, str], cp_model.IntVar] = {}
    teacher_vars = _collect_day_teacher_vars(data, dv)
    for t in teachers:
        for d in days:
            vars_list = []
            for s, lst in teacher_vars.get(t, {}).get(d, {}).items():
                if s.block == "下午":
                    vars_list.extend(lst)
            fixed = 0
            for (cls, slot), subj in data.fixed_assign.items():
                if slot.day != d:
                    continue
                if slot.block != "下午":
                    continue
                if data.cls_subj_teacher.get((cls, subj)) == t:
                    fixed += 1
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


def apply_personalized_constraints(
    model: cp_model.CpModel,
    day_data: DayInputData | None,
    day_vars: DayVars | None,
    night_vars: dict | None,
    night_ctx: dict | None,
    bridge: dict | None,
    cfg: PersonalizedConfig,
    out_dir: Path,
) -> Tuple[List[str], List[cp_model.IntVar], dict]:
    """
    应用个性化约束（硬/软）。
    返回：
      - hard_notes：硬约束无法落地的提示
      - penalties：软惩罚变量列表（由上层加入 objective）
      - stats：诊断统计（用于 checklist）
    """
    hard_notes: List[str] = []
    penalties: List[cp_model.IntVar] = []
    stats: Dict[str, dict] = {}

    out_dir.mkdir(parents=True, exist_ok=True)

    day_days = sorted({s.day for s in day_data.available_slots}) if day_data else []
    night_days = night_ctx["days"] if night_ctx else []
    night_periods = night_ctx["periods"] if night_ctx else []
    day_teachers = set(day_data.cls_subj_teacher.values()) if day_data else set()
    night_teachers = set(night_ctx["cst"].values()) if night_ctx else set()
    all_teachers = sorted(set(day_teachers) | set(night_teachers))

    slot_keys = {
        "上午1": "上午1",
        "上午2": "上午2",
        "上午3": "上午3",
        "上午4": "上午4",
        "下午1": "下午1",
        "下午3": "下午3",
    }

    audit_lines = [
        "[Personalized Audit Before]",
        f"DayDays={day_days}",
        f"NightDays={night_days}",
        f"TeachersDay={len(day_teachers)}",
        f"TeachersNight={len(night_teachers)}",
        f"TeachersAll={len(all_teachers)}",
        f"SlotKeys={slot_keys}",
        f"enable_xhd_night_no_pm3={cfg.enable_xhd_night_no_pm3} mode={cfg.xhd_night_no_pm3_mode} w={cfg.w_xhd_night_no_pm3}",
        f"enable_xhd_night_no_pm={cfg.enable_xhd_night_no_pm} mode={cfg.xhd_night_no_pm_mode} w={cfg.w_xhd_night_no_pm}",
        f"enable_couple_xhd_zfy={cfg.enable_couple_xhd_zfy} mode={cfg.couple_xhd_zfy_mode} w_soft={cfg.w_couple_need_overlap} (configured_pair\u81f3\u5c11\u540c\u5929\u4e00\u6b21)",
        (
            "enable_zw_night_need_pm="
            f"{cfg.enable_zw_night_need_pm} mode={cfg.zw_night_need_pm_mode} w={cfg.w_zw_night_need_pm}"
        ),
        (
            "enable_zw_am1_cap="
            f"{cfg.enable_zw_am1_cap} mode={cfg.zw_am1_cap_mode} slot={cfg.zw_am1_slot_key} "
            f"max={cfg.zw_am1_cap_max} w={cfg.w_zw_am1_cap}"
        ),
        (
            "enable_zw_am2_cap="
            f"{cfg.enable_zw_am2_cap} mode={cfg.zw_am2_cap_mode} slot={cfg.zw_am2_slot_key} "
            f"max={cfg.zw_am2_cap_max} w={cfg.w_zw_am2_cap}"
        ),
        (
            "enable_zw_am4_cap="
            f"{cfg.enable_zw_am4_cap} mode={cfg.zw_am4_cap_mode} slot={cfg.zw_am4_slot_key} "
            f"max={cfg.zw_am4_cap_max} w={cfg.w_zw_am4_cap}"
        ),
        (
            "enable_zw_weekday_pm1_cap="
            f"{cfg.enable_zw_weekday_pm1_cap} mode={cfg.zw_weekday_pm1_cap_mode} "
            f"slot={cfg.zw_weekday_pm1_slot_key} max={cfg.zw_weekday_pm1_cap_max} "
            f"w={cfg.w_zw_weekday_pm1_cap}"
        ),
        f"enable_lm_sun_am12={cfg.enable_lm_sun_am12} mode={cfg.lm_sun_am12_mode} w={cfg.w_lm_sun_am12}",
        f"enable_ytt_sun_pref={cfg.enable_ytt_sun_pref} mode={cfg.ytt_sun_pref_mode} w_am={cfg.w_ytt_sun_am_pref} w_night={cfg.w_ytt_no_sun_night}",
        f"enable_dym_no_fri_sun_night={cfg.enable_dym_no_fri_sun_night}",
        f"enable_pol_no_sun_night={cfg.enable_pol_no_sun_night} mode={cfg.pol_no_sun_night_mode} w_cnt={cfg.w_pol_sun_teacher_count} w_super={cfg.w_pol_sun_super}",
        f"enable_ld_reduce_pm={cfg.enable_ld_reduce_pm} mode={cfg.ld_reduce_pm_mode} w={cfg.w_ld_reduce_pm}",
        (
            "enable_ld_tue_fri_pm_penalty="
            f"{cfg.enable_ld_tue_fri_pm_penalty} "
            f"w_pm_each={cfg.w_ld_tue_fri_pm_each} "
            f"w_pm1_extra_each={cfg.w_ld_tue_fri_pm1_extra_each}"
        ),
        f"enable_ld_no_mon_pm={cfg.enable_ld_no_mon_pm}",
        f"enable_zfj_ban_mon_fri_pm3={cfg.enable_zfj_ban_mon_fri_pm3}",
        (
            "enable_zfj_night_checkin_penalty="
            f"{cfg.enable_zfj_night_checkin_penalty} w={cfg.w_zfj_night_checkin_penalty}"
        ),
        f"enable_jxq_prefs={cfg.enable_jxq_prefs} mode={cfg.jxq_prefs_mode}",
        f"enable_csqi_prefs={cfg.enable_csqi_prefs} mode={cfg.csqi_prefs_mode}",
        (
            "enable_csqi_need_consecutive_night="
            f"{cfg.enable_csqi_need_consecutive_night} "
            f"mode={cfg.csqi_need_consecutive_night_mode} "
            f"w_soft={cfg.w_csqi_need_consecutive_night}"
        ),
        f"enable_zzx_prefs={cfg.enable_zzx_prefs} mode={cfg.zzx_prefs_mode}",
        (
            "enable_zzx_no_sunday_night="
            f"{cfg.enable_zzx_no_sunday_night} "
            f"mode={cfg.zzx_no_sunday_night_mode} "
            f"w_soft={cfg.w_zzx_no_sunday_night}"
        ),
        (
            "enable_xyx_night_days_only="
            f"{cfg.enable_xyx_night_days_only} "
            f"mode={cfg.xyx_night_days_only_mode} "
            f"allowed_days={cfg.xyx_night_allowed_days} "
            f"w_soft={cfg.w_xyx_night_days_only}"
        ),
        f"enable_hwj_prefs={cfg.enable_hwj_prefs} mode={cfg.hwj_prefs_mode}",
        (
            "enable_hwj_night_sun_mon_assign="
            f"{cfg.enable_hwj_night_sun_mon_assign} "
            f"mode={cfg.hwj_night_sun_mon_assign_mode} "
            f"w_soft={cfg.w_hwj_night_sun_mon_assign}"
        ),
        f"enable_hsm_no_fri_night={cfg.enable_hsm_no_fri_night} mode={cfg.hsm_no_fri_night_mode}",
        (
            "enable_hsm_weekday_early_no_am1="
            f"{cfg.enable_hsm_weekday_early_no_am1} "
            f"mode={cfg.hsm_weekday_early_no_am1_mode} "
            f"w_soft={cfg.w_hsm_weekday_early_no_am1}"
        ),
        (
            "enable_wxl_weekday_early_no_am1="
            f"{cfg.enable_wxl_weekday_early_no_am1} "
            f"mode={cfg.wxl_weekday_early_no_am1_mode} "
            f"w_soft={cfg.w_wxl_weekday_early_no_am1}"
        ),
        (
            "enable_dln_weekday_no_am1="
            f"{cfg.enable_dln_weekday_no_am1} "
            f"mode={cfg.dln_weekday_no_am1_mode} "
            f"w_soft={cfg.w_dln_weekday_no_am1}"
        ),
        (
            "enable_custom_no_am1_teachers="
            f"{cfg.enable_custom_no_am1_teachers} "
            f"teachers={cfg.custom_no_am1_teachers}"
        ),
        f"enable_zhoubo_hard={cfg.enable_zhoubo_hard}",
        f"enable_zhoubo_liumeng_same_night={cfg.enable_zhoubo_liumeng_same_night}",
        f"enable_zhoubo_weekday_am1_penalty={cfg.enable_zhoubo_weekday_am1_penalty} mode={cfg.zhoubo_weekday_am1_penalty_mode} w={cfg.w_zhoubo_weekday_am1_penalty}",
        f"enable_liumeng_no_sunday={cfg.enable_liumeng_no_sunday}",
        (
            "enable_xww_weekday_am4_pm1_stair="
            f"{cfg.enable_xww_weekday_am4_pm1_stair} "
            f"mode={cfg.xww_weekday_am4_pm1_stair_mode} "
            f"w2={cfg.w_xww_weekday_am4_pm1_e2} "
            f"w3={cfg.w_xww_weekday_am4_pm1_e3} "
            f"w4={cfg.w_xww_weekday_am4_pm1_e4}"
        ),
        (
            "enable_zfy_no_consecutive_night="
            f"{cfg.enable_zfy_no_consecutive_night} "
            f"mode={cfg.zfy_no_consecutive_night_mode} "
            f"w_soft={cfg.w_zfy_no_consecutive_night} "
            "(configured_teacher_no_consecutive_night)"
        ),
        (
            "enable_zw_no_consecutive_night="
            f"{cfg.enable_zw_no_consecutive_night} "
            f"mode={cfg.zw_no_consecutive_night_mode} "
            f"w_soft={cfg.w_zw_no_consecutive_night} "
            "(指定教师晚自习不连续)"
        ),
        (
            "enable_zfy_no_sunday_night="
            f"{cfg.enable_zfy_no_sunday_night} "
            f"mode={cfg.zfy_no_sunday_night_mode} "
            f"w_soft={cfg.w_zfy_no_sunday_night}"
        ),
        (
            "enable_sll_sun_am_only="
            f"{cfg.enable_sll_sun_am_only} "
            f"mode={cfg.sll_sun_am_only_mode} "
            f"w_soft={cfg.w_sll_sun_am_only}"
        ),
        (
            "enable_cc_weekday_no_am4="
            f"{cfg.enable_cc_weekday_no_am4} "
            f"mode={cfg.cc_weekday_no_am4_mode} "
            f"w_soft={cfg.w_cc_weekday_no_am4}"
        ),
        (
            "enable_cc_sat_am34_class17="
            f"{cfg.enable_cc_sat_am34_class17} "
            f"mode={cfg.cc_sat_am34_class17_mode} "
            f"w_soft={cfg.w_cc_sat_am34_class17}"
        ),
        (
            "enable_sm_mon_no_am="
            f"{cfg.enable_sm_mon_no_am} "
            f"mode={cfg.sm_mon_no_am_mode} "
            f"w_soft={cfg.w_sm_mon_no_am}"
        ),
        (
            "enable_sm_mon_no_pm1="
            f"{cfg.enable_sm_mon_no_pm1} "
            f"mode={cfg.sm_mon_no_pm1_mode} "
            f"w_soft={cfg.w_sm_mon_no_pm1}"
        ),
        (
            "enable_mrj_hsm_sun_am12_fixed="
            f"{cfg.enable_mrj_hsm_sun_am12_fixed} "
            f"mode={cfg.mrj_hsm_sun_am12_fixed_mode} "
            f"w_soft={cfg.w_mrj_hsm_sun_am12_fixed}"
        ),
    ]
    (out_dir / "personalized_audit_before.txt").write_text("\n".join(audit_lines), encoding="utf-8")

    if not cfg.enabled:
        return hard_notes, penalties, stats

    ctx = build_personalized_rule_context(
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
        day_teachers=set(day_teachers),
        night_teachers=set(night_teachers),
        all_teachers=all_teachers,
    )
    for rule_module in PERSONALIZED_RULE_MODULES:
        rule_module.apply(ctx)
    register_personalized_penalties(ctx)

    # checklist is written after solve by caller

    return hard_notes, penalties, stats


def write_personalized_checklist(
    out_dir: Path,
    solver: cp_model.CpSolver,
    stats: dict,
    hard_notes: List[str],
) -> None:
    """输出个性化检查清单（各规则触发次数与罚分）。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "personalized_checklist.txt"
    lines = ["[Personalized Checklist]"]
    total_pen = 0
    for key, info in sorted(stats.items()):
        vars_list = info.get("vars", [])
        weights = info.get("weights")
        if weights and len(weights) == len(vars_list):
            cnt = sum(solver.Value(v) for v in vars_list)
            pen = sum(int(wi) * solver.Value(vi) for wi, vi in zip(weights, vars_list))
            w_show = "/".join(str(int(wi)) for wi in weights)
        else:
            w = info.get("w", 0)
            cnt = sum(solver.Value(v) for v in vars_list)
            pen = cnt * w
            w_show = str(w)
        total_pen += pen
        extra = ""
        if "count_var" in info:
            extra = f" raw_count={solver.Value(info['count_var'])}"
        lines.append(f"{key}: count={cnt} weight={w_show} penalty={pen}{extra}")

    couple_info = stats.get("rule2_couple_overlap_soft", {})
    couple_vars = list(couple_info.get("vars", []))
    if couple_vars:
        couple_viol = int(solver.Value(couple_vars[0]))
        couple_satisfied = (couple_viol == 0)
        lines.append(f"rule2_couple_overlap_soft_satisfied={couple_satisfied}")
        if not couple_satisfied:
            lines.append(f"rule2_couple_overlap_soft_teachers={couple_info.get('teacher', '')}")
    else:
        lines.append("rule2_couple_overlap_soft_satisfied=N/A")

    zfy_info = stats.get("rule18_zfy_consecutive_night", {})
    zfy_vars = list(zfy_info.get("vars", []))
    zfy_labels = list(zfy_info.get("pair_labels", []))
    if zfy_vars:
        violated_pairs = [label for var, label in zip(zfy_vars, zfy_labels) if solver.Value(var)]
        teacher_name = str(zfy_info.get("teacher", ""))
        lines.append(f"rule18_zfy_consecutive_night_teacher={teacher_name}")
        lines.append(
            "rule18_zfy_consecutive_night_violated_pairs=" + (",".join(violated_pairs) if violated_pairs else "None")
        )

    zw_info = stats.get("rule29_zw_no_consecutive_night", {})
    zw_vars = list(zw_info.get("vars", []))
    zw_labels = list(zw_info.get("pair_labels", []))
    if zw_vars:
        violated_pairs = [label for var, label in zip(zw_vars, zw_labels) if solver.Value(var)]
        teacher_name = str(zw_info.get("teacher", ""))
        lines.append(f"rule29_zw_no_consecutive_night_teacher={teacher_name}")
        lines.append(
            "rule29_zw_no_consecutive_night_violated_pairs=" + (",".join(violated_pairs) if violated_pairs else "None")
        )
    lines.append(f"TotalPenalty={total_pen}")
    lines.append(f"HardNotes={hard_notes}")
    path.write_text("\n".join(lines), encoding="utf-8")


def write_personalized_infeasible_hints(out_dir: Path, hard_notes: List[str]) -> None:
    """输出个性化不可行提示（硬约束缺失/无法落地）。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    if not hard_notes:
        return
    (out_dir / "personalized_infeasible_hints.txt").write_text(
        "[Personalized Infeasible Hints]\n" + "\n".join(hard_notes), encoding="utf-8"
    )
