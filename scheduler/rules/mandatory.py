# -*- coding: utf-8 -*-
"""Product-facing mandatory rules that define a legally usable schedule.

These rows are deliberately separate from school preferences.  They are
locked, always hard, and must have either CP-SAT constraint evidence or an
input/model-structure receipt before a solve may start.
"""
from __future__ import annotations

from typing import Any


MANDATORY_DEFAULT_RULES: tuple[dict[str, Any], ...] = (
    {
        "id": "system.course.class_slot_unique",
        "title": "同一班级同一时段只能有一项课程安排",
        "explanation": "每个启用课位只能对应一门课程或一项固定活动，不能同时出现两门课、两位教师或重复占课。",
        "business_domain": "course",
        "rule_category": "basic",
        "scope": "全部班级 / 全部启用课位",
        "solver_bindings": ["joint.day.one_subject_per_slot", "joint.night.hard_base"],
        "enforcement": "cp_sat_constraint",
    },
    {
        "id": "system.course.teacher_slot_unique",
        "title": "同一教师同一时段只能承担一个教学任务",
        "explanation": "教师不能分身，不能在同一节课同时给两个班上课，也不能同时出现在两个教学地点。",
        "business_domain": "course",
        "rule_category": "basic",
        "scope": "全部教师 / 全部启用课位",
        "solver_bindings": ["joint.day.teacher_no_conflict", "joint.night.hard_teacher_limits"],
        "enforcement": "cp_sat_constraint",
    },
    {
        "id": "system.course.subject_hours_exact",
        "title": "班级学科课时必须与课时计划一致",
        "explanation": "每个班级、每门学科的早自习、工作日、周末及晚自习课时必须满足已确认的课时计划。",
        "business_domain": "course",
        "rule_category": "basic",
        "scope": "全部班级 / 全部开设学科",
        "solver_bindings": ["joint.day.subject_hour_constraints", "joint.night.hard_base"],
        "enforcement": "cp_sat_constraint",
    },
    {
        "id": "system.course.active_slots_only",
        "title": "课程只能安排在已启用的作息时段",
        "explanation": "停课日、公休日和未启用节次不会生成排课变量，求解器不能把课程排到作息表之外。",
        "business_domain": "course",
        "rule_category": "basic",
        "scope": "本学期作息表",
        "solver_bindings": ["system.calendar.active_slot_only"],
        "enforcement": "model_structure",
    },
    {
        "id": "system.course.fixed_activity_protected",
        "title": "固定课程和固定事项不得被普通课程覆盖",
        "explanation": "已确认的班会、活动、固定课位等先占用对应课位，普通排课不会在同一位置再次建模。",
        "business_domain": "course",
        "rule_category": "basic",
        "scope": "全部固定课位",
        "solver_bindings": ["system.day.fixed_slot_integrity"],
        "enforcement": "model_structure",
    },
    {
        "id": "system.course.teacher_assignment_complete",
        "title": "每个教学任务必须关联有效任课关系",
        "explanation": "只有教师定位表中存在的班级、学科、教师关系才能进入模型，缺失或重复关系会在求解前阻断。",
        "business_domain": "course",
        "rule_category": "basic",
        "scope": "全部班级 / 学科 / 教师",
        "solver_bindings": ["system.assignment.teacher_mapping_required"],
        "enforcement": "input_validation",
    },
    {
        "id": "system.course.hard_bans_enforced",
        "title": "已确认的禁排时段必须严格执行",
        "explanation": "学科禁排、教师不可用和明确的硬禁排一旦确认，就不会生成可违反的候选安排。",
        "business_domain": "course",
        "rule_category": "basic",
        "scope": "全部已确认硬禁排",
        "solver_bindings": ["system.hard_unavailability"],
        "enforcement": "model_structure",
    },
    {
        "id": "system.roster.person_slot_unique",
        "title": "同一人员同一时段只能承担一个排班任务",
        "explanation": "值班、查寝等排班任务启用后，同一人员不能在重叠时段被重复安排。",
        "business_domain": "roster",
        "rule_category": "basic",
        "scope": "全部启用的排班任务",
        "solver_bindings": ["joint.day.head_duty_constraints", "joint.day.noon_dorm_duty_constraints", "joint.night.checkin"],
        "enforcement": "cp_sat_constraint",
        "conditional": True,
    },
    {
        "id": "system.roster.staffing_satisfied",
        "title": "每个启用班次必须满足岗位人数要求",
        "explanation": "启用值班或查寝后，每个班次必须安排足额且符合候选条件的人员，否则模型不可行。",
        "business_domain": "roster",
        "rule_category": "basic",
        "scope": "全部启用的班次与岗位",
        "solver_bindings": ["joint.day.head_duty_constraints", "joint.day.noon_dorm_duty_constraints", "joint.night.checkin"],
        "enforcement": "cp_sat_constraint",
        "conditional": True,
    },
    {
        "id": "system.roster.candidate_eligibility",
        "title": "排班人员必须来自有效候选范围",
        "explanation": "岗位身份、性别、年级组、排除名单和可用日期共同决定候选池，候选池外人员不会进入排班模型。",
        "business_domain": "roster",
        "rule_category": "basic",
        "scope": "全部启用的排班候选池",
        "solver_bindings": ["joint.day.head_duty_constraints", "joint.day.noon_dorm_duty_constraints", "joint.night.checkin"],
        "enforcement": "model_structure",
        "conditional": True,
    },
)


MANDATORY_RULE_IDS = frozenset(str(item["id"]) for item in MANDATORY_DEFAULT_RULES)


def mandatory_default_rules() -> list[dict[str, Any]]:
    """Return JSON-safe copies for API payloads."""
    return [
        {
            **item,
            "targets": ["全体适用"],
            "mode": "硬规则",
            "enabled": True,
            "mandatory": True,
            "locked": True,
            "editable": False,
            "deletable": False,
            "allow_exceptions": False,
            "policy_level": "default",
            "effective_time": {"mode": "project_term", "week_pattern": "all"},
            "solver_support": {
                "status": "supported",
                "message": "求解前必须取得实际建模回执",
            },
            "editor": {"fields": []},
        }
        for item in MANDATORY_DEFAULT_RULES
    ]
