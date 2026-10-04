# -*- coding: utf-8 -*-
"""Read-only SchoolProblem preview for Web and runtime evidence.

This module adapts the current DayInputData into the standard SchoolProblem
contract without changing the solver input path.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from scheduler.data.day_rules_reader import load_day_inputs
from scheduler.domain.rule_instance import compile_rule_instances, rule_instances_from_mapping
from scheduler.domain.school_problem import (
    school_problem_from_day_inputs,
    school_problem_summary,
    validate_school_problem,
)
from scheduler.domain.school_profile import profile_from_legacy_config, profile_from_mapping


def build_school_problem_preview_payload(
    *,
    mode: str,
    effective_cfg: dict[str, Any],
    io_cfg: dict[str, Any],
    io_path: Path,
    registry: Any,
    run_id: str = "",
    git_commit: str | None = None,
    source: str = "web_preview",
) -> dict[str, Any]:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    repo_root = io_path.parent.parent.parent.resolve()
    base_dir = io_path.parent.parent
    day_cfg = io_cfg.get("day", {}) if isinstance(io_cfg.get("day"), dict) else {}
    rules_xlsx = (base_dir / str(day_cfg.get("rules_path") or "白天规则.xlsx")).resolve()
    teacher_xlsx = (base_dir / str(day_cfg.get("teacher_table_path") or "教师定位表.xlsx")).resolve()
    profile_path = repo_root / "profiles" / "current_school" / "profile.yaml"
    payload: dict[str, Any] = {
        "schema_version": "scheduler.school_problem_preview.v1",
        "timestamp": timestamp,
        "source": source,
        "solver_effect": "none",
        "mode": str(mode),
        "run_id": str(run_id or ""),
        "git_commit": git_commit,
        "adapter": {
            "source": "DayInputData",
            "rules_path": str(rules_xlsx),
            "teacher_table_path": str(teacher_xlsx),
        },
        "validation": {"ok": False, "errors": []},
        "summary": {},
    }
    try:
        profile_data: dict[str, Any] = {}
        if profile_path.exists():
            raw_profile = yaml.safe_load(profile_path.read_text(encoding="utf-8")) or {}
            profile_data = raw_profile if isinstance(raw_profile, dict) else {}
            profile = profile_from_mapping(profile_data, source=profile_path.as_posix())
            rule_instances = compile_rule_instances(
                rule_instances_from_mapping(profile_data, source=profile_path.as_posix()),
                registry=registry,
            )
        else:
            profile = profile_from_legacy_config(
                effective_cfg,
                profile_id="current_school",
                name="当前学校",
                stage="senior",
            )
            rule_instances = ()

        day_inputs = load_day_inputs(str(rules_xlsx), str(teacher_xlsx), io_cfg.get("web_tables"))
        problem = school_problem_from_day_inputs(
            profile,
            day_inputs,
            rule_instances=rule_instances,
            source="runtime.day_inputs" if source == "runtime_snapshot" else "web.day_inputs",
        )
        errors = validate_school_problem(problem)
        payload.update(
            {
                "profile": {
                    "profile_id": profile.profile_id,
                    "stage": profile.stage,
                    "source": profile.source,
                },
                "summary": school_problem_summary(problem),
                "validation": {"ok": not errors, "errors": list(errors)},
            }
        )
    except Exception as exc:
        payload["validation"] = {"ok": False, "errors": [str(exc)]}
        payload["adapter"]["status"] = "unavailable"
    return payload
