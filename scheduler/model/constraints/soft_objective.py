# model/constraints/soft_objective.py
"""晚自习软约束目标函数。"""

from __future__ import annotations

from ortools.sat.python import cp_model

from scheduler.diagnostics.penalty_registry import register
from scheduler.model.constraints.night_special import (
    build_physics_math_soft_penalties,
    build_subject_sync_penalty_terms,
)
from scheduler.model.constraints.teacher_targets import teacher_names

WEEKDAY_NAMES = {"星期一", "星期二", "星期三", "星期四", "星期五"}
SPLIT_EXTRA_DAYS = {"星期日"}


def _and2(model: cp_model.CpModel, a, b, name: str):
    """z = a AND b 线性化。"""
    z = model.NewBoolVar(name)
    model.Add(z <= a)
    model.Add(z <= b)
    model.Add(z >= a + b - 1)
    return z


def _find_teacher_key(all_teachers: list[str], target_name: str) -> str | None:
    """按归一化姓名在 all_teachers 中查找真实键名。"""
    target = "".join(str(target_name).split())
    for tch in all_teachers:
        if "".join(str(tch).split()) == target:
            return tch
    return None


def apply_soft_objective(
    model: cp_model.CpModel,
    vars: dict,
    ctx: dict,
    rules: dict,
    set_objective: bool = True,
):
    """构建晚自习软约束目标项；set_objective=False 时仅返回项列表。"""
    soft_cfg = rules.get("soft", {}) or {}
    if soft_cfg.get("enabled", True) is False:
        return []

    w_cfg = soft_cfg.get("weights", {}) or {}
    W_MISS_HEAD_ON = int(w_cfg.get("miss_head_on", 50))
    W_ADJ_TEACHER = int(w_cfg.get("adjacent_teacher", 5))
    W_FRI_SUN = int(w_cfg.get("fri_sun_teacher", 10))
    W_CHECKIN_REPEAT = int(w_cfg.get("checkin_repeat", 20))
    W_SUN_MON = int(w_cfg.get("sun_mon_teacher", 4))
    adj_exempt_raw = soft_cfg.get("adjacent_teacher_exempt_teachers", []) or []
    adj_exempt = {"".join(str(x).split()) for x in adj_exempt_raw if str(x).strip()}

    days = ctx["days"]
    periods = ctx["periods"]
    cst = ctx["cst"]
    male_heads = ctx["male_heads"]
    female_heads = ctx["female_heads"]

    on = vars.get("on_teacher_day", {})
    y = vars.get("y", {})
    all_teachers = vars.get("all_teachers", [])
    checkin_m = vars.get("checkin_m", {})
    checkin_f = vars.get("checkin_f", {})

    # variable -> (teacher, class, subject, day, period) for event_log teacher tracing
    night_var_meta = {}
    for (cls, subj, d, p), term in y.items():
        night_var_meta[term] = (cst.get((cls, subj)), cls, subj, d, str(p))

    penalties = []

    def _is_adj_exempt(teacher: str) -> bool:
        return "".join(str(teacher).split()) in adj_exempt

    # S2: 每天至少有男/女班主任在岗（缺口惩罚）
    for d in days:
        miss_m = model.NewBoolVar(f"miss_male_head_on__{d}")
        male_on_sum = sum(on.get((tch, d), 0) for tch in male_heads)
        big_m = max(1, len(male_heads))
        model.Add(male_on_sum >= 1 - big_m * miss_m)
        model.Add(male_on_sum <= big_m * (1 - miss_m))
        penalties.append(W_MISS_HEAD_ON * miss_m)
        register("night_miss_head_on_male", "晚自习男班主任在岗缺口", W_MISS_HEAD_ON, miss_m, day=d)

        miss_f = model.NewBoolVar(f"miss_female_head_on__{d}")
        female_on_sum = sum(on.get((tch, d), 0) for tch in female_heads)
        big_f = max(1, len(female_heads))
        model.Add(female_on_sum >= 1 - big_f * miss_f)
        model.Add(female_on_sum <= big_f * (1 - miss_f))
        penalties.append(W_MISS_HEAD_ON * miss_f)
        register("night_miss_head_on_female", "晚自习女班主任在岗缺口", W_MISS_HEAD_ON, miss_f, day=d)

    # S3: 相邻天连续晚自习惩罚
    for i in range(len(days) - 1):
        d1 = days[i]
        d2 = days[i + 1]
        for tch in all_teachers:
            if _is_adj_exempt(tch):
                continue
            if (tch, d1) not in on or (tch, d2) not in on:
                continue
            adj = _and2(model, on[(tch, d1)], on[(tch, d2)], f"adj_on__{tch}__{d1}__{d2}")
            penalties.append(W_ADJ_TEACHER * adj)
            register("night_adjacent_days", "晚自习教师相邻天连续上课", W_ADJ_TEACHER, adj, teacher=tch, day=f"{d1}->{d2}")

    # S3.1: 周日+周一连续
    if ("星期日" in days) and ("星期一" in days):
        for tch in all_teachers:
            if _is_adj_exempt(tch):
                continue
            if (tch, "星期日") in on and (tch, "星期一") in on:
                z = _and2(model, on[(tch, "星期日")], on[(tch, "星期一")], f"sun_mon__{tch}")
                penalties.append(W_SUN_MON * z)
                register("night_sun_mon", "晚自习周日周一连续", W_SUN_MON, z, teacher=tch, day="星期日->星期一")

    # S4: 周五+周日晚自习互斥（soft 模式）
    eve_cfg = rules.get("evening_constraints", {}) or {}
    fri_sun_enabled = eve_cfg.get("enable_fri_sun_mutex", False)
    fri_sun_mode = eve_cfg.get("fri_sun_mutex_mode", "soft")
    fri_sun_weight = int(eve_cfg.get("fri_sun_mutex_weight", W_FRI_SUN))
    fri_sun_exempt = {
        "".join(str(t).split())
        for t in (eve_cfg.get("fri_sun_mutex_exempt_teachers", []) or [])
        if str(t).strip()
    }
    if fri_sun_enabled and fri_sun_mode == "soft" and ("星期五" in days) and ("星期日" in days):
        for tch in all_teachers:
            if "".join(str(tch).split()) in fri_sun_exempt:
                continue
            if (tch, "星期五") in on and (tch, "星期日") in on:
                z = _and2(model, on[(tch, "星期五")], on[(tch, "星期日")], f"fri_sun__{tch}")
                penalties.append(fri_sun_weight * z)
                register("night_fri_sun_mutex_soft", "晚自习周五周日互斥软约束", fri_sun_weight, z, teacher=tch, day="星期五+星期日")

    # S4.1: 配置教师对周五晚自习互斥（soft 模式）
    yk_xxc_enabled = eve_cfg.get("enable_yk_xxc_fri_mutex", True)
    yk_xxc_mode = str(eve_cfg.get("yk_xxc_fri_mutex_mode", "hard")).lower()
    yk_xxc_weight = int(eve_cfg.get("yk_xxc_fri_mutex_weight", 2000))
    if yk_xxc_enabled and yk_xxc_mode == "soft" and ("星期五" in days):
        pair = teacher_names(eve_cfg.get("yk_xxc_fri_mutex_teachers", []))
        left = _find_teacher_key(all_teachers, pair[0]) if len(pair) >= 1 else None
        right = _find_teacher_key(all_teachers, pair[1]) if len(pair) >= 2 else None
        if left and right and (left, "星期五") in on and (right, "星期五") in on:
            z = _and2(model, on[(left, "星期五")], on[(right, "星期五")], f"fri_mutex__{left}__{right}")
            penalties.append(yk_xxc_weight * z)
            register(
                "night_yk_xxc_fri_mutex_soft",
                "指定教师对周五晚自习不可同时安排（软）",
                yk_xxc_weight,
                z,
                teacher=f"{left},{right}",
                day="星期五",
                weight_key="evening_constraints.yk_xxc_fri_mutex_weight",
            )

    # S5: 查寝重复惩罚
    if checkin_m and checkin_f:
        for tch in male_heads:
            cnt = sum(checkin_m[(tch, d)] for d in days)
            repeat = model.NewBoolVar(f"checkin_repeat_m__{tch}")
            model.Add(cnt >= 2).OnlyEnforceIf(repeat)
            model.Add(cnt <= 1).OnlyEnforceIf(repeat.Not())
            penalties.append(W_CHECKIN_REPEAT * repeat)
            register("night_checkin_repeat_male", "晚自习男晚查寝重复", W_CHECKIN_REPEAT, repeat, teacher=tch)
        for tch in female_heads:
            cnt = sum(checkin_f[(tch, d)] for d in days)
            repeat = model.NewBoolVar(f"checkin_repeat_f__{tch}")
            model.Add(cnt >= 2).OnlyEnforceIf(repeat)
            model.Add(cnt <= 1).OnlyEnforceIf(repeat.Not())
            penalties.append(W_CHECKIN_REPEAT * repeat)
            register("night_checkin_repeat_female", "晚自习女晚查寝重复", W_CHECKIN_REPEAT, repeat, teacher=tch)

    # S6: 双班教师规则日(工作日+周日)两次晚自习拆分（soft 模式）
    split_enabled = eve_cfg.get("enable_double_class_weekday_p1_p2_split", True)
    split_mode = eve_cfg.get("double_class_weekday_p1_p2_mode", "hard")
    W_DOUBLE_CLASS_WEEKDAY_SPLIT = int(eve_cfg.get("double_class_weekday_p1_p2_weight", 20000))
    split_days = [d for d in days if d in WEEKDAY_NAMES or d in SPLIT_EXTRA_DAYS]
    if split_enabled and split_mode == "soft" and len(periods) == 2 and split_days:
        p1, p2 = periods[0], periods[1]
        teacher_classes = {}
        for (cls, _subj), tch in cst.items():
            teacher_classes.setdefault(tch, set()).add(cls)

        for (cls, subj), tch in cst.items():
            if len(teacher_classes.get(tch, set())) != 2:
                continue
            split_total = model.NewIntVar(0, 2 * len(split_days), f"dbl_split_total__{cls}__{subj}")
            model.Add(split_total == sum(vars["y"][(cls, subj, d, p)] for d in split_days for p in periods))
            split_two = model.NewBoolVar(f"dbl_split_two__{cls}__{subj}")
            model.Add(split_total == 2).OnlyEnforceIf(split_two)
            model.Add(split_total != 2).OnlyEnforceIf(split_two.Not())

            p1_cnt = model.NewIntVar(0, len(split_days), f"dbl_split_p1__{cls}__{subj}")
            p2_cnt = model.NewIntVar(0, len(split_days), f"dbl_split_p2__{cls}__{subj}")
            model.Add(p1_cnt == sum(vars["y"][(cls, subj, d, p1)] for d in split_days))
            model.Add(p2_cnt == sum(vars["y"][(cls, subj, d, p2)] for d in split_days))

            bad_p1 = model.NewBoolVar(f"dbl_wd_badp1__{cls}__{subj}")
            bad_p2 = model.NewBoolVar(f"dbl_wd_badp2__{cls}__{subj}")
            model.Add(p1_cnt == 2).OnlyEnforceIf(bad_p1)
            model.Add(p1_cnt != 2).OnlyEnforceIf(bad_p1.Not())
            model.Add(p2_cnt == 2).OnlyEnforceIf(bad_p2)
            model.Add(p2_cnt != 2).OnlyEnforceIf(bad_p2.Not())
            model.Add(bad_p1 <= split_two)
            model.Add(bad_p2 <= split_two)

            penalties.append(W_DOUBLE_CLASS_WEEKDAY_SPLIT * bad_p1)
            penalties.append(W_DOUBLE_CLASS_WEEKDAY_SPLIT * bad_p2)
            register(
                "night_double_class_weekday_p1_p2_soft",
                "双班教师规则日(工作日+周日)两次晚自习未拆分到1/2节",
                W_DOUBLE_CLASS_WEEKDAY_SPLIT,
                bad_p1,
                teacher=tch,
                cls=cls,
                subj=subj,
            )
            register(
                "night_double_class_weekday_p1_p2_soft",
                "双班教师规则日(工作日+周日)两次晚自习未拆分到1/2节",
                W_DOUBLE_CLASS_WEEKDAY_SPLIT,
                bad_p2,
                teacher=tch,
                cls=cls,
                subj=subj,
            )

    # S7: 同学科同时上晚自习
    w_extra_cfg = eve_cfg.get("weights", {}) or {}
    W_SUBJ_SYNC = int(w_extra_cfg.get("subject_sync", 20))
    subj_sync_terms = build_subject_sync_penalty_terms(model, vars, ctx, rules)
    for t, subj, day, period in subj_sync_terms:
        penalties.append(W_SUBJ_SYNC * t)
        register("night_subject_sync", "同学科教师晚自习同节集中", W_SUBJ_SYNC, t, day=day, slot=period, subj=subj)

    # S8: 物理/历史/配置数学教师周五惩罚
    W_PHY_FRI = int(w_extra_cfg.get("physics_fri_penalty", 120))
    W_HIS_FRI = int(w_extra_cfg.get("history_fri_penalty", 120))
    W_MATH_ZENG_FRI_P1 = int(w_extra_cfg.get("math_zeng_fri_p1_penalty", w_extra_cfg.get("math_zeng_fri_penalty", 500)))
    W_MATH_ZENG_FRI_P2 = int(w_extra_cfg.get("math_zeng_fri_p2_penalty", w_extra_cfg.get("math_zeng_fri_penalty", 500)))
    phy_math_terms = build_physics_math_soft_penalties(model, vars, ctx, rules)
    for term, kind in phy_math_terms:
        teacher, cls, subj, day, period = night_var_meta.get(term, (None, None, None, None, None))
        if kind == "physics_fri":
            penalties.append(W_PHY_FRI * term)
            register(
                "night_physics_fri",
                "物理周五晚自习惩罚",
                W_PHY_FRI,
                term,
                teacher=teacher,
                cls=cls,
                subj=subj or "物理",
                day=day or "星期五",
                slot=period,
            )
        elif kind == "history_fri":
            penalties.append(W_HIS_FRI * term)
            register(
                "night_history_fri",
                "历史周五晚自习惩罚",
                W_HIS_FRI,
                term,
                teacher=teacher,
                cls=cls,
                subj=subj or "历史",
                day=day or "星期五",
                slot=period,
            )
        elif kind == "math_zeng_fri_p1":
            penalties.append(W_MATH_ZENG_FRI_P1 * term)
            register(
                "night_math_zeng_fri_p1",
                "指定数学教师周五晚自习1惩罚",
                W_MATH_ZENG_FRI_P1,
                term,
                teacher=teacher,
                cls=cls,
                subj=subj or "数学",
                day=day or "星期五",
                slot=period or "晚自习1",
            )
        elif kind == "math_zeng_fri_p2":
            penalties.append(W_MATH_ZENG_FRI_P2 * term)
            register(
                "night_math_zeng_fri_p2",
                "指定数学教师周五晚自习2惩罚",
                W_MATH_ZENG_FRI_P2,
                term,
                teacher=teacher,
                cls=cls,
                subj=subj or "数学",
                day=day or "星期五",
                slot=period or "晚自习2",
            )

    if set_objective:
        model.Minimize(sum(penalties))
    return penalties
