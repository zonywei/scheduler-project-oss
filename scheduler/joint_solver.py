# -*- coding: utf-8 -*-
from __future__ import annotations

import logging
import copy
import json
import time
from datetime import datetime
from pathlib import Path
from typing import List

from ortools.sat.python import cp_model

from ai_orchestrated_optimization import create_existing_cp_model
from scheduler.config.loader import load_effective_config, merge_section
from scheduler.data.day_rules_reader import load_day_inputs
from scheduler.data.teacher_table_reader import checkin_candidate_pool_available, read_teacher_table
from scheduler.data.teacher_table_schema import (
    configured_teacher_table_columns,
    head_gender_pools,
    load_teacher_table_frame,
)
from scheduler.model.day_variables import build_day_variables
from scheduler.model.variables import build_variables, build_checkin_variables
from scheduler.model.constraints.day_hard_one_per_slot import apply_one_subject_per_slot
from scheduler.model.constraints.day_hard_subject_hours import apply_subject_hour_constraints
from scheduler.model.constraints.day_hard_teacher_conflict import apply_teacher_no_conflict
from scheduler.model.constraints.day_weekend_constraints import (
    WeekendConfig,
    apply_weekend_subject_whitelist,
    apply_weekend_double_period_same_class,
    apply_weekend_one_day_only,
    apply_weekend_cross_halfday_penalty,
    apply_weekend_halfday_constraint,
    apply_yjc_sunday_am12_pm12_rule,
    check_weekend_feasibility_inputs,
    write_weekend_diagnostic,
)
from scheduler.day_constraints_morning_reading import (
    apply_morning_reading_constraints,
    extract_morning_reading_results,
    write_morning_reading_diagnostic,
    check_morning_reading_inputs,
)
from scheduler.model.constraints.day_weekday_constraints import (
    WeekdayConfig,
    build_audit_before,
    write_audit_before,
    load_head_teachers,
    get_pe_teachers,
    get_lang_teachers,
    apply_no_am1_am4,
    apply_core_subject_teacher_day_load_and_no_am1_am4,
    apply_no_consecutive_same_teacher_same_class,
    apply_head_pm1_min,
    apply_teacher_weekday_am_pm_presence,
    apply_pref_lang_am,
    apply_reduce_stem_am1,
    apply_teacher_am1_fragmentation,
    apply_two_class_daily_min_per_class,
    apply_two_class_low_hours_max_empty_days,
    apply_low_weekday_subject_max1_per_day,
    apply_high_weekday_subject_min1_per_day,
    apply_multi_class_halfday_soft,
    apply_teacher_am4_pm1_threshold_penalty,
    apply_teacher_continuity_penalty,
    apply_teacher_m1_cap_constraint,
    apply_am1_pm1_mutex,
    apply_two_class_am1_pm1_combo,
    apply_am1_pm1_exclusive,
    apply_single_class_weekly_am1_cap,
    apply_weekday_subject_balance,
    write_day_check_hard_constraints,
    write_day_constraint_checklist,
    write_teacher_continuity_report,
    write_teacher_am4_pm1_penalty_report,
    write_teacher_m1_cap_report,
    write_teacher_m1_cap_infeasible_hint,
    write_soft_timepref_audit,
    write_day_soft_timepref_report,
    write_two_class_daily_min_report,
    write_core_teacher_day_load_sanity,
    write_core_teacher_day_load_infeasible_hint,
    write_low_weekday_subject_max1_report,
    write_day_infeasible_hints,
)
from scheduler.model.constraints.day_pe_tech_constraints import (
    PeTechConfig,
    get_pe_tech_teachers,
    write_pe_tech_audit,
    apply_pe_time_window_hard,
    apply_teacher_whitelist_hard,
    apply_pe_reduce_am_soft,
    apply_pe_tech_compact_soft,
    write_pe_tech_checklist,
)
from scheduler.model.constraints.day_head_teacher_duty_constraints import (
    HeadDutyConfig,
    write_head_duty_audit_before,
    apply_head_duty_constraints,
    write_head_duty_vars_count,
    write_head_duty_hard_check,
    write_head_duty_soft_report,
    write_head_duty_infeasible_hints,
    extract_duty_results,
)
from scheduler.model.constraints.day_noon_dorm_duty_constraints import (
    NoonDormDutyConfig,
    apply_noon_dorm_duty_constraints,
    add_noon_night_checkin_coupling,
    add_noon_prev_same_day_no_night_class_constraints,
    write_noon_dorm_checklist,
    extract_noon_dorm_rows,
)
from scheduler.model.constraints.global_binding_constraints import (
    apply_global_day_binding_8_chem_9_bio,
    apply_global_night_binding_8_chem_9_bio,
)
from scheduler.model.constraints.duty_joint_constraints import (
    DutyJointConfig,
    add_duty_joint_constraints,
    write_duty_joint_audit,
    write_duty_joint_checklist,
)
from scheduler.model.constraints.grade_group_duty_constraints import (
    GradeGroupDutyConfig,
    apply_grade_group_duty_constraints,
    extract_grade_group_duty_map,
    extract_grade_group_available_map,
    write_grade_group_duty_audit,
    write_grade_group_duty_checklist,
)
from scheduler.model.constraints.hard_base import apply_hard_base
from scheduler.model.constraints.hard_bans import apply_hard_bans
from scheduler.model.constraints.checkin import apply_checkin
from scheduler.model.constraints.hard_teacher_limits import apply_hard_teacher_limits
from scheduler.model.constraints.night_special import (
    apply_physics_math_hard_bans,
    apply_fri_sun_mutex,
    write_night_constraints_audit,
    write_night_constraint_checklist,
    append_infeasible_audit,
)
from scheduler.model.constraints.night_single_class_period_split import (
    apply_single_class_teacher_p1_p2_split,
    apply_double_class_teacher_weekday_alternate_p1_p2,
    write_double_class_weekday_p1_p2_report,
)
from scheduler.model.constraints.soft_objective import apply_soft_objective
from scheduler.model.constraints.day_night_bridge import (
    LinkConfig,
    build_bridge_vars,
    add_link_constraints,
    write_link_audit,
    write_link_checklist,
)
from scheduler.model.constraints.personalized_constraints import (
    PersonalizedConfig,
    apply_personalized_constraints,
    write_personalized_checklist,
    write_personalized_infeasible_hints,
)
from scheduler.model.constraints.rule_v2 import apply_rule_v2_constraints
from scheduler.diagnostic_utils import move_diagnostics_to_folder, move_root_meta_files
from scheduler.joint_runtime import (
    CountingSolutionCallback,
    DayBuildResult,
    NightBuildResult,
    build_evening_assignments_from_solver,
)
from scheduler.joint_pipeline import (
    apply_joint_cross_model_constraints,
    apply_joint_warm_start_hints,
    build_and_apply_joint_objective,
    build_joint_artifact_config,
    export_joint_solution_outputs,
    finalize_joint_outputs,
    solve_joint_model,
    write_joint_diagnostics,
)
from scheduler.output_paths import resolve_output_dir, resolve_project_path
from scheduler.solver_params import apply_joint_solver_parameters
from scheduler.solver_callbacks.timed_snapshot_callback import (
    SnapshotExportConfig,
    SolutionArchiveConfig,
    TimedSnapshotExportCallback,
)
from scheduler.solver_quality import enrich_solver_overview
from scheduler.warm_start import (
    WarmStartConfig,
    compute_rules_data_hash,
    select_solution_file,
    save_best_solution_json,
    save_solution_json,
    load_solution_json,
    trim_solution_pool,
)
from scheduler.snapshot_diagnostics import build_multi_solution_diagnostic
from scheduler.diagnostics.penalty_registry import (
    clear_registry,
    register,
    summarize_event_log_csv,
    validate_registered_rule_meta,
    write_event_log_csv,
)
from scheduler.diagnostics.baseline_report import write_baseline_report
from scheduler.output.day_exporter_combo import save_day_class_and_teacher_summary_excel
from scheduler.output.day_exporter import export_day_schedule_df, export_day_schedule_grid_df, save_day_schedule_excel
from scheduler.output.value_maps import build_checkin_rows_from_solver
from scheduler.rules.runtime import bind_rule_wrappers_for_module
from scheduler.model.constraints.teacher_targets import teacher_names

logger = logging.getLogger(__name__)

bind_rule_wrappers_for_module(__name__, globals())


