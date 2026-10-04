from __future__ import annotations

import sys
import json
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


from scheduler.app import config_service
from scheduler.app import readiness as readiness_module
from scheduler.app.readiness import build_readiness_payload, build_solve_readiness_preview, latest_matching_infeasible_item


def _config_payload(tmp_path: Path) -> dict:
    io_path = tmp_path / "io.yaml"
    rules_path = tmp_path / "rules.yaml"
    io_path.write_text("teacher_table: {}\n", encoding="utf-8")
    rules_path.write_text("evening: {}\n", encoding="utf-8")
    return {
        "paths": {"io": str(io_path), "rules": str(rules_path)},
        "effective": {
            "teacher_table": {"columns": {"class": "班级", "head": "班主任", "head_gender": "班主任性别"}},
            "evening": {"subjects": ["语文"]},
        },
        "business_rule_groups": [{"rules": [{"id": "demo"}]}],
    }


def _academic_payload(risks: list[dict] | None = None) -> dict:
    return {
        "summary": {
            "risks": risks or [],
            "metrics": {"health_score": 100 if not risks else 72},
        }
    }


def _conflict_payload(errors: int = 0, warnings: int = 0) -> dict:
    return {
        "summary": {"total": errors + warnings, "errors": errors, "warnings": warnings},
        "conflicts": [],
    }


def test_readiness_blocks_solver_when_required_inputs_or_rules_fail(tmp_path: Path) -> None:
    readiness = build_readiness_payload(
        mode="joint",
        config_payload=_config_payload(tmp_path),
        teacher_rows=[],
        day_rule_tables={"time_grid": [], "subject_hours": []},
        academic_payload=_academic_payload(),
        conflict_payload=_conflict_payload(errors=1),
    )

    assert readiness["summary"]["can_start_solver"] is False
    assert readiness["summary"]["blocking_errors"] >= 3
    titles = {item["title"] for item in readiness["items"] if item["blocking"]}
    assert "教师定位表没有可用数据" in titles
    assert "白天时间格子为空" in titles
    assert "存在确定不可行的规则组合" in titles


def test_readiness_allows_solver_but_marks_publish_risk(tmp_path: Path) -> None:
    readiness = build_readiness_payload(
        mode="joint",
        config_payload=_config_payload(tmp_path),
        teacher_rows=[{"班级": "1班", "班主任": "教师D", "班主任性别": "女", "语文": "教师A"}],
        day_rule_tables={
            "time_grid": [{"时段节次": "上午1", "星期一": 1}],
            "subject_hours": [{"学科": "语文", "周中课时": 5}],
        },
        academic_payload=_academic_payload(
            [{"severity": "error", "title": "教师同一时段多任务冲突", "detail": "", "suggestion": ""}]
        ),
        conflict_payload=_conflict_payload(),
    )

    assert readiness["summary"]["can_start_solver"] is True
    assert readiness["summary"]["can_publish"] is False
    assert readiness["summary"]["status"] == "ready"
    assert any(item["publish_blocking"] for item in readiness["items"])
    quality = readiness["metrics"]["teacher_data_quality"]
    assert quality["subject_coverage"][0]["subject"] == "语文"
    assert quality["subject_coverage"][0]["coverage_pct"] == 100


def test_readiness_recommends_substitutes_from_leave_log_without_blocking_solver(tmp_path: Path) -> None:
    config = _config_payload(tmp_path)
    readiness = build_readiness_payload(
        mode="joint",
        config_payload=config,
        teacher_rows=[
            {"班级": "初一1班", "班主任": "教师D", "班主任性别": "女", "语文": "教师A"},
            {"班级": "初一2班", "班主任": "钱老师", "班主任性别": "女", "语文": "教师B"},
            {"班级": "初二1班", "班主任": "教师G", "班主任性别": "男", "语文": "教师C"},
            {"班级": "初一3班", "班主任": "教师H", "班主任性别": "男", "数学": "吴老师"},
        ],
        day_rule_tables={
            "time_grid": [{"时段节次": "上午1", "星期一": 1}],
            "subject_hours": [{"学科": "语文", "周中课时": 5}],
        },
        academic_payload={
            "data": {
                "tables": {
                    "teacher_leave": [
                        {"教师": "教师A", "星期": "星期一", "时段": "全天", "状态": "已审批"},
                    ]
                }
            },
            "summary": {"risks": [], "metrics": {"health_score": 100}},
        },
        conflict_payload=_conflict_payload(),
    )

    item = next(item for item in readiness["items"] if item["title"] == "请假日志代课建议")
    assert readiness["summary"]["can_start_solver"] is True
    assert item["blocking"] is False
    assert item["publish_blocking"] is False
    assert item["remediation_options"][0]["id"] == "academic.review_leave_log_substitutes"
    assert item["remediation_options"][0]["fields"] == []
    evidence = item["evidence"][0]["value"]
    assert "同年级同学科：教师B（初一2班）" in evidence
    assert "非同年级同学科：教师C（初二1班）" in evidence
    assert "hard_bans.teacher_day_bans" not in json.dumps(item, ensure_ascii=False)


