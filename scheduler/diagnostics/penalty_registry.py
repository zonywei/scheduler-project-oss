# -*- coding: utf-8 -*-
"""软约束罚分登记册与事件明细导出。"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from scheduler.diagnostics.rule_registry import (
    ensure_rule_meta,
    rule_meta_map,
    validate_rule_ids,
)

@dataclass
class PenaltyRecord:
    rule_id: str
    rule_name: str
    weight: int | float
    var: Any
    teacher: Optional[str] = None
    day: Optional[str] = None
    slot: Optional[str] = None
    cls: Optional[str] = None
    subj: Optional[str] = None
    constraint_category: str = "preference"
    mode: str = "soft"
    source_module: str = "unknown"
    description: str = ""
    rule_params: str = ""
    constraint_name: Optional[str] = None
    weight_key: str = ""


RULE_META_DEFAULTS: Dict[str, Dict[str, str]] = {
    "night_subject_sync": {
        "constraint_category": "night-duty",
        "source_module": "scheduler/model/constraints/soft_objective.py",
        "description": "同学科教师尽量同节上晚自习",
        "constraint_name": "同学科同步偏好",
    },
    "night_fri_sun_mutex_soft": {
        "constraint_category": "ban",
        "source_module": "scheduler/model/constraints/soft_objective.py",
        "description": "教师周五与周日晚自习尽量不同时安排",
        "constraint_name": "周五+周日晚自习互斥(软)",
    },
    "night_double_class_weekday_p1_p2_soft": {
        "constraint_category": "compactness",
        "source_module": "scheduler/model/constraints/soft_objective.py",
        "description": "双班教师规则日(工作日+周日)两次晚自习尽量拆分到晚自习1/2",
        "constraint_name": "双班教师晚自习节次拆分(软)",
    },
    "multi_class_halfday": {
        "constraint_category": "fairness",
        "source_module": "scheduler/model/constraints/day_weekday_constraints.py",
        "description": "多班教师同半天授课偏好",
        "constraint_name": "多班同半天",
    },
    "teacher_continuity_gap": {
        "constraint_category": "compactness",
        "source_module": "scheduler/model/constraints/day_weekday_constraints.py",
        "description": "减少教师同半天内部空档",
        "constraint_name": "教师连续性",
    },
}


for _rid, _meta in RULE_META_DEFAULTS.items():
    ensure_rule_meta(
        _rid,
        name_cn=str(_meta.get("constraint_name", _rid)),
        description=str(_meta.get("description", _meta.get("constraint_name", _rid))),
        default_weight=str(_meta.get("weight_key", "")),
        mode=str(_meta.get("mode", "soft")),
        source_module=str(_meta.get("source_module", "")),
    )


_REGISTRY: List[PenaltyRecord] = []
_DEDUP_KEYS: set[Tuple[str, int, Optional[str], Optional[str], Optional[str], Optional[str], Optional[str], float]] = set()


def _apply_defaults(rule_id: str, kwargs: dict) -> dict:
    meta = dict(RULE_META_DEFAULTS.get(rule_id, {}))
    meta.update({k: v for k, v in kwargs.items() if v is not None})
    return meta


def register(
    rule_id: str,
    rule_name: str,
    weight: int | float,
    var: Any,
    teacher: Optional[str] = None,
    day: Optional[str] = None,
    slot: Optional[str] = None,
    cls: Optional[str] = None,
    subj: Optional[str] = None,
    **kwargs: Any,
) -> None:
    """登记一个软约束违例变量（仅记录引用，不新增约束）。"""
    key = (rule_id, id(var), teacher, day, slot, cls, subj, float(weight))
    if key in _DEDUP_KEYS:
        return
    _DEDUP_KEYS.add(key)
    meta = _apply_defaults(rule_id, kwargs)
    ensure_rule_meta(
        str(rule_id),
        name_cn=str(meta.get("constraint_name", rule_name)),
        description=str(meta.get("description", rule_name)),
        default_weight=str(meta.get("weight_key", "")),
        mode=str(meta.get("mode", "soft")),
        source_module=str(meta.get("source_module", "")),
    )
    _REGISTRY.append(
        PenaltyRecord(
            rule_id=rule_id,
            rule_name=rule_name,
            weight=weight,
            var=var,
            teacher=teacher,
            day=day,
            slot=slot,
            cls=cls,
            subj=subj,
            constraint_category=str(meta.get("constraint_category", "preference")),
            mode=str(meta.get("mode", "soft")),
            source_module=str(meta.get("source_module", "unknown")),
            description=str(meta.get("description", rule_name)),
            rule_params=str(meta.get("rule_params", "")),
            constraint_name=meta.get("constraint_name"),
            weight_key=str(meta.get("weight_key", "")),
        )
    )


def get_records() -> List[PenaltyRecord]:
    return list(_REGISTRY)


def clear_registry() -> None:
    _REGISTRY.clear()
    _DEDUP_KEYS.clear()


def get_rule_meta_catalog() -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    for rid, meta in rule_meta_map().items():
        out[rid] = {
            "name_cn": meta.name_cn,
            "description": meta.description,
            "mode": meta.mode,
            "source_module": meta.source_module,
            "default_weight": meta.default_weight,
            "config_keys": ",".join(meta.config_keys),
        }
    return out


def validate_registered_rule_meta(context: str = "model") -> None:
    validate_rule_ids([rec.rule_id for rec in _REGISTRY], context=context)


def event_rows_with_values(
    val: Any,
    *,
    solution_id: str,
    snapshot_id: str,
    include_zero: bool = False,
) -> List[Dict[str, Any]]:
    """构建事实层 event_log 行。"""
    rows: List[Dict[str, Any]] = []
    for rec in _REGISTRY:
        try:
            count_val = float(val.Value(rec.var))
        except Exception:
            continue
        penalty = float(rec.weight) * count_val
        if not include_zero and count_val <= 0:
            continue
        rows.append(
            {
                "solution_id": solution_id,
                "snapshot_id": snapshot_id,
                "constraint_id": rec.rule_id,
                "constraint_name": rec.constraint_name or rec.rule_name,
                "constraint_category": rec.constraint_category,
                "mode": rec.mode,
                "teacher_name": rec.teacher or "GLOBAL",
                "day": rec.day or "",
                "period": rec.slot or "",
                "class_name": rec.cls or "",
                "subject": rec.subj or "",
                "penalty": penalty,
                "unit_penalty": float(rec.weight),
                "count_value": count_val,
                "weight_key": rec.weight_key,
                "rule_params": rec.rule_params,
                "source_module": rec.source_module,
                "description": rec.description or rec.rule_name,
            }
        )
    return rows


def summarize_event_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """按 rule_id + teacher 聚合罚分（统一快照与最终解摘要口径）。"""
    grouped: Dict[Tuple[str, str, str, float], Dict[str, Any]] = {}
    for row in rows:
        gk = (
            str(row.get("constraint_id", "")),
            str(row.get("constraint_name", "")),
            str(row.get("teacher_name", "GLOBAL")),
            float(row.get("unit_penalty", 0.0) or 0.0),
        )
        out = grouped.setdefault(
            gk,
            {
                "rule_id": gk[0],
                "rule_name": gk[1],
                "teacher": gk[2],
                "weight": gk[3],
                "count": 0.0,
                "penalty_sum": 0.0,
            },
        )
        out["count"] += float(row.get("count_value", 0.0) or 0.0)
        out["penalty_sum"] += float(row.get("penalty", 0.0) or 0.0)
    out_rows = list(grouped.values())
    out_rows.sort(key=lambda x: (x["rule_id"], x["teacher"]))
    return out_rows


def summarize_event_log_csv(path: Path) -> List[Dict[str, Any]]:
    """从 event_log.csv 读取并聚合软约束摘要。"""
    if not path.exists():
        return []
    rows: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append(
                {
                    "constraint_id": str(r.get("constraint_id", "")),
                    "constraint_name": str(r.get("constraint_name", "")),
                    "teacher_name": str(r.get("teacher_name", "GLOBAL")),
                    "unit_penalty": float(r.get("unit_penalty", 0.0) or 0.0),
                    "count_value": float(r.get("count_value", 0.0) or 0.0),
                    "penalty": float(r.get("penalty", 0.0) or 0.0),
                    "mode": str(r.get("mode", "")),
                }
            )
    return summarize_event_rows(rows)


def summarize_with_values(val: Any) -> List[Dict[str, Any]]:
    """兼容旧接口：按规则×教师聚合。"""
    rows = event_rows_with_values(val, solution_id="", snapshot_id="", include_zero=False)
    return summarize_event_rows(rows)


def write_event_log_csv(
    out_dir: Path,
    val: Any,
    *,
    solution_id: str,
    snapshot_id: str,
) -> Path:
    """导出 event_log.csv（事实层）。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "event_log.csv"
    rows = event_rows_with_values(val, solution_id=solution_id, snapshot_id=snapshot_id, include_zero=False)
    fields = [
        "solution_id",
        "snapshot_id",
        "constraint_id",
        "constraint_name",
        "constraint_category",
        "mode",
        "teacher_name",
        "day",
        "period",
        "class_name",
        "subject",
        "penalty",
        "unit_penalty",
        "count_value",
        "weight_key",
        "rule_params",
        "source_module",
        "description",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return path
