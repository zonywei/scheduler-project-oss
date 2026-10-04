# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

from scheduler.app.config_service import IO_PATH, PROJECT_ROOT, RULES_PATH, build_effective_config_fingerprint
from scheduler.app.delivery_manifest import MANIFEST_FILENAME, write_delivery_manifest
from scheduler.app.diagnostic_comparison import build_diagnostic_comparison
from scheduler.app.formal_run_history import build_formal_run_comparison, build_recommended_formal_candidate
from scheduler.app.publish_assessment import build_publish_assessment
from scheduler.app.readiness import build_solve_readiness
from scheduler.app.release_messages import apply_release_aware_run_message
from scheduler.app.result_availability import attach_result_availability
from scheduler.app.rule_explain import build_rule_explain
from scheduler.app.solve_diagnostics import build_solve_diagnostics
from scheduler.config.loader import runtime_config_overrides
from scheduler.scheduler_core import SchedulerCore
from scheduler.solver_quality import solver_quality_fields


STATUS_FILENAME = "status.json"
DIAGNOSTIC_MAX_KEEP = 3


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _json_list_arg(value: str) -> list[dict[str, Any]]:
    if not str(value or "").strip():
        return []
    try:
        data = json.loads(str(value))
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict)]


def effective_max_keep(requested: int, *, run_purpose: str = "") -> int:
    value = max(1, int(requested))
    if str(run_purpose or "") == "diagnostic_trial":
        return min(value, DIAGNOSTIC_MAX_KEEP)
    return value


def _max_keep_status_fields(requested: int, effective: int, *, run_purpose: str = "") -> dict[str, Any]:
    if requested == effective:
        return {}
    return {
        "requested_max_keep": requested,
        "max_keep_capped": True,
        "max_keep_cap_reason": (
            f"诊断试跑最多保留 {DIAGNOSTIC_MAX_KEEP} 个候选课表，避免排障批次长时间卡在多解 Excel 导出阶段。"
            if str(run_purpose or "") == "diagnostic_trial"
            else ""
        ),
    }


def _iso_now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _file_item(path: Path, base: Path) -> dict[str, Any]:
    stat = path.stat()
    try:
        label = str(path.relative_to(base))
    except ValueError:
        label = path.name
    return {
        "label": label,
        "path": str(path.resolve()),
        "size": int(stat.st_size),
        "modified_at": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
    }


def _safe_mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return -1.0


def collect_artifacts(run_dir: Path, started_at_ts: float, ended_at_ts: float | None = None) -> list[dict[str, Any]]:
    output_dir = PROJECT_ROOT / "outputs"
    patterns = ("*.xlsx", "*.json", "*.yaml", "*.yml", "*.txt", "*.csv", "*.log", "*.zip")
    files: list[Path] = []
    for root in (run_dir, output_dir):
        if not root.exists():
            continue
        for pattern in patterns:
            files.extend(path for path in root.rglob(pattern) if path.is_file())
    unique: dict[str, Path] = {}
    for path in files:
        if path.name == "result_package.zip":
            continue
        try:
            mtime = path.stat().st_mtime
            if run_dir not in path.parents:
                if mtime + 2 < started_at_ts:
                    continue
                if ended_at_ts is not None and mtime > ended_at_ts + 2:
                    continue
        except OSError:
            continue
        unique[str(path.resolve())] = path
    artifacts: list[dict[str, Any]] = []
    for path in sorted(unique.values(), key=_safe_mtime, reverse=True):
        try:
            artifacts.append(_file_item(path, PROJECT_ROOT))
        except OSError:
            continue
    return artifacts


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""


def _first_match(text: str, pattern: str) -> str | None:
    match = re.search(pattern, text)
    return match.group(1).strip() if match else None


def _read_run_summary(files: list[dict[str, Any]]) -> dict[str, Any]:
    for item in files:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or item.get("path") or "").replace("\\", "/")
        if not label.endswith("run_summary.json"):
            continue
        path = Path(str(item.get("path") or ""))
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}
    return {}


def _read_solver_overview(files: list[dict[str, Any]]) -> dict[str, Any]:
    candidates: list[Path] = []
    for item in files:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or item.get("path") or "").replace("\\", "/")
        if not label.endswith("final_solver_overview.json"):
            continue
        path = Path(str(item.get("path") or ""))
        if path.exists() and path.is_file():
            candidates.append(path)
    if not candidates:
        return {}
    latest = max(candidates, key=lambda path: path.stat().st_mtime)
    data = _read_json(latest)
    return data if isinstance(data, dict) else {}


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


