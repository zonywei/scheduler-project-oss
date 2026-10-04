# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path
import sys
import warnings
from unittest.mock import patch

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scheduler.app import service
from scheduler.config.loader import load_effective_config, merge_section as merge_section_new
from scheduler.config_loader import merge_section as merge_section_old
from scheduler.diagnostics.rule_registry import ensure_rule_meta, get_rule_meta
from scheduler.scheduler_core import SchedulerCore


def _collect_enable_flags(obj: object, prefix: str = "") -> dict[str, object]:
    out: dict[str, object] = {}
    if isinstance(obj, dict):
        for key, value in obj.items():
            key_s = str(key)
            path = f"{prefix}.{key_s}" if prefix else key_s
            if key_s.startswith("enable_"):
                out[path] = value
            out.update(_collect_enable_flags(value, path))
    return out


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _legacy_merge_section(io_cfg: dict, rules_cfg: dict, section: str) -> dict:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        return merge_section_old(io_cfg, rules_cfg, section)


def check_effective_config_equivalence(io_path: Path, rules_path: Path) -> None:
    effective = load_effective_config("joint", {"io_path": io_path, "rules_path": rules_path})
    io_cfg = effective.io_cfg
    rules_cfg = effective.rules_cfg
    sections = sorted(set(io_cfg.keys()) | set(rules_cfg.keys()))
    for section in sections:
        old_section = _legacy_merge_section(io_cfg, rules_cfg, section)
        new_section = merge_section_new(effective, section)
        _assert(
            old_section == new_section,
            f"section merge mismatch: {section}",
        )


def check_enabled_rule_set_equivalence(io_path: Path, rules_path: Path) -> None:
    effective = load_effective_config("joint", {"io_path": io_path, "rules_path": rules_path})
    io_cfg = effective.io_cfg
    rules_cfg = effective.rules_cfg
    sections = sorted(set(io_cfg.keys()) | set(rules_cfg.keys()))
    old_all: dict[str, object] = {}
    new_all: dict[str, object] = {}
    for section in sections:
        old_section = _legacy_merge_section(io_cfg, rules_cfg, section)
        new_section = merge_section_new(effective, section)
        old_all.update(_collect_enable_flags(old_section, section))
        new_all.update(_collect_enable_flags(new_section, section))
    _assert(old_all == new_all, "enabled rule set mismatch between old/new config path")


def _latest_event_log(outputs_dir: Path) -> Path | None:
    candidates = []
    candidates.extend(outputs_dir.glob("solutions/run_*/_run_meta/diag_cache/event_log.csv"))
    candidates.extend(outputs_dir.glob("solutions/run_*/pool_cache/sol_*/event_log.csv"))
    candidates.extend(outputs_dir.glob("event_log.csv"))
    candidates = [p for p in candidates if p.is_file()]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def check_rule_id_chinese_mapping(outputs_dir: Path) -> None:
    event_log = _latest_event_log(outputs_dir)
    if event_log is None:
        return
    missing: list[str] = []
    bad_desc: list[str] = []
    with event_log.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rid = str(row.get("constraint_id", "") or "").strip()
            if not rid:
                continue
            ensure_rule_meta(
                rid,
                name_cn=str(row.get("constraint_name", "") or rid),
                description=str(row.get("description", "") or str(row.get("constraint_name", "") or rid)),
                default_weight=str(row.get("weight_key", "") or ""),
                mode=str(row.get("mode", "") or "soft"),
                source_module=str(row.get("source_module", "") or ""),
            )
            meta = get_rule_meta(rid)
            if meta is None:
                missing.append(rid)
                continue
            if not str(meta.name_cn).strip() or not str(meta.description).strip():
                bad_desc.append(rid)
                continue
            if not re.search(r"[\u4e00-\u9fff]", str(meta.name_cn) + str(meta.description)):
                bad_desc.append(rid)
    _assert(not missing, f"rule_id missing RuleMeta: {sorted(set(missing))}")
    _assert(not bad_desc, f"rule_id meta lacks Chinese description: {sorted(set(bad_desc))}")


def check_service_run_paths(io_path: Path, rules_path: Path) -> None:
    with patch.object(service, "_pre_run_cleanup", lambda *_args, **_kwargs: None):
        with patch.object(SchedulerCore, "run_mode", lambda *_args, **_kwargs: None):
            result = service.run("joint", io_path=io_path, rules_path=rules_path, grade_prefix="高二")
    if result.run_id:
        _assert(result.run_id.startswith("run_"), "service.run run_id format invalid")
    if result.best_solution_path:
        _assert(Path(result.best_solution_path).exists(), "best_solution_path does not exist")
    if result.pool_index_path:
        _assert(Path(result.pool_index_path).exists(), "pool_index_path does not exist")
    if result.diagnostics_summary_path:
        _assert(Path(result.diagnostics_summary_path).exists(), "diagnostics_summary_path does not exist")


def main() -> None:
    parser = argparse.ArgumentParser(description="governance regression checks")
    parser.add_argument(
        "--io",
        default=str(Path("scheduler") / "config" / "io.yaml"),
        help="io.yaml path",
    )
    args = parser.parse_args()
    io_path = Path(args.io).resolve()
    rules_path = io_path.with_name("rules.yaml")
    outputs_dir = (io_path.parent.parent.parent / "outputs").resolve()

    check_effective_config_equivalence(io_path, rules_path)
    check_enabled_rule_set_equivalence(io_path, rules_path)
    check_rule_id_chinese_mapping(outputs_dir)
    check_service_run_paths(io_path, rules_path)
    print("governance regression checks: PASS")


if __name__ == "__main__":
    main()
