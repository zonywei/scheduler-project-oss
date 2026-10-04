# -*- coding: utf-8 -*-
from __future__ import annotations

import inspect

import pandas as pd

from ai_orchestrated_optimization import OptimizationProblemSpec
import scheduler.exam_review_schedule as exam_review_schedule
from scheduler.exam_review_schedule import (
    CORE_SUBJECTS,
    BLOCK_BY_CODE,
    build_class_wide_table,
    load_review_courses,
    solve_review_schedule,
)


def _write_teacher_positioning(path):
    rows = [
        {
            "班级": "1班",
            "班主任": "",
            "班主任性别": "",
            "语文": "语文1",
            "数学": "共享数学",
            "外语": "外语1",
            "物理": "物理1",
            "化学": "化学1",
            "生物": "生物1",
            "历史": "",
            "政治": "",
            "地理": "",
        },
        {
            "班级": "2班",
            "班主任": "",
            "班主任性别": "",
            "语文": "语文2",
            "数学": "共享数学",
            "外语": "外语2",
            "物理": "物理2",
            "化学": "化学2",
            "生物": "生物2",
            "历史": "",
            "政治": "",
            "地理": "",
        },
    ]
    pd.DataFrame(rows).to_excel(path, sheet_name="Sheet1", index=False)


def test_exam_review_schedule_enforces_date_rules_and_teacher_conflict(tmp_path):
    xlsx_path = tmp_path / "教师定位表.xlsx"
    _write_teacher_positioning(xlsx_path)

    classes, courses_by_class = load_review_courses(xlsx_path)
    result = solve_review_schedule(classes, courses_by_class, time_limit_seconds=5)

    assert result.validation_errors == ()
    assert len(result.assignments) == 12

    by_class_date = {}
    for assignment in result.assignments:
        block = BLOCK_BY_CODE[assignment.block_code]
        by_class_date.setdefault((assignment.class_name, block.date_label), set()).add(assignment.subject)

    for class_name in classes:
        assert by_class_date[(class_name, "5.21")] == CORE_SUBJECTS
        assert by_class_date[(class_name, "5.22")] == set(courses_by_class[class_name]) - CORE_SUBJECTS

    shared_math_blocks = {
        assignment.block_code
        for assignment in result.assignments
        if assignment.teacher == "共享数学"
    }
    assert len(shared_math_blocks) == 2


def test_exam_review_schedule_compiles_to_generic_ai_or_problem(tmp_path):
    xlsx_path = tmp_path / "教师定位表.xlsx"
    _write_teacher_positioning(xlsx_path)

    classes, courses_by_class = load_review_courses(xlsx_path)
    assert hasattr(exam_review_schedule, "build_review_schedule_problem")
    compiled = exam_review_schedule.build_review_schedule_problem(classes, courses_by_class)

    assert isinstance(compiled.problem, OptimizationProblemSpec)
    assert compiled.problem.problem_id == "exam_review_schedule"
    assert {rule.rule_id for rule in compiled.problem.rules} >= {
        "review.class_subject_once",
        "review.class_block_once",
        "review.teacher_block_capacity",
        "review.subject_sync",
    }
    assert len(compiled.assignment_by_variable) == 40

    solve_source = inspect.getsource(exam_review_schedule.solve_review_schedule)
    assert "solve_cp_sat_problem" in solve_source
    assert "cp_model.CpModel" not in solve_source
    assert "cp_model.CpSolver" not in solve_source


def test_exam_review_class_wide_table_has_six_review_blocks(tmp_path):
    xlsx_path = tmp_path / "教师定位表.xlsx"
    _write_teacher_positioning(xlsx_path)

    classes, courses_by_class = load_review_courses(xlsx_path)
    result = solve_review_schedule(classes, courses_by_class, time_limit_seconds=5)
    table = build_class_wide_table(result)

    assert list(table.columns) == ["班级", "5.21 第1-2节", "5.21 第3-4节", "5.22 第1-2节", "5.22 第3-4节", "5.22 第5-6节", "5.22 第7-8节"]
    assert table.shape == (2, 7)
