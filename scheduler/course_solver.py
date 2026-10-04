"""Configurable course scheduling without the legacy school's optional rules."""
from __future__ import annotations

import json
import logging
from collections import defaultdict
from pathlib import Path

from ortools.sat.python import cp_model

from scheduler.config.loader import load_effective_config
from scheduler.data.course_problem_reader import load_course_inputs
from scheduler.model.constraints.rule_v2 import apply_rule_v2_constraints, _exception_mode, _matches_rule_context, _is_preferred_slot, _ordered_slots_by_day
from scheduler.model.day_variables import DayVars
from scheduler.output.day_exporter import export_day_schedule_df
from scheduler.output.excel_writer import create_excel_writer
from scheduler.output_paths import resolve_output_dir
from scheduler.solver_params import apply_solver_parameters
from scheduler.solver_quality import enrich_solver_overview
from scheduler.rules.mandatory import MANDATORY_RULE_IDS


def build_course_model(model, io_cfg, rules_cfg, *, grade_prefix=""):
    data = load_course_inputs(io_cfg.get("web_tables") or {})
    x = {}
    by_slot = defaultdict(list)
    by_subject = defaultdict(list)
    by_teacher = defaultdict(list)
    fixed_teacher = defaultdict(int)
    fixed_subject = defaultdict(int)
    for (cls, slot), subject in data.fixed_assign.items():
        teacher = data.cls_subj_teacher.get((cls, subject))
        if slot in data.subject_ban_slots.get(subject, set()):
            raise ValueError(f"固定安排与学科禁排冲突：{cls}/{subject}/{slot}")
        if teacher:
            fixed_teacher[(teacher, slot)] += 1
            fixed_subject[(cls, subject)] += 1
    for cls in data.classes:
        for slot in data.available_slots:
            if (cls, slot) in data.fixed_assign:
                continue
            for (c, subject), teacher in data.cls_subj_teacher.items():
                if c != cls or slot in data.subject_ban_slots.get(subject, set()):
                    continue
                var = model.NewBoolVar(f"course[{cls},{subject},{slot}]")
                x[(cls, subject, slot)] = var
                by_slot[(cls, slot)].append(var)
                by_subject[(cls, subject)].append(var)
                by_teacher[(teacher, slot)].append(var)
            model.Add(sum(by_slot[(cls, slot)]) <= 1)
    for pair, (_, required, _) in data.req_hours.items():
        model.Add(sum(by_subject[pair]) + fixed_subject[pair] == required)
    for key in set(by_teacher) | set(fixed_teacher):
        model.Add(sum(by_teacher[key]) + fixed_teacher[key] <= 1)
    dv = DayVars(x, dict(by_slot), dict(by_subject))
    active = [r for r in (rules_cfg.get("rule_v2") or {}).get("rules", []) if r.get("enabled", True) and r.get("status") == "active"]
    for rule in active:
        if rule.get("constraint", {}).get("type") == "catalog_ref":
            catalog_id = rule["constraint"].get("catalog_id")
            if catalog_id not in MANDATORY_RULE_IDS or str(catalog_id).startswith("system.roster"):
                raise ValueError(f"课程排课未实现该目录规则：{catalog_id}")
    compiled = apply_rule_v2_constraints(model, data, dv, rules_cfg, grade_prefix=grade_prefix, respect_slot_order=True)
    missing = {r["id"] for r in active} - set(compiled.applied_rule_ids)
    fixed_costs = defaultdict(int)
    for rule in active:
        if rule.get("constraint", {}).get("type") not in {"teacher_unavailable", "prefer_period"}:
            continue
        # Fixed lessons cannot silently escape a user's hard unavailability.
        for (cls, slot), subject in data.fixed_assign.items():
            teacher = data.cls_subj_teacher.get((cls, subject), "")
            if not _matches_rule_context(rule, cls, subject, teacher, slot, grade_prefix):
                continue
            if rule["constraint"]["type"] == "prefer_period" and _is_preferred_slot(slot, rule["constraint"]["params"]["period"], _ordered_slots_by_day(data.available_slots, respect_slot_order=True)[slot.day], include_all_blocks=True):
                continue
            exception = _exception_mode(rule, cls, subject, teacher, slot, grade_prefix)
            if exception == "exclude":
                continue
            if rule.get("strength") == "hard" and exception != "soften":
                raise ValueError(f"固定安排与规则冲突：{rule['id']}/{cls}/{slot}")
            fixed_costs[rule["id"]] += int(rule.get("weight") or 300)
            for diagnostic in compiled.diagnostics:
                if diagnostic["rule_id"] == rule["id"]:
                    diagnostic["constraint_units"] = int(diagnostic.get("constraint_units") or 0) + 1
    for diagnostic in compiled.diagnostics:
        if diagnostic.get("constraint_units") or diagnostic.get("status") != "applied":
            continue
        rule = next(r for r in active if r["id"] == diagnostic["rule_id"])
        if rule["constraint"]["type"] != "prefer_period":
            continue
        matching = [(cls, subject, slot) for cls, subject, slot in dv.x if _matches_rule_context(rule, cls, subject, data.cls_subj_teacher[(cls, subject)], slot, grade_prefix)]
        if matching:
            diagnostic.update(status="delegated", constraint_units=len(matching), message="所有匹配的候选课位均满足时段偏好，无需额外限制")
    if missing or any(d.get("status") == "applied" and not d.get("constraint_units") for d in compiled.diagnostics):
        raise ValueError(f"启用规则没有匹配到排课对象或未编译：{sorted(missing)}")
    for diagnostic in compiled.diagnostics:
        diagnostic["fixed_penalty"] = fixed_costs[diagnostic["rule_id"]]
    compiled.objective_terms.extend(fixed_costs.values())
    if compiled.objective_terms:
        model.Minimize(sum(compiled.objective_terms))
    return data, dv, compiled


