from __future__ import annotations

import argparse
import json
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from http.cookiejar import CookieJar
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import HTTPCookieProcessor, Request, build_opener


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scheduler.platform.auth import AuthService, PasswordHasher  # noqa: E402
from scheduler.platform.backup import create_database_backup, inspect_database_backup  # noqa: E402
from scheduler.platform.database import PlatformDatabase, PlatformDatabaseSettings  # noqa: E402
from scheduler.platform.jobs import SolveJobStore  # noqa: E402
from scheduler.platform.migration import import_yaml_workspace  # noqa: E402
from scheduler.platform.store import PlatformStore  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Run an isolated single-school SaaS release-candidate audit")
    parser.add_argument("--output", type=Path, default=None, help="Optional JSON evidence file")
    args = parser.parse_args()

    with tempfile.TemporaryDirectory(prefix="scheduler-saas-audit-") as temporary:
        result = _run_audit(Path(temporary))
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output is not None:
        output_path = Path(args.output).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered + "\n", encoding="utf-8")
    sys.stdout.write(rendered + "\n")


def _run_audit(root: Path) -> dict[str, Any]:
    database_path = root / "platform" / "scheduler.db"
    migration = import_yaml_workspace(
        database_path=database_path,
        yaml_path=REPO_ROOT / "deploy" / "seed" / "blank_school.yaml",
        organization_slug="release-school",
        organization_name="发布候选学校",
        actor_user_id="release-audit",
    )
    store = PlatformStore(PlatformDatabase(PlatformDatabaseSettings(path=database_path)))
    store.initialize()
    organization = store.get_organization_by_slug("release-school")
    password = secrets.token_urlsafe(24)
    AuthService(store, password_hasher=PasswordHasher(iterations=100_000)).create_user(
        organization.id,
        username="release-admin",
        display_name="发布验收管理员",
        role="academic_admin",
        password=password,
    )
    workspace = store.load_workspace(organization.id)
    _expect(workspace is not None, "release workspace was not initialized")
    _expect(workspace.payload.get("io") == {}, "release seed contains IO overrides")
    _expect(workspace.payload.get("rules") == {}, "release seed contains rule overrides")
    _expect(
        workspace.payload.get("change_audit", {}).get("entries") == [],
        "release seed contains change history",
    )
    seeded_job = SolveJobStore(store).create_job(
        organization.id,
        {"mode": "joint", "time_limit_seconds": 10, "workers": 1},
        created_by="release-audit",
        workspace_revision=workspace.revision,
        idempotency_key="release-audit-job",
    ).job

    port = _free_port()
    environment = os.environ.copy()
    environment.update(
        {
            "PYTHONUTF8": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "SCHEDULER_STATE_BACKEND": "sqlite",
            "SCHEDULER_DATABASE_PATH": str(database_path),
            "SCHEDULER_ORGANIZATION_ID": organization.id,
            "SCHEDULER_ORGANIZATION_SLUG": organization.slug,
            "SCHEDULER_AUTH_MODE": "required",
            "SCHEDULER_COOKIE_SECURE": "false",
            "SCHEDULER_SOLVE_MODE": "async",
            "SCHEDULER_LOGIN_RATE_LIMIT_SECRET": secrets.token_urlsafe(32),
        }
    )
    web = _start_process(
        [sys.executable, "-m", "scheduler.app.web", "--host", "127.0.0.1", "--port", str(port)],
        environment,
    )
    worker: subprocess.Popen[str] | None = None
    checks: list[dict[str, Any]] = []
    try:
        client = _HttpClient(f"http://127.0.0.1:{port}")
        live = _wait_json(client, "/api/health/live", expected_status=200)
        checks.append({"name": "web_liveness", "status": live["status"]})

        ready, ready_headers = client.json_request("GET", "/api/health/ready")
        _expect(ready.get("ready") is True, "Web readiness failed before Worker startup")
        _expect(ready.get("checks", {}).get("worker") == "unavailable", "unexpected Worker heartbeat")
        _expect(ready_headers.get("x-content-type-options") == "nosniff", "security headers missing")
        checks.append({"name": "database_workspace_readiness", "status": "passed"})

        session, _ = client.json_request(
            "POST",
            "/api/auth/login",
            {
                "organization_slug": organization.slug,
                "username": "release-admin",
                "password": password,
            },
        )
        _expect(session.get("authenticated") is True, "administrator login failed")
        csrf = client.cookie("scheduler_csrf")
        _expect(bool(csrf), "CSRF cookie was not issued")
        access, _ = client.json_request("GET", "/api/access/context")
        _expect(access.get("role", {}).get("key") == "academic_admin", "server-side role mismatch")
        checks.append({"name": "auth_session_csrf_rbac", "status": "passed"})

        quota, _ = client.json_request(
            "POST",
            "/api/model/quota",
            {"request_limit": 100, "token_limit": 100_000, "cost_limit_microunits": 1_000_000},
            headers={"X-CSRF-Token": csrf},
        )
        _expect(quota.get("request_limit") == 100, "model quota was not persisted")
        checks.append({"name": "model_usage_quota", "status": "passed"})

        jobs_before, _ = client.json_request("GET", "/api/solve/jobs")
        job_id = seeded_job.id
        _expect(
            jobs_before.get("jobs", [{}])[0].get("id") == job_id
            and jobs_before.get("jobs", [{}])[0].get("status") == "queued",
            "durable solve job was not visible through the tenant API",
        )
        cancelled, _ = client.json_request(
            "POST",
            f"/api/solve/jobs/{job_id}/cancel",
            {},
            headers={"X-CSRF-Token": csrf},
        )
        _expect(cancelled.get("status") == "cancelled", "queued job was not cancelled safely")
        checks.append({"name": "durable_job_list_cancel", "status": "passed", "job_id": job_id})

        worker = _start_process(
            [sys.executable, "-m", "scheduler.platform.worker", "--poll-seconds", "0.2"],
            environment,
        )
        worker_ready = _wait_for_worker(client)
        _expect(worker_ready.get("checks", {}).get("worker") == "healthy", "Worker heartbeat unavailable")
        jobs, _ = client.json_request("GET", "/api/solve/jobs")
        _expect(jobs.get("jobs", [{}])[0].get("status") == "cancelled", "cancelled job state changed")
        checks.append({"name": "independent_worker_heartbeat", "status": "passed"})

        backup_path = root / "backups" / "scheduler.db"
        backup = create_database_backup(database_path, backup_path)
        verified = inspect_database_backup(backup_path)
        _expect(backup.get("integrity") == "ok" and verified.get("integrity") == "ok", "backup verification failed")
        checks.append({"name": "online_backup_integrity", "status": "passed"})
    finally:
        _stop_process(worker)
        _stop_process(web)

    return {
        "schema_version": "scheduler.saas_release_candidate_audit.v1",
        "status": "passed",
        "migration_versions": migration.get("migration_versions", []),
        "checks": checks,
        "checks_passed": len(checks),
        "notes": [
            "The queued task was cancelled before Worker startup; no formal solver run was launched.",
            "The audit used an isolated temporary database and removed it on completion.",
        ],
    }