def build_day_model(
    model: cp_model.CpModel,
    io_path: Path,
    rules_path: Path,
    grade_prefix: str,
    ts: str,
    io_cfg: dict | None = None,
    rules_cfg: dict | None = None,
) -> DayBuildResult:
    if io_cfg is None or rules_cfg is None:
        effective = load_effective_config(
            "day",
            {"io_path": io_path, "rules_path": rules_path},
        )
        io_cfg = effective.io_cfg
        rules_cfg = effective.rules_cfg
    base_dir = io_path.parent.parent
    day_cfg = io_cfg.get("day", {})
    rules = base_dir / day_cfg.get("rules_path", "白天规则.xlsx")
    pos = base_dir / day_cfg.get("teacher_table_path", "教师定位表.xlsx")
    output_cfg = io_cfg.get("output", {})
    out_dir = resolve_output_dir(io_cfg, io_path)
    summary_name = output_cfg.get("day_summary_xlsx", "课表及值班安排.xlsx")
    formal_name = output_cfg.get("day_formal_xlsx", "白天课表_正式版.xlsx")
    weekend_cfg_raw = day_cfg.get("weekend_constraints", {}) or {}
    weekday_cfg_raw = day_cfg.get("weekday_constraints", {}) or {}
    _lang_tue_fri_target_teachers_raw = weekday_cfg_raw.get("lang_tue_fri_target_teachers", [])
    if isinstance(_lang_tue_fri_target_teachers_raw, str):
        _lang_tue_fri_target_teachers = [
            s.strip()
            for s in _lang_tue_fri_target_teachers_raw.replace("，", ",").split(",")
            if s.strip()
        ]
    elif isinstance(_lang_tue_fri_target_teachers_raw, (list, tuple, set)):
        _lang_tue_fri_target_teachers = [str(s).strip() for s in _lang_tue_fri_target_teachers_raw if str(s).strip()]
    else:
        _lang_tue_fri_target_teachers = []
    day_constraints_rules_raw = merge_section(io_cfg, rules_cfg, "day_constraints")
    pe_cfg_raw = day_cfg.get("pe_tech_constraints", {}) or {}
    head_duty_cfg_raw = day_cfg.get("head_duty_constraints", {}) or {}
    noon_cfg_raw = day_cfg.get("noon_dorm_duty", {}) or {}
    link_cfg_raw = merge_section(io_cfg, rules_cfg, "day_night_link")
    pers_cfg_raw = merge_section(io_cfg, rules_cfg, "personalized_constraints")
    personalized_rules_raw = pers_cfg_raw

    out_dir.mkdir(parents=True, exist_ok=True)

    data = load_day_inputs(
        str(rules),
        str(pos),
        io_cfg.get("web_tables"),
        teacher_columns=((io_cfg.get("teacher_table", {}) or {}).get("columns", {}) or {}),
    )
    dv = build_day_variables(model, data)
    apply_one_subject_per_slot(model, data, dv)
    apply_subject_hour_constraints(model, data, dv)
    apply_teacher_no_conflict(model, data, dv)

    audit_info = build_audit_before(data, io_cfg, base_dir)
    write_audit_before(out_dir, audit_info)

    head_teachers = load_head_teachers(io_cfg, base_dir)
    _class_col, head_col, gender_col = configured_teacher_table_columns(io_cfg)
    teacher_frame = load_teacher_table_frame(io_cfg, base_dir)
    table_male_heads, table_female_heads = head_gender_pools(
        teacher_frame,
        head_col=head_col,
        gender_col=gender_col,
        strict_gender=False,
    )
    has_head_gender_pools = bool(table_male_heads and table_female_heads)
    pe_teachers = get_pe_teachers(data)
    pe_tech_teachers = get_pe_tech_teachers(data)

    mr_ctx, mr_errors = check_morning_reading_inputs(data)
    if mr_errors:
        write_morning_reading_diagnostic(out_dir, mr_ctx, "INVALID_INPUT", errors=mr_errors)
        raise ValueError("; ".join(mr_errors))
    apply_morning_reading_constraints(model, data, dv)

    weekend_cfg = WeekendConfig(
        enable_weekend_subject_whitelist=weekend_cfg_raw.get("enable_weekend_subject_whitelist", True),
        enable_weekend_double_period_same_class=weekend_cfg_raw.get("enable_weekend_double_period_same_class", True),
        enable_weekend_one_day_only=weekend_cfg_raw.get("enable_weekend_one_day_only", True),
        enable_weekend_cross_halfday_penalty=weekend_cfg_raw.get("enable_weekend_cross_halfday_penalty", True),
        cross_halfday_penalty=int(weekend_cfg_raw.get("cross_halfday_penalty", 200)),
        enable_yjc_sun_cross_halfday_exempt=bool(weekend_cfg_raw.get("enable_yjc_sun_cross_halfday_exempt", True)),
        enable_yjc_sun_am12_pm12_rule=bool(weekend_cfg_raw.get("enable_yjc_sun_am12_pm12_rule", True)),
        yjc_sun_am12_pm12_mode=str(weekend_cfg_raw.get("yjc_sun_am12_pm12_mode", "hard")),
        w_yjc_sun_am12_pm12=int(weekend_cfg_raw.get("w_yjc_sun_am12_pm12", 1000)),
        sun_cross_halfday_exempt_teachers=teacher_names(weekend_cfg_raw.get("sun_cross_halfday_exempt_teachers", [])),
        sunday_am12_pm12_teachers=teacher_names(weekend_cfg_raw.get("sunday_am12_pm12_teachers", [])),
        enable_weekend_halfday_constraint=bool(day_constraints_rules_raw.get("enable_weekend_halfday_constraint", weekend_cfg_raw.get("enable_weekend_halfday_constraint", True))),
        weekend_halfday_mode=str(day_constraints_rules_raw.get("weekend_halfday_mode", weekend_cfg_raw.get("weekend_halfday_mode", "hard"))),
        w_weekend_halfday=int(day_constraints_rules_raw.get("w_weekend_halfday", weekend_cfg_raw.get("w_weekend_halfday", 3000))),
    )

    diag = check_weekend_feasibility_inputs(data)
    if weekend_cfg.enable_weekend_subject_whitelist:
        apply_weekend_subject_whitelist(model, data, dv)
    if weekend_cfg.enable_weekend_double_period_same_class:
        apply_weekend_double_period_same_class(model, data, dv)
    if weekend_cfg.enable_weekend_one_day_only:
        apply_weekend_one_day_only(model, data, dv)
    weekend_penalties = []
    if weekend_cfg.enable_weekend_cross_halfday_penalty:
        weekend_penalties = apply_weekend_cross_halfday_penalty(
            model,
            data,
            dv,
            weekend_cfg.cross_halfday_penalty,
            yjc_sun_exempt=weekend_cfg.enable_yjc_sun_cross_halfday_exempt,
            sun_exempt_teachers=weekend_cfg.sun_cross_halfday_exempt_teachers,
        )
    weekend_halfday_penalties = apply_weekend_halfday_constraint(
        model,
        data,
        dv,
        enabled=weekend_cfg.enable_weekend_halfday_constraint,
        mode=weekend_cfg.weekend_halfday_mode,
        weight=weekend_cfg.w_weekend_halfday,
    )
    yjc_sun_am12_pm12_penalties = apply_yjc_sunday_am12_pm12_rule(
        model,
        data,
        dv,
        enabled=weekend_cfg.enable_yjc_sun_am12_pm12_rule,
        mode=weekend_cfg.yjc_sun_am12_pm12_mode,
        teachers=weekend_cfg.sunday_am12_pm12_teachers,
    )

    weekday_cfg = WeekdayConfig(
        enable_binding_chem_bio=weekday_cfg_raw.get("enable_binding_chem_bio", True),
        enable_no_am1_am4=weekday_cfg_raw.get("enable_no_am1_am4", True),
        enable_core_teacher_day_load_limit=weekday_cfg_raw.get("enable_core_teacher_day_load_limit", True),
        enable_no_consecutive_same_teacher_same_class=weekday_cfg_raw.get("enable_no_consecutive_same_teacher_same_class", True),
        enable_head_pm1_min=bool(weekday_cfg_raw.get("enable_head_pm1_min", True)) and bool(head_teachers),
        enable_teacher_weekday_am_pm_presence=weekday_cfg_raw.get("enable_teacher_weekday_am_pm_presence", True),
        enable_pref_lang_am=weekday_cfg_raw.get("enable_pref_lang_am", True),
        enable_reduce_stem_am1=weekday_cfg_raw.get("enable_reduce_stem_am1", True),
        enable_teacher_am1_fragmentation=weekday_cfg_raw.get("enable_teacher_am1_fragmentation", True),
        enable_two_class_daily_min_per_class=weekday_cfg_raw.get("enable_two_class_daily_min_per_class", True),
        enable_two_class_low_hours_max_empty_days=weekday_cfg_raw.get("enable_two_class_low_hours_max_empty_days", True),
        enable_low_weekday_subject_max1_per_day=weekday_cfg_raw.get("enable_low_weekday_subject_max1_per_day", True),
        enable_high_weekday_subject_min1_per_day=weekday_cfg_raw.get("enable_high_weekday_subject_min1_per_day", True),
        enable_multi_class_halfday=weekday_cfg_raw.get("enable_multi_class_halfday", True),
        enable_teacher_am4_pm1_threshold_penalty=weekday_cfg_raw.get("enable_teacher_am4_pm1_threshold_penalty", True),
        enable_teacher_continuity_penalty=weekday_cfg_raw.get("enable_teacher_continuity_penalty", True),
        enable_teacher_m1_cap_constraint=weekday_cfg_raw.get("enable_teacher_m1_cap_constraint", True),
        enable_balance_weekday_subject_hours=weekday_cfg_raw.get("enable_balance_weekday_subject_hours", True),
        enable_am1_pm1_mutex=day_constraints_rules_raw.get("enable_am1_pm1_mutex", weekday_cfg_raw.get("enable_am1_pm1_mutex", True)),
        am1_pm1_mutex_mode=str(day_constraints_rules_raw.get("am1_pm1_mutex_mode", weekday_cfg_raw.get("am1_pm1_mutex_mode", "hard"))),
        w_am1_pm1_mutex=int(day_constraints_rules_raw.get("w_am1_pm1_mutex", weekday_cfg_raw.get("w_am1_pm1_mutex", 3000))),
        enable_two_class_am1_pm1_combo=day_constraints_rules_raw.get("enable_two_class_am1_pm1_combo", weekday_cfg_raw.get("enable_two_class_am1_pm1_combo", True)),
        two_class_am1_pm1_combo_mode=str(day_constraints_rules_raw.get("two_class_am1_pm1_combo_mode", weekday_cfg_raw.get("two_class_am1_pm1_combo_mode", "hard"))),
        w_two_class_am1_pm1_combo=int(day_constraints_rules_raw.get("w_two_class_am1_pm1_combo", weekday_cfg_raw.get("w_two_class_am1_pm1_combo", 3000))),
        enable_am1_pm1_exclusive=day_constraints_rules_raw.get("enable_am1_pm1_exclusive", weekday_cfg_raw.get("enable_am1_pm1_exclusive", True)),
        am1_pm1_exclusive_mode=str(day_constraints_rules_raw.get("am1_pm1_exclusive_mode", weekday_cfg_raw.get("am1_pm1_exclusive_mode", "hard"))),
        w_am1_pm1_exclusive=int(day_constraints_rules_raw.get("w_am1_pm1_exclusive", weekday_cfg_raw.get("w_am1_pm1_exclusive", 3000))),
        enable_single_class_weekly_am1_cap=day_constraints_rules_raw.get("enable_single_class_weekly_am1_cap", weekday_cfg_raw.get("enable_single_class_weekly_am1_cap", True)),
        single_class_weekly_am1_cap_max=int(day_constraints_rules_raw.get("single_class_weekly_am1_cap_max", weekday_cfg_raw.get("single_class_weekly_am1_cap_max", 2))),
        balance_weekday_subject_hours_mode=weekday_cfg_raw.get("balance_weekday_subject_hours_mode", "soft"),
        core_teacher_day_load_max=int(weekday_cfg_raw.get("core_teacher_day_load_max", 3)),
        w_lang_pm_penalty=int(weekday_cfg_raw.get("w_lang_pm_penalty", 200)),
        w_lang_am_reward=int(weekday_cfg_raw.get("w_lang_am_reward", 0)),
        enable_lang_tue_fri_preferences=bool(weekday_cfg_raw.get("enable_lang_tue_fri_preferences", True)),
        enable_lang_tue_fri_am1_penalty_exempt=bool(weekday_cfg_raw.get("enable_lang_tue_fri_am1_penalty_exempt", True)),
        lang_tue_fri_target_teachers=_lang_tue_fri_target_teachers,
        w_lang_tue_fri_am1_reward=int(weekday_cfg_raw.get("w_lang_tue_fri_am1_reward", 200)),
        w_lang_tue_fri_pm1_penalty=int(weekday_cfg_raw.get("w_lang_tue_fri_pm1_penalty", 4500)),
        w_lang_tue_fri_pm2_penalty=int(weekday_cfg_raw.get("w_lang_tue_fri_pm2_penalty", 3000)),
        w_lang_tue_fri_pm3_penalty=int(weekday_cfg_raw.get("w_lang_tue_fri_pm3_penalty", 2000)),
        w_stem_am1_penalty=int(weekday_cfg_raw.get("w_stem_am1_penalty", 250)),
        w_teacher_only_am1_day=int(weekday_cfg_raw.get("w_teacher_only_am1_day", 300)),
        k_teacher_am1_week=int(weekday_cfg_raw.get("k_teacher_am1_week", 2)),
        w_teacher_am1_excess=int(weekday_cfg_raw.get("w_teacher_am1_excess", 150)),
        w_two_class_daily_min_per_class=int(weekday_cfg_raw.get("w_two_class_daily_min_per_class", 300)),
        two_class_low_hours_threshold=int(weekday_cfg_raw.get("two_class_low_hours_threshold", 5)),
        two_class_max_empty_days=int(weekday_cfg_raw.get("two_class_max_empty_days", 1)),
        low_weekday_subject_max1_threshold=int(weekday_cfg_raw.get("low_weekday_subject_max1_threshold", 4)),
        high_weekday_subject_min1_threshold=int(weekday_cfg_raw.get("high_weekday_subject_min1_threshold", 5)),
        two_class_daily_min_mode=weekday_cfg_raw.get("two_class_daily_min_mode", "soft"),
        weight_multi_class_halfday=int(weekday_cfg_raw.get("weight_multi_class_halfday", 300)),
        teacher_am4_pm1_w3=int(weekday_cfg_raw.get("teacher_am4_pm1_w3", 50)),
        teacher_am4_pm1_w4=int(weekday_cfg_raw.get("teacher_am4_pm1_w4", 100)),
        teacher_am4_pm1_w5=int(weekday_cfg_raw.get("teacher_am4_pm1_w5", 200)),
        teacher_am4_pm1_w6=int(weekday_cfg_raw.get("teacher_am4_pm1_w6", 400)),
        teacher_continuity_gap_weight=int(weekday_cfg_raw.get("teacher_continuity_gap_weight", 250)),
        teacher_m1_cap_max=int(weekday_cfg_raw.get("teacher_m1_cap_max", 3)),
        w_hit_m1_cap=int(weekday_cfg_raw.get("w_hit_m1_cap", 500)),
        weight_balance_weekday_subject_hours=int(weekday_cfg_raw.get("weight_balance_weekday_subject_hours", 150)),
    )

    pe_cfg = PeTechConfig(
        enable_pe_time_window_hard=pe_cfg_raw.get("enable_pe_time_window_hard", True),
        enable_pe_reduce_am=pe_cfg_raw.get("enable_pe_reduce_am", True),
        enable_pe_tech_compact=pe_cfg_raw.get("enable_pe_tech_compact", True),
        w_pe_am_penalty=int(pe_cfg_raw.get("w_pe_am_penalty", 200)),
        w_pe_gap_penalty=int(pe_cfg_raw.get("w_pe_gap_penalty", 200)),
    )

    head_duty_w_pm1 = int(head_duty_cfg_raw.get("w_pm1_penalty", head_duty_cfg_raw.get("w_excess_pm1", 120)))
    head_duty_weekday_pm1_requires_duty_exempt_raw = head_duty_cfg_raw.get(
        "weekday_pm1_requires_duty_exempt_teachers",
        [],
    )
    if isinstance(head_duty_weekday_pm1_requires_duty_exempt_raw, str):
        head_duty_weekday_pm1_requires_duty_exempt = tuple(
            s.strip()
            for s in head_duty_weekday_pm1_requires_duty_exempt_raw.replace("，", ",").split(",")
            if s.strip()
        )
    elif isinstance(head_duty_weekday_pm1_requires_duty_exempt_raw, (list, tuple, set)):
        head_duty_weekday_pm1_requires_duty_exempt = tuple(
            str(s).strip() for s in head_duty_weekday_pm1_requires_duty_exempt_raw if str(s).strip()
        )
    else:
        head_duty_weekday_pm1_requires_duty_exempt = ()
    head_duty_cfg = HeadDutyConfig(
        enable_head_duty=bool(head_duty_cfg_raw.get("enable_head_duty", True)) and bool(head_teachers),
        w_pm1_penalty=head_duty_w_pm1,
        w_excess_pm1=head_duty_w_pm1,
        w_excess_duty=int(head_duty_cfg_raw.get("w_excess_duty", 0)),
        enable_pm1_min_if_missing=head_duty_cfg_raw.get("enable_pm1_min_if_missing", True),
        k_pm1_excess=int(head_duty_cfg_raw.get("k_pm1_excess", 2)),
        enable_weekday_pm1_requires_duty=bool(head_duty_cfg_raw.get("enable_weekday_pm1_requires_duty", True)),
        weekday_pm1_requires_duty_mode=str(head_duty_cfg_raw.get("weekday_pm1_requires_duty_mode", "hard")),
        w_weekday_pm1_requires_duty=int(head_duty_cfg_raw.get("w_weekday_pm1_requires_duty", 5000)),
        weekday_pm1_requires_duty_exempt_teachers=head_duty_weekday_pm1_requires_duty_exempt,
    )
    noon_cfg = NoonDormDutyConfig(
        enabled=bool(noon_cfg_raw.get("enabled", True)) and has_head_gender_pools,
        w_need_am4_lvl3=int(noon_cfg_raw.get("w_need_am4_lvl3", 200)),
        w_need_am4_lvl2=int(noon_cfg_raw.get("w_need_am4_lvl2", 400)),
        w_need_am4_lvl1=int(noon_cfg_raw.get("w_need_am4_lvl1", 800)),
        w_need_am4_lvl0=int(noon_cfg_raw.get("w_need_am4_lvl0", 1000)),
        w_noon_with_pm1=int(noon_cfg_raw.get("w_noon_with_pm1", 300)),
        w_female_noon_night_checkin=int(noon_cfg_raw.get("w_female_noon_night_checkin", 1000)),
        lhj_noon_ban_mode=str(noon_cfg_raw.get("lhj_noon_ban_mode", "hard")),
        w_lhj_noon_ban=int(noon_cfg_raw.get("w_lhj_noon_ban", 1000)),
        zeng_noon_ban_mode=str(noon_cfg_raw.get("zeng_noon_ban_mode", "hard")),
        w_zeng_noon_ban=int(noon_cfg_raw.get("w_zeng_noon_ban", 3000)),
        noon_exclude_teachers=teacher_names(noon_cfg_raw.get("noon_exclude_teachers", [])),
        male_candidate_extra_teachers=teacher_names(noon_cfg_raw.get("male_candidate_extra_teachers", [])),
        noon_disallow_teachers=teacher_names(noon_cfg_raw.get("noon_disallow_teachers", [])),
        saturday_fixed_female_teachers=teacher_names(noon_cfg_raw.get("saturday_fixed_female_teachers", [])),
        special_male_noon_max1_teachers=teacher_names(noon_cfg_raw.get("special_male_noon_max1_teachers", [])),
        lhj_noon_ban_teachers=teacher_names(noon_cfg_raw.get("lhj_noon_ban_teachers", [])),
        zeng_noon_ban_teachers=teacher_names(noon_cfg_raw.get("zeng_noon_ban_teachers", [])),
        noon_am_link_teachers=teacher_names(noon_cfg_raw.get("noon_am_link_teachers", [])),
    )

    link_cfg = LinkConfig(
        enable_day_night_link=link_cfg_raw.get("enable_day_night_link", True),
        w1=int(link_cfg_raw.get("w1", 50)),
        enable_night_requires_day=bool(link_cfg_raw.get("enable_night_requires_day", True)),
        night_requires_day_mode=str(link_cfg_raw.get("night_requires_day_mode", "hard")),
        w_night_requires_day=int(link_cfg_raw.get("w_night_requires_day", 3000)),
        enable_sun_night_no_mon_am1=bool(link_cfg_raw.get("enable_sun_night_no_mon_am1", True)),
        sun_night_no_mon_am1_mode=str(link_cfg_raw.get("sun_night_no_mon_am1_mode", "hard")),
        w_sun_night_no_mon_am1=int(link_cfg_raw.get("w_sun_night_no_mon_am1", 2000)),
        enable_sun_pm_night_no_mon_am=bool(link_cfg_raw.get("enable_sun_pm_night_no_mon_am", True)),
        sun_pm_night_no_mon_am_mode=str(link_cfg_raw.get("sun_pm_night_no_mon_am_mode", "hard")),
        w_sun_pm_night_no_mon_am=int(link_cfg_raw.get("w_sun_pm_night_no_mon_am", 2000)),
        w3=int(link_cfg_raw.get("w3", 200)),
        heavy_load=int(link_cfg_raw.get("heavy_load", 4)),
        w4=int(link_cfg_raw.get("w4", 120)),
        enable_two_class_empty_day_no_night=link_cfg_raw.get("enable_two_class_empty_day_no_night", True),
        w_two_class_empty_day_no_night=int(link_cfg_raw.get("w_two_class_empty_day_no_night", 200)),
        weekday_load2_no_night_teachers=teacher_names(link_cfg_raw.get("weekday_load2_no_night_teachers", [])),
    )
    pers_cfg = PersonalizedConfig(
        enabled=pers_cfg_raw.get("enabled", True),
        teacher_targets=pers_cfg_raw.get("teacher_targets", pers_cfg_raw.get("targets", {})) or {},
        enable_xhd_night_no_pm3=pers_cfg_raw.get("enable_xhd_night_no_pm3", True),
        xhd_night_no_pm3_mode=str(pers_cfg_raw.get("xhd_night_no_pm3_mode", "soft")),
        w_xhd_night_no_pm3=int(pers_cfg_raw.get("w_xhd_night_no_pm3", 150)),
        enable_xhd_night_no_pm=personalized_rules_raw.get("enable_xhd_night_no_pm", pers_cfg_raw.get("enable_xhd_night_no_pm", True)),
        xhd_night_no_pm_mode=str(personalized_rules_raw.get("xhd_night_no_pm_mode", pers_cfg_raw.get("xhd_night_no_pm_mode", "hard"))),
        w_xhd_night_no_pm=int(personalized_rules_raw.get("w_xhd_night_no_pm", pers_cfg_raw.get("w_xhd_night_no_pm", 3000))),
        enable_couple_xhd_zfy=pers_cfg_raw.get("enable_couple_xhd_zfy", True),
        couple_xhd_zfy_mode=str(pers_cfg_raw.get("couple_xhd_zfy_mode", "soft")),
        w_couple_diff_day=int(pers_cfg_raw.get("w_couple_diff_day", 200)),
        w_couple_need_overlap=int(pers_cfg_raw.get("w_couple_need_overlap", 5000)),
        enable_zw_night_need_pm=pers_cfg_raw.get("enable_zw_night_need_pm", True),
        zw_night_need_pm_mode=str(pers_cfg_raw.get("zw_night_need_pm_mode", "hard")),
        w_zw_night_need_pm=int(pers_cfg_raw.get("w_zw_night_need_pm", 3000)),
        enable_zw_am1_cap=pers_cfg_raw.get("enable_zw_am1_cap", True),
        zw_am1_cap_mode=str(pers_cfg_raw.get("zw_am1_cap_mode", "hard")),
        zw_am1_slot_key=str(pers_cfg_raw.get("zw_am1_slot_key", "上午1")),
        zw_am1_cap_max=int(pers_cfg_raw.get("zw_am1_cap_max", 1)),
        w_zw_am1_cap=int(pers_cfg_raw.get("w_zw_am1_cap", 3000)),
        enable_zw_am2_cap=pers_cfg_raw.get("enable_zw_am2_cap", True),
        zw_am2_cap_mode=str(pers_cfg_raw.get("zw_am2_cap_mode", "hard")),
        zw_am2_slot_key=str(pers_cfg_raw.get("zw_am2_slot_key", "上午2")),
        zw_am2_cap_max=int(pers_cfg_raw.get("zw_am2_cap_max", 2)),
        w_zw_am2_cap=int(pers_cfg_raw.get("w_zw_am2_cap", 3000)),
        enable_zw_am4_cap=pers_cfg_raw.get("enable_zw_am4_cap", True),
        zw_am4_cap_mode=str(pers_cfg_raw.get("zw_am4_cap_mode", "hard")),
        zw_am4_slot_key=str(pers_cfg_raw.get("zw_am4_slot_key", "上午4")),
        zw_am4_cap_max=int(pers_cfg_raw.get("zw_am4_cap_max", 1)),
        w_zw_am4_cap=int(pers_cfg_raw.get("w_zw_am4_cap", 3000)),
        enable_zw_weekday_pm1_cap=personalized_rules_raw.get("enable_zw_weekday_pm1_cap", pers_cfg_raw.get("enable_zw_weekday_pm1_cap", True)),
        zw_weekday_pm1_cap_mode=str(personalized_rules_raw.get("zw_weekday_pm1_cap_mode", pers_cfg_raw.get("zw_weekday_pm1_cap_mode", "hard"))),
        zw_weekday_pm1_slot_key=str(personalized_rules_raw.get("zw_weekday_pm1_slot_key", pers_cfg_raw.get("zw_weekday_pm1_slot_key", "下午1"))),
        zw_weekday_pm1_cap_max=int(personalized_rules_raw.get("zw_weekday_pm1_cap_max", pers_cfg_raw.get("zw_weekday_pm1_cap_max", 2))),
        w_zw_weekday_pm1_cap=int(personalized_rules_raw.get("w_zw_weekday_pm1_cap", pers_cfg_raw.get("w_zw_weekday_pm1_cap", 3000))),
        enable_lm_sun_am12=pers_cfg_raw.get("enable_lm_sun_am12", True),
        lm_sun_am12_mode=str(pers_cfg_raw.get("lm_sun_am12_mode", "soft")),
        w_lm_sun_am12=int(pers_cfg_raw.get("w_lm_sun_am12", 400)),
        enable_ytt_sun_pref=pers_cfg_raw.get("enable_ytt_sun_pref", True),
        ytt_sun_pref_mode=str(pers_cfg_raw.get("ytt_sun_pref_mode", "soft")),
        w_ytt_sun_am_pref=int(pers_cfg_raw.get("w_ytt_sun_am_pref", 60)),
        w_ytt_no_sun_night=int(pers_cfg_raw.get("w_ytt_no_sun_night", 80)),
        enable_dym_no_fri_sun_night=pers_cfg_raw.get("enable_dym_no_fri_sun_night", True),
        enable_pol_no_sun_night=pers_cfg_raw.get("enable_pol_no_sun_night", True),
        pol_no_sun_night_mode=str(pers_cfg_raw.get("pol_no_sun_night_mode", "soft")),
        w_pol_sun_teacher_count=int(pers_cfg_raw.get("w_pol_sun_teacher_count", 300)),
        w_pol_sun_super=int(pers_cfg_raw.get("w_pol_sun_super", 600)),
        enable_ld_reduce_pm=pers_cfg_raw.get("enable_ld_reduce_pm", True),
        ld_reduce_pm_mode=str(pers_cfg_raw.get("ld_reduce_pm_mode", "soft")),
        w_ld_reduce_pm=int(pers_cfg_raw.get("w_ld_reduce_pm", 80)),
        enable_ld_tue_fri_pm_penalty=pers_cfg_raw.get("enable_ld_tue_fri_pm_penalty", True),
        w_ld_tue_fri_pm_each=int(pers_cfg_raw.get("w_ld_tue_fri_pm_each", 5000)),
        w_ld_tue_fri_pm1_extra_each=int(pers_cfg_raw.get("w_ld_tue_fri_pm1_extra_each", 6000)),
        enable_ld_no_mon_pm=personalized_rules_raw.get("enable_ld_no_mon_pm", pers_cfg_raw.get("enable_ld_no_mon_pm", True)),
        enable_zfj_ban_mon_fri_pm3=pers_cfg_raw.get("enable_zfj_ban_mon_fri_pm3", True),
        enable_zfj_night_checkin_penalty=pers_cfg_raw.get("enable_zfj_night_checkin_penalty", True),
        w_zfj_night_checkin_penalty=int(pers_cfg_raw.get("w_zfj_night_checkin_penalty", 1000)),
        enable_jxq_prefs=pers_cfg_raw.get("enable_jxq_prefs", True),
        jxq_prefs_mode=str(pers_cfg_raw.get("jxq_prefs_mode", "soft")),
        w_jxq_no_mon_am1=int(pers_cfg_raw.get("w_jxq_no_mon_am1", 80)),
        w_jxq_sun_pm_pref=int(pers_cfg_raw.get("w_jxq_sun_pm_pref", 60)),
        w_jxq_no_sun_night=int(pers_cfg_raw.get("w_jxq_no_sun_night", 150)),
        enable_csqi_prefs=pers_cfg_raw.get("enable_csqi_prefs", True),
        csqi_prefs_mode=str(pers_cfg_raw.get("csqi_prefs_mode", "soft")),
        w_csqi_sun_am_pref=int(pers_cfg_raw.get("w_csqi_sun_am_pref", 60)),
        w_csqi_night_outside_pen=int(pers_cfg_raw.get("w_csqi_night_outside_pen", 120)),
        w_csqi_need_sun_or_mon=int(pers_cfg_raw.get("w_csqi_need_sun_or_mon", 80)),
        enable_csqi_need_consecutive_night=pers_cfg_raw.get("enable_csqi_need_consecutive_night", True),
        csqi_need_consecutive_night_mode=str(pers_cfg_raw.get("csqi_need_consecutive_night_mode", "hard")),
        w_csqi_need_consecutive_night=int(pers_cfg_raw.get("w_csqi_need_consecutive_night", 3000)),
        enable_zzx_prefs=pers_cfg_raw.get("enable_zzx_prefs", True),
        zzx_prefs_mode=str(pers_cfg_raw.get("zzx_prefs_mode", "soft")),
        w_zzx_no_sun_night=int(pers_cfg_raw.get("w_zzx_no_sun_night", 220)),
        w_zzx_sun_am_pref=int(pers_cfg_raw.get("w_zzx_sun_am_pref", 70)),
        w_zzx_reduce_am4=int(pers_cfg_raw.get("w_zzx_reduce_am4", 60)),
        enable_zzx_no_sunday_night=personalized_rules_raw.get("enable_zzx_no_sunday_night", pers_cfg_raw.get("enable_zzx_no_sunday_night", True)),
        zzx_no_sunday_night_mode=str(personalized_rules_raw.get("zzx_no_sunday_night_mode", pers_cfg_raw.get("zzx_no_sunday_night_mode", "hard"))),
        w_zzx_no_sunday_night=int(personalized_rules_raw.get("w_zzx_no_sunday_night", pers_cfg_raw.get("w_zzx_no_sunday_night", 3000))),
        enable_xyx_night_days_only=personalized_rules_raw.get("enable_xyx_night_days_only", pers_cfg_raw.get("enable_xyx_night_days_only", True)),
        xyx_night_days_only_mode=str(personalized_rules_raw.get("xyx_night_days_only_mode", pers_cfg_raw.get("xyx_night_days_only_mode", "hard"))),
        xyx_night_allowed_days=[
            str(x).strip()
            for x in (
                personalized_rules_raw.get("xyx_night_allowed_days", pers_cfg_raw.get("xyx_night_allowed_days", ["星期五", "星期日"]))
                if isinstance(
                    personalized_rules_raw.get("xyx_night_allowed_days", pers_cfg_raw.get("xyx_night_allowed_days", ["星期五", "星期日"])),
                    (list, tuple, set),
                )
                else [personalized_rules_raw.get("xyx_night_allowed_days", pers_cfg_raw.get("xyx_night_allowed_days", ["星期五", "星期日"]))]
            )
            if str(x).strip()
        ],
        w_xyx_night_days_only=int(personalized_rules_raw.get("w_xyx_night_days_only", pers_cfg_raw.get("w_xyx_night_days_only", 2000))),
        enable_hwj_prefs=pers_cfg_raw.get("enable_hwj_prefs", True),
        hwj_prefs_mode=str(pers_cfg_raw.get("hwj_prefs_mode", "soft")),
        w_hwj_need_sun_mon=int(pers_cfg_raw.get("w_hwj_need_sun_mon", 220)),
        w_hwj_need_consecutive=int(pers_cfg_raw.get("w_hwj_need_consecutive", 120)),
        enable_hwj_night_sun_mon_assign=pers_cfg_raw.get("enable_hwj_night_sun_mon_assign", True),
        hwj_night_sun_mon_assign_mode=str(pers_cfg_raw.get("hwj_night_sun_mon_assign_mode", "hard")),
        w_hwj_night_sun_mon_assign=int(pers_cfg_raw.get("w_hwj_night_sun_mon_assign", 2000)),
        enable_hsm_no_fri_night=pers_cfg_raw.get("enable_hsm_no_fri_night", True),
        hsm_no_fri_night_mode=str(pers_cfg_raw.get("hsm_no_fri_night_mode", "soft")),
        w_hsm_no_fri_night=int(pers_cfg_raw.get("w_hsm_no_fri_night", 80)),
        enable_hsm_weekday_early_no_am1=personalized_rules_raw.get("enable_hsm_weekday_early_no_am1", pers_cfg_raw.get("enable_hsm_weekday_early_no_am1", True)),
        hsm_weekday_early_no_am1_mode=str(personalized_rules_raw.get("hsm_weekday_early_no_am1_mode", pers_cfg_raw.get("hsm_weekday_early_no_am1_mode", "hard"))),
        w_hsm_weekday_early_no_am1=int(personalized_rules_raw.get("w_hsm_weekday_early_no_am1", pers_cfg_raw.get("w_hsm_weekday_early_no_am1", 2000))),
        enable_wxl_weekday_early_no_am1=personalized_rules_raw.get("enable_wxl_weekday_early_no_am1", pers_cfg_raw.get("enable_wxl_weekday_early_no_am1", True)),
        wxl_weekday_early_no_am1_mode=str(personalized_rules_raw.get("wxl_weekday_early_no_am1_mode", pers_cfg_raw.get("wxl_weekday_early_no_am1_mode", "hard"))),
        w_wxl_weekday_early_no_am1=int(personalized_rules_raw.get("w_wxl_weekday_early_no_am1", pers_cfg_raw.get("w_wxl_weekday_early_no_am1", 2000))),
        enable_dln_weekday_no_am1=personalized_rules_raw.get("enable_dln_weekday_no_am1", pers_cfg_raw.get("enable_dln_weekday_no_am1", True)),
        dln_weekday_no_am1_mode=str(personalized_rules_raw.get("dln_weekday_no_am1_mode", pers_cfg_raw.get("dln_weekday_no_am1_mode", "hard"))),
        w_dln_weekday_no_am1=int(personalized_rules_raw.get("w_dln_weekday_no_am1", pers_cfg_raw.get("w_dln_weekday_no_am1", 2000))),
        enable_custom_no_am1_teachers=personalized_rules_raw.get(
            "enable_custom_no_am1_teachers",
            pers_cfg_raw.get("enable_custom_no_am1_teachers", True),
        ),
        custom_no_am1_teachers=[
            str(x).strip()
            for x in (
                personalized_rules_raw.get(
                    "custom_no_am1_teachers",
                    pers_cfg_raw.get("custom_no_am1_teachers", []),
                )
                if isinstance(
                    personalized_rules_raw.get(
                        "custom_no_am1_teachers",
                        pers_cfg_raw.get("custom_no_am1_teachers", []),
                    ),
                    (list, tuple, set),
                )
                else [
                    personalized_rules_raw.get(
                        "custom_no_am1_teachers",
                        pers_cfg_raw.get("custom_no_am1_teachers", []),
                    )
                ]
            )
            if str(x).strip()
        ],
        enable_mrj_hsm_sun_am12_fixed=personalized_rules_raw.get("enable_mrj_hsm_sun_am12_fixed", pers_cfg_raw.get("enable_mrj_hsm_sun_am12_fixed", True)),
        mrj_hsm_sun_am12_fixed_mode=str(personalized_rules_raw.get("mrj_hsm_sun_am12_fixed_mode", pers_cfg_raw.get("mrj_hsm_sun_am12_fixed_mode", "hard"))),
        w_mrj_hsm_sun_am12_fixed=int(personalized_rules_raw.get("w_mrj_hsm_sun_am12_fixed", pers_cfg_raw.get("w_mrj_hsm_sun_am12_fixed", 3000))),
        enable_zhoubo_hard=pers_cfg_raw.get("enable_zhoubo_hard", True),
        enable_zhoubo_liumeng_same_night=pers_cfg_raw.get("enable_zhoubo_liumeng_same_night", True),
        enable_zhoubo_weekday_am1_penalty=pers_cfg_raw.get("enable_zhoubo_weekday_am1_penalty", True),
        zhoubo_weekday_am1_penalty_mode=str(pers_cfg_raw.get("zhoubo_weekday_am1_penalty_mode", "soft")),
        w_zhoubo_weekday_am1_penalty=int(pers_cfg_raw.get("w_zhoubo_weekday_am1_penalty", 300)),
        enable_liumeng_no_sunday=pers_cfg_raw.get("enable_liumeng_no_sunday", True),
        enable_xww_weekday_am4_pm1_stair=pers_cfg_raw.get("enable_xww_weekday_am4_pm1_stair", True),
        xww_weekday_am4_pm1_stair_mode=str(pers_cfg_raw.get("xww_weekday_am4_pm1_stair_mode", "soft")),
        w_xww_weekday_am4_pm1_e2=int(pers_cfg_raw.get("w_xww_weekday_am4_pm1_e2", 80)),
        w_xww_weekday_am4_pm1_e3=int(pers_cfg_raw.get("w_xww_weekday_am4_pm1_e3", 160)),
        w_xww_weekday_am4_pm1_e4=int(pers_cfg_raw.get("w_xww_weekday_am4_pm1_e4", 320)),
        enable_zfy_no_consecutive_night=pers_cfg_raw.get("enable_zfy_no_consecutive_night", True),
        zfy_no_consecutive_night_mode=str(pers_cfg_raw.get("zfy_no_consecutive_night_mode", "soft")),
        w_zfy_no_consecutive_night=int(pers_cfg_raw.get("w_zfy_no_consecutive_night", 3000)),
        enable_zw_no_consecutive_night=personalized_rules_raw.get("enable_zw_no_consecutive_night", pers_cfg_raw.get("enable_zw_no_consecutive_night", True)),
        zw_no_consecutive_night_mode=str(personalized_rules_raw.get("zw_no_consecutive_night_mode", pers_cfg_raw.get("zw_no_consecutive_night_mode", "hard"))),
        w_zw_no_consecutive_night=int(personalized_rules_raw.get("w_zw_no_consecutive_night", pers_cfg_raw.get("w_zw_no_consecutive_night", 3000))),
        enable_zfy_no_sunday_night=pers_cfg_raw.get("enable_zfy_no_sunday_night", True),
        zfy_no_sunday_night_mode=str(pers_cfg_raw.get("zfy_no_sunday_night_mode", "soft")),
        w_zfy_no_sunday_night=int(pers_cfg_raw.get("w_zfy_no_sunday_night", 500)),
        enable_sll_sun_am_only=pers_cfg_raw.get("enable_sll_sun_am_only", True),
        sll_sun_am_only_mode=str(pers_cfg_raw.get("sll_sun_am_only_mode", "soft")),
        w_sll_sun_am_only=int(pers_cfg_raw.get("w_sll_sun_am_only", 300)),
        enable_cc_weekday_no_am4=pers_cfg_raw.get("enable_cc_weekday_no_am4", True),
        cc_weekday_no_am4_mode=str(pers_cfg_raw.get("cc_weekday_no_am4_mode", "soft")),
        w_cc_weekday_no_am4=int(pers_cfg_raw.get("w_cc_weekday_no_am4", 300)),
        enable_cc_sat_am34_class17=pers_cfg_raw.get("enable_cc_sat_am34_class17", True),
        cc_sat_am34_class17_mode=str(pers_cfg_raw.get("cc_sat_am34_class17_mode", "soft")),
        w_cc_sat_am34_class17=int(pers_cfg_raw.get("w_cc_sat_am34_class17", 600)),
        enable_sm_mon_no_am=pers_cfg_raw.get("enable_sm_mon_no_am", True),
        sm_mon_no_am_mode=str(pers_cfg_raw.get("sm_mon_no_am_mode", "soft")),
        w_sm_mon_no_am=int(pers_cfg_raw.get("w_sm_mon_no_am", 300)),
        enable_sm_mon_no_pm1=pers_cfg_raw.get("enable_sm_mon_no_pm1", True),
        sm_mon_no_pm1_mode=str(pers_cfg_raw.get("sm_mon_no_pm1_mode", "soft")),
        w_sm_mon_no_pm1=int(pers_cfg_raw.get("w_sm_mon_no_pm1", 300)),
    )
    lang_teachers = get_lang_teachers(data)
    lang_tue_fri_target_teachers = {
        str(t).strip() for t in (weekday_cfg.lang_tue_fri_target_teachers or []) if str(t).strip()
    }
    if lang_tue_fri_target_teachers:
        lang_teachers_for_tue_fri = set(lang_tue_fri_target_teachers)
    else:
        lang_teachers_for_tue_fri = set(lang_teachers)
    lang_am1_exempt_teacher_days = set()
    if weekday_cfg.enable_lang_tue_fri_am1_penalty_exempt:
        for teacher in lang_teachers_for_tue_fri:
            for day in ("星期二", "星期三", "星期四", "星期五"):
                lang_am1_exempt_teacher_days.add((teacher, day))

    if weekday_cfg.enable_binding_chem_bio:
        apply_global_day_binding_8_chem_9_bio(model, data, dv)
    if weekday_cfg.enable_no_am1_am4:
        apply_no_am1_am4(model, data, dv, pe_teachers)
    core_load_details = {}
    if weekday_cfg.enable_core_teacher_day_load_limit:
        core_load_details = apply_core_subject_teacher_day_load_and_no_am1_am4(
            model,
            data,
            dv,
            max_per_day=weekday_cfg.core_teacher_day_load_max,
        )
    if weekday_cfg.enable_no_consecutive_same_teacher_same_class:
        apply_no_consecutive_same_teacher_same_class(model, data, dv)
    if weekday_cfg.enable_head_pm1_min:
        apply_head_pm1_min(model, data, dv, [t for t in head_teachers if t not in pe_teachers])
    if weekday_cfg.enable_teacher_weekday_am_pm_presence:
        apply_teacher_weekday_am_pm_presence(model, data, dv, pe_teachers)
    am1_pm1_mutex_penalties = apply_am1_pm1_mutex(
        model,
        data,
        dv,
        enabled=weekday_cfg.enable_am1_pm1_mutex,
        mode=weekday_cfg.am1_pm1_mutex_mode,
        weight=weekday_cfg.w_am1_pm1_mutex,
    )
    two_class_am1_pm1_penalties = apply_two_class_am1_pm1_combo(
        model,
        data,
        dv,
        pe_teachers,
        enabled=weekday_cfg.enable_two_class_am1_pm1_combo,
        mode=weekday_cfg.two_class_am1_pm1_combo_mode,
        weight=weekday_cfg.w_two_class_am1_pm1_combo,
    )
    am1_pm1_exclusive_penalties = apply_am1_pm1_exclusive(
        model,
        data,
        dv,
        enabled=weekday_cfg.enable_am1_pm1_exclusive,
        mode=weekday_cfg.am1_pm1_exclusive_mode,
        weight=weekday_cfg.w_am1_pm1_exclusive,
    )
    apply_single_class_weekly_am1_cap(
        model,
        data,
        dv,
        enabled=weekday_cfg.enable_single_class_weekly_am1_cap,
        max_occurrences=weekday_cfg.single_class_weekly_am1_cap_max,
    )
    if weekday_cfg.enable_two_class_low_hours_max_empty_days:
        apply_two_class_low_hours_max_empty_days(
            model,
            data,
            dv,
            pe_teachers,
            weekday_cfg.two_class_low_hours_threshold,
            weekday_cfg.two_class_max_empty_days,
        )
    if weekday_cfg.enable_low_weekday_subject_max1_per_day:
        apply_low_weekday_subject_max1_per_day(
            model,
            data,
            dv,
            weekday_cfg.low_weekday_subject_max1_threshold,
        )
        write_low_weekday_subject_max1_report(out_dir, data, weekday_cfg.low_weekday_subject_max1_threshold)
    if weekday_cfg.enable_high_weekday_subject_min1_per_day:
        apply_high_weekday_subject_min1_per_day(
            model,
            data,
            dv,
            weekday_cfg.high_weekday_subject_min1_threshold,
        )

    write_soft_timepref_audit(out_dir, data)

    duty_vars = {}
    teach_pm1_vars = {}
    excess_duty = {}
    excess_pm1 = {}
    duty_floor_vars = {}
    duty_trigger_vars = {}
    head_floor_by_teacher = {}
    head_floor_groups = {}
    head_allowed_duty_floors = {}
    head_borrow_5_to_4 = {}
    head_weekly_duty_count_45f = {}
    head_h4_base = []
    head_h5_base = []
    head_t9_teacher = ""
    head_duty_days = sorted({s.day for s in data.available_slots})
    head_duty_hints = []
    head_weekday_pm1_requires_duty_penalties = []
    noon_male_vars = {}
    noon_female_vars = {}
    noon_penalties = []
    noon_day_penalty = {}
    noon_days = sorted({s.day for s in data.available_slots})
    noon_hints = []
    if head_duty_cfg.enable_head_duty:
        (
            duty_vars,
            teach_pm1_vars,
            head_weekday_pm1_requires_duty_penalties,
            excess_duty,
            excess_pm1,
            duty_floor_vars,
            duty_trigger_vars,
            head_floor_by_teacher,
            head_floor_groups,
            head_allowed_duty_floors,
            head_borrow_5_to_4,
            head_weekly_duty_count_45f,
            head_h4_base,
            head_h5_base,
            head_t9_teacher,
            head_duty_hints,
        ) = apply_head_duty_constraints(
            model,
            data,
            dv,
            head_teachers,
            io_cfg=io_cfg,
            base_dir=base_dir,
            cfg=head_duty_cfg,
        )
        write_head_duty_vars_count(out_dir, duty_vars, teach_pm1_vars, duty_floor_vars, duty_trigger_vars)

    if noon_cfg.enabled:
        (
            noon_male_vars,
            noon_female_vars,
            noon_penalties,
            noon_day_penalty,
            noon_days,
            noon_hints,
        ) = apply_noon_dorm_duty_constraints(
            model,
            data,
            dv,
            io_cfg=io_cfg,
            base_dir=base_dir,
            out_dir=out_dir,
            cfg=noon_cfg,
            night_vars=None,
        )

    pe_illegal_fixed = 0
    whitelist_viol_fixed = 0
    liu_allowed = set()
    tao_allowed = set()
    liu_viol_fixed = 0
    tao_viol_fixed = 0
    write_pe_tech_audit(out_dir, data, pe_tech_teachers)
    if pe_cfg.enable_pe_time_window_hard:
        pe_illegal_fixed = apply_pe_time_window_hard(model, data, dv)
    if pe_tech_teachers:
        for item in pe_cfg_raw.get("teacher_whitelist_rules", []) or []:
            if not isinstance(item, dict):
                continue
            teacher = str(item.get("teacher", "")).strip()
            allowed = set()
            for slot_item in item.get("allowed_slots", []) or []:
                if isinstance(slot_item, dict):
                    day = str(slot_item.get("day", "")).strip()
                    slot = str(slot_item.get("slot", "")).strip()
                elif isinstance(slot_item, (list, tuple)) and len(slot_item) >= 2:
                    day = str(slot_item[0]).strip()
                    slot = str(slot_item[1]).strip()
                else:
                    continue
                if day and slot:
                    allowed.add((day, slot))
            if teacher and allowed:
                whitelist_viol_fixed += apply_teacher_whitelist_hard(model, data, dv, teacher, allowed)
    liu_viol_fixed = whitelist_viol_fixed

    multi_penalties, multi_details = [], None
    if weekday_cfg.enable_multi_class_halfday:
        multi_penalties, multi_details = apply_multi_class_halfday_soft(
            model, data, dv, pe_teachers, weekday_cfg.weight_multi_class_halfday
        )

    am4pm1_penalties, am4pm1_details = [], {}
    if weekday_cfg.enable_teacher_am4_pm1_threshold_penalty:
        am4pm1_penalties, am4pm1_details = apply_teacher_am4_pm1_threshold_penalty(
            model,
            data,
            dv,
            pe_teachers,
            (
                weekday_cfg.teacher_am4_pm1_w3,
                weekday_cfg.teacher_am4_pm1_w4,
                weekday_cfg.teacher_am4_pm1_w5,
                weekday_cfg.teacher_am4_pm1_w6,
            ),
        )

    lang_am_vars: List[cp_model.IntVar] = []
    lang_pm1_vars: List[cp_model.IntVar] = []
    lang_pm2_vars: List[cp_model.IntVar] = []
    lang_pm3_vars: List[cp_model.IntVar] = []
    lang_pm_vars: List[cp_model.IntVar] = []
    lang_fixed = (0, 0)
    if weekday_cfg.enable_pref_lang_am and weekday_cfg.enable_lang_tue_fri_preferences:
        lang_am_vars, lang_pm1_vars, lang_pm2_vars, lang_pm3_vars = apply_pref_lang_am(
            model,
            data,
            dv,
            enabled=True,
            target_teachers=lang_teachers_for_tue_fri,
        )
        lang_pm_vars = [*lang_pm1_vars, *lang_pm2_vars, *lang_pm3_vars]

    stem_am1_vars, stem_am1_fixed = [], 0
    if weekday_cfg.enable_reduce_stem_am1:
        stem_am1_vars, stem_am1_fixed = apply_reduce_stem_am1(model, data, dv, weekday_cfg.w_stem_am1_penalty)

    teacher_only_am1_penalties, teacher_am1_excess_penalties, teacher_am1_details = [], [], {}
    if weekday_cfg.enable_teacher_am1_fragmentation:
        teacher_only_am1_penalties, teacher_am1_excess_penalties, teacher_am1_details = apply_teacher_am1_fragmentation(
            model,
            data,
            dv,
            pe_teachers,
            weekday_cfg.k_teacher_am1_week,
            weekday_cfg.w_teacher_only_am1_day,
            weekday_cfg.w_teacher_am1_excess,
            am1_penalty_exempt_teacher_days=lang_am1_exempt_teacher_days,
        )

    two_class_penalties, two_class_details = [], {}
    if weekday_cfg.enable_two_class_daily_min_per_class:
        two_class_penalties, two_class_details = apply_two_class_daily_min_per_class(
            model,
            data,
            dv,
            pe_teachers,
            weekday_cfg.two_class_daily_min_mode,
            weekday_cfg.w_two_class_daily_min_per_class,
        )

    continuity_penalties, continuity_details = [], {}
    if weekday_cfg.enable_teacher_continuity_penalty:
        continuity_penalties, continuity_details = apply_teacher_continuity_penalty(
            model, data, dv, pe_teachers, weekday_cfg.teacher_continuity_gap_weight
        )

    m1_cap_penalties, m1_cap_details, m1_cap_structural_impossible = [], {}, {}
    if weekday_cfg.enable_teacher_m1_cap_constraint:
        m1_cap_penalties, m1_cap_details, m1_cap_structural_impossible = apply_teacher_m1_cap_constraint(
            model,
            data,
            dv,
            max_m1=weekday_cfg.teacher_m1_cap_max,
            weight=weekday_cfg.w_hit_m1_cap,
            am1_penalty_exempt_teacher_days=lang_am1_exempt_teacher_days,
        )

    weekday_balance_penalties = []
    if weekday_cfg.enable_balance_weekday_subject_hours:
        weekday_balance_penalties = apply_weekday_subject_balance(
            model,
            data,
            dv,
            weekday_cfg.balance_weekday_subject_hours_mode,
            weekday_cfg.weight_balance_weekday_subject_hours,
        )

    pe_am_penalties = []
    pe_gap_penalties = []
    pe_gap_details = {}
    if pe_cfg.enable_pe_reduce_am:
        pe_am_penalties = apply_pe_reduce_am_soft(data, dv, pe_teachers)
    if pe_cfg.enable_pe_tech_compact:
        pe_gap_penalties, pe_gap_details = apply_pe_tech_compact_soft(model, data, dv, pe_tech_teachers)

    # 软约束登记：构建变量到教师/班级/学科映射，供诊断汇总使用
    var_meta = {}
    for (cls, subj, slot), var in dv.x.items():
        var_meta[var] = (data.cls_subj_teacher.get((cls, subj)), cls, subj, slot.day, f"{slot.block}{slot.period}")

    objective_terms: List[cp_model.IntVar] = []
    if weekend_penalties:
        objective_terms.extend([weekend_cfg.cross_halfday_penalty * v for v in weekend_penalties])
        for v in weekend_penalties:
            teacher = None
            day = None
            try:
                v_name = v.Name()
            except Exception:
                v_name = ""
            if v_name.startswith("cross_halfday[") and v_name.endswith("]"):
                parts = v_name[len("cross_halfday["):-1].split(",", 1)
                if len(parts) == 2:
                    teacher, day = parts
            register(
                "weekend_cross_halfday",
                "周末跨半天惩罚",
                weekend_cfg.cross_halfday_penalty,
                v,
                teacher=teacher,
                day=day,
            )
    if weekend_halfday_penalties and weekend_cfg.weekend_halfday_mode.lower() == "soft":
        objective_terms.extend([weekend_cfg.w_weekend_halfday * v for v in weekend_halfday_penalties])
    if yjc_sun_am12_pm12_penalties and weekend_cfg.yjc_sun_am12_pm12_mode.lower() == "soft":
        objective_terms.extend([weekend_cfg.w_yjc_sun_am12_pm12 * v for v in yjc_sun_am12_pm12_penalties])
        for v in yjc_sun_am12_pm12_penalties:
            teacher = None
            v_name = v.Name()
            if v_name.startswith("target_sun_am12_pm12_combo[") and v_name.endswith("]"):
                parts = v_name[len("target_sun_am12_pm12_combo["):-1].split(",", 1)
                if parts:
                    teacher = parts[0]
            register(
                "weekend_yjc_sun_am12_pm12",
                "指定教师周日禁排 AM1+AM2+PM1+PM2",
                weekend_cfg.w_yjc_sun_am12_pm12,
                v,
                teacher=teacher,
                day="星期日",
                weight_key="day.weekend_constraints.w_yjc_sun_am12_pm12",
                source_module="scheduler/model/constraints/day_weekend_constraints.py",
                constraint_category="personalized",
                mode="soft",
            )
    if multi_penalties:
        objective_terms.extend([weekday_cfg.weight_multi_class_halfday * v for v in multi_penalties])
    if am4pm1_penalties:
        w3 = weekday_cfg.teacher_am4_pm1_w3
        w4 = weekday_cfg.teacher_am4_pm1_w4
        w5 = weekday_cfg.teacher_am4_pm1_w5
        w6 = weekday_cfg.teacher_am4_pm1_w6
        for _tch, (_total_max, _cnt, e3, e4, e5, e6) in am4pm1_details.items():
            objective_terms.extend([w3 * e3, w4 * e4, w5 * e5, w6 * e6])
            register("teacher_am4_pm1_w3", "教师AM4+PM1阶梯3", w3, e3, teacher=_tch)
            register("teacher_am4_pm1_w4", "教师AM4+PM1阶梯4", w4, e4, teacher=_tch)
            register("teacher_am4_pm1_w5", "教师AM4+PM1阶梯5", w5, e5, teacher=_tch)
            register("teacher_am4_pm1_w6", "教师AM4+PM1阶梯6", w6, e6, teacher=_tch)
    if lang_am_vars and weekday_cfg.w_lang_tue_fri_am1_reward > 0:
        objective_terms.extend([-weekday_cfg.w_lang_tue_fri_am1_reward * v for v in lang_am_vars])
        for v in lang_am_vars:
            meta = var_meta.get(v, (None, None, None, None, None))
            register(
                "lang_tue_fri_am1_reward",
                "语文外语周二至周五上午1奖励",
                -weekday_cfg.w_lang_tue_fri_am1_reward,
                v,
                teacher=meta[0],
                cls=meta[1],
                subj=meta[2],
                day=meta[3],
                slot=meta[4],
                weight_key="day.weekday_constraints.w_lang_tue_fri_am1_reward",
                source_module="scheduler/model/constraints/day_weekday_constraints.py",
                constraint_category="preference",
                mode="soft",
            )
    if lang_pm1_vars and weekday_cfg.w_lang_tue_fri_pm1_penalty > 0:
        objective_terms.extend([weekday_cfg.w_lang_tue_fri_pm1_penalty * v for v in lang_pm1_vars])
        for v in lang_pm1_vars:
            meta = var_meta.get(v, (None, None, None, None, None))
            register(
                "lang_tue_fri_pm1_penalty",
                "语文外语周二至周五下午1惩罚",
                weekday_cfg.w_lang_tue_fri_pm1_penalty,
                v,
                teacher=meta[0],
                cls=meta[1],
                subj=meta[2],
                day=meta[3],
                slot=meta[4],
                weight_key="day.weekday_constraints.w_lang_tue_fri_pm1_penalty",
                source_module="scheduler/model/constraints/day_weekday_constraints.py",
                constraint_category="preference",
                mode="soft",
            )
    if lang_pm2_vars and weekday_cfg.w_lang_tue_fri_pm2_penalty > 0:
        objective_terms.extend([weekday_cfg.w_lang_tue_fri_pm2_penalty * v for v in lang_pm2_vars])
        for v in lang_pm2_vars:
            meta = var_meta.get(v, (None, None, None, None, None))
            register(
                "lang_tue_fri_pm2_penalty",
                "语文外语周二至周五下午2惩罚",
                weekday_cfg.w_lang_tue_fri_pm2_penalty,
                v,
                teacher=meta[0],
                cls=meta[1],
                subj=meta[2],
                day=meta[3],
                slot=meta[4],
                weight_key="day.weekday_constraints.w_lang_tue_fri_pm2_penalty",
                source_module="scheduler/model/constraints/day_weekday_constraints.py",
                constraint_category="preference",
                mode="soft",
            )
    if lang_pm3_vars and weekday_cfg.w_lang_tue_fri_pm3_penalty > 0:
        objective_terms.extend([weekday_cfg.w_lang_tue_fri_pm3_penalty * v for v in lang_pm3_vars])
        for v in lang_pm3_vars:
            meta = var_meta.get(v, (None, None, None, None, None))
            register(
                "lang_tue_fri_pm3_penalty",
                "语文外语周二至周五下午3惩罚",
                weekday_cfg.w_lang_tue_fri_pm3_penalty,
                v,
                teacher=meta[0],
                cls=meta[1],
                subj=meta[2],
                day=meta[3],
                slot=meta[4],
                weight_key="day.weekday_constraints.w_lang_tue_fri_pm3_penalty",
                source_module="scheduler/model/constraints/day_weekday_constraints.py",
                constraint_category="preference",
                mode="soft",
            )
    if stem_am1_vars:
        objective_terms.extend([weekday_cfg.w_stem_am1_penalty * v for v in stem_am1_vars])
        for v in stem_am1_vars:
            meta = var_meta.get(v, (None, None, None, None, None))
            register("stem_am1_penalty", "理科AM1减少", weekday_cfg.w_stem_am1_penalty, v, teacher=meta[0], cls=meta[1], subj=meta[2], day=meta[3], slot=meta[4])
    if teacher_only_am1_penalties:
        objective_terms.extend([weekday_cfg.w_teacher_only_am1_day * v for v in teacher_only_am1_penalties])
    if teacher_am1_excess_penalties:
        objective_terms.extend([weekday_cfg.w_teacher_am1_excess * v for v in teacher_am1_excess_penalties])
        for tch, (_am1_cnt, _fixed, _only_days, excess) in teacher_am1_details.items():
            register("teacher_am1_excess", "教师AM1周超额", weekday_cfg.w_teacher_am1_excess, excess, teacher=tch)
    if am1_pm1_mutex_penalties and weekday_cfg.am1_pm1_mutex_mode.lower() == "soft":
        objective_terms.extend([weekday_cfg.w_am1_pm1_mutex * v for v in am1_pm1_mutex_penalties])
    if two_class_am1_pm1_penalties and weekday_cfg.two_class_am1_pm1_combo_mode.lower() == "soft":
        objective_terms.extend([weekday_cfg.w_two_class_am1_pm1_combo * v for v in two_class_am1_pm1_penalties])
    if am1_pm1_exclusive_penalties and weekday_cfg.am1_pm1_exclusive_mode.lower() == "soft":
        objective_terms.extend([weekday_cfg.w_am1_pm1_exclusive * v for v in am1_pm1_exclusive_penalties])
    if two_class_penalties and weekday_cfg.two_class_daily_min_mode == "soft":
        objective_terms.extend([weekday_cfg.w_two_class_daily_min_per_class * v for v in two_class_penalties])
    if head_duty_cfg.enable_head_duty and duty_trigger_vars and head_duty_cfg.w_pm1_penalty > 0:
        objective_terms.extend([head_duty_cfg.w_pm1_penalty * v for v in duty_trigger_vars.values()])
        for (tch, day), v in duty_trigger_vars.items():
            register(
                "head_duty_pm1_without_duty",
                "班主任PM1无同日值班惩罚",
                head_duty_cfg.w_pm1_penalty,
                v,
                teacher=tch,
                day=day,
                slot="下午1",
                weight_key="day.head_duty_constraints.w_pm1_penalty",
                source_module="scheduler/model/constraints/day_head_teacher_duty_constraints.py",
                constraint_category="dorm-duty",
            )
    if (
        head_duty_cfg.enable_head_duty
        and head_duty_cfg.enable_weekday_pm1_requires_duty
        and str(head_duty_cfg.weekday_pm1_requires_duty_mode).lower() == "soft"
        and head_weekday_pm1_requires_duty_penalties
    ):
        objective_terms.extend(
            [head_duty_cfg.w_weekday_pm1_requires_duty * v for v in head_weekday_pm1_requires_duty_penalties]
        )
    if noon_penalties:
        objective_terms.extend(noon_penalties)
    if pe_am_penalties:
        objective_terms.extend([pe_cfg.w_pe_am_penalty * v for v in pe_am_penalties])
        for v in pe_am_penalties:
            meta = var_meta.get(v, (None, None, None, None, None))
            register("pe_am_penalty", "体育教师上午惩罚", pe_cfg.w_pe_am_penalty, v, teacher=meta[0], cls=meta[1], subj=meta[2], day=meta[3], slot=meta[4])
    if pe_gap_penalties:
        objective_terms.extend([pe_cfg.w_pe_gap_penalty * v for v in pe_gap_penalties])
        for (tch, day, tag), vars_list in pe_gap_details.items():
            for v in vars_list:
                register("pe_gap_penalty", "体育技术紧凑性", pe_cfg.w_pe_gap_penalty, v, teacher=tch, day=day, slot=tag)
    if continuity_penalties:
        objective_terms.extend([weekday_cfg.teacher_continuity_gap_weight * v for v in continuity_penalties])
        for (tch, day, tag), vars_list in continuity_details.items():
            for v in vars_list:
                register("teacher_continuity_gap", "教师半天连续性空档", weekday_cfg.teacher_continuity_gap_weight, v, teacher=tch, day=day, slot=tag)
    if m1_cap_penalties:
        objective_terms.extend([weekday_cfg.w_hit_m1_cap * v for v in m1_cap_penalties])
    if weekday_balance_penalties:
        objective_terms.extend([weekday_cfg.weight_balance_weekday_subject_hours * v for v in weekday_balance_penalties])

    rule_v2_compile = apply_rule_v2_constraints(
        model,
        data,
        dv,
        rules_cfg,
        grade_prefix=grade_prefix,
    )
    active_rule_v2_ids = {
        str(item.get("id") or "")
        for item in (((rules_cfg.get("rule_v2") or {}).get("rules") or []) if isinstance(rules_cfg, dict) else [])
        if isinstance(item, dict) and item.get("enabled", True) and item.get("status") == "active"
    }
    missing_rule_v2_ids = sorted(active_rule_v2_ids - set(rule_v2_compile.applied_rule_ids))
    if missing_rule_v2_ids:
        raise ValueError("以下已启用规则没有进入求解模型：" + "、".join(missing_rule_v2_ids[:12]))
    objective_terms.extend(rule_v2_compile.objective_terms)
    for item in rule_v2_compile.diagnostics:
        level = logging.WARNING if item.get("status") == "skipped" else logging.INFO
        logger.log(
            level,
            "Rule V2 compile rule_id=%s status=%s message=%s",
            item.get("rule_id"),
            item.get("status"),
            item.get("message"),
        )

    summary_out = (out_dir / summary_name).with_name(
        f"{Path(summary_name).stem}_{ts}{Path(summary_name).suffix}"
    )
    formal_out = (out_dir / formal_name).with_name(
        f"{Path(formal_name).stem}_{ts}{Path(formal_name).suffix}"
    )

    return DayBuildResult(
        data=data,
        dv=dv,
        out_dir=out_dir,
        summary_out=summary_out,
        formal_out=formal_out,
        objective_terms=objective_terms,
        weekend_diag=diag,
        weekend_cfg=weekend_cfg,
        weekday_cfg=weekday_cfg,
        pe_cfg=pe_cfg,
        head_teachers=head_teachers,
        pe_teachers=pe_teachers,
        pe_tech_teachers=pe_tech_teachers,
        multi_details=multi_details,
        am4pm1_details=am4pm1_details,
        continuity_details=continuity_details,
        core_load_details=core_load_details,
        m1_cap_details=m1_cap_details,
        m1_cap_structural_impossible=m1_cap_structural_impossible,
        teacher_am1_details=teacher_am1_details,
        lang_am_vars=lang_am_vars,
        lang_pm_vars=lang_pm_vars,
        lang_fixed=lang_fixed,
        stem_am1_vars=stem_am1_vars,
        stem_am1_fixed=stem_am1_fixed,
        pe_am_penalties=pe_am_penalties,
        pe_gap_details=pe_gap_details,
        liu_allowed=liu_allowed,
        tao_allowed=tao_allowed,
        liu_viol_fixed=liu_viol_fixed,
        tao_viol_fixed=tao_viol_fixed,
        pe_illegal_fixed=pe_illegal_fixed,
        weekday_balance_penalties=weekday_balance_penalties,
        day_night_link_cfg=link_cfg,
        head_duty_cfg=head_duty_cfg,
        duty_vars=duty_vars,
        teach_pm1_vars=teach_pm1_vars,
        excess_duty=excess_duty,
        excess_pm1=excess_pm1,
        duty_floor_vars=duty_floor_vars,
        duty_trigger_vars=duty_trigger_vars,
        head_floor_by_teacher=head_floor_by_teacher,
        head_floor_groups=head_floor_groups,
        head_allowed_duty_floors=head_allowed_duty_floors,
        head_borrow_5_to_4=head_borrow_5_to_4,
        head_weekly_duty_count_45f=head_weekly_duty_count_45f,
        head_h4_base=head_h4_base,
        head_h5_base=head_h5_base,
        head_t9_teacher=head_t9_teacher,
        head_duty_days=head_duty_days,
        head_duty_hints=head_duty_hints,
        noon_dorm_cfg=noon_cfg,
        noon_male_vars=noon_male_vars,
        noon_female_vars=noon_female_vars,
        noon_day_penalty=noon_day_penalty,
        noon_days=noon_days,
        noon_hints=noon_hints,
        two_class_details=two_class_details,
        pers_cfg=pers_cfg,
    )


