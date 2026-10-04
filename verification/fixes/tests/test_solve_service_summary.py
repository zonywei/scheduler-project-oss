from __future__ import annotations

import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


import pytest

from scheduler.app import config_service
import scheduler.app.solve_service as solve_service
from scheduler.app.solve_service import (
    _annotate_file_artifacts,
    _apply_result_message,
    _attach_config_freshness,
    _diagnostic_run_metadata,
    _payload_optional_bool,
    _payload_optional_float,
    _payload_random_seed,
    _payload_solver_profile,
)


def test_completed_infeasible_status_gets_clear_user_message() -> None:
    status = {
        "status": "completed",
        "message": "求解完成，结果文件已汇总",
        "publish_assessment": {
            "outcome": {"solver_status": "INFEASIBLE", "solution_count": 0},
            "file_categories": {"schedule": 0},
        },
    }

    _apply_result_message(status)

    assert status["solver_status"] == "INFEASIBLE"
    assert status["solution_count"] == 0
    assert status["schedule_file_count"] == 0
    assert status["message"] == "求解器判定当前规则组合不可行，未生成可交付课表文件。"


def test_completed_zero_solution_status_does_not_claim_export_success() -> None:
    status = {
        "status": "completed",
        "message": "求解完成，结果文件已汇总",
        "publish_assessment": {
            "outcome": {"solver_status": "", "solution_count": 0},
            "file_categories": {"schedule": 0},
        },
    }

    _apply_result_message(status)

    assert status["message"] == "求解已结束，但未捕获可行解，未生成可交付课表文件。"


def test_diagnostic_trial_status_does_not_claim_deliverable_schedule() -> None:
    status = {
        "status": "completed",
        "run_purpose": "diagnostic_trial",
        "message": "求解完成，结果文件已汇总",
        "publish_assessment": {
            "outcome": {"solver_status": "FEASIBLE", "solution_count": 1},
            "file_categories": {"schedule": 3},
        },
    }

    _apply_result_message(status)

    assert status["schedule_file_count"] == 3
    assert status["message"] == "诊断试跑已生成候选课表，但包含临时放宽规则，不能直接作为交付版本。"


def test_legacy_review_status_is_normalized_to_ready() -> None:
    status = {
        "status": "completed",
        "message": "求解完成，结果文件已汇总",
        "publish_assessment": {
            "summary": {"status": "review", "status_label": "旧版复核状态", "can_publish": True},
            "outcome": {"solver_status": "FEASIBLE", "solution_count": 1},
            "file_categories": {"schedule": 41},
        },
    }

    _apply_result_message(status)

    assert status["message"] == "求解完成，已发现可交付课表文件。"
    assert status["release_state"]["status"] == "ready"
    assert status["release_state"]["package_label"] == "正式结果包"
    assert status["release_state"]["formal_release_ready"] is True
    assert status["release_state"]["can_publish_candidate"] is True


def test_blocked_status_does_not_claim_deliverable_schedule() -> None:
    status = {
        "status": "completed",
        "message": "求解完成，结果文件已汇总",
        "publish_assessment": {
            "summary": {"status": "blocked"},
            "outcome": {"solver_status": "FEASIBLE", "solution_count": 1},
            "file_categories": {"schedule": 2},
        },
    }

    _apply_result_message(status)

    assert status["message"] == "求解完成，但发布校验未通过；课表文件仅供排障参考，不能直接交付。"


def test_ready_status_labels_schedule_as_formal_delivery() -> None:
    status = {
        "status": "completed",
        "message": "求解完成，结果文件已汇总",
        "publish_assessment": {
            "summary": {"status": "ready"},
            "outcome": {"solver_status": "FEASIBLE", "solution_count": 1},
            "file_categories": {"schedule": 3},
        },
    }

    _apply_result_message(status)

    assert status["message"] == "求解完成，已发现可交付课表文件。"
    assert status["release_state"]["status"] == "ready"
    assert status["release_state"]["package_kind"] == "formal"
    assert status["release_state"]["formal_release_ready"] is True
    assert status["release_state"]["next_action"] == "可下载正式结果包，并按学校现有 OA 或线下流程归档。"


