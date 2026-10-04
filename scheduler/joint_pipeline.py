# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List

from ortools.sat.python import cp_model

from ai_orchestrated_optimization import solve_existing_cp_model
from scheduler.day_constraints_morning_reading import (
    check_morning_reading_inputs,
    extract_morning_reading_results,
    write_morning_reading_diagnostic,
)
from scheduler.diagnostic_utils import move_diagnostics_to_folder, move_root_meta_files
from scheduler.diagnostics.baseline_report import write_baseline_report
from scheduler.diagnostics.penalty_registry import (
    summarize_event_log_csv,
    validate_registered_rule_meta,
    write_event_log_csv,
)
from scheduler.model.constraints.day_head_teacher_duty_constraints import (
    extract_duty_results,
    write_head_duty_hard_check,
    write_head_duty_infeasible_hints,
    write_head_duty_soft_report,
)
from scheduler.model.constraints.day_night_bridge import (
    add_link_constraints,
    build_bridge_vars,
    write_link_audit,
    write_link_checklist,
)
from scheduler.model.constraints.day_noon_dorm_duty_constraints import (
    add_noon_night_checkin_coupling,
    add_noon_prev_same_day_no_night_class_constraints,
    extract_noon_dorm_rows,
    write_noon_dorm_checklist,
)
from scheduler.model.constraints.day_pe_tech_constraints import write_pe_tech_checklist
from scheduler.model.constraints.day_weekday_constraints import (
    write_core_teacher_day_load_infeasible_hint,
    write_core_teacher_day_load_sanity,
    write_day_check_hard_constraints,
    write_day_constraint_checklist,
    write_day_infeasible_hints,
    write_day_soft_timepref_report,
    write_low_weekday_subject_max1_report,
    write_teacher_am4_pm1_penalty_report,
    write_teacher_continuity_report,
    write_teacher_m1_cap_infeasible_hint,
    write_teacher_m1_cap_report,
    write_two_class_daily_min_report,
)
from scheduler.model.constraints.day_weekend_constraints import write_weekend_diagnostic
from scheduler.model.constraints.duty_joint_constraints import (
    DutyJointConfig,
    add_duty_joint_constraints,
    write_duty_joint_audit,
    write_duty_joint_checklist,
)
from scheduler.model.constraints.grade_group_duty_constraints import (
    GradeGroupDutyConfig,
    apply_grade_group_duty_constraints,
    extract_grade_group_available_map,
    extract_grade_group_duty_map,
    write_grade_group_duty_audit,
    write_grade_group_duty_checklist,
)
from scheduler.model.constraints.night_single_class_period_split import (
    write_double_class_weekday_p1_p2_report,
)
from scheduler.model.constraints.night_special import (
    append_infeasible_audit,
    write_night_constraint_checklist,
)
from scheduler.model.constraints.personalized_constraints import (
    apply_personalized_constraints,
    write_personalized_checklist,
    write_personalized_infeasible_hints,
)
from scheduler.model.constraints.teacher_targets import teacher_names
from scheduler.output.day_exporter import (
    export_day_schedule_df,
    export_day_schedule_grid_df,
    save_day_schedule_excel,
)
from scheduler.output.day_exporter_combo import save_day_class_and_teacher_summary_excel
from scheduler.output.value_maps import build_checkin_rows_from_solver
from scheduler.output_paths import resolve_project_path
from scheduler.snapshot_diagnostics import build_multi_solution_diagnostic
from scheduler.solver_callbacks.timed_snapshot_callback import (
    SnapshotExportConfig,
    SolutionArchiveConfig,
    TimedSnapshotExportCallback,
)
from scheduler.solver_params import build_scheduler_cp_sat_solve_config
from scheduler.solver_quality import enrich_solver_overview
from scheduler.warm_start import (
    WarmStartConfig,
    load_solution_json,
    save_best_solution_json,
    save_solution_json,
    select_solution_file,
    trim_solution_pool,
)
from scheduler.joint_runtime import (
    CountingSolutionCallback,
    DayBuildResult,
    NightBuildResult,
    build_evening_assignments_from_solver,
)

logger = logging.getLogger(__name__)


@dataclass
class JointArtifactConfig:
    warm_cfg: WarmStartConfig
    snapshot_cfg: SnapshotExportConfig
    archive_cfg: SolutionArchiveConfig
    stop_file: Path | None


@dataclass
class JointCrossBuildResult:
    bridge: dict
    link_penalties: list
    link_stats: dict
    duty_joint_penalties: list
    duty_joint_info: dict
    grade_group_penalties: list
    grade_group_duty_vars: dict
    grade_group_info: dict
    hard_notes: list[str]
    pers_penalties: list
    pers_stats: dict
    noon_night_penalties: list
    noon_prev_same_penalties: list
    snapshot_day_ctx: dict
    snapshot_night_ctx: dict


@dataclass
class WarmStartApplyResult:
    selected: Path | None


@dataclass
class JointSolveResult:
    solver: cp_model.CpSolver
    status: int
    status_name: str
    feasible_count: int
    callback: TimedSnapshotExportCallback | None


