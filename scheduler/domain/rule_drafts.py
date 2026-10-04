# -*- coding: utf-8 -*-
"""Versioned, validated rule drafts shared by UI, AI adapters, and config loading."""
from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping


RULE_DRAFT_SCHEMA_VERSION = "scheduler.rule-draft.v1"
NATURAL_LANGUAGE_RULE_KIND = "natural_language_rule"
RULE_DRAFT_STATUSES = {"draft", "active", "rejected"}
ALLOWED_DAYS = {f"星期{value}" for value in "一二三四五六日"}
_RULE_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_MAX_SOURCE_CHARS = 2_000
_MAX_PATCHES = 16
_MAX_TARGETS = 200


@dataclass(frozen=True)
class RuleDraftValidation:
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


def build_rule_draft(
    raw_rule: Mapping[str, Any],
    *,
    source_text: str,
    parser: str,
    provider_id: str = "",
    model: str = "",
    known_targets: Iterable[str] = (),
    default_confidence: float = 0.5,
) -> dict[str, Any]:
    raw = copy.deepcopy(dict(raw_rule))
    source = str(source_text or "").strip()
    generated_at = _utc_now()
    draft: dict[str, Any] = {
        **raw,
        "schema_version": RULE_DRAFT_SCHEMA_VERSION,
        "id": str(raw.get("id") or "").strip(),
        "source": source,
        "created_at": generated_at,
        "status": "draft",
        "target_teachers": _clean_string_list(raw.get("target_teachers")),
        "patches": copy.deepcopy(raw.get("patches")) if isinstance(raw.get("patches"), list) else [],
        "solver_supported": bool(raw.get("solver_supported", False)),
        "confidence": _normalized_confidence(raw.get("confidence"), default_confidence),
        "provenance": {
            "parser": str(parser or "unknown").strip() or "unknown",
            "provider_id": str(provider_id or "").strip(),
            "model": str(model or "").strip(),
            "generated_at": generated_at,
        },
        "confirmation": {
            "required": True,
            "confirmed": False,
        },
    }
    validation = validate_rule_draft(draft, known_targets=known_targets)
    draft["validation"] = validation.as_dict()
    return draft


def validate_rule_draft(
    rule: Mapping[str, Any],
    *,
    known_targets: Iterable[str] = (),
) -> RuleDraftValidation:
    errors: list[str] = []
    warnings: list[str] = []

    if str(rule.get("schema_version") or "") != RULE_DRAFT_SCHEMA_VERSION:
        errors.append(f"schema_version must be {RULE_DRAFT_SCHEMA_VERSION!r}")
    rule_id = str(rule.get("id") or "").strip()
    if not _RULE_ID_RE.fullmatch(rule_id):
        errors.append("rule id contains unsupported characters or has an invalid length")
    source = str(rule.get("source") or "").strip()
    if not source or len(source) > _MAX_SOURCE_CHARS:
        errors.append(f"rule source must contain 1-{_MAX_SOURCE_CHARS} characters")
    if str(rule.get("status") or "") not in RULE_DRAFT_STATUSES:
        errors.append("rule status must be draft, active, or rejected")
    action = str(rule.get("action") or "")
    scope = str(rule.get("scope") or "")
    status = str(rule.get("status") or "")
    if action not in {"ban", "require"}:
        errors.append("rule action must be ban or require")
    if scope not in {"day", "night"}:
        errors.append("rule scope must be day or night")

    confirmation = rule.get("confirmation")
    if status == "active" and (
        not isinstance(confirmation, dict)
        or confirmation.get("required") is not True
        or confirmation.get("confirmed") is not True
    ):
        errors.append("active rules must contain explicit user confirmation")

    day = rule.get("day")
    if day is not None and str(day) not in ALLOWED_DAYS:
        errors.append("rule day is not a supported weekday")
    slot = rule.get("slot")
    if slot is not None and (not str(slot).strip() or len(str(slot)) > 40):
        errors.append("rule slot is invalid")

    targets = _clean_string_list(rule.get("target_teachers"))
    if len(targets) > _MAX_TARGETS:
        errors.append(f"rule contains more than {_MAX_TARGETS} target teachers")
    if not targets:
        warnings.append("未识别到规则目标，应用前需要补充教师")
    known = {str(value).strip() for value in known_targets if str(value).strip()}
    unknown = sorted(set(targets) - known) if known else []
    if unknown:
        warnings.append("以下目标未出现在当前基础数据中：" + "、".join(unknown))

    patches = rule.get("patches")
    if not isinstance(patches, list):
        errors.append("rule patches must be a list")
        patches = []
    if len(patches) > _MAX_PATCHES:
        errors.append(f"rule contains more than {_MAX_PATCHES} patches")
    for index, patch in enumerate(patches):
        if not isinstance(patch, dict):
            errors.append(f"patch[{index}] must be an object")
            continue
        patch_errors = _validate_patch(
            patch,
            targets=set(targets),
            action=action,
            scope=scope,
            day=str(day) if day is not None else None,
            slot=str(slot) if slot is not None else None,
        )
        errors.extend(f"patch[{index}]: {message}" for message in patch_errors)

    patch_paths = {
        tuple(patch.get("path") or ())
        for patch in patches
        if isinstance(patch, dict) and isinstance(patch.get("path"), list)
    }
    enable_no_am1_path = ("personalized_constraints", "enable_custom_no_am1_teachers")
    teacher_no_am1_path = ("personalized_constraints", "custom_no_am1_teachers")
    if enable_no_am1_path in patch_paths and teacher_no_am1_path not in patch_paths:
        errors.append("enabling custom no-AM1 rules requires a target-teacher patch in the same draft")

    solver_supported = bool(rule.get("solver_supported", False))
    if solver_supported and not targets:
        errors.append("solver_supported rules must declare at least one target teacher")
    if solver_supported and not patches:
        errors.append("solver_supported rules must contain at least one allowlisted patch")
    if not solver_supported:
        warnings.append("该草案尚未映射到求解器，只能保留，不能加入正式求解")

    return RuleDraftValidation(errors=tuple(errors), warnings=tuple(dict.fromkeys(warnings)))


