# -*- coding: utf-8 -*-
from __future__ import annotations

import copy
import hashlib
import json
import uuid
from datetime import datetime, timezone
from io import BytesIO, StringIO
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from scheduler.app.academic_affairs import ACADEMIC_TABLES, normalize_academic_affairs, summarize_academic_affairs
from scheduler.app.business_rules import build_business_rule_domains, build_business_rule_groups
from scheduler.config.loader import load_effective_config
from scheduler.output.excel_writer import create_excel_writer
from scheduler.data.day_rules_reader import (
    ALL_DAYS,
    SHEET_FIXED,
    SHEET_HOURS,
    SHEET_OVERRIDES,
    SHEET_SUBJECT_BANS,
    SHEET_TIME_GRID,
)
from scheduler.domain.profile_catalog import profile_catalog_payload, validate_profile_catalog
from scheduler.platform.runtime import (
    load_runtime_workspace,
    save_runtime_workspace,
    uses_sqlite_workspace,
)
from scheduler.app.school_problem_preview import build_school_problem_preview_payload
from scheduler.rules import build_default_rule_registry, dump_effective_rules
from scheduler.app.rule_display import localize_rule


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = PROJECT_ROOT / "scheduler" / "config"
IO_PATH = CONFIG_DIR / "io.yaml"
RULES_PATH = CONFIG_DIR / "rules.yaml"
WEB_OVERRIDES_PATH = CONFIG_DIR / "web_overrides.yaml"
PROFILES_ROOT = PROJECT_ROOT / "profiles"
CHANGE_AUDIT_KEY = "change_audit"
MAX_CHANGE_AUDIT_ENTRIES = 80
DAY_RULE_TABLE_LABELS = {
    "time_grid": "时间格子",
    "fixed_slots": "固定课位",
    "subject_hours": "学科课时",
    "subject_bans": "学科禁排",
    "class_overrides": "班级差异",
}

# The teacher-positioning table is intentionally open-ended: every user-provided
# course header is a potential subject. Only generic annotation columns are
# excluded from the course schema; this must not become a school subject list.
_TEACHER_TABLE_AUXILIARY_HEADERS = {
    "备注",
    "备注信息",
    "说明",
    "说明信息",
    "注释",
    "comment",
    "comments",
    "description",
    "note",
    "notes",
    "remark",
    "remarks",
}


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        return {}
    return data


