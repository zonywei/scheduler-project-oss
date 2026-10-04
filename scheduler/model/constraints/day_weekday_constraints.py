# -*- coding: utf-8 -*-
"""
What：白天工作日约束集合（weekday hard/soft constraints）。
Why：保证教师冲突、均匀分布、半天偏好与班级绑定等业务规则。
How：基于 x[(班级,学科,Slot)] 统计教师/班级/日内布尔量，
    通过线性化（OnlyEnforceIf/big-M/AND）实现硬约束与软惩罚。
Weights：见 io.yaml -> day.weekday_constraints.*（建议 50/100/200/400 级）
Diagnostics：
    - outputs/诊断/白天_硬约束检查.txt
    - outputs/诊断/白天_约束清单.txt
    - outputs/诊断/白天_软约束报告.txt
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple, Set

import pandas as pd
from ortools.sat.python import cp_model

from scheduler.data.day_rules_reader import DayInputData, Slot
from scheduler.data.teacher_table_schema import (
    configured_teacher_table_columns,
    load_teacher_table_frame,
)
from scheduler.model.day_variables import DayVars
from scheduler.model.constraints.global_binding_constraints import apply_global_day_binding_8_chem_9_bio
from scheduler.model.constraints.day_weekday_reports import (
    write_core_teacher_day_load_infeasible_hint,
    write_core_teacher_day_load_sanity,
    write_day_infeasible_hints,
    write_day_soft_timepref_report,
    write_low_weekday_subject_max1_report,
    write_teacher_am4_pm1_penalty_report,
    write_teacher_continuity_report,
    write_teacher_m1_cap_infeasible_hint,
    write_teacher_m1_cap_report,
    write_two_class_daily_min_report,
)
from scheduler.diagnostics.penalty_registry import register
from scheduler.calendar import ALL_DAYS, TUESDAY_TO_FRIDAY, WEEKDAY_DAYS

logger = logging.getLogger(__name__)

WEEKDAYS = WEEKDAY_DAYS
WEEK_ALL_DAYS = ALL_DAYS
TUE_TO_FRI = TUESDAY_TO_FRIDAY
CORE_SUBJECTS = {"语文", "数学", "外语", "物理", "化学", "生物", "历史", "地理", "政治"}

SUBJ_ALIAS = {
    "体育": "体育",
    "体育与健康": "体育",
    "技术": "技术",
    "信息技术": "技术",
    "通用技术": "技术",
    "英语": "外语",
    "化学": "化学",
    "生物": "生物",
}


@dataclass
class WeekdayConfig:
    enable_binding_chem_bio: bool = True
    enable_no_am1_am4: bool = True
    enable_no_consecutive_same_teacher_same_class: bool = True
    enable_head_pm1_min: bool = True
    enable_teacher_weekday_am_pm_presence: bool = True
    enable_pref_lang_am: bool = True
    enable_reduce_stem_am1: bool = True
    enable_teacher_am1_fragmentation: bool = True
    enable_two_class_daily_min_per_class: bool = True
    enable_two_class_low_hours_max_empty_days: bool = True
    enable_low_weekday_subject_max1_per_day: bool = True
    enable_high_weekday_subject_min1_per_day: bool = True
    enable_multi_class_halfday: bool = True
    enable_teacher_am4_pm1_threshold_penalty: bool = True
    enable_teacher_continuity_penalty: bool = True
    enable_teacher_m1_cap_constraint: bool = True
    enable_balance_weekday_subject_hours: bool = True
    enable_core_teacher_day_load_limit: bool = True
    enable_am1_pm1_mutex: bool = True
    am1_pm1_mutex_mode: str = "hard"  # soft|hard
    w_am1_pm1_mutex: int = 3000
    enable_two_class_am1_pm1_combo: bool = True
    two_class_am1_pm1_combo_mode: str = "hard"  # soft|hard
    w_two_class_am1_pm1_combo: int = 3000
    enable_am1_pm1_exclusive: bool = True
    am1_pm1_exclusive_mode: str = "hard"  # soft|hard
    w_am1_pm1_exclusive: int = 3000
    enable_single_class_weekly_am1_cap: bool = True
    single_class_weekly_am1_cap_max: int = 2
    balance_weekday_subject_hours_mode: str = "soft"  # soft|hard
    core_teacher_day_load_max: int = 3
    w_lang_pm_penalty: int = 200
    w_lang_am_reward: int = 0
    enable_lang_tue_fri_preferences: bool = True
    enable_lang_tue_fri_am1_penalty_exempt: bool = True
    lang_tue_fri_target_teachers: List[str] | None = None
    w_lang_tue_fri_am1_reward: int = 200
    w_lang_tue_fri_pm1_penalty: int = 4500
    w_lang_tue_fri_pm2_penalty: int = 3000
    w_lang_tue_fri_pm3_penalty: int = 2000
    w_stem_am1_penalty: int = 250
    w_teacher_only_am1_day: int = 300
    k_teacher_am1_week: int = 2
    w_teacher_am1_excess: int = 150
    w_two_class_daily_min_per_class: int = 300
    two_class_low_hours_threshold: int = 5
    two_class_max_empty_days: int = 1
    low_weekday_subject_max1_threshold: int = 4
    high_weekday_subject_min1_threshold: int = 5
    two_class_daily_min_mode: str = "soft"  # soft|hard
    weight_multi_class_halfday: int = 300
    teacher_am4_pm1_w3: int = 50
    teacher_am4_pm1_w4: int = 100
    teacher_am4_pm1_w5: int = 200
    teacher_am4_pm1_w6: int = 400
    teacher_continuity_gap_weight: int = 250
    teacher_m1_cap_max: int = 3
    w_hit_m1_cap: int = 500
    weight_balance_weekday_subject_hours: int = 150


@dataclass
class AuditInfo:
    days: List[str]
    periods: List[str]
    am_periods: List[str]
    pm_periods: List[str]
    mapping: Dict[str, str]
    head_teacher_source: str


def normalize_subject(name: str) -> str:
    """学科名称归一化，统一别名到主名。"""
    return SUBJ_ALIAS.get(str(name).strip(), str(name).strip())


def is_lang_subject(name: str) -> bool:
    """是否为语文/外语学科。"""
    return normalize_subject(name) in ("语文", "外语")


def is_stem_subject(name: str) -> bool:
    """是否为数理化学科。"""
    return normalize_subject(name) in ("数学", "物理", "化学")


def is_pe_or_tech_subject(name: str) -> bool:
    """是否为体育/技术学科。"""
    return normalize_subject(name) in ("体育", "技术")


def _slot_key(slot: Slot) -> str:
    """将 Slot 转为统一的 block+period 口径。"""
    return f"{slot.block}{slot.period}"


def _is_weekday(day: str) -> bool:
    """是否工作日。"""
    return day in WEEKDAYS


def _is_am(slot: Slot) -> bool:
    """是否上午或早自习。"""
    return slot.block in ("早自习", "上午")


def _is_pm(slot: Slot) -> bool:
    """是否下午。"""
    return slot.block == "下午"


def _is_daytime(slot: Slot) -> bool:
    """是否白天课（仅上午/下午；不含早自习与夜间时段）。"""
    return slot.block in ("上午", "下午")


def _is_am1(slot: Slot) -> bool:
    """是否上午第一节。"""
    return slot.block == "上午" and int(slot.period) == 1


def _is_am4(slot: Slot) -> bool:
    """是否上午第四节。"""
    return slot.block == "上午" and int(slot.period) == 4


def _is_pm1(slot: Slot) -> bool:
    """是否下午第一节。"""
    return slot.block == "下午" and int(slot.period) == 1


def _slot_order_key(slot: Slot) -> Tuple[int, int]:
    """为 Slot 提供排序键，保证早自习在上午之前。"""
    if slot.block == "早自习":
        return (0, 0)
    if slot.block == "上午":
        return (1, int(slot.period))
    if slot.block == "下午":
        return (2, int(slot.period))
    return (99, int(slot.period))


def _and2(model: cp_model.CpModel, a, b, name: str):
    """构造 a AND b 的布尔变量。"""
    z = model.NewBoolVar(name)
    model.Add(z <= a)
    model.Add(z <= b)
    model.Add(z >= a + b - 1)
    return z


def _norm_mode(mode: str | None, default: str = "hard") -> str:
    m = str(mode or default).strip().lower()
    if m not in {"soft", "hard"}:
        return default
    return m


def _build_teacher_day_slot_presence(
    model: cp_model.CpModel,
    data: DayInputData,
    dv: DayVars,
    *,
    days: Tuple[str, ...] | List[str],
    slot_predicate,
) -> Dict[Tuple[str, str], cp_model.IntVar]:
    """
    构造 teacher/day 是否命中某节次口径的布尔量（含 fixed_assign）。
    返回：presence[(teacher, day)] -> BoolVar
    """
    teacher_day_vars: Dict[Tuple[str, str], List[cp_model.IntVar]] = {}
    fixed_hits: Dict[Tuple[str, str], int] = {}
    teachers = sorted({t for t in data.cls_subj_teacher.values() if t})

    for (cls, subj, slot), var in dv.x.items():
        if slot.day not in days or not slot_predicate(slot):
            continue
        teacher = data.cls_subj_teacher.get((cls, subj))
        if not teacher:
            continue
        teacher_day_vars.setdefault((teacher, slot.day), []).append(var)

    for (cls, slot), subj in data.fixed_assign.items():
        if slot.day not in days or not slot_predicate(slot):
            continue
        teacher = data.cls_subj_teacher.get((cls, subj))
        if not teacher:
            continue
        fixed_hits[(teacher, slot.day)] = fixed_hits.get((teacher, slot.day), 0) + 1

    out: Dict[Tuple[str, str], cp_model.IntVar] = {}
    for t in teachers:
        for d in days:
            b = model.NewBoolVar(f"slot_presence[{t},{d}]")
            fixed = fixed_hits.get((t, d), 0)
            vars_list = teacher_day_vars.get((t, d), [])
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


def _collect_periods(data: DayInputData) -> Tuple[List[str], List[str], List[str]]:
    """汇总工作日节次、上午节次、下午节次。"""
    all_periods = sorted({_slot_key(s) for s in data.available_slots})
    am = sorted({_slot_key(s) for s in data.available_slots if _is_am(s)})
    pm = sorted({_slot_key(s) for s in data.available_slots if _is_pm(s)})
    return all_periods, am, pm


def load_head_teachers(io_cfg: dict, base_dir: Path) -> List[str]:
    """从教师定位表读取班主任名单。"""
    _class_col, head_col, _gender_col = configured_teacher_table_columns(io_cfg)
    df = load_teacher_table_frame(io_cfg, base_dir)
    # 班主任是值班/查寝附加信息，没有这一列时仍可进行课程排课。
    if df.empty or head_col not in df.columns:
        return []
    heads = []
    for v in df[head_col].tolist():
        if pd.isna(v):
            continue
        s = str(v).strip()
        if s:
            heads.append(s)
    return sorted(set(heads))


def build_audit_before(data: DayInputData, io_cfg: dict, base_dir: Path) -> AuditInfo:
    """构建工作日约束前置审计信息。"""
    days = sorted({s.day for s in data.available_slots})
    periods, am, pm = _collect_periods(data)
    mapping = {k: v for k, v in SUBJ_ALIAS.items() if k != v}
    head_src = f"{io_cfg.get('teacher_table', {}).get('path', '教师定位表.xlsx')}::{io_cfg.get('teacher_table', {}).get('columns', {}).get('head', '班主任')}"
    return AuditInfo(days=days, periods=periods, am_periods=am, pm_periods=pm, mapping=mapping, head_teacher_source=head_src)


def write_audit_before(out_dir: Path, info: AuditInfo) -> None:
    """写出白天工作日约束的前置审计信息。

    说明：
    - 记录天列表、节次列表、上午下午划分与学科归一化映射。
    - 便于在诊断文件中定位规则口径与数据是否匹配。
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "day_constraints_audit_before.txt"
    lines = ["[Day Constraints Audit Before]"]
    lines.append(f"Days={info.days}")
    lines.append(f"Periods={info.periods}")
    lines.append(f"AM={info.am_periods}")
    lines.append(f"PM={info.pm_periods}")
    lines.append(f"Mapping={info.mapping}")
    lines.append(f"HeadTeacherSource={info.head_teacher_source}")
    path.write_text("\n".join(lines), encoding="utf-8")

