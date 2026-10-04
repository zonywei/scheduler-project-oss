# -*- coding: utf-8 -*-
"""Profile catalog validation for cross-school fixtures.

The catalog is an audit/validation layer. It discovers persisted school
profiles, compiles their rule instances, validates sample problems when present,
and checks that instances map to the registry execution plan. It does not load
real Excel files and does not call solver constraints.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml

from scheduler.domain.rule_instance import (
    CompiledRuleInstance,
    RuleInstance,
    compile_rule_instances,
    rule_instances_from_mapping,
    validate_rule_instances,
)
from scheduler.domain.personalized_rule_catalog import personalized_rule_catalog_payload
from scheduler.domain.school_problem import (
    SchoolProblem,
    school_problem_from_mapping,
    school_problem_summary,
    validate_school_problem,
)
from scheduler.domain.school_profile import SchoolProfile, profile_from_mapping, validate_school_profile
from scheduler.rules.defaults import build_default_rule_registry
from scheduler.rules.execution_plan import RuleExecutionPlan, build_rule_execution_plan
from scheduler.rules.registry import RuleRegistry


@dataclass(frozen=True)
class ProfileCatalogEntry:
    profile_id: str
    profile_path: Path
    profile: SchoolProfile
    rule_instances: tuple[RuleInstance, ...]
    compiled_rule_instances: tuple[CompiledRuleInstance, ...]
    execution_plan: RuleExecutionPlan
    sample_problem_path: Path | None = None
    sample_problem: SchoolProblem | None = None
    personalized_rule_catalog: dict[str, Any] | None = None


@dataclass(frozen=True)
class ProfileCatalogIssue:
    profile_id: str
    severity: str
    message: str
    path: str


@dataclass(frozen=True)
class ProfileCatalogValidation:
    entries: tuple[ProfileCatalogEntry, ...]
    issues: tuple[ProfileCatalogIssue, ...]

    @property
    def ok(self) -> bool:
        return not any(issue.severity == "error" for issue in self.issues)

    def summary(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "profiles": len(self.entries),
            "sample_problems": sum(1 for entry in self.entries if entry.sample_problem is not None),
            "issues": len(self.issues),
            "errors": sum(1 for issue in self.issues if issue.severity == "error"),
            "warnings": sum(1 for issue in self.issues if issue.severity == "warning"),
            "profile_ids": [entry.profile_id for entry in self.entries],
        }


def validate_profile_catalog(
    profiles_root: Path,
    effective_cfg: Mapping[str, Any],
    *,
    mode: str = "joint",
    registry: RuleRegistry | None = None,
) -> ProfileCatalogValidation:
    reg = registry or build_default_rule_registry()
    entries: list[ProfileCatalogEntry] = []
    issues: list[ProfileCatalogIssue] = []
    root = Path(profiles_root)

    for profile_path in sorted(root.glob("*/profile.yaml")):
        profile_id = profile_path.parent.name
        try:
            data = _load_yaml_mapping(profile_path)
            profile = profile_from_mapping(data, source=profile_path.as_posix())
            _extend_issues(issues, profile_id, profile_path, validate_school_profile(profile))

            rule_instances = rule_instances_from_mapping(data, source=profile_path.as_posix())
            _extend_issues(issues, profile_id, profile_path, validate_rule_instances(rule_instances, registry=reg))
            compiled = compile_rule_instances(rule_instances, registry=reg)
            plan = build_rule_execution_plan(
                reg,
                dict(effective_cfg),
                mode=mode,
                profile=profile,
                rule_instances=compiled,
                only_enabled=False,
                source=profile_path.as_posix(),
            )
            _extend_issues(
                issues,
                profile_id,
                profile_path,
                tuple(
                    f"{item.instance_id}: {item.reason}"
                    for item in plan.unplanned_rule_instances
                ),
            )

            sample_path = profile_path.with_name("sample_problem.yaml")
            sample_problem = None
            if sample_path.exists():
                sample_data = _load_yaml_mapping(sample_path)
                sample_problem = school_problem_from_mapping(
                    profile,
                    sample_data,
                    rule_instances=compiled,
                    source=sample_path.as_posix(),
                )
                _extend_issues(issues, profile_id, sample_path, validate_school_problem(sample_problem))
            elif profile_id != "current_school":
                issues.append(
                    ProfileCatalogIssue(
                        profile_id=profile_id,
                        severity="warning",
                        message="sample_problem.yaml is missing",
                        path=sample_path.as_posix(),
                    )
                )

            entries.append(
                ProfileCatalogEntry(
                    profile_id=profile.profile_id,
                    profile_path=profile_path,
                    profile=profile,
                    rule_instances=rule_instances,
                    compiled_rule_instances=compiled,
                    execution_plan=plan,
                    sample_problem_path=sample_path if sample_path.exists() else None,
                    sample_problem=sample_problem,
                    personalized_rule_catalog=personalized_rule_catalog_payload(
                        effective_cfg,
                        rule_instances=rule_instances,
                        profile_data=data,
                        source=profile_path.as_posix(),
                    ),
                )
            )
        except Exception as exc:
            issues.append(
                ProfileCatalogIssue(
                    profile_id=profile_id,
                    severity="error",
                    message=str(exc),
                    path=profile_path.as_posix(),
                )
            )

    if not entries:
        issues.append(
            ProfileCatalogIssue(
                profile_id="",
                severity="error",
                message="no profile.yaml files found",
                path=root.as_posix(),
            )
        )
    return ProfileCatalogValidation(entries=tuple(entries), issues=tuple(issues))


def profile_catalog_payload(report: ProfileCatalogValidation) -> dict[str, Any]:
    return {
        "summary": report.summary(),
        "rule_coverage": _rule_coverage_payload(report),
        "issues": [
            {
                "profile_id": issue.profile_id,
                "severity": issue.severity,
                "message": issue.message,
                "path": issue.path,
            }
            for issue in report.issues
        ],
        "profiles": [
            {
                "profile_id": entry.profile_id,
                "stage": entry.profile.stage,
                "profile_path": entry.profile_path.as_posix(),
                "sample_problem_path": entry.sample_problem_path.as_posix() if entry.sample_problem_path else None,
                "rule_instances": len(entry.compiled_rule_instances),
                "execution_plan_items": len(entry.execution_plan.items),
                "personalized_rule_catalog": entry.personalized_rule_catalog,
                "sample_problem": school_problem_summary(entry.sample_problem) if entry.sample_problem else None,
            }
            for entry in report.entries
        ],
    }


def _rule_coverage_payload(report: ProfileCatalogValidation) -> dict[str, Any]:
    profiles = [
        {
            "profile_id": entry.profile_id,
            "stage": entry.profile.stage,
            "has_sample_problem": entry.sample_problem is not None,
            "rule_instances": len(entry.compiled_rule_instances),
            "enabled_rule_instances": sum(1 for instance in entry.compiled_rule_instances if instance.enabled),
            "rule_families": _family_counts(entry.compiled_rule_instances),
        }
        for entry in report.entries
    ]
    template_rows: list[dict[str, Any]] = []
    template_ids = sorted({instance.template_id for entry in report.entries for instance in entry.compiled_rule_instances})
    for template_id in template_ids:
        instances = [
            (entry, instance)
            for entry in report.entries
            for instance in entry.compiled_rule_instances
            if instance.template_id == template_id
        ]
        profile_ids = tuple(entry.profile_id for entry, _ in instances)
        enabled_profile_ids = tuple(entry.profile_id for entry, instance in instances if instance.enabled)
        stages = tuple(sorted({entry.profile.stage for entry, _ in instances}))
        template_rows.append(
            {
                "template_id": template_id,
                "family": _rule_family(template_id),
                "profile_ids": list(profile_ids),
                "enabled_profile_ids": list(enabled_profile_ids),
                "stages": list(stages),
                "instance_ids": [instance.instance_id for _, instance in instances],
                "profile_count": len(set(profile_ids)),
                "enabled_profile_count": len(set(enabled_profile_ids)),
                "current_school_only": set(profile_ids) == {"current_school"},
            }
        )

    family_rows: list[dict[str, Any]] = []
    family_ids = sorted({row["family"] for row in template_rows})
    for family in family_ids:
        rows = [row for row in template_rows if row["family"] == family]
        profile_ids = sorted({profile_id for row in rows for profile_id in row["profile_ids"]})
        family_rows.append(
            {
                "family": family,
                "templates": len(rows),
                "profile_ids": profile_ids,
                "current_school_only_templates": sum(1 for row in rows if row["current_school_only"]),
            }
        )

    return {
        "schema_version": "scheduler.rule_coverage_matrix.v1",
        "source": "profile_catalog",
        "solver_effect": "none",
        "can_block_solver": False,
        "summary": {
            "profiles": len(report.entries),
            "sample_problem_profiles": sum(1 for entry in report.entries if entry.sample_problem is not None),
            "template_rules": len(template_rows),
            "rule_families": len(family_rows),
            "current_school_only_templates": sum(1 for row in template_rows if row["current_school_only"]),
            "cross_profile_templates": sum(1 for row in template_rows if row["profile_count"] > 1),
        },
        "profiles": profiles,
        "families": family_rows,
        "templates": template_rows,
        "contract": {
            "scope": "cross_school_rule_instance_coverage",
            "solver_effect": "none",
            "can_block_solver": False,
        },
    }


def _family_counts(instances: tuple[CompiledRuleInstance, ...]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for instance in instances:
        family = _rule_family(instance.template_id)
        counts[family] = counts.get(family, 0) + 1
    return dict(sorted(counts.items()))


def _rule_family(template_id: str) -> str:
    text = str(template_id or "").strip()
    if not text:
        return "unknown"
    return text.split(".", 1)[0]


def _load_yaml_mapping(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path.as_posix()} must contain a YAML mapping")
    return data


def _extend_issues(
    issues: list[ProfileCatalogIssue],
    profile_id: str,
    path: Path,
    messages: tuple[str, ...],
) -> None:
    for message in messages:
        issues.append(
            ProfileCatalogIssue(
                profile_id=profile_id,
                severity="error",
                message=str(message),
                path=path.as_posix(),
            )
        )
