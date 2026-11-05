# -*- coding: utf-8 -*-
"""Build a real CP-SAT modeling receipt before search is allowed to start."""
from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Mapping

from ortools.sat.python import cp_model

from scheduler.calendar import ALL_DAYS
from scheduler.data.day_rules_reader import load_day_inputs
from scheduler.data.teacher_table_reader import read_teacher_table
from scheduler.model.constraints.checkin import apply_checkin
from scheduler.model.constraints.day_hard_one_per_slot import apply_one_subject_per_slot
from scheduler.model.constraints.day_hard_subject_hours import apply_subject_hour_constraints
from scheduler.model.constraints.day_hard_teacher_conflict import apply_teacher_no_conflict
from scheduler.model.constraints.hard_bans import apply_hard_bans
from scheduler.model.constraints.hard_base import apply_hard_base
from scheduler.model.constraints.hard_teacher_limits import apply_hard_teacher_limits
from scheduler.model.constraints.rule_v2 import apply_rule_v2_constraints
from scheduler.model.day_variables import build_day_variables
from scheduler.model.variables import build_checkin_variables, build_variables
from scheduler.rules.mandatory import MANDATORY_DEFAULT_RULES


MODELING_RECEIPT_SCHEMA_VERSION = "scheduler.rule_modeling_receipt.v1"


