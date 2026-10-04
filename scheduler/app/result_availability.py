# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from scheduler.app.config_service import PROJECT_ROOT
from scheduler.app.runtime_audit_artifacts import (
    RUNTIME_AUDIT_RELEASE_USE,
    is_runtime_audit_artifact,
    runtime_audit_display_name,
)


RESULT_AVAILABILITY_SCHEMA_VERSION = "scheduler.result_availability.v1"
PRIMARY_RESULT_LIMIT = 6


def attach_result_availability(status: dict[str, Any]) -> None:
    status["result_availability"] = build_result_availability(status)


def build_result_availability(
    status: dict[str, Any],
    files: list[Any] | None = None,
    project_root: Path | None = PROJECT_ROOT,
) -> dict[str, Any]:
    status = status if isinstance(status, dict) else {}
    root = project_root.resolve() if project_root is not None else None
    source: dict[str, str]
    if isinstance(files, list):
        source = _availability_source("provided_files", status)
    else:
        status, source = _select_availability_status(status, root)
    source_files = files if isinstance(files, list) else status.get("files")
    normalized_files = [
        _availability_source_item(item, status)
        for item in (source_files if isinstance(source_files, list) else [])
        if isinstance(item, dict)
    ]
    categories = Counter(str(item.get("category") or "other") for item in normalized_files)
    schedule_files = [item for item in normalized_files if str(item.get("category") or "") == "schedule"]
    package_files = [item for item in normalized_files if str(item.get("category") or "") == "package"]
    diagnostic_files = [item for item in normalized_files if str(item.get("category") or "") == "diagnostic"]
    publish_summary = status.get("publish_assessment") if isinstance(status.get("publish_assessment"), dict) else {}
    publish_summary = publish_summary.get("summary") if isinstance(publish_summary.get("summary"), dict) else {}
    release_state = status.get("release_state") if isinstance(status.get("release_state"), dict) else {}
    publish_status = str(release_state.get("status") or publish_summary.get("status") or "")
    schedule_count = max(
        len(schedule_files),
        _optional_int(status.get("schedule_file_count")),
        _optional_int(release_state.get("schedule_file_count")),
    )
    primary_schedule_files = sorted(schedule_files, key=_result_artifact_priority_key)[:PRIMARY_RESULT_LIMIT]
    package_available = bool(package_files) or _path_points_to_file(status.get("package_file"))
    label, message, tone = _result_availability_message(
        status,
        publish_status=publish_status,
        schedule_count=schedule_count,
        package_available=package_available,
    )
    return {
        "schema_version": RESULT_AVAILABILITY_SCHEMA_VERSION,
        **source,
        "status": _result_availability_status(status, schedule_count),
        "label": label,
        "message": message,
        "tone": tone,
        "has_schedule_files": schedule_count > 0,
        "has_result_package": package_available,
        "schedule_file_count": schedule_count,
        "diagnostic_file_count": len(diagnostic_files),
        "package_file_count": max(len(package_files), 1 if package_available else 0),
        "total_file_count": len(normalized_files),
        "package_label": str(release_state.get("package_label") or _package_label_for_status(status, publish_status)),
        "formal_release_ready": bool(release_state.get("formal_release_ready", publish_status == "ready")),
        "hidden_schedule_file_count": max(0, schedule_count - len(primary_schedule_files)),
        "primary_schedule_files": [_availability_file_item(item) for item in primary_schedule_files],
        "category_counts": dict(categories),
    }


