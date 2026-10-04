# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import csv
from pathlib import Path
from typing import Any

from scheduler.diagnostics.penalty_registry import summarize_event_log_csv


RULE_EXPLAIN_SCHEMA_VERSION = "scheduler.result_rule_explain.v1"


def empty_rule_explain(message: str = "当前结果没有可读的规则影响日志。") -> dict[str, Any]:
    return {
        "schema_version": RULE_EXPLAIN_SCHEMA_VERSION,
        "summary": {
            "status": "unavailable",
            "status_label": "暂无解释",
            "message": message,
            "total_penalty": 0,
            "rule_count": 0,
            "source": "",
            "source_label": "",
        },
        "top": [],
    }


def build_rule_explain(status: dict[str, Any], project_root: Path | None = None) -> dict[str, Any]:
    status = status if isinstance(status, dict) else {}
    root = project_root.resolve() if project_root is not None else None
    source = _preferred_event_log_path(status, root)
    if source is None:
        return empty_rule_explain("未发现当前最优课表对应的 event_log.csv；重新求解或重新打包后可展示规则影响解释。")

    try:
        summarized_rows = summarize_event_log_csv(source)
    except Exception as exc:
        return {
            **empty_rule_explain(f"event_log.csv 读取失败：{exc}"),
            "summary": {
                **empty_rule_explain()["summary"],
                "status": "error",
                "status_label": "解释失败",
                "message": f"event_log.csv 读取失败：{exc}",
                "source": str(source.resolve()),
                "source_label": _display_source_label(source, root),
            },
        }
    summarized_rows = _normalize_legacy_rollup_rows(summarized_rows)
    reconciliation = _objective_reconciliation(summarized_rows, status)
    event_examples = _event_examples_by_rule(source)
    grouped = _group_penalty_rows(summarized_rows, event_examples)
    total_penalty = float(reconciliation["total_penalty"])
    top = grouped[:8]
    if not top or total_penalty <= 0:
        return {
            "schema_version": RULE_EXPLAIN_SCHEMA_VERSION,
            "summary": {
                "status": "clean",
                "status_label": "规则影响低",
                "message": "当前 event_log 没有正向罚分记录，结果页暂未发现主导性的软约束代价。",
                "total_penalty": 0,
                "rule_count": 0,
                "source": str(source.resolve()),
                "source_label": _display_source_label(source, root),
                **reconciliation,
            },
            "top": [],
        }

    top = [
        {
            **item,
            "rank": index + 1,
            "share": round(float(item["penalty_sum"]) / total_penalty * 100, 1) if total_penalty else 0,
            "severity": _rule_severity(float(item["penalty_sum"]), total_penalty),
            "action": _rule_action(item),
        }
        for index, item in enumerate(top)
    ]
    leading = top[0]
    message = f"当前最优课表仍有 {total_penalty:g} 分正向软约束罚分，主因是 {leading.get('rule_name') or leading.get('rule_id')}。"
    reward_credit = float(reconciliation.get("reward_credit") or 0.0)
    if reward_credit > 0:
        message += f" 已记录奖励抵扣 {reward_credit:g} 分，净事件日志值 {float(reconciliation.get('net_event_penalty') or 0.0):g}。"
    return {
        "schema_version": RULE_EXPLAIN_SCHEMA_VERSION,
        "summary": {
            "status": "warning",
            "status_label": "存在规则代价",
            "message": message,
            "total_penalty": total_penalty,
            "rule_count": len(grouped),
            "source": str(source.resolve()),
            "source_label": _display_source_label(source, root),
            **reconciliation,
        },
        "top": top,
    }


def _preferred_event_log_path(status: dict[str, Any], root: Path | None) -> Path | None:
    files = status.get("files") if isinstance(status.get("files"), list) else []
    all_logs = _event_log_paths(files, root)
    paths: list[Path] = []
    best_meta = _best_solution_meta(status, root)
    for raw in _event_logs_from_best_meta(best_meta, root):
        _append_existing_path(paths, raw, root)

    seq_id = _meta_seq_id(best_meta)
    if seq_id is not None:
        seq_token = f"sol_{seq_id:04d}"
        snapshot_token = f"seq{seq_id:04d}"
        for path in all_logs:
            text = str(path).replace("\\", "/")
            if seq_token in text or snapshot_token in text:
                _append_existing_path(paths, path, root)

    for path in all_logs:
        _append_existing_path(paths, path, root)
    for path in _scan_run_event_logs(status, root):
        _append_existing_path(paths, path, root)
    return paths[0] if paths else None


def _event_log_paths(files: list[Any], root: Path | None) -> list[Path]:
    paths: list[Path] = []
    for file in files:
        if not isinstance(file, dict):
            continue
        label = str(file.get("label") or file.get("path") or "").replace("\\", "/")
        if not label.endswith("event_log.csv"):
            continue
        _append_existing_path(paths, file.get("path"), root)
    return paths


