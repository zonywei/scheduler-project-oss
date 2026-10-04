# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from scheduler.app.config_service import PROJECT_ROOT
from scheduler.solver_quality import solver_quality_fields


SEVERITY_RANK = {"ok": 0, "info": 1, "warning": 2, "error": 3}
DIAGNOSTIC_TOKENS = ("不可行", "诊断", "审计", "infeasible", "diagnostic", "audit", "conflict")


def build_solve_diagnostics(
    status: dict[str, Any],
    *,
    project_root: Path = PROJECT_ROOT,
) -> dict[str, Any]:
    status = status if isinstance(status, dict) else {}
    files = status.get("files") if isinstance(status.get("files"), list) else []
    issues: list[dict[str, Any]] = []

    business_floor_notes = _build_business_floor_notes(status)
    issues.extend(_issues_from_log(status, project_root=project_root, business_floor_notes=business_floor_notes))
    for file in files:
        if not isinstance(file, dict):
            continue
        issue = _issue_from_file(file, project_root=project_root)
        if issue:
            issues.append(issue)

    issues = _dedupe_issues(issues)
    issues.sort(key=lambda item: (-SEVERITY_RANK.get(str(item.get("severity") or ""), 0), int(item.get("priority") or 99), str(item.get("title") or "")))
    evidence_count = sum(1 for issue in issues if issue.get("source_label"))
    relaxation_plans = _build_relaxation_plans(issues)
    quality_plan = _build_quality_plan(status, issues, business_floor_notes=business_floor_notes, project_root=project_root)
    business_floor_adjusted_quality = _build_business_floor_adjusted_quality(status, business_floor_notes)
    summary = _summary(status, issues, evidence_count)
    return {
        "summary": summary,
        "issues": issues[:10],
        "next_actions": _next_actions(issues),
        "relaxation_plans": relaxation_plans,
        "quality_plan": quality_plan,
        "business_floor_notes": business_floor_notes,
        "business_floor_adjusted_quality": business_floor_adjusted_quality,
    }