def _select_availability_status(status: dict[str, Any], root: Path | None) -> tuple[dict[str, Any], dict[str, str]]:
    current_run_id = _status_run_id(status)
    source = _availability_source("latest_run", status)
    recommendation = status.get("recommended_formal_candidate")
    if not isinstance(recommendation, dict):
        return status, source
    summary = recommendation.get("summary") if isinstance(recommendation.get("summary"), dict) else {}
    selected_run_id = str(summary.get("selected_run_id") or "").strip()
    if not selected_run_id or selected_run_id == current_run_id:
        return status, source
    candidate = recommendation.get("candidate") if isinstance(recommendation.get("candidate"), dict) else {}
    candidate_status_path = _candidate_status_path(candidate, selected_run_id=selected_run_id, root=root)
    if candidate_status_path is None:
        source.update(
            {
                "source_kind": "recommended_candidate_missing",
                "source_run_id": selected_run_id,
                "source_message": "已推荐历史正式候选，但未定位到候选批次 status.json；快捷结果暂用最新批次。",
            }
        )
        return status, source
    try:
        candidate_status = json.loads(candidate_status_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        source.update(
            {
                "source_kind": "recommended_candidate_unreadable",
                "source_run_id": selected_run_id,
                "source_message": "已推荐历史正式候选，但候选批次 status.json 无法读取；快捷结果暂用最新批次。",
            }
        )
        return status, source
    if not isinstance(candidate_status, dict):
        return status, source
    candidate_status.setdefault("status_file", str(candidate_status_path))
    source.update(
        {
            "source_kind": "recommended_formal_candidate",
            "source_run_id": selected_run_id,
            "source_message": "最新正式批次退化；快捷结果已切换到推荐的历史最好正式候选。",
        }
    )
    return candidate_status, source


def _availability_source(kind: str, status: dict[str, Any]) -> dict[str, str]:
    run_id = _status_run_id(status)
    if kind == "provided_files":
        message = "快捷结果使用调用方提供的文件列表。"
    else:
        message = "快捷结果使用最新求解批次。"
    return {
        "source_kind": kind,
        "source_run_id": run_id,
        "latest_run_id": run_id,
        "source_message": message,
    }


def _status_run_id(status: dict[str, Any]) -> str:
    run_id = str(status.get("run_id") or "").strip()
    if run_id:
        return run_id
    run_dir = str(status.get("run_dir") or "").strip()
    return Path(run_dir).name if run_dir else ""


def _candidate_status_path(candidate: dict[str, Any], *, selected_run_id: str, root: Path | None) -> Path | None:
    raw_status = str(candidate.get("status_file") or "").strip()
    if raw_status:
        path = _existing_file_path(Path(raw_status))
        if path is not None:
            return path
    raw_dir = str(candidate.get("run_dir") or "").strip()
    if raw_dir:
        run_dir = _existing_dir_path(Path(raw_dir))
        if run_dir is not None:
            path = _existing_file_path(run_dir / "status.json")
            if path is not None:
                return path
    if root is not None and selected_run_id:
        path = _existing_file_path(root / "outputs" / "web_runs" / selected_run_id / "status.json")
        if path is not None:
            return path
    return None


def _existing_file_path(path: Path) -> Path | None:
    try:
        return path if path.exists() and path.is_file() else None
    except OSError:
        return None


def _existing_dir_path(path: Path) -> Path | None:
    try:
        return path if path.exists() and path.is_dir() else None
    except OSError:
        return None


def _availability_source_item(item: dict[str, Any], status: dict[str, Any]) -> dict[str, Any]:
    path = Path(str(item.get("path") or ""))
    out = dict(item)
    category = str(out.get("category") or "")
    if not category:
        category = _artifact_category(out, path)
        out["category"] = category
    if not str(out.get("display_label") or "").strip():
        out["display_label"] = runtime_audit_display_name(path) or str(out.get("label") or out.get("path") or path.name)
    if not str(out.get("download_name") or "").strip():
        out["download_name"] = runtime_audit_display_name(path) or path.name or str(out.get("display_label") or out.get("label") or "")
    if not str(out.get("release_use") or "").strip():
        out["release_use"] = RUNTIME_AUDIT_RELEASE_USE if is_runtime_audit_artifact(path) else _artifact_release_use(category, status)
    if category == "schedule" and not str(out.get("release_badge") or "").strip():
        out["release_badge"] = _schedule_release_badge(status)
    return out


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
    if _is_schedule_artifact(source, filename):
        return "schedule"
    if filename.endswith((".log", ".json", ".txt")) or any(token in filename for token in ("meta", "summary", "config_diff")):
        return "log"
    return "other"


def _is_schedule_artifact(source: str, filename: str) -> bool:
    if not filename.endswith((".xlsx", ".xls", ".csv")):
        return False
    lower = source.lower()
    if any(token in lower for token in ("诊断", "审计", "diagnostic", "audit", "checklist", "penalty", "conflict", "violation")):
        return False
    return (
        "课表" in source
        or any(token in source for token in ("最优解", "全局最优", "正式版"))
        or any(token in filename for token in ("schedule", "timetable", "teacher", "class"))
    )


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
        if publish_status == "ready":
            return "official_delivery"
        return "generated_schedule"
    if category == "package":
        if diagnostic or publish_status == "blocked":
            return "troubleshooting_archive"
        if publish_status == "ready":
            return "official_archive"
        return "archive"
    if category == "diagnostic":
        return "diagnostic_material"
    if category == "log":
        return "run_evidence"
    return "supporting_material"


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


def _result_availability_status(status: dict[str, Any], schedule_count: int) -> str:
    lifecycle = str(status.get("status") or "")
    if schedule_count > 0:
        return "available"
    if lifecycle in {"running", "pause_requested", "starting"}:
        return "pending"
    if lifecycle == "completed":
        return "missing"
    return "empty"


def _result_availability_message(
    status: dict[str, Any],
    *,
    publish_status: str,
    schedule_count: int,
    package_available: bool,
) -> tuple[str, str, str]:
    lifecycle = str(status.get("status") or "")
    run_purpose = str(status.get("run_purpose") or "")
    package_text = "结果包已生成" if package_available else "结果包可手动生成"
    if schedule_count <= 0:
        if lifecycle in {"running", "pause_requested", "starting"}:
            return "等待课表文件", "求解仍在运行，捕获可行解后会显示课表和结果包。", "muted"
        if lifecycle == "completed":
            return "未生成课表文件", "本批次未发现可下载课表，请查看诊断报告和日志后调整规则重跑。", "error"
        return "暂无结果文件", "完成一次求解后会在这里列出课表、诊断材料和结果包。", "muted"
    if run_purpose == "diagnostic_trial":
        return "已生成排障参考课表", f"发现 {schedule_count} 个候选课表文件；诊断试跑不能直接发布，{package_text}。", "warning"
    if publish_status == "blocked":
        return "已生成排障参考课表", f"发现 {schedule_count} 个课表文件，但发布校验未通过；只能用于排障复核，{package_text}。", "warning"
    if publish_status == "ready":
        return "已生成正式课表", f"发现 {schedule_count} 个可正式交付课表文件，{package_text}。", "ready"
    return "已生成课表文件", f"发现 {schedule_count} 个课表文件；发布状态尚未明确，下载前请先查看发布评估。", "neutral"


def _package_label_for_status(status: dict[str, Any], publish_status: str) -> str:
    if str(status.get("run_purpose") or "") == "diagnostic_trial" or publish_status == "blocked":
        return "排障包"
    if publish_status == "ready":
        return "正式结果包"
    return "结果包"


def _availability_file_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "label": str(item.get("label") or ""),
        "display_label": str(item.get("display_label") or item.get("label") or item.get("path") or ""),
        "path": str(item.get("path") or ""),
        "download_name": str(item.get("download_name") or item.get("display_label") or item.get("label") or ""),
        "release_use": str(item.get("release_use") or ""),
        "release_badge": str(item.get("release_badge") or ""),
        "size": int(item.get("size") or 0),
        "modified_at": str(item.get("modified_at") or ""),
    }


def _result_artifact_priority_key(item: dict[str, Any]) -> tuple[int, str]:
    source = str(item.get("display_label") or item.get("label") or item.get("path") or "").replace("\\", "/")
    lower = source.lower()
    priority = 80
    if "best/" in lower or "/best/" in lower:
        priority = min(priority, 0)
    if "最终全局最优解" in source:
        priority = min(priority, 1)
    if "课表及值班安排" in source:
        priority = min(priority, 5)
    if "正式版" in source:
        priority = min(priority, 8)
    if "显示节次调整版" in source:
        priority = min(priority, 10)
    top_match = re.search(r"top(\d+)", lower)
    if top_match:
        priority = min(priority, 20 + int(top_match.group(1)))
    return priority, lower


def _path_points_to_file(value: Any) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    try:
        return Path(text).is_file()
    except OSError:
        return False


def _optional_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