def _best_solution_meta(status: dict[str, Any], root: Path | None) -> dict[str, Any]:
    files = status.get("files") if isinstance(status.get("files"), list) else []
    candidates: list[tuple[int, Path]] = []
    for file in files:
        if not isinstance(file, dict):
            continue
        label = str(file.get("label") or file.get("path") or "").replace("\\", "/")
        if not label.endswith("最终全局最优解_meta.json"):
            continue
        path = _safe_existing_file(file.get("path"), root)
        if path is None:
            continue
        score = 0 if "/best/" in label else 10
        candidates.append((score, path))

    run_dir = _safe_existing_dir(status.get("run_dir"), root)
    if run_dir is not None:
        for path in run_dir.rglob("最终全局最优解_meta.json"):
            if not path.is_file():
                continue
            text = str(path).replace("\\", "/")
            score = 0 if "/best/" in text else 10
            candidates.append((score, path))

    seen: set[str] = set()
    unique: list[tuple[int, Path]] = []
    for score, path in candidates:
        key = str(path.resolve())
        if key in seen:
            continue
        seen.add(key)
        unique.append((score, path))

    for _, path in sorted(unique, key=lambda item: (item[0], str(item[1]))):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(data, dict):
            return data
    return {}


def _event_logs_from_best_meta(meta: dict[str, Any], root: Path | None) -> list[Path]:
    paths: list[Path] = []
    if not isinstance(meta, dict) or not meta:
        return paths
    _append_existing_path(paths, meta.get("event_log_file"), root)
    source_solution = str(meta.get("source_solution_file") or "").strip()
    if source_solution:
        _append_existing_path(paths, Path(source_solution).with_name("event_log.csv"), root)
    return paths


def _scan_run_event_logs(status: dict[str, Any], root: Path | None) -> list[Path]:
    run_dir = _safe_existing_dir(status.get("run_dir"), root)
    if run_dir is None:
        return []
    return sorted(
        (path for path in run_dir.rglob("event_log.csv") if path.is_file()),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )


def _append_existing_path(paths: list[Path], raw: Any, root: Path | None) -> None:
    path = _safe_existing_file(raw, root)
    if path is None:
        return
    key = str(path.resolve())
    if all(str(existing.resolve()) != key for existing in paths):
        paths.append(path)


def _safe_existing_file(raw: Any, root: Path | None) -> Path | None:
    path = _coerce_path(raw, root)
    if path is None or not path.exists() or not path.is_file():
        return None
    target = path.resolve()
    if root is not None and target != root and root not in target.parents:
        return None
    return target


def _safe_existing_dir(raw: Any, root: Path | None) -> Path | None:
    path = _coerce_path(raw, root)
    if path is None or not path.exists() or not path.is_dir():
        return None
    target = path.resolve()
    if root is not None and target != root and root not in target.parents:
        return None
    return target


def _coerce_path(raw: Any, root: Path | None) -> Path | None:
    text = str(raw or "").strip()
    if not text:
        return None
    path = Path(text)
    if not path.is_absolute() and root is not None:
        path = root / path
    return path


def _meta_seq_id(meta: dict[str, Any]) -> int | None:
    if not isinstance(meta, dict):
        return None
    value = meta.get("seq_id")
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _group_penalty_rows(
    rows: list[dict[str, Any]],
    event_examples: dict[str, list[dict[str, Any]]] | None = None,
) -> list[dict[str, Any]]:
    event_examples = event_examples or {}
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        rule_id = str(row.get("rule_id") or "UNKNOWN")
        rule_name = str(row.get("rule_name") or rule_id)
        teacher = str(row.get("teacher") or "GLOBAL")
        penalty_sum = float(row.get("penalty_sum", 0.0) or 0.0)
        count_value = float(row.get("count", 0.0) or 0.0)
        slot = grouped.setdefault(
            (rule_id, rule_name),
            {
                "rule_id": rule_id,
                "rule_name": rule_name,
                "penalty_sum": 0.0,
                "count": 0.0,
                "top_offenders": {},
            },
        )
        slot["penalty_sum"] += penalty_sum
        slot["count"] += count_value
        offenders: dict[str, float] = slot["top_offenders"]
        offenders[teacher] = offenders.get(teacher, 0.0) + penalty_sum

    out: list[dict[str, Any]] = []
    for values in grouped.values():
        penalty_sum = round(float(values["penalty_sum"]), 2)
        if penalty_sum <= 0:
            continue
        offenders = [
            {"entity": entity, "penalty_sum": round(score, 2)}
            for entity, score in sorted(
                values["top_offenders"].items(),
                key=lambda item: item[1],
                reverse=True,
            )
            if score > 0
        ][:4]
        out.append(
            {
                "rule_id": values["rule_id"],
                "rule_name": values["rule_name"],
                "penalty_sum": penalty_sum,
                "count": round(float(values["count"]), 2),
                "top_offenders": offenders,
                "example_events": event_examples.get(str(values["rule_id"]) or "", [])[:6],
                "potential_penalty_reduction": penalty_sum,
            }
        )
    return sorted(out, key=lambda item: (-float(item["penalty_sum"]), str(item["rule_id"])))


