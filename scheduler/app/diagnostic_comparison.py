# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


DIAGNOSTIC_COMPARISON_SCHEMA_VERSION = "scheduler.diagnostic_comparison.v1"


def build_diagnostic_comparison(status: dict[str, Any], project_root: Path) -> dict[str, Any]:
    status = status if isinstance(status, dict) else {}
    if str(status.get("run_purpose") or "") != "diagnostic_trial":
        return {}

    root = project_root.resolve()
    current_run = _safe_dir(status.get("run_dir"), root)
    if current_run is None:
        return _empty("当前诊断批次缺少 run_dir，无法对比正式基线。")
    baseline = _find_baseline_status(current_run, status, root)
    if not baseline:
        return _empty("未找到早于本诊断批次的正式求解基线，无法判断临时调参是否真的改善课表。")

    baseline_breakdown = _breakdown_rows(baseline)
    current_breakdown = _breakdown_rows(status)
    adjusted_rules = _adjusted_rule_ids(status)
    compare_rule_ids = _compare_rule_ids(baseline_breakdown, current_breakdown, adjusted_rules)
    changes = [
        _rule_change(rule_id, baseline_breakdown.get(rule_id), current_breakdown.get(rule_id), adjusted=rule_id in adjusted_rules)
        for rule_id in compare_rule_ids
    ]

    objective_delta = _delta(status.get("objective_value"), baseline.get("objective_value"))
    gap_percent_delta = _delta(status.get("gap_percent"), baseline.get("gap_percent"))
    objective_comparable = not _has_weight_patch(status)
    unchanged_adjusted = [
        item
        for item in changes
        if item.get("adjusted") and item.get("baseline_count") is not None and item.get("diagnostic_count") is not None and item.get("count_delta") == 0
    ]
    reduced_adjusted = [
        item
        for item in changes
        if item.get("adjusted") and _as_float(item.get("count_delta")) is not None and float(item.get("count_delta")) < 0
    ]

    summary = _summary(
        objective_delta=objective_delta,
        gap_percent_delta=gap_percent_delta,
        objective_comparable=objective_comparable,
        adjusted_count=len(adjusted_rules),
        unchanged_adjusted=unchanged_adjusted,
        reduced_adjusted=reduced_adjusted,
    )
    return {
        "schema_version": DIAGNOSTIC_COMPARISON_SCHEMA_VERSION,
        "summary": summary,
        "baseline": _run_snapshot(baseline),
        "diagnostic": _run_snapshot(status),
        "objective_comparable": objective_comparable,
        "objective_delta": objective_delta,
        "gap_percent_delta": gap_percent_delta,
        "adjusted_rule_ids": sorted(adjusted_rules),
        "top_changes": changes[:10],
    }


def _empty(message: str) -> dict[str, Any]:
    return {
        "schema_version": DIAGNOSTIC_COMPARISON_SCHEMA_VERSION,
        "summary": {
            "status": "unavailable",
            "status_label": "暂无对比",
            "message": message,
        },
        "baseline": {},
        "diagnostic": {},
        "objective_comparable": False,
        "objective_delta": None,
        "gap_percent_delta": None,
        "adjusted_rule_ids": [],
        "top_changes": [],
    }


def _find_baseline_status(current_run: Path, current_status: dict[str, Any], root: Path) -> dict[str, Any]:
    web_runs = root / "outputs" / "web_runs"
    if not web_runs.exists():
        return {}
    current_started = _parse_time(current_status.get("started_at"))
    candidates: list[tuple[float, Path, dict[str, Any]]] = []
    for path in web_runs.glob("run_*/status.json"):
        run_dir = path.parent.resolve()
        if run_dir == current_run.resolve():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if str(data.get("run_purpose") or "") == "diagnostic_trial":
            continue
        if str(data.get("status") or "") != "completed":
            continue
        if str(data.get("solver_status") or "").upper() not in {"FEASIBLE", "OPTIMAL"}:
            continue
        started = _parse_time(data.get("started_at")) or path.stat().st_mtime
        if current_started is not None and started > current_started:
            continue
        candidates.append((started, path, data))
    if not candidates:
        return {}
    candidates.sort(key=lambda item: (item[0], str(item[1])), reverse=True)
    return candidates[0][2]


def _parse_time(value: Any) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(text[:19], fmt).timestamp()
        except ValueError:
            continue
    return None


def _safe_dir(raw: Any, root: Path) -> Path | None:
    text = str(raw or "").strip()
    if not text:
        return None
    path = Path(text)
    if not path.is_absolute():
        path = root / path
    try:
        target = path.resolve()
    except OSError:
        return None
    if target != root and root not in target.parents:
        return None
    return target if target.exists() and target.is_dir() else None


def _breakdown_rows(status: dict[str, Any]) -> dict[str, dict[str, Any]]:
    breakdown = status.get("objective_breakdown") if isinstance(status.get("objective_breakdown"), dict) else {}
    rows = breakdown.get("top") if isinstance(breakdown.get("top"), list) else []
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        rule_id = str(row.get("rule_id") or row.get("rule_name") or "").strip()
        if not rule_id:
            continue
        out[rule_id] = row
    return out


