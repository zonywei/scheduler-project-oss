"""SQLite runtime database, schema migrations, and transaction boundaries."""
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator


@dataclass(frozen=True)
class PlatformDatabaseSettings:
    path: Path
    busy_timeout_ms: int = 5_000

    @classmethod
    def from_environment(cls, *, project_root: Path | None = None) -> "PlatformDatabaseSettings":
        root = Path(project_root) if project_root is not None else Path(__file__).resolve().parents[2]
        data_dir_raw = str(os.environ.get("SCHEDULER_DATA_DIR") or "").strip()
        data_dir = Path(data_dir_raw).expanduser() if data_dir_raw else root / "var"
        database_raw = str(os.environ.get("SCHEDULER_DATABASE_PATH") or "").strip()
        database_path = Path(database_raw).expanduser() if database_raw else data_dir / "scheduler.db"
        return cls(path=database_path.resolve())


@dataclass(frozen=True)
class _Migration:
    version: int
    description: str
    sql: str


_MIGRATIONS: tuple[_Migration, ...] = (
    _Migration(
        version=1,
        description="initial single-school SaaS platform schema",
        sql="""
CREATE TABLE IF NOT EXISTS organizations (
    id TEXT PRIMARY KEY,
    slug TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    username_normalized TEXT NOT NULL,
    display_name TEXT NOT NULL,
    role TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (organization_id, username_normalized)
);

CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    csrf_token_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    revoked_at TEXT
);

CREATE TABLE IF NOT EXISTS workspace_snapshots (
    organization_id TEXT PRIMARY KEY REFERENCES organizations(id) ON DELETE CASCADE,
    revision INTEGER NOT NULL,
    payload_json TEXT NOT NULL,
    updated_by TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS workspace_versions (
    organization_id TEXT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    revision INTEGER NOT NULL,
    payload_json TEXT NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    created_by TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY (organization_id, revision)
);

CREATE TABLE IF NOT EXISTS rule_drafts (
    organization_id TEXT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    rule_id TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    status TEXT NOT NULL,
    version INTEGER NOT NULL,
    payload_json TEXT NOT NULL,
    created_by TEXT,
    updated_by TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (organization_id, rule_id)
);

CREATE TABLE IF NOT EXISTS audit_events (
    id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    actor_user_id TEXT,
    event_type TEXT NOT NULL,
    resource_type TEXT NOT NULL,
    resource_id TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS solve_jobs (
    id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    status TEXT NOT NULL,
    request_json TEXT NOT NULL,
    run_dir TEXT NOT NULL DEFAULT '',
    worker_id TEXT NOT NULL DEFAULT '',
    process_id INTEGER,
    error_code TEXT NOT NULL DEFAULT '',
    error_message TEXT NOT NULL DEFAULT '',
    created_by TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    heartbeat_at TEXT,
    completed_at TEXT,
    cancel_requested_at TEXT
);

CREATE TABLE IF NOT EXISTS model_usage_events (
    id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    user_id TEXT,
    provider_id TEXT NOT NULL,
    model TEXT NOT NULL,
    request_id TEXT NOT NULL DEFAULT '',
    operation TEXT NOT NULL,
    prompt_tokens INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    total_tokens INTEGER NOT NULL DEFAULT 0,
    cost_microunits INTEGER NOT NULL DEFAULT 0,
    currency TEXT NOT NULL DEFAULT 'CNY',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    occurred_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_users_org ON users(organization_id);
CREATE INDEX IF NOT EXISTS idx_sessions_org_user ON sessions(organization_id, user_id);
CREATE INDEX IF NOT EXISTS idx_rule_drafts_org_status ON rule_drafts(organization_id, status);
CREATE INDEX IF NOT EXISTS idx_audit_events_org_created ON audit_events(organization_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_solve_jobs_org_created ON solve_jobs(organization_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_model_usage_org_occurred ON model_usage_events(organization_id, occurred_at DESC);
""",
    ),
    _Migration(
        version=2,
        description="durable solve job leases, idempotency, and result metadata",
        sql="""
ALTER TABLE solve_jobs ADD COLUMN idempotency_key TEXT NOT NULL DEFAULT '';
ALTER TABLE solve_jobs ADD COLUMN workspace_revision INTEGER NOT NULL DEFAULT 0;
ALTER TABLE solve_jobs ADD COLUMN result_json TEXT NOT NULL DEFAULT '{}';
ALTER TABLE solve_jobs ADD COLUMN updated_at TEXT NOT NULL DEFAULT '';

CREATE UNIQUE INDEX IF NOT EXISTS idx_solve_jobs_org_idempotency
ON solve_jobs(organization_id, idempotency_key)
WHERE idempotency_key <> '';

CREATE UNIQUE INDEX IF NOT EXISTS idx_solve_jobs_one_running_org
ON solve_jobs(organization_id)
WHERE status IN ('running', 'cancel_requested');
""",
    ),
    _Migration(
        version=3,
        description="metered model usage quotas and provider circuit state",
        sql="""
ALTER TABLE model_usage_events ADD COLUMN status TEXT NOT NULL DEFAULT 'succeeded';
ALTER TABLE model_usage_events ADD COLUMN latency_ms INTEGER NOT NULL DEFAULT 0;
ALTER TABLE model_usage_events ADD COLUMN error_code TEXT NOT NULL DEFAULT '';
ALTER TABLE model_usage_events ADD COLUMN estimated INTEGER NOT NULL DEFAULT 0;

CREATE TABLE IF NOT EXISTS model_quotas (
    organization_id TEXT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    scope_user_id TEXT NOT NULL DEFAULT '',
    period TEXT NOT NULL DEFAULT 'monthly',
    request_limit INTEGER NOT NULL DEFAULT 0,
    token_limit INTEGER NOT NULL DEFAULT 0,
    cost_limit_microunits INTEGER NOT NULL DEFAULT 0,
    updated_by TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL,
    PRIMARY KEY (organization_id, scope_user_id, period)
);

CREATE TABLE IF NOT EXISTS model_provider_health (
    organization_id TEXT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    provider_id TEXT NOT NULL,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    opened_until TEXT NOT NULL DEFAULT '',
    last_error_code TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL,
    PRIMARY KEY (organization_id, provider_id)
);

CREATE INDEX IF NOT EXISTS idx_model_usage_org_status_occurred
ON model_usage_events(organization_id, status, occurred_at DESC);
""",
    ),
    _Migration(
        version=4,
        description="persistent login throttling and service heartbeats",
        sql="""
CREATE TABLE IF NOT EXISTS auth_login_limits (
    key_hash TEXT PRIMARY KEY,
    failure_count INTEGER NOT NULL DEFAULT 0,
    window_started_at TEXT NOT NULL,
    blocked_until TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS service_heartbeats (
    organization_id TEXT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    service_kind TEXT NOT NULL,
    instance_id TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    last_seen_at TEXT NOT NULL,
    PRIMARY KEY (organization_id, service_kind, instance_id)
);

CREATE INDEX IF NOT EXISTS idx_auth_login_limits_updated
ON auth_login_limits(updated_at);

CREATE INDEX IF NOT EXISTS idx_service_heartbeats_lookup
ON service_heartbeats(organization_id, service_kind, last_seen_at DESC);
""",
    ),
    _Migration(
        version=5,
        description="premium conversational scheduling sessions, messages, and uploads",
        sql="""
CREATE TABLE IF NOT EXISTS conversation_sessions (
    id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    created_by TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL,
    entry_mode TEXT NOT NULL,
    source_mode TEXT NOT NULL,
    status TEXT NOT NULL,
    phase TEXT NOT NULL,
    context_json TEXT NOT NULL DEFAULT '{}',
    model_json TEXT NOT NULL DEFAULT '{}',
    confirmed_at TEXT NOT NULL DEFAULT '',
    solve_job_id TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS conversation_messages (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES conversation_sessions(id) ON DELETE CASCADE,
    organization_id TEXT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'text',
    content TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS conversation_files (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES conversation_sessions(id) ON DELETE CASCADE,
    organization_id TEXT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    purpose TEXT NOT NULL,
    original_name TEXT NOT NULL,
    content_type TEXT NOT NULL DEFAULT 'application/octet-stream',
    size_bytes INTEGER NOT NULL DEFAULT 0,
    sha256 TEXT NOT NULL,
    storage_path TEXT NOT NULL,
    summary_json TEXT NOT NULL DEFAULT '{}',
    created_by TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_conversation_sessions_owner_updated
ON conversation_sessions(organization_id, created_by, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_conversation_messages_session_created
ON conversation_messages(organization_id, session_id, created_at, id);

CREATE INDEX IF NOT EXISTS idx_conversation_files_session_created
ON conversation_files(organization_id, session_id, created_at, id);
""",
    ),
    _Migration(
        version=6,
        description="hard account expiry for bounded trial access",
        sql="""
ALTER TABLE users ADD COLUMN expires_at TEXT NOT NULL DEFAULT '';

CREATE INDEX IF NOT EXISTS idx_users_active_expiry
ON users(organization_id, status, expires_at)
WHERE expires_at <> '';
""",
    ),
)


