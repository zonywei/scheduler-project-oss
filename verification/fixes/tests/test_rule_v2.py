from __future__ import annotations

from ortools.sat.python import cp_model

from scheduler.data.day_rules_reader import DayInputData, Slot
from scheduler.domain.rule_v2 import activate_rule_v2, normalize_rule_v2, parse_rule_v2_local
from scheduler.model.constraints.rule_v2 import apply_rule_v2_constraints
from scheduler.model.day_variables import build_day_variables


def _data() -> DayInputData:
    slots = [
        Slot("星期一", "上午", 1),
        Slot("星期一", "下午", 1),
        Slot("星期二", "上午", 1),
        Slot("星期二", "下午", 1),
    ]
    return DayInputData(
        classes=["1班"],
        cls_subj_teacher={("1班", "数学"): "样例教师A"},
        available_slots=slots,
        fixed_assign={},
        req_hours={("1班", "数学"): (0, 1, 0)},
        subject_ban_slots={},
    )


def _active(raw: dict) -> dict:
    return activate_rule_v2(normalize_rule_v2(raw), confirmed=True, actor="test")


def test_local_parser_builds_confirmable_teacher_unavailable_rule() -> None:
    parsed = parse_rule_v2_local(
        "样例教师A周一第1节不能排课",
        known_teachers=["样例教师A"],
        slot_context={"第1节": ["上午1"]},
    )
    assert parsed["constraint"]["type"] == "teacher_unavailable"
    assert parsed["solver_support"]["status"] == "supported"
    assert parsed["effective_time"]["days"] == ["星期一"]
    assert parsed["validation"]["valid"] is True


def test_local_parser_does_not_guess_a_teacher_from_an_unknown_name() -> None:
    parsed = parse_rule_v2_local(
        "样例教师A甲周一第1节不能排课",
        known_teachers=["1", "高三1班"],
        slot_context={"第1节": ["上午1"]},
    )
    assert parsed["scope"]["teachers"] == []
    assert parsed["status"] == "needs_clarification"


def test_unsupported_week_pattern_cannot_be_activated() -> None:
    parsed = parse_rule_v2_local(
        "样例教师A周一第1节不能排课",
        known_teachers=["样例教师A"],
        slot_context={"第1节": ["上午1"]},
    )
    parsed["effective_time"]["week_pattern"] = "odd"
    parsed = normalize_rule_v2(parsed)
    assert parsed["validation"]["valid"] is False


def test_local_parser_expands_periods_only_from_uploaded_slot_context() -> None:
    parsed = parse_rule_v2_local(
        "样例教师A周一上午不能排课",
        known_teachers=["样例教师A"],
        slot_context={"上午": ["上午1", "上午2", "上午3"]},
    )
    assert parsed["effective_time"]["slots"] == ["上午1", "上午2", "上午3"]

    unresolved = parse_rule_v2_local("样例教师A周一上午不能排课", known_teachers=["样例教师A"])
    assert unresolved["status"] == "needs_clarification"
    assert unresolved["effective_time"]["slots"] == []

    early = parse_rule_v2_local(
        "样例教师A早自习不能排课",
        known_teachers=["样例教师A"],
        slot_context={"早自习": ["早自习"]},
    )
    assert early["effective_time"]["slots"] == ["早自习"]


def test_local_parser_requires_exact_entity_binding_for_subject_and_class() -> None:
    parsed = parse_rule_v2_local(
        "物理甲周一上午不能排课",
        known_subjects=["物理"],
        known_classes=["实验班"],
        slot_context={"上午": ["上午1"]},
    )
    assert parsed["status"] == "needs_clarification"
    assert parsed["scope"]["subjects"] == []
    assert parsed["scope"]["classes"] == []


def test_compiler_applies_confirmed_hard_unavailability() -> None:
    data = _data()
    model = cp_model.CpModel()
    dv = build_day_variables(model, data)
    rule = _active({
        "title": "样例教师A周一上午不可排",
        "strength": "hard",
        "scope": {"teachers": ["样例教师A"]},
        "effective_time": {"mode": "project_term", "week_pattern": "all", "days": ["星期一"], "slots": ["上午1"]},
        "constraint": {"type": "teacher_unavailable", "params": {}},
        "solver_support": {"status": "supported", "compiler": "day.rule_v2.v1"},
    })
    result = apply_rule_v2_constraints(model, data, dv, {"rule_v2": {"rules": [rule]}}, grade_prefix="高二")
    target = dv.x[("1班", "数学", Slot("星期一", "上午", 1))]
    model.Add(target == 1)
    status = cp_model.CpSolver().Solve(model)
    assert status == cp_model.INFEASIBLE
    assert result.applied_rule_ids == [rule["id"]]


def test_compiler_adds_soft_preference_terms_without_forcing_infeasible() -> None:
    data = _data()
    model = cp_model.CpModel()
    dv = build_day_variables(model, data)
    rule = _active({
        "title": "数学尽量排上午",
        "strength": "soft",
        "scope": {"subjects": ["数学"]},
        "effective_time": {"mode": "project_term", "week_pattern": "all"},
        "constraint": {"type": "prefer_period", "params": {"period": "morning"}},
        "solver_support": {"status": "supported", "compiler": "day.rule_v2.v1"},
        "weight": 500,
    })
    result = apply_rule_v2_constraints(model, data, dv, {"rule_v2": {"rules": [rule]}})
    assert len(result.objective_terms) == 2
    model.Minimize(sum(result.objective_terms))
    assert cp_model.CpSolver().Solve(model) in {cp_model.OPTIMAL, cp_model.FEASIBLE}


def test_unconfirmed_rule_is_skipped() -> None:
    data = _data()
    model = cp_model.CpModel()
    dv = build_day_variables(model, data)
    draft = parse_rule_v2_local("样例教师A周一第1节不能排课", known_teachers=["样例教师A"])
    result = apply_rule_v2_constraints(model, data, dv, {"rule_v2": {"rules": [draft]}})
    assert result.applied_rule_ids == []
    assert result.skipped_rule_ids == [draft["id"]]
