# -*- coding: utf-8 -*-
"""
查寝/值班联合约束（午查 + 课前值班 + 晚查）。

模块目标：
- 复用现有 duty 变量（中午查寝、下午课前值班、晚查寝）做联合约束；
- 不改变既有约束语义，只新增联合层约束；
- 软约束通过 penalty_registry 登记到 event_log（teacher_name 可追溯）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Tuple

import pandas as pd
from ortools.sat.python import cp_model

from scheduler.diagnostics.penalty_registry import register
from scheduler.model.constraints.day_pairs import adjacent_day_pairs
from scheduler.model.constraints.teacher_targets import teacher_name_set
from scheduler.data.teacher_table_schema import (
    configured_teacher_table_columns,
    head_gender_pools,
    load_teacher_table_frame,
)


@dataclass
class DutyJointConfig:
    enabled: bool = True
    enable_soft_male_duty_balance: bool = True
    w_soft_male_duty_balance: int = 60
    male_max_min_mode: str = "soft"  # hard|soft
    w_male_max_min_gap: int = 600
    male_total_target: int = 2
    male_total_target_mode: str = "hard"  # hard|soft
    w_male_total_target_deviation: int = 2500
    enable_female_head_extra_noon_if_no_night: bool = True
    female_head_extra_noon_mode: str = "hard"  # hard|soft
    female_min_noon_night_mode: str = "soft"  # hard|soft
    w_female_min_noon_night: int = 2000
    enable_female_two_duty_penalty: bool = True
    w_female_two_duty_penalty: int = 3000
    pm_pre_class_no_consecutive_mode: str = "hard"  # hard|soft
    w_pm_pre_class_no_consecutive: int = 2000
    female_total_limit_extra_teachers: List[str] = field(default_factory=list)
    male_balance_exclude_teachers: List[str] = field(default_factory=list)
    male_total_eq2_exclude_teachers: List[str] = field(default_factory=list)
    noon_max1_teachers: List[str] = field(default_factory=list)
    total_noon_night_max1_teachers: List[str] = field(default_factory=list)
    male_noon_rule_exempt_teachers: List[str] = field(default_factory=list)


def _norm(x: object) -> str:
    if pd.isna(x):
        return ""
    return str(x).strip()


def _norm_mode(x: object, default: str = "soft") -> str:
    m = str(x or default).strip().lower()
    return m if m in {"hard", "soft"} else default


def _day_order(day: str) -> int:
    order = {
        "星期一": 1,
        "星期二": 2,
        "星期三": 3,
        "星期四": 4,
        "星期五": 5,
        "星期六": 6,
        "星期日": 7,
    }
    return order.get(day, 99)


def load_head_gender_sets(io_cfg: dict, base_dir: Path) -> Tuple[List[str], List[str]]:
    """从教师定位表读取男/女班主任名单（供 day-only 模式调用）。"""
    _class_col, head_col, gender_col = configured_teacher_table_columns(io_cfg)
    df = load_teacher_table_frame(io_cfg, base_dir)
    if df.empty:
        return [], []
    return head_gender_pools(df, head_col=head_col, gender_col=gender_col, strict_gender=False)


def _get_var_or_zero(var_map: Dict[Tuple[str, str], cp_model.IntVar], key: Tuple[str, str]):
    v = var_map.get(key)
    return v


def add_duty_joint_constraints(
    model: cp_model.CpModel,
    *,
    days: List[str],
    noon_male_duty: Dict[Tuple[str, str], cp_model.IntVar],
    noon_female_duty: Dict[Tuple[str, str], cp_model.IntVar],
    pm_pre_class_duty: Dict[Tuple[str, str], cp_model.IntVar],
    night_dorm_duty_male: Dict[Tuple[str, str], cp_model.IntVar],
    night_dorm_duty_female: Dict[Tuple[str, str], cp_model.IntVar],
    male_heads: List[str],
    female_heads: List[str],
    cfg: DutyJointConfig,
) -> Tuple[List[cp_model.IntVar], dict]:
    """
    新增联合约束入口。

    返回：
    - penalties: 软约束项（加入既有 objective_terms）
    - info: 诊断结构（用于写 checklist）
    """
    if not cfg.enabled:
        return [], {"enabled": False}
    if not any(
        (
            male_heads,
            female_heads,
            noon_male_duty,
            noon_female_duty,
            pm_pre_class_duty,
            night_dorm_duty_male,
            night_dorm_duty_female,
        )
    ):
        # 没有班主任/性别元数据时，课程排课仍可独立运行；值班联动不应
        # 用空候选池制造一个与课程数据无关的不可行模型。
        return [], {"enabled": False, "skipped": "teacher_table_head_gender_not_provided"}

    penalties: List[cp_model.IntVar] = []
    info: dict = {
        "enabled": True,
        "days": days,
        "F_ALL": sorted(set(female_heads)),
        "M_ALL": sorted(set(male_heads)),
    }

    # 集合定义：所有教师特例来自配置，默认不绑定具体姓名。
    f_all = set(female_heads)
    f_except_cfg = teacher_name_set(cfg.female_total_limit_extra_teachers)
    m_balance_exclude = teacher_name_set(cfg.male_balance_exclude_teachers)
    m_total_eq2_exclude = teacher_name_set(cfg.male_total_eq2_exclude_teachers)
    noon_max1_teachers = teacher_name_set(cfg.noon_max1_teachers)
    total_noon_night_max1_teachers = teacher_name_set(cfg.total_noon_night_max1_teachers)
    male_noon_rule_exempt = teacher_name_set(cfg.male_noon_rule_exempt_teachers) | noon_max1_teachers
    f_main = sorted(f_all - f_except_cfg)
    f_except = sorted(f_all & f_except_cfg)
    m_main = sorted(set(male_heads) - m_balance_exclude)

    info["F_MAIN"] = f_main
    info["F_EXCEPT"] = f_except
    info["M_MAIN"] = m_main

    # 构造计数变量
    noon_count: Dict[str, cp_model.IntVar] = {}
    night_count: Dict[str, cp_model.IntVar] = {}
    total_count: Dict[str, cp_model.IntVar] = {}

    all_teachers = sorted(set(female_heads) | set(male_heads) | {t for (t, _) in noon_male_duty.keys()} | {t for (t, _) in noon_female_duty.keys()})

    for t in all_teachers:
        noon_terms = []
        night_terms = []
        for d in days:
            v_noon_m = _get_var_or_zero(noon_male_duty, (t, d))
            v_noon_f = _get_var_or_zero(noon_female_duty, (t, d))
            if v_noon_m is not None:
                noon_terms.append(v_noon_m)
            if v_noon_f is not None:
                noon_terms.append(v_noon_f)

            v_night_m = _get_var_or_zero(night_dorm_duty_male, (t, d))
            v_night_f = _get_var_or_zero(night_dorm_duty_female, (t, d))
            if v_night_m is not None:
                night_terms.append(v_night_m)
            if v_night_f is not None:
                night_terms.append(v_night_f)

        n_var = model.NewIntVar(0, max(0, len(noon_terms)), f"duty_joint_noon_count[{t}]")
        if noon_terms:
            model.Add(n_var == sum(noon_terms))
        else:
            model.Add(n_var == 0)
        noon_count[t] = n_var

        k_var = model.NewIntVar(0, max(0, len(night_terms)), f"duty_joint_night_count[{t}]")
        if night_terms:
            model.Add(k_var == sum(night_terms))
        else:
            model.Add(k_var == 0)
        night_count[t] = k_var

        tot = model.NewIntVar(0, len(days) * 4, f"duty_joint_total_count[{t}]")
        model.Add(tot == n_var + k_var)
        total_count[t] = tot

    noon_teachers = {t for (t, _d) in noon_male_duty.keys()} | {t for (t, _d) in noon_female_duty.keys()}

    # 硬约束：所有班主任每周午查+晚查总次数至少 1 次
    for t in sorted(set(male_heads) | set(female_heads)):
        if t in total_count:
            model.Add(total_count[t] >= 1)

    female_extra_mode = _norm_mode(cfg.female_head_extra_noon_mode, "hard")
    enable_female_extra = bool(cfg.enable_female_head_extra_noon_if_no_night) and female_extra_mode == "hard"

    # 约束1：女性午查+晚查次数上限（硬）
    # 当启用“无晚查可午查两次”规则时，改由新规则统一约束，不再叠加旧上限（避免冲突）
    if not enable_female_extra:
        for t in f_main:
            if t in total_count:
                model.Add(total_count[t] <= 1)
        for t in f_except:
            if t in total_count:
                model.Add(total_count[t] <= 2)

    # 约束1.1：女班主任若本周无晚查寝，则中午查寝可到2次；否则最多1次
    # 线性形式：sum_d noon_female(t,d) + sum_d checkin_f(t,d) <= 2
    # 等价于：夜查=0 -> 午查<=2；夜查=1 -> 午查<=1（夜查通常周上限1）
    if enable_female_extra:
        for t in sorted(set(female_heads)):
            noon_terms = [v for (tt, _d), v in noon_female_duty.items() if tt == t]
            night_terms = [v for (tt, _d), v in night_dorm_duty_female.items() if tt == t]
            ub = len(days) * 2
            total = model.NewIntVar(0, ub, f"duty_joint_female_noon_night_total[{t}]")
            model.Add(total == sum(noon_terms + night_terms) if (noon_terms or night_terms) else 0)
            model.Add(total <= 2)
            register(
                "duty_joint_female_extra_noon_if_no_night",
                "女班主任无晚查可午查两次",
                0,
                total,
                teacher=t,
                mode="hard",
                constraint_category="dorm-duty",
                source_module="scheduler/model/constraints/duty_joint_constraints.py",
                description="硬约束：sum(noon_female)+sum(checkin_f)<=2；无晚查时午查最多2次",
            )

    # 配置项：指定教师一周中午查寝最多一次（硬）
    for t in sorted(noon_max1_teachers):
        if t in noon_count:
            model.Add(noon_count[t] <= 1)

    # 配置项：指定教师一周午查寝+晚查寝（覆盖男寝+女寝）最多一次（硬）
    for t in sorted(total_noon_night_max1_teachers):
        if t in total_count:
            model.Add(total_count[t] <= 1)

    # 男性班主任（排除配置名单）每周午查+晚查总次数目标。
    # hard 保持旧语义；soft 用可审计罚分承接真实学校中“总需求超过人均2次”的情况。
    male_total_target = max(0, int(cfg.male_total_target))
    male_total_target_mode = _norm_mode(cfg.male_total_target_mode, "hard")
    male_total_target_deviation: Dict[str, dict] = {}
    for t in sorted(set(male_heads) - m_total_eq2_exclude):
        if t in total_count:
            if male_total_target_mode == "hard":
                model.Add(total_count[t] == male_total_target)
            else:
                ub = len(days) * 4
                over = model.NewIntVar(0, ub, f"duty_joint_male_total_over_target[{t}]")
                under = model.NewIntVar(0, ub, f"duty_joint_male_total_under_target[{t}]")
                model.Add(over >= total_count[t] - male_total_target)
                model.Add(under >= male_total_target - total_count[t])
                penalties.append(cfg.w_male_total_target_deviation * over)
                penalties.append(cfg.w_male_total_target_deviation * under)
                register(
                    "duty_joint_male_total_target_over",
                    "男班主任午查+晚查次数超过目标",
                    cfg.w_male_total_target_deviation,
                    over,
                    teacher=t,
                    constraint_category="dorm-duty",
                    source_module="scheduler/model/constraints/duty_joint_constraints.py",
                    description=f"软约束：男班主任本周午查+晚查总次数超过目标 {male_total_target}",
                )
                register(
                    "duty_joint_male_total_target_under",
                    "男班主任午查+晚查次数低于目标",
                    cfg.w_male_total_target_deviation,
                    under,
                    teacher=t,
                    constraint_category="dorm-duty",
                    source_module="scheduler/model/constraints/duty_joint_constraints.py",
                    description=f"软约束：男班主任本周午查+晚查总次数低于目标 {male_total_target}",
                )
                male_total_target_deviation[t] = {"over": over, "under": under}

    # 男班主任中午查寝周口径（硬）：
    # - 若本周无晚查寝：中午查寝必须 2 次
    # - 若本周有晚查寝：中午查寝最多 1 次
    for t in sorted(set(male_heads)):
        if t not in noon_teachers or t in male_noon_rule_exempt:
            continue
        if t not in noon_count or t not in night_count:
            continue
        no_night = model.NewBoolVar(f"duty_joint_male_no_night[{t}]")
        model.Add(night_count[t] == 0).OnlyEnforceIf(no_night)
        model.Add(night_count[t] >= 1).OnlyEnforceIf(no_night.Not())
        model.Add(noon_count[t] == 2).OnlyEnforceIf(no_night)
        model.Add(noon_count[t] <= 1).OnlyEnforceIf(no_night.Not())

    # 女班主任每周“午查寝+晚查寝（覆盖男寝+女寝）”至少一次（soft/hard 可切换）
    female_min_mode = _norm_mode(cfg.female_min_noon_night_mode, "soft")
    if female_min_mode == "hard":
        for t in sorted(set(female_heads)):
            if t in total_count:
                model.Add(total_count[t] >= 1)
    else:
        for t in sorted(set(female_heads)):
            if t not in total_count:
                continue
            miss = model.NewIntVar(0, 1, f"duty_joint_female_min_noon_night_miss[{t}]")
            model.Add(miss >= 1 - total_count[t])
            penalties.append(cfg.w_female_min_noon_night * miss)
            register(
                "duty_joint_female_min_noon_night",
                "女班主任每周午查+晚查至少1次",
                cfg.w_female_min_noon_night,
                miss,
                teacher=t,
                constraint_category="dorm-duty",
                source_module="scheduler/model/constraints/duty_joint_constraints.py",
                description="软约束：女班主任每周午查+晚查总次数不足1次的缺口",
            )

    # 女教师一周“查寝总次数>=2”按人头罚分（每人一次）
    if cfg.enable_female_two_duty_penalty:
        for t in sorted(set(female_heads)):
            if t not in total_count:
                continue
            hit_two = model.NewBoolVar(f"duty_joint_female_two_duty_hit[{t}]")
            model.Add(total_count[t] >= 2).OnlyEnforceIf(hit_two)
            model.Add(total_count[t] <= 1).OnlyEnforceIf(hit_two.Not())
            penalties.append(cfg.w_female_two_duty_penalty * hit_two)
            register(
                "duty_joint_female_two_duty_penalty",
                "女教师每周查寝两次惩罚",
                cfg.w_female_two_duty_penalty,
                hit_two,
                teacher=t,
                constraint_category="dorm-duty",
                source_module="scheduler/model/constraints/duty_joint_constraints.py",
                description="软约束：该女教师本周午查+晚查总次数达到2次",
            )

    # 约束2.1：男班主任午查+晚查 max-min<=1（soft/hard 可切换）
    min_total = None
    max_total = None
    male_gap = None
    male_gap_excess = None
    male_max_min_mode = _norm_mode(cfg.male_max_min_mode, "soft")
    if m_main:
        ub = len(days) * 4
        min_total = model.NewIntVar(0, ub, "duty_joint_male_min_total")
        max_total = model.NewIntVar(0, ub, "duty_joint_male_max_total")
        for t in m_main:
            if t not in total_count:
                continue
            model.Add(total_count[t] >= min_total)
            model.Add(total_count[t] <= max_total)
        male_gap = model.NewIntVar(0, ub, "duty_joint_male_gap")
        model.Add(male_gap == max_total - min_total)
        if male_max_min_mode == "hard":
            model.Add(male_gap <= 1)
        else:
            male_gap_excess = model.NewIntVar(0, ub, "duty_joint_male_gap_excess")
            model.Add(male_gap_excess >= male_gap - 1)
            penalties.append(cfg.w_male_max_min_gap * male_gap_excess)
            register(
                "duty_joint_male_max_min_gap",
                "男班主任午查+晚查 max-min 超阈值",
                cfg.w_male_max_min_gap,
                male_gap_excess,
                constraint_category="fairness",
                source_module="scheduler/model/constraints/duty_joint_constraints.py",
                description="男班主任午查+晚查总次数的 max-min 超过 1 的超额",
            )

    # 约束2.2：男班主任均衡软约束（可选）
    if cfg.enable_soft_male_duty_balance and m_main and min_total is not None:
        for t in m_main:
            if t not in total_count:
                continue
            dev = model.NewIntVar(0, len(days) * 4, f"duty_joint_male_dev[{t}]")
            model.Add(dev == total_count[t] - min_total)
            penalties.append(cfg.w_soft_male_duty_balance * dev)
            register(
                "soft_male_duty_balance",
                "男班主任午查+晚查次数均衡",
                cfg.w_soft_male_duty_balance,
                dev,
                teacher=t,
                constraint_category="fairness",
                source_module="scheduler/model/constraints/duty_joint_constraints.py",
                description="该老师午查+晚查总次数高于男班主任最小值的偏差",
            )

    # 约束3：中午查寝 + 下午课前值班 同日互斥（硬）
    union_teachers = sorted(set(all_teachers) | {t for (t, _) in pm_pre_class_duty.keys()})
    for t in union_teachers:
        for d in days:
            noon_terms = []
            v_nm = _get_var_or_zero(noon_male_duty, (t, d))
            v_nf = _get_var_or_zero(noon_female_duty, (t, d))
            if v_nm is not None:
                noon_terms.append(v_nm)
            if v_nf is not None:
                noon_terms.append(v_nf)
            if noon_terms:
                noon_any = model.NewIntVar(0, len(noon_terms), f"duty_joint_noon_any[{t},{d}]")
                model.Add(noon_any == sum(noon_terms))
            else:
                noon_any = model.NewConstant(0)

            pm_any = _get_var_or_zero(pm_pre_class_duty, (t, d))
            if pm_any is None:
                pm_any = model.NewConstant(0)
            model.Add(noon_any + pm_any <= 1)

            # 约束3.1：所有班主任同日不得同时中午查寝+晚查寝（硬）
            night_terms = []
            v_cm = _get_var_or_zero(night_dorm_duty_male, (t, d))
            v_cf = _get_var_or_zero(night_dorm_duty_female, (t, d))
            if v_cm is not None:
                night_terms.append(v_cm)
            if v_cf is not None:
                night_terms.append(v_cf)
            if night_terms:
                night_any = model.NewIntVar(0, len(night_terms), f"duty_joint_night_any[{t},{d}]")
                model.Add(night_any == sum(night_terms))
            else:
                night_any = model.NewConstant(0)
            model.Add(noon_any + night_any <= 1)

    # 约束4：下午课前值班不连续两天（soft/hard 可切换）
    pm_days_sorted = sorted(days, key=_day_order)
    pm_adjacent_pairs: List[Tuple[str, str]] = adjacent_day_pairs(pm_days_sorted, include_sun_mon=True)
    pm_teachers = sorted({t for (t, _d) in pm_pre_class_duty.keys()})
    pm_consecutive_mode = _norm_mode(cfg.pm_pre_class_no_consecutive_mode, "hard")
    for t in pm_teachers:
        for d1, d2 in pm_adjacent_pairs:
            v1 = _get_var_or_zero(pm_pre_class_duty, (t, d1))
            v2 = _get_var_or_zero(pm_pre_class_duty, (t, d2))
            if v1 is None or v2 is None:
                continue
            if pm_consecutive_mode == "hard":
                model.Add(v1 + v2 <= 1)
            else:
                viol = model.NewBoolVar(f"duty_joint_pm_pre_consecutive[{t},{d1},{d2}]")
                model.Add(viol <= v1)
                model.Add(viol <= v2)
                model.Add(viol >= v1 + v2 - 1)
                penalties.append(cfg.w_pm_pre_class_no_consecutive * viol)
                register(
                    "duty_joint_pm_pre_class_no_consecutive",
                    "下午课前值班不连续两天",
                    cfg.w_pm_pre_class_no_consecutive,
                    viol,
                    teacher=t,
                    day=f"{d1}->{d2}",
                    constraint_category="dorm-duty",
                    source_module="scheduler/model/constraints/duty_joint_constraints.py",
                    description="软约束：同一教师连续两天均安排下午课前值班",
                )

    info["noon_count"] = noon_count
    info["night_count"] = night_count
    info["total_count"] = total_count
    info["min_total"] = min_total
    info["max_total"] = max_total
    info["male_gap"] = male_gap
    info["male_gap_excess"] = male_gap_excess
    info["male_max_min_mode"] = male_max_min_mode
    info["male_max_min_soft_weight"] = cfg.w_male_max_min_gap
    info["soft_weight"] = cfg.w_soft_male_duty_balance
    info["male_total_target"] = male_total_target
    info["male_total_target_mode"] = male_total_target_mode
    info["male_total_target_weight"] = int(cfg.w_male_total_target_deviation)
    info["male_total_target_deviation"] = male_total_target_deviation
    info["female_extra_noon_mode"] = female_extra_mode
    info["female_extra_noon_enabled"] = bool(cfg.enable_female_head_extra_noon_if_no_night)
    info["female_min_noon_night_mode"] = female_min_mode
    info["female_min_noon_night_weight"] = int(cfg.w_female_min_noon_night)
    info["female_two_duty_penalty_enabled"] = bool(cfg.enable_female_two_duty_penalty)
    info["female_two_duty_penalty_weight"] = int(cfg.w_female_two_duty_penalty)
    info["pm_pre_class_no_consecutive_mode"] = pm_consecutive_mode
    info["pm_pre_class_no_consecutive_weight"] = int(cfg.w_pm_pre_class_no_consecutive)
    return penalties, info


def write_duty_joint_checklist(
    out_dir: Path,
    val: cp_model.CpSolver | cp_model.CpSolverSolutionCallback,
    info: dict,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    lines = ["[Duty Joint Checklist]"]
    if not info.get("enabled", False):
        lines.append("enabled=false")
        (out_dir / "查寝值班联合_检查.txt").write_text("\n".join(lines), encoding="utf-8")
        return

    f_main = info.get("F_MAIN", [])
    f_except = info.get("F_EXCEPT", [])
    m_main = info.get("M_MAIN", [])
    total_count = info.get("total_count", {})
    min_total = info.get("min_total")
    max_total = info.get("max_total")
    male_gap = info.get("male_gap")
    male_gap_excess = info.get("male_gap_excess")
    male_max_min_mode = str(info.get("male_max_min_mode", "soft"))
    male_total_target = int(info.get("male_total_target", 2))
    male_total_target_mode = str(info.get("male_total_target_mode", "hard"))
    male_total_target_deviation = info.get("male_total_target_deviation", {})

    lines.append(f"F_MAIN={f_main}")
    lines.append(f"F_EXCEPT={f_except}")
    lines.append(f"M_MAIN={m_main}")
    lines.append("FemaleCounts=")
    for t in f_main + f_except:
        if t in total_count:
            lines.append(f"  {t}: {val.Value(total_count[t])}")
    if min_total is not None and max_total is not None:
        lines.append(f"MaleMin={val.Value(min_total)} MaleMax={val.Value(max_total)} Diff={val.Value(max_total)-val.Value(min_total)}")
    lines.append(
        f"MaleMaxMinMode={male_max_min_mode} MaleMaxMinSoftWeight={int(info.get('male_max_min_soft_weight', 0))}"
    )
    if male_gap is not None:
        lines.append(f"MaleGap={val.Value(male_gap)}")
    if male_gap_excess is not None:
        lines.append(f"MaleGapExcess={val.Value(male_gap_excess)}")
    lines.append(f"MaleTotalTarget={male_total_target}")
    lines.append(f"MaleTotalTargetMode={male_total_target_mode}")
    if male_total_target_mode == "soft" and isinstance(male_total_target_deviation, dict):
        lines.append("MaleTotalTargetDeviation=")
        for t in sorted(male_total_target_deviation):
            pair = male_total_target_deviation.get(t) or {}
            over = pair.get("over")
            under = pair.get("under")
            over_value = val.Value(over) if over is not None else 0
            under_value = val.Value(under) if under is not None else 0
            if over_value or under_value:
                lines.append(f"  {t}: over={over_value} under={under_value}")
    lines.append(f"SoftWeight={info.get('soft_weight', 0)}")

    (out_dir / "查寝值班联合_检查.txt").write_text("\n".join(lines), encoding="utf-8")


def write_duty_joint_audit(out_dir: Path, info: dict) -> None:
    """输出联合约束审计（用于不可行时快速定位约束口径）。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    lines = [
        "[Duty Joint Audit]",
        "hard_0=所有班主任每周午查+晚查总次数>=1",
        "hard_1=女性班主任午查+晚查次数上限(F_MAIN<=1,F_EXCEPT<=2)",
        "hard_1_0=女班主任中午查寝周上限<=1（中午模块）",
        "rule_2=男班主任午查+晚查总次数 max-min<=1（排除配置名单，soft/hard 可切换）",
        "hard_3=中午查寝与下午课前值班同日互斥",
        "hard_3_1=所有班主任同日不得同时中午查寝+晚查寝",
        "hard_1_1=女班主任无晚查可午查两次（sum(noon_female)+sum(checkin_f)<=2）",
        "hard_1_2=男班主任：无晚查寝=>中午查寝2次；有晚查寝=>中午查寝<=1",
        "rule_1_3=男性班主任（排除配置名单）每周午查+晚查总次数目标（hard/soft 可切换）",
        "rule_1_2=女班主任每周午查+晚查至少1次（soft/hard 可切换）",
        "rule_4=下午课前值班不连续两天（soft/hard 可切换）",
        "soft_1=soft_male_duty_balance（男班主任午查+晚查次数均衡）",
        f"rule_2_mode={info.get('male_max_min_mode', 'soft')}",
        f"rule_2_soft_weight={info.get('male_max_min_soft_weight', 0)}",
        f"male_total_target={info.get('male_total_target', 2)}",
        f"male_total_target_mode={info.get('male_total_target_mode', 'hard')}",
        f"male_total_target_weight={info.get('male_total_target_weight', 2500)}",
        f"female_extra_noon_enabled={info.get('female_extra_noon_enabled', False)}",
        f"female_extra_noon_mode={info.get('female_extra_noon_mode', 'hard')}",
        f"female_min_noon_night_mode={info.get('female_min_noon_night_mode', 'soft')}",
        f"female_min_noon_night_weight={info.get('female_min_noon_night_weight', 2000)}",
        f"pm_pre_class_no_consecutive_mode={info.get('pm_pre_class_no_consecutive_mode', 'hard')}",
        f"pm_pre_class_no_consecutive_weight={info.get('pm_pre_class_no_consecutive_weight', 2000)}",
        f"F_MAIN={info.get('F_MAIN', [])}",
        f"F_EXCEPT={info.get('F_EXCEPT', [])}",
        f"M_MAIN={info.get('M_MAIN', [])}",
    ]
    (out_dir / "查寝值班联合_审计.txt").write_text("\n".join(lines), encoding="utf-8")
