# -*- coding: utf-8 -*-
from __future__ import annotations

import hashlib
import json
import logging
import platform
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from scheduler.config.loader import load_effective_config
from scheduler.diagnostics.penalty_registry import summarize_event_log_csv
from scheduler.solver_quality import solver_quality_fields
from scheduler.output_paths import is_scheduler_outputs_path, resolve_output_dir, resolve_project_path
from scheduler.app.school_problem_preview import build_school_problem_preview_payload
from scheduler.rules import (
    audit_rule_trace_against_plan,
    build_default_rule_registry,
    build_rule_execution_plan,
    dump_effective_rules,
    generic_scheduler_rule_ids,
    rule_execution_plan_payload,
    rule_runtime_context,
)
from scheduler.rules.runtime import runtime_rules_snapshot_payload, runtime_trace_payload
from scheduler.scheduler_core import SchedulerCore


logger = logging.getLogger(__name__)


BEST_SOLUTION_FILENAMES = (
    "最终全局最优解_正式版.xlsx",
    "最终全局最优解.xlsx",
)
DIAGNOSTICS_SUMMARY_FILENAMES = (
    "多解诊断报告.xlsx",
)
DAY_SCHEDULE_PATTERN = "*课表及值班安排*.xlsx"
DIAGNOSTICS_SUMMARY_PATTERN = "多解诊断报告*.xlsx"


@dataclass(frozen=True)
class RunResult:
    run_id: str
    best_solution_path: str
    pool_index_path: str
    diagnostics_summary_path: str


def _resolve_outputs_dir(io_cfg: dict, io_path: Path) -> Path:
    out_dir = resolve_output_dir(io_cfg, io_path)
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir


def _is_safe_cleanup_target(out_dir: Path, io_path: Path) -> tuple[bool, str]:
    """Guard cleanup against dangerous output directory misconfiguration."""
    repo_root = io_path.parent.parent.parent.resolve()
    target = out_dir.resolve()
    anchor = Path(target.anchor) if target.anchor else None
    if anchor is not None and target == anchor:
        return False, "target_is_filesystem_root"
    if target == repo_root:
        return False, "target_is_repo_root"
    if is_scheduler_outputs_path(target, project_root=repo_root):
        return False, "target_is_scheduler_outputs"
    if repo_root not in target.parents:
        return False, "target_outside_repo_root"
    return True, "ok"


def _latest_run_dir(outputs_dir: Path) -> Path | None:
    runs_root = outputs_dir / "solutions"
    if not runs_root.exists():
        return None
    runs = [p for p in runs_root.iterdir() if p.is_dir() and p.name.startswith("run_")]
    if not runs:
        return None
    return max(runs, key=lambda p: p.stat().st_mtime)


def _find_latest_file(outputs_dir: Path, pattern: str) -> Path | None:
    files = [p for p in outputs_dir.glob(pattern) if p.is_file()]
    if not files:
        return None
    return max(files, key=lambda p: p.stat().st_mtime)


def _first_existing(paths: list[Path]) -> Path | None:
    for path in paths:
        if path.exists():
            return path
    return None


def _select_best_solution_path(run_dir: Path | None, outputs_dir: Path) -> Path | None:
    if run_dir is not None:
        best_dirs = [run_dir / "best", run_dir / "solutions" / "best"]
        candidate = _first_existing(
            [best_dir / file_name for best_dir in best_dirs for file_name in BEST_SOLUTION_FILENAMES]
        )
        if candidate is not None:
            return candidate

    fallback_best = _find_latest_file(outputs_dir, DAY_SCHEDULE_PATTERN)
    if fallback_best is not None:
        return fallback_best
    return None


def _select_diagnostics_summary_path(run_dir: Path | None, outputs_dir: Path) -> Path | None:
    if run_dir is not None:
        candidate = _first_existing(
            [run_dir / "diagnostics" / file_name for file_name in DIAGNOSTICS_SUMMARY_FILENAMES]
        )
        if candidate is not None:
            return candidate

    fallback_diag = _find_latest_file(outputs_dir, DIAGNOSTICS_SUMMARY_PATTERN)
    if fallback_diag is not None:
        return fallback_diag
    return None


