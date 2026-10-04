# model/constraints/checkin.py
"""
查寝模块（硬约束为主）：
- 每天指派 男X人、女Y人
- 每个班主任一周最多被指派 N 次
- 可选：被指派的人当天必须有晚自习课（require_teacher_has_class_that_day）

注意：本文件只加约束，不负责创建变量。
"""
from __future__ import annotations

from typing import List

from ortools.sat.python import cp_model

from scheduler.diagnostics.penalty_registry import register
from scheduler.model.constraints.teacher_targets import teacher_names, teacher_norm_set


def _norm_name(x: object) -> str:
    return str(x or "").strip()


def _norm_mode(x: object, default: str = "hard") -> str:
    m = str(x or default).strip().lower()
    return m if m in {"hard", "soft"} else default


def _same_day_class_mode(cfg: dict) -> str:
    raw_mode = cfg.get("require_teacher_has_class_that_day_mode")
    if raw_mode is not None:
        mode = str(raw_mode or "").strip().lower()
        if mode in {"hard", "soft", "off"}:
            return mode
    return "hard" if bool(cfg.get("require_teacher_has_class_that_day", True)) else "off"


def _add_same_day_class_penalty(model, penalties: List, teacher: str, day: str, checkin_var, on_var, weight: int, *, slot: str) -> None:
    viol = model.NewBoolVar(f"checkin_need_same_day_class[{teacher},{day},{slot}]")
    if on_var is None:
        model.Add(viol == checkin_var)
    else:
        # viol = checkin AND (NOT on)
        model.Add(viol <= checkin_var)
        model.Add(viol + on_var <= 1)
        model.Add(viol >= checkin_var - on_var)
    penalties.append(weight * viol)
    register(
        "night_checkin_need_same_day_class",
        "晚查寝教师需当日有晚自习",
        weight,
        viol,
        teacher=teacher,
        day=day,
        slot=slot,
        constraint_category="preference",
        source_module="scheduler/model/constraints/checkin.py",
        description="晚查寝教师当天没有晚自习课",
    )


