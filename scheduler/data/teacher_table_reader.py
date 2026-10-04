# 读取教师定位表 → 生成 cst/ts/classes/head pools
from __future__ import annotations

from pathlib import Path

from scheduler.data.teacher_table_schema import (
    configured_teacher_table_columns,
    head_gender_pools,
    load_teacher_table_frame,
    teacher_subject_columns,
)


def read_teacher_table(io_cfg: dict, rules: dict):
    """读取用户实际提供的宽表。

    ``evening.subjects`` 为空时，晚自习学科完全来自上传表格的非结构列；
    非空时表示教务人员主动配置的晚自习白名单，只取其中实际存在的列，
    不再因为白名单里有一个缺失列而拒绝整张表。
    """
    base_dir = Path(__file__).resolve().parents[1]
    class_col, head_col, gender_col = configured_teacher_table_columns(io_cfg)
    df = load_teacher_table_frame(io_cfg, base_dir)
    if df.empty:
        raise ValueError("教师定位表没有可用数据")
    if class_col not in df.columns:
        raise ValueError(f"教师定位表缺少必需列：{class_col}")

    actual_subjects = teacher_subject_columns(
        df.columns,
        class_col=class_col,
        head_col=head_col,
        gender_col=gender_col,
    )
    if not actual_subjects:
        raise ValueError("教师定位表至少需要一列学科/任课教师列")

    configured_subjects = _as_subject_list((rules.get("evening", {}) or {}).get("subjects"))
    if configured_subjects:
        evening_subjects = [subject for subject in configured_subjects if subject in actual_subjects]
    else:
        evening_subjects = actual_subjects

    # 班级
    classes = []
    for value in df[class_col].tolist():
        text = _cell_text(value)
        if text:
            classes.append(text)
    classes = list(dict.fromkeys(classes))

    # 班主任/性别只是值班与查寝附加数据；课程排课不依赖它们。
    male_heads, female_heads = head_gender_pools(
        df,
        head_col=head_col,
        gender_col=gender_col,
        strict_gender=True,
    )
    extra_heads = (rules.get("checkin", {}) or {}).get("extra_heads", []) or []
    for item in extra_heads:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        gender = str(item.get("gender", "")).strip()
        if not name:
            continue
        if gender == "男":
            male_heads.append(name)
        elif gender == "女":
            female_heads.append(name)
        else:
            raise ValueError(f"extra_heads 性别必须为 男/女：{item}")

    # (班,科)->师映射：空白=不开设/不参与。
    recs = []
    per_class_cnt = {}
    for _, row in df.iterrows():
        cls = _cell_text(row.get(class_col, ""))
        if not cls:
            continue
        cnt = 0
        for subject in evening_subjects:
            teacher = _cell_text(row.get(subject, ""))
            if not teacher:
                continue
            recs.append((cls, subject, teacher))
            cnt += 1
        per_class_cnt[cls] = cnt

    max_subj = int((rules.get("evening", {}) or {}).get("max_subjects_per_class", 6))
    too_many = {cls: count for cls, count in per_class_cnt.items() if count > max_subj}
    if too_many:
        raise ValueError(f"以下班级晚自习科目数 > {max_subj}：{too_many}")

    cst = {(cls, subject): teacher for (cls, subject, teacher) in recs}

    ts = {}
    for cls, subject, teacher in recs:
        ts.setdefault((teacher, subject), set()).add(cls)
    ts = {(teacher, subject): sorted(classes) for (teacher, subject), classes in ts.items()}

    return classes, cst, ts, sorted(set(male_heads)), sorted(set(female_heads))


def checkin_candidate_pool_available(checkin_cfg: dict, male_heads: list[str], female_heads: list[str]) -> bool:
    """判断当前性别候选池是否足以启用查寝附加模块。"""
    if not isinstance(checkin_cfg, dict):
        return False
    per_day = checkin_cfg.get("per_day", {})
    per_day = per_day if isinstance(per_day, dict) else {}
    male_need = _as_nonnegative_int(per_day.get("male"), 1)
    female_need = _as_nonnegative_int(per_day.get("female"), 1)
    return (male_need == 0 or bool(male_heads)) and (female_need == 0 or bool(female_heads))


def _as_subject_list(value) -> list[str]:
    if not isinstance(value, (list, tuple, set)):
        return []
    return list(dict.fromkeys(str(item).strip() for item in value if str(item).strip()))


def _as_nonnegative_int(value, default: int) -> int:
    try:
        return max(0, int(float(str(value).strip())))
    except (TypeError, ValueError):
        return max(0, int(default))


def _cell_text(value) -> str:
    if value is None:
        return ""
    try:
        import pandas as pd

        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()
