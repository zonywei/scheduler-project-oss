# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import time
import csv
import shutil
import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, List

from ortools.sat.python import cp_model
import logging
import yaml

from scheduler.output.day_exporter_combo import save_day_class_and_teacher_summary_excel
from scheduler.output.day_exporter import export_day_schedule_df, export_day_schedule_grid_df, save_day_schedule_excel
from scheduler.output.night_exporter import export_result_xlsx
from scheduler.model.constraints.day_weekday_constraints import (
    write_day_check_hard_constraints,
    write_day_constraint_checklist,
    write_teacher_continuity_report,
    write_teacher_am4_pm1_penalty_report,
    write_day_soft_timepref_report,
    write_two_class_daily_min_report,
    write_core_teacher_day_load_sanity,
    write_teacher_m1_cap_report,
)
from scheduler.model.constraints.day_pe_tech_constraints import write_pe_tech_checklist
from scheduler.model.constraints.day_head_teacher_duty_constraints import extract_duty_results, write_head_duty_hard_check, write_head_duty_soft_report
from scheduler.model.constraints.day_noon_dorm_duty_constraints import write_noon_dorm_checklist, extract_noon_dorm_rows
from scheduler.model.constraints.grade_group_duty_constraints import (
    extract_grade_group_available_map,
    extract_grade_group_duty_map,
    write_grade_group_duty_checklist,
)
from scheduler.model.constraints.personalized_constraints import write_personalized_checklist
from scheduler.model.constraints.night_special import write_night_constraint_checklist
from scheduler.model.constraints.night_single_class_period_split import write_double_class_weekday_p1_p2_report
from scheduler.model.constraints.day_night_bridge import write_link_checklist
from scheduler.diagnostics.penalty_registry import summarize_event_log_csv, write_event_log_csv
from scheduler.output.value_maps import build_checkin_rows_from_solver
from scheduler.output_paths import project_output_dir
from scheduler.solver_quality import enrich_solver_overview
from scheduler.snapshot_diagnostics import build_multi_solution_diagnostic

logger = logging.getLogger(__name__)

DAY_SUMMARY_XLSX = "\u767d\u5929\u8bfe\u8868_\u6c47\u603b\u7248.xlsx"
DAY_FORMAL_XLSX = "\u767d\u5929\u8bfe\u8868_\u6b63\u5f0f\u7248.xlsx"
NIGHT_SCHEDULE_XLSX = "\u665a\u81ea\u4e60\u8bfe\u8868.xlsx"
MULTI_DIAGNOSTIC_XLSX = "\u591a\u89e3\u8bca\u65ad\u62a5\u544a.xlsx"
TOP_DAY_PREFIX = "\u767d\u5929\u8bfe\u8868_\u6c47\u603b\u7248"
TOP_NIGHT_PREFIX = "\u665a\u81ea\u4e60\u8bfe\u8868"
BEST_SOLUTION_XLSX = "\u6700\u7ec8\u5168\u5c40\u6700\u4f18\u89e3.xlsx"
BEST_SOLUTION_META_JSON = "\u6700\u7ec8\u5168\u5c40\u6700\u4f18\u89e3_meta.json"
BEST_SOLUTION_FORMAL_XLSX = "\u6700\u7ec8\u5168\u5c40\u6700\u4f18\u89e3_\u6b63\u5f0f\u7248.xlsx"


@dataclass
class SnapshotExportConfig:
    enabled: bool = True
    interval_sec: int = 60
    root_dir: Path = field(default_factory=lambda: project_output_dir() / "snapshots")
    export_day: bool = True
    export_night: bool = True
    export_link_reports: bool = True
    export_checklists: bool = True


@dataclass
class SolutionArchiveConfig:
    enabled: bool = True
    root_dir: Path = field(default_factory=lambda: project_output_dir() / "solutions")
    max_keep: int = 50
    keep_last_runs: int = 20
    periodic_export_every: int = 0


class FrozenSolutionAccessor:
    def __init__(self, values_by_index: Dict[int, float]) -> None:
        self._values_by_index = values_by_index

    def Value(self, var: Any) -> int | float:
        try:
            key = int(var.Index())
        except Exception:
            return 0
        return self._values_by_index.get(key, 0)


