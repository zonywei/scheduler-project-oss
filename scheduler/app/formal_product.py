# -*- coding: utf-8 -*-
"""Formal product workflow, Rule V2 persistence, and publish records."""
from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

from scheduler.app.config_service import load_web_overrides, save_web_overrides
from scheduler.app.model_gateway import (
    JsonModelClient,
    pseudonymize_teacher_context,
    replace_model_tokens,
)
from scheduler.domain.rule_v2 import (
    RULE_V2_CONSTRAINT_TYPES,
    RULE_V2_COMPILER,
    RULE_V2_SCHEMA_VERSION,
    activate_rule_v2,
    normalize_rule_v2,
    parse_rule_v2_local,
    validate_rule_v2,
)


RULESET_SCHEMA_VERSION = "scheduler.ruleset.v2"
PROJECT_STATE_SCHEMA_VERSION = "scheduler.project_state.v2"
PUBLISH_RECORD_SCHEMA_VERSION = "scheduler.publish_record.v1"
MAX_RULESET_SNAPSHOTS = 30
MAX_PUBLISH_RECORDS = 50

DEFAULT_PROJECT_SETTINGS: dict[str, Any] = {
    "term_name": "2026-2027 学年第一学期",
    "term_start": "2026-09-01",
    "term_end": "2027-01-22",
    "week_mode": "weekly",
    "weekend_enabled": False,
    "active_days": ["星期一", "星期二", "星期三", "星期四", "星期五"],
    "public_rest": "星期六、星期日",
    "period_counts": {"early": 0, "morning": 0, "afternoon": 0, "evening": 0},
}


def load_project_settings() -> dict[str, Any]:
    """Return the education-office settings that describe one timetable project."""
    overrides = load_web_overrides()
    rules_root = overrides.get("rules") if isinstance(overrides.get("rules"), Mapping) else {}
    product = rules_root.get("product_state") if isinstance(rules_root.get("product_state"), Mapping) else {}
    saved = product.get("project_settings") if isinstance(product.get("project_settings"), Mapping) else {}
    settings = copy.deepcopy(DEFAULT_PROJECT_SETTINGS)
    settings.update({key: copy.deepcopy(value) for key, value in saved.items() if key in settings})
    settings["week_mode"] = "weekly"
    settings["weekend_enabled"] = bool(settings.get("weekend_enabled", False))
    settings["active_days"] = [
        str(value) for value in settings.get("active_days", [])
        if str(value) in {"星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"}
    ]
    counts = settings.get("period_counts") if isinstance(settings.get("period_counts"), Mapping) else {}
    settings["period_counts"] = {
        key: max(0, min(12, _as_int(counts.get(key), DEFAULT_PROJECT_SETTINGS["period_counts"][key])))
        for key in ("early", "morning", "afternoon", "evening")
    }
    return settings


def save_project_settings(raw: Mapping[str, Any], *, actor: str) -> dict[str, Any]:
    """Persist the plain-language calendar settings used by the foundation flow."""
    current = load_project_settings()
    term_name = str(raw.get("term_name") or current["term_name"]).strip()[:120]
    term_start = str(raw.get("term_start") or current["term_start"]).strip()[:20]
    term_end = str(raw.get("term_end") or current["term_end"]).strip()[:20]
    active_days = [
        str(value) for value in raw.get("active_days", current["active_days"])
        if str(value) in {"星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"}
    ]
    counts_raw = raw.get("period_counts") if isinstance(raw.get("period_counts"), Mapping) else current["period_counts"]
    settings = {
        "term_name": term_name,
        "term_start": term_start,
        "term_end": term_end,
        # V1 production launch intentionally uses one repeating week.  Keeping
        # this server-side prevents a stale browser from enabling A/B weeks.
        "week_mode": "weekly",
        "weekend_enabled": any(day in {"星期六", "星期日"} for day in active_days),
        "active_days": active_days or list(DEFAULT_PROJECT_SETTINGS["active_days"]),
        "public_rest": str(raw.get("public_rest") or current["public_rest"]).strip()[:200],
        "period_counts": {
            key: max(0, min(12, _as_int(counts_raw.get(key), current["period_counts"][key])))
            for key in ("early", "morning", "afternoon", "evening")
        },
        "updated_at": _utc_now(),
        "updated_by": str(actor or "web")[:120],
    }
    overrides = load_web_overrides()
    rules_root = overrides.setdefault("rules", {})
    product = rules_root.setdefault("product_state", {})
    product["project_settings"] = settings
    product["updated_at"] = settings["updated_at"]
    product["updated_by"] = settings["updated_by"]
    save_web_overrides(overrides, actor_user_id=actor, reason="project.settings.save")
    return copy.deepcopy(settings)


def load_rule_v2_payload() -> dict[str, Any]:
    overrides = load_web_overrides()
    section = _ruleset_section(overrides)
    rules = [copy.deepcopy(item) for item in section["rules"]]
    active = [item for item in rules if item.get("enabled", True) and item.get("status") == "active"]
    return {
        "schema_version": RULESET_SCHEMA_VERSION,
        "rule_schema_version": RULE_V2_SCHEMA_VERSION,
        "revision": section["revision"],
        "updated_at": section.get("updated_at", ""),
        "updated_by": section.get("updated_by", ""),
        "rules": rules,
        "summary": {
            "total": len(rules),
            "active": len(active),
            "hard": sum(1 for item in active if item.get("strength") == "hard"),
            "soft": sum(1 for item in active if item.get("strength") == "soft"),
            "drafts": sum(1 for item in rules if item.get("status") in {"draft", "needs_clarification", "validated"}),
            "unsupported": sum(1 for item in rules if (item.get("solver_support") or {}).get("status") != "supported"),
        },
        "snapshots": [copy.deepcopy(item) for item in section.get("snapshots", [])],
    }


def save_rule_v2(
    raw_rule: Mapping[str, Any],
    *,
    expected_revision: int | None,
    actor: str,
    reason: str = "rule.v2.save",
) -> dict[str, Any]:
    candidate = normalize_rule_v2(raw_rule)
    overrides = load_web_overrides()
    section = _ruleset_section(overrides)
    _assert_ruleset_revision(section, expected_revision)
    rules = list(section["rules"])
    existing = next((index for index, item in enumerate(rules) if str(item.get("id") or "") == candidate["id"]), None)
    if existing is None:
        rules.append(candidate)
    else:
        candidate["created_at"] = str(rules[existing].get("created_at") or candidate["created_at"])
        if _rule_semantic_digest(candidate) != _rule_semantic_digest(rules[existing]):
            candidate["status"] = "draft"
            candidate["confirmation"] = {
                "required": True,
                "confirmed": False,
                "confirmed_by": "",
                "confirmed_at": "",
            }
        rules[existing] = candidate
    _persist_ruleset(overrides, section, rules, actor=actor, reason=reason)
    return load_rule_v2_payload()


