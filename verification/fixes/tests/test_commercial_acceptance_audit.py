from __future__ import annotations

import json
import zipfile
from pathlib import Path

from verification.fixes.commercial_acceptance_audit import (
    _current_package_contract,
    _latest_status,
    _status_for_recommended_candidate,
    _status_publishable,
)


def _availability(*, schedule_file_count: int, package_label: str = "正式结果包") -> dict:
    has_schedule = schedule_file_count > 0
    return {
        "schema_version": "scheduler.result_availability.v1",
        "status": "available" if has_schedule else "missing",
        "label": "已生成正式课表" if has_schedule else "未生成课表文件",
        "tone": "ready" if has_schedule else "warning",
        "has_schedule_files": has_schedule,
        "has_result_package": True,
        "schedule_file_count": schedule_file_count,
        "diagnostic_file_count": 0,
        "package_file_count": 1,
        "total_file_count": schedule_file_count + 1,
        "package_label": package_label,
        "formal_release_ready": has_schedule,
        "hidden_schedule_file_count": 0,
        "primary_schedule_files": [
            {
                "label": "outputs/最终全局最优解.xlsx",
                "display_label": "最终全局最优解.xlsx",
                "path": "outputs/最终全局最优解.xlsx",
                "download_name": "最终全局最优解.xlsx",
                "release_use": "official_delivery",
                "release_badge": "正式交付",
                "size": 123,
                "modified_at": "2026-05-06 12:00:00",
            }
        ]
        if has_schedule
        else [],
        "category_counts": {"schedule": schedule_file_count, "package": 1},
    }


def _write_package(tmp_path: Path, *, status_value: str = "ready", schedule_file_count: int = 1) -> Path:
    package = tmp_path / "result_package.zip"
    message = "求解完成，已发现可交付课表文件。" if schedule_file_count else "求解已结束，但未捕获可行解，未生成可交付课表文件。"
    formal_ready = status_value == "ready"
    can_publish = status_value == "ready" and schedule_file_count > 0
    availability = _availability(schedule_file_count=schedule_file_count)
    release_state = {
        "schema_version": "scheduler.release_state.v2",
        "status": status_value,
        "status_label": "可发布",
        "run_purpose": "formal",
        "solver_status": "FEASIBLE" if schedule_file_count else "INFEASIBLE",
        "solution_count": 1 if schedule_file_count else 0,
        "schedule_file_count": schedule_file_count,
        "can_publish_candidate": can_publish,
        "formal_release_ready": formal_ready,
        "package_kind": "formal" if formal_ready else "diagnostic",
        "package_label": "正式结果包" if formal_ready else "排障包",
        "run_message": message,
        "next_action": "可下载正式结果包，并按学校现有 OA 或线下流程归档。",
    }
    solver = {
        "solver_status": "FEASIBLE" if schedule_file_count else "INFEASIBLE",
        "solution_count": 1 if schedule_file_count else 0,
        "schedule_file_count": schedule_file_count,
        "objective_value": 100.0 if schedule_file_count else None,
        "best_bound": 100.0 if schedule_file_count else None,
        "objective_gap": 0.0 if schedule_file_count else None,
        "gap_percent": 0.0 if schedule_file_count else None,
        "optimality_status": "proven_optimal" if schedule_file_count else "unknown",
    }
    diagnostics = {
        "summary": {"status": "ok", "errors": 0, "warnings": 0, "message": "未见阻断。"},
        "issues": [],
        "next_actions": [],
    }
    status_payload = {
        "message": message,
        **solver,
        "release_state": release_state,
        "result_availability": availability,
        "solve_diagnostics": diagnostics,
        "publish_assessment": {
            "summary": {"status": status_value, "can_publish": can_publish},
            "gates": [],
            "next_actions": [],
        },
    }
    manifest = {
        "run": {"message": message},
        "solver": solver,
        "release_state": release_state,
        "publish_assessment": {"summary": status_payload["publish_assessment"]["summary"], "gates": [], "next_actions": []},
        "release_decision": {
            "status": status_value,
            "can_publish": can_publish,
            "formal_release_ready": formal_ready,
            "warning_titles": [],
        },
        "result_availability": availability,
        "solve_diagnostics": {"summary": diagnostics["summary"], "next_actions": []},
        "package_integrity": {"status": "ok"},
    }
    with zipfile.ZipFile(package, "w") as zf:
        zf.writestr("delivery_manifest.json", json.dumps(manifest, ensure_ascii=False))
        zf.writestr("status.json", json.dumps(status_payload, ensure_ascii=False))
    return package


