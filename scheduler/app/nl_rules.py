# -*- coding: utf-8 -*-
from __future__ import annotations

import hashlib
import re
from typing import Any

from scheduler.app.model_gateway import (
    JsonModelClient,
    ModelProviderConfig,
    OpenAICompatibleJsonClient,
    pseudonymize_teacher_context,
    replace_model_tokens,
)
from scheduler.domain.rule_drafts import build_rule_draft, validate_rule_draft


DAY_ALIASES = {
    "周一": "星期一",
    "星期一": "星期一",
    "周二": "星期二",
    "星期二": "星期二",
    "周三": "星期三",
    "星期三": "星期三",
    "周四": "星期四",
    "星期四": "星期四",
    "周五": "星期五",
    "星期五": "星期五",
    "周六": "星期六",
    "星期六": "星期六",
    "周日": "星期日",
    "星期日": "星期日",
    "周天": "星期日",
}

SLOT_PATTERNS = [
    ("早自习", "早自习"),
    ("上午1", "上午1"),
    ("上午2", "上午2"),
    ("上午3", "上午3"),
    ("上午4", "上午4"),
    ("下午1", "下午1"),
    ("下午2", "下午2"),
    ("下午3", "下午3"),
    ("下午4", "下午4"),
    ("晚自习1", "晚自习1"),
    ("晚自习2", "晚自习2"),
    ("晚自习", "晚自习"),
]


def _stable_id(text: str) -> str:
    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:10]
    return f"tmp.nl.{digest}"


def _extract_day(text: str) -> str | None:
    for alias, day in DAY_ALIASES.items():
        if alias in text:
            return day
    return None


def _extract_slot(text: str) -> str | None:
    compact = re.sub(r"\s+", "", text)
    for pattern, slot in SLOT_PATTERNS:
        if pattern in compact:
            return slot
    return None


def _extract_targets(text: str, known_teachers: list[str] | None = None) -> list[str]:
    teachers = [str(x).strip() for x in (known_teachers or []) if str(x).strip()]
    hits = [name for name in teachers if name and name in text]
    if hits:
        return sorted(set(hits))

    quoted = re.findall(r"[“\"']([^“\"']{1,12})[”\"']", text)
    if quoted:
        return sorted({x.strip() for x in quoted if x.strip()})

    m = re.search(r"([\u4e00-\u9fa5A-Za-z0-9_、,，/ ]{1,40}?)(?:老师|教师)?(?:不排|禁排|不能|必须|需要|安排)", text)
    if not m:
        return []
    raw = m.group(1)
    for token in DAY_ALIASES:
        raw = raw.replace(token, "")
    for pattern, _slot in SLOT_PATTERNS:
        raw = raw.replace(pattern, "")
    parts = re.split(r"[、,，/ ]+", raw)
    return sorted({p.strip() for p in parts if 1 <= len(p.strip()) <= 12})


def _is_require(text: str) -> bool:
    return any(token in text for token in ("必须", "需要", "固定", "安排到", "只能"))


def _is_ban(text: str) -> bool:
    return any(token in text for token in ("不排", "禁排", "不能", "禁止", "避免"))


def parse_natural_language_rule(text: str, *, known_teachers: list[str] | None = None) -> dict[str, Any]:
    cleaned = str(text or "").strip()
    if not cleaned:
        raise ValueError("自然语言指令不能为空")
    day = _extract_day(cleaned)
    slot = _extract_slot(cleaned)
    targets = _extract_targets(cleaned, known_teachers)
    action = "require" if _is_require(cleaned) and not _is_ban(cleaned) else "ban"
    scope = "night" if slot and slot.startswith("晚自习") or "晚自习" in cleaned else "day"

    patches: list[dict[str, Any]] = []
    solver_supported = False
    if action == "ban" and scope == "night" and day and targets:
        patches.append(
            {
                "target": "rules",
                "path": ["hard_bans", "teacher_day_bans", day],
                "operation": "append_unique",
                "values": targets,
            }
        )
        solver_supported = True
    elif action == "ban" and scope == "day" and slot == "上午1" and targets:
        patches.append(
            {
                "target": "rules",
                "path": ["personalized_constraints", "custom_no_am1_teachers"],
                "operation": "append_unique",
                "values": targets,
            }
        )
        patches.append(
            {
                "target": "rules",
                "path": ["personalized_constraints", "enable_custom_no_am1_teachers"],
                "operation": "set",
                "value": True,
            }
        )
        solver_supported = True

    raw_rule = {
        "id": _stable_id(cleaned),
        "action": action,
        "scope": scope,
        "target_teachers": targets,
        "day": day,
        "slot": slot,
        "solver_supported": solver_supported,
        "patches": patches,
        "description": _describe(action, scope, targets, day, slot, solver_supported),
    }
    return build_rule_draft(
        raw_rule,
        source_text=cleaned,
        parser="local",
        known_targets=known_teachers or (),
        default_confidence=0.98 if solver_supported else 0.35,
    )


