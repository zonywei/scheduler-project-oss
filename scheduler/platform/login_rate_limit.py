"""Persistent login throttling shared by all Web processes."""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

from scheduler.platform.auth import AuthenticationError
from scheduler.platform.store import PlatformStore


@dataclass(frozen=True)
class LoginRateLimitPolicy:
    max_failures: int = 5
    window_seconds: int = 15 * 60
    block_seconds: int = 15 * 60

    @classmethod
    def from_environment(cls) -> "LoginRateLimitPolicy":
        return cls(
            max_failures=_bounded_env_int("SCHEDULER_LOGIN_MAX_FAILURES", 5, 2, 50),
            window_seconds=_bounded_env_int("SCHEDULER_LOGIN_WINDOW_SECONDS", 15 * 60, 60, 24 * 60 * 60),
            block_seconds=_bounded_env_int("SCHEDULER_LOGIN_BLOCK_SECONDS", 15 * 60, 60, 24 * 60 * 60),
        )


class LoginRateLimiter:
    def __init__(
        self,
        store: PlatformStore,
        *,
        policy: LoginRateLimitPolicy | None = None,
        now: Callable[[], datetime] | None = None,
        key_secret: str = "",
    ) -> None:
        self.store = store
        self.policy = policy or LoginRateLimitPolicy.from_environment()
        self._now = now or (lambda: datetime.now(timezone.utc))
        self.key_secret = str(key_secret or os.environ.get("SCHEDULER_LOGIN_RATE_LIMIT_SECRET") or "scheduler-login")

    def key(self, *, organization_slug: str, username: str, client_ip: str) -> str:
        material = "\0".join(
            (
                self.key_secret,
                str(organization_slug or "").strip().casefold(),
                str(username or "").strip().casefold(),
                str(client_ip or "unknown").strip().casefold(),
            )
        )
        return hashlib.sha256(material.encode("utf-8")).hexdigest()

    def assert_allowed(self, key_hash: str) -> None:
        now = _utc(self._now())
        now_text = _iso(now)
        with self.store.database.transaction() as connection:
            row = connection.execute(
                "SELECT window_started_at, blocked_until FROM auth_login_limits WHERE key_hash = ?",
                (str(key_hash),),
            ).fetchone()
            if row is None:
                return
            blocked_until = str(row["blocked_until"] or "")
            if blocked_until and blocked_until > now_text:
                raise AuthenticationError("登录尝试过多，请稍后再试")
            window_started = _parse(str(row["window_started_at"] or ""))
            if window_started is None or now - window_started >= timedelta(seconds=self.policy.window_seconds):
                connection.execute("DELETE FROM auth_login_limits WHERE key_hash = ?", (str(key_hash),))

    def record_failure(self, key_hash: str) -> None:
        now = _utc(self._now())
        now_text = _iso(now)
        with self.store.database.transaction() as connection:
            row = connection.execute(
                "SELECT failure_count, window_started_at FROM auth_login_limits WHERE key_hash = ?",
                (str(key_hash),),
            ).fetchone()
            window_started = _parse(str(row["window_started_at"] or "")) if row is not None else None
            if row is None or window_started is None or now - window_started >= timedelta(seconds=self.policy.window_seconds):
                failures = 1
                window_started_text = now_text
            else:
                failures = int(row["failure_count"] or 0) + 1
                window_started_text = _iso(window_started)
            blocked_until = (
                _iso(now + timedelta(seconds=self.policy.block_seconds))
                if failures >= self.policy.max_failures
                else ""
            )
            connection.execute(
                """
                INSERT INTO auth_login_limits(key_hash, failure_count, window_started_at, blocked_until, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(key_hash) DO UPDATE SET
                    failure_count = excluded.failure_count,
                    window_started_at = excluded.window_started_at,
                    blocked_until = excluded.blocked_until,
                    updated_at = excluded.updated_at
                """,
                (str(key_hash), failures, window_started_text, blocked_until, now_text),
            )
            retention_cutoff = _iso(now - timedelta(days=7))
            connection.execute("DELETE FROM auth_login_limits WHERE updated_at < ?", (retention_cutoff,))

    def record_success(self, key_hash: str) -> None:
        with self.store.database.transaction() as connection:
            connection.execute("DELETE FROM auth_login_limits WHERE key_hash = ?", (str(key_hash),))


def _bounded_env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = str(os.environ.get(name) or default).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


def _utc(value: datetime) -> datetime:
    return value.astimezone(timezone.utc) if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _iso(value: datetime) -> str:
    return _utc(value).isoformat(timespec="microseconds")


def _parse(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or ""))
    except ValueError:
        return None
    return _utc(parsed)
