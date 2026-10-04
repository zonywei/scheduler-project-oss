from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


from scheduler.solver_callbacks import timed_snapshot_callback as snapshot_cb  # noqa: E402
from scheduler.solver_callbacks.timed_snapshot_callback import (  # noqa: E402
    SnapshotExportConfig,
    SolutionArchiveConfig,
    TimedSnapshotExportCallback,
)


class _FakeVar:
    def __init__(self, index: int) -> None:
        self._index = index

    def Index(self) -> int:
        return self._index


class _FakeAccessor:
    def __init__(self, values: dict[int, float]) -> None:
        self._values = values

    def Value(self, var: _FakeVar) -> float:
        return self._values.get(var.Index(), 0.0)


def _stub_event_log(out_dir: Path, _solver: object, *, solution_id: str, snapshot_id: str) -> Path:
    path = Path(out_dir) / "event_log.csv"
    path.write_text(
        "solution_id,snapshot_id,rule_id,rule_name,teacher,weight,count,penalty_sum\n"
        f"{solution_id},{snapshot_id},demo,示例,GLOBAL,1,0,0\n",
        encoding="utf-8-sig",
    )
    return path


def _callback(tmp_path: Path) -> TimedSnapshotExportCallback:
    return TimedSnapshotExportCallback(
        SnapshotExportConfig(enabled=False, root_dir=tmp_path / "snapshots"),
        archive_cfg=SolutionArchiveConfig(
            enabled=True,
            root_dir=tmp_path / "solutions",
            max_keep=3,
            keep_last_runs=20,
        ),
        day_ctx={"dv": SimpleNamespace(x={"a": _FakeVar(1)})},
    )


def test_archive_keeps_lower_objective_with_same_solution_hash(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(snapshot_cb, "write_event_log_csv", _stub_event_log)
    monkeypatch.setattr(snapshot_cb, "summarize_event_log_csv", lambda _path: [])
    cb = _callback(tmp_path)
    accessor = _FakeAccessor({1: 1.0})

    assert cb._capture_archive_solution(accessor, objective_value=110.0, best_bound=50.0)
    assert cb._capture_archive_solution(accessor, objective_value=100.0, best_bound=60.0)
    assert not cb._capture_archive_solution(accessor, objective_value=100.0, best_bound=70.0)

    objectives = sorted(float(entry["objective_value"]) for entry in cb._archive_entries)
    assert objectives == [100.0, 110.0]
    assert cb._archive_best_objective == 100.0
    assert cb._archive_stats["captured"] == 2
    assert cb._archive_stats["non_improving_skipped"] == 1


def test_archive_diagnostic_uses_final_solver_overview_bound(monkeypatch, tmp_path: Path) -> None:
    def fake_build_multi_solution_diagnostic(diag_root: Path) -> Path:
        out = Path(diag_root) / "diagnostic.xlsx"
        out.write_text("diagnostic", encoding="utf-8")
        return out

    monkeypatch.setattr(snapshot_cb, "build_multi_solution_diagnostic", fake_build_multi_solution_diagnostic)
    cb = _callback(tmp_path)
    event_log = tmp_path / "event_log.csv"
    event_log.write_text("solution_id,snapshot_id\n", encoding="utf-8-sig")
    cb._final_solver_overview = {
        "solution_id": "final_20260512",
        "snapshot_id": "最终解",
        "solver_status": "FEASIBLE",
        "objective_value": 100.0,
        "best_bound": 80.0,
        "objective_gap": 20.0,
        "gap_percent": 20.0,
        "wall_time": 2400.0,
        "is_best_solution": True,
    }
    best_entry = {
        "seq_id": 1,
        "objective_value": 120.0,
        "best_bound": 50.0,
        "time_limit": 300.0,
        "conflicts": 1,
        "branches": 2,
        "elapsed_sec": 10.0,
        "solution_count": 1,
        "event_log_file": str(event_log),
    }

    cb._build_archive_diagnostic([best_entry], best_entry)

    overview_path = cb._archive_meta_dir / "diag_cache" / "final_solver_overview.json"
    overview = json.loads(overview_path.read_text(encoding="utf-8"))
    assert overview["objective_value"] == 100.0
    assert overview["best_bound"] == 80.0
    assert overview["objective_gap"] == 20.0


def test_archive_diagnostic_recreates_missing_diagnostics_dir(monkeypatch, tmp_path: Path) -> None:
    def fake_build_multi_solution_diagnostic(diag_root: Path) -> Path:
        out = Path(diag_root) / "diagnostic.xlsx"
        out.write_text("diagnostic", encoding="utf-8")
        return out

    monkeypatch.setattr(snapshot_cb, "build_multi_solution_diagnostic", fake_build_multi_solution_diagnostic)
    cb = _callback(tmp_path)
    event_log = tmp_path / "event_log.csv"
    event_log.write_text("solution_id,snapshot_id\n", encoding="utf-8-sig")
    best_entry = {
        "seq_id": 1,
        "objective_value": 120.0,
        "best_bound": 50.0,
        "time_limit": 300.0,
        "conflicts": 1,
        "branches": 2,
        "elapsed_sec": 10.0,
        "solution_count": 1,
        "event_log_file": str(event_log),
    }

    for child in cb._archive_diag_dir.glob("*"):
        child.unlink()
    cb._archive_diag_dir.rmdir()

    diag_alias = cb._build_archive_diagnostic([best_entry], best_entry)

    assert diag_alias.exists()
    assert diag_alias.parent == cb._archive_diag_dir