def _resolve_data_path(raw_path: str | Path | None, base_dir: Path) -> Path | None:
    if raw_path is None:
        return None
    path = Path(str(raw_path))
    if not path.is_absolute():
        path = (base_dir / path).resolve()
    return path


def _sha256_file(path: Path) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _file_evidence(label: str, path: Path | None) -> dict[str, Any]:
    if path is None:
        return {
            "label": label,
            "path": None,
            "exists": False,
            "size_bytes": None,
            "mtime": None,
            "sha256": None,
        }
    info: dict[str, Any] = {
        "label": label,
        "path": str(path.resolve()),
        "exists": path.exists(),
        "size_bytes": None,
        "mtime": None,
        "sha256": None,
    }
    if path.exists():
        st = path.stat()
        info["size_bytes"] = int(st.st_size)
        info["mtime"] = datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        info["sha256"] = _sha256_file(path)
    return info


def _extract_solver_settings(mode: str, io_cfg: dict, rules_cfg: dict) -> dict[str, Any]:
    day_joint_cfg = (io_cfg.get("joint_solve", {}) or {})
    night_cfg = (rules_cfg.get("solve", {}) or {})
    active: str | list[str]
    if mode == "night":
        active = "night"
    elif mode in ("day", "joint"):
        active = "day_joint"
    else:
        active = ["night", "day_joint"]
    return {
        "active_for_mode": active,
        "day_joint": {
            "time_limit_seconds": day_joint_cfg.get("time_limit_seconds"),
            "workers": day_joint_cfg.get("workers"),
            "random_seed": day_joint_cfg.get("random_seed"),
            "relative_gap_limit": day_joint_cfg.get("relative_gap_limit"),
            "absolute_gap_limit": day_joint_cfg.get("absolute_gap_limit"),
            "log_search_progress": day_joint_cfg.get("log_search_progress"),
        },
        "night": {
            "time_limit_seconds": night_cfg.get("time_limit_seconds"),
            "workers": night_cfg.get("workers"),
            "random_seed": night_cfg.get("random_seed"),
            "relative_gap_limit": night_cfg.get("relative_gap_limit"),
            "absolute_gap_limit": night_cfg.get("absolute_gap_limit"),
            "log_search_progress": night_cfg.get("log_search_progress"),
        },
    }


def _extract_solve_result_summary(outputs_dir: Path, *, min_mtime: float | None = None) -> dict[str, Any]:
    summary = {
        "status": None,
        "wall_time": None,
        "objective": None,
        "penalty": None,
        "best_bound": None,
        "objective_gap": None,
        "gap_percent": None,
        "optimality_status": "unknown",
    }
    candidates = [p for p in outputs_dir.rglob("final_solver_overview.json") if p.is_file()]
    if min_mtime is not None:
        candidates = [p for p in candidates if p.stat().st_mtime >= float(min_mtime)]
    if not candidates:
        return summary
    latest = max(candidates, key=lambda p: p.stat().st_mtime)
    try:
        data = json.loads(latest.read_text(encoding="utf-8"))
    except Exception:
        return summary
    objective = data.get("objective_value")
    summary["status"] = data.get("solver_status")
    summary["wall_time"] = data.get("wall_time")
    summary["objective"] = objective
    summary["penalty"] = objective
    summary["best_bound"] = data.get("best_bound")
    summary.update(solver_quality_fields(objective, data.get("best_bound"), solver_status=str(data.get("solver_status") or "")))
    return summary


def _get_git_commit(repo_root: Path) -> str | None:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception:
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip() or None


