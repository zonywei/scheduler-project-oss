from __future__ import annotations

import http.client
import json
import threading
from datetime import datetime, timedelta, timezone
from http.cookies import SimpleCookie
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import pytest

from scheduler.app import web as web_module
from scheduler.app.web import SchedulerWebHandler, _validate_server_startup
from scheduler.platform import (
    AuthenticationError,
    AuthService,
    CsrfValidationError,
    PasswordHasher,
    PlatformDatabase,
    PlatformDatabaseSettings,
    PlatformStore,
)
from scheduler.platform.cli import _create_user, _ensure_user


PASSWORD = "Correct-Horse-2026!"


def _store(tmp_path: Path) -> PlatformStore:
    store = PlatformStore(
        PlatformDatabase(PlatformDatabaseSettings(path=tmp_path / "scheduler.db"))
    )
    assert store.initialize() == (1, 2, 3, 4, 5, 6)
    return store


def _fast_auth(store: PlatformStore, *, now: Any = None) -> AuthService:
    return AuthService(store, password_hasher=PasswordHasher(iterations=100_000), now=now)


def test_password_hash_and_session_tokens_are_not_stored_in_plaintext(tmp_path: Path) -> None:
    store = _store(tmp_path)
    organization = store.create_organization(slug="school-a", name="学校 A")
    auth = _fast_auth(store)
    user = auth.create_user(
        organization.id,
        username="Scheduler.Admin",
        display_name="排课管理员",
        role="academic_admin",
        password=PASSWORD,
    )

    issued = auth.login(organization_slug="school-a", username="scheduler.admin", password=PASSWORD)
    assert issued.user == user
    assert auth.password_hasher.verify(PASSWORD, _password_hash(store, user.user_id)) is True
    assert auth.password_hasher.verify("incorrect-password", _password_hash(store, user.user_id)) is False

    with store.database.connect() as connection:
        session = connection.execute(
            "SELECT token_hash, csrf_token_hash FROM sessions WHERE user_id = ?",
            (user.user_id,),
        ).fetchone()
    assert session is not None
    assert str(session["token_hash"]) != issued.session_token
    assert str(session["csrf_token_hash"]) != issued.csrf_token
    assert PASSWORD not in _password_hash(store, user.user_id)


def test_sessions_require_csrf_for_writes_and_can_be_revoked_or_expire(tmp_path: Path) -> None:
    store = _store(tmp_path)
    organization = store.create_organization(slug="school-a", name="学校 A")
    clock = [datetime(2026, 7, 26, tzinfo=timezone.utc)]
    auth = _fast_auth(store, now=lambda: clock[0])
    user = auth.create_user(
        organization.id,
        username="operator",
        display_name="操作员",
        role="scheduler_operator",
        password=PASSWORD,
    )
    issued = auth.login(
        organization_slug=organization.slug,
        username=user.username,
        password=PASSWORD,
        ttl_seconds=300,
    )

    assert auth.resolve_session(issued.session_token) == user
    with pytest.raises(CsrfValidationError):
        auth.resolve_session(issued.session_token, require_csrf=True)
    with pytest.raises(CsrfValidationError):
        auth.resolve_session(issued.session_token, csrf_token="wrong", require_csrf=True)
    assert auth.resolve_session(
        issued.session_token,
        csrf_token=issued.csrf_token,
        require_csrf=True,
    ) == user

    assert auth.revoke_session(issued.session_token) is True
    assert auth.revoke_session(issued.session_token) is False
    with pytest.raises(AuthenticationError):
        auth.resolve_session(issued.session_token)

    second = auth.login(organization_slug=organization.slug, username=user.username, password=PASSWORD, ttl_seconds=300)
    clock[0] += timedelta(seconds=301)
    with pytest.raises(AuthenticationError):
        auth.resolve_session(second.session_token)


def test_account_expiry_caps_sessions_and_blocks_relogin(tmp_path: Path) -> None:
    store = _store(tmp_path)
    organization = store.create_organization(slug="school-a", name="学校 A")
    clock = [datetime(2026, 7, 26, 8, 30, tzinfo=timezone.utc)]
    expiry = clock[0] + timedelta(days=3)
    auth = _fast_auth(store, now=lambda: clock[0])
    user = auth.create_user(
        organization.id,
        username="trial-viewer",
        display_name="三天试用账号",
        role="viewer",
        password=PASSWORD,
        expires_at=expiry,
    )

    issued = auth.login(
        organization_slug=organization.slug,
        username=user.username,
        password=PASSWORD,
        ttl_seconds=7 * 24 * 60 * 60,
    )
    assert issued.expires_at == expiry.isoformat(timespec="microseconds")
    assert auth.resolve_session(issued.session_token) == user

    clock[0] = expiry
    with pytest.raises(AuthenticationError, match="过期"):
        auth.resolve_session(issued.session_token)
    with pytest.raises(AuthenticationError):
        auth.login(
            organization_slug=organization.slug,
            username=user.username,
            password=PASSWORD,
        )