def run_course(io_path: Path, rules_path: Path, *, grade_prefix=""):
    effective = load_effective_config("course", {"io_path": io_path, "rules_path": rules_path})
    model = cp_model.CpModel()
    data, dv, compiled = build_course_model(model, effective.io_cfg, effective.rules_cfg, grade_prefix=grade_prefix)
    solver = cp_model.CpSolver()
    apply_solver_parameters(solver, effective.io_cfg.get("joint_solve") or {}, default_time_limit_seconds=300)
    status = solver.Solve(model)
    status_name = solver.StatusName(status)
    logging.info("status = %s", status_name)
    out = resolve_output_dir(effective.io_cfg, io_path)
    out.mkdir(parents=True, exist_ok=True)
    feasible = status in {cp_model.FEASIBLE, cp_model.OPTIMAL}
    overview = enrich_solver_overview({"solver_status": status_name, "solution_count": int(feasible), "objective_value": solver.ObjectiveValue() if feasible else None, "best_bound": solver.BestObjectiveBound() if feasible else None, "wall_time_seconds": solver.WallTime(), "mode": "course"})
    (out / "final_solver_overview.json").write_text(json.dumps(overview, ensure_ascii=False, indent=2), encoding="utf-8")
    explanation = {"schema_version": "scheduler.course_explanation.v1", "solver_status": status_name, "rules": compiled.diagnostics, "scope": "按用户时间格及周期课时排课，不预设早晚或周中周末配额", "objective_value": overview["objective_value"]}
    offset = 0
    for diagnostic in compiled.diagnostics:
        size = int(diagnostic.get("objective_terms_added") or 0)
        diagnostic["penalty_value"] = (sum(solver.Value(term) for term in compiled.objective_terms[offset:offset + size]) + diagnostic["fixed_penalty"]) if feasible else None
        offset += size
    (out / "course_explanation.json").write_text(json.dumps(explanation, ensure_ascii=False, indent=2), encoding="utf-8")
    if not feasible:
        return
    wide = export_day_schedule_df(data, dv, solver)
    days = list(dict.fromkeys(slot.day for slot in data.available_slots))
    columns = [f"{day}_{slot.block}{slot.period}" for day in days for slot in data.available_slots if slot.day == day]
    wide = wide.reindex(columns=columns)
    wide.index.name = "班级"
    path = out / "课程课表.xlsx"
    with create_excel_writer(path) as writer:
        wide.to_excel(writer, sheet_name="课程课表_宽表")
    logging.info("课程课表已导出：%s", path)
