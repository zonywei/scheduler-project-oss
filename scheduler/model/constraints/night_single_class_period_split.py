# -*- coding: utf-8 -*-
"""晚自习节次拆分约束（单班教师 + 双班教师）。"""

from __future__ import annotations

import csv
from pathlib import Path

from ortools.sat.python import cp_model

WEEKDAY_NAMES = {"星期一", "星期二", "星期三", "星期四", "星期五"}
SPLIT_EXTRA_DAYS = {"星期日"}


def _build_teacher_classes(cst: dict) -> dict[str, set[str]]:
    """从 (班级,学科)->教师 映射构建 teacher -> classes。"""
    teacher_classes: dict[str, set[str]] = {}
    for (cls, _subj), tch in cst.items():
        teacher_classes.setdefault(tch, set()).add(cls)
    return teacher_classes


def apply_single_class_teacher_p1_p2_split(
    model: cp_model.CpModel,
    vars: dict,
    ctx: dict,
    rules: dict,
) -> None:
    """单班教师：每个班级学科的一周两次晚自习必须拆到晚自习1/2 各一次。"""
    cfg = rules.get("evening_constraints", {}) or {}
    if cfg.get("enable_single_class_p1_p2_split", True) is False:
        return

    periods = ctx["periods"]
    days = ctx["days"]
    cst = ctx["cst"]
    y = vars["y"]

    weekly_k = int(rules.get("evening", {}).get("weekly_occurrences_per_subject", 2))
    if weekly_k != 2 or len(periods) != 2:
        return

    p1, p2 = periods[0], periods[1]
    teacher_classes = _build_teacher_classes(cst)

    for (cls, subj), tch in cst.items():
        if len(teacher_classes.get(tch, set())) != 1:
            continue
        model.Add(sum(y[(cls, subj, d, p1)] for d in days) == 1)
        model.Add(sum(y[(cls, subj, d, p2)] for d in days) == 1)


def apply_double_class_teacher_weekday_alternate_p1_p2(
    model: cp_model.CpModel,
    vars: dict,
    ctx: dict,
    rules: dict,
) -> None:
    """双班教师：规则日(工作日+周日)两次晚自习时，强制一节在晚自习1、一节在晚自习2（hard 模式）。"""
    cfg = rules.get("evening_constraints", {}) or {}
    if cfg.get("enable_double_class_weekday_p1_p2_split", True) is False:
        return
    if cfg.get("double_class_weekday_p1_p2_mode", "hard") != "hard":
        return

    periods = ctx["periods"]
    days = ctx["days"]
    cst = ctx["cst"]
    y = vars["y"]

    weekly_k = int(rules.get("evening", {}).get("weekly_occurrences_per_subject", 2))
    if weekly_k != 2 or len(periods) != 2:
        return

    split_days = [d for d in days if d in WEEKDAY_NAMES or d in SPLIT_EXTRA_DAYS]
    if not split_days:
        return

    p1, p2 = periods[0], periods[1]
    teacher_classes = _build_teacher_classes(cst)

    for (cls, subj), tch in cst.items():
        if len(teacher_classes.get(tch, set())) != 2:
            continue

        split_total = sum(y[(cls, subj, d, p)] for d in split_days for p in periods)
        split_two = model.NewBoolVar(f"split_two[{cls},{subj}]")
        model.Add(split_total == 2).OnlyEnforceIf(split_two)
        model.Add(split_total != 2).OnlyEnforceIf(split_two.Not())

        split_p1 = sum(y[(cls, subj, d, p1)] for d in split_days)
        split_p2 = sum(y[(cls, subj, d, p2)] for d in split_days)
        model.Add(split_p1 == 1).OnlyEnforceIf(split_two)
        model.Add(split_p2 == 1).OnlyEnforceIf(split_two)


def build_double_class_weekday_p1_p2_rows(
    val,
    vars: dict,
    ctx: dict,
    rules: dict,
) -> list[dict]:
    """构建“双班教师工作日晚自习1/2拆分”诊断行。"""
    periods = ctx.get("periods", [])
    days = ctx.get("days", [])
    cst = ctx.get("cst", {})
    y = vars.get("y", {})
    if len(periods) != 2 or not cst or not y:
        return []

    split_days = [d for d in days if d in WEEKDAY_NAMES or d in SPLIT_EXTRA_DAYS]
    if not split_days:
        return []

    cfg = rules.get("evening_constraints", {}) or {}
    enabled = bool(cfg.get("enable_double_class_weekday_p1_p2_split", True))
    mode = str(cfg.get("double_class_weekday_p1_p2_mode", "hard")).lower()
    teacher_classes = _build_teacher_classes(cst)
    p1, p2 = periods[0], periods[1]

    rows: list[dict] = []
    for (cls, subj), tch in sorted(cst.items()):
        if len(teacher_classes.get(tch, set())) != 2:
            continue
        split_p1 = sum(int(val.Value(y[(cls, subj, d, p1)])) for d in split_days)
        split_p2 = sum(int(val.Value(y[(cls, subj, d, p2)])) for d in split_days)
        split_total = split_p1 + split_p2
        triggered = int(split_total == 2)
        violation = int(triggered == 1 and (split_p1 == 2 or split_p2 == 2))
        rows.append(
            {
                "教师": tch,
                "班级": cls,
                "学科": subj,
                "规则日晚自习总次数(工作日+周日)": split_total,
                f"{p1}次数(规则日)": split_p1,
                f"{p2}次数(规则日)": split_p2,
                "触发条件(规则日=2次)": triggered,
                "是否同节重复(违规)": violation,
                "规则开关": int(enabled),
                "规则模式": mode,
            }
        )
    return rows


def write_double_class_weekday_p1_p2_report(
    out_dir: Path,
    val,
    vars: dict,
    ctx: dict,
    rules: dict,
) -> Path:
    """导出双班教师工作日晚自习1/2拆分明细 CSV。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "night_double_class_weekday_p1_p2_report.csv"
    rows = build_double_class_weekday_p1_p2_rows(val, vars, ctx, rules)
    columns = [
        "教师",
        "班级",
        "学科",
        "规则日晚自习总次数(工作日+周日)",
        f"{ctx.get('periods', ['晚自习1', '晚自习2'])[0]}次数(规则日)",
        f"{ctx.get('periods', ['晚自习1', '晚自习2'])[1]}次数(规则日)",
        "触发条件(规则日=2次)",
        "是否同节重复(违规)",
        "规则开关",
        "规则模式",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return path
