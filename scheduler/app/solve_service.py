# -*- coding: utf-8 -*-
from __future__ import annotations

import copy
import json
import re
import subprocess
import sys
import time
import zipfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from scheduler.app.config_service import (
    PROJECT_ROOT,
    build_effective_config_fingerprint,
    list_teacher_subject_rows,
    load_academic_affairs_payload,
)
from scheduler.app.delivery_manifest import MANIFEST_FILENAME, write_delivery_manifest
from scheduler.app.local_timetable_repair import (
    apply_leave_substitution_repair as _apply_leave_substitution_repair,
    preview_leave_substitution_repair as _preview_leave_substitution_repair,
)
from scheduler.app.local_timetable_adjustment import (
    apply_manual_timetable_adjustment as _apply_manual_timetable_adjustment,
    preview_manual_timetable_adjustment as _preview_manual_timetable_adjustment,
)
from scheduler.app.diagnostic_relaxation import active_relaxation_plans
from scheduler.app.formal_run_history import build_formal_run_comparison, build_recommended_formal_candidate
from scheduler.app.publish_assessment import build_publish_assessment
from scheduler.app.readiness import build_solve_readiness
from scheduler.app.release_messages import apply_release_aware_run_message
from scheduler.app.result_availability import attach_result_availability
from scheduler.app.runtime_audit_artifacts import (
    RUNTIME_AUDIT_RELEASE_USE,
    is_runtime_audit_artifact,
    runtime_audit_display_name,
)
from scheduler.app.rule_explain import build_rule_explain
from scheduler.app.solve_diagnostics import build_solve_diagnostics
from scheduler.app.solve_runner import DIAGNOSTIC_MAX_KEEP, collect_artifacts, effective_max_keep
from scheduler.platform.runtime import runtime_organization_id, uses_sqlite_workspace
from scheduler.solver_quality import solver_quality_fields


WEB_RUN_ROOT = PROJECT_ROOT / "outputs" / "web_runs"
RUN_DIR_PATTERN = re.compile(r"^run_\d{8}_\d{6}$")
STATUS_FILENAME = "status.json"
SYSTEM_PACKAGE_ENTRIES = [MANIFEST_FILENAME]
LEGACY_PUBLISH_REVIEW_STATUS_KEYS = (
    "release_handoff_file",
    "release_review_worksheet_file",
    "release_review",
    "release_review_draft",
    "release_review_candidate_draft",
    "release_artifact_sync",
)
_current_process: subprocess.Popen[str] | None = None
_current_run_dir: Path | None = None
_current_started_ts: float | None = None


def runtime_web_run_root() -> Path:
    if not uses_sqlite_workspace():
        return WEB_RUN_ROOT
    organization_id = runtime_organization_id()
    safe_organization_id = re.sub(r"[^A-Za-z0-9._-]", "_", organization_id)
    return PROJECT_ROOT / "outputs" / "tenants" / safe_organization_id / "web_runs"


def _iso_now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _read_status(run_dir: Path | None) -> dict[str, Any]:
    if run_dir is None:
        return {"status": "idle", "message": "暂无求解任务", "files": []}
    path = run_dir / "status.json"
    if not path.exists():
        return {
            "status": "starting",
            "run_dir": str(run_dir),
            "message": "求解任务正在启动",
            "files": [],
        }
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception as exc:
        return {"status": "unknown", "run_dir": str(run_dir), "message": str(exc), "files": []}


def _write_status(run_dir: Path, payload: dict[str, Any]) -> None:
    path = run_dir / "status.json"
    current = _read_status(run_dir)
    current.update(payload)
    _drop_legacy_publish_review_state(current)
    current["updated_at"] = _iso_now()
    path.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")


def _is_running() -> bool:
    return _current_process is not None and _current_process.poll() is None


def _latest_run_dir() -> Path | None:
    if _current_run_dir is not None:
        current_status = _read_status(_current_run_dir)
        if _is_active_run_status(current_status) or not _is_diagnostic_run_status(current_status):
            return _current_run_dir
    web_run_root = runtime_web_run_root()
    if not web_run_root.exists():
        return None
    runs = [
        path
        for path in web_run_root.iterdir()
        if path.is_dir() and RUN_DIR_PATTERN.fullmatch(path.name)
    ]
    if not runs:
        return None
    active_runs = [path for path in runs if _is_active_run_status(_read_status(path))]
    if active_runs:
        return max(active_runs, key=lambda path: path.stat().st_mtime)
    formal_runs = [path for path in runs if not _is_diagnostic_run_status(_read_status(path))]
    if formal_runs:
        return max(formal_runs, key=lambda path: path.stat().st_mtime)
    return max(runs, key=lambda path: path.stat().st_mtime)


def _is_active_run_status(status: dict[str, Any]) -> bool:
    return str(status.get("status") or "") in {"running", "pause_requested", "starting"}


def _is_diagnostic_run_status(status: dict[str, Any]) -> bool:
    return str(status.get("run_purpose") or "") == "diagnostic_trial"


def _refresh_finished_status() -> dict[str, Any]:
    global _current_process
    run_dir = _latest_run_dir()
    status = _read_status(run_dir)
    if _current_process is not None and _current_process.poll() is not None:
        code = int(_current_process.returncode or 0)
        if status.get("status") in {"running", "pause_requested", "starting"}:
            next_status = "completed" if code == 0 else "stopped"
            message = "求解已结束" if code == 0 else "求解进程已停止，可下载已捕获的阶段性结果"
            files = collect_artifacts(run_dir, _current_started_ts or 0) if run_dir else []
            _write_status(run_dir, {"status": next_status, "message": message, "completed_at": _iso_now(), "files": files})
            status = _read_status(run_dir)
        _current_process = None
    if _is_running():
        status["status"] = status.get("status") if status.get("status") == "pause_requested" else "running"
    return status