def activate_saved_rule_v2(
    rule_id: str,
    *,
    expected_revision: int | None,
    confirmed: bool,
    actor: str,
) -> dict[str, Any]:
    overrides = load_web_overrides()
    section = _ruleset_section(overrides)
    _assert_ruleset_revision(section, expected_revision)
    rules = list(section["rules"])
    index = next((i for i, item in enumerate(rules) if str(item.get("id") or "") == str(rule_id)), None)
    if index is None:
        raise ValueError(f"未找到规则：{rule_id}")
    rules[index] = activate_rule_v2(rules[index], confirmed=confirmed, actor=actor)
    _persist_ruleset(overrides, section, rules, actor=actor, reason="rule.v2.activate")
    return load_rule_v2_payload()


def set_rule_v2_enabled(
    rule_id: str,
    *,
    enabled: bool,
    expected_revision: int | None,
    actor: str,
) -> dict[str, Any]:
    overrides = load_web_overrides()
    section = _ruleset_section(overrides)
    _assert_ruleset_revision(section, expected_revision)
    rules = list(section["rules"])
    index = next((i for i, item in enumerate(rules) if str(item.get("id") or "") == str(rule_id)), None)
    if index is None:
        raise ValueError(f"未找到规则：{rule_id}")
    candidate = copy.deepcopy(rules[index])
    candidate["enabled"] = bool(enabled)
    candidate["status"] = "active" if enabled and candidate.get("status") == "disabled" else ("disabled" if not enabled else candidate.get("status"))
    candidate["updated_at"] = _utc_now()
    rules[index] = candidate
    _persist_ruleset(overrides, section, rules, actor=actor, reason="rule.v2.toggle")
    return load_rule_v2_payload()


def delete_rule_v2(
    rule_id: str,
    *,
    expected_revision: int | None,
    actor: str,
) -> dict[str, Any]:
    overrides = load_web_overrides()
    section = _ruleset_section(overrides)
    _assert_ruleset_revision(section, expected_revision)
    rules = [item for item in section["rules"] if str(item.get("id") or "") != str(rule_id)]
    if len(rules) == len(section["rules"]):
        raise ValueError(f"未找到规则：{rule_id}")
    _persist_ruleset(overrides, section, rules, actor=actor, reason="rule.v2.delete")
    return load_rule_v2_payload()


def apply_confirmed_rule_v2_drafts(
    overrides: dict[str, Any],
    drafts: Iterable[Mapping[str, Any]],
    *,
    actor: str,
    reason: str = "rule.v2.confirmed_batch",
) -> tuple[dict[str, Any], int, list[str]]:
    """Apply confirmed drafts to an in-memory workspace payload.

    This deliberately does not call save_web_overrides.  The conversation
    workflow persists the returned payload together with imported data and its
    session confirmation on one caller-owned database transaction.
    """
    section = _ruleset_section(overrides)
    rules = [copy.deepcopy(item) for item in section["rules"]]
    activated_ids: list[str] = []
    for raw_draft in drafts:
        candidate = normalize_rule_v2(raw_draft)
        existing = next((index for index, item in enumerate(rules) if str(item.get("id") or "") == candidate["id"]), None)
        if existing is None:
            rules.append(candidate)
            index = len(rules) - 1
        else:
            candidate["created_at"] = str(rules[existing].get("created_at") or candidate["created_at"])
            rules[existing] = candidate
            index = existing
        rules[index] = activate_rule_v2(rules[index], confirmed=True, actor=actor)
        activated_ids.append(str(rules[index].get("id") or ""))
    if activated_ids:
        _set_ruleset_payload(overrides, section, rules, actor=actor, reason=reason)
    return overrides, int(_ruleset_section(overrides)["revision"]), activated_ids


