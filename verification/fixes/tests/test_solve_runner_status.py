from __future__ import annotations

import json
import os
import sys
import zipfile
from pathlib import Path
from types import SimpleNamespace


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


from scheduler.app import solve_runner
from scheduler.app.delivery_manifest import MANIFEST_FILENAME


def _artifact(path: Path, base: Path) -> dict:
    return solve_runner._file_item(path, base)


def test_collect_artifacts_skips_files_that_disappear_during_scan(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(solve_runner, "PROJECT_ROOT", tmp_path)
    run_dir = tmp_path / "outputs" / "web_runs" / "run_20260506_080000"
    run_dir.mkdir(parents=True)
    keep = run_dir / "run.log"
    transient = run_dir / "meta_0001.json"
    keep.write_text("ok", encoding="utf-8")
    transient.write_text("moving", encoding="utf-8")

    original_file_item = solve_runner._file_item

    def flaky_file_item(path: Path, base: Path) -> dict:
        if path == transient:
            raise FileNotFoundError(str(path))
        return original_file_item(path, base)

    monkeypatch.setattr(solve_runner, "_file_item", flaky_file_item)

    artifacts = solve_runner.collect_artifacts(run_dir, started_at_ts=0)

    labels = {str(item["label"]).replace("\\", "/") for item in artifacts}
    assert "outputs/web_runs/run_20260506_080000/run.log" in labels
    assert "outputs/web_runs/run_20260506_080000/meta_0001.json" not in labels


def test_completion_status_updates_report_infeasible_without_schedule(tmp_path: Path) -> None:
    run_dir = tmp_path / "run_20260506_080000"
    meta_dir = run_dir / "solutions" / "run_20260506_080001" / "_run_meta"
    meta_dir.mkdir(parents=True)
    log_path = run_dir / "run.log"
    log_path.write_text("求解状态：INFEASIBLE\n回调捕获解数量：0\n", encoding="utf-8")
    summary_path = meta_dir / "run_summary.json"
    summary_path.write_text(
        json.dumps({"kept_solutions": 0, "top_exported": 0, "captured": 0, "best_objective": None}),
        encoding="utf-8",
    )
    diagnostic = run_dir / "多解诊断报告.xlsx"
    diagnostic.write_text("diagnostic", encoding="utf-8")

    updates = solve_runner.completion_status_updates(
        [_artifact(summary_path, tmp_path), _artifact(log_path, tmp_path), _artifact(diagnostic, tmp_path)],
        log_path,
    )

    assert updates["solver_status"] == "INFEASIBLE"
    assert updates["solution_count"] == 0
    assert updates["schedule_file_count"] == 0
    assert updates["message"] == "求解器判定当前规则组合不可行，未生成可交付课表文件。"


def test_completion_status_updates_count_schedule_files_only(tmp_path: Path) -> None:
    run_dir = tmp_path / "run_20260506_081000"
    run_dir.mkdir()
    log_path = run_dir / "run.log"
    log_path.write_text("求解状态：OPTIMAL\n回调捕获解数量：1\n", encoding="utf-8")
    schedule = run_dir / "晚自习课表_top01.xlsx"
    schedule.write_text("schedule", encoding="utf-8")
    diagnostic = run_dir / "多解诊断报告.xlsx"
    diagnostic.write_text("diagnostic", encoding="utf-8")

    updates = solve_runner.completion_status_updates(
        [_artifact(schedule, tmp_path), _artifact(diagnostic, tmp_path), _artifact(log_path, tmp_path)],
        log_path,
        run_purpose="diagnostic_trial",
    )

    assert updates["solver_status"] == "OPTIMAL"
    assert updates["solution_count"] == 1
    assert updates["schedule_file_count"] == 1
    assert updates["message"] == "诊断试跑已生成候选课表，但包含临时放宽规则，不能直接作为交付版本。"


def test_completion_status_updates_includes_solver_quality_gap(tmp_path: Path) -> None:
    run_dir = tmp_path / "run_20260506_081500"
    run_dir.mkdir()
    log_path = run_dir / "run.log"
    log_path.write_text("求解状态：FEASIBLE\n回调捕获解数量：1\n", encoding="utf-8")
    overview = run_dir / "final_solver_overview.json"
    overview.write_text(
        json.dumps(
            {
                "solver_status": "FEASIBLE",
                "objective_value": 100,
                "best_bound": 70,
                "wall_time": 12.3,
            }
        ),
        encoding="utf-8",
    )

    updates = solve_runner.completion_status_updates(
        [_artifact(overview, tmp_path), _artifact(log_path, tmp_path)],
        log_path,
    )

    assert updates["solver_status"] == "FEASIBLE"
    assert updates["best_objective"] == 100
    assert updates["objective_value"] == 100
    assert updates["best_bound"] == 70
    assert updates["objective_gap"] == 30
    assert updates["gap_percent"] == 30
    assert updates["optimality_status"] == "gap_remaining"


def test_completion_status_updates_falls_back_to_solver_overview_when_log_has_no_status(tmp_path: Path) -> None:
    run_dir = tmp_path / "run_20260506_081700"
    run_dir.mkdir()
    log_path = run_dir / "run.log"
    log_path.write_text("Web solve completed\n", encoding="utf-8")
    overview = run_dir / "final_solver_overview.json"
    overview.write_text(
        json.dumps(
            {
                "solver_status": "INFEASIBLE",
                "objective_value": None,
                "best_bound": None,
                "solutions_seen": 0,
            }
        ),
        encoding="utf-8",
    )

    updates = solve_runner.completion_status_updates(
        [_artifact(overview, tmp_path), _artifact(log_path, tmp_path)],
        log_path,
    )

    assert updates["solver_status"] == "INFEASIBLE"
    assert updates["solution_count"] == 0
    assert updates["message"] == "求解器判定当前规则组合不可行，未生成可交付课表文件。"


def test_result_package_contains_final_status_message(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(solve_runner, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(solve_runner, "build_solve_readiness", lambda _mode: {"summary": {"can_publish": False}})
    monkeypatch.setattr(
        solve_runner,
        "build_publish_assessment",
        lambda status, _readiness: {
            "summary": {"status": "blocked", "status_label": "不可发布", "can_publish": False, "errors": 1, "warnings": 0},
            "outcome": {"solver_status": status.get("solver_status"), "solution_count": status.get("solution_count")},
            "file_categories": {"schedule": status.get("schedule_file_count", 0), "diagnostic": 1, "package": 1},
        },
    )
    run_dir = tmp_path / "outputs" / "web_runs" / "run_20260506_082000"
    run_dir.mkdir(parents=True)
    status_path = run_dir / "status.json"
    log_path = run_dir / "run.log"
    log_path.write_text("求解状态：INFEASIBLE\n回调捕获解数量：0\n", encoding="utf-8")
    status_path.write_text(
        json.dumps({"status": "running", "message": "求解运行中"}, ensure_ascii=False),
        encoding="utf-8",
    )
    files = solve_runner.collect_artifacts(run_dir, started_at_ts=0)
    updates = solve_runner.completion_status_updates(files, log_path)
    package_path = run_dir / "result_package.zip"
    solve_runner._status_update(
        status_path,
        status="completed",
        completed_at="2026-05-06 08:20:00",
        files=files,
        package_file=str(package_path),
        **updates,
    )

    package = solve_runner.build_result_package(run_dir, started_at_ts=0)

    with zipfile.ZipFile(package) as zf:
        names = zf.namelist()
        assert MANIFEST_FILENAME in names
        status_names = [name for name in zf.namelist() if name.endswith("status.json")]
        assert status_names == ["status.json"]
        archived_status = json.loads(zf.read(status_names[0]).decode("utf-8"))
        manifest = json.loads(zf.read(MANIFEST_FILENAME).decode("utf-8"))

    assert archived_status["status"] == "completed"
    assert archived_status["solver_status"] == "INFEASIBLE"
    assert archived_status["message"] == "求解器判定当前规则组合不可行，未生成可交付课表文件。"
    assert archived_status["package_integrity"]["status"] == "ok"
    assert archived_status["package_integrity"]["checks"]["zip_verified"] is True
    assert Path(archived_status["delivery_manifest_file"]).name == MANIFEST_FILENAME
    assert manifest["run"]["run_id"] == run_dir.name


def test_result_package_treats_legacy_review_status_as_ready_before_archiving(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(solve_runner, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(solve_runner, "build_solve_readiness", lambda _mode: {"summary": {"can_publish": True}})
    monkeypatch.setattr(
        solve_runner,
        "build_publish_assessment",
        lambda status, _readiness: {
            "summary": {"status": "review", "status_label": "旧版复核状态", "can_publish": True, "errors": 0, "warnings": 1},
            "outcome": {"solver_status": "FEASIBLE", "solution_count": 1},
            "file_categories": {"schedule": status.get("schedule_file_count", 0), "diagnostic": 0, "package": 1},
        },
    )
    run_dir = tmp_path / "outputs" / "web_runs" / "run_20260506_102257"
    run_dir.mkdir(parents=True)
    status_path = run_dir / "status.json"
    schedule = run_dir / "课表及值班安排.xlsx"
    schedule.write_text("schedule", encoding="utf-8")
    status_path.write_text(
        json.dumps(
            {
                "run_id": run_dir.name,
                "status": "completed",
                "mode": "joint",
                "solver_status": "FEASIBLE",
                "solution_count": 1,
                "schedule_file_count": 1,
                "message": "求解完成，已发现可交付课表文件。",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    package = solve_runner.build_result_package(run_dir, started_at_ts=0)

    with zipfile.ZipFile(package) as zf:
        status_names = [name for name in zf.namelist() if name.endswith("status.json")]
        assert status_names == ["status.json"]
        archived_status = json.loads(zf.read(status_names[0]).decode("utf-8"))
        manifest = json.loads(zf.read(MANIFEST_FILENAME).decode("utf-8"))

    expected = "求解完成，已发现可交付课表文件。"
    assert archived_status["message"] == expected
    assert manifest["run"]["message"] == expected
    assert archived_status["release_state"]["status"] == "ready"
    assert archived_status["release_state"]["package_label"] == "正式结果包"


def test_result_package_hydrates_solver_quality_before_archiving(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(solve_runner, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(solve_runner, "build_solve_readiness", lambda _mode: {"summary": {"can_publish": True}})
    monkeypatch.setattr(
        solve_runner,
        "build_publish_assessment",
        lambda status, _readiness: {
            "summary": {"status": "review", "status_label": "旧版待确认状态", "can_publish": True, "errors": 0, "warnings": 1},
            "outcome": {
                "solver_status": "FEASIBLE",
                "solution_count": 1,
                "best_objective": "100",
                "objective_value": 100,
                "best_bound": 70,
                "objective_gap": 30,
                "gap_percent": 30,
                "optimality_status": "gap_remaining",
            },
            "file_categories": {"schedule": status.get("schedule_file_count", 0), "diagnostic": 0, "package": 1},
        },
    )
    run_dir = tmp_path / "outputs" / "web_runs" / "run_20260506_102258"
    run_dir.mkdir(parents=True)
    schedule = run_dir / "课表及值班安排.xlsx"
    schedule.write_text("schedule", encoding="utf-8")
    best_log = run_dir / "solutions" / "run_20260506_102302" / "pool_cache" / "sol_0035" / "event_log.csv"
    best_log.parent.mkdir(parents=True)
    best_log.write_text(
        "constraint_id,constraint_name,teacher_name,unit_penalty,count_value,penalty,mode\n"
        "lang_tue_fri_pm3_penalty,语文外语周二至周五下午3惩罚,教师A,10,2,20,soft\n"
        "lang_tue_fri_pm3_penalty,语文外语周二至周五下午3惩罚,教师B,10,1,10,soft\n"
        "day_night_link_w1,晚自习需当天下午有课,教师C,5,1,5,soft\n",
        encoding="utf-8",
    )
    best_meta = run_dir / "solutions" / "run_20260506_102302" / "best" / "最终全局最优解_meta.json"
    best_meta.parent.mkdir(parents=True)
    best_meta.write_text(
        json.dumps(
            {
                "seq_id": 35,
                "event_log_file": str(best_log),
                "source_solution_file": str(best_log.with_name("最终全局最优解.xlsx")),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (run_dir / "status.json").write_text(
        json.dumps(
            {
                "run_id": run_dir.name,
                "status": "completed",
                "mode": "joint",
                "solver_status": "FEASIBLE",
                "solution_count": 1,
                "schedule_file_count": 1,
                "message": "求解完成，已发现可交付课表文件。",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    package = solve_runner.build_result_package(run_dir, started_at_ts=0)

    with zipfile.ZipFile(package) as zf:
        archived_status = json.loads(zf.read("status.json").decode("utf-8"))
        manifest = json.loads(zf.read(MANIFEST_FILENAME).decode("utf-8"))

    assert archived_status["objective_value"] == 100
    assert archived_status["best_bound"] == 70
    assert archived_status["objective_gap"] == 30
    assert archived_status["gap_percent"] == 30
    assert archived_status["optimality_status"] == "gap_remaining"
    assert archived_status["objective_breakdown"]["summary"]["total_penalty"] == 35
    assert archived_status["objective_breakdown"]["summary"]["net_event_penalty"] == 35
    assert archived_status["objective_breakdown"]["summary"]["solver_objective_value"] == 100
    assert archived_status["objective_breakdown"]["summary"]["objective_explain_delta"] == 65
    assert archived_status["objective_breakdown"]["summary"]["objective_reconciliation_status"] == "unmatched"
    assert archived_status["objective_breakdown"]["top"][0]["rule_id"] == "lang_tue_fri_pm3_penalty"
    assert archived_status["solve_diagnostics"]["summary"]["status"] == "review"
    assert any(issue["title"] == "目标值解释未完全对账" for issue in archived_status["solve_diagnostics"]["issues"])
    assert any(
        issue["title"] == "主导软约束代价：语文外语周二至周五下午3惩罚"
        for issue in archived_status["solve_diagnostics"]["issues"]
    )
    assert manifest["solver"]["objective_gap"] == 30
    assert manifest["solver"]["optimality_status"] == "gap_remaining"
    assert manifest["solver"]["objective_breakdown"]["summary"]["total_penalty"] == 35
    assert manifest["solver"]["objective_breakdown"]["summary"]["objective_explain_delta"] == 65
    assert manifest["solver"]["objective_breakdown"]["top"][0]["rule_name"] == "语文外语周二至周五下午3惩罚"
    assert manifest["solve_diagnostics"]["summary"]["status"] == "review"


def test_result_package_rebuild_can_cap_global_outputs_after_end_time(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(solve_runner, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(solve_runner, "build_solve_readiness", lambda _mode: {"summary": {"can_publish": True}})
    monkeypatch.setattr(
        solve_runner,
        "build_publish_assessment",
        lambda status, _readiness: {
            "summary": {"status": "ready", "status_label": "可发布", "can_publish": True, "errors": 0, "warnings": 0},
            "outcome": {"solver_status": "OPTIMAL", "solution_count": 1},
            "file_categories": {"schedule": status.get("schedule_file_count", 0), "diagnostic": 0, "package": 1},
        },
    )
    output_dir = tmp_path / "outputs"
    run_dir = output_dir / "web_runs" / "run_20260506_102259"
    run_dir.mkdir(parents=True)
    (run_dir / "课表及值班安排.xlsx").write_text("schedule", encoding="utf-8")
    during = output_dir / "meta" / "during_run.json"
    later = output_dir / "meta" / "future_run.json"
    during.parent.mkdir(parents=True)
    during.write_text("during", encoding="utf-8")
    later.write_text("later", encoding="utf-8")
    started = 1_778_024_590.0
    ended = started + 260
    os.utime(during, (started + 20, started + 20))
    os.utime(later, (ended + 300, ended + 300))
    (run_dir / "status.json").write_text(
        json.dumps(
            {
                "status": "completed",
                "mode": "joint",
                "solver_status": "OPTIMAL",
                "solution_count": 1,
                "schedule_file_count": 1,
                "message": "求解完成，已发现可交付课表文件。",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    package = solve_runner.build_result_package(run_dir, started_at_ts=started, ended_at_ts=ended)

    with zipfile.ZipFile(package) as zf:
        names = {name.replace("\\", "/") for name in zf.namelist()}

    assert "outputs/meta/during_run.json" in names
    assert "outputs/meta/future_run.json" not in names


def test_result_package_hydrates_config_fingerprint_before_archiving(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(solve_runner, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        solve_runner,
        "build_effective_config_fingerprint",
        lambda _mode: {"mode": "joint", "hash": "same", "generated_at": "2026-05-12T02:41:38+00:00"},
    )
    monkeypatch.setattr(solve_runner, "build_solve_readiness", lambda _mode: {"summary": {"can_publish": True}})
    monkeypatch.setattr(
        solve_runner,
        "build_publish_assessment",
        lambda status, _readiness: {
            "summary": {"status": "ready", "status_label": "可发布", "can_publish": True, "errors": 0, "warnings": 0},
            "outcome": {"solver_status": "OPTIMAL", "solution_count": 1},
            "file_categories": {"schedule": status.get("schedule_file_count", 0), "diagnostic": 0, "package": 1},
        },
    )
    run_dir = tmp_path / "outputs" / "web_runs" / "run_20260512_024200"
    run_dir.mkdir(parents=True)
    (run_dir / "课表及值班安排.xlsx").write_text("schedule", encoding="utf-8")
    (run_dir / "status.json").write_text(
        json.dumps(
            {
                "status": "completed",
                "mode": "joint",
                "solver_status": "OPTIMAL",
                "solution_count": 1,
                "schedule_file_count": 1,
                "config_fingerprint": {"mode": "joint", "hash": "same"},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    package = solve_runner.build_result_package(run_dir, started_at_ts=0)

    with zipfile.ZipFile(package) as zf:
        archived_status = json.loads(zf.read("status.json").decode("utf-8"))
        manifest = json.loads(zf.read(MANIFEST_FILENAME).decode("utf-8"))

    assert archived_status["config_fingerprint_match"] is True
    assert archived_status["config_freshness"]["status"] == "matched"
    assert manifest["config"]["fingerprint_match"] is True
    assert manifest["config"]["freshness"]["status"] == "matched"


def test_collect_artifacts_filters_global_outputs_after_end_time(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(solve_runner, "PROJECT_ROOT", tmp_path)
    output_dir = tmp_path / "outputs"
    run_dir = output_dir / "web_runs" / "run_20260506_094310"
    run_dir.mkdir(parents=True)
    during = output_dir / "课表及值班安排_20260506_094311.xlsx"
    later = output_dir / "meta" / "encoding_regression" / "中文编码校验.xlsx"
    run_log = run_dir / "run.log"
    later.parent.mkdir(parents=True)
    during.write_text("schedule", encoding="utf-8")
    later.write_text("later", encoding="utf-8")
    run_log.write_text("log", encoding="utf-8")
    started = 1_778_024_590.0
    ended = started + 260
    os.utime(during, (started + 20, started + 20))
    os.utime(later, (ended + 300, ended + 300))
    os.utime(run_log, (ended + 300, ended + 300))

    labels = {
        item["label"].replace("\\", "/")
        for item in solve_runner.collect_artifacts(run_dir, started_at_ts=started, ended_at_ts=ended)
    }

    assert "outputs/课表及值班安排_20260506_094311.xlsx" in labels
    assert "outputs/web_runs/run_20260506_094310/run.log" in labels
    assert "outputs/meta/encoding_regression/中文编码校验.xlsx" not in labels


def test_collect_artifacts_includes_effective_config_yaml(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(solve_runner, "PROJECT_ROOT", tmp_path)
    run_dir = tmp_path / "outputs" / "web_runs" / "run_20260506_102257"
    meta_dir = run_dir / "solutions" / "run_20260506_102302" / "_run_meta"
    meta_dir.mkdir(parents=True)
    effective = meta_dir / "effective_config.yaml"
    effective.write_text("checkin:\n  enabled: true\n", encoding="utf-8")

    labels = {
        item["label"].replace("\\", "/")
        for item in solve_runner.collect_artifacts(run_dir, started_at_ts=0)
    }

    assert "outputs/web_runs/run_20260506_102257/solutions/run_20260506_102302/_run_meta/effective_config.yaml" in labels


def test_runner_status_records_replay_parameters(monkeypatch, tmp_path: Path) -> None:
    class FakeSchedulerCore:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def run_mode(self, mode: str) -> None:
            assert mode == "joint"

    monkeypatch.setattr(solve_runner, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(solve_runner, "SchedulerCore", FakeSchedulerCore)
    monkeypatch.setattr(solve_runner, "collect_artifacts", lambda _run_dir, _started_at_ts: [])
    monkeypatch.setattr(
        solve_runner,
        "completion_status_updates",
        lambda _files, _log_path, run_purpose="": {
            "message": "求解完成",
            "solver_status": "FEASIBLE",
            "solution_count": 1,
            "schedule_file_count": 0,
            "best_objective": 12,
        },
    )
    monkeypatch.setattr(solve_runner, "build_result_package", lambda run_dir, _started_at_ts: run_dir / "result_package.zip")

    run_dir = tmp_path / "outputs" / "web_runs" / "run_20260506_090000"
    result = solve_runner.run(
        SimpleNamespace(
            run_id="run_20260506_090000",
            run_dir=str(run_dir),
            mode="joint",
            grade_prefix="高二",
            time_limit_seconds=123,
            workers=3,
            seed=99,
            relative_gap_limit=0.03,
            absolute_gap_limit=4.0,
            log_search_progress=True,
            max_keep=4,
            snapshot_interval_sec=15,
            enable_snapshots=True,
            run_purpose="diagnostic_trial",
            diagnostic_plan_id="relax.day_night_link",
            diagnostic_plan_title="先放宽白天-晚自习联动",
            active_diagnostic_relaxations_json=json.dumps(
                [
                    {
                        "id": "relax.day_night_link",
                        "title": "先放宽白天-晚自习联动",
                        "domain": "联动规则",
                        "patch_count": 1,
                    }
                ],
                ensure_ascii=False,
            ),
        )
    )

    status = json.loads((run_dir / "status.json").read_text(encoding="utf-8"))
    assert result == 0
    assert status["grade_prefix"] == "高二"
    assert status["time_limit_seconds"] == 123
    assert status["workers"] == 3
    assert status["max_keep"] == 3
    assert status["requested_max_keep"] == 4
    assert status["max_keep_capped"] is True
    assert "诊断试跑最多保留" in status["max_keep_cap_reason"]
    assert status["snapshot_interval_sec"] == 15
    assert status["enable_snapshots"] is True
    assert status["random_seed"] == 99
    assert status["relative_gap_limit"] == 0.03
    assert status["absolute_gap_limit"] == 4.0
    assert status["log_search_progress"] is True
    assert status["run_purpose"] == "diagnostic_trial"
    assert status["diagnostic_plan_id"] == "relax.day_night_link"
    assert status["active_diagnostic_relaxations"][0]["title"] == "先放宽白天-晚自习联动"
