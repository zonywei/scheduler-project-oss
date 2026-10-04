# -*- coding: utf-8 -*-
"""
年级组值班模块（独立于查寝/晚自习排课主约束）。

目标：
- 对固定年级组成员按天安排值班；
- 约束周六、周日不排值班，其余天每天恰好 1 人；
- 值班人当晚无晚自习时给软惩罚；
- 提供次数均衡软约束（与现有公平性口径一致：相对最小值偏差惩罚）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Tuple

from ortools.sat.python import cp_model

from scheduler.diagnostics.penalty_registry import register


@dataclass
class GradeGroupDutyConfig:
    enabled: bool = True
    members: List[str] = field(default_factory=list)
    min_once_mode: str = "hard"  # hard|soft
    w_min_once: int = 1000
    daily_need_night_mode: str = "soft"  # hard|soft
    w_daily_need_night: int = 2000
    w_no_night_penalty: int = 1000
    enable_fairness: bool = True
    w_fairness_balance: int = 100


def _norm_name(x: object) -> str:
    return "".join(str(x or "").split())


def _norm_mode(x: object, default: str = "hard") -> str:
    m = str(x or default).strip().lower()
    return m if m in {"hard", "soft"} else default


def _find_teacher_key(all_teachers: List[str], name: str) -> str | None:
    target = _norm_name(name)
    for t in all_teachers:
        if _norm_name(t) == target:
            return t
    return None


def _and2(model: cp_model.CpModel, a, b, name: str) -> cp_model.IntVar:
    z = model.NewBoolVar(name)
    model.Add(z <= a)
    model.Add(z <= b)
    model.Add(z >= a + b - 1)
    return z


def apply_grade_group_duty_constraints(
    model: cp_model.CpModel,
    *,
    days: List[str],
    on_teacher_day: Dict[Tuple[str, str], cp_model.IntVar],
    all_teachers: List[str],
    cfg: GradeGroupDutyConfig,
) -> Tuple[List[cp_model.IntVar], Dict[Tuple[str, str], cp_model.IntVar], dict]:
    """
    返回：
    - penalties：软约束项（加入全局 objective）
    - grade_duty：值班变量 grade_duty[(teacher, day)]
    - info：诊断信息
    """
    info = {
        "enabled": bool(cfg.enabled),
        "members": list(cfg.members or []),
        "days": list(days or []),
        "min_once_mode": _norm_mode(cfg.min_once_mode, "hard"),
        "w_min_once": int(cfg.w_min_once),
        "daily_need_night_mode": _norm_mode(cfg.daily_need_night_mode, "soft"),
        "w_daily_need_night": int(cfg.w_daily_need_night),
        "w_no_night_penalty": int(cfg.w_no_night_penalty),
        "enable_fairness": bool(cfg.enable_fairness),
        "w_fairness_balance": int(cfg.w_fairness_balance),
    }
    if not cfg.enabled:
        return [], {}, info

    members = [str(t).strip() for t in (cfg.members or []) if str(t).strip()]
    info["members"] = members
    if not members or not days:
        return [], {}, info

    penalties: List[cp_model.IntVar] = []
    grade_duty: Dict[Tuple[str, str], cp_model.IntVar] = {}
    night_teacher_keys = sorted({t for (t, _d) in on_teacher_day.keys()})
    member_night_key = {t: _find_teacher_key(night_teacher_keys, t) for t in members}
    info["member_night_key"] = member_night_key

    # 除周六、周日外，每天至少有一个年级组成员有当日晚自习（soft/hard 可切换）
    daily_need_night_mode = _norm_mode(cfg.daily_need_night_mode, "soft")
    info["daily_need_night_mode"] = daily_need_night_mode
    daily_need_night_days = [d for d in days if d not in {"星期六", "星期日"}]
    info["daily_need_night_days"] = list(daily_need_night_days)
    for d in daily_need_night_days:
        has_vars = [
            on_teacher_day.get((member_night_key.get(t), d), model.NewConstant(0))
            if member_night_key.get(t)
            else model.NewConstant(0)
            for t in members
        ]
        group_has_night = model.NewBoolVar(f"grade_group_has_night[{d}]")
        if has_vars:
            model.Add(sum(has_vars) >= group_has_night)
            for v in has_vars:
                model.Add(v <= group_has_night)
        else:
            model.Add(group_has_night == 0)

        if daily_need_night_mode == "hard":
            model.Add(group_has_night == 1)
        else:
            miss = model.NewBoolVar(f"grade_group_daily_need_night_miss[{d}]")
            model.Add(miss + group_has_night == 1)
            penalties.append(cfg.w_daily_need_night * miss)
            register(
                "grade_group_daily_need_night",
                "年级组每日至少1人有晚自习",
                cfg.w_daily_need_night,
                miss,
                day=d,
                constraint_category="grade-duty",
                source_module="scheduler/model/constraints/grade_group_duty_constraints.py",
                description="软约束：当天年级组成员无人有晚自习",
                weight_key="day.grade_group_duty.w_daily_need_night",
            )

    for t in members:
        for d in days:
            grade_duty[(t, d)] = model.NewBoolVar(f"grade_duty[{t},{d}]")

    no_duty_days = {"星期六", "星期日"}
    for d in days:
        vars_day = [grade_duty[(t, d)] for t in members]
        if d in no_duty_days:
            for v in vars_day:
                model.Add(v == 0)
        else:
            model.Add(sum(vars_day) == 1)

    # 每位成员每周至少安排 1 次（soft/hard 可切换）
    min_once_mode = _norm_mode(cfg.min_once_mode, "soft")
    active_days = [d for d in days if d not in no_duty_days]
    info["min_once_mode"] = min_once_mode
    for t in members:
        if not active_days:
            break
        cnt = model.NewIntVar(0, len(active_days), f"grade_duty_week_count[{t}]")
        model.Add(cnt == sum(grade_duty[(t, d)] for d in active_days))
        if min_once_mode == "hard":
            model.Add(cnt >= 1)
        else:
            miss = model.NewBoolVar(f"grade_duty_min_once_miss[{t}]")
            model.Add(miss >= 1 - cnt)
            penalties.append(cfg.w_min_once * miss)
            register(
                "grade_duty_min_once",
                "年级组成员每周至少1次值班",
                cfg.w_min_once,
                miss,
                teacher=t,
                constraint_category="grade-duty",
                source_module="scheduler/model/constraints/grade_group_duty_constraints.py",
                description="软约束：成员周值班次数不足1次",
                weight_key="day.grade_group_duty.w_min_once",
            )

    # 软约束：值班人当晚无晚自习惩罚
    for t in members:
        night_key = member_night_key.get(t)
        for d in days:
            duty_var = grade_duty[(t, d)]
            has_night = on_teacher_day.get((night_key, d), model.NewConstant(0)) if night_key else model.NewConstant(0)
            no_night = model.NewBoolVar(f"grade_duty_no_night[{t},{d}]")
            model.Add(no_night + has_night == 1)
            viol = _and2(model, duty_var, no_night, f"grade_duty_no_night_viol[{t},{d}]")
            penalties.append(cfg.w_no_night_penalty * viol)
            register(
                "grade_duty_no_night_penalty",
                "年级组值班当晚无晚自习惩罚",
                cfg.w_no_night_penalty,
                viol,
                teacher=t,
                day=d,
                constraint_category="grade-duty",
                source_module="scheduler/model/constraints/grade_group_duty_constraints.py",
                description="值班教师当晚无晚自习时触发惩罚",
                weight_key="day.grade_group_duty.w_no_night_penalty",
            )

    # 软约束：成员周值班次数尽量均衡（相对最小值偏差）
    if cfg.enable_fairness:
        active_days = [d for d in days if d not in no_duty_days]
        if active_days:
            ub = len(active_days)
            min_cnt = model.NewIntVar(0, ub, "grade_duty_min_count")
            info["min_count_var"] = min_cnt
            for t in members:
                cnt = model.NewIntVar(0, ub, f"grade_duty_count[{t}]")
                model.Add(cnt == sum(grade_duty[(t, d)] for d in active_days))
                model.Add(cnt >= min_cnt)
                dev = model.NewIntVar(0, ub, f"grade_duty_dev[{t}]")
                model.Add(dev == cnt - min_cnt)
                penalties.append(cfg.w_fairness_balance * dev)
                register(
                    "grade_duty_fairness_balance",
                    "年级组值班次数均衡",
                    cfg.w_fairness_balance,
                    dev,
                    teacher=t,
                    constraint_category="fairness",
                    source_module="scheduler/model/constraints/grade_group_duty_constraints.py",
                    description="该成员值班次数高于组内最小值的偏差",
                    weight_key="day.grade_group_duty.w_fairness_balance",
                )

    return penalties, grade_duty, info


def extract_grade_group_duty_map(
    val: cp_model.CpSolver | cp_model.CpSolverSolutionCallback,
    grade_duty: Dict[Tuple[str, str], cp_model.IntVar],
    days: List[str],
    members: List[str],
) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for d in days:
        if d == "星期六":
            out[d] = ""
            continue
        selected = ""
        for t in members:
            v = grade_duty.get((t, d))
            if v is not None and val.Value(v) == 1:
                selected = t
                break
        out[d] = selected
    return out


def extract_grade_group_available_map(
    val: cp_model.CpSolver | cp_model.CpSolverSolutionCallback,
    on_teacher_day: Dict[Tuple[str, str], cp_model.IntVar],
    days: List[str],
    members: List[str],
) -> Dict[str, str]:
    out: Dict[str, str] = {}
    all_teachers = sorted({t for (t, _d) in on_teacher_day.keys()})
    for d in days:
        if d == "星期六":
            out[d] = ""
            continue
        names: List[str] = []
        for m in members:
            key = _find_teacher_key(all_teachers, m)
            v = on_teacher_day.get((key, d)) if key else None
            if v is not None and val.Value(v) == 1:
                names.append(m)
        out[d] = "，".join(names)
    return out


def write_grade_group_duty_audit(out_dir: Path, info: dict) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    lines = [
        "[Grade Group Duty Audit]",
        f"enabled={info.get('enabled', False)}",
        f"members={info.get('members', [])}",
        f"days={info.get('days', [])}",
        f"min_once_mode={info.get('min_once_mode', 'hard')}",
        f"w_min_once={info.get('w_min_once', 1000)}",
        f"daily_need_night_mode={info.get('daily_need_night_mode', 'soft')}",
        f"w_daily_need_night={info.get('w_daily_need_night', 2000)}",
        f"w_no_night_penalty={info.get('w_no_night_penalty', 1000)}",
        f"enable_fairness={info.get('enable_fairness', True)}",
        f"w_fairness_balance={info.get('w_fairness_balance', 100)}",
        f"member_night_key={info.get('member_night_key', {})}",
    ]
    (out_dir / "年级组值班_审计.txt").write_text("\n".join(lines), encoding="utf-8")


def write_grade_group_duty_checklist(
    out_dir: Path,
    val: cp_model.CpSolver | cp_model.CpSolverSolutionCallback,
    *,
    info: dict,
    grade_duty: Dict[Tuple[str, str], cp_model.IntVar],
    on_teacher_day: Dict[Tuple[str, str], cp_model.IntVar],
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    days = list(info.get("days", []))
    members = list(info.get("members", []))
    lines = ["[Grade Group Duty Checklist]"]
    if not info.get("enabled", False):
        lines.append("enabled=false")
        (out_dir / "年级组值班_检查.txt").write_text("\n".join(lines), encoding="utf-8")
        return

    duty_map = extract_grade_group_duty_map(val, grade_duty, days, members)
    avail_map = extract_grade_group_available_map(val, on_teacher_day, days, members)
    lines.append("DutyByDay=")
    for d in days:
        lines.append(f"  {d}: {duty_map.get(d, '')}")
    lines.append("AvailableByNight=")
    for d in days:
        lines.append(f"  {d}: {avail_map.get(d, '')}")
    lines.append("DailyAtLeastOneNightByGroup=")
    all_teachers = sorted({t for (t, _d) in on_teacher_day.keys()})
    for d in days:
        cnt = 0
        for m in members:
            key = _find_teacher_key(all_teachers, m)
            v = on_teacher_day.get((key, d)) if key else None
            cnt += int(v is not None and val.Value(v) == 1)
        lines.append(f"  {d}: {'Y' if cnt >= 1 else 'N'} (count={cnt})")
    lines.append("CountByMember=")
    for t in members:
        cnt = sum(val.Value(grade_duty[(t, d)]) for d in days if (t, d) in grade_duty)
        lines.append(f"  {t}: {cnt}")
    lines.append(f"MinOnceMode={info.get('min_once_mode', 'hard')} MinOnceWeight={info.get('w_min_once', 1000)}")
    lines.append(
        f"DailyNeedNightMode={info.get('daily_need_night_mode', 'soft')} "
        f"DailyNeedNightWeight={info.get('w_daily_need_night', 2000)}"
    )

    (out_dir / "年级组值班_检查.txt").write_text("\n".join(lines), encoding="utf-8")