def _event_examples_by_rule(source: Path) -> dict[str, list[dict[str, Any]]]:
    examples: dict[str, list[dict[str, Any]]] = {}
    try:
        with source.open("r", encoding="utf-8-sig", newline="") as fh:
            for row in csv.DictReader(fh):
                rule_id = str(row.get("constraint_id") or "").strip()
                penalty = _float_or_none(row.get("penalty")) or 0.0
                if not rule_id or penalty <= 0:
                    continue
                item = {
                    "teacher": str(row.get("teacher_name") or "GLOBAL"),
                    "day": str(row.get("day") or ""),
                    "period": str(row.get("period") or ""),
                    "class_name": str(row.get("class_name") or ""),
                    "subject": str(row.get("subject") or ""),
                    "penalty": round(penalty, 2),
                    "unit_penalty": round(_float_or_none(row.get("unit_penalty")) or 0.0, 2),
                    "count": round(_float_or_none(row.get("count_value")) or 0.0, 2),
                    "description": str(row.get("description") or ""),
                }
                examples.setdefault(rule_id, []).append(item)
    except OSError:
        return {}

    for rows in examples.values():
        rows.sort(
            key=lambda item: (
                -float(item.get("penalty") or 0),
                str(item.get("teacher") or ""),
                str(item.get("day") or ""),
                str(item.get("period") or ""),
            )
        )
        del rows[6:]
    return examples


def _normalize_legacy_rollup_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    has_multi_detail = any(
        str(row.get("rule_id") or "") in {"multi_class_halfday_split", "multi_class_halfday_cross"}
        for row in rows
    )
    excluded = {"head_duty_pm1_trigger"}
    if has_multi_detail:
        excluded.add("multi_class_halfday")
    return [row for row in rows if str(row.get("rule_id") or "") not in excluded]


def _objective_reconciliation(rows: list[dict[str, Any]], status: dict[str, Any]) -> dict[str, Any]:
    positive = 0.0
    negative = 0.0
    for row in rows:
        value = float(row.get("penalty_sum", 0.0) or 0.0)
        if value >= 0:
            positive += value
        else:
            negative += value
    net = positive + negative
    solver_objective = _float_or_none(status.get("objective_value", status.get("best_objective")))
    delta = None
    reconciliation_status = "unavailable"
    if solver_objective is not None:
        delta = round(float(solver_objective) - net, 2)
        reconciliation_status = "matched" if abs(delta) <= 1e-6 else "unmatched"
    return {
        "total_penalty": round(positive, 2),
        "reward_credit": round(abs(negative), 2),
        "net_event_penalty": round(net, 2),
        "solver_objective_value": round(float(solver_objective), 2) if solver_objective is not None else None,
        "objective_explain_delta": delta,
        "objective_reconciliation_status": reconciliation_status,
    }


def _float_or_none(value: Any) -> float | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _rule_severity(penalty_sum: float, total_penalty: float) -> str:
    share = penalty_sum / total_penalty if total_penalty else 0
    if share >= 0.5 or penalty_sum >= 100:
        return "warning"
    if share >= 0.25 or penalty_sum >= 30:
        return "notice"
    return "info"


def _rule_action(item: dict[str, Any]) -> str:
    text = f"{item.get('rule_id') or ''} {item.get('rule_name') or ''}".lower()
    if "checkin" in text or "查寝" in text or "晚查" in text:
        return "按人力供给问题处理：优先补充同日可用候选，或在晚自习表中改派已有候选后重新求解。"
    if "continu" in text or "gap" in text or "连续" in text or "空档" in text:
        return "优先进入课表微调沙盘，尝试拆开连续课或半天空档，并检查涉及教师的调整后课表。"
    if "halfday" in text or "半天" in text or "multi_class" in text:
        return "核对多班教师同半天偏好是否过强；若影响有限，可保留为统计提示，否则调低权重后重跑。"
    if "day_night" in text:
        return "优先核对白天-晚自习联动规则和候选池；若是可接受例外，记录为排课风险，否则调整候选、固定课位或权重后重跑。"
    if "night" in text or "晚自习" in text or "晚间" in text:
        return "优先核对晚自习规则和候选池；若是可接受例外，记录为排课风险，否则调整候选或权重后重跑。"
    if "pm" in text or "下午" in text or "上午" in text or "lang_" in text:
        return "核对该学科在对应星期和节次的偏好是否过强；若只是排课偏好，可调低权重，否则回到固定课位或学科分布规则调整后重跑。"
    return "先核对该规则的配置、权重和涉及对象；必要时用微调沙盘验证局部调整，再决定是否重跑。"


def _display_source_label(path: Path, root: Path | None) -> str:
    if root is not None:
        try:
            return str(path.resolve().relative_to(root)).replace("\\", "/")
        except ValueError:
            pass
    return path.name