def _status(tmp_path: Path, *, publish_status: str = "ready", schedule_file_count: int = 1) -> dict:
    package = _write_package(tmp_path, status_value=publish_status, schedule_file_count=schedule_file_count)
    return {
        "status_file": str(tmp_path / "status.json"),
        "run_id": tmp_path.name,
        "run_dir": str(tmp_path),
        "package_file": str(package),
        "solver_status": "FEASIBLE" if schedule_file_count else "INFEASIBLE",
        "solution_count": 1 if schedule_file_count else 0,
        "schedule_file_count": schedule_file_count,
        "config_fingerprint_match": True,
        "publish_assessment": {"summary": {"status": publish_status, "can_publish": publish_status == "ready"}},
    }


def test_latest_status_prefers_formal_run_over_newer_diagnostic_trial(tmp_path: Path) -> None:
    formal_dir = tmp_path / "outputs" / "web_runs" / "run_20260506_100000"
    diagnostic_dir = tmp_path / "outputs" / "web_runs" / "run_20260506_110000"
    formal_dir.mkdir(parents=True)
    diagnostic_dir.mkdir(parents=True)
    (formal_dir / "status.json").write_text(json.dumps({"run_id": formal_dir.name}), encoding="utf-8")
    (diagnostic_dir / "status.json").write_text(
        json.dumps({"run_id": diagnostic_dir.name, "run_purpose": "diagnostic_trial"}),
        encoding="utf-8",
    )

    latest = _latest_status(tmp_path, include_diagnostic=False)

    assert latest is not None
    assert latest["run_id"] == formal_dir.name


def test_status_for_recommended_candidate_reads_selected_run_status(tmp_path: Path) -> None:
    latest_dir = tmp_path / "outputs" / "web_runs" / "run_20260506_110000"
    candidate_dir = tmp_path / "outputs" / "web_runs" / "run_20260506_100000"
    latest_dir.mkdir(parents=True)
    candidate_dir.mkdir(parents=True)
    candidate_status = {"run_id": candidate_dir.name, "objective_value": 90, "status_file": str(candidate_dir / "status.json")}
    (candidate_dir / "status.json").write_text(json.dumps(candidate_status), encoding="utf-8")
    latest_status = {
        "run_id": latest_dir.name,
        "recommended_formal_candidate": {
            "summary": {"selected_run_id": candidate_dir.name, "current_run_id": latest_dir.name},
            "candidate": {"run_dir": str(candidate_dir), "status_file": str(candidate_dir / "status.json")},
        },
    }

    selected = _status_for_recommended_candidate(latest_status, repo_root=tmp_path)

    assert selected is not None
    assert selected["run_id"] == candidate_dir.name
    assert selected["audit_latest_run_id"] == latest_dir.name


def test_current_package_contract_accepts_manifest_and_status_only(tmp_path: Path) -> None:
    ok, evidence, gap = _current_package_contract(_status(tmp_path))

    assert ok is True
    assert gap == ""
    assert any(item.startswith("status_entries=status.json") for item in evidence)


def test_current_package_contract_blocks_missing_root_status(tmp_path: Path) -> None:
    package = tmp_path / "result_package.zip"
    with zipfile.ZipFile(package, "w") as zf:
        zf.writestr("delivery_manifest.json", "{}")

    ok, _evidence, gap = _current_package_contract({"package_file": str(package)})

    assert ok is False
    assert "status.json" in gap


def test_status_publishable_allows_feasible_gap_as_advisory(tmp_path: Path) -> None:
    status = _status(tmp_path)
    status.update({"optimality_status": "gap_remaining", "objective_value": 100, "best_bound": 70, "objective_gap": 30})

    ok, evidence, gap, formal_ready = _status_publishable(status, strict_release=True)

    assert ok is True
    assert formal_ready is True
    assert gap == ""
    assert "objective_gap=30" in evidence


def test_status_publishable_blocks_diagnostic_trial(tmp_path: Path) -> None:
    status = _status(tmp_path)
    status["run_purpose"] = "diagnostic_trial"

    ok, _evidence, gap, formal_ready = _status_publishable(status, strict_release=True)

    assert ok is False
    assert formal_ready is False
    assert "诊断试跑" in gap
