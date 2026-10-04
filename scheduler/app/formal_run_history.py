# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def build_formal_run_comparison(status: dict[str, Any], project_root: Path) -> dict[str, Any]:
    """Compare a formal run with prior formal runs under the same config hash."""
    if not isinstance(status, dict):
        return {}
    if str(status.get("run_purpose") or "") == "diagnostic_trial":
        return {}
    current = _run_summary(status)
    current_objective = current.get("objective_value")
    if current_objective is None:
        return _empty_comparison("unavailable", "当前批次未记录目标值，无法与历史正式批次比较。", current)
    run_hash = _fingerprint_hash(status.get("config_fingerprint"))
    current_run_id = str(status.get("run_id") or Path(str(status.get("run_dir") or "")).name)
    history_root = _history_root(status, project_root)
    prior = [
        item
        for item in _iter_formal_statuses(history_root, exclude_run_id=current_run_id)
        if item.get("objective_value") is not None
        and (not run_hash or item.get("config_hash") == run_hash)
    ]
    if not prior:
        return _empty_comparison("no_comparable_prior", "未找到同配置历史正式批次；当前批次作为比较基线。", current)
    best_prior = min(prior, key=lambda item: (float(item["objective_value"]), str(item.get("completed_at") or "")))
    delta = round(float(current_objective) - float(best_prior["objective_value"]), 6)
    tolerance = 1e-6
    if delta > tolerance:
        status_key = "regressed"
        message = f"本批次目标值比历史最好正式批次高 {delta}，不应自动替代历史最好候选。"
        recommendation = "保留历史最好正式批次作为当前候选；本批次只作为继续迭代记录或排障比较材料。"
    elif delta < -tolerance:
        status_key = "improved"
        message = f"本批次目标值比历史最好正式批次低 {abs(delta)}，可作为新的更优候选。"
        recommendation = "使用本批次作为新的正式候选，并继续完成严格发布验收。"
    else:
        status_key = "tie"
        message = "本批次目标值与历史最好正式批次持平。"
        recommendation = "可按发布时间、复核材料完整性和业务复核结果选择候选批次。"
    return {
        "schema_version": "scheduler.formal_run_comparison.v1",
        "summary": {
            "status": status_key,
            "message": message,
            "recommendation": recommendation,
            "comparable_prior_count": len(prior),
        },
        "current": current,
        "best_prior": _public_prior(best_prior),
        "delta_objective": delta,
        "config_hash": run_hash,
    }


def build_recommended_formal_candidate(status: dict[str, Any], project_root: Path) -> dict[str, Any]:
    """Select the best formal candidate run under the current run config hash."""
    if not isinstance(status, dict):
        return {}
    if str(status.get("run_purpose") or "") == "diagnostic_trial":
        return _empty_candidate("unavailable", "当前批次是诊断试跑，不能推荐为正式候选。", {}, "", [])
    run_hash = _fingerprint_hash(status.get("config_fingerprint"))
    current = _run_summary(status)
    rows: dict[str, dict[str, Any]] = {}
    current_row = _formal_candidate_row(status)
    if current_row and (not run_hash or current_row.get("config_hash") == run_hash):
        rows[str(current_row.get("run_id") or "")] = current_row
    for row in _iter_formal_statuses(_history_root(status, project_root), exclude_run_id=""):
        if run_hash and row.get("config_hash") != run_hash:
            continue
        rows[str(row.get("run_id") or "")] = row
    candidates = [row for key, row in rows.items() if key and row.get("objective_value") is not None]
    if not candidates:
        return _empty_candidate("unavailable", "未找到同配置可推荐的正式候选批次。", current, run_hash, [])

    ordered = sorted(candidates, key=_candidate_sort_key)
    candidate = ordered[0]
    current_run_id = str(current.get("run_id") or "")
    selected_run_id = str(candidate.get("run_id") or "")
    if selected_run_id == current_run_id:
        status_key = "current_best"
        message = "当前批次是同配置正式批次中的最低目标值候选。"
        recommendation = "使用当前批次作为正式候选，并继续完成严格发布验收。"
    else:
        status_key = "historical_best"
        message = f"推荐保留历史正式批次 {selected_run_id}，其目标值低于当前批次或当前批次不可作为候选。"
        recommendation = "不要因继续求解产生了新批次就自动替换候选；以推荐批次作为当前交付候选。"
    quality_evidence = _build_quality_evidence(candidate, ordered)
    return {
        "schema_version": "scheduler.recommended_formal_candidate.v1",
        "summary": {
            "status": status_key,
            "message": message,
            "recommendation": recommendation,
            "candidate_count": len(candidates),
            "current_run_id": current_run_id,
            "selected_run_id": selected_run_id,
        },
        "candidate": _public_prior(candidate),
        "current": current,
        "alternatives": [_public_prior(row) for row in ordered[1:6]],
        "quality_evidence": quality_evidence,
        "config_hash": run_hash,
    }


