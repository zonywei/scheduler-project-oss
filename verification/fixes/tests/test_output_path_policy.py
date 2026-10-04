from __future__ import annotations

import inspect
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scheduler.output_paths import (  # noqa: E402
    is_scheduler_outputs_path,
    project_output_dir,
    project_root_from_io_path,
    resolve_output_dir,
    resolve_project_path,
)
from scheduler.app.service import run, _select_best_solution_path, _select_diagnostics_summary_path  # noqa: E402
from scheduler.solver_callbacks.timed_snapshot_callback import (  # noqa: E402
    SnapshotExportConfig,
    SolutionArchiveConfig,
    TimedSnapshotExportCallback,
)


def test_output_dir_resolves_to_project_root_outputs() -> None:
    io_path = REPO_ROOT / "scheduler" / "config" / "io.yaml"
    out_dir = resolve_output_dir({"output": {"dir": "outputs"}}, io_path)

    assert project_root_from_io_path(io_path) == REPO_ROOT
    assert out_dir == REPO_ROOT / "outputs"
    assert project_output_dir() == REPO_ROOT / "outputs"


def test_output_policy_rejects_scheduler_package_outputs() -> None:
    io_path = REPO_ROOT / "scheduler" / "config" / "io.yaml"

    assert is_scheduler_outputs_path(REPO_ROOT / "scheduler" / "outputs")
    assert is_scheduler_outputs_path(REPO_ROOT / "scheduler" / "outputs" / "meta")

    with pytest.raises(ValueError, match="scheduler/outputs"):
        resolve_output_dir({"output": {"dir": "scheduler/outputs"}}, io_path)

    with pytest.raises(ValueError, match="scheduler/outputs"):
        resolve_project_path(
            "scheduler/outputs/snapshots",
            project_root=REPO_ROOT,
            label="snapshot_export.root_dir",
            reject_scheduler_outputs=True,
        )


def test_callback_defaults_use_project_root_outputs() -> None:
    assert SnapshotExportConfig().root_dir == REPO_ROOT / "outputs" / "snapshots"
    assert SolutionArchiveConfig().root_dir == REPO_ROOT / "outputs" / "solutions"
    assert SolutionArchiveConfig().periodic_export_every == 0


def test_legacy_run_result_selects_chinese_best_solution_filename(tmp_path: Path) -> None:
    outputs_dir = tmp_path / "outputs"
    run_dir = outputs_dir / "solutions" / "run_20260506_120000"
    best_dir = run_dir / "best"
    best_dir.mkdir(parents=True)
    plain = best_dir / "最终全局最优解.xlsx"
    formal = best_dir / "最终全局最优解_正式版.xlsx"
    plain.write_text("plain", encoding="utf-8")
    formal.write_text("formal", encoding="utf-8")

    assert _select_best_solution_path(run_dir, outputs_dir) == formal


def test_legacy_run_result_falls_back_to_day_schedule_filename(tmp_path: Path) -> None:
    outputs_dir = tmp_path / "outputs"
    outputs_dir.mkdir()
    schedule = outputs_dir / "课表及值班安排（汇总版）_20260506_120000.xlsx"
    schedule.write_text("schedule", encoding="utf-8")

    assert _select_best_solution_path(None, outputs_dir) == schedule


def test_legacy_run_result_selects_chinese_diagnostics_filename(tmp_path: Path) -> None:
    outputs_dir = tmp_path / "outputs"
    run_dir = outputs_dir / "solutions" / "run_20260506_120000"
    diag_dir = run_dir / "diagnostics"
    diag_dir.mkdir(parents=True)
    report = diag_dir / "多解诊断报告.xlsx"
    report.write_text("report", encoding="utf-8")

    assert _select_diagnostics_summary_path(run_dir, outputs_dir) == report


def test_legacy_backend_defaults_keep_readable_chinese_labels() -> None:
    assert inspect.signature(run).parameters["grade_prefix"].default == "高二"
    assert inspect.signature(TimedSnapshotExportCallback).parameters["grade_prefix"].default == "高二"

    joint_solver_source = (REPO_ROOT / "scheduler" / "joint_solver.py").read_text(encoding="utf-8")
    for readable in ("上午1", "上午2", "上午4", "下午1"):
        assert readable in joint_solver_source
    for mojibake in ("楂樹簩", "涓婂崍", "涓嬪崍"):
        assert mojibake not in joint_solver_source
