# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


READ_PERMISSION = "read"
ALL_PERMISSION = "*"


class PermissionDenied(PermissionError):
    """Raised when a Web role tries to use an operation outside its scope."""


@dataclass(frozen=True)
class RoleDefinition:
    key: str
    label: str
    description: str
    permissions: tuple[str, ...]


ROLE_DEFINITIONS: dict[str, RoleDefinition] = {
    "academic_admin": RoleDefinition(
        key="academic_admin",
        label="教务管理员",
        description="可维护基础数据、规则、教务表、求解和变更回退。",
        permissions=(ALL_PERMISSION,),
    ),
    "scheduler_operator": RoleDefinition(
        key="scheduler_operator",
        label="排课操作员",
        description="可维护排课配置、运行求解和局部调课。",
        permissions=("base_data.write", "rules.write", "config.write", "academic.write", "solve.run", "schedule.adjust", "schedule.publish", "model.use", "conversation.schedule"),
    ),
    "trial_operator": RoleDefinition(
        key="trial_operator",
        label="教务测试员",
        description="限时测试账号，可完整体验导入、规则建模、求解、调课和发布；不能管理账号、系统接口或额度。",
        permissions=("base_data.write", "rules.write", "academic.write", "solve.run", "schedule.adjust", "schedule.publish", "model.use", "conversation.schedule"),
    ),
    "grade_lead": RoleDefinition(
        key="grade_lead",
        label="年级组",
        description="可维护教务表和处理调代课，不能改核心规则。",
        permissions=("academic.write", "schedule.adjust"),
    ),
    "dorm_supervisor": RoleDefinition(
        key="dorm_supervisor",
        label="宿管/值周",
        description="可查看晚查寝、值周相关结果，不能改排课规则或启动求解。",
        permissions=(READ_PERMISSION,),
    ),
    "viewer": RoleDefinition(
        key="viewer",
        label="只读查看",
        description="可查看配置、课表、诊断和结果包，不能保存或启动任务。",
        permissions=(READ_PERMISSION,),
    ),
}


ROLE_ALIASES = {
    "admin": "academic_admin",
    "教务管理员": "academic_admin",
    "operator": "scheduler_operator",
    "排课操作员": "scheduler_operator",
    "trial": "trial_operator",
    "教务测试员": "trial_operator",
    "grade": "grade_lead",
    "年级组": "grade_lead",
    "dorm": "dorm_supervisor",
    "宿管": "dorm_supervisor",
    "viewer": "viewer",
    "readonly": "viewer",
    "只读": "viewer",
}


POST_PERMISSION_MAP: dict[str, str] = {
    "/api/config": "config.write",
    "/api/teacher-subjects": "base_data.write",
    "/api/teacher-subjects/import": "base_data.write",
    "/api/teacher-subjects/import-file": "base_data.write",
    "/api/day-rules": "base_data.write",
    "/api/day-rules/import-file": "base_data.write",
    "/api/ai-settings": "system.manage",
    "/api/ai-settings/test": "system.manage",
    "/api/rules/configure": "rules.write",
    "/api/config/audit/rollback": "rules.write",
    "/api/academic-affairs": "academic.write",
    "/api/academic-affairs/import-csv": "academic.write",
    "/api/academic-affairs/import-file": "academic.write",
    "/api/academic-affairs/import-workbook": "academic.write",
    "/api/academic-affairs/leave-repair/apply": "schedule.adjust",
    "/api/academic-affairs/timetable-adjustment/apply": "schedule.adjust",
    "/api/solve/start": "solve.run",
    "/api/solve/jobs": "solve.run",
    "/api/solve/pause": "solve.run",
    "/api/solve/stop": "solve.run",
    "/api/solve/relaxation/apply": "rules.write",
    "/api/solve/relaxation/remove": "rules.write",
    "/api/nl-rules/add": "rules.write",
    "/api/nl-rules/remove": "rules.write",
    "/api/nl-rules/parse": "model.use",
    "/api/rules/v2": "rules.write",
    "/api/rules/v2/activate": "rules.write",
    "/api/rules/v2/parse": "model.use",
    "/api/readiness/ai-review": "model.use",
    "/api/project/publish": "schedule.publish",
    "/api/project/settings": "base_data.write",
    "/api/model/quota": "billing.manage",
    "/api/conversation-scheduler/sessions": "conversation.schedule",
}


GET_PERMISSION_MAP: dict[str, str] = {
    "/api/model/usage": "billing.read",
    "/api/model/quota": "billing.read",
}