class _HttpClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.cookies = CookieJar()
        self.opener = build_opener(HTTPCookieProcessor(self.cookies))

    def cookie(self, name: str) -> str:
        return next((item.value for item in self.cookies if item.name == name), "")

    def json_request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        headers: dict[str, str] | None = None,
    ) -> tuple[dict[str, Any], dict[str, str]]:
        raw = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request_headers = dict(headers or {})
        if raw is not None:
            request_headers["Content-Type"] = "application/json"
        request = Request(self.base_url + path, data=raw, headers=request_headers, method=method)
        try:
            with self.opener.open(request, timeout=10) as response:
                status = response.status
                body = response.read()
                response_headers = {key.lower(): value for key, value in response.headers.items()}
        except HTTPError as exc:
            status = exc.code
            body = exc.read()
            response_headers = {key.lower(): value for key, value in exc.headers.items()}
        if status < 200 or status >= 300:
            raise RuntimeError(f"{method} {path} returned HTTP {status}: {body.decode('utf-8', errors='replace')}")
        decoded = json.loads(body.decode("utf-8"))
        if not isinstance(decoded, dict):
            raise RuntimeError(f"{method} {path} did not return a JSON object")
        return decoded, response_headers


def _wait_json(client: _HttpClient, path: str, *, expected_status: int, timeout: float = 15) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last_error = ""
    while time.monotonic() < deadline:
        try:
            payload, _ = client.json_request("GET", path)
            if expected_status == 200:
                return payload
        except (OSError, RuntimeError, URLError) as exc:
            last_error = str(exc)
        time.sleep(0.1)
    raise RuntimeError(f"timed out waiting for {path}: {last_error}")


def _wait_for_worker(client: _HttpClient, timeout: float = 15) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        payload, _ = client.json_request("GET", "/api/health/ready")
        if payload.get("checks", {}).get("worker") == "healthy":
            return payload
        time.sleep(0.1)
    raise RuntimeError("timed out waiting for Worker heartbeat")


def _start_process(argv: list[str], environment: dict[str, str]) -> subprocess.Popen[str]:
    return subprocess.Popen(
        argv,
        cwd=str(REPO_ROOT),
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
    )


def _stop_process(process: subprocess.Popen[str] | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _expect(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


if __name__ == "__main__":
    main()
