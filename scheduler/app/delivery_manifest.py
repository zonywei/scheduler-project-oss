# -*- coding: utf-8 -*-
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from scheduler.app.result_availability import build_result_availability
from scheduler.app.release_messages import release_aware_run_message, release_state_summary
from scheduler.app.runtime_audit_artifacts import (
    RUNTIME_AUDIT_RELEASE_USE,
    runtime_audit_artifact_key,
    runtime_audit_display_name,
)


MANIFEST_FILENAME = "delivery_manifest.json"
MANIFEST_SCHEMA_VERSION = "scheduler.delivery_manifest.v1"
MAX_HASH_BYTES = 100 * 1024 * 1024


def build_delivery_manifest(
    status: dict[str, Any],
    artifacts: list[dict[str, Any]],
    *,
    package_path: Path | None = None,
) -> dict[str, Any]:
    status = status if isinstance(status, dict) else {}
    assessment = status.get("publish_assessment") if isinstance(status.get("publish_assessment"), dict) else {}
    publish_summary = assessment.get("summary") if isinstance(assessment.get("summary"), dict) else {}
    solve_diagnostics = status.get("solve_diagnostics") if isinstance(status.get("solve_diagnostics"), dict) else {}
    diagnostic_summary = solve_diagnostics.get("summary") if isinstance(solve_diagnostics.get("summary"), dict) else {}
    categories = assessment.get("file_categories") if isinstance(assessment.get("file_categories"), dict) else {}
    current_readiness = status.get("current_readiness") if isinstance(status.get("current_readiness"), dict) else {}
    package_integrity = status.get("package_integrity") if isinstance(status.get("package_integrity"), dict) else {}
    run_message = release_aware_run_message(status)
    release_state = release_state_summary(status, run_message=run_message)

    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "generated_at": _iso_now(),
        "release_state": release_state,
        "release_decision": {
            "status": str(publish_summary.get("status") or "unknown"),
            "status_label": str(publish_summary.get("status_label") or "待评估"),
            "can_publish": bool(publish_summary.get("can_publish", False)),
            "formal_release_ready": _formal_release_ready(publish_summary),
            "errors": int(publish_summary.get("errors") or 0),
            "warnings": int(publish_summary.get("warnings") or 0),
            "blocking_titles": _gate_titles(assessment, severity="error"),
            "warning_titles": _gate_titles(assessment, severity="warning"),
        },
        "result_availability": _manifest_result_availability(status),
        "run": {
            "run_id": str(status.get("run_id") or ""),
            "mode": str(status.get("mode") or ""),
            "status": str(status.get("status") or ""),
            "message": run_message,
            "run_purpose": str(status.get("run_purpose") or "formal"),
            "diagnostic_plan_id": str(status.get("diagnostic_plan_id") or ""),
            "diagnostic_plan_title": str(status.get("diagnostic_plan_title") or ""),
            "active_diagnostic_relaxations": _manifest_diagnostic_relaxations(
                status.get("active_diagnostic_relaxations") if isinstance(status.get("active_diagnostic_relaxations"), list) else []
            ),
            "runtime_parameters": _manifest_runtime_parameters(status),
            "started_at": str(status.get("started_at") or ""),
            "completed_at": str(status.get("completed_at") or ""),
            "run_dir": str(status.get("run_dir") or ""),
        },
        "config": {
            "run_fingerprint": _fingerprint(status.get("config_fingerprint")),
            "current_fingerprint": _fingerprint(status.get("current_config_fingerprint")),
            "fingerprint_match": status.get("config_fingerprint_match"),
            "freshness": status.get("config_freshness") if isinstance(status.get("config_freshness"), dict) else {},
        },
        "solver": {
            "solver_status": str(status.get("solver_status") or (assessment.get("outcome") or {}).get("solver_status") or ""),
            "solution_count": status.get("solution_count", (assessment.get("outcome") or {}).get("solution_count")),
            "schedule_file_count": int(status.get("schedule_file_count") or categories.get("schedule") or 0),
            "best_objective": str((assessment.get("outcome") or {}).get("best_objective") or ""),
            "objective_value": _optional_float(status.get("objective_value", (assessment.get("outcome") or {}).get("objective_value"))),
            "best_bound": _optional_float(status.get("best_bound", (assessment.get("outcome") or {}).get("best_bound"))),
            "objective_gap": _optional_float(status.get("objective_gap", (assessment.get("outcome") or {}).get("objective_gap"))),
            "gap_percent": _optional_float(status.get("gap_percent", (assessment.get("outcome") or {}).get("gap_percent"))),
            "optimality_status": str(status.get("optimality_status") or (assessment.get("outcome") or {}).get("optimality_status") or ""),
            "objective_breakdown": _manifest_objective_breakdown(status.get("objective_breakdown")),
            "formal_run_comparison": _manifest_formal_run_comparison(status.get("formal_run_comparison")),
            "recommended_formal_candidate": _manifest_recommended_formal_candidate(status.get("recommended_formal_candidate")),
        },
        "publish_assessment": {
            "summary": publish_summary,
            "gates": _manifest_gates(assessment.get("gates") if isinstance(assessment.get("gates"), list) else []),
            "next_actions": assessment.get("next_actions") if isinstance(assessment.get("next_actions"), list) else [],
        },
        "current_readiness": _manifest_readiness(current_readiness),
        "solve_diagnostics": {
            "summary": diagnostic_summary,
            "next_actions": solve_diagnostics.get("next_actions") if isinstance(solve_diagnostics.get("next_actions"), list) else [],
            "quality_plan": _manifest_quality_plan(solve_diagnostics.get("quality_plan")),
            "business_floor_notes": _manifest_business_floor_notes(solve_diagnostics.get("business_floor_notes")),
            "business_floor_adjusted_quality": _manifest_business_floor_adjusted_quality(
                solve_diagnostics.get("business_floor_adjusted_quality")
            ),
        },
        "runtime_audit": _manifest_runtime_audit(artifacts, status),
        "diagnostic_comparison": _manifest_diagnostic_comparison(status.get("diagnostic_comparison")),
        "package_integrity": _manifest_package_integrity(package_integrity),
        "artifacts": {
            "total": len(artifacts),
            "categories": categories,
            "package": str(package_path) if package_path else str(status.get("package_file") or ""),
            "files": [_manifest_artifact(item, status) for item in artifacts if isinstance(item, dict)],
        },
    }


