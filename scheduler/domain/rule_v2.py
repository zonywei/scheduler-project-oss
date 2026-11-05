# -*- coding: utf-8 -*-
"""Safe, versioned Rule V2 contracts for AI-assisted school scheduling."""
from __future__ import annotations

import copy
import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping


RULE_V2_SCHEMA_VERSION = "scheduler.rule.v2"
RULE_V2_POLICY_LEVELS = {"default", "schoolwide", "grade_subject", "special"}
RULE_V2_BUSINESS_DOMAINS = {"course", "roster"}
RULE_V2_RULE_CATEGORIES = {"basic", "teacher", "subject"}
RULE_V2_STRENGTHS = {"hard", "soft", "advisory"}
RULE_V2_STATUSES = {
    "draft",
    "needs_clarification",
    "validated",
    "active",
    "disabled",
    "rejected",
}
RULE_V2_SUPPORT_STATUSES = {"supported", "partial", "unsupported"}
RULE_V2_WEEK_PATTERNS = {"all", "a", "b", "ab", "odd", "even", "specific"}
RULE_V2_TIME_MODES = {"project_term", "date_range"}
RULE_V2_CONSTRAINT_TYPES = {
    "catalog_ref",
    "teacher_unavailable",
    "prefer_period",
    "max_daily_lessons",
}
RULE_V2_COMPILER = "day.rule_v2.v1"

_RULE_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_ALLOWED_DAYS = {f"星期{value}" for value in "一二三四五六日"}
_DAY_ALIASES = {
    "周一": "星期一", "星期一": "星期一",
    "周二": "星期二", "星期二": "星期二",
    "周三": "星期三", "星期三": "星期三",
    "周四": "星期四", "星期四": "星期四",
    "周五": "星期五", "星期五": "星期五",
    "周六": "星期六", "星期六": "星期六",
    "周日": "星期日", "周天": "星期日", "星期日": "星期日",
}
_MAX_LIST_ITEMS = 300
_MAX_EXCEPTIONS = 80


@dataclass(frozen=True)
class RuleV2Validation:
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def valid(self) -> bool:
        return not self.errors

    def as_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "requires_confirmation": True,
        }