def test_night_readiness_does_not_require_day_rule_tables(tmp_path: Path) -> None:
    readiness = build_readiness_payload(
        mode="night",
        config_payload=_config_payload(tmp_path),
        teacher_rows=[{"班级": "1班", "语文": "教师A"}],
        day_rule_tables={},
        academic_payload=_academic_payload(),
        conflict_payload=_conflict_payload(),
    )

    assert readiness["summary"]["status"] == "ready"
    assert readiness["summary"]["can_start_solver"] is True
    assert all(item["domain"] != "白天规则" for item in readiness["items"])


def test_night_readiness_uses_uploaded_subjects_without_technical_or_head_columns(tmp_path: Path) -> None:
    config = _config_payload(tmp_path)
    config["effective"]["evening"]["subjects"] = []

    readiness = build_readiness_payload(
        mode="night",
        config_payload=config,
        teacher_rows=[{"班级": "1班", "综合实践": "教师A"}],
        day_rule_tables={},
        academic_payload=_academic_payload(),
        conflict_payload=_conflict_payload(),
    )

    assert readiness["summary"]["can_start_solver"] is True
    assert not any(item["title"] == "晚自习学科列缺失" for item in readiness["items"])
    quality = readiness["metrics"]["teacher_data_quality"]
    assert quality["subject_coverage"] == [
        {"subject": "综合实践", "present": True, "filled": 1, "total": 1, "missing": 0, "coverage_pct": 100}
    ]


def test_readiness_allows_course_solver_without_head_names(tmp_path: Path) -> None:
    config = _config_payload(tmp_path)
    config["effective"]["day"] = {
        "head_duty_constraints": {
            "enabled": True,
            "enable_head_pm1_min": True,
        }
    }

    readiness = build_readiness_payload(
        mode="joint",
        config_payload=config,
        teacher_rows=[{"班级": "1班", "语文": "教师A", "班主任": ""}],
        day_rule_tables={
            "time_grid": [{"时段节次": "上午1", "星期一": 1}],
            "subject_hours": [{"学科": "语文", "周中课时": 5}],
        },
        academic_payload=_academic_payload(),
        conflict_payload=_conflict_payload(),
    )

    assert readiness["summary"]["can_start_solver"] is True
    item = next(item for item in readiness["items"] if item["title"] == "未提供班主任信息（可选）")
    assert item["severity"] == "info"
    assert item["blocking"] is False


def test_readiness_allows_course_solver_without_head_names_when_pm1_is_enabled(tmp_path: Path) -> None:
    config = _config_payload(tmp_path)
    config["effective"]["day"] = {
        "weekday_constraints": {
            "enable_head_pm1_min": True,
        },
        "head_duty_constraints": {
            "enabled": False,
        },
    }

    readiness = build_readiness_payload(
        mode="joint",
        config_payload=config,
        teacher_rows=[{"班级": "1班", "语文": "教师A", "班主任": ""}],
        day_rule_tables={
            "time_grid": [{"时段节次": "上午1", "星期一": 1}],
            "subject_hours": [{"学科": "语文", "周中课时": 5}],
        },
        academic_payload=_academic_payload(),
        conflict_payload=_conflict_payload(),
    )

    assert readiness["summary"]["can_start_solver"] is True
    item = next(item for item in readiness["items"] if item["title"] == "未提供班主任信息（可选）")
    assert item["severity"] == "info"
    assert item["blocking"] is False