def _adjusted_rule_ids(status: dict[str, Any]) -> set[str]:
    out: set[str] = set()
    for item in _active_relaxations(status):
        patches = item.get("patches") if isinstance(item.get("patches"), list) else []
        for patch in patches:
            if not isinstance(patch, dict):
                continue
            label = str(patch.get("path_label") or ".".join(str(part) for part in (patch.get("path") or []))).strip()
            rule_id = _rule_id_from_patch(label)
            if rule_id:
                out.add(rule_id)
    return out


def _active_relaxations(status: dict[str, Any]) -> list[dict[str, Any]]:
    rows = status.get("active_diagnostic_relaxations") if isinstance(status.get("active_diagnostic_relaxations"), list) else []
    return [item for item in rows if isinstance(item, dict)]


def _rule_id_from_patch(label: str) -> str:
    leaf = label.split(".")[-1]
    if leaf.startswith("w_"):
        return leaf[2:]
    if leaf in {"require_teacher_has_class_that_day", "w_require_teacher_has_class_that_day"}:
        return "night_checkin_need_same_day_class"
    if leaf.endswith("_weight"):
        return leaf[: -len("_weight")]
    return ""


def _compare_rule_ids(
    baseline: dict[str, dict[str, Any]],
    current: dict[str, dict[str, Any]],
    adjusted_rules: set[str],
) -> list[str]:
    ordered: list[str] = []
    for rule_id in list(adjusted_rules) + list(baseline.keys()) + list(current.keys()):
        if rule_id not in ordered:
            ordered.append(rule_id)
    return ordered


def _rule_change(rule_id: str, baseline: dict[str, Any] | None, current: dict[str, Any] | None, *, adjusted: bool) -> dict[str, Any]:
    baseline = baseline or {}
    current = current or {}
    return {
        "rule_id": rule_id,
        "rule_name": str(current.get("rule_name") or baseline.get("rule_name") or rule_id),
        "adjusted": adjusted,
        "baseline_penalty": _as_float(baseline.get("penalty_sum")),
        "diagnostic_penalty": _as_float(current.get("penalty_sum")),
        "penalty_delta": _delta(current.get("penalty_sum"), baseline.get("penalty_sum")),
        "baseline_count": _as_float(baseline.get("count")),
        "diagnostic_count": _as_float(current.get("count")),
        "count_delta": _delta(current.get("count"), baseline.get("count")),
        "baseline_share": _as_float(baseline.get("share")),
        "diagnostic_share": _as_float(current.get("share")),
    }


def _run_snapshot(status: dict[str, Any]) -> dict[str, Any]:
    return {
        "run_id": str(status.get("run_id") or Path(str(status.get("run_dir") or "")).name),
        "run_purpose": str(status.get("run_purpose") or "formal"),
        "solver_status": str(status.get("solver_status") or ""),
        "objective_value": _as_float(status.get("objective_value")),
        "best_bound": _as_float(status.get("best_bound")),
        "objective_gap": _as_float(status.get("objective_gap")),
        "gap_percent": _as_float(status.get("gap_percent")),
        "optimality_status": str(status.get("optimality_status") or ""),
    }


def _summary(
    *,
    objective_delta: float | None,
    gap_percent_delta: float | None,
    objective_comparable: bool,
    adjusted_count: int,
    unchanged_adjusted: list[dict[str, Any]],
    reduced_adjusted: list[dict[str, Any]],
) -> dict[str, Any]:
    if adjusted_count and unchanged_adjusted and not reduced_adjusted:
        message = "诊断试跑降低了部分权重，但被调规则的违例次数未下降；目标值变化主要是重定价，不能视为课表质量改善。"
        status = "warning"
        label = "仅重定价"
    elif reduced_adjusted:
        message = "诊断试跑减少了部分被调规则的违例次数，可作为后续正式调参或局部修复候选。"
        status = "review"
        label = "有结构变化"
    else:
        message = "诊断试跑已完成，可结合目标值、gap 和主导规则变化继续复核。"
        status = "review"
        label = "需复核"
    if objective_delta is not None:
        message += f" 目标值变化 {objective_delta:g}。"
    if gap_percent_delta is not None:
        message += f" gap 百分点变化 {gap_percent_delta:g}。"
    if not objective_comparable:
        message += " 本次修改包含权重变化，目标值只能和规则违例次数一起解读。"
    return {
        "status": status,
        "status_label": label,
        "message": message,
        "objective_comparable": objective_comparable,
        "adjusted_rule_count": adjusted_count,
        "unchanged_adjusted_rule_count": len(unchanged_adjusted),
        "reduced_adjusted_rule_count": len(reduced_adjusted),
    }


def _has_weight_patch(status: dict[str, Any]) -> bool:
    for item in _active_relaxations(status):
        patches = item.get("patches") if isinstance(item.get("patches"), list) else []
        for patch in patches:
            if not isinstance(patch, dict):
                continue
            label = str(patch.get("path_label") or ".".join(str(part) for part in (patch.get("path") or []))).lower()
            if ".w_" in label or label.split(".")[-1].startswith("w_") or "weight" in label or "penalty" in label:
                return True
    return False


def _delta(current: Any, baseline: Any) -> float | None:
    current_value = _as_float(current)
    baseline_value = _as_float(baseline)
    if current_value is None or baseline_value is None:
        return None
    return round(current_value - baseline_value, 6)


def _as_float(value: Any) -> float | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