def write_soft_timepref_audit(
    out_dir: Path,
    data: DayInputData,
) -> None:
    """写出时间偏好软约束的前置审计信息。

    记录 AM/PM/AM1 的节次映射与学科归一化口径，便于排查偏好类规则。
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "day_soft_timepref_audit.txt"
    am = sorted({_slot_key(s) for s in data.available_slots if s.block == "上午"})
    pm = sorted({_slot_key(s) for s in data.available_slots if s.block == "下午"})
    am1 = [p for p in am if p.endswith("1")]

    mapping = {"英语": "外语"}
    lines = ["[Day Soft Time Preference Audit]"]
    lines.append(f"AM={am}")
    lines.append(f"PM={pm}")
    lines.append(f"AM1={am1}")
    lines.append(f"SubjectMapping={mapping}")
    lines.append("LangSubjects=['语文','外语']")
    lines.append("StemSubjects=['数学','物理','化学']")
    path.write_text("\n".join(lines), encoding="utf-8")


def get_pe_teachers(data: DayInputData) -> Set[str]:
    """统计体育/技术教师集合。"""
    pe_teachers: Set[str] = set()
    for (cls, subj), tch in data.cls_subj_teacher.items():
        if is_pe_or_tech_subject(subj):
            pe_teachers.add(tch)
    return pe_teachers


def get_lang_teachers(data: DayInputData) -> Set[str]:
    """统计语文/外语教师集合。"""
    lang_teachers: Set[str] = set()
    for (cls, subj), tch in data.cls_subj_teacher.items():
        if is_lang_subject(subj) and tch:
            lang_teachers.add(tch)
    return lang_teachers


def get_core_subject_teachers(data: DayInputData) -> Set[str]:
    """统计九大学科教师集合（语数外理化生史地政）。"""
    teachers: Set[str] = set()
    for (cls, subj), tch in data.cls_subj_teacher.items():
        if normalize_subject(subj) in CORE_SUBJECTS and tch:
            teachers.add(tch)
    return teachers


def _teacher_weekday_required_hours(
    data: DayInputData,
    target_teachers: Set[str],
) -> Dict[str, int]:
    """按 teacher 汇总“周一到周五白天”需求课时（req_hours 的 weekday 分量）。"""
    out: Dict[str, int] = {t: 0 for t in target_teachers}
    for (cls, subj), teacher in data.cls_subj_teacher.items():
        if teacher not in target_teachers:
            continue
        if normalize_subject(subj) not in CORE_SUBJECTS:
            continue
        _early, weekday_hours, _weekend = data.req_hours.get((cls, subj), (0, 0, 0))
        out[teacher] = out.get(teacher, 0) + int(weekday_hours)
    return out


def _collect_teacher_vars(
    data: DayInputData,
    dv: DayVars,
    exclude_pe_tech: bool = True,
) -> Dict[str, Dict[str, Dict[Slot, List[cp_model.IntVar]]]]:
    """按教师汇总工作日授课变量，必要时排除体育/技术。"""
    out: Dict[str, Dict[str, Dict[Slot, List[cp_model.IntVar]]]] = {}
    for (cls, subj, slot), var in dv.x.items():
        if exclude_pe_tech and is_pe_or_tech_subject(subj):
            continue
        teacher = data.cls_subj_teacher.get((cls, subj))
        if not teacher:
            continue
        if not _is_weekday(slot.day):
            continue
        out.setdefault(teacher, {}).setdefault(slot.day, {}).setdefault(slot, []).append(var)
    return out


def apply_teacher_continuity_penalty(
    model: cp_model.CpModel,
    data: DayInputData,
    dv: DayVars,
    pe_teachers: Set[str],
    weight: int = 1,
) -> Tuple[List[cp_model.IntVar], Dict[Tuple[str, str, str], List[cp_model.IntVar]]]:
    """
    教师半天内“1-0-1”空档惩罚（软约束）。
    返回 penalties 与 gap 明细；权重在 day.weekday_constraints.teacher_continuity_gap_weight。
    """
    penalties: List[cp_model.IntVar] = []
    details: Dict[Tuple[str, str, str], List[cp_model.IntVar]] = {}

    teacher_vars = _collect_teacher_vars(data, dv, exclude_pe_tech=True)

    for t, days in teacher_vars.items():
        if t in pe_teachers:
            continue
        for day, slots_map in days.items():
            if day not in WEEKDAYS:
                continue

            am_slots = sorted([s for s in slots_map.keys() if _is_am(s)], key=_slot_order_key)
            pm_slots = sorted([s for s in slots_map.keys() if _is_pm(s)], key=_slot_order_key)

            def build_gap_for_half(half_slots: List[Slot], tag: str) -> None:
                if not half_slots:
                    return

                # busy var per slot (sum of vars in that slot)
                busy = []
                for s in half_slots:
                    vars_list = slots_map.get(s, [])
                    if vars_list:
                        b = model.NewBoolVar(f"busy[{t},{day},{_slot_key(s)}]")
                        model.Add(sum(vars_list) == b)
                    else:
                        b = model.NewBoolVar(f"busy[{t},{day},{_slot_key(s)}]")
                        model.Add(b == 0)
                    busy.append(b)

                gap_vars: List[cp_model.IntVar] = []

                if len(busy) >= 3:
                    for i in range(len(busy) - 2):
                        b1, b2, b3 = busy[i], busy[i + 1], busy[i + 2]
                        gap = model.NewBoolVar(f"gap[{t},{day},{tag},{i}]")
                        model.Add(gap <= b1)
                        model.Add(gap <= b3)
                        model.Add(gap <= 1 - b2)
                        model.Add(gap >= b1 + b3 - b2 - 1)
                        gap_vars.append(gap)
                        penalties.append(gap)  # weight: day.weekday_constraints.teacher_continuity_gap_weight（建议 50~400）
                        register(
                            rule_id="teacher_continuity_gap",
                            rule_name="教师半天连续性空档",
                            weight=weight,
                            var=gap,
                            teacher=t,
                            day=day,
                            slot=tag,
                        )
                else:
                    # 退化：相邻空档惩罚（1-0）
                    for i in range(len(busy) - 1):
                        b1, b2 = busy[i], busy[i + 1]
                        gap = model.NewBoolVar(f"gap_adj[{t},{day},{tag},{i}]")
                        model.Add(gap <= b1)
                        model.Add(gap <= 1 - b2)
                        model.Add(gap >= b1 - b2)
                        gap_vars.append(gap)
                        penalties.append(gap)  # weight: day.weekday_constraints.teacher_continuity_gap_weight（建议 50~400）
                        register(
                            rule_id="teacher_continuity_gap",
                            rule_name="教师半天连续性空档",
                            weight=weight,
                            var=gap,
                            teacher=t,
                            day=day,
                            slot=tag,
                        )

                if gap_vars:
                    details[(t, day, tag)] = gap_vars

            build_gap_for_half(am_slots, "AM")
            build_gap_for_half(pm_slots, "PM")

    return penalties, details


def apply_teacher_m1_cap_constraint(
    model: cp_model.CpModel,
    data: DayInputData,
    dv: DayVars,
    max_m1: int = 3,
    weight: int = 1,
    am1_penalty_exempt_teacher_days: Set[Tuple[str, str]] | None = None,
) -> Tuple[
    List[cp_model.IntVar],
    Dict[str, Tuple[cp_model.IntVar, cp_model.IntVar, Dict[str, cp_model.IntVar], int]],
    Dict[str, int],
]:
    """教师上午1约束（周一到周五）。

    - 硬约束：每位教师周一到周五上午1累计 <= max_m1
    - 软约束：累计 == max_m1 时触发高罚分 hit（鼓励 <= max_m1-1）
    """
    penalties: List[cp_model.IntVar] = []
    details: Dict[str, Tuple[cp_model.IntVar, cp_model.IntVar, Dict[str, cp_model.IntVar], int]] = {}
    structural_impossible: Dict[str, int] = {}

    teachers = sorted({t for t in data.cls_subj_teacher.values() if t})

    # teacher/day AM1 variables
    teacher_day_am1_vars: Dict[Tuple[str, str], List[cp_model.IntVar]] = {}
    for (cls, subj, slot), var in dv.x.items():
        teacher = data.cls_subj_teacher.get((cls, subj))
        if not teacher:
            continue
        if slot.day not in WEEKDAYS:
            continue
        if not _is_am1(slot):
            continue
        teacher_day_am1_vars.setdefault((teacher, slot.day), []).append(var)

    # fixed AM1 lower bound by teacher/day
    fixed_by_teacher_day: Dict[Tuple[str, str], int] = {}
    fixed_total_by_teacher: Dict[str, int] = {}
    for (cls, slot), subj in data.fixed_assign.items():
        if slot.day not in WEEKDAYS:
            continue
        if not _is_am1(slot):
            continue
        teacher = data.cls_subj_teacher.get((cls, subj))
        if not teacher:
            continue
        key = (teacher, slot.day)
        fixed_by_teacher_day[key] = fixed_by_teacher_day.get(key, 0) + 1
        fixed_total_by_teacher[teacher] = fixed_total_by_teacher.get(teacher, 0) + 1

    exempt_teacher_days = am1_penalty_exempt_teacher_days or set()

    for teacher in teachers:
        occ_by_day: Dict[str, cp_model.IntVar] = {}
        for day in WEEKDAYS:
            occ = model.NewBoolVar(f"occ_m1[{teacher},{day}]")
            fixed = fixed_by_teacher_day.get((teacher, day), 0)
            vars_list = teacher_day_am1_vars.get((teacher, day), [])
            if fixed > 0:
                model.Add(occ == 1)
            elif vars_list:
                for v in vars_list:
                    model.Add(occ >= v)
                model.Add(occ <= sum(vars_list))
            else:
                model.Add(occ == 0)
            occ_by_day[day] = occ

        m1_total = model.NewIntVar(0, len(WEEKDAYS), f"m1_total[{teacher}]")
        model.Add(m1_total == sum(occ_by_day[d] for d in WEEKDAYS))
        model.Add(m1_total <= max_m1)

        hit_cap = model.NewBoolVar(f"hit_m1_cap[{teacher}]")
        penalty_days = [d for d in WEEKDAYS if (teacher, d) not in exempt_teacher_days]
        if penalty_days:
            m1_penalty_total = model.NewIntVar(0, len(penalty_days), f"m1_penalty_total[{teacher}]")
            model.Add(m1_penalty_total == sum(occ_by_day[d] for d in penalty_days))
            model.Add(m1_penalty_total == max_m1).OnlyEnforceIf(hit_cap)
            model.Add(m1_penalty_total != max_m1).OnlyEnforceIf(hit_cap.Not())
        else:
            model.Add(hit_cap == 0)

        penalties.append(hit_cap)
        register(
            rule_id="teacher_m1_hit_cap",
            rule_name="教师周中上午1达到上限惩罚",
            weight=weight,
            var=hit_cap,
            teacher=teacher,
        )

        fixed_total = fixed_total_by_teacher.get(teacher, 0)
        if fixed_total > max_m1:
            structural_impossible[teacher] = fixed_total
        details[teacher] = (m1_total, hit_cap, occ_by_day, fixed_total)

    return penalties, details, structural_impossible


def apply_no_consecutive_same_teacher_same_class(
    model: cp_model.CpModel,
    data: DayInputData,
    dv: DayVars,
) -> None:
    """同一教师同一班级相邻节次不得连上（硬约束）。"""
    # 预构建 teacher-class-slot -> vars
    tcs_vars: Dict[Tuple[str, str, Slot], List[cp_model.IntVar]] = {}
    for (cls, subj, slot), var in dv.x.items():
        if not _is_weekday(slot.day):
            continue
        teacher = data.cls_subj_teacher.get((cls, subj))
        if not teacher:
            continue
        tcs_vars.setdefault((teacher, cls, slot), []).append(var)

    # 每个班每天按时序检查相邻节次
    for cls in data.classes:
        for day in WEEKDAYS:
            slots = [s for s in data.available_slots if s.day == day and s.block in ("上午", "下午")]
            slots.sort(key=_slot_order_key)
            if len(slots) < 2:
                continue

            # 构建当天该班涉及到的教师集合
            teachers = set()
            for (c, subj), tch in data.cls_subj_teacher.items():
                if c == cls:
                    teachers.add(tch)

            for t in teachers:
                for i in range(len(slots) - 1):
                    s1, s2 = slots[i], slots[i + 1]

                    def slot_expr(slot: Slot):
                        # 固定课位
                        if (cls, slot) in data.fixed_assign:
                            subj = data.fixed_assign[(cls, slot)]
                            t_fixed = data.cls_subj_teacher.get((cls, subj))
                            return 1 if t_fixed == t else 0
                        # 变量课位
                        vars_list = tcs_vars.get((t, cls, slot), [])
                        return sum(vars_list) if vars_list else 0

                    e1 = slot_expr(s1)
                    e2 = slot_expr(s2)
                    model.Add(e1 + e2 <= 1)


def apply_binding_8_chem_9_bio(model: cp_model.CpModel, data: DayInputData, dv: DayVars) -> None:
    """兼容入口：8班化学与9班生物全局白天绑定（含周末）。"""
    apply_global_day_binding_8_chem_9_bio(model, data, dv)


def apply_no_am1_am4(model: cp_model.CpModel, data: DayInputData, dv: DayVars, pe_teachers: Set[str]) -> None:
    """禁止同一教师同一天 AM1 + AM4（非体育/技术）（硬约束）。"""
    teacher_vars = _collect_teacher_vars(data, dv, exclude_pe_tech=True)
    for teacher, days in teacher_vars.items():
        if teacher in pe_teachers:
            continue
        for day, slots in days.items():
            am1 = sum(v for s, vars_list in slots.items() if _is_am1(s) for v in vars_list)
            am4 = sum(v for s, vars_list in slots.items() if _is_am4(s) for v in vars_list)
            model.Add(am1 + am4 <= 1)


def apply_core_subject_teacher_day_load_and_no_am1_am4(
    model: cp_model.CpModel,
    data: DayInputData,
    dv: DayVars,
    max_per_day: int = 3,
) -> Dict[str, object]:
    """新增硬约束（仅九大学科教师，且仅周一到周五白天时段）。

    约束15：每位目标教师每天白天课时 <= max_per_day（默认3）。
    约束16：同一天禁止“上午1 + 上午4”同时出现。
    """
    target_teachers = get_core_subject_teachers(data)

    # teacher/day/slot -> vars（仅周一到周五 + 上午/下午）
    teacher_slots: Dict[str, Dict[str, Dict[Slot, List[cp_model.IntVar]]]] = {}
    for (cls, subj, slot), var in dv.x.items():
        if not _is_weekday(slot.day):
            continue
        if not _is_daytime(slot):
            continue
        teacher = data.cls_subj_teacher.get((cls, subj))
        if teacher not in target_teachers:
            continue
        teacher_slots.setdefault(teacher, {}).setdefault(slot.day, {}).setdefault(slot, []).append(var)

    # 固定课位统计（同口径）
    fixed_counts: Dict[Tuple[str, str, str], int] = {}
    for (cls, slot), subj in data.fixed_assign.items():
        if not _is_weekday(slot.day):
            continue
        if not _is_daytime(slot):
            continue
        teacher = data.cls_subj_teacher.get((cls, subj))
        if teacher not in target_teachers:
            continue
        key = (teacher, slot.day, _slot_key(slot))
        fixed_counts[key] = fixed_counts.get(key, 0) + 1

    for teacher in sorted(target_teachers):
        for day in WEEKDAYS:
            slots = teacher_slots.get(teacher, {}).get(day, {})
            day_vars = [v for vars_list in slots.values() for v in vars_list]
            day_fixed = sum(v for (t, d, _k), v in fixed_counts.items() if t == teacher and d == day)
            model.Add(sum(day_vars) + day_fixed <= max_per_day)

            am1_vars = [v for s, vars_list in slots.items() if _is_am1(s) for v in vars_list]
            am4_vars = [v for s, vars_list in slots.items() if _is_am4(s) for v in vars_list]
            am1_fixed = sum(v for (t, d, k), v in fixed_counts.items() if t == teacher and d == day and k == "上午1")
            am4_fixed = sum(v for (t, d, k), v in fixed_counts.items() if t == teacher and d == day and k == "上午4")
            model.Add(sum(am1_vars) + am1_fixed + sum(am4_vars) + am4_fixed <= 1)

    required_hours = _teacher_weekday_required_hours(data, target_teachers)
    impossible_teachers = sorted(
        [t for t, h in required_hours.items() if h > max_per_day * len(WEEKDAYS)],
        key=lambda t: (-required_hours[t], t),
    )

    return {
        "target_teachers": sorted(target_teachers),
        "teacher_slots": teacher_slots,
        "fixed_counts": fixed_counts,
        "required_hours": required_hours,
        "max_per_day": max_per_day,
        "impossible_teachers": impossible_teachers,
    }


def apply_head_pm1_min(model: cp_model.CpModel, data: DayInputData, dv: DayVars, head_teachers: List[str]) -> None:
    """每天 PM1 至少 3 位班主任上课（硬约束）。"""
    teacher_vars = _collect_teacher_vars(data, dv, exclude_pe_tech=True)
    for day in WEEKDAYS:
        cnt = []
        for t in head_teachers:
            slots = teacher_vars.get(t, {}).get(day, {})
            pm1_vars = [v for s, vars_list in slots.items() if _is_pm1(s) for v in vars_list]
            if pm1_vars:
                cnt.append(sum(pm1_vars))
        if cnt:
            model.Add(sum(cnt) >= 3)
        else:
            model.Add(0 >= 3)


def apply_teacher_weekday_am_pm_presence(
    model: cp_model.CpModel,
    data: DayInputData,
    dv: DayVars,
    pe_teachers: Set[str],
) -> None:
    """工作日教师上午/下午至少一边有课（硬约束，豁免体育/技术）。"""
    teacher_vars = _collect_teacher_vars(data, dv, exclude_pe_tech=True)

    teachers: Set[str] = set(teacher_vars.keys())
    for (cls, slot), subj in data.fixed_assign.items():
        if not _is_weekday(slot.day):
            continue
        tch = data.cls_subj_teacher.get((cls, subj))
        if tch:
            teachers.add(tch)

    for tch in teachers:
        if tch in pe_teachers:
            continue

        am_vars: List[cp_model.IntVar] = []
        pm_vars: List[cp_model.IntVar] = []
        for day in WEEKDAYS:
            slots = teacher_vars.get(tch, {}).get(day, {})
            am_vars.extend(v for s, vars_list in slots.items() if _is_am(s) for v in vars_list)
            pm_vars.extend(v for s, vars_list in slots.items() if _is_pm(s) for v in vars_list)

        am_fixed = 0
        pm_fixed = 0
        for (cls, slot), subj in data.fixed_assign.items():
            if not _is_weekday(slot.day):
                continue
            t_fixed = data.cls_subj_teacher.get((cls, subj))
            if t_fixed != tch:
                continue
            if _is_am(slot):
                am_fixed += 1
            if _is_pm(slot):
                pm_fixed += 1

        total_possible = len(am_vars) + len(pm_vars) + am_fixed + pm_fixed
        if total_possible == 0:
            continue

        model.Add(sum(am_vars) + am_fixed >= 1)
        model.Add(sum(pm_vars) + pm_fixed >= 1)


def apply_pref_lang_am(
    model: cp_model.CpModel,
    data: DayInputData,
    dv: DayVars,
    *,
    enabled: bool = True,
    target_teachers: Set[str] | None = None,
) -> Tuple[List[cp_model.IntVar], List[cp_model.IntVar], List[cp_model.IntVar], List[cp_model.IntVar]]:
    """
    语文/外语教师周二到周五节次偏好变量：
    - 上午1：奖励
    - 下午1：高惩罚
    - 下午2：中惩罚
    - 下午3：较低惩罚
    """
    if not enabled:
        return [], [], [], []

    am1_vars: List[cp_model.IntVar] = []
    pm1_vars: List[cp_model.IntVar] = []
    pm2_vars: List[cp_model.IntVar] = []
    pm3_vars: List[cp_model.IntVar] = []

    norm_targets = {str(t).strip() for t in (target_teachers or set()) if str(t).strip()}

    for (cls, subj, slot), var in dv.x.items():
        if slot.day not in TUE_TO_FRI:
            continue
        if not is_lang_subject(subj):
            continue
        if norm_targets:
            teacher = str(data.cls_subj_teacher.get((cls, subj), "")).strip()
            if teacher not in norm_targets:
                continue
        if _is_am1(slot):
            am1_vars.append(var)
        elif slot.block == "下午" and int(slot.period) == 1:
            pm1_vars.append(var)
        elif slot.block == "下午" and int(slot.period) == 2:
            pm2_vars.append(var)
        elif slot.block == "下午" and int(slot.period) == 3:
            pm3_vars.append(var)

    return am1_vars, pm1_vars, pm2_vars, pm3_vars


def apply_reduce_stem_am1(
    model: cp_model.CpModel,
    data: DayInputData,
    dv: DayVars,
    weight: int,
) -> Tuple[List[cp_model.IntVar], int]:
    """数理化减少 AM1（软约束）；权重在 day.weekday_constraints.w_stem_am1_penalty。"""
    am1_vars: List[cp_model.IntVar] = []
    am1_fixed = 0

    for (cls, subj, slot), var in dv.x.items():
        if not _is_weekday(slot.day):
            continue
        if not is_stem_subject(subj):
            continue
        if _is_am1(slot):
            am1_vars.append(var)
            register(
                rule_id="stem_am1_penalty",
                rule_name="理科AM1减少",
                weight=weight,
                var=var,
                teacher=data.cls_subj_teacher.get((cls, subj)),
                day=slot.day,
                slot=_slot_key(slot),
                cls=cls,
                subj=subj,
            )

    for (cls, slot), subj in data.fixed_assign.items():
        if not _is_weekday(slot.day):
            continue
        if not is_stem_subject(subj):
            continue
        if _is_am1(slot):
            am1_fixed += 1

    return am1_vars, am1_fixed


def apply_teacher_am1_fragmentation(
    model: cp_model.CpModel,
    data: DayInputData,
    dv: DayVars,
    pe_teachers: Set[str],
    k_week: int,
    w_only_am1: int,
    w_am1_excess: int,
    am1_penalty_exempt_teacher_days: Set[Tuple[str, str]] | None = None,
) -> Tuple[List[cp_model.IntVar], List[cp_model.IntVar], Dict[str, Tuple[cp_model.IntVar, int, cp_model.IntVar, cp_model.IntVar]]]:
    """教师碎片化（只上 AM1 与 AM1 过多）惩罚；权重在 day.weekday_constraints.w_teacher_only_am1_day / w_teacher_am1_excess。"""
    only_am1_penalties: List[cp_model.IntVar] = []
    excess_penalties: List[cp_model.IntVar] = []
    details: Dict[str, Tuple[cp_model.IntVar, int, cp_model.IntVar, cp_model.IntVar]] = {}

    teacher_vars = _collect_teacher_vars(data, dv, exclude_pe_tech=True)
    exempt_teacher_days = am1_penalty_exempt_teacher_days or set()
    teachers: Set[str] = set(teacher_vars.keys())
    for (cls, slot), subj in data.fixed_assign.items():
        if not _is_weekday(slot.day):
            continue
        tch = data.cls_subj_teacher.get((cls, subj))
        if tch:
            teachers.add(tch)

    for tch in sorted(teachers):
        if tch in pe_teachers:
            continue
        only_am1_count = model.NewIntVar(0, len(WEEKDAYS), f"only_am1_days[{tch}]")
        only_am1_vars: List[cp_model.IntVar] = []

        am1_vars_week: List[cp_model.IntVar] = []
        am1_fixed_week = 0
        am1_vars_penalty_week: List[cp_model.IntVar] = []
        am1_fixed_penalty_week = 0

        for day in WEEKDAYS:
            slots = teacher_vars.get(tch, {}).get(day, {})
            am1_vars = [v for s, vars_list in slots.items() if _is_am1(s) for v in vars_list]
            non_am1_vars = [
                v
                for s, vars_list in slots.items()
                if s.block in ("上午", "下午") and not _is_am1(s)
                for v in vars_list
            ]

            am1_fixed = 0
            non_am1_fixed = 0
            for (cls, slot), subj in data.fixed_assign.items():
                if slot.day != day:
                    continue
                t_fixed = data.cls_subj_teacher.get((cls, subj))
                if t_fixed != tch:
                    continue
                if _is_am1(slot):
                    am1_fixed += 1
                elif slot.block in ("上午", "下午"):
                    non_am1_fixed += 1

            am1_vars_week.extend(am1_vars)
            am1_fixed_week += am1_fixed
            is_penalty_exempt = (tch, day) in exempt_teacher_days
            if not is_penalty_exempt:
                am1_vars_penalty_week.extend(am1_vars)
                am1_fixed_penalty_week += am1_fixed

            am1_busy = model.NewBoolVar(f"am1_busy[{tch},{day}]")
            if am1_fixed > 0:
                model.Add(am1_busy == 1)
            elif am1_vars:
                model.Add(sum(am1_vars) >= am1_busy)
                for v in am1_vars:
                    model.Add(v <= am1_busy)
            else:
                model.Add(am1_busy == 0)

            has_non_am1 = model.NewBoolVar(f"has_non_am1[{tch},{day}]")
            if non_am1_fixed > 0:
                model.Add(has_non_am1 == 1)
            elif non_am1_vars:
                model.Add(sum(non_am1_vars) >= has_non_am1)
                for v in non_am1_vars:
                    model.Add(v <= has_non_am1)
            else:
                model.Add(has_non_am1 == 0)

            only_am1 = model.NewBoolVar(f"only_am1[{tch},{day}]")
            model.Add(only_am1 <= am1_busy)
            model.Add(only_am1 <= 1 - has_non_am1)
            model.Add(only_am1 >= am1_busy - has_non_am1)
            only_am1_vars.append(only_am1)
            if not is_penalty_exempt:
                only_am1_penalties.append(only_am1)  # weight: day.weekday_constraints.w_teacher_only_am1_day（建议 100~400）
                register(
                    rule_id="teacher_only_am1_day",
                    rule_name="教师仅AM1碎片化",
                    weight=w_only_am1,
                    var=only_am1,
                    teacher=tch,
                    day=day,
                )

        if only_am1_vars:
            model.Add(only_am1_count == sum(only_am1_vars))
        else:
            model.Add(only_am1_count == 0)

        max_am1 = len(am1_vars_penalty_week) + am1_fixed_penalty_week
        if max_am1 > 0:
            am1_cnt = model.NewIntVar(0, max_am1, f"am1_cnt[{tch}]")
            model.Add(am1_cnt == sum(am1_vars_penalty_week) + am1_fixed_penalty_week)
            excess = model.NewIntVar(0, max_am1, f"am1_excess[{tch}]")
            model.Add(excess >= am1_cnt - k_week)
            excess_penalties.append(excess)  # weight: day.weekday_constraints.w_teacher_am1_excess（建议 50~300）
            register(
                rule_id="teacher_am1_excess",
                rule_name="教师AM1周超额",
                weight=w_am1_excess,
                var=excess,
                teacher=tch,
            )
            details[tch] = (am1_cnt, am1_fixed_penalty_week, only_am1_count, excess)

    return only_am1_penalties, excess_penalties, details


def apply_two_class_daily_min_per_class(
    model: cp_model.CpModel,
    data: DayInputData,
    dv: DayVars,
    pe_teachers: Set[str],
    mode: str,
    w_soft: int = 300,
) -> Tuple[List[cp_model.IntVar], Dict[Tuple[str, str, str], cp_model.IntVar]]:
    """代双班教师：当天上课则每班至少一节（soft/hard 可切换）。"""
    penalties: List[cp_model.IntVar] = []
    details: Dict[Tuple[str, str, str], cp_model.IntVar] = {}

    # teacher -> classes he teaches (non PE/tech)
    tch_classes: Dict[str, Set[str]] = {}
    for (cls, subj), tch in data.cls_subj_teacher.items():
        if is_pe_or_tech_subject(subj):
            continue
        tch_classes.setdefault(tch, set()).add(cls)

    for tch, cls_set in tch_classes.items():
        if tch in pe_teachers or len(cls_set) != 2:
            continue
        for day in WEEKDAYS:
            # collect vars per class
            has_any = model.NewBoolVar(f"two_cls_any[{tch},{day}]")
            any_vars = []
            for cls in cls_set:
                vars_list = [
                    v
                    for (c, subj, slot), v in dv.x.items()
                    if c == cls and slot.day == day and data.cls_subj_teacher.get((c, subj)) == tch
                ]
                if not vars_list:
                    has_cls = model.NewBoolVar(f"two_cls_has[{tch},{day},{cls}]")
                    model.Add(has_cls == 0)
                else:
                    has_cls = model.NewBoolVar(f"two_cls_has[{tch},{day},{cls}]")
                    model.Add(sum(vars_list) >= has_cls)
                    for v in vars_list:
                        model.Add(v <= has_cls)
                    any_vars.extend(vars_list)

                if mode == "hard":
                    model.Add(has_cls >= has_any)
                else:
                    viol = model.NewBoolVar(f"two_cls_vio[{tch},{day},{cls}]")
                    model.Add(viol <= has_any)
                    model.Add(viol <= 1 - has_cls)
                    model.Add(viol >= has_any - has_cls)
                    penalties.append(viol)  # weight: day.weekday_constraints.w_two_class_daily_min_per_class（soft 模式）
                    details[(tch, day, cls)] = viol
                    register(
                        "two_class_daily_min_per_class",
                        "双班教师当天两班至少各1节",
                        w_soft,
                        viol,
                        teacher=tch,
                        cls=cls,
                        day=day,
                        source_module="scheduler/model/constraints/day_weekday_constraints.py",
                        constraint_category="fairness",
                        mode="soft",
                        weight_key="day.weekday_constraints.w_two_class_daily_min_per_class",
                    )

            if any_vars:
                model.Add(sum(any_vars) >= has_any)
                for v in any_vars:
                    model.Add(v <= has_any)
            else:
                model.Add(has_any == 0)

    return penalties, details


def apply_am1_pm1_mutex(
    model: cp_model.CpModel,
    data: DayInputData,
    dv: DayVars,
    *,
    enabled: bool = True,
    mode: str = "hard",
    weight: int = 3000,
) -> List[cp_model.IntVar]:
    """
    工作日禁止同日 AM1+PM1 组合（soft/hard 可切换）。
    - hard: AM1 + PM1 <= 1
    - soft: 每个 teacher/day 出现组合罚一次
    """
    if not enabled:
        return []

    mode_norm = _norm_mode(mode, "hard")
    days = [d for d in WEEKDAYS if any(s.day == d for s in data.available_slots)]
    am1_map = _build_teacher_day_slot_presence(model, data, dv, days=days, slot_predicate=_is_am1)
    pm1_map = _build_teacher_day_slot_presence(model, data, dv, days=days, slot_predicate=_is_pm1)
    teachers = sorted({t for t in data.cls_subj_teacher.values() if t})
    penalties: List[cp_model.IntVar] = []

    for t in teachers:
        for d in days:
            am1 = am1_map[(t, d)]
            pm1 = pm1_map[(t, d)]
            if mode_norm == "hard":
                model.Add(am1 + pm1 <= 1)
            else:
                viol = _and2(model, am1, pm1, f"am1_pm1_mutex_vio[{t},{d}]")
                penalties.append(viol)
                register(
                    "am1_pm1_mutex",
                    "工作日AM1+PM1组合惩罚",
                    weight,
                    viol,
                    teacher=t,
                    day=d,
                    source_module="scheduler/model/constraints/day_weekday_constraints.py",
                    constraint_category="schedule_pattern",
                    mode="soft",
                    weight_key="day_constraints.w_am1_pm1_mutex",
                )
    return penalties


def apply_two_class_am1_pm1_combo(
    model: cp_model.CpModel,
    data: DayInputData,
    dv: DayVars,
    pe_teachers: Set[str],
    *,
    enabled: bool = True,
    mode: str = "hard",
    weight: int = 3000,
) -> List[cp_model.IntVar]:
    """
    双班教师工作日“上午仅1节 + 下午仅1节”禁排（soft/hard 可切换）。
    """
    if not enabled:
        return []

    mode_norm = _norm_mode(mode, "hard")
    penalties: List[cp_model.IntVar] = []

    tch_classes: Dict[str, Set[str]] = {}
    for (cls, subj), tch in data.cls_subj_teacher.items():
        if is_pe_or_tech_subject(subj):
            continue
        tch_classes.setdefault(tch, set()).add(cls)
    two_class_teachers = sorted([t for t, cls_set in tch_classes.items() if len(cls_set) == 2 and t not in pe_teachers])

    for tch in two_class_teachers:
        for day in WEEKDAYS:
            am_vars = [
                v
                for (cls, subj, slot), v in dv.x.items()
                if slot.day == day and slot.block == "上午" and data.cls_subj_teacher.get((cls, subj)) == tch
            ]
            pm_vars = [
                v
                for (cls, subj, slot), v in dv.x.items()
                if slot.day == day and slot.block == "下午" and data.cls_subj_teacher.get((cls, subj)) == tch
            ]
            fixed_am = sum(
                1
                for (cls, slot), subj in data.fixed_assign.items()
                if slot.day == day and slot.block == "上午" and data.cls_subj_teacher.get((cls, subj)) == tch
            )
            fixed_pm = sum(
                1
                for (cls, slot), subj in data.fixed_assign.items()
                if slot.day == day and slot.block == "下午" and data.cls_subj_teacher.get((cls, subj)) == tch
            )
            max_am = len(am_vars) + fixed_am
            max_pm = len(pm_vars) + fixed_pm
            am_cnt = model.NewIntVar(0, max_am, f"two_class_am_cnt[{tch},{day}]")
            pm_cnt = model.NewIntVar(0, max_pm, f"two_class_pm_cnt[{tch},{day}]")
            model.Add(am_cnt == sum(am_vars) + fixed_am)
            model.Add(pm_cnt == sum(pm_vars) + fixed_pm)

            am_eq1 = model.NewBoolVar(f"two_class_am_eq1[{tch},{day}]")
            pm_eq1 = model.NewBoolVar(f"two_class_pm_eq1[{tch},{day}]")
            model.Add(am_cnt == 1).OnlyEnforceIf(am_eq1)
            model.Add(am_cnt != 1).OnlyEnforceIf(am_eq1.Not())
            model.Add(pm_cnt == 1).OnlyEnforceIf(pm_eq1)
            model.Add(pm_cnt != 1).OnlyEnforceIf(pm_eq1.Not())

            viol = _and2(model, am_eq1, pm_eq1, f"two_class_am1_pm1_combo_vio[{tch},{day}]")
            if mode_norm == "hard":
                model.Add(viol == 0)
            else:
                penalties.append(viol)
                register(
                    "two_class_am1_pm1_combo",
                    "双班教师AM1+PM1分散组合惩罚",
                    weight,
                    viol,
                    teacher=tch,
                    day=day,
                    source_module="scheduler/model/constraints/day_weekday_constraints.py",
                    constraint_category="schedule_pattern",
                    mode="soft",
                    weight_key="day_constraints.w_two_class_am1_pm1_combo",
                )
    return penalties


def apply_am1_pm1_exclusive(
    model: cp_model.CpModel,
    data: DayInputData,
    dv: DayVars,
    *,
    enabled: bool = True,
    mode: str = "hard",
    weight: int = 3000,
) -> List[cp_model.IntVar]:
    """
    工作日 AM1 与 PM1 互斥（soft/hard 可切换）。
    """
    if not enabled:
        return []

    mode_norm = _norm_mode(mode, "hard")
    days = [d for d in WEEKDAYS if any(s.day == d for s in data.available_slots)]
    am1_map = _build_teacher_day_slot_presence(model, data, dv, days=days, slot_predicate=_is_am1)
    pm1_map = _build_teacher_day_slot_presence(model, data, dv, days=days, slot_predicate=_is_pm1)
    teachers = sorted({t for t in data.cls_subj_teacher.values() if t})
    penalties: List[cp_model.IntVar] = []

    for t in teachers:
        for d in days:
            am1 = am1_map[(t, d)]
            pm1 = pm1_map[(t, d)]
            if mode_norm == "hard":
                model.Add(am1 + pm1 <= 1)
            else:
                viol = _and2(model, am1, pm1, f"am1_pm1_exclusive_vio[{t},{d}]")
                penalties.append(viol)
                register(
                    "am1_pm1_exclusive",
                    "工作日AM1与PM1互斥惩罚",
                    weight,
                    viol,
                    teacher=t,
                    day=d,
                    source_module="scheduler/model/constraints/day_weekday_constraints.py",
                    constraint_category="schedule_pattern",
                    mode="soft",
                    weight_key="day_constraints.w_am1_pm1_exclusive",
                )
    return penalties


def apply_single_class_weekly_am1_cap(
    model: cp_model.CpModel,
    data: DayInputData,
    dv: DayVars,
    *,
    enabled: bool = True,
    max_occurrences: int = 2,
) -> None:
    """
    单班教师周一到周日 AM1 出现次数上限（硬约束）。
    统计口径：按 teacher/day 是否出现 AM1（含 fixed_assign）。
    """
    if not enabled:
        return

    max_occurrences = max(0, int(max_occurrences))
    days = [d for d in WEEK_ALL_DAYS if any(s.day == d for s in data.available_slots)]
    if not days:
        return

    teacher_to_classes: Dict[str, Set[str]] = {}
    for (cls, _subj), teacher in data.cls_subj_teacher.items():
        if not teacher:
            continue
        teacher_to_classes.setdefault(teacher, set()).add(cls)
    single_class_teachers = sorted([t for t, cls_set in teacher_to_classes.items() if len(cls_set) == 1])
    if not single_class_teachers:
        return

    am1_presence = _build_teacher_day_slot_presence(model, data, dv, days=days, slot_predicate=_is_am1)
    for teacher in single_class_teachers:
        max_cnt = len(days)
        am1_cnt = model.NewIntVar(0, max_cnt, f"single_class_am1_week_cnt[{teacher}]")
        model.Add(am1_cnt == sum(am1_presence[(teacher, d)] for d in days))
        model.Add(am1_cnt <= max_occurrences)


def apply_two_class_low_hours_max_empty_days(
    model: cp_model.CpModel,
    data: DayInputData,
    dv: DayVars,
    pe_teachers: Set[str],
    threshold: int,
    max_empty_days: int,
) -> None:
    """双班低课时教师：工作日空整天数量上限（硬约束）。"""
    # teacher -> classes set
    tch_classes: Dict[str, Set[str]] = {}
    for (cls, subj), tch in data.cls_subj_teacher.items():
        if is_pe_or_tech_subject(subj):
            continue
        tch_classes.setdefault(tch, set()).add(cls)

    # teacher -> weekday total hours (exclude early/selfstudy/weekend)
    tch_weekday_hours: Dict[str, int] = {}
    for (cls, subj), tch in data.cls_subj_teacher.items():
        if is_pe_or_tech_subject(subj):
            continue
        req = data.req_hours.get((cls, subj))
        if not req:
            continue
        _req_e, req_w, _req_we = req
        tch_weekday_hours[tch] = tch_weekday_hours.get(tch, 0) + int(req_w)

    for tch, cls_set in tch_classes.items():
        if tch in pe_teachers or len(cls_set) != 2:
            continue
        if tch_weekday_hours.get(tch, 0) >= threshold:
            continue

        empty_flags: List[cp_model.IntVar] = []
        for day in WEEKDAYS:
            vars_list = [
                v
                for (c, subj, slot), v in dv.x.items()
                if slot.day == day and slot.block in ("上午", "下午") and data.cls_subj_teacher.get((c, subj)) == tch
            ]
            fixed_cnt = 0
            for (c, slot), subj in data.fixed_assign.items():
                if slot.day != day:
                    continue
                if slot.block not in ("上午", "下午"):
                    continue
                if data.cls_subj_teacher.get((c, subj)) == tch:
                    fixed_cnt += 1

            has_any = model.NewBoolVar(f"two_cls_low_has[{tch},{day}]")
            if fixed_cnt > 0:
                model.Add(has_any == 1)
            elif vars_list:
                model.Add(sum(vars_list) >= has_any)
                for v in vars_list:
                    model.Add(v <= has_any)
            else:
                model.Add(has_any == 0)

            empty = model.NewBoolVar(f"two_cls_low_empty[{tch},{day}]")
            model.Add(empty + has_any == 1)
            empty_flags.append(empty)

        if empty_flags:
            model.Add(sum(empty_flags) <= max_empty_days)


def apply_low_weekday_subject_max1_per_day(
    model: cp_model.CpModel,
    data: DayInputData,
    dv: DayVars,
    max_weekday_hours: int,
) -> None:
    """周中课时<=阈值学科：工作日每天最多1节（硬约束）。"""
    # 对每个班级-学科，若周一到周五课时 <= 阈值，则每个工作日最多1节（上午+下午）
    for (cls, subj), req in data.req_hours.items():
        if req is None:
            continue
        _req_e, req_w, _req_we = req
        if int(req_w) > max_weekday_hours:
            continue

        for day in WEEKDAYS:
            vars_list = [
                v
                for (c, s, slot), v in dv.x.items()
                if c == cls and s == subj and slot.day == day and slot.block in ("上午", "下午")
            ]
            fixed_cnt = 0
            for (c, slot), s in data.fixed_assign.items():
                if c != cls or s != subj:
                    continue
                if slot.day != day:
                    continue
                if slot.block not in ("上午", "下午"):
                    continue
                fixed_cnt += 1
            if vars_list:
                model.Add(sum(vars_list) + fixed_cnt <= 1)
            else:
                model.Add(fixed_cnt <= 1)


def apply_high_weekday_subject_min1_per_day(
    model: cp_model.CpModel,
    data: DayInputData,
    dv: DayVars,
    min_weekday_hours: int,
) -> None:
    """周中课时>=阈值学科：工作日每天至少1节（硬约束）。"""
    # 对每个班级-学科，若周一到周五课时 >= 阈值，则每个工作日至少1节（上午+下午）
    for (cls, subj), req in data.req_hours.items():
        if req is None:
            continue
        _req_e, req_w, _req_we = req
        if int(req_w) < min_weekday_hours:
            continue

        for day in WEEKDAYS:
            vars_list = [
                v
                for (c, s, slot), v in dv.x.items()
                if c == cls and s == subj and slot.day == day and slot.block in ("上午", "下午")
            ]
            fixed_cnt = 0
            for (c, slot), s in data.fixed_assign.items():
                if c != cls or s != subj:
                    continue
                if slot.day != day:
                    continue
                if slot.block not in ("上午", "下午"):
                    continue
                fixed_cnt += 1
            if vars_list:
                model.Add(sum(vars_list) + fixed_cnt >= 1)
            else:
                model.Add(fixed_cnt >= 1)


def apply_multi_class_halfday_soft(
    model: cp_model.CpModel,
    data: DayInputData,
    dv: DayVars,
    pe_teachers: Set[str],
    weight: int,
) -> Tuple[List[cp_model.IntVar], Dict[Tuple[str, str, str], Tuple[cp_model.IntVar, cp_model.IntVar, cp_model.IntVar]]]:
    """多班教师半天偏好（软约束）。"""
    penalties: List[cp_model.IntVar] = []
    details: Dict[Tuple[str, str, str], Tuple[cp_model.IntVar, cp_model.IntVar, cp_model.IntVar]] = {}

    # teacher -> classes he teaches (non PE/tech)
    tch_classes: Dict[str, Set[str]] = {}
    for (cls, subj), tch in data.cls_subj_teacher.items():
        if is_pe_or_tech_subject(subj):
            continue
        tch_classes.setdefault(tch, set()).add(cls)

    for tch, cls_set in tch_classes.items():
        if tch in pe_teachers or len(cls_set) < 2:
            continue
        for day in WEEKDAYS:
            # split_forced flags
            split_forced_list: List[cp_model.IntVar] = []
            has_any_am = model.NewBoolVar(f"has_any_am[{tch},{day}]")
            has_any_pm = model.NewBoolVar(f"has_any_pm[{tch},{day}]")
            am_vars_all = []
            pm_vars_all = []

            for cls in cls_set:
                am_vars = []
                pm_vars = []
                all_vars = []
                for (c, subj, slot), var in dv.x.items():
                    if c != cls:
                        continue
                    if data.cls_subj_teacher.get((c, subj)) != tch:
                        continue
                    if is_pe_or_tech_subject(subj):
                        continue
                    if slot.day != day:
                        continue
                    all_vars.append(var)
                    if _is_am(slot):
                        am_vars.append(var)
                    if _is_pm(slot):
                        pm_vars.append(var)

                if not all_vars:
                    continue

                cnt = model.NewIntVar(0, len(all_vars), f"cnt[{tch},{day},{cls}]")
                model.Add(cnt == sum(all_vars))

                has_am = model.NewBoolVar(f"has_am[{tch},{day},{cls}]")
                has_pm = model.NewBoolVar(f"has_pm[{tch},{day},{cls}]")

                if am_vars:
                    model.Add(sum(am_vars) >= has_am)
                    for v in am_vars:
                        model.Add(v <= has_am)
                else:
                    model.Add(has_am == 0)

                if pm_vars:
                    model.Add(sum(pm_vars) >= has_pm)
                    for v in pm_vars:
                        model.Add(v <= has_pm)
                else:
                    model.Add(has_pm == 0)

                am_vars_all.extend(am_vars)
                pm_vars_all.extend(pm_vars)

                cnt_ge2 = model.NewBoolVar(f"cnt_ge2[{tch},{day},{cls}]")
                model.Add(cnt >= 2).OnlyEnforceIf(cnt_ge2)
                model.Add(cnt <= 1).OnlyEnforceIf(cnt_ge2.Not())

                split_ok = _and2(model, has_am, has_pm, f"split_ok[{tch},{day},{cls}]")
                not_split = model.NewBoolVar(f"not_split[{tch},{day},{cls}]")
                model.Add(split_ok + not_split == 1)
                vio = _and2(model, cnt_ge2, not_split, f"split_vio[{tch},{day},{cls}]")
                penalties.append(vio)  # weight: day.weekday_constraints.weight_multi_class_halfday（建议 100~400）
                register(
                    rule_id="multi_class_halfday_split",
                    rule_name="多班教师半天拆分",
                    weight=weight,
                    var=vio,
                    teacher=tch,
                    day=day,
                    cls=cls,
                )

                split_forced_list.append(cnt_ge2)
                details[(tch, day, cls)] = (cnt, has_am, has_pm)

            if not split_forced_list:
                continue

            for v in am_vars_all:
                model.Add(v <= has_any_am)
            for v in pm_vars_all:
                model.Add(v <= has_any_pm)
            if am_vars_all:
                model.Add(sum(am_vars_all) >= has_any_am)
            else:
                model.Add(has_any_am == 0)
            if pm_vars_all:
                model.Add(sum(pm_vars_all) >= has_any_pm)
            else:
                model.Add(has_any_pm == 0)

            split_forced = model.NewBoolVar(f"split_forced[{tch},{day}]")
            model.AddMaxEquality(split_forced, split_forced_list)
            cross = _and2(model, has_any_am, has_any_pm, f"cross_halfday[{tch},{day}]")
            not_forced = model.NewBoolVar(f"not_forced[{tch},{day}]")
            model.Add(split_forced + not_forced == 1)
            cross_pen = _and2(model, cross, not_forced, f"cross_pen[{tch},{day}]")
            penalties.append(cross_pen)  # weight: day.weekday_constraints.weight_multi_class_halfday（建议 100~400）
            register(
                rule_id="multi_class_halfday_cross",
                rule_name="多班教师跨半天",
                weight=weight,
                var=cross_pen,
                teacher=tch,
                day=day,
            )

    return penalties, details


def apply_teacher_am4_pm1_threshold_penalty(
    model: cp_model.CpModel,
    data: DayInputData,
    dv: DayVars,
    pe_teachers: Set[str],
    weights: Tuple[int, int, int, int],
) -> Tuple[List[cp_model.IntVar], Dict[str, Tuple[int, cp_model.IntVar, cp_model.IntVar, cp_model.IntVar, cp_model.IntVar, cp_model.IntVar]]]:
    """教师 AM4+PM1 阈值阶梯惩罚（软约束）。"""
    penalties: List[cp_model.IntVar] = []
    details: Dict[str, Tuple[int, cp_model.IntVar, cp_model.IntVar, cp_model.IntVar, cp_model.IntVar, cp_model.IntVar]] = {}

    teacher_vars = _collect_teacher_vars(data, dv, exclude_pe_tech=True)
    for tch, days in teacher_vars.items():
        if tch in pe_teachers:
            continue
        am4 = []
        pm1 = []
        for day in WEEKDAYS:
            slots = days.get(day, {})
            am4.extend(v for s, vars_list in slots.items() if _is_am4(s) for v in vars_list)
            pm1.extend(v for s, vars_list in slots.items() if _is_pm1(s) for v in vars_list)

        total = am4 + pm1
        if not total:
            continue

        cnt = model.NewIntVar(0, len(total), f"am4_pm1_cnt[{tch}]")
        model.Add(cnt == sum(total))
        model.Add(cnt <= 6)

        e3 = model.NewIntVar(0, 10, f"e3[{tch}]")
        e4 = model.NewIntVar(0, 10, f"e4[{tch}]")
        e5 = model.NewIntVar(0, 10, f"e5[{tch}]")
        e6 = model.NewIntVar(0, 10, f"e6[{tch}]")

        model.Add(e3 >= cnt - 2)
        model.Add(e4 >= cnt - 3)
        model.Add(e5 >= cnt - 4)
        model.Add(e6 >= cnt - 5)

        penalties.extend([e3, e4, e5, e6])  # weights: day.weekday_constraints.teacher_am4_pm1_w3~w6
        w3, w4, w5, w6 = weights
        register("teacher_am4_pm1_w3", "教师AM4+PM1阶梯3", w3, e3, teacher=tch)
        register("teacher_am4_pm1_w4", "教师AM4+PM1阶梯4", w4, e4, teacher=tch)
        register("teacher_am4_pm1_w5", "教师AM4+PM1阶梯5", w5, e5, teacher=tch)
        register("teacher_am4_pm1_w6", "教师AM4+PM1阶梯6", w6, e6, teacher=tch)
        details[tch] = (len(total), cnt, e3, e4, e5, e6)

    return penalties, details


def apply_weekday_subject_balance(
    model: cp_model.CpModel,
    data: DayInputData,
    dv: DayVars,
    mode: str,
    weight: int = 1,
) -> List[cp_model.IntVar]:
    """学科周内均匀分配（soft/hard 可切换）。"""
    penalties: List[cp_model.IntVar] = []

    for (cls, subj), (_req_e, req_w, _req_we) in data.req_hours.items():
        if is_pe_or_tech_subject(subj):
            continue
        total_weekday = int(req_w)
        if total_weekday == 0:
            continue
        base = total_weekday // 5
        rem = total_weekday % 5

        day_hours_vars: Dict[str, cp_model.IntVar] = {}
        for day in WEEKDAYS:
            vars_list = [
                v
                for (c, s, slot), v in dv.x.items()
                if c == cls and s == subj and slot.day == day
            ]
            fixed_cnt = sum(
                1
                for (c, slot), fs in data.fixed_assign.items()
                if c == cls and slot.day == day and fs == subj
            )
            day_var = model.NewIntVar(0, 10, f"day_hours[{cls},{subj},{day}]")
            model.Add(day_var == sum(vars_list) + fixed_cnt)
            day_hours_vars[day] = day_var

        if mode == "hard":
            for day, v in day_hours_vars.items():
                model.Add(v >= base)
                model.Add(v <= base + 1)
        else:
            for day, v in day_hours_vars.items():
                over = model.NewIntVar(0, 10, f"over[{cls},{subj},{day}]")
                under = model.NewIntVar(0, 10, f"under[{cls},{subj},{day}]")
                model.Add(over >= v - (base + 1))
                model.Add(under >= base - v)
                penalties.append(over)  # weight: day.weekday_constraints.weight_balance_weekday_subject_hours
                penalties.append(under)  # weight: day.weekday_constraints.weight_balance_weekday_subject_hours
                teacher = data.cls_subj_teacher.get((cls, subj), "")
                register(
                    "weekday_subject_balance_over",
                    "学科周中均衡(超额)",
                    weight,
                    over,
                    teacher=teacher,
                    cls=cls,
                    subj=subj,
                    day=day,
                    source_module="scheduler/model/constraints/day_weekday_constraints.py",
                    constraint_category="fairness",
                    mode="soft",
                    weight_key="day.weekday_constraints.weight_balance_weekday_subject_hours",
                )
                register(
                    "weekday_subject_balance_under",
                    "学科周中均衡(不足)",
                    weight,
                    under,
                    teacher=teacher,
                    cls=cls,
                    subj=subj,
                    day=day,
                    source_module="scheduler/model/constraints/day_weekday_constraints.py",
                    constraint_category="fairness",
                    mode="soft",
                    weight_key="day.weekday_constraints.weight_balance_weekday_subject_hours",
                )

    return penalties


def write_day_check_hard_constraints(
    out_dir: Path,
    data: DayInputData,
    dv: DayVars,
    solver: cp_model.CpSolver,
    head_teachers: List[str],
    pe_teachers: Set[str],
) -> None:
    """输出硬约束检查（绑定/AM1+AM4/PM1班主任等）。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "day_check_hard_constraints.txt"

    # 8化/9生绑定
    cls8 = [c for c in data.classes if "8班" in c]
    cls9 = [c for c in data.classes if "9班" in c]
    bind_diff = 0
    if cls8 and cls9:
        c8 = cls8[0]
        c9 = cls9[0]
        for slot in data.available_slots:
            if not _is_weekday(slot.day):
                continue
            v8 = 0
            v9 = 0
            for (c, s, sl), var in dv.x.items():
                if sl != slot:
                    continue
                if c == c8 and s == "化学" and solver.Value(var) == 1:
                    v8 = 1
                if c == c9 and s == "生物" and solver.Value(var) == 1:
                    v9 = 1
            if v8 != v9:
                bind_diff += 1

    # AM1+AM4 违规
    am1am4_viol = 0
    teacher_vars = _collect_teacher_vars(data, dv, exclude_pe_tech=True)
    for t, days in teacher_vars.items():
        if t in pe_teachers:
            continue
        for day, slots in days.items():
            am1 = sum(solver.Value(v) for s, vars_list in slots.items() if _is_am1(s) for v in vars_list)
            am4 = sum(solver.Value(v) for s, vars_list in slots.items() if _is_am4(s) for v in vars_list)
            if am1 > 0 and am4 > 0:
                am1am4_viol += 1

    # PM1 班主任数
    pm1_counts: Dict[str, int] = {}
    for day in WEEKDAYS:
        cnt = 0
        for t in head_teachers:
            slots = teacher_vars.get(t, {}).get(day, {})
            pm1 = sum(solver.Value(v) for s, vars_list in slots.items() if _is_pm1(s) for v in vars_list)
            if pm1 > 0:
                cnt += 1
        pm1_counts[day] = cnt

    lines = ["[Day Hard Constraint Check]"]
    lines.append(f"Bind8Chem9BioDiff={bind_diff}")
    lines.append(f"AM1AM4Violations={am1am4_viol}")
    # 连续两节同班同师违规
    consec_viol = 0
    for cls in data.classes:
        for day in WEEKDAYS:
            slots = [s for s in data.available_slots if s.day == day and s.block in ("上午", "下午")]
            slots.sort(key=_slot_order_key)
            if len(slots) < 2:
                continue
            # teacher -> list of subjects in class
            teachers = set()
            for (c, subj), tch in data.cls_subj_teacher.items():
                if c == cls:
                    teachers.add(tch)
            for t in teachers:
                for i in range(len(slots) - 1):
                    s1, s2 = slots[i], slots[i + 1]
                    v1 = 0
                    v2 = 0
                    for (c, s, sl), var in dv.x.items():
                        if c == cls and sl == s1 and data.cls_subj_teacher.get((c, s)) == t and solver.Value(var) == 1:
                            v1 = 1
                        if c == cls and sl == s2 and data.cls_subj_teacher.get((c, s)) == t and solver.Value(var) == 1:
                            v2 = 1
                    if v1 == 1 and v2 == 1:
                        consec_viol += 1
    lines.append(f"ConsecutiveSameTeacherSameClassViolations={consec_viol}")
    lines.append("PM1HeadCounts=")
    for d in WEEKDAYS:
        lines.append(f"  {d}: {pm1_counts.get(d,0)}")

    path.write_text("\n".join(lines), encoding="utf-8")