def start_solve(payload: dict[str, Any]) -> dict[str, Any]:
    global _current_process, _current_run_dir, _current_started_ts
    if _is_running():
        raise RuntimeError("已有求解任务正在运行，请先暂停或等待完成")

    mode = str(payload.get("mode") or "joint")
    if mode not in {"course", "day", "joint", "night"}:
        raise ValueError("mode must be course, day, joint or night")
    readiness = build_solve_readiness(mode)
    if not readiness.get("summary", {}).get("can_start_solver", False):
        blocking = [item for item in readiness.get("items", []) if item.get("blocking") and item.get("severity") == "error"]
        titles = "；".join(str(item.get("title") or "求解前校验未通过") for item in blocking[:3])
        raise RuntimeError(f"求解前校验未通过：{titles or '存在阻断项'}")
    time_limit = max(10, int(float(payload.get("time_limit_seconds") or 300)))
    workers = max(1, int(float(payload.get("workers") or 8)))
    requested_max_keep = max(1, int(float(payload.get("max_keep") or 10)))
    snapshot_interval = max(5, int(float(payload.get("snapshot_interval_sec") or 30)))
    enable_snapshots = bool(payload.get("enable_snapshots", False))
    grade_prefix = str(payload.get("grade_prefix") or "高二")
    random_seed = _payload_random_seed(payload)
    relative_gap_limit = _payload_optional_float(payload, "relative_gap_limit")
    absolute_gap_limit = _payload_optional_float(payload, "absolute_gap_limit")
    log_search_progress = _payload_optional_bool(payload, "log_search_progress")
    continue_from_best = _payload_optional_bool(payload, "continue_from_best") is True
    solver_profile = _payload_solver_profile(payload, continue_from_best=continue_from_best)
    diagnostic_metadata = _diagnostic_run_metadata(payload)
    max_keep = effective_max_keep(requested_max_keep, run_purpose=str(diagnostic_metadata.get("run_purpose") or ""))
    config_fingerprint = build_effective_config_fingerprint(mode)

    run_id = datetime.now().strftime("run_%Y%m%d_%H%M%S")
    run_dir = runtime_web_run_root() / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    log_file = run_dir / "process.log"
    command = [
        sys.executable,
        "-m",
        "scheduler.app.solve_runner",
        "--run-id",
        run_id,
        "--run-dir",
        str(run_dir),
        "--mode",
        mode,
        "--grade-prefix",
        grade_prefix,
        "--time-limit-seconds",
        str(time_limit),
        "--workers",
        str(workers),
        "--max-keep",
        str(max_keep),
        "--snapshot-interval-sec",
        str(snapshot_interval),
    ]
    if random_seed is not None:
        command.extend(["--seed", str(random_seed)])
    if relative_gap_limit is not None:
        command.extend(["--relative-gap-limit", str(relative_gap_limit)])
    if absolute_gap_limit is not None:
        command.extend(["--absolute-gap-limit", str(absolute_gap_limit)])
    if log_search_progress is True:
        command.append("--log-search-progress")
    if solver_profile:
        command.extend(["--solver-profile", solver_profile])
    if enable_snapshots:
        command.append("--enable-snapshots")
    if diagnostic_metadata:
        command.extend(["--run-purpose", diagnostic_metadata["run_purpose"]])
        command.extend(["--diagnostic-plan-id", diagnostic_metadata["diagnostic_plan_id"]])
        command.extend(["--diagnostic-plan-title", diagnostic_metadata["diagnostic_plan_title"]])
        active_relaxations = diagnostic_metadata.get("active_diagnostic_relaxations")
        if isinstance(active_relaxations, list) and active_relaxations:
            command.extend(
                [
                    "--active-diagnostic-relaxations-json",
                    json.dumps(active_relaxations, ensure_ascii=False, separators=(",", ":")),
                ]
            )

    _current_started_ts = time.time()
    with log_file.open("w", encoding="utf-8") as out:
        _current_process = subprocess.Popen(
            command,
            cwd=str(PROJECT_ROOT),
            stdout=out,
            stderr=subprocess.STDOUT,
            text=True,
        )
    _current_run_dir = run_dir
    status_payload = {
        "run_id": run_id,
        "status": "running",
        "mode": mode,
        "grade_prefix": grade_prefix,
        "time_limit_seconds": time_limit,
        "workers": workers,
        "max_keep": max_keep,
        "requested_max_keep": requested_max_keep if requested_max_keep != max_keep else None,
        "max_keep_capped": requested_max_keep != max_keep,
        "max_keep_cap_reason": (
            f"诊断试跑最多保留 {DIAGNOSTIC_MAX_KEEP} 个候选课表，避免排障批次长时间卡在多解 Excel 导出阶段。"
            if requested_max_keep != max_keep
            else ""
        ),
        "snapshot_interval_sec": snapshot_interval,
        "enable_snapshots": enable_snapshots,
        "random_seed": random_seed,
        "relative_gap_limit": relative_gap_limit,
        "absolute_gap_limit": absolute_gap_limit,
        "log_search_progress": log_search_progress,
        "continue_from_best": continue_from_best,
        "solver_profile": solver_profile or "",
        "run_dir": str(run_dir),
        "log_file": str(log_file),
        "process_id": getattr(_current_process, "pid", None),
        "started_at": _iso_now(),
        "message": "求解任务已启动",
        "files": [],
        "config_fingerprint": config_fingerprint,
    }
    status_payload.update(diagnostic_metadata)
    _write_status(run_dir, status_payload)
    return get_solve_status()


def _payload_random_seed(payload: dict[str, Any]) -> int | None:
    raw = payload.get("random_seed", payload.get("seed"))
    if raw is None or str(raw).strip() == "":
        return None
    value = int(float(raw))
    if value < 0:
        raise ValueError("random_seed must be a non-negative integer")
    return value


def _payload_optional_float(payload: dict[str, Any], key: str) -> float | None:
    raw = payload.get(key)
    if raw is None or str(raw).strip() == "":
        return None
    value = float(raw)
    if value < 0:
        raise ValueError(f"{key} must be a non-negative number")
    return value


def _payload_optional_bool(payload: dict[str, Any], key: str) -> bool | None:
    raw = payload.get(key)
    if raw is None or str(raw).strip() == "":
        return None
    if isinstance(raw, bool):
        return raw
    text = str(raw).strip().lower()
    if text in {"1", "true", "yes", "on", "y"}:
        return True
    if text in {"0", "false", "no", "off", "n"}:
        return False
    raise ValueError(f"{key} must be a boolean")


def _payload_solver_profile(payload: dict[str, Any], *, continue_from_best: bool) -> str:
    raw = payload.get("solver_profile", payload.get("optimization_profile"))
    if raw is None or str(raw).strip() == "":
        return "improve_incumbent" if continue_from_best else ""
    value = str(raw).strip().lower().replace("-", "_")
    aliases = {
        "default": "balanced",
        "balanced": "balanced",
        "continue": "improve_incumbent",
        "incumbent": "improve_incumbent",
        "improve": "improve_incumbent",
        "improve_incumbent": "improve_incumbent",
        "prove": "prove_bound",
        "bound": "prove_bound",
        "prove_bound": "prove_bound",
    }
    if value not in aliases:
        raise ValueError(f"unknown solver_profile: {raw!r}")
    return aliases[value]