def activate_rule_draft(
    rule: Mapping[str, Any],
    *,
    confirmed: bool,
    actor: str,
    known_targets: Iterable[str] = (),
) -> dict[str, Any]:
    validation = validate_rule_draft(rule, known_targets=known_targets)
    if not validation.valid:
        raise ValueError("规则草案校验失败：" + "；".join(validation.errors))
    if not confirmed:
        raise ValueError("规则草案必须由用户明确确认后才能加入求解")
    if not bool(rule.get("solver_supported")) or not rule.get("patches"):
        raise ValueError("该规则草案尚未映射到求解器，不能加入正式求解")

    activated = copy.deepcopy(dict(rule))
    activated["kind"] = NATURAL_LANGUAGE_RULE_KIND
    activated["status"] = "active"
    activated["validation"] = validation.as_dict()
    activated["confirmation"] = {
        "required": True,
        "confirmed": True,
        "confirmed_by": str(actor or "web").strip() or "web",
        "confirmed_at": _utc_now(),
    }
    return activated


def materialize_active_rule_drafts(rules: Mapping[str, Any]) -> dict[str, Any]:
    """Overlay confirmed natural-language rules without mutating stored base overrides."""
    materialized = copy.deepcopy(dict(rules))
    temporary = materialized.get("temporary_rules")
    active = temporary.get("active") if isinstance(temporary, dict) else None
    if not isinstance(active, list):
        return materialized

    for item in active:
        if not isinstance(item, dict):
            continue
        if str(item.get("kind") or "") != NATURAL_LANGUAGE_RULE_KIND:
            continue
        validation = validate_rule_draft(item)
        if str(item.get("status") or "") != "active" or not validation.valid or not item.get("solver_supported"):
            continue
        candidate = copy.deepcopy(materialized)
        try:
            for patch in item.get("patches") or []:
                _apply_allowlisted_patch(candidate, patch)
        except (TypeError, ValueError):
            continue
        materialized = candidate
    return materialized


def _validate_patch(
    patch: Mapping[str, Any],
    *,
    targets: set[str],
    action: str,
    scope: str,
    day: str | None,
    slot: str | None,
) -> tuple[str, ...]:
    errors: list[str] = []
    if str(patch.get("target") or "") != "rules":
        errors.append("target must be rules")
    path_value = patch.get("path")
    if not isinstance(path_value, list) or not all(isinstance(item, str) and item for item in path_value):
        return tuple(errors + ["path must be a non-empty string list"])
    path = tuple(path_value)
    operation = str(patch.get("operation") or "")

    if path == ("personalized_constraints", "enable_custom_no_am1_teachers"):
        if operation != "set" or patch.get("value") is not True:
            errors.append("this path only allows set=true")
        if action != "ban" or scope != "day" or slot != "上午1":
            errors.append("this path requires a daytime AM1 ban rule")
        return tuple(errors)

    if path == ("personalized_constraints", "custom_no_am1_teachers"):
        errors.extend(_validate_append_unique(patch, targets=targets))
        if action != "ban" or scope != "day" or slot != "上午1":
            errors.append("this path requires a daytime AM1 ban rule")
        return tuple(errors)

    if len(path) == 3 and path[:2] == ("hard_bans", "teacher_day_bans") and path[2] in ALLOWED_DAYS:
        errors.extend(_validate_append_unique(patch, targets=targets))
        if action != "ban" or scope != "night":
            errors.append("this path requires a night ban rule")
        if day != path[2]:
            errors.append("patch weekday must match the rule weekday")
        return tuple(errors)

    errors.append("path is not in the server allowlist")
    return tuple(errors)


def _validate_append_unique(patch: Mapping[str, Any], *, targets: set[str]) -> tuple[str, ...]:
    errors: list[str] = []
    if str(patch.get("operation") or "") != "append_unique":
        errors.append("this path only allows append_unique")
    values = _clean_string_list(patch.get("values"))
    if not values:
        errors.append("append_unique values must not be empty")
    if set(values) - targets:
        errors.append("patch values must be declared in target_teachers")
    return tuple(errors)


def _clean_string_list(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = str(item or "").strip()
        if text and len(text) <= 80 and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _apply_allowlisted_patch(target: dict[str, Any], patch: Mapping[str, Any]) -> None:
    path = [str(part) for part in patch.get("path") or []]
    if not path:
        raise ValueError("patch path is empty")
    current: dict[str, Any] = target
    for part in path[:-1]:
        existing = current.get(part)
        if existing is None:
            current[part] = {}
        elif not isinstance(existing, dict):
            raise ValueError("patch parent is not an object")
        current = current[part]

    leaf = path[-1]
    operation = str(patch.get("operation") or "")
    if operation == "set":
        current[leaf] = copy.deepcopy(patch.get("value"))
        return
    if operation != "append_unique":
        raise ValueError("unsupported patch operation")
    existing_values = current.get(leaf, [])
    if not isinstance(existing_values, list):
        raise ValueError("append_unique target is not a list")
    merged = copy.deepcopy(existing_values)
    seen = {str(value) for value in merged}
    for value in _clean_string_list(patch.get("values")):
        if value not in seen:
            merged.append(value)
            seen.add(value)
    current[leaf] = merged


def _normalized_confidence(value: Any, default_value: float) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        result = float(default_value)
    return round(min(1.0, max(0.0, result)), 3)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