POST_READONLY_PATHS = {
    "/api/readiness/preview-remediation",
    "/api/academic-affairs/preview",
    "/api/academic-affairs/leave-repair/preview",
    "/api/academic-affairs/timetable-adjustment/preview",
}


def normalize_role_key(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return "academic_admin"
    return ROLE_ALIASES.get(text, text if text in ROLE_DEFINITIONS else "academic_admin")


def build_access_context(role: Any = None, academic_payload: dict[str, Any] | None = None) -> dict[str, Any]:
    role_key = normalize_role_key(role)
    role_def = ROLE_DEFINITIONS[role_key]
    permissions = list(role_def.permissions)
    return {
        "schema_version": "scheduler.access_context.v1",
        "role": {
            "key": role_def.key,
            "label": role_def.label,
            "description": role_def.description,
        },
        "roles": [
            {
                "key": item.key,
                "label": item.label,
                "description": item.description,
                "permissions": list(item.permissions),
            }
            for item in ROLE_DEFINITIONS.values()
        ],
        "permissions": permissions,
        "write_scopes": _write_scopes_for_permissions(permissions),
        "campus_scope": _campus_scope(academic_payload),
    }


def request_permission(method: str, path: str) -> str:
    normalized_path = str(path or "").split("?", 1)[0]
    if str(method or "").upper() in {"GET", "HEAD", "OPTIONS"}:
        return GET_PERMISSION_MAP.get(normalized_path, READ_PERMISSION)
    if normalized_path.startswith("/api/conversation-scheduler/sessions/"):
        return "conversation.schedule"
    if normalized_path.startswith("/api/solve/jobs/") and normalized_path.endswith("/cancel"):
        return "solve.run"
    if normalized_path in POST_READONLY_PATHS:
        return READ_PERMISSION
    return POST_PERMISSION_MAP.get(normalized_path, ALL_PERMISSION)


def assert_request_allowed(method: str, path: str, role: Any = None) -> None:
    permission = request_permission(method, path)
    if _has_permission(normalize_role_key(role), permission):
        return
    role_def = ROLE_DEFINITIONS[normalize_role_key(role)]
    raise PermissionDenied(f"{role_def.label}没有执行该操作的权限")


def _has_permission(role_key: str, permission: str) -> bool:
    role_def = ROLE_DEFINITIONS[normalize_role_key(role_key)]
    permissions = set(role_def.permissions)
    return ALL_PERMISSION in permissions or permission == READ_PERMISSION or permission in permissions


def _write_scopes_for_permissions(permissions: list[str]) -> list[dict[str, str]]:
    if ALL_PERMISSION in permissions:
        return [{"key": "all", "label": "全部写入权限"}]
    labels = {
        "base_data.write": "基础数据",
        "rules.write": "规则配置",
        "config.write": "高级排课配置",
        "academic.write": "教务表",
        "solve.run": "求解运行",
        "schedule.adjust": "课表微调",
        "schedule.publish": "课表发布",
        "conversation.schedule": "AI 对话排课",
    }
    return [{"key": key, "label": labels[key]} for key in labels if key in permissions]


def _campus_scope(academic_payload: dict[str, Any] | None) -> dict[str, Any]:
    data = academic_payload.get("data") if isinstance(academic_payload, dict) else academic_payload
    data = data if isinstance(data, dict) else {}
    settings = data.get("settings") if isinstance(data.get("settings"), dict) else {}
    explicit = _string_list(settings.get("campuses"))
    inferred = _infer_campuses(data.get("tables") if isinstance(data.get("tables"), dict) else {})
    campuses = _ordered_unique([*explicit, *inferred])
    return {
        "campuses": campuses,
        "campus_count": len(campuses),
        "mode": "multi_campus" if len(campuses) > 1 else "single_campus",
        "message": "已识别多校区范围。" if len(campuses) > 1 else "未配置多校区时按当前学校统一范围处理。",
    }


def _infer_campuses(tables: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for rows in tables.values():
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            for key in ("校区", "所属校区", "区域"):
                values.extend(_campus_tokens(row.get(key)))
    return values


def _campus_tokens(value: Any) -> list[str]:
    text = str(value or "").strip()
    if not text:
        return []
    parts = [part.strip() for part in text.replace("，", "/").replace("、", "/").split("/") if part.strip()]
    return [part for part in parts if "校区" in part]


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [item.strip() for item in value.replace("，", ",").replace("、", ",").split(",") if item.strip()]
    return []


def _ordered_unique(values: list[str]) -> list[str]:
    seen: dict[str, None] = {}
    for value in values:
        text = str(value or "").strip()
        if text:
            seen.setdefault(text, None)
    return list(seen.keys())
