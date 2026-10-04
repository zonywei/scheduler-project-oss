"""Password, user, and revocable session services for the SaaS boundary."""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import sqlite3
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Callable

from scheduler.platform.store import PlatformStore


PASSWORD_ALGORITHM = "pbkdf2_sha256"
DEFAULT_PASSWORD_ITERATIONS = 310_000
ALLOWED_ROLES = {
    "academic_admin",
    "scheduler_operator",
    "trial_operator",
    "grade_lead",
    "dorm_supervisor",
    "viewer",
}
DEFAULT_PASSWORD_MIN_LENGTH = 12
TRIAL_PASSWORD_MIN_LENGTH = 8
MAX_SHORT_PASSWORD_TTL = timedelta(days=7)


class AuthenticationError(PermissionError):
    pass


class CsrfValidationError(PermissionError):
    pass


@dataclass(frozen=True)
class AuthenticatedUser:
    user_id: str
    organization_id: str
    organization_slug: str
    organization_name: str
    username: str
    display_name: str
    role: str


@dataclass(frozen=True)
class IssuedSession:
    user: AuthenticatedUser
    session_token: str
    csrf_token: str
    expires_at: str


@dataclass(frozen=True)
class UserProvisionResult:
    user: AuthenticatedUser
    created: bool
    changed_fields: tuple[str, ...]


class PasswordHasher:
    def __init__(self, *, iterations: int = DEFAULT_PASSWORD_ITERATIONS) -> None:
        if not 100_000 <= int(iterations) <= 2_000_000:
            raise ValueError("password iterations must be between 100000 and 2000000")
        self.iterations = int(iterations)

    def hash(self, password: str, *, minimum_length: int = DEFAULT_PASSWORD_MIN_LENGTH) -> str:
        clean = _validate_password(password, minimum_length=minimum_length)
        salt = secrets.token_bytes(18)
        digest = hashlib.pbkdf2_hmac("sha256", clean.encode("utf-8"), salt, self.iterations)
        return "$".join(
            (
                PASSWORD_ALGORITHM,
                str(self.iterations),
                _b64encode(salt),
                _b64encode(digest),
            )
        )

    def verify(self, password: str, encoded: str) -> bool:
        try:
            algorithm, iterations_raw, salt_raw, expected_raw = str(encoded or "").split("$", 3)
            if algorithm != PASSWORD_ALGORITHM:
                return False
            iterations = int(iterations_raw)
            if not 100_000 <= iterations <= 2_000_000:
                return False
            salt = _b64decode(salt_raw)
            expected = _b64decode(expected_raw)
            actual = hashlib.pbkdf2_hmac("sha256", str(password or "").encode("utf-8"), salt, iterations)
            return hmac.compare_digest(actual, expected)
        except (TypeError, ValueError):
            return False


