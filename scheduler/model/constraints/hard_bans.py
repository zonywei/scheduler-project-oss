# 日禁排：学科/教师
# model/constraints/hard_bans.py
"""
这里放“禁排类硬约束”。

禁排分两类：
1) 学科禁排：例如 数学 周五/周日 禁排
2) 教师禁排：例如 指定教师 周一/周五 禁排

注意：这些都是“硬约束”，触犯就直接不可行（INFEASIBLE）。
"""

def apply_hard_bans(model, vars, ctx, rules):
    """
    参数说明（你不用懂CP-SAT，只要知道它们从哪来）：
    - model: OR-Tools 的模型对象，用 model.Add(...) 加约束
    - vars: 变量字典，目前至少有 vars["y"]
    - ctx : 上下文数据（classes / cst / ts / days / periods）
    - rules: config/rules.yaml 读出来的配置字典
    """

    # -----------------------------
    # 0) 读取开关：不启用就直接返回
    # -----------------------------
    cfg = rules.get("hard_bans", {})
    if not cfg.get("enabled", False):
        return

    # -----------------------------
    # 1) 取出最关键的数据结构
    # -----------------------------
    y = vars["y"]                # y[(班,科,天,节)] = 0/1
    cst = ctx["cst"]             # (班,科) -> 教师
    days = ctx["days"]           # ["星期一",...]
    periods = ctx["periods"]     # ["晚自习1","晚自习2"]

    # ============================================================
    # A. 学科禁排（subject_bans）
    # ============================================================
    # 配置长这样：
    # subject_bans:
    #   - subject: "数学"
    #     days: ["星期五","星期日"]
    #     periods: ["晚自习1","晚自习2"]
    #
    # 逻辑：只要是这个学科，在这些天这些节 y 必须为 0
    subject_bans = cfg.get("subject_bans", [])
    for item in subject_bans:
        subj = item.get("subject")
        ban_days = set(item.get("days", []))
        ban_periods = set(item.get("periods", []))

        if not subj:
            continue

        # 如果 periods 没写，就默认禁排全天两节
        if not ban_periods:
            ban_periods = set(periods)

        for (cls, s) in cst.keys():
            if s != subj:
                continue
            for d in ban_days:
                if d not in days:
                    continue
                for p in ban_periods:
                    if p not in periods:
                        continue
                    # “禁排”就是：强制该格子不能排该学科
                    model.Add(y[(cls, subj, d, p)] == 0)

    # ============================================================
    # B. 教师禁排（teacher_day_bans）
    # ============================================================
    # 配置长这样：
    # teacher_day_bans:
    #   星期一: ["指定教师","指定教师"]
    #   星期五: ["指定教师"]
    #
    # 逻辑：如果某个格子对应的教师在当日禁排名单里，则该格子 y 必须为 0
    #
    # 注意：y 是“班-科-天-节”，教师信息要通过 cst[(班,科)] 查出来。
    teacher_day_bans = cfg.get("teacher_day_bans", {}) or {}
    for d, ban_teachers in teacher_day_bans.items():
        if d not in days:
            continue
        ban_set = set(ban_teachers or [])

        # 遍历所有(班,科)，查该科的任课老师是否在禁排名单
        for (cls, subj), tch in cst.items():
            if tch in ban_set:
                for p in periods:
                    # 该老师在这一天任何节次都不能上
                    model.Add(y[(cls, subj, d, p)] == 0)

