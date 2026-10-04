from __future__ import annotations

import copy

import pytest
from ortools.sat.python import cp_model

from scheduler.app.job_api import normalize_solve_request
from scheduler.course_solver import build_course_model
from scheduler.domain.rule_v2 import activate_rule_v2, normalize_rule_v2
from scheduler.domain.rule_v2 import parse_rule_v2_local


def inputs():
    return {"web_tables": {
        "teacher_subjects": [{"班级": "三年级A", "科学": "教师A", "艺术": "教师B"}],
        "day_rules": {
            "time_grid": [{"星期": "星期六", "时段": "社团", "节次": 1}, {"星期": "星期日", "时段": "夜间课程", "节次": 9}],
            "subject_hours": [{"学科": "科学", "周期课时": 1}, {"学科": "艺术", "周期课时": 1}],
            "fixed_slots": [], "class_overrides": [], "subject_bans": [],
        },
    }}


def rule(kind="teacher_unavailable", *, teacher="教师A", strength="hard", params=None):
    return activate_rule_v2(normalize_rule_v2({"title": "测试规则", "strength": strength, "scope": {"teachers": [teacher]}, "effective_time": {"mode": "project_term", "week_pattern": "all", "days": ["星期六"], "slots": ["社团1"]}, "constraint": {"type": kind, "params": params or {}}, "solver_support": {"status": "supported", "compiler": "day.rule_v2.v1"}, "weight": 50}), confirmed=True, actor="test")


def test_custom_blocks_and_weekend_demand_are_not_split_into_legacy_quotas():
    model = cp_model.CpModel()
    data, dv, receipt = build_course_model(model, inputs(), {"rule_v2": {"rules": [rule()]}})
    solver = cp_model.CpSolver()
    assert solver.Solve(model) == cp_model.OPTIMAL
    assert solver.Value(dv.x[("三年级A", "科学", data.available_slots[0])]) == 0
    assert receipt.diagnostics[0]["constraint_units"] == 1
    assert normalize_solve_request({"mode": "course"})["mode"] == "course"


def test_fixed_course_counts_toward_demand_and_teacher_availability():
    io = inputs()
    io["web_tables"]["day_rules"]["fixed_slots"] = [{"班级": "三年级A", "星期": "星期六", "时段": "社团", "节次": 1, "学科": "科学"}]
    model = cp_model.CpModel()
    data, dv, _ = build_course_model(model, io, {})
    solver = cp_model.CpSolver()
    assert solver.Solve(model) == cp_model.OPTIMAL
    assert len([key for key, var in dv.x.items() if solver.Value(var)]) == 1
    with pytest.raises(ValueError, match="固定安排与规则冲突"):
        build_course_model(cp_model.CpModel(), io, {"rule_v2": {"rules": [rule()]}})


def test_shared_teacher_cannot_teach_a_fixed_and_variable_lesson_together():
    io = inputs()
    io["web_tables"]["teacher_subjects"].append({"班级": "三年级B", "科学": "教师A", "艺术": "教师C"})
    io["web_tables"]["day_rules"]["fixed_slots"] = [{"班级": "三年级A", "星期": "星期六", "时段": "社团", "节次": 1, "学科": "科学"}]
    model = cp_model.CpModel()
    data, dv, _ = build_course_model(model, io, {})
    solver = cp_model.CpSolver()
    assert solver.Solve(model) == cp_model.OPTIMAL
    assert solver.Value(dv.x[("三年级B", "科学", data.available_slots[0])]) == 0


def test_available_slots_do_not_require_full_occupancy():
    io = inputs()
    io["web_tables"]["day_rules"]["subject_hours"][1]["周期课时"] = 0
    model = cp_model.CpModel()
    _, dv, _ = build_course_model(model, io, {})
    solver = cp_model.CpSolver()
    assert solver.Solve(model) == cp_model.OPTIMAL
    assert sum(solver.Value(var) for var in dv.x.values()) == 1


@pytest.mark.parametrize("first_block", ["课程", "早自习"])
def test_first_slot_preference_respects_configured_order_of_custom_blocks(first_block):
    io = inputs()
    io["web_tables"]["day_rules"]["time_grid"] = [{"星期": "星期六", "时段": first_block, "节次": 8}, {"星期": "星期六", "时段": "社团", "节次": 1}]
    preferred = rule("prefer_period", params={"period": "first"})
    preferred["effective_time"]["slots"] = []
    model = cp_model.CpModel()
    data, dv, _ = build_course_model(model, io, {"rule_v2": {"rules": [preferred]}})
    solver = cp_model.CpSolver()
    assert solver.Solve(model) == cp_model.OPTIMAL
    assert solver.Value(dv.x[("三年级A", "科学", data.available_slots[0])]) == 1