def apply_checkin(model, vars, ctx, rules) -> List:
    """查寝约束入口（硬约束 + 可选软惩罚）。"""
    penalties: List = []
    cfg = rules.get("checkin", {})
    if not cfg.get("enabled", False):
        return penalties

    days = ctx["days"]
    male_heads = ctx["male_heads"]
    female_heads = ctx["female_heads"]

    # 变量
    checkin_m = vars.get("checkin_m", {})
    checkin_f = vars.get("checkin_f", {})
    on_teacher_day = vars.get("on_teacher_day", {})

    # 配置
    male_need = int(cfg.get("per_day", {}).get("male", 1))
    female_need = int(cfg.get("per_day", {}).get("female", 1))
    per_teacher_max = int(cfg.get("per_teacher_max_times", 1))
    same_day_class_mode = _same_day_class_mode(cfg)
    require_on_hard = same_day_class_mode == "hard"
    require_on_soft = same_day_class_mode == "soft"
    w_same_day_class = int(cfg.get("w_require_teacher_has_class_that_day", 3000))
    exclude_heads = {str(x).strip() for x in (cfg.get("exclude_heads", []) or []) if str(x).strip()}
    require_class_teachers = teacher_names(
        cfg.get("require_class_teacher_names", cfg.get("zeng_checkin_teacher_name", []))
    )
    require_class_teacher_norms = teacher_norm_set(require_class_teachers)
    zeng_mode = _norm_mode(cfg.get("zeng_checkin_require_class_mode", "hard"), default="hard")
    w_zeng = int(cfg.get("w_zeng_checkin_require_class_that_day", 3000))
    enable_zeng_rule = bool(cfg.get("enable_zeng_checkin_require_class_that_day", True))
    zeng_penalty_mode = _norm_mode(cfg.get("zeng_night_checkin_penalty_mode", "soft"), default="soft")
    w_zeng_night_penalty = int(cfg.get("w_zeng_night_checkin_penalty", 2000))
    night_checkin_penalty_teachers = teacher_names(
        cfg.get("night_checkin_penalty_teachers", cfg.get("zeng_checkin_teacher_name", []))
    )
    extra_head_allowed_days = _extra_head_allowed_days(cfg, days)
    # Hc0：逐日覆盖性约束
    if require_on_hard:
        for d in days:
            # 男班主任当天 on 的人数 >= male_need
            if male_heads:
                model.Add(sum(on_teacher_day.get((tch, d), 0) for tch in male_heads) >= male_need)
            else:
                if male_need > 0:
                    model.Add(0 >= male_need)  # 直接不可行

            # 女班主任当天 on 的人数 >= female_need
            if female_heads:
                model.Add(sum(on_teacher_day.get((tch, d), 0) for tch in female_heads) >= female_need)
            else:
                if female_need > 0:
                    model.Add(0 >= female_need)

    # -----------------------------
    # Hc1：每天必须指派 男1女1（或你配置的数量）
    # -----------------------------
    # Hc1.0：黑名单班主任不参与晚查寝（硬约束）
    if exclude_heads:
        for d in days:
            for tch in male_heads:
                if tch in exclude_heads:
                    model.Add(checkin_m[(tch, d)] == 0)
            for tch in female_heads:
                if tch in exclude_heads:
                    model.Add(checkin_f[(tch, d)] == 0)

    for (tch, gender), allowed_days in extra_head_allowed_days.items():
        if gender == "男":
            for d in days:
                if d not in allowed_days and (tch, d) in checkin_m:
                    model.Add(checkin_m[(tch, d)] == 0)
        elif gender == "女":
            for d in days:
                if d not in allowed_days and (tch, d) in checkin_f:
                    model.Add(checkin_f[(tch, d)] == 0)

    # 指定教师晚查寝惩罚（soft/hard 可切换）
    for target in night_checkin_penalty_teachers:
        for d in days:
            target_vars = []
            vm = checkin_m.get((target, d))
            if vm is not None:
                target_vars.append(vm)
            vf = checkin_f.get((target, d))
            if vf is not None:
                target_vars.append(vf)
            if not target_vars:
                continue
            for idx, v in enumerate(target_vars):
                if zeng_penalty_mode == "hard":
                    model.Add(v == 0)
                else:
                    penalties.append(w_zeng_night_penalty * v)
                    register(
                        "night_checkin_target_penalty",
                        "指定教师晚查寝惩罚",
                        w_zeng_night_penalty,
                        v,
                        teacher=target,
                        day=d,
                        slot=f"晚查寝[{idx}]",
                        constraint_category="preference",
                        source_module="scheduler/model/constraints/checkin.py",
                        description="指定教师被安排晚查寝",
                    )

    for d in days:
        # 男
        if male_heads:
            model.Add(sum(checkin_m[(tch, d)] for tch in male_heads) == male_need)
        else:
            # 没有男班主任池，但又要求男查寝人数>0，直接不可行
            if male_need > 0:
                model.Add(0 == male_need)

        # 女
        if female_heads:
            model.Add(sum(checkin_f[(tch, d)] for tch in female_heads) == female_need)
        else:
            if female_need > 0:
                model.Add(0 == female_need)

    # -----------------------------
    # Hc2：每位班主任一周最多被指派 N 次
    # -----------------------------
    for tch in male_heads:
        model.Add(sum(checkin_m[(tch, d)] for d in days) <= per_teacher_max)

    for tch in female_heads:
        model.Add(sum(checkin_f[(tch, d)] for d in days) <= per_teacher_max)

    # 指定教师周男寝晚查寝上限（硬）
    for target in teacher_names(cfg.get("male_weekly_max1_teachers", [])):
        if target in male_heads:
            model.Add(sum(checkin_m[(target, d)] for d in days) <= 1)

    # -----------------------------
    # Hc3（可选）：被指派查寝的人，当天必须有晚自习课
    # hard=硬约束；soft=允许但计入诊断罚分；off=不检查
    # -----------------------------
    if require_on_hard or require_on_soft:
        for tch in male_heads:
            if enable_zeng_rule and "".join(str(tch).split()) in require_class_teacher_norms:
                continue
            for d in days:
                on = on_teacher_day.get((tch, d))
                if require_on_hard:
                    # checkin_m(t,d)=1 => on_teacher_day(t,d)=1
                    # 等价写法：checkin_m <= on
                    if on is not None:
                        model.Add(checkin_m[(tch, d)] <= on)
                    else:
                        # 如果该班主任不在任课教师集合里（没有 on 变量），那他永远不能被指派
                        model.Add(checkin_m[(tch, d)] == 0)
                else:
                    _add_same_day_class_penalty(
                        model,
                        penalties,
                        tch,
                        d,
                        checkin_m[(tch, d)],
                        on,
                        w_same_day_class,
                        slot="男晚查寝",
                    )

        for tch in female_heads:
            if enable_zeng_rule and "".join(str(tch).split()) in require_class_teacher_norms:
                continue
            for d in days:
                on = on_teacher_day.get((tch, d))
                if require_on_hard:
                    if on is not None:
                        model.Add(checkin_f[(tch, d)] <= on)
                    else:
                        model.Add(checkin_f[(tch, d)] == 0)
                else:
                    _add_same_day_class_penalty(
                        model,
                        penalties,
                        tch,
                        d,
                        checkin_f[(tch, d)],
                        on,
                        w_same_day_class,
                        slot="女晚查寝",
                    )

    # 指定教师：若被安排晚查寝，则当天需有晚自习（soft/hard 可切换）
    if enable_zeng_rule:
        for target in require_class_teachers:
            for d in days:
                target_vars = []
                vm = checkin_m.get((target, d))
                if vm is not None:
                    target_vars.append(vm)
                vf = checkin_f.get((target, d))
                if vf is not None:
                    target_vars.append(vf)
                if not target_vars:
                    continue
                on = on_teacher_day.get((target, d))
                for idx, v in enumerate(target_vars):
                    if zeng_mode == "hard":
                        if on is None:
                            model.Add(v == 0)
                        else:
                            model.Add(v <= on)
                    else:
                        viol = model.NewBoolVar(f"checkin_target_need_on[{target},{d},{idx}]")
                        if on is None:
                            model.Add(viol == v)
                        else:
                            # viol = v AND (NOT on)
                            model.Add(viol <= v)
                            model.Add(viol + on <= 1)
                            model.Add(viol >= v - on)
                        penalties.append(w_zeng * viol)
                        register(
                            "night_checkin_target_need_on",
                            "指定教师晚查寝需当日有晚自习",
                            w_zeng,
                            viol,
                            teacher=target,
                            day=d,
                            constraint_category="preference",
                            source_module="scheduler/model/constraints/checkin.py",
                        )

    return penalties


def _extra_head_allowed_days(cfg: dict, days: list[str]) -> dict[tuple[str, str], set[str]]:
    out: dict[tuple[str, str], set[str]] = {}
    valid_days = {str(day).strip() for day in days}
    for item in cfg.get("extra_heads", []) or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        gender = str(item.get("gender") or "").strip()
        if not name or gender not in {"男", "女"}:
            continue
        scoped_days = _coerce_days(item.get("days", item.get("day", item.get("available_days"))))
        scoped_days = {day for day in scoped_days if day in valid_days}
        if scoped_days:
            out[(name, gender)] = scoped_days
    return out


def _coerce_days(value) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, (list, tuple, set)):
        raw = value
    else:
        raw = str(value).replace("，", ",").replace("、", ",").replace("/", ",").split(",")
    return {str(day).strip() for day in raw if str(day).strip()}
