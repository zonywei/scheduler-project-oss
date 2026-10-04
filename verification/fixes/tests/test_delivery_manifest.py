from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


import scheduler.app.solve_service as solve_service
from scheduler.app.delivery_manifest import MANIFEST_FILENAME, build_delivery_manifest


def _artifact(path: Path, *, label: str | None = None) -> dict:
    return {
        "label": label or f"outputs/{path.name}",
        "path": str(path),
        "size": path.stat().st_size,
        "modified_at": "",
    }


def test_delivery_manifest_records_release_decision_without_review_artifacts(tmp_path: Path) -> None:
    schedule = tmp_path / "课表.xlsx"
    schedule.write_text("schedule", encoding="utf-8")
    status = {
        "run_id": "run_test",
        "status": "completed",
        "mode": "joint",
        "message": "求解完成",
        "solver_status": "FEASIBLE",
        "solution_count": 1,
        "schedule_file_count": 1,
        "publish_assessment": {
            "summary": {
                "status": "ready",
                "status_label": "可发布（含风险提示）",
                "can_publish": True,
                "errors": 0,
                "warnings": 1,
            },
            "gates": [
                {
                    "severity": "warning",
                    "domain": "晚查寝策略",
                    "title": "存在当天无晚自习查寝安排",
                    "suggestion": "下载前查看风险提示。",
                    "remediation_options": [
                        {
                            "id": "publish.checkin.record_external_exception",
                            "title": "外部记录保留例外",
                            "action_type": "external_record",
                        }
                    ],
                }
            ],
            "outcome": {"solver_status": "FEASIBLE", "solution_count": 1},
            "file_categories": {"schedule": 1, "package": 1},
        },
        "package_integrity": {"status": "ok", "checks": {"expected_zip_entries": 2}},
    }

    manifest = build_delivery_manifest(status, [_artifact(schedule)], package_path=tmp_path / "result_package.zip")

    assert manifest["release_decision"]["status"] == "ready"
    assert manifest["release_decision"]["formal_release_ready"] is True
    assert manifest["release_decision"]["warning_titles"] == ["存在当天无晚自习查寝安排"]
    assert "review_titles" not in manifest["release_decision"]
    assert "release_preflight" not in manifest["publish_assessment"]
    assert "release_handoff" not in manifest["artifacts"]
    assert "release_review_worksheet" not in manifest["artifacts"]
    assert manifest["artifacts"]["files"][0]["sha256"]
    assert manifest["package_integrity"]["status"] == "ok"


def test_result_package_includes_delivery_manifest_and_root_status_only(monkeypatch, tmp_path: Path) -> None:
    run_dir = tmp_path / "run_20260506_120000"
    run_dir.mkdir()
    schedule = run_dir / "课表及值班安排.xlsx"
    schedule.write_text("schedule", encoding="utf-8")
    artifact = _artifact(schedule, label="outputs/课表及值班安排.xlsx")
    status = {
        "run_id": run_dir.name,
        "run_dir": str(run_dir),
        "status": "completed",
        "mode": "joint",
        "message": "求解完成",
        "files": [artifact],
        "package_file": str(run_dir / "result_package.zip"),
        "log_tail": "status = FEASIBLE\n回调捕获解数量：1",
        "config_fingerprint": {"mode": "joint", "hash": "a" * 64},
        "current_config_fingerprint": {"mode": "joint", "hash": "a" * 64},
        "config_fingerprint_match": True,
    }

    monkeypatch.setattr(solve_service, "_latest_run_dir", lambda: run_dir)
    monkeypatch.setattr(solve_service, "_current_started_ts", run_dir.stat().st_mtime)
    monkeypatch.setattr(solve_service, "collect_artifacts", lambda _run_dir, _started_ts, ended_at_ts=None: [artifact])
    monkeypatch.setattr(solve_service, "get_solve_status", lambda: dict(status))
    monkeypatch.setattr(solve_service, "build_solve_readiness", lambda _mode: {"summary": {"can_publish": True}})
    monkeypatch.setattr(
        solve_service,
        "build_effective_config_fingerprint",
        lambda _mode: {"mode": "joint", "hash": "a" * 64},
    )

    package = solve_service.build_package_for_latest_run()

    with zipfile.ZipFile(package) as zf:
        names = zf.namelist()
        assert MANIFEST_FILENAME in names
        assert "status.json" in names
        assert "release_handoff.md" not in names
        assert "release_review_worksheet.csv" not in names
        assert [name for name in names if name.endswith("status.json")] == ["status.json"]
        manifest = json.loads(zf.read(MANIFEST_FILENAME).decode("utf-8"))
        packaged_status = json.loads(zf.read("status.json").decode("utf-8"))

    assert manifest["run"]["run_id"] == run_dir.name
    assert manifest["release_decision"]["can_publish"] is True
    assert packaged_status["package_integrity"]["status"] == "ok"
    status_after = json.loads((run_dir / "status.json").read_text(encoding="utf-8"))
    assert Path(status_after["delivery_manifest_file"]).name == MANIFEST_FILENAME
    assert "release_handoff_file" not in status_after
    assert "release_review_worksheet_file" not in status_after


