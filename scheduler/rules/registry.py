# -*- coding: utf-8 -*-
"""Audit-only rule registry.

The scheduler still executes constraints through explicit solver call sites.
This registry resolves effective enabled/mode/weight metadata for snapshots,
trace rows, and migration audits; it does not decide whether a constraint
function is called during a solve.
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Any, Callable, Iterable

from scheduler.rules.spec import EffectiveRule, RuleSpec


class RuleRegistry:
    """Registry of rule metadata used for audit snapshots, not execution gating."""

    def __init__(self) -> None:
        self._items: dict[str, RuleSpec] = {}

    def register(self, spec: RuleSpec, *, overwrite: bool = False) -> RuleSpec:
        rid = str(spec.rule_id or "").strip()
        if not rid:
            raise ValueError("rule_id is required")
        if rid in self._items and not overwrite:
            return self._items[rid]
        self._items[rid] = spec
        return spec

    def get(self, rule_id: str) -> RuleSpec | None:
        return self._items.get(str(rule_id or "").strip())

    def list(self) -> list[RuleSpec]:
        return list(self._items.values())

    def items(self) -> Iterable[tuple[str, RuleSpec]]:
        return self._items.items()

    def __len__(self) -> int:
        return len(self._items)


def _get_by_path(payload: dict[str, Any], dotted_path: str | None) -> Any:
    if not dotted_path:
        return None
    cur: Any = payload
    for part in str(dotted_path).split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur.get(part)
    return cur


def _coerce_mode(value: Any, default_mode: str) -> str:
    if value is None:
        return str(default_mode)
    mode = str(value).strip().lower()
    return mode if mode in {"hard", "soft"} else str(default_mode)


def _coerce_enabled(value: Any, default_value: bool = True) -> bool:
    if value is None:
        return bool(default_value)
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return bool(value)


def resolve_effective_rule(spec: RuleSpec, effective_cfg: dict[str, Any]) -> EffectiveRule:
    enabled_raw = _get_by_path(effective_cfg, spec.enabled_path)
    mode_raw = _get_by_path(effective_cfg, spec.mode_path)
    weight_raw = _get_by_path(effective_cfg, spec.weight_path)
    enabled = _coerce_enabled(enabled_raw, True)
    mode = _coerce_mode(mode_raw, spec.default_mode)
    weight = spec.default_weight if weight_raw is None else weight_raw
    fn_name = ""
    if callable(spec.apply_fn):
        fn_name = getattr(spec.apply_fn, "__name__", str(spec.apply_fn))
    elif spec.apply_fn_ref:
        fn_name = str(spec.apply_fn_ref)
    return EffectiveRule(
        rule_id=spec.rule_id,
        name=spec.name,
        category_path=spec.category_path,
        stage=spec.stage,
        order=int(spec.order),
        tags=tuple(spec.tags),
        config_key=spec.config_key,
        enabled=enabled,
        mode=mode,
        weight=weight,
        explanation_template=spec.explanation_template,
        apply_fn_name=fn_name,
        enabled_path=spec.enabled_path,
        mode_path=spec.mode_path,
        weight_path=spec.weight_path,
    )


def _rule_matches_mode(spec: RuleSpec, mode: str) -> bool:
    tags = {str(x).strip().lower() for x in spec.tags}
    target = str(mode or "").strip().lower()
    if not tags:
        return True
    return target in tags or "shared" in tags or "all" in tags


def enumerate_effective_rules(
    registry: RuleRegistry,
    effective_cfg: dict[str, Any],
    *,
    mode: str | None = None,
    only_enabled: bool = False,
) -> list[EffectiveRule]:
    out: list[EffectiveRule] = []
    for spec in registry.list():
        if mode is not None and not _rule_matches_mode(spec, mode):
            continue
        state = resolve_effective_rule(spec, effective_cfg)
        if only_enabled and not state.enabled:
            continue
        out.append(state)
    out.sort(key=lambda x: (str(x.stage), int(x.order), x.rule_id))
    return out


def dump_effective_rules(
    registry: RuleRegistry,
    effective_cfg: dict[str, Any],
    *,
    mode: str | None = None,
    only_enabled: bool = False,
) -> list[dict[str, Any]]:
    rows = enumerate_effective_rules(
        registry,
        effective_cfg,
        mode=mode,
        only_enabled=only_enabled,
    )
    return [asdict(x) for x in rows]


def select_enabled_rules_for_audit(
    registry: RuleRegistry,
    effective_cfg: dict[str, Any],
    *,
    mode: str | None,
    stage: str | None,
    invoke: Callable[[EffectiveRule], Any],
) -> list[EffectiveRule]:
    """Select enabled metadata rows for audit tooling.

    ``invoke`` is a caller-supplied audit callback. This helper deliberately
    does not call solver constraint functions and does not control runtime
    enablement; solver modules keep their existing explicit call order.
    """
    rows = enumerate_effective_rules(
        registry,
        effective_cfg,
        mode=mode,
        only_enabled=True,
    )
    selected: list[EffectiveRule] = []
    for row in rows:
        if stage is not None and str(row.stage) != str(stage):
            continue
        invoke(row)
        selected.append(row)
    return selected


def apply_enabled_rules(
    registry: RuleRegistry,
    effective_cfg: dict[str, Any],
    *,
    mode: str | None,
    stage: str | None,
    invoke: Callable[[EffectiveRule], Any],
) -> list[EffectiveRule]:
    """Backward-compatible alias for ``select_enabled_rules_for_audit``."""
    return select_enabled_rules_for_audit(
        registry,
        effective_cfg,
        mode=mode,
        stage=stage,
        invoke=invoke,
    )