def test_short_passwords_are_limited_to_bounded_non_admin_trials(tmp_path: Path) -> None:
    store = _store(tmp_path)
    organization = store.create_organization(slug="school-a", name="学校 A")
    clock = datetime(2026, 7, 26, 8, 30, tzinfo=timezone.utc)
    auth = _fast_auth(store, now=lambda: clock)

    trial = auth.create_user(
        organization.id,
        username="short-trial",
        display_name="短期只读试用",
        role="viewer",
        password="test0101",
        expires_at=clock + timedelta(days=3),
    )
    assert auth.login(
        organization_slug=organization.slug,
        username=trial.username,
        password="test0101",
    ).user == trial

    operator_trial = auth.create_user(
        organization.id,
        username="short-operator-trial",
        display_name="短期教务测试员",
        role="trial_operator",
        password="test0202",
        expires_at=clock + timedelta(days=3),
    )
    assert auth.login(
        organization_slug=organization.slug,
        username=operator_trial.username,
        password="test0202",
    ).user == operator_trial

    with pytest.raises(ValueError, match="12-256"):
        auth.create_user(
            organization.id,
            username="permanent-viewer",
            display_name="长期只读账号",
            role="viewer",
            password="test0202",
        )
    with pytest.raises(ValueError, match="12-256"):
        auth.create_user(
            organization.id,
            username="short-admin",
            display_name="短密码管理员",
            role="academic_admin",
            password="test0303",
            expires_at=clock + timedelta(days=3),
        )
    with pytest.raises(ValueError, match="12-256"):
        auth.create_user(
            organization.id,
            username="long-trial",
            display_name="超期试用账号",
            role="viewer",
            password="test0404",
            expires_at=clock + timedelta(days=8),
        )


def test_usernames_and_sessions_are_tenant_scoped(tmp_path: Path) -> None:
    store = _store(tmp_path)
    school_a = store.create_organization(slug="school-a", name="学校 A")
    school_b = store.create_organization(slug="school-b", name="学校 B")
    auth = _fast_auth(store)
    user_a = auth.create_user(
        school_a.id,
        username="operator",
        display_name="A 操作员",
        role="scheduler_operator",
        password=PASSWORD,
    )
    user_b = auth.create_user(
        school_b.id,
        username="operator",
        display_name="B 操作员",
        role="viewer",
        password=PASSWORD,
    )

    assert auth.login(organization_slug="school-a", username="operator", password=PASSWORD).user == user_a
    assert auth.login(organization_slug="school-b", username="operator", password=PASSWORD).user == user_b
    with pytest.raises(ValueError, match="already exists"):
        auth.create_user(
            school_a.id,
            username="OPERATOR",
            display_name="重复用户",
            role="viewer",
            password=PASSWORD,
        )
    with pytest.raises(AuthenticationError):
        auth.login(organization_slug="school-b", username="missing", password=PASSWORD)


def test_create_user_cli_reads_password_only_from_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = _store(tmp_path)
    organization = store.create_organization(slug="school-a", name="学校 A")
    monkeypatch.setenv("TEST_BOOTSTRAP_PASSWORD", PASSWORD)

    expiry = "2026-07-29T08:30:00.000000+00:00"
    result = _create_user(
        store.database.path,
        slug=organization.slug,
        username="admin",
        display_name="管理员",
        role="academic_admin",
        password_env="TEST_BOOTSTRAP_PASSWORD",
        expires_at=expiry,
    )

    assert result["user"]["username"] == "admin"
    assert result["user"]["expires_at"] == expiry
    assert PASSWORD not in json.dumps(result, ensure_ascii=False)
    with store.database.connect() as connection:
        row = connection.execute("SELECT password_hash FROM users WHERE id = ?", (result["user"]["id"],)).fetchone()
    assert row is not None and PASSWORD not in str(row["password_hash"])