def test_package_snapshot_rebases_a_relocated_run_directory(tmp_path: Path) -> None:
    run_dir = tmp_path / "run_20260506_120001"
    run_dir.mkdir()
    stale_run_dir = Path("C:/old-checkout/outputs/web_runs") / run_dir.name

    snapshot = solve_service._package_status_snapshot(
        run_dir,
        [],
        run_dir / "result_package.zip",
        base_status={
            "run_id": run_dir.name,
            "run_dir": str(stale_run_dir),
            "status": "completed",
        },
    )

    assert snapshot["run_dir"] == str(run_dir)


def test_package_download_name_matches_publish_state() -> None:
    assert solve_service.package_download_name(
        {
            "run_id": "run_20260506_120000",
            "run_purpose": "diagnostic_trial",
            "publish_assessment": {"summary": {"status": "blocked"}},
        }
    ) == "排障包_run_20260506_120000.zip"
    assert solve_service.package_download_name(
        {
            "run_id": "run_20260506_130000",
            "publish_assessment": {"summary": {"status": "review"}},
        }
    ) == "结果包_run_20260506_130000.zip"
    assert solve_service.package_download_name(
        {
            "run_id": "run_20260506_140000",
            "publish_assessment": {"summary": {"status": "ready"}},
        }
    ) == "正式结果包_run_20260506_140000.zip"


def test_file_download_name_labels_diagnostic_and_blocked_schedule_files(tmp_path: Path) -> None:
    run_dir = tmp_path / "run_20260506_150000"
    schedule = run_dir / "solutions" / "best" / "最终全局最优解_正式版.xlsx"
    schedule.parent.mkdir(parents=True)
    schedule.write_text("schedule", encoding="utf-8")

    assert solve_service.file_download_name(
        schedule,
        {
            "run_dir": str(run_dir),
            "run_purpose": "diagnostic_trial",
            "publish_assessment": {"summary": {"status": "blocked"}},
        },
    ) == "候选课表_排障参考_最终全局最优解.xlsx"
    assert solve_service.file_download_name(
        schedule,
        {"run_dir": str(run_dir), "publish_assessment": {"summary": {"status": "blocked"}}},
    ) == "不可发布_排障参考_最终全局最优解.xlsx"
    assert solve_service.file_download_name(
        schedule,
        {"run_dir": str(run_dir), "publish_assessment": {"summary": {"status": "ready"}}},
    ) == "最终全局最优解_正式版.xlsx"