def _schedule_file_count(files: list[dict[str, Any]]) -> int:
    count = 0
    for item in files:
        if not isinstance(item, dict):
            continue
        path = Path(str(item.get("path") or ""))
        if _is_schedule_artifact(path):
            count += 1
    return count


def _solution_count_from(log: str, summary: dict[str, Any], solver_overview: dict[str, Any] | None = None) -> int | None:
    raw = _first_match(log, r"回调捕获解数量：(\d+)") or _first_match(log, r"top_count=(\d+)")
    if raw is None:
        overview = solver_overview if isinstance(solver_overview, dict) else {}
        for key in ("solution_count", "solutions_seen", "total_solutions_seen", "callback_solution_count"):
            value = overview.get(key)
            if isinstance(value, int):
                raw = str(value)
                break
    if raw is None:
        for key in ("top_exported", "kept_solutions", "captured"):
            value = summary.get(key)
            if isinstance(value, int):
                raw = str(value)
                break
    return int(raw) if str(raw or "").isdigit() else None


def _completed_message(
    *,
    solver_status: str,
    solution_count: int | None,
    schedule_file_count: int,
    run_purpose: str,
) -> str:
    if solver_status == "INFEASIBLE":
        return "求解器判定当前规则组合不可行，未生成可交付课表文件。"
    if isinstance(solution_count, int) and solution_count <= 0 and schedule_file_count <= 0:
        return "求解已结束，但未捕获可行解，未生成可交付课表文件。"
    if run_purpose == "diagnostic_trial" and schedule_file_count > 0:
        return "诊断试跑已生成候选课表，但包含临时放宽规则，不能直接作为交付版本。"
    if schedule_file_count > 0:
        return "求解完成，已发现可交付课表文件。"
    return "求解已结束，请查看诊断材料和日志确认结果。"


def completion_status_updates(files: list[dict[str, Any]], log_path: Path, *, run_purpose: str = "") -> dict[str, Any]:
    log = _read_text(log_path)
    summary = _read_run_summary(files)
    solver_overview = _read_solver_overview(files)
    solver_status = (
        _first_match(log, r"求解状态：([A-Z_]+)")
        or _first_match(log, r"status\s*=\s*([A-Z_]+)")
        or str(solver_overview.get("solver_status") or "")
    )
    solution_count = _solution_count_from(log, summary, solver_overview)
    schedule_count = _schedule_file_count(files)
    objective = solver_overview.get("objective_value", summary.get("best_objective"))
    best_bound = solver_overview.get("best_bound")
    best_objective = summary.get("best_objective")
    if best_objective is None:
        best_objective = objective
    quality = solver_quality_fields(objective, best_bound, solver_status=solver_status)
    return {
        "message": _completed_message(
            solver_status=solver_status,
            solution_count=solution_count,
            schedule_file_count=schedule_count,
            run_purpose=str(run_purpose or ""),
        ),
        "solver_status": solver_status,
        "solution_count": solution_count,
        "schedule_file_count": schedule_count,
        "best_objective": best_objective,
        "objective_value": objective,
        "best_bound": best_bound,
        **quality,
    }


def build_result_package(run_dir: Path, started_at_ts: float, ended_at_ts: float | None = None) -> Path:
    package = run_dir / "result_package.zip"
    status_path = run_dir / "status.json"
    artifacts = _without_manifest_artifacts(collect_artifacts(run_dir, started_at_ts, ended_at_ts=ended_at_ts))
    status = _read_json(status_path)
    status["run_id"] = str(status.get("run_id") or run_dir.name)
    status["package_file"] = str(package)
    status["delivery_manifest_file"] = str(run_dir / MANIFEST_FILENAME)
    status["files"] = artifacts
    _refresh_status_publish_context(status)

    manifest_path = write_delivery_manifest(run_dir, status, artifacts, package_path=package)
    package_artifacts = _prepend_system_artifacts(_system_package_entries(manifest_path), artifacts)
    status["package_integrity"] = _basic_package_integrity_report(package_artifacts, zip_entries=None)
    _write_json(status_path, status)

    package_artifacts = _prepend_system_artifacts(_system_package_entries(manifest_path), artifacts)
    _write_package(package, package_artifacts)
    zip_entries = _zip_entry_names(package)
    status["package_integrity"] = _basic_package_integrity_report(package_artifacts, zip_entries=zip_entries)
    _refresh_status_publish_context(status)
    write_delivery_manifest(run_dir, status, artifacts, package_path=package)
    package_artifacts = _prepend_system_artifacts(_system_package_entries(manifest_path), artifacts)
    status["files"] = package_artifacts
    _write_json(status_path, status)
    _write_package(package, package_artifacts)
    return package


