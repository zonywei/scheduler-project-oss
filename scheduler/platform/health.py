"""Operational health signals for the Web and solve Worker processes."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from scheduler.platform.store import PlatformStore


def record_service_heartbeat(
    store: PlatformStore,
    organization_id: str,
    *,
    service_kind: str,
    instance_id: str,
    metadata: Mapping[str, Any] | None = None,
    now: datetime | None = None,
) -> None:
    timestamp = _iso(now or datetime.now(timezone.utc))
    with store.database.transaction() as connection:
        store._require_organization(connection, organization_id)
        connection.execute(
            """
            INSERT INTO service_heartbeats(
                organization_id, service_kind, instance_id, metadata_json, last_seen_at
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(organization_id, service_kind, instance_id) DO UPDATE SET
                metadata_json = excluded.metadata_json,
                last_seen_at = excluded.last_seen_at
            """,
            (
                str(organization_id),
                _label(service_kind, "service_kind", 40),
                _label(instance_id, "instance_id", 160),
                json.dumps(dict(metadata or {}), ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                timestamp,
            ),
        )
        connection.execute(
            "DELETE FROM service_heartbeats WHERE last_seen_at < ?",
            (_iso((now or datetime.now(timezone.utc)) - timedelta(days=7)),),
        )


def platform_health(
    store: PlatformStore,
    organization_id: str,
    *,
    worker_max_age_seconds: int = 60,
    now: datetime | None = None,
) -> dict[str, Any]:
    timestamp = now or datetime.now(timezone.utc)
    versions = store.initialize()
    organization = store.get_organization(organization_id)
    workspace = store.load_workspace(organization_id)
    cutoff = _iso(timestamp - timedelta(seconds=max(10, int(worker_max_age_seconds))))
    with store.database.connect() as connection:
        worker = connection.execute(
            """
            SELECT last_seen_at, metadata_json
            FROM service_heartbeats
            WHERE organization_id = ? AND service_kind = 'solve-worker' AND last_seen_at >= ?
            ORDER BY last_seen_at DESC LIMIT 1
            """,
            (str(organization_id), cutoff),
        ).fetchone()
    database_ok = store.database.integrity_check() == "ok"
    ready = database_ok and organization.status == "active" and workspace is not None
    return {
        "schema_version": "scheduler.platform_health.v1",
        "status": "ready" if ready else "not_ready",
        "ready": ready,
        "checks": {
            "database": "ok" if database_ok else "error",
            "migrations": list(versions),
            "organization": "active" if organization.status == "active" else "inactive",
            "workspace": "ready" if workspace is not None else "missing",
            "worker": "healthy" if worker is not None else "unavailable",
        },
        "worker_last_seen_at": str(worker["last_seen_at"]) if worker is not None else "",
    }


def _label(value: str, name: str, maximum: int) -> str:
    clean = str(value or "").strip()
    if not clean or len(clean) > maximum or any(ord(character) < 32 for character in clean):
        raise ValueError(f"{name} must contain 1-{maximum} visible characters")
    return clean


def _iso(value: datetime) -> str:
    normalized = value.astimezone(timezone.utc) if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    return normalized.isoformat(timespec="microseconds")