def test_result_package_filters_stale_manifest_before_rewriting(monkeypatch, tmp_path: Path) -> None:
    run_dir = tmp_path / "run_20260506_130000"
    run_dir.mkdir()
    stale_manifest = run_dir / MANIFEST_FILENAME
    stale_manifest.write_text('{"stale": true}', encoding="utf-8")
    schedule = run_dir / "课表.xlsx"
    schedule.write_text("schedule", encoding="utf-8")
    schedule_artifact = _artifact(schedule, label="outputs/课表.xlsx")
    stale_artifact = _artifact(stale_manifest, label=f"outputs/{run_dir.name}/{MANIFEST_FILENAME}")
    status = {
        "run_id": run_dir.name,
        "status": "completed",
        "mode": "joint",
        "message": "求解完成",
        "files": [stale_artifact, schedule_artifact],
        "log_tail": "status = FEASIBLE\n回调捕获解数量：1",
    }

    monkeypatch.setattr(solve_service, "_latest_run_dir", lambda: run_dir)
    monkeypatch.setattr(solve_service, "_current_started_ts", run_dir.stat().st_mtime)
    monkeypatch.setattr(solve_service, "collect_artifacts", lambda _run_dir, _started_ts, ended_at_ts=None: [stale_artifact, schedule_artifact])
    monkeypatch.setattr(solve_service, "get_solve_status", lambda: dict(status))
    monkeypatch.setattr(solve_service, "build_solve_readiness", lambda _mode: {"summary": {"can_publish": True}})

    package = solve_service.build_package_for_latest_run()

    with zipfile.ZipFile(package) as zf:
        names = zf.namelist()
        assert names.count(MANIFEST_FILENAME) == 1
        assert names.count("status.json") == 1
        assert not any(name.endswith(f"/{MANIFEST_FILENAME}") for name in names)
        assert not any(name.endswith("/status.json") for name in names)
        manifest = json.loads(zf.read(MANIFEST_FILENAME).decode("utf-8"))

    manifest_labels = [item["label"] for item in manifest["artifacts"]["files"]]
    assert all(not label.endswith(MANIFEST_FILENAME) for label in manifest_labels)
    status_after = json.loads((run_dir / "status.json").read_text(encoding="utf-8"))
    assert sum(1 for item in status_after["files"] if Path(item["path"]).name == MANIFEST_FILENAME) == 1
    assert sum(1 for item in status_after["files"] if Path(item["path"]).name == "status.json") == 1


def test_package_integrity_report_blocks_stale_formal_label_for_candidate_schedule(tmp_path: Path) -> None:
    schedule = tmp_path / "最终全局最优解_正式版.xlsx"
    schedule.write_text("schedule", encoding="utf-8")

    report = solve_service.build_package_integrity_report(
        [
            {
                "label": "outputs/最终全局最优解_正式版.xlsx",
                "path": str(schedule),
                "archive_name": "outputs/最终全局最优解_正式版.xlsx",
                "category": "schedule",
                "release_use": "troubleshooting_reference",
                "display_label": "最终全局最优解_正式版.xlsx",
                "download_name": "最终全局最优解_正式版.xlsx",
            }
        ],
        {"run_purpose": "diagnostic_trial"},
        expected_system_entries=[MANIFEST_FILENAME],
        zip_entries=["outputs/最终全局最优解_正式版.xlsx", MANIFEST_FILENAME],
    )

    assert report["status"] == "error"
    assert report["checks"]["forbidden_release_names"] == 1
    assert any(issue["title"] == "候选课表仍含正式版字样" for issue in report["issues"])


def test_package_integrity_report_detects_missing_zip_entry(tmp_path: Path) -> None:
    schedule = tmp_path / "课表.xlsx"
    schedule.write_text("schedule", encoding="utf-8")

    report = solve_service.build_package_integrity_report(
        [
            {
                "label": "outputs/课表.xlsx",
                "path": str(schedule),
                "archive_name": "outputs/课表.xlsx",
                "category": "schedule",
                "release_use": "official_delivery",
            }
        ],
        {},
        expected_system_entries=[MANIFEST_FILENAME],
        zip_entries=[MANIFEST_FILENAME],
    )

    assert report["status"] == "error"
    assert report["checks"]["missing_zip_entries"] == 1
