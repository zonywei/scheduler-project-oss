"""Tenant-scoped repositories for product state and immutable audit history."""
from __future__ import annotations

import json
import re
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

from scheduler.domain.rule_drafts import validate_rule_draft
from scheduler.platform.database import PlatformDatabase


_SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


class TenantNotFound(LookupError):
    pass


class RevisionConflict(RuntimeError):
    pass


@dataclass(frozen=True)
class OrganizationRecord:
    id: str
    slug: str
    name: str
    status: str
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class WorkspaceRecord:
    organization_id: str
    revision: int
    payload: dict[str, Any]
    updated_by: str
    updated_at: str


class PlatformStore:
    def __init__(self, database: PlatformDatabase) -> None:
        self.database = database

    def initialize(self) -> tuple[int, ...]:
        return self.database.initialize()

    def create_organization(
        self,
        *,
        slug: str,
        name: str,
        organization_id: str | None = None,
    ) -> OrganizationRecord:
        normalized_slug = str(slug or "").strip().lower()
        clean_name = str(name or "").strip()
        if not _SLUG_RE.fullmatch(normalized_slug):
            raise ValueError("organization slug must contain 1-63 lowercase letters, digits, or hyphens")
        if not clean_name or len(clean_name) > 120:
            raise ValueError("organization name must contain 1-120 characters")
        record_id = str(organization_id or uuid.uuid4())
        now = _utc_now()
        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO organizations(id, slug, name, status, created_at, updated_at)
                VALUES (?, ?, ?, 'active', ?, ?)
                """,
                (record_id, normalized_slug, clean_name, now, now),
            )
        return self.get_organization(record_id)

    def get_organization(self, organization_id: str) -> OrganizationRecord:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT id, slug, name, status, created_at, updated_at FROM organizations WHERE id = ?",
                (str(organization_id),),
            ).fetchone()
        if row is None:
            raise TenantNotFound(f"organization not found: {organization_id}")
        return OrganizationRecord(**dict(row))

    def get_organization_by_slug(self, slug: str) -> OrganizationRecord:
        normalized_slug = str(slug or "").strip().lower()
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT id, slug, name, status, created_at, updated_at FROM organizations WHERE slug = ?",
                (normalized_slug,),
            ).fetchone()
        if row is None:
            raise TenantNotFound(f"organization not found: {normalized_slug}")
        return OrganizationRecord(**dict(row))

    def load_workspace(self, organization_id: str) -> WorkspaceRecord | None:
        with self.database.connect() as connection:
            self._require_organization(connection, organization_id)
            row = connection.execute(
                """
                SELECT organization_id, revision, payload_json, updated_by, updated_at
                FROM workspace_snapshots WHERE organization_id = ?
                """,
                (str(organization_id),),
            ).fetchone()
        return _workspace_record(row) if row is not None else None

    def save_workspace(
        self,
        organization_id: str,
        payload: Mapping[str, Any],
        *,
        expected_revision: int | None,
        actor_user_id: str = "",
        reason: str = "",
    ) -> WorkspaceRecord:
        with self.database.transaction() as connection:
            self.save_workspace_in_transaction(
                connection,
                organization_id,
                payload,
                expected_revision=expected_revision,
                actor_user_id=actor_user_id,
                reason=reason,
            )
        record = self.load_workspace(organization_id)
        assert record is not None
        return record

    def save_workspace_in_transaction(
        self,
        connection: sqlite3.Connection,
        organization_id: str,
        payload: Mapping[str, Any],
        *,
        expected_revision: int | None,
        actor_user_id: str = "",
        reason: str = "",
    ) -> WorkspaceRecord:
        """Save a workspace using a caller-owned transaction.

        Conversation confirmation uses this primitive to commit the workspace,
        Rule V2 payload, and session state on the same SQLite connection.
        The caller owns rollback when any later part of the confirmation fails.
        """
        clean_payload = _mapping_payload(payload, label="workspace payload")
        encoded = _encode_json(clean_payload)
        self._require_organization(connection, organization_id)
        current_row = connection.execute(
            "SELECT revision FROM workspace_snapshots WHERE organization_id = ?",
            (str(organization_id),),
        ).fetchone()
        current_revision = int(current_row["revision"]) if current_row is not None else 0
        if expected_revision is not None and int(expected_revision) != current_revision:
            raise RevisionConflict(
                f"workspace revision changed: expected {expected_revision}, current {current_revision}"
            )
        next_revision = current_revision + 1
        now = _utc_now()
        connection.execute(
            """
            INSERT INTO workspace_snapshots(organization_id, revision, payload_json, updated_by, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(organization_id) DO UPDATE SET
                revision = excluded.revision,
                payload_json = excluded.payload_json,
                updated_by = excluded.updated_by,
                updated_at = excluded.updated_at
            """,
            (str(organization_id), next_revision, encoded, str(actor_user_id or ""), now),
        )
        connection.execute(
            """
            INSERT INTO workspace_versions(
                organization_id, revision, payload_json, reason, created_by, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                str(organization_id),
                next_revision,
                encoded,
                str(reason or ""),
                str(actor_user_id or ""),
                now,
            ),
        )
        self._insert_audit(
            connection,
            organization_id=str(organization_id),
            actor_user_id=str(actor_user_id or ""),
            event_type="workspace.saved",
            resource_type="workspace",
            resource_id=str(organization_id),
            payload={"revision": next_revision, "reason": str(reason or "")},
            created_at=now,
        )
        return WorkspaceRecord(
            organization_id=str(organization_id),
            revision=next_revision,
            payload=clean_payload,
            updated_by=str(actor_user_id or ""),
            updated_at=now,
        )

    def list_workspace_versions(self, organization_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
        safe_limit = min(200, max(1, int(limit)))
        with self.database.connect() as connection:
            self._require_organization(connection, organization_id)
            rows = connection.execute(
                """
                SELECT revision, payload_json, reason, created_by, created_at
                FROM workspace_versions
                WHERE organization_id = ?
                ORDER BY revision DESC LIMIT ?
                """,
                (str(organization_id), safe_limit),
            ).fetchall()
        return [
            {
                "revision": int(row["revision"]),
                "payload": _decode_mapping(row["payload_json"]),
                "reason": str(row["reason"] or ""),
                "created_by": str(row["created_by"] or ""),
                "created_at": str(row["created_at"]),
            }
            for row in rows
        ]

    def get_workspace_version(self, organization_id: str, revision: int) -> WorkspaceRecord:
        target_revision = int(revision)
        if target_revision <= 0:
            raise ValueError("workspace revision must be positive")
        with self.database.connect() as connection:
            self._require_organization(connection, organization_id)
            row = connection.execute(
                """
                SELECT organization_id, revision, payload_json, created_by AS updated_by, created_at AS updated_at
                FROM workspace_versions
                WHERE organization_id = ? AND revision = ?
                """,
                (str(organization_id), target_revision),
            ).fetchone()
        if row is None:
            raise RevisionConflict(f"workspace revision not found: {target_revision}")
        return _workspace_record(row)

    def save_rule_draft(
        self,
        organization_id: str,
        rule: Mapping[str, Any],
        *,
        actor_user_id: str = "",
    ) -> dict[str, Any]:
        validation = validate_rule_draft(rule)
        if not validation.valid:
            raise ValueError("invalid rule draft: " + "; ".join(validation.errors))
        clean_rule = _mapping_payload(rule, label="rule draft")
        rule_id = str(clean_rule.get("id") or "").strip()
        now = _utc_now()
        encoded = _encode_json(clean_rule)
        with self.database.transaction() as connection:
            self._require_organization(connection, organization_id)
            current = connection.execute(
                """
                SELECT version, created_by, created_at FROM rule_drafts
                WHERE organization_id = ? AND rule_id = ?
                """,
                (str(organization_id), rule_id),
            ).fetchone()
            version = int(current["version"]) + 1 if current is not None else 1
            created_by = str(current["created_by"] or "") if current is not None else str(actor_user_id or "")
            created_at = str(current["created_at"]) if current is not None else now
            connection.execute(
                """
                INSERT INTO rule_drafts(
                    organization_id, rule_id, schema_version, status, version, payload_json,
                    created_by, updated_by, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(organization_id, rule_id) DO UPDATE SET
                    schema_version = excluded.schema_version,
                    status = excluded.status,
                    version = excluded.version,
                    payload_json = excluded.payload_json,
                    updated_by = excluded.updated_by,
                    updated_at = excluded.updated_at
                """,
                (
                    str(organization_id),
                    rule_id,
                    str(clean_rule.get("schema_version") or ""),
                    str(clean_rule.get("status") or ""),
                    version,
                    encoded,
                    created_by,
                    str(actor_user_id or ""),
                    created_at,
                    now,
                ),
            )
            self._insert_audit(
                connection,
                organization_id=str(organization_id),
                actor_user_id=str(actor_user_id or ""),
                event_type="rule_draft.saved",
                resource_type="rule_draft",
                resource_id=rule_id,
                payload={"version": version, "status": str(clean_rule.get("status") or "")},
                created_at=now,
            )
        return self.get_rule_draft(organization_id, rule_id) or {}

    def get_rule_draft(self, organization_id: str, rule_id: str) -> dict[str, Any] | None:
        with self.database.connect() as connection:
            self._require_organization(connection, organization_id)
            row = connection.execute(
                """
                SELECT version, payload_json, created_by, updated_by, created_at, updated_at
                FROM rule_drafts WHERE organization_id = ? AND rule_id = ?
                """,
                (str(organization_id), str(rule_id)),
            ).fetchone()
        if row is None:
            return None
        return {
            "version": int(row["version"]),
            "rule": _decode_mapping(row["payload_json"]),
            "created_by": str(row["created_by"] or ""),
            "updated_by": str(row["updated_by"] or ""),
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
        }

    def list_rule_drafts(self, organization_id: str, *, status: str = "", limit: int = 100) -> list[dict[str, Any]]:
        safe_limit = min(500, max(1, int(limit)))
        params: list[Any] = [str(organization_id)]
        where = "organization_id = ?"
        if str(status or "").strip():
            where += " AND status = ?"
            params.append(str(status).strip())
        params.append(safe_limit)
        with self.database.connect() as connection:
            self._require_organization(connection, organization_id)
            rows = connection.execute(
                f"""
                SELECT rule_id, version, payload_json, created_by, updated_by, created_at, updated_at
                FROM rule_drafts WHERE {where}
                ORDER BY updated_at DESC LIMIT ?
                """,
                tuple(params),
            ).fetchall()
        return [
            {
                "id": str(row["rule_id"]),
                "version": int(row["version"]),
                "rule": _decode_mapping(row["payload_json"]),
                "created_by": str(row["created_by"] or ""),
                "updated_by": str(row["updated_by"] or ""),
                "created_at": str(row["created_at"]),
                "updated_at": str(row["updated_at"]),
            }
            for row in rows
        ]

    def append_audit_event(
        self,
        organization_id: str,
        *,
        actor_user_id: str,
        event_type: str,
        resource_type: str,
        resource_id: str,
        payload: Mapping[str, Any] | None = None,
    ) -> str:
        event_id = str(uuid.uuid4())
        with self.database.transaction() as connection:
            self._require_organization(connection, organization_id)
            self._insert_audit(
                connection,
                organization_id=str(organization_id),
                actor_user_id=str(actor_user_id or ""),
                event_type=str(event_type or "").strip(),
                resource_type=str(resource_type or "").strip(),
                resource_id=str(resource_id or "").strip(),
                payload=_mapping_payload(payload or {}, label="audit payload"),
                created_at=_utc_now(),
                event_id=event_id,
            )
        return event_id

    def list_audit_events(self, organization_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
        safe_limit = min(500, max(1, int(limit)))
        with self.database.connect() as connection:
            self._require_organization(connection, organization_id)
            rows = connection.execute(
                """
                SELECT id, actor_user_id, event_type, resource_type, resource_id, payload_json, created_at
                FROM audit_events WHERE organization_id = ?
                ORDER BY created_at DESC, rowid DESC LIMIT ?
                """,
                (str(organization_id), safe_limit),
            ).fetchall()
        return [
            {
                "id": str(row["id"]),
                "actor_user_id": str(row["actor_user_id"] or ""),
                "event_type": str(row["event_type"]),
                "resource_type": str(row["resource_type"]),
                "resource_id": str(row["resource_id"]),
                "payload": _decode_mapping(row["payload_json"]),
                "created_at": str(row["created_at"]),
            }
            for row in rows
        ]

    @staticmethod
    def _require_organization(connection: sqlite3.Connection, organization_id: str) -> None:
        row = connection.execute(
            "SELECT 1 FROM organizations WHERE id = ? AND status = 'active'",
            (str(organization_id),),
        ).fetchone()
        if row is None:
            raise TenantNotFound(f"active organization not found: {organization_id}")

    @staticmethod
    def _insert_audit(
        connection: sqlite3.Connection,
        *,
        organization_id: str,
        actor_user_id: str,
        event_type: str,
        resource_type: str,
        resource_id: str,
        payload: Mapping[str, Any],
        created_at: str,
        event_id: str | None = None,
    ) -> None:
        if not event_type or not resource_type or not resource_id:
            raise ValueError("audit event type, resource type, and resource id are required")
        connection.execute(
            """
            INSERT INTO audit_events(
                id, organization_id, actor_user_id, event_type,
                resource_type, resource_id, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(event_id or uuid.uuid4()),
                organization_id,
                actor_user_id,
                event_type,
                resource_type,
                resource_id,
                _encode_json(_mapping_payload(payload, label="audit payload")),
                created_at,
            ),
        )


def _workspace_record(row: sqlite3.Row) -> WorkspaceRecord:
    return WorkspaceRecord(
        organization_id=str(row["organization_id"]),
        revision=int(row["revision"]),
        payload=_decode_mapping(row["payload_json"]),
        updated_by=str(row["updated_by"] or ""),
        updated_at=str(row["updated_at"]),
    )


def _mapping_payload(value: Mapping[str, Any], *, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    return json.loads(_encode_json(dict(value)))


def _encode_json(value: Mapping[str, Any]) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise ValueError("payload must contain JSON-serializable values") from exc


def _decode_mapping(raw: str) -> dict[str, Any]:
    value = json.loads(str(raw or "{}"))
    if not isinstance(value, dict):
        raise ValueError("stored payload is not a JSON object")
    return value


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")
