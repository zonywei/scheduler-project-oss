"""Model quota reservations, cost ledger, and persistent provider circuit state."""
from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Mapping
from zoneinfo import ZoneInfo

from scheduler.platform.store import PlatformStore


ACTIVE_USAGE_STATUSES = {"reserved", "succeeded"}


class ModelQuotaExceeded(PermissionError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class QuotaLimits:
    request_limit: int = 0
    token_limit: int = 0
    cost_limit_microunits: int = 0


@dataclass(frozen=True)
class UsageReservation:
    event_id: str
    organization_id: str
    user_id: str
    operation: str


class ModelUsageStore:
    def __init__(
        self,
        store: PlatformStore,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.store = store
        self._now = now or (lambda: datetime.now(timezone.utc))

    def set_quota(
        self,
        organization_id: str,
        *,
        scope_user_id: str = "",
        request_limit: int = 0,
        token_limit: int = 0,
        cost_limit_microunits: int = 0,
        actor_user_id: str,
    ) -> QuotaLimits:
        limits = QuotaLimits(
            request_limit=_limit(request_limit, "request_limit"),
            token_limit=_limit(token_limit, "token_limit"),
            cost_limit_microunits=_limit(cost_limit_microunits, "cost_limit_microunits"),
        )
        scope = str(scope_user_id or "").strip()
        now = _iso(self._now())
        with self.store.database.transaction() as connection:
            self.store._require_organization(connection, organization_id)
            if scope:
                user = connection.execute(
                    "SELECT 1 FROM users WHERE organization_id = ? AND id = ? AND status = 'active'",
                    (str(organization_id), scope),
                ).fetchone()
                if user is None:
                    raise ValueError("quota user does not belong to the organization")
            connection.execute(
                """
                INSERT INTO model_quotas(
                    organization_id, scope_user_id, period, request_limit,
                    token_limit, cost_limit_microunits, updated_by, updated_at
                ) VALUES (?, ?, 'monthly', ?, ?, ?, ?, ?)
                ON CONFLICT(organization_id, scope_user_id, period) DO UPDATE SET
                    request_limit = excluded.request_limit,
                    token_limit = excluded.token_limit,
                    cost_limit_microunits = excluded.cost_limit_microunits,
                    updated_by = excluded.updated_by,
                    updated_at = excluded.updated_at
                """,
                (
                    str(organization_id),
                    scope,
                    limits.request_limit,
                    limits.token_limit,
                    limits.cost_limit_microunits,
                    str(actor_user_id or ""),
                    now,
                ),
            )
            self.store._insert_audit(
                connection,
                organization_id=str(organization_id),
                actor_user_id=str(actor_user_id or ""),
                event_type="model_quota.updated",
                resource_type="model_quota",
                resource_id=scope or "organization",
                payload={
                    "request_limit": limits.request_limit,
                    "token_limit": limits.token_limit,
                    "cost_limit_microunits": limits.cost_limit_microunits,
                },
                created_at=now,
            )
        return limits

    def effective_quota(self, organization_id: str, *, user_id: str = "") -> QuotaLimits:
        with self.store.database.connect() as connection:
            self.store._require_organization(connection, organization_id)
            return self._effective_quota(connection, organization_id, user_id)

    def reserve(
        self,
        organization_id: str,
        *,
        user_id: str,
        operation: str,
        estimated_prompt_tokens: int,
        estimated_completion_tokens: int,
        estimated_cost_microunits: int,
        metadata: Mapping[str, Any] | None = None,
    ) -> UsageReservation:
        prompt_tokens = _nonnegative(estimated_prompt_tokens, "estimated_prompt_tokens")
        completion_tokens = _nonnegative(estimated_completion_tokens, "estimated_completion_tokens")
        total_tokens = prompt_tokens + completion_tokens
        cost = _nonnegative(estimated_cost_microunits, "estimated_cost_microunits")
        clean_operation = str(operation or "").strip()
        if not clean_operation or len(clean_operation) > 120:
            raise ValueError("model operation must contain 1-120 characters")
        event_id = str(uuid.uuid4())
        now_value = self._now()
        now = _iso(now_value)
        period_start = _billing_period_start(now_value)
        denial: tuple[str, str] | None = None
        with self.store.database.transaction() as connection:
            self.store._require_organization(connection, organization_id)
            organization_limits = self._quota_for_scope(connection, organization_id, "")
            organization_usage = connection.execute(
                """
                SELECT COUNT(*) AS requests,
                       COALESCE(SUM(total_tokens), 0) AS tokens,
                       COALESCE(SUM(cost_microunits), 0) AS cost
                FROM model_usage_events
                WHERE organization_id = ?
                  AND status IN ('reserved', 'succeeded')
                  AND occurred_at >= ?
                """,
                (str(organization_id), period_start),
            ).fetchone()
            assert organization_usage is not None
            denial = _quota_denial(
                organization_limits,
                organization_usage,
                added_tokens=total_tokens,
                added_cost=cost,
            )
            if denial is None and str(user_id or ""):
                user_limits = self._quota_for_scope(connection, organization_id, str(user_id))
                user_usage = connection.execute(
                    """
                    SELECT COUNT(*) AS requests,
                           COALESCE(SUM(total_tokens), 0) AS tokens,
                           COALESCE(SUM(cost_microunits), 0) AS cost
                    FROM model_usage_events
                    WHERE organization_id = ? AND user_id = ?
                      AND status IN ('reserved', 'succeeded') AND occurred_at >= ?
                    """,
                    (str(organization_id), str(user_id), period_start),
                ).fetchone()
                assert user_usage is not None
                denial = _quota_denial(
                    user_limits,
                    user_usage,
                    added_tokens=total_tokens,
                    added_cost=cost,
                )
            status = "denied" if denial else "reserved"
            connection.execute(
                """
                INSERT INTO model_usage_events(
                    id, organization_id, user_id, provider_id, model, request_id, operation,
                    prompt_tokens, completion_tokens, total_tokens, cost_microunits, currency,
                    metadata_json, occurred_at, status, latency_ms, error_code, estimated
                ) VALUES (?, ?, ?, 'router', 'pending', '', ?, ?, ?, ?, ?, 'CNY', ?, ?, ?, 0, ?, 1)
                """,
                (
                    event_id,
                    str(organization_id),
                    str(user_id or ""),
                    clean_operation,
                    prompt_tokens,
                    completion_tokens,
                    total_tokens,
                    cost,
                    _encode(metadata or {}),
                    now,
                    status,
                    denial[0] if denial else "",
                ),
            )
        if denial:
            raise ModelQuotaExceeded(*denial)
        return UsageReservation(
            event_id=event_id,
            organization_id=str(organization_id),
            user_id=str(user_id or ""),
            operation=clean_operation,
        )

    def finalize_success(
        self,
        reservation: UsageReservation,
        *,
        provider_id: str,
        model: str,
        request_id: str,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
        cost_microunits: int,
        latency_ms: int,
        estimated: bool,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        prompt = _nonnegative(prompt_tokens, "prompt_tokens")
        completion = _nonnegative(completion_tokens, "completion_tokens")
        total = max(prompt + completion, _nonnegative(total_tokens, "total_tokens"))
        now = _iso(self._now())
        with self.store.database.transaction() as connection:
            updated = connection.execute(
                """
                UPDATE model_usage_events
                SET provider_id = ?, model = ?, request_id = ?, prompt_tokens = ?,
                    completion_tokens = ?, total_tokens = ?, cost_microunits = ?,
                    metadata_json = ?, status = 'succeeded', latency_ms = ?,
                    error_code = '', estimated = ?, occurred_at = ?
                WHERE id = ? AND organization_id = ? AND status = 'reserved'
                """,
                (
                    _label(provider_id, "provider_id", 80),
                    _label(model, "model", 160),
                    str(request_id or "")[:200],
                    prompt,
                    completion,
                    total,
                    _nonnegative(cost_microunits, "cost_microunits"),
                    _encode(metadata or {}),
                    _nonnegative(latency_ms, "latency_ms"),
                    1 if estimated else 0,
                    now,
                    reservation.event_id,
                    reservation.organization_id,
                ),
            )
            if updated.rowcount != 1:
                raise RuntimeError("model usage reservation is no longer active")

    def finalize_failure(
        self,
        reservation: UsageReservation,
        *,
        error_code: str,
        latency_ms: int,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        with self.store.database.transaction() as connection:
            updated = connection.execute(
                """
                UPDATE model_usage_events
                SET prompt_tokens = 0, completion_tokens = 0, total_tokens = 0,
                    cost_microunits = 0, metadata_json = ?, status = 'failed',
                    latency_ms = ?, error_code = ?, estimated = 0
                WHERE id = ? AND organization_id = ? AND status = 'reserved'
                """,
                (
                    _encode(metadata or {}),
                    _nonnegative(latency_ms, "latency_ms"),
                    str(error_code or "model_request_failed")[:120],
                    reservation.event_id,
                    reservation.organization_id,
                ),
            )
            if updated.rowcount != 1:
                raise RuntimeError("model usage reservation is no longer active")

    def provider_available(self, organization_id: str, provider_id: str) -> bool:
        now = _iso(self._now())
        with self.store.database.connect() as connection:
            row = connection.execute(
                """
                SELECT opened_until FROM model_provider_health
                WHERE organization_id = ? AND provider_id = ?
                """,
                (str(organization_id), str(provider_id)),
            ).fetchone()
        return row is None or not str(row["opened_until"] or "") or str(row["opened_until"]) <= now

    def record_provider_success(self, organization_id: str, provider_id: str) -> None:
        now = _iso(self._now())
        with self.store.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO model_provider_health(
                    organization_id, provider_id, consecutive_failures, opened_until, last_error_code, updated_at
                ) VALUES (?, ?, 0, '', '', ?)
                ON CONFLICT(organization_id, provider_id) DO UPDATE SET
                    consecutive_failures = 0, opened_until = '', last_error_code = '', updated_at = excluded.updated_at
                """,
                (str(organization_id), _label(provider_id, "provider_id", 80), now),
            )

    def record_provider_failure(
        self,
        organization_id: str,
        provider_id: str,
        *,
        error_code: str,
        threshold: int = 3,
        cooldown_seconds: int = 60,
    ) -> None:
        now_value = self._now()
        now = _iso(now_value)
        clean_provider = _label(provider_id, "provider_id", 80)
        with self.store.database.transaction() as connection:
            row = connection.execute(
                """
                SELECT consecutive_failures FROM model_provider_health
                WHERE organization_id = ? AND provider_id = ?
                """,
                (str(organization_id), clean_provider),
            ).fetchone()
            failures = int(row["consecutive_failures"] or 0) + 1 if row is not None else 1
            opened_until = (
                _iso(now_value + timedelta(seconds=max(1, int(cooldown_seconds))))
                if failures >= max(1, int(threshold))
                else ""
            )
            connection.execute(
                """
                INSERT INTO model_provider_health(
                    organization_id, provider_id, consecutive_failures, opened_until, last_error_code, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(organization_id, provider_id) DO UPDATE SET
                    consecutive_failures = excluded.consecutive_failures,
                    opened_until = excluded.opened_until,
                    last_error_code = excluded.last_error_code,
                    updated_at = excluded.updated_at
                """,
                (
                    str(organization_id),
                    clean_provider,
                    failures,
                    opened_until,
                    str(error_code or "provider_error")[:120],
                    now,
                ),
            )

    def summary(self, organization_id: str, *, user_id: str = "") -> dict[str, Any]:
        now = self._now()
        start = _billing_period_start(now)
        with self.store.database.connect() as connection:
            self.store._require_organization(connection, organization_id)
            rows = connection.execute(
                """
                SELECT provider_id, model, status, COUNT(*) AS requests,
                       COALESCE(SUM(total_tokens), 0) AS tokens,
                       COALESCE(SUM(cost_microunits), 0) AS cost
                FROM model_usage_events
                WHERE organization_id = ? AND (? = '' OR user_id = ?) AND occurred_at >= ?
                GROUP BY provider_id, model, status
                ORDER BY requests DESC, provider_id ASC
                """,
                (str(organization_id), str(user_id or ""), str(user_id or ""), start),
            ).fetchall()
            limits = self._effective_quota(connection, organization_id, user_id)
        items = [
            {
                "provider_id": str(row["provider_id"]),
                "model": str(row["model"]),
                "status": str(row["status"]),
                "requests": int(row["requests"]),
                "tokens": int(row["tokens"]),
                "cost_microunits": int(row["cost"]),
            }
            for row in rows
        ]
        succeeded = [item for item in items if item["status"] == "succeeded"]
        return {
            "schema_version": "scheduler.model_usage_summary.v1",
            "period": "monthly",
            "period_start": start,
            "scope_user_id": str(user_id or ""),
            "totals": {
                "requests": sum(item["requests"] for item in succeeded),
                "tokens": sum(item["tokens"] for item in succeeded),
                "cost_microunits": sum(item["cost_microunits"] for item in succeeded),
                "failed_requests": sum(item["requests"] for item in items if item["status"] == "failed"),
                "denied_requests": sum(item["requests"] for item in items if item["status"] == "denied"),
            },
            "quota": {
                "request_limit": limits.request_limit,
                "token_limit": limits.token_limit,
                "cost_limit_microunits": limits.cost_limit_microunits,
            },
            "breakdown": items,
        }

    @staticmethod
    def _effective_quota(connection: sqlite3.Connection, organization_id: str, user_id: str) -> QuotaLimits:
        scopes = [""] + ([str(user_id)] if str(user_id or "") else [])
        placeholders = ",".join("?" for _ in scopes)
        rows = connection.execute(
            f"""
            SELECT request_limit, token_limit, cost_limit_microunits
            FROM model_quotas
            WHERE organization_id = ? AND period = 'monthly' AND scope_user_id IN ({placeholders})
            """,
            (str(organization_id), *scopes),
        ).fetchall()
        return QuotaLimits(
            request_limit=_strictest(int(row["request_limit"]) for row in rows),
            token_limit=_strictest(int(row["token_limit"]) for row in rows),
            cost_limit_microunits=_strictest(int(row["cost_limit_microunits"]) for row in rows),
        )

    @staticmethod
    def _quota_for_scope(connection: sqlite3.Connection, organization_id: str, scope_user_id: str) -> QuotaLimits:
        row = connection.execute(
            """
            SELECT request_limit, token_limit, cost_limit_microunits
            FROM model_quotas
            WHERE organization_id = ? AND scope_user_id = ? AND period = 'monthly'
            """,
            (str(organization_id), str(scope_user_id or "")),
        ).fetchone()
        if row is None:
            return QuotaLimits()
        return QuotaLimits(
            request_limit=int(row["request_limit"]),
            token_limit=int(row["token_limit"]),
            cost_limit_microunits=int(row["cost_limit_microunits"]),
        )


def _billing_period_start(value: datetime) -> str:
    normalized = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    shanghai = normalized.astimezone(ZoneInfo("Asia/Shanghai"))
    local_start = datetime(shanghai.year, shanghai.month, 1, tzinfo=ZoneInfo("Asia/Shanghai"))
    return _iso(local_start.astimezone(timezone.utc))


def _strictest(values: Any) -> int:
    positives = [int(value) for value in values if int(value) > 0]
    return min(positives) if positives else 0


def _quota_denial(
    limits: QuotaLimits,
    usage: sqlite3.Row,
    *,
    added_tokens: int,
    added_cost: int,
) -> tuple[str, str] | None:
    if limits.request_limit and int(usage["requests"]) + 1 > limits.request_limit:
        return "request_quota_exceeded", "本月 AI 请求次数配额已用完"
    if limits.token_limit and int(usage["tokens"]) + added_tokens > limits.token_limit:
        return "token_quota_exceeded", "本月 AI Token 配额不足"
    if limits.cost_limit_microunits and int(usage["cost"]) + added_cost > limits.cost_limit_microunits:
        return "cost_quota_exceeded", "本月 AI 费用配额不足"
    return None


def _limit(value: Any, label: str) -> int:
    parsed = _nonnegative(value, label)
    if parsed > 10**15:
        raise ValueError(f"{label} is too large")
    return parsed


def _nonnegative(value: Any, label: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be an integer") from exc
    if parsed < 0:
        raise ValueError(f"{label} must be non-negative")
    return parsed


def _label(value: Any, label: str, maximum: int) -> str:
    text = str(value or "").strip()
    if not text or len(text) > maximum:
        raise ValueError(f"{label} must contain 1-{maximum} characters")
    return text


def _encode(value: Mapping[str, Any]) -> str:
    try:
        return json.dumps(dict(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise ValueError("model usage metadata must be JSON serializable") from exc


def _iso(value: datetime) -> str:
    normalized = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    return normalized.astimezone(timezone.utc).isoformat(timespec="microseconds")
