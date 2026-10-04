"""晚自习排课入口。

职责：
- 读取 rules.yaml 与 io.yaml
- 构建晚自习模型与约束
- 求解并导出晚自习 Excel 与诊断文件
"""

import copy
import logging
import json
import time
from pathlib import Path
from datetime import datetime

from ortools.sat.python import cp_model

from ai_orchestrated_optimization import create_existing_cp_model, solve_existing_cp_model
from scheduler.config.loader import load_effective_config, merge_section
from scheduler.data.teacher_table_reader import checkin_candidate_pool_available, read_teacher_table
from scheduler.model.variables import build_variables, build_checkin_variables
from scheduler.model.constraints.hard_base import apply_hard_base
from scheduler.model.constraints.hard_bans import apply_hard_bans
from scheduler.model.constraints.checkin import apply_checkin
from scheduler.model.constraints.soft_objective import apply_soft_objective
from scheduler.model.constraints.hard_teacher_limits import apply_hard_teacher_limits
from scheduler.model.constraints.night_special import (
    apply_physics_math_hard_bans,
    apply_fri_sun_mutex,
    write_night_constraints_audit,
    write_night_constraint_checklist,
    append_infeasible_audit,
)
from scheduler.model.constraints.global_binding_constraints import apply_global_night_binding_8_chem_9_bio
from scheduler.model.constraints.night_single_class_period_split import (
    apply_single_class_teacher_p1_p2_split,
    apply_double_class_teacher_weekday_alternate_p1_p2,
    write_double_class_weekday_p1_p2_report,
)
from scheduler.output.night_exporter import export_result_xlsx
from scheduler.model.constraints.personalized_constraints import (
    PersonalizedConfig,
    apply_personalized_constraints,
    write_personalized_checklist,
    write_personalized_infeasible_hints,
)
from scheduler.diagnostic_utils import move_diagnostics_to_folder, move_root_meta_files
from scheduler.output_paths import resolve_output_dir, resolve_project_path
from scheduler.solver_params import build_scheduler_cp_sat_solve_config
from scheduler.solver_quality import enrich_solver_overview
from scheduler.solver_callbacks.timed_snapshot_callback import (
    SnapshotExportConfig,
    SolutionArchiveConfig,
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


class _CountingSolutionCallback(cp_model.CpSolverSolutionCallback):
    """Lightweight callback for counting solutions seen during search."""

    def __init__(self) -> None:
        super().__init__()
        self.solution_count = 0

    def on_solution_callback(self) -> None:
        self.solution_count += 1


def run_night(
    project_root: Path | None = None,
    rules_path: Path | None = None,
    io_path: Path | None = None,
) -> None:
    """晚自习主流程。"""
    clear_registry()
    # 统一将相对路径基于项目根目录解析，避免在子目录运行导致输出偏移
    project_root_fs = Path(__file__).resolve().parent.parent
    if io_path is not None and not Path(io_path).is_absolute():
        io_path = (project_root_fs / io_path).resolve()
    if rules_path is not None and not Path(rules_path).is_absolute():
        rules_path = (project_root_fs / rules_path).resolve()
    if project_root is None and io_path is None and rules_path is None:
        # 无显式路径时，默认以当前文件所在目录为基准
        project_root = Path(__file__).resolve().parent

    if project_root is not None:
        base_dir = Path(project_root)
    else:
        # 从 io.yaml 或 rules.yaml 推导项目根目录
        io_p = Path(io_path) if io_path is not None else Path(rules_path).with_name("io.yaml")
        base_dir = io_p.parent.parent

    # 统一配置入口（rules 覆盖 io）
    effective = load_effective_config(
        "night",
        {
            "project_root": base_dir if project_root is not None else None,
            "rules_path": rules_path,
            "io_path": io_path,
        },
    )
    rules = copy.deepcopy(effective.rules_cfg)
    io_cfg = effective.io_cfg
    io_path = effective.io_path
    rules_path = effective.rules_path
    base_dir = io_path.parent.parent

    out_dir = resolve_output_dir(io_cfg, io_path)
    out_dir.mkdir(parents=True, exist_ok=True)

    # 读取教师定位表与班级学科映射
    if "teacher_table" in io_cfg and "path" in io_cfg["teacher_table"]:
        tt_path = Path(io_cfg["teacher_table"]["path"])
        if not tt_path.is_absolute():
            io_cfg["teacher_table"]["path"] = str((base_dir / tt_path).resolve())
    classes, cst, ts_map, male_heads, female_heads = read_teacher_table(io_cfg, rules)
    checkin_cfg = rules.get("checkin", {}) or {}
    if checkin_cfg.get("enabled", False) and not checkin_candidate_pool_available(
        checkin_cfg,
        male_heads,
        female_heads,
    ):
        # 课程排课不依赖班主任/性别；没有满足需求的性别候选池时跳过查寝附加模块。
        rules["checkin"] = dict(checkin_cfg)
        rules["checkin"]["enabled"] = False
    days = rules["calendar"]["days"]
    periods = rules["calendar"]["periods"]

    # 创建 CP-SAT 模型与变量
    model = create_existing_cp_model("scheduler.night")
    vars = build_variables(model, classes, cst, days, periods)
    checkin_vars = build_checkin_variables(model, male_heads, female_heads, days)
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

    # 硬约束与软目标
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

    # 个性化约束
    pers_cfg_raw = merge_section(effective, "personalized_constraints")
    pers_cfg = PersonalizedConfig(
        enabled=pers_cfg_raw.get("enabled", True),
        teacher_targets=pers_cfg_raw.get("teacher_targets", pers_cfg_raw.get("targets", {})) or {},
        enable_xhd_night_no_pm3=pers_cfg_raw.get("enable_xhd_night_no_pm3", True),
        w_xhd_night_no_pm3=int(pers_cfg_raw.get("w_xhd_night_no_pm3", 150)),
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
        w_lm_sun_am12=int(pers_cfg_raw.get("w_lm_sun_am12", 400)),
        enable_ytt_sun_pref=pers_cfg_raw.get("enable_ytt_sun_pref", True),
        w_ytt_sun_am_pref=int(pers_cfg_raw.get("w_ytt_sun_am_pref", 60)),
        w_ytt_no_sun_night=int(pers_cfg_raw.get("w_ytt_no_sun_night", 80)),
        enable_dym_no_fri_sun_night=pers_cfg_raw.get("enable_dym_no_fri_sun_night", True),
        enable_pol_no_sun_night=pers_cfg_raw.get("enable_pol_no_sun_night", True),
        w_pol_sun_teacher_count=int(pers_cfg_raw.get("w_pol_sun_teacher_count", 300)),
        w_pol_sun_super=int(pers_cfg_raw.get("w_pol_sun_super", 600)),
        enable_ld_reduce_pm=pers_cfg_raw.get("enable_ld_reduce_pm", True),
        w_ld_reduce_pm=int(pers_cfg_raw.get("w_ld_reduce_pm", 80)),
        enable_ld_no_mon_pm=pers_cfg_raw.get("enable_ld_no_mon_pm", True),
        enable_zfj_ban_mon_fri_pm3=pers_cfg_raw.get("enable_zfj_ban_mon_fri_pm3", True),
        enable_jxq_prefs=pers_cfg_raw.get("enable_jxq_prefs", True),
        w_jxq_no_mon_am1=int(pers_cfg_raw.get("w_jxq_no_mon_am1", 80)),
        w_jxq_sun_pm_pref=int(pers_cfg_raw.get("w_jxq_sun_pm_pref", 60)),
        w_jxq_no_sun_night=int(pers_cfg_raw.get("w_jxq_no_sun_night", 150)),
        enable_csqi_prefs=pers_cfg_raw.get("enable_csqi_prefs", True),
        w_csqi_sun_am_pref=int(pers_cfg_raw.get("w_csqi_sun_am_pref", 60)),
        w_csqi_night_outside_pen=int(pers_cfg_raw.get("w_csqi_night_outside_pen", 120)),
        w_csqi_need_sun_or_mon=int(pers_cfg_raw.get("w_csqi_need_sun_or_mon", 80)),
        enable_zzx_prefs=pers_cfg_raw.get("enable_zzx_prefs", True),
        w_zzx_no_sun_night=int(pers_cfg_raw.get("w_zzx_no_sun_night", 220)),
        w_zzx_sun_am_pref=int(pers_cfg_raw.get("w_zzx_sun_am_pref", 70)),
        w_zzx_reduce_am4=int(pers_cfg_raw.get("w_zzx_reduce_am4", 60)),
        enable_zzx_no_sunday_night=pers_cfg_raw.get("enable_zzx_no_sunday_night", True),
        zzx_no_sunday_night_mode=str(pers_cfg_raw.get("zzx_no_sunday_night_mode", "hard")),
        w_zzx_no_sunday_night=int(pers_cfg_raw.get("w_zzx_no_sunday_night", 3000)),
        enable_xyx_night_days_only=pers_cfg_raw.get("enable_xyx_night_days_only", True),
        xyx_night_days_only_mode=str(pers_cfg_raw.get("xyx_night_days_only_mode", "hard")),
        xyx_night_allowed_days=[
            str(x).strip()
            for x in (
                pers_cfg_raw.get("xyx_night_allowed_days", ["星期五", "星期日"])
                if isinstance(pers_cfg_raw.get("xyx_night_allowed_days", ["星期五", "星期日"]), (list, tuple, set))
                else [pers_cfg_raw.get("xyx_night_allowed_days", ["星期五", "星期日"])]
            )
            if str(x).strip()
        ],
        w_xyx_night_days_only=int(pers_cfg_raw.get("w_xyx_night_days_only", 2000)),
        enable_hwj_prefs=pers_cfg_raw.get("enable_hwj_prefs", True),
        w_hwj_need_sun_mon=int(pers_cfg_raw.get("w_hwj_need_sun_mon", 220)),
        w_hwj_need_consecutive=int(pers_cfg_raw.get("w_hwj_need_consecutive", 120)),
        enable_hwj_night_sun_mon_assign=pers_cfg_raw.get("enable_hwj_night_sun_mon_assign", True),
        hwj_night_sun_mon_assign_mode=str(pers_cfg_raw.get("hwj_night_sun_mon_assign_mode", "hard")),
        w_hwj_night_sun_mon_assign=int(pers_cfg_raw.get("w_hwj_night_sun_mon_assign", 2000)),
        enable_hsm_no_fri_night=pers_cfg_raw.get("enable_hsm_no_fri_night", True),
        w_hsm_no_fri_night=int(pers_cfg_raw.get("w_hsm_no_fri_night", 80)),
        enable_zhoubo_hard=pers_cfg_raw.get("enable_zhoubo_hard", True),
        enable_zhoubo_liumeng_same_night=pers_cfg_raw.get("enable_zhoubo_liumeng_same_night", True),
        enable_zhoubo_weekday_am1_penalty=pers_cfg_raw.get("enable_zhoubo_weekday_am1_penalty", True),
        w_zhoubo_weekday_am1_penalty=int(pers_cfg_raw.get("w_zhoubo_weekday_am1_penalty", 300)),
        enable_liumeng_no_sunday=pers_cfg_raw.get("enable_liumeng_no_sunday", True),
        enable_xww_weekday_am4_pm1_stair=pers_cfg_raw.get("enable_xww_weekday_am4_pm1_stair", True),
        w_xww_weekday_am4_pm1_e2=int(pers_cfg_raw.get("w_xww_weekday_am4_pm1_e2", 80)),
        w_xww_weekday_am4_pm1_e3=int(pers_cfg_raw.get("w_xww_weekday_am4_pm1_e3", 160)),
        w_xww_weekday_am4_pm1_e4=int(pers_cfg_raw.get("w_xww_weekday_am4_pm1_e4", 320)),
        enable_zfy_no_consecutive_night=pers_cfg_raw.get("enable_zfy_no_consecutive_night", True),
        zfy_no_consecutive_night_mode=str(pers_cfg_raw.get("zfy_no_consecutive_night_mode", "soft")),
        w_zfy_no_consecutive_night=int(pers_cfg_raw.get("w_zfy_no_consecutive_night", 3000)),
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
        enable_custom_no_am1_teachers=pers_cfg_raw.get("enable_custom_no_am1_teachers", True),
        custom_no_am1_teachers=[
            str(x).strip()
            for x in (
                pers_cfg_raw.get("custom_no_am1_teachers", [])
                if isinstance(pers_cfg_raw.get("custom_no_am1_teachers", []), (list, tuple, set))
                else [pers_cfg_raw.get("custom_no_am1_teachers", [])]
            )
            if str(x).strip()
        ],
    )
    hard_notes, pers_penalties, pers_stats = apply_personalized_constraints(
        model, None, None, vars, ctx, None, pers_cfg, out_dir
    )

    objective_terms = []
    objective_terms.extend(penalties)
    objective_terms.extend(pers_penalties)
    if objective_terms:
        model.Minimize(sum(objective_terms))
    validate_registered_rule_meta(context="night")

    # 约束审计
    write_night_constraints_audit(base_dir, rules, ctx)

    # 求解器参数
    solve_cfg = rules.get("solve", {})
    solve_config = build_scheduler_cp_sat_solve_config(solve_cfg, default_time_limit_seconds=3000)

    # 快照导出配置
    snapshot_raw = (io_cfg.get("snapshot_export", {}) or {}) if io_cfg else {}
    snapshot_cfg = SnapshotExportConfig(
        enabled=bool(snapshot_raw.get("enabled", True)),
        interval_sec=int(snapshot_raw.get("interval_sec", 60)),
        root_dir=resolve_project_path(
            snapshot_raw.get("root_dir", "outputs/snapshots"),
            project_root=base_dir.parent,
            label="snapshot_export.root_dir",
            reject_scheduler_outputs=True,
        ),
        export_day=bool(snapshot_raw.get("export_day", False)),
        export_night=bool(snapshot_raw.get("export_night", True)),
        export_link_reports=bool(snapshot_raw.get("export_link_reports", False)),
        export_checklists=bool(snapshot_raw.get("export_checklists", True)),
    )
    archive_raw = (io_cfg.get("multi_solution_output", {}) or {}) if io_cfg else {}
    archive_cfg = SolutionArchiveConfig(
        enabled=bool(archive_raw.get("enabled", True)),
        root_dir=resolve_project_path(
            archive_raw.get("root_dir", "outputs/solutions"),
            project_root=base_dir.parent,
            label="multi_solution_output.root_dir",
            reject_scheduler_outputs=True,
        ),
        max_keep=int(archive_raw.get("max_keep", 50)),
        keep_last_runs=int(archive_raw.get("keep_last_runs", 20)),
        periodic_export_every=int(archive_raw.get("periodic_export_every", 0)),
    )
    stop_file_raw = (io_cfg.get("web_solve_control", {}) or {}).get("stop_file")
    stop_file = Path(str(stop_file_raw)).resolve() if stop_file_raw else None

    callback = None
    counting_callback = _CountingSolutionCallback()
    active_callback: cp_model.CpSolverSolutionCallback = counting_callback
    solve_start_dt = datetime.now()
    solve_start_ts = time.perf_counter()
    use_callback = snapshot_cfg.enabled or archive_cfg.enabled
    if use_callback:
        night_ctx = {"vars": vars, "ctx": ctx, "rules": rules, "out_dir": out_dir}
        callback = TimedSnapshotExportCallback(
            snapshot_cfg,
            archive_cfg=archive_cfg,
            effective_config=effective.effective_cfg,
            config_diff_text=effective.config_diff_text,
            night_ctx=night_ctx,
            stop_file=stop_file,
        )
        active_callback = callback
    logger.info("开始求解时间：%s", solve_start_dt.strftime("%Y-%m-%d %H:%M:%S"))
    solve_result = solve_existing_cp_model(model, solve_config, solution_callback=active_callback)
    solver = solve_result.solver
    status = solve_result.status

    solve_end_dt = datetime.now()
    solve_elapsed_sec = time.perf_counter() - solve_start_ts
    status_name = solver.StatusName(status)
    logger.info("求解状态：%s", status_name)
    feasible_count = 0
    try:
        feasible_count = int(active_callback.NumSolutions())
    except Exception:
        feasible_count = 1 if status in (cp_model.OPTIMAL, cp_model.FEASIBLE) else 0
    logger.info("求解完成时间：%s", solve_end_dt.strftime("%Y-%m-%d %H:%M:%S"))
    logger.info("求解总耗时：%.3f 秒", solve_elapsed_sec)
    logger.info("回调捕获解数量：%d", feasible_count)

    if status == cp_model.INFEASIBLE:
        append_infeasible_audit(base_dir, rules, ["晚自习硬约束冲突"])  # 兜底提示
        if hard_notes:
            write_personalized_infeasible_hints(out_dir, hard_notes)

    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        write_night_constraint_checklist(base_dir, rules, ctx, vars, solver, status_name)
        write_double_class_weekday_p1_p2_report(out_dir, solver, vars, ctx, rules)
        if pers_stats or hard_notes:
            write_personalized_checklist(out_dir, solver, pers_stats, hard_notes)
        # 最终解软约束明细（给综合诊断表使用）
        event_log_path = write_event_log_csv(
            out_dir,
            solver,
            solution_id="final",
            snapshot_id="最终解",
        )
        final_rows = summarize_event_log_csv(event_log_path)
        final_csv = out_dir / "final_soft_violation_summary.csv"
        with final_csv.open("w", encoding="utf-8-sig") as f:
            f.write("rule_id,rule_name,teacher,weight,count,penalty_sum\n")
            for r in final_rows:
                f.write(
                    f"{r.get('rule_id','')},{r.get('rule_name','')},{r.get('teacher','')},"
                    f"{r.get('weight',0)},{r.get('count',0)},{r.get('penalty_sum',0)}\n"
                )
        final_solver_meta = enrich_solver_overview({
            "solution_id": "final",
            "snapshot_id": "最终解",
            "solver_status": status_name,
            "objective_value": float(solver.ObjectiveValue() if penalties or pers_penalties else 0.0),
            "best_bound": float(solver.BestObjectiveBound()) if penalties or pers_penalties else None,
            "time_limit": float(solver.parameters.max_time_in_seconds) if hasattr(solver, "parameters") else None,
            "num_conflicts": int(solver.NumConflicts()),
            "num_branches": int(solver.NumBranches()),
            "wall_time": float(solver.WallTime()),
            "is_best_solution": True,
        })
        (out_dir / "final_solver_overview.json").write_text(
            json.dumps(final_solver_meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    # 导出结果
    out_path = rules.get("output", {}).get("result_xlsx", "outputs/结果_MVP.xlsx")
    out_path_p = resolve_project_path(
        out_path,
        project_root=base_dir.parent,
        label="rules.output.result_xlsx",
        reject_scheduler_outputs=True,
    )
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path_p = out_path_p.with_name(f"{out_path_p.stem}_{ts}{out_path_p.suffix}")
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        export_result_xlsx(
            str(out_path_p),
            solver,
            vars,
            ctx["classes"],
            ctx["cst"],
            ctx["days"],
            ctx["periods"],
            ctx["male_heads"],
            ctx["female_heads"],
        )
        logger.info("已导出：%s", str(out_path_p))

    archive_result = None
    if callback is not None:
        archive_result = callback.export_solution_archive(mode="night", root_best_copy=out_path_p)
        if archive_result:
            logger.info(
                "多解输出完成：run_dir=%s, top_count=%s, best=%s, diagnostics=%s",
                str(archive_result.get("run_dir", "")),
                int(archive_result.get("top_count", 0) or 0),
                str(archive_result.get("best_excel", "")),
                str(archive_result.get("diag_excel", "")),
            )

    move_diagnostics_to_folder(out_dir)
    if archive_result and archive_result.get("diag_excel"):
        diag_xlsx = Path(str(archive_result.get("diag_excel")))
    else:
        diag_xlsx = build_multi_solution_diagnostic(out_dir)
    objective_val = float(solver.ObjectiveValue()) if objective_terms else 0.0
    write_baseline_report(
        out_dir,
        mode="night",
        status=status_name,
        objective=objective_val if status in (cp_model.OPTIMAL, cp_model.FEASIBLE) else None,
        expected_files=[out_path_p, out_dir / "event_log.csv", diag_xlsx],
        extra={"days": days, "periods": periods},
    )
    move_root_meta_files(out_dir, folder_name="meta", include_txt=True, include_json=True, include_csv=True)


if __name__ == "__main__":
    run_night()