def write_delivery_manifest(
    run_dir: Path,
    status: dict[str, Any],
    artifacts: list[dict[str, Any]],
    *,
    package_path: Path | None = None,
) -> Path:
    path = run_dir / MANIFEST_FILENAME
    manifest = build_delivery_manifest(status, artifacts, package_path=package_path)
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _iso_now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _fingerprint(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {
        "mode": str(value.get("mode") or ""),
        "hash": str(value.get("hash") or ""),
        "generated_at": str(value.get("generated_at") or ""),
    }


def _formal_release_ready(publish_summary: dict[str, Any]) -> bool:
    return str(publish_summary.get("status") or "") == "ready"


def _manifest_runtime_parameters(status: dict[str, Any]) -> dict[str, Any]:
    params = {
        "grade_prefix": str(status.get("grade_prefix") or ""),
        "time_limit_seconds": _optional_int(status.get("time_limit_seconds")),
        "workers": _optional_int(status.get("workers")),
        "max_keep": _optional_int(status.get("max_keep")),
        "snapshot_interval_sec": _optional_int(status.get("snapshot_interval_sec")),
        "enable_snapshots": _optional_bool(status.get("enable_snapshots")),
        "random_seed": _optional_int(status.get("random_seed")),
    }
    optional = {
        "relative_gap_limit": _optional_float(status.get("relative_gap_limit")),
        "absolute_gap_limit": _optional_float(status.get("absolute_gap_limit")),
        "log_search_progress": _optional_bool(status.get("log_search_progress")),
        "continue_from_best": _optional_bool(status.get("continue_from_best")),
    }
    params.update({key: value for key, value in optional.items() if value is not None})
    if str(status.get("solver_profile") or "").strip():
        params["solver_profile"] = str(status.get("solver_profile") or "").strip()
    return params


def _manifest_objective_breakdown(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    summary = value.get("summary") if isinstance(value.get("summary"), dict) else {}
    top = value.get("top") if isinstance(value.get("top"), list) else []
    return {
        "schema_version": str(value.get("schema_version") or "scheduler.result_rule_explain.v1"),
        "summary": {
            "status": str(summary.get("status") or ""),
            "status_label": str(summary.get("status_label") or ""),
            "message": str(summary.get("message") or ""),
            "total_penalty": _optional_float(summary.get("total_penalty")),
            "reward_credit": _optional_float(summary.get("reward_credit")),
            "net_event_penalty": _optional_float(summary.get("net_event_penalty")),
            "solver_objective_value": _optional_float(summary.get("solver_objective_value")),
            "objective_explain_delta": _optional_float(summary.get("objective_explain_delta")),
            "objective_reconciliation_status": str(summary.get("objective_reconciliation_status") or ""),
            "rule_count": _optional_int(summary.get("rule_count")),
            "source": str(summary.get("source") or ""),
            "source_label": str(summary.get("source_label") or ""),
        },
        "top": [_manifest_objective_rule(item) for item in top[:8] if isinstance(item, dict)],
    }


def _manifest_formal_run_comparison(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    summary = value.get("summary") if isinstance(value.get("summary"), dict) else {}
    current = value.get("current") if isinstance(value.get("current"), dict) else {}
    best_prior = value.get("best_prior") if isinstance(value.get("best_prior"), dict) else {}
    return {
        "schema_version": str(value.get("schema_version") or "scheduler.formal_run_comparison.v1"),
        "summary": {
            "status": str(summary.get("status") or ""),
            "message": str(summary.get("message") or ""),
            "recommendation": str(summary.get("recommendation") or ""),
            "comparable_prior_count": _optional_int(summary.get("comparable_prior_count")),
        },
        "current": _manifest_run_comparison_item(current),
        "best_prior": _manifest_run_comparison_item(best_prior),
        "delta_objective": _optional_float(value.get("delta_objective")),
        "config_hash": str(value.get("config_hash") or ""),
    }


def _manifest_recommended_formal_candidate(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    summary = value.get("summary") if isinstance(value.get("summary"), dict) else {}
    alternatives = value.get("alternatives") if isinstance(value.get("alternatives"), list) else []
    return {
        "schema_version": str(value.get("schema_version") or "scheduler.recommended_formal_candidate.v1"),
        "summary": {
            "status": str(summary.get("status") or ""),
            "message": str(summary.get("message") or ""),
            "recommendation": str(summary.get("recommendation") or ""),
            "candidate_count": _optional_int(summary.get("candidate_count")),
            "current_run_id": str(summary.get("current_run_id") or ""),
            "selected_run_id": str(summary.get("selected_run_id") or ""),
        },
        "candidate": _manifest_run_comparison_item(value.get("candidate") if isinstance(value.get("candidate"), dict) else {}),
        "current": _manifest_run_comparison_item(value.get("current") if isinstance(value.get("current"), dict) else {}),
        "alternatives": [_manifest_run_comparison_item(item) for item in alternatives[:5] if isinstance(item, dict)],
        "quality_evidence": _manifest_formal_quality_evidence(value.get("quality_evidence")),
        "config_hash": str(value.get("config_hash") or ""),
    }


def _manifest_formal_quality_evidence(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    summary = value.get("summary") if isinstance(value.get("summary"), dict) else {}
    return {
        "schema_version": str(value.get("schema_version") or "scheduler.formal_quality_evidence.v1"),
        "summary": {
            "status": str(summary.get("status") or ""),
            "message": str(summary.get("message") or ""),
            "candidate_run_id": str(summary.get("candidate_run_id") or ""),
            "proof_run_id": str(summary.get("proof_run_id") or ""),
            "proof_best_bound": _optional_float(summary.get("proof_best_bound")),
            "candidate_objective_gap": _optional_float(summary.get("candidate_objective_gap")),
            "candidate_gap_percent": _optional_float(summary.get("candidate_gap_percent")),
            "bound_improvement_over_candidate_run": _optional_float(summary.get("bound_improvement_over_candidate_run")),
        },
        "candidate": _manifest_run_comparison_item(value.get("candidate") if isinstance(value.get("candidate"), dict) else {}),
        "proof_bound_run": _manifest_run_comparison_item(
            value.get("proof_bound_run") if isinstance(value.get("proof_bound_run"), dict) else {}
        ),
        "config_hash": str(value.get("config_hash") or ""),
    }


def _manifest_run_comparison_item(value: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {
        "run_id": str(value.get("run_id") or ""),
        "solver_status": str(value.get("solver_status") or ""),
        "objective_value": _optional_float(value.get("objective_value")),
        "best_bound": _optional_float(value.get("best_bound")),
        "objective_gap": _optional_float(value.get("objective_gap")),
        "gap_percent": _optional_float(value.get("gap_percent")),
        "publish_status": str(value.get("publish_status") or ""),
        "review_confirmed": _optional_bool(value.get("review_confirmed")),
        "completed_at": str(value.get("completed_at") or ""),
        "run_dir": str(value.get("run_dir") or ""),
        "package_file": str(value.get("package_file") or ""),
        "solver_profile": str(value.get("solver_profile") or ""),
    }


def _manifest_objective_rule(item: dict[str, Any]) -> dict[str, Any]:
    offenders = item.get("top_offenders") if isinstance(item.get("top_offenders"), list) else []
    examples = item.get("example_events") if isinstance(item.get("example_events"), list) else []
    return {
        "rank": _optional_int(item.get("rank")),
        "rule_id": str(item.get("rule_id") or ""),
        "rule_name": str(item.get("rule_name") or ""),
        "penalty_sum": _optional_float(item.get("penalty_sum")),
        "share": _optional_float(item.get("share")),
        "count": _optional_float(item.get("count")),
        "severity": str(item.get("severity") or ""),
        "action": str(item.get("action") or ""),
        "potential_penalty_reduction": _optional_float(item.get("potential_penalty_reduction")),
        "top_offenders": [
            {
                "entity": str(offender.get("entity") or ""),
                "penalty_sum": _optional_float(offender.get("penalty_sum")),
            }
            for offender in offenders[:5]
            if isinstance(offender, dict)
        ],
        "example_events": [_manifest_objective_event(event) for event in examples[:6] if isinstance(event, dict)],
    }


def _manifest_objective_event(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "teacher": str(item.get("teacher") or ""),
        "day": str(item.get("day") or ""),
        "period": str(item.get("period") or ""),
        "class_name": str(item.get("class_name") or ""),
        "subject": str(item.get("subject") or ""),
        "penalty": _optional_float(item.get("penalty")),
        "unit_penalty": _optional_float(item.get("unit_penalty")),
        "count": _optional_float(item.get("count")),
        "description": str(item.get("description") or ""),
    }


def _manifest_diagnostic_comparison(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    summary = value.get("summary") if isinstance(value.get("summary"), dict) else {}
    top_changes = value.get("top_changes") if isinstance(value.get("top_changes"), list) else []
    return {
        "schema_version": str(value.get("schema_version") or "scheduler.diagnostic_comparison.v1"),
        "summary": {
            "status": str(summary.get("status") or ""),
            "status_label": str(summary.get("status_label") or ""),
            "message": str(summary.get("message") or ""),
            "objective_comparable": _optional_bool(summary.get("objective_comparable")),
            "adjusted_rule_count": _optional_int(summary.get("adjusted_rule_count")),
            "unchanged_adjusted_rule_count": _optional_int(summary.get("unchanged_adjusted_rule_count")),
            "reduced_adjusted_rule_count": _optional_int(summary.get("reduced_adjusted_rule_count")),
        },
        "baseline": _manifest_run_snapshot(value.get("baseline")),
        "diagnostic": _manifest_run_snapshot(value.get("diagnostic")),
        "objective_comparable": _optional_bool(value.get("objective_comparable")),
        "objective_delta": _optional_float(value.get("objective_delta")),
        "gap_percent_delta": _optional_float(value.get("gap_percent_delta")),
        "adjusted_rule_ids": [str(item) for item in value.get("adjusted_rule_ids", []) if str(item).strip()][:8]
        if isinstance(value.get("adjusted_rule_ids"), list)
        else [],
        "top_changes": [_manifest_comparison_change(item) for item in top_changes[:8] if isinstance(item, dict)],
    }


def _manifest_quality_plan(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    steps = value.get("steps") if isinstance(value.get("steps"), list) else []
    current = _manifest_run_snapshot(value.get("current"))
    current_value = value.get("current") if isinstance(value.get("current"), dict) else {}
    adjusted = _manifest_business_floor_adjusted_quality(current_value.get("business_floor_adjusted_quality"))
    if adjusted:
        current["business_floor_adjusted_quality"] = adjusted
    attempt_count = _optional_int(current_value.get("attempt_count"))
    if attempt_count is not None:
        current["attempt_count"] = attempt_count
    attempt_history = current_value.get("attempt_history") if isinstance(current_value.get("attempt_history"), list) else []
    if attempt_history:
        current["attempt_history"] = [
            _manifest_quality_attempt(item) for item in attempt_history[:8] if isinstance(item, dict)
        ]
    return {
        "schema_version": str(value.get("schema_version") or "scheduler.solve_quality_plan.v1"),
        "status": str(value.get("status") or ""),
        "status_label": str(value.get("status_label") or ""),
        "message": str(value.get("message") or ""),
        "current": current,
        "steps": [_manifest_quality_step(item) for item in steps[:5] if isinstance(item, dict)],
    }


def _manifest_quality_attempt(value: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": str(value.get("source") or ""),
        "run_id": str(value.get("run_id") or ""),
        "solver_profile": str(value.get("solver_profile") or ""),
        "random_seed": _optional_int(value.get("random_seed")),
        "objective_value": _optional_float(value.get("objective_value")),
        "best_bound": _optional_float(value.get("best_bound")),
        "objective_gap": _optional_float(value.get("objective_gap")),
        "gap_percent": _optional_float(value.get("gap_percent")),
        "completed_at": str(value.get("completed_at") or ""),
    }


def _manifest_business_floor_notes(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [_manifest_business_floor_note(item) for item in value[:6] if isinstance(item, dict)]


def _manifest_business_floor_note(value: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(value.get("id") or ""),
        "domain": str(value.get("domain") or ""),
        "title": str(value.get("title") or ""),
        "status": str(value.get("status") or ""),
        "penalty_sum": _optional_float(value.get("penalty_sum")),
        "shortage_count": _optional_int(value.get("shortage_count")),
        "potential_penalty_reduction": _optional_float(value.get("potential_penalty_reduction")),
        "days": [str(item) for item in value.get("days", []) if str(item).strip()][:14]
        if isinstance(value.get("days"), list)
        else [],
        "assigned_teachers": [str(item) for item in value.get("assigned_teachers", []) if str(item).strip()][:20]
        if isinstance(value.get("assigned_teachers"), list)
        else [],
        "pending_candidates": [str(item) for item in value.get("pending_candidates", []) if str(item).strip()][:20]
        if isinstance(value.get("pending_candidates"), list)
        else [],
        "ledger": [_manifest_business_floor_ledger(item) for item in value.get("ledger", [])[:8] if isinstance(item, dict)]
        if isinstance(value.get("ledger"), list)
        else [],
        "message": str(value.get("message") or ""),
        "next_action": str(value.get("next_action") or ""),
    }


def _manifest_business_floor_ledger(value: dict[str, Any]) -> dict[str, Any]:
    return {
        "day": str(value.get("day") or ""),
        "gender": str(value.get("gender") or ""),
        "duty": str(value.get("duty") or ""),
        "shortage": _optional_int(value.get("shortage")),
        "potential_penalty_reduction": _optional_float(value.get("potential_penalty_reduction")),
        "assigned_teachers": [str(item) for item in value.get("assigned_teachers", []) if str(item).strip()][:10]
        if isinstance(value.get("assigned_teachers"), list)
        else [],
        "suggested_candidates": [str(item) for item in value.get("suggested_candidates", []) if str(item).strip()][:10]
        if isinstance(value.get("suggested_candidates"), list)
        else [],
        "status": str(value.get("status") or ""),
    }


def _manifest_business_floor_adjusted_quality(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {
        "schema_version": str(value.get("schema_version") or "scheduler.business_floor_adjusted_quality.v1"),
        "status": str(value.get("status") or ""),
        "status_label": str(value.get("status_label") or ""),
        "objective_value": _optional_float(value.get("objective_value")),
        "best_bound": _optional_float(value.get("best_bound")),
        "raw_objective_gap": _optional_float(value.get("raw_objective_gap")),
        "raw_gap_percent": _optional_float(value.get("raw_gap_percent")),
        "gap_basis": str(value.get("gap_basis") or ""),
        "basis_objective_value": _optional_float(value.get("basis_objective_value")),
        "basis_best_bound": _optional_float(value.get("basis_best_bound")),
        "basis_objective_gap": _optional_float(value.get("basis_objective_gap")),
        "basis_gap_percent": _optional_float(value.get("basis_gap_percent")),
        "stronger_bound_proof": _manifest_stronger_bound_proof(value.get("stronger_bound_proof")),
        "business_floor_gap_explained": _optional_float(value.get("business_floor_gap_explained")),
        "business_floor_note_ids": [str(item) for item in value.get("business_floor_note_ids", []) if str(item).strip()][:10]
        if isinstance(value.get("business_floor_note_ids"), list)
        else [],
        "business_floor_note_summaries": _manifest_business_floor_notes(value.get("business_floor_note_summaries")),
        "adjusted_objective_gap": _optional_float(value.get("adjusted_objective_gap")),
        "adjusted_gap_percent": _optional_float(value.get("adjusted_gap_percent")),
        "message": str(value.get("message") or ""),
        "next_action": str(value.get("next_action") or ""),
    }


def _manifest_stronger_bound_proof(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {
        "run_id": str(value.get("run_id") or ""),
        "best_bound": _optional_float(value.get("best_bound")),
        "objective_gap": _optional_float(value.get("objective_gap")),
        "gap_percent": _optional_float(value.get("gap_percent")),
    }


def _manifest_quality_step(value: dict[str, Any]) -> dict[str, Any]:
    payload = value.get("start_solve_payload") if isinstance(value.get("start_solve_payload"), dict) else {}
    out = {
        "id": str(value.get("id") or ""),
        "title": str(value.get("title") or ""),
        "purpose": str(value.get("purpose") or ""),
        "expected_effect": str(value.get("expected_effect") or ""),
        "start_solve_payload": {
            "mode": str(payload.get("mode") or ""),
            "time_limit_seconds": _optional_int(payload.get("time_limit_seconds")),
            "workers": _optional_int(payload.get("workers")),
            "max_keep": _optional_int(payload.get("max_keep")),
            "random_seed": _optional_int(payload.get("random_seed")),
            "continue_from_best": _optional_bool(payload.get("continue_from_best")),
            "solver_profile": str(payload.get("solver_profile") or ""),
            "relative_gap_limit": _optional_float(payload.get("relative_gap_limit")),
            "log_search_progress": _optional_bool(payload.get("log_search_progress")),
        },
    }
    manual_action = _manifest_quality_manual_action(value.get("manual_action"))
    if manual_action:
        out["manual_action"] = manual_action
    return out


def _manifest_quality_manual_action(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {
        "action": str(value.get("action") or ""),
        "status": str(value.get("status") or ""),
        "business_floor_gap_explained": _optional_float(value.get("business_floor_gap_explained")),
        "adjusted_objective_gap": _optional_float(value.get("adjusted_objective_gap")),
        "adjusted_gap_percent": _optional_float(value.get("adjusted_gap_percent")),
        "business_floor_note_ids": [str(item) for item in value.get("business_floor_note_ids", []) if str(item).strip()][:10]
        if isinstance(value.get("business_floor_note_ids"), list)
        else [],
        "business_floor_note_summaries": _manifest_business_floor_notes(value.get("business_floor_note_summaries")),
        "next_action": str(value.get("next_action") or ""),
    }


def _manifest_run_snapshot(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {
        "run_id": str(value.get("run_id") or ""),
        "run_purpose": str(value.get("run_purpose") or ""),
        "solver_status": str(value.get("solver_status") or ""),
        "objective_value": _optional_float(value.get("objective_value")),
        "best_bound": _optional_float(value.get("best_bound")),
        "objective_gap": _optional_float(value.get("objective_gap")),
        "gap_percent": _optional_float(value.get("gap_percent")),
        "optimality_status": str(value.get("optimality_status") or ""),
    }


def _manifest_comparison_change(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "rule_id": str(item.get("rule_id") or ""),
        "rule_name": str(item.get("rule_name") or ""),
        "adjusted": bool(item.get("adjusted", False)),
        "baseline_penalty": _optional_float(item.get("baseline_penalty")),
        "diagnostic_penalty": _optional_float(item.get("diagnostic_penalty")),
        "penalty_delta": _optional_float(item.get("penalty_delta")),
        "baseline_count": _optional_float(item.get("baseline_count")),
        "diagnostic_count": _optional_float(item.get("diagnostic_count")),
        "count_delta": _optional_float(item.get("count_delta")),
    }


def _manifest_result_availability(status: dict[str, Any]) -> dict[str, Any]:
    availability = status.get("result_availability") if isinstance(status.get("result_availability"), dict) else {}
    if not availability:
        availability = build_result_availability(status)
    primary = availability.get("primary_schedule_files") if isinstance(availability.get("primary_schedule_files"), list) else []
    categories = availability.get("category_counts") if isinstance(availability.get("category_counts"), dict) else {}
    return {
        "schema_version": str(availability.get("schema_version") or "scheduler.result_availability.v1"),
        "status": str(availability.get("status") or ""),
        "label": str(availability.get("label") or ""),
        "message": str(availability.get("message") or ""),
        "tone": str(availability.get("tone") or ""),
        "has_schedule_files": bool(availability.get("has_schedule_files", False)),
        "has_result_package": bool(availability.get("has_result_package", False)),
        "schedule_file_count": int(availability.get("schedule_file_count") or 0),
        "diagnostic_file_count": int(availability.get("diagnostic_file_count") or 0),
        "package_file_count": int(availability.get("package_file_count") or 0),
        "total_file_count": int(availability.get("total_file_count") or 0),
        "package_label": str(availability.get("package_label") or ""),
        "formal_release_ready": bool(availability.get("formal_release_ready", False)),
        "hidden_schedule_file_count": int(availability.get("hidden_schedule_file_count") or 0),
        "primary_schedule_files": [_manifest_availability_file(item) for item in primary if isinstance(item, dict)][:6],
        "category_counts": {str(key): int(value or 0) for key, value in categories.items()},
    }


def _manifest_availability_file(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "label": str(item.get("label") or ""),
        "display_label": str(item.get("display_label") or ""),
        "path": str(item.get("path") or ""),
        "download_name": str(item.get("download_name") or ""),
        "release_use": str(item.get("release_use") or ""),
        "release_badge": str(item.get("release_badge") or ""),
        "size": int(item.get("size") or 0),
        "modified_at": str(item.get("modified_at") or ""),
    }


def _optional_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None or str(value).strip() == "":
        return None
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return None


def _optional_float(value: Any) -> float | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _gate_titles(assessment: dict[str, Any], *, severity: str) -> list[str]:
    return [
        str(gate.get("title") or "")
        for gate in (assessment.get("gates") or [])
        if (
            isinstance(gate, dict)
            and gate.get("severity") == severity
            and str(gate.get("title") or "")
            and (severity != "warning" or gate.get("confirmation_required") is not False)
        )
    ][:8]


def _manifest_gates(gates: list[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for gate in gates:
        if not isinstance(gate, dict):
            continue
        out.append(
            {
                "severity": str(gate.get("severity") or ""),
                "domain": str(gate.get("domain") or ""),
                "title": str(gate.get("title") or ""),
                "detail": str(gate.get("detail") or ""),
                "suggestion": str(gate.get("suggestion") or ""),
                "blocking": bool(gate.get("blocking", False)),
                "confirmation_required": gate.get("confirmation_required") is not False,
                "review_scope": str(gate.get("review_scope") or ""),
                "evidence_source": str(gate.get("evidence_source") or ""),
                "decision_points": _manifest_evidence(
                    gate.get("decision_points") if isinstance(gate.get("decision_points"), list) else []
                ),
                "checkin_supply_ledger": _manifest_checkin_supply_ledger(
                    gate.get("checkin_supply_ledger") if isinstance(gate.get("checkin_supply_ledger"), list) else []
                ),
                "candidate_data_requirements": _manifest_candidate_data_requirements(
                    gate.get("candidate_data_requirements") if isinstance(gate.get("candidate_data_requirements"), list) else []
                ),
                "remediation_options": _manifest_remediations(
                    gate.get("remediation_options") if isinstance(gate.get("remediation_options"), list) else []
                ),
            }
        )
    return out


def _manifest_readiness(readiness: dict[str, Any]) -> dict[str, Any]:
    if not readiness:
        return {}
    items = readiness.get("items") if isinstance(readiness.get("items"), list) else []
    notable = [
        _manifest_readiness_item(item)
        for item in items
        if isinstance(item, dict) and (item.get("severity") != "ok" or item.get("blocking") or item.get("publish_blocking"))
    ]
    return {
        "mode": str(readiness.get("mode") or ""),
        "checked_at": str(readiness.get("checked_at") or ""),
        "summary": readiness.get("summary") if isinstance(readiness.get("summary"), dict) else {},
        "items": notable[:12],
        "next_actions": readiness.get("next_actions") if isinstance(readiness.get("next_actions"), list) else [],
    }


def _manifest_readiness_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "severity": str(item.get("severity") or ""),
        "domain": str(item.get("domain") or ""),
        "title": str(item.get("title") or ""),
        "detail": str(item.get("detail") or ""),
        "suggestion": str(item.get("suggestion") or ""),
        "blocking": bool(item.get("blocking", False)),
        "publish_blocking": bool(item.get("publish_blocking", False)),
        "evidence": _manifest_evidence(item.get("evidence") if isinstance(item.get("evidence"), list) else []),
        "remediation_options": _manifest_remediations(
            item.get("remediation_options") if isinstance(item.get("remediation_options"), list) else []
        ),
    }


def _manifest_diagnostic_relaxations(rows: list[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        patches = row.get("patches") if isinstance(row.get("patches"), list) else []
        out.append(
            {
                "id": str(row.get("id") or ""),
                "title": str(row.get("title") or ""),
                "domain": str(row.get("domain") or ""),
                "risk": str(row.get("risk") or ""),
                "patch_count": int(row.get("patch_count") or len([patch for patch in patches if isinstance(patch, dict)])),
                "patches": [
                    {
                        "target": str(patch.get("target") or ""),
                        "path_label": str(patch.get("path_label") or ""),
                        "operation": str(patch.get("operation") or ""),
                    }
                    for patch in patches
                    if isinstance(patch, dict)
                ][:12],
            }
        )
    return out[:8]


def _manifest_evidence(rows: list[Any]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        out.append(
            {
                "label": str(row.get("label") or ""),
                "value": str(row.get("value") or ""),
                "tone": str(row.get("tone") or "info"),
            }
        )
    return out[:16]


def _manifest_checkin_supply_ledger(rows: list[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        out.append(
            {
                "day": str(row.get("day") or ""),
                "gender": str(row.get("gender") or ""),
                "duty": str(row.get("duty") or ""),
                "exception_count": int(row.get("exception_count") or 0),
                "penalty_sum": _optional_float(row.get("penalty_sum")),
                "potential_penalty_reduction": _optional_float(row.get("potential_penalty_reduction")),
                "assigned_teachers": [str(item) for item in (row.get("assigned_teachers") or []) if str(item).strip()][:8]
                if isinstance(row.get("assigned_teachers"), list)
                else [],
                "direct_candidate_count": int(row.get("direct_candidate_count") or 0),
                "direct_candidates": [str(item) for item in (row.get("direct_candidates") or []) if str(item).strip()][:8]
                if isinstance(row.get("direct_candidates"), list)
                else [],
                "suggested_candidate_count": int(row.get("suggested_candidate_count") or 0),
                "ready_candidate_count": int(row.get("ready_candidate_count") or 0),
                "pending_candidate_count": int(row.get("pending_candidate_count") or 0),
                "suggested_candidates": [str(item) for item in (row.get("suggested_candidates") or []) if str(item).strip()][:8]
                if isinstance(row.get("suggested_candidates"), list)
                else [],
                "shortage": int(row.get("shortage") or 0),
                "status": str(row.get("status") or ""),
                "tone": str(row.get("tone") or "info"),
            }
        )
    return out[:12]


def _manifest_candidate_data_requirements(rows: list[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        out.append(
            {
                "teacher": str(row.get("teacher") or ""),
                "day": str(row.get("day") or ""),
                "required_gender": str(row.get("required_gender") or ""),
                "known_gender": str(row.get("known_gender") or ""),
                "missing_fields": [str(item) for item in (row.get("missing_fields") or []) if str(item).strip()]
                if isinstance(row.get("missing_fields"), list)
                else [],
                "source": str(row.get("source") or ""),
                "action": str(row.get("action") or ""),
            }
        )
    return out[:12]


def _manifest_remediations(options: list[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for option in options:
        if not isinstance(option, dict):
            continue
        out.append(
            {
                "id": str(option.get("id") or ""),
                "title": str(option.get("title") or ""),
                "detail": str(option.get("detail") or ""),
                "risk": str(option.get("risk") or ""),
                "action_type": str(option.get("action_type") or ""),
                "manual_hint": str(option.get("manual_hint") or ""),
                "fields": _manifest_remediation_fields(option.get("fields") if isinstance(option.get("fields"), list) else []),
                "quick_actions": _manifest_quick_actions(
                    option.get("quick_actions") if isinstance(option.get("quick_actions"), list) else []
                ),
                "candidate_suggestions": _manifest_candidate_suggestions(
                    option.get("candidate_suggestions") if isinstance(option.get("candidate_suggestions"), list) else []
                ),
                "decision_points": _manifest_evidence(option.get("decision_points") if isinstance(option.get("decision_points"), list) else []),
                "checklist": [str(item) for item in (option.get("checklist") or []) if str(item).strip()][:8]
                if isinstance(option.get("checklist"), list)
                else [],
            }
        )
    return out[:6]


def _manifest_candidate_suggestions(candidates: list[Any]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for item in candidates:
        if not isinstance(item, dict):
            continue
        out.append(
            {
                "teacher": str(item.get("teacher") or ""),
                "day": str(item.get("day") or ""),
                "required_gender": str(item.get("required_gender") or ""),
                "known_gender": str(item.get("known_gender") or ""),
                "status": str(item.get("status") or ""),
                "confidence": str(item.get("confidence") or ""),
                "reason": str(item.get("reason") or ""),
                "config_hint": str(item.get("config_hint") or ""),
            }
        )
    return out[:12]


def _manifest_quick_actions(actions: list[Any]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for action in actions:
        if not isinstance(action, dict):
            continue
        out.append(
            {
                "id": str(action.get("id") or ""),
                "label": str(action.get("label") or ""),
                "action": str(action.get("action") or ""),
                "view": str(action.get("view") or ""),
                "rule_id": str(action.get("rule_id") or ""),
                "search": str(action.get("search") or ""),
                "focus": str(action.get("focus") or ""),
            }
        )
    return out[:6]


def _manifest_remediation_fields(fields: list[Any]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for field in fields:
        if not isinstance(field, dict):
            continue
        out.append(
            {
                "label": str(field.get("label") or ""),
                "store": str(field.get("store") or ""),
                "path": str(field.get("path") or ""),
                "type": str(field.get("type") or ""),
                "value": str(field.get("value") or ""),
            }
        )
    return out[:12]


def _manifest_artifact(item: dict[str, Any], status: dict[str, Any]) -> dict[str, Any]:
    path = Path(str(item.get("path") or ""))
    source_label = str(item.get("label") or item.get("path") or "")
    display_label = (
        str(item.get("display_label") or "").strip()
        or runtime_audit_display_name(path)
        or _artifact_display_label(source_label, path, status)
    )
    payload = {
        "label": display_label,
        "path": str(item.get("path") or ""),
        "size": int(item.get("size") or 0),
        "modified_at": str(item.get("modified_at") or ""),
    }
    if str(item.get("category") or "").strip():
        payload["category"] = str(item.get("category") or "")
    elif runtime_audit_artifact_key(path):
        payload["category"] = "diagnostic"
    if str(item.get("release_use") or "").strip():
        payload["release_use"] = str(item.get("release_use") or "")
    elif runtime_audit_artifact_key(path):
        payload["release_use"] = RUNTIME_AUDIT_RELEASE_USE
    if str(item.get("download_name") or "").strip():
        payload["download_name"] = str(item.get("download_name") or "")
    elif runtime_audit_display_name(path):
        payload["download_name"] = runtime_audit_display_name(path)
    if display_label != source_label:
        payload["source_label"] = source_label
    if str(item.get("archive_name") or "").strip():
        payload["archive_name"] = str(item.get("archive_name") or "")
    if path.exists() and path.is_file():
        payload["sha256"] = _sha256(path)
    return payload


def _manifest_runtime_audit(artifacts: list[dict[str, Any]], status: dict[str, Any]) -> dict[str, Any]:
    evidence: dict[str, Any] = {
        "schema_version": "scheduler.runtime_audit_evidence.v1",
        "solver_effect": "none",
        "files": {},
    }
    for item in artifacts:
        if not isinstance(item, dict):
            continue
        path = Path(str(item.get("path") or ""))
        key = runtime_audit_artifact_key(path)
        if not key or key in evidence["files"]:
            continue
        evidence["files"][key] = _manifest_artifact(item, status)
    evidence["available"] = bool(evidence["files"].get("rule_execution_plan"))
    evidence["file_count"] = len(evidence["files"])
    return evidence

def _manifest_package_integrity(report: dict[str, Any]) -> dict[str, Any]:
    if not report:
        return {}
    checks = report.get("checks") if isinstance(report.get("checks"), dict) else {}
    issues = report.get("issues") if isinstance(report.get("issues"), list) else []
    return {
        "schema_version": str(report.get("schema_version") or ""),
        "checked_at": str(report.get("checked_at") or ""),
        "status": str(report.get("status") or ""),
        "status_label": str(report.get("status_label") or ""),
        "message": str(report.get("message") or ""),
        "checks": {
            "artifact_count": _optional_int(checks.get("artifact_count")),
            "archive_name_count": _optional_int(checks.get("archive_name_count")),
            "expected_zip_entries": _optional_int(checks.get("expected_zip_entries")),
            "zip_verified": bool(checks.get("zip_verified", False)),
            "zip_entry_count": _optional_int(checks.get("zip_entry_count")),
            "missing_archive_names": _optional_int(checks.get("missing_archive_names")),
            "missing_files": _optional_int(checks.get("missing_files")),
            "duplicate_archive_names": _optional_int(checks.get("duplicate_archive_names")),
            "forbidden_release_names": _optional_int(checks.get("forbidden_release_names")),
            "missing_zip_entries": _optional_int(checks.get("missing_zip_entries")),
            "unexpected_zip_entries": _optional_int(checks.get("unexpected_zip_entries")),
            "duplicate_zip_entries": _optional_int(checks.get("duplicate_zip_entries")),
        },
        "issues": [_manifest_package_integrity_issue(issue) for issue in issues if isinstance(issue, dict)][:12],
    }


def _manifest_package_integrity_issue(issue: dict[str, Any]) -> dict[str, str]:
    return {
        "severity": str(issue.get("severity") or ""),
        "title": str(issue.get("title") or ""),
        "detail": str(issue.get("detail") or ""),
        "suggestion": str(issue.get("suggestion") or ""),
        "examples": str(issue.get("examples") or ""),
    }


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _artifact_display_label(source_label: str, path: Path, status: dict[str, Any]) -> str:
    if not _is_schedule_artifact(source_label, path):
        return source_label
    publish_summary = status.get("publish_assessment") if isinstance(status.get("publish_assessment"), dict) else {}
    publish_summary = publish_summary.get("summary") if isinstance(publish_summary.get("summary"), dict) else {}
    publish_status = str(publish_summary.get("status") or "")
    if str(status.get("run_purpose") or "") == "diagnostic_trial":
        prefix = "候选课表_排障参考"
    elif publish_status == "blocked":
        prefix = "不可发布_复核参考"
    else:
        return source_label
    return f"{prefix}_{_clean_schedule_filename(_filename_from_label(source_label, path))}"


def _filename_from_label(source_label: str, path: Path) -> str:
    normalized = str(source_label or "").replace("\\", "/").strip("/")
    if normalized:
        return normalized.rsplit("/", 1)[-1]
    return path.name


def _clean_schedule_filename(filename: str) -> str:
    text = str(filename or "课表")
    dot_index = text.rfind(".")
    suffix = text[dot_index:] if dot_index > 0 else ""
    stem = text[:dot_index] if dot_index > 0 else text
    stem = (
        stem.replace("最终全局最优解_正式版", "最终全局最优解")
        .replace("_正式版", "")
        .replace("正式版", "")
    )
    stem = re.sub(r"[_\s-]+$", "", stem)
    return f"{stem or '课表'}{suffix}"


def _is_schedule_artifact(source_label: str, path: Path) -> bool:
    source = f"{source_label} {path}".replace("\\", "/").lower()
    filename = _filename_from_label(source_label, path).lower()
    if not filename.endswith((".xlsx", ".xls", ".csv")):
        return False
    if any(token in source for token in ("诊断", "审计", "diagnostic", "audit", "checklist", "penalty", "conflict", "violation")):
        return False
    return (
        "课表" in source
        or any(token in source for token in ("最优解", "全局最优", "正式版"))
        or any(token in filename for token in ("schedule", "timetable", "teacher", "class"))
    )


def _sha256(path: Path) -> str:
    try:
        if path.stat().st_size > MAX_HASH_BYTES:
            return ""
        digest = hashlib.sha256()
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return ""