def test_readiness_distinguishes_missing_subject_columns_from_blank_cells(tmp_path: Path) -> None:
    config = _config_payload(tmp_path)
    config["effective"]["evening"]["subjects"] = ["语文", "数学"]

    readiness = build_readiness_payload(
        mode="joint",
        config_payload=config,
        teacher_rows=[{"班级": "1班", "班主任": "教师D", "班主任性别": "女", "语文": "教师A"}],
        day_rule_tables={
            "time_grid": [{"时段节次": "上午1", "星期一": 1}],
            "subject_hours": [{"学科": "语文", "周中课时": 5}],
        },
        academic_payload=_academic_payload(),
        conflict_payload=_conflict_payload(),
    )

    assert readiness["summary"]["can_start_solver"] is False
    assert any(item["title"] == "晚自习学科列缺失" and item["blocking"] for item in readiness["items"])
    quality = readiness["metrics"]["teacher_data_quality"]
    by_subject = {item["subject"]: item for item in quality["subject_coverage"]}
    assert by_subject["语文"]["present"] is True
    assert by_subject["数学"]["present"] is False


def test_teacher_quality_reports_actionable_row_issues(tmp_path: Path) -> None:
    readiness = build_readiness_payload(
        mode="joint",
        config_payload=_config_payload(tmp_path),
        teacher_rows=[
            {"row_index": 0, "班级": "1班", "班主任": "", "班主任性别": "", "语文": ""},
            {"row_index": 1, "班级": "2班", "班主任": "教师C", "班主任性别": "女", "语文": "教师B"},
        ],
        day_rule_tables={
            "time_grid": [{"时段节次": "上午1", "星期一": 1}],
            "subject_hours": [{"学科": "语文", "周中课时": 5}],
        },
        academic_payload=_academic_payload(),
        conflict_payload=_conflict_payload(),
    )

    quality = readiness["metrics"]["teacher_data_quality"]
    assert quality["issue_rows"] == 1
    assert quality["missing_subject_cells"] == 1
    issue = quality["row_issues"][0]
    assert issue["class_name"] == "1班"
    assert issue["missing_fields"] == []
    assert issue["missing_subjects"] == ["语文"]
    assert issue["has_any_subject_teacher"] is False


def test_readiness_skips_checkin_when_optional_gender_pool_is_missing(tmp_path: Path) -> None:
    config = _config_payload(tmp_path)
    config["effective"]["calendar"] = {"days": ["星期一", "星期二"]}
    config["effective"]["checkin"] = {
        "enabled": True,
        "per_day": {"male": 1, "female": 1},
        "per_teacher_max_times": 1,
        "require_teacher_has_class_that_day": True,
    }

    readiness = build_readiness_payload(
        mode="joint",
        config_payload=config,
        teacher_rows=[{"班级": "1班", "班主任": "教师D", "班主任性别": "男", "语文": "教师A"}],
        day_rule_tables={
            "time_grid": [{"时段节次": "上午1", "星期一": 1}],
            "subject_hours": [{"学科": "语文", "周中课时": 5}],
        },
        academic_payload=_academic_payload(),
        conflict_payload=_conflict_payload(),
    )

    assert readiness["summary"]["can_start_solver"] is True
    item = next(item for item in readiness["items"] if item["title"] == "未提供完整查寝候选字段（可选）")
    assert item["severity"] == "info"
    assert item["blocking"] is False


def test_readiness_blocks_conflicting_checkin_extra_head_gender(tmp_path: Path) -> None:
    config = _config_payload(tmp_path)
    config["effective"]["calendar"] = {"days": ["星期一"]}
    config["effective"]["checkin"] = {
        "enabled": True,
        "per_day": {"male": 1, "female": 1},
        "per_teacher_max_times": 1,
        "extra_heads": [{"name": "教师D", "gender": "女"}],
    }

    readiness = build_readiness_payload(
        mode="joint",
        config_payload=config,
        teacher_rows=[
            {"班级": "1班", "班主任": "教师D", "班主任性别": "男", "语文": "教师A"},
            {"班级": "2班", "班主任": "钱老师", "班主任性别": "女", "语文": "教师B"},
        ],
        day_rule_tables={
            "time_grid": [{"时段节次": "上午1", "星期一": 1}],
            "subject_hours": [{"学科": "语文", "周中课时": 5}],
        },
        academic_payload=_academic_payload(),
        conflict_payload=_conflict_payload(),
    )

    assert readiness["summary"]["can_start_solver"] is False
    item = next(item for item in readiness["items"] if item["title"] == "额外晚查寝候选性别冲突")
    assert item["blocking"] is True
    assert item["publish_blocking"] is True
    assert "教师D: 教师定位表=男, extra_heads=女" in item["detail"]
    assert item["remediation_options"][0]["id"] == "checkin.extra_heads_review"


