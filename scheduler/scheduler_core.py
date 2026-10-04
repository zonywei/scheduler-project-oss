from __future__ import annotations

from pathlib import Path

from scheduler import main as night_main
from scheduler.day_schedule_entry import run_day


class SchedulerCore:
    """Thin orchestration wrapper without changing solver behavior."""

    def __init__(self, io_path: Path, rules_path: Path, grade_prefix: str = "高二") -> None:
        self.io_path = io_path
        self.rules_path = rules_path
        self.grade_prefix = grade_prefix

    def run_day(self) -> None:
        run_day(grade_prefix=self.grade_prefix, io_path=self.io_path)

    def run_night(self) -> None:
        night_main.run_night(rules_path=self.rules_path, io_path=self.io_path)

    def run_joint(self) -> None:
        from scheduler.joint_solver import run_joint

        run_joint(grade_prefix=self.grade_prefix, io_path=self.io_path, rules_path=self.rules_path)

    def run_mode(self, mode: str) -> None:
        if mode in ("night", "both"):
            self.run_night()
        if mode in ("day", "both"):
            self.run_day()
        if mode == "joint":
            self.run_joint()