def _empty_comparison(status_key: str, message: str, current: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "scheduler.formal_run_comparison.v1",
        "summary": {
            "status": status_key,
            "message": message,
            "recommendation": "",
            "comparable_prior_count": 0,
        },
        "current": current,
        "best_prior": {},
        "delta_objective": None,
        "config_hash": "",
    }


def _empty_candidate(
    status_key: str,
    message: str,
    current: dict[str, Any],
    config_hash: str,
    candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "schema_version": "scheduler.recommended_formal_candidate.v1",
        "summary": {
            "status": status_key,
            "message": message,
            "recommendation": "",
            "candidate_count": len(candidates),
            "current_run_id": str(current.get("run_id") or ""),
            "selected_run_id": "",
        },
        "candidate": {},
        "current": current,
        "alternatives": [_public_prior(row) for row in candidates[:5]],
        "quality_evidence": {},
        "config_hash": config_hash,
    }


def _history_root(status: dict[str, Any], project_root: Path) -> Path:
    """Use the current run's tenant-scoped directory when one is available."""
    run_dir_raw = str(status.get("run_dir") or "").strip()
    if run_dir_raw:
        run_dir = Path(run_dir_raw)
        if run_dir.name.startswith("run_"):
            return run_dir.parent
    return project_root / "outputs" / "web_runs"