def build_joint_artifact_config(io_cfg: dict, io_path: Path) -> JointArtifactConfig:
    project_root = io_path.parent.parent.parent
    warm_cfg_raw = io_cfg.get("warm_start", {}) or {}
    warm_cfg = WarmStartConfig(
        enabled=warm_cfg_raw.get("enabled", True),
        path=resolve_project_path(
            warm_cfg_raw.get("path", "outputs/meta/last_solution.json"),
            project_root=project_root,
            label="warm_start.path",
            reject_scheduler_outputs=True,
        ),
        best_path=resolve_project_path(
            warm_cfg_raw.get("best_path", "outputs/meta/best_warm_start_solution.json"),
            project_root=project_root,
            label="warm_start.best_path",
            reject_scheduler_outputs=True,
        ),
        pool_dir=resolve_project_path(
            warm_cfg_raw.get("pool_dir", "outputs/solution_pool"),
            project_root=project_root,
            label="warm_start.pool_dir",
            reject_scheduler_outputs=True,
        ),
        keep_last_n=int(warm_cfg_raw.get("keep_last_n", 10)),
        prefer_same_rules_hash=bool(warm_cfg_raw.get("prefer_same_rules_hash", True)),
        prefer_same_data_hash=bool(warm_cfg_raw.get("prefer_same_data_hash", True)),
    )
    snapshot_raw = io_cfg.get("snapshot_export", {}) or {}
    snapshot_cfg = SnapshotExportConfig(
        enabled=bool(snapshot_raw.get("enabled", True)),
        interval_sec=int(snapshot_raw.get("interval_sec", 60)),
        root_dir=resolve_project_path(
            snapshot_raw.get("root_dir", "outputs/snapshots"),
            project_root=project_root,
            label="snapshot_export.root_dir",
            reject_scheduler_outputs=True,
        ),
        export_day=bool(snapshot_raw.get("export_day", True)),
        export_night=bool(snapshot_raw.get("export_night", True)),
        export_link_reports=bool(snapshot_raw.get("export_link_reports", True)),
        export_checklists=bool(snapshot_raw.get("export_checklists", True)),
    )
    archive_raw = io_cfg.get("multi_solution_output", {}) or {}
    archive_cfg = SolutionArchiveConfig(
        enabled=bool(archive_raw.get("enabled", True)),
        root_dir=resolve_project_path(
            archive_raw.get("root_dir", "outputs/solutions"),
            project_root=project_root,
            label="multi_solution_output.root_dir",
            reject_scheduler_outputs=True,
        ),
        max_keep=int(archive_raw.get("max_keep", 50)),
        keep_last_runs=int(archive_raw.get("keep_last_runs", 20)),
        periodic_export_every=int(archive_raw.get("periodic_export_every", 0)),
    )
    stop_file_raw = (io_cfg.get("web_solve_control", {}) or {}).get("stop_file")
    stop_file = Path(str(stop_file_raw)).resolve() if stop_file_raw else None
    return JointArtifactConfig(
        warm_cfg=warm_cfg,
        snapshot_cfg=snapshot_cfg,
        archive_cfg=archive_cfg,
        stop_file=stop_file,
    )