def _refresh_status_publish_context(status: dict[str, Any]) -> None:
    mode = str(status.get("mode") or "joint")
    _hydrate_status_config_freshness(status, mode=mode)
    try:
        readiness = build_solve_readiness(mode if mode in {"joint", "night"} else "joint")
    except Exception as exc:
        readiness = {"summary": {"can_publish": False, "errors": 1, "message": f"发布前校验失败：{exc}"}}
    status["current_readiness"] = readiness
    status["publish_assessment"] = build_publish_assessment(status, readiness)
    _hydrate_status_solver_quality(status)
    _hydrate_status_objective_breakdown(status)
    status["formal_run_comparison"] = build_formal_run_comparison(status, PROJECT_ROOT)
    status["recommended_formal_candidate"] = build_recommended_formal_candidate(status, PROJECT_ROOT)
    status["diagnostic_comparison"] = build_diagnostic_comparison(status, PROJECT_ROOT)
    status["solve_diagnostics"] = build_solve_diagnostics(status)
    apply_release_aware_run_message(status)
    attach_result_availability(status)


def _hydrate_status_config_freshness(status: dict[str, Any], *, mode: str) -> None:
    try:
        current = build_effective_config_fingerprint(mode if mode in {"joint", "night"} else "joint")
    except Exception:
        return
    status["current_config_fingerprint"] = current
    run_hash = _fingerprint_hash(status.get("config_fingerprint"))
    current_hash = _fingerprint_hash(current)
    if not run_hash:
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


def _hydrate_status_solver_quality(status: dict[str, Any]) -> None:
    assessment = status.get("publish_assessment") if isinstance(status.get("publish_assessment"), dict) else {}
    outcome = assessment.get("outcome") if isinstance(assessment.get("outcome"), dict) else {}
    for key in ("solver_status", "solution_count", "best_objective"):
        if not _has_value(status.get(key)) and _has_value(outcome.get(key)):
            status[key] = outcome.get(key)
    if not _has_value(status.get("objective_value")):
        status["objective_value"] = _first_present(outcome.get("objective_value"), status.get("best_objective"), outcome.get("best_objective"))
    if "best_bound" not in status or not _has_value(status.get("best_bound")):
        status["best_bound"] = _first_present(outcome.get("best_bound"))
    quality = solver_quality_fields(
        _first_present(status.get("objective_value"), status.get("best_objective")),
        status.get("best_bound"),
        solver_status=str(status.get("solver_status") or outcome.get("solver_status") or ""),
    )
    for key in ("objective_gap", "gap_percent", "optimality_status"):
        if _has_value(status.get(key)):
            continue
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


def _fingerprint_hash(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("hash") or "").strip()
    return str(value or "").strip()


