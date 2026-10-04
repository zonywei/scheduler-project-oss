from __future__ import annotations

from verification.fixes.ai_or_acceptance_audit import REPO_ROOT, build_audit
from scheduler.rules.generic_bridge import generic_scheduler_rule_contract_summary


def test_ai_or_acceptance_audit_passes_current_generic_framework_boundary() -> None:
    report = build_audit(REPO_ROOT)

    assert report["overall"] == "pass", report
    check_ids = {check["id"] for check in report["checks"]}
    assert {
        "generic_kernel_files",
        "agent_architecture_contract",
        "generic_solver_capabilities",
        "agent_orchestration_workflow",
        "scheduler_generic_rule_bridge",
        "scheduler_solver_controls_bridge",
        "scheduler_conflict_detection_generic_backend",
        "scheduler_exam_review_generic_backend",
        "release_boundary_hygiene",
        "open_source_deidentification",
        "documentation_positioning",
    } <= check_ids
    kernel_check = next(check for check in report["checks"] if check["id"] == "generic_kernel_files")
    assert "Automaton" in " ".join(kernel_check["evidence"])
    assert "Reservoir" in " ".join(kernel_check["evidence"])
    solver_check = next(check for check in report["checks"] if check["id"] == "generic_solver_capabilities")
    assert "table_element_status=OPTIMAL" in solver_check["evidence"]
    assert "arithmetic_status=OPTIMAL" in solver_check["evidence"]
    assert "control_search=FIXED_SEARCH" in solver_check["evidence"]
    assert "assumption_core=forced_bad_choice" in solver_check["evidence"]
    workflow_check = next(check for check in report["checks"] if check["id"] == "agent_orchestration_workflow")
    assert "workflow_status=OPTIMAL" in workflow_check["evidence"]
    scheduler_bridge_check = next(check for check in report["checks"] if check["id"] == "scheduler_generic_rule_bridge")
    assert "scheduler_bridge_status=OPTIMAL" in scheduler_bridge_check["evidence"]
    scope_summary = generic_scheduler_rule_contract_summary()
    assert (
        f"scheduler_bridge_contract_scope_exact_cp_sat_shape={scope_summary['exact_cp_sat_shape_contract']}"
        in scheduler_bridge_check["evidence"]
    )
    assert (
        f"scheduler_bridge_contract_scope_catalog={scope_summary['catalog_contract']}"
        in scheduler_bridge_check["evidence"]
    )
    solver_controls_check = next(check for check in report["checks"] if check["id"] == "scheduler_solver_controls_bridge")
    assert "scheduler_control_search=FIXED_SEARCH" in solver_controls_check["evidence"]
    assert "legacy_solver_ai_or_parameters=True" in solver_controls_check["evidence"]
    assert "legacy_solver_ai_or_adapter=existing_cp_model" in solver_controls_check["evidence"]
    assert "day_entry_ai_or_adapter=True" in solver_controls_check["evidence"]
    assert "night_entry_ai_or_adapter=True" in solver_controls_check["evidence"]
    assert "joint_pipeline_ai_or_adapter=True" in solver_controls_check["evidence"]
    assert "scheduler_model_factory_adapter=True" in solver_controls_check["evidence"]
    assert "scheduler_rule_operation_trace=True" in solver_controls_check["evidence"]
    assert "scheduler_rule_operation_summary=True" in solver_controls_check["evidence"]
    assert "scheduler_rule_migration_backlog=True" in solver_controls_check["evidence"]
    assert "scheduler_runtime_snapshot_migration_backlog=True" in solver_controls_check["evidence"]
    assert "scheduler_runtime_snapshot_operation_types=True" in solver_controls_check["evidence"]
    assert "scheduler_runtime_snapshot_candidate_specs=True" in solver_controls_check["evidence"]
    assert "scheduler_agent_migration_plan_roles=True" in solver_controls_check["evidence"]
    assert "scheduler_real_rule_generic_contract=True" in solver_controls_check["evidence"]
    assert "scheduler_day_one_subject_generic_contract=True" in solver_controls_check["evidence"]
    assert "scheduler_day_subject_hours_generic_contract=True" in solver_controls_check["evidence"]
    assert "scheduler_day_teacher_no_conflict_generic_contract=True" in solver_controls_check["evidence"]
    assert "scheduler_day_morning_reading_generic_contract=True" in solver_controls_check["evidence"]
    assert "scheduler_day_core_subject_teacher_day_load_generic_contract=True" in solver_controls_check["evidence"]
    assert "scheduler_day_teacher_weekday_am_pm_presence_generic_contract=True" in solver_controls_check["evidence"]
    assert "scheduler_day_head_pm1_min_generic_contract=True" in solver_controls_check["evidence"]
    assert "scheduler_day_two_class_low_hours_generic_contract=True" in solver_controls_check["evidence"]
    assert "scheduler_day_low_weekday_subject_generic_contract=True" in solver_controls_check["evidence"]
    assert "scheduler_day_high_weekday_subject_generic_contract=True" in solver_controls_check["evidence"]
    assert "scheduler_day_pe_time_window_generic_contract=True" in solver_controls_check["evidence"]
    assert "scheduler_day_teacher_whitelist_generic_contract=True" in solver_controls_check["evidence"]
    assert "scheduler_day_reduce_stem_am1_generic_contract=True" in solver_controls_check["evidence"]
    assert "scheduler_day_pe_reduce_am_soft_generic_contract=True" in solver_controls_check["evidence"]
    assert "scheduler_day_pref_lang_am_generic_contract=True" in solver_controls_check["evidence"]
    assert "scheduler_day_pe_tech_compact_soft_generic_contract=True" in solver_controls_check["evidence"]
    assert "scheduler_day_teacher_am4_pm1_threshold_generic_contract=True" in solver_controls_check["evidence"]
    assert "scheduler_day_weekday_subject_balance_generic_contract=True" in solver_controls_check["evidence"]
    assert "scheduler_day_teacher_continuity_generic_contract=True" in solver_controls_check["evidence"]
    assert "scheduler_day_two_class_daily_min_generic_contract=True" in solver_controls_check["evidence"]
    assert "scheduler_day_teacher_m1_cap_generic_contract=True" in solver_controls_check["evidence"]
    assert "scheduler_day_teacher_am1_fragmentation_generic_contract=True" in solver_controls_check["evidence"]
    assert "scheduler_day_multi_class_halfday_generic_contract=True" in solver_controls_check["evidence"]
    assert "scheduler_solver_parameter_rules_generic_contract=True" in solver_controls_check["evidence"]
    assert "scheduler_duty_joint_generic_contract=True" in solver_controls_check["evidence"]
    assert "scheduler_night_soft_objective_generic_contract=True" in solver_controls_check["evidence"]
    assert "scheduler_personalized_legacy_catalog_generic_contract=True" in solver_controls_check["evidence"]
    assert "scheduler_day_special_duty_catalog_generic_contract=True" in solver_controls_check["evidence"]
    assert "scheduler_grade_group_duty_generic_contract=True" in solver_controls_check["evidence"]
    assert "scheduler_day_weekend_subject_whitelist_generic_contract=True" in solver_controls_check["evidence"]
    assert "scheduler_day_weekend_double_period_generic_contract=True" in solver_controls_check["evidence"]
    assert "scheduler_day_weekend_cross_halfday_generic_contract=True" in solver_controls_check["evidence"]
    assert "scheduler_day_yjc_sunday_am12_pm12_generic_contract=True" in solver_controls_check["evidence"]
    assert "scheduler_day_binding_generic_contract=True" in solver_controls_check["evidence"]
    assert "scheduler_day_no_am1_am4_generic_contract=True" in solver_controls_check["evidence"]
    assert "scheduler_day_am1_pm1_mutex_generic_contract=True" in solver_controls_check["evidence"]
    assert "scheduler_day_two_class_am1_pm1_combo_generic_contract=True" in solver_controls_check["evidence"]
    assert "scheduler_day_am1_pm1_exclusive_generic_contract=True" in solver_controls_check["evidence"]
    assert "scheduler_day_single_class_weekly_am1_cap_generic_contract=True" in solver_controls_check["evidence"]
    assert "scheduler_day_no_consecutive_same_teacher_same_class_generic_contract=True" in solver_controls_check["evidence"]
    assert "scheduler_day_weekend_one_day_only_generic_contract=True" in solver_controls_check["evidence"]
    assert "scheduler_day_weekend_halfday_generic_contract=True" in solver_controls_check["evidence"]
    assert "scheduler_night_hard_bans_generic_contract=True" in solver_controls_check["evidence"]
    assert "scheduler_night_hard_teacher_limits_generic_contract=True" in solver_controls_check["evidence"]
    assert "scheduler_night_binding_generic_contract=True" in solver_controls_check["evidence"]
    assert "scheduler_night_physics_math_special_generic_contract=True" in solver_controls_check["evidence"]
    assert "scheduler_night_fri_sun_mutex_generic_contract=True" in solver_controls_check["evidence"]
    assert "scheduler_night_single_class_p1_p2_split_generic_contract=True" in solver_controls_check["evidence"]
    assert "scheduler_night_double_class_weekday_p1_p2_split_generic_contract=True" in solver_controls_check["evidence"]
    assert "scheduler_night_checkin_generic_contract=True" in solver_controls_check["evidence"]
    conflict_detection_check = next(
        check for check in report["checks"] if check["id"] == "scheduler_conflict_detection_generic_backend"
    )
    assert "conflict_detection_backend=ai_or" in conflict_detection_check["evidence"]
    exam_review_check = next(
        check for check in report["checks"] if check["id"] == "scheduler_exam_review_generic_backend"
    )
    assert "exam_review_backend=ai_or" in exam_review_check["evidence"]
    assert "exam_review_status=OPTIMAL" in exam_review_check["evidence"]
    deidentification_check = next(check for check in report["checks"] if check["id"] == "open_source_deidentification")
    assert "blocked_markers=0" in deidentification_check["evidence"]


def test_ai_or_acceptance_audit_source_does_not_publish_local_workspace_paths() -> None:
    source = (REPO_ROOT / "verification" / "fixes" / "ai_or_acceptance_audit.py").read_text(encoding="utf-8")
    local_user = "87" + "859"
    runtime_markers = (
        "C:" + "\\Users" + "\\" + local_user,
        "D:" + "\\1" + "\\github" + "开源",
    )
    local_markers = (local_user,) + runtime_markers + tuple(marker.replace("\\", "\\\\") for marker in runtime_markers)

    for marker in local_markers:
        assert marker not in source