def apply_joint_cross_model_constraints(
    model: cp_model.CpModel,
    io_cfg: dict,
    day_build: DayBuildResult,
    night_build: NightBuildResult,
) -> JointCrossBuildResult:
    duty_joint_raw = (io_cfg.get("day", {}) or {}).get("duty_joint_constraints", {}) or {}
    duty_joint_cfg = DutyJointConfig(
        enabled=bool(duty_joint_raw.get("enabled", True)),
        enable_soft_male_duty_balance=bool(duty_joint_raw.get("enable_soft_male_duty_balance", True)),
        w_soft_male_duty_balance=int(duty_joint_raw.get("w_soft_male_duty_balance", 60)),
        male_max_min_mode=str(duty_joint_raw.get("male_max_min_mode", "soft")),
        w_male_max_min_gap=int(duty_joint_raw.get("w_male_max_min_gap", 600)),
        male_total_target=int(duty_joint_raw.get("male_total_target", 2)),
        male_total_target_mode=str(duty_joint_raw.get("male_total_target_mode", "hard")),
        w_male_total_target_deviation=int(duty_joint_raw.get("w_male_total_target_deviation", 2500)),
        enable_female_head_extra_noon_if_no_night=bool(
            duty_joint_raw.get("enable_female_head_extra_noon_if_no_night", True)
        ),
        female_head_extra_noon_mode=str(duty_joint_raw.get("female_head_extra_noon_mode", "hard")),
        female_min_noon_night_mode=str(duty_joint_raw.get("female_min_noon_night_mode", "soft")),
        w_female_min_noon_night=int(duty_joint_raw.get("w_female_min_noon_night", 2000)),
        enable_female_two_duty_penalty=bool(duty_joint_raw.get("enable_female_two_duty_penalty", True)),
        w_female_two_duty_penalty=int(duty_joint_raw.get("w_female_two_duty_penalty", 3000)),
        pm_pre_class_no_consecutive_mode=str(duty_joint_raw.get("pm_pre_class_no_consecutive_mode", "hard")),
        w_pm_pre_class_no_consecutive=int(duty_joint_raw.get("w_pm_pre_class_no_consecutive", 2000)),
        female_total_limit_extra_teachers=teacher_names(duty_joint_raw.get("female_total_limit_extra_teachers", [])),
        male_balance_exclude_teachers=teacher_names(duty_joint_raw.get("male_balance_exclude_teachers", [])),
        male_total_eq2_exclude_teachers=teacher_names(duty_joint_raw.get("male_total_eq2_exclude_teachers", [])),
        noon_max1_teachers=teacher_names(duty_joint_raw.get("noon_max1_teachers", [])),
        total_noon_night_max1_teachers=teacher_names(duty_joint_raw.get("total_noon_night_max1_teachers", [])),
        male_noon_rule_exempt_teachers=teacher_names(duty_joint_raw.get("male_noon_rule_exempt_teachers", [])),
    )
    duty_joint_penalties, duty_joint_info = add_duty_joint_constraints(
        model,
        days=day_build.noon_days,
        noon_male_duty=day_build.noon_male_vars,
        noon_female_duty=day_build.noon_female_vars,
        pm_pre_class_duty=day_build.duty_vars,
        night_dorm_duty_male=night_build.vars.get("checkin_m", {}),
        night_dorm_duty_female=night_build.vars.get("checkin_f", {}),
        male_heads=night_build.ctx.get("male_heads", []),
        female_heads=night_build.ctx.get("female_heads", []),
        cfg=duty_joint_cfg,
    )
    write_duty_joint_audit(day_build.out_dir, duty_joint_info)

    grade_group_raw = (io_cfg.get("day", {}) or {}).get("grade_group_duty", {}) or {}
    grade_group_cfg = GradeGroupDutyConfig(
        enabled=bool(grade_group_raw.get("enabled", True)),
        members=teacher_names(grade_group_raw.get("members", [])),
        min_once_mode=str(grade_group_raw.get("min_once_mode", "hard")),
        w_min_once=int(grade_group_raw.get("w_min_once", 1000)),
        daily_need_night_mode=str(grade_group_raw.get("daily_need_night_mode", "soft")),
        w_daily_need_night=int(grade_group_raw.get("w_daily_need_night", 2000)),
        w_no_night_penalty=int(grade_group_raw.get("w_no_night_penalty", 1000)),
        enable_fairness=bool(grade_group_raw.get("enable_fairness", True)),
        w_fairness_balance=int(grade_group_raw.get("w_fairness_balance", 100)),
    )
    grade_group_penalties, grade_group_duty_vars, grade_group_info = apply_grade_group_duty_constraints(
        model,
        days=night_build.ctx.get("days", []),
        on_teacher_day=night_build.vars.get("on_teacher_day", {}),
        all_teachers=night_build.vars.get("all_teachers", []),
        cfg=grade_group_cfg,
    )
    write_grade_group_duty_audit(day_build.out_dir, grade_group_info)

    bridge = build_bridge_vars(model, day_build.data, day_build.dv, night_build.vars, night_build.ctx)
    write_link_audit(day_build.out_dir, bridge)
    link_penalties, link_stats = add_link_constraints(model, bridge, day_build.day_night_link_cfg)

    hard_notes, pers_penalties, pers_stats = apply_personalized_constraints(
        model,
        day_build.data,
        day_build.dv,
        night_build.vars,
        night_build.ctx,
        bridge,
        day_build.pers_cfg,
        day_build.out_dir,
    )
    noon_night_penalties = add_noon_night_checkin_coupling(
        model,
        day_build.noon_female_vars,
        night_build.vars,
        day_build.noon_dorm_cfg,
    )
    noon_prev_same_penalties = add_noon_prev_same_day_no_night_class_constraints(
        model,
        noon_male=day_build.noon_male_vars,
        noon_female=day_build.noon_female_vars,
        night_vars=night_build.vars,
        hard_teachers=teacher_names(((io_cfg.get("day", {}) or {}).get("noon_dorm_duty", {}) or {}).get("prev_same_day_no_night_hard_teachers", [])),
        soft_weight=3000,
    )

    snapshot_day_ctx = {
        "data": day_build.data,
        "dv": day_build.dv,
        "head_teachers": day_build.head_teachers,
        "duty_vars": day_build.duty_vars,
        "teach_pm1_vars": day_build.teach_pm1_vars,
        "excess_duty": day_build.excess_duty,
        "excess_pm1": day_build.excess_pm1,
        "duty_floor_vars": day_build.duty_floor_vars,
        "duty_trigger_vars": day_build.duty_trigger_vars,
        "head_floor_by_teacher": day_build.head_floor_by_teacher,
        "head_floor_groups": day_build.head_floor_groups,
        "head_allowed_duty_floors": day_build.head_allowed_duty_floors,
        "head_borrow_5_to_4": day_build.head_borrow_5_to_4,
        "head_weekly_duty_count_45f": day_build.head_weekly_duty_count_45f,
        "head_h4_base": day_build.head_h4_base,
        "head_h5_base": day_build.head_h5_base,
        "head_t9_teacher": day_build.head_t9_teacher,
        "head_duty_days": day_build.head_duty_days,
        "weekday_cfg": day_build.weekday_cfg,
        "pe_teachers": day_build.pe_teachers,
        "pe_tech_teachers": day_build.pe_tech_teachers,
        "pe_cfg": day_build.pe_cfg,
        "liu_allowed": day_build.liu_allowed,
        "tao_allowed": day_build.tao_allowed,
        "liu_viol_fixed": day_build.liu_viol_fixed,
        "tao_viol_fixed": day_build.tao_viol_fixed,
        "pe_illegal_fixed": day_build.pe_illegal_fixed,
        "pe_gap_details": day_build.pe_gap_details,
        "pe_am_penalties": day_build.pe_am_penalties,
        "multi_details": day_build.multi_details,
        "am4pm1_details": day_build.am4pm1_details,
        "continuity_details": day_build.continuity_details,
        "core_load_details": day_build.core_load_details,
        "m1_cap_details": day_build.m1_cap_details,
        "lang_am_vars": day_build.lang_am_vars,
        "lang_pm_vars": day_build.lang_pm_vars,
        "lang_fixed": day_build.lang_fixed,
        "stem_am1_vars": day_build.stem_am1_vars,
        "stem_am1_fixed": day_build.stem_am1_fixed,
        "teacher_am1_details": day_build.teacher_am1_details,
        "two_class_details": day_build.two_class_details,
        "weekday_balance_penalties": day_build.weekday_balance_penalties,
        "day_night_link_cfg": day_build.day_night_link_cfg,
        "head_duty_w_excess_duty": day_build.head_duty_cfg.w_excess_duty,
        "head_duty_w_excess_pm1": day_build.head_duty_cfg.w_pm1_penalty,
        "noon_male_vars": day_build.noon_male_vars,
        "noon_female_vars": day_build.noon_female_vars,
        "noon_day_penalty": day_build.noon_day_penalty,
        "noon_days": day_build.noon_days,
        "grade_group_duty_vars": grade_group_duty_vars,
        "grade_group_info": grade_group_info,
        "pers_stats": pers_stats,
        "pers_hard_notes": hard_notes,
    }
    snapshot_night_ctx = {"vars": night_build.vars, "ctx": night_build.ctx, "rules": night_build.rules}

    return JointCrossBuildResult(
        bridge=bridge,
        link_penalties=link_penalties,
        link_stats=link_stats,
        duty_joint_penalties=duty_joint_penalties,
        duty_joint_info=duty_joint_info,
        grade_group_penalties=grade_group_penalties,
        grade_group_duty_vars=grade_group_duty_vars,
        grade_group_info=grade_group_info,
        hard_notes=hard_notes,
        pers_penalties=pers_penalties,
        pers_stats=pers_stats,
        noon_night_penalties=noon_night_penalties,
        noon_prev_same_penalties=noon_prev_same_penalties,
        snapshot_day_ctx=snapshot_day_ctx,
        snapshot_night_ctx=snapshot_night_ctx,
    )