def test_readiness_warns_about_checkin_extra_head_quality_issues(tmp_path: Path) -> None:
    config = _config_payload(tmp_path)
    config["effective"]["calendar"] = {"days": ["星期一"]}
    config["effective"]["checkin"] = {
        "enabled": True,
        "per_day": {"male": 1, "female": 1},
        "per_teacher_max_times": 1,
        "exclude_heads": ["教师E"],
        "extra_heads": [
            {"name": "教师B", "gender": ""},
            {"name": "教师C", "gender": "男"},
            {"name": "教师C", "gender": "男"},
            {"name": "教师E", "gender": "女"},
        ],
    }

    readiness = build_readiness_payload(
        mode="joint",
        config_payload=config,
        teacher_rows=[
            {"班级": "1班", "班主任": "教师C", "班主任性别": "男", "语文": "教师A"},
            {"班级": "2班", "班主任": "钱老师", "班主任性别": "女", "语文": "教师B"},
        ],
        day_rule_tables={
            "time_grid": [{"时段节次": "上午1", "星期一": 1}],
            "subject_hours": [{"学科": "语文", "周中课时": 5}],
        },
        academic_payload=_academic_payload(),
        conflict_payload=_conflict_payload(),
    )

    assert readiness["summary"]["can_start_solver"] is True
    item = next(item for item in readiness["items"] if item["title"] == "额外晚查寝候选需复核")
    assert item["severity"] == "warning"
    assert "缺少性别：教师B" in item["detail"]
    assert "重复配置：教师C(男)×2" in item["detail"]
    assert "已是班主任候选：教师C(男)" in item["detail"]
    assert "同时在排除名单：教师E" in item["detail"]
    assert item["remediation_options"][0]["quick_actions"][0]["rule_id"] == "duty.night_checkin.extra_heads"


def test_readiness_blocks_hard_male_noon_night_total_target_conflict(tmp_path: Path) -> None:
    config = _config_payload(tmp_path)
    config["effective"]["calendar"] = {"days": ["星期一", "星期二", "星期三", "星期四", "星期五", "星期日"]}
    config["effective"]["checkin"] = {
        "enabled": True,
        "per_day": {"male": 1, "female": 0},
        "per_teacher_max_times": 2,
    }
    config["effective"]["day"] = {
        "noon_dorm_duty": {"enabled": True},
        "duty_joint_constraints": {
            "enabled": True,
            "male_total_target": 2,
            "male_total_target_mode": "hard",
            "male_total_eq2_exclude_teachers": [],
        },
    }
    teacher_rows = [
        {"班级": f"{index}班", "班主任": name, "班主任性别": "男", "语文": f"语文{name}"}
        for index, name in enumerate(["严昆", "张锋剑", "徐延兴", "李政", "肖祥宠"], start=1)
    ]
    day_rule_tables = {
        "time_grid": [
            {
                "时段节次": "上午1",
                "星期一": 1,
                "星期二": 1,
                "星期三": 1,
                "星期四": 1,
                "星期五": 1,
                "星期六": 1,
                "星期日": 1,
            }
        ],
        "subject_hours": [{"学科": "语文", "周中课时": 5}],
    }

    readiness = build_readiness_payload(
        mode="joint",
        config_payload=config,
        teacher_rows=teacher_rows,
        day_rule_tables=day_rule_tables,
        academic_payload=_academic_payload(),
        conflict_payload=_conflict_payload(),
    )

    assert readiness["summary"]["can_start_solver"] is False
    item = next(item for item in readiness["items"] if item["title"] == "男班主任午查+晚查硬目标不可满足")
    assert item["blocking"] is True
    assert "合计需求 12 次" in item["detail"]
    assert any(option["id"] == "duty_joint.male_total_target_soft" for option in item["remediation_options"])


