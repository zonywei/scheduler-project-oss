# -*- coding: utf-8 -*-
"""Canonical scheduling problem contracts.

``SchoolProblem`` is the target shape for future Excel/OA adapters. It is a
side-effect-free domain object and does not replace the existing solver inputs
yet.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from scheduler.domain.rule_instance import CompiledRuleInstance
from scheduler.domain.school_profile import SchoolProfile, validate_school_profile


@dataclass(frozen=True)
class ProblemSlot:
    day: str
    block: str
    period: int

    @property
    def label(self) -> str:
        if self.block == "早自习":
            return f"早自习{self.period}" if self.period != 1 else "早自习"
        return f"{self.block}{self.period}"


@dataclass(frozen=True)
class ClassSubjectTeacher:
    class_name: str
    subject: str
    teacher: str


@dataclass(frozen=True)
class FixedClassSlot:
    class_name: str
    slot: ProblemSlot
    subject: str


@dataclass(frozen=True)
class SubjectRequirement:
    class_name: str
    subject: str
    early: int = 0
    weekday: int = 0
    weekend: int = 0


@dataclass(frozen=True)
class SubjectBan:
    subject: str
    slots: tuple[ProblemSlot, ...]


@dataclass(frozen=True)
class SchoolProblem:
    profile: SchoolProfile
    classes: tuple[str, ...]
    subjects: tuple[str, ...]
    teachers: tuple[str, ...]
    class_subject_teachers: tuple[ClassSubjectTeacher, ...]
    available_slots: tuple[ProblemSlot, ...] = ()
    fixed_assignments: tuple[FixedClassSlot, ...] = ()
    subject_requirements: tuple[SubjectRequirement, ...] = ()
    subject_bans: tuple[SubjectBan, ...] = ()
    academic_tables: Mapping[str, tuple[Mapping[str, Any], ...]] = field(default_factory=dict)
    rule_instances: tuple[CompiledRuleInstance, ...] = ()
    source: str = "in_memory"


def school_problem_from_day_inputs(
    profile: SchoolProfile,
    day_inputs: Any,
    *,
    academic_payload: Mapping[str, Any] | None = None,
    rule_instances: Sequence[CompiledRuleInstance] = (),
    source: str = "day_inputs",
) -> SchoolProblem:
    cst_rows = tuple(
        ClassSubjectTeacher(class_name=str(cls), subject=str(subj), teacher=str(teacher))
        for (cls, subj), teacher in sorted((day_inputs.cls_subj_teacher or {}).items())
    )
    classes = tuple(str(item) for item in (day_inputs.classes or ()))
    subjects = _sorted_unique(row.subject for row in cst_rows)
    teachers = _sorted_unique(row.teacher for row in cst_rows)
    slots = tuple(_slot_from_any(slot) for slot in (day_inputs.available_slots or ()))
    fixed = tuple(
        FixedClassSlot(class_name=str(cls), slot=_slot_from_any(slot), subject=str(subject))
        for (cls, slot), subject in sorted((day_inputs.fixed_assign or {}).items(), key=lambda item: (str(item[0][0]), str(item[0][1])))
    )
    requirements = tuple(
        SubjectRequirement(
            class_name=str(cls),
            subject=str(subj),
            early=int(values[0] or 0),
            weekday=int(values[1] or 0),
            weekend=int(values[2] or 0),
        )
        for (cls, subj), values in sorted((day_inputs.req_hours or {}).items())
    )
    bans = tuple(
        SubjectBan(subject=str(subject), slots=tuple(_slot_from_any(slot) for slot in sorted(slots, key=str)))
        for subject, slots in sorted((day_inputs.subject_ban_slots or {}).items())
    )
    return SchoolProblem(
        profile=profile,
        classes=classes,
        subjects=subjects,
        teachers=teachers,
        class_subject_teachers=cst_rows,
        available_slots=slots,
        fixed_assignments=fixed,
        subject_requirements=requirements,
        subject_bans=bans,
        academic_tables=_normalize_academic_tables(academic_payload),
        rule_instances=tuple(rule_instances),
        source=source,
    )


def school_problem_from_mapping(
    profile: SchoolProfile,
    data: Mapping[str, Any],
    *,
    rule_instances: Sequence[CompiledRuleInstance] = (),
    source: str = "mapping",
) -> SchoolProblem:
    rows = tuple(
        ClassSubjectTeacher(
            class_name=str(item.get("class") or item.get("class_name") or "").strip(),
            subject=str(item.get("subject") or "").strip(),
            teacher=str(item.get("teacher") or "").strip(),
        )
        for item in (data.get("class_subject_teachers") or ())
        if isinstance(item, Mapping)
    )
    classes = tuple(data.get("classes") or _sorted_unique(row.class_name for row in rows))
    subjects = tuple(data.get("subjects") or _sorted_unique(row.subject for row in rows))
    teachers = tuple(data.get("teachers") or _sorted_unique(row.teacher for row in rows))
    slots = tuple(_slot_from_mapping(item) for item in (data.get("available_slots") or ()))
    requirements = tuple(
        SubjectRequirement(
            class_name=str(item.get("class") or item.get("class_name") or "").strip(),
            subject=str(item.get("subject") or "").strip(),
            early=int(item.get("early") or 0),
            weekday=int(item.get("weekday") or 0),
            weekend=int(item.get("weekend") or 0),
        )
        for item in (data.get("subject_requirements") or ())
        if isinstance(item, Mapping)
    )
    return SchoolProblem(
        profile=profile,
        classes=tuple(str(item).strip() for item in classes if str(item).strip()),
        subjects=tuple(str(item).strip() for item in subjects if str(item).strip()),
        teachers=tuple(str(item).strip() for item in teachers if str(item).strip()),
        class_subject_teachers=tuple(row for row in rows if row.class_name and row.subject and row.teacher),
        available_slots=slots,
        subject_requirements=requirements,
        academic_tables=_normalize_academic_tables(data.get("academic_tables")),
        rule_instances=tuple(rule_instances),
        source=source,
    )


def validate_school_problem(problem: SchoolProblem) -> tuple[str, ...]:
    errors = list(validate_school_profile(problem.profile))
    if not problem.classes:
        errors.append("at least one class is required")
    if not problem.class_subject_teachers:
        errors.append("at least one class-subject-teacher row is required")
    class_set = set(problem.classes)
    subject_set = set(problem.subjects)
    teacher_set = set(problem.teachers)
    seen_cst: set[tuple[str, str]] = set()
    valid_days = set(problem.profile.calendar.teaching_days)
    for row in problem.class_subject_teachers:
        key = (row.class_name, row.subject)
        if key in seen_cst:
            errors.append(f"duplicate class-subject teacher row: {row.class_name}/{row.subject}")
        seen_cst.add(key)
        if row.class_name not in class_set:
            errors.append(f"class-subject row references unknown class: {row.class_name}")
        if row.subject not in subject_set:
            errors.append(f"class-subject row references unknown subject: {row.subject}")
        if row.teacher not in teacher_set:
            errors.append(f"class-subject row references unknown teacher: {row.teacher}")
    for slot in problem.available_slots:
        if slot.day not in valid_days:
            errors.append(f"slot references non-teaching day: {slot.day}")
    for fixed in problem.fixed_assignments:
        if fixed.class_name not in class_set:
            errors.append(f"fixed assignment references unknown class: {fixed.class_name}")
    for req in problem.subject_requirements:
        if req.class_name not in class_set:
            errors.append(f"subject requirement references unknown class: {req.class_name}")
        if req.subject not in subject_set:
            errors.append(f"subject requirement references unknown subject: {req.subject}")
    return tuple(errors)


def school_problem_summary(problem: SchoolProblem) -> dict[str, Any]:
    return {
        "profile_id": problem.profile.profile_id,
        "stage": problem.profile.stage,
        "classes": len(problem.classes),
        "subjects": len(problem.subjects),
        "teachers": len(problem.teachers),
        "class_subject_teacher_rows": len(problem.class_subject_teachers),
        "available_slots": len(problem.available_slots),
        "fixed_assignments": len(problem.fixed_assignments),
        "subject_requirements": len(problem.subject_requirements),
        "academic_tables": {key: len(rows) for key, rows in problem.academic_tables.items()},
        "rule_instances": len(problem.rule_instances),
        "source": problem.source,
    }


def _slot_from_any(value: Any) -> ProblemSlot:
    if isinstance(value, ProblemSlot):
        return value
    if isinstance(value, Mapping):
        return _slot_from_mapping(value)
    return ProblemSlot(
        day=str(getattr(value, "day")),
        block=str(getattr(value, "block")),
        period=int(getattr(value, "period")),
    )


def _slot_from_mapping(value: Mapping[str, Any]) -> ProblemSlot:
    return ProblemSlot(
        day=str(value.get("day") or "").strip(),
        block=str(value.get("block") or "").strip(),
        period=int(value.get("period") or 0),
    )


def _normalize_academic_tables(payload: Mapping[str, Any] | None) -> dict[str, tuple[Mapping[str, Any], ...]]:
    if not isinstance(payload, Mapping):
        return {}
    tables = payload.get("tables") if "tables" in payload else payload
    if not isinstance(tables, Mapping):
        return {}
    return {
        str(key): tuple(dict(row) for row in rows if isinstance(row, Mapping))
        for key, rows in tables.items()
        if isinstance(rows, list)
    }


def _sorted_unique(values: Sequence[str] | Any) -> tuple[str, ...]:
    return tuple(sorted({str(item).strip() for item in values if str(item).strip()}))