def apply_joint_warm_start_hints(
    model: cp_model.CpModel,
    day_build: DayBuildResult,
    night_build: NightBuildResult,
    warm_cfg: WarmStartConfig,
    rules_hash: str,
    data_hash: str,
) -> WarmStartApplyResult:
    audit_path = day_build.out_dir / "warm_start_audit_before.txt"
    day_example = None
    if day_build.dv.x:
        k = next(iter(day_build.dv.x.keys()))
        day_example = [k[0], k[1], k[2].day, k[2].block, str(k[2].period)]
    night_example = None
    if night_build.vars.get("y"):
        k2 = next(iter(night_build.vars["y"].keys()))
        night_example = [k2[0], k2[1], k2[2], k2[3]]
    audit_lines = [
        "[Warm Start Audit Before]",
        f"Entry=scheduler/joint_solver.py",
        f"DayVar=day_vars.x key=[class,subject,day,block,period] example={day_example}",
        f"NightVar=night_vars.y key=[class,subject,day,period] example={night_example}",
        f"OutputDir={day_build.out_dir}",
        f"DayOutputPattern={day_build.summary_out.name},{day_build.formal_out.name}",
        f"NightOutputPattern={night_build.out_path.name}",
    ]
    audit_path.write_text("\n".join(audit_lines), encoding="utf-8")

    hint_report = day_build.out_dir / "hint_apply_report.txt"
    selected = select_solution_file(warm_cfg, rules_hash, data_hash)
    applied_day = applied_night = missing_day = missing_night = 0
    skipped_samples: List[str] = []
    if warm_cfg.enabled and selected:
        try:
            payload = load_solution_json(selected)
            day_list = payload.get("day", {}).get("x1", [])
            night_list = payload.get("night", {}).get("y1", [])
            day_map = {}
            for (cls, subj, slot), var in day_build.dv.x.items():
                key = (cls, subj, slot.day, slot.block, str(slot.period))
                day_map[key] = var
            night_map = {}
            for (cls, subj, d, p), var in night_build.vars.get("y", {}).items():
                night_map[(cls, subj, d, str(p))] = var
            for rec in day_list:
                if len(rec) != 5:
                    missing_day += 1
                    if len(skipped_samples) < 20:
                        skipped_samples.append(f"day_mismatch:{rec}")
                    continue
                key = (rec[0], rec[1], rec[2], rec[3], str(rec[4]))
                var = day_map.get(key)
                if var is None:
                    missing_day += 1
                    if len(skipped_samples) < 20:
                        skipped_samples.append(f"day_missing:{rec}")
                    continue
                model.AddHint(var, 1)
                applied_day += 1
            for rec in night_list:
                if len(rec) != 4:
                    missing_night += 1
                    if len(skipped_samples) < 20:
                        skipped_samples.append(f"night_mismatch:{rec}")
                    continue
                key = (rec[0], rec[1], rec[2], str(rec[3]))
                var = night_map.get(key)
                if var is None:
                    missing_night += 1
                    if len(skipped_samples) < 20:
                        skipped_samples.append(f"night_missing:{rec}")
                    continue
                model.AddHint(var, 1)
                applied_night += 1
        except Exception as exc:
            skipped_samples.append(f"exception:{exc}")
    else:
        selected = None

    hint_lines = [
        "[Hint Apply Report]",
        f"SelectedFile={selected}",
        f"ExpectedDay={applied_day + missing_day}",
        f"ExpectedNight={applied_night + missing_night}",
        f"AppliedDay={applied_day}",
        f"AppliedNight={applied_night}",
        f"SkippedDay={missing_day}",
        f"SkippedNight={missing_night}",
        "SkippedSamples=",
    ] + [f"  {s}" for s in skipped_samples]
    hint_report.write_text("\n".join(hint_lines), encoding="utf-8")
    return WarmStartApplyResult(selected=selected)


