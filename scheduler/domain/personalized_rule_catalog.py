# -*- coding: utf-8 -*-
"""Audit catalog for legacy personalized teacher rules.

This module makes current-school personalized teacher targets explicit as a
portable data contract. It is intentionally visibility-only: it does not
instantiate solver constraints, toggle rule execution, or alter penalties.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

from scheduler.rules.personalized_legacy import (
    PERSONALIZED_LEGACY_RULES,
    PERSONALIZED_RULE_INSTANCE_TEMPLATE_IDS,
    PERSONALIZED_TARGET_SLOTS,
    PersonalizedLegacyRule,
    PersonalizedTargetSlot,
    personalized_template_id,
)


def personalized_rule_catalog_payload(
    effective_cfg: Mapping[str, Any] | None,
    *,
    rule_instances: Sequence[Any] = (),
    profile_data: Mapping[str, Any] | None = None,
    source: str = "effective_config",
) -> dict[str, Any]:
    """Build a read-only migration catalog for personalized rules."""
    cfg = _mapping((effective_cfg or {}).get("personalized_constraints"))
    target_cfg = _mapping(cfg.get("teacher_targets"))
    slot_payloads = []
    values_by_slot: dict[str, list[str]] = {}

    for slot in PERSONALIZED_TARGET_SLOTS:
        values = _clean_values(_slot_raw_value(slot, cfg, target_cfg))
        values_by_slot[slot.slot_id] = values
        slot_payloads.append(
            {
                "slot_id": slot.slot_id,
                "label": slot.label,
                "config_path": slot.config_path,
                "value_kind": slot.value_kind,
                "values": values,
                "configured": bool(values),
                "status": "configured" if values else "missing",
                "solver_effect": "none",
            }
        )

    personalized_instances = [
        {
            "instance_id": _attr_or_key(instance, "instance_id"),
            "template_id": _attr_or_key(instance, "template_id"),
            "source": _attr_or_key(instance, "source"),
        }
        for instance in rule_instances
        if _attr_or_key(instance, "template_id") in PERSONALIZED_RULE_INSTANCE_TEMPLATE_IDS
    ]
    has_profile_instances = bool(personalized_instances)
    granular_template_ids = {personalized_template_id(rule.rule_key) for rule in PERSONALIZED_LEGACY_RULES}
    profile_template_ids = {str(item["template_id"]) for item in personalized_instances}
    granular_profile_instances = [
        item
        for item in personalized_instances
        if item["template_id"] in granular_template_ids
    ]
    collection_profile_instances = [
        item
        for item in personalized_instances
        if item["template_id"] not in granular_template_ids
    ]

    legacy_rule_payloads = []
    for rule in PERSONALIZED_LEGACY_RULES:
        enabled = bool(cfg.get(rule.rule_key, False))
        missing_slots = [slot_id for slot_id in rule.target_slots if not values_by_slot.get(slot_id)]
        target_values = [value for slot_id in rule.target_slots for value in values_by_slot.get(slot_id, ())]
        template_id = personalized_template_id(rule.rule_key)
        if template_id in profile_template_ids:
            migration_status = "granular_profile_rule_instance"
        elif has_profile_instances:
            migration_status = "profile_rule_instance_present"
        elif enabled:
            migration_status = "legacy_config"
        else:
            migration_status = "disabled"
        legacy_rule_payloads.append(
            {
                "rule_key": rule.rule_key,
                "template_id": template_id,
                "title": rule.title,
                "enabled": enabled,
                "target_slots": list(rule.target_slots),
                "targets": target_values,
                "missing_target_slots": missing_slots,
                "target_status": "configured" if not missing_slots else "missing_required_targets",
                "mode_path": f"personalized_constraints.{rule.mode_key}" if rule.mode_key else None,
                "mode": cfg.get(rule.mode_key) if rule.mode_key else None,
                "weight_path": f"personalized_constraints.{rule.weight_key}" if rule.weight_key else None,
                "weight": cfg.get(rule.weight_key) if rule.weight_key else None,
                "migration_status": migration_status,
                "solver_effect": "none",
            }
        )

    profile_groups = tuple(_profile_source_groups(profile_data))
    legacy_group_declared = "personalized_constraints" in profile_groups
    configured_slots = sum(1 for item in slot_payloads if item["configured"])
    enabled_rules = [item for item in legacy_rule_payloads if item["enabled"]]
    enabled_rules_missing_targets = [
        item["rule_key"]
        for item in enabled_rules
        if item["missing_target_slots"]
    ]
    overall_status = (
        "granular_profile_rule_instances_present"
        if granular_profile_instances
        else "profile_rule_instance_present"
        if has_profile_instances
        else "legacy_config_declared"
        if legacy_group_declared
        else "legacy_config_only"
    )

    return {
        "schema_version": "scheduler.personalized_rule_catalog.v1",
        "source": source,
        "solver_effect": "none",
        "can_block_solver": False,
        "migration_status": overall_status,
        "summary": {
            "target_slots": len(slot_payloads),
            "configured_target_slots": configured_slots,
            "missing_target_slots": len(slot_payloads) - configured_slots,
            "legacy_rules": len(legacy_rule_payloads),
            "enabled_legacy_rules": len(enabled_rules),
            "enabled_rules_missing_targets": len(enabled_rules_missing_targets),
            "profile_rule_instances": len(personalized_instances),
            "granular_profile_rule_instances": len(granular_profile_instances),
            "collection_profile_rule_instances": len(collection_profile_instances),
            "legacy_group_declared": legacy_group_declared,
        },
        "profile_source_groups": list(profile_groups),
        "profile_rule_instances": personalized_instances,
        "granular_profile_rule_instances": granular_profile_instances,
        "collection_profile_rule_instances": collection_profile_instances,
        "enabled_rules_missing_targets": enabled_rules_missing_targets,
        "target_slots": slot_payloads,
        "legacy_rules": legacy_rule_payloads,
        "contract": {
            "scope": "personalized_teacher_rule_migration_audit",
            "solver_effect": "none",
            "can_block_solver": False,
        },
    }


def _slot_raw_value(slot: PersonalizedTargetSlot, cfg: Mapping[str, Any], target_cfg: Mapping[str, Any]) -> Any:
    prefix = "personalized_constraints.teacher_targets."
    if slot.config_path.startswith(prefix):
        return target_cfg.get(slot.slot_id)
    return cfg.get(slot.slot_id)


def _clean_values(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        parts = raw.replace("，", ",").replace("、", ",").split(",")
        return [part.strip() for part in parts if part.strip()]
    if isinstance(raw, Mapping):
        return []
    if isinstance(raw, (list, tuple, set)):
        values: list[str] = []
        for item in raw:
            values.extend(_clean_values(item))
        return values
    text = str(raw).strip()
    return [text] if text else []


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _profile_source_groups(profile_data: Mapping[str, Any] | None) -> tuple[str, ...]:
    sources = _mapping((profile_data or {}).get("rule_instance_sources"))
    groups = sources.get("groups")
    if not isinstance(groups, (list, tuple, set)):
        return ()
    return tuple(str(group) for group in groups if str(group).strip())


def _attr_or_key(value: Any, name: str) -> Any:
    if isinstance(value, Mapping):
        return value.get(name)
    return getattr(value, name, None)
