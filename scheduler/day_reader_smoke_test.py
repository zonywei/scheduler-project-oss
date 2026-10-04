# -*- coding: utf-8 -*-
"""Compatibility entry for the renamed daytime scheduling runner.

The production daytime entry now lives in :mod:`scheduler.day_schedule_entry`.
This module remains importable for older scripts and tests that still refer to
``scheduler.day_reader_smoke_test``.
"""
from __future__ import annotations

from scheduler.day_schedule_entry import run_day

__all__ = ["run_day"]


if __name__ == "__main__":
    run_day()