def build_and_apply_joint_objective(
    model: cp_model.CpModel,
    day_build: DayBuildResult,
    night_build: NightBuildResult,
    cross: JointCrossBuildResult,
) -> list:
    objective_terms = []
    objective_terms.extend(day_build.objective_terms)
    objective_terms.extend(night_build.penalties)
    objective_terms.extend(cross.link_penalties)
    objective_terms.extend(cross.pers_penalties)
    objective_terms.extend(cross.noon_night_penalties)
    objective_terms.extend(cross.noon_prev_same_penalties)
    objective_terms.extend(cross.duty_joint_penalties)
    objective_terms.extend(cross.grade_group_penalties)
    if objective_terms:
        model.Minimize(sum(objective_terms))
    validate_registered_rule_meta(context="joint")
    return objective_terms


def solve_joint_model(
    model: cp_model.CpModel,
    io_cfg: dict,
    effective: object,
    grade_prefix: str,
    artifact_cfg: JointArtifactConfig,
    cross: JointCrossBuildResult,
) -> JointSolveResult:
    joint_cfg = io_cfg.get("joint_solve", {}) or {}
    solve_config = build_scheduler_cp_sat_solve_config(joint_cfg, default_time_limit_seconds=300)

    callback = None
    counting_callback = CountingSolutionCallback()
    active_callback: cp_model.CpSolverSolutionCallback = counting_callback
    solve_start_dt = datetime.now()
    solve_start_ts = time.perf_counter()
    use_callback = artifact_cfg.snapshot_cfg.enabled or artifact_cfg.archive_cfg.enabled
    if use_callback:
        callback = TimedSnapshotExportCallback(
            artifact_cfg.snapshot_cfg,
            archive_cfg=artifact_cfg.archive_cfg,
            effective_config=effective.effective_cfg,
            config_diff_text=effective.config_diff_text,
            day_ctx=cross.snapshot_day_ctx if (artifact_cfg.snapshot_cfg.export_day or artifact_cfg.archive_cfg.enabled) else None,
            night_ctx=cross.snapshot_night_ctx if (artifact_cfg.snapshot_cfg.export_night or artifact_cfg.archive_cfg.enabled) else None,
            bridge=cross.bridge if artifact_cfg.snapshot_cfg.export_link_reports else None,
            link_stats=cross.link_stats if artifact_cfg.snapshot_cfg.export_link_reports else None,
            grade_prefix=grade_prefix,
            stop_file=artifact_cfg.stop_file,
        )
        active_callback = callback
    logger.info("开始求解时间：%s", solve_start_dt.strftime("%Y-%m-%d %H:%M:%S"))
    solve_result = solve_existing_cp_model(model, solve_config, solution_callback=active_callback)
    solver = solve_result.solver
    status = solve_result.status

    solve_end_dt = datetime.now()
    solve_elapsed_sec = time.perf_counter() - solve_start_ts
    status_name = solver.StatusName(status)
    logger.info("=== Joint Solve Status ===")
    logger.info("status = %s", status_name)
    feasible_count = 0
    try:
        feasible_count = int(active_callback.NumSolutions())
    except Exception:
        feasible_count = 1 if status in (cp_model.OPTIMAL, cp_model.FEASIBLE) else 0
    logger.info("求解完成时间：%s", solve_end_dt.strftime("%Y-%m-%d %H:%M:%S"))
    logger.info("求解总耗时：%.3f 秒", solve_elapsed_sec)
    logger.info("回调捕获解数量：%d", feasible_count)
    return JointSolveResult(
        solver=solver,
        status=status,
        status_name=status_name,
        feasible_count=feasible_count,
        callback=callback,
    )


