# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Any


def apply_release_aware_run_message(status: dict[str, Any]) -> None:
    fields = release_outcome_fields(status)
    status["solver_status"] = fields["solver_status"]
    status["solution_count"] = fields["solution_count"]
    status["schedule_file_count"] = fields["schedule_file_count"]
    message = release_aware_run_message(status, fields=fields)
    if message:
        status["message"] = message
    status["release_state"] = release_state_summary(
        status,
        fields=fields,
        run_message=str(status.get("message") or message or ""),
    )


def release_aware_run_message(status: dict[str, Any], *, fields: dict[str, Any] | None = None) -> str:
    status = status if isinstance(status, dict) else {}
    fields = fields if isinstance(fields, dict) else release_outcome_fields(status)
    fallback = str(status.get("message") or "")
    if str(status.get("status") or "") != "completed":
        return fallback

    solver_status = str(fields.get("solver_status") or "")
    solution_count = fields.get("solution_count")
    schedule_count = int(fields.get("schedule_file_count") or 0)
    publish_status = _normalized_publish_status(str(fields.get("publish_status") or ""))
    run_purpose = str(status.get("run_purpose") or "")

    if solver_status == "INFEASIBLE":
        return "求解器判定当前规则组合不可行，未生成可交付课表文件。"
    if isinstance(solution_count, int) and solution_count <= 0 and schedule_count <= 0:
        return "求解已结束，但未捕获可行解，未生成可交付课表文件。"
    if run_purpose == "diagnostic_trial" and schedule_count > 0:
        return "诊断试跑已生成候选课表，但包含临时放宽规则，不能直接作为交付版本。"
    if publish_status == "blocked" and schedule_count > 0:
        return "求解完成，但发布校验未通过；课表文件仅供排障参考，不能直接交付。"
    if publish_status == "ready" and schedule_count > 0:
        return "求解完成，已发现可交付课表文件。"
    if schedule_count > 0 and "可交付课表文件" in fallback:
        return "求解完成，已发现课表文件；发布状态尚未评估。"
    return fallback


def release_outcome_fields(status: dict[str, Any]) -> dict[str, Any]:
    status = status if isinstance(status, dict) else {}
    assessment = status.get("publish_assessment") if isinstance(status.get("publish_assessment"), dict) else {}
    summary = assessment.get("summary") if isinstance(assessment.get("summary"), dict) else {}
    outcome = assessment.get("outcome") if isinstance(assessment.get("outcome"), dict) else {}
    categories = assessment.get("file_categories") if isinstance(assessment.get("file_categories"), dict) else {}
    return {
        "solver_status": str(outcome.get("solver_status") or status.get("solver_status") or ""),
        "solution_count": outcome.get("solution_count", status.get("solution_count")),
        "schedule_file_count": int(categories.get("schedule") or status.get("schedule_file_count") or 0),
        "publish_status": _normalized_publish_status(str(summary.get("status") or "")),
    }


def release_state_summary(
    status: dict[str, Any],
    *,
    fields: dict[str, Any] | None = None,
    run_message: str = "",
) -> dict[str, Any]:
    status = status if isinstance(status, dict) else {}
    fields = fields if isinstance(fields, dict) else release_outcome_fields(status)
    assessment = status.get("publish_assessment") if isinstance(status.get("publish_assessment"), dict) else {}
    summary = assessment.get("summary") if isinstance(assessment.get("summary"), dict) else {}
    publish_status = _normalized_publish_status(str(summary.get("status") or fields.get("publish_status") or "unknown"))
    run_purpose = str(status.get("run_purpose") or "formal")
    package_kind, package_label = _release_package_kind_and_label(status, publish_status)
    formal_ready = publish_status == "ready"
    return {
        "schema_version": "scheduler.release_state.v2",
        "status": publish_status,
        "status_label": str(summary.get("status_label") or _publish_status_label(publish_status)),
        "run_purpose": run_purpose,
        "solver_status": str(fields.get("solver_status") or ""),
        "solution_count": fields.get("solution_count"),
        "schedule_file_count": int(fields.get("schedule_file_count") or 0),
        "can_publish_candidate": bool(summary.get("can_publish", False)),
        "formal_release_ready": formal_ready,
        "package_kind": package_kind,
        "package_label": package_label,
        "run_message": run_message,
        "next_action": _release_next_action(status, publish_status=publish_status, run_purpose=run_purpose, fields=fields),
    }


def _release_package_kind_and_label(status: dict[str, Any], publish_status: str) -> tuple[str, str]:
    if str(status.get("run_purpose") or "") == "diagnostic_trial" or publish_status == "blocked":
        return "diagnostic", "排障包"
    if publish_status == "ready":
        return "formal", "正式结果包"
    return "result", "结果包"


def _release_next_action(
    status: dict[str, Any],
    *,
    publish_status: str,
    run_purpose: str,
    fields: dict[str, Any],
) -> str:
    solver_status = str(fields.get("solver_status") or "")
    schedule_count = int(fields.get("schedule_file_count") or 0)
    solution_count = fields.get("solution_count")
    if str(status.get("status") or "") != "completed":
        return "等待当前求解任务结束后再判断发布状态。"
    if solver_status == "INFEASIBLE" or (isinstance(solution_count, int) and solution_count <= 0 and schedule_count <= 0):
        return "先修复无解或无可行解问题，重新运行正式求解。"
    if run_purpose == "diagnostic_trial":
        return "这是诊断试跑结果，只能用于排障；确认方案后需重新运行正式求解。"
    if publish_status == "blocked":
        return "先处理发布阻断项，重新生成并校验结果包。"
    if publish_status == "ready":
        return "可下载正式结果包，并按学校现有 OA 或线下流程归档。"
    if schedule_count > 0:
        return "已有课表文件，但发布状态尚未明确；请刷新发布评估。"
    return "查看诊断材料和日志，确认是否需要调整规则后重跑。"


def _publish_status_label(status: str) -> str:
    return {
        "blocked": "不可发布",
        "ready": "可正式交付",
        "unknown": "待评估",
    }.get(status, "待评估")


def _normalized_publish_status(status: str) -> str:
    value = str(status or "").strip()
    return "ready" if value == "review" else value