def _diagnostic_run_metadata(payload: dict[str, Any]) -> dict[str, Any]:
    active_records = _active_diagnostic_relaxation_records(active_relaxation_plans())
    if not bool(payload.get("diagnostic_trial", False)):
        if not active_records:
            return {}
        plan_ids = [str(item.get("id") or "").strip() for item in active_records if str(item.get("id") or "").strip()]
        titles = [str(item.get("title") or item.get("id") or "").strip() for item in active_records if str(item.get("title") or item.get("id") or "").strip()]
        title = "、".join(titles[:3]) or "已应用临时放宽方案"
        if len(titles) > 3:
            title += f" 等 {len(titles)} 项"
        return {
            "run_purpose": "diagnostic_trial",
            "diagnostic_plan_id": ",".join(plan_ids[:5]) or "active_diagnostic_relaxation",
            "diagnostic_plan_title": f"已应用临时放宽方案：{title}",
            "active_diagnostic_relaxations": active_records,
        }
    plan_id = str(payload.get("diagnostic_plan_id") or "").strip()
    if not plan_id:
        raise ValueError("diagnostic_plan_id is required for diagnostic trial")
    title = str(payload.get("diagnostic_plan_title") or plan_id).strip()
    metadata: dict[str, Any] = {
        "run_purpose": "diagnostic_trial",
        "diagnostic_plan_id": plan_id,
        "diagnostic_plan_title": title or plan_id,
    }
    if active_records:
        metadata["active_diagnostic_relaxations"] = active_records
    return metadata


