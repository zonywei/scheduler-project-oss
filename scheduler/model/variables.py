# model/variables.py
from ortools.sat.python import cp_model

def build_variables(model: cp_model.CpModel, classes, cst, days, periods):
    """
    变量工厂：所有 CP-SAT 变量只能在这里创建，避免散落各处难维护。

    返回 vars 字典：
    - y[(班,科,天,节)]：是否排该学科在该格子
    - on_teacher_day[(教师,天)]：该教师这一天是否上了任意晚自习（至少一节）
    - checkin_m[(教师,天)]：男班主任该天是否被指派查寝
    - checkin_f[(教师,天)]：女班主任该天是否被指派查寝
    """

    # -----------------------------
    # 1) 核心排课变量 y
    # -----------------------------
    y = {}
    for (cls, subj) in cst.keys():
        for d in days:
            for p in periods:
                y[(cls, subj, d, p)] = model.NewBoolVar(f"y__{cls}__{subj}__{d}__{p}")

    # -----------------------------
    # 2) 派生变量：教师是否在某天上过晚自习（至少一节）
    #    这是为了查寝模块可选约束：“查寝的人当天必须上晚自习”
    # -----------------------------
    # 先收集所有教师名单（来自 cst 的值）
    all_teachers = sorted(set(cst.values()))

    # 创建 on_teacher_day 布尔变量
    on_teacher_day = {}
    for tch in all_teachers:
        for d in days:
            on_teacher_day[(tch, d)] = model.NewBoolVar(f"on__{tch}__{d}")

    # 让 on_teacher_day 与 y 关联起来：
    # on(t,d) = OR( 该教师在这天任意班任意科任意节的 y )
    # OR-Tools 没有直接 OR 等式，我们用 “>=” 和 “<=” 的方式绑定：
    #
    # 令 L 是该教师在该天所有相关 y 的列表
    # - on >= 每个 y （只要有一个 y=1，则 on 必须=1）
    # - on <= sum(L) （如果所有 y=0，则 sum=0，on 只能=0）
    #
    # 当 L 为空（该教师根本不教任何晚自习科目）时：
    # - 我们强制 on=0
    teacher_day_ylist = {(tch, d): [] for tch in all_teachers for d in days}

    for (cls, subj), tch in cst.items():
        for d in days:
            for p in periods:
                teacher_day_ylist[(tch, d)].append(y[(cls, subj, d, p)])

    for tch in all_teachers:
        for d in days:
            L = teacher_day_ylist[(tch, d)]
            if not L:
                model.Add(on_teacher_day[(tch, d)] == 0)
            else:
                # on >= y_i
                for v in L:
                    model.Add(on_teacher_day[(tch, d)] >= v)
                # on <= sum(L)
                model.Add(on_teacher_day[(tch, d)] <= sum(L))

    # 注意：查寝变量不在这里创建，因为要用到 male_heads/female_heads，
    # 而它们目前是在 ctx 里，不在 build_variables 参数里。
    # 为了保持“变量只能在 variables.py 创建”的原则，我们给一个函数专门创建查寝变量。
    return {"y": y, "on_teacher_day": on_teacher_day, "all_teachers": all_teachers}

def build_checkin_variables(model: cp_model.CpModel, male_heads, female_heads, days):
    """
    专门创建查寝变量（因为它依赖班主任池）。
    """
    checkin_m = {}
    for tch in male_heads:
        for d in days:
            checkin_m[(tch, d)] = model.NewBoolVar(f"checkin_m__{tch}__{d}")

    checkin_f = {}
    for tch in female_heads:
        for d in days:
            checkin_f[(tch, d)] = model.NewBoolVar(f"checkin_f__{tch}__{d}")

    return {"checkin_m": checkin_m, "checkin_f": checkin_f}