def _write_yaml(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def _deep_merge(base: Any, override: Any) -> Any:
    if isinstance(base, dict) and isinstance(override, dict):
        out = dict(base)
        for key, value in override.items():
            out[key] = _deep_merge(out.get(key), value) if key in out else copy.deepcopy(value)
        return out
    return copy.deepcopy(override)


def _resolve_project_path(raw_path: str | None) -> Path | None:
    if not raw_path:
        return None
    path = Path(str(raw_path))
    if path.is_absolute():
        return path
    return (PROJECT_ROOT / "scheduler" / path).resolve()


def load_web_overrides() -> dict[str, Any]:
    workspace = load_runtime_workspace() if uses_sqlite_workspace() else None
    raw = workspace.payload if workspace is not None else _load_yaml(WEB_OVERRIDES_PATH)
    result = {
        "io": raw.get("io") if isinstance(raw.get("io"), dict) else {},
        "rules": raw.get("rules") if isinstance(raw.get("rules"), dict) else {},
        "temporary_rules": raw.get("temporary_rules") if isinstance(raw.get("temporary_rules"), dict) else {"active": []},
        "academic_affairs": normalize_academic_affairs(raw.get("academic_affairs") if isinstance(raw, dict) else None),
        CHANGE_AUDIT_KEY: _normalize_change_audit(raw.get(CHANGE_AUDIT_KEY) if isinstance(raw, dict) else None),
    }
    if uses_sqlite_workspace():
        result["_meta"] = {
            "backend": "sqlite",
            "organization_id": workspace.organization_id if workspace is not None else "",
            "revision": workspace.revision if workspace is not None else 0,
            "updated_by": workspace.updated_by if workspace is not None else "",
            "updated_at": workspace.updated_at if workspace is not None else "",
        }
    return result


def save_web_overrides(
    payload: dict[str, Any],
    *,
    actor_user_id: str = "",
    reason: str = "",
) -> dict[str, Any]:
    current = load_web_overrides()
    next_payload = {
        "io": payload.get("io", current.get("io", {})) if isinstance(payload.get("io", current.get("io", {})), dict) else {},
        "rules": payload.get("rules", current.get("rules", {})) if isinstance(payload.get("rules", current.get("rules", {})), dict) else {},
        "temporary_rules": payload.get("temporary_rules", current.get("temporary_rules", {"active": []})),
        "academic_affairs": normalize_academic_affairs(payload.get("academic_affairs", current.get("academic_affairs"))),
        CHANGE_AUDIT_KEY: _normalize_change_audit(payload.get(CHANGE_AUDIT_KEY, current.get(CHANGE_AUDIT_KEY))),
    }
    if not isinstance(next_payload["temporary_rules"], dict):
        next_payload["temporary_rules"] = {"active": []}
    if uses_sqlite_workspace():
        meta = payload.get("_meta") if isinstance(payload.get("_meta"), dict) else {}
        current_meta = current.get("_meta") if isinstance(current.get("_meta"), dict) else {}
        expected_revision = int(meta.get("revision", current_meta.get("revision", 0)) or 0)
        saved = save_runtime_workspace(
            next_payload,
            expected_revision=expected_revision,
            actor_user_id=actor_user_id,
            reason=reason,
        )
        next_payload["_meta"] = {
            "backend": "sqlite",
            "organization_id": saved.organization_id,
            "revision": saved.revision,
            "updated_by": saved.updated_by,
            "updated_at": saved.updated_at,
        }
    else:
        _write_yaml(WEB_OVERRIDES_PATH, next_payload)
    return next_payload


def load_academic_affairs_payload() -> dict[str, Any]:
    data = load_web_overrides().get("academic_affairs")
    normalized = normalize_academic_affairs(data if isinstance(data, dict) else None)
    return {
        "data": normalized,
        "summary": summarize_academic_affairs(normalized),
    }


def save_academic_affairs_payload(
    payload: dict[str, Any],
    *,
    actor: str = "web",
    source: str = "academic_affairs.save",
    reason: str = "",
) -> dict[str, Any]:
    overrides = load_web_overrides()
    before = normalize_academic_affairs(overrides.get("academic_affairs"))
    after = normalize_academic_affairs(payload.get("academic_affairs", payload))
    overrides["academic_affairs"] = after
    changes = _build_academic_affairs_changes(before, after)
    if changes:
        _prepend_change_audit_entry(
            overrides,
            actor=actor,
            source=source,
            reason=reason,
            changes=changes,
        )
    return save_web_overrides(overrides, actor_user_id=actor, reason=reason or source)


def preview_academic_affairs_payload(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_academic_affairs(payload.get("academic_affairs", payload))
    return {
        "data": normalized,
        "summary": summarize_academic_affairs(normalized),
        "persisted": False,
    }


def load_effective_payload(mode: str = "joint") -> dict[str, Any]:
    effective = load_effective_config(
        mode,
        {"io_path": IO_PATH, "rules_path": RULES_PATH},
    )
    registry = build_default_rule_registry()
    rule_rows = dump_effective_rules(registry, effective.effective_cfg, mode=mode, only_enabled=False)
    business_groups = build_business_rule_groups(effective.effective_cfg)
    return {
        "mode": effective.mode,
        "paths": {
            "io": str(effective.io_path.resolve()),
            "rules": str(effective.rules_path.resolve()),
            "web_overrides": str(WEB_OVERRIDES_PATH.resolve()),
        },
        "io": effective.io_cfg,
        "rules": effective.rules_cfg,
        "effective": effective.effective_cfg,
        "overrides": load_web_overrides(),
        "rule_catalog": [localize_rule(row) for row in rule_rows],
        "business_rule_groups": business_groups,
        "business_rule_domains": build_business_rule_domains(effective.effective_cfg, business_groups),
        "config_diff": effective.config_diff_text,
    }


def load_profile_catalog_payload(mode: str = "joint") -> dict[str, Any]:
    """Return a Web-facing cross-school profile validation snapshot.

    This is a product visibility layer only. It validates persisted school
    profiles against the current effective config, but does not enable, disable,
    or execute solver constraints.
    """
    effective = load_effective_config(
        mode,
        {"io_path": IO_PATH, "rules_path": RULES_PATH},
    )
    report = validate_profile_catalog(PROFILES_ROOT, effective.effective_cfg, mode=effective.mode)
    payload = profile_catalog_payload(report)
    payload.update(
        {
            "schema_version": "scheduler.profile_catalog.web.v1",
            "source": "profile_catalog",
            "mode": effective.mode,
            "paths": {
                "profiles_root": str(PROFILES_ROOT.resolve()),
                "io": str(effective.io_path.resolve()),
                "rules": str(effective.rules_path.resolve()),
            },
            "contract": {
                "scope": "cross_school_profile_validation",
                "solver_effect": "none",
                "can_block_solver": False,
            },
        }
    )
    return payload


def load_school_problem_preview_payload(mode: str = "joint") -> dict[str, Any]:
    """Return a read-only preview of the current inputs as a SchoolProblem."""
    effective = load_effective_config(
        mode,
        {"io_path": IO_PATH, "rules_path": RULES_PATH},
    )
    return build_school_problem_preview_payload(
        mode=effective.mode,
        effective_cfg=effective.effective_cfg,
        io_cfg=effective.io_cfg,
        io_path=effective.io_path,
        registry=build_default_rule_registry(),
        source="web_preview",
    )


def build_effective_config_fingerprint(mode: str = "joint") -> dict[str, Any]:
    """Return a stable fingerprint for the business config that drives solving."""
    effective = load_effective_config(
        mode,
        {"io_path": IO_PATH, "rules_path": RULES_PATH},
    )
    canonical = json.dumps(
        effective.effective_cfg,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return {
        "mode": effective.mode,
        "hash": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def list_teacher_subject_rows() -> list[dict[str, Any]]:
    effective = load_effective_config("joint", {"io_path": IO_PATH, "rules_path": RULES_PATH})
    web_rows = (((effective.io_cfg.get("web_tables", {}) or {}).get("teacher_subjects")) or [])
    if isinstance(web_rows, list) and web_rows:
        return [dict(row, row_index=int(idx)) for idx, row in enumerate(web_rows) if isinstance(row, dict)]
    tt_cfg = effective.io_cfg.get("teacher_table", {}) or {}
    path = _resolve_project_path(tt_cfg.get("path"))
    if path is None or not path.exists():
        return []
    sheet = tt_cfg.get("sheet_name", 0)
    df = pd.read_excel(path, sheet_name=sheet)
    rows = []
    for idx, row in df.fillna("").iterrows():
        item = {"row_index": int(idx)}
        for col in df.columns:
            item[str(col)] = str(row.get(col, "")).strip()
        rows.append(item)
    return rows


def save_teacher_subject_rows(
    rows: list[dict[str, Any]],
    *,
    actor: str = "web",
    source: str = "base_data.teacher_subjects.save",
    reason: str = "",
    _overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    overrides = _overrides if _overrides is not None else load_web_overrides()
    io_override = overrides.setdefault("io", {})
    if not isinstance(io_override, dict):
        io_override = {}
        overrides["io"] = io_override
    web_tables = io_override.setdefault("web_tables", {})
    before_exists = isinstance(web_tables.get("teacher_subjects"), list)
    before_rows = copy.deepcopy(web_tables.get("teacher_subjects") if before_exists else [])
    after_rows = _clean_rows(rows)
    web_tables["teacher_subjects"] = after_rows
    change = _build_table_rows_change(
        "教师定位表",
        store="io",
        path=["web_tables", "teacher_subjects"],
        before_exists=before_exists,
        before_rows=before_rows,
        after_rows=after_rows,
    )
    if change:
        _prepend_change_audit_entry(
            overrides,
            actor=actor,
            source=source,
            reason=reason,
            changes=[change],
        )
    if _overrides is not None:
        return overrides
    return save_web_overrides(overrides, actor_user_id=actor, reason=reason or source)


def _teacher_subject_template_shape() -> tuple[list[str], dict[str, str]]:
    rows = list_teacher_subject_rows()
    if rows:
        columns = [key for key in rows[0].keys() if key != "row_index"]
    else:
        # 空项目模板只保留结构列；如果已有学科课时表，则从用户/租户数据补齐学科列。
        metadata = ["班级", "班主任", "班主任性别"]
        subject_names = []
        for row in (load_day_rule_tables().get("subject_hours") or []):
            subject = str(row.get("学科") or "").strip()
            if subject and subject not in subject_names:
                subject_names.append(subject)
        # A blank workspace still needs an explicit subject column so the
        # downloadable template can be parsed back as a safe import preview.
        columns = metadata + (subject_names or ["示例学科（请改名）"])
        effective = load_effective_config("joint", {"io_path": IO_PATH, "rules_path": RULES_PATH})
        duty_cfg = ((effective.io_cfg.get("day", {}) or {}).get("head_duty_constraints", {}) or {})
        floor_col = str(duty_cfg.get("teacher_floor_column") or "").strip()
        if floor_col and floor_col not in columns:
            columns.insert(3, floor_col)
    sample = {col: "" for col in columns}
    if "班级" in sample:
        sample["班级"] = "1班"
    if "班主任性别" in sample:
        sample["班主任性别"] = "男/女"
    return columns, sample


def build_teacher_subject_template() -> bytes:
    columns, sample = _teacher_subject_template_shape()
    buffer = BytesIO()
    with create_excel_writer(buffer) as writer:
        pd.DataFrame([sample], columns=columns).to_excel(writer, index=False, sheet_name="教师定位表")
    return buffer.getvalue()


def build_teacher_subject_template_csv() -> bytes:
    columns, sample = _teacher_subject_template_shape()
    text = pd.DataFrame([sample], columns=columns).to_csv(index=False)
    return ("\ufeff" + text).encode("utf-8")


def parse_teacher_subject_excel(content: bytes, sheet_name: int | str = 0) -> list[dict[str, Any]]:
    return parse_teacher_subject_xlsx(content, sheet_name=sheet_name)["rows"]


def parse_teacher_subject_xlsx(content: bytes, sheet_name: int | str = 0) -> dict[str, Any]:
    if not content:
        raise ValueError("上传的 Excel 文件为空")
    df = pd.read_excel(BytesIO(content), sheet_name=sheet_name)
    return _parse_teacher_subject_frame(df)


def parse_teacher_subject_csv(csv_text: str) -> dict[str, Any]:
    if not str(csv_text or "").strip():
        raise ValueError("上传的 CSV 文件为空")
    df = pd.read_csv(StringIO(csv_text))
    return _parse_teacher_subject_frame(df)


def _parse_teacher_subject_frame(df: pd.DataFrame) -> dict[str, Any]:
    actual_columns = [str(col).strip().lstrip("\ufeff") for col in df.columns if str(col).strip()]
    aliases = {"班": "班级", "班号": "班级", "class": "班级", "class_name": "班级"}
    class_col = "班级" if "班级" in actual_columns else next(
        (col for col in actual_columns if col.lower() in aliases), ""
    )
    if not class_col:
        raise ValueError("教师定位表至少需要班级列")
    frame = df.copy()
    rename = {class_col: "班级"} if class_col != "班级" else {}
    frame.columns = [
        rename.get(str(col).strip().lstrip("\ufeff"), str(col).strip().lstrip("\ufeff"))
        for col in df.columns
    ]
    actual_columns = [str(col).strip() for col in frame.columns if str(col).strip()]
    structural = {"班级", "班主任", "班主任性别", "row_index"}
    ignored_columns = [
        col
        for col in actual_columns
        if col not in structural
        and col.casefold() in _TEACHER_TABLE_AUXILIARY_HEADERS
    ]
    subject_columns = [
        col for col in actual_columns if col not in structural and col not in ignored_columns
    ]
    if not subject_columns:
        raise ValueError("教师定位表至少需要一列实际学科/任课教师列")
    rows: list[dict[str, Any]] = []
    for idx, row in frame.fillna("").iterrows():
        item = {"row_index": int(idx)}
        for col in actual_columns:
            item[col] = str(row.get(col, "")).strip()
        if any(str(v).strip() for key, v in item.items() if key != "row_index"):
            rows.append(item)
    return {
        "schema_version": "scheduler.teacher_subject_import.v1",
        "table": "teacher_subjects",
        "label": "教师定位表",
        "rows": rows,
        "row_count": len(rows),
        # Keep ignored fields in each preview row for safe user inspection; the
        # list only describes which headers are outside the course schema.
        "ignored_columns": ignored_columns,
        "persisted": False,
        "message": f"已解析 {len(rows)} 行，请核对后保存教师定位表。",
    }


def _sheet_rows(path: Path, sheet_name: str) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        df = pd.read_excel(path, sheet_name=sheet_name)
    except Exception:
        return []
    rows: list[dict[str, Any]] = []
    for idx, row in df.fillna("").iterrows():
        item = {"row_index": int(idx)}
        for col in df.columns:
            value = row.get(col, "")
            item[str(col)] = value.item() if hasattr(value, "item") else value
        rows.append(item)
    return rows


def load_day_rule_tables() -> dict[str, list[dict[str, Any]]]:
    effective = load_effective_config("joint", {"io_path": IO_PATH, "rules_path": RULES_PATH})
    day_cfg = effective.io_cfg.get("day", {}) or {}
    path = _resolve_project_path(day_cfg.get("rules_path"))
    if path is None:
        return {}
    tables = {
        "time_grid": _sheet_rows(path, SHEET_TIME_GRID),
        "fixed_slots": _sheet_rows(path, SHEET_FIXED),
        "subject_hours": _sheet_rows(path, SHEET_HOURS),
        "subject_bans": _sheet_rows(path, SHEET_SUBJECT_BANS),
        "class_overrides": _sheet_rows(path, SHEET_OVERRIDES),
        "days": [{"day": day} for day in ALL_DAYS],
    }
    web_day_rules = (((effective.io_cfg.get("web_tables", {}) or {}).get("day_rules")) or {})
    if isinstance(web_day_rules, dict):
        for key in ("time_grid", "fixed_slots", "subject_hours", "subject_bans", "class_overrides"):
            rows = _clean_rows(web_day_rules.get(key, []))
            if rows:
                tables[key] = rows
    return tables


def save_day_rule_table(
    table_key: str,
    rows: list[dict[str, Any]],
    *,
    actor: str = "web",
    source: str = "base_data.day_rules.save",
    reason: str = "",
    _overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    valid = {"time_grid", "fixed_slots", "subject_hours", "subject_bans", "class_overrides"}
    if table_key not in valid:
        raise ValueError(f"unknown day rule table: {table_key}")
    overrides = _overrides if _overrides is not None else load_web_overrides()
    io_override = overrides.setdefault("io", {})
    if not isinstance(io_override, dict):
        io_override = {}
        overrides["io"] = io_override
    web_tables = io_override.setdefault("web_tables", {})
    day_rules = web_tables.setdefault("day_rules", {})
    before_exists = isinstance(day_rules.get(table_key), list)
    before_rows = copy.deepcopy(day_rules.get(table_key) if before_exists else [])
    after_rows = _clean_rows(rows)
    day_rules[table_key] = after_rows
    change = _build_table_rows_change(
        f"白天规则表：{DAY_RULE_TABLE_LABELS.get(table_key, table_key)}",
        store="io",
        path=["web_tables", "day_rules", table_key],
        before_exists=before_exists,
        before_rows=before_rows,
        after_rows=after_rows,
    )
    if change:
        _prepend_change_audit_entry(
            overrides,
            actor=actor,
            source=source,
            reason=reason,
            changes=[change],
        )
    if _overrides is not None:
        return overrides
    return save_web_overrides(overrides, actor_user_id=actor, reason=reason or source)


def build_day_rule_table_template_csv(table_key: str) -> bytes:
    table_key = _validate_day_rule_import_table(table_key)
    columns, sample = _day_rule_table_template_shape(table_key)
    return pd.DataFrame([sample], columns=columns).to_csv(index=False, lineterminator="\n").encode("utf-8-sig")


def build_day_rule_table_template_xlsx(table_key: str) -> bytes:
    table_key = _validate_day_rule_import_table(table_key)
    columns, sample = _day_rule_table_template_shape(table_key)
    label = DAY_RULE_TABLE_LABELS.get(table_key, table_key)
    buffer = BytesIO()
    with create_excel_writer(buffer) as writer:
        pd.DataFrame([sample], columns=columns).to_excel(writer, index=False, sheet_name=label[:31])
    return buffer.getvalue()


def parse_day_rule_table_csv(table_key: str, csv_text: str) -> dict[str, Any]:
    if not str(csv_text or "").strip():
        raise ValueError("上传的 CSV 文件为空")
    df = pd.read_csv(BytesIO(str(csv_text).encode("utf-8-sig"))).fillna("")
    return _parse_day_rule_table_frame(table_key, df)


def parse_day_rule_table_xlsx(table_key: str, content: bytes) -> dict[str, Any]:
    if not content:
        raise ValueError("上传的 Excel 文件为空")
    df = pd.read_excel(BytesIO(content)).fillna("")
    return _parse_day_rule_table_frame(table_key, df)


def save_ai_rule_assistant(settings: dict[str, Any]) -> dict[str, Any]:
    overrides = load_web_overrides()
    rules_override = overrides.setdefault("rules", {})
    if not isinstance(rules_override, dict):
        rules_override = {}
        overrides["rules"] = rules_override
    providers_raw = settings.get("providers") if isinstance(settings.get("providers"), list) else []
    providers = [
        _sanitize_ai_provider(item)
        for item in providers_raw[:8]
        if isinstance(item, dict)
    ]
    rules_override["ai_rule_assistant"] = {
        "enabled": bool(settings.get("enabled", False)),
        "provider_name": str(settings.get("provider_name", "")).strip(),
        "base_url": str(settings.get("base_url", "")).strip(),
        "model": str(settings.get("model", "")).strip(),
        "api_key_env": str(settings.get("api_key_env", "")).strip(),
        "wire_api": str(settings.get("wire_api") or "chat_completions").strip(),
        "reasoning_effort": str(settings.get("reasoning_effort") or "").strip(),
        "response_format": str(settings.get("response_format") or "").strip().lower(),
        "disable_response_storage": settings.get("disable_response_storage", True) is not False,
        "timeout_seconds": _bounded_ai_number(settings.get("timeout_seconds", 30), 1, 120, 30),
        "max_completion_tokens": int(_bounded_ai_number(settings.get("max_completion_tokens", 2048), 128, 8192, 2048)),
        "input_price_microunits_per_million": int(_bounded_ai_number(settings.get("input_price_microunits_per_million", 0), 0, 10**12, 0)),
        "output_price_microunits_per_million": int(_bounded_ai_number(settings.get("output_price_microunits_per_million", 0), 0, 10**12, 0)),
        "providers": providers,
        "prompt_template": str(settings.get("prompt_template", "")).strip(),
    }
    return save_web_overrides(
        overrides,
        actor_user_id=str(settings.get("actor") or "web"),
        reason="ai provider settings updated",
    )


def _sanitize_ai_provider(value: dict[str, Any]) -> dict[str, Any]:
    return {
        "provider_name": str(value.get("provider_name") or value.get("provider_id") or "").strip()[:80],
        "base_url": str(value.get("base_url") or "").strip()[:500],
        "model": str(value.get("model") or "").strip()[:160],
        "api_key_env": str(value.get("api_key_env") or "").strip()[:120],
        "wire_api": str(value.get("wire_api") or "chat_completions").strip()[:40],
        "reasoning_effort": str(value.get("reasoning_effort") or "").strip()[:40],
        "response_format": str(value.get("response_format") or "").strip().lower()[:40],
        "disable_response_storage": value.get("disable_response_storage", True) is not False,
        "enabled": value.get("enabled", True) is not False,
        "priority": int(_bounded_ai_number(value.get("priority", 100), 0, 10_000, 100)),
        "timeout_seconds": _bounded_ai_number(value.get("timeout_seconds", 30), 1, 120, 30),
        "max_completion_tokens": int(_bounded_ai_number(value.get("max_completion_tokens", 2048), 128, 8192, 2048)),
        "input_price_microunits_per_million": int(_bounded_ai_number(value.get("input_price_microunits_per_million", 0), 0, 10**12, 0)),
        "output_price_microunits_per_million": int(_bounded_ai_number(value.get("output_price_microunits_per_million", 0), 0, 10**12, 0)),
        "circuit_failure_threshold": int(_bounded_ai_number(value.get("circuit_failure_threshold", 3), 1, 20, 3)),
        "circuit_cooldown_seconds": int(_bounded_ai_number(value.get("circuit_cooldown_seconds", 60), 1, 3600, 60)),
    }


def _bounded_ai_number(value: Any, minimum: float, maximum: float, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = float(default)
    return max(float(minimum), min(float(maximum), parsed))


def _validate_day_rule_import_table(table_key: str) -> str:
    key = str(table_key or "").strip()
    if key not in DAY_RULE_TABLE_LABELS:
        raise ValueError(f"unknown day rule table: {key}")
    return key


def _day_rule_table_template_shape(table_key: str) -> tuple[list[str], dict[str, Any]]:
    rows = _clean_rows(load_day_rule_tables().get(table_key, []))
    if rows:
        columns = [key for key in rows[0].keys() if str(key) != "row_index"]
        sample = {col: rows[0].get(col, "") for col in columns}
        return columns, sample
    columns = {
        "time_grid": ["时段节次", *ALL_DAYS],
        "fixed_slots": ["班级", "星期", "节次", "学科", "教师"],
        "subject_hours": ["班级", "语文", "数学", "外语"],
        "subject_bans": ["学科", "星期", "节次", "原因"],
        "class_overrides": ["班级", "字段", "值", "说明"],
    }.get(table_key, ["名称"])
    sample = {col: "" for col in columns}
    if table_key == "time_grid":
        sample["时段节次"] = "上午1"
        for day in ALL_DAYS:
            sample[day] = 1 if day in {"星期一", "星期二", "星期三", "星期四", "星期五"} else 0
    if "星期" in sample:
        sample["星期"] = "星期一"
    if "节次" in sample:
        sample["节次"] = "上午1"
    if "班级" in sample:
        sample["班级"] = "1班"
    return columns, sample


def _parse_day_rule_table_frame(table_key: str, df: pd.DataFrame) -> dict[str, Any]:
    key = _validate_day_rule_import_table(table_key)
    columns, _sample = _day_rule_table_template_shape(key)
    normalized_columns = {str(col).strip("\ufeff ").strip(): col for col in df.columns}
    missing = [col for col in columns if col not in normalized_columns]
    if missing:
        raise ValueError(f"{DAY_RULE_TABLE_LABELS.get(key, key)}导入缺少必需列：{', '.join(missing)}")
    ignored = [str(col).strip("\ufeff ").strip() for col in df.columns if str(col).strip("\ufeff ").strip() not in columns]
    rows: list[dict[str, Any]] = []
    for _idx, row in df.fillna("").iterrows():
        item: dict[str, Any] = {}
        for col in columns:
            raw_column = normalized_columns[col]
            value = row.get(raw_column, "")
            item[col] = value.item() if hasattr(value, "item") else str(value).strip()
        if any(str(value).strip() for value in item.values()):
            rows.append(item)
    label = DAY_RULE_TABLE_LABELS.get(key, key)
    return {
        "table": key,
        "label": label,
        "rows": rows,
        "row_count": len(rows),
        "ignored_columns": ignored,
        "persisted": False,
        "message": f"已解析 {len(rows)} 行，请核对后保存当前白天规则表。",
    }

def save_rule_field_updates(
    fields: list[dict[str, Any]],
    *,
    actor: str = "web",
    source: str = "rules.configure",
    reason: str = "",
) -> dict[str, Any]:
    overrides = load_web_overrides()
    changes = _apply_rule_field_updates(overrides, fields)
    if changes:
        _prepend_change_audit_entry(
            overrides,
            actor=actor,
            source=source,
            reason=reason,
            changes=changes,
        )
    return save_web_overrides(overrides, actor_user_id=actor, reason=reason or source)


def preview_rule_field_updates(fields: list[dict[str, Any]]) -> dict[str, Any]:
    overrides = copy.deepcopy(load_web_overrides())
    changes = _apply_rule_field_updates(overrides, fields)
    return {
        "persisted": False,
        "overrides": overrides,
        "changes": changes,
    }


def _apply_rule_field_updates(overrides: dict[str, Any], fields: list[dict[str, Any]]) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    for field in fields:
        if not isinstance(field, dict):
            continue
        path = _field_path(field.get("path"))
        if not path:
            continue
        store = _field_store(field.get("store"), path)
        root = overrides.setdefault(store, {})
        if not isinstance(root, dict):
            root = {}
            overrides[store] = root
        before_exists, before_value = _get_path_value(root, path)
        after_value = _coerce_field_value(field.get("value"), str(field.get("type") or "text"))
        _set_path_value(root, path, after_value)
        if before_exists and before_value == after_value:
            continue
        changes.append(
            {
                "label": str(field.get("label") or ".".join(path)),
                "store": store,
                "path": path,
                "full_path": f"{store}.{'.'.join(path)}",
                "before_exists": before_exists,
                "before": copy.deepcopy(before_value) if before_exists else None,
                "after": copy.deepcopy(after_value),
            }
        )
    return changes


def _build_table_rows_change(
    label: str,
    *,
    store: str,
    path: list[str],
    before_rows: list[dict[str, Any]],
    after_rows: list[dict[str, Any]],
    before_exists: bool = True,
) -> dict[str, Any] | None:
    if before_rows == after_rows:
        return None
    return {
        "label": label,
        "store": store,
        "path": path,
        "full_path": f"{store}.{'.'.join(path)}",
        "before_exists": bool(before_exists),
        "before": copy.deepcopy(before_rows),
        "after_exists": True,
        "after": copy.deepcopy(after_rows),
        "row_count_before": len(before_rows),
        "row_count_after": len(after_rows),
    }


def _build_academic_affairs_changes(before: dict[str, Any], after: dict[str, Any]) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    before_tables = before.get("tables") if isinstance(before.get("tables"), dict) else {}
    after_tables = after.get("tables") if isinstance(after.get("tables"), dict) else {}
    table_keys = list(dict.fromkeys([*ACADEMIC_TABLES.keys(), *before_tables.keys(), *after_tables.keys()]))
    for table_key in table_keys:
        before_rows = copy.deepcopy(before_tables.get(table_key) if isinstance(before_tables.get(table_key), list) else [])
        after_rows = copy.deepcopy(after_tables.get(table_key) if isinstance(after_tables.get(table_key), list) else [])
        if before_rows == after_rows:
            continue
        label = str((ACADEMIC_TABLES.get(table_key) or {}).get("label") or table_key)
        change = _build_table_rows_change(
            f"教务表：{label}",
            store="academic_affairs",
            path=["tables", str(table_key)],
            before_rows=before_rows,
            after_rows=after_rows,
        )
        if change:
            changes.append(change)

    before_settings = copy.deepcopy(before.get("settings") if isinstance(before.get("settings"), dict) else {})
    after_settings = copy.deepcopy(after.get("settings") if isinstance(after.get("settings"), dict) else {})
    if before_settings != after_settings:
        changes.append(
            {
                "label": "教务参数",
                "store": "academic_affairs",
                "path": ["settings"],
                "full_path": "academic_affairs.settings",
                "before_exists": True,
                "before": before_settings,
                "after_exists": True,
                "after": after_settings,
            }
        )
    return changes


def _normalize_change_audit(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {"entries": []}
    entries = raw.get("entries")
    if not isinstance(entries, list):
        return {"entries": []}
    return {"entries": [copy.deepcopy(item) for item in entries if isinstance(item, dict)][:MAX_CHANGE_AUDIT_ENTRIES]}


def _new_change_audit_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"cfg_{stamp}_{uuid.uuid4().hex[:8]}"


def _clean_audit_text(value: Any, fallback: str, max_len: int = 200) -> str:
    text = str(value or "").strip()
    if not text:
        text = fallback
    return text[:max_len]


def _prepend_change_audit_entry(
    overrides: dict[str, Any],
    *,
    actor: str,
    source: str,
    reason: str,
    changes: list[dict[str, Any]],
    rollback_of: str = "",
) -> dict[str, Any]:
    audit = _normalize_change_audit(overrides.get(CHANGE_AUDIT_KEY))
    entry = {
        "id": _new_change_audit_id(),
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "actor": _clean_audit_text(actor, "web", 80),
        "source": _clean_audit_text(source, "rules.configure", 120),
        "reason": _clean_audit_text(reason, "", 400),
        "changes": [copy.deepcopy(change) for change in changes],
    }
    if rollback_of:
        entry["rollback_of"] = str(rollback_of)
    audit["entries"] = [entry, *audit["entries"]][:MAX_CHANGE_AUDIT_ENTRIES]
    overrides[CHANGE_AUDIT_KEY] = audit
    return entry


def list_config_change_audit(limit: int = 30) -> dict[str, Any]:
    audit = load_web_overrides().get(CHANGE_AUDIT_KEY)
    normalized = _normalize_change_audit(audit)
    limit = max(1, min(int(limit or 30), MAX_CHANGE_AUDIT_ENTRIES))
    return {"entries": normalized["entries"][:limit]}


def rollback_config_change(
    entry_id: str,
    *,
    actor: str = "web",
    source: str = "config.rollback",
    reason: str = "",
) -> dict[str, Any]:
    target_id = str(entry_id or "").strip()
    if not target_id:
        raise ValueError("entry_id is required")
    overrides = load_web_overrides()
    entries = _normalize_change_audit(overrides.get(CHANGE_AUDIT_KEY)).get("entries", [])
    target = next((entry for entry in entries if str(entry.get("id") or "") == target_id), None)
    if not target:
        raise ValueError(f"change audit entry not found: {target_id}")

    rollback_changes: list[dict[str, Any]] = []
    for change in target.get("changes", []) or []:
        if not isinstance(change, dict):
            continue
        store = _field_store(change.get("store"), _field_path(change.get("path")))
        path = _field_path(change.get("path"))
        if not path:
            continue
        root = overrides.setdefault(store, {})
        if not isinstance(root, dict):
            root = {}
            overrides[store] = root
        current_exists, current_value = _get_path_value(root, path)
        before_exists = bool(change.get("before_exists", True))
        restored_value = copy.deepcopy(change.get("before"))
        if before_exists:
            _set_path_value(root, path, restored_value)
            after_exists, after_value = True, restored_value
        else:
            _delete_path_value(root, path)
            after_exists, after_value = False, None
        rollback_change = {
            "label": str(change.get("label") or ".".join(path)),
            "store": store,
            "path": path,
            "full_path": f"{store}.{'.'.join(path)}",
            "before_exists": current_exists,
            "before": copy.deepcopy(current_value) if current_exists else None,
            "after_exists": after_exists,
            "after": copy.deepcopy(after_value) if after_exists else None,
        }
        if isinstance(rollback_change["before"], list) or isinstance(rollback_change["after"], list):
            rollback_change["row_count_before"] = len(rollback_change["before"]) if isinstance(rollback_change["before"], list) else 0
            rollback_change["row_count_after"] = len(rollback_change["after"]) if isinstance(rollback_change["after"], list) else 0
        rollback_changes.append(rollback_change)

    if not rollback_changes:
        raise ValueError(f"change audit entry has no rollbackable changes: {target_id}")
    _prepend_change_audit_entry(
        overrides,
        actor=actor,
        source=source,
        reason=reason or f"rollback {target_id}",
        changes=rollback_changes,
        rollback_of=target_id,
    )
    return save_web_overrides(overrides, actor_user_id=actor, reason=reason or source)


def _clean_rows(rows: Any) -> list[dict[str, Any]]:
    if not isinstance(rows, list):
        return []
    cleaned: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        item = {}
        for key, value in row.items():
            if str(key) == "row_index":
                continue
            item[str(key)] = value
        if any(str(v).strip() for v in item.values()):
            cleaned.append(item)
    return cleaned


def _field_path(raw: Any) -> list[str]:
    if isinstance(raw, list):
        return [str(part).strip() for part in raw if str(part).strip()]
    return [part for part in str(raw or "").split(".") if part]


def _field_store(raw_store: Any, path: list[str]) -> str:
    explicit = str(raw_store or "").strip()
    if explicit in {"io", "rules", "academic_affairs"}:
        return explicit
    return "io" if path and path[0] in {"teacher_table", "joint_solve", "warm_start", "pre_run_cleanup", "multi_solution_output", "snapshot_export", "day"} else "rules"


def _set_path_value(root: dict[str, Any], path: list[str], value: Any) -> None:
    cur: Any = root
    for part in path[:-1]:
        if not isinstance(cur.get(part), dict):
            cur[part] = {}
        cur = cur[part]
    cur[path[-1]] = value


def _get_path_value(root: dict[str, Any], path: list[str]) -> tuple[bool, Any]:
    cur: Any = root
    for part in path[:-1]:
        if not isinstance(cur, dict) or part not in cur:
            return False, None
        cur = cur[part]
    if not isinstance(cur, dict) or path[-1] not in cur:
        return False, None
    return True, copy.deepcopy(cur[path[-1]])


def _delete_path_value(root: dict[str, Any], path: list[str]) -> None:
    stack: list[tuple[dict[str, Any], str]] = []
    cur: Any = root
    for part in path[:-1]:
        if not isinstance(cur, dict) or not isinstance(cur.get(part), dict):
            return
        stack.append((cur, part))
        cur = cur[part]
    if isinstance(cur, dict):
        cur.pop(path[-1], None)
    for parent, key in reversed(stack):
        child = parent.get(key)
        if isinstance(child, dict) and not child:
            parent.pop(key, None)
        else:
            break


def _coerce_field_value(value: Any, field_type: str) -> Any:
    if field_type == "bool":
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in {"true", "1", "yes", "on", "启用", "是"}
    if field_type in {"int", "number"}:
        text = str(value).strip()
        if not text:
            return 0
        return int(float(text))
    if field_type in {"list", "teacher_list", "subject_group_list", "exception_list"}:
        if isinstance(value, list):
            return [str(x).strip() for x in value if str(x).strip()]
        return [part.strip() for part in str(value or "").replace("，", ",").replace("、", ",").replace("/", ",").split(",") if part.strip()]
    if field_type == "json":
        if isinstance(value, (dict, list, int, float, bool)) or value is None:
            return value
        return yaml.safe_load(str(value)) if str(value).strip() else None
    if field_type == "checkin_extra_heads":
        raw = value
        if not isinstance(raw, list):
            raw = yaml.safe_load(str(value)) if str(value).strip() else []
        if not isinstance(raw, list):
            return []
        out = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            gender = str(item.get("gender") or "").strip()
            if not name:
                continue
            if gender not in {"男", "女"}:
                gender = ""
            entry = {"name": name, "gender": gender}
            days = _coerce_day_list(item.get("days", item.get("day", item.get("available_days"))))
            if days:
                entry["days"] = days
            out.append(entry)
        return out
    if field_type == "mode":
        text = str(value or "").strip()
        if text in {"硬性要求", "硬约束", "hard"}:
            return "hard"
        if text in {"尽量满足", "软约束", "soft"}:
            return "soft"
        return text or "hard"
    if field_type in {"choice", "target_scope", "exception_mode"}:
        return str(value or "").strip()
    return str(value or "").strip()


def _coerce_day_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        raw = value
    else:
        raw = str(value).replace("，", ",").replace("、", ",").replace("/", ",").split(",")
    seen: dict[str, None] = {}
    for item in raw:
        day = str(item or "").strip()
        if day:
            seen.setdefault(day, None)
    return list(seen.keys())