def test_ensure_user_reads_secret_file_is_idempotent_and_rotates_safely(tmp_path: Path) -> None:
    store = _store(tmp_path)
    organization = store.create_organization(slug="school-a", name="学校 A")
    secret_file = tmp_path / "admin_password"
    secret_file.write_text(PASSWORD + "\n", encoding="utf-8")

    created = _ensure_user(
        store.database.path,
        slug=organization.slug,
        username="Admin",
        display_name="教务管理员",
        role="academic_admin",
        password_env="",
        password_file=secret_file,
    )
    unchanged = _ensure_user(
        store.database.path,
        slug=organization.slug,
        username="admin",
        display_name="教务管理员",
        role="academic_admin",
        password_env="",
        password_file=secret_file,
    )

    assert created["created"] is True
    assert created["changed_fields"] == ["account"]
    assert unchanged["created"] is False
    assert unchanged["changed_fields"] == []
    assert PASSWORD not in json.dumps(created, ensure_ascii=False)

    auth = AuthService(store)
    issued = auth.login(organization_slug=organization.slug, username="admin", password=PASSWORD)
    rotated_password = "Rotated-Secret-2026!"
    secret_file.write_text(rotated_password, encoding="utf-8")
    rotated = _ensure_user(
        store.database.path,
        slug=organization.slug,
        username="admin",
        display_name="教务管理员",
        role="academic_admin",
        password_env="",
        password_file=secret_file,
    )

    assert rotated["changed_fields"] == ["password"]
    with pytest.raises(AuthenticationError):
        auth.login(organization_slug=organization.slug, username="admin", password=PASSWORD)
    with pytest.raises(AuthenticationError):
        auth.resolve_session(issued.session_token)
    assert auth.login(
        organization_slug=organization.slug,
        username="admin",
        password=rotated_password,
    ).user.role == "academic_admin"


def test_required_http_auth_ignores_spoofed_roles_and_enforces_csrf_and_artifact_scope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path)
    organization = store.create_organization(slug="school-a", name="学校 A")
    store.save_workspace(
        organization.id,
        {"io": {}, "rules": {}, "temporary_rules": {"active": []}, "academic_affairs": {}},
        expected_revision=0,
        actor_user_id="bootstrap",
        reason="test bootstrap",
    )
    auth = _fast_auth(store)
    auth.create_user(
        organization.id,
        username="operator",
        display_name="排课操作员",
        role="scheduler_operator",
        password=PASSWORD,
    )
    auth.create_user(
        organization.id,
        username="viewer",
        display_name="只读用户",
        role="viewer",
        password=PASSWORD,
    )
    monkeypatch.setenv("SCHEDULER_STATE_BACKEND", "sqlite")
    monkeypatch.setenv("SCHEDULER_DATABASE_PATH", str(store.database.path))
    monkeypatch.setenv("SCHEDULER_ORGANIZATION_ID", organization.id)
    monkeypatch.setenv("SCHEDULER_AUTH_MODE", "required")
    monkeypatch.setenv("SCHEDULER_COOKIE_SECURE", "false")

    server = _TestServer(SchedulerWebHandler)
    try:
        status, payload, _ = server.json_request("GET", "/api/auth/session")
        assert status == 200 and payload["authenticated"] is False
        status, payload, _ = server.json_request("GET", "/api/access/context")
        assert status == 401 and payload["authentication_required"] is True

        operator_cookies = server.login("operator")
        spoofed_headers = {
            "Cookie": _cookie_header(operator_cookies),
            "X-Scheduler-Role": "viewer",
        }
        status, payload, _ = server.json_request("GET", "/api/access/context", headers=spoofed_headers)
        assert status == 200
        assert payload["role"]["key"] == "scheduler_operator"
        assert payload["authentication"]["user"]["organization_id"] == organization.id

        status, payload, _ = server.json_request("POST", "/api/config", body={}, headers=spoofed_headers)
        assert status == 403 and payload["csrf_failed"] is True
        spoofed_headers["X-CSRF-Token"] = operator_cookies["scheduler_csrf"]
        status, payload, _ = server.json_request("POST", "/api/config", body={}, headers=spoofed_headers)
        assert status == 200 and payload["overrides"]["_meta"]["updated_by"]

        viewer_cookies = server.login("viewer")
        viewer_headers = {
            "Cookie": _cookie_header(viewer_cookies),
            "X-CSRF-Token": viewer_cookies["scheduler_csrf"],
            "X-Scheduler-Role": "academic_admin",
        }
        status, payload, _ = server.json_request("POST", "/api/config", body={}, headers=viewer_headers)
        assert status == 403 and payload["permission_denied"] is True

        forbidden = urlencode({"path": str(Path(__file__).resolve().parents[3] / "README.md")})
        status, payload, _ = server.json_request("GET", f"/api/file?{forbidden}", headers=viewer_headers)
        assert status == 403 and payload["error"] == "invalid download path"

        status, payload, logout_headers = server.json_request(
            "POST",
            "/api/auth/logout",
            body={},
            headers=viewer_headers,
        )
        assert status == 200 and payload["authenticated"] is False
        assert len([value for name, value in logout_headers if name.lower() == "set-cookie"]) == 2
        status, _, _ = server.json_request("GET", "/api/access/context", headers={"Cookie": _cookie_header(viewer_cookies)})
        assert status == 401
    finally:
        server.close()


