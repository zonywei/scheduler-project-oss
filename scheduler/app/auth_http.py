"""HTTP cookie and tenant boundary for the platform authentication service."""
from __future__ import annotations

import hmac
import os
from dataclasses import asdict
from http.cookies import CookieError, SimpleCookie
from typing import Any, Mapping

from scheduler.platform.auth import (
    AuthenticatedUser,
    AuthenticationError,
    AuthService,
    CsrfValidationError,
    IssuedSession,
)
from scheduler.platform.runtime import runtime_organization_id, runtime_store, uses_sqlite_workspace
from scheduler.platform.login_rate_limit import LoginRateLimiter
from scheduler.platform.store import TenantNotFound


SESSION_COOKIE_NAME = "scheduler_session"
CSRF_COOKIE_NAME = "scheduler_csrf"
CSRF_HEADER_NAME = "X-CSRF-Token"
AUTH_MODES = {"disabled", "required"}


def auth_mode() -> str:
    value = str(os.environ.get("SCHEDULER_AUTH_MODE") or "disabled").strip().lower()
    if value not in AUTH_MODES:
        raise ValueError("SCHEDULER_AUTH_MODE must be disabled or required")
    return value


def auth_required() -> bool:
    return auth_mode() == "required"


def authenticate_headers(
    headers: Mapping[str, str],
    *,
    require_csrf: bool = False,
) -> AuthenticatedUser | None:
    if not auth_required():
        return None
    service, organization_id = _runtime_auth_service()
    cookies = _read_cookies(headers)
    session_token = cookies.get(SESSION_COOKIE_NAME, "")
    if not session_token:
        raise AuthenticationError("请先登录")
    csrf_token = ""
    if require_csrf:
        csrf_cookie = cookies.get(CSRF_COOKIE_NAME, "")
        csrf_header = str(headers.get(CSRF_HEADER_NAME) or "")
        if not csrf_cookie or not csrf_header or not hmac.compare_digest(csrf_cookie, csrf_header):
            raise CsrfValidationError("CSRF 校验失败")
        csrf_token = csrf_header
    user = service.resolve_session(
        session_token,
        csrf_token=csrf_token,
        require_csrf=require_csrf,
    )
    if user.organization_id != organization_id:
        raise AuthenticationError("登录会话不属于当前学校")
    return user


def login_from_payload(
    payload: Mapping[str, Any],
    *,
    client_ip: str = "unknown",
) -> tuple[IssuedSession, list[tuple[str, str]]]:
    if not auth_required():
        raise AuthenticationError("当前运行模式未启用账号登录")
    service, organization_id = _runtime_auth_service()
    organization_slug = str(
        payload.get("organization_slug")
        or os.environ.get("SCHEDULER_ORGANIZATION_SLUG")
        or ""
    ).strip().lower()
    if not organization_slug:
        organization_slug = service.store.get_organization(organization_id).slug
    limiter = LoginRateLimiter(service.store)
    rate_key = limiter.key(
        organization_slug=organization_slug,
        username=str(payload.get("username") or ""),
        client_ip=client_ip,
    )
    limiter.assert_allowed(rate_key)
    try:
        organization = service.store.get_organization_by_slug(organization_slug)
        if organization.id != organization_id:
            raise AuthenticationError("用户名、密码或学校标识不正确")
        ttl_seconds = _session_ttl_seconds()
        issued = service.login(
            organization_slug=organization.slug,
            username=str(payload.get("username") or ""),
            password=str(payload.get("password") or ""),
            ttl_seconds=ttl_seconds,
        )
    except (AuthenticationError, TenantNotFound, ValueError) as exc:
        limiter.record_failure(rate_key)
        raise AuthenticationError("用户名、密码或学校标识不正确") from exc
    limiter.record_success(rate_key)
    return issued, _issued_cookie_headers(issued, ttl_seconds=ttl_seconds)


def logout_from_headers(headers: Mapping[str, str]) -> list[tuple[str, str]]:
    user = authenticate_headers(headers, require_csrf=True)
    assert user is not None
    cookies = _read_cookies(headers)
    service, _ = _runtime_auth_service()
    service.revoke_session(cookies.get(SESSION_COOKIE_NAME, ""), actor_user_id=user.user_id)
    return _cleared_cookie_headers()


def session_payload(user: AuthenticatedUser | None) -> dict[str, Any]:
    if user is None:
        return {
            "schema_version": "scheduler.auth_session.v1",
            "auth_mode": auth_mode(),
            "authenticated": False,
        }
    identity = asdict(user)
    return {
        "schema_version": "scheduler.auth_session.v1",
        "auth_mode": auth_mode(),
        "authenticated": True,
        "user": identity,
    }


def _runtime_auth_service() -> tuple[AuthService, str]:
    if not uses_sqlite_workspace():
        raise RuntimeError("required authentication needs SCHEDULER_STATE_BACKEND=sqlite")
    organization_id = runtime_organization_id()
    return AuthService(runtime_store()), organization_id


def _read_cookies(headers: Mapping[str, str]) -> dict[str, str]:
    raw = str(headers.get("Cookie") or "")
    if not raw:
        return {}
    cookie = SimpleCookie()
    try:
        cookie.load(raw)
    except CookieError as exc:
        raise AuthenticationError("Cookie 格式无效") from exc
    return {name: morsel.value for name, morsel in cookie.items()}


def _issued_cookie_headers(issued: IssuedSession, *, ttl_seconds: int) -> list[tuple[str, str]]:
    secure = _cookie_secure()
    return [
        (
            "Set-Cookie",
            _cookie_value(
                SESSION_COOKIE_NAME,
                issued.session_token,
                max_age=ttl_seconds,
                http_only=True,
                secure=secure,
            ),
        ),
        (
            "Set-Cookie",
            _cookie_value(
                CSRF_COOKIE_NAME,
                issued.csrf_token,
                max_age=ttl_seconds,
                http_only=False,
                secure=secure,
            ),
        ),
        ("Cache-Control", "no-store"),
    ]


def _cleared_cookie_headers() -> list[tuple[str, str]]:
    secure = _cookie_secure()
    return [
        (
            "Set-Cookie",
            _cookie_value(SESSION_COOKIE_NAME, "", max_age=0, http_only=True, secure=secure),
        ),
        (
            "Set-Cookie",
            _cookie_value(CSRF_COOKIE_NAME, "", max_age=0, http_only=False, secure=secure),
        ),
        ("Cache-Control", "no-store"),
    ]


def _cookie_value(
    name: str,
    value: str,
    *,
    max_age: int,
    http_only: bool,
    secure: bool,
) -> str:
    parts = [f"{name}={value}", "Path=/", f"Max-Age={max(0, int(max_age))}", "SameSite=Lax"]
    if http_only:
        parts.append("HttpOnly")
    if secure:
        parts.append("Secure")
    return "; ".join(parts)


def _session_ttl_seconds() -> int:
    raw = str(os.environ.get("SCHEDULER_SESSION_TTL_SECONDS") or "28800").strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError("SCHEDULER_SESSION_TTL_SECONDS must be an integer") from exc
    return min(7 * 24 * 60 * 60, max(5 * 60, value))


def _cookie_secure() -> bool:
    raw = str(os.environ.get("SCHEDULER_COOKIE_SECURE") or "true").strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    raise ValueError("SCHEDULER_COOKIE_SECURE must be true or false")