def write_joint_diagnostics(
    io_path: Path,
    day_build: DayBuildResult,
    night_build: NightBuildResult,
    cross: JointCrossBuildResult,
    solve: JointSolveResult,
    archive_cfg: SolutionArchiveConfig,
) -> None:
    solver = solve.solver
    status = solve.status
    status_name = solve.status_name
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        if cross.hard_notes:
            write_personalized_infeasible_hints(day_build.out_dir, cross.hard_notes)
        write_day_infeasible_hints(day_build.out_dir, day_build.weekday_cfg)
        if day_build.core_load_details:
            write_core_teacher_day_load_infeasible_hint(day_build.out_dir, day_build.core_load_details)
        if day_build.m1_cap_structural_impossible:
            write_teacher_m1_cap_infeasible_hint(
                day_build.out_dir,
                day_build.m1_cap_structural_impossible,
                day_build.weekday_cfg.teacher_m1_cap_max,
            )
        if day_build.head_duty_cfg.enable_head_duty:
            write_head_duty_infeasible_hints(
                day_build.out_dir,
                day_build.data,
                day_build.head_teachers,
                day_build.teach_pm1_vars,
                day_build.head_floor_groups,
                day_build.head_duty_hints,
                day_build.head_duty_cfg,
            )
        link_hints = []
        if (
            day_build.day_night_link_cfg.enable_sun_pm_night_no_mon_am
            and str(day_build.day_night_link_cfg.sun_pm_night_no_mon_am_mode).lower() == "hard"
        ):
            link_hints.append("联动硬约束：周日+周日晚自习 与 周一上午1/2 禁止组合")
        if day_build.day_night_link_cfg.enable_night_requires_day and str(day_build.day_night_link_cfg.night_requires_day_mode).lower() == "hard":
            link_hints.append("联动硬约束：白天无课不得安排晚自习/晚查寝")
        if link_hints:
            (day_build.out_dir / "joint_infeasible_hints.txt").write_text(
                "[Joint Infeasible Hints]\n可能冲突来源：\n- " + "\n- ".join(link_hints) + "\n",
                encoding="utf-8",
            )
            append_infeasible_audit(
                io_path.parent.parent,
                night_build.rules,
                link_hints,
            )

    suspected = []
    if day_build.weekend_diag.teacher_weekend_hours_odd:
        suspected.append("周末课时为奇数（成对约束）")
    if day_build.weekend_cfg.enable_weekend_one_day_only:
        suspected.append("周末同一老师不得跨两天")
    if day_build.weekend_cfg.enable_weekend_subject_whitelist:
        suspected.append("周末学科白名单")
    write_weekend_diagnostic(day_build.out_dir, day_build.weekend_diag, status_name, suspected)

    mr_results = None
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        mr_results = extract_morning_reading_results(day_build.data, day_build.dv, solver)
    write_morning_reading_diagnostic(day_build.out_dir, check_morning_reading_inputs(day_build.data)[0], status_name, results=mr_results)

    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE) and not archive_cfg.enabled:
        write_day_check_hard_constraints(day_build.out_dir, day_build.data, day_build.dv, solver, day_build.head_teachers, day_build.pe_teachers)
        if day_build.core_load_details:
            write_core_teacher_day_load_sanity(day_build.out_dir, solver, day_build.core_load_details)
        if day_build.m1_cap_details:
            write_teacher_m1_cap_report(
                day_build.out_dir,
                solver,
                day_build.m1_cap_details,
                day_build.weekday_cfg.teacher_m1_cap_max,
                day_build.weekday_cfg.w_hit_m1_cap,
            )
        write_day_constraint_checklist(
            day_build.out_dir,
            day_build.data,
            day_build.dv,
            solver,
            day_build.head_teachers,
            day_build.pe_teachers,
            day_build.multi_details,
            day_build.am4pm1_details,
            (
                day_build.weekday_cfg.teacher_am4_pm1_w3,
                day_build.weekday_cfg.teacher_am4_pm1_w4,
                day_build.weekday_cfg.teacher_am4_pm1_w5,
                day_build.weekday_cfg.teacher_am4_pm1_w6,
            ),
            day_build.weekday_balance_penalties,
        )
        if day_build.continuity_details:
            write_teacher_continuity_report(day_build.out_dir, solver, day_build.continuity_details)
        if day_build.am4pm1_details:
            write_teacher_am4_pm1_penalty_report(
                day_build.out_dir,
                solver,
                day_build.am4pm1_details,
                (
                    day_build.weekday_cfg.teacher_am4_pm1_w3,
                    day_build.weekday_cfg.teacher_am4_pm1_w4,
                    day_build.weekday_cfg.teacher_am4_pm1_w5,
                    day_build.weekday_cfg.teacher_am4_pm1_w6,
                ),
            )
        if day_build.head_duty_cfg.enable_head_duty and day_build.duty_vars:
            write_head_duty_hard_check(
                day_build.out_dir,
                solver,
                day_build.duty_vars,
                day_build.teach_pm1_vars,
                day_build.head_teachers,
                day_build.head_duty_days,
                day_build.duty_floor_vars,
                day_build.head_floor_groups,
                day_build.head_floor_by_teacher,
                day_build.head_allowed_duty_floors,
                day_build.head_weekly_duty_count_45f,
                day_build.head_borrow_5_to_4,
            )
            write_head_duty_soft_report(
                day_build.out_dir,
                solver,
                day_build.duty_vars,
                day_build.teach_pm1_vars,
                day_build.head_teachers,
                day_build.head_duty_days,
                day_build.excess_duty,
                day_build.excess_pm1,
                day_build.head_duty_cfg.w_excess_duty,
                day_build.head_duty_cfg.w_pm1_penalty,
                day_build.head_weekly_duty_count_45f,
                day_build.head_borrow_5_to_4,
                day_build.head_h4_base,
                day_build.head_h5_base,
                day_build.head_t9_teacher,
            )
        if day_build.two_class_details or day_build.weekday_cfg.two_class_daily_min_mode == "hard":
            write_two_class_daily_min_report(
                day_build.out_dir, solver, day_build.two_class_details, day_build.weekday_cfg.two_class_daily_min_mode
            )
        write_day_soft_timepref_report(
            day_build.out_dir,
            solver,
            day_build.lang_am_vars,
            day_build.lang_pm_vars,
            day_build.lang_fixed,
            day_build.stem_am1_vars,
            day_build.stem_am1_fixed,
            day_build.teacher_am1_details,
            (
                day_build.weekday_cfg.w_lang_pm_penalty,
                day_build.weekday_cfg.w_lang_am_reward,
                day_build.weekday_cfg.w_stem_am1_penalty,
                day_build.weekday_cfg.w_teacher_only_am1_day,
                day_build.weekday_cfg.k_teacher_am1_week,
                day_build.weekday_cfg.w_teacher_am1_excess,
            ),
        )
        write_pe_tech_checklist(
            day_build.out_dir,
            day_build.data,
            day_build.dv,
            solver,
            day_build.pe_teachers,
            day_build.pe_tech_teachers,
            day_build.liu_allowed,
            day_build.tao_allowed,
            day_build.liu_viol_fixed,
            day_build.tao_viol_fixed,
            day_build.pe_illegal_fixed,
            day_build.pe_am_penalties,
            day_build.pe_gap_details,
            (day_build.pe_cfg.w_pe_am_penalty, day_build.pe_cfg.w_pe_gap_penalty),
        )
        if day_build.noon_male_vars:
            write_noon_dorm_checklist(
                day_build.out_dir,
                solver,
                day_build.noon_days,
                day_build.noon_male_vars,
                day_build.noon_female_vars,
                day_build.noon_day_penalty,
            )
        write_duty_joint_checklist(day_build.out_dir, solver, cross.duty_joint_info)
        write_grade_group_duty_checklist(
            day_build.out_dir,
            solver,
            info=cross.grade_group_info,
            grade_duty=cross.grade_group_duty_vars,
            on_teacher_day=night_build.vars.get("on_teacher_day", {}),
        )
        write_link_checklist(day_build.out_dir, solver, cross.bridge, cross.link_stats, day_build.day_night_link_cfg)