def test_preference_already_guaranteed_by_available_slots_is_not_rejected():
    model = cp_model.CpModel()
    preferred = rule("prefer_period", params={"period": "first"})
    preferred["effective_time"]["slots"] = []
    _, _, receipt = build_course_model(model, inputs(), {"rule_v2": {"rules": [preferred]}})
    assert receipt.diagnostics[0]["status"] == "delegated"


def test_natural_language_uses_only_the_school_configured_custom_slots():
    parsed = parse_rule_v2_local("教师A周六社团1不能排课", known_teachers=["教师A"], slot_context={"社团1": ["社团1"]})
    assert parsed["solver_support"]["status"] == "supported"
    assert parsed["effective_time"]["slots"] == ["社团1"]
    assert parse_rule_v2_local("教师A周六社团2不能排课", known_teachers=["教师A"], slot_context={"社团1": ["社团1"]})["solver_support"]["status"] != "supported"
    from scheduler.app.formal_product import parse_rule_v2_with_ai
    fallback = parse_rule_v2_with_ai("教师A周六社团1不能排课", known_teachers=["教师A"], slot_context={"社团1": ["社团1"]})
    assert fallback["solver_support"]["status"] == "supported"
    assert fallback["ai_used"] is False


def test_explicit_empty_import_never_reads_a_legacy_workbook(monkeypatch):
    from scheduler.data.day_rules_reader import _read_teacher_positioning
    from scheduler.app import config_service
    from types import SimpleNamespace
    import pandas as pd
    monkeypatch.setattr(pd, "read_excel", lambda *args, **kwargs: pytest.fail("read legacy workbook"))
    frame = _read_teacher_positioning("old-school.xlsx", {"teacher_subjects": []})
    assert frame.empty
    monkeypatch.setattr(config_service, "load_effective_config", lambda *args, **kwargs: SimpleNamespace(io_cfg={"day": {"rules_path": "old-school.xlsx"}, "web_tables": {"day_rules": {key: [] for key in ("time_grid", "fixed_slots", "subject_hours", "subject_bans", "class_overrides")}}}))
    assert config_service.load_day_rule_tables()["subject_hours"] == []


def test_course_template_and_import_preserve_cycle_demand_and_custom_blocks(monkeypatch):
    from scheduler.app import config_service
    monkeypatch.setattr(config_service, "load_day_rule_tables", lambda: {})
    content = config_service.build_day_rule_table_template_csv("subject_hours", mode="course").decode("utf-8-sig")
    imported = config_service.parse_day_rule_table_csv("subject_hours", content)
    assert imported["rows"] == [{"学科": "语文", "周期课时": "5"}]
    imported = config_service.parse_day_rule_table_csv("time_grid", "时段,节次,星期六\n社团,1,1\n")
    assert imported["rows"] == [{"时段": "社团", "节次": "1", "星期六": "1"}]


def test_conflicting_hard_rules_produce_infeasible_without_relaxation():
    io = inputs()
    unavailable = rule()
    unavailable["effective_time"]["days"] = ["星期六", "星期日"]
    unavailable["effective_time"]["slots"] = []
    model = cp_model.CpModel()
    build_course_model(model, io, {"rule_v2": {"rules": [unavailable]}})
    assert cp_model.CpSolver().Solve(model) == cp_model.INFEASIBLE


@pytest.mark.parametrize("change", ["empty", "duplicate", "fractional", "capacity", "unknown_rule"])
def test_invalid_business_inputs_are_blocked(change):
    io = copy.deepcopy(inputs())
    tables = io["web_tables"]["day_rules"]
    rules = {}
    if change == "empty":
        io["web_tables"]["teacher_subjects"] = []
    elif change == "duplicate":
        tables["time_grid"].append(dict(tables["time_grid"][0]))
    elif change == "fractional":
        tables["subject_hours"][0]["周期课时"] = 1.5
    elif change == "capacity":
        tables["subject_hours"][0]["周期课时"] = 2
    else:
        rules = {"rule_v2": {"rules": [rule(teacher="未知教师")]}}
    with pytest.raises(ValueError):
        build_course_model(cp_model.CpModel(), io, rules)