def test_readiness_warns_when_male_noon_night_total_target_is_soft(tmp_path: Path) -> None:
    config = _config_payload(tmp_path)
    config["effective"]["calendar"] = {"days": ["星期一", "星期二", "星期三", "星期四", "星期五", "星期日"]}
    config["effective"]["checkin"] = {
        "enabled": True,
        "per_day": {"male": 1, "female": 0},
        "per_teacher_max_times": 2,
    }
    config["effective"]["day"] = {
        "noon_dorm_duty": {"enabled": True},
        "duty_joint_constraints": {
            "enabled": True,
            "male_total_target": 2,
            "male_total_target_mode": "soft",
        },
    }
    teacher_rows = [
        {"班级": f"{index}班", "班主任": name, "班主任性别": "男", "语文": f"语文{name}"}
        for index, name in enumerate(["严昆", "张锋剑", "徐延兴", "李政", "肖祥宠"], start=1)
    ]
    day_rule_tables = {
        "time_grid": [
            {
                "时段节次": "上午1",
                "星期一": 1,
                "星期二": 1,
                "星期三": 1,
                "星期四": 1,
                "星期五": 1,
                "星期六": 1,
                "星期日": 1,
            }
        ],
        "subject_hours": [{"学科": "语文", "周中课时": 5}],
    }

    readiness = build_readiness_payload(
        mode="joint",
        config_payload=config,
        teacher_rows=teacher_rows,
        day_rule_tables=day_rule_tables,
        academic_payload=_academic_payload(),
        conflict_payload=_conflict_payload(),
    )

    assert readiness["summary"]["can_start_solver"] is True
    item = next(item for item in readiness["items"] if item["title"] == "男班主任查寝目标需软化承接")
    assert item["severity"] == "warning"
    assert "目标容量 10 次" in item["detail"]


