# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ortools.sat.python import cp_model

from scheduler.data.evening_excel_reader import EveningAssign


class CountingSolutionCallback(cp_model.CpSolverSolutionCallback):
    """Lightweight callback for counting solutions seen during search."""

    def __init__(self) -> None:
        super().__init__()
        self.solution_count = 0

    def on_solution_callback(self) -> None:
        self.solution_count += 1


@dataclass
class DayBuildResult:
    data: Any
    dv: Any
    out_dir: Path
    summary_out: Path
    formal_out: Path
    objective_terms: list[Any]
    weekend_diag: Any
    weekend_cfg: Any
    weekday_cfg: Any
    pe_cfg: Any
    head_teachers: list
    pe_teachers: set
    pe_tech_teachers: set
    multi_details: Any
    am4pm1_details: Any
    continuity_details: Any
    core_load_details: dict
    m1_cap_details: dict
    m1_cap_structural_impossible: dict
    teacher_am1_details: Any
    lang_am_vars: list
    lang_pm_vars: list
    lang_fixed: tuple[int, int]
    stem_am1_vars: list
    stem_am1_fixed: int
    pe_am_penalties: list
    pe_gap_details: dict
    liu_allowed: set
    tao_allowed: set
    liu_viol_fixed: int
    tao_viol_fixed: int
    pe_illegal_fixed: int
    weekday_balance_penalties: list
    day_night_link_cfg: Any
    head_duty_cfg: Any
    duty_vars: dict
    teach_pm1_vars: dict
    excess_duty: dict
    excess_pm1: dict
    duty_floor_vars: dict
    duty_trigger_vars: dict
    head_floor_by_teacher: dict
    head_floor_groups: dict
    head_allowed_duty_floors: dict
    head_borrow_5_to_4: dict
    head_weekly_duty_count_45f: dict
    head_h4_base: list
    head_h5_base: list
    head_t9_teacher: str
    head_duty_days: list
    head_duty_hints: list
    noon_dorm_cfg: Any
    noon_male_vars: dict
    noon_female_vars: dict
    noon_day_penalty: dict
    noon_days: list
    noon_hints: list
    two_class_details: dict
    pers_cfg: Any


@dataclass
class NightBuildResult:
    vars: dict
    ctx: dict
    rules: dict
    out_dir: Path
    out_path: Path
    penalties: list[Any]


def build_evening_assignments_from_solver(
    solver: cp_model.CpSolver,
    night_vars: dict,
    night_ctx: dict,
) -> EveningAssign:
    assigns: EveningAssign = {}
    y = night_vars["y"]
    cst = night_ctx["cst"]
    days = night_ctx["days"]
    periods = night_ctx["periods"]
    classes = night_ctx["classes"]
    for cls in classes:
        for d in days:
            for p in periods:
                for (c, subj), tch in cst.items():
                    if c != cls:
                        continue
                    if solver.Value(y[(cls, subj, d, p)]) == 1:
                        assigns[(cls, d, 1 if p == periods[0] else 2)] = (subj, tch)
                        break
    return assigns
