from __future__ import annotations

import http.client
import json
import os
import threading
from datetime import datetime, timedelta, timezone
from http.cookies import SimpleCookie
from pathlib import Path
from typing import Any

import pytest

from scheduler.app import job_api
from scheduler.app.web import SchedulerWebHandler
from scheduler.platform import (
    AuthService,
    JobNotFound,
    PasswordHasher,
    PlatformDatabase,
    PlatformDatabaseSettings,
    PlatformStore,
    RevisionConflict,
    SolveJobStore,
)
from scheduler.platform.jobs import CANCELLED, COMPLETED, FAILED, JobIdempotencyConflict
from scheduler.platform.worker import ExecutionOutcome, SolveWorker
from scheduler.platform.runtime import load_runtime_workspace


PASSWORD = "Correct-Horse-2026!"


def _platform(tmp_path: Path) -> tuple[PlatformStore, Any]:
    store = PlatformStore(PlatformDatabase(PlatformDatabaseSettings(path=tmp_path / "scheduler.db")))
    assert store.initialize() == (1, 2, 3, 4, 5, 6)
    organization = store.create_organization(slug="school-a", name="学校 A")
    store.save_workspace(
        organization.id,
        {"io": {}, "rules": {"version": 1}, "temporary_rules": {"active": []}},
        expected_revision=0,
        actor_user_id="bootstrap",
        reason="initial",
    )
    return store, organization


def test_job_creation_is_idempotent_and_tenant_scoped(tmp_path: Path) -> None:
    store, school_a = _platform(tmp_path)
    school_b = store.create_organization(slug="school-b", name="学校 B")
    store.save_workspace(school_b.id, {"rules": {}}, expected_revision=0)
    jobs = SolveJobStore(store)

    first = jobs.create_job(
        school_a.id,
        {"mode": "joint", "time_limit_seconds": 30},
        created_by="admin-a",
        workspace_revision=1,
        idempotency_key="request-001",
    )
    repeated = jobs.create_job(
        school_a.id,
        {"mode": "joint", "time_limit_seconds": 30},
        created_by="admin-a",
        workspace_revision=1,
        idempotency_key="request-001",
    )

    assert first.created is True
    assert repeated.created is False
    assert repeated.job.id == first.job.id
    assert repeated.job.request["mode"] == "joint"
    assert [job.id for job in jobs.list_jobs(school_a.id)] == [first.job.id]
    with pytest.raises(JobNotFound):
        jobs.get_job(school_b.id, first.job.id)

    with pytest.raises(JobIdempotencyConflict):
        jobs.create_job(
            school_a.id,
            {"mode": "night", "time_limit_seconds": 60},
            created_by="admin-a",
            workspace_revision=1,
            idempotency_key="request-001",
        )
    with pytest.raises(JobIdempotencyConflict):
        jobs.create_job(
            school_a.id,
            {"mode": "joint", "time_limit_seconds": 30},
            created_by="admin-b",
            workspace_revision=1,
            idempotency_key="request-001",
        )
    with pytest.raises(JobIdempotencyConflict):
        jobs.create_job(
            school_a.id,
            {"mode": "joint", "time_limit_seconds": 30},
            created_by="admin-a",
            workspace_revision=2,
            idempotency_key="request-001",
        )


def test_job_creation_checks_expected_workspace_revision_inside_enqueue_transaction(tmp_path: Path) -> None:
    store, organization = _platform(tmp_path)
    jobs = SolveJobStore(store)

    first = jobs.create_job(
        organization.id,
        {"mode": "joint"},
        created_by="operator",
        workspace_revision=1,
        expected_workspace_revision=1,
        idempotency_key="revision-bound-1",
    ).job
    assert first.workspace_revision == 1

    store.save_workspace(
        organization.id,
        {"rules": {"version": 2}},
        expected_revision=1,
        actor_user_id="admin",
        reason="changed after confirmation",
    )
    with pytest.raises(RevisionConflict):
        jobs.create_job(
            organization.id,
            {"mode": "joint"},
            created_by="operator",
            workspace_revision=1,
            expected_workspace_revision=1,
            idempotency_key="revision-bound-2",
        )


