# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path


RUNTIME_AUDIT_RELEASE_USE = "runtime_audit_evidence"
RUNTIME_AUDIT_ARTIFACTS: dict[str, tuple[str, str]] = {
    "school_problem_snapshot.json": ("school_problem_snapshot", "标准排课问题快照.json"),
    "rule_execution_plan.json": ("rule_execution_plan", "规则执行计划与trace审计.json"),
    "applied_rules_trace.json": ("applied_rules_trace", "规则应用trace.json"),
    "effective_rules_snapshot.json": ("effective_rules_snapshot", "有效规则快照.json"),
    "solver_params_snapshot.json": ("solver_params_snapshot", "求解参数快照.json"),
    "inputs_fingerprint.json": ("inputs_fingerprint", "输入文件指纹.json"),
}


def runtime_audit_artifact_key(path_or_name: Path | str) -> str:
    entry = RUNTIME_AUDIT_ARTIFACTS.get(_artifact_name(path_or_name))
    return entry[0] if entry else ""


def runtime_audit_display_name(path_or_name: Path | str) -> str:
    entry = RUNTIME_AUDIT_ARTIFACTS.get(_artifact_name(path_or_name))
    return entry[1] if entry else ""


def is_runtime_audit_artifact(path_or_name: Path | str) -> bool:
    return _artifact_name(path_or_name) in RUNTIME_AUDIT_ARTIFACTS


def _artifact_name(path_or_name: Path | str) -> str:
    return Path(str(path_or_name)).name.lower()
