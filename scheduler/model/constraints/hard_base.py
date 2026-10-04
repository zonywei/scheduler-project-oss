# model/constraints/hard_base.py
"""
这里放“基础结构类硬约束”。

基础结构 = 不满足就根本不是一个合法的晚自习课表。
"""

def apply_hard_base(model, vars, ctx, rules):
    """
    这个函数只做“最基础”的硬约束：
    H1：每班每天每节必须恰好一个学科（不许空、不许一节两科）
    H2：每个(班,科)一周恰好出现 K 次（默认 2 次）
    H3：同一班同一天同科最多 1 次（避免两节都上同一科）
    """

    # 取出核心变量与数据
    y = vars["y"]                # y[(班,科,天,节)] = 0/1
    classes = ctx["classes"]     # 班级列表
    cst = ctx["cst"]             # (班,科)->教师
    days = ctx["days"]           # ["星期一",...]
    periods = ctx["periods"]     # ["晚自习1","晚自习2"]

    # 规则参数：每科每周出现次数（你现在默认 2）
    weekly_k = int(rules["evening"].get("weekly_occurrences_per_subject", 2))

    # -----------------------------
    # H1：每班每天每节必须恰好一个学科
    # -----------------------------
    for cls in classes:
        # 这个班参与晚自习的学科集合（来自定位表，空白不算）
        subj_list = [s for (c, s) in cst.keys() if c == cls]

        # 对每一天、每一节：必须从 subj_list 里选 1 个学科
        for d in days:
            for p in periods:
                model.Add(sum(y[(cls, subj, d, p)] for subj in subj_list) == 1)

    # -----------------------------
    # H2：每个(班,科)一周恰好出现 K 次
    # -----------------------------
    for (cls, subj) in cst.keys():
        model.Add(sum(y[(cls, subj, d, p)] for d in days for p in periods) == weekly_k)

    # -----------------------------
    # H3：同一班同一天同科最多 1 次
    # -----------------------------
    # 解释：避免某班在同一天的晚自习1/2 都排同一门学科
    # 注意：这一条对所有(班,科)都适用（除非以后你做“例外教师”如指定教师）
    for (cls, subj) in cst.keys():
        for d in days:
            model.Add(sum(y[(cls, subj, d, p)] for p in periods) <= 1)