class AuthService:
    def __init__(
        self,
        store: PlatformStore,
        *,
        password_hasher: PasswordHasher | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.store = store
        self.password_hasher = password_hasher or PasswordHasher()
        self._now = now or (lambda: datetime.now(timezone.utc))

    def create_user(
        self,
        organization_id: str,
        *,
        username: str,
        display_name: str,
        role: str,
        password: str,
        actor_user_id: str = "bootstrap",
        expires_at: datetime | str | None = None,
    ) -> AuthenticatedUser:
        organization = self.store.get_organization(organization_id)
        normalized, clean_display, clean_role = _validated_user_fields(
            username=username,
            display_name=display_name,
            role=role,
        )
        user_id = str(uuid.uuid4())
        now = _iso(self._now())
        account_expires_at = _normalize_optional_expiry(expires_at)
        minimum_length = _password_minimum_length(
            role=clean_role,
            expires_at=account_expires_at,
            now=self._now(),
        )
        password_hash = self.password_hasher.hash(password, minimum_length=minimum_length)
        try:
            with self.store.database.transaction() as connection:
                connection.execute(
                    """
                    INSERT INTO users(
                        id, organization_id, username_normalized, display_name,
                        role, password_hash, status, expires_at, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?, ?)
                    """,
                    (
                        user_id,
                        organization.id,
                        normalized,
                        clean_display,
                        clean_role,
                        password_hash,
                        account_expires_at,
                        now,
                        now,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError("username already exists in this organization") from exc
        self.store.append_audit_event(
            organization.id,
            actor_user_id=actor_user_id,
            event_type="auth.user_created",
            resource_type="user",
            resource_id=user_id,
            payload={
                "username": normalized,
                "role": clean_role,
                "expires_at": account_expires_at,
            },
        )
        return AuthenticatedUser(
            user_id=user_id,
            organization_id=organization.id,
            organization_slug=organization.slug,
            organization_name=organization.name,
            username=normalized,
            display_name=clean_display,
            role=clean_role,
        )

    def ensure_user(
        self,
        organization_id: str,
        *,
        username: str,
        display_name: str,
        role: str,
        password: str,
        actor_user_id: str = "bootstrap",
        expires_at: datetime | str | None = None,
    ) -> UserProvisionResult:
        """Create or reconcile a deployment-managed user without exposing its secret.

        Re-running the command with the same desired state is a no-op. If the
        password or account attributes change, active sessions are revoked so
        the declared deployment credentials take effect immediately.
        """
        organization = self.store.get_organization(organization_id)
        normalized, clean_display, clean_role = _validated_user_fields(
            username=username,
            display_name=display_name,
            role=role,
        )
        account_expires_at = _normalize_optional_expiry(expires_at)
        minimum_length = _password_minimum_length(
            role=clean_role,
            expires_at=account_expires_at,
            now=self._now(),
        )
        clean_password = _validate_password(password, minimum_length=minimum_length)
        with self.store.database.connect() as connection:
            row = connection.execute(
                """
                SELECT id, display_name, role, password_hash, status, expires_at
                FROM users
                WHERE organization_id = ? AND username_normalized = ?
                """,
                (organization.id, normalized),
            ).fetchone()
        if row is None:
            user = self.create_user(
                organization.id,
                username=normalized,
                display_name=clean_display,
                role=clean_role,
                password=clean_password,
                actor_user_id=actor_user_id,
                expires_at=account_expires_at,
            )
            return UserProvisionResult(
                user=user,
                created=True,
                changed_fields=("account",),
            )

        user_id = str(row["id"])
        changed_fields: list[str] = []
        if str(row["display_name"]) != clean_display:
            changed_fields.append("display_name")
        if str(row["role"]) != clean_role:
            changed_fields.append("role")
        if str(row["status"]) != "active":
            changed_fields.append("status")
        if str(row["expires_at"] or "") != account_expires_at:
            changed_fields.append("expires_at")
        password_changed = not self.password_hasher.verify(clean_password, str(row["password_hash"]))
        if password_changed:
            changed_fields.append("password")

        if changed_fields:
            now = _iso(self._now())
            password_hash = (
                self.password_hasher.hash(clean_password, minimum_length=minimum_length)
                if password_changed
                else str(row["password_hash"])
            )
            with self.store.database.transaction() as connection:
                connection.execute(
                    """
                    UPDATE users
                    SET display_name = ?, role = ?, password_hash = ?, status = 'active',
                        expires_at = ?, updated_at = ?
                    WHERE id = ? AND organization_id = ?
                    """,
                    (
                        clean_display,
                        clean_role,
                        password_hash,
                        account_expires_at,
                        now,
                        user_id,
                        organization.id,
                    ),
                )
                connection.execute(
                    """
                    UPDATE sessions SET revoked_at = ?
                    WHERE user_id = ? AND organization_id = ? AND revoked_at IS NULL
                    """,
                    (now, user_id, organization.id),
                )
            self.store.append_audit_event(
                organization.id,
                actor_user_id=actor_user_id,
                event_type="auth.user_provisioned",
                resource_type="user",
                resource_id=user_id,
                payload={
                    "username": normalized,
                    "role": clean_role,
                    "changed_fields": changed_fields,
                },
            )

        return UserProvisionResult(
            user=AuthenticatedUser(
                user_id=user_id,
                organization_id=organization.id,
                organization_slug=organization.slug,
                organization_name=organization.name,
                username=normalized,
                display_name=clean_display,
                role=clean_role,
            ),
            created=False,
            changed_fields=tuple(changed_fields),
        )

    def login(
        self,
        *,
        organization_slug: str,
        username: str,
        password: str,
        ttl_seconds: int = 8 * 60 * 60,
    ) -> IssuedSession:
        try:
            normalized = _normalize_username(username)
        except ValueError as exc:
            raise AuthenticationError("用户名、密码或学校标识不正确") from exc
        with self.store.database.connect() as connection:
            row = connection.execute(
                """
                SELECT
                    u.id AS user_id, u.organization_id, u.username_normalized,
                    u.display_name, u.role, u.password_hash, u.status AS user_status,
                    u.expires_at AS user_expires_at,
                    o.slug AS organization_slug, o.name AS organization_name, o.status AS organization_status
                FROM users u JOIN organizations o ON o.id = u.organization_id
                WHERE o.slug = ? AND u.username_normalized = ?
                """,
                (str(organization_slug or "").strip().lower(), normalized),
            ).fetchone()
        encoded_hash = str(row["password_hash"]) if row is not None else _dummy_password_hash(self.password_hasher)
        password_valid = self.password_hasher.verify(password, encoded_hash)
        if (
            row is None
            or not password_valid
            or str(row["user_status"]) != "active"
            or str(row["organization_status"]) != "active"
            or _expiry_reached(row["user_expires_at"], self._now())
        ):
            raise AuthenticationError("用户名、密码或学校标识不正确")
        user = _user_from_row(row)
        return self._issue_session(
            user,
            ttl_seconds=ttl_seconds,
            account_expires_at=str(row["user_expires_at"] or ""),
        )

    def resolve_session(
        self,
        session_token: str,
        *,
        csrf_token: str = "",
        require_csrf: bool = False,
    ) -> AuthenticatedUser:
        token_hash = _token_hash(session_token)
        now = _iso(self._now())
        with self.store.database.transaction() as connection:
            row = connection.execute(
                """
                SELECT
                    u.id AS user_id, u.organization_id, u.username_normalized,
                    u.display_name, u.role, u.status AS user_status,
                    u.expires_at AS user_expires_at,
                    o.slug AS organization_slug, o.name AS organization_name, o.status AS organization_status,
                    s.csrf_token_hash, s.expires_at, s.revoked_at
                FROM sessions s
                JOIN users u ON u.id = s.user_id AND u.organization_id = s.organization_id
                JOIN organizations o ON o.id = s.organization_id
                WHERE s.token_hash = ?
                """,
                (token_hash,),
            ).fetchone()
            if (
                row is None
                or row["revoked_at"] is not None
                or str(row["expires_at"]) <= now
                or str(row["user_status"]) != "active"
                or str(row["organization_status"]) != "active"
                or _expiry_reached(row["user_expires_at"], self._now())
            ):
                raise AuthenticationError("登录会话无效或已过期")
            if require_csrf:
                if not csrf_token or not hmac.compare_digest(_token_hash(csrf_token), str(row["csrf_token_hash"])):
                    raise CsrfValidationError("CSRF 校验失败")
            connection.execute(
                "UPDATE sessions SET last_seen_at = ? WHERE token_hash = ?",
                (now, token_hash),
            )
        return _user_from_row(row)

    def revoke_session(self, session_token: str, *, actor_user_id: str = "") -> bool:
        token_hash = _token_hash(session_token)
        now = _iso(self._now())
        with self.store.database.transaction() as connection:
            row = connection.execute(
                "SELECT organization_id, user_id, revoked_at FROM sessions WHERE token_hash = ?",
                (token_hash,),
            ).fetchone()
            if row is None or row["revoked_at"] is not None:
                return False
            connection.execute(
                "UPDATE sessions SET revoked_at = ? WHERE token_hash = ?",
                (now, token_hash),
            )
        self.store.append_audit_event(
            str(row["organization_id"]),
            actor_user_id=actor_user_id or str(row["user_id"]),
            event_type="auth.logout",
            resource_type="session",
            resource_id=token_hash[:16],
            payload={},
        )
        return True

    def _issue_session(
        self,
        user: AuthenticatedUser,
        *,
        ttl_seconds: int,
        account_expires_at: str = "",
    ) -> IssuedSession:
        ttl = min(7 * 24 * 60 * 60, max(5 * 60, int(ttl_seconds)))
        session_token = secrets.token_urlsafe(36)
        csrf_token = secrets.token_urlsafe(32)
        now_value = self._now()
        now = _iso(now_value)
        session_deadline = now_value + timedelta(seconds=ttl)
        if account_expires_at:
            account_deadline = _parse_expiry(account_expires_at)
            if account_deadline <= _as_utc(now_value):
                raise AuthenticationError("账号已过期")
            session_deadline = min(_as_utc(session_deadline), account_deadline)
        expires_at = _iso(session_deadline)
        with self.store.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO sessions(
                    token_hash, organization_id, user_id, csrf_token_hash,
                    created_at, last_seen_at, expires_at, revoked_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL)
                """,
                (
                    _token_hash(session_token),
                    user.organization_id,
                    user.user_id,
                    _token_hash(csrf_token),
                    now,
                    now,
                    expires_at,
                ),
            )
        self.store.append_audit_event(
            user.organization_id,
            actor_user_id=user.user_id,
            event_type="auth.login",
            resource_type="session",
            resource_id=_token_hash(session_token)[:16],
            payload={},
        )
        return IssuedSession(
            user=user,
            session_token=session_token,
            csrf_token=csrf_token,
            expires_at=expires_at,
        )


def _validate_password(password: str, *, minimum_length: int = DEFAULT_PASSWORD_MIN_LENGTH) -> str:
    value = str(password or "")
    minimum = max(TRIAL_PASSWORD_MIN_LENGTH, int(minimum_length))
    if not minimum <= len(value) <= 256:
        raise ValueError(f"password must contain {minimum}-256 characters")
    if value.strip() != value or "\x00" in value:
        raise ValueError("password must not contain surrounding whitespace or null bytes")
    return value


def _normalize_optional_expiry(value: datetime | str | None) -> str:
    if value is None or (isinstance(value, str) and not value.strip()):
        return ""
    return _iso(_parse_expiry(value))


def _password_minimum_length(*, role: str, expires_at: str, now: datetime) -> int:
    if role not in {"viewer", "trial_operator"} or not expires_at:
        return DEFAULT_PASSWORD_MIN_LENGTH
    deadline = _parse_expiry(expires_at)
    current = _as_utc(now)
    if current < deadline <= current + MAX_SHORT_PASSWORD_TTL:
        return TRIAL_PASSWORD_MIN_LENGTH
    return DEFAULT_PASSWORD_MIN_LENGTH


def _parse_expiry(value: datetime | str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        raw = str(value or "").strip()
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("expires_at must be an ISO-8601 timestamp") from exc
    return _as_utc(parsed)


def _expiry_reached(value: object, now: datetime) -> bool:
    raw = str(value or "").strip()
    if not raw:
        return False
    try:
        return _parse_expiry(raw) <= _as_utc(now)
    except ValueError:
        return True


def _as_utc(value: datetime) -> datetime:
    normalized = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    return normalized.astimezone(timezone.utc)


def _validated_user_fields(*, username: str, display_name: str, role: str) -> tuple[str, str, str]:
    normalized = _normalize_username(username)
    clean_display = str(display_name or "").strip()
    clean_role = str(role or "").strip()
    if not clean_display or len(clean_display) > 80:
        raise ValueError("display name must contain 1-80 characters")
    if clean_role not in ALLOWED_ROLES:
        raise ValueError(f"unsupported role: {clean_role}")
    return normalized, clean_display, clean_role


def _normalize_username(username: str) -> str:
    value = unicodedata.normalize("NFKC", str(username or "")).strip().casefold()
    if not 3 <= len(value) <= 80 or any(ord(character) < 32 for character in value):
        raise ValueError("username must contain 3-80 visible characters")
    return value


def _token_hash(token: str) -> str:
    return hashlib.sha256(str(token or "").encode("utf-8")).hexdigest()


def _dummy_password_hash(hasher: PasswordHasher) -> str:
    return _cached_dummy_password_hash(hasher.iterations)


@lru_cache(maxsize=8)
def _cached_dummy_password_hash(iterations: int) -> str:
    salt = b"scheduler-auth-dummy"
    digest = hashlib.pbkdf2_hmac("sha256", b"invalid-password", salt, iterations)
    return "$".join((PASSWORD_ALGORITHM, str(iterations), _b64encode(salt), _b64encode(digest)))


def _user_from_row(row: sqlite3.Row) -> AuthenticatedUser:
    return AuthenticatedUser(
        user_id=str(row["user_id"]),
        organization_id=str(row["organization_id"]),
        organization_slug=str(row["organization_slug"]),
        organization_name=str(row["organization_name"]),
        username=str(row["username_normalized"]),
        display_name=str(row["display_name"]),
        role=str(row["role"]),
    )


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    raw = str(value or "")
    return base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))


def _iso(value: datetime) -> str:
    normalized = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    return normalized.astimezone(timezone.utc).isoformat(timespec="microseconds")
