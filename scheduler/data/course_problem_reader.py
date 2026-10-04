"""Course inputs defined by the school's slots and cycle-wide demand.

Unlike the legacy adapter, this reader has no morning/evening or weekday/weekend
quotas. Fixed activities consume slots separately from the course demand.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Any, Mapping

from scheduler.data.day_rules_reader import ALL_DAYS, DayInputData, Slot
from scheduler.data.teacher_table_schema import teacher_subject_columns


def _integer(value: Any, label: str, *, minimum: int = 0) -> int:
    try:
        number = float(value)
        integer = int(number)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{label}必须是整数") from exc
    if number != integer or integer < minimum:
        raise ValueError(f"{label}必须是大于等于 {minimum} 的整数")
    return integer


def _slot(row: Mapping[str, Any], *, day: str) -> Slot:
    block = str(row.get("时段") or "").strip()
    if block:
        period = _integer(row.get("节次"), "节次", minimum=1)
    else:
        label = str(row.get("时段节次") or "").strip()
        match = re.fullmatch(r"(.+?)(\d+)", label)
        if not match:
            raise ValueError("时间格请提供时段和节次，或如‘课程1’的时段节次")
        block, period = match.group(1), _integer(match.group(2), "节次", minimum=1)
    return Slot(day=day, block=block, period=period)


def load_course_inputs(web_tables: Mapping[str, Any]) -> DayInputData:
    teachers = web_tables.get("teacher_subjects")
    tables = web_tables.get("day_rules")
    if not isinstance(teachers, list) or not isinstance(tables, Mapping):
        raise ValueError("请先确认保存教师定位和排课数据；课程排课不读取旧学校 Excel")
    relations = {}
    classes = []
    for row in teachers:
        cls = str(row.get("班级") or "").strip()
        if not cls or cls in classes:
            raise ValueError("教师定位的班级必须非空且唯一")
        classes.append(cls)
        for subject in teacher_subject_columns(row.keys()):
            teacher = str(row.get(subject) or "").strip()
            if teacher:
                relations[(cls, subject)] = teacher
    slots = []
    for row in tables.get("time_grid", []):
        if "星期" in row:
            day = str(row.get("星期") or "").strip()
            if day not in ALL_DAYS:
                raise ValueError(f"当前周期日须为星期一至星期日：{day}")
            available = _integer(row.get("可排", 1), "可排")
            if available not in (0, 1):
                raise ValueError("时间格可排值只能为 0 或 1")
            days = [day] if available else []
        else:
            days = []
            for day in ALL_DAYS:
                available = _integer(row.get(day, 0), f"{day}可排")
                if available not in (0, 1):
                    raise ValueError("时间格可排值只能为 0 或 1")
                if available:
                    days.append(day)
        slots.extend(_slot(row, day=day) for day in days)
    if not classes or not relations or not slots or len(set(slots)) != len(slots):
        raise ValueError("班级、任课关系和时间格不能为空，且时间格不能重复")
    defaults = {}
    for row in tables.get("subject_hours", []):
        subject = str(row.get("学科") or "").strip()
        if not subject or subject in defaults or "周期课时" not in row:
            raise ValueError("学科课时须提供唯一学科和周期课时，无须拆分周中、周末或早自习")
        defaults[subject] = _integer(row["周期课时"], f"{subject}周期课时")
    demand = {}
    for cls, subject in relations:
        if subject not in defaults:
            raise ValueError(f"{cls}/{subject}缺少周期课时")
        demand[(cls, subject)] = defaults[subject]
    for row in tables.get("class_overrides", []):
        key = (str(row.get("班级") or "").strip(), str(row.get("学科") or "").strip())
        if key not in relations:
            raise ValueError(f"班级课时差异引用未知任课关系：{key}")
        demand[key] = _integer(row.get("周期课时"), f"{key}周期课时")
    fixed = {}
    for row in tables.get("fixed_slots", []):
        slot = _slot(row, day=str(row.get("星期") or "").strip())
        subject = str(row.get("学科") or "").strip()
        targets = classes if str(row.get("作用范围") or "").upper() == "ALL" else [str(row.get("班级") or "").strip()]
        if slot not in slots or not subject:
            raise ValueError("固定安排必须引用可排时间格并填写活动或学科")
        for cls in targets:
            if cls not in classes or (cls, slot) in fixed:
                raise ValueError("固定安排引用未知班级或重复课位")
            fixed[(cls, slot)] = subject
    bans: dict[str, set[Slot]] = {}
    for row in tables.get("subject_bans", []):
        subject = str(row.get("学科") or "").strip()
        day = str(row.get("禁排星期") or row.get("星期") or "").strip()
        block = str(row.get("禁排时段") or row.get("时段") or "").strip()
        period = row.get("节次")
        if subject not in defaults or day not in ALL_DAYS or not block:
            raise ValueError("学科禁排须引用已定义学科、周期日和时段")
        target_period = None if str(period).upper() == "ALL" else _integer(period, "禁排节次", minimum=1)
        hits = {s for s in slots if s.day == day and s.block == block and (target_period is None or s.period == target_period)}
        if not hits:
            raise ValueError("学科禁排没有匹配到任何可排时间格")
        bans.setdefault(subject, set()).update(hits)
    fixed_counts = Counter(cls for (cls, _), subject in fixed.items() if (cls, subject) not in relations)
    for cls in classes:
        required = sum(value for (c, _), value in demand.items() if c == cls)
        capacity = len(slots) - fixed_counts[cls]
        if required > capacity:
            raise ValueError(f"{cls}周期课时 {required} 超过课程课位 {capacity}；请调整课时或可排时间")
    # The legacy tuple is populated only for interface compatibility. The course
    # compiler uses total demand and never applies its E/W/WE classification.
    return DayInputData(classes, relations, slots, fixed, {key: (0, value, 0) for key, value in demand.items()}, bans)