def normalize_rule_v2(
    value: Mapping[str, Any],
    *,
    source_text: str = "",
    parser: str = "manual",
    provider_id: str = "",
    model: str = "",
) -> dict[str, Any]:
    """Return a JSON-safe Rule V2 object without executing model-provided expressions."""
    raw = copy.deepcopy(dict(value or {}))
    now = _utc_now()
    source_raw = raw.get("source") if isinstance(raw.get("source"), Mapping) else {}
    source_value = str(source_text or source_raw.get("text") or raw.get("source_text") or "").strip()
    rule_id = str(raw.get("id") or _stable_rule_id(source_value or str(raw.get("title") or now))).strip()
    title = str(raw.get("title") or raw.get("name") or _title_from_source(source_value)).strip()[:120]

    scope_raw = raw.get("scope") if isinstance(raw.get("scope"), Mapping) else {}
    scope = {
        key: _clean_string_list(scope_raw.get(key), maximum=_MAX_LIST_ITEMS)
        for key in ("campuses", "grades", "classes", "subjects", "teachers", "rooms")
    }
    exclude_raw = scope_raw.get("exclude") if isinstance(scope_raw.get("exclude"), Mapping) else {}
    scope["exclude"] = {
        key: _clean_string_list(exclude_raw.get(key), maximum=_MAX_LIST_ITEMS)
        for key in ("campuses", "grades", "classes", "subjects", "teachers", "rooms")
    }

    time_raw = raw.get("effective_time") if isinstance(raw.get("effective_time"), Mapping) else {}
    effective_time = {
        "mode": str(time_raw.get("mode") or "project_term").strip(),
        "term_id": str(time_raw.get("term_id") or "current").strip()[:120],
        "date_from": str(time_raw.get("date_from") or "").strip()[:20],
        "date_to": str(time_raw.get("date_to") or "").strip()[:20],
        "week_pattern": str(time_raw.get("week_pattern") or "all").strip().lower(),
        "weeks": _clean_int_list(time_raw.get("weeks"), minimum=1, maximum=60),
        "days": [_normalize_day(item) for item in _clean_string_list(time_raw.get("days")) if _normalize_day(item)],
        "slots": _clean_string_list(time_raw.get("slots"), maximum=80),
    }

    exceptions: list[dict[str, Any]] = []
    for index, item in enumerate(raw.get("exceptions") if isinstance(raw.get("exceptions"), list) else []):
        if not isinstance(item, Mapping) or len(exceptions) >= _MAX_EXCEPTIONS:
            continue
        item_scope = item.get("scope") if isinstance(item.get("scope"), Mapping) else {}
        exceptions.append(
            {
                "id": str(item.get("id") or f"exception-{index + 1}")[:128],
                "mode": str(item.get("mode") or "exclude").strip().lower(),
                "days": [_normalize_day(day) for day in _clean_string_list(item.get("days")) if _normalize_day(day)],
                "slots": _clean_string_list(item.get("slots"), maximum=80),
                "scope": {
                    key: _clean_string_list(item_scope.get(key), maximum=_MAX_LIST_ITEMS)
                    for key in ("grades", "classes", "subjects", "teachers", "rooms")
                },
                "note": str(item.get("note") or "").strip()[:400],
            }
        )

    constraint_raw = raw.get("constraint") if isinstance(raw.get("constraint"), Mapping) else {}
    constraint_type = str(constraint_raw.get("type") or raw.get("constraint_type") or "").strip()
    params_raw = constraint_raw.get("params") if isinstance(constraint_raw.get("params"), Mapping) else {}
    constraint = {
        "type": constraint_type,
        "params": _json_safe_params(params_raw),
    }
    if constraint_type == "catalog_ref":
        constraint["catalog_id"] = str(constraint_raw.get("catalog_id") or raw.get("catalog_id") or "").strip()[:160]

    support_raw = raw.get("solver_support") if isinstance(raw.get("solver_support"), Mapping) else {}
    inferred_support = "supported" if constraint_type in RULE_V2_CONSTRAINT_TYPES and constraint_type else "unsupported"
    support_status = str(support_raw.get("status") or inferred_support).strip().lower()
    solver_support = {
        "status": support_status,
        "compiler": str(support_raw.get("compiler") or (RULE_V2_COMPILER if support_status == "supported" else "")).strip()[:120],
        "message": str(support_raw.get("message") or _support_message(support_status)).strip()[:500],
    }

    confirmation_raw = raw.get("confirmation") if isinstance(raw.get("confirmation"), Mapping) else {}
    confirmation = {
        "required": True,
        "confirmed": bool(confirmation_raw.get("confirmed", False)),
        "confirmed_by": str(confirmation_raw.get("confirmed_by") or "").strip()[:120],
        "confirmed_at": str(confirmation_raw.get("confirmed_at") or "").strip()[:80],
    }

    provenance_raw = raw.get("provenance") if isinstance(raw.get("provenance"), Mapping) else {}
    normalized = {
        "schema_version": RULE_V2_SCHEMA_VERSION,
        "id": rule_id,
        "title": title or "未命名规则",
        "description": str(raw.get("description") or source_value or title).strip()[:2_000],
        "policy_level": str(raw.get("policy_level") or "special").strip().lower(),
        "business_domain": str(raw.get("business_domain") or "course").strip().lower(),
        "rule_category": str(raw.get("rule_category") or _infer_rule_category(scope)).strip().lower(),
        "strength": str(raw.get("strength") or "soft").strip().lower(),
        "status": str(raw.get("status") or "draft").strip().lower(),
        "enabled": bool(raw.get("enabled", True)),
        "source": {
            "kind": str(source_raw.get("kind") or ("natural_language" if source_value else "manual")).strip().lower(),
            "text": source_value[:2_000],
        },
        "scope": scope,
        "effective_time": effective_time,
        "exceptions": exceptions,
        "constraint": constraint,
        "weight": _bounded_int(raw.get("weight", 300), 1, 100_000, 300),
        "solver_support": solver_support,
        "confirmation": confirmation,
        "provenance": {
            "parser": str(provenance_raw.get("parser") or parser or "manual").strip()[:80],
            "provider_id": str(provenance_raw.get("provider_id") or provider_id).strip()[:120],
            "model": str(provenance_raw.get("model") or model).strip()[:160],
            "generated_at": str(provenance_raw.get("generated_at") or now).strip()[:80],
        },
        "ai_used": bool(raw.get("ai_used", False)),
        "ai_note": str(raw.get("ai_note") or "").strip()[:1_000],
        "model_request_id": str(raw.get("model_request_id") or "").strip()[:160],
        "ai_modeling": _normalize_ai_modeling(raw.get("ai_modeling")),
        "created_at": str(raw.get("created_at") or now).strip()[:80],
        "updated_at": now,
    }
    validation = validate_rule_v2(normalized)
    normalized["validation"] = validation.as_dict()
    return normalized