def _active_diagnostic_relaxation_records(plans: list[dict[str, Any]]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for plan in plans:
        if not isinstance(plan, dict):
            continue
        patches = plan.get("patches") if isinstance(plan.get("patches"), list) else []
        records.append(
            {
                "id": str(plan.get("id") or ""),
                "title": str(plan.get("description") or plan.get("title") or plan.get("id") or ""),
                "domain": str(plan.get("domain") or ""),
                "risk": str(plan.get("risk") or ""),
                "patch_count": len([patch for patch in patches if isinstance(patch, dict)]),
                "patches": [
                    {
                        "target": str(patch.get("target") or ""),
                        "path_label": str(patch.get("path_label") or ".".join(str(part) for part in (patch.get("path") or []))),
                        "operation": str(patch.get("operation") or "set"),
                    }
                    for patch in patches
                    if isinstance(patch, dict)
                ],
            }
        )
    return records[:8]


def pause_solve() -> dict[str, Any]:
    run_dir = _latest_run_dir()
    if run_dir is None:
        return {"status": "idle", "message": "暂无求解任务", "files": []}
    if not _is_running():
        return get_solve_status()
    stop_file = run_dir / "STOP_REQUESTED"
    stop_file.write_text(_iso_now(), encoding="utf-8")
    _write_status(
        run_dir,
        {
            "status": "pause_requested",
            "message": "已请求暂停；求解器在捕获到下一个可行解后会停止并导出当前最优解",
            "stop_requested_at": _iso_now(),
        },
    )
    return get_solve_status()


def force_stop_solve() -> dict[str, Any]:
    global _current_process
    run_dir = _latest_run_dir()
    if _is_running() and _current_process is not None:
        _current_process.terminate()
        try:
            _current_process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            _current_process.kill()
        _current_process = None
    if run_dir is not None:
        files = collect_artifacts(run_dir, _current_started_ts or 0)
        _write_status(
            run_dir,
            {
                "status": "stopped",
                "message": "已强制停止；只保留停止前已经导出的结果",
                "completed_at": _iso_now(),
                "files": files,
            },
        )
    return get_solve_status()


def preview_leave_substitution_repair(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    body = payload if isinstance(payload, dict) else {}
    academic = body.get("academic_affairs") if isinstance(body.get("academic_affairs"), dict) else load_academic_affairs_payload()
    return _preview_leave_substitution_repair(
        status=get_solve_status(),
        academic_payload=academic,
        teacher_rows=list_teacher_subject_rows(),
        request=body,
    )


def apply_leave_substitution_repair(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    body = payload if isinstance(payload, dict) else {}
    run_dir = _latest_run_dir()
    if run_dir is None:
        raise RuntimeError("暂无求解批次，无法更新全局课表")
    academic = body.get("academic_affairs") if isinstance(body.get("academic_affairs"), dict) else load_academic_affairs_payload()
    repair = _apply_leave_substitution_repair(
        status=get_solve_status(),
        academic_payload=academic,
        teacher_rows=list_teacher_subject_rows(),
        request=body,
        output_dir=run_dir / "local_repairs",
    )
    _persist_local_timetable_repair(run_dir, repair)
    try:
        package = build_package_for_latest_run()
        repair["package_file"] = str(package)
    except Exception as exc:  # pragma: no cover - package sync depends on current run artifact state
        repair["package_sync_error"] = str(exc)
    refreshed = get_solve_status()
    repair["status"] = refreshed
    return repair


def preview_manual_timetable_adjustment(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    body = payload if isinstance(payload, dict) else {}
    academic = body.get("academic_affairs") if isinstance(body.get("academic_affairs"), dict) else load_academic_affairs_payload()
    return _preview_manual_timetable_adjustment(
        status=get_solve_status(),
        academic_payload=academic,
        request=body,
    )


def apply_manual_timetable_adjustment(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    body = payload if isinstance(payload, dict) else {}
    run_dir = _latest_run_dir()
    if run_dir is None:
        raise RuntimeError("暂无求解批次，无法更新全局课表")
    academic = body.get("academic_affairs") if isinstance(body.get("academic_affairs"), dict) else load_academic_affairs_payload()
    adjustment = _apply_manual_timetable_adjustment(
        status=get_solve_status(),
        academic_payload=academic,
        request=body,
        output_dir=run_dir / "local_adjustments",
    )
    _persist_manual_timetable_adjustment(run_dir, adjustment)
    try:
        package = build_package_for_latest_run()
        adjustment["package_file"] = str(package)
    except Exception as exc:  # pragma: no cover - package sync depends on current run artifact state
        adjustment["package_sync_error"] = str(exc)
    refreshed = get_solve_status()
    adjustment["status"] = refreshed
    return adjustment


def _persist_local_timetable_repair(run_dir: Path, repair: dict[str, Any]) -> None:
    record = repair.get("record") if isinstance(repair.get("record"), dict) else {}
    active_file = str(repair.get("output_file") or record.get("active_file") or "").strip()
    if not active_file:
        raise RuntimeError("局部调课未生成可用课表文件")
    status = _read_status(run_dir)
    history = status.get("local_timetable_repairs") if isinstance(status.get("local_timetable_repairs"), list) else []
    history = [record, *[item for item in history if isinstance(item, dict)]][:20]
    status["local_timetable_repairs"] = history
    status["local_timetable_repair"] = {
        "schema_version": record.get("schema_version") or repair.get("schema_version"),
        "active_file": active_file,
        "applied_at": record.get("applied_at") or _iso_now(),
        "summary": record.get("summary") or repair.get("summary") or {},
        "leave": record.get("leave") or repair.get("leave") or {},
    }
    started_ts, ended_ts = _artifact_collection_window(run_dir, status)
    status["files"] = collect_artifacts(run_dir, started_ts, ended_at_ts=ended_ts)
    status["message"] = "已应用请假日志局部调课，并生成调整后的全局课表。"
    _annotate_file_artifacts(status)
    _write_status(run_dir, status)


def _persist_manual_timetable_adjustment(run_dir: Path, adjustment: dict[str, Any]) -> None:
    record = adjustment.get("record") if isinstance(adjustment.get("record"), dict) else {}
    active_file = str(adjustment.get("output_file") or record.get("active_file") or "").strip()
    if not active_file:
        raise RuntimeError("课表微调未生成可用课表文件")
    status = _read_status(run_dir)
    history = status.get("local_timetable_adjustments") if isinstance(status.get("local_timetable_adjustments"), list) else []
    history = [record, *[item for item in history if isinstance(item, dict)]][:20]
    status["local_timetable_adjustments"] = history
    status["local_timetable_adjustment"] = {
        "schema_version": record.get("schema_version") or adjustment.get("schema_version"),
        "active_file": active_file,
        "applied_at": record.get("applied_at") or _iso_now(),
        "summary": record.get("summary") or adjustment.get("summary") or {},
        "adjustment": record.get("adjustment") or adjustment.get("adjustment") or {},
    }
    started_ts, ended_ts = _artifact_collection_window(run_dir, status)
    status["files"] = collect_artifacts(run_dir, started_ts, ended_at_ts=ended_ts)
    status["message"] = "已应用课表微调，并生成调整后的全局课表。"
    _annotate_file_artifacts(status)
    _write_status(run_dir, status)


def get_solve_status() -> dict[str, Any]:
    status = _refresh_finished_status()
    _drop_legacy_publish_review_state(status)
    run_dir = _latest_run_dir()
    if run_dir is not None:
        log_path = Path(str(status.get("log_file") or run_dir / "run.log"))
        if log_path.exists():
            try:
                text = log_path.read_text(encoding="utf-8", errors="ignore")
                status["log_tail"] = text[-6000:]
            except Exception:
                status["log_tail"] = ""
        if _current_started_ts is not None:
            status["elapsed_seconds"] = max(0, int(time.time() - _current_started_ts))
    mode = str(status.get("mode") or "joint")
    _attach_config_freshness(status, mode if mode in {"course", "day", "joint", "night"} else "joint")
    readiness: dict[str, Any] = {}
    try:
        readiness = build_solve_readiness(mode if mode in {"course", "day", "joint", "night"} else "joint")
    except Exception as exc:
        readiness = {"summary": {"can_publish": False, "errors": 1, "message": f"发布前校验失败：{exc}"}}
    status["current_readiness"] = readiness
    status["publish_assessment"] = build_publish_assessment(status, readiness)
    status["formal_run_comparison"] = build_formal_run_comparison(status, PROJECT_ROOT)
    status["recommended_formal_candidate"] = build_recommended_formal_candidate(status, PROJECT_ROOT)
    status["solve_diagnostics"] = build_solve_diagnostics(status)
    _attach_recommended_formal_candidate_status(status)
    _apply_result_message(status)
    _annotate_file_artifacts(status)
    return status


def _attach_config_freshness(status: dict[str, Any], mode: str) -> None:
    try:
        current = build_effective_config_fingerprint(mode)
    except Exception as exc:
        status["config_freshness"] = {
            "status": "unknown",
            "message": f"当前配置版本校验失败：{exc}",
        }
        status["config_fingerprint_match"] = None
        return

    status["current_config_fingerprint"] = current
    run_hash = _fingerprint_hash(status.get("config_fingerprint"))
    current_hash = _fingerprint_hash(current)
    if not run_hash:
        status["config_fingerprint_match"] = None
        status["config_freshness"] = {
            "status": "unknown",
            "message": "本批次未记录配置版本，无法确认当前配置是否与求解时一致。",
        }
        return

    matched = bool(current_hash and run_hash == current_hash)
    status["config_fingerprint_match"] = matched
    status["config_changed_after_run"] = not matched
    status["config_freshness"] = {
        "status": "matched" if matched else "stale",
        "run_hash": run_hash,
        "current_hash": current_hash,
        "message": "当前配置与求解时一致。" if matched else "当前配置已在本批次求解后发生变化。",
    }


def _fingerprint_hash(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("hash") or "").strip()
    return str(value or "").strip()


def _apply_result_message(status: dict[str, Any]) -> None:
    apply_release_aware_run_message(status)


def build_package_for_latest_run() -> Path:
    run_dir = _latest_run_dir()
    if run_dir is None:
        raise FileNotFoundError("暂无求解任务，无法打包结果")
    return _build_package_for_run_dir(run_dir)


def build_package_for_download() -> tuple[Path, dict[str, Any]]:
    latest_status = get_solve_status()
    run_dir = _recommended_candidate_run_dir(latest_status)
    if run_dir is None:
        run_dir = _latest_run_dir()
    if run_dir is None:
        raise FileNotFoundError("暂无求解任务，无法打包结果")
    package = _build_package_for_run_dir(run_dir, base_status=_read_status(run_dir))
    status = _read_status(run_dir)
    _refresh_status_publish_context(status)
    return package, status


def _build_package_for_run_dir(run_dir: Path, *, base_status: dict[str, Any] | None = None) -> Path:
    raw_status = base_status if isinstance(base_status, dict) else _read_status(run_dir)
    started_ts, ended_ts = _artifact_collection_window(run_dir, raw_status)
    artifacts = _without_manifest_artifacts(collect_artifacts(run_dir, started_ts, ended_at_ts=ended_ts))
    package = run_dir / "result_package.zip"
    manifest_path = run_dir / MANIFEST_FILENAME
    status = _package_status_snapshot(run_dir, artifacts, package, base_status=base_status)
    status["package_file"] = str(package)
    status["delivery_manifest_file"] = str(manifest_path)
    status["files"] = artifacts
    _annotate_file_artifacts(status)
    _write_status(run_dir, status)
    artifacts = _prepend_unique_artifact(_artifact_item(run_dir / "status.json"), artifacts)
    artifacts = _with_archive_names(artifacts, manifest_path=manifest_path, status=status)
    status["files"] = artifacts
    _annotate_file_artifacts(status)
    status["package_integrity"] = build_package_integrity_report(
        artifacts,
        status,
        expected_system_entries=SYSTEM_PACKAGE_ENTRIES,
    )
    _write_status(run_dir, status)
    manifest_path = write_delivery_manifest(run_dir, status, artifacts, package_path=package)
    artifacts = _prepend_system_artifacts(_system_artifact_items(manifest_path), artifacts)
    status["files"] = artifacts
    _annotate_file_artifacts(status)
    _write_status(run_dir, status)
    _write_package_zip(package, artifacts, manifest_path=manifest_path, status=status)
    zip_entries = _zip_entry_names(package)
    manifest_artifacts = [item for item in artifacts if not _is_system_artifact(item)]
    status["package_integrity"] = build_package_integrity_report(
        manifest_artifacts,
        status,
        expected_system_entries=SYSTEM_PACKAGE_ENTRIES,
        zip_entries=zip_entries,
    )
    _refresh_status_publish_context(status)
    _write_status(run_dir, status)
    manifest_path = write_delivery_manifest(run_dir, status, manifest_artifacts, package_path=package)
    artifacts = _prepend_system_artifacts(_system_artifact_items(manifest_path), manifest_artifacts)
    status["files"] = artifacts
    _annotate_file_artifacts(status)
    _write_status(run_dir, status)
    _write_package_zip(package, artifacts, manifest_path=manifest_path, status=status)
    return package


def _recommended_candidate_run_dir(status: dict[str, Any]) -> Path | None:
    status = status if isinstance(status, dict) else {}
    recommendation = status.get("recommended_formal_candidate")
    if not isinstance(recommendation, dict):
        return None
    summary = recommendation.get("summary") if isinstance(recommendation.get("summary"), dict) else {}
    selected_run_id = str(summary.get("selected_run_id") or "").strip()
    current_run_id = str(summary.get("current_run_id") or status.get("run_id") or "").strip()
    if not selected_run_id or selected_run_id == current_run_id:
        return None
    candidate = recommendation.get("candidate") if isinstance(recommendation.get("candidate"), dict) else {}
    raw_dir = str(candidate.get("run_dir") or "").strip()
    if raw_dir:
        path = Path(raw_dir)
        if path.exists() and path.is_dir():
            return path
    raw_status = str(candidate.get("status_file") or "").strip()
    if raw_status:
        path = Path(raw_status)
        if path.name == STATUS_FILENAME and path.exists() and path.is_file():
            return path.parent
    path = runtime_web_run_root() / selected_run_id
    return path if path.exists() and path.is_dir() else None


def _artifact_collection_window(run_dir: Path, status: dict[str, Any]) -> tuple[float, float | None]:
    if _current_started_ts is not None:
        return _current_started_ts, None
    started_ts = _status_datetime_ts(status.get("started_at")) or _run_id_timestamp(run_dir.name)
    ended_ts = _status_datetime_ts(status.get("completed_at"))
    return started_ts if started_ts is not None else 0.0, ended_ts


def _status_datetime_ts(value: Any) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    text = text.replace("T", " ").replace("Z", "")
    if "." in text:
        text = text.split(".", 1)[0]
    for fmt, width in (("%Y-%m-%d %H:%M:%S", 19), ("%Y-%m-%d %H:%M", 16)):
        try:
            return datetime.strptime(text[:width], fmt).timestamp()
        except ValueError:
            continue
    return None


def _run_id_timestamp(run_id: str) -> float | None:
    match = RUN_DIR_PATTERN.fullmatch(str(run_id or ""))
    if not match:
        return None
    try:
        return datetime.strptime(run_id, "run_%Y%m%d_%H%M%S").timestamp()
    except ValueError:
        return None


def package_download_name(status: dict[str, Any] | None = None) -> str:
    status = status if isinstance(status, dict) else get_solve_status()
    run_id = _safe_filename_part(status.get("run_id") or Path(str(status.get("run_dir") or "")).name)
    suffix = f"_{run_id}" if run_id else ""
    publish_summary = status.get("publish_assessment") if isinstance(status.get("publish_assessment"), dict) else {}
    publish_summary = publish_summary.get("summary") if isinstance(publish_summary.get("summary"), dict) else {}
    publish_status = str(publish_summary.get("status") or "")
    if str(status.get("run_purpose") or "") == "diagnostic_trial" or publish_status == "blocked":
        prefix = "排障包"
    elif publish_status == "ready":
        prefix = "正式结果包"
    else:
        prefix = "结果包"
    return f"{prefix}{suffix}.zip"


def file_download_name(path: Path, status: dict[str, Any] | None = None) -> str:
    status = status if isinstance(status, dict) else get_solve_status()
    target = Path(path)
    audit_name = runtime_audit_display_name(target)
    if audit_name and _is_current_run_file(target, status):
        return audit_name
    if not _is_current_run_file(target, status) or not _is_schedule_artifact(target):
        return target.name
    publish_summary = status.get("publish_assessment") if isinstance(status.get("publish_assessment"), dict) else {}
    publish_summary = publish_summary.get("summary") if isinstance(publish_summary.get("summary"), dict) else {}
    publish_status = str(publish_summary.get("status") or "")
    if str(status.get("run_purpose") or "") == "diagnostic_trial":
        prefix = "候选课表_排障参考"
    elif publish_status == "blocked":
        prefix = "不可发布_排障参考"
    else:
        return target.name
    stem = _safe_filename_part(_schedule_download_stem(target.stem)) or "课表"
    suffix = target.suffix if target.suffix else ""
    return f"{prefix}_{stem}{suffix}"


def _package_status_snapshot(
    run_dir: Path,
    artifacts: list[dict[str, Any]],
    package: Path,
    *,
    base_status: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if isinstance(base_status, dict):
        status = dict(base_status)
    else:
        disk_status: dict[str, Any] = {}
        live_status: dict[str, Any] = {}
        try:
            disk_status = _read_status(run_dir)
        except Exception:
            disk_status = {}
        try:
            live_status = get_solve_status()
        except Exception:
            live_status = {}
        if _status_is_placeholder(disk_status) and _status_belongs_to_run(live_status, run_dir):
            status = live_status
        elif _status_belongs_to_run(disk_status, run_dir):
            status = disk_status
        elif _status_belongs_to_run(live_status, run_dir):
            status = live_status
        else:
            status = disk_status or live_status
    # A result directory can outlive the absolute checkout path recorded when
    # the solve originally ran (for example after moving the repository).
    # Rebase package metadata to the directory we are packaging so status.json
    # stays at the ZIP root and all download paths point at the live checkout.
    status["run_dir"] = str(run_dir)
    status["package_file"] = str(package)
    status["files"] = artifacts
    _refresh_status_publish_context(status)
    return status


def _status_belongs_to_run(status: dict[str, Any], run_dir: Path) -> bool:
    if not isinstance(status, dict) or not status:
        return False
    run_id = str(status.get("run_id") or "").strip()
    if run_id and run_id == run_dir.name:
        return True
    raw_run_dir = str(status.get("run_dir") or "").strip()
    if raw_run_dir:
        try:
            return Path(raw_run_dir).resolve() == run_dir.resolve()
        except Exception:
            return False
    return False


def _status_is_placeholder(status: dict[str, Any]) -> bool:
    if not isinstance(status, dict) or not status:
        return True
    if str(status.get("run_id") or "").strip():
        return False
    return str(status.get("status") or "").strip() in {"", "starting", "idle", "unknown"}


def _refresh_status_publish_context(status: dict[str, Any]) -> None:
    _drop_legacy_publish_review_state(status)
    mode = str(status.get("mode") or "joint")
    _attach_config_freshness(status, mode if mode in {"course", "day", "joint", "night"} else "joint")
    try:
        readiness = build_solve_readiness(mode if mode in {"course", "day", "joint", "night"} else "joint")
    except Exception as exc:
        readiness = {"summary": {"can_publish": False, "errors": 1, "message": f"发布前校验失败：{exc}"}}
    status["current_readiness"] = readiness
    status["publish_assessment"] = build_publish_assessment(status, readiness)
    _hydrate_status_solver_quality(status)
    _hydrate_status_objective_breakdown(status)
    status["formal_run_comparison"] = build_formal_run_comparison(status, PROJECT_ROOT)
    status["recommended_formal_candidate"] = build_recommended_formal_candidate(status, PROJECT_ROOT)
    status["solve_diagnostics"] = build_solve_diagnostics(status)
    attach_result_availability(status)
    _attach_recommended_formal_candidate_status(status)
    _apply_result_message(status)
    _annotate_file_artifacts(status)


def _drop_legacy_publish_review_state(status: dict[str, Any]) -> None:
    if not isinstance(status, dict):
        return
    for key in LEGACY_PUBLISH_REVIEW_STATUS_KEYS:
        status.pop(key, None)


def _attach_recommended_formal_candidate_status(status: dict[str, Any]) -> None:
    run_dir = _recommended_candidate_run_dir(status)
    if run_dir is None:
        return
    try:
        candidate_status = _read_status(run_dir)
    except Exception:
        return
    if not isinstance(candidate_status, dict) or not candidate_status:
        return
    candidate_status.setdefault("run_dir", str(run_dir))
    recommendation = status.get("recommended_formal_candidate")
    if not isinstance(recommendation, dict):
        return
    recommendation["status_snapshot"] = _recommended_formal_status_snapshot(candidate_status)


def _recommended_formal_status_snapshot(status: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "run_id",
        "run_dir",
        "status",
        "mode",
        "message",
        "started_at",
        "completed_at",
        "elapsed_seconds",
        "solver_status",
        "solution_count",
        "schedule_file_count",
        "objective_value",
        "best_bound",
        "objective_gap",
        "gap_percent",
        "optimality_status",
        "solver_profile",
        "config_fingerprint",
        "current_config_fingerprint",
        "config_fingerprint_match",
        "config_freshness",
        "publish_assessment",
        "release_state",
        "result_availability",
        "package_integrity",
        "package_file",
        "delivery_manifest_file",
        "files",
        "solve_diagnostics",
        "objective_breakdown",
        "formal_run_comparison",
    )
    return {key: copy.deepcopy(status[key]) for key in keys if key in status}


def _hydrate_status_solver_quality(status: dict[str, Any]) -> None:
    assessment = status.get("publish_assessment") if isinstance(status.get("publish_assessment"), dict) else {}
    outcome = assessment.get("outcome") if isinstance(assessment.get("outcome"), dict) else {}
    for key in ("solver_status", "solution_count", "best_objective"):
        if not _has_value(status.get(key)) and _has_value(outcome.get(key)):
            status[key] = outcome.get(key)
    if not _has_value(status.get("objective_value")):
        status["objective_value"] = _first_present(outcome.get("objective_value"), status.get("best_objective"), outcome.get("best_objective"))
    if not _has_value(status.get("best_bound")):
        status["best_bound"] = _first_present(outcome.get("best_bound"))
    quality = solver_quality_fields(
        _first_present(status.get("objective_value"), status.get("best_objective")),
        status.get("best_bound"),
        solver_status=str(status.get("solver_status") or outcome.get("solver_status") or ""),
    )
    for key in ("objective_gap", "gap_percent", "optimality_status"):
        if not _has_value(status.get(key)):
            status[key] = _first_present(outcome.get(key), quality.get(key))


def _hydrate_status_objective_breakdown(status: dict[str, Any]) -> None:
    try:
        status["objective_breakdown"] = build_rule_explain(status, PROJECT_ROOT)
    except Exception as exc:
        status["objective_breakdown"] = {
            "schema_version": "scheduler.result_rule_explain.v1",
            "summary": {
                "status": "error",
                "status_label": "解释失败",
                "message": f"目标值分解生成失败：{exc}",
                "total_penalty": 0,
                "reward_credit": 0,
                "net_event_penalty": 0,
                "solver_objective_value": None,
                "objective_explain_delta": None,
                "objective_reconciliation_status": "unavailable",
                "rule_count": 0,
                "source": "",
                "source_label": "",
            },
            "top": [],
        }


def _has_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str) and not value.strip():
        return False
    return True


def _first_present(*values: Any) -> Any:
    for value in values:
        if _has_value(value):
            return value
    return None


def _annotate_file_artifacts(status: dict[str, Any]) -> None:
    files = status.get("files") if isinstance(status.get("files"), list) else []
    for item in files:
        if not isinstance(item, dict):
            continue
        path = Path(str(item.get("path") or ""))
        category = _artifact_category(item, path)
        item["category"] = category
        item["release_use"] = _artifact_release_use(category, status)
        if is_runtime_audit_artifact(path):
            item["release_use"] = RUNTIME_AUDIT_RELEASE_USE
        item["display_label"] = _artifact_display_label_for_status(item, path, status, category)
        item["download_name"] = file_download_name(path, status) if str(item.get("path") or "") else item["display_label"]
        if category == "schedule":
            item["release_badge"] = _schedule_release_badge(status)
    attach_result_availability(status)


def _artifact_category(item: dict[str, Any], path: Path) -> str:
    source = str(item.get("label") or item.get("path") or path).replace("\\", "/")
    filename = source.rsplit("/", 1)[-1].lower()
    lower = source.lower()
    if filename.endswith(".zip") or "result_package" in filename:
        return "package"
    if is_runtime_audit_artifact(filename or path):
        return "diagnostic"
    if any(token in lower for token in ("诊断", "审计", "diagnostic", "audit", "checklist", "penalty", "conflict", "violation")):
        return "diagnostic"
    if _is_schedule_artifact(path):
        return "schedule"
    if filename.endswith((".log", ".json", ".txt")) or any(token in filename for token in ("meta", "summary", "config_diff")):
        return "log"
    return "other"


def _artifact_release_use(category: str, status: dict[str, Any]) -> str:
    publish_summary = status.get("publish_assessment") if isinstance(status.get("publish_assessment"), dict) else {}
    publish_summary = publish_summary.get("summary") if isinstance(publish_summary.get("summary"), dict) else {}
    publish_status = str(publish_summary.get("status") or "")
    diagnostic = str(status.get("run_purpose") or "") == "diagnostic_trial"
    if category == "schedule":
        if diagnostic:
            return "troubleshooting_reference"
        if publish_status == "blocked":
            return "unpublishable_reference"
        if publish_status in {"ready", "review"}:
            return "official_delivery"
        return "generated_schedule"
    if category == "package":
        if diagnostic or publish_status == "blocked":
            return "troubleshooting_archive"
        if publish_status in {"ready", "review"}:
            return "official_archive"
        return "archive"
    if category == "diagnostic":
        return "diagnostic_material"
    if category == "log":
        return "run_evidence"
    return "supporting_material"


def _artifact_display_label_for_status(item: dict[str, Any], path: Path, status: dict[str, Any], category: str) -> str:
    source = str(item.get("label") or item.get("path") or path.name)
    audit_name = runtime_audit_display_name(path)
    if audit_name:
        return audit_name
    if category != "schedule":
        return source
    renamed = file_download_name(path, status)
    return renamed if renamed != path.name else source


def _schedule_release_badge(status: dict[str, Any]) -> str:
    publish_summary = status.get("publish_assessment") if isinstance(status.get("publish_assessment"), dict) else {}
    publish_summary = publish_summary.get("summary") if isinstance(publish_summary.get("summary"), dict) else {}
    publish_status = str(publish_summary.get("status") or "")
    if str(status.get("run_purpose") or "") == "diagnostic_trial":
        return "排障参考"
    if publish_status == "blocked":
        return "不可发布"
    if publish_status == "ready":
        return "正式交付"
    return ""


def _safe_filename_part(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    safe = re.sub(r'[\\/:*?"<>|\s]+', "_", text)
    safe = re.sub(r"_+", "_", safe).strip("._ ")
    return safe[:80]


def _is_current_run_file(path: Path, status: dict[str, Any]) -> bool:
    run_dir = str(status.get("run_dir") or "").strip()
    if not run_dir:
        return False
    try:
        target = path.resolve()
        root = Path(run_dir).resolve()
    except OSError:
        return False
    return target == root or root in target.parents


def _is_schedule_artifact(path: Path) -> bool:
    source = str(path).replace("\\", "/").lower()
    filename = path.name.lower()
    if not filename.endswith((".xlsx", ".xls", ".csv")):
        return False
    if any(token in source for token in ("诊断", "审计", "diagnostic", "audit", "checklist", "penalty", "conflict", "violation")):
        return False
    return (
        "课表" in source
        or any(token in source for token in ("最优解", "全局最优", "正式版"))
        or any(token in filename for token in ("schedule", "timetable", "teacher", "class"))
    )


def _schedule_download_stem(stem: str) -> str:
    text = str(stem or "")
    replacements = (
        ("最终全局最优解_正式版", "最终全局最优解"),
        ("最终全局最优解", "最终全局最优解"),
        ("_正式版", ""),
        ("正式版", ""),
    )
    for old, new in replacements:
        text = text.replace(old, new)
    return text.strip("_ -") or stem


def _artifact_item(path: Path) -> dict[str, Any]:
    stat = path.stat()
    try:
        label = str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        label = path.name
    return {
        "label": label,
        "path": str(path.resolve()),
        "size": int(stat.st_size),
        "modified_at": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
    }


def _system_artifact_items(manifest_path: Path) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    if manifest_path.exists():
        item = _artifact_item(manifest_path)
        item["archive_name"] = MANIFEST_FILENAME
        items.append(item)
    return items


def _package_arcname(path: Path, *, manifest_path: Path, status: dict[str, Any] | None = None) -> Path:
    if path.resolve() == manifest_path.resolve():
        return Path(MANIFEST_FILENAME)
    if _is_current_run_status_file(path, status):
        return Path(STATUS_FILENAME)
    try:
        arcname = path.relative_to(PROJECT_ROOT)
    except ValueError:
        arcname = Path(path.name)
    renamed = file_download_name(path, status or {})
    if renamed != path.name:
        arcname = arcname.with_name(renamed)
    return arcname


def _unique_arcname(arcname: Path, used: set[str]) -> Path:
    key = str(arcname).replace("\\", "/")
    if key not in used:
        used.add(key)
        return arcname
    parent = arcname.parent
    stem = arcname.stem
    suffix = arcname.suffix
    counter = 2
    while True:
        candidate = parent / f"{stem}_{counter}{suffix}"
        candidate_key = str(candidate).replace("\\", "/")
        if candidate_key not in used:
            used.add(candidate_key)
            return candidate
        counter += 1


def _with_archive_names(
    artifacts: list[dict[str, Any]],
    *,
    manifest_path: Path,
    status: dict[str, Any],
) -> list[dict[str, Any]]:
    used_arcnames: set[str] = set()
    out: list[dict[str, Any]] = []
    for artifact in artifacts:
        item = dict(artifact)
        path = Path(str(item.get("path") or ""))
        if path.exists() and path.is_file():
            arcname = _unique_arcname(_package_arcname(path, manifest_path=manifest_path, status=status), used_arcnames)
            item["archive_name"] = str(arcname).replace("\\", "/")
        out.append(item)
    return out


def _is_current_run_status_file(path: Path, status: dict[str, Any] | None) -> bool:
    if path.name != STATUS_FILENAME or not isinstance(status, dict):
        return False
    run_dir = str(status.get("run_dir") or "").strip()
    if not run_dir:
        return False
    try:
        return path.resolve() == (Path(run_dir).resolve() / STATUS_FILENAME)
    except OSError:
        return False


def build_package_integrity_report(
    artifacts: list[dict[str, Any]],
    status: dict[str, Any],
    *,
    expected_system_entries: list[str] | None = None,
    zip_entries: list[str] | None = None,
) -> dict[str, Any]:
    artifact_rows = [item for item in artifacts if isinstance(item, dict)]
    system_entries = [_normalize_archive_name(name) for name in (expected_system_entries or []) if _normalize_archive_name(name)]
    archive_names = [_normalize_archive_name(item.get("archive_name")) for item in artifact_rows]
    archive_names = [name for name in archive_names if name]
    expected_entries = archive_names + system_entries
    expected_counts = Counter(expected_entries)
    issues: list[dict[str, str]] = []

    missing_archive_labels = [
        _artifact_integrity_label(item)
        for item in artifact_rows
        if not _normalize_archive_name(item.get("archive_name"))
    ]
    if missing_archive_labels:
        issues.append(_package_integrity_issue(
            "error",
            "清单缺少包内文件名",
            f"{len(missing_archive_labels)} 个文件没有 archive_name，解压后无法从交付清单精确定位。",
            "重新生成结果包；若仍出现该问题，检查打包服务的文件归档映射。",
            missing_archive_labels,
        ))

    missing_file_labels = [
        _artifact_integrity_label(item)
        for item in artifact_rows
        if not _artifact_path_exists(item)
    ]
    if missing_file_labels:
        issues.append(_package_integrity_issue(
            "error",
            "清单指向的文件不存在",
            f"{len(missing_file_labels)} 个清单文件在磁盘上不存在，结果包可能缺失材料。",
            "重新刷新求解状态并生成结果包；若文件被手动删除，需要重新求解或恢复运行目录。",
            missing_file_labels,
        ))

    duplicate_expected = sorted(name for name, count in expected_counts.items() if count > 1)
    if duplicate_expected:
        issues.append(_package_integrity_issue(
            "error",
            "包内文件名重复",
            f"{len(duplicate_expected)} 个 archive_name 重复，解压后可能覆盖文件。",
            "重新生成结果包；系统应自动追加序号，若仍重复需要检查归档命名逻辑。",
            duplicate_expected,
        ))

    forbidden_labels = [
        _artifact_integrity_label(item)
        for item in artifact_rows
        if _artifact_has_forbidden_release_name(item)
    ]
    if forbidden_labels:
        issues.append(_package_integrity_issue(
            "error",
            "候选课表仍含正式版字样",
            f"{len(forbidden_labels)} 个不可发布课表的展示名或包内名仍含正式版字样。",
            "不要交付当前结果包；先重新生成包并确认课表文件被标记为候选或排障参考。",
            forbidden_labels,
        ))

    zip_verified = zip_entries is not None
    zip_names = [_normalize_archive_name(name) for name in (zip_entries or []) if _normalize_archive_name(name)]
    missing_zip_entries: list[str] = []
    unexpected_zip_entries: list[str] = []
    duplicate_zip_entries: list[str] = []
    if zip_verified:
        zip_counts = Counter(zip_names)
        missing_zip_entries = sorted(name for name, count in expected_counts.items() if zip_counts.get(name, 0) < count)
        unexpected_zip_entries = sorted(name for name in zip_counts if name not in expected_counts)
        duplicate_zip_entries = sorted(name for name, count in zip_counts.items() if count > 1)
        if missing_zip_entries:
            issues.append(_package_integrity_issue(
                "error",
                "ZIP 缺少清单文件",
                f"{len(missing_zip_entries)} 个清单条目没有写入 ZIP。",
                "不要使用当前结果包；重新生成后再次下载。",
                missing_zip_entries,
            ))
        if duplicate_zip_entries:
            issues.append(_package_integrity_issue(
                "error",
                "ZIP 内部条目重复",
                f"{len(duplicate_zip_entries)} 个 ZIP 条目重复，解压行为可能不一致。",
                "重新生成结果包；若仍重复需要检查归档去重逻辑。",
                duplicate_zip_entries,
            ))
        if unexpected_zip_entries:
            issues.append(_package_integrity_issue(
                "warning",
                "ZIP 存在清单外文件",
                f"{len(unexpected_zip_entries)} 个 ZIP 条目没有出现在交付清单中。",
                "下载前检查这些额外文件是否应纳入清单，必要时重新生成结果包。",
                unexpected_zip_entries,
            ))

    if any(issue["severity"] == "error" for issue in issues):
        report_status = "error"
        status_label = "异常"
        message = "结果包清单或 ZIP 条目存在异常，不能作为可靠交付物。"
    elif issues:
        report_status = "warning"
        status_label = "需检查"
        message = "结果包可生成，但存在需要检查的清单差异。"
    elif zip_verified:
        report_status = "ok"
        status_label = "已校验"
        message = "结果包清单、包内条目和发布语义一致。"
    else:
        report_status = "pending"
        status_label = "待写包"
        message = "结果包清单已生成，等待 ZIP 写入后完成校验。"

    return {
        "schema_version": "scheduler.package_integrity.v1",
        "checked_at": _iso_now(),
        "status": report_status,
        "status_label": status_label,
        "message": message,
        "checks": {
            "artifact_count": len(artifact_rows),
            "archive_name_count": len(archive_names),
            "expected_zip_entries": len(expected_entries),
            "zip_verified": zip_verified,
            "zip_entry_count": len(zip_names) if zip_verified else None,
            "missing_archive_names": len(missing_archive_labels),
            "missing_files": len(missing_file_labels),
            "duplicate_archive_names": len(duplicate_expected),
            "forbidden_release_names": len(forbidden_labels),
            "missing_zip_entries": len(missing_zip_entries),
            "unexpected_zip_entries": len(unexpected_zip_entries),
            "duplicate_zip_entries": len(duplicate_zip_entries),
        },
        "issues": issues[:12],
    }


def _write_package_zip(
    package: Path,
    artifacts: list[dict[str, Any]],
    *,
    manifest_path: Path,
    status: dict[str, Any],
) -> None:
    with zipfile.ZipFile(package, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for item in artifacts:
            path = Path(str(item.get("path") or ""))
            if not path.exists() or path.resolve() == package.resolve():
                continue
            arcname = Path(str(item.get("archive_name") or _package_arcname(path, manifest_path=manifest_path, status=status)))
            zf.write(path, arcname=str(arcname))


def _zip_entry_names(package: Path) -> list[str]:
    with zipfile.ZipFile(package) as zf:
        return [str(name).replace("\\", "/") for name in zf.namelist()]


def _normalize_archive_name(value: Any) -> str:
    return str(value or "").replace("\\", "/").strip().strip("/")


def _artifact_path_exists(item: dict[str, Any]) -> bool:
    raw_path = str(item.get("path") or "")
    if not raw_path:
        return False
    path = Path(raw_path)
    return path.exists() and path.is_file()


def _artifact_integrity_label(item: dict[str, Any]) -> str:
    return str(item.get("display_label") or item.get("label") or item.get("archive_name") or item.get("path") or "未命名文件")


def _artifact_has_forbidden_release_name(item: dict[str, Any]) -> bool:
    if str(item.get("category") or "") != "schedule":
        return False
    if str(item.get("release_use") or "") not in {"troubleshooting_reference", "unpublishable_reference"}:
        return False
    visible_names = (
        str(item.get("archive_name") or ""),
        str(item.get("display_label") or ""),
        str(item.get("download_name") or ""),
    )
    return any("正式版" in name for name in visible_names)


def _package_integrity_issue(
    severity: str,
    title: str,
    detail: str,
    suggestion: str,
    examples: list[str],
) -> dict[str, str]:
    return {
        "severity": severity,
        "title": title,
        "detail": detail,
        "suggestion": suggestion,
        "examples": "；".join(str(item) for item in examples[:5]),
    }


def _without_manifest_artifacts(artifacts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [artifact for artifact in artifacts if not _is_system_artifact(artifact)]


def _prepend_artifact(item: dict[str, Any], artifacts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    item_path = str(item.get("path") or "")
    return [item, *[artifact for artifact in artifacts if str(artifact.get("path") or "") != item_path and not _is_system_artifact(artifact)]]


def _prepend_system_artifacts(system_items: list[dict[str, Any]], artifacts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for item in [*system_items, *artifacts]:
        path = str(item.get("path") or "")
        key = str(Path(path).resolve()) if path else str(item)
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _prepend_unique_artifact(item: dict[str, Any], artifacts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    item_path = str(item.get("path") or "")
    return [item, *[artifact for artifact in artifacts if str(artifact.get("path") or "") != item_path]]


def _is_manifest_artifact(artifact: dict[str, Any]) -> bool:
    source = str(artifact.get("label") or artifact.get("path") or "").replace("\\", "/")
    return source.rsplit("/", 1)[-1] == MANIFEST_FILENAME


def _is_system_artifact(artifact: dict[str, Any]) -> bool:
    source = str(artifact.get("label") or artifact.get("path") or "").replace("\\", "/")
    return source.rsplit("/", 1)[-1] == MANIFEST_FILENAME
