# -*- coding: utf-8 -*-
"""Domain-level contracts for reusable K12 scheduling products."""
from __future__ import annotations

from scheduler.domain.rule_instance import (
    CompiledRuleInstance,
    RuleInstance,
    compile_rule_instances,
    rule_instances_from_mapping,
    validate_rule_instances,
)
from scheduler.domain.profile_catalog import (
    ProfileCatalogEntry,
    ProfileCatalogIssue,
    ProfileCatalogValidation,
    profile_catalog_payload,
    validate_profile_catalog,
)
from scheduler.domain.personalized_rule_catalog import (
    PERSONALIZED_LEGACY_RULES,
    PERSONALIZED_RULE_INSTANCE_TEMPLATE_IDS,
    PERSONALIZED_TARGET_SLOTS,
    PersonalizedLegacyRule,
    PersonalizedTargetSlot,
    personalized_template_id,
    personalized_rule_catalog_payload,
)
from scheduler.domain.school_problem import (
    ClassSubjectTeacher,
    FixedClassSlot,
    ProblemSlot,
    SchoolProblem,
    SubjectBan,
    SubjectRequirement,
    school_problem_from_day_inputs,
    school_problem_from_mapping,
    school_problem_summary,
    validate_school_problem,
)
from scheduler.domain.school_profile import (
    CalendarSpec,
    PeriodGroup,
    PeriodSpec,
    SchoolProfile,
    default_high_school_profile,
    profile_from_legacy_config,
    profile_from_mapping,
    validate_school_profile,
)

__all__ = [
    "CalendarSpec",
    "CompiledRuleInstance",
    "ClassSubjectTeacher",
    "FixedClassSlot",
    "PeriodGroup",
    "PeriodSpec",
    "ProblemSlot",
    "PERSONALIZED_LEGACY_RULES",
    "PERSONALIZED_RULE_INSTANCE_TEMPLATE_IDS",
    "PERSONALIZED_TARGET_SLOTS",
    "PersonalizedLegacyRule",
    "PersonalizedTargetSlot",
    "ProfileCatalogEntry",
    "ProfileCatalogIssue",
    "ProfileCatalogValidation",
    "RuleInstance",
    "SchoolProblem",
    "SchoolProfile",
    "SubjectBan",
    "SubjectRequirement",
    "compile_rule_instances",
    "default_high_school_profile",
    "profile_from_legacy_config",
    "profile_from_mapping",
    "profile_catalog_payload",
    "personalized_template_id",
    "personalized_rule_catalog_payload",
    "rule_instances_from_mapping",
    "school_problem_from_day_inputs",
    "school_problem_from_mapping",
    "school_problem_summary",
    "validate_school_problem",
    "validate_rule_instances",
    "validate_profile_catalog",
    "validate_school_profile",
]