def test_health_endpoints_are_public_and_send_browser_security_headers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path)
    organization = store.create_organization(slug="school-a", name="学校 A")
    store.save_workspace(
        organization.id,
        {"io": {}, "rules": {}, "temporary_rules": {"active": []}, "academic_affairs": {}},
        expected_revision=0,
        actor_user_id="bootstrap",
    )
    monkeypatch.setenv("SCHEDULER_STATE_BACKEND", "sqlite")
    monkeypatch.setenv("SCHEDULER_DATABASE_PATH", str(store.database.path))
    monkeypatch.setenv("SCHEDULER_ORGANIZATION_ID", organization.id)
    monkeypatch.setenv("SCHEDULER_AUTH_MODE", "required")
    monkeypatch.setenv("SCHEDULER_COOKIE_SECURE", "false")

    server = _TestServer(SchedulerWebHandler)
    try:
        status, payload, headers = server.json_request("GET", "/api/health/live")
        assert status == 200 and payload["status"] == "up"
        normalized = {name.lower(): value for name, value in headers}
        assert normalized["server"] == "SchedulerWeb/0.2"
        assert normalized["x-content-type-options"] == "nosniff"
        assert normalized["x-frame-options"] == "DENY"
        assert "frame-ancestors 'none'" in normalized["content-security-policy"]

        status, payload, _ = server.json_request("GET", "/api/health/ready")
        assert status == 200 and payload["ready"] is True
        assert payload["checks"]["worker"] == "unavailable"
    finally:
        server.close()


def test_unhandled_http_error_does_not_disclose_internal_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SCHEDULER_AUTH_MODE", "disabled")

    def fail_config(_mode: str) -> dict[str, Any]:
        raise Exception("private database path and credential")

    monkeypatch.setattr(web_module, "load_effective_payload", fail_config)
    server = _TestServer(SchedulerWebHandler)
    try:
        status, payload, _ = server.json_request("GET", "/api/config")
        assert status == 500
        assert payload["error"] == "服务器内部错误"
        assert len(payload["error_id"]) == 12
        assert "private" not in json.dumps(payload)
    finally:
        server.close()


def test_non_loopback_startup_rejects_placeholder_login_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SCHEDULER_AUTH_MODE", "required")
    monkeypatch.setenv("SCHEDULER_STATE_BACKEND", "sqlite")
    monkeypatch.setenv("SCHEDULER_COOKIE_SECURE", "true")
    monkeypatch.setenv("SCHEDULER_LOGIN_RATE_LIMIT_SECRET", "replace-before-production-000000")

    with pytest.raises(RuntimeError, match="random SCHEDULER_LOGIN_RATE_LIMIT_SECRET"):
        _validate_server_startup("0.0.0.0")


def _password_hash(store: PlatformStore, user_id: str) -> str:
    with store.database.connect() as connection:
        row = connection.execute("SELECT password_hash FROM users WHERE id = ?", (user_id,)).fetchone()
    assert row is not None
    return str(row["password_hash"])


def _cookie_header(cookies: dict[str, str]) -> str:
    return "; ".join(f"{name}={value}" for name, value in cookies.items())


class _TestServer:
    def __init__(self, handler: type[SchedulerWebHandler]) -> None:
        from http.server import ThreadingHTTPServer

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def json_request(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, dict[str, Any], list[tuple[str, str]]]:
        raw = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
        request_headers = dict(headers or {})
        if raw is not None:
            request_headers["Content-Type"] = "application/json"
            request_headers["Content-Length"] = str(len(raw))
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_address[1], timeout=10)
        try:
            connection.request(method, path, body=raw, headers=request_headers)
            response = connection.getresponse()
            response_headers = response.getheaders()
            payload = json.loads(response.read().decode("utf-8"))
            return response.status, payload, response_headers
        finally:
            connection.close()

    def login(self, username: str) -> dict[str, str]:
        status, payload, headers = self.json_request(
            "POST",
            "/api/auth/login",
            body={"organization_slug": "school-a", "username": username, "password": PASSWORD},
        )
        assert status == 200, payload
        cookies: dict[str, str] = {}
        for name, value in headers:
            if name.lower() != "set-cookie":
                continue
            parsed = SimpleCookie()
            parsed.load(value)
            cookies.update({key: morsel.value for key, morsel in parsed.items()})
        assert {"scheduler_session", "scheduler_csrf"} <= set(cookies)
        return cookies

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
