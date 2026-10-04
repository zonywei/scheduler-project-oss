from __future__ import annotations

import sys
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


from scheduler.data.day_rules_reader import DayInputData, Slot  # noqa: E402
from scheduler.app.school_problem_preview import build_school_problem_preview_payload  # noqa: E402
from scheduler.domain.rule_instance import compile_rule_instances, rule_instances_from_mapping  # noqa: E402
from scheduler.domain.school_problem import (  # noqa: E402
    school_problem_from_day_inputs,
    school_problem_from_mapping,
    school_problem_summary,
    validate_school_problem,
)
from scheduler.domain.school_profile import profile_from_mapping  # noqa: E402
from scheduler.rules import build_default_rule_registry  # noqa: E402


def _load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _profile(profile_id: str):
    path = REPO_ROOT / "profiles" / profile_id / "profile.yaml"
    return profile_from_mapping(_load_yaml(path), source=path.relative_to(REPO_ROOT).as_posix())


def _compiled_rule_instances(profile_id: str):
    path = REPO_ROOT / "profiles" / profile_id / "profile.yaml"
    return compile_rule_instances(rule_instances_from_mapping(_load_yaml(path), source=path.relative_to(REPO_ROOT).as_posix()))


def test_school_problem_adapter_accepts_existing_day_input_data_without_solver_side_effects() -> None:
    profile = _profile("current_school")
    day_inputs = DayInputData(
        classes=["1班", "2班"],
        cls_subj_teacher={
            ("1班", "语文"): "匿名教师A",
            ("1班", "数学"): "匿名教师B",
            ("2班", "语文"): "匿名教师C",
        },
        available_slots=[Slot(day="星期一", block="上午", period=1), Slot(day="星期日", block="晚自习", period=1)],
        fixed_assign={("1班", Slot(day="星期一", block="上午", period=1)): "班会"},
        req_hours={("1班", "语文"): (0, 4, 1), ("1班", "数学"): (0, 4, 1), ("2班", "语文"): (0, 4, 1)},
        subject_ban_slots={"语文": {Slot(day="星期日", block="晚自习", period=1)}},
    )

    problem = school_problem_from_day_inputs(
        profile,
        day_inputs,
        academic_payload={"tables": {"after_school": [{"课程名称": "答疑", "状态": "待确认"}]}},
        rule_instances=_compiled_rule_instances("current_school"),
        source="unit.day_inputs",
    )

    assert validate_school_problem(problem) == ()
    summary = school_problem_summary(problem)
    assert summary["profile_id"] == "current_school"
    assert summary["classes"] == 2
    assert summary["subjects"] == 2
    assert summary["teachers"] == 3
    assert summary["fixed_assignments"] == 1
    assert summary["rule_instances"] == 46
    assert summary["academic_tables"] == {"after_school": 1}


def test_school_problem_mapping_adapter_validates_cross_school_fixtures() -> None:
    expectations = {
        "base_high_school": {"stage": "senior", "classes": 2, "rule_instances": 1},
        "junior_day_school": {"stage": "junior", "classes": 1, "rule_instances": 1},
        "primary_after_school": {"stage": "primary", "classes": 1, "rule_instances": 1},
    }
    for profile_id, expected in expectations.items():
        profile = _profile(profile_id)
        problem_data = _load_yaml(REPO_ROOT / "profiles" / profile_id / "sample_problem.yaml")
        problem = school_problem_from_mapping(
            profile,
            problem_data,
            rule_instances=_compiled_rule_instances(profile_id),
            source=f"profiles/{profile_id}/sample_problem.yaml",
        )

        assert validate_school_problem(problem) == ()
        summary = school_problem_summary(problem)
        assert summary["stage"] == expected["stage"]
        assert summary["classes"] == expected["classes"]
        assert summary["rule_instances"] == expected["rule_instances"]
        assert summary["class_subject_teacher_rows"] >= expected["classes"]


def test_school_problem_validation_rejects_rows_outside_profile_scope() -> None:
    profile = _profile("junior_day_school")
    problem = school_problem_from_mapping(
        profile,
        {
            "classes": ["七年级1班"],
            "class_subject_teachers": [{"class": "七年级1班", "subject": "语文", "teacher": "匿名教师"}],
            "available_slots": [{"day": "星期日", "block": "上午", "period": 1}],
        },
    )

    errors = validate_school_problem(problem)
    assert "slot references non-teaching day: 星期日" in errors


def test_school_problem_preview_payload_adapts_web_tables_without_solver_side_effects(tmp_path: Path) -> None:
    cfg_dir = tmp_path / "scheduler" / "config"
    cfg_dir.mkdir(parents=True)
    io_path = cfg_dir / "io.yaml"
    io_path.write_text("io: 1\n", encoding="utf-8")
    io_cfg = {
        "day": {"rules_path": "白天规则.xlsx", "teacher_table_path": "教师定位表.xlsx"},
        "web_tables": {
            "teacher_subjects": [
                {"班级": "1班", "班主任": "教师A", "班主任性别": "男", "语文": "教师A", "数学": "教师B"},
                {"班级": "2班", "班主任": "教师C", "班主任性别": "女", "语文": "教师C", "数学": "教师B"},
            ],
            "day_rules": {
                "time_grid": [
                    {
                        "时段节次": "上午1",
                        "星期一": 1,
                        "星期二": 1,
                        "星期三": 0,
                        "星期四": 0,
                        "星期五": 0,
                        "星期六": 0,
                        "星期日": 0,
                    }
                ],
                "fixed_slots": [],
                "subject_hours": [
                    {"学科": "语文", "早自习课时": 0, "周中课时": 1, "周末课时": 0},
                    {"学科": "数学", "早自习课时": 0, "周中课时": 1, "周末课时": 0},
                ],
                "subject_bans": [],
                "class_overrides": [],
            },
        },
    }

    payload = build_school_problem_preview_payload(
        mode="joint",
        effective_cfg={"calendar": {"days": ["星期一", "星期二"], "periods": []}},
        io_cfg=io_cfg,
        io_path=io_path,
        registry=build_default_rule_registry(),
        source="web_preview",
    )

    assert payload["schema_version"] == "scheduler.school_problem_preview.v1"
    assert payload["source"] == "web_preview"
    assert payload["solver_effect"] == "none"
    assert payload["validation"]["ok"] is True
    assert payload["summary"]["profile_id"] == "current_school"
    assert payload["summary"]["classes"] == 2
    assert payload["summary"]["class_subject_teacher_rows"] == 4
    assert payload["summary"]["available_slots"] == 2
    assert payload["summary"]["rule_instances"] == 0