class PlatformDatabase:
    def __init__(self, settings: PlatformDatabaseSettings) -> None:
        self.settings = settings

    @property
    def path(self) -> Path:
        return self.settings.path

    def initialize(self) -> tuple[int, ...]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    description TEXT NOT NULL,
                    applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            applied = {
                int(row["version"])
                for row in connection.execute("SELECT version FROM schema_migrations").fetchall()
            }
            for migration in _MIGRATIONS:
                if migration.version in applied:
                    continue
                escaped_description = migration.description.replace("'", "''")
                script = (
                    "BEGIN IMMEDIATE;\n"
                    + migration.sql
                    + "\nINSERT INTO schema_migrations(version, description) VALUES "
                    + f"({migration.version}, '{escaped_description}');\nCOMMIT;"
                )
                try:
                    connection.executescript(script)
                except Exception:
                    if connection.in_transaction:
                        connection.rollback()
                    raise
        return self.applied_versions()

    def applied_versions(self) -> tuple[int, ...]:
        if not self.path.exists():
            return ()
        with self.connect() as connection:
            rows = connection.execute("SELECT version FROM schema_migrations ORDER BY version").fetchall()
        return tuple(int(row["version"]) for row in rows)

    def integrity_check(self) -> str:
        with self.connect() as connection:
            row = connection.execute("PRAGMA integrity_check").fetchone()
        return str(row[0] if row is not None else "unknown")

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(
            str(self.path),
            timeout=max(1.0, self.settings.busy_timeout_ms / 1000),
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute(f"PRAGMA busy_timeout = {int(self.settings.busy_timeout_ms)}")
            connection.execute("PRAGMA journal_mode = WAL")
            yield connection
        finally:
            connection.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
            except Exception:
                connection.rollback()
                raise
            else:
                connection.commit()
