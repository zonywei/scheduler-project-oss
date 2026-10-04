"""Durable, tenant-scoped solve job queue and worker lease transitions."""
from __future__ import annotations

import json
import re
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Mapping

from scheduler.platform.store import PlatformStore, RevisionConflict


QUEUED = "queued"
RUNNING = "running"
CANCEL_REQUESTED = "cancel_requested"
COMPLETED = "completed"
FAILED = "failed"
CANCELLED = "cancelled"
ACTIVE_JOB_STATUSES = {QUEUED, RUNNING, CANCEL_REQUESTED}
LEASED_JOB_STATUSES = {RUNNING, CANCEL_REQUESTED}
TERMINAL_JOB_STATUSES = {COMPLETED, FAILED, CANCELLED}
_IDEMPOTENCY_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


class JobNotFound(LookupError):
    pass


class JobLeaseLost(RuntimeError):
    pass


class JobQueueFull(RuntimeError):
    pass


class JobIdempotencyConflict(RuntimeError):
    """Raised when an idempotency key is reused for a different request scope."""

    pass


@dataclass(frozen=True)
class SolveJob:
    id: str
    organization_id: str
    status: str
    request: dict[str, Any]
    run_dir: str
    worker_id: str
    process_id: int | None
    error_code: str
    error_message: str
    created_by: str
    created_at: str
    started_at: str
    heartbeat_at: str
    completed_at: str
    cancel_requested_at: str
    idempotency_key: str
    workspace_revision: int
    result: dict[str, Any]
    updated_at: str


@dataclass(frozen=True)
class JobCreateResult:
    job: SolveJob
    created: bool