def validate_rule_v2(rule: Mapping[str, Any]) -> RuleV2Validation:
    errors: list[str] = []
    warnings: list[str] = []
    if str(rule.get("schema_version") or "") != RULE_V2_SCHEMA_VERSION:
        errors.append(f"schema_version must be {RULE_V2_SCHEMA_VERSION}")
    if not _RULE_ID_RE.fullmatch(str(rule.get("id") or "")):
        errors.append("rule id contains unsupported characters or has an invalid length")
    if not str(rule.get("title") or "").strip():
        errors.append("rule title is required")
    if str(rule.get("policy_level") or "") not in RULE_V2_POLICY_LEVELS:
        errors.append("policy_level is unsupported")
    if str(rule.get("business_domain") or "") not in RULE_V2_BUSINESS_DOMAINS:
        errors.append("business_domain is unsupported")
    if str(rule.get("rule_category") or "") not in RULE_V2_RULE_CATEGORIES:
        errors.append("rule_category is unsupported")
    strength = str(rule.get("strength") or "")
    if strength not in RULE_V2_STRENGTHS:
        errors.append("strength is unsupported")
    status = str(rule.get("status") or "")
    if status not in RULE_V2_STATUSES:
        errors.append("status is unsupported")

    scope = rule.get("scope") if isinstance(rule.get("scope"), Mapping) else None
    if scope is None:
        errors.append("scope must be an object")
        scope = {}
    for key in ("campuses", "grades", "classes", "subjects", "teachers", "rooms"):
        values = scope.get(key)
        if not isinstance(values, list):
            errors.append(f"scope.{key} must be a list")
        elif len(values) > _MAX_LIST_ITEMS:
            errors.append(f"scope.{key} has too many values")

    effective = rule.get("effective_time") if isinstance(rule.get("effective_time"), Mapping) else None
    if effective is None:
        errors.append("effective_time must be an object")
        effective = {}
    if str(effective.get("mode") or "") not in RULE_V2_TIME_MODES:
        errors.append("effective_time.mode is unsupported")
    if str(effective.get("mode") or "") == "date_range" and (
        not str(effective.get("date_from") or "") or not str(effective.get("date_to") or "")
    ):
        errors.append("date_range rules require date_from and date_to")
    if str(effective.get("week_pattern") or "") not in RULE_V2_WEEK_PATTERNS:
        errors.append("effective_time.week_pattern is unsupported")
    if str(effective.get("week_pattern") or "") in {"a", "b", "odd", "even", "specific"}:
        warnings.append("当前求解底座只对 A/B 同时生效或整学期规则提供完整编译；该周次范围需要二次校验")
    for day in effective.get("days") if isinstance(effective.get("days"), list) else []:
        if str(day) not in _ALLOWED_DAYS:
            errors.append(f"unsupported weekday: {day}")

    exceptions = rule.get("exceptions")
    if not isinstance(exceptions, list):
        errors.append("exceptions must be a list")
        exceptions = []
    if len(exceptions) > _MAX_EXCEPTIONS:
        errors.append("too many exceptions")
    for index, item in enumerate(exceptions):
        if not isinstance(item, Mapping):
            errors.append(f"exceptions[{index}] must be an object")
            continue
        if str(item.get("mode") or "") not in {"exclude", "soften", "note"}:
            errors.append(f"exceptions[{index}].mode is unsupported")

    constraint = rule.get("constraint") if isinstance(rule.get("constraint"), Mapping) else None
    if constraint is None:
        errors.append("constraint must be an object")
        constraint = {}
    constraint_type = str(constraint.get("type") or "")
    if constraint_type not in RULE_V2_CONSTRAINT_TYPES:
        errors.append("constraint.type is unsupported")
    if not isinstance(constraint.get("params"), Mapping):
        errors.append("constraint.params must be an object")
    if constraint_type == "catalog_ref" and not str(constraint.get("catalog_id") or ""):
        errors.append("catalog_ref requires catalog_id")
    params = constraint.get("params") if isinstance(constraint.get("params"), Mapping) else {}
    if constraint_type == "teacher_unavailable":
        if not scope.get("teachers"):
            errors.append("teacher_unavailable requires scope.teachers")
        if not effective.get("days") and not effective.get("slots"):
            errors.append("teacher_unavailable requires at least one day or slot")
    if constraint_type == "prefer_period" and str(params.get("period") or "").lower() not in {
        "morning", "afternoon", "early", "first", "last",
    }:
        errors.append("prefer_period requires params.period in morning/afternoon/early/first/last")
    if constraint_type == "prefer_period" and strength == "hard":
        warnings.append("时间偏好设为硬规则可能导致无解；建议先使用软规则")
    if constraint_type == "max_daily_lessons":
        maximum = _bounded_int(params.get("max", 0), 0, 100, 0)
        if not 1 <= maximum <= 12:
            errors.append("max_daily_lessons requires params.max between 1 and 12")
        if not any(scope.get(key) for key in ("grades", "classes", "subjects", "teachers")):
            errors.append("max_daily_lessons requires a teacher, class, grade, or subject scope")

    support = rule.get("solver_support") if isinstance(rule.get("solver_support"), Mapping) else None
    if support is None:
        errors.append("solver_support must be an object")
        support = {}
    support_status = str(support.get("status") or "")
    if support_status not in RULE_V2_SUPPORT_STATUSES:
        errors.append("solver_support.status is unsupported")
    if support_status == "supported" and str(support.get("compiler") or "") != RULE_V2_COMPILER:
        errors.append("supported rules must use the allowlisted Rule V2 compiler")
    if support_status == "supported" and str(effective.get("mode") or "") != "project_term":
        errors.append("date_range rules are not fully supported by the current term solver")
    if support_status == "supported" and str(effective.get("week_pattern") or "") not in {"all", "ab"}:
        errors.append("the current solver only fully supports all-term or A/B-combined rules")
    if support_status == "supported" and (scope.get("campuses") or scope.get("rooms")):
        errors.append("campus and room scope require a solver data adapter before activation")
    if support_status == "supported" and strength == "advisory":
        errors.append("advisory rules cannot be marked as solver-supported")
    if support_status == "supported" and str(rule.get("business_domain") or "") == "roster":
        errors.append("roster rules require the roster Rule V2 compiler before activation")
    if support_status == "supported" and constraint_type == "max_daily_lessons" and any(
        isinstance(item, Mapping) and str(item.get("mode") or "") == "soften"
        for item in exceptions
    ):
        warnings.append("课时上限的软化例外按命中的整天处理，请在激活前复核")
    if support_status != "supported":
        warnings.append("该规则尚未获得完整求解支持，不能直接加入正式规则集")

    confirmation = rule.get("confirmation") if isinstance(rule.get("confirmation"), Mapping) else {}
    if status == "active" and (
        confirmation.get("required") is not True
        or confirmation.get("confirmed") is not True
        or support_status != "supported"
    ):
        errors.append("active rules require explicit confirmation and full solver support")

    if not any(scope.get(key) for key in ("campuses", "grades", "classes", "subjects", "teachers", "rooms")):
        warnings.append("作用范围为空时按全校处理，请在确认前复核")
    return RuleV2Validation(errors=tuple(dict.fromkeys(errors)), warnings=tuple(dict.fromkeys(warnings)))


