# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

_DIAG_NAME_MAP = {
    "audit_before.txt": "白天_审计_前置.txt",
    "day_check_hard_constraints.txt": "白天_硬约束检查.txt",
    "day_constraint_checklist.txt": "白天_约束清单.txt",
    "day_diagnostic_morning_reading.txt": "白天_早自习诊断.txt",
    "day_diagnostic_weekend.txt": "白天_周末诊断.txt",
    "day_infeasible_hints.txt": "白天_不可行提示.txt",
    "day_low_weekday_subject_max1_report.txt": "白天_周中少课学科每日上限.txt",
    "day_pe_tech_audit.txt": "白天_体技审计.txt",
    "day_pe_tech_checklist.txt": "白天_体技约束检查.txt",
    "day_soft_timepref_audit.txt": "白天_软约束审计.txt",
    "day_soft_timepref_report.txt": "白天_软约束报告.txt",
    "day_teacher_am4_pm1_penalty_report.txt": "白天_AM4_PM1阈值报告.txt",
    "day_teacher_m1_cap_report.txt": "白天_教师上午1上限报告.txt",
    "day_teacher_m1_cap_infeasible_hint.txt": "白天_教师上午1上限不可行提示.txt",
    "day_core_teacher_day_load_sanity.txt": "白天_九学科教师日负载自检.txt",
    "day_core_teacher_day_load_infeasible_hint.txt": "白天_九学科教师日负载不可行提示.txt",
    "day_teacher_continuity_report.txt": "白天_教师连续性报告.txt",
    "day_two_class_daily_min_report.txt": "白天_双班每日最小课时报告.txt",
    "head_duty_audit_before.txt": "班主任值班_审计.txt",
    "head_duty_hard_check.txt": "班主任值班_硬约束检查.txt",
    "head_duty_soft_report.txt": "班主任值班_软约束报告.txt",
    "head_duty_vars_count.txt": "班主任值班_变量统计.txt",
    "head_duty_infeasible_hints.txt": "班主任值班_不可行提示.txt",
    "hint_apply_report.txt": "热启动_提示应用报告.txt",
    "joint_infeasible_hints.txt": "联合求解_不可行提示.txt",
    "link_bridge_audit.txt": "联动桥_审计.txt",
    "day_night_link_checklist.txt": "联动约束_检查.txt",
    "night_constraint_checklist.txt": "晚自习_约束检查.txt",
    "night_constraints_audit.txt": "晚自习_约束审计.txt",
    "personalized_audit_before.txt": "个性化_审计.txt",
    "personalized_checklist.txt": "个性化_检查.txt",
    "personalized_infeasible_hints.txt": "个性化_不可行提示.txt",
    "warm_start_audit_before.txt": "热启动_审计.txt",
    "warm_start_benchmark.txt": "热启动_对比.txt",
    "warm_start_save_report.txt": "热启动_保存报告.txt",
}


def move_diagnostics_to_folder(out_dir: Path, folder_name: str = "诊断") -> Path:
    """
    Move all .txt diagnostic files under out_dir into a subfolder, and
    rename with a Chinese prefix to make names clearly diagnostic.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    diag_dir = out_dir / folder_name
    diag_dir.mkdir(parents=True, exist_ok=True)

    for p in out_dir.glob("*.txt"):
        if p.name in ("best_snapshot_path.txt",):
            continue
        new_name = _DIAG_NAME_MAP.get(p.name, f"诊断_{p.name}")
        target = diag_dir / new_name
        if target.exists():
            stem = target.stem
            suffix = target.suffix
            i = 1
            while True:
                cand = diag_dir / f"{stem}_{i}{suffix}"
                if not cand.exists():
                    target = cand
                    break
                i += 1
        p.replace(target)
    return diag_dir

def move_root_meta_files(
    out_dir: Path,
    folder_name: str = "meta",
    *,
    include_txt: bool = True,
    include_json: bool = True,
    include_csv: bool = False,
    keep_names: tuple[str, ...] = (),
) -> Path:
    """
    Move root-level txt/json/csv files into a dedicated subfolder.
    Only files directly under out_dir are moved.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    meta_dir = out_dir / folder_name
    meta_dir.mkdir(parents=True, exist_ok=True)

    patterns: list[str] = []
    if include_txt:
        patterns.append("*.txt")
    if include_json:
        patterns.append("*.json")
    if include_csv:
        patterns.append("*.csv")

    keep = set(keep_names or ())
    for pattern in patterns:
        for p in out_dir.glob(pattern):
            if not p.is_file():
                continue
            if p.name in keep:
                continue
            target = meta_dir / p.name
            if target.exists():
                stem = target.stem
                suffix = target.suffix
                i = 1
                while True:
                    cand = meta_dir / f"{stem}_{i}{suffix}"
                    if not cand.exists():
                        target = cand
                        break
                    i += 1
            p.replace(target)
    return meta_dir