def write_day_constraint_checklist(
    out_dir: Path,
    data: DayInputData,
    dv: DayVars,
    solver: cp_model.CpSolver,
    head_teachers: List[str],
    pe_teachers: Set[str],
    multi_details: Dict[Tuple[str, str, str], Tuple[cp_model.IntVar, cp_model.IntVar, cp_model.IntVar]] | None,
    am4pm1_details: Dict[str, Tuple[int, cp_model.IntVar, cp_model.IntVar, cp_model.IntVar, cp_model.IntVar, cp_model.IntVar]] | None,
    am4pm1_weights: Tuple[int, int, int, int] | None,
    weekday_balance_penalties: List[cp_model.IntVar],
) -> None:
    """输出白天约束清单（硬/软统计汇总）。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "day_constraint_checklist.txt"

    teacher_vars = _collect_teacher_vars(data, dv, exclude_pe_tech=True)

    # AM1+AM4 violations
    am1am4_viol = 0
    for t, days in teacher_vars.items():
        if t in pe_teachers:
            continue
        for day, slots in days.items():
            am1 = sum(solver.Value(v) for s, vars_list in slots.items() if _is_am1(s) for v in vars_list)
            am4 = sum(solver.Value(v) for s, vars_list in slots.items() if _is_am4(s) for v in vars_list)
            if am1 > 0 and am4 > 0:
                am1am4_viol += 1

    # PM1 head counts
    pm1_counts: Dict[str, int] = {}
    for day in WEEKDAYS:
        cnt = 0
        for t in head_teachers:
            slots = teacher_vars.get(t, {}).get(day, {})
            pm1 = sum(solver.Value(v) for s, vars_list in slots.items() if _is_pm1(s) for v in vars_list)
            if pm1 > 0:
                cnt += 1
        pm1_counts[day] = cnt

    lines = ["[Day Constraint Checklist]"]
    lines.append(f"AM1AM4Violations={am1am4_viol}")
    lines.append("PM1HeadCounts=")
    for d in WEEKDAYS:
        lines.append(f"  {d}: {pm1_counts.get(d,0)}")

    # 8化/9生绑定检查
    cls8 = [c for c in data.classes if "8班" in c]
    cls9 = [c for c in data.classes if "9班" in c]
    bind_diff = 0
    if cls8 and cls9:
        c8 = cls8[0]
        c9 = cls9[0]
        for slot in data.available_slots:
            if not _is_weekday(slot.day):
                continue
            v8 = 0
            v9 = 0
            for (c, s, sl), var in dv.x.items():
                if sl != slot:
                    continue
                if c == c8 and s == "化学" and solver.Value(var) == 1:
                    v8 = 1
                if c == c9 and s == "生物" and solver.Value(var) == 1:
                    v9 = 1
            if v8 != v9:
                bind_diff += 1
    lines.append(f"Bind8Chem9BioDiff={bind_diff}")
    # 连续两节同班同师违规
    consec_viol = 0
    for cls in data.classes:
        for day in WEEKDAYS:
            slots = [s for s in data.available_slots if s.day == day]
            slots.sort(key=_slot_order_key)
            if len(slots) < 2:
                continue
            teachers = set()
            for (c, subj), tch in data.cls_subj_teacher.items():
                if c == cls:
                    teachers.add(tch)
            for t in teachers:
                for i in range(len(slots) - 1):
                    s1, s2 = slots[i], slots[i + 1]
                    v1 = 0
                    v2 = 0
                    for (c, s, sl), var in dv.x.items():
                        if c == cls and sl == s1 and data.cls_subj_teacher.get((c, s)) == t and solver.Value(var) == 1:
                            v1 = 1
                        if c == cls and sl == s2 and data.cls_subj_teacher.get((c, s)) == t and solver.Value(var) == 1:
                            v2 = 1
                    if v1 == 1 and v2 == 1:
                        consec_viol += 1
    lines.append(f"ConsecutiveSameTeacherSameClassViolations={consec_viol}")

    # 多班教师 AM/PM 分布
    if multi_details:
        lines.append("MultiClassAMPM=")
        for (t, d, c), (cnt, has_am, has_pm) in sorted(multi_details.items()):
            lines.append(
                f"  {t} {d} {c}: cnt={solver.Value(cnt)} am={solver.Value(has_am)} pm={solver.Value(has_pm)}"
            )

    # 软约束罚分分解（数量级）
    if am4pm1_details and am4pm1_weights:
        w3, w4, w5, w6 = am4pm1_weights
        penalty_sum = 0
        over6 = 0
        for _tch, (_total_max, cnt, e3, e4, e5, e6) in am4pm1_details.items():
            cnt_val = solver.Value(cnt)
            penalty_sum += (
                w3 * solver.Value(e3)
                + w4 * solver.Value(e4)
                + w5 * solver.Value(e5)
                + w6 * solver.Value(e6)
            )
            if cnt_val > 6:
                over6 += 1
        lines.append(f"AM4PM1PenaltySum={penalty_sum}")
        lines.append(f"AM4PM1OverLimitCount(>6)={over6}")
    if weekday_balance_penalties:
        lines.append(f"WeekdayBalancePenaltySum={sum(solver.Value(v) for v in weekday_balance_penalties)}")

    path.write_text("\n".join(lines), encoding="utf-8")