def test_diagnostic_trial_metadata_requires_plan_id(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config_service, "WEB_OVERRIDES_PATH", tmp_path / "web_overrides.yaml")
    config_service.save_web_overrides({"io": {}, "rules": {}, "temporary_rules": {"active": []}})

    assert _diagnostic_run_metadata({}) == {}

    with pytest.raises(ValueError):
        _diagnostic_run_metadata({"diagnostic_trial": True})

    metadata = _diagnostic_run_metadata(
        {
            "diagnostic_trial": True,
            "diagnostic_plan_id": "relax.day_night_link",
            "diagnostic_plan_title": "先放宽白天-晚自习联动",
        }
    )

    assert metadata == {
        "run_purpose": "diagnostic_trial",
        "diagnostic_plan_id": "relax.day_night_link",
        "diagnostic_plan_title": "先放宽白天-晚自习联动",
    }


def test_diagnostic_run_metadata_auto_marks_active_relaxation_as_diagnostic(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config_service, "WEB_OVERRIDES_PATH", tmp_path / "web_overrides.yaml")
    config_service.save_web_overrides(
        {
            "io": {"day_night_link": {"night_requires_day_mode": "soft"}},
            "rules": {},
            "temporary_rules": {
                "active": [
                    {
                        "id": "relax.day_night_link",
                        "kind": "diagnostic_relaxation",
                        "status": "active",
                        "description": "先放宽白天-晚自习联动",
                        "domain": "联动规则",
                        "risk": "只用于排障。",
                        "patches": [
                            {
                                "target": "io",
                                "operation": "set",
                                "path": ["day_night_link", "night_requires_day_mode"],
                                "path_label": "day_night_link.night_requires_day_mode",
                            }
                        ],
                    },
                    {
                        "id": "tmp.nl.demo",
                        "kind": "manual_rule",
                        "status": "active",
                    },
                ]
            },
        }
    )

    metadata = _diagnostic_run_metadata({})

    assert metadata["run_purpose"] == "diagnostic_trial"
    assert metadata["diagnostic_plan_id"] == "relax.day_night_link"
    assert metadata["diagnostic_plan_title"] == "已应用临时放宽方案：先放宽白天-晚自习联动"
    relaxation = metadata["active_diagnostic_relaxations"][0]
    assert relaxation["domain"] == "联动规则"
    assert relaxation["patch_count"] == 1
    assert relaxation["patches"][0]["path_label"] == "day_night_link.night_requires_day_mode"


def test_payload_random_seed_accepts_blank_or_non_negative_values() -> None:
    assert _payload_random_seed({}) is None
    assert _payload_random_seed({"random_seed": ""}) is None
    assert _payload_random_seed({"random_seed": "7"}) == 7
    assert _payload_random_seed({"seed": 8}) == 8

    with pytest.raises(ValueError):
        _payload_random_seed({"random_seed": -1})


def test_payload_optional_solver_quality_controls_parse_values() -> None:
    assert _payload_optional_float({}, "relative_gap_limit") is None
    assert _payload_optional_float({"relative_gap_limit": ""}, "relative_gap_limit") is None
    assert _payload_optional_float({"relative_gap_limit": "0.05"}, "relative_gap_limit") == 0.05
    assert _payload_optional_bool({}, "log_search_progress") is None
    assert _payload_optional_bool({"log_search_progress": "true"}, "log_search_progress") is True
    assert _payload_optional_bool({"log_search_progress": "false"}, "log_search_progress") is False

    with pytest.raises(ValueError):
        _payload_optional_float({"relative_gap_limit": -0.1}, "relative_gap_limit")
    with pytest.raises(ValueError):
        _payload_optional_bool({"log_search_progress": "maybe"}, "log_search_progress")