def activate_rule_v2(rule: Mapping[str, Any], *, confirmed: bool, actor: str) -> dict[str, Any]:
    candidate = normalize_rule_v2(rule)
    validation = validate_rule_v2(candidate)
    if not validation.valid:
        raise ValueError("Rule V2 校验失败：" + "；".join(validation.errors))
    if not confirmed:
        raise ValueError("规则必须由教务人员明确确认")
    if candidate["solver_support"]["status"] != "supported":
        raise ValueError("当前规则尚未获得完整求解支持，不能加入正式规则集")
    candidate["status"] = "active"
    candidate["confirmation"] = {
        "required": True,
        "confirmed": True,
        "confirmed_by": str(actor or "web").strip() or "web",
        "confirmed_at": _utc_now(),
    }
    candidate["updated_at"] = _utc_now()
    candidate["validation"] = validate_rule_v2(candidate).as_dict()
    return candidate


def parse_rule_v2_local(
    text: str,
    *,
    known_teachers: Iterable[str] = (),
    known_subjects: Iterable[str] = (),
    known_classes: Iterable[str] = (),
    known_grades: Iterable[str] = (),
    slot_context: Mapping[str, Iterable[str]] | None = None,
) -> dict[str, Any]:
    """Parse the supported grammar against caller-owned entity and slot inventories.

    slot_context maps time expressions to concrete compiler labels, for example
    {"上午": ["上午1", "上午2"], "第3节": ["下午1"]}. Numbered whole-day
    aliases must be supplied explicitly; the parser never assumes a block size.
    Unconsumed text (including unknown entities) requires clarification.
    """
    source = str(text or "").strip()
    if not source:
        raise ValueError("自然语言规则不能为空")
    inventories = {
        "teachers": _teacher_candidates(known_teachers),
        "classes": list(known_classes),
        "grades": list(known_grades),
        "subjects": list(known_subjects),
    }
    day_pattern = r"(?:周[一二三四五六日天]|星期[一二三四五六日])"
    slot_pattern = r"(?:(?:上午|下午|早上|早自习)(?:第?\d+节)?|第\d+节)"
    if slot_context:
        configured_aliases = [str(key) for key in slot_context if str(key).strip()]
        if configured_aliases:
            aliases_pattern = "|".join(re.escape(alias) for alias in sorted(configured_aliases, key=len, reverse=True))
            slot_pattern = f"(?:{aliases_pattern}|{slot_pattern})"
    body = source.rstrip("。.!！").strip()
    exceptions = []
    exception_match = re.search(
        rf"[，,；;]\s*(?:但)?(?P<day>{day_pattern})(?P<slot>{slot_pattern})除外$", body,
    )
    time_bound = True
    if exception_match:
        exception_slots = _extract_slots(exception_match["slot"], slot_context=slot_context)
        time_bound = bool(exception_slots)
        exceptions = [{"id": "exception-1", "mode": "exclude",
                       "days": [_normalize_day(exception_match["day"])],
                       "slots": exception_slots, "note": "自然语言识别的例外"}]
        body = body[:exception_match.start()].strip()

    time_pattern = rf"(?P<day>{day_pattern})?\s*(?P<slot>{slot_pattern})?"
    ban_match = re.fullmatch(
        rf"(?P<scope>.+?){time_pattern}\s*(?:必须|绝对)?"
        r"(?:不能排课|不能排|不排课|不排|禁排|不能上课|不上课|禁止排课|不得排课)", body,
    )
    prefer_match = re.fullmatch(
        rf"(?P<scope>.+?)(?P<day>{day_pattern})?\s*"
        r"(?P<strength>尽量|优先|必须|一定要|只能)?\s*"
        r"(?:安排在|安排到|安排|排在|排到|排)\s*(?P<slot>上午|早上|下午|早自习)", body,
    )
    maximum_match = re.fullmatch(
        r"(?P<scope>.+?)每天(?:不超过|最多)\s*(?P<max>\d+)\s*节", body,
    )
    match = ban_match or prefer_match or maximum_match
    scope, scope_bound = _bind_scope(match["scope"] if match else "", inventories)
    teachers, classes, grades, subjects = (scope[key] for key in ("teachers", "classes", "grades", "subjects"))
    day = match.groupdict().get("day") if match else None
    days = [_normalize_day(day)] if day else []
    slot_expression = match.groupdict().get("slot") if match else None
    slots = _extract_slots(slot_expression or "", slot_context=slot_context)
    if slot_expression and not slots:
        time_bound = False

    raw: dict[str, Any] = {
        "id": _stable_rule_id(source),
        "title": _title_from_source(source),
        "description": source,
        "policy_level": "grade_subject" if grades or subjects else "special",
        "business_domain": "roster" if any(token in source for token in ("排班", "值班", "查寝", "值日")) else "course",
        "rule_category": "teacher" if teachers else "subject" if subjects else "basic",
        "strength": "soft" if prefer_match and prefer_match["strength"] in {"尽量", "优先"} else "hard",
        "status": "draft",
        "source": {"kind": "natural_language", "text": source},
        "scope": {"grades": grades, "classes": classes, "subjects": subjects, "teachers": teachers},
        "effective_time": {"mode": "project_term", "week_pattern": "all", "days": days},
        "exceptions": exceptions,
        "constraint": {"type": "", "params": {}},
        "solver_support": {"status": "unsupported", "message": "需要补充或人工选择规则类型"},
        "provenance": {"parser": "local.rule_v2"},
    }
    if ban_match and teachers:
        raw["effective_time"]["slots"] = slots
        raw["constraint"] = {"type": "teacher_unavailable", "params": {}}
    elif prefer_match:
        period = {"上午": "morning", "早上": "morning", "下午": "afternoon", "早自习": "early"}[prefer_match["slot"]]
        raw["constraint"] = {"type": "prefer_period", "params": {"period": period}}
    elif maximum_match:
        raw["constraint"] = {"type": "max_daily_lessons", "params": {"max": int(maximum_match["max"])}}
    if raw["constraint"]["type"] and scope_bound and time_bound:
        raw["solver_support"] = {
            "status": "supported",
            "compiler": RULE_V2_COMPILER,
            "message": "可由白天 Rule V2 编译器执行",
        }
    else:
        raw["solver_support"]["message"] = "请明确规则对象、适用范围和时段，并提供当前项目的对应数据"
    normalized = normalize_rule_v2(raw, source_text=source, parser="local.rule_v2")
    if normalized["solver_support"]["status"] != "supported" or not normalized["validation"]["valid"]:
        normalized["status"] = "needs_clarification"
        normalized["solver_support"] = {"status": "unsupported", "compiler": "", "message": "规则尚有未明确或不支持的范围、时段或条件，请补充后再确认"}
        normalized["validation"] = validate_rule_v2(normalized).as_dict()
    return normalized