def _iter_formal_statuses(root: Path, *, exclude_run_id: str = "") -> list[dict[str, Any]]:
    if not root.exists():
        return []
    rows: list[dict[str, Any]] = []
    for path in root.glob("run_*/status.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        run_id = str(payload.get("run_id") or path.parent.name)
        if exclude_run_id and run_id == exclude_run_id:
            continue
        row = _formal_candidate_row(payload)
        if not row:
            continue
        row["status_file"] = str(path)
        rows.append(row)
    return rows


def _formal_candidate_row(status: dict[str, Any]) -> dict[str, Any] | None:
    if str(status.get("run_purpose") or "") == "diagnostic_trial":
        return None
    if str(status.get("status") or "") not in {"completed", "ready"}:
        return None
    if str(status.get("solver_status") or "").upper() not in {"FEASIBLE", "OPTIMAL"}:
        return None
    objective = _to_float(status.get("objective_value", status.get("best_objective")))
    if objective is None:
        return None
    row = _run_summary(status)
    row["objective_value"] = objective
    row["status_file"] = str(status.get("status_file") or "")
    row["config_hash"] = _fingerprint_hash(status.get("config_fingerprint"))
    return row


def _run_summary(status: dict[str, Any]) -> dict[str, Any]:
    return {
        "run_id": str(status.get("run_id") or Path(str(status.get("run_dir") or "")).name),
        "status": str(status.get("status") or ""),
        "solver_status": str(status.get("solver_status") or ""),
        "objective_value": _to_float(status.get("objective_value", status.get("best_objective"))),
        "best_bound": _to_float(status.get("best_bound")),
        "objective_gap": _to_float(status.get("objective_gap")),
        "gap_percent": _to_float(status.get("gap_percent")),
        "publish_status": _publish_status(status),
        "completed_at": str(status.get("completed_at") or ""),
        "run_dir": str(status.get("run_dir") or ""),
        "package_file": str(status.get("package_file") or ""),
        "solver_profile": str(status.get("solver_profile") or ""),
    }


def _candidate_sort_key(row: dict[str, Any]) -> tuple[float, int, int, str, str]:
    publish_priority = {"ready": 0, "blocked": 1, "": 2}.get(str(row.get("publish_status") or ""), 2)
    objective = _to_float(row.get("objective_value"))
    return (
        float("inf") if objective is None else objective,
        publish_priority,
        0,
        str(row.get("completed_at") or ""),
        str(row.get("run_id") or ""),
    )


def _build_quality_evidence(candidate: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    candidate_objective = _to_float(candidate.get("objective_value"))
    if candidate_objective is None:
        return {}
    bounded = [row for row in rows if _to_float(row.get("best_bound")) is not None]
    if not bounded:
        return {}

    proof = max(
        bounded,
        key=lambda row: (
            _sort_float(_to_float(row.get("best_bound")), missing=float("-inf")),
            -_sort_float(_to_float(row.get("objective_value")), missing=float("inf")),
            str(row.get("completed_at") or ""),
            str(row.get("run_id") or ""),
        ),
    )
    proof_bound = _to_float(proof.get("best_bound"))
    if proof_bound is None:
        return {}

    candidate_bound = _to_float(candidate.get("best_bound"))
    bound_improvement = None
    if candidate_bound is not None:
        bound_improvement = round(max(0.0, proof_bound - candidate_bound), 6)
    candidate_gap = round(max(0.0, candidate_objective - proof_bound), 6)
    candidate_gap_percent = _gap_percent(candidate_gap, candidate_objective)

    candidate_run_id = str(candidate.get("run_id") or "")
    proof_run_id = str(proof.get("run_id") or "")
    if proof_run_id == candidate_run_id:
        status = "candidate_bound"
        message = "推荐正式候选自身提供当前同配置最强求解下界。"
    elif bound_improvement and bound_improvement > 1e-6:
        status = "bound_improved"
        message = (
            f"批次 {proof_run_id} 未替代推荐候选，但提供更强求解下界；"
            "可用该下界重算推荐候选的剩余最优性缺口。"
        )
    else:
        status = "external_bound"
        message = f"批次 {proof_run_id} 提供同配置求解下界，可作为推荐候选的证明材料。"

    return {
        "schema_version": "scheduler.formal_quality_evidence.v1",
        "summary": {
            "status": status,
            "message": message,
            "candidate_run_id": candidate_run_id,
            "proof_run_id": proof_run_id,
            "proof_best_bound": proof_bound,
            "candidate_objective_gap": candidate_gap,
            "candidate_gap_percent": candidate_gap_percent,
            "bound_improvement_over_candidate_run": bound_improvement,
        },
        "candidate": _public_prior(candidate),
        "proof_bound_run": _public_prior(proof),
        "config_hash": str(candidate.get("config_hash") or proof.get("config_hash") or ""),
    }


def _public_prior(row: dict[str, Any]) -> dict[str, Any]:
    return {
        key: row.get(key)
        for key in (
            "run_id",
            "status",
            "solver_status",
            "objective_value",
            "best_bound",
            "objective_gap",
            "gap_percent",
            "publish_status",
            "completed_at",
            "run_dir",
            "package_file",
            "status_file",
            "solver_profile",
        )
    }


def _publish_status(status: dict[str, Any]) -> str:
    assessment = status.get("publish_assessment") if isinstance(status.get("publish_assessment"), dict) else {}
    summary = assessment.get("summary") if isinstance(assessment.get("summary"), dict) else {}
    value = str(summary.get("status") or "")
    return "ready" if value == "review" else value


def _fingerprint_hash(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("hash") or "").strip()
    return str(value or "").strip()


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _gap_percent(gap: float, objective: float) -> float | None:
    if objective == 0:
        return None
    return round(gap / abs(objective) * 100.0, 6)


def _sort_float(value: float | None, *, missing: float) -> float:
    return missing if value is None else float(value)