def parse_rule_with_ai_settings(
    text: str,
    *,
    known_teachers: list[str] | None = None,
    settings: dict[str, Any] | None = None,
    client: JsonModelClient | None = None,
) -> dict[str, Any]:
    cfg = settings or {}
    if not bool(cfg.get("enabled")):
        rule = parse_natural_language_rule(text, known_teachers=known_teachers)
        rule["ai_used"] = False
        rule["ai_note"] = "AI 助手未启用，已使用本地规则解析。"
        return rule
    provider_list = cfg.get("providers") if isinstance(cfg.get("providers"), list) else []
    has_routed_provider = any(
        isinstance(item, dict)
        and item.get("enabled", True) is not False
        and str(item.get("base_url") or "").strip()
        and str(item.get("model") or "").strip()
        for item in provider_list
    )
    has_legacy_provider = bool(str(cfg.get("base_url") or "").strip() and str(cfg.get("model") or "").strip())
    if client is None and not has_legacy_provider and not has_routed_provider:
        rule = parse_natural_language_rule(text, known_teachers=known_teachers)
        rule["ai_used"] = False
        rule["ai_note"] = "AI 接口地址或模型未配置，已使用本地规则解析。"
        return rule

    prompt = str(cfg.get("prompt_template") or "").strip() or (
        "你是排课规则配置助手。请把用户自然语言转成 JSON，字段必须包括 "
        "id, source, action, scope, target_teachers, day, slot, solver_supported, patches, status, description。"
        "patches 支持 set 或 append_unique，target 固定为 rules。只输出 JSON。"
    )
    try:
        teacher_names = [str(value).strip() for value in (known_teachers or []) if str(value).strip()]
        model_text, model_teachers, teacher_restore_map = pseudonymize_teacher_context(
            str(text),
            teacher_names,
        )
        gateway = client
        if gateway is None:
            config = ModelProviderConfig.from_settings(cfg)
            gateway = OpenAICompatibleJsonClient(config)
        result = gateway.complete_json(
            system_prompt=prompt,
            user_payload={"text": model_text, "known_teachers": model_teachers},
        )
        raw_rule = dict(replace_model_tokens(result.value, teacher_restore_map))
        raw_rule["id"] = _stable_id(str(text))
        rule = build_rule_draft(
            raw_rule,
            source_text=str(text),
            parser="model",
            provider_id=result.provider_id,
            model=result.model,
            known_targets=known_teachers or (),
            default_confidence=0.7,
        )
        validation = validate_rule_draft(rule, known_targets=known_teachers or ())
        if not validation.valid:
            raise ValueError("AI 规则草案未通过安全校验：" + "；".join(validation.errors))
        rule["ai_used"] = True
        rule["model_request_id"] = result.request_id
        if result.usage:
            rule["model_usage"] = result.usage
        return rule
    except Exception as exc:
        rule = parse_natural_language_rule(text, known_teachers=known_teachers)
        rule["ai_used"] = False
        rule["ai_note"] = f"AI 解析失败，已使用本地规则解析：{exc}"
        return rule


def _describe(action: str, scope: str, targets: list[str], day: str | None, slot: str | None, supported: bool) -> str:
    verb = "必须安排" if action == "require" else "禁排"
    names = "、".join(targets) if targets else "未识别教师"
    where = " ".join(x for x in [day, slot] if x)
    suffix = "可映射到求解配置" if supported else "暂存为待人工确认规则"
    return f"{names} {where} {verb}（{scope}，{suffix}）"


def apply_patch_to_mapping(target: dict[str, Any], patch: dict[str, Any], *, reverse: bool = False) -> None:
    path = [str(x) for x in patch.get("path", [])]
    if not path:
        return
    cur = target
    for part in path[:-1]:
        cur = cur.setdefault(part, {})
    leaf = path[-1]
    op = str(patch.get("operation") or "")
    if op == "set":
        cur[leaf] = None if reverse else patch.get("value")
    elif op == "append_unique":
        values = [str(x).strip() for x in patch.get("values", []) if str(x).strip()]
        current = cur.get(leaf)
        if not isinstance(current, list):
            current = []
        if reverse:
            cur[leaf] = [x for x in current if x not in set(values)]
        else:
            seen = set(str(x) for x in current)
            for value in values:
                if value not in seen:
                    current.append(value)
                    seen.add(value)
            cur[leaf] = current
