"""白天排课主入口。

职责：
- 读取白天规则与教师表
- 建模并添加白天约束与软目标
- 求解并导出白天课表与诊断文件
- 可选读取晚自习结果并合并导出

说明：
- 该文件名历史上是 smoke_test，但当前是白天流程入口
- 仅做流程编排，不应在此实现约束逻辑
"""

from __future__ import annotations

from pathlib import Path
from datetime import datetime
import logging
import json

from ortools.sat.python import cp_model

from ai_orchestrated_optimization import create_existing_cp_model, solve_existing_cp_model
from scheduler.config.loader import load_effective_config
from scheduler.joint_solver import build_day_model
from scheduler.output.day_exporter import export_day_schedule_df, export_day_schedule_grid_df, save_day_schedule_excel
from scheduler.output.day_exporter_combo import save_day_class_and_teacher_summary_excel
from scheduler.data.evening_excel_reader import read_evening_assignments, read_evening_checkin_rows
from scheduler.day_constraints_morning_reading import (
    extract_morning_reading_results,
    write_morning_reading_diagnostic,
    check_morning_reading_inputs,
)
from scheduler.model.constraints.day_weekend_constraints import write_weekend_diagnostic
from scheduler.model.constraints.day_weekday_constraints import (
    write_day_check_hard_constraints,
    write_day_constraint_checklist,
    write_day_soft_timepref_report,
    write_two_class_daily_min_report,
    write_teacher_continuity_report,
    write_teacher_am4_pm1_penalty_report,
    write_core_teacher_day_load_sanity,
    write_core_teacher_day_load_infeasible_hint,
    write_teacher_m1_cap_report,
    write_teacher_m1_cap_infeasible_hint,
    write_day_infeasible_hints,
)
from scheduler.model.constraints.day_pe_tech_constraints import write_pe_tech_checklist
from scheduler.model.constraints.day_head_teacher_duty_constraints import (
    write_head_duty_hard_check,
    write_head_duty_soft_report,
    write_head_duty_infeasible_hints,
)
from scheduler.model.constraints.day_noon_dorm_duty_constraints import (
    write_noon_dorm_checklist,
    extract_noon_dorm_rows,
)
from scheduler.model.constraints.duty_joint_constraints import (
    DutyJointConfig,
    add_duty_joint_constraints,
    write_duty_joint_audit,
    write_duty_joint_checklist,
    load_head_gender_sets,
)
from scheduler.model.constraints.personalized_constraints import (
    PersonalizedConfig,
    apply_personalized_constraints,
    write_personalized_checklist,
    write_personalized_infeasible_hints,
)
from scheduler.diagnostic_utils import move_diagnostics_to_folder, move_root_meta_files
from scheduler.output_paths import resolve_project_path
from scheduler.solver_params import build_scheduler_cp_sat_solve_config
from scheduler.solver_quality import enrich_solver_overview
from scheduler.solver_callbacks.timed_snapshot_callback import (
    SnapshotExportConfig,
    TimedSnapshotExportCallback,
)
from scheduler.snapshot_diagnostics import build_multi_solution_diagnostic
from scheduler.diagnostics.penalty_registry import (
    clear_registry,
    summarize_event_log_csv,
    validate_registered_rule_meta,
    write_event_log_csv,
)
from scheduler.diagnostics.baseline_report import write_baseline_report
from scheduler.rules.runtime import bind_rule_wrappers_for_module

logger = logging.getLogger(__name__)

bind_rule_wrappers_for_module(__name__, globals())