class SolveJobStore:
    def __init__(
        self,
        store: PlatformStore,
        *,
        now: Callable[[], datetime] | None = None,
        max_queued_per_organization: int = 20,
    ) -> None:
        self.store = store
        self._now = now or (lambda: datetime.now(timezone.utc))
        self.max_queued_per_organization = max(1, int(max_queued_per_organization))

    def create_job(
        self,
        organization_id: str,
        request: Mapping[str, Any],
        *,
        created_by: str,
        workspace_revision: int,
        idempotency_key: str = "",
        expected_workspace_revision: int | None = None,
    ) -> JobCreateResult:
        payload = _mapping(request, "solve request")
        encoded_payload = _encode(payload)
        revision = int(workspace_revision)
        if revision <= 0:
            raise ValueError("workspace revision must be positive")
        expected_revision = (
            int(expected_workspace_revision)
            if expected_workspace_revision is not None
            else None
        )
        if expected_revision is not None and expected_revision <= 0:
            raise ValueError("expected workspace revision must be positive")
        if expected_revision is not None and expected_revision != revision:
            raise RevisionConflict(
                "enqueue workspace revision mismatch: "
                f"expected {expected_revision}, requested {revision}"
            )
        key = str(idempotency_key or "").strip()
        if key and not _IDEMPOTENCY_RE.fullmatch(key):
            raise ValueError("idempotency key must contain 1-128 safe ASCII characters")
        actor = str(created_by or "")
        now = _iso(self._now())
        job_id = str(uuid.uuid4())
        with self.store.database.transaction() as connection:
            self.store._require_organization(connection, organization_id)
            if key:
                existing = connection.execute(
                    "SELECT * FROM solve_jobs WHERE organization_id = ? AND idempotency_key = ?",
                    (str(organization_id), key),
                ).fetchone()
                if existing is not None:
                    existing_job = _job(existing)
                    if (
                        existing_job.created_by != actor
                        or existing_job.workspace_revision != revision
                        or _decode(existing["request_json"]) != payload
                    ):
                        raise JobIdempotencyConflict(
                            "幂等键已被其他操作者、请求内容或 workspace 版本占用"
                        )
                    return JobCreateResult(job=existing_job, created=False)
            workspace_row = connection.execute(
                "SELECT revision FROM workspace_snapshots WHERE organization_id = ?",
                (str(organization_id),),
            ).fetchone()
            if workspace_row is None:
                raise RuntimeError("当前学校尚未初始化工作区")
            current_revision = int(workspace_row["revision"])
            if current_revision != revision:
                raise RevisionConflict(
                    "workspace revision changed: "
                    f"requested {revision}, current {current_revision}"
                )
            if expected_revision is not None and current_revision != expected_revision:
                raise RevisionConflict(
                    "workspace revision changed: "
                    f"expected {expected_revision}, current {current_revision}"
                )
            queued_count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM solve_jobs WHERE organization_id = ? AND status = 'queued'",
                    (str(organization_id),),
                ).fetchone()[0]
            )
            if queued_count >= self.max_queued_per_organization:
                raise JobQueueFull("该学校待处理求解任务已达到上限")
            connection.execute(
                """
                INSERT INTO solve_jobs(
                    id, organization_id, status, request_json, run_dir, worker_id,
                    process_id, error_code, error_message, created_by, created_at,
                    started_at, heartbeat_at, completed_at, cancel_requested_at,
                    idempotency_key, workspace_revision, result_json, updated_at
                ) VALUES (?, ?, 'queued', ?, '', '', NULL, '', '', ?, ?, NULL, NULL, NULL, NULL, ?, ?, '{}', ?)
                """,
                (
                    job_id,
                    str(organization_id),
                    encoded_payload,
                    actor,
                    now,
                    key,
                    revision,
                    now,
                ),
            )
            self.store._insert_audit(
                connection,
                organization_id=str(organization_id),
                actor_user_id=actor,
                event_type="solve_job.queued",
                resource_type="solve_job",
                resource_id=job_id,
                payload={"workspace_revision": revision},
                created_at=now,
            )
            row = connection.execute("SELECT * FROM solve_jobs WHERE id = ?", (job_id,)).fetchone()
        assert row is not None
        return JobCreateResult(job=_job(row), created=True)

    def get_job(self, organization_id: str, job_id: str) -> SolveJob:
        with self.store.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM solve_jobs WHERE organization_id = ? AND id = ?",
                (str(organization_id), str(job_id)),
            ).fetchone()
        if row is None:
            raise JobNotFound(f"solve job not found: {job_id}")
        return _job(row)

    def latest_job(self, organization_id: str) -> SolveJob | None:
        with self.store.database.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM solve_jobs WHERE organization_id = ?
                ORDER BY created_at DESC, rowid DESC LIMIT 1
                """,
                (str(organization_id),),
            ).fetchone()
        return _job(row) if row is not None else None

    def list_jobs(self, organization_id: str, *, limit: int = 50) -> list[SolveJob]:
        safe_limit = min(200, max(1, int(limit)))
        with self.store.database.connect() as connection:
            self.store._require_organization(connection, organization_id)
            rows = connection.execute(
                """
                SELECT * FROM solve_jobs WHERE organization_id = ?
                ORDER BY created_at DESC, rowid DESC LIMIT ?
                """,
                (str(organization_id), safe_limit),
            ).fetchall()
        return [_job(row) for row in rows]

    def claim_next(self, organization_id: str, *, worker_id: str) -> SolveJob | None:
        clean_worker = _worker_id(worker_id)
        now = _iso(self._now())
        try:
            with self.store.database.transaction() as connection:
                self.store._require_organization(connection, organization_id)
                active = connection.execute(
                    """
                    SELECT 1 FROM solve_jobs
                    WHERE organization_id = ? AND status IN ('running', 'cancel_requested')
                    LIMIT 1
                    """,
                    (str(organization_id),),
                ).fetchone()
                if active is not None:
                    return None
                row = connection.execute(
                    """
                    SELECT id FROM solve_jobs
                    WHERE organization_id = ? AND status = 'queued'
                    ORDER BY created_at ASC, rowid ASC LIMIT 1
                    """,
                    (str(organization_id),),
                ).fetchone()
                if row is None:
                    return None
                job_id = str(row["id"])
                updated = connection.execute(
                    """
                    UPDATE solve_jobs
                    SET status = 'running', worker_id = ?, started_at = ?, heartbeat_at = ?, updated_at = ?
                    WHERE organization_id = ? AND id = ? AND status = 'queued'
                    """,
                    (clean_worker, now, now, now, str(organization_id), job_id),
                )
                if updated.rowcount != 1:
                    return None
                self.store._insert_audit(
                    connection,
                    organization_id=str(organization_id),
                    actor_user_id=clean_worker,
                    event_type="solve_job.started",
                    resource_type="solve_job",
                    resource_id=job_id,
                    payload={"worker_id": clean_worker},
                    created_at=now,
                )
                claimed = connection.execute("SELECT * FROM solve_jobs WHERE id = ?", (job_id,)).fetchone()
        except sqlite3.IntegrityError:
            return None
        assert claimed is not None
        return _job(claimed)

    def attach_execution(
        self,
        job_id: str,
        *,
        worker_id: str,
        run_dir: str,
        process_id: int | None,
    ) -> SolveJob:
        clean_worker = _worker_id(worker_id)
        now = _iso(self._now())
        with self.store.database.transaction() as connection:
            updated = connection.execute(
                """
                UPDATE solve_jobs SET run_dir = ?, process_id = ?, heartbeat_at = ?, updated_at = ?
                WHERE id = ? AND worker_id = ? AND status IN ('running', 'cancel_requested')
                """,
                (str(run_dir or ""), process_id, now, now, str(job_id), clean_worker),
            )
            if updated.rowcount != 1:
                raise JobLeaseLost(f"solve job lease lost: {job_id}")
            row = connection.execute("SELECT * FROM solve_jobs WHERE id = ?", (str(job_id),)).fetchone()
        assert row is not None
        return _job(row)

    def heartbeat(self, job_id: str, *, worker_id: str) -> None:
        clean_worker = _worker_id(worker_id)
        now = _iso(self._now())
        with self.store.database.transaction() as connection:
            updated = connection.execute(
                """
                UPDATE solve_jobs SET heartbeat_at = ?, updated_at = ?
                WHERE id = ? AND worker_id = ? AND status IN ('running', 'cancel_requested')
                """,
                (now, now, str(job_id), clean_worker),
            )
            if updated.rowcount != 1:
                raise JobLeaseLost(f"solve job lease lost: {job_id}")

    def cancellation_requested(self, job_id: str, *, worker_id: str) -> bool:
        clean_worker = _worker_id(worker_id)
        with self.store.database.connect() as connection:
            row = connection.execute(
                "SELECT status FROM solve_jobs WHERE id = ? AND worker_id = ?",
                (str(job_id), clean_worker),
            ).fetchone()
        if row is None:
            raise JobLeaseLost(f"solve job lease lost: {job_id}")
        return str(row["status"]) == CANCEL_REQUESTED

    def request_cancel(self, organization_id: str, job_id: str, *, actor_user_id: str) -> SolveJob:
        now = _iso(self._now())
        with self.store.database.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM solve_jobs WHERE organization_id = ? AND id = ?",
                (str(organization_id), str(job_id)),
            ).fetchone()
            if row is None:
                raise JobNotFound(f"solve job not found: {job_id}")
            status = str(row["status"])
            next_status = CANCELLED if status == QUEUED else CANCEL_REQUESTED if status == RUNNING else status
            if next_status != status:
                completed_at = now if next_status == CANCELLED else None
                connection.execute(
                    """
                    UPDATE solve_jobs
                    SET status = ?, cancel_requested_at = ?, completed_at = COALESCE(?, completed_at), updated_at = ?
                    WHERE organization_id = ? AND id = ?
                    """,
                    (next_status, now, completed_at, now, str(organization_id), str(job_id)),
                )
                self.store._insert_audit(
                    connection,
                    organization_id=str(organization_id),
                    actor_user_id=str(actor_user_id or ""),
                    event_type="solve_job.cancel_requested",
                    resource_type="solve_job",
                    resource_id=str(job_id),
                    payload={"previous_status": status, "status": next_status},
                    created_at=now,
                )
            result = connection.execute("SELECT * FROM solve_jobs WHERE id = ?", (str(job_id),)).fetchone()
        assert result is not None
        return _job(result)

    def finish(
        self,
        job_id: str,
        *,
        worker_id: str,
        status: str,
        result: Mapping[str, Any] | None = None,
        error_code: str = "",
        error_message: str = "",
    ) -> SolveJob:
        if status not in TERMINAL_JOB_STATUSES:
            raise ValueError(f"invalid terminal solve job status: {status}")
        clean_worker = _worker_id(worker_id)
        now = _iso(self._now())
        clean_result = _mapping(result or {}, "solve result")
        with self.store.database.transaction() as connection:
            row = connection.execute(
                "SELECT organization_id, status FROM solve_jobs WHERE id = ? AND worker_id = ?",
                (str(job_id), clean_worker),
            ).fetchone()
            if row is None or str(row["status"]) not in LEASED_JOB_STATUSES:
                raise JobLeaseLost(f"solve job lease lost: {job_id}")
            final_status = CANCELLED if str(row["status"]) == CANCEL_REQUESTED else status
            connection.execute(
                """
                UPDATE solve_jobs
                SET status = ?, result_json = ?, error_code = ?, error_message = ?,
                    completed_at = ?, heartbeat_at = ?, updated_at = ?
                WHERE id = ? AND worker_id = ?
                """,
                (
                    final_status,
                    _encode(clean_result),
                    str(error_code or "")[:120],
                    str(error_message or "")[:2000],
                    now,
                    now,
                    now,
                    str(job_id),
                    clean_worker,
                ),
            )
            self.store._insert_audit(
                connection,
                organization_id=str(row["organization_id"]),
                actor_user_id=clean_worker,
                event_type=f"solve_job.{final_status}",
                resource_type="solve_job",
                resource_id=str(job_id),
                payload={"error_code": str(error_code or "")[:120]},
                created_at=now,
            )
            final = connection.execute("SELECT * FROM solve_jobs WHERE id = ?", (str(job_id),)).fetchone()
        assert final is not None
        return _job(final)

    def fail_stale_leases(self, organization_id: str, *, heartbeat_before: datetime) -> list[str]:
        cutoff = _iso(heartbeat_before)
        now = _iso(self._now())
        failed_ids: list[str] = []
        with self.store.database.transaction() as connection:
            rows = connection.execute(
                """
                SELECT id FROM solve_jobs
                WHERE organization_id = ?
                  AND status IN ('running', 'cancel_requested')
                  AND COALESCE(heartbeat_at, started_at, created_at) < ?
                """,
                (str(organization_id), cutoff),
            ).fetchall()
            for row in rows:
                job_id = str(row["id"])
                failed_ids.append(job_id)
                connection.execute(
                    """
                    UPDATE solve_jobs
                    SET status = 'failed', error_code = 'worker_lease_expired',
                        error_message = 'Worker heartbeat expired; manual output review may be required.',
                        completed_at = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (now, now, job_id),
                )
                self.store._insert_audit(
                    connection,
                    organization_id=str(organization_id),
                    actor_user_id="worker-recovery",
                    event_type="solve_job.failed",
                    resource_type="solve_job",
                    resource_id=job_id,
                    payload={"error_code": "worker_lease_expired"},
                    created_at=now,
                )
        return failed_ids