def _write_json_file(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_text_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _read_json_file(path: Path) -> dict[str, Any] | None:
    if not path.exists() or not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if isinstance(data, dict):
        return data
    return None


def _find_latest_event_log(outputs_dir: Path, *, min_mtime: float | None = None) -> Path | None:
    candidates = [p for p in outputs_dir.rglob("event_log.csv") if p.is_file()]
    if min_mtime is not None:
        candidates = [p for p in candidates if p.stat().st_mtime >= float(min_mtime)]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def _extract_penalty_breakdown(
    outputs_dir: Path,
    *,
    min_mtime: float | None = None,
) -> tuple[list[dict[str, Any]], str | None, float | None]:
    event_log_path = _find_latest_event_log(outputs_dir, min_mtime=min_mtime)
    if event_log_path is None:
        return [], None, None
    try:
        summarized_rows = summarize_event_log_csv(event_log_path)
    except Exception:
        return [], str(event_log_path.resolve()), None
    if not summarized_rows:
        return [], str(event_log_path.resolve()), None
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for row in summarized_rows:
        rule_id = str(row.get("rule_id") or "UNKNOWN")
        rule_name = str(row.get("rule_name") or row.get("rule_id") or "UNKNOWN")
        teacher = str(row.get("teacher") or "GLOBAL")
        penalty_sum = float(row.get("penalty_sum", 0.0) or 0.0)
        count_val = float(row.get("count", 0.0) or 0.0)
        slot = grouped.setdefault(
            (rule_id, rule_name),
            {"penalty_sum": 0.0, "count": 0.0, "offenders": {}},
        )
        slot["penalty_sum"] += penalty_sum
        slot["count"] += count_val
        offenders: dict[str, float] = slot["offenders"]
        offenders[teacher] = float(offenders.get(teacher, 0.0) + penalty_sum)
    total_penalty = sum(v["penalty_sum"] for v in grouped.values())
    ranked = sorted(grouped.items(), key=lambda kv: kv[1]["penalty_sum"], reverse=True)[:10]
    rows = []
    for (rule_id, rule_name), values in ranked:
        if values["penalty_sum"] <= 0:
            continue
        top_offenders = [
            {"entity": teacher, "penalty_sum": score}
            for teacher, score in sorted(
                (values.get("offenders") or {}).items(),
                key=lambda kv: kv[1],
                reverse=True,
            )[:3]
        ]
        rows.append(
            {
                "rule_id": rule_id,
                "rule_name": rule_name,
                "penalty_sum": values["penalty_sum"],
                "count": values["count"],
                "top_offenders": top_offenders,
            }
        )
    return rows, str(event_log_path.resolve()), total_penalty


def _extract_solutions_seen(outputs_dir: Path) -> Any:
    candidates = [p for p in outputs_dir.rglob("final_solver_overview.json") if p.is_file()]
    if not candidates:
        return None
    latest = max(candidates, key=lambda p: p.stat().st_mtime)
    data = _read_json_file(latest)
    if not data:
        return None
    for key in (
        "solutions_seen",
        "solution_count",
        "total_solutions_seen",
        "archive_count",
        "callback_solution_count",
    ):
        if key in data:
            return data.get(key)
    return None


def _select_mode_solver_settings(mode: str, evidence_payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if not evidence_payload:
        return None
    settings = evidence_payload.get("effective_solver_settings")
    if not isinstance(settings, dict):
        return None
    if mode == "night":
        src = settings.get("night")
    elif mode in ("day", "joint"):
        src = settings.get("day_joint")
    else:
        return None
    if not isinstance(src, dict):
        return None
    return {
        "time_limit_seconds": src.get("time_limit_seconds"),
        "workers": src.get("workers"),
        "random_seed": src.get("random_seed"),
        "relative_gap_limit": src.get("relative_gap_limit"),
        "absolute_gap_limit": src.get("absolute_gap_limit"),
        "log_search_progress": src.get("log_search_progress"),
    }


def _format_explain_summary(
    *,
    mode: str,
    run_id: str,
    evidence_payload: dict[str, Any] | None,
    solve_result_summary: dict[str, Any],
    penalty_rows: list[dict[str, Any]],
    penalty_source: str | None,
    total_penalty: float | None,
    evidence_file_name: str | None,
    solutions_seen: Any,
) -> str:
    solver_settings = _select_mode_solver_settings(mode, evidence_payload) or {
        "time_limit_seconds": None,
        "workers": None,
        "random_seed": None,
        "relative_gap_limit": None,
        "absolute_gap_limit": None,
        "log_search_progress": None,
    }
    input_files: list[dict[str, Any]] = []
    if evidence_payload and isinstance(evidence_payload.get("input_files"), list):
        input_files = [x for x in evidence_payload["input_files"] if isinstance(x, dict)]

    no_input_msg = "No input fingerprint available (run_evidence missing)."
    no_penalty_msg = "Current run did not expose penalty breakdown data source."
    ps_note = "PowerShell 5.1 requires -Encoding UTF8 when reading UTF-8 files."

    lines: list[str] = []
    lines.append("# explain_summary")
    lines.append("")
    lines.append("## A. Run Metadata")
    lines.append(f"- timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"- git_commit: {None if not evidence_payload else evidence_payload.get('git_commit')}")
    lines.append(f"- mode: {mode}")
    lines.append(f"- run_id: {run_id or None}")
    lines.append(f"- time_limit_seconds: {solver_settings.get('time_limit_seconds')}")
    lines.append(f"- workers: {solver_settings.get('workers')}")
    lines.append(f"- random_seed: {solver_settings.get('random_seed')}")
    lines.append(f"- relative_gap_limit: {solver_settings.get('relative_gap_limit')}")
    lines.append(f"- absolute_gap_limit: {solver_settings.get('absolute_gap_limit')}")
    lines.append(f"- log_search_progress: {solver_settings.get('log_search_progress')}")
    lines.append("")
    lines.append("## B. Input Fingerprints")
    if evidence_file_name:
        lines.append(f"- evidence_ref: {evidence_file_name}")
    if not input_files:
        lines.append(f"- {no_input_msg}")
    else:
        for item in input_files:
            lines.append(
                "- {label}: path={path}, exists={exists}, size_bytes={size_bytes}, mtime={mtime}, sha256={sha256}".format(
                    label=item.get("label"),
                    path=item.get("path"),
                    exists=item.get("exists"),
                    size_bytes=item.get("size_bytes"),
                    mtime=item.get("mtime"),
                    sha256=item.get("sha256"),
                )
            )
    lines.append("")
    lines.append("## C. Solve Result")
    lines.append(f"- status: {solve_result_summary.get('status')}")
    lines.append(f"- objective: {solve_result_summary.get('objective')}")
    lines.append(f"- best_bound: {solve_result_summary.get('best_bound')}")
    lines.append(f"- objective_gap: {solve_result_summary.get('objective_gap')}")
    lines.append(f"- gap_percent: {solve_result_summary.get('gap_percent')}")
    lines.append(f"- optimality_status: {solve_result_summary.get('optimality_status')}")
    lines.append(f"- solutions_seen: {solutions_seen}")
    lines.append("")
    lines.append("## D. Penalty Breakdown")
    lines.append(f"- total_penalty: {total_penalty}")
    if penalty_source:
        lines.append(f"- data_source: {penalty_source}")
    if penalty_rows:
        for idx, row in enumerate(penalty_rows, start=1):
            offenders = ", ".join(
                f"{item.get('entity')}({item.get('penalty_sum')})"
                for item in (row.get("top_offenders") or [])
            ) or "N/A"
            lines.append(
                (
                    f"{idx}. rule_id={row.get('rule_id')}, rule_name={row.get('rule_name')}, "
                    f"penalty_sum={row.get('penalty_sum')}, violation_count={row.get('count')}, "
                    f"top_offenders={offenders}"
                )
            )
    else:
        lines.append(f"- {no_penalty_msg}")
    lines.append("")
    lines.append("## E. Viewing Notes")
    lines.append(f"- {ps_note}")
    lines.append("- Get-Content outputs/meta/explain_summary_latest.md -Encoding UTF8 -TotalCount 60")
    lines.append("")
    return "\n".join(lines)


def _collect_input_files(io_cfg: dict, io_path: Path, rules_path: Path) -> list[dict[str, Any]]:
    base_dir = io_path.parent.parent
    teacher_table = _resolve_data_path((io_cfg.get("teacher_table", {}) or {}).get("path"), base_dir)
    day_cfg = io_cfg.get("day", {}) or {}
    day_rules = _resolve_data_path(day_cfg.get("rules_path"), base_dir)
    day_teacher_table = _resolve_data_path(day_cfg.get("teacher_table_path"), base_dir)
    raw_items: list[tuple[str, Path | None]] = [
        ("io_yaml", io_path),
        ("rules_yaml", rules_path),
        ("teacher_table", teacher_table),
        ("day_rules", day_rules),
        ("day_teacher_table", day_teacher_table),
    ]
    seen: set[tuple[str, str | None]] = set()
    out: list[dict[str, Any]] = []
    for label, path in raw_items:
        norm = str(path.resolve()) if isinstance(path, Path) else None
        key = (label, norm)
        if key in seen:
            continue
        seen.add(key)
        out.append(_file_evidence(label, path))
    return out


def _mode_for_rule_enumeration(mode: str) -> str | None:
    target = str(mode or "").strip().lower()
    if target in {"day", "night", "joint"}:
        return target
    return None


def _build_solver_params_snapshot_payload(
    *,
    mode: str,
    run_id: str,
    git_commit: str | None,
    io_cfg: dict[str, Any],
    rules_cfg: dict[str, Any],
) -> dict[str, Any]:
    return {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "mode": str(mode),
        "run_id": str(run_id or ""),
        "git_commit": git_commit,
        "solver_params": _extract_solver_settings(mode, io_cfg, rules_cfg),
    }


def _build_inputs_fingerprint_payload(
    *,
    mode: str,
    run_id: str,
    git_commit: str | None,
    io_cfg: dict[str, Any],
    io_path: Path,
    rules_path: Path,
) -> dict[str, Any]:
    return {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "mode": str(mode),
        "run_id": str(run_id or ""),
        "git_commit": git_commit,
        "inputs": _collect_input_files(io_cfg, io_path, rules_path),
    }


def _build_rule_execution_plan_snapshot_payload(
    *,
    mode: str,
    run_id: str,
    git_commit: str | None,
    registry: Any,
    effective_cfg: dict[str, Any],
    trace: list[dict[str, Any]],
) -> dict[str, Any]:
    mode_filter = _mode_for_rule_enumeration(mode)
    plan = build_rule_execution_plan(
        registry,
        effective_cfg,
        mode=mode_filter,
        only_enabled=False,
        source="runtime_snapshot",
    )
    trace_audit = audit_rule_trace_against_plan(
        plan,
        trace,
        require_all_enabled=False,
    )
    payload = rule_execution_plan_payload(plan)
    payload.update(
        {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "mode": str(mode),
            "run_id": str(run_id or ""),
            "git_commit": git_commit,
            "trace_audit": {
                "ok": trace_audit.ok,
                "planned_rule_ids": list(trace_audit.planned_rule_ids),
                "traced_rule_ids": list(trace_audit.traced_rule_ids),
                "missing_enabled_rule_ids": list(trace_audit.missing_enabled_rule_ids),
                "unexpected_trace_rule_ids": list(trace_audit.unexpected_trace_rule_ids),
                "errored_trace_rule_ids": list(trace_audit.errored_trace_rule_ids),
            },
        }
    )
    return payload


def _write_runtime_snapshots(
    *,
    mode: str,
    run_id: str,
    outputs_dir: Path,
    run_dir: Path | None,
    effective_cfg: dict[str, Any],
    io_cfg: dict[str, Any],
    rules_cfg: dict[str, Any],
    io_path: Path,
    rules_path: Path,
    registry: Any,
    trace: list[dict[str, Any]],
) -> None:
    try:
        repo_root = io_path.parent.parent.parent.resolve()
        git_commit = _get_git_commit(repo_root)
        mode_filter = _mode_for_rule_enumeration(mode)
        rules_rows = dump_effective_rules(
            registry,
            effective_cfg,
            mode=mode_filter,
            only_enabled=False,
        )
        rules_payload = runtime_rules_snapshot_payload(
            mode=mode,
            run_id=run_id,
            git_commit=git_commit,
            rows=rules_rows,
        )
        trace_payload = runtime_trace_payload(
            mode=mode,
            run_id=run_id,
            git_commit=git_commit,
            trace=trace,
            generic_rule_ids=generic_scheduler_rule_ids(),
        )
        school_problem_payload = build_school_problem_preview_payload(
            mode=mode,
            run_id=run_id,
            git_commit=git_commit,
            effective_cfg=effective_cfg,
            io_cfg=io_cfg,
            io_path=io_path,
            registry=registry,
            source="runtime_snapshot",
        )
        execution_plan_payload = _build_rule_execution_plan_snapshot_payload(
            mode=mode,
            run_id=run_id,
            git_commit=git_commit,
            registry=registry,
            effective_cfg=effective_cfg,
            trace=trace,
        )
        solver_payload = _build_solver_params_snapshot_payload(
            mode=mode,
            run_id=run_id,
            git_commit=git_commit,
            io_cfg=io_cfg,
            rules_cfg=rules_cfg,
        )
        inputs_payload = _build_inputs_fingerprint_payload(
            mode=mode,
            run_id=run_id,
            git_commit=git_commit,
            io_cfg=io_cfg,
            io_path=io_path,
            rules_path=rules_path,
        )

        target_dirs = [(outputs_dir / "meta").resolve()]
        if run_dir is not None:
            target_dirs.append((run_dir / "_run_meta").resolve())
        for target_dir in target_dirs:
            _write_json_file(target_dir / "effective_rules_snapshot.json", rules_payload)
            _write_json_file(target_dir / "solver_params_snapshot.json", solver_payload)
            _write_json_file(target_dir / "inputs_fingerprint.json", inputs_payload)
            _write_json_file(target_dir / "school_problem_snapshot.json", school_problem_payload)
            _write_json_file(target_dir / "applied_rules_trace.json", trace_payload)
            _write_json_file(target_dir / "rule_execution_plan.json", execution_plan_payload)
    except Exception as exc:
        logger.warning("write runtime snapshots failed: %s", exc)
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("runtime snapshot write detail", exc_info=True)


def _mirror_run_level_meta_to_run_dir(
    *,
    run_dir: Path | None,
    run_id: str,
    evidence_payload: dict[str, Any] | None,
    explain_summary_path: Path,
) -> None:
    if run_dir is None:
        return
    try:
        run_meta_dir = (run_dir / "_run_meta").resolve()
        if isinstance(evidence_payload, dict):
            _write_json_file(run_meta_dir / "run_evidence_latest.json", evidence_payload)
            rid = str(run_id or "").strip()
            if rid:
                _write_json_file(run_meta_dir / f"run_evidence_{rid}.json", evidence_payload)
        if explain_summary_path.exists():
            _write_text_file(
                run_meta_dir / "explain_summary_latest.md",
                explain_summary_path.read_text(encoding="utf-8"),
            )
    except Exception as exc:
        logger.warning("mirror run-level meta to run_dir failed: %s", exc)
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("run-level meta mirror detail", exc_info=True)


def _build_run_evidence_payload(
    *,
    mode: str,
    cli_args: list[str],
    io_cfg: dict,
    rules_cfg: dict,
    io_path: Path,
    rules_path: Path,
    outputs_dir: Path,
    solve_result_summary: dict[str, Any],
) -> dict[str, Any]:
    repo_root = io_path.parent.parent.parent.resolve()
    return {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "git_commit": _get_git_commit(repo_root),
        "mode": str(mode),
        "cli_args": list(cli_args),
        "python_version": sys.version,
        "platform": platform.platform(),
        "config_paths": {
            "io_yaml": str(io_path.resolve()),
            "rules_yaml": str(rules_path.resolve()),
        },
        "effective_solver_settings": _extract_solver_settings(mode, io_cfg, rules_cfg),
        "input_files": _collect_input_files(io_cfg, io_path, rules_path),
        "outputs_dir": str(outputs_dir.resolve()),
        "solve_result_summary": solve_result_summary,
    }


def write_run_evidence(
    *,
    mode: str,
    cli_args: list[str] | None,
    io_cfg: dict,
    rules_cfg: dict,
    io_path: Path,
    rules_path: Path,
    outputs_dir: Path,
    run_id: str | None = None,
    solve_result_summary: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    try:
        payload = _build_run_evidence_payload(
            mode=mode,
            cli_args=cli_args or [],
            io_cfg=io_cfg,
            rules_cfg=rules_cfg,
            io_path=io_path,
            rules_path=rules_path,
            outputs_dir=outputs_dir,
            solve_result_summary=solve_result_summary or _extract_solve_result_summary(outputs_dir),
        )
        meta_dir = outputs_dir / "meta"
        _write_json_file(meta_dir / "run_evidence_latest.json", payload)
        rid = str(run_id or "").strip()
        if rid:
            _write_json_file(meta_dir / f"run_evidence_{rid}.json", payload)
        return payload
    except Exception as exc:
        logger.warning("write run-level evidence failed: %s", exc)
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("run-level evidence write detail", exc_info=True)
        return None


def write_explain_summary(
    *,
    mode: str,
    run_id: str,
    outputs_dir: Path,
    solve_result_summary: dict[str, Any] | None = None,
    run_evidence_payload: dict[str, Any] | None = None,
    min_mtime: float | None = None,
) -> None:
    try:
        meta_dir = outputs_dir / "meta"
        evidence_path = meta_dir / "run_evidence_latest.json"
        evidence_payload = run_evidence_payload or _read_json_file(evidence_path)
        penalty_rows, penalty_source, total_penalty = _extract_penalty_breakdown(outputs_dir, min_mtime=min_mtime)
        summary_text = _format_explain_summary(
            mode=mode,
            run_id=run_id,
            evidence_payload=evidence_payload,
            solve_result_summary=solve_result_summary or _extract_solve_result_summary(outputs_dir, min_mtime=min_mtime),
            penalty_rows=penalty_rows,
            penalty_source=penalty_source,
            total_penalty=total_penalty,
            evidence_file_name=evidence_path.name if evidence_path.exists() else None,
            solutions_seen=_extract_solutions_seen(outputs_dir),
        )
        _write_text_file(meta_dir / "explain_summary_latest.md", summary_text)
    except Exception as exc:
        logger.warning("write explain_summary failed: %s", exc)
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("explain_summary write detail", exc_info=True)


def _pre_run_cleanup(io_cfg: dict, io_path: Path) -> None:
    cleanup_cfg = (io_cfg.get("pre_run_cleanup", {}) or {})
    if not bool(cleanup_cfg.get("enabled", True)):
        logger.info("pre-run cleanup is disabled")
        return

    out_dir = _resolve_outputs_dir(io_cfg, io_path)
    safe_cleanup, reason = _is_safe_cleanup_target(out_dir, io_path)
    if not safe_cleanup:
        logger.warning("skip pre-run cleanup: unsafe output dir %s (%s)", str(out_dir), reason)
        return
    solutions_dir = (out_dir / "solutions").resolve()

    warm_cfg = (io_cfg.get("warm_start", {}) or {})
    base_dir = io_path.parent.parent
    project_root = effective_project_root = io_path.parent.parent.parent
    warm_file = resolve_project_path(
        warm_cfg.get("path", "outputs/meta/last_solution.json"),
        project_root=effective_project_root,
        label="warm_start.path",
        reject_scheduler_outputs=True,
    )
    warm_pool = resolve_project_path(
        warm_cfg.get("pool_dir", "outputs/solution_pool"),
        project_root=project_root,
        label="warm_start.pool_dir",
        reject_scheduler_outputs=True,
    )

    tokens = [str(t).lower() for t in cleanup_cfg.get("preserve_name_tokens", ["warm", "hint", "hotstart", "seed", "keep"])]

    def _should_keep(path: Path) -> bool:
        rp = path.resolve()
        if solutions_dir.exists() and (rp == solutions_dir or solutions_dir in rp.parents):
            return True
        if rp == warm_file:
            return True
        if warm_pool.exists() and (rp == warm_pool or warm_pool in rp.parents):
            return True
        name = path.name.lower()
        return any(token and token in name for token in tokens)

    for path in sorted(out_dir.rglob("*")):
        if not path.is_file():
            continue
        if _should_keep(path):
            continue
        try:
            path.unlink()
        except Exception as exc:
            logger.warning("cleanup failed: %s (%s)", str(path), exc)

    for directory in sorted(out_dir.rglob("*"), reverse=True):
        if not directory.is_dir() or directory == out_dir:
            continue
        if warm_pool.exists() and (directory == warm_pool or warm_pool in directory.parents):
            continue
        try:
            if not any(directory.iterdir()):
                directory.rmdir()
        except Exception:
            continue

    logger.info("cleanup completed: historical exports removed, warm-start artifacts preserved")


def run(
    mode: str,
    *,
    io_path: Path,
    rules_path: Path | None = None,
    grade_prefix: str = "高二",
    cli_args: list[str] | None = None,
) -> RunResult:
    effective = load_effective_config(
        mode,
        {"io_path": io_path, "rules_path": rules_path or io_path.with_name("rules.yaml")},
    )
    io_cfg = effective.io_cfg
    _pre_run_cleanup(io_cfg, effective.io_path)

    core = SchedulerCore(
        io_path=effective.io_path,
        rules_path=effective.rules_path,
        grade_prefix=grade_prefix,
    )
    run_started_at = time.time()
    runtime_registry = build_default_rule_registry()
    runtime_trace: list[dict[str, Any]] = []
    with rule_runtime_context(
        mode=mode,
        run_id="",
        effective_cfg=effective.effective_cfg,
        registry=runtime_registry,
        trace=runtime_trace,
    ):
        core.run_mode(mode)

    outputs_dir = _resolve_outputs_dir(io_cfg, effective.io_path)
    run_dir = _latest_run_dir(outputs_dir)
    if run_dir is not None and run_dir.stat().st_mtime < run_started_at:
        run_dir = None

    best_path = Path("")
    pool_index = Path("")
    diag_path = Path("")
    run_id = ""
    if run_dir is not None:
        run_id = run_dir.name
        pool_index = run_dir / "pool_cache" / "index.json"

    selected_best = _select_best_solution_path(run_dir, outputs_dir)
    if selected_best is not None:
        best_path = selected_best
    selected_diag = _select_diagnostics_summary_path(run_dir, outputs_dir)
    if selected_diag is not None:
        diag_path = selected_diag

    result = RunResult(
        run_id=run_id,
        best_solution_path=str(best_path.resolve()) if best_path.exists() else "",
        pool_index_path=str(pool_index.resolve()) if pool_index.exists() else "",
        diagnostics_summary_path=str(diag_path.resolve()) if diag_path.exists() else "",
    )
    if result.run_id:
        for item in runtime_trace:
            if isinstance(item, dict) and not item.get("run_id"):
                item["run_id"] = result.run_id

    _write_runtime_snapshots(
        mode=mode,
        run_id=result.run_id,
        outputs_dir=outputs_dir,
        run_dir=run_dir,
        effective_cfg=effective.effective_cfg,
        io_cfg=effective.io_cfg,
        rules_cfg=effective.rules_cfg,
        io_path=effective.io_path,
        rules_path=effective.rules_path,
        registry=runtime_registry,
        trace=runtime_trace,
    )
    solve_result_summary = _extract_solve_result_summary(outputs_dir, min_mtime=run_started_at)
    evidence_payload = write_run_evidence(
        mode=mode,
        cli_args=cli_args,
        io_cfg=effective.io_cfg,
        rules_cfg=effective.rules_cfg,
        io_path=effective.io_path,
        rules_path=effective.rules_path,
        outputs_dir=outputs_dir,
        run_id=result.run_id,
        solve_result_summary=solve_result_summary,
    )
    write_explain_summary(
        mode=mode,
        run_id=result.run_id,
        outputs_dir=outputs_dir,
        solve_result_summary=solve_result_summary,
        run_evidence_payload=evidence_payload,
        min_mtime=run_started_at,
    )
    _mirror_run_level_meta_to_run_dir(
        run_dir=run_dir,
        run_id=result.run_id,
        evidence_payload=evidence_payload,
        explain_summary_path=outputs_dir / "meta" / "explain_summary_latest.md",
    )
    return result

