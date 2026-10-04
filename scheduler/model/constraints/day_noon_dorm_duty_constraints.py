# -*- coding: utf-8 -*-
"""
中午查寝约束模块（独立于晚查寝与下午课前值班）。

设计说明：
- 本模块只新增“中午查寝”变量与约束，不改现有晚查寝/下午值班语义。
- 每日中午安排：男寝1人；女寝除周六外1人（周六女寝置空）。
- 软约束通过 penalty_registry 逐条登记到 event_log，确保可追溯到教师与日期。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Set, Tuple

import pandas as pd
from ortools.sat.python import cp_model

from scheduler.data.day_rules_reader import DayInputData, Slot
from scheduler.data.teacher_table_schema import (
    configured_teacher_table_columns,
    load_teacher_table_frame,
)
from scheduler.model.day_variables import DayVars
from scheduler.diagnostics.penalty_registry import register
from scheduler.model.constraints.teacher_targets import teacher_names, teacher_name_set
from scheduler.calendar import MONDAY, SATURDAY, day_rank, ordered_days, previous_day


@dataclass
class NoonDormDutyConfig:
    enabled: bool = True
    # 阶梯罚分：中午查寝当天优先上午4，否则按 3/2/1/无上午课依次惩罚
    w_need_am4_lvl3: int = 200
    w_need_am4_lvl2: int = 400
    w_need_am4_lvl1: int = 800
    w_need_am4_lvl0: int = 1000
    # 中午查寝当天尽量不排下午1
    w_noon_with_pm1: int = 300
    # 女教师同一天“中午查寝+晚查寝”高罚分
    w_female_noon_night_checkin: int = 1000
    # 指定教师中午查寝禁排（soft/hard 可切换）
    lhj_noon_ban_mode: str = "hard"  # hard|soft
    w_lhj_noon_ban: int = 1000
    # 指定教师中午查寝禁排（soft/hard 可切换）
    zeng_noon_ban_mode: str = "hard"  # hard|soft
    w_zeng_noon_ban: int = 3000
    noon_exclude_teachers: List[str] = field(default_factory=list)
    male_candidate_extra_teachers: List[str] = field(default_factory=list)
    noon_disallow_teachers: List[str] = field(default_factory=list)
    saturday_fixed_female_teachers: List[str] = field(default_factory=list)
    special_male_noon_max1_teachers: List[str] = field(default_factory=list)
    lhj_noon_ban_teachers: List[str] = field(default_factory=list)
    zeng_noon_ban_teachers: List[str] = field(default_factory=list)
    noon_am_link_teachers: List[str] = field(default_factory=list)


def _norm(s: object) -> str:
    if pd.isna(s):
        return ""
    return str(s).strip()


def _norm_mode(x: object, default: str = "hard") -> str:
    m = str(x or default).strip().lower()
    return m if m in {"hard", "soft"} else default


def _slot_key(slot: Slot) -> str:
    return f"{slot.block}{slot.period}"


def _all_days(data: DayInputData) -> List[str]:
    days = {s.day for s in data.available_slots}
    known = ordered_days(days)
    unknown = sorted(day for day in days if day not in known)
    return [*known, *unknown]


def _read_head_gender(io_cfg: dict, base_dir: Path) -> Tuple[Set[str], Set[str], Dict[str, str], List[str]]:
    _class_col, head_col, gender_col = configured_teacher_table_columns(io_cfg)
    hints: List[str] = []

    df = load_teacher_table_frame(io_cfg, base_dir)
    if df.empty:
        hints.append("教师定位表不存在或没有可用行")
        return set(), set(), {}, hints

    if head_col not in df.columns or gender_col not in df.columns:
        hints.append(f"未提供可选班主任/性别列: {head_col}/{gender_col}")
        return set(), set(), {}, hints

    male: Set[str] = set()
    female: Set[str] = set()
    gender_map: Dict[str, str] = {}
    for _, row in df.iterrows():
        t = _norm(row.get(head_col, ""))
        g = _norm(row.get(gender_col, ""))
        if not t:
            continue
        if g == "男":
            male.add(t)
            gender_map[t] = "男"
        elif g == "女":
            female.add(t)
            gender_map[t] = "女"
        else:
            hints.append(f"班主任性别异常: {t}={g}")
    return male, female, gender_map, hints


def _build_teacher_slot_has(
    model: cp_model.CpModel,
    data: DayInputData,
    dv: DayVars,
    teachers: Set[str],
    days: List[str],
    target_key: str,
) -> Dict[Tuple[str, str], cp_model.IntVar]:
    """构造 teacher_has_slot[t,d,target_key]，固定课位也计入。"""
    out: Dict[Tuple[str, str], cp_model.IntVar] = {}
    vars_map: Dict[Tuple[str, str], List[cp_model.IntVar]] = {}

    for (cls, subj, slot), var in dv.x.items():
        if _slot_key(slot) != target_key:
            continue
        t = data.cls_subj_teacher.get((cls, subj), "")
        if t in teachers:
            vars_map.setdefault((t, slot.day), []).append(var)

    for t in teachers:
        for d in days:
            fixed = 0
            for (cls, slot), subj in data.fixed_assign.items():
                if slot.day != d or _slot_key(slot) != target_key:
                    continue
                if data.cls_subj_teacher.get((cls, subj), "") == t:
                    fixed += 1

            b = model.NewBoolVar(f"noon_has[{t},{d},{target_key}]")
            vars_list = vars_map.get((t, d), [])
            if fixed > 0:
                model.Add(b == 1)
            elif vars_list:
                for v in vars_list:
                    model.Add(b >= v)
                model.Add(b <= sum(vars_list))
            else:
                model.Add(b == 0)
            out[(t, d)] = b
    return out


def _and2(model: cp_model.CpModel, a, b, name: str):
    z = model.NewBoolVar(name)
    model.Add(z <= a)
    model.Add(z <= b)
    model.Add(z >= a + b - 1)
    return z


def _build_am_tiers(
    model: cp_model.CpModel,
    has_am1,
    has_am2,
    has_am3,
    has_am4,
    tag: str,
):
    """返回 tier4/3/2/1/0（互斥且和为1）。"""
    t4 = model.NewBoolVar(f"noon_t4[{tag}]")
    t3 = model.NewBoolVar(f"noon_t3[{tag}]")
    t2 = model.NewBoolVar(f"noon_t2[{tag}]")
    t1 = model.NewBoolVar(f"noon_t1[{tag}]")
    t0 = model.NewBoolVar(f"noon_t0[{tag}]")

    model.Add(t4 == has_am4)
    model.Add(t3 <= has_am3)
    model.Add(t3 <= 1 - has_am4)
    model.Add(t3 >= has_am3 - has_am4)

    model.Add(t2 <= has_am2)
    model.Add(t2 <= 1 - has_am3)
    model.Add(t2 <= 1 - has_am4)
    model.Add(t2 >= has_am2 - has_am3 - has_am4)

    model.Add(t1 <= has_am1)
    model.Add(t1 <= 1 - has_am2)
    model.Add(t1 <= 1 - has_am3)
    model.Add(t1 <= 1 - has_am4)
    model.Add(t1 >= has_am1 - has_am2 - has_am3 - has_am4)

    model.Add(t0 + t1 + t2 + t3 + t4 == 1)
    return t4, t3, t2, t1, t0


def write_noon_dorm_audit(
    out_dir: Path,
    days: List[str],
    male_candidates: List[str],
    female_candidates: List[str],
    hints: List[str],
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    lines = [
        "[Noon Dorm Duty Audit]",
        f"Days={days}",
        f"MaleCandidates={male_candidates}",
        f"FemaleCandidates={female_candidates}",
        "TODO=“中午查寝则尽量不安排周一至周五其他上午4”缺少“额外上午4”的唯一口径，暂不硬判，已保留PM1软约束且不影响求解正确性。",
    ]
    if hints:
        lines.append("Hints=")
        lines.extend([f"  - {h}" for h in hints])
    (out_dir / "中午查寝_审计.txt").write_text("\n".join(lines), encoding="utf-8")


def write_noon_dorm_checklist(
    out_dir: Path,
    val: cp_model.CpSolver | cp_model.CpSolverSolutionCallback,
    days: List[str],
    noon_male: Dict[Tuple[str, str], cp_model.IntVar],
    noon_female: Dict[Tuple[str, str], cp_model.IntVar],
    day_penalty: Dict[str, cp_model.IntVar],
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    lines = ["[Noon Dorm Duty Checklist]"]
    for d in days:
        male = [t for (t, dd), v in noon_male.items() if dd == d and val.Value(v) == 1]
        female = [t for (t, dd), v in noon_female.items() if dd == d and val.Value(v) == 1]
        p = val.Value(day_penalty.get(d, 0)) if d in day_penalty else 0
        lines.append(f"{d}: 男寝={','.join(male)} 女寝={','.join(female)} 当日罚分={p}")
    (out_dir / "中午查寝_检查.txt").write_text("\n".join(lines), encoding="utf-8")


def extract_noon_dorm_rows(
    val: cp_model.CpSolver | cp_model.CpSolverSolutionCallback,
    days: List[str],
    noon_male: Dict[Tuple[str, str], cp_model.IntVar],
    noon_female: Dict[Tuple[str, str], cp_model.IntVar],
    day_penalty: Dict[str, cp_model.IntVar] | None = None,
) -> List[dict[str, str]]:
    rows: List[dict[str, str]] = []
    day_penalty = day_penalty or {}
    for d in days:
        male = ""
        female = ""
        for (t, dd), v in noon_male.items():
            if dd == d and val.Value(v) == 1:
                male = t
                break
        for (t, dd), v in noon_female.items():
            if dd == d and val.Value(v) == 1:
                female = t
                break
        note = ""
        if d in day_penalty:
            p = int(val.Value(day_penalty[d]))
            if p > 0:
                note = f"当日中午查寝相关罚分={p}"
        rows.append({"星期": d, "男寝教师": male, "女寝教师": female, "备注": note})
    return rows


def apply_noon_dorm_duty_constraints(
    model: cp_model.CpModel,
    data: DayInputData,
    dv: DayVars,
    io_cfg: dict,
    base_dir: Path,
    out_dir: Path,
    cfg: NoonDormDutyConfig,
    night_vars: dict | None = None,
) -> Tuple[
    Dict[Tuple[str, str], cp_model.IntVar],  # noon_male
    Dict[Tuple[str, str], cp_model.IntVar],  # noon_female
    List[cp_model.IntVar],                    # penalties
    Dict[str, cp_model.IntVar],              # day_penalty
    List[str],                               # days
    List[str],                               # hints
]:
    """
    中午查寝约束入口。

    说明：
    - 仅新增本模块变量和约束，不改既有约束语义。
    - 周六女寝置空：周六不安排女寝中午查寝且不产生女寝相关罚分。
    """
    days = _all_days(data)
    if not cfg.enabled:
        return {}, {}, [], {}, days, []

    male_heads, female_heads, gender_map, hints = _read_head_gender(io_cfg, base_dir)
    all_heads = set(male_heads) | set(female_heads)

    # 中午查寝候选集合（与晚查寝候选集合分离）：所有特例均来自配置。
    saturday_fixed_female = teacher_names(cfg.saturday_fixed_female_teachers)
    noon_base = {t for t in all_heads if t not in teacher_name_set(cfg.noon_exclude_teachers)}
    male_candidates = male_heads & noon_base
    female_candidates = female_heads & noon_base

    # 配置例外：允许指定教师进入男寝候选池。
    for t in teacher_names(cfg.male_candidate_extra_teachers):
        if t in noon_base:
            male_candidates.add(t)
    for t in teacher_names(cfg.noon_disallow_teachers):
        male_candidates.discard(t)
        female_candidates.discard(t)

    male_candidates = set(sorted(male_candidates))
    female_candidates = set(sorted(female_candidates))

    # 只保留出现在白天教师映射中的老师
    day_teachers = set(data.cls_subj_teacher.values())
    male_candidates = {t for t in male_candidates if t in day_teachers}
    female_candidates = {t for t in female_candidates if t in day_teachers or t in saturday_fixed_female}

    # 时段占用口径（白天，不含早晚自习）
    has_am1 = _build_teacher_slot_has(model, data, dv, male_candidates | female_candidates, days, "上午1")
    has_am2 = _build_teacher_slot_has(model, data, dv, male_candidates | female_candidates, days, "上午2")
    has_am3 = _build_teacher_slot_has(model, data, dv, male_candidates | female_candidates, days, "上午3")
    has_am4 = _build_teacher_slot_has(model, data, dv, male_candidates | female_candidates, days, "上午4")
    has_pm1 = _build_teacher_slot_has(model, data, dv, male_candidates | female_candidates, days, "下午1")

    noon_male: Dict[Tuple[str, str], cp_model.IntVar] = {}
    noon_female: Dict[Tuple[str, str], cp_model.IntVar] = {}

    # 变量创建
    for d in days:
        for t in sorted(male_candidates):
            noon_male[(t, d)] = model.NewBoolVar(f"noon_male[{t},{d}]")
        for t in sorted(female_candidates):
            noon_female[(t, d)] = model.NewBoolVar(f"noon_female[{t},{d}]")

    # 硬约束：每天男寝1人；周日强制为空（0人）
    for d in days:
        male_vars = [noon_male[(t, d)] for t in sorted(male_candidates)]
        if d == "星期日":
            if male_vars:
                model.Add(sum(male_vars) == 0)
        elif male_vars:
            model.Add(sum(male_vars) == 1)
        else:
            model.Add(0 == 1)
            hints.append(f"{d} 无男寝候选教师，模型不可行")

    # 硬约束：非周六女寝1人；周六可配置固定女寝查寝教师
    for d in days:
        female_vars = [noon_female[(t, d)] for t in sorted(female_candidates)]
        if d == SATURDAY:
            fixed_vars = [noon_female[(t, d)] for t in saturday_fixed_female if (t, d) in noon_female]
            if saturday_fixed_female and not fixed_vars:
                model.Add(0 == 1)
                hints.append(f"{d} 缺少配置的固定女查寝教师变量，无法满足周六固定女查寝")
            elif fixed_vars:
                model.Add(sum(fixed_vars) == 1)
                fixed_set = set(saturday_fixed_female)
                for t in sorted(female_candidates):
                    if t in fixed_set:
                        continue
                    model.Add(noon_female[(t, d)] == 0)
            else:
                for t in sorted(female_candidates):
                    model.Add(noon_female[(t, d)] == 0)
        else:
            if female_vars:
                model.Add(sum(female_vars) == 1)
            else:
                model.Add(0 == 1)
                hints.append(f"{d} 无女寝候选教师，模型不可行")

    # 硬约束：同一天不能同一人兼男寝与女寝
    both_candidates = male_candidates & female_candidates
    for d in days:
        for t in sorted(both_candidates):
            model.Add(noon_male[(t, d)] + noon_female[(t, d)] <= 1)

    # 硬约束：配置教师集合一周内男午寝总次数最多 1
    special_male_noon = teacher_names(cfg.special_male_noon_max1_teachers)
    special_terms = []
    for t in special_male_noon:
        for d in days:
            v = noon_male.get((t, d))
            if v is not None:
                special_terms.append(v)
    if special_terms:
        model.Add(sum(special_terms) <= 1)

    # 硬约束：每位女班主任一周中午查寝最多安排一次
    # 说明：男班主任口径由 duty_joint_constraints 统一处理
    # （无晚查寝=>中午查寝2次；有晚查寝=>中午查寝最多1次）
    for t in sorted(male_candidates | female_candidates):
        if t not in female_heads:
            continue
        terms = []
        for d in days:
            if (t, d) in noon_male:
                terms.append(noon_male[(t, d)])
            if (t, d) in noon_female:
                terms.append(noon_female[(t, d)])
        if terms:
            model.Add(sum(terms) <= 1)

    penalties: List[cp_model.IntVar] = []
    day_penalty_terms: Dict[str, List[cp_model.IntVar]] = {d: [] for d in days}

    # 规则：第一组配置教师中午查寝禁排（soft/hard 可切换，默认 hard）
    lhj_mode = _norm_mode(cfg.lhj_noon_ban_mode, "hard")
    for lhj in teacher_names(cfg.lhj_noon_ban_teachers):
        for d in days:
            if d == SATURDAY:
                continue
            vm = noon_male.get((lhj, d))
            if vm is not None and lhj_mode == "hard":
                model.Add(vm == 0)
            elif vm is not None:
                penalties.append(cfg.w_lhj_noon_ban * vm)
                day_penalty_terms[d].append(cfg.w_lhj_noon_ban * vm)
                register(
                    "noon_dorm_ban_target_group1_soft",
                    "中午查寝禁止指定教师（软约束）",
                    cfg.w_lhj_noon_ban,
                    vm,
                    teacher=lhj,
                    day=d,
                    slot="中午查寝",
                    constraint_category="preference",
                    source_module="scheduler/model/constraints/day_noon_dorm_duty_constraints.py",
                    description="指定教师被安排中午查寝",
                )
            vf = noon_female.get((lhj, d))
            if vf is not None and lhj_mode == "hard":
                model.Add(vf == 0)
            elif vf is not None:
                penalties.append(cfg.w_lhj_noon_ban * vf)
                day_penalty_terms[d].append(cfg.w_lhj_noon_ban * vf)
                register(
                    "noon_dorm_ban_target_group1_soft",
                    "中午查寝禁止指定教师（软约束）",
                    cfg.w_lhj_noon_ban,
                    vf,
                    teacher=lhj,
                    day=d,
                    slot="中午查寝",
                    constraint_category="preference",
                    source_module="scheduler/model/constraints/day_noon_dorm_duty_constraints.py",
                    description="指定教师被安排中午查寝",
                )

    # 规则：第二组配置教师中午查寝禁排（soft/hard 可切换，默认 hard）
    zeng_mode = _norm_mode(cfg.zeng_noon_ban_mode, "hard")
    for zeng in teacher_names(cfg.zeng_noon_ban_teachers):
        for d in days:
            vm = noon_male.get((zeng, d))
            if vm is not None and zeng_mode == "hard":
                model.Add(vm == 0)
            vf = noon_female.get((zeng, d))
            if vf is not None and zeng_mode == "hard":
                model.Add(vf == 0)
            if vm is not None and zeng_mode != "hard":
                penalties.append(cfg.w_zeng_noon_ban * vm)
                day_penalty_terms[d].append(cfg.w_zeng_noon_ban * vm)
                register(
                    "noon_dorm_ban_target_group2_soft",
                    "中午查寝禁止指定教师（软约束）",
                    cfg.w_zeng_noon_ban,
                    vm,
                    teacher=zeng,
                    day=d,
                    slot="中午查寝",
                    constraint_category="preference",
                    source_module="scheduler/model/constraints/day_noon_dorm_duty_constraints.py",
                    description="指定教师被安排中午查寝",
                )
            if vf is not None and zeng_mode != "hard":
                penalties.append(cfg.w_zeng_noon_ban * vf)
                day_penalty_terms[d].append(cfg.w_zeng_noon_ban * vf)
                register(
                    "noon_dorm_ban_target_group2_soft",
                    "中午查寝禁止指定教师（软约束）",
                    cfg.w_zeng_noon_ban,
                    vf,
                    teacher=zeng,
                    day=d,
                    slot="中午查寝",
                    constraint_category="preference",
                    source_module="scheduler/model/constraints/day_noon_dorm_duty_constraints.py",
                    description="指定教师被安排中午查寝",
                )

    # 规则：配置教师中午查寝联动（硬+软）
    # 硬：若被安排中午查寝，则不得上午4有课，且上午需有课（AM1/AM2/AM3）
    # 软：若安排中午查寝，AM3=0且AM2=1 罚2000；仅AM1（AM2=0且AM3=0）罚5000
    for zfj in teacher_names(cfg.noon_am_link_teachers):
        for d in days:
            zfj_noon_vars = []
            vm = noon_male.get((zfj, d))
            vf = noon_female.get((zfj, d))
            if vm is not None:
                zfj_noon_vars.append(vm)
            if vf is not None:
                zfj_noon_vars.append(vf)
            if not zfj_noon_vars:
                continue
    
            if len(zfj_noon_vars) == 1:
                zfj_noon = zfj_noon_vars[0]
            else:
                zfj_noon = model.NewBoolVar(f"noon_any[{zfj},{d}]")
                model.Add(zfj_noon <= sum(zfj_noon_vars))
                for v in zfj_noon_vars:
                    model.Add(zfj_noon >= v)
    
            am1 = has_am1.get((zfj, d), model.NewConstant(0))
            am2 = has_am2.get((zfj, d), model.NewConstant(0))
            am3 = has_am3.get((zfj, d), model.NewConstant(0))
            am4 = has_am4.get((zfj, d), model.NewConstant(0))
    
            model.Add(am4 == 0).OnlyEnforceIf(zfj_noon)
            model.Add(am1 + am2 + am3 >= 1).OnlyEnforceIf(zfj_noon)
    
            am2_case = model.NewBoolVar(f"noon_zfj_am2_case[{d}]")
            model.Add(am2_case <= am2)
            model.Add(am2_case <= 1 - am3)
            model.Add(am2_case >= am2 - am3)
            viol_am2 = _and2(model, zfj_noon, am2_case, f"noon_zfj_am2_pen[{d}]")
            penalties.append(2000 * viol_am2)
            day_penalty_terms[d].append(2000 * viol_am2)
            register(
                "noon_zfj_am2_penalty",
                "指定教师中午查寝上午2惩罚",
                2000,
                viol_am2,
                teacher=zfj,
                day=d,
                slot="中午查寝",
                constraint_category="preference",
                source_module="scheduler/model/constraints/day_noon_dorm_duty_constraints.py",
                description="指定教师中午查寝且无上午3、有上午2",
            )
    
            am1_only_case = model.NewBoolVar(f"noon_zfj_am1_only_case[{d}]")
            model.Add(am1_only_case <= am1)
            model.Add(am1_only_case <= 1 - am2)
            model.Add(am1_only_case <= 1 - am3)
            model.Add(am1_only_case >= am1 - am2 - am3)
            viol_am1 = _and2(model, zfj_noon, am1_only_case, f"noon_zfj_am1_pen[{d}]")
            penalties.append(5000 * viol_am1)
            day_penalty_terms[d].append(5000 * viol_am1)
            register(
                "noon_zfj_am1_only_penalty",
                "指定教师中午查寝仅上午1惩罚",
                5000,
                viol_am1,
                teacher=zfj,
                day=d,
                slot="中午查寝",
                constraint_category="preference",
                source_module="scheduler/model/constraints/day_noon_dorm_duty_constraints.py",
                description="指定教师中午查寝且仅上午1有课",
            )
    
    # 软约束：中午查寝优先上午4（阶梯）
    for d in days:
        for t in sorted(male_candidates | female_candidates):
            if d == SATURDAY and t in set(saturday_fixed_female):
                # 周六固定女查寝：不参与中午查寝相关罚分
                continue
            x_vars = []
            if (t, d) in noon_male:
                x_vars.append(noon_male[(t, d)])
            if (t, d) in noon_female:
                x_vars.append(noon_female[(t, d)])
            if not x_vars:
                continue
            duty_any = model.NewBoolVar(f"noon_duty_any[{t},{d}]")
            model.Add(duty_any <= sum(x_vars))
            for v in x_vars:
                model.Add(duty_any >= v)

            t4, t3, t2, t1, t0 = _build_am_tiers(
                model,
                has_am1.get((t, d), model.NewConstant(0)),
                has_am2.get((t, d), model.NewConstant(0)),
                has_am3.get((t, d), model.NewConstant(0)),
                has_am4.get((t, d), model.NewConstant(0)),
                f"{t},{d}",
            )
            v3 = _and2(model, duty_any, t3, f"noon_am4_lvl3[{t},{d}]")
            v2 = _and2(model, duty_any, t2, f"noon_am4_lvl2[{t},{d}]")
            v1 = _and2(model, duty_any, t1, f"noon_am4_lvl1[{t},{d}]")
            v0 = _and2(model, duty_any, t0, f"noon_am4_lvl0[{t},{d}]")

            penalties.extend(
                [
                    cfg.w_need_am4_lvl3 * v3,
                    cfg.w_need_am4_lvl2 * v2,
                    cfg.w_need_am4_lvl1 * v1,
                    cfg.w_need_am4_lvl0 * v0,
                ]
            )
            day_penalty_terms[d].extend(
                [
                    cfg.w_need_am4_lvl3 * v3,
                    cfg.w_need_am4_lvl2 * v2,
                    cfg.w_need_am4_lvl1 * v1,
                    cfg.w_need_am4_lvl0 * v0,
                ]
            )
            register(
                "noon_dorm_need_am4_lvl3",
                "中午查寝优先上午4（阶梯罚分）",
                cfg.w_need_am4_lvl3,
                v3,
                teacher=t,
                day=d,
                slot="中午查寝",
                constraint_category="preference",
                source_module="scheduler/model/constraints/day_noon_dorm_duty_constraints.py",
                description="未满足上午4，改用上午3",
            )
            register(
                "noon_dorm_need_am4_lvl2",
                "中午查寝优先上午4（阶梯罚分）",
                cfg.w_need_am4_lvl2,
                v2,
                teacher=t,
                day=d,
                slot="中午查寝",
                constraint_category="preference",
                source_module="scheduler/model/constraints/day_noon_dorm_duty_constraints.py",
                description="未满足上午4，改用上午2",
            )
            register(
                "noon_dorm_need_am4_lvl1",
                "中午查寝优先上午4（阶梯罚分）",
                cfg.w_need_am4_lvl1,
                v1,
                teacher=t,
                day=d,
                slot="中午查寝",
                constraint_category="preference",
                source_module="scheduler/model/constraints/day_noon_dorm_duty_constraints.py",
                description="未满足上午4，改用上午1",
            )
            register(
                "noon_dorm_need_am4_lvl0",
                "中午查寝优先上午4（阶梯罚分）",
                cfg.w_need_am4_lvl0,
                v0,
                teacher=t,
                day=d,
                slot="中午查寝",
                constraint_category="preference",
                source_module="scheduler/model/constraints/day_noon_dorm_duty_constraints.py",
                description="未满足上午4，且当天无上午课程",
            )

            # 软约束A：中午查寝当天尽量不排下午1
            pm1_viol = _and2(model, duty_any, has_pm1.get((t, d), model.NewConstant(0)), f"noon_pm1[{t},{d}]")
            penalties.append(cfg.w_noon_with_pm1 * pm1_viol)
            day_penalty_terms[d].append(cfg.w_noon_with_pm1 * pm1_viol)
            register(
                "noon_dorm_avoid_pm1",
                "中午查寝当天尽量不排下午1",
                cfg.w_noon_with_pm1,
                pm1_viol,
                teacher=t,
                day=d,
                slot="下午1",
                constraint_category="preference",
                source_module="scheduler/model/constraints/day_noon_dorm_duty_constraints.py",
                description="中午查寝当天出现下午1课程",
            )

    # 软约束：女教师同日“中午查寝+晚查寝”高罚分（夜间变量存在时）
    checkin_f = (night_vars or {}).get("checkin_f", {})
    if checkin_f:
        for d in days:
            if d == SATURDAY:
                # 周六女寝置空，不触发该条
                continue
            for t in sorted(female_candidates):
                day_noon = noon_female.get((t, d))
                night_ck = checkin_f.get((t, d))
                if day_noon is None or night_ck is None:
                    continue
                both = _and2(model, day_noon, night_ck, f"noon_night_ck[{t},{d}]")
                penalties.append(cfg.w_female_noon_night_checkin * both)
                day_penalty_terms[d].append(cfg.w_female_noon_night_checkin * both)
                register(
                    "noon_female_with_night_checkin",
                    "女教师同日中午查寝+晚查寝惩罚",
                    cfg.w_female_noon_night_checkin,
                    both,
                    teacher=t,
                    day=d,
                    slot="中午查寝+晚查寝",
                    constraint_category="fairness",
                    source_module="scheduler/model/constraints/day_noon_dorm_duty_constraints.py",
                    description="同一女教师同一天同时承担中午查寝与晚查寝",
                )
    else:
        hints.append("未提供晚查寝变量，已跳过“女教师中午查寝+晚查寝”联动惩罚。")

    # 每日罚分汇总（用于导出备注）
    day_penalty: Dict[str, cp_model.IntVar] = {}
    for d in days:
        terms = day_penalty_terms.get(d, [])
        ub = 100000
        p = model.NewIntVar(0, ub, f"noon_day_penalty[{d}]")
        if terms:
            model.Add(p == sum(terms))
        else:
            model.Add(p == 0)
        day_penalty[d] = p

    write_noon_dorm_audit(
        out_dir,
        days,
        sorted(male_candidates),
        sorted(female_candidates),
        hints,
    )
    return noon_male, noon_female, penalties, day_penalty, days, hints


def add_noon_night_checkin_coupling(
    model: cp_model.CpModel,
    noon_female: Dict[Tuple[str, str], cp_model.IntVar],
    night_vars: dict | None,
    cfg: NoonDormDutyConfig,
) -> List[cp_model.IntVar]:
    """
    仅追加“女教师同日中午查寝+晚查寝”联动软惩罚（joint 模式使用）。
    """
    if not cfg.enabled:
        return []
    checkin_f = (night_vars or {}).get("checkin_f", {})
    if not checkin_f:
        return []

    penalties: List[cp_model.IntVar] = []
    for (t, d), noon_var in noon_female.items():
        if d == SATURDAY:
            continue
        night_var = checkin_f.get((t, d))
        if night_var is None:
            continue
        both = _and2(model, noon_var, night_var, f"noon_night_ck_joint[{t},{d}]")
        penalties.append(cfg.w_female_noon_night_checkin * both)
        register(
            "noon_female_with_night_checkin",
            "女教师同日中午查寝+晚查寝惩罚",
            cfg.w_female_noon_night_checkin,
            both,
            teacher=t,
            day=d,
            slot="中午查寝+晚查寝",
            constraint_category="fairness",
            source_module="scheduler/model/constraints/day_noon_dorm_duty_constraints.py",
            description="同一女教师同一天同时承担中午查寝与晚查寝",
        )
    return penalties


def add_noon_prev_same_day_no_night_class_constraints(
    model: cp_model.CpModel,
    *,
    noon_male: Dict[Tuple[str, str], cp_model.IntVar],
    noon_female: Dict[Tuple[str, str], cp_model.IntVar],
    night_vars: dict | None,
    hard_teacher: str = "",
    hard_teachers: List[str] | None = None,
    soft_weight: int = 3000,
) -> List[cp_model.IntVar]:
    """
    联动“中午查寝”与“晚自习(on_teacher_day)”：
    - hard: 配置教师若在 d 日被安排中午查寝，则 d 日不得安排晚自习；
      且在非星期一时，d-1 也不得安排晚自习。
    - soft: 任意教师若在 d 日被安排中午查寝，则 d-1 与 d 两天尽量不得安排晚自习；
      若违反，则按“每冲突一天”罚分 soft_weight（最多 2*soft_weight）。
    """
    night_on = (night_vars or {}).get("on_teacher_day", {})
    if not night_on:
        return []

    # Build noon_any[t,d] = OR(noon_male[t,d], noon_female[t,d]).
    noon_any: Dict[Tuple[str, str], cp_model.IntVar] = {}
    keys = set(noon_male.keys()) | set(noon_female.keys())
    for (t, d) in sorted(keys, key=lambda x: (str(x[0]), day_rank(x[1]))):
        m = noon_male.get((t, d))
        f = noon_female.get((t, d))
        if m is not None and f is not None:
            b = model.NewBoolVar(f"noon_any[{t},{d}]")
            model.AddMaxEquality(b, [m, f])
            noon_any[(t, d)] = b
        else:
            noon_any[(t, d)] = m if m is not None else f

    penalties: List[cp_model.IntVar] = []
    hard_teacher_set = teacher_name_set(hard_teachers or ([hard_teacher] if hard_teacher else []))

    for (t, d), noon_var in noon_any.items():
        if noon_var is None:
            continue
        prev_d = previous_day(d)
        if not prev_d:
            continue

        night_today = night_on.get((t, d), model.NewConstant(0))
        night_prev = night_on.get((t, prev_d), model.NewConstant(0))

        # Hard: configured teachers.
        if t in hard_teacher_set:
            model.Add(noon_var + night_today <= 1)
            # 放开“周一中午查寝”对前一天(周日)晚自习的硬联动，避免形成周一禁排。
            if d != MONDAY:
                model.Add(noon_var + night_prev <= 1)

        # Soft: any teacher, per-day penalty (may be 2*soft_weight).
        bad_today = _and2(model, noon_var, night_today, f"noon_night_same_day[{t},{d}]")
        bad_prev = _and2(model, noon_var, night_prev, f"noon_night_prev_day[{t},{d}]")

        penalties.append(int(soft_weight) * bad_today)
        register(
            "noon_prev_same_day_no_night_class_soft",
            "中午查寝前一天及当天不排晚自习(软)",
            int(soft_weight),
            bad_today,
            teacher=t,
            day=d,
            slot="当天",
            constraint_category="linkage",
            mode="soft",
            source_module="scheduler/model/constraints/day_noon_dorm_duty_constraints.py",
            description="若教师在d日安排中午查寝，则d日尽量不安排晚自习；星期一前一天视为星期日",
        )
        penalties.append(int(soft_weight) * bad_prev)
        register(
            "noon_prev_same_day_no_night_class_soft",
            "中午查寝前一天及当天不排晚自习(软)",
            int(soft_weight),
            bad_prev,
            teacher=t,
            day=d,
            slot="前一天",
            constraint_category="linkage",
            mode="soft",
            source_module="scheduler/model/constraints/day_noon_dorm_duty_constraints.py",
            description="若教师在d日安排中午查寝，则d-1日尽量不安排晚自习；星期一前一天视为星期日",
        )

    return penalties
