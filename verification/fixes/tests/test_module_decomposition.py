from __future__ import annotations

from pathlib import Path

from scheduler.diagnostics.display_catalog import (
    DORM_RULE_NAME_FALLBACK,
    PERSONALIZED_RULE_DESC_CN,
    PERSONALIZED_RULE_NAME_CN,
    RULE_NAME_FALLBACK_CN,
)
from scheduler.snapshot_diagnostics import _friendly_personalized_name


REPO_ROOT = Path(__file__).resolve().parents[3]


def _line_count(path: Path) -> int:
    return sum(1 for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip())


def test_snapshot_diagnostics_first_split_keeps_file_under_2000_nonblank_lines() -> None:
    assert _line_count(REPO_ROOT / "scheduler" / "snapshot_diagnostics.py") < 2000


def test_joint_solver_runtime_split_keeps_file_under_2000_nonblank_lines() -> None:
    assert _line_count(REPO_ROOT / "scheduler" / "joint_solver.py") < 2000


def test_day_weekday_constraint_reports_split_keeps_file_under_1800_nonblank_lines() -> None:
    assert _line_count(REPO_ROOT / "scheduler" / "model" / "constraints" / "day_weekday_constraints.py") < 1800


def test_diagnostic_display_catalog_is_separate_and_populated() -> None:
    catalog_path = REPO_ROOT / "scheduler" / "diagnostics" / "display_catalog.py"
    assert catalog_path.exists()
    assert len(PERSONALIZED_RULE_NAME_CN) >= 40
    assert len(RULE_NAME_FALLBACK_CN) >= 10
    assert len(DORM_RULE_NAME_FALLBACK) >= 8
    missing_desc = sorted(set(PERSONALIZED_RULE_NAME_CN) - set(PERSONALIZED_RULE_DESC_CN))
    assert not missing_desc, f"personalized display names need descriptions: {missing_desc}"


def test_snapshot_diagnostics_still_uses_catalog_names() -> None:
    assert _friendly_personalized_name("rule1", "fallback") == PERSONALIZED_RULE_NAME_CN["rule1"]


def test_joint_runtime_module_is_separate_and_importable() -> None:
    runtime_path = REPO_ROOT / "scheduler" / "joint_runtime.py"
    assert runtime_path.exists()
    assert _line_count(runtime_path) < 200

    from scheduler.joint_runtime import CountingSolutionCallback, DayBuildResult, NightBuildResult

    assert CountingSolutionCallback.__name__ == "CountingSolutionCallback"
    assert DayBuildResult.__name__ == "DayBuildResult"
    assert NightBuildResult.__name__ == "NightBuildResult"


def test_joint_pipeline_module_splits_flow_layers() -> None:
    pipeline_path = REPO_ROOT / "scheduler" / "joint_pipeline.py"
    assert pipeline_path.exists()

    import scheduler.joint_pipeline as joint_pipeline

    for name in (
        "build_joint_artifact_config",
        "apply_joint_cross_model_constraints",
        "solve_joint_model",
        "write_joint_diagnostics",
        "export_joint_solution_outputs",
        "finalize_joint_outputs",
    ):
        assert hasattr(joint_pipeline, name), f"missing joint pipeline layer: {name}"


def test_day_schedule_entry_replaces_smoke_test_name_with_compatibility_import() -> None:
    import scheduler.day_reader_smoke_test as legacy
    import scheduler.day_schedule_entry as day_entry

    assert (REPO_ROOT / "scheduler" / "day_schedule_entry.py").exists()
    assert legacy.run_day is day_entry.run_day
    wrapper = (REPO_ROOT / "scheduler" / "day_reader_smoke_test.py").read_text(encoding="utf-8")
    assert "Compatibility entry" in wrapper
    assert "scheduler.day_schedule_entry" in wrapper


def test_personalized_constraints_use_registered_rule_modules() -> None:
    from scheduler.model.constraints import personalized_constraints
    from scheduler.model.constraints.personalized_rules import PERSONALIZED_RULE_MODULES

    assert len(PERSONALIZED_RULE_MODULES) >= 3
    assert all(hasattr(module, "apply") for module in PERSONALIZED_RULE_MODULES)
    source = (REPO_ROOT / "scheduler" / "model" / "constraints" / "personalized_constraints.py").read_text(encoding="utf-8")
    assert "for rule_module in PERSONALIZED_RULE_MODULES" in source
    assert personalized_constraints.apply_personalized_constraints.__name__ == "apply_personalized_constraints"


def test_day_weekday_reports_module_is_separate_and_legacy_importable() -> None:
    reports_path = REPO_ROOT / "scheduler" / "model" / "constraints" / "day_weekday_reports.py"
    assert reports_path.exists()
    assert _line_count(reports_path) < 350

    from scheduler.model.constraints import day_weekday_constraints as legacy
    from scheduler.model.constraints import day_weekday_reports as reports

    assert reports.write_day_soft_timepref_report is legacy.write_day_soft_timepref_report
    assert reports.write_day_infeasible_hints is legacy.write_day_infeasible_hints
    assert reports.write_core_teacher_day_load_sanity is legacy.write_core_teacher_day_load_sanity