def build_night_model(
    model: cp_model.CpModel,
    rules_path: Path,
    io_path: Path,
    ts: str,
    io_cfg: dict | None = None,
    rules_cfg: dict | None = None,
) -> NightBuildResult:
    if io_cfg is None or rules_cfg is None:
        effective = load_effective_config(
            "night",
            {"io_path": io_path, "rules_path": rules_path},
        )
        io_cfg = effective.io_cfg
        rules_cfg = effective.rules_cfg
    rules = copy.deepcopy(rules_cfg)
    base_dir = io_path.parent.parent
    # normalize teacher_table path to absolute
    if "teacher_table" in io_cfg and "path" in io_cfg["teacher_table"]:
        tt_path = Path(io_cfg["teacher_table"]["path"])
        if not tt_path.is_absolute():
            io_cfg["teacher_table"]["path"] = str((base_dir / tt_path).resolve())
    classes, cst, ts_map, male_heads, female_heads = read_teacher_table(io_cfg, rules)
    days = rules["calendar"]["days"]
    periods = rules["calendar"]["periods"]

    vars = build_variables(model, classes, cst, days, periods)
    checkin_cfg = rules.get("checkin", {}) or {}
    checkin_enabled_raw = checkin_cfg.get("enabled", False)
    if isinstance(checkin_enabled_raw, str):
        checkin_enabled = checkin_enabled_raw.strip().lower() not in {"0", "false", "no", "off", "否", "关闭"}
    else:
        checkin_enabled = bool(checkin_enabled_raw)
    checkin_enabled = checkin_enabled and checkin_candidate_pool_available(
        checkin_cfg,
        male_heads,
        female_heads,
    )
    if not checkin_enabled and checkin_enabled_raw:
        rules.setdefault("checkin", {})["enabled"] = False
    checkin_vars = (
        build_checkin_variables(model, male_heads, female_heads, days)
        if checkin_enabled
        else {"checkin_m": {}, "checkin_f": {}}
    )
    vars.update(checkin_vars)

    ctx = {
        "classes": classes,
        "cst": cst,
        "ts": ts_map,
        "male_heads": male_heads,
        "female_heads": female_heads,
        "days": days,
        "periods": periods,
    }

    apply_hard_base(model, vars, ctx, rules)
    apply_hard_bans(model, vars, ctx, rules)
    apply_hard_teacher_limits(model, vars, ctx, rules)
    apply_global_night_binding_8_chem_9_bio(model, vars, ctx, rules)
    apply_physics_math_hard_bans(model, vars, ctx, rules)
    apply_fri_sun_mutex(model, vars, ctx, rules)
    apply_single_class_teacher_p1_p2_split(model, vars, ctx, rules)
    apply_double_class_teacher_weekday_alternate_p1_p2(model, vars, ctx, rules)
    checkin_penalties = apply_checkin(model, vars, ctx, rules)
    penalties = []
    penalties.extend(checkin_penalties)
    penalties.extend(apply_soft_objective(model, vars, ctx, rules, set_objective=False))
    base_dir = io_path.parent.parent
    write_night_constraints_audit(base_dir, rules, ctx)

    out_path = rules.get("output", {}).get("result_xlsx", "结果_v4_含查寝.xlsx")
    out_path_p = resolve_project_path(
        out_path,
        project_root=base_dir.parent,
        label="rules.output.result_xlsx",
        reject_scheduler_outputs=True,
    )
    out_path_p = out_path_p.with_name(f"{out_path_p.stem}_{ts}{out_path_p.suffix}")

    return NightBuildResult(vars=vars, ctx=ctx, rules=rules, out_dir=base_dir.parent, out_path=out_path_p, penalties=penalties)