def test_worker_claim_heartbeat_cancel_and_terminal_state_are_atomic(tmp_path: Path) -> None:
    store, organization = _platform(tmp_path)
    clock = [datetime(2026, 7, 26, 8, 0, tzinfo=timezone.utc)]
    jobs = SolveJobStore(store, now=lambda: clock[0])
    queued = jobs.create_job(
        organization.id,
        {"mode": "joint"},
        created_by="operator",
        workspace_revision=1,
    ).job
    claimed = jobs.claim_next(organization.id, worker_id="worker-1")

    assert claimed is not None and claimed.id == queued.id and claimed.status == "running"
    assert jobs.claim_next(organization.id, worker_id="worker-2") is None
    clock[0] += timedelta(seconds=10)
    jobs.heartbeat(claimed.id, worker_id="worker-1")
    attached = jobs.attach_execution(
        claimed.id,
        worker_id="worker-1",
        run_dir="outputs/tenants/a/web_runs/run_1",
        process_id=1234,
    )
    assert attached.process_id == 1234
    requested = jobs.request_cancel(organization.id, claimed.id, actor_user_id="operator")
    assert requested.status == "cancel_requested"
    assert jobs.cancellation_requested(claimed.id, worker_id="worker-1") is True
    finished = jobs.finish(
        claimed.id,
        worker_id="worker-1",
        status=COMPLETED,
        result={"status": "completed"},
    )
    assert finished.status == CANCELLED
    assert finished.completed_at

    events = store.list_audit_events(organization.id)
    assert {event["event_type"] for event in events} >= {
        "solve_job.queued",
        "solve_job.started",
        "solve_job.cancel_requested",
        "solve_job.cancelled",
    }


def test_stale_worker_lease_is_failed_before_next_job_claim(tmp_path: Path) -> None:
    store, organization = _platform(tmp_path)
    clock = [datetime(2026, 7, 26, 8, 0, tzinfo=timezone.utc)]
    jobs = SolveJobStore(store, now=lambda: clock[0])
    first = jobs.create_job(
        organization.id,
        {"mode": "joint"},
        created_by="operator",
        workspace_revision=1,
    ).job
    second = jobs.create_job(
        organization.id,
        {"mode": "night"},
        created_by="operator",
        workspace_revision=1,
    ).job
    assert jobs.claim_next(organization.id, worker_id="dead-worker").id == first.id  # type: ignore[union-attr]

    clock[0] += timedelta(minutes=5)
    failed = jobs.fail_stale_leases(
        organization.id,
        heartbeat_before=clock[0] - timedelta(minutes=2),
    )
    assert failed == [first.id]
    assert jobs.get_job(organization.id, first.id).status == FAILED
    assert jobs.claim_next(organization.id, worker_id="replacement").id == second.id  # type: ignore[union-attr]


def test_solve_worker_executes_injected_job_and_records_failures(tmp_path: Path) -> None:
    store, organization = _platform(tmp_path)
    jobs = SolveJobStore(store)
    successful = jobs.create_job(
        organization.id,
        {"mode": "joint"},
        created_by="operator",
        workspace_revision=1,
    ).job

    def success_executor(job, control):
        assert job.id == successful.id
        control.attach_execution(run_dir="run-dir", process_id=9)
        control.heartbeat()
        return ExecutionOutcome(status=COMPLETED, result={"objective": 42})

    worker = SolveWorker(
        jobs,
        organization_id=organization.id,
        worker_id="worker-success",
        executor=success_executor,
    )
    assert worker.run_once() is True
    completed = jobs.get_job(organization.id, successful.id)
    assert completed.status == COMPLETED
    assert completed.result == {"objective": 42}
    assert completed.run_dir == "run-dir"

    failing = jobs.create_job(
        organization.id,
        {"mode": "night"},
        created_by="operator",
        workspace_revision=1,
    ).job

    def failing_executor(_job, _control):
        raise RuntimeError("synthetic solver failure")

    failed_worker = SolveWorker(
        jobs,
        organization_id=organization.id,
        worker_id="worker-failure",
        executor=failing_executor,
    )
    assert failed_worker.run_once() is True
    failed = jobs.get_job(organization.id, failing.id)
    assert failed.status == FAILED
    assert failed.error_code == "worker_execution_error"
    assert "synthetic solver failure" in failed.error_message


