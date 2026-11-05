from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class ScriptCheck:
    name: str
    argv: tuple[str, ...]
    requires_local_inputs: bool = False


PYTEST_GATE: tuple[str, ...] = (
    "verification/fixes/tests/test_requirements_min.py",
    "verification/fixes/tests/test_environment_verification.py",
    "verification/fixes/tests/test_pre_run_cleanup_guard.py",
    "verification/fixes/tests/test_time_limit_override.py",
    "verification/fixes/tests/test_seed_override.py",
    "verification/fixes/tests/test_loader_single_entry_guard.py",
    "verification/fixes/tests/test_loader_single_entry_strong_guard.py",
    "verification/fixes/tests/test_output_path_policy.py",
    "verification/fixes/tests/test_excel_export_policy.py",
    "verification/fixes/tests/test_module_decomposition.py",
    "verification/fixes/tests/test_calendar_scope_contract.py",
    "verification/fixes/tests/test_school_profile_contract.py",
    "verification/fixes/tests/test_ui_source_of_truth.py",
    "verification/fixes/tests/test_rule_instance_contract.py",
    "verification/fixes/tests/test_rule_v2.py",
    "verification/fixes/tests/test_course_scheduling.py",
    "verification/fixes/tests/test_school_problem_adapter.py",
    "verification/fixes/tests/test_rule_execution_plan.py",
    "verification/fixes/tests/test_profile_catalog_validation.py",
    "verification/fixes/tests/test_ai_or_framework.py",
    "verification/fixes/tests/test_ai_or_orchestration.py",
    "verification/fixes/tests/test_ai_or_acceptance_audit.py",
    "verification/fixes/tests/test_scheduler_generic_rule_bridge.py",
    "verification/fixes/tests/test_engineering_hygiene.py",
    "verification/fixes/tests/test_commercial_acceptance_audit.py",
    "verification/fixes/tests/test_run_evidence_writer.py",
    "verification/fixes/tests/test_explain_summary_writer.py",
    "verification/fixes/tests/test_explain_penalty_breakdown.py",
    "verification/fixes/tests/test_explain_summary_real_run_proof.py",
    "verification/fixes/tests/test_gate_no_traceback_noise.py",
    "verification/fixes/tests/test_rule_registry_skeleton.py",
    "verification/fixes/tests/test_rule_registry_apply_enabled.py",
    "verification/fixes/tests/test_rule_runtime_snapshots.py",
    "verification/fixes/tests/test_penalty_registry_metadata.py",
    "verification/fixes/tests/test_profile_overrides.py",
    "verification/fixes/tests/test_run_meta_mirror.py",
    "verification/fixes/tests/test_snapshot_diagnostics.py",
    "verification/fixes/tests/test_solve_readiness.py",
    "verification/fixes/tests/test_leave_log_local_repair.py",
    "verification/fixes/tests/test_manual_timetable_adjustment.py",
    "verification/fixes/tests/test_access_control.py",
    "verification/fixes/tests/test_formal_run_history.py",
    "verification/fixes/tests/test_formal_product_v2.py",
    "verification/fixes/tests/test_solver_params.py",
    "verification/fixes/tests/test_warm_start.py",
    "verification/fixes/tests/test_solve_runner_status.py",
    "verification/fixes/tests/test_solve_service_summary.py",
    "verification/fixes/tests/test_solve_diagnostics.py",
    "verification/fixes/tests/test_timed_snapshot_archive.py",
    "verification/fixes/tests/test_publish_assessment.py",
    "verification/fixes/tests/test_delivery_manifest.py",
    "verification/fixes/tests/test_checkin_same_day_class_mode.py",
    "verification/fixes/tests/test_day_night_link_modes.py",
    "verification/fixes/tests/test_diagnostic_relaxation.py",
    "verification/fixes/tests/test_infeasible_hint_filters.py",
    "verification/fixes/tests/test_result_preview.py",
    "verification/fixes/tests/test_web_rule_workspace.py",
    "verification/fixes/tests/test_productization_foundation.py",
    "verification/fixes/tests/test_saas_persistence.py",
    "verification/fixes/tests/test_saas_auth.py",
    "verification/fixes/tests/test_saas_jobs.py",
    "verification/fixes/tests/test_saas_model_usage.py",
    "verification/fixes/tests/test_saas_frontend.py",
    "verification/fixes/tests/test_conversational_scheduler.py",
    "verification/fixes/tests/test_saas_operations.py",
    "verification/fixes/tests/test_saas_deployment.py",
    "verification/fixes/tests/test_k12_academic_affairs_expansion.py",
    "verification/fixes/tests/test_dev_gate_manifest.py",
)


SCRIPT_GATE: tuple[ScriptCheck, ...] = (
    ScriptCheck(
        name="environment verification",
        argv=("verification/fixes/verify_environment.py", "--dev"),
    ),
    ScriptCheck(
        name="governance regression",
        argv=("scheduler/tests/governance_regression.py",),
    ),
    ScriptCheck(
        name="encoding regression",
        argv=("scheduler/tests/encoding_regression.py",),
    ),
    ScriptCheck(
        name="profile catalog validation",
        argv=("verification/fixes/validate_profiles.py",),
    ),
    ScriptCheck(
        name="AI OR framework acceptance audit",
        argv=("verification/fixes/ai_or_acceptance_audit.py",),
    ),
    ScriptCheck(
        name="deployment privacy audit",
        argv=("verification/fixes/deployment_privacy_audit.py",),
    ),
    ScriptCheck(
        name="single-school SaaS release-candidate audit",
        argv=("verification/fixes/saas_release_candidate_audit.py",),
    ),
    ScriptCheck(
        name="morning-reading smoke check",
        argv=("-m", "scheduler.day_morning_reading_smoke_test"),
    ),
    ScriptCheck(
        name="weekend scheduling smoke check",
        argv=("-m", "scheduler.day_weekend_smoke_test"),
    ),
)


LOCAL_SMOKE_GATE: tuple[ScriptCheck, ...] = (
    ScriptCheck(
        name="scheduler smoke check",
        argv=("-m", "scheduler.smoke_check"),
        requires_local_inputs=True,
    ),
)


def all_manifest_paths() -> tuple[str, ...]:
    paths = list(PYTEST_GATE)
    for check in (*SCRIPT_GATE, *LOCAL_SMOKE_GATE):
        first = check.argv[0]
        if first.endswith(".py"):
            paths.append(first)
    return tuple(paths)