def catalog_rule_to_v2(rule: Mapping[str, Any], *, group_id: str, group_title: str) -> dict[str, Any]:
    mode = str(rule.get("mode") or "").lower()
    strength = "soft" if "软" in mode or mode == "soft" else "hard"
    raw = {
        "id": f"catalog.{str(rule.get('id') or _stable_rule_id(str(rule)))}",
        "title": str(rule.get("title") or rule.get("label") or "未命名规则"),
        "description": str(rule.get("explanation") or rule.get("description") or ""),
        "policy_level": "special" if group_id in {"teacher_personal", "temporary"} else "schoolwide",
        "business_domain": str(rule.get("business_domain") or ("roster" if group_id == "duty" else "course")),
        "rule_category": str(rule.get("rule_category") or ("teacher" if group_id == "teacher_personal" else "basic")),
        "strength": strength,
        "status": "active" if bool(rule.get("enabled", True)) else "disabled",
        "enabled": bool(rule.get("enabled", True)),
        "source": {"kind": "catalog", "text": group_title},
        "scope": {"teachers": _clean_string_list(rule.get("targets"))},
        "effective_time": {"mode": "project_term", "week_pattern": "all"},
        "constraint": {"type": "catalog_ref", "catalog_id": str(rule.get("id") or ""), "params": {}},
        "solver_support": {
            "status": "supported",
            "compiler": RULE_V2_COMPILER,
            "message": "由现有约束目录适配器执行",
        },
        "confirmation": {
            "required": True,
            "confirmed": True,
            "confirmed_by": "catalog",
            "confirmed_at": _utc_now(),
        },
        "provenance": {"parser": "catalog.adapter"},
    }
    return normalize_rule_v2(raw)


