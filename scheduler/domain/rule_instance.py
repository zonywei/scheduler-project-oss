# -*- coding: utf-8 -*-
"""School-specific rule instances.

Rule instances are product/domain artifacts: they describe how a school uses a
generic rule template. They are intentionally side-effect free and do not decide
whether solver constraints execute.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from scheduler.rules.personalized_legacy import PERSONALIZED_LEGACY_RULES, personalized_template_id
from scheduler.rules.defaults import build_default_rule_registry
from scheduler.rules.registry import RuleRegistry


VALID_RULE_INSTANCE_MODES = frozenset({"hard", "soft", "off"})


@dataclass(frozen=True)
class RuleInstance:
    instance_id: str
    template_id: str
    enabled: bool = True
    mode: str | None = None
    weight: float | int | None = None
    target_scope: str = "school"
    params: Mapping[str, Any] = field(default_factory=dict)
    source: str = "in_memory"


@dataclass(frozen=True)
class CompiledRuleInstance:
    instance_id: str
    template_id: str
    rule_name: str
    category_path: str
    enabled: bool
    mode: str
    weight: float | int | None
    target_scope: str
    params: Mapping[str, Any]
    source: str


def rule_instances_from_mapping(
    data: Mapping[str, Any] | Sequence[Mapping[str, Any]],
    *,
    source: str = "mapping",
) -> tuple[RuleInstance, ...]:
    rows: Sequence[Mapping[str, Any]]
    if isinstance(data, Mapping):
        rows = list(data.get("rule_instances") or ())
        rows.extend(_generated_rule_instance_rows(data))
    else:
        rows = data
    instances: list[RuleInstance] = []
    for item in rows:
        mode_raw = item.get("mode")
        instances.append(
            RuleInstance(
                instance_id=str(item.get("id") or item.get("instance_id") or "").strip(),
                template_id=str(item.get("template_id") or item.get("rule_id") or "").strip(),
                enabled=_coerce_bool(item.get("enabled"), True),
                mode=str(mode_raw).strip().lower() if mode_raw is not None else None,
                weight=item.get("weight"),
                target_scope=str(item.get("target_scope") or "school").strip() or "school",
                params=dict(item.get("params") or {}),
                source=source,
            )
        )
    return tuple(instances)


def _generated_rule_instance_rows(data: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    generated: list[Mapping[str, Any]] = []
    for item in data.get("generated_rule_instance_sets") or ():
        if not isinstance(item, Mapping):
            continue
        template_group = str(item.get("template_group") or "").strip()
        if template_group != "personalized_legacy_rules":
            continue
        id_prefix = str(item.get("id_prefix") or "personalized").strip().rstrip(".") or "personalized"
        target_scope = str(item.get("target_scope") or "school").strip() or "school"
        enabled = _coerce_bool(item.get("enabled"), True)
        base_params = dict(item.get("params") or {})
        for rule in PERSONALIZED_LEGACY_RULES:
            suffix = _personalized_instance_suffix(rule.rule_key)
            params = dict(base_params)
            params.update(
                {
                    "legacy_rule": rule.rule_key,
                    "target_slots": list(rule.target_slots),
                    "template_group": template_group,
                    "mode_path": f"personalized_constraints.{rule.mode_key}" if rule.mode_key else None,
                    "weight_path": f"personalized_constraints.{rule.weight_key}" if rule.weight_key else None,
                    "solver_effect": "none",
                }
            )
            generated.append(
                {
                    "id": f"{id_prefix}.{suffix}",
                    "template_id": personalized_template_id(rule.rule_key),
                    "enabled": enabled,
                    "target_scope": target_scope,
                    "params": params,
                }
            )
    return generated


def _personalized_instance_suffix(rule_key: str) -> str:
    text = str(rule_key or "").strip()
    return text[len("enable_"):] if text.startswith("enable_") else text


def validate_rule_instances(
    instances: Sequence[RuleInstance],
    *,
    registry: RuleRegistry | None = None,
) -> tuple[str, ...]:
    reg = registry or build_default_rule_registry()
    errors: list[str] = []
    seen: set[str] = set()
    for item in instances:
        if not item.instance_id:
            errors.append("instance_id is required")
        elif item.instance_id in seen:
            errors.append(f"duplicate instance_id: {item.instance_id}")
        seen.add(item.instance_id)
        if not item.template_id:
            errors.append(f"{item.instance_id or '<missing>'}: template_id is required")
        elif reg.get(item.template_id) is None:
            errors.append(f"{item.instance_id}: unknown template_id: {item.template_id}")
        if item.mode is not None and item.mode not in VALID_RULE_INSTANCE_MODES:
            errors.append(f"{item.instance_id}: unsupported mode: {item.mode}")
        if item.weight is not None and not isinstance(item.weight, (int, float)):
            errors.append(f"{item.instance_id}: weight must be numeric")
        if not item.target_scope:
            errors.append(f"{item.instance_id}: target_scope is required")
    return tuple(errors)


def compile_rule_instances(
    instances: Sequence[RuleInstance],
    *,
    registry: RuleRegistry | None = None,
) -> tuple[CompiledRuleInstance, ...]:
    reg = registry or build_default_rule_registry()
    errors = validate_rule_instances(instances, registry=reg)
    if errors:
        raise ValueError("; ".join(errors))
    compiled: list[CompiledRuleInstance] = []
    for item in instances:
        spec = reg.get(item.template_id)
        if spec is None:
            continue
        mode = item.mode or spec.default_mode
        enabled = item.enabled and mode != "off"
        compiled.append(
            CompiledRuleInstance(
                instance_id=item.instance_id,
                template_id=item.template_id,
                rule_name=spec.name,
                category_path=spec.category_path,
                enabled=enabled,
                mode=mode if mode != "off" else spec.default_mode,
                weight=spec.default_weight if item.weight is None else item.weight,
                target_scope=item.target_scope,
                params=dict(item.params),
                source=item.source,
            )
        )
    return tuple(compiled)


def _coerce_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return bool(value)