class TimedSnapshotExportCallback(cp_model.CpSolverSolutionCallback):
    def __init__(
        self,
        cfg: SnapshotExportConfig,
        *,
        archive_cfg: Optional[SolutionArchiveConfig] = None,
        effective_config: Optional[dict] = None,
        config_diff_text: str = "",
        day_ctx: Optional[dict] = None,
        night_ctx: Optional[dict] = None,
        bridge: Optional[dict] = None,
        link_stats: Optional[dict] = None,
        grade_prefix: str = "高二",
        stop_file: Optional[Path] = None,
    ) -> None:
        super().__init__()
        self._cfg = cfg
        self._day_ctx = day_ctx or {}
        self._night_ctx = night_ctx or {}
        self._bridge = bridge or {}
        self._link_stats = link_stats or {}
        self._grade_prefix = grade_prefix
        self._last_export_ts = 0.0
        self._start_ts = time.monotonic()
        self._in_export = False
        self._archive_cfg = archive_cfg or SolutionArchiveConfig(enabled=False)
        self._archive_effective_config = effective_config or {}
        self._archive_config_diff_text = str(config_diff_text or "")
        self._archive_run_dir: Optional[Path] = None
        self._archive_top_dir: Optional[Path] = None
        self._archive_best_dir: Optional[Path] = None
        self._archive_diag_dir: Optional[Path] = None
        self._archive_meta_dir: Optional[Path] = None
        self._archive_cache_dir: Optional[Path] = None
        self._archive_entries: List[dict] = []
        self._archive_hashes: set[str] = set()
        self._archive_seq = 0
        self._archive_best_objective: Optional[float] = None
        self._final_solver_overview: Optional[dict] = None
        self._archive_stats = {
            "captured": 0,
            "dedup_skipped": 0,
            "non_improving_skipped": 0,
            "evicted": 0,
            "periodic_exports": 0,
        }
        self._stop_file = Path(stop_file).resolve() if stop_file else None
        if self._archive_cfg.enabled:
            self._init_archive_dirs()

    @staticmethod
    def _safe_metric(source: Any, name: str, default: float | int | None = None):
        fn = getattr(source, name, None)
        if fn is None:
            return default
        try:
            return fn()
        except Exception:
            return default

    def _current_time_limit_seconds(self) -> Optional[float]:
        cfg = self._archive_effective_config or {}
        try:
            if self._archive_mode() == "joint":
                v = ((cfg.get("joint_solve", {}) or {}).get("time_limit_seconds", None))
                return float(v) if v is not None else None
            if self._archive_mode() == "night":
                v = ((cfg.get("solve", {}) or {}).get("time_limit_seconds", None))
                return float(v) if v is not None else None
            return None
        except Exception:
            return None

    @staticmethod
    def _unique_path(path: Path) -> Path:
        if not path.exists():
            return path
        stem = path.stem
        suffix = path.suffix
        parent = path.parent
        idx = 1
        while True:
            candidate = parent / f"{stem}_{idx:02d}{suffix}"
            if not candidate.exists():
                return candidate
            idx += 1

    def _archive_mode(self) -> str:
        if self._day_ctx and self._night_ctx:
            return "joint"
        return "night"

    def _export_periodic_best_excel(self) -> None:
        if not self._archive_top_dir:
            return
        if not self._archive_entries:
            return
        mode = self._archive_mode()
        best_entry = min(self._archive_entries, key=lambda e: (float(e["objective_value"]), int(e["seq_id"])))
        captured = int(self._archive_stats.get("captured", 0))
        export_ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        if mode == "joint":
            file_name = (
                f"{TOP_DAY_PREFIX}_pool{captured:04d}_best_seq{int(best_entry['seq_id']):04d}_{export_ts}.xlsx"
            )
            out_path = self._unique_path(self._archive_top_dir / file_name)
            self._export_joint_entry_excel(best_entry, out_path)
        else:
            file_name = (
                f"{TOP_NIGHT_PREFIX}_pool{captured:04d}_best_seq{int(best_entry['seq_id']):04d}_{export_ts}.xlsx"
            )
            out_path = self._unique_path(self._archive_top_dir / file_name)
            self._export_night_entry_excel(best_entry, out_path)
        self._archive_stats["periodic_exports"] = int(self._archive_stats.get("periodic_exports", 0)) + 1

    def _init_archive_dirs(self) -> None:
        root_dir = self._archive_cfg.root_dir.resolve()
        root_dir.mkdir(parents=True, exist_ok=True)
        run_name = f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        run_dir = root_dir / run_name
        suffix = 1
        while run_dir.exists():
            run_dir = root_dir / f"{run_name}_{suffix:02d}"
            suffix += 1

        top_dir = run_dir / "top50_excels"
        best_dir = run_dir / "best"
        diag_dir = run_dir / "diagnostics"
        meta_dir = run_dir / "_run_meta"
        cache_dir = run_dir / "pool_cache"
        for p in (top_dir, best_dir, diag_dir, meta_dir, cache_dir):
            p.mkdir(parents=True, exist_ok=True)

        self._archive_run_dir = run_dir
        self._archive_top_dir = top_dir
        self._archive_best_dir = best_dir
        self._archive_diag_dir = diag_dir
        self._archive_meta_dir = meta_dir
        self._archive_cache_dir = cache_dir

        self._write_effective_config_yaml()
        self._write_archive_index()
        self._prune_old_runs()

    def _write_effective_config_yaml(self) -> None:
        if not self._archive_meta_dir:
            return
        payload = self._archive_effective_config or {}
        out_path = self._archive_meta_dir / "effective_config.yaml"
        out_path.write_text(
            yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
        diff_path = self._archive_meta_dir / "config_diff.txt"
        diff_text = self._archive_config_diff_text.strip() or "NO_DIFF"
        diff_path.write_text(diff_text, encoding="utf-8")

    def _prune_old_runs(self) -> None:
        keep_last_runs = int(self._archive_cfg.keep_last_runs or 0)
        if keep_last_runs <= 0:
            return
        root_dir = self._archive_cfg.root_dir.resolve()
        if not root_dir.exists():
            return
        all_runs = sorted([p for p in root_dir.iterdir() if p.is_dir() and p.name.startswith("run_")], key=lambda p: p.name)
        if len(all_runs) <= keep_last_runs:
            return
        removable = all_runs[: len(all_runs) - keep_last_runs]
        for old_run in removable:
            if self._archive_run_dir is not None and old_run.resolve() == self._archive_run_dir.resolve():
                continue
            try:
                shutil.rmtree(old_run)
            except Exception:
                logger.warning("failed to remove old run dir: %s", old_run, exc_info=True)

    def _write_archive_index(self) -> None:
        if not self._archive_cache_dir:
            return
        index_path = self._archive_cache_dir / "index.json"
        payload = {
            "max_keep": int(self._archive_cfg.max_keep),
            "entries": [
                {
                    "seq_id": int(e["seq_id"]),
                    "objective_value": float(e["objective_value"]),
                    "created_at": str(e["created_at"]),
                    "solution_hash": str(e["solution_hash"]),
                    "solution_file": str(e["solution_file"]),
                    "meta_file": str(e["meta_file"]),
                    "event_log_file": str(e.get("event_log_file", "")),
                }
                for e in sorted(self._archive_entries, key=lambda x: (float(x["objective_value"]), int(x["seq_id"])))
            ],
        }
        index_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _iter_solution_vars(self) -> List[Any]:
        vars_list: List[Any] = []
        day_ctx = self._day_ctx or {}
        night_ctx = self._night_ctx or {}

        dv = day_ctx.get("dv")
        if dv is not None and hasattr(dv, "x"):
            vars_list.extend(list(dv.x.values()))

        for key in ("duty_vars", "duty_floor_vars", "noon_male_vars", "noon_female_vars", "grade_group_duty_vars"):
            mapping = day_ctx.get(key, {}) or {}
            vars_list.extend(list(mapping.values()))

        night_vars = night_ctx.get("vars", {}) or {}
        for key in ("y", "checkin_m", "checkin_f", "on_teacher_day"):
            mapping = night_vars.get(key, {}) or {}
            vars_list.extend(list(mapping.values()))

        return vars_list

    def _collect_sparse_values(self, accessor: Any | None = None) -> Dict[int, float]:
        sparse: Dict[int, float] = {}
        seen_var_index: set[int] = set()
        source = accessor or self
        for var in self._iter_solution_vars():
            try:
                idx = int(var.Index())
            except Exception:
                continue
            if idx in seen_var_index:
                continue
            seen_var_index.add(idx)
            try:
                value = float(source.Value(var))
            except Exception:
                continue
            if abs(value) <= 1e-9:
                continue
            sparse[idx] = value
        return sparse

    @staticmethod
    def _stable_hash(values_by_index: Dict[int, float]) -> str:
        items = [f"{idx}:{values_by_index[idx]}" for idx in sorted(values_by_index.keys())]
        return hashlib.sha256("|".join(items).encode("utf-8")).hexdigest()

    def _capture_improvement_solution(self) -> None:
        if not self._archive_cfg.enabled:
            return
        if not self._archive_cache_dir:
            return
        try:
            objective_value = float(self.ObjectiveValue())
        except Exception:
            objective_value = 0.0

        self._capture_archive_solution(self, objective_value=objective_value)

    def _capture_archive_solution(
        self,
        accessor: Any,
        *,
        objective_value: float,
        solver_status: str = "FEASIBLE",
        best_bound: Any = None,
        time_limit: Any = None,
        num_conflicts: Any = None,
        num_branches: Any = None,
        elapsed_sec: Any = None,
        wall_time: Any = None,
        solution_count: Any = None,
    ) -> bool:
        if not self._archive_cfg.enabled:
            return False
        if not self._archive_cache_dir:
            return False

        if self._archive_best_objective is not None and not (objective_value < self._archive_best_objective - 1e-9):
            self._archive_stats["non_improving_skipped"] += 1
            return False

        values_by_index = self._collect_sparse_values(accessor)
        solution_hash = self._stable_hash(values_by_index)
        duplicate_same_score = any(
            str(entry.get("solution_hash")) == solution_hash
            and abs(float(entry.get("objective_value", 0) or 0) - objective_value) <= 1e-9
            for entry in self._archive_entries
        )
        if duplicate_same_score:
            self._archive_stats["dedup_skipped"] += 1
            return False

        self._archive_seq += 1
        seq_id = self._archive_seq
        created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cache_subdir = self._archive_cache_dir / f"sol_{seq_id:04d}"
        cache_subdir.mkdir(parents=True, exist_ok=True)
        solution_file = cache_subdir / f"sol_{seq_id:04d}.json"
        meta_file = cache_subdir / f"meta_{seq_id:04d}.json"

        solution_file.write_text(
            json.dumps(
                {
                    "seq_id": seq_id,
                    "objective_value": objective_value,
                    "created_at": created_at,
                    "values_by_index": values_by_index,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        event_log_path = write_event_log_csv(
            cache_subdir,
            accessor,
            solution_id=f"sol_{seq_id:04d}",
            snapshot_id=f"sol_{seq_id:04d}",
        )
        violation_rows = summarize_event_log_csv(event_log_path)
        teacher_names = sorted(
            {
                str(r.get("teacher", "")).strip()
                for r in violation_rows
                if str(r.get("teacher", "")).strip() and str(r.get("teacher", "")).strip() != "GLOBAL"
            }
        )
        soft_penalty_total = sum(float(r.get("penalty_sum", 0) or 0) for r in violation_rows)
        soft_trigger_total = sum(float(r.get("count", 0) or 0) for r in violation_rows)
        if best_bound is None:
            best_bound = self._safe_metric(accessor, "BestObjectiveBound", None)
        if num_conflicts is None:
            num_conflicts = self._safe_metric(accessor, "NumConflicts", 0)
        if num_branches is None:
            num_branches = self._safe_metric(accessor, "NumBranches", 0)
        if elapsed_sec is None:
            elapsed_sec = wall_time if wall_time is not None else round(time.monotonic() - self._start_ts, 3)
        if solution_count is None:
            solution_count = self._safe_metric(accessor, "NumSolutions", seq_id) or seq_id
        if time_limit is None:
            time_limit = self._current_time_limit_seconds()

        meta_file.write_text(
            json.dumps(
                {
                    "seq_id": seq_id,
                    "created_at": created_at,
                    "solver_status": str(solver_status or "FEASIBLE"),
                    "objective_value": objective_value,
                    "solution_hash": solution_hash,
                    "best_bound": float(best_bound) if best_bound is not None else None,
                    "time_limit": float(time_limit) if time_limit is not None else None,
                    "conflicts": int(num_conflicts or 0),
                    "branches": int(num_branches or 0),
                    "elapsed_sec": float(elapsed_sec),
                    "solution_count": int(solution_count),
                    "soft_penalty_total": soft_penalty_total,
                    "soft_trigger_total": soft_trigger_total,
                    "teachers": teacher_names,
                    "event_log_file": str(event_log_path),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        entry = {
            "seq_id": seq_id,
            "created_at": created_at,
            "solver_status": str(solver_status or "FEASIBLE"),
            "objective_value": objective_value,
            "solution_hash": solution_hash,
            "best_bound": float(best_bound) if best_bound is not None else None,
            "time_limit": float(time_limit) if time_limit is not None else None,
            "conflicts": int(num_conflicts or 0),
            "branches": int(num_branches or 0),
            "elapsed_sec": float(elapsed_sec),
            "solution_count": int(solution_count),
            "solution_file": str(solution_file),
            "meta_file": str(meta_file),
            "event_log_file": str(event_log_path),
        }
        self._archive_entries.append(entry)
        self._archive_hashes.add(solution_hash)
        self._archive_best_objective = objective_value
        self._archive_stats["captured"] += 1

        max_keep = int(self._archive_cfg.max_keep)
        if max_keep > 0 and len(self._archive_entries) > max_keep:
            remove_entry = max(
                self._archive_entries,
                key=lambda e: (float(e["objective_value"]), -int(e["seq_id"])),
            )
            self._archive_entries.remove(remove_entry)
            self._archive_hashes.discard(str(remove_entry["solution_hash"]))
            try:
                shutil.rmtree(Path(str(remove_entry["solution_file"])).parent)
            except Exception:
                logger.warning("failed to remove evicted cache entry: %s", remove_entry.get("solution_file"), exc_info=True)
            self._archive_stats["evicted"] += 1

        self._write_archive_index()
        periodic_every = int(self._archive_cfg.periodic_export_every or 0)
        if periodic_every > 0 and int(self._archive_stats.get("captured", 0)) % periodic_every == 0:
            try:
                self._export_periodic_best_excel()
            except Exception:
                logger.warning("periodic archive export failed", exc_info=True)
        return True

    def record_final_solver_overview(self, solver: Any, meta: dict) -> None:
        final_meta = enrich_solver_overview(dict(meta))
        self._final_solver_overview = final_meta
        status = str(final_meta.get("solver_status") or "").upper()
        if status not in {"OPTIMAL", "FEASIBLE"}:
            return
        try:
            objective_value = float(final_meta.get("objective_value"))
        except Exception:
            return
        self._capture_archive_solution(
            solver,
            objective_value=objective_value,
            solver_status=status,
            best_bound=final_meta.get("best_bound"),
            time_limit=final_meta.get("time_limit"),
            num_conflicts=final_meta.get("num_conflicts"),
            num_branches=final_meta.get("num_branches"),
            wall_time=final_meta.get("wall_time"),
            solution_count=final_meta.get("solution_index"),
        )

    def _snapshot_dir(self) -> Path:
        ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        return self._cfg.root_dir / ts

    def _write_meta(self, snap_dir: Path) -> None:
        raw_metrics: Dict[str, Any] = {}
        if self._link_stats:
            raw_metrics["link_viol1"] = sum(self.Value(v) for v in self._link_stats.get("viol1", []))
            raw_metrics["link_viol3"] = sum(self.Value(v) for v in self._link_stats.get("viol3", []))
            raw_metrics["link_viol4"] = sum(self.Value(v) for v in self._link_stats.get("viol4", []))
            raw_metrics["link_viol5"] = sum(self.Value(v) for v in self._link_stats.get("viol5", []))
        has_obj = hasattr(self, "ObjectiveValue")
        def _safe(name: str, default: int = 0) -> int:
            fn = getattr(self, name, None)
            if fn is None:
                return default
            try:
                return int(fn())
            except Exception:
                return default

        meta = {
            "snapshot_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "elapsed_sec": round(time.monotonic() - self._start_ts, 3),
            "objective_value": float(self.ObjectiveValue()) if has_obj else None,
            "best_bound": float(self.BestObjectiveBound()) if has_obj else None,
            "status": "FOUND_SOLUTION",
            "solution_count": _safe("NumSolutions"),
            "conflicts": _safe("NumConflicts"),
            "branches": _safe("NumBranches"),
            "raw_metrics": raw_metrics,
        }
        (snap_dir / "snapshot_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    def _build_evening_assign(self) -> Optional[dict]:
        if not self._night_ctx:
            return None
        night_vars = self._night_ctx.get("vars", {})
        ctx = self._night_ctx.get("ctx", {})
        if not night_vars or not ctx:
            return None
        assigns = {}
        y = night_vars.get("y", {})
        cst = ctx.get("cst", {})
        days = ctx.get("days", [])
        periods = ctx.get("periods", [])
        classes = ctx.get("classes", [])
        if not (y and cst and days and periods and classes):
            return None
        for cls in classes:
            for d in days:
                for p in periods:
                    for (c, subj), tch in cst.items():
                        if c != cls:
                            continue
                        if self.Value(y[(cls, subj, d, p)]) == 1:
                            assigns[(cls, d, 1 if p == periods[0] else 2)] = (subj, tch)
                            break
        return assigns

    def _build_checkin_rows(self) -> Optional[list[dict[str, str]]]:
        if not self._night_ctx:
            return None
        night_vars = self._night_ctx.get("vars", {})
        ctx = self._night_ctx.get("ctx", {})
        checkin_m = night_vars.get("checkin_m")
        checkin_f = night_vars.get("checkin_f")
        if not (checkin_m and checkin_f and ctx):
            return None
        return build_checkin_rows_from_solver(
            checkin_m,
            checkin_f,
            ctx.get("days", []),
            ctx.get("male_heads", []),
            ctx.get("female_heads", []),
            self,
        )

    def _export_day(self, snap_dir: Path) -> None:
        data = self._day_ctx.get("data")
        dv = self._day_ctx.get("dv")
        if data is None or dv is None:
            return
        head_teachers = self._day_ctx.get("head_teachers", [])
        duty_vars = self._day_ctx.get("duty_vars", {})
        teach_pm1_vars = self._day_ctx.get("teach_pm1_vars", {})
        excess_duty = self._day_ctx.get("excess_duty", {})
        excess_pm1 = self._day_ctx.get("excess_pm1", {})
        duty_floor_vars = self._day_ctx.get("duty_floor_vars", {})
        head_floor_by_teacher = self._day_ctx.get("head_floor_by_teacher", {})
        head_floor_groups = self._day_ctx.get("head_floor_groups", {})
        head_allowed_duty_floors = self._day_ctx.get("head_allowed_duty_floors", {})
        head_borrow_5_to_4 = self._day_ctx.get("head_borrow_5_to_4", {})
        head_weekly_duty_count_45f = self._day_ctx.get("head_weekly_duty_count_45f", {})
        head_h4_base = self._day_ctx.get("head_h4_base", [])
        head_h5_base = self._day_ctx.get("head_h5_base", [])
        head_t9_teacher = self._day_ctx.get("head_t9_teacher", "")
        head_duty_days = self._day_ctx.get("head_duty_days", sorted({s.day for s in data.available_slots}))
        weekday_cfg = self._day_ctx.get("weekday_cfg")
        pe_teachers = self._day_ctx.get("pe_teachers", set())
        pe_tech_teachers = self._day_ctx.get("pe_tech_teachers", set())
        pe_cfg = self._day_ctx.get("pe_cfg")
        liu_allowed = self._day_ctx.get("liu_allowed", set())
        tao_allowed = self._day_ctx.get("tao_allowed", set())
        liu_viol_fixed = self._day_ctx.get("liu_viol_fixed", 0)
        tao_viol_fixed = self._day_ctx.get("tao_viol_fixed", 0)
        pe_illegal_fixed = self._day_ctx.get("pe_illegal_fixed", 0)
        pe_gap_details = self._day_ctx.get("pe_gap_details", {})
        pe_am_penalties = self._day_ctx.get("pe_am_penalties", [])
        multi_details = self._day_ctx.get("multi_details")
        am4pm1_details = self._day_ctx.get("am4pm1_details", {})
        continuity_details = self._day_ctx.get("continuity_details", {})
        core_load_details = self._day_ctx.get("core_load_details", {})
        m1_cap_details = self._day_ctx.get("m1_cap_details", {})
        lang_am_vars = self._day_ctx.get("lang_am_vars", [])
        lang_pm_vars = self._day_ctx.get("lang_pm_vars", [])
        lang_fixed = self._day_ctx.get("lang_fixed", (0, 0))
        stem_am1_vars = self._day_ctx.get("stem_am1_vars", [])
        stem_am1_fixed = self._day_ctx.get("stem_am1_fixed", 0)
        teacher_am1_details = self._day_ctx.get("teacher_am1_details", {})
        two_class_details = self._day_ctx.get("two_class_details", {})
        noon_male_vars = self._day_ctx.get("noon_male_vars", {})
        noon_female_vars = self._day_ctx.get("noon_female_vars", {})
        noon_day_penalty = self._day_ctx.get("noon_day_penalty", {})
        noon_days = self._day_ctx.get("noon_days", sorted({s.day for s in data.available_slots}))
        grade_group_duty_vars = self._day_ctx.get("grade_group_duty_vars", {})
        grade_group_info = self._day_ctx.get("grade_group_info", {}) or {}

        evening_assign = self._build_evening_assign()
        checkin_rows = self._build_checkin_rows()
        head_duty_result = None
        if duty_vars:
            head_duty_result = extract_duty_results(self, duty_vars, head_teachers, head_duty_days)
        noon_dorm_rows = None
        if noon_male_vars:
            noon_dorm_rows = extract_noon_dorm_rows(
                self,
                noon_days,
                noon_male_vars,
                noon_female_vars,
                noon_day_penalty,
            )
        grade_duty_map = extract_grade_group_duty_map(
            self,
            grade_group_duty_vars,
            grade_group_info.get("days", []),
            grade_group_info.get("members", []),
        )
        grade_available_map = extract_grade_group_available_map(
            self,
            self._night_ctx.get("vars", {}).get("on_teacher_day", {}),
            grade_group_info.get("days", []),
            grade_group_info.get("members", []),
        )

        summary_path = snap_dir / DAY_SUMMARY_XLSX
        formal_path = snap_dir / DAY_FORMAL_XLSX
        save_day_class_and_teacher_summary_excel(
            data,
            dv,
            self,
            str(summary_path),
            evening_assign=evening_assign,
            grade_prefix=self._grade_prefix,
            head_teachers=head_teachers,
            male_head_teachers=self._night_ctx.get("ctx", {}).get("male_heads", []) if self._night_ctx else [],
            female_head_teachers=self._night_ctx.get("ctx", {}).get("female_heads", []) if self._night_ctx else [],
            head_duty_result=head_duty_result,
            duty_floor_vars=duty_floor_vars,
            head_floor_groups=head_floor_groups,
            checkin_rows=checkin_rows,
            noon_dorm_rows=noon_dorm_rows,
            grade_group_duty_map=grade_duty_map,
            grade_group_available_map=grade_available_map,
        )
        wide_df = export_day_schedule_df(data, dv, self)
        grid_dfs = export_day_schedule_grid_df(data, dv, self)
        save_day_schedule_excel(wide_df, grid_dfs, str(formal_path))

        if self._cfg.export_checklists and weekday_cfg is not None:
            write_day_check_hard_constraints(snap_dir, data, dv, self, head_teachers, pe_teachers)
            if core_load_details:
                write_core_teacher_day_load_sanity(snap_dir, self, core_load_details)
            if m1_cap_details:
                write_teacher_m1_cap_report(
                    snap_dir,
                    self,
                    m1_cap_details,
                    weekday_cfg.teacher_m1_cap_max,
                    weekday_cfg.w_hit_m1_cap,
                )
            write_day_constraint_checklist(
                snap_dir,
                data,
                dv,
                self,
                head_teachers,
                pe_teachers,
                multi_details,
                am4pm1_details,
                (
                    weekday_cfg.teacher_am4_pm1_w3,
                    weekday_cfg.teacher_am4_pm1_w4,
                    weekday_cfg.teacher_am4_pm1_w5,
                    weekday_cfg.teacher_am4_pm1_w6,
                ),
                self._day_ctx.get("weekday_balance_penalties", []),
            )
            if continuity_details:
                write_teacher_continuity_report(snap_dir, self, continuity_details)
            if am4pm1_details:
                write_teacher_am4_pm1_penalty_report(
                    snap_dir,
                    self,
                    am4pm1_details,
                    (
                        weekday_cfg.teacher_am4_pm1_w3,
                        weekday_cfg.teacher_am4_pm1_w4,
                        weekday_cfg.teacher_am4_pm1_w5,
                        weekday_cfg.teacher_am4_pm1_w6,
                    ),
                )
            if duty_vars:
                write_head_duty_hard_check(
                    snap_dir,
                    self,
                    duty_vars,
                    teach_pm1_vars,
                    head_teachers,
                    head_duty_days,
                    duty_floor_vars,
                    head_floor_groups,
                    head_floor_by_teacher,
                    head_allowed_duty_floors,
                    head_weekly_duty_count_45f,
                    head_borrow_5_to_4,
                )
                write_head_duty_soft_report(
                    snap_dir,
                    self,
                    duty_vars,
                    teach_pm1_vars,
                    head_teachers,
                    head_duty_days,
                    excess_duty,
                    excess_pm1,
                    self._day_ctx.get("head_duty_w_excess_duty", 300),
                    self._day_ctx.get("head_duty_w_excess_pm1", 120),
                    head_weekly_duty_count_45f,
                    head_borrow_5_to_4,
                    head_h4_base,
                    head_h5_base,
                    head_t9_teacher,
                )
            if two_class_details or (weekday_cfg.two_class_daily_min_mode == "hard"):
                write_two_class_daily_min_report(snap_dir, self, two_class_details, weekday_cfg.two_class_daily_min_mode)
            write_day_soft_timepref_report(
                snap_dir,
                self,
                lang_am_vars,
                lang_pm_vars,
                lang_fixed,
                stem_am1_vars,
                stem_am1_fixed,
                teacher_am1_details,
                (
                    weekday_cfg.w_lang_pm_penalty,
                    weekday_cfg.w_lang_am_reward,
                    weekday_cfg.w_stem_am1_penalty,
                    weekday_cfg.w_teacher_only_am1_day,
                    weekday_cfg.k_teacher_am1_week,
                    weekday_cfg.w_teacher_am1_excess,
                ),
            )
            if pe_cfg is not None:
                write_pe_tech_checklist(
                    snap_dir,
                    data,
                    dv,
                    self,
                    pe_teachers,
                    pe_tech_teachers,
                    liu_allowed,
                    tao_allowed,
                    liu_viol_fixed,
                    tao_viol_fixed,
                    pe_illegal_fixed,
                    pe_am_penalties,
                    pe_gap_details,
                    (pe_cfg.w_pe_am_penalty, pe_cfg.w_pe_gap_penalty),
                )
            if noon_male_vars:
                write_noon_dorm_checklist(
                    snap_dir,
                    self,
                    noon_days,
                    noon_male_vars,
                    noon_female_vars,
                    noon_day_penalty,
                )
            if grade_group_duty_vars:
                write_grade_group_duty_checklist(
                    snap_dir,
                    self,
                    info=grade_group_info,
                    grade_duty=grade_group_duty_vars,
                    on_teacher_day=self._night_ctx.get("vars", {}).get("on_teacher_day", {}),
                )
            pers_stats = self._day_ctx.get("pers_stats", {})
            pers_hard_notes = self._day_ctx.get("pers_hard_notes", [])
            if pers_stats:
                write_personalized_checklist(snap_dir, self, pers_stats, pers_hard_notes)

    def _export_night(self, snap_dir: Path) -> None:
        if not self._night_ctx:
            return
        night_vars = self._night_ctx.get("vars", {})
        ctx = self._night_ctx.get("ctx", {})
        rules = self._night_ctx.get("rules", {})
        if not night_vars or not ctx:
            return
        export_result_xlsx(
            str(snap_dir / NIGHT_SCHEDULE_XLSX),
            self,
            night_vars,
            ctx["classes"],
            ctx["cst"],
            ctx["days"],
            ctx["periods"],
            ctx["male_heads"],
            ctx["female_heads"],
        )
        if self._cfg.export_checklists and rules:
            rules_tmp = dict(rules)
            rules_tmp.setdefault("output", {})
            rules_tmp["output"]["result_xlsx"] = str((snap_dir / NIGHT_SCHEDULE_XLSX).as_posix())
            write_night_constraint_checklist(snap_dir, rules_tmp, ctx, night_vars, self, "FOUND_SOLUTION")
            write_double_class_weekday_p1_p2_report(snap_dir, self, night_vars, ctx, rules_tmp)

    def _export_link(self, snap_dir: Path) -> None:
        if not self._bridge or not self._link_stats:
            return
        if not self._cfg.export_link_reports:
            return
        cfg = self._day_ctx.get("day_night_link_cfg")
        if cfg is None:
            return
        write_link_checklist(snap_dir, self, self._bridge, self._link_stats, cfg)

    def _write_soft_violation_summary(self, snap_dir: Path) -> None:
        """Write soft violation summary for current snapshot."""
        event_log_path = write_event_log_csv(
            snap_dir,
            self,
            solution_id=f"snapshot_{snap_dir.name}",
            snapshot_id=snap_dir.name,
        )
        rows = summarize_event_log_csv(event_log_path)
        total_penalty = sum(float(r.get("penalty_sum", 0) or 0) for r in rows)
        out_csv = snap_dir / "soft_violation_summary.csv"
        with out_csv.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(
                f, fieldnames=["rule_id", "rule_name", "teacher", "weight", "count", "penalty_sum"]
            )
            writer.writeheader()
            for row in rows:
                writer.writerow(row)

        # 仅导出“未满足”明细（触发次数>0 且罚分>0），便于老师直接查看
        detail_csv = snap_dir / "软约束未满足明细.csv"
        with detail_csv.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=["约束ID", "约束名称", "教师", "权重", "触发次数", "罚分合计"],
            )
            writer.writeheader()
            for row in rows:
                if float(row.get("count", 0) or 0) <= 0:
                    continue
                if float(row.get("penalty_sum", 0) or 0) <= 0:
                    continue
                writer.writerow(
                    {
                        "约束ID": row.get("rule_id", ""),
                        "约束名称": row.get("rule_name", ""),
                        "教师": row.get("teacher", ""),
                        "权重": row.get("weight", 0),
                        "触发次数": row.get("count", 0),
                        "罚分合计": row.get("penalty_sum", 0),
                    }
                )

        summary_txt = snap_dir / "求解评分摘要.txt"
        obj = None
        try:
            obj = float(self.ObjectiveValue())
        except Exception:
            obj = None
        lines = [
            "[求解评分摘要]",
            f"软约束总罚分：{total_penalty}",
            f"目标值：{obj if obj is not None else ''}",
        ]
        summary_txt.write_text("\n".join(lines), encoding="utf-8")

    def _load_frozen_accessor(self, entry: dict) -> FrozenSolutionAccessor:
        payload = json.loads(Path(str(entry["solution_file"])).read_text(encoding="utf-8"))
        raw_map = payload.get("values_by_index", {}) or {}
        values_by_index = {int(k): float(v) for k, v in raw_map.items()}
        return FrozenSolutionAccessor(values_by_index)

    def _build_evening_assign_with_value(self, value_accessor: Any) -> Optional[dict]:
        if not self._night_ctx:
            return None
        night_vars = self._night_ctx.get("vars", {})
        ctx = self._night_ctx.get("ctx", {})
        if not night_vars or not ctx:
            return None
        assigns = {}
        y = night_vars.get("y", {})
        cst = ctx.get("cst", {})
        days = ctx.get("days", [])
        periods = ctx.get("periods", [])
        classes = ctx.get("classes", [])
        if not (y and cst and days and periods and classes):
            return None
        for cls in classes:
            for d in days:
                for p in periods:
                    for (c, subj), tch in cst.items():
                        if c != cls:
                            continue
                        if value_accessor.Value(y[(cls, subj, d, p)]) == 1:
                            assigns[(cls, d, 1 if p == periods[0] else 2)] = (subj, tch)
                            break
        return assigns

    def _build_checkin_rows_with_value(self, value_accessor: Any) -> Optional[list[dict[str, str]]]:
        if not self._night_ctx:
            return None
        night_vars = self._night_ctx.get("vars", {})
        ctx = self._night_ctx.get("ctx", {})
        checkin_m = night_vars.get("checkin_m")
        checkin_f = night_vars.get("checkin_f")
        if not (checkin_m and checkin_f and ctx):
            return None
        return build_checkin_rows_from_solver(
            checkin_m,
            checkin_f,
            ctx.get("days", []),
            ctx.get("male_heads", []),
            ctx.get("female_heads", []),
            value_accessor,
        )

    def _export_joint_entry_excel(self, entry: dict, out_path: Path) -> None:
        if not self._day_ctx:
            return
        data = self._day_ctx.get("data")
        dv = self._day_ctx.get("dv")
        if data is None or dv is None:
            return
        value_accessor = self._load_frozen_accessor(entry)
        head_teachers = self._day_ctx.get("head_teachers", [])
        duty_vars = self._day_ctx.get("duty_vars", {})
        duty_floor_vars = self._day_ctx.get("duty_floor_vars", {})
        head_floor_groups = self._day_ctx.get("head_floor_groups", {})
        head_duty_days = self._day_ctx.get("head_duty_days", sorted({s.day for s in data.available_slots}))
        noon_male_vars = self._day_ctx.get("noon_male_vars", {})
        noon_female_vars = self._day_ctx.get("noon_female_vars", {})
        noon_day_penalty = self._day_ctx.get("noon_day_penalty", {})
        noon_days = self._day_ctx.get("noon_days", sorted({s.day for s in data.available_slots}))
        grade_group_duty_vars = self._day_ctx.get("grade_group_duty_vars", {})
        grade_group_info = self._day_ctx.get("grade_group_info", {}) or {}

        evening_assign = self._build_evening_assign_with_value(value_accessor)
        checkin_rows = self._build_checkin_rows_with_value(value_accessor)
        head_duty_result = None
        if duty_vars:
            head_duty_result = extract_duty_results(value_accessor, duty_vars, head_teachers, head_duty_days)
        noon_dorm_rows = None
        if noon_male_vars:
            noon_dorm_rows = extract_noon_dorm_rows(
                value_accessor,
                noon_days,
                noon_male_vars,
                noon_female_vars,
                noon_day_penalty,
            )
        grade_duty_map = extract_grade_group_duty_map(
            value_accessor,
            grade_group_duty_vars,
            grade_group_info.get("days", []),
            grade_group_info.get("members", []),
        )
        grade_available_map = extract_grade_group_available_map(
            value_accessor,
            self._night_ctx.get("vars", {}).get("on_teacher_day", {}),
            grade_group_info.get("days", []),
            grade_group_info.get("members", []),
        )

        save_day_class_and_teacher_summary_excel(
            data,
            dv,
            value_accessor,
            str(out_path),
            evening_assign=evening_assign,
            grade_prefix=self._grade_prefix,
            head_teachers=head_teachers,
            male_head_teachers=self._night_ctx.get("ctx", {}).get("male_heads", []) if self._night_ctx else [],
            female_head_teachers=self._night_ctx.get("ctx", {}).get("female_heads", []) if self._night_ctx else [],
            head_duty_result=head_duty_result,
            duty_floor_vars=duty_floor_vars,
            head_floor_groups=head_floor_groups,
            checkin_rows=checkin_rows,
            noon_dorm_rows=noon_dorm_rows,
            grade_group_duty_map=grade_duty_map,
            grade_group_available_map=grade_available_map,
        )

    def _export_joint_entry_formal_excel(self, entry: dict, out_path: Path) -> None:
        if not self._day_ctx:
            return
        data = self._day_ctx.get("data")
        dv = self._day_ctx.get("dv")
        if data is None or dv is None:
            return
        value_accessor = self._load_frozen_accessor(entry)
        wide_df = export_day_schedule_df(data, dv, value_accessor)
        grid_dfs = export_day_schedule_grid_df(data, dv, value_accessor)
        save_day_schedule_excel(wide_df, grid_dfs, str(out_path))

    def _export_night_entry_excel(self, entry: dict, out_path: Path) -> None:
        if not self._night_ctx:
            return
        value_accessor = self._load_frozen_accessor(entry)
        night_vars = self._night_ctx.get("vars", {})
        ctx = self._night_ctx.get("ctx", {})
        if not night_vars or not ctx:
            return
        export_result_xlsx(
            str(out_path),
            value_accessor,
            night_vars,
            ctx["classes"],
            ctx["cst"],
            ctx["days"],
            ctx["periods"],
            ctx["male_heads"],
            ctx["female_heads"],
        )

    def _build_archive_diagnostic(self, entries: List[dict], best_entry: dict) -> Optional[Path]:
        if not self._archive_meta_dir or not self._archive_diag_dir:
            return None
        diag_root = self._archive_meta_dir / "diag_cache"
        if diag_root.exists():
            shutil.rmtree(diag_root)
        snapshots_root = diag_root / "snapshots"
        snapshots_root.mkdir(parents=True, exist_ok=True)

        for rank, entry in enumerate(entries, start=1):
            sid = f"top{rank:02d}_seq{int(entry['seq_id']):04d}"
            snap_dir = snapshots_root / sid
            snap_dir.mkdir(parents=True, exist_ok=True)
            event_log_src = Path(str(entry.get("event_log_file", "")))
            if event_log_src.exists():
                shutil.copy2(event_log_src, snap_dir / "event_log.csv")
            snap_meta = {
                "snapshot_time": str(entry.get("created_at", "")),
                "status": "FOUND_SOLUTION",
                "solution_count": int(entry.get("solution_count", entry.get("seq_id", 0))),
                "objective_value": float(entry.get("objective_value", 0)),
                "best_bound": entry.get("best_bound", None),
                "time_limit": entry.get("time_limit", None),
                "conflicts": int(entry.get("conflicts", 0) or 0),
                "branches": int(entry.get("branches", 0) or 0),
                "elapsed_sec": entry.get("elapsed_sec", None),
            }
            (snap_dir / "snapshot_meta.json").write_text(
                json.dumps(snap_meta, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

        best_event_log = Path(str(best_entry.get("event_log_file", "")))
        if best_event_log.exists():
            shutil.copy2(best_event_log, diag_root / "event_log.csv")

        # 生成“最终解”概览元数据，避免求解概览关键列为空
        final_overview = dict(self._final_solver_overview or {})
        if final_overview:
            final_overview.setdefault("solution_id", "final")
            final_overview["snapshot_id"] = "最终解"
            final_overview.setdefault("is_best_solution", True)
        else:
            final_overview = enrich_solver_overview(
                {
                    "solution_id": "final",
                    "snapshot_id": "最终解",
                    "solver_status": "FEASIBLE",
                    "objective_value": float(best_entry.get("objective_value", 0) or 0),
                    "best_bound": best_entry.get("best_bound", None),
                    "time_limit": best_entry.get("time_limit", self._current_time_limit_seconds()),
                    "num_conflicts": int(self._safe_metric(self, "NumConflicts", 0) or 0),
                    "num_branches": int(self._safe_metric(self, "NumBranches", 0) or 0),
                    "wall_time": float(self._safe_metric(self, "WallTime", 0.0) or 0.0),
                    "solution_index": int(self._safe_metric(self, "NumSolutions", 0) or 0),
                    "is_best_solution": True,
                }
            )
        (diag_root / "final_solver_overview.json").write_text(
            json.dumps(final_overview, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        diag_xlsx_tmp = build_multi_solution_diagnostic(diag_root)
        self._archive_diag_dir.mkdir(parents=True, exist_ok=True)
        diag_target_ts = self._archive_diag_dir / diag_xlsx_tmp.name
        shutil.copy2(diag_xlsx_tmp, diag_target_ts)
        diag_alias = self._archive_diag_dir / MULTI_DIAGNOSTIC_XLSX
        shutil.copy2(diag_target_ts, diag_alias)
        return diag_alias

    def _write_run_summary(
        self,
        mode: str,
        best_entry: Optional[dict],
        top_count: int,
        diag_path: Optional[Path],
        diag_root_path: Optional[Path] = None,
    ) -> None:
        if not self._archive_meta_dir:
            return
        summary = {
            "mode": mode,
            "run_dir": str(self._archive_run_dir) if self._archive_run_dir else "",
            "max_keep": int(self._archive_cfg.max_keep),
            "kept_solutions": len(self._archive_entries),
            "top_exported": top_count,
            "captured": int(self._archive_stats["captured"]),
            "dedup_skipped": int(self._archive_stats["dedup_skipped"]),
            "non_improving_skipped": int(self._archive_stats["non_improving_skipped"]),
            "evicted": int(self._archive_stats["evicted"]),
            "periodic_exports": int(self._archive_stats.get("periodic_exports", 0)),
            "periodic_export_every": int(self._archive_cfg.periodic_export_every or 0),
            "best_objective": float(best_entry["objective_value"]) if best_entry else None,
            "best_seq_id": int(best_entry["seq_id"]) if best_entry else None,
            "diagnostics_file": str(diag_path) if diag_path else "",
            "diagnostics_file_root": str(diag_root_path) if diag_root_path else "",
        }
        (self._archive_meta_dir / "run_summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def export_solution_archive(
        self,
        mode: str,
        root_best_copy: Optional[Path] = None,
        root_formal_copy: Optional[Path] = None,
    ) -> Optional[dict]:
        if not self._archive_cfg.enabled:
            return None
        if not self._archive_run_dir:
            return None
        entries = sorted(self._archive_entries, key=lambda e: (float(e["objective_value"]), int(e["seq_id"])))
        if not entries:
            self._write_run_summary(mode, None, 0, None)
            return {
                "run_dir": self._archive_run_dir,
                "top_count": 0,
                "best_excel": None,
                "diag_excel": None,
            }

        top_entries = entries[: int(self._archive_cfg.max_keep)]
        for rank, entry in enumerate(top_entries, start=1):
            export_ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            if mode == "joint":
                file_name = f"{TOP_DAY_PREFIX}_top{rank:02d}_seq{int(entry['seq_id']):04d}_{export_ts}.xlsx"
                out_path = self._unique_path(self._archive_top_dir / file_name)
                self._export_joint_entry_excel(entry, out_path)
            else:
                file_name = f"{TOP_NIGHT_PREFIX}_top{rank:02d}_seq{int(entry['seq_id']):04d}_{export_ts}.xlsx"
                out_path = self._unique_path(self._archive_top_dir / file_name)
                self._export_night_entry_excel(entry, out_path)

        best_entry = top_entries[0]
        best_excel = self._archive_best_dir / BEST_SOLUTION_XLSX
        best_formal_excel = self._archive_best_dir / BEST_SOLUTION_FORMAL_XLSX
        if mode == "joint":
            self._export_joint_entry_excel(best_entry, best_excel)
            self._export_joint_entry_formal_excel(best_entry, best_formal_excel)
        else:
            self._export_night_entry_excel(best_entry, best_excel)
        best_meta = self._archive_best_dir / BEST_SOLUTION_META_JSON
        best_meta.write_text(
            json.dumps(
                {
                    "objective_value": float(best_entry["objective_value"]),
                    "seq_id": int(best_entry["seq_id"]),
                    "solution_hash": str(best_entry["solution_hash"]),
                    "created_at": str(best_entry["created_at"]),
                    "source_solution_file": str(best_entry["solution_file"]),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        if root_best_copy is not None:
            root_best_copy.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(best_excel, root_best_copy)
        if mode == "joint" and root_formal_copy is not None:
            root_formal_copy.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(best_formal_excel, root_formal_copy)

        diag_path = self._build_archive_diagnostic(top_entries, best_entry)
        diag_root_copy: Optional[Path] = None
        if diag_path is not None:
            out_root = self._archive_cfg.root_dir.resolve().parent
            out_root.mkdir(parents=True, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            diag_root_copy = self._unique_path(out_root / f"{MULTI_DIAGNOSTIC_XLSX[:-5]}_{ts}.xlsx")
            shutil.copy2(diag_path, diag_root_copy)

        self._write_run_summary(mode, best_entry, len(top_entries), diag_path, diag_root_copy)
        return {
            "run_dir": self._archive_run_dir,
            "top_count": len(top_entries),
            "best_excel": best_excel,
            "best_formal_excel": best_formal_excel if mode == "joint" else None,
            "diag_excel": diag_root_copy or diag_path,
        }

    def on_solution_callback(self) -> None:
        self._capture_improvement_solution()
        if self._stop_file is not None and self._stop_file.exists():
            logger.info("stop file detected, stopping search after current solution: %s", self._stop_file)
            self.StopSearch()
            return

        # TopN/Best 归档开启时，仅做轻量解池采集，不再做 snapshots 导出
        if self._archive_cfg.enabled:
            return

        if not self._cfg.enabled:
            return
        now = time.monotonic()
        if now - self._last_export_ts < self._cfg.interval_sec:
            return
        if self._in_export:
            return

        self._in_export = True
        try:
            snap_dir = self._snapshot_dir()
            snap_dir.mkdir(parents=True, exist_ok=True)
            self._write_meta(snap_dir)
            if self._cfg.export_day:
                self._export_day(snap_dir)
            if self._cfg.export_night:
                self._export_night(snap_dir)
            self._export_link(snap_dir)
            self._write_soft_violation_summary(snap_dir)
        except Exception:
            logger.warning("snapshot export failed", exc_info=True)
        finally:
            self._last_export_ts = time.monotonic()
            self._in_export = False