def test_readiness_preview_shows_remediation_effect_without_persisting(tmp_path: Path, monkeypatch) -> None:
    io_path = tmp_path / "io.yaml"
    rules_path = tmp_path / "rules.yaml"
    web_path = tmp_path / "web_overrides.yaml"
    monkeypatch.setattr(config_service, "IO_PATH", io_path)
    monkeypatch.setattr(config_service, "RULES_PATH", rules_path)
    monkeypatch.setattr(config_service, "WEB_OVERRIDES_PATH", web_path)
    io_path.write_text(
        yaml.safe_dump(
            {
                "teacher_table": {
                    "path": "missing.xlsx",
                    "columns": {"class": "班级", "head": "班主任", "head_gender": "班主任性别"},
                },
                "day": {"rules_path": "missing_day_rules.xlsx"},
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    rules_path.write_text(
        yaml.safe_dump(
            {
                "calendar": {"days": ["星期一", "星期二"]},
                "evening": {"subjects": ["语文"]},
                "checkin": {
                    "enabled": True,
                    "per_day": {"male": 1, "female": 0},
                    "per_teacher_max_times": 1,
                },
                "day": {"head_duty_constraints": {"enabled": False}, "weekday_constraints": {"enable_head_pm1_min": False}},
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    web_path.write_text(
        yaml.safe_dump(
            {
                "io": {
                    "web_tables": {
                        "teacher_subjects": [{"班级": "1班", "班主任": "教师D", "班主任性别": "男", "语文": "教师A"}],
                        "day_rules": {
                            "time_grid": [{"时段节次": "上午1", "星期一": 1}],
                            "subject_hours": [{"学科": "语文", "周中课时": 1}],
                        },
                    }
                }
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )

    preview = build_solve_readiness_preview(
        "joint",
        [{"store": "rules", "path": "checkin.per_teacher_max_times", "type": "int", "value": "2"}],
    )

    assert preview["preview"]["persisted"] is False
    assert preview["preview"]["changed_count"] == 1
    assert preview["summary"]["can_start_solver"] is True
    assert not any(item["title"] == "晚查寝候选人数不足" for item in preview["items"])
    assert config_service.load_web_overrides()["rules"] == {}


def test_readiness_warns_when_head_duty_and_checkin_hard_chain_are_tight(tmp_path: Path) -> None:
    config = _config_payload(tmp_path)
    config["effective"]["calendar"] = {"days": ["星期一", "星期二", "星期三", "星期四", "星期五", "星期日"]}
    config["effective"]["checkin"] = {
        "enabled": True,
        "per_day": {"male": 1, "female": 1},
        "per_teacher_max_times": 1,
        "require_teacher_has_class_that_day": True,
    }
    config["effective"]["day"] = {
        "head_duty_constraints": {
            "enable_head_duty": True,
            "enable_weekday_pm1_requires_duty": True,
            "weekday_pm1_requires_duty_mode": "hard",
        }
    }
    rows = [
        {
            "班级": f"{idx}班",
            "班主任": f"班主任{idx}",
            "班主任性别": "男" if idx % 2 else "女",
            "语文": f"语文{idx}",
        }
        for idx in range(1, 18)
    ]

    readiness = build_readiness_payload(
        mode="joint",
        config_payload=config,
        teacher_rows=rows,
        day_rule_tables={
            "days": [{"day": day} for day in ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]],
            "time_grid": [{"时段节次": "上午1", "星期一": 1}],
            "subject_hours": [{"学科": "语文", "周中课时": 5}],
        },
        academic_payload=_academic_payload(),
        conflict_payload=_conflict_payload(),
    )

    assert readiness["summary"]["can_start_solver"] is True
    item = next(item for item in readiness["items"] if item["title"] == "班主任值班与晚查寝硬联动过紧")
    assert item["severity"] == "warning"
    option = next(option for option in item["remediation_options"] if option["id"] == "head_duty.pm1_requires_duty_soft")
    assert option["fields"][0]["path"] == "day.head_duty_constraints.weekday_pm1_requires_duty_mode"
    assert option["fields"][0]["store"] == "io"
    checkin_option = next(
        option for option in item["remediation_options"] if option["id"] == "checkin.same_day_class_soft"
    )
    assert checkin_option["fields"][0]["path"] == "checkin.require_teacher_has_class_that_day_mode"
    assert checkin_option["fields"][0]["store"] == "rules"
    assert checkin_option["fields"][0]["value"] == "soft"
    assert any(option["id"] == "checkin.same_day_class_off" for option in item["remediation_options"])
    assert option["fields"][0]["value"] == "soft"


def test_latest_matching_infeasible_item_blocks_repeating_same_config(tmp_path: Path) -> None:
    web_runs = tmp_path / "web_runs"
    run_dir = web_runs / "run_20260506_074204"
    run_dir.mkdir(parents=True)
    (run_dir / "status.json").write_text(
        json.dumps(
            {
                "status": "completed",
                "mode": "night",
                "run_id": "run_20260506_074204",
                "completed_at": "2026-05-06 07:42:06",
                "config_fingerprint": {"hash": "abc123"},
                "solver_status": "INFEASIBLE",
                "solution_count": 0,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    item = latest_matching_infeasible_item("night", {"hash": "abc123"}, web_run_root=web_runs)

    assert item is not None
    assert item["title"] == "当前配置已被证明无解"
    assert item["severity"] == "error"
    assert item["blocking"] is True
    assert item["publish_blocking"] is True
    assert "run_20260506_074204" in item["detail"]
    assert "INFEASIBLE" in item["detail"]
    option_ids = {option["id"] for option in item["remediation_options"]}
    assert {"checkin.same_day_class_soft", "checkin.same_day_class_off"} <= option_ids
    soft_option = next(option for option in item["remediation_options"] if option["id"] == "checkin.same_day_class_soft")
    assert soft_option["fields"][0]["path"] == "checkin.require_teacher_has_class_that_day_mode"
    assert soft_option["fields"][0]["value"] == "soft"
    assert soft_option["fields"][1]["path"] == "checkin.w_require_teacher_has_class_that_day"
    assert soft_option["quick_actions"][0]["action"] == "activate_view"
    assert soft_option["quick_actions"][0]["view"] == "results"
    assert soft_option["decision_points"]
    assert soft_option["checklist"]
    off_option = next(option for option in item["remediation_options"] if option["id"] == "checkin.same_day_class_off")
    assert off_option["fields"][0]["value"] == "off"
    assert off_option["decision_points"]


def test_latest_matching_infeasible_item_ignores_diagnostic_or_stale_runs(tmp_path: Path) -> None:
    web_runs = tmp_path / "web_runs"
    diagnostic = web_runs / "run_20260506_073016"
    diagnostic.mkdir(parents=True)
    (diagnostic / "status.json").write_text(
        json.dumps(
            {
                "status": "completed",
                "mode": "night",
                "run_purpose": "diagnostic_trial",
                "config_fingerprint": {"hash": "abc123"},
                "solver_status": "INFEASIBLE",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    assert latest_matching_infeasible_item("night", {"hash": "abc123"}, web_run_root=web_runs) is None

    official = web_runs / "run_20260506_074204"
    official.mkdir()
    (official / "status.json").write_text(
        json.dumps(
            {
                "status": "completed",
                "mode": "night",
                "config_fingerprint": {"hash": "old456"},
                "solver_status": "INFEASIBLE",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    assert latest_matching_infeasible_item("night", {"hash": "abc123"}, web_run_root=web_runs) is None


def test_runtime_history_item_updates_readiness_summary(monkeypatch) -> None:
    item = {
        "severity": "error",
        "domain": "求解历史",
        "title": "当前配置已被证明无解",
        "detail": "同配置 INFEASIBLE。",
        "suggestion": "先排障。",
        "blocking": True,
        "publish_blocking": True,
        "evidence": [],
        "remediation_options": [],
    }
    readiness = {
        "summary": {"can_start_solver": True},
        "items": [
            {
                "severity": "ok",
                "domain": "配置文件",
                "title": "规则配置可读取",
                "detail": "",
                "suggestion": "",
                "blocking": False,
                "publish_blocking": False,
                "evidence": [],
                "remediation_options": [],
            }
        ],
    }
    monkeypatch.setattr(readiness_module, "build_effective_config_fingerprint", lambda mode: {"hash": "abc123"})
    monkeypatch.setattr(readiness_module, "latest_matching_infeasible_item", lambda mode, fingerprint: item)

    updated = readiness_module._with_runtime_history_items(readiness, "night")

    assert updated["summary"]["can_start_solver"] is False
    assert updated["summary"]["blocking_errors"] == 1
    assert updated["stages"][-1]["domain"] == "求解历史"
    assert updated["next_actions"][0]["title"] == "当前配置已被证明无解"
def test_readiness_marks_head_teacher_optional_when_weekday_head_rule_is_enabled(tmp_path: Path) -> None:
    config = _config_payload(tmp_path)
    config["effective"]["day"] = {
        "weekday_constraints": {"enable_head_pm1_min": True},
        "head_duty_constraints": {"enabled": False},
    }

    readiness = build_readiness_payload(
        mode="joint",
        config_payload=config,
        teacher_rows=[{"班级": "自定义1班", "语文": "教师A"}],
        day_rule_tables={
            "time_grid": [{"时段节次": "上午1", "星期一": 1}],
            "subject_hours": [{"学科": "语文", "周中课时": 5}],
        },
        academic_payload=_academic_payload(),
        conflict_payload=_conflict_payload(),
    )

    assert readiness["summary"]["can_start_solver"] is True
    assert any(item["title"] == "未提供班主任信息（可选）" and not item["blocking"] for item in readiness["items"])


def test_readiness_does_not_require_head_teacher_when_head_rules_are_disabled(tmp_path: Path) -> None:
    config = _config_payload(tmp_path)
    config["effective"]["day"] = {
        "weekday_constraints": {"enable_head_pm1_min": False},
        "head_duty_constraints": {"enabled": False},
    }

    readiness = build_readiness_payload(
        mode="joint",
        config_payload=config,
        teacher_rows=[{"班级": "自定义1班", "语文": "教师A"}],
        day_rule_tables={
            "time_grid": [{"时段节次": "上午1", "星期一": 1}],
            "subject_hours": [{"学科": "语文", "周中课时": 5}],
        },
        academic_payload=_academic_payload(),
        conflict_payload=_conflict_payload(),
    )

    assert readiness["summary"]["can_start_solver"] is True
    assert not any(item["title"] == "班主任名单为空" for item in readiness["items"])


def test_readiness_supports_uploaded_custom_subject_without_hardcoded_names(tmp_path: Path) -> None:
    config = _config_payload(tmp_path)
    config["effective"]["evening"] = {"subjects": ["机器人"]}
    config["effective"]["day"] = {
        "weekday_constraints": {"enable_head_pm1_min": False},
        "head_duty_constraints": {"enabled": False},
    }

    readiness = build_readiness_payload(
        mode="joint",
        config_payload=config,
        teacher_rows=[{"班级": "自定义1班", "机器人": "教师T"}],
        day_rule_tables={
            "time_grid": [{"时段节次": "上午1", "星期一": 1}],
            "subject_hours": [{"学科": "机器人", "周中课时": 5}],
        },
        academic_payload=_academic_payload(),
        conflict_payload=_conflict_payload(),
    )

    assert readiness["summary"]["can_start_solver"] is True
    coverage = readiness["metrics"]["teacher_data_quality"]["subject_coverage"]
    assert coverage == [
        {
            "subject": "机器人",
            "present": True,
            "filled": 1,
            "total": 1,
            "missing": 0,
            "coverage_pct": 100,
        }
    ]