def run_day(
    rules_path: Path | None = None,
    pos_path: Path | None = None,
    outputs_dir: Path | None = None,
    evening_xlsx: Path | None = None,
    grade_prefix: str = "高二",
    io_path: Path | None = None,
) -> None:
    """白天排课主流程。

    参数：
    - rules_path：白天规则 Excel 路径
    - pos_path：教师定位表路径
    - outputs_dir：输出目录
    - evening_xlsx：晚自习导出结果路径
    - grade_prefix：年级前缀，用于筛选班级
    - io_path：统一配置文件 io.yaml
    """
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    clear_registry()

    # 统一配置模式：默认使用 scheduler/config/io.yaml
    if io_path is None:
        io_path = Path(__file__).resolve().parent / "config" / "io.yaml"
    io_path = Path(io_path)
    if not io_path.is_absolute():
        # 相对路径按项目根目录解析，避免在子目录运行导致输出偏移
        project_root = Path(__file__).resolve().parent.parent
        io_path = (project_root / io_path).resolve()
    if rules_path is not None and not Path(rules_path).is_absolute():
        project_root = Path(__file__).resolve().parent.parent
        rules_path = (project_root / rules_path).resolve()
    rules_path = rules_path or io_path.with_name("rules.yaml")
    effective = load_effective_config(
        "day",
        {"io_path": io_path, "rules_path": rules_path},
    )
    io_cfg = effective.io_cfg
    rules_cfg = effective.rules_cfg
    io_path = effective.io_path
    rules_path = effective.rules_path
    base_dir = io_path.parent.parent

    # 创建模型并复用 build_day_model
    model = create_existing_cp_model("scheduler.day")
    day_build = build_day_model(
        model,
        io_path,
        rules_path,
        grade_prefix,
        ts,
        io_cfg=io_cfg,
        rules_cfg=rules_cfg,
    )

    # 个性化约束
    pers_cfg_raw = io_cfg.get("personalized_constraints", {}) or {}
    personalized_rules_raw = rules_cfg.get("personalized_constraints", {}) or {}
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
        enable_zzx_prefs=pers_cfg_raw.get("enable_zzx_prefs", True),
        zzx_prefs_mode=str(pers_cfg_raw.get("zzx_prefs_mode", "soft")),
        w_zzx_no_sun_night=int(pers_cfg_raw.get("w_zzx_no_sun_night", 220)),
        w_zzx_sun_am_pref=int(pers_cfg_raw.get("w_zzx_sun_am_pref", 70)),
        w_zzx_reduce_am4=int(pers_cfg_raw.get("w_zzx_reduce_am4", 60)),
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
    )
    hard_notes, pers_penalties, pers_stats = apply_personalized_constraints(
        model,
        day_build.data,
        day_build.dv,
        None,
        None,
        None,
        pers_cfg,
        day_build.out_dir,
    )
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
        pm_pre_class_no_consecutive_mode=str(duty_joint_raw.get("pm_pre_class_no_consecutive_mode", "hard")),
        w_pm_pre_class_no_consecutive=int(duty_joint_raw.get("w_pm_pre_class_no_consecutive", 2000)),
    )
    male_heads, female_heads = load_head_gender_sets(io_cfg, base_dir)
    duty_joint_penalties, duty_joint_info = add_duty_joint_constraints(
        model,
        days=day_build.noon_days,
        noon_male_duty=day_build.noon_male_vars,
        noon_female_duty=day_build.noon_female_vars,
        pm_pre_class_duty=day_build.duty_vars,
        night_dorm_duty_male={},
        night_dorm_duty_female={},
        male_heads=male_heads,
        female_heads=female_heads,
        cfg=duty_joint_cfg,
    )
    write_duty_joint_audit(day_build.out_dir, duty_joint_info)

    # 目标函数
    objective_terms = []
    objective_terms.extend(day_build.objective_terms)
    objective_terms.extend(pers_penalties)
    objective_terms.extend(duty_joint_penalties)
    if objective_terms:
        model.Minimize(sum(objective_terms))
    validate_registered_rule_meta(context="day")

    # 求解器参数
    joint_cfg = io_cfg.get("joint_solve", {}) or {}
    solve_config = build_scheduler_cp_sat_solve_config(joint_cfg, default_time_limit_seconds=600)

    # 快照导出配置
    snapshot_raw = io_cfg.get("snapshot_export", {}) or {}
    snapshot_cfg = SnapshotExportConfig(
        enabled=bool(snapshot_raw.get("enabled", True)),
        interval_sec=int(snapshot_raw.get("interval_sec", 60)),
        root_dir=resolve_project_path(
            snapshot_raw.get("root_dir", "outputs/snapshots"),
            project_root=base_dir.parent,
            label="snapshot_export.root_dir",
            reject_scheduler_outputs=True,
        ),
        export_day=bool(snapshot_raw.get("export_day", True)),
        export_night=bool(snapshot_raw.get("export_night", False)),
        export_link_reports=bool(snapshot_raw.get("export_link_reports", False)),
        export_checklists=bool(snapshot_raw.get("export_checklists", True)),
    )

    callback = None
    if snapshot_cfg.enabled:
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
        }
        callback = TimedSnapshotExportCallback(snapshot_cfg, day_ctx=snapshot_day_ctx, grade_prefix=grade_prefix)
    solve_result = solve_existing_cp_model(model, solve_config, solution_callback=callback)
    solver = solve_result.solver
    status = solve_result.status

    status_name = solver.StatusName(status)
    logger.info("=== 求解状态 ===")
    logger.info("status = %s", status_name)

    if status == cp_model.INFEASIBLE:
        write_day_infeasible_hints(day_build.out_dir)
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
            )
        if hard_notes:
            write_personalized_infeasible_hints(day_build.out_dir, hard_notes)

    # 周末诊断
    suspected = []
    if day_build.weekend_diag.teacher_weekend_hours_odd:
        suspected.append("周末课时非偶数")
    if day_build.weekend_cfg.enable_weekend_one_day_only:
        suspected.append("周末同一教师不得跨两天")
    if day_build.weekend_cfg.enable_weekend_subject_whitelist:
        suspected.append("周末学科白名单")
    write_weekend_diagnostic(day_build.out_dir, day_build.weekend_diag, status_name, suspected)

    # 早自习诊断
    mr_results = None
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        mr_results = extract_morning_reading_results(day_build.data, day_build.dv, solver)
    write_morning_reading_diagnostic(
        day_build.out_dir, check_morning_reading_inputs(day_build.data)[0], status_name, results=mr_results
    )

    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        write_day_check_hard_constraints(
            day_build.out_dir, day_build.data, day_build.dv, solver, day_build.head_teachers, day_build.pe_teachers
        )
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
        if day_build.noon_male_vars:
            write_noon_dorm_checklist(
                day_build.out_dir,
                solver,
                day_build.noon_days,
                day_build.noon_male_vars,
                day_build.noon_female_vars,
                day_build.noon_day_penalty,
            )
        write_duty_joint_checklist(day_build.out_dir, solver, duty_joint_info)
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
        if pers_stats or hard_notes:
            write_personalized_checklist(day_build.out_dir, solver, pers_stats, hard_notes)
        # 最终解软约束明细（给综合诊断表使用）
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

    # 导出白天课表
    evening_assign = None
    checkin_rows = None
    if evening_xlsx is not None:
        try:
            evening_assign = read_evening_assignments(str(evening_xlsx))
            checkin_rows = read_evening_checkin_rows(str(evening_xlsx))
        except Exception:
            evening_assign = None
            checkin_rows = None
    else:
        # 若未指定，尝试读取晚自习默认输出
        try:
            night_out = rules_cfg.get("output", {}).get("result_xlsx", "outputs/结果_MVP.xlsx")
            night_path = resolve_project_path(
                night_out,
                project_root=base_dir.parent,
                label="rules.output.result_xlsx",
                reject_scheduler_outputs=True,
            )
            if night_path.exists():
                evening_assign = read_evening_assignments(str(night_path))
                checkin_rows = read_evening_checkin_rows(str(night_path))
            else:
                logger.warning("未发现晚自习排课文件：%s（将仅导出白天课表）", str(night_path))
        except Exception:
            pass

    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        wide_df = export_day_schedule_df(day_build.data, day_build.dv, solver)
        grid_dfs = export_day_schedule_grid_df(day_build.data, day_build.dv, solver)
        save_day_class_and_teacher_summary_excel(
            day_build.data,
            day_build.dv,
            solver,
            str(day_build.summary_out),
            evening_assign=evening_assign,
            male_head_teachers=male_heads,
            female_head_teachers=female_heads,
            duty_floor_vars=day_build.duty_floor_vars,
            head_floor_groups=day_build.head_floor_groups,
            checkin_rows=checkin_rows,
            noon_dorm_rows=(
                extract_noon_dorm_rows(
                    solver,
                    day_build.noon_days,
                    day_build.noon_male_vars,
                    day_build.noon_female_vars,
                    day_build.noon_day_penalty,
                )
                if day_build.noon_male_vars
                else None
            ),
        )
        logger.info("已导出：%s", str(day_build.summary_out))

        save_day_schedule_excel(wide_df, grid_dfs, str(day_build.formal_out))
        logger.info("已导出：%s", str(day_build.formal_out))

    move_diagnostics_to_folder(day_build.out_dir)
    diag_xlsx = build_multi_solution_diagnostic(day_build.out_dir)
    objective_val = float(solver.ObjectiveValue()) if objective_terms else 0.0
    expected = [day_build.summary_out, day_build.formal_out, day_build.out_dir / "event_log.csv", diag_xlsx]
    write_baseline_report(
        day_build.out_dir,
        mode="day",
        status=status_name,
        objective=objective_val if status in (cp_model.OPTIMAL, cp_model.FEASIBLE) else None,
        expected_files=expected,
        extra={"grade_prefix": grade_prefix},
    )
    move_root_meta_files(day_build.out_dir, folder_name="meta", include_txt=True, include_json=True, include_csv=True)


if __name__ == "__main__":
    run_day()