def run_joint(grade_prefix: str, io_path: Path, rules_path: Path) -> None:
    """Run the joint day/night pipeline without changing scheduling semantics."""
    clear_registry()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    model = create_existing_cp_model("scheduler.joint")

    effective = load_effective_config(
        "joint",
        {"io_path": io_path, "rules_path": rules_path},
    )
    io_cfg = effective.io_cfg
    rules_cfg = effective.rules_cfg
    io_path = effective.io_path
    rules_path = effective.rules_path
    artifact_cfg = build_joint_artifact_config(io_cfg, io_path)

    day_rules_path = io_path.parent.parent / io_cfg.get("day", {}).get("rules_path", "白天规则.xlsx")
    teacher_table_path = io_path.parent.parent / io_cfg.get("teacher_table", {}).get("path", "教师定位表.xlsx")
    rules_hash, data_hash = compute_rules_data_hash(io_path, rules_path, day_rules_path, teacher_table_path)

    day_build = build_day_model(
        model,
        io_path,
        rules_path,
        grade_prefix,
        ts,
        io_cfg=io_cfg,
        rules_cfg=rules_cfg,
    )
    night_build = build_night_model(
        model,
        rules_path,
        io_path,
        ts,
        io_cfg=io_cfg,
        rules_cfg=rules_cfg,
    )

    cross = apply_joint_cross_model_constraints(model, io_cfg, day_build, night_build)
    warm_start = apply_joint_warm_start_hints(
        model,
        day_build,
        night_build,
        artifact_cfg.warm_cfg,
        rules_hash,
        data_hash,
    )
    objective_terms = build_and_apply_joint_objective(model, day_build, night_build, cross)
    solve = solve_joint_model(model, io_cfg, effective, grade_prefix, artifact_cfg, cross)

    write_joint_diagnostics(
        io_path,
        day_build,
        night_build,
        cross,
        solve,
        artifact_cfg.archive_cfg,
    )
    export_joint_solution_outputs(
        io_path,
        ts,
        grade_prefix,
        day_build,
        night_build,
        cross,
        solve,
        artifact_cfg,
        objective_terms,
        rules_hash,
        data_hash,
    )
    finalize_joint_outputs(
        ts,
        day_build,
        solve,
        objective_terms,
        warm_start,
        artifact_cfg.warm_cfg,
        rules_hash,
        data_hash,
    )