def _infer_rule_category(scope: Mapping[str, Any]) -> str:
    if scope.get("teachers"):
        return "teacher"
    if scope.get("subjects"):
        return "subject"
    return "basic"


def _parse_exceptions(source: str) -> list[dict[str, Any]]:
    exceptions: list[dict[str, Any]] = []
    match = re.search(r"(周[一二三四五六日天]|星期[一二三四五六日])\s*第?\s*(\d+)\s*节[^，。；;]{0,12}(?:除外|例外|不受)", source)
    if match:
        exceptions.append(
            {
                "id": "exception-1",
                "mode": "exclude",
                "days": [_normalize_day(match.group(1))],
                "slots": [f"第{int(match.group(2))}节"],
                "note": "自然语言识别的例外",
            }
        )
    return exceptions


def _extract_slots(source: str, *, slot_context: Mapping[str, Iterable[str]] | None = None) -> list[str]:
    """Resolve one complete time expression; emit only block-qualified labels."""
    if not slot_context:
        return []
    expression = source.strip()
    aliases = [expression]
    if expression == "早上":
        aliases.append("上午")
    elif expression == "上午":
        aliases.append("早上")
    values: Iterable[str] = ()
    for alias in aliases:
        if alias in slot_context:
            values = slot_context[alias]
            break
    if isinstance(values, str):
        return []
    slots = list(dict.fromkeys(str(value).strip() for value in values))
    if not slots or any(not re.fullmatch(r"[^\s]{1,80}[1-9]\d*|早自习", value) for value in slots):
        return []
    normalized_expression = expression.replace("早上", "上午")
    block = re.fullmatch(r"上午|下午|早自习", normalized_expression)
    if block and any(not value.startswith(normalized_expression) for value in slots):
        return []
    return slots


