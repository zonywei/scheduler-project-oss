# -*- coding: utf-8 -*-
"""Baseline 回归摘要写入工具（只读统计，不影响求解语义）。"""

from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except Exception:
        return default


def _event_log_summary(event_log_path: Path) -> dict[str, Any]:
    if not event_log_path.exists():
        return {
            "exists": False,
            "rows": 0,
            "soft_rows": 0,
            "hard_rows": 0,
            "soft_penalty_sum": 0.0,
            "rule_id_count": 0,
        }

    rows = 0
    soft_rows = 0
    hard_rows = 0
    soft_penalty_sum = 0.0
    rule_ids: set[str] = set()
    with event_log_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows += 1
            mode = str(r.get("mode", "")).strip().lower()
            penalty = _safe_float(r.get("penalty", 0.0), 0.0)
            rid = str(r.get("constraint_id", "")).strip()
            if rid:
                rule_ids.add(rid)
            if mode == "soft":
                soft_rows += 1
                soft_penalty_sum += penalty
            elif mode == "hard":
                hard_rows += 1

    return {
        "exists": True,
        "rows": rows,
        "soft_rows": soft_rows,
        "hard_rows": hard_rows,
        "soft_penalty_sum": soft_penalty_sum,
        "rule_id_count": len(rule_ids),
    }


def write_baseline_report(
    out_dir: Path,
    *,
    mode: str,
    status: str,
    objective: float | None,
    expected_files: list[Path],
    extra: dict[str, Any] | None = None,
) -> Path:
    """写 baseline 回归口径摘要。

    仅做统计与落盘，不参与任何约束、目标或求解器参数。
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    expected = []
    for p in expected_files:
        pp = Path(p)
        expected.append(
            {
                "path": str(pp),
                "exists": pp.exists(),
            }
        )

    event_log_path = out_dir / "event_log.csv"
    report = {
        "timestamp": now,
        "mode": mode,
        "status": status,
        "objective": objective,
        "expected_outputs": expected,
        "event_log": _event_log_summary(event_log_path),
        "extra": extra or {},
    }

    latest_path = out_dir / f"baseline_{mode}_latest.json"
    latest_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    history_path = out_dir / "baseline_history.csv"
    new_row = {
        "timestamp": now,
        "mode": mode,
        "status": status,
        "objective": objective if objective is not None else "",
        "event_log_exists": report["event_log"]["exists"],
        "event_log_rows": report["event_log"]["rows"],
        "soft_penalty_sum": report["event_log"]["soft_penalty_sum"],
        "rule_id_count": report["event_log"]["rule_id_count"],
    }
    fields = list(new_row.keys())
    need_header = not history_path.exists()
    with history_path.open("a", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        if need_header:
            writer.writeheader()
        writer.writerow(new_row)

    return latest_path

