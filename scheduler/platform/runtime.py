"""Runtime selection for legacy YAML or tenant-scoped SQLite workspace state."""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Mapping

from scheduler.platform.database import PlatformDatabase, PlatformDatabaseSettings
from scheduler.platform.store import PlatformStore, WorkspaceRecord


@dataclass(frozen=True)
class RuntimeWorkspace:
    organization_id: str
    revision: int
    payload: dict[str, Any]
    updated_by: str = ""
    updated_at: str = ""


def runtime_state_backend() -> str:
    value = str(os.environ.get("SCHEDULER_STATE_BACKEND") or "yaml").strip().lower()
    if value not in {"yaml", "sqlite"}:
        raise ValueError("SCHEDULER_STATE_BACKEND must be yaml or sqlite")
    return value


def uses_sqlite_workspace() -> bool:
    return runtime_state_backend() == "sqlite"


def runtime_organization_id() -> str:
    value = str(os.environ.get("SCHEDULER_ORGANIZATION_ID") or "").strip()
    if value:
        return value
    slug = str(os.environ.get("SCHEDULER_ORGANIZATION_SLUG") or "").strip().lower()
    if slug:
        return runtime_store().get_organization_by_slug(slug).id
    raise ValueError(
        "SCHEDULER_ORGANIZATION_ID or SCHEDULER_ORGANIZATION_SLUG is required when the state backend is sqlite"
    )


def runtime_store() -> PlatformStore:
    database = PlatformDatabase(PlatformDatabaseSettings.from_environment())
    store = PlatformStore(database)
    store.initialize()
    return store


def load_runtime_workspace() -> RuntimeWorkspace | None:
    organization_id = runtime_organization_id()
    store = runtime_store()
    revision_raw = str(os.environ.get("SCHEDULER_WORKSPACE_REVISION") or "").strip()
    record = (
        store.get_workspace_version(organization_id, int(revision_raw))
        if revision_raw
        else store.load_workspace(organization_id)
    )
    return _runtime_record(record) if record is not None else None


def save_runtime_workspace(
    payload: Mapping[str, Any],
    *,
    expected_revision: int | None,
    actor_user_id: str = "",
    reason: str = "",
) -> RuntimeWorkspace:
    organization_id = runtime_organization_id()
    record = runtime_store().save_workspace(
        organization_id,
        payload,
        expected_revision=expected_revision,
        actor_user_id=actor_user_id,
        reason=reason,
    )
    return _runtime_record(record)


def _runtime_record(record: WorkspaceRecord) -> RuntimeWorkspace:
    return RuntimeWorkspace(
        organization_id=record.organization_id,
        revision=record.revision,
        payload=record.payload,
        updated_by=record.updated_by,
        updated_at=record.updated_at,
    )
