# -*- coding: utf-8 -*-
from __future__ import annotations

import copy
from datetime import datetime
from typing import Any

from scheduler.app import config_service


RELAXATION_KIND = "diagnostic_relaxation"


def apply_relaxation_plan(plan: dict[str, Any]) -> dict[str, Any]:
    clean_plan = _clean_plan(plan)
    plan_id = clean_plan["id"]
    overrides = config_service.load_web_overrides()
    active = _active_items(overrides)
    current = _find_active(active, plan_id)
    if current:
        return {"overrides": overrides, "plan": current, "applied": False, "already_active": True}

    restore: list[dict[str, Any]] = []
    for patch in clean_plan["patches"]:
        root = _target_root(overrides, patch["target"])
        existed, old_value = _get_path_value(root, patch["path"])
        created_containers = _created_container_paths(root, patch["path"])
        restore.append(
            {
                "target": patch["target"],
                "path": list(patch["path"]),
                "path_label": patch["path_label"],
                "existed": existed,
                "value": copy.deepcopy(old_value),
                "created_containers": created_containers,
            }
        )
        _apply_patch(root, patch)

    active_item = {
        "id": plan_id,
        "kind": RELAXATION_KIND,
        "status": "active",
        "description": clean_plan["title"],
        "source": f"诊断试运行方案：{clean_plan['rationale']}",
        "domain": clean_plan["domain"],
        "risk": clean_plan["risk"],
        "patches": copy.deepcopy(clean_plan["patches"]),
        "restore": restore,
        "solver_supported": True,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    active.append(active_item)
    _set_active_items(overrides, active)
    saved = config_service.save_web_overrides(
        overrides,
        actor_user_id="system",
        reason=f"apply diagnostic relaxation {plan_id}",
    )
    return {"overrides": saved, "plan": active_item, "applied": True, "already_active": False}


def remove_relaxation_plan(plan_id: str) -> dict[str, Any]:
    plan_id = str(plan_id or "").strip()
    if not plan_id:
        raise ValueError("plan_id is required")
    overrides = config_service.load_web_overrides()
    active = _active_items(overrides)
    current = _find_active(active, plan_id)
    if not current:
        return {"overrides": overrides, "removed": False, "plan_id": plan_id}

    for item in reversed(current.get("restore") or []):
        if not isinstance(item, dict):
            continue
        target = str(item.get("target") or "")
        path = _clean_path(item.get("path"))
        if target not in {"io", "rules"} or not path:
            continue
        root = _target_root(overrides, target)
        if bool(item.get("existed", False)):
            _set_path_value(root, path, copy.deepcopy(item.get("value")))
        else:
            _delete_path_value(root, path)
            for container_path in reversed(item.get("created_containers") or []):
                cleaned_path = _clean_path(container_path)
                if cleaned_path:
                    deleted = _delete_empty_container(root, cleaned_path)
                    if not deleted and _container_exists(root, cleaned_path):
                        _remember_pending_created_container(overrides, target, cleaned_path)

    active = [item for item in active if not _matches_active(item, plan_id)]
    _set_active_items(overrides, active)
    _prune_pending_created_containers(overrides)
    saved = config_service.save_web_overrides(
        overrides,
        actor_user_id="system",
        reason=f"remove diagnostic relaxation {plan_id}",
    )
    return {"overrides": saved, "removed": True, "plan_id": plan_id}


def active_relaxation_plans(overrides: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    source = overrides if isinstance(overrides, dict) else config_service.load_web_overrides()
    return [
        copy.deepcopy(item)
        for item in _active_items(source)
        if _is_active_relaxation(item)
    ]


def is_relaxation_plan_active(overrides: dict[str, Any], plan_id: str) -> bool:
    return _find_active(_active_items(overrides), str(plan_id or "").strip()) is not None


def _clean_plan(plan: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(plan, dict):
        raise ValueError("plan must be an object")
    plan_id = str(plan.get("id") or "").strip()
    if not plan_id:
        raise ValueError("plan.id is required")
    patches = [_clean_patch(patch) for patch in plan.get("patches") or [] if isinstance(patch, dict)]
    if not patches:
        raise ValueError("plan.patches is required")
    return {
        "id": plan_id,
        "title": str(plan.get("title") or plan_id),
        "domain": str(plan.get("domain") or "排障方案"),
        "rationale": str(plan.get("rationale") or ""),
        "risk": str(plan.get("risk") or ""),
        "patches": patches,
    }


def _clean_patch(patch: dict[str, Any]) -> dict[str, Any]:
    target = str(patch.get("target") or "").strip()
    if target not in {"io", "rules"}:
        raise ValueError(f"unsupported patch target: {target}")
    operation = str(patch.get("operation") or "set").strip()
    if operation not in {"set", "append_unique"}:
        raise ValueError(f"unsupported patch operation: {operation}")
    path = _clean_path(patch.get("path"))
    if not path:
        raise ValueError("patch.path is required")
    path_label = str(patch.get("path_label") or ".".join(path))
    clean = {"target": target, "operation": operation, "path": path, "path_label": path_label}
    if operation == "append_unique":
        clean["values"] = [str(value).strip() for value in patch.get("values", []) if str(value).strip()]
    else:
        clean["value"] = copy.deepcopy(patch.get("value"))
    return clean


def _clean_path(raw: Any) -> list[str]:
    if isinstance(raw, list):
        return [str(part).strip() for part in raw if str(part).strip()]
    return [part.strip() for part in str(raw or "").split(".") if part.strip()]


def _target_root(overrides: dict[str, Any], target: str) -> dict[str, Any]:
    root = overrides.setdefault(target, {})
    if not isinstance(root, dict):
        root = {}
        overrides[target] = root
    return root


def _active_items(overrides: dict[str, Any]) -> list[dict[str, Any]]:
    temporary = overrides.setdefault("temporary_rules", {"active": []})
    if not isinstance(temporary, dict):
        temporary = {"active": []}
        overrides["temporary_rules"] = temporary
    active = temporary.get("active")
    if not isinstance(active, list):
        active = []
        temporary["active"] = active
    return [item for item in active if isinstance(item, dict)]


def _set_active_items(overrides: dict[str, Any], active: list[dict[str, Any]]) -> None:
    temporary = overrides.setdefault("temporary_rules", {"active": []})
    if not isinstance(temporary, dict):
        temporary = {"active": []}
        overrides["temporary_rules"] = temporary
    temporary["active"] = active


def _matches_active(item: dict[str, Any], plan_id: str) -> bool:
    return str(item.get("id") or "") == plan_id and str(item.get("kind") or "") == RELAXATION_KIND


def _is_active_relaxation(item: dict[str, Any]) -> bool:
    return str(item.get("kind") or "") == RELAXATION_KIND and str(item.get("status") or "") == "active"


def _find_active(active: list[dict[str, Any]], plan_id: str) -> dict[str, Any] | None:
    for item in active:
        if _matches_active(item, plan_id):
            return item
    return None


def _get_path_value(root: dict[str, Any], path: list[str]) -> tuple[bool, Any]:
    cur: Any = root
    for part in path[:-1]:
        if not isinstance(cur, dict) or part not in cur:
            return False, None
        cur = cur[part]
    if not isinstance(cur, dict):
        return False, None
    leaf = path[-1]
    return leaf in cur, copy.deepcopy(cur.get(leaf))


def _created_container_paths(root: dict[str, Any], path: list[str]) -> list[list[str]]:
    cur: Any = root
    created: list[list[str]] = []
    missing_parent = False
    for index, part in enumerate(path[:-1], start=1):
        prefix = list(path[:index])
        if missing_parent:
            created.append(prefix)
            continue
        if not isinstance(cur, dict):
            raise ValueError(f"patch parent is not an object: {'.'.join(path[: index - 1])}")
        if part not in cur:
            created.append(prefix)
            missing_parent = True
            continue
        cur = cur[part]
        if not isinstance(cur, dict):
            raise ValueError(f"patch parent is not an object: {'.'.join(prefix)}")
    return created


def _set_path_value(root: dict[str, Any], path: list[str], value: Any) -> None:
    cur: Any = root
    for part in path[:-1]:
        if not isinstance(cur.get(part), dict):
            cur[part] = {}
        cur = cur[part]
    cur[path[-1]] = value


def _delete_path_value(root: dict[str, Any], path: list[str]) -> None:
    cur: Any = root
    for part in path[:-1]:
        if not isinstance(cur, dict) or not isinstance(cur.get(part), dict):
            return
        cur = cur[part]
    if isinstance(cur, dict):
        cur.pop(path[-1], None)


def _delete_empty_container(root: dict[str, Any], path: list[str]) -> bool:
    cur: Any = root
    parents: list[tuple[dict[str, Any], str]] = []
    for part in path:
        if not isinstance(cur, dict) or not isinstance(cur.get(part), dict):
            return True
        parents.append((cur, part))
        cur = cur[part]
    for parent, part in reversed(parents):
        value = parent.get(part)
        if isinstance(value, dict) and not value:
            parent.pop(part, None)
            continue
        return False
    return True


def _container_exists(root: dict[str, Any], path: list[str]) -> bool:
    cur: Any = root
    for part in path:
        if not isinstance(cur, dict) or not isinstance(cur.get(part), dict):
            return False
        cur = cur[part]
    return isinstance(cur, dict)


def _pending_created_containers(overrides: dict[str, Any]) -> list[dict[str, Any]]:
    temporary = overrides.setdefault("temporary_rules", {"active": []})
    if not isinstance(temporary, dict):
        temporary = {"active": []}
        overrides["temporary_rules"] = temporary
    pending = temporary.get("diagnostic_created_containers")
    if not isinstance(pending, list):
        pending = []
        temporary["diagnostic_created_containers"] = pending
    return [item for item in pending if isinstance(item, dict)]


def _remember_pending_created_container(overrides: dict[str, Any], target: str, path: list[str]) -> None:
    pending = _pending_created_containers(overrides)
    marker = {"target": target, "path": list(path)}
    if not any(item.get("target") == target and _clean_path(item.get("path")) == path for item in pending):
        pending.append(marker)
    temporary = overrides.setdefault("temporary_rules", {"active": []})
    if isinstance(temporary, dict):
        temporary["diagnostic_created_containers"] = pending


def _prune_pending_created_containers(overrides: dict[str, Any]) -> None:
    pending = _pending_created_containers(overrides)
    remaining: list[dict[str, Any]] = []
    for item in sorted(pending, key=lambda raw: len(_clean_path(raw.get("path"))), reverse=True):
        target = str(item.get("target") or "")
        path = _clean_path(item.get("path"))
        if target not in {"io", "rules"} or not path:
            continue
        root = _target_root(overrides, target)
        deleted = _delete_empty_container(root, path)
        if not deleted and _container_exists(root, path):
            remaining.append({"target": target, "path": path})

    temporary = overrides.setdefault("temporary_rules", {"active": []})
    if isinstance(temporary, dict):
        if remaining:
            temporary["diagnostic_created_containers"] = remaining
        else:
            temporary.pop("diagnostic_created_containers", None)


def _apply_patch(root: dict[str, Any], patch: dict[str, Any]) -> None:
    if patch["operation"] == "set":
        _set_path_value(root, patch["path"], copy.deepcopy(patch.get("value")))
        return
    existed, current = _get_path_value(root, patch["path"])
    values = [str(value).strip() for value in patch.get("values", []) if str(value).strip()]
    current_list = list(current) if existed and isinstance(current, list) else []
    seen = {str(value) for value in current_list}
    for value in values:
        if value not in seen:
            current_list.append(value)
            seen.add(value)
    _set_path_value(root, patch["path"], current_list)