def test_default_worker_executes_the_workspace_revision_captured_at_enqueue(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scheduler.app import solve_service

    store, organization = _platform(tmp_path)
    queued = SolveJobStore(store).create_job(
        organization.id,
        {"mode": "joint"},
        created_by="operator",
        workspace_revision=1,
    ).job
    store.save_workspace(
        organization.id,
        {"io": {}, "rules": {"version": 2}, "temporary_rules": {"active": []}},
        expected_revision=1,
        actor_user_id="admin",
        reason="changed after enqueue",
    )
    monkeypatch.setenv("SCHEDULER_STATE_BACKEND", "sqlite")
    monkeypatch.setenv("SCHEDULER_DATABASE_PATH", str(store.database.path))
    monkeypatch.setenv("SCHEDULER_ORGANIZATION_ID", organization.id)
    monkeypatch.delenv("SCHEDULER_WORKSPACE_REVISION", raising=False)

    def fake_start(_request):
        workspace = load_runtime_workspace()
        assert workspace is not None
        assert workspace.revision == 1
        assert workspace.payload["rules"]["version"] == 1
        return {"status": "running", "run_dir": str(tmp_path / "run"), "process_id": 42}

    monkeypatch.setattr(solve_service, "start_solve", fake_start)
    monkeypatch.setattr(
        solve_service,
        "get_solve_status",
        lambda: {"status": "completed", "run_dir": str(tmp_path / "run"), "message": "done"},
    )

    jobs = SolveJobStore(store)
    worker = SolveWorker(
        jobs,
        organization_id=organization.id,
        worker_id="snapshot-worker",
        poll_seconds=0.1,
    )
    assert worker.run_once() is True
    completed = jobs.get_job(organization.id, queued.id)
    assert completed.status == COMPLETED
    assert completed.process_id == 42
    assert "SCHEDULER_WORKSPACE_REVISION" not in os.environ


def test_http_job_api_queues_idempotently_and_cancels_without_web_process_globals(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, organization = _platform(tmp_path)
    auth = AuthService(store, password_hasher=PasswordHasher(iterations=100_000))
    auth.create_user(
        organization.id,
        username="operator",
        display_name="操作员",
        role="scheduler_operator",
        password=PASSWORD,
    )
    monkeypatch.setenv("SCHEDULER_STATE_BACKEND", "sqlite")
    monkeypatch.setenv("SCHEDULER_DATABASE_PATH", str(store.database.path))
    monkeypatch.setenv("SCHEDULER_ORGANIZATION_ID", organization.id)
    monkeypatch.setenv("SCHEDULER_AUTH_MODE", "required")
    monkeypatch.setenv("SCHEDULER_COOKIE_SECURE", "false")
    monkeypatch.setenv("SCHEDULER_SOLVE_MODE", "async")
    monkeypatch.setattr(
        job_api,
        "build_solve_readiness",
        lambda _mode: {"summary": {"can_start_solver": True}, "items": []},
    )

    server = _HttpServer()
    try:
        cookies = server.login()
        headers = {
            "Cookie": "; ".join(f"{key}={value}" for key, value in cookies.items()),
            "X-CSRF-Token": cookies["scheduler_csrf"],
            "Idempotency-Key": "solve-request-001",
        }
        status, first = server.request(
            "POST",
            "/api/solve/start",
            body={"mode": "joint", "time_limit_seconds": 60, "workers": 2},
            headers=headers,
        )
        assert status == 202 and first["created"] is True and first["status"] == "queued"
        status, repeated = server.request(
            "POST",
            "/api/solve/start",
            body={"mode": "joint", "time_limit_seconds": 60, "workers": 2},
            headers=headers,
        )
        assert status == 202 and repeated["created"] is False and repeated["id"] == first["id"]

        status, current = server.request("GET", "/api/solve/status", headers={"Cookie": headers["Cookie"]})
        assert status == 200 and current["job_id"] == first["id"] and current["status"] == "queued"
        status, listing = server.request("GET", "/api/solve/jobs", headers={"Cookie": headers["Cookie"]})
        assert status == 200 and listing["count"] == 1
        status, cancelled = server.request(
            "POST",
            f"/api/solve/jobs/{first['id']}/cancel",
            body={},
            headers=headers,
        )
        assert status == 200 and cancelled["status"] == CANCELLED
    finally:
        server.close()


class _HttpServer:
    def __init__(self) -> None:
        from http.server import ThreadingHTTPServer

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), SchedulerWebHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def request(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, dict[str, Any]]:
        raw = None if body is None else json.dumps(body).encode("utf-8")
        request_headers = dict(headers or {})
        if raw is not None:
            request_headers.update({"Content-Type": "application/json", "Content-Length": str(len(raw))})
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_address[1], timeout=10)
        try:
            connection.request(method, path, body=raw, headers=request_headers)
            response = connection.getresponse()
            return response.status, json.loads(response.read().decode("utf-8"))
        finally:
            connection.close()

    def login(self) -> dict[str, str]:
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_address[1], timeout=10)
        body = json.dumps({"username": "operator", "password": PASSWORD}).encode("utf-8")
        try:
            connection.request(
                "POST",
                "/api/auth/login",
                body=body,
                headers={"Content-Type": "application/json", "Content-Length": str(len(body))},
            )
            response = connection.getresponse()
            assert response.status == 200, response.read().decode("utf-8")
            cookies: dict[str, str] = {}
            for name, value in response.getheaders():
                if name.lower() == "set-cookie":
                    parsed = SimpleCookie()
                    parsed.load(value)
                    cookies.update({key: morsel.value for key, morsel in parsed.items()})
            response.read()
            return cookies
        finally:
            connection.close()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