def parse_rule_v2_with_ai(
    text: str,
    *,
    known_teachers: Iterable[str] = (),
    known_subjects: Iterable[str] = (),
    known_classes: Iterable[str] = (),
    client: JsonModelClient | None = None,
    catalog: Iterable[Mapping[str, Any]] = (),
    slot_context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    source = str(text or "").strip()
    if not source:
        raise ValueError("自然语言规则不能为空")
    teacher_names = tuple(str(value).strip() for value in known_teachers if str(value).strip())
    subject_names = tuple(str(value).strip() for value in known_subjects if str(value).strip())
    if not subject_names and isinstance(slot_context, Mapping):
        subject_names = tuple(str(value).strip() for value in slot_context.get("subjects", ()) if str(value).strip())
    class_names = tuple(str(value).strip() for value in known_classes if str(value).strip())
    if client is None:
        draft = parse_rule_v2_local(
            source,
            known_teachers=teacher_names,
            known_subjects=subject_names,
            known_classes=class_names,
        )
        draft["ai_used"] = False
        draft["ai_note"] = "AI 服务未启用，已使用本地安全解析器生成草案。"
        draft["ai_modeling"] = _build_rule_modeling_report(
            draft,
            {},
            ai_used=False,
            note=draft["ai_note"],
        )
        return draft

    model_source, model_teachers, teacher_restore_map = pseudonymize_teacher_context(
        source,
        teacher_names,
    )
    teacher_redaction_map = {
        teacher: alias for alias, teacher in teacher_restore_map.items()
    }

    catalog_rows = [
        {
            "id": str(item.get("id") or ""),
            "title": replace_model_tokens(str(item.get("title") or ""), teacher_redaction_map),
            "description": replace_model_tokens(
                str(item.get("explanation") or item.get("description") or "")[:300],
                teacher_redaction_map,
            ),
        }
        for item in catalog
        if isinstance(item, Mapping) and str(item.get("id") or "")
    ][:120]
    system_prompt = (
        "你是学校教务排课规则建模助手。你必须实际参与建模：理解业务需求、拆分软硬约束、识别作用范围、"
        "作用时间与例外，并把可执行部分映射为 Rule V2。只输出一个 JSON 对象。"
        "输出字段：title, description, policy_level(default/schoolwide/grade_subject/special), "
        "business_domain(course/roster), rule_category(basic/teacher/subject), "
        "strength(hard/soft/advisory), scope, effective_time, exceptions, constraint, weight, solver_support, modeling_report。"
        "constraint 必须严格是 {type, params} 对象：type 是上述白名单之一，params 必须是对象；所有可执行参数只能放在 params 中。"
        "constraint.type 只能是 catalog_ref、teacher_unavailable、prefer_period、max_daily_lessons，"
        "或空字符串表示需要澄清；不得输出代码、表达式、脚本、action、execute、expression、solver 或新的执行类型。"
        "只有语义完全匹配时才把 solver_support.status 设为 supported，compiler 必须是 day.rule_v2.v1；"
        "否则设为 partial/unsupported 并说明缺少信息。默认作用时间为整个当前学期。"
        "modeling_report 必须包含 interpreted_requirements、constraint_mapping、limitations、recommendations 四个数组；"
        "每个局限必须说明对求解的影响，每条建议必须是教务人员可执行的解决动作。"
        "系统不需要第三方确认，只有当前用户对规则的明确确认。"
    )
    try:
        result = client.complete_json(
            system_prompt=system_prompt,
            user_payload={
                "requirement": model_source,
                "known_teachers": model_teachers,
                "allowlisted_constraint_types": sorted(RULE_V2_CONSTRAINT_TYPES),
                "catalog": catalog_rows,
                "slot_context": dict(slot_context or {}),
            },
        )
        restored = replace_model_tokens(result.value, teacher_restore_map)
        repaired = _repair_allowlisted_model_rule(
            restored,
            source,
            teacher_names,
            known_subjects=subject_names,
            known_classes=class_names,
            slot_context=slot_context,
        )
        draft = normalize_rule_v2(
            repaired,
            source_text=source,
            parser="model.rule_v2",
            provider_id=result.provider_id,
            model=result.model,
        )
        supplied_support = repaired.get("solver_support") if isinstance(repaired.get("solver_support"), Mapping) else {}
        if isinstance(draft.get("solver_support"), dict):
            draft["solver_support"]["message"] = str(supplied_support.get("message") or "")
        draft["ai_used"] = True
        draft["model_request_id"] = result.request_id
        draft["ai_modeling"] = _build_rule_modeling_report(
            draft,
            repaired,
            ai_used=True,
        )
        if repaired.get("_semantic_confirmation_state") == "pending_user_confirmation":
            draft["confirmation_state"] = "pending_user_confirmation"
            draft["candidate_id"] = str(draft.get("id") or "")
            draft["candidate_hash"] = rule_candidate_hash(draft)
            draft["confirmation_fields"] = list(RULE_CANDIDATE_CONFIRMATION_FIELDS)
        if draft["ai_modeling"]["limitations"]:
            current_support = draft.get("solver_support") if isinstance(draft.get("solver_support"), Mapping) else {}
            structurally_executable = (
                bool((draft.get("validation") or {}).get("valid"))
                and str(current_support.get("status") or "") == "supported"
                and str(current_support.get("compiler") or "") == RULE_V2_COMPILER
            )
            if structurally_executable:
                # Modeling notes are user-visible review material, not proof
                # that a validated Rule V2 candidate is unsupported.
                draft["solver_support"] = {
                    "status": "supported",
                    "compiler": RULE_V2_COMPILER,
                    "message": "",
                }
                draft["ai_modeling"]["status"] = "ready_with_notes"
                draft["ai_modeling"]["solver_handoff"] = {
                    "status": "supported",
                    "compiler": RULE_V2_COMPILER,
                    "requires_user_confirmation": True,
                }
            else:
                draft["solver_support"] = {
                    "status": "partial",
                    "compiler": "",
                    "message": "AI 已识别到尚未完整建模的需求；请先处理局限或拆分规则，再交给求解器。",
                }
                draft["status"] = "needs_clarification"
                draft["validation"] = validate_rule_v2(draft).as_dict()
                draft["ai_modeling"]["status"] = "limited"
                draft["ai_modeling"]["solver_handoff"] = {
                    "status": "partial",
                    "compiler": "",
                    "requires_user_confirmation": True,
                }
        if result.usage:
            draft["model_usage"] = result.usage
        if not draft["validation"]["valid"]:
            draft["status"] = "needs_clarification"
        return draft
    except Exception as exc:
        draft = parse_rule_v2_local(
            source,
            known_teachers=teacher_names,
            known_subjects=subject_names,
            known_classes=class_names,
        )
        draft["ai_used"] = False
        draft["ai_note"] = f"AI 建模失败，已回退本地安全解析器：{exc}"
        draft["ai_modeling"] = _build_rule_modeling_report(
            draft,
            {},
            ai_used=False,
            note="AI 建模服务本次不可用，当前仅为本地安全草案。",
        )
        return draft


def _repair_allowlisted_model_rule(
    value: Mapping[str, Any],
    source: str,
    known_teachers: Iterable[str],
    *,
    known_subjects: Iterable[str] = (),
    known_classes: Iterable[str] = (),
    slot_context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Repair deterministic omissions and block semantic changes from the model.

    The local parser is the deterministic contract for facts that can be
    established from the user's statement and uploaded entity roster.  A
    model may improve wording, but it must not change the rule's meaning.  A
    mismatch is deliberately left visible as a clarification blocker instead
    of being silently corrected or activated.
    """
    raw = copy.deepcopy(dict(value or {}))
    teacher_names = tuple(str(value).strip() for value in known_teachers if str(value).strip())
    subject_names = tuple(str(value).strip() for value in known_subjects if str(value).strip())
    class_names = tuple(str(value).strip() for value in known_classes if str(value).strip())
    local = parse_rule_v2_local(
        source,
        known_teachers=teacher_names,
        known_subjects=subject_names,
        known_classes=class_names,
    )
    semantic_repairs: list[str] = []
    local_constraint_type = str((local.get("constraint") or {}).get("type") or "")
    if local_constraint_type:
        local_strength = str(local.get("strength") or "")
        if local_strength and str(raw.get("strength") or "") != local_strength:
            raw["strength"] = local_strength
            semantic_repairs.append("模型改写了用户指定的规则强度；已恢复原意")
        local_scope = local.get("scope") if isinstance(local.get("scope"), Mapping) else {}
        candidate_scope = raw.get("scope") if isinstance(raw.get("scope"), Mapping) else {}
        if any(list(candidate_scope.get(key) or []) != list(local_scope.get(key) or []) for key in ("teachers", "subjects", "classes")):
            raw["scope"] = copy.deepcopy(local_scope)
            semantic_repairs.append("模型改写了作用对象；已恢复用户原句中的对象")
    scope = raw.get("scope") if isinstance(raw.get("scope"), Mapping) else {}
    if not any(scope.get(key) for key in ("grades", "classes", "subjects", "teachers", "rooms")):
        raw["scope"] = copy.deepcopy(local.get("scope") or {})
    constraint = raw.get("constraint") if isinstance(raw.get("constraint"), Mapping) else {}
    constraint_type = str(constraint.get("type") or "")
    local_constraint = local.get("constraint") if isinstance(local.get("constraint"), Mapping) else {}
    local_type = str(local_constraint.get("type") or "")
    if not constraint_type and local_type:
        raw["constraint"] = copy.deepcopy(local_constraint)
        raw["solver_support"] = copy.deepcopy(local.get("solver_support") or {})
        raw["guardrail_note"] = "模型未提供约束类型，采用确定性解析结果。"
        constraint = raw["constraint"]
        constraint_type = local_type
    raw, candidate_normalization_violations = _normalize_model_candidate_constraint(
        raw,
        slot_context=slot_context,
    )
    constraint = raw.get("constraint") if isinstance(raw.get("constraint"), Mapping) else {}
    constraint_type = str(constraint.get("type") or "")
    params = constraint.get("params") if isinstance(constraint.get("params"), Mapping) else {}
    local_params = local_constraint.get("params") if isinstance(local_constraint.get("params"), Mapping) else {}
    if (
        constraint_type == "prefer_period"
        and not params.get("period")
        and local_params.get("period")
        and not raw.get("_model_period_candidate_present")
        and not candidate_normalization_violations
    ):
        raw["constraint"] = {**dict(constraint), "params": {**dict(params), "period": local_params["period"]}}

    if candidate_normalization_violations:
        _mark_semantic_guard_blocked(raw, candidate_normalization_violations)

    normalized_probe = normalize_rule_v2(raw, source_text=source, parser="model.rule_v2")
    guard_result = _semantic_rule_guard_violations(
        source=source,
        local=local,
        candidate=normalized_probe,
    )
    violations, local_unknown = guard_result
    violations.extend(semantic_repairs)
    if candidate_normalization_violations:
        violations.extend(candidate_normalization_violations)
    if local_unknown and not isinstance(slot_context, Mapping):
        violations.append("无法确认规则类型：本地解析不确定且没有上传 slot_context 证据")
    if local_unknown:
        candidate_entity_violations = _candidate_entity_scope_violations(
            source=source,
            candidate=normalized_probe,
            known_teachers=teacher_names,
            known_subjects=subject_names,
            known_classes=class_names,
        )
        candidate_validation = validate_rule_v2(normalized_probe)
        candidate_type = str((normalized_probe.get("constraint") or {}).get("type") or "")
        candidate_is_supported = (
            candidate_validation.valid
            and candidate_type in RULE_V2_CONSTRAINT_TYPES
            and not candidate_entity_violations
            and not violations
        )
        if candidate_is_supported:
            raw["solver_support"] = {
                "status": "supported",
                "compiler": RULE_V2_COMPILER,
                "message": "",
            }
            raw["_semantic_confirmation_state"] = "pending_user_confirmation"
            raw["_semantic_confirmation_note"] = "本地解析未识别该表达，但候选已通过本地 Rule V2、实体和上下文证据校验，等待用户逐项确认。"
        else:
            reasons = list(violations)
            if candidate_entity_violations:
                reasons.extend(candidate_entity_violations)
            if not candidate_validation.valid:
                reasons.append("候选未通过 Rule V2 结构校验")
            if candidate_type not in RULE_V2_CONSTRAINT_TYPES:
                reasons.append("候选约束类型不在 Rule V2 白名单中")
            _mark_semantic_guard_blocked(raw, reasons or ["本地和 AI 均无法确认可执行语义"])
    elif violations:
        _mark_semantic_guard_blocked(raw, violations)
    else:
        candidate_validation = validate_rule_v2(normalized_probe)
        if candidate_validation.valid and str((normalized_probe.get("constraint") or {}).get("type") or "") in RULE_V2_CONSTRAINT_TYPES:
            raw["solver_support"] = {
                "status": "supported",
                "compiler": RULE_V2_COMPILER,
                "message": "",
            }
        else:
            _mark_semantic_guard_blocked(raw, ["候选未通过本地 Rule V2 结构校验"])
    return raw


_PREFERRED_PERIODS = frozenset({"morning", "afternoon", "early", "first", "last"})
_MODEL_EXECUTION_FIELDS = frozenset({
    "action", "execute", "execution", "expression", "code", "script", "solver",
    "operation", "call", "command", "function", "tool",
})
_PERIOD_LABEL_PREFIXES = (
    ("早自习", "early"),
    ("morning", "morning"),
    ("上午", "morning"),
    ("afternoon", "afternoon"),
    ("下午", "afternoon"),
)
_EXPLICIT_FIRST_LABELS = frozenset({"first", "首节", "第一节", "first_slot"})
_EXPLICIT_LAST_LABELS = frozenset({"last", "末节", "最后一节", "last_slot"})


def _slot_context_labels(slot_context: Mapping[str, Any] | None) -> tuple[str, ...]:
    if not isinstance(slot_context, Mapping) or str(slot_context.get("status") or "") != "available":
        return ()
    labels: list[str] = []
    rows = slot_context.get("time_grid_rows")
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, Mapping):
            continue
        for key in ("时段节次", "节次", "period", "slot", "time_slot", "时段", "block"):
            value = str(row.get(key) or "").strip()
            if value:
                labels.append(value)
    return tuple(dict.fromkeys(labels))


def _period_from_proven_slot(value: Any, labels: tuple[str, ...]) -> str | None:
    token = str(value or "").strip().lower()
    if not token:
        return None
    label_tokens = {item.lower() for item in labels}
    if token in _PREFERRED_PERIODS:
        for label in label_tokens:
            if token == "morning" and (label.startswith("morning") or label.startswith("上午")):
                return token
            if token == "afternoon" and (label.startswith("afternoon") or label.startswith("下午")):
                return token
            if token == "early" and (label.startswith("early") or label.startswith("早自习")):
                return token
            if token == "first" and label in _EXPLICIT_FIRST_LABELS:
                return token
            if token == "last" and label in _EXPLICIT_LAST_LABELS:
                return token
        return None
    for label in label_tokens:
        if token != label:
            continue
        for prefix, period in _PERIOD_LABEL_PREFIXES:
            if label.startswith(prefix):
                return period
        if label in _EXPLICIT_FIRST_LABELS:
            return "first"
        if label in _EXPLICIT_LAST_LABELS:
            return "last"
    return None


def _normalize_model_candidate_constraint(
    raw: dict[str, Any],
    *,
    slot_context: Mapping[str, Any] | None,
) -> tuple[dict[str, Any], list[str]]:
    """Keep model output inside the Rule V2 data contract.

    A localized slot label is only translated after an exact label is present
    in the uploaded time grid.  This intentionally refuses to infer a period
    from words such as “午间” or from a default school timetable.
    """
    source = raw.get("constraint") if isinstance(raw.get("constraint"), Mapping) else {}
    constraint_type = str(source.get("type") or raw.get("constraint_type") or "").strip()
    source_params = source.get("params") if isinstance(source.get("params"), Mapping) else {}
    violations: list[str] = []
    if not isinstance(raw.get("constraint"), Mapping):
        violations.append("模型候选 constraint 必须是 {type, params} 对象")
    if any(str(key).strip().lower() in _MODEL_EXECUTION_FIELDS for key in source):
        violations.append("模型候选包含被禁止的执行字段")

    params: dict[str, Any] = {}
    candidate_values: list[Any] = []
    for key in ("period", "preferred_periods"):
        if key in source_params:
            value = source_params.get(key)
            candidate_values.extend(value if key == "preferred_periods" and isinstance(value, list) else [value])
        if key in source:
            value = source.get(key)
            candidate_values.extend(value if key == "preferred_periods" and isinstance(value, list) else [value])
    raw["_model_period_candidate_present"] = bool(candidate_values)
    if constraint_type == "prefer_period":
        labels = _slot_context_labels(slot_context)
        canonical_values = [str(value or "").strip().lower() for value in candidate_values]
        if not candidate_values:
            # Let the deterministic parser fill this when the user sentence
            # itself establishes a canonical period.
            pass
        elif all(value in _PREFERRED_PERIODS for value in canonical_values) and len(set(canonical_values)) == 1:
            params["period"] = canonical_values[0]
        else:
            mapped = [period for value in candidate_values if (period := _period_from_proven_slot(value, labels))]
            if not labels:
                violations.append("prefer_period 非标准时段标签必须由上传的 slot_context 时段数据证明")
            elif len(mapped) != len(candidate_values) or len(set(mapped)) != 1:
                violations.append("模型返回的时段未知或无法唯一映射到 morning/afternoon/early/first/last")
            else:
                params["period"] = mapped[0]
    elif constraint_type == "max_daily_lessons":
        if "max" in source_params:
            params["max"] = source_params.get("max")
        elif "max" in source:
            params["max"] = source.get("max")
    elif constraint_type == "teacher_unavailable":
        # Rule V2 currently derives the time restriction from effective_time.
        params = {}
    elif constraint_type == "catalog_ref":
        params = {}

    allowed_constraint = {"type": constraint_type, "params": params}
    if constraint_type == "catalog_ref":
        allowed_constraint["catalog_id"] = str(source.get("catalog_id") or raw.get("catalog_id") or "").strip()[:160]
    raw["constraint"] = allowed_constraint
    if violations:
        return raw, list(dict.fromkeys(violations))
    return raw, []


_EXPLICIT_HARD_STRENGTH_MARKERS = (
    "必须", "务必", "一定要", "不得", "不能", "禁止", "严禁", "不允许", "禁排",
)
_EXPLICIT_SOFT_STRENGTH_MARKERS = (
    "尽量", "优先", "避免", "尽可能", "最好", "希望",
)
_EXPLICIT_ADVISORY_STRENGTH_MARKERS = (
    "仅供参考", "提醒", "建议",
)
_SEMANTIC_SCOPE_KEYS = ("campuses", "grades", "classes", "subjects", "teachers", "rooms")
RULE_CANDIDATE_CONFIRMATION_FIELDS = (
    "source",
    "scope",
    "effective_time",
    "constraint_type",
    "strength",
    "params",
)


def rule_candidate_hash(rule: Mapping[str, Any]) -> str:
    """Hash only the user-visible semantic fields of a Rule V2 candidate."""
    payload = {
        "id": str(rule.get("id") or ""),
        "source": rule.get("source") if isinstance(rule.get("source"), Mapping) else {},
        "scope": rule.get("scope") if isinstance(rule.get("scope"), Mapping) else {},
        "effective_time": rule.get("effective_time") if isinstance(rule.get("effective_time"), Mapping) else {},
        "constraint_type": str((rule.get("constraint") or {}).get("type") or "") if isinstance(rule.get("constraint"), Mapping) else "",
        "params": (rule.get("constraint") or {}).get("params", {}) if isinstance(rule.get("constraint"), Mapping) else {},
        "strength": str(rule.get("strength") or ""),
        "business_domain": str(rule.get("business_domain") or ""),
        "rule_category": str(rule.get("rule_category") or ""),
        "solver_support": rule.get("solver_support") if isinstance(rule.get("solver_support"), Mapping) else {},
    }
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
def _explicit_strength_from_source(source: str) -> str | None:
    text = str(source or "")
    if any(marker in text for marker in _EXPLICIT_HARD_STRENGTH_MARKERS):
        return "hard"
    if any(marker in text for marker in _EXPLICIT_ADVISORY_STRENGTH_MARKERS):
        return "advisory"
    if any(marker in text for marker in _EXPLICIT_SOFT_STRENGTH_MARKERS):
        return "soft"
    return None


def _semantic_json_equal(left: Any, right: Any) -> bool:
    return json.dumps(left, ensure_ascii=False, sort_keys=True, separators=(",", ":")) == json.dumps(
        right,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _semantic_rule_guard_violations(
    *,
    source: str,
    local: Mapping[str, Any],
    candidate: Mapping[str, Any],
) -> tuple[list[str], bool]:
    """Return semantic conflicts and whether local parsing was inconclusive."""
    violations: list[str] = []
    local_support = local.get("solver_support") if isinstance(local.get("solver_support"), Mapping) else {}
    local_constraint = local.get("constraint") if isinstance(local.get("constraint"), Mapping) else {}
    candidate_constraint = candidate.get("constraint") if isinstance(candidate.get("constraint"), Mapping) else {}
    local_type = str(local_constraint.get("type") or "")
    candidate_type = str(candidate_constraint.get("type") or "")

    local_unknown = str(local_support.get("status") or "") != "supported" or not local_type
    if not local_unknown and candidate_type != local_type:
        violations.append("模型改写了确定性规则类型")

    source_text = str(source or "")
    source_prefers_period = any(
        marker in source_text for marker in ("上午", "下午", "早自习", "午前", "午后", "首节", "末节", "最后一节")
    ) and not any(marker in source_text for marker in ("每天最多", "最多安排", "不能上课", "不得上课", "不可排课"))
    if source_prefers_period and candidate_type and candidate_type != "prefer_period":
        violations.append("用户原句明确表达时段偏好，模型不得改写为其他约束类型")

    expected_strength = _explicit_strength_from_source(source)
    if expected_strength is None:
        expected_strength = str(local.get("strength") or "")
    if expected_strength and str(candidate.get("strength") or "") != expected_strength:
        violations.append("模型改写了规则强度")

    if local_type and not _semantic_json_equal(
        candidate_constraint.get("params") if isinstance(candidate_constraint.get("params"), Mapping) else {},
        local_constraint.get("params") if isinstance(local_constraint.get("params"), Mapping) else {},
    ):
        violations.append("模型改写了约束关键参数")

    local_scope = local.get("scope") if isinstance(local.get("scope"), Mapping) else {}
    candidate_scope = candidate.get("scope") if isinstance(candidate.get("scope"), Mapping) else {}
    for key in _SEMANTIC_SCOPE_KEYS:
        expected = list(local_scope.get(key) or [])
        actual = list(candidate_scope.get(key) or [])
        if expected != actual and (expected or actual):
            violations.append(f"模型改写了实体范围 scope.{key}")
    local_exclude = local_scope.get("exclude") if isinstance(local_scope.get("exclude"), Mapping) else {}
    candidate_exclude = candidate_scope.get("exclude") if isinstance(candidate_scope.get("exclude"), Mapping) else {}
    if not _semantic_json_equal(local_exclude, candidate_exclude) and (local_exclude or candidate_exclude):
        violations.append("模型改写了实体排除范围")

    local_time = local.get("effective_time") if isinstance(local.get("effective_time"), Mapping) else {}
    candidate_time = candidate.get("effective_time") if isinstance(candidate.get("effective_time"), Mapping) else {}
    for key in ("mode", "term_id", "date_from", "date_to", "week_pattern", "weeks", "days", "slots"):
        expected = local_time.get(key)
        actual = candidate_time.get(key)
        if expected != actual and (expected or actual):
            violations.append(f"模型改写了生效时间 {key}")

    for key in ("business_domain", "rule_category"):
        if str(candidate.get(key) or "") != str(local.get(key) or ""):
            violations.append(f"模型改写了业务语义字段 {key}")

    return list(dict.fromkeys(violations)), local_unknown


def _candidate_entity_scope_violations(
    *,
    source: str,
    candidate: Mapping[str, Any],
    known_teachers: Iterable[str],
    known_subjects: Iterable[str],
    known_classes: Iterable[str] = (),
) -> list[str]:
    scope = candidate.get("scope") if isinstance(candidate.get("scope"), Mapping) else {}
    source_text = str(source or "")
    known = {
        "teachers": {str(value).strip() for value in known_teachers if str(value).strip()},
        "subjects": {str(value).strip() for value in known_subjects if str(value).strip()},
        "classes": {str(value).strip() for value in known_classes if str(value).strip()},
    }
    violations: list[str] = []
    for key in _SEMANTIC_SCOPE_KEYS:
        values = scope.get(key) if isinstance(scope.get(key), list) else []
        for value in values:
            entity = str(value).strip()
            if not entity:
                continue
            if known.get(key) and entity not in known[key]:
                violations.append(f"候选实体不在上传的 {key} 数据中")
            elif entity not in source_text:
                violations.append(f"候选实体 scope.{key} 未在用户原句或上传实体中确认")
    return list(dict.fromkeys(violations))


def _mark_semantic_guard_blocked(raw: dict[str, Any], violations: Iterable[str]) -> None:
    reasons = [str(item).strip() for item in violations if str(item).strip()]
    if not reasons:
        return
    raw["status"] = "needs_clarification"
    raw["solver_support"] = {
        "status": "unsupported",
        "compiler": "",
        "message": "语义守卫阻止模型候选进入求解：" + "；".join(reasons),
    }
    raw["ai_note"] = "语义守卫要求用户核对：" + "；".join(reasons)
    report = copy.deepcopy(raw.get("modeling_report")) if isinstance(raw.get("modeling_report"), Mapping) else {}
    limitations = report.get("limitations") if isinstance(report.get("limitations"), list) else []
    limitations.append({
        "title": "模型候选与用户原始语义不一致",
        "detail": "；".join(reasons),
        "impact": "未核对前不得激活或交给求解器",
        "recommendation": "请核对规则类型、强度、关键参数和作用范围后重新确认",
    })
    report["limitations"] = limitations[:8]
    report.setdefault("interpreted_requirements", [])
    report.setdefault("constraint_mapping", [])
    report.setdefault("recommendations", [])
    raw["modeling_report"] = report


def _build_rule_modeling_report(
    draft: Mapping[str, Any],
    raw: Mapping[str, Any],
    *,
    ai_used: bool,
    note: str = "",
) -> dict[str, Any]:
    source_report = raw.get("modeling_report") if isinstance(raw.get("modeling_report"), Mapping) else {}
    if not source_report and isinstance(raw.get("ai_modeling"), Mapping):
        source_report = raw.get("ai_modeling")  # type: ignore[assignment]
    interpreted = _report_text_list(source_report.get("interpreted_requirements"))
    if not interpreted:
        interpreted = [str(draft.get("description") or draft.get("title") or "当前排课需求")[:400]]
    mappings = _report_mapping_list(
        source_report.get("constraint_mapping"),
        fields=("requirement", "rule_v2_type", "strength", "solver_effect", "support_status"),
    )
    constraint = draft.get("constraint") if isinstance(draft.get("constraint"), Mapping) else {}
    support = draft.get("solver_support") if isinstance(draft.get("solver_support"), Mapping) else {}
    if not mappings:
        mappings = [{
            "requirement": str(draft.get("title") or "当前排课需求")[:300],
            "rule_v2_type": str(constraint.get("type") or "待补充")[:120],
            "strength": str(draft.get("strength") or "soft")[:40],
            "solver_effect": "编译为求解约束" if support.get("status") == "supported" else "暂不进入求解",
            "support_status": str(support.get("status") or "unsupported")[:40],
        }]
    limitations = _report_mapping_list(
        source_report.get("limitations"),
        fields=("title", "detail", "impact", "recommendation"),
    )
    validation = draft.get("validation") if isinstance(draft.get("validation"), Mapping) else {}
    for message in [*list(validation.get("errors") or []), *list(validation.get("warnings") or [])]:
        text = str(message or "").strip()
        if text and not any(text in str(item.get("detail") or "") for item in limitations):
            limitations.append({
                "title": "规则结构或求解支持仍有限",
                "detail": text[:500],
                "impact": "未解决前不能把该草案加入正式求解",
                "recommendation": "编辑草案补充范围、时间或约束参数后重新检查",
            })
    recommendations = _report_mapping_list(
        source_report.get("recommendations"),
        fields=("title", "action", "reason"),
    )
    if limitations and not recommendations:
        recommendations = [{
            "title": "补齐规则信息后重新建模",
            "action": str(limitations[0].get("recommendation") or "编辑草案，补充缺失字段并重新检查")[:500],
            "reason": "只有通过 Rule V2 校验且求解器支持的规则才能由用户确认",
        }]
    if not ai_used and note:
        limitations.insert(0, {
            "title": "AI 本次未完成建模",
            "detail": str(note)[:500],
            "impact": "当前草案可能只覆盖基础语义",
            "recommendation": "检查模型服务后重新生成，或由用户编辑并确认草案",
        })
    blocking_items = [
        {
            "title": str(item.get("title") or "建模局限")[:200],
            "limitation": str(item.get("detail") or item.get("impact") or "")[:500],
            "solution": str(
                item.get("recommendation")
                or (recommendations[index].get("action") if index < len(recommendations) else "")
                or "补充信息后重新建模"
            )[:500],
        }
        for index, item in enumerate(limitations[:8])
    ]
    return {
        "participated": bool(ai_used),
        "status": "ready" if ai_used and not limitations and support.get("status") == "supported" else ("limited" if ai_used else "fallback"),
        "interpreted_requirements": interpreted[:8],
        "constraint_mapping": mappings[:8],
        "limitations": limitations[:8],
        "recommendations": recommendations[:8],
        "blocking_items": blocking_items,
        "solver_handoff": {
            "status": str(support.get("status") or "unsupported")[:40],
            "compiler": str(support.get("compiler") or "")[:120],
            "requires_user_confirmation": True,
        },
    }


def _report_text_list(value: Any, *, limit: int = 12, maximum: int = 500) -> list[str]:
    items = value if isinstance(value, list) else []
    return [str(item).strip()[:maximum] for item in items[:limit] if str(item).strip()]


def _report_mapping_list(
    value: Any,
    *,
    fields: tuple[str, ...],
    limit: int = 12,
    maximum: int = 500,
) -> list[dict[str, str]]:
    items = value if isinstance(value, list) else []
    result: list[dict[str, str]] = []
    for item in items[:limit]:
        if isinstance(item, Mapping):
            row = {field: str(item.get(field) or "").strip()[:maximum] for field in fields}
        else:
            row = {fields[0]: str(item or "").strip()[:maximum]}
        if any(row.values()):
            result.append(row)
    return result


def review_readiness_blockers_with_ai(
    readiness: Mapping[str, Any],
    *,
    known_teachers: Iterable[str] = (),
    client: JsonModelClient | None = None,
) -> dict[str, Any]:
    items = [
        {
            "title": str(item.get("title") or item.get("domain") or "排课阻断项")[:200],
            "severity": str(item.get("severity") or "warning")[:40],
            "detail": str(item.get("detail") or "")[:1_000],
            "suggestion": str(item.get("suggestion") or "")[:1_000],
        }
        for item in readiness.get("items", [])
        if isinstance(item, Mapping)
        and str(item.get("severity") or "") in {"error", "blocked", "warning"}
    ][:24]
    fallback_items = [
        {
            "source_title": item["title"],
            "limitation": item["detail"] or "当前数据或规则尚不满足求解条件。",
            "solution": item["suggestion"] or "补齐对应数据或调整规则后重新检查。",
            "priority": "必须先处理" if item["severity"] in {"error", "blocked"} else "建议处理",
            "solvability": "处理后重新运行求解前检查",
        }
        for item in items
    ]
    if client is None:
        return {
            "ai_used": False,
            "status": "fallback",
            "summary": "AI 阻断审查当前不可用，已展示系统校验给出的现有局限与处理建议。",
            "items": fallback_items,
        }
    serialized = json.dumps(items, ensure_ascii=False)
    redacted, _mentioned, restore_map = pseudonymize_teacher_context(serialized, known_teachers)
    try:
        redacted_items = json.loads(redacted)
        result = client.complete_json(
            system_prompt=(
                "你是学校教务排课的阻断审查助手。根据系统已确认的校验事实逐项分析，"
                "只输出 JSON 对象：summary 和 items。items 每项必须包含 source_title、limitation、solution、"
                "priority、solvability。不得虚构已完成的修复，不得要求第三方审批；解决建议必须是当前教务用户"
                "可执行的具体动作，并明确哪些能力是当前系统或数据的局限。"
            ),
            user_payload={"blocking_checks": redacted_items},
        )
        restored = replace_model_tokens(result.value, restore_map)
        reviewed = _report_mapping_list(
            restored.get("items") if isinstance(restored, Mapping) else [],
            fields=("source_title", "limitation", "solution", "priority", "solvability"),
            limit=24,
            maximum=1_000,
        )
        return {
            "ai_used": True,
            "status": "ready",
            "summary": str(restored.get("summary") or "AI 已逐项分析现有局限并给出处理建议。")[:1_000],
            "items": reviewed or fallback_items,
            "request_id": result.request_id,
        }
    except Exception:
        return {
            "ai_used": False,
            "status": "fallback",
            "summary": "AI 阻断审查本次未成功，已保留系统校验给出的现有局限与处理建议。",
            "items": fallback_items,
        }


def attach_formal_solve_phase(status: Mapping[str, Any] | None) -> dict[str, Any]:
    payload = copy.deepcopy(dict(status or {}))
    raw_status = str(payload.get("status") or "idle")
    failed_phase = str(payload.get("failed_phase") or "finding_feasible")
    execution_phase = str(payload.get("execution_phase") or "")
    if raw_status in {"queued", "starting"}:
        phase = "validating"
    elif raw_status in {"running", "pause_requested", "cancel_requested"}:
        solution_count = _as_int(payload.get("solution_count"), _as_int(payload.get("solutions_found"), 0))
        phase = execution_phase if execution_phase in {"validating", "compiling", "finding_feasible", "optimizing", "packaging"} else ("optimizing" if solution_count > 0 else "finding_feasible")
    elif raw_status == "completed":
        phase = "completed"
    elif raw_status in {"failed", "cancelled", "stopped"}:
        phase = "failed"
    else:
        phase = "idle"
    order = ["validating", "compiling", "finding_feasible", "optimizing", "packaging"]
    if phase == "failed" and failed_phase in order:
        current_index = order.index(failed_phase)
    else:
        current_index = order.index(phase) if phase in order else (len(order) if phase == "completed" else -1)
    payload["phase"] = phase
    payload["phase_label"] = {
        "idle": "等待启动",
        "validating": "校验数据与规则",
        "compiling": "应用排课规则",
        "finding_feasible": "寻找首个可行解",
        "optimizing": "全局优化候选课表",
        "packaging": "生成结果与诊断",
        "completed": "求解完成",
        "failed": "求解未完成",
    }[phase]
    payload["phase_timeline"] = [
        {
            "id": item,
            "label": {
                "validating": "校验数据与规则",
                "compiling": "应用排课规则",
                "finding_feasible": "寻找可行解",
                "optimizing": "全局优化",
                "packaging": "生成结果包",
            }[item],
            "status": (
                "completed"
                if current_index > index or phase == "completed"
                else "failed"
                if phase == "failed" and current_index == index
                else "active"
                if current_index == index
                else "pending"
            ),
        }
        for index, item in enumerate(order)
    ]
    return payload


def build_project_state(
    *,
    teacher_rows: Iterable[Mapping[str, Any]],
    day_rules: Mapping[str, Any],
    readiness: Mapping[str, Any],
    solve_status: Mapping[str, Any],
    result_preview: Mapping[str, Any],
) -> dict[str, Any]:
    rule_payload = load_rule_v2_payload()
    solve = attach_formal_solve_phase(solve_status)
    teachers = list(teacher_rows)
    day_rule_count = sum(len(value) for value in day_rules.values() if isinstance(value, list))
    readiness_summary = readiness.get("summary") if isinstance(readiness.get("summary"), Mapping) else {}
    result_has_schedule = _result_preview_has_schedule(result_preview)
    solve_completed = str(solve.get("status") or "") == "completed" and result_has_schedule
    publish = load_publish_state()
    stages = [
        _stage("foundation", "基础设置", bool(teachers and day_rule_count), "导入教师定位表并完成作息、课时设置"),
        _stage("rules", "规则设置", rule_payload["summary"]["active"] > 0 or bool(readiness_summary.get("can_start_solver")), "核对默认规则，并用 AI 助手整理个性化要求"),
        _stage("solve", "AI 智能排课", solve_completed, "工业级求解引擎校验可行性并全局优化"),
        _stage("review", "方案审查与优化", result_has_schedule, "查看风险、说明问题并发起二次优化"),
        _stage("publish", "课表发布", bool(publish.get("current")), "由当前用户确认、下载并留存当前版本"),
    ]
    current = next((item for item in stages if not item["completed"]), stages[-1])
    if solve.get("status") in {"queued", "starting", "running", "pause_requested", "cancel_requested"}:
        current = stages[2]
    return {
        "schema_version": PROJECT_STATE_SCHEMA_VERSION,
        "phase": current["id"],
        "phase_label": current["label"],
        "stages": stages,
        "readiness": copy.deepcopy(dict(readiness_summary)),
        "ruleset": rule_payload["summary"],
        "solve": solve,
        "publish": publish,
        "settings": load_project_settings(),
        "updated_at": _utc_now(),
    }


def load_publish_state() -> dict[str, Any]:
    overrides = load_web_overrides()
    rules = overrides.get("rules") if isinstance(overrides.get("rules"), Mapping) else {}
    state = rules.get("product_state") if isinstance(rules.get("product_state"), Mapping) else {}
    records = [copy.deepcopy(item) for item in state.get("publish_records", []) if isinstance(item, Mapping)]
    return {
        "schema_version": PUBLISH_RECORD_SCHEMA_VERSION,
        "current": copy.deepcopy(records[-1]) if records else None,
        "records": records,
        "count": len(records),
    }


def publish_current_candidate(
    status: Mapping[str, Any],
    *,
    actor: str,
    note: str = "",
    version_label: str = "",
    result_preview: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    assessment = status.get("publish_assessment") if isinstance(status.get("publish_assessment"), Mapping) else {}
    summary = assessment.get("summary") if isinstance(assessment.get("summary"), Mapping) else {}
    if str(summary.get("status") or "") != "ready" or summary.get("can_publish") is not True:
        raise ValueError("当前候选尚未通过发布门禁")
    freshness = status.get("config_freshness") if isinstance(status.get("config_freshness"), Mapping) else {}
    if str(freshness.get("status") or "") == "stale" or status.get("config_changed_after_run") is True:
        raise ValueError("规则或基础数据已在求解后变化，请重新求解后再发布")
    if result_preview is not None and not _result_preview_has_schedule(result_preview):
        raise ValueError("当前候选缺少可在线核验的课表文件，请重新求解并生成结果包")
    files = [item for item in status.get("files", []) if isinstance(item, Mapping)]
    schedule_files = [item for item in files if str(item.get("category") or "") == "schedule" or str(item.get("name") or "").endswith((".xlsx", ".xls"))]
    if not schedule_files:
        raise ValueError("当前候选没有可发布的课表文件")

    overrides = load_web_overrides()
    rules = overrides.setdefault("rules", {})
    product = rules.setdefault("product_state", {})
    records = [copy.deepcopy(item) for item in product.get("publish_records", []) if isinstance(item, Mapping)]
    version = str(version_label or f"课表 V{len(records) + 1}").strip()[:80]
    record = {
        "schema_version": PUBLISH_RECORD_SCHEMA_VERSION,
        "id": "publish." + hashlib.sha256(f"{_utc_now()}|{actor}|{version}".encode("utf-8")).hexdigest()[:16],
        "version": version,
        "status": "published",
        "run_id": str(status.get("job_id") or status.get("run_id") or status.get("run_dir") or "")[-240:],
        "ruleset_revision": _ruleset_section(overrides)["revision"],
        "config_fingerprint": copy.deepcopy(status.get("config_fingerprint") or status.get("current_config_fingerprint") or {}),
        "schedule_files": [str(item.get("name") or item.get("path") or "")[-240:] for item in schedule_files[:20]],
        "note": str(note or "").strip()[:1_000],
        "published_by": str(actor or "web")[:120],
        "published_at": _utc_now(),
    }
    records.append(record)
    product["publish_records"] = records[-MAX_PUBLISH_RECORDS:]
    product["updated_at"] = record["published_at"]
    product["updated_by"] = record["published_by"]
    save_web_overrides(overrides, actor_user_id=actor, reason="project.publish")
    return load_publish_state()


def _result_preview_has_schedule(result_preview: Mapping[str, Any]) -> bool:
    summary = result_preview.get("summary") if isinstance(result_preview.get("summary"), Mapping) else {}
    availability = result_preview.get("availability") if isinstance(result_preview.get("availability"), Mapping) else {}
    return bool(
        summary.get("schedule_files")
        or availability.get("schedule_file_count")
        or result_preview.get("has_schedule")
        or result_preview.get("workbooks")
        or result_preview.get("class_views")
        or result_preview.get("teacher_views")
    )


def flatten_catalog_rules(groups: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        copy.deepcopy(dict(rule))
        for group in groups
        if isinstance(group, Mapping)
        for rule in (group.get("rules") if isinstance(group.get("rules"), list) else [])
        if isinstance(rule, Mapping)
    ]


def _ruleset_section(overrides: Mapping[str, Any]) -> dict[str, Any]:
    rules_root = overrides.get("rules") if isinstance(overrides.get("rules"), Mapping) else {}
    raw = rules_root.get("rule_v2") if isinstance(rules_root.get("rule_v2"), Mapping) else {}
    rules = [copy.deepcopy(item) for item in raw.get("rules", []) if isinstance(item, Mapping)]
    snapshots = [copy.deepcopy(item) for item in raw.get("snapshots", []) if isinstance(item, Mapping)]
    return {
        "schema_version": RULESET_SCHEMA_VERSION,
        "revision": max(0, _as_int(raw.get("revision"), 0)),
        "rules": rules,
        "snapshots": snapshots[-MAX_RULESET_SNAPSHOTS:],
        "updated_at": str(raw.get("updated_at") or ""),
        "updated_by": str(raw.get("updated_by") or ""),
    }


def _persist_ruleset(
    overrides: dict[str, Any],
    previous: Mapping[str, Any],
    rules: list[Mapping[str, Any]],
    *,
    actor: str,
    reason: str,
) -> None:
    _set_ruleset_payload(overrides, previous, rules, actor=actor, reason=reason)
    save_web_overrides(overrides, actor_user_id=actor, reason=reason)


def _set_ruleset_payload(
    overrides: dict[str, Any],
    previous: Mapping[str, Any],
    rules: list[Mapping[str, Any]],
    *,
    actor: str,
    reason: str,
) -> None:
    revision = int(previous.get("revision") or 0) + 1
    frozen_rules = [copy.deepcopy(dict(item)) for item in rules]
    digest = hashlib.sha256(json.dumps(frozen_rules, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    snapshot = {
        "revision": revision,
        "digest": digest,
        "created_at": _utc_now(),
        "created_by": str(actor or "web")[:120],
        "active_rule_ids": [str(item.get("id") or "") for item in frozen_rules if item.get("status") == "active" and item.get("enabled", True)],
        "rules": frozen_rules,
    }
    snapshots = [copy.deepcopy(item) for item in previous.get("snapshots", []) if isinstance(item, Mapping)]
    if not snapshots or snapshots[-1].get("digest") != digest:
        snapshots.append(snapshot)
    rules_root = overrides.setdefault("rules", {})
    rules_root["rule_v2"] = {
        "schema_version": RULESET_SCHEMA_VERSION,
        "revision": revision,
        "rules": frozen_rules,
        "snapshots": snapshots[-MAX_RULESET_SNAPSHOTS:],
        "updated_at": snapshot["created_at"],
        "updated_by": snapshot["created_by"],
    }


def _rule_semantic_digest(rule: Mapping[str, Any]) -> str:
    fields = {
        key: copy.deepcopy(rule.get(key))
        for key in (
            "title",
            "description",
            "policy_level",
            "business_domain",
            "rule_category",
            "strength",
            "enabled",
            "scope",
            "effective_time",
            "exceptions",
            "constraint",
            "weight",
            "solver_support",
        )
    }
    return hashlib.sha256(
        json.dumps(fields, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _assert_ruleset_revision(section: Mapping[str, Any], expected: int | None) -> None:
    if expected is None:
        return
    if int(expected) != int(section.get("revision") or 0):
        raise ValueError("规则集已被其他操作更新，请刷新后重试")


def _stage(stage_id: str, label: str, completed: bool, description: str) -> dict[str, Any]:
    return {"id": stage_id, "label": label, "completed": bool(completed), "description": description}


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