def _write_package(package: Path, artifacts: list[dict[str, Any]]) -> None:
    with zipfile.ZipFile(package, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for item in artifacts:
            path = Path(str(item.get("path") or ""))
            if not path.exists() or path.resolve() == package.resolve():
                continue
            arcname = str(item.get("archive_name") or _package_arcname(path))
            zf.write(path, arcname=arcname)


def _system_package_entries(manifest_path: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    if manifest_path.exists():
        entries.append(_file_item(manifest_path, PROJECT_ROOT))
    status_path = manifest_path.parent / STATUS_FILENAME
    if status_path.exists():
        item = _file_item(status_path, PROJECT_ROOT)
        item["archive_name"] = STATUS_FILENAME
        entries.append(item)
    return entries


def _prepend_system_artifacts(system_items: list[dict[str, Any]], artifacts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for item in [*system_items, *artifacts]:
        key = str(Path(str(item.get("path") or "")).resolve()) if str(item.get("path") or "") else str(item)
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _without_manifest_artifacts(artifacts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in artifacts:
        source = str(item.get("label") or item.get("path") or "").replace("\\", "/")
        if source.rsplit("/", 1)[-1] == MANIFEST_FILENAME:
            continue
        out.append(item)
    return out


def _package_arcname(path: Path) -> str:
    if path.name == MANIFEST_FILENAME:
        return MANIFEST_FILENAME
    try:
        return str(path.relative_to(PROJECT_ROOT)).replace("\\", "/")
    except ValueError:
        return path.name


def _zip_entry_names(package: Path) -> list[str]:
    with zipfile.ZipFile(package) as zf:
        return [str(name).replace("\\", "/") for name in zf.namelist()]


def _basic_package_integrity_report(
    artifacts: list[dict[str, Any]],
    *,
    zip_entries: list[str] | None,
) -> dict[str, Any]:
    expected = []
    missing_files = 0
    for item in artifacts:
        path = Path(str(item.get("path") or ""))
        if not path.exists() or not path.is_file():
            missing_files += 1
            continue
        expected.append(str(item.get("archive_name") or _package_arcname(path)))
    expected_set = set(expected)
    zip_set = set(zip_entries or [])
    missing_zip_entries = sorted(expected_set - zip_set) if zip_entries is not None else []
    unexpected_zip_entries = sorted(zip_set - expected_set) if zip_entries is not None else []
    duplicate_zip_entries = len(zip_entries or []) - len(zip_set) if zip_entries is not None else 0
    has_error = bool(missing_files or missing_zip_entries or duplicate_zip_entries)
    status = "error" if has_error else ("warning" if unexpected_zip_entries else ("ok" if zip_entries is not None else "pending"))
    return {
        "schema_version": "scheduler.package_integrity.v1",
        "checked_at": _iso_now(),
        "status": status,
        "status_label": {"ok": "已校验", "warning": "需复核", "error": "异常", "pending": "待写包"}[status],
        "message": "结果包已包含交付清单和运行状态。" if status == "ok" else "结果包清单或 ZIP 条目需要复核。",
        "checks": {
            "artifact_count": len(artifacts),
            "expected_zip_entries": len(expected),
            "zip_verified": zip_entries is not None,
            "zip_entry_count": len(zip_entries or []),
            "missing_files": missing_files,
            "missing_zip_entries": len(missing_zip_entries),
            "unexpected_zip_entries": len(unexpected_zip_entries),
            "duplicate_zip_entries": duplicate_zip_entries,
        },
        "issues": [],
    }


def _status_update(status_path: Path, **updates: Any) -> dict[str, Any]:
    payload = _read_json(status_path)
    payload.update(updates)
    payload["updated_at"] = _iso_now()
    _write_json(status_path, payload)
    return payload


def _configure_logging(log_path: Path) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(log_path, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def run(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir).resolve()
    run_dir.mkdir(parents=True, exist_ok=True)
    status_path = run_dir / "status.json"
    log_path = run_dir / "run.log"
    stop_file = run_dir / "STOP_REQUESTED"
    started_at_ts = time.time()
    _configure_logging(log_path)
    requested_max_keep = max(1, int(args.max_keep))
    max_keep = effective_max_keep(requested_max_keep, run_purpose=str(args.run_purpose or ""))
    max_keep_status_fields = _max_keep_status_fields(
        requested_max_keep,
        max_keep,
        run_purpose=str(args.run_purpose or ""),
    )

    _status_update(
        status_path,
        run_id=args.run_id,
        status="running",
        mode=args.mode,
        grade_prefix=str(args.grade_prefix),
        time_limit_seconds=int(args.time_limit_seconds),
        workers=int(args.workers),
        max_keep=max_keep,
        snapshot_interval_sec=int(args.snapshot_interval_sec),
        enable_snapshots=bool(args.enable_snapshots),
        random_seed=int(args.seed) if args.seed is not None else None,
        relative_gap_limit=getattr(args, "relative_gap_limit", None),
        absolute_gap_limit=getattr(args, "absolute_gap_limit", None),
        log_search_progress=bool(getattr(args, "log_search_progress", False)),
        solver_profile=str(getattr(args, "solver_profile", "") or ""),
        run_dir=str(run_dir),
        log_file=str(log_path),
        stop_file=str(stop_file),
        started_at=_iso_now(),
        message="求解运行中",
        files=[],
        run_purpose=str(args.run_purpose or ""),
        diagnostic_plan_id=str(args.diagnostic_plan_id or ""),
        diagnostic_plan_title=str(args.diagnostic_plan_title or ""),
        active_diagnostic_relaxations=_json_list_arg(getattr(args, "active_diagnostic_relaxations_json", "")),
        config_fingerprint=build_effective_config_fingerprint(args.mode),
        **max_keep_status_fields,
    )

    io_override = {
        "joint_solve": {
            "time_limit_seconds": int(args.time_limit_seconds),
            "workers": int(args.workers),
        },
        "multi_solution_output": {
            "enabled": True,
            "root_dir": str(run_dir / "solutions"),
            "max_keep": max_keep,
            "keep_last_runs": 5,
            "periodic_export_every": 0,
        },
        "snapshot_export": {
            "enabled": bool(args.enable_snapshots),
            "interval_sec": int(args.snapshot_interval_sec),
            "root_dir": str(run_dir / "snapshots"),
            "export_day": True,
            "export_night": True,
            "export_link_reports": True,
            "export_checklists": True,
        },
        "web_solve_control": {
            "stop_file": str(stop_file),
        },
    }
    rules_override = {
        "solve": {
            "time_limit_seconds": int(args.time_limit_seconds),
            "workers": int(args.workers),
        }
    }
    if args.seed is not None:
        io_override["joint_solve"]["random_seed"] = int(args.seed)
        rules_override["solve"]["random_seed"] = int(args.seed)
    if getattr(args, "relative_gap_limit", None) is not None:
        io_override["joint_solve"]["relative_gap_limit"] = float(args.relative_gap_limit)
        rules_override["solve"]["relative_gap_limit"] = float(args.relative_gap_limit)
    if getattr(args, "absolute_gap_limit", None) is not None:
        io_override["joint_solve"]["absolute_gap_limit"] = float(args.absolute_gap_limit)
        rules_override["solve"]["absolute_gap_limit"] = float(args.absolute_gap_limit)
    if bool(getattr(args, "log_search_progress", False)):
        io_override["joint_solve"]["log_search_progress"] = True
        rules_override["solve"]["log_search_progress"] = True
    solver_profile = str(getattr(args, "solver_profile", "") or "").strip()
    if solver_profile:
        io_override["joint_solve"]["solver_profile"] = solver_profile
        rules_override["solve"]["solver_profile"] = solver_profile

    try:
        logging.info(
            "Web solve started: mode=%s time_limit=%s workers=%s seed=%s rel_gap=%s abs_gap=%s log_search=%s solver_profile=%s",
            args.mode,
            args.time_limit_seconds,
            args.workers,
            args.seed if args.seed is not None else "",
            getattr(args, "relative_gap_limit", None),
            getattr(args, "absolute_gap_limit", None),
            bool(getattr(args, "log_search_progress", False)),
            solver_profile,
        )
        core = SchedulerCore(IO_PATH, RULES_PATH, grade_prefix=args.grade_prefix)
        with runtime_config_overrides(io_cfg=io_override, rules_cfg=rules_override):
            core.run_mode(args.mode)
        files = collect_artifacts(run_dir, started_at_ts)
        package = run_dir / "result_package.zip"
        completion = completion_status_updates(files, log_path, run_purpose=args.run_purpose)
        _status_update(
            status_path,
            status="completed",
            completed_at=_iso_now(),
            files=files,
            package_file=str(package),
            **completion,
        )
        package = build_result_package(run_dir, started_at_ts)
        logging.info("Web solve completed")
        return 0
    except Exception as exc:
        logging.exception("Web solve failed")
        files = collect_artifacts(run_dir, started_at_ts)
        package = run_dir / "result_package.zip"
        _status_update(
            status_path,
            status="failed",
            completed_at=_iso_now(),
            message=str(exc),
            files=files,
            package_file=str(package),
        )
        build_result_package(run_dir, started_at_ts)
        return 1


def main() -> None:
    parser = argparse.ArgumentParser(description="Run scheduler solve from Web UI")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--mode", choices=["joint", "night"], default="joint")
    parser.add_argument("--grade-prefix", default="高二")
    parser.add_argument("--time-limit-seconds", type=int, default=300)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--relative-gap-limit", type=float, default=None)
    parser.add_argument("--absolute-gap-limit", type=float, default=None)
    parser.add_argument("--log-search-progress", action="store_true")
    parser.add_argument("--solver-profile", choices=["balanced", "improve_incumbent", "prove_bound"], default="")
    parser.add_argument("--max-keep", type=int, default=10)
    parser.add_argument("--snapshot-interval-sec", type=int, default=30)
    parser.add_argument("--enable-snapshots", action="store_true")
    parser.add_argument("--run-purpose", default="")
    parser.add_argument("--diagnostic-plan-id", default="")
    parser.add_argument("--diagnostic-plan-title", default="")
    parser.add_argument("--active-diagnostic-relaxations-json", default="")
    raise SystemExit(run(parser.parse_args()))


if __name__ == "__main__":
    main()
