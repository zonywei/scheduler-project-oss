# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable


@dataclass(frozen=True)
class RuleMeta:
    id: str
    name_cn: str
    description: str
    config_keys: tuple[str, ...] = field(default_factory=tuple)
    default_weight: str = ""
    mode: str = "soft"
    source_module: str = ""


_REGISTRY: dict[str, RuleMeta] = {}


def register_rule_meta(meta: RuleMeta, *, overwrite: bool = False) -> RuleMeta:
    rid = str(meta.id or "").strip()
    if not rid:
        raise ValueError("RuleMeta.id is required")
    if rid in _REGISTRY and not overwrite:
        return _REGISTRY[rid]
    _REGISTRY[rid] = meta
    return meta


def ensure_rule_meta(
    rule_id: str,
    *,
    name_cn: str = "",
    description: str = "",
    config_keys: Iterable[str] | None = None,
    default_weight: str = "",
    mode: str = "soft",
    source_module: str = "",
) -> RuleMeta:
    rid = str(rule_id or "").strip()
    if not rid:
        raise ValueError("rule_id is required")
    exists = _REGISTRY.get(rid)
    if exists is not None:
        return exists
    name = str(name_cn or rid)
    desc = str(description or name)
    keys = tuple(str(k).strip() for k in (config_keys or []) if str(k).strip())
    return register_rule_meta(
        RuleMeta(
            id=rid,
            name_cn=name,
            description=desc,
            config_keys=keys,
            default_weight=str(default_weight or ""),
            mode=str(mode or "soft"),
            source_module=str(source_module or ""),
        )
    )


def get_rule_meta(rule_id: str) -> RuleMeta | None:
    return _REGISTRY.get(str(rule_id or "").strip())


def all_rule_meta() -> list[RuleMeta]:
    return list(_REGISTRY.values())


def rule_meta_map() -> dict[str, RuleMeta]:
    return dict(_REGISTRY)


def validate_rule_ids(rule_ids: Iterable[str], *, context: str = "") -> None:
    missing = sorted(
        {
            str(rid).strip()
            for rid in rule_ids
            if str(rid).strip() and str(rid).strip() not in _REGISTRY
        }
    )
    if missing:
        prefix = f"[{context}] " if context else ""
        raise RuntimeError(
            f"{prefix}存在未注册 RuleMeta 的规则: {', '.join(missing)}"
        )
