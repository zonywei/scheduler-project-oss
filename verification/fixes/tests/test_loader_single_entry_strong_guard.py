from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import scheduler.config.loader as loader_mod  # noqa: E402
import scheduler.day_schedule_entry as day_entry  # noqa: E402
import scheduler.joint_solver as joint_entry  # noqa: E402
import scheduler.main as night_entry  # noqa: E402


class _StopAfterConfig(Exception):
    pass


def _assert_entry_calls_load_effective_config() -> None:
    io_path = (REPO_ROOT / "scheduler" / "config" / "io.yaml").resolve()
    rules_path = io_path.with_name("rules.yaml")
    calls = {"day": 0, "night": 0, "joint": 0}
    base_loader = loader_mod.load_effective_config

    def _wrap(tag: str):
        def _inner(*args, **kwargs):
            calls[tag] += 1
            return base_loader(*args, **kwargs)

        return _inner

    day_loader = _wrap("day")
    night_loader = _wrap("night")
    joint_loader = _wrap("joint")

    with patch.object(day_entry, "load_effective_config", new=day_loader):
        with patch.object(day_entry, "build_day_model", side_effect=_StopAfterConfig):
            try:
                day_entry.run_day(io_path=io_path, rules_path=rules_path)
            except _StopAfterConfig:
                pass

    with patch.object(night_entry, "load_effective_config", new=night_loader):
        with patch.object(night_entry, "read_teacher_table", side_effect=_StopAfterConfig):
            try:
                night_entry.run_night(io_path=io_path, rules_path=rules_path)
            except _StopAfterConfig:
                pass

    with patch.object(joint_entry, "load_effective_config", new=joint_loader):
        with patch.object(joint_entry, "build_day_model", side_effect=_StopAfterConfig):
            try:
                joint_entry.run_joint("高二", io_path=io_path, rules_path=rules_path)
            except _StopAfterConfig:
                pass

    assert calls["day"] >= 1, "day entry did not call load_effective_config"
    assert calls["night"] >= 1, "night entry did not call load_effective_config"
    assert calls["joint"] >= 1, "joint entry did not call load_effective_config"


def main() -> None:
    _assert_entry_calls_load_effective_config()
    print("test_loader_single_entry_strong_guard: PASS")

if __name__ == "__main__":
    raise SystemExit(main())