def job_payload(job: SolveJob) -> dict[str, Any]:
    return {
        "schema_version": "scheduler.solve_job.v1",
        "id": job.id,
        "organization_id": job.organization_id,
        "status": job.status,
        "request": job.request,
        "run_dir": job.run_dir,
        "worker_id": job.worker_id,
        "process_id": job.process_id,
        "error": {"code": job.error_code, "message": job.error_message},
        "created_by": job.created_by,
        "created_at": job.created_at,
        "started_at": job.started_at,
        "heartbeat_at": job.heartbeat_at,
        "completed_at": job.completed_at,
        "cancel_requested_at": job.cancel_requested_at,
        "workspace_revision": job.workspace_revision,
        "result": job.result,
        "updated_at": job.updated_at,
    }


def _job(row: sqlite3.Row) -> SolveJob:
    return SolveJob(
        id=str(row["id"]),
        organization_id=str(row["organization_id"]),
        status=str(row["status"]),
        request=_decode(row["request_json"]),
        run_dir=str(row["run_dir"] or ""),
        worker_id=str(row["worker_id"] or ""),
        process_id=int(row["process_id"]) if row["process_id"] is not None else None,
        error_code=str(row["error_code"] or ""),
        error_message=str(row["error_message"] or ""),
        created_by=str(row["created_by"] or ""),
        created_at=str(row["created_at"]),
        started_at=str(row["started_at"] or ""),
        heartbeat_at=str(row["heartbeat_at"] or ""),
        completed_at=str(row["completed_at"] or ""),
        cancel_requested_at=str(row["cancel_requested_at"] or ""),
        idempotency_key=str(row["idempotency_key"] or ""),
        workspace_revision=int(row["workspace_revision"] or 0),
        result=_decode(row["result_json"]),
        updated_at=str(row["updated_at"] or ""),
    )


def _mapping(value: Mapping[str, Any], label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    return _decode(_encode(dict(value)))


def _encode(value: Mapping[str, Any]) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise ValueError("solve job data must be JSON serializable") from exc


def _decode(raw: Any) -> dict[str, Any]:
    value = json.loads(str(raw or "{}"))
    if not isinstance(value, dict):
        raise ValueError("stored solve job data is invalid")
    return value


def _worker_id(value: str) -> str:
    clean = str(value or "").strip()
    if not clean or len(clean) > 120:
        raise ValueError("worker id must contain 1-120 characters")
    return clean


def _iso(value: datetime) -> str:
    normalized = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    return normalized.astimezone(timezone.utc).isoformat(timespec="microseconds")