def export_joint_solution_outputs(
    io_path: Path,
    ts: str,
    grade_prefix: str,
    day_build: DayBuildResult,
    night_build: NightBuildResult,
    cross: JointCrossBuildResult,
    solve: JointSolveResult,
    artifact_cfg: JointArtifactConfig,
    objective_terms: list,
    rules_hash: str,
    data_hash: str,
) -> None:
    solver = solve.solver
    status = solve.status
    status_name = solve.status_name
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return

    event_log_path = write_event_log_csv(
        day_build.out_dir,
        solver,
        solution_id=f"final_{ts}",
        snapshot_id="最终解",
    )
    final_rows = summarize_event_log_csv(event_log_path)
    final_csv = day_build.out_dir / "final_soft_violation_summary.csv"
    with final_csv.open("w", encoding="utf-8-sig") as f:
        f.write("rule_id,rule_name,teacher,weight,count,penalty_sum\n")
        for r in final_rows:
            f.write(
                f"{r.get('rule_id','')},{r.get('rule_name','')},{r.get('teacher','')},"
                f"{r.get('weight',0)},{r.get('count',0)},{r.get('penalty_sum',0)}\n"
            )

    final_cn_csv = day_build.out_dir / "最终解_软约束未满足明细.csv"
    with final_cn_csv.open("w", encoding="utf-8-sig") as f:
        f.write("约束ID,约束名称,教师,权重,触发次数,罚分合计\n")
        for r in final_rows:
            if float(r.get("count", 0) or 0) <= 0:
                continue
            if float(r.get("penalty_sum", 0) or 0) <= 0:
                continue
            f.write(
                f"{r.get('rule_id','')},{r.get('rule_name','')},{r.get('teacher','')},"
                f"{r.get('weight',0)},{r.get('count',0)},{r.get('penalty_sum',0)}\n"
            )
    final_score_txt = day_build.out_dir / "最终解_评分摘要.txt"
    final_score_txt.write_text(
        "\n".join(
            [
                "[最终解评分摘要]",
                f"状态：{status_name}",
                f"目标值：{float(solver.ObjectiveValue() if objective_terms else 0.0)}",
                f"软约束总罚分：{sum(float(r.get('penalty_sum', 0) or 0) for r in final_rows)}",
            ]
        ),
        encoding="utf-8",
    )
    final_solver_meta = enrich_solver_overview({
        "solution_id": f"final_{ts}",
        "snapshot_id": "最终解",
        "solver_status": status_name,
        "objective_value": float(solver.ObjectiveValue() if objective_terms else 0.0),
        "best_bound": float(solver.BestObjectiveBound()) if objective_terms else None,
        "time_limit": float(solver.parameters.max_time_in_seconds) if hasattr(solver, "parameters") else None,
        "num_conflicts": int(solver.NumConflicts()),
        "num_branches": int(solver.NumBranches()),
        "wall_time": float(solver.WallTime()),
        "is_best_solution": True,
    })
    (day_build.out_dir / "final_solver_overview.json").write_text(
        json.dumps(final_solver_meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if solve.callback is not None:
        solve.callback.record_final_solver_overview(solver, final_solver_meta)

    meta = {
        "timestamp": ts,
        "status": status_name,
        "objective": float(solver.ObjectiveValue() if objective_terms else 0.0),
        "rules_hash": rules_hash,
        "data_hash": data_hash,
    }
    day_x1 = []
    for (cls, subj, slot), var in day_build.dv.x.items():
        if solver.Value(var) == 1:
            day_x1.append([cls, subj, slot.day, slot.block, str(slot.period)])
    night_y1 = []
    for (cls, subj, d, p), var in night_build.vars.get("y", {}).items():
        if solver.Value(var) == 1:
            night_y1.append([cls, subj, d, str(p)])
    if artifact_cfg.warm_cfg.enabled:
        save_solution_json(artifact_cfg.warm_cfg.path, meta, day_x1, night_y1)
        best_save = save_best_solution_json(artifact_cfg.warm_cfg.best_path, meta, day_x1, night_y1)
        if artifact_cfg.warm_cfg.pool_dir:
            pool_path = artifact_cfg.warm_cfg.pool_dir / f"solution_{ts}_{status_name}.json"
            save_solution_json(pool_path, meta, day_x1, night_y1)
            trim_solution_pool(artifact_cfg.warm_cfg.pool_dir, artifact_cfg.warm_cfg.keep_last_n)
        else:
            pool_path = None

        save_report = day_build.out_dir / "warm_start_save_report.txt"
        save_lines = [
            "[Warm Start Save Report]",
            f"LastSolution={artifact_cfg.warm_cfg.path}",
            f"BestSolution={artifact_cfg.warm_cfg.best_path}",
            f"BestSolutionStatus={best_save.get('status')}",
            f"BestSolutionObjective={best_save.get('objective')}",
            f"BestSolutionExistingObjective={best_save.get('existing_objective', best_save.get('previous_objective', ''))}",
            f"PoolDir={artifact_cfg.warm_cfg.pool_dir}",
            f"PoolSaved={pool_path}",
            f"DayCount={len(day_x1)}",
            f"NightCount={len(night_y1)}",
            f"Meta={meta}",
        ]
        save_report.write_text("\n".join(save_lines), encoding="utf-8")

    write_personalized_checklist(day_build.out_dir, solver, cross.pers_stats, cross.hard_notes)

    write_night_constraint_checklist(
        io_path.parent.parent,
        night_build.rules,
        night_build.ctx,
        night_build.vars,
        solver,
        status_name,
    )
    write_double_class_weekday_p1_p2_report(
        day_build.out_dir,
        solver,
        night_build.vars,
        night_build.ctx,
        night_build.rules,
    )

    evening_assign = build_evening_assignments_from_solver(solver, night_build.vars, night_build.ctx)
    checkin_rows = build_checkin_rows_from_solver(
        night_build.vars.get("checkin_m", {}),
        night_build.vars.get("checkin_f", {}),
        night_build.ctx["days"],
        night_build.ctx["male_heads"],
        night_build.ctx["female_heads"],
        solver,
    )
    head_duty_result = None
    if day_build.duty_vars:
        head_duty_result = extract_duty_results(
            solver, day_build.duty_vars, day_build.head_teachers, day_build.head_duty_days
        )
    noon_dorm_rows = None
    if day_build.noon_male_vars:
        noon_dorm_rows = extract_noon_dorm_rows(
            solver,
            day_build.noon_days,
            day_build.noon_male_vars,
            day_build.noon_female_vars,
            day_build.noon_day_penalty,
        )
    grade_duty_map = extract_grade_group_duty_map(
        solver,
        cross.grade_group_duty_vars,
        cross.grade_group_info.get("days", []),
        cross.grade_group_info.get("members", []),
    )
    grade_available_map = extract_grade_group_available_map(
        solver,
        night_build.vars.get("on_teacher_day", {}),
        cross.grade_group_info.get("days", []),
        cross.grade_group_info.get("members", []),
    )
    save_day_class_and_teacher_summary_excel(
        day_build.data,
        day_build.dv,
        solver,
        str(day_build.summary_out),
        evening_assign=evening_assign,
        grade_prefix=grade_prefix,
        head_teachers=day_build.head_teachers,
        male_head_teachers=night_build.ctx.get("male_heads", []),
        female_head_teachers=night_build.ctx.get("female_heads", []),
        head_duty_result=head_duty_result,
        duty_floor_vars=day_build.duty_floor_vars,
        head_floor_groups=day_build.head_floor_groups,
        checkin_rows=checkin_rows,
        noon_dorm_rows=noon_dorm_rows,
        grade_group_duty_map=grade_duty_map,
        grade_group_available_map=grade_available_map,
    )
    wide_df = export_day_schedule_df(day_build.data, day_build.dv, solver)
    grid_dfs = export_day_schedule_grid_df(day_build.data, day_build.dv, solver)
    save_day_schedule_excel(wide_df, grid_dfs, str(day_build.formal_out))


def finalize_joint_outputs(
    ts: str,
    day_build: DayBuildResult,
    solve: JointSolveResult,
    objective_terms: list,
    warm_start: WarmStartApplyResult,
    warm_cfg: WarmStartConfig,
    rules_hash: str,
    data_hash: str,
) -> None:
    archive_result = None
    if solve.callback is not None:
        archive_result = solve.callback.export_solution_archive(
            mode="joint",
            root_best_copy=day_build.summary_out,
            root_formal_copy=day_build.formal_out,
        )
        if archive_result:
            logger.info(
                "多解输出完成：run_dir=%s, top_count=%s, best=%s, diagnostics=%s",
                str(archive_result.get("run_dir", "")),
                int(archive_result.get("top_count", 0) or 0),
                str(archive_result.get("best_excel", "")),
                str(archive_result.get("diag_excel", "")),
            )

    move_diagnostics_to_folder(day_build.out_dir)
    if archive_result and archive_result.get("diag_excel"):
        diag_xlsx = Path(str(archive_result.get("diag_excel")))
    else:
        diag_xlsx = build_multi_solution_diagnostic(day_build.out_dir)
    objective_val = float(solve.solver.ObjectiveValue()) if objective_terms else 0.0
    write_baseline_report(
        day_build.out_dir,
        mode="joint",
        status=solve.status_name,
        objective=objective_val if solve.status in (cp_model.OPTIMAL, cp_model.FEASIBLE) else None,
        expected_files=[
            day_build.summary_out,
            day_build.formal_out,
            day_build.out_dir / "event_log.csv",
            diag_xlsx,
        ],
        extra={"rules_hash": rules_hash, "data_hash": data_hash},
    )

    bench_path = day_build.out_dir / "warm_start_benchmark.txt"
    bench_line = (
        f"{ts} enabled={warm_cfg.enabled} selected={warm_start.selected} "
        f"status={solve.status_name} obj={float(solve.solver.ObjectiveValue() if objective_terms else 0.0)} "
        f"wall_time={solve.solver.WallTime()} rules_hash={rules_hash} data_hash={data_hash}"
    )
    if bench_path.exists():
        bench_path.write_text(bench_path.read_text(encoding="utf-8") + "\n" + bench_line, encoding="utf-8")
    else:
        bench_path.write_text("[Warm Start Benchmark]\n" + bench_line, encoding="utf-8")
    move_root_meta_files(day_build.out_dir, folder_name="meta", include_txt=True, include_json=True, include_csv=True)