def _issues_from_log(
    status: dict[str, Any],
    *,
    project_root: Path,
    business_floor_notes: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    log = str(status.get("log_tail") or "")
    overview = _read_solver_overview(status, project_root=project_root)
    issues: list[dict[str, Any]] = []
    solver_status = _first_present(
        status.get("solver_status"),
        overview.get("solver_status"),
        _first_match(log, r"(?:求解状态：|status\s*=\s*)([A-Z_]+)"),
    )
    solution_count = _first_present(
        status.get("solution_count"),
        overview.get("solution_count"),
        overview.get("solutions_seen"),
        overview.get("total_solutions_seen"),
        overview.get("callback_solution_count"),
        _first_match(log, r"回调捕获解数量：(\d+)"),
        _first_match(log, r"top_count=(\d+)"),
    )
    if str(solver_status or "").strip().upper() == "INFEASIBLE":
        mode = str(status.get("mode") or "").strip().lower()
        suggestion = "优先查看下方不可行提示文件；先从联动、周末、班主任值班等跨域硬约束开始降级排查。"
        if mode == "night":
            suggestion = "夜间模型无解时优先检查晚查寝当天有晚自习、男/女查寝人数、周五周日互斥和个性化禁排；先用晚查寝专项放宽试跑定位。"
        issues.append(
            _issue(
                "error",
                "求解器",
                "求解器判定规则组合不可行",
                "本批次没有可行课表，继续加时通常不会解决，需要先放宽硬约束或处理互斥规则。",
                suggestion,
                priority=1,
            )
        )
    if str(status.get("status") or "") == "completed" and str(solution_count or "0").isdigit() and int(str(solution_count or "0")) == 0:
        issues.append(
            _issue(
                "error",
                "可行解",
                "本批次未捕获可行解",
                "求解正常结束，但没有任何候选课表可供预览或发布。",
                "先处理错误级排障项；如果只剩软约束警告，再延长求解时间并开启快照。",
                priority=2,
            )
        )
    quality_issue = _quality_issue_from_status(
        status,
        overview=overview,
        solver_status=str(solver_status or ""),
        business_floor_notes=business_floor_notes or [],
    )
    if quality_issue:
        issues.append(quality_issue)
    issues.extend(_issues_from_objective_breakdown(status))
    return issues


def _issues_from_objective_breakdown(status: dict[str, Any]) -> list[dict[str, Any]]:
    breakdown = status.get("objective_breakdown") if isinstance(status.get("objective_breakdown"), dict) else {}
    summary = breakdown.get("summary") if isinstance(breakdown.get("summary"), dict) else {}
    top = breakdown.get("top") if isinstance(breakdown.get("top"), list) else []
    total = _float_or_none(summary.get("total_penalty"))
    if not top or total is None or total <= 0:
        return []

    source_label = str(summary.get("source_label") or summary.get("source") or "")
    source_path = str(summary.get("source") or "")
    issues: list[dict[str, Any]] = []
    reconciliation_issue = _objective_reconciliation_issue(summary, source_label=source_label, source_path=source_path)
    if reconciliation_issue:
        issues.append(reconciliation_issue)
    for index, item in enumerate([row for row in top if isinstance(row, dict)][:3], start=1):
        penalty = _float_or_none(item.get("penalty_sum"))
        if penalty is None or penalty <= 0:
            continue
        share = _float_or_none(item.get("share"))
        rule_id = str(item.get("rule_id") or "")
        rule_name = str(item.get("rule_name") or rule_id or "未命名规则")
        offenders = item.get("top_offenders") if isinstance(item.get("top_offenders"), list) else []
        offender_text = _top_offender_text(offenders)
        detail = f"该规则罚分 {_num(penalty)}，占已记录软约束代价 {_num(share)}%。"
        if offender_text:
            detail += f" 主要对象：{offender_text}。"
        issues.append(
            _issue(
                "warning",
                _objective_domain(rule_id, rule_name),
                f"主导软约束代价：{rule_name}",
                detail,
                str(item.get("action") or _objective_suggestion(rule_id, rule_name)),
                source_label=source_label,
                source_path=source_path,
                priority=4 + index,
            )
        )
    return issues


def _objective_reconciliation_issue(
    summary: dict[str, Any],
    *,
    source_label: str,
    source_path: str,
) -> dict[str, Any] | None:
    if str(summary.get("objective_reconciliation_status") or "") != "unmatched":
        return None
    delta = _float_or_none(summary.get("objective_explain_delta"))
    if delta is None or abs(delta) <= 1e-6:
        return None
    return _issue(
        "warning",
        "目标解释",
        "目标值解释未完全对账",
        (
            f"事件日志净值 {_num(summary.get('net_event_penalty'))}，"
            f"求解器目标值 {_num(summary.get('solver_objective_value'))}，"
            f"差额 {_num(delta)}。"
        ),
        "补齐未登记的目标项或在交付说明中保留该差额，避免把正罚分、奖励抵扣和求解目标值混为同一口径。",
        source_label=source_label,
        source_path=source_path,
        priority=5,
    )


def _build_business_floor_notes(status: dict[str, Any]) -> list[dict[str, Any]]:
    notes: list[dict[str, Any]] = []
    checkin_note = _checkin_supply_floor_note(status)
    if checkin_note:
        notes.append(checkin_note)
    return notes


def _checkin_supply_floor_note(status: dict[str, Any]) -> dict[str, Any] | None:
    rule = _objective_top_rule(status, "night_checkin_need_same_day_class")
    penalty = _float_or_none(rule.get("penalty_sum")) if rule else None
    ledger = _checkin_supply_ledger_from_publish_assessment(status)
    shortage_rows = [row for row in ledger if _float_or_none(row.get("shortage")) and float(row.get("shortage") or 0) > 0]
    if penalty is None or penalty <= 0 or not shortage_rows:
        return None

    shortage_count = sum(int(float(row.get("shortage") or 0)) for row in shortage_rows)
    potential_reduction = sum(float(_float_or_none(row.get("potential_penalty_reduction")) or 0.0) for row in shortage_rows)
    days = "、".join(str(row.get("day") or "").strip() for row in shortage_rows if str(row.get("day") or "").strip())
    assigned = sorted(
        {
            str(name).strip()
            for row in shortage_rows
            for name in (row.get("assigned_teachers") if isinstance(row.get("assigned_teachers"), list) else [])
            if str(name).strip()
        }
    )
    pending = sorted(
        {
            str(name).strip()
            for row in shortage_rows
            for name in (row.get("suggested_candidates") if isinstance(row.get("suggested_candidates"), list) else [])
            if str(name).strip()
        }
    )
    return {
        "id": "business_floor.checkin_same_day_supply",
        "domain": "晚查寝",
        "title": "晚查寝同日有晚自习罚分来自确认人力缺口",
        "status": "action_required",
        "penalty_sum": penalty,
        "shortage_count": shortage_count,
        "potential_penalty_reduction": potential_reduction or penalty,
        "days": [str(row.get("day") or "") for row in shortage_rows],
        "assigned_teachers": assigned,
        "pending_candidates": pending[:12],
        "message": (
            f"当前确认可用人力下，{days or '相关日期'} 男寝晚查没有同日晚自习直接候选，"
            f"形成 {_num(penalty)} 罚分；这部分优先按新增/确认候选处理，而不是单纯延长求解。"
        ),
        "next_action": "确认可承担查寝的新教师、宿管或行政值守人员后写入额外候选，再用当前最优 warm-start 复跑。",
        "ledger": shortage_rows,
    }


def _build_business_floor_adjusted_quality(
    status: dict[str, Any],
    business_floor_notes: list[dict[str, Any]],
) -> dict[str, Any]:
    objective = _float_or_none(_first_present(status.get("objective_value"), status.get("best_objective")))
    bound = _float_or_none(status.get("best_bound"))
    quality = solver_quality_fields(objective, bound, solver_status=str(status.get("solver_status") or ""))
    raw_gap = _float_or_none(_first_present(status.get("objective_gap"), quality.get("objective_gap")))
    raw_gap_percent = _float_or_none(_first_present(status.get("gap_percent"), quality.get("gap_percent")))
    proof = _stronger_formal_candidate_proof(status, current_gap=raw_gap)
    basis_objective = _float_or_none(proof.get("candidate_objective_value")) if proof else objective
    basis_gap = _float_or_none(proof.get("candidate_objective_gap")) if proof else raw_gap
    basis_gap_percent = _float_or_none(proof.get("candidate_gap_percent")) if proof else raw_gap_percent
    if basis_gap_percent is None and basis_gap is not None:
        basis_gap_percent = _gap_percent_for_objective(basis_gap, basis_objective)
    basis_bound = _float_or_none(proof.get("proof_best_bound")) if proof else bound
    actionable_notes = [
        note
        for note in business_floor_notes
        if isinstance(note, dict) and str(note.get("status") or "") == "action_required"
    ]
    explained = sum(
        float(
            _float_or_none(_first_present(note.get("potential_penalty_reduction"), note.get("penalty_sum")))
            or 0.0
        )
        for note in actionable_notes
    )
    if basis_gap is None or basis_gap <= 0 or explained <= 0:
        return {
            "schema_version": "scheduler.business_floor_adjusted_quality.v1",
            "status": "none",
            "message": "当前没有可从最优性缺口中单独解释的业务下限项。",
        }

    explained_gap = min(basis_gap, explained)
    adjusted_gap = round(max(0.0, basis_gap - explained_gap), 6)
    adjusted_gap_percent = _gap_percent_for_objective(adjusted_gap, basis_objective)
    result = {
        "schema_version": "scheduler.business_floor_adjusted_quality.v1",
        "status": "action_required",
        "status_label": "先处理业务下限",
        "objective_value": objective,
        "best_bound": bound,
        "raw_objective_gap": raw_gap,
        "raw_gap_percent": raw_gap_percent,
        "gap_basis": "stronger_proof_bound" if proof else "current_run_bound",
        "basis_objective_value": basis_objective,
        "basis_best_bound": basis_bound,
        "basis_objective_gap": basis_gap,
        "basis_gap_percent": basis_gap_percent,
        "business_floor_gap_explained": explained_gap,
        "business_floor_note_ids": [str(note.get("id") or "") for note in actionable_notes if str(note.get("id") or "")],
        "business_floor_note_summaries": [_business_floor_note_summary(note) for note in actionable_notes[:3]],
        "adjusted_objective_gap": adjusted_gap,
        "adjusted_gap_percent": adjusted_gap_percent,
        "message": (
            f"当前可复核缺口 {_num(basis_gap)} 中，至少 {_num(explained_gap)} 可由已识别业务下限解释；"
            f"排除该项后仍需算法证明或继续优化的剩余缺口约 {_num(adjusted_gap)}。"
        ),
        "next_action": "先完成业务人力确认或规则补充，再判断是否需要继续长跑证明最优性。",
    }
    if proof:
        result["stronger_bound_proof"] = {
            "run_id": str(proof.get("proof_run_id") or ""),
            "best_bound": basis_bound,
            "objective_gap": basis_gap,
            "gap_percent": basis_gap_percent,
        }
        result["message"] = (
            "结合同配置的更强证明界，"
            f"当前可复核缺口 {_num(basis_gap)} 中，至少 {_num(explained_gap)} 可由已识别业务下限解释；"
            f"排除该项后仍需算法证明或继续优化的剩余缺口约 {_num(adjusted_gap)}。"
        )
    return result


def _stronger_formal_candidate_proof(status: dict[str, Any], *, current_gap: float | None) -> dict[str, Any]:
    recommended = status.get("recommended_formal_candidate") if isinstance(status.get("recommended_formal_candidate"), dict) else {}
    evidence = recommended.get("quality_evidence") if isinstance(recommended.get("quality_evidence"), dict) else {}
    summary = evidence.get("summary") if isinstance(evidence.get("summary"), dict) else {}
    if str(summary.get("status") or "") != "bound_improved":
        return {}
    proof_run_id = str(summary.get("proof_run_id") or "").strip()
    proof_best_bound = _float_or_none(summary.get("proof_best_bound"))
    candidate_gap = _float_or_none(summary.get("candidate_objective_gap"))
    if not proof_run_id or proof_best_bound is None or candidate_gap is None:
        return {}
    if current_gap is not None and candidate_gap >= current_gap:
        return {}
    evidence_candidate = evidence.get("candidate") if isinstance(evidence.get("candidate"), dict) else {}
    recommended_candidate = recommended.get("candidate") if isinstance(recommended.get("candidate"), dict) else {}
    candidate_objective = _float_or_none(
        _first_present(
            summary.get("candidate_objective_value"),
            recommended_candidate.get("objective_value"),
            evidence_candidate.get("objective_value"),
            status.get("objective_value"),
            status.get("best_objective"),
        )
    )
    return {
        "proof_run_id": proof_run_id,
        "proof_best_bound": proof_best_bound,
        "candidate_objective_value": candidate_objective,
        "candidate_objective_gap": candidate_gap,
        "candidate_gap_percent": _float_or_none(summary.get("candidate_gap_percent")),
    }


def _objective_top_rule(status: dict[str, Any], rule_id: str) -> dict[str, Any] | None:
    breakdown = status.get("objective_breakdown") if isinstance(status.get("objective_breakdown"), dict) else {}
    top = breakdown.get("top") if isinstance(breakdown.get("top"), list) else []
    for row in top:
        if isinstance(row, dict) and str(row.get("rule_id") or "") == rule_id:
            return row
    return None


def _checkin_supply_ledger_from_publish_assessment(status: dict[str, Any]) -> list[dict[str, Any]]:
    assessment = status.get("publish_assessment") if isinstance(status.get("publish_assessment"), dict) else {}
    gates = assessment.get("gates") if isinstance(assessment.get("gates"), list) else []
    for gate in gates:
        if not isinstance(gate, dict):
            continue
        ledger = gate.get("checkin_supply_ledger")
        if isinstance(ledger, list):
            return [row for row in ledger if isinstance(row, dict)]
    return []


def _quality_issue_from_status(
    status: dict[str, Any],
    *,
    overview: dict[str, Any],
    solver_status: str,
    business_floor_notes: list[dict[str, Any]],
) -> dict[str, Any] | None:
    status_name = str(solver_status or "").strip().upper()
    if status_name != "FEASIBLE":
        return None
    objective = _first_present(status.get("objective_value"), overview.get("objective_value"), status.get("best_objective"))
    bound = _first_present(status.get("best_bound"), overview.get("best_bound"))
    quality = solver_quality_fields(objective, bound, solver_status=status_name)
    if quality.get("optimality_status") != "gap_remaining":
        return None
    gap = quality.get("objective_gap")
    gap_percent = quality.get("gap_percent")
    detail_parts = [f"当前目标值 {objective}", f"最优界 {bound}", f"缺口 {gap}"]
    if gap_percent is not None:
        detail_parts.append(f"约 {float(gap_percent):.2f}%")
    detail = "，".join(detail_parts) + "。"
    adjusted = _build_business_floor_adjusted_quality(status, business_floor_notes)
    suggestion = "商业发布前建议延长时限或固定随机种子复跑；若业务必须立即使用，应把该课表标为候选并重点复核高罚分规则。"
    if str(adjusted.get("status") or "") == "action_required":
        proof = adjusted.get("stronger_bound_proof") if isinstance(adjusted.get("stronger_bound_proof"), dict) else {}
        if proof:
            basis_objective = _float_or_none(adjusted.get("basis_objective_value"))
            if basis_objective is not None and objective is not None and abs(basis_objective - float(objective)) > 1e-6:
                detail += f" 推荐正式候选目标值 {_num(basis_objective)}；"
            detail += (
                f" 结合同配置的更强证明界 {_num(proof.get('best_bound'))}，"
                f"当前可复核缺口为 {_num(adjusted.get('basis_objective_gap'))}"
            )
            basis_percent = _float_or_none(adjusted.get("basis_gap_percent"))
            if basis_percent is not None:
                detail += f"（约 {basis_percent:.2f}%）"
            detail += "；"
        else:
            detail += " "
        detail += (
            f"其中 {_num(adjusted.get('business_floor_gap_explained'))} 已由业务下限解释，"
            f"业务调整后剩余缺口约 {_num(adjusted.get('adjusted_objective_gap'))}"
        )
        adjusted_percent = _float_or_none(adjusted.get("adjusted_gap_percent"))
        if adjusted_percent is not None:
            detail += f"（约 {adjusted_percent:.2f}%）"
        detail += "；这不是求解器可单独消除的纯算法缺口。"
        suggestion = (
            "先处理业务下限项，例如补充/确认可用人力或调整规则口径；"
            "再用当前最优 warm-start 复跑，并复核剩余最优性缺口。"
        )
    return _issue(
        "warning",
        "求解质量",
        "可行解尚未证明全局最优",
        detail,
        suggestion,
        priority=4,
    )


def _gap_percent_for_objective(gap: float, objective: float | None) -> float | None:
    if objective is None or objective == 0:
        return None
    return round(abs(float(gap) / float(objective)) * 100.0, 6)


def _read_solver_overview(status: dict[str, Any], *, project_root: Path) -> dict[str, Any]:
    files = status.get("files") if isinstance(status.get("files"), list) else []
    candidates: list[Path] = []
    for file in files:
        if not isinstance(file, dict):
            continue
        label = str(file.get("label") or file.get("path") or "").replace("\\", "/")
        if not label.endswith("final_solver_overview.json"):
            continue
        path = Path(str(file.get("path") or ""))
        if _is_safe_file(path, project_root):
            candidates.append(path)
    if not candidates:
        return {}
    latest = max(candidates, key=lambda path: path.stat().st_mtime)
    try:
        data = json.loads(latest.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _first_present(*values: Any) -> Any:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        return value
    return None


def _float_or_none(value: Any) -> float | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _positive_int(value: Any, *, default: int) -> int:
    try:
        parsed = int(float(value))
    except (TypeError, ValueError):
        return int(default)
    return parsed if parsed > 0 else int(default)


def _non_negative_int(value: Any) -> int | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        parsed = int(float(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _num(value: Any) -> str:
    number = _float_or_none(value)
    if number is None:
        return "未记录"
    if number.is_integer():
        return str(int(number))
    return f"{number:.2f}".rstrip("0").rstrip(".")


def _top_offender_text(rows: list[Any]) -> str:
    out: list[str] = []
    for row in rows[:3]:
        if not isinstance(row, dict):
            continue
        entity = _offender_entity_label(row.get("entity"))
        penalty = _num(row.get("penalty_sum"))
        if entity:
            out.append(f"{entity}({_text_limit(penalty, 16)})")
    return "、".join(out)


def _offender_entity_label(value: Any) -> str:
    text = str(value or "").strip()
    if not text or text.upper() == "GLOBAL":
        return "全局规则"
    return text


def _objective_domain(rule_id: str, rule_name: str) -> str:
    text = f"{rule_id} {rule_name}".lower()
    if "checkin" in text or "查寝" in text or "晚查" in text:
        return "晚查寝"
    if "lang" in text or "语文" in text or "外语" in text:
        return "学科时段偏好"
    if "day_night" in text or "联动" in text:
        return "联动规则"
    if "continu" in text or "gap" in text or "halfday" in text or "半天" in text or "连续" in text:
        return "教师负荷"
    if "night" in text or "晚自习" in text:
        return "晚自习"
    return "软约束代价"


def _objective_suggestion(rule_id: str, rule_name: str) -> str:
    text = f"{rule_id} {rule_name}".lower()
    if "lang" in text or "语文" in text or "外语" in text:
        return "建议做一次诊断调参：降低语文/外语周二到周五下午罚分权重，观察总目标值、教师负荷和班级时段分布是否更稳定。"
    if "checkin" in text or "查寝" in text or "晚查" in text:
        return "建议优先补充同日有晚自习的查寝候选；若只是可接受例外，把同日任课权重降回诊断级别后短时复跑。"
    return "建议用短时诊断试跑验证该软约束权重是否过强，再决定调权、补候选或走学校既有流程记录例外。"


def _text_limit(value: Any, limit: int) -> str:
    text = str(value or "")
    return text[:limit] + ("..." if len(text) > limit else "")


def _issue_from_file(file: dict[str, Any], *, project_root: Path) -> dict[str, Any] | None:
    label = str(file.get("label") or file.get("path") or "")
    normalized = label.replace("\\", "/")
    lower = normalized.lower()
    if not any(token in lower for token in DIAGNOSTIC_TOKENS):
        return None
    path = Path(str(file.get("path") or ""))
    if not _is_safe_file(path, project_root):
        return None
    text = _read_text(path)
    if not text.strip():
        return None
    name = Path(normalized).name
    domain = _domain_from_name(name)
    title = _title_from_name(name)
    bullets = _extract_bullets(text)
    total_hits = _first_match(text, r"TotalHits=(\d+)")

    if "不可行" in name or "infeasible" in lower:
        detail = "；".join(bullets[:4]) if bullets else _compact_text(text)
        return _issue(
            "error",
            domain,
            title,
            detail or "诊断文件提示该模块存在不可行风险。",
            _suggestion_for(domain, title, text, hard=True),
            source_label=label,
            source_path=str(path),
            priority=_priority_for(domain, title),
        )
    if "PossibleConflicts=" in text or "PossibleConflicts" in text:
        detail = "；".join(bullets[:4]) if bullets else _compact_text(text)
        return _issue(
            "warning",
            domain,
            title,
            detail or "诊断文件列出了可能冲突来源。",
            _suggestion_for(domain, title, text),
            source_label=label,
            source_path=str(path),
            priority=5,
        )
    if total_hits and int(total_hits) > 0:
        return _issue(
            "warning",
            domain,
            title,
            f"该规则命中 {total_hits} 个班级-学科组合，可能显著压缩排课空间。",
            _suggestion_for(domain, title, text),
            source_label=label,
            source_path=str(path),
            priority=6,
        )
    if "审计" in name or "audit" in lower:
        return _issue(
            "info",
            domain,
            title,
            _compact_text(text),
            "作为复核材料保留；若错误级排障项处理完仍不可行，再逐项查看审计细节。",
            source_label=label,
            source_path=str(path),
            priority=8,
        )
    return None


def _is_safe_file(path: Path, project_root: Path) -> bool:
    if not path.exists() or not path.is_file():
        return False
    try:
        target = path.resolve()
        root = project_root.resolve()
        return target == root or root in target.parents
    except OSError:
        return False


def _read_text(path: Path) -> str:
    for encoding in ("utf-8", "utf-8-sig", "gb18030"):
        try:
            return path.read_text(encoding=encoding, errors="ignore")
        except Exception:
            continue
    return ""


def _extract_bullets(text: str) -> list[str]:
    bullets: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith(("-", "•", "*")):
            bullets.append(line.lstrip("-•* ").strip())
        elif re.match(r"^\d+[.)、]\s*", line):
            bullets.append(re.sub(r"^\d+[.)、]\s*", "", line).strip())
    return [item for item in bullets if item]


def _compact_text(text: str, limit: int = 120) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip() and not line.strip().startswith("[")]
    compact = "；".join(lines[:4])
    return compact[:limit] + ("..." if len(compact) > limit else "")


def _domain_from_name(name: str) -> str:
    if "联合" in name or "联动" in name:
        return "联动规则"
    if "班主任" in name or "值班" in name or "查寝" in name:
        return "值班规则"
    if "周末" in name:
        return "周末规则"
    if "白天" in name or "九学科" in name or "周中" in name:
        return "白天排课"
    if "晚自习" in name:
        return "晚自习"
    if "热启动" in name:
        return "热启动"
    return "诊断材料"


def _title_from_name(name: str) -> str:
    stem = Path(name).stem
    stem = re.sub(r"_\d+$", "", stem)
    return stem.replace("_", " ")


def _suggestion_for(domain: str, title: str, text: str, *, hard: bool = False) -> str:
    combined = f"{domain} {title} {text}"
    if "周日" in combined or "晚自习" in combined or "联动" in combined:
        return "先临时降级白天-晚自习联动硬约束，重点核查周日晚自习、周一上午和白天无课不得晚自习的组合。"
    if "班主任" in combined or "每楼层" in combined or "pm1" in combined.lower():
        return "检查班主任值班人数、楼层需求和 PM1 关联要求；必要时先把 duty<=pm1 或每日楼层人数改为软约束。"
    if "周末" in combined or "白名单" in combined:
        return "核查周末学科白名单、同一教师是否必须只上其中一天，以及周末连堂/半天规则是否叠加过强。"
    if "九学科" in combined or "日负载" in combined or "上午1" in combined:
        return "检查教师每日上限、上午1/上午4互斥和固定课位；先解除固定课位再验证是否可行。"
    if "周中少课" in combined or "TotalHits" in combined:
        return "该规则命中面广，建议确认低课时阈值是否合理，必要时把每日最多一次从硬约束改为软约束。"
    if hard:
        return "先在规则总览中按该模块关闭或降级硬约束，再重新运行短时求解验证。"
    return "把该诊断作为第二优先级复核项；若错误级项处理后仍不可行，再逐条放宽。"


def _priority_for(domain: str, title: str) -> int:
    combined = f"{domain} {title}"
    if "联动" in combined or "联合" in combined:
        return 3
    if "白天 不可行" in combined:
        return 4
    if "值班" in combined or "班主任" in combined:
        return 5
    if "九学科" in combined or "日负载" in combined:
        return 6
    if "周末" in combined:
        return 7
    return 8


def _dedupe_issues(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, str]] = set()
    out: list[dict[str, Any]] = []
    for issue in issues:
        key = (str(issue.get("severity") or ""), str(issue.get("domain") or ""), str(issue.get("title") or ""))
        if key in seen:
            continue
        seen.add(key)
        out.append(issue)
    return out


def _summary(status: dict[str, Any], issues: list[dict[str, Any]], evidence_count: int) -> dict[str, Any]:
    errors = sum(1 for issue in issues if issue.get("severity") == "error")
    warnings = sum(1 for issue in issues if issue.get("severity") == "warning")
    infos = sum(1 for issue in issues if issue.get("severity") == "info")
    if errors:
        state = "blocked"
        label = "需要排障"
        message = f"已识别 {errors} 个错误级排障项，先处理这些硬约束或无解证据。"
    elif warnings:
        state = "review"
        label = "需要复核"
        message = f"未发现错误级排障项，但有 {warnings} 个可能压缩可行域的诊断。"
    elif str(status.get("status") or "") == "idle":
        state = "empty"
        label = "暂无诊断"
        message = "还没有求解批次，暂无排障建议。"
    else:
        state = "ok"
        label = "未见阻断"
        message = "当前日志和诊断文件没有识别到明确排障项。"
    return {
        "status": state,
        "status_label": label,
        "message": message,
        "errors": errors,
        "warnings": warnings,
        "infos": infos,
        "issue_count": len(issues),
        "evidence_files": evidence_count,
    }


def _next_actions(issues: list[dict[str, Any]]) -> list[dict[str, str]]:
    actions: list[dict[str, str]] = []
    for issue in issues:
        if issue.get("severity") not in {"error", "warning"}:
            continue
        actions.append(
            {
                "title": str(issue.get("title") or ""),
                "domain": str(issue.get("domain") or ""),
                "severity": str(issue.get("severity") or ""),
                "suggestion": str(issue.get("suggestion") or ""),
                "source_label": str(issue.get("source_label") or ""),
            }
        )
        if len(actions) >= 5:
            break
    return actions


def _build_relaxation_plans(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates: dict[str, dict[str, Any]] = {}
    for issue in issues:
        text = " ".join(str(issue.get(key) or "") for key in ("domain", "title", "detail", "suggestion"))
        for plan in _plans_for_text(text, issue):
            existing = candidates.get(plan["id"])
            if existing is None:
                candidates[plan["id"]] = plan
            else:
                existing["evidence"].extend(item for item in plan["evidence"] if item not in existing["evidence"])
    plans = list(candidates.values())
    plans.sort(key=lambda item: (int(item.get("priority") or 99), str(item.get("title") or "")))
    return plans[:8]


def _build_quality_plan(
    status: dict[str, Any],
    issues: list[dict[str, Any]],
    *,
    business_floor_notes: list[dict[str, Any]] | None = None,
    project_root: Path = PROJECT_ROOT,
) -> dict[str, Any]:
    quality_issue = next(
        (
            issue
            for issue in issues
            if str(issue.get("domain") or "") == "求解质量"
            and str(issue.get("title") or "") == "可行解尚未证明全局最优"
        ),
        None,
    )
    if quality_issue is None:
        return {
            "schema_version": "scheduler.solve_quality_plan.v1",
            "status": "none",
            "status_label": "无需复跑计划",
            "message": "当前求解状态没有识别到最优性缺口复跑需求。",
            "steps": [],
        }

    base_time = _positive_int(status.get("time_limit_seconds"), default=300)
    retry_time = max(base_time * 2, 600)
    workers = _positive_int(status.get("workers"), default=8)
    max_keep = max(1, min(_positive_int(status.get("max_keep"), default=3), 3))
    seed = _non_negative_int(status.get("random_seed"))
    attempt_history = _quality_attempt_history(status, project_root=project_root)
    used_improve_seeds = _used_seeds_for_profile(attempt_history, "improve_incumbent")
    used_prove_seeds = _used_seeds_for_profile(attempt_history, "prove_bound")
    objective = _float_or_none(_first_present(status.get("objective_value"), status.get("best_objective")))
    bound = _float_or_none(status.get("best_bound"))
    quality = solver_quality_fields(objective, bound, solver_status=str(status.get("solver_status") or "FEASIBLE"))
    current_gap = _float_or_none(_first_present(status.get("objective_gap"), quality.get("objective_gap")))
    current_gap_percent = _float_or_none(_first_present(status.get("gap_percent"), quality.get("gap_percent")))
    adjusted_quality = _build_business_floor_adjusted_quality(status, business_floor_notes or [])

    improve_payload: dict[str, Any] = {
        "mode": str(status.get("mode") or "joint"),
        "time_limit_seconds": retry_time,
        "workers": workers,
        "max_keep": max_keep,
        "continue_from_best": True,
        "solver_profile": "improve_incumbent",
    }
    if seed is not None:
        improve_payload["random_seed"] = _next_unused_seed(seed + 1, used_improve_seeds)

    prove_payload: dict[str, Any] = {
        "mode": str(status.get("mode") or "joint"),
        "time_limit_seconds": retry_time,
        "workers": workers,
        "max_keep": max_keep,
        "solver_profile": "prove_bound",
        "log_search_progress": True,
    }
    if seed is not None:
        prove_seed = _next_unused_seed(seed, used_prove_seeds)
        prove_payload["random_seed"] = prove_seed

    strict_payload: dict[str, Any] = {
        "mode": str(status.get("mode") or "joint"),
        "time_limit_seconds": max(retry_time * 2, 1200),
        "workers": workers,
        "max_keep": max_keep,
        "solver_profile": "prove_bound",
        "relative_gap_limit": 0.05,
        "log_search_progress": True,
    }
    if seed is not None:
        strict_payload["random_seed"] = _next_unused_seed(int(prove_payload.get("random_seed", seed)) + 1, used_prove_seeds)

    current = {
        "run_id": str(status.get("run_id") or ""),
        "solver_status": str(status.get("solver_status") or ""),
        "objective_value": objective,
        "best_bound": bound,
        "objective_gap": current_gap,
        "gap_percent": current_gap_percent,
        "solver_profile": str(status.get("solver_profile") or ""),
        "time_limit_seconds": base_time,
    }
    if str(adjusted_quality.get("status") or "") == "action_required":
        current["business_floor_adjusted_quality"] = adjusted_quality
    if attempt_history:
        current["attempt_history"] = attempt_history[:8]
        current["attempt_count"] = len(attempt_history)

    message = (
        "当前可行解仍有最优性缺口；建议先改善 incumbent，再单独收紧下界证明，"
        "必要时追加严格 gap 目标长跑。"
    )
    if str(adjusted_quality.get("status") or "") == "action_required":
        message = (
            "当前缺口中含业务人力或规则口径造成的业务下限；先完成这些业务确认，"
            "再按 incumbent 改善、下界证明和严格 gap 目标的顺序复跑。"
        )
    steps: list[dict[str, Any]] = []
    if str(adjusted_quality.get("status") or "") == "action_required":
        steps.append(_business_floor_resolution_step(adjusted_quality))
    steps.extend(
        [
            {
                "id": "quality.improve_incumbent",
                "title": "从当前最优继续改善目标值",
                "purpose": "优先寻找更低目标值的候选课表，降低正式候选的软约束总成本。",
                "expected_effect": "可能降低 objective_value；不保证显著改善 best_bound。",
                "start_solve_payload": improve_payload,
            },
            {
                "id": "quality.prove_bound",
                "title": "单独加强最优界证明",
                "purpose": "用证明型 profile 收紧 best_bound，判断当前缺口是否主要来自下界证明不足。",
                "expected_effect": "可能降低 objective_gap/gap_percent；不一定找到更低目标值。",
                "start_solve_payload": prove_payload,
            },
            {
                "id": "quality.strict_gap_5pct",
                "title": "严格 5% gap 目标长跑",
                "purpose": "商业发布前若仍需更强证明，启动更长时限并设置 5% 相对 gap 目标。",
                "expected_effect": "达到目标会自动停止；若仍未达到，保留结果包并走学校既有流程记录质量缺口。",
                "start_solve_payload": strict_payload,
            },
        ]
    )

    return {
        "schema_version": "scheduler.solve_quality_plan.v1",
        "status": "recommended",
        "status_label": "先处理业务下限" if steps and steps[0].get("id") == "quality.resolve_business_floor" else "建议复跑",
        "message": message,
        "current": current,
        "steps": steps,
    }


def _quality_attempt_history(status: dict[str, Any], *, project_root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    target_config_hash = _status_config_hash(status)

    def add(source: str, payload: dict[str, Any] | None) -> None:
        if not isinstance(payload, dict):
            return
        expanded = _read_quality_attempt_status(payload, project_root=project_root) or payload
        row = _quality_attempt_row(source, expanded)
        if row is None:
            return
        key = str(row.get("run_id") or f"{row.get('solver_profile')}|{row.get('random_seed')}|{row.get('completed_at')}")
        if key in seen:
            return
        seen.add(key)
        rows.append(row)

    add("current", status)
    recommended = status.get("recommended_formal_candidate") if isinstance(status.get("recommended_formal_candidate"), dict) else {}
    add("recommended", recommended.get("candidate") if isinstance(recommended, dict) else None)
    for item in recommended.get("alternatives") if isinstance(recommended.get("alternatives"), list) else []:
        add("alternative", item)
    for item in _same_config_status_history(project_root=project_root, target_config_hash=target_config_hash):
        add("same_config_history", item)

    rows.sort(key=lambda row: str(row.get("completed_at") or row.get("run_id") or ""), reverse=True)
    return rows


def _same_config_status_history(*, project_root: Path, target_config_hash: str) -> list[dict[str, Any]]:
    if not target_config_hash:
        return []
    root = project_root / "outputs" / "web_runs"
    if not root.exists():
        return []
    rows: list[dict[str, Any]] = []
    for status_file in sorted(root.glob("run_*/status.json")):
        try:
            loaded = json.loads(status_file.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(loaded, dict):
            continue
        if _status_config_hash(loaded) != target_config_hash:
            continue
        rows.append(loaded)
    return rows


def _read_quality_attempt_status(entry: dict[str, Any], *, project_root: Path) -> dict[str, Any] | None:
    raw_path = str(entry.get("status_file") or "").strip()
    if not raw_path:
        return None
    try:
        path = Path(raw_path)
        if not path.is_absolute():
            path = project_root / path
        resolved = path.resolve()
        root = project_root.resolve()
        if not resolved.is_relative_to(root):
            return None
        if not resolved.exists():
            return None
        loaded = json.loads(resolved.read_text(encoding="utf-8"))
        return loaded if isinstance(loaded, dict) else None
    except Exception:
        return None


def _status_config_hash(payload: dict[str, Any]) -> str:
    if not isinstance(payload, dict):
        return ""
    for key in ("config_fingerprint", "current_config_fingerprint"):
        value = payload.get(key)
        if isinstance(value, dict):
            text = str(value.get("hash") or "").strip()
            if text:
                return text
    for key in ("config_hash", "effective_config_hash"):
        text = str(payload.get(key) or "").strip()
        if text:
            return text
    recommended = payload.get("recommended_formal_candidate")
    if isinstance(recommended, dict):
        text = str(recommended.get("config_hash") or "").strip()
        if text:
            return text
    return ""


def _quality_attempt_row(source: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    profile = str(payload.get("solver_profile") or "").strip()
    seed = _non_negative_int(payload.get("random_seed"))
    if not profile and seed is None:
        return None
    return {
        "source": source,
        "run_id": str(payload.get("run_id") or ""),
        "solver_profile": profile,
        "random_seed": seed,
        "objective_value": _float_or_none(_first_present(payload.get("objective_value"), payload.get("best_objective"))),
        "best_bound": _float_or_none(payload.get("best_bound")),
        "objective_gap": _float_or_none(payload.get("objective_gap")),
        "gap_percent": _float_or_none(payload.get("gap_percent")),
        "completed_at": str(payload.get("completed_at") or ""),
    }


def _used_seeds_for_profile(attempts: list[dict[str, Any]], profile: str) -> set[int]:
    return {
        int(seed)
        for row in attempts
        if str(row.get("solver_profile") or "") == profile
        for seed in [_non_negative_int(row.get("random_seed"))]
        if seed is not None
    }


def _next_unused_seed(start: int, used: set[int]) -> int:
    seed = max(0, int(start))
    while seed in used:
        seed += 1
    return seed


def _business_floor_resolution_step(adjusted_quality: dict[str, Any]) -> dict[str, Any]:
    note_summaries = (
        adjusted_quality.get("business_floor_note_summaries")
        if isinstance(adjusted_quality.get("business_floor_note_summaries"), list)
        else []
    )
    return {
        "id": "quality.resolve_business_floor",
        "title": "先处理业务下限",
        "purpose": (
            "当前最优性缺口中已有一部分来自业务人力供给或规则口径下限；"
            "继续求解前先把这些事项补充或确认。"
        ),
        "expected_effect": (
            f"先把业务下限解释的 {_num(adjusted_quality.get('business_floor_gap_explained'))} 分从纯算法缺口中拆出；"
            f"处理后再复核剩余缺口 {_num(adjusted_quality.get('adjusted_objective_gap'))}。"
        ),
        "manual_action": {
            "action": "resolve_business_floor",
            "status": str(adjusted_quality.get("status") or "action_required"),
            "business_floor_gap_explained": adjusted_quality.get("business_floor_gap_explained"),
            "adjusted_objective_gap": adjusted_quality.get("adjusted_objective_gap"),
            "adjusted_gap_percent": adjusted_quality.get("adjusted_gap_percent"),
            "business_floor_note_ids": adjusted_quality.get("business_floor_note_ids") or [],
            "business_floor_note_summaries": note_summaries,
            "next_action": adjusted_quality.get("next_action"),
        },
    }


def _business_floor_note_summary(note: dict[str, Any]) -> dict[str, Any]:
    ledger = note.get("ledger") if isinstance(note.get("ledger"), list) else []
    return {
        "id": str(note.get("id") or ""),
        "domain": str(note.get("domain") or ""),
        "title": str(note.get("title") or ""),
        "status": str(note.get("status") or ""),
        "penalty_sum": _float_or_none(note.get("penalty_sum")),
        "shortage_count": _positive_int(note.get("shortage_count"), default=0),
        "potential_penalty_reduction": _float_or_none(note.get("potential_penalty_reduction")),
        "days": [str(item) for item in note.get("days", []) if str(item).strip()][:14]
        if isinstance(note.get("days"), list)
        else [],
        "assigned_teachers": [str(item) for item in note.get("assigned_teachers", []) if str(item).strip()][:20]
        if isinstance(note.get("assigned_teachers"), list)
        else [],
        "pending_candidates": [str(item) for item in note.get("pending_candidates", []) if str(item).strip()][:20]
        if isinstance(note.get("pending_candidates"), list)
        else [],
        "ledger": [_business_floor_ledger_summary(item) for item in ledger[:8] if isinstance(item, dict)],
        "next_action": str(note.get("next_action") or ""),
    }


def _business_floor_ledger_summary(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "day": str(row.get("day") or ""),
        "gender": str(row.get("gender") or ""),
        "duty": str(row.get("duty") or ""),
        "shortage": _positive_int(row.get("shortage"), default=0),
        "potential_penalty_reduction": _float_or_none(row.get("potential_penalty_reduction")),
        "assigned_teachers": [str(item) for item in row.get("assigned_teachers", []) if str(item).strip()][:10]
        if isinstance(row.get("assigned_teachers"), list)
        else [],
        "suggested_candidates": [str(item) for item in row.get("suggested_candidates", []) if str(item).strip()][:10]
        if isinstance(row.get("suggested_candidates"), list)
        else [],
        "status": str(row.get("status") or ""),
    }


def _plans_for_text(text: str, issue: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    evidence = [str(issue.get("title") or "").strip()]
    source = str(issue.get("source_label") or "").strip()
    if source:
        evidence.append(source)
    if any(token in text for token in ("联动", "周日晚自习", "白天无课不得安排晚自习", "周一上午")):
        out.append(
            _plan(
                "relax.day_night_link",
                "先放宽白天-晚自习联动",
                "联动规则",
                "将周日晚自习到周一上午、白天无课不得晚自习这类跨域硬约束降为软约束，验证是否由联动规则造成无解。",
                "可能允许个别教师晚自习前后白天课位不理想，试跑后必须查看教师负荷和连班情况。",
                [
                    _patch("io", ["day_night_link", "night_requires_day_mode"], "soft"),
                    _patch("io", ["day_night_link", "sun_night_no_mon_am1_mode"], "soft"),
                    _patch("io", ["day_night_link", "sun_pm_night_no_mon_am_mode"], "soft"),
                ],
                evidence,
                priority=1,
            )
        )
    if any(token in text for token in ("班主任", "PM1", "pm1", "每楼层", "duty")):
        out.append(
            _plan(
                "relax.head_duty_pm1",
                "放宽班主任 PM1 与值班绑定",
                "值班规则",
                "将“有下午1课必须当天值班”等值班联动先降为软约束，排查 PM1 下限、楼层值班和班主任课位是否互相卡死。",
                "可能出现少量 PM1 班主任当天未值班，需要发布前由教务人工确认或补调值班。",
                [
                    _patch("io", ["day", "head_duty_constraints", "weekday_pm1_requires_duty_mode"], "soft"),
                    _patch("io", ["day", "duty_joint_constraints", "pm_pre_class_no_consecutive_mode"], "soft"),
                ],
                evidence,
                priority=2,
            )
        )
    if any(token in text for token in ("晚查", "查寝", "checkin")):
        out.append(
            _plan(
                "relax.checkin_same_day_class",
                "放宽晚查寝当天有晚自习要求",
                "晚查寝",
                "保留每天男女查寝人数和周次数上限，把“查寝教师当天必须有晚自习课”临时降为软约束，验证无解是否由同日有课硬链路造成。",
                "可能出现个别查寝教师当天没有晚自习课；诊断表会记录罚分，正式采用前需要教务确认教师是否可接受专门返校或改由宿管值守。",
                [
                    _patch("rules", ["checkin", "require_teacher_has_class_that_day_mode"], "soft"),
                    _patch("rules", ["checkin", "w_require_teacher_has_class_that_day"], 3000),
                ],
                evidence,
                priority=2,
            )
        )
        out.append(
            _plan(
                "relax.checkin_only",
                "仅关闭晚查寝分配",
                "晚查寝",
                "只临时关闭晚查寝分配，验证无解是否由查寝候选、性别人数、当日有课和晚间课位共同造成。",
                "该方案不会安排晚查寝人员，只能用于定位晚自习模型是否被查寝模块卡死，不能作为可发布排课结果。",
                [
                    _patch("rules", ["checkin", "enabled"], False),
                ],
                evidence,
                priority=3,
            )
        )
    if any(token in text for token in ("班主任值班", "晚查", "查寝", "值班规则", "checkin")):
        out.append(
            _plan(
                "relax.head_duty_checkin_chain",
                "关闭班主任值班与晚查寝链路",
                "值班规则",
                "临时关闭下午课前班主任楼层值班和晚查寝分配，验证是否由值班名额、楼层需求和查寝链路共同造成无解。",
                "该方案会跳过真实值班与查寝安排，只能用于定位无解来源，不能作为可发布排课结果。",
                [
                    _patch("io", ["day", "head_duty_constraints", "enable_head_duty"], False),
                    _patch("rules", ["checkin", "enabled"], False),
                ],
                evidence,
                priority=4,
            )
        )
    if any(token in text for token in ("语文外语", "语文", "外语", "lang_tue_fri", "下午2", "下午3")):
        out.append(
            _plan(
                "tune.lang_tue_fri_pm_penalty",
                "降低语文/外语下午偏好罚分做诊断试跑",
                "学科时段偏好",
                "将语文/外语周二到周五下午1/2/3的软惩罚临时降到诊断级别，验证当前高目标值是否主要来自时段偏好权重过强，而不是硬性课位冲突。",
                "可能允许更多语文/外语出现在下午；该方案只用于权重敏感性分析，正式发布前仍需查看学科时段分布和班级日课表。",
                [
                    _patch("io", ["day", "weekday_constraints", "w_lang_tue_fri_pm1_penalty"], 2500),
                    _patch("io", ["day", "weekday_constraints", "w_lang_tue_fri_pm2_penalty"], 1500),
                    _patch("io", ["day", "weekday_constraints", "w_lang_tue_fri_pm3_penalty"], 1000),
                ],
                evidence,
                priority=3,
            )
        )
    if any(token in text for token in ("白天 不可行", "8班化学", "9班生物", "上午1与上午4", "固定课位")):
        out.append(
            _plan(
                "relax.day_core_conflicts",
                "放宽白天核心硬约束组合",
                "白天排课",
                "先关闭跨班绑定和 AM1/AM4 同日互斥，用短时求解判断白天主课约束是否是无解主因。",
                "可能破坏原先希望的跨班同步或教师作息偏好，只适合排障试跑，不建议直接发布。",
                [
                    _patch("io", ["day", "weekday_constraints", "enable_binding_chem_bio"], False),
                    _patch("io", ["day", "weekday_constraints", "enable_no_am1_am4"], False),
                    _patch("io", ["day", "weekday_constraints", "enable_head_pm1_min"], False),
                ],
                evidence,
                priority=3,
            )
        )
    if any(token in text for token in ("九学科", "日负载", "每天最多3节", "教师每日上限")):
        out.append(
            _plan(
                "relax.core_teacher_day_load",
                "放宽九学科教师日负载上限",
                "白天排课",
                "临时关闭九大学科教师每日最多3节与同日上午1/上午4联动，验证是否是固定课位叠加导致无解。",
                "可能出现个别核心教师单日课量偏重，需要后续通过权重和人工调课再压回。",
                [
                    _patch("io", ["day", "weekday_constraints", "enable_core_teacher_day_load_limit"], False),
                    _patch("io", ["day", "weekday_constraints", "core_teacher_day_load_max"], 4),
                ],
                evidence,
                priority=4,
            )
        )
    if any(token in text for token in ("周末", "白名单", "跨两天", "半天")):
        out.append(
            _plan(
                "relax.weekend_rules",
                "放宽周末白名单与跨天规则",
                "周末规则",
                "临时关闭周末学科白名单和同一教师不得跨两天，排查周末课位空间是否过窄。",
                "可能让周末课程分布不符合原始偏好，试跑后需重点抽查周末班级课表。",
                [
                    _patch("io", ["day", "weekend_constraints", "enable_weekend_subject_whitelist"], False),
                    _patch("io", ["day", "weekend_constraints", "enable_weekend_one_day_only"], False),
                    _patch("rules", ["day_constraints", "weekend_halfday_mode"], "soft"),
                ],
                evidence,
                priority=5,
            )
        )
    if any(token in text for token in ("周中少课", "TotalHits", "每天最多一次", "低课时")):
        out.append(
            _plan(
                "relax.low_hour_subject_daily_cap",
                "放宽低课时学科每日最多一次",
                "白天排课",
                "关闭低课时学科每日最多一次限制，验证体育、技术、化生政地等低课时学科是否占用了过多可行域。",
                "可能让低课时学科同一天集中出现，试跑后需检查班级日课表均衡性。",
                [
                    _patch("io", ["day", "weekday_constraints", "enable_low_weekday_subject_max1_per_day"], False),
                ],
                evidence,
                priority=6,
            )
        )
    return out


def _plan(
    plan_id: str,
    title: str,
    domain: str,
    rationale: str,
    risk: str,
    patches: list[dict[str, Any]],
    evidence: list[str],
    *,
    priority: int,
) -> dict[str, Any]:
    return {
        "id": plan_id,
        "title": title,
        "domain": domain,
        "rationale": rationale,
        "risk": risk,
        "priority": priority,
        "patches": patches,
        "patch_count": len(patches),
        "evidence": [item for item in evidence if item],
    }


def _patch(target: str, path: list[str], value: Any) -> dict[str, Any]:
    return {
        "target": target,
        "operation": "set",
        "path": path,
        "value": value,
        "path_label": ".".join(path),
    }


def _issue(
    severity: str,
    domain: str,
    title: str,
    detail: str,
    suggestion: str,
    *,
    source_label: str = "",
    source_path: str = "",
    priority: int = 9,
) -> dict[str, Any]:
    return {
        "severity": severity,
        "domain": domain,
        "title": title,
        "detail": detail,
        "suggestion": suggestion,
        "source_label": source_label,
        "source_path": source_path,
        "priority": priority,
    }


def _first_match(text: str, pattern: str) -> str | None:
    match = re.search(pattern, text, flags=re.IGNORECASE)
    return match.group(1).strip() if match else None