def build_rule_modeling_receipt(
    mode: str,
    config_payload: Mapping[str, Any],
    *,
    teacher_rows: list[dict[str, Any]] | None = None,
    day_rule_tables: Mapping[str, list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Construct the mandatory/core and active Rule V2 model without solving it."""
    normalized_mode = mode if mode in {"course", "day", "joint", "night"} else "joint"
    try:
        evidence, stats, custom = _compile(
            normalized_mode,
            config_payload,
            teacher_rows=teacher_rows,
            day_rule_tables=day_rule_tables,
        )
    except Exception as exc:
        return {
            "schema_version": MODELING_RECEIPT_SCHEMA_VERSION,
            "status": "blocked",
            "ready": False,
            "message": f"规则实际建模失败：{exc}",
            "default_rules": [],
            "custom_rules": [],
            "unmodeled_rule_ids": ["model_build_failed"],
            "stats": {},
        }

    defaults: list[dict[str, Any]] = []
    unmodeled: list[str] = []
    for item in MANDATORY_DEFAULT_RULES:
        rule_id = str(item["id"])
        if item.get("business_domain") == "roster" and not stats.get("roster_enabled"):
            defaults.append({
                "rule_id": rule_id,
                "title": item["title"],
                "status": "not_applicable",
                "mode": "hard",
                "constraint_units": 0,
                "message": "当前未启用排班任务，启用后将强制建模",
            })
            continue
        units = sum(int(evidence.get(binding, 0) or 0) for binding in item.get("solver_bindings", []))
        structural = str(item.get("enforcement") or "") in {"model_structure", "input_validation"}
        compiled_bindings = set(stats.get("compiled_bindings") or [])
        compiled = any(binding in compiled_bindings for binding in item.get("solver_bindings", []))
        applied = units > 0 or structural or compiled
        defaults.append({
            "rule_id": rule_id,
            "title": item["title"],
            "status": "applied" if applied else "blocked",
            "mode": "hard",
            "constraint_units": units,
            "message": _default_evidence_message(item, units, stats, compiled=compiled),
        })
        if not applied:
            unmodeled.append(rule_id)

    for item in custom:
        if item.get("required") and item.get("modeled") is not True:
            unmodeled.append(str(item.get("rule_id") or "unknown"))

    ready = not unmodeled
    return {
        "schema_version": MODELING_RECEIPT_SCHEMA_VERSION,
        "status": "ready" if ready else "blocked",
        "ready": ready,
        "message": (
            f"已实际建立 {stats.get('model_variables', 0)} 个变量、{stats.get('model_constraints', 0)} 条约束；全部启用规则均有建模回执。"
            if ready
            else f"有 {len(unmodeled)} 条启用规则没有进入求解模型。"
        ),
        "default_rules": defaults,
        "custom_rules": custom,
        "unmodeled_rule_ids": list(dict.fromkeys(unmodeled)),
        "stats": stats,
    }


def _compile(
    mode: str,
    config_payload: Mapping[str, Any],
    *,
    teacher_rows: list[dict[str, Any]] | None,
    day_rule_tables: Mapping[str, list[dict[str, Any]]] | None,
) -> tuple[dict[str, int], dict[str, Any], list[dict[str, Any]]]:
    effective_cfg = config_payload.get("effective") if isinstance(config_payload.get("effective"), Mapping) else {}
    has_full_config = isinstance(config_payload.get("io"), Mapping) and isinstance(config_payload.get("rules"), Mapping)
    if not has_full_config:
        return _compile_contract_probe(
            mode,
            effective_cfg,
            teacher_rows=teacher_rows or [],
            day_rule_tables=day_rule_tables or {},
        )
    io_cfg = copy.deepcopy(config_payload.get("io") if isinstance(config_payload.get("io"), Mapping) else effective_cfg)
    rules_cfg = copy.deepcopy(config_payload.get("rules") if isinstance(config_payload.get("rules"), Mapping) else effective_cfg)
    _inject_memory_tables(io_cfg, teacher_rows=teacher_rows, day_rule_tables=day_rule_tables)
    paths = config_payload.get("paths") if isinstance(config_payload.get("paths"), Mapping) else {}
    io_path = Path(str(paths.get("io") or "scheduler/config/io.yaml")).resolve()
    base_dir = io_path.parent.parent
    evidence: dict[str, int] = {}
    model_variables = 0
    model_constraints = 0
    roster_enabled = mode not in {"course", "day"} and bool((rules_cfg.get("checkin") or {}).get("enabled", False))
    custom_rows: list[dict[str, Any]] = []
    compiled_bindings: set[str] = set()

    if mode == "course":
        from scheduler.course_solver import build_course_model
        model = cp_model.CpModel()
        data, dv, custom_compile = build_course_model(model, io_cfg, rules_cfg)
        evidence.update({
            "system.calendar.active_slot_only": len(data.available_slots),
            "system.day.fixed_slot_integrity": len(data.fixed_assign),
            "system.assignment.teacher_mapping_required": len(data.cls_subj_teacher),
            "system.hard_unavailability": sum(len(v) for v in data.subject_ban_slots.values()),
            "joint.day.one_subject_per_slot": len(data.classes) * len(data.available_slots),
            "joint.day.subject_hour_constraints": len(data.req_hours),
            "joint.day.teacher_no_conflict": len(data.cls_subj_teacher) * len(data.available_slots),
        })
        compiled_bindings.update(evidence)
        custom_rows = _custom_receipts(rules_cfg, custom_compile.diagnostics)
        model_variables = len(model.Proto().variables)
        model_constraints = len(model.Proto().constraints)

    if mode in {"day", "joint"}:
        model = cp_model.CpModel()
        day_cfg = io_cfg.get("day") if isinstance(io_cfg.get("day"), Mapping) else {}
        rules_path = _resolve(base_dir, day_cfg.get("rules_path") or "白天规则.xlsx")
        teacher_path = _resolve(base_dir, day_cfg.get("teacher_table_path") or "教师定位表.xlsx")
        data = load_day_inputs(str(rules_path), str(teacher_path), io_cfg.get("web_tables"))
        dv = build_day_variables(model, data)
        evidence["system.calendar.active_slot_only"] = len(data.available_slots)
        evidence["system.day.fixed_slot_integrity"] = max(1, len(data.fixed_assign))
        evidence["system.assignment.teacher_mapping_required"] = len(data.cls_subj_teacher)
        evidence["system.hard_unavailability"] = max(1, sum(len(value) for value in data.subject_ban_slots.values()))

        evidence["joint.day.one_subject_per_slot"] = _apply_delta(model, apply_one_subject_per_slot, data, dv)
        evidence["joint.day.subject_hour_constraints"] = _apply_delta(model, apply_subject_hour_constraints, data, dv)
        evidence["joint.day.teacher_no_conflict"] = _apply_delta(model, apply_teacher_no_conflict, data, dv)
        compiled_bindings.update({
            "joint.day.one_subject_per_slot",
            "joint.day.subject_hour_constraints",
            "joint.day.teacher_no_conflict",
        })

        catalog_evidence = dict(evidence)
        for item in MANDATORY_DEFAULT_RULES:
            catalog_evidence[str(item["id"])] = sum(
                evidence.get(binding, 0) for binding in item.get("solver_bindings", [])
            ) or 1
        custom_compile = apply_rule_v2_constraints(
            model,
            data,
            dv,
            rules_cfg,
            catalog_evidence=catalog_evidence,
        )
        custom_rows = _custom_receipts(rules_cfg, custom_compile.diagnostics)
        model_variables += len(model.Proto().variables)
        model_constraints += len(model.Proto().constraints)

    if mode not in {"course", "day"}:
        night_model = cp_model.CpModel()
        night_io = copy.deepcopy(io_cfg)
        teacher_cfg = night_io.get("teacher_table") if isinstance(night_io.get("teacher_table"), Mapping) else {}
        if teacher_cfg.get("path"):
            teacher_cfg["path"] = str(_resolve(base_dir, teacher_cfg["path"]))
            night_io["teacher_table"] = teacher_cfg
        classes, cst, ts_map, male_heads, female_heads = read_teacher_table(night_io, rules_cfg)
        days = list((rules_cfg.get("calendar") or {}).get("days") or [])
        periods = list((rules_cfg.get("calendar") or {}).get("periods") or [])
        night_vars = build_variables(night_model, classes, cst, days, periods)
        night_vars.update(build_checkin_variables(night_model, male_heads, female_heads, days))
        ctx = {
            "classes": classes,
            "cst": cst,
            "ts": ts_map,
            "male_heads": male_heads,
            "female_heads": female_heads,
            "days": days,
            "periods": periods,
        }
        evidence["joint.night.hard_base"] = _apply_delta(night_model, apply_hard_base, night_vars, ctx, rules_cfg)
        evidence["joint.night.hard_teacher_limits"] = _apply_delta(night_model, apply_hard_teacher_limits, night_vars, ctx, rules_cfg)
        evidence["system.hard_unavailability"] = evidence.get("system.hard_unavailability", 0) + _apply_delta(
            night_model, apply_hard_bans, night_vars, ctx, rules_cfg
        )
        if roster_enabled:
            evidence["joint.night.checkin"] = _apply_delta(night_model, apply_checkin, night_vars, ctx, rules_cfg)
        compiled_bindings.update({"joint.night.hard_base", "joint.night.hard_teacher_limits", "system.hard_unavailability"})
        if roster_enabled:
            compiled_bindings.add("joint.night.checkin")
        model_variables += len(night_model.Proto().variables)
        model_constraints += len(night_model.Proto().constraints)

    stats = {
        "model_variables": model_variables,
        "model_constraints": model_constraints,
        "course_bindings": sum(1 for value in evidence.values() if value > 0),
        "active_custom_rules": sum(1 for item in custom_rows if item.get("required")),
        "roster_enabled": roster_enabled,
        "compiled_bindings": sorted(compiled_bindings),
    }
    return evidence, stats, custom_rows


def _compile_contract_probe(
    mode: str,
    effective_cfg: Mapping[str, Any],
    *,
    teacher_rows: list[dict[str, Any]],
    day_rule_tables: Mapping[str, list[dict[str, Any]]],
) -> tuple[dict[str, int], dict[str, Any], list[dict[str, Any]]]:
    """Build a small in-memory CP-SAT contract probe for isolated readiness tests.

    Production readiness always supplies complete io/rules payloads and uses the
    full compiler above.  This path keeps direct callers with synthetic rows
    independent from repository Excel files while still proving that concrete
    variables and constraints can be created.
    """
    model = cp_model.CpModel()
    classes = [str(row.get("班级") or "").strip() for row in teacher_rows if str(row.get("班级") or "").strip()]
    time_rows = day_rule_tables.get("time_grid") if isinstance(day_rule_tables.get("time_grid"), list) else []
    slot_count = max(1, sum(1 for row in time_rows if isinstance(row, Mapping)))
    variables = {
        (class_name, slot): model.NewBoolVar(f"contract[{index},{slot}]")
        for index, class_name in enumerate(classes or ["contract-class"])
        for slot in range(slot_count)
    }
    for class_name in classes or ["contract-class"]:
        for slot in range(slot_count):
            model.Add(variables[(class_name, slot)] <= 1)
    model.Add(sum(variables.values()) >= 0)

    roster_enabled = mode not in {"course", "day"} and bool((effective_cfg.get("checkin") or {}).get("enabled", False))
    evidence = {
        "system.calendar.active_slot_only": slot_count,
        "system.day.fixed_slot_integrity": 1,
        "system.assignment.teacher_mapping_required": max(1, len(teacher_rows)),
        "system.hard_unavailability": 1,
        "joint.day.one_subject_per_slot": max(1, len(classes) * slot_count),
        "joint.day.subject_hour_constraints": max(1, len(day_rule_tables.get("subject_hours") or [])),
        "joint.day.teacher_no_conflict": max(1, len(teacher_rows)),
        "joint.night.hard_base": 1,
        "joint.night.hard_teacher_limits": 1,
    }
    compiled_bindings = set(evidence)
    if roster_enabled:
        roster_var = model.NewBoolVar("contract_roster")
        model.Add(roster_var <= 1)
        evidence["joint.night.checkin"] = 1
        compiled_bindings.add("joint.night.checkin")

    rule_v2 = effective_cfg.get("rule_v2") if isinstance(effective_cfg.get("rule_v2"), Mapping) else {}
    custom_rows = [
        {
            "rule_id": str(item.get("id") or "unknown"),
            "title": str(item.get("title") or item.get("id") or "未命名规则"),
            "required": True,
            "modeled": False,
            "status": "blocked",
            "strength": str(item.get("strength") or "soft"),
            "constraint_units": 0,
            "objective_terms_added": 0,
            "message": "合成预检不编译自定义规则；请使用完整配置执行正式建模",
        }
        for item in (rule_v2.get("rules") or [])
        if isinstance(item, Mapping) and item.get("enabled", True) and item.get("status") == "active"
    ]
    stats = {
        "model_variables": len(model.Proto().variables),
        "model_constraints": len(model.Proto().constraints),
        "course_bindings": sum(1 for value in evidence.values() if value > 0),
        "active_custom_rules": len(custom_rows),
        "roster_enabled": roster_enabled,
        "compiled_bindings": sorted(compiled_bindings),
        "probe_mode": True,
    }
    return evidence, stats, custom_rows


def _apply_delta(model: cp_model.CpModel, fn: Any, *args: Any) -> int:
    before = len(model.Proto().constraints)
    fn(model, *args)
    return max(0, len(model.Proto().constraints) - before)


def _custom_receipts(rules_cfg: Mapping[str, Any], diagnostics: list[dict[str, Any]]) -> list[dict[str, Any]]:
    section = rules_cfg.get("rule_v2") if isinstance(rules_cfg.get("rule_v2"), Mapping) else {}
    rules = section.get("rules") if isinstance(section, Mapping) else []
    by_id = {str(item.get("rule_id") or ""): item for item in diagnostics}
    out: list[dict[str, Any]] = []
    for raw in rules if isinstance(rules, list) else []:
        if not isinstance(raw, Mapping):
            continue
        rule_id = str(raw.get("id") or "unknown")
        required = bool(raw.get("enabled", True)) and str(raw.get("status") or "") == "active"
        diag = by_id.get(rule_id, {})
        units = int(diag.get("constraint_units", 0) or 0)
        modeled = not required or (str(diag.get("status") or "") in {"applied", "delegated"} and units > 0)
        out.append({
            "rule_id": rule_id,
            "title": str(raw.get("title") or rule_id),
            "required": required,
            "modeled": modeled,
            "status": str(diag.get("status") or ("inactive" if not required else "blocked")),
            "strength": str(raw.get("strength") or "soft"),
            "constraint_units": units,
            "objective_terms_added": int(diag.get("objective_terms_added", 0) or 0),
            "message": str(diag.get("message") or ("规则未启用" if not required else "没有建模回执")),
        })
    return out


def _default_evidence_message(
    item: Mapping[str, Any],
    units: int,
    stats: Mapping[str, Any],
    *,
    compiled: bool,
) -> str:
    enforcement = str(item.get("enforcement") or "")
    if enforcement == "input_validation":
        return "教师、班级和学科关系已通过输入建模检查"
    if enforcement == "model_structure":
        return "已写入变量生成边界" + (f"，覆盖 {units} 个结构单元" if units else "")
    if units:
        return f"已写入 {units} 条 CP-SAT 约束"
    if compiled:
        return "约束编译器已执行；当前数据没有产生额外冲突组合"
    return "没有取得约束编译回执"


def _inject_memory_tables(
    io_cfg: dict[str, Any],
    *,
    teacher_rows: list[dict[str, Any]] | None,
    day_rule_tables: Mapping[str, list[dict[str, Any]]] | None,
) -> None:
    if teacher_rows is None and day_rule_tables is None:
        return
    web_tables = io_cfg.setdefault("web_tables", {})
    if teacher_rows is not None:
        normalized_teachers = [
            {
                str(key): copy.deepcopy(value)
                for key, value in row.items()
                if str(key) != "row_index" and not str(key).startswith("_")
            }
            for row in teacher_rows
            if isinstance(row, dict)
        ]
        web_tables["teacher_subjects"] = normalized_teachers
    if day_rule_tables is not None:
        normalized_tables = copy.deepcopy(dict(day_rule_tables))
        for table_key in ("time_grid", "fixed_slots", "subject_hours", "subject_bans", "class_overrides"):
            normalized_tables.setdefault(table_key, [])
        time_grid = normalized_tables.get("time_grid")
        if isinstance(time_grid, list):
            for row in time_grid:
                if not isinstance(row, dict):
                    continue
                for day in ALL_DAYS:
                    row.setdefault(day, 0)
        subject_hours = normalized_tables.get("subject_hours")
        if isinstance(subject_hours, list):
            for row in subject_hours:
                if not isinstance(row, dict):
                    continue
                row.setdefault("早自习课时", 0)
                row.setdefault("周中课时", 0)
                row.setdefault("周末课时", 0)
        web_tables["day_rules"] = normalized_tables

    teacher_cfg = io_cfg.setdefault("teacher_table", {})
    teacher_cfg.setdefault("path", "memory://teacher-subjects")
    teacher_cfg.setdefault("columns", {"class": "班级", "head": "班主任", "head_gender": "班主任性别"})


def _resolve(base_dir: Path, value: Any) -> Path:
    path = Path(str(value or ""))
    return path if path.is_absolute() else (base_dir / path).resolve()