def test_payload_solver_profile_defaults_continue_runs_to_incumbent_profile() -> None:
    assert _payload_solver_profile({}, continue_from_best=False) == ""
    assert _payload_solver_profile({}, continue_from_best=True) == "improve_incumbent"
    assert _payload_solver_profile({"solver_profile": "prove"}, continue_from_best=True) == "prove_bound"

    with pytest.raises(ValueError):
        _payload_solver_profile({"solver_profile": "unknown"}, continue_from_best=False)


def test_start_solve_passes_random_seed_to_runner_and_status(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}

    class FakeProcess:
        returncode = None

        def poll(self) -> None:
            return None

    def fake_popen(command, **kwargs):
        captured["command"] = list(command)
        captured["kwargs"] = kwargs
        return FakeProcess()

    monkeypatch.setattr(solve_service, "WEB_RUN_ROOT", tmp_path)
    monkeypatch.setattr(config_service, "WEB_OVERRIDES_PATH", tmp_path / "web_overrides.yaml")
    config_service.save_web_overrides({"io": {}, "rules": {}, "temporary_rules": {"active": []}})
    monkeypatch.setattr(solve_service, "_current_process", None)
    monkeypatch.setattr(solve_service, "_current_run_dir", None)
    monkeypatch.setattr(solve_service, "_current_started_ts", None)
    monkeypatch.setattr(solve_service.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(
        solve_service,
        "build_solve_readiness",
        lambda mode: {"summary": {"can_start_solver": True}, "items": []},
    )
    monkeypatch.setattr(
        solve_service,
        "build_effective_config_fingerprint",
        lambda mode: {"mode": mode, "hash": "abc123", "generated_at": "now"},
    )
    monkeypatch.setattr(
        solve_service,
        "get_solve_status",
        lambda: solve_service._read_status(solve_service._current_run_dir),
    )

    status = solve_service.start_solve(
        {
            "mode": "night",
            "time_limit_seconds": 10,
            "workers": 2,
            "max_keep": 3,
            "snapshot_interval_sec": 5,
            "random_seed": 123,
            "relative_gap_limit": 0.02,
            "absolute_gap_limit": 5,
            "log_search_progress": True,
        }
    )

    command = captured["command"]
    assert "--seed" in command
    assert command[command.index("--seed") + 1] == "123"
    assert "--relative-gap-limit" in command
    assert command[command.index("--relative-gap-limit") + 1] == "0.02"
    assert "--absolute-gap-limit" in command
    assert command[command.index("--absolute-gap-limit") + 1] == "5.0"
    assert "--log-search-progress" in command
    assert "--solver-profile" not in command
    assert status["random_seed"] == 123
    assert status["relative_gap_limit"] == 0.02
    assert status["absolute_gap_limit"] == 5.0
    assert status["log_search_progress"] is True
    assert status["continue_from_best"] is False
    assert status["solver_profile"] == ""
    assert status["max_keep"] == 3
    assert status["snapshot_interval_sec"] == 5
    assert status["enable_snapshots"] is False
    assert status["grade_prefix"] == "高二"
    assert status["status"] == "running"


def test_start_solve_continue_from_best_uses_incumbent_solver_profile(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}

    class FakeProcess:
        returncode = None

        def poll(self) -> None:
            return None

    def fake_popen(command, **kwargs):
        captured["command"] = list(command)
        captured["kwargs"] = kwargs
        return FakeProcess()

    monkeypatch.setattr(solve_service, "WEB_RUN_ROOT", tmp_path)
    monkeypatch.setattr(config_service, "WEB_OVERRIDES_PATH", tmp_path / "web_overrides.yaml")
    config_service.save_web_overrides({"io": {}, "rules": {}, "temporary_rules": {"active": []}})
    monkeypatch.setattr(solve_service, "_current_process", None)
    monkeypatch.setattr(solve_service, "_current_run_dir", None)
    monkeypatch.setattr(solve_service, "_current_started_ts", None)
    monkeypatch.setattr(solve_service.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(
        solve_service,
        "build_solve_readiness",
        lambda mode: {"summary": {"can_start_solver": True}, "items": []},
    )
    monkeypatch.setattr(
        solve_service,
        "build_effective_config_fingerprint",
        lambda mode: {"mode": mode, "hash": "abc123", "generated_at": "now"},
    )
    monkeypatch.setattr(
        solve_service,
        "get_solve_status",
        lambda: solve_service._read_status(solve_service._current_run_dir),
    )

    status = solve_service.start_solve(
        {
            "mode": "joint",
            "time_limit_seconds": 10,
            "continue_from_best": True,
        }
    )

    command = captured["command"]
    assert "--solver-profile" in command
    assert command[command.index("--solver-profile") + 1] == "improve_incumbent"
    assert status["continue_from_best"] is True
    assert status["solver_profile"] == "improve_incumbent"


def test_start_solve_passes_active_relaxation_evidence_to_runner(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}

    class FakeProcess:
        returncode = None

        def poll(self) -> None:
            return None

    def fake_popen(command, **kwargs):
        captured["command"] = list(command)
        captured["kwargs"] = kwargs
        return FakeProcess()

    monkeypatch.setattr(solve_service, "WEB_RUN_ROOT", tmp_path / "runs")
    monkeypatch.setattr(config_service, "WEB_OVERRIDES_PATH", tmp_path / "web_overrides.yaml")
    config_service.save_web_overrides(
        {
            "io": {},
            "rules": {},
            "temporary_rules": {
                "active": [
                    {
                        "id": "relax.day_night_link",
                        "kind": "diagnostic_relaxation",
                        "status": "active",
                        "description": "先放宽白天-晚自习联动",
                        "patches": [{"target": "io", "path_label": "day_night_link.night_requires_day_mode"}],
                    }
                ]
            },
        }
    )
    monkeypatch.setattr(solve_service, "_current_process", None)
    monkeypatch.setattr(solve_service, "_current_run_dir", None)
    monkeypatch.setattr(solve_service, "_current_started_ts", None)
    monkeypatch.setattr(solve_service.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(
        solve_service,
        "build_solve_readiness",
        lambda mode: {"summary": {"can_start_solver": True}, "items": []},
    )
    monkeypatch.setattr(
        solve_service,
        "build_effective_config_fingerprint",
        lambda mode: {"mode": mode, "hash": "abc123", "generated_at": "now"},
    )
    monkeypatch.setattr(
        solve_service,
        "get_solve_status",
        lambda: solve_service._read_status(solve_service._current_run_dir),
    )

    status = solve_service.start_solve({"mode": "joint", "time_limit_seconds": 10})

    command = captured["command"]
    assert command[command.index("--run-purpose") + 1] == "diagnostic_trial"
    assert command[command.index("--diagnostic-plan-id") + 1] == "relax.day_night_link"
    assert "--active-diagnostic-relaxations-json" in command
    payload = json.loads(command[command.index("--active-diagnostic-relaxations-json") + 1])
    assert payload[0]["patches"][0]["path_label"] == "day_night_link.night_requires_day_mode"
    assert command[command.index("--max-keep") + 1] == "3"
    assert status["run_purpose"] == "diagnostic_trial"
    assert status["max_keep"] == 3
    assert status["requested_max_keep"] == 10
    assert status["max_keep_capped"] is True
    assert status["active_diagnostic_relaxations"][0]["id"] == "relax.day_night_link"


def test_file_artifact_annotations_expose_release_semantics(tmp_path: Path) -> None:
    run_dir = tmp_path / "run_20260506_190000"
    schedule = run_dir / "solutions" / "best" / "最终全局最优解_正式版.xlsx"
    report = run_dir / "diagnostics" / "多解诊断报告.xlsx"
    schedule.parent.mkdir(parents=True)
    report.parent.mkdir(parents=True)
    schedule.write_text("schedule", encoding="utf-8")
    report.write_text("report", encoding="utf-8")
    status = {
        "run_dir": str(run_dir),
        "run_purpose": "diagnostic_trial",
        "publish_assessment": {"summary": {"status": "blocked"}},
        "files": [
            {"label": "outputs/最终全局最优解_正式版.xlsx", "path": str(schedule), "size": 8, "modified_at": ""},
            {"label": "outputs/diagnostics/多解诊断报告.xlsx", "path": str(report), "size": 6, "modified_at": ""},
        ],
    }

    _annotate_file_artifacts(status)

    schedule_item = status["files"][0]
    report_item = status["files"][1]
    assert schedule_item["category"] == "schedule"
    assert schedule_item["release_use"] == "troubleshooting_reference"
    assert schedule_item["release_badge"] == "排障参考"
    assert schedule_item["display_label"] == "候选课表_排障参考_最终全局最优解.xlsx"
    assert schedule_item["download_name"] == "候选课表_排障参考_最终全局最优解.xlsx"
    assert report_item["category"] == "diagnostic"
    assert report_item["release_use"] == "diagnostic_material"
    assert report_item["display_label"] == report_item["label"]
    availability = status["result_availability"]
    assert availability["label"] == "已生成排障参考课表"
    assert availability["has_schedule_files"] is True
    assert availability["schedule_file_count"] == 1
    assert availability["diagnostic_file_count"] == 1
    assert availability["primary_schedule_files"][0]["display_label"] == "候选课表_排障参考_最终全局最优解.xlsx"


def test_rule_execution_plan_artifact_is_labeled_as_audit_evidence(tmp_path: Path) -> None:
    run_dir = tmp_path / "run_20260506_191500"
    plan = run_dir / "_run_meta" / "rule_execution_plan.json"
    plan.parent.mkdir(parents=True)
    plan.write_text('{"source":"runtime_snapshot"}', encoding="utf-8")
    status = {
        "run_dir": str(run_dir),
        "status": "completed",
        "files": [
            {
                "label": "outputs/web_runs/run_20260506_191500/_run_meta/rule_execution_plan.json",
                "path": str(plan),
                "size": plan.stat().st_size,
                "modified_at": "",
            }
        ],
    }

    _annotate_file_artifacts(status)

    item = status["files"][0]
    assert item["category"] == "diagnostic"
    assert item["release_use"] == "runtime_audit_evidence"
    assert item["display_label"] == "规则执行计划与trace审计.json"
    assert item["download_name"] == "规则执行计划与trace审计.json"
    assert status["result_availability"]["diagnostic_file_count"] == 1


def test_result_availability_prioritizes_primary_schedule_files(tmp_path: Path) -> None:
    run_dir = tmp_path / "run_20260506_200000"
    best = run_dir / "solutions" / "run_x" / "best" / "最终全局最优解_正式版.xlsx"
    top = run_dir / "solutions" / "run_x" / "top50_excels" / "白天课表_汇总版_top01.xlsx"
    package = run_dir / "result_package.zip"
    best.parent.mkdir(parents=True)
    top.parent.mkdir(parents=True)
    best.write_text("best", encoding="utf-8")
    top.write_text("top", encoding="utf-8")
    package.write_text("zip", encoding="utf-8")
    status = {
        "run_dir": str(run_dir),
        "status": "completed",
        "package_file": str(package),
        "publish_assessment": {"summary": {"status": "ready"}},
        "release_state": {"status": "ready", "package_label": "正式结果包", "formal_release_ready": True},
        "files": [
            {"label": "outputs/top50_excels/白天课表_汇总版_top01.xlsx", "path": str(top), "size": 3, "modified_at": ""},
            {"label": "outputs/result_package.zip", "path": str(package), "size": 3, "modified_at": ""},
            {"label": "outputs/best/最终全局最优解_正式版.xlsx", "path": str(best), "size": 4, "modified_at": ""},
        ],
    }

    _annotate_file_artifacts(status)

    availability = status["result_availability"]
    assert availability["label"] == "已生成正式课表"
    assert availability["package_label"] == "正式结果包"
    assert availability["has_result_package"] is True
    assert availability["schedule_file_count"] == 2
    assert availability["primary_schedule_files"][0]["display_label"] == "outputs/best/最终全局最优解_正式版.xlsx"
    assert availability["primary_schedule_files"][1]["display_label"] == "outputs/top50_excels/白天课表_汇总版_top01.xlsx"


def test_result_availability_uses_recommended_formal_candidate_files(tmp_path: Path) -> None:
    latest_dir = tmp_path / "run_20260512_133712"
    candidate_dir = tmp_path / "run_20260512_090347"
    latest_schedule = latest_dir / "solutions" / "best" / "latest.xlsx"
    candidate_schedule = candidate_dir / "solutions" / "best" / "candidate.xlsx"
    candidate_package = candidate_dir / "result_package.zip"
    latest_schedule.parent.mkdir(parents=True)
    candidate_schedule.parent.mkdir(parents=True)
    latest_schedule.write_text("latest", encoding="utf-8")
    candidate_schedule.write_text("candidate", encoding="utf-8")
    candidate_package.write_text("zip", encoding="utf-8")
    candidate_status = {
        "run_id": candidate_dir.name,
        "run_dir": str(candidate_dir),
        "status": "completed",
        "package_file": str(candidate_package),
        "publish_assessment": {"summary": {"status": "ready"}},
        "release_state": {"status": "ready", "package_label": "正式结果包"},
        "files": [
            {
                "label": "outputs/best/candidate.xlsx",
                "path": str(candidate_schedule),
                "size": candidate_schedule.stat().st_size,
                "modified_at": "",
                "category": "schedule",
                "display_label": "candidate.xlsx",
                "download_name": "candidate.xlsx",
                "release_badge": "正式结果",
            },
            {
                "label": "outputs/result_package.zip",
                "path": str(candidate_package),
                "size": candidate_package.stat().st_size,
                "modified_at": "",
                "category": "package",
            },
        ],
    }
    candidate_status_path = candidate_dir / "status.json"
    candidate_status_path.write_text(json.dumps(candidate_status, ensure_ascii=False), encoding="utf-8")
    status = {
        "run_id": latest_dir.name,
        "run_dir": str(latest_dir),
        "status": "completed",
        "publish_assessment": {"summary": {"status": "ready"}},
        "release_state": {"status": "ready", "package_label": "正式结果包"},
        "recommended_formal_candidate": {
            "summary": {
                "selected_run_id": candidate_dir.name,
                "current_run_id": latest_dir.name,
            },
            "candidate": {
                "run_dir": str(candidate_dir),
                "status_file": str(candidate_status_path),
            },
        },
        "files": [
            {
                "label": "outputs/best/latest.xlsx",
                "path": str(latest_schedule),
                "size": latest_schedule.stat().st_size,
                "modified_at": "",
            }
        ],
    }

    _annotate_file_artifacts(status)
    solve_service._attach_recommended_formal_candidate_status(status)

    availability = status["result_availability"]
    assert availability["source_kind"] == "recommended_formal_candidate"
    assert availability["source_run_id"] == candidate_dir.name
    assert availability["latest_run_id"] == latest_dir.name
    assert availability["schedule_file_count"] == 1
    assert availability["has_result_package"] is True
    assert availability["primary_schedule_files"][0]["path"] == str(candidate_schedule)
    assert availability["primary_schedule_files"][0]["display_label"] == "candidate.xlsx"
    assert all(item["path"] != str(latest_schedule) for item in availability["primary_schedule_files"])
    snapshot = status["recommended_formal_candidate"]["status_snapshot"]
    assert snapshot["run_id"] == candidate_dir.name
    assert snapshot["package_file"] == str(candidate_package)
    assert snapshot["files"][0]["path"] == str(candidate_schedule)
    assert snapshot["release_state"]["package_label"] == "正式结果包"


def test_latest_run_dir_ignores_probe_directories(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    web_runs = tmp_path / "web_runs"
    web_runs.mkdir()
    official = web_runs / "run_20260506_034741"
    official.mkdir()
    (official / "status.json").write_text('{"status":"completed"}', encoding="utf-8")
    probe = web_runs / "constraint_probes_minimal"
    probe.mkdir()

    monkeypatch.setattr(solve_service, "WEB_RUN_ROOT", web_runs)
    monkeypatch.setattr(solve_service, "_current_run_dir", None)

    assert solve_service._latest_run_dir() == official


def test_latest_run_dir_prefers_formal_run_over_stopped_diagnostic(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    web_runs = tmp_path / "web_runs"
    web_runs.mkdir()
    formal = web_runs / "run_20260506_034741"
    diagnostic = web_runs / "run_20260506_044741"
    formal.mkdir()
    diagnostic.mkdir()
    (formal / "status.json").write_text(
        json.dumps({"run_id": formal.name, "status": "completed", "run_purpose": ""}),
        encoding="utf-8",
    )
    (diagnostic / "status.json").write_text(
        json.dumps({"run_id": diagnostic.name, "status": "stopped", "run_purpose": "diagnostic_trial"}),
        encoding="utf-8",
    )

    monkeypatch.setattr(solve_service, "WEB_RUN_ROOT", web_runs)
    monkeypatch.setattr(solve_service, "_current_run_dir", None)

    assert solve_service._latest_run_dir() == formal


def test_latest_run_dir_keeps_running_diagnostic(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    web_runs = tmp_path / "web_runs"
    web_runs.mkdir()
    formal = web_runs / "run_20260506_034741"
    diagnostic = web_runs / "run_20260506_044741"
    formal.mkdir()
    diagnostic.mkdir()
    (formal / "status.json").write_text(
        json.dumps({"run_id": formal.name, "status": "completed", "run_purpose": ""}),
        encoding="utf-8",
    )
    (diagnostic / "status.json").write_text(
        json.dumps({"run_id": diagnostic.name, "status": "running", "run_purpose": "diagnostic_trial"}),
        encoding="utf-8",
    )

    monkeypatch.setattr(solve_service, "WEB_RUN_ROOT", web_runs)
    monkeypatch.setattr(solve_service, "_current_run_dir", None)

    assert solve_service._latest_run_dir() == diagnostic


def test_attach_config_freshness_marks_matching_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        solve_service,
        "build_effective_config_fingerprint",
        lambda mode: {"mode": mode, "hash": "abc123", "generated_at": "now"},
    )
    status = {"config_fingerprint": {"hash": "abc123"}}

    _attach_config_freshness(status, "joint")

    assert status["config_fingerprint_match"] is True
    assert status["config_changed_after_run"] is False
    assert status["config_freshness"]["status"] == "matched"


def test_attach_config_freshness_marks_stale_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        solve_service,
        "build_effective_config_fingerprint",
        lambda mode: {"mode": mode, "hash": "new456", "generated_at": "now"},
    )
    status = {"config_fingerprint": {"hash": "old123"}}

    _attach_config_freshness(status, "joint")

    assert status["config_fingerprint_match"] is False
    assert status["config_changed_after_run"] is True
    assert status["config_freshness"]["status"] == "stale"


def test_get_solve_status_exposes_current_readiness_for_result_advice(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run_20260506_150000"
    run_dir.mkdir()
    (run_dir / "status.json").write_text(
        '{"status":"completed","mode":"joint","files":[],"config_fingerprint":{"hash":"abc123"}}',
        encoding="utf-8",
    )
    readiness = {
        "summary": {"can_publish": False, "errors": 1, "warnings": 0},
        "items": [
            {
                "severity": "error",
                "domain": "值班/查寝",
                "title": "晚查寝候选人数不足",
                "suggestion": "引入男晚查寝候选人。",
                "blocking": True,
                "remediation_options": [{"id": "checkin.add_gender_candidate", "title": "引入候选"}],
            }
        ],
    }

    monkeypatch.setattr(solve_service, "_current_process", None)
    monkeypatch.setattr(solve_service, "_current_started_ts", None)
    monkeypatch.setattr(solve_service, "_latest_run_dir", lambda: run_dir)
    monkeypatch.setattr(
        solve_service,
        "build_effective_config_fingerprint",
        lambda mode: {"mode": mode, "hash": "abc123", "generated_at": "now"},
    )
    monkeypatch.setattr(solve_service, "build_solve_readiness", lambda _mode: readiness)
    monkeypatch.setattr(solve_service, "build_solve_diagnostics", lambda _status: {"summary": {}})

    status = solve_service.get_solve_status()

    assert status["current_readiness"] == readiness
    assert any(gate["title"] == "发布校验未通过" for gate in status["publish_assessment"]["gates"])


def test_package_publish_context_recomputes_config_freshness_before_assessment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    status = {
        "mode": "joint",
        "config_fingerprint": {"mode": "joint", "hash": "abc123"},
        "config_fingerprint_match": False,
        "publish_assessment": {"summary": {"status": "blocked"}},
    }
    observed: dict[str, object] = {}

    def fake_publish_assessment(next_status: dict, _readiness: dict) -> dict:
        observed["match"] = next_status.get("config_fingerprint_match")
        return {"summary": {"status": "ready" if next_status.get("config_fingerprint_match") else "blocked"}}

    monkeypatch.setattr(
        solve_service,
        "build_effective_config_fingerprint",
        lambda _mode: {"mode": "joint", "hash": "abc123"},
    )
    monkeypatch.setattr(solve_service, "build_solve_readiness", lambda _mode: {"summary": {"can_publish": True}})
    monkeypatch.setattr(solve_service, "build_publish_assessment", fake_publish_assessment)
    monkeypatch.setattr(solve_service, "build_formal_run_comparison", lambda _status, _root: {})
    monkeypatch.setattr(solve_service, "build_recommended_formal_candidate", lambda _status, _root: {})
    monkeypatch.setattr(solve_service, "build_solve_diagnostics", lambda _status: {})
    monkeypatch.setattr(solve_service, "attach_result_availability", lambda _status: None)
    monkeypatch.setattr(solve_service, "_apply_result_message", lambda _status: None)
    monkeypatch.setattr(solve_service, "_annotate_file_artifacts", lambda _status: None)

    solve_service._refresh_status_publish_context(status)

    assert observed["match"] is True
    assert status["config_fingerprint_match"] is True
    assert status["publish_assessment"]["summary"]["status"] == "ready"


def test_package_status_snapshot_reads_requested_run_status(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run_history"
    run_dir.mkdir()
    (run_dir / "status.json").write_text(
        json.dumps({"run_id": "run_history", "objective_value": 10}),
        encoding="utf-8",
    )

    monkeypatch.setattr(solve_service, "get_solve_status", lambda: {"run_id": "run_latest", "objective_value": 99})
    monkeypatch.setattr(solve_service, "_refresh_status_publish_context", lambda _status: None)

    status = solve_service._package_status_snapshot(run_dir, [], run_dir / "result_package.zip")

    assert status["run_id"] == "run_history"
    assert status["objective_value"] == 10
    assert status["package_file"] == str(run_dir / "result_package.zip")