def _known_teacher_hits(source: str, known_teachers: Iterable[str]) -> list[str]:
    return _known_entity_hits(source, _teacher_candidates(known_teachers))


def _teacher_candidates(known_teachers: Iterable[str]) -> list[str]:
    return [
        str(value).strip()
        for value in known_teachers
        if 2 <= len(str(value).strip()) <= 20
        and not re.fullmatch(r"\d+|.+班", str(value).strip())
    ]


def _known_entity_hits(source: str, values: Iterable[str]) -> list[str]:
    scope, bound = _bind_scope(source, {"entities": values})
    return scope["entities"] if bound else []


def _bind_scope(source: str, inventories: Mapping[str, Iterable[str]]) -> tuple[dict[str, list[str]], bool]:
    """Consume the whole scope with exact inventory tokens, longest first.

    A partial match is discarded, never widened to a known subset or the school.
    Names shared between entity kinds require the caller to disambiguate.
    """
    result: dict[str, list[str]] = {key: [] for key in inventories}
    candidates: dict[str, list[str]] = {}
    for key, values in inventories.items():
        for value in values:
            name = str(value).strip()
            if 1 <= len(name) <= 120:
                candidates.setdefault(name, [])
                if key not in candidates[name]:
                    candidates[name].append(key)
    remaining = source.strip()
    while remaining:
        matches = [name for name in candidates if remaining.startswith(name)]
        if not matches:
            return {key: [] for key in inventories}, False
        name = max(matches, key=len)
        kinds = candidates[name]
        if len(kinds) != 1:
            return {key: [] for key in inventories}, False
        if name not in result[kinds[0]]:
            result[kinds[0]].append(name)
        remaining = remaining[len(name):]
        remaining = re.sub(r"^(?:\s+|[、,，]|和|与|及|的)+", "", remaining)
    return result, any(result.values())


