# -*- coding: utf-8 -*-
"""
What：晚自习学科/教师特殊规则（physics/math/history + 周五周日互斥）。
Why：周末/周五晚自习负担重，部分学科/教师有硬禁排或高惩罚。
How：在 y[(班级,学科,day,period)] 上做硬禁排；软惩罚在 soft_objective 中计入。
Weights：
    - evening_constraints.physics_fri_penalty（建议 200/500/1000）
    - evening_constraints.history_fri_penalty（建议 100/200/400）
    - evening_constraints.math_zeng_fri_p1_penalty（建议 200/300/500）
    - evening_constraints.math_zeng_fri_p2_penalty（建议 300/500/800）
    - evening_constraints.fri_sun_mutex_weight（建议 500/1000/2000）
Diagnostics：
    - outputs/诊断/晚自习_约束审计.txt
    - outputs/诊断/晚自习_约束检查.txt
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List, Tuple

from ortools.sat.python import cp_model
from scheduler.output_paths import resolve_project_path

from scheduler.model.constraints.global_binding_constraints import apply_global_night_binding_8_chem_9_bio
from scheduler.model.constraints.teacher_targets import teacher_names, teacher_norm_set

logger = logging.getLogger(__name__)

PHYSICS_NAMES = {"物理"}
HISTORY_NAMES = {"历史"}
MATH_NAMES = {"数学"}


def _norm_teacher(name: str) -> str:
    """教师名归一化（去空格）。"""
    return "".join(str(name).split())


def _find_teacher_key(all_teachers: List[str], target_name: str) -> str | None:
    """按归一化姓名在 all_teachers 中查找真实键名。"""
    target = _norm_teacher(target_name)
    for tch in all_teachers:
        if _norm_teacher(tch) == target:
            return tch
    return None


def _norm_subject(name: str) -> str:
    """学科名归一化。"""
    return str(name).strip()


def _is_physics(name: str) -> bool:
    """是否物理学科。"""
    return _norm_subject(name) in PHYSICS_NAMES


def _is_history(name: str) -> bool:
    """是否历史学科。"""
    return _norm_subject(name) in HISTORY_NAMES


def _is_math(name: str) -> bool:
    """是否数学学科。"""
    return _norm_subject(name) in MATH_NAMES


def _get_output_dir(rules: dict, project_root: Path) -> Path:
    """根据输出配置推导诊断文件目录。"""
    out_path = rules.get("output", {}).get("result_xlsx", "outputs/结果_MVP.xlsx")
    p = resolve_project_path(
        out_path,
        project_root=project_root.parent,
        label="rules.output.result_xlsx",
        reject_scheduler_outputs=True,
    )
    return p.parent


def apply_physics_math_hard_bans(model: cp_model.CpModel, vars: dict, ctx: dict, rules: dict) -> None:
    """物理/历史/数学晚自习硬禁排规则。"""
    cfg = rules.get("evening_constraints", {})
    if cfg.get("enabled", True) is False:
        return
    if cfg.get("enable_physics_math_special", True) is False:
        return

    physics_fri_mode = str(cfg.get("physics_fri_mode", "soft")).lower()
    history_fri_mode = str(cfg.get("history_fri_mode", "soft")).lower()

    y = vars["y"]
    cst = ctx["cst"]
    days = ctx["days"]
    periods = ctx["periods"]
    physics_sun_exceptions = teacher_norm_set(cfg.get("physics_sunday_exempt_teachers", []))
    physics_fri_exceptions = teacher_norm_set(cfg.get("physics_friday_exempt_teachers", []))
    history_fri_exceptions = teacher_norm_set(cfg.get("history_friday_exempt_teachers", []))
    math_friday_allowed = teacher_norm_set(cfg.get("math_friday_allowed_teachers", []))

    for (cls, subj), teacher in cst.items():
        subj_norm = _norm_subject(subj)
        t_norm = _norm_teacher(teacher)

        for d in days:
            for p in periods:
                if (
                    (_is_physics(subj_norm) and t_norm not in physics_sun_exceptions)
                    or _is_history(subj_norm)
                ) and d == "星期日":
                    model.Add(y[(cls, subj, d, p)] == 0)

                if (
                    _is_physics(subj_norm)
                    and d == "星期五"
                    and physics_fri_mode == "hard"
                    and t_norm not in physics_fri_exceptions
                ):
                    model.Add(y[(cls, subj, d, p)] == 0)

                if (
                    _is_history(subj_norm)
                    and d == "星期五"
                    and history_fri_mode == "hard"
                    and t_norm not in history_fri_exceptions
                ):
                    model.Add(y[(cls, subj, d, p)] == 0)

                if _is_math(subj_norm) and d == "星期日":
                    model.Add(y[(cls, subj, d, p)] == 0)

                if _is_math(subj_norm) and d == "星期五":
                    if t_norm not in math_friday_allowed:
                        model.Add(y[(cls, subj, d, p)] == 0)


def apply_fri_sun_mutex(model: cp_model.CpModel, vars: dict, ctx: dict, rules: dict) -> None:
    """晚自习硬互斥：周五+周日互斥、配置教师对周五互斥。"""
    cfg = rules.get("evening_constraints", {})
    if cfg.get("enabled", True) is False:
        return

    days = ctx["days"]
    on = vars.get("on_teacher_day", {})
    all_teachers = vars.get("all_teachers", [])
    fri_sun_exempt = {
        _norm_teacher(t)
        for t in (cfg.get("fri_sun_mutex_exempt_teachers", []) or [])
        if str(t).strip()
    }

    # 既有规则：教师周五+周日晚自习互斥（hard）
    if cfg.get("enable_fri_sun_mutex", False) and str(cfg.get("fri_sun_mutex_mode", "soft")).lower() == "hard":
        if "星期五" in days and "星期日" in days:
            for tch in all_teachers:
                if _norm_teacher(tch) in fri_sun_exempt:
                    continue
                if (tch, "星期五") in on and (tch, "星期日") in on:
                    model.Add(on[(tch, "星期五")] + on[(tch, "星期日")] <= 1)

    # 配置规则：指定两位教师周五晚自习不可同时安排（hard）
    if cfg.get("enable_yk_xxc_fri_mutex", True) and str(cfg.get("yk_xxc_fri_mutex_mode", "hard")).lower() == "hard":
        if "星期五" in days:
            pair = teacher_names(cfg.get("yk_xxc_fri_mutex_teachers", []))
            if len(pair) >= 2:
                left = _find_teacher_key(all_teachers, pair[0])
                right = _find_teacher_key(all_teachers, pair[1])
                if left and right and (left, "星期五") in on and (right, "星期五") in on:
                    model.Add(on[(left, "星期五")] + on[(right, "星期五")] <= 1)


def apply_night_binding_8_chem_9_bio(model: cp_model.CpModel, vars: dict, ctx: dict, rules: dict) -> None:
    """兼容入口：晚自习8班化学与9班生物全局绑定。"""
    apply_global_night_binding_8_chem_9_bio(model, vars, ctx, rules)


SubjectSyncTerm = Tuple[cp_model.IntVar, str, str, str]


def build_subject_sync_penalty_terms(model: cp_model.CpModel, vars: dict, ctx: dict, rules: dict) -> List[SubjectSyncTerm]:
    """同学科同时上晚自习的软惩罚变量及其科目/日期/节次。"""
    cfg = rules.get("evening_constraints", {})
    if cfg.get("enabled", True) is False:
        return []
    if cfg.get("enable_subject_sync", True) is False:
        return []

    y = vars["y"]
    cst = ctx["cst"]
    days = ctx["days"]
    periods = ctx["periods"]

    subjects = sorted({s for (_c, s) in cst.keys()})
    penalties: List[SubjectSyncTerm] = []

    # 预先按 (subj, day, period) 聚合，减少约束数量
    related_map: Dict[Tuple[str, str, str], List[cp_model.IntVar]] = {}
    for (cls, subj), _t in cst.items():
        for d in days:
            for p in periods:
                related_map.setdefault((subj, d, p), []).append(y[(cls, subj, d, p)])

    # active[subject, day, period] = 1 if any class has this subject at this slot
    for subj in subjects:
        for d in days:
            for p in periods:
                related = related_map.get((subj, d, p), [])
                active = model.NewBoolVar(f"subj_active[{subj},{d},{p}]")
                if related:
                    # 用 2 条线性约束替代逐个 v <= active
                    m = len(related)
                    model.Add(sum(related) >= active)
                    model.Add(sum(related) <= m * active)
                else:
                    model.Add(active == 0)
                penalties.append((active, subj, d, str(p)))

    return penalties


def build_subject_sync_penalties(model: cp_model.CpModel, vars: dict, ctx: dict, rules: dict) -> List[cp_model.IntVar]:
    """兼容旧接口：只返回同学科同步软惩罚变量。"""
    return [term for term, _subj, _day, _period in build_subject_sync_penalty_terms(model, vars, ctx, rules)]


def build_physics_math_soft_penalties(
    model: cp_model.CpModel,
    vars: dict,
    ctx: dict,
    rules: dict,
) -> List[Tuple[cp_model.IntVar, str]]:
    """物理/历史/数学周五软惩罚项（由 soft_objective 乘权重）。"""
    cfg = rules.get("evening_constraints", {})
    if cfg.get("enabled", True) is False:
        return []
    if cfg.get("enable_physics_math_special", True) is False:
        return []

    physics_fri_mode = str(cfg.get("physics_fri_mode", "soft")).lower()
    history_fri_mode = str(cfg.get("history_fri_mode", "soft")).lower()

    y = vars["y"]
    cst = ctx["cst"]
    days = ctx["days"]
    periods = ctx["periods"]

    penalties: List[Tuple[cp_model.IntVar, str]] = []
    physics_fri_exceptions = teacher_norm_set(cfg.get("physics_friday_exempt_teachers", []))
    history_fri_exceptions = teacher_norm_set(cfg.get("history_friday_exempt_teachers", []))
    math_friday_allowed = teacher_norm_set(cfg.get("math_friday_allowed_teachers", []))

    p1 = periods[0] if periods else "晚自习1"
    p2 = periods[1] if len(periods) > 1 else "晚自习2"

    for (cls, subj), teacher in cst.items():
        subj_norm = _norm_subject(subj)
        t_norm = _norm_teacher(teacher)
        for d in days:
            for p in periods:
                if _is_physics(subj_norm) and d == "星期五" and physics_fri_mode == "soft":
                    if t_norm not in physics_fri_exceptions:
                        penalties.append((y[(cls, subj, d, p)], "physics_fri"))
                if _is_history(subj_norm) and d == "星期五" and history_fri_mode == "soft":
                    if t_norm not in history_fri_exceptions:
                        penalties.append((y[(cls, subj, d, p)], "history_fri"))
                if _is_math(subj_norm) and d == "星期五" and t_norm in math_friday_allowed:
                    if p == p1:
                        penalties.append((y[(cls, subj, d, p)], "math_zeng_fri_p1"))
                    elif p == p2:
                        penalties.append((y[(cls, subj, d, p)], "math_zeng_fri_p2"))
                    else:
                        penalties.append((y[(cls, subj, d, p)], "math_zeng_fri_p2"))

    return penalties


def write_night_constraints_audit(project_root: Path, rules: dict, ctx: dict) -> None:
    """输出晚自习约束审计（模块/开关概览）。"""
    out_dir = _get_output_dir(rules, project_root)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "night_constraints_audit.txt"

    modules = [
        "hard_base.py: apply_hard_base",
        "hard_bans.py: apply_hard_bans",
        "hard_teacher_limits.py: apply_hard_teacher_limits",
        "checkin.py: apply_checkin",
        "soft_objective.py: apply_soft_objective",
        "night_special.py: apply_physics_math_hard_bans + subject_sync penalties",
        "night_single_class_period_split.py: apply_single_class_teacher_p1_p2_split + apply_double_class_teacher_weekday_alternate_p1_p2",
    ]

    cfg = rules.get("evening_constraints", {})
    enabled = cfg.get("enabled", True)

    lines = ["[Night Constraints Audit]"]
    lines.append("Modules=")
    for m in modules:
        lines.append(f"  - {m}")

    lines.append("TargetChecks=")
    lines.append(f"  subject_sync_soft_enabled={cfg.get('enable_subject_sync', True)}")
    lines.append(f"  physics_math_special_enabled={cfg.get('enable_physics_math_special', True)}")
    lines.append(f"  physics_fri_mode={cfg.get('physics_fri_mode', 'soft')}")
    lines.append(f"  history_fri_mode={cfg.get('history_fri_mode', 'soft')}")
    lines.append(f"  double_class_weekday_p1_p2_split_enabled={cfg.get('enable_double_class_weekday_p1_p2_split', True)}")
    lines.append(f"  double_class_weekday_p1_p2_mode={cfg.get('double_class_weekday_p1_p2_mode', 'hard')}")
    lines.append(f"  rules_evening_constraints_enabled={enabled}")
    lines.append("ExistingImplementations=")
    lines.append("  - hard_bans.subject_bans (历史周日禁排)")
    lines.append("  - no explicit physics/math special before night_special")

    path.write_text("\n".join(lines), encoding="utf-8")


def append_infeasible_audit(project_root: Path, rules: dict, reasons: List[str]) -> None:
    """在审计文件追加不可行原因列表。"""
    out_dir = _get_output_dir(rules, project_root)
    path = out_dir / "night_constraints_audit.txt"
    if not path.exists():
        return
    lines = path.read_text(encoding="utf-8").splitlines()
    lines.append("SolveStatus=INFEASIBLE")
    if reasons:
        lines.append("PossibleConflicts=")
        for r in reasons:
            lines.append(f"  - {r}")
    path.write_text("\n".join(lines), encoding="utf-8")


def write_night_constraint_checklist(
    project_root: Path,
    rules: dict,
    ctx: dict,
    vars: dict,
    solver: cp_model.CpSolver,
    status_name: str,
) -> None:
    """输出晚自习约束检查清单（禁排统计与同步统计）。"""
    out_dir = _get_output_dir(rules, project_root)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "night_constraint_checklist.txt"

    y = vars["y"]
    cst = ctx["cst"]
    days = ctx["days"]
    periods = ctx["periods"]
    cfg = rules.get("evening_constraints", {}) or {}
    physics_sun_exceptions = teacher_norm_set(cfg.get("physics_sunday_exempt_teachers", []))
    math_friday_allowed = teacher_norm_set(cfg.get("math_friday_allowed_teachers", []))

    def count_hits(filter_fn) -> int:
        cnt = 0
        for (cls, subj), teacher in cst.items():
            for d in days:
                for p in periods:
                    if filter_fn(cls, subj, teacher, d, p):
                        if solver.Value(y[(cls, subj, d, p)]) == 1:
                            cnt += 1
        return cnt

    physics_sun = count_hits(
        lambda _c, s, t, d, _p: _is_physics(s)
        and d == "星期日"
        and _norm_teacher(t) not in physics_sun_exceptions
    )
    physics_fri = count_hits(lambda _c, s, _t, d, _p: _is_physics(s) and d == "星期五")
    history_sun = count_hits(lambda _c, s, _t, d, _p: _is_history(s) and d == "星期日")
    history_fri = count_hits(lambda _c, s, _t, d, _p: _is_history(s) and d == "星期五")
    math_sun = count_hits(lambda _c, s, _t, d, _p: _is_math(s) and d == "星期日")
    math_fri_non_zeng = count_hits(
        lambda _c, s, t, d, _p: _is_math(s) and d == "星期五" and _norm_teacher(t) not in math_friday_allowed
    )
    math_fri_zeng = count_hits(
        lambda _c, s, t, d, _p: _is_math(s) and d == "星期五" and _norm_teacher(t) in math_friday_allowed
    )

    # subject sync stats: active teacher counts per (subj,day,period)
    subj_stats: List[str] = []
    for subj in sorted({s for (_c, s) in cst.keys()}):
        for d in days:
            for p in periods:
                cnt = sum(
                    solver.Value(y[(cls, subj, d, p)])
                    for (cls, s) in cst.keys()
                    if s == subj
                )
                subj_stats.append(f"  {subj} {d} {p}: {cnt}")

    lines = ["[Night Constraint Checklist]"]
    lines.append(f"SolveStatus={status_name}")
    lines.append(f"PhysicsSundayCount={physics_sun}")
    lines.append(f"PhysicsFridayCount={physics_fri}")
    lines.append(f"HistorySundayCount={history_sun}")
    lines.append(f"HistoryFridayCount={history_fri}")
    lines.append(f"MathSundayCount={math_sun}")
    lines.append(f"MathFridayNonZengCount={math_fri_non_zeng}")
    lines.append(f"MathFridayZengCount={math_fri_zeng}")
    lines.append("SubjectSyncStats=")
    lines.extend(subj_stats)

    path.write_text("\n".join(lines), encoding="utf-8")