def _title_from_source(source: str) -> str:
    text = re.sub(r"\s+", " ", str(source or "").strip())
    return (text[:38] + "…") if len(text) > 38 else (text or "未命名规则")


def _stable_rule_id(source: str) -> str:
    return "rule.v2." + hashlib.sha256(str(source).encode("utf-8")).hexdigest()[:16]


def _normalize_day(value: Any) -> str:
    text = str(value or "").strip()
    return _DAY_ALIASES.get(text, text if text in _ALLOWED_DAYS else "")


def _clean_string_list(value: Any, *, maximum: int = _MAX_LIST_ITEMS) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        candidates = re.split(r"[、,，/\n]+", value)
    elif isinstance(value, (list, tuple, set)):
        candidates = list(value)
    else:
        return []
    result: list[str] = []
    for item in candidates:
        text = str(item or "").strip()
        if text and len(text) <= 120 and text not in result:
            result.append(text)
        if len(result) >= maximum:
            break
    return result


def _clean_int_list(value: Any, *, minimum: int, maximum: int) -> list[int]:
    values = value if isinstance(value, (list, tuple, set)) else []
    result: list[int] = []
    for item in values:
        try:
            number = int(item)
        except (TypeError, ValueError):
            continue
        if minimum <= number <= maximum and number not in result:
            result.append(number)
    return result


def _json_safe_params(value: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, item in value.items():
        clean_key = str(key or "").strip()
        if not clean_key or len(clean_key) > 80:
            continue
        if isinstance(item, bool) or item is None:
            result[clean_key] = item
        elif isinstance(item, (int, float)):
            result[clean_key] = item
        elif isinstance(item, str):
            result[clean_key] = item[:300]
        elif isinstance(item, (list, tuple)):
            result[clean_key] = [str(value)[:120] for value in item[:100]]
    return result


def _normalize_ai_modeling(value: Any) -> dict[str, Any]:
    raw = value if isinstance(value, Mapping) else {}
    list_fields = {
        "interpreted_requirements": ("detail", "title"),
        "constraint_mapping": ("requirement", "rule_v2_type", "strength", "solver_effect", "support_status"),
        "limitations": ("title", "detail", "impact", "recommendation"),
        "recommendations": ("title", "action", "reason"),
        "blocking_items": ("title", "limitation", "solution"),
    }
    normalized: dict[str, Any] = {
        "participated": bool(raw.get("participated", False)),
        "status": str(raw.get("status") or "").strip()[:40],
    }
    for key, fields in list_fields.items():
        rows = raw.get(key) if isinstance(raw.get(key), list) else []
        cleaned: list[Any] = []
        for item in rows[:12]:
            if isinstance(item, Mapping):
                row = {field: str(item.get(field) or "").strip()[:500] for field in fields}
                if any(row.values()):
                    cleaned.append(row)
            else:
                text = str(item or "").strip()[:500]
                if text:
                    cleaned.append(text)
        normalized[key] = cleaned
    handoff = raw.get("solver_handoff") if isinstance(raw.get("solver_handoff"), Mapping) else {}
    normalized["solver_handoff"] = {
        "status": str(handoff.get("status") or "").strip()[:40],
        "compiler": str(handoff.get("compiler") or "").strip()[:120],
        "requires_user_confirmation": True,
    }
    return normalized


def _bounded_int(value: Any, minimum: int, maximum: int, default: int) -> int:
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, number))


def _support_message(status: str) -> str:
    return {
        "supported": "可由白天 Rule V2 编译器执行",
        "partial": "部分语义可执行，保存前需要处理未支持部分",
        "unsupported": "尚未映射到求解器，只能保留为需求草稿",
    }.get(status, "尚未完成求解支持检查")


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
