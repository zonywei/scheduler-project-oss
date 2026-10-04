"""Administrative CLI for platform database migration and inspection."""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from scheduler.platform.database import PlatformDatabase, PlatformDatabaseSettings
from scheduler.platform.auth import ALLOWED_ROLES, AuthService
from scheduler.platform.backup import create_database_backup, inspect_database_backup, restore_database_backup
from scheduler.platform.migration import import_yaml_workspace
from scheduler.platform.model_usage import ModelUsageStore
from scheduler.platform.health import platform_health
from scheduler.platform.store import PlatformStore


def main() -> None:
    parser = argparse.ArgumentParser(description="Scheduler platform database administration")
    parser.add_argument("--database", type=Path, default=None, help="SQLite database path")
    subparsers = parser.add_subparsers(dest="command", required=True)

    migrate = subparsers.add_parser("migrate-yaml", help="Import a legacy web_overrides.yaml non-destructively")
    migrate.add_argument("--yaml", type=Path, default=Path("scheduler/config/web_overrides.yaml"))
    migrate.add_argument("--slug", default="current-school")
    migrate.add_argument("--name", default="当前学校")
    migrate.add_argument("--actor", default="migration")
    migrate.add_argument("--force", action="store_true")

    inspect = subparsers.add_parser("check", help="Check schema, integrity, and an organization workspace")
    inspect.add_argument("--slug", default="current-school")

    create_user = subparsers.add_parser("create-user", help="Create a tenant user from a secret source")
    _add_user_arguments(create_user)

    ensure_user = subparsers.add_parser(
        "ensure-user",
        help="Create or reconcile a deployment-managed tenant user from a secret source",
    )
    _add_user_arguments(ensure_user)

    quota = subparsers.add_parser("set-model-quota", help="Set a monthly organization or user model quota")
    quota.add_argument("--slug", default="current-school")
    quota.add_argument("--scope-user-id", default="")
    quota.add_argument("--request-limit", type=int, default=0)
    quota.add_argument("--token-limit", type=int, default=0)
    quota.add_argument("--cost-limit-microunits", type=int, default=0)
    quota.add_argument("--actor", default="bootstrap")

    usage = subparsers.add_parser("model-usage", help="Show the current monthly model usage ledger")
    usage.add_argument("--slug", default="current-school")
    usage.add_argument("--scope-user-id", default="")

    backup = subparsers.add_parser("backup", help="Create an online SQLite backup")
    backup.add_argument("--output", type=Path, required=True)

    verify_backup = subparsers.add_parser("verify-backup", help="Verify a SQLite backup without modifying it")
    verify_backup.add_argument("--backup", type=Path, required=True)

    restore = subparsers.add_parser("restore", help="Restore a verified backup after services are stopped")
    restore.add_argument("--backup", type=Path, required=True)
    restore.add_argument("--confirm-target", type=Path, required=True)
    restore.add_argument("--recovery-directory", type=Path, default=None)

    health = subparsers.add_parser("health", help="Check database, workspace, and optional Worker heartbeat")
    health.add_argument("--slug", default="current-school")
    health.add_argument("--require-worker", action="store_true")

    args = parser.parse_args()
    database_path = Path(args.database).resolve() if args.database else PlatformDatabaseSettings.from_environment().path
    if args.command == "migrate-yaml":
        result = import_yaml_workspace(
            database_path=database_path,
            yaml_path=Path(args.yaml),
            organization_slug=str(args.slug),
            organization_name=str(args.name),
            actor_user_id=str(args.actor),
            force=bool(args.force),
        )
    elif args.command == "check":
        result = _check(database_path, str(args.slug))
    elif args.command == "create-user":
        expires_at = _expiry_from_arguments(str(args.expires_at), int(args.expires_in_hours))
        result = _create_user(
            database_path,
            slug=str(args.slug),
            username=str(args.username),
            display_name=str(args.display_name),
            role=str(args.role),
            password_env=str(args.password_env),
            password_file=Path(args.password_file) if args.password_file else None,
            expires_at=expires_at,
        )
    elif args.command == "ensure-user":
        expires_at = _expiry_from_arguments(str(args.expires_at), int(args.expires_in_hours))
        result = _ensure_user(
            database_path,
            slug=str(args.slug),
            username=str(args.username),
            display_name=str(args.display_name),
            role=str(args.role),
            password_env=str(args.password_env),
            password_file=Path(args.password_file) if args.password_file else None,
            expires_at=expires_at,
        )
    elif args.command == "set-model-quota":
        result = _set_model_quota(
            database_path,
            slug=str(args.slug),
            scope_user_id=str(args.scope_user_id),
            request_limit=int(args.request_limit),
            token_limit=int(args.token_limit),
            cost_limit_microunits=int(args.cost_limit_microunits),
            actor_user_id=str(args.actor),
        )
    elif args.command == "model-usage":
        result = _model_usage(
            database_path,
            slug=str(args.slug),
            scope_user_id=str(args.scope_user_id),
        )
    elif args.command == "backup":
        result = create_database_backup(database_path, Path(args.output))
    elif args.command == "verify-backup":
        result = inspect_database_backup(Path(args.backup))
        result = {"schema_version": "scheduler.database_backup_check.v1", "backup": str(Path(args.backup).resolve()), **result}
    elif args.command == "restore":
        confirmed = Path(args.confirm_target).resolve()
        if confirmed != database_path:
            raise ValueError(f"--confirm-target must resolve to the live database path: {database_path}")
        result = restore_database_backup(
            Path(args.backup),
            database_path,
            recovery_directory=Path(args.recovery_directory) if args.recovery_directory else None,
        )
    else:
        store = _initialized_store(database_path)
        organization = store.get_organization_by_slug(str(args.slug))
        result = platform_health(store, organization.id)
        if bool(args.require_worker) and result.get("checks", {}).get("worker") != "healthy":
            result["ready"] = False
            result["status"] = "not_ready"
    sys.stdout.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    if args.command == "health" and not result.get("ready"):
        raise SystemExit(1)


def _check(database_path: Path, slug: str) -> dict[str, Any]:
    database = PlatformDatabase(PlatformDatabaseSettings(path=database_path))
    store = PlatformStore(database)
    versions = store.initialize()
    organization = store.get_organization_by_slug(slug)
    workspace = store.load_workspace(organization.id)
    return {
        "schema_version": "scheduler.platform-check.v1",
        "database": str(database.path),
        "integrity": database.integrity_check(),
        "migration_versions": list(versions),
        "organization": {
            "id": organization.id,
            "slug": organization.slug,
            "name": organization.name,
            "status": organization.status,
        },
        "workspace_revision": workspace.revision if workspace is not None else 0,
        "rule_drafts": len(store.list_rule_drafts(organization.id)),
        "audit_events": len(store.list_audit_events(organization.id, limit=500)),
    }


def _create_user(
    database_path: Path,
    *,
    slug: str,
    username: str,
    display_name: str,
    role: str,
    password_env: str,
    password_file: Path | None = None,
    expires_at: str = "",
) -> dict[str, Any]:
    password = _read_password_secret(password_env=password_env, password_file=password_file)
    database = PlatformDatabase(PlatformDatabaseSettings(path=database_path))
    store = PlatformStore(database)
    store.initialize()
    organization = store.get_organization_by_slug(slug)
    user = AuthService(store).create_user(
        organization.id,
        username=username,
        display_name=display_name,
        role=role,
        password=password,
        expires_at=expires_at,
    )
    return {
        "schema_version": "scheduler.platform-user.v1",
        "database": str(database.path),
        "user": {
            "id": user.user_id,
            "organization_id": user.organization_id,
            "organization_slug": user.organization_slug,
            "username": user.username,
            "display_name": user.display_name,
            "role": user.role,
            "expires_at": _user_expiry(store, user.user_id),
        },
    }


def _ensure_user(
    database_path: Path,
    *,
    slug: str,
    username: str,
    display_name: str,
    role: str,
    password_env: str,
    password_file: Path | None = None,
    expires_at: str = "",
) -> dict[str, Any]:
    password = _read_password_secret(password_env=password_env, password_file=password_file)
    database = PlatformDatabase(PlatformDatabaseSettings(path=database_path))
    store = PlatformStore(database)
    store.initialize()
    organization = store.get_organization_by_slug(slug)
    provisioned = AuthService(store).ensure_user(
        organization.id,
        username=username,
        display_name=display_name,
        role=role,
        password=password,
        expires_at=expires_at,
    )
    user = provisioned.user
    return {
        "schema_version": "scheduler.platform-user-provision.v1",
        "database": str(database.path),
        "created": provisioned.created,
        "changed_fields": list(provisioned.changed_fields),
        "user": {
            "id": user.user_id,
            "organization_id": user.organization_id,
            "organization_slug": user.organization_slug,
            "username": user.username,
            "display_name": user.display_name,
            "role": user.role,
            "expires_at": _user_expiry(store, user.user_id),
        },
    }


def _add_user_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--slug", default="current-school")
    parser.add_argument("--username", required=True)
    parser.add_argument("--display-name", required=True)
    parser.add_argument("--role", required=True, choices=sorted(ALLOWED_ROLES))
    parser.add_argument("--password-env", default="SCHEDULER_BOOTSTRAP_PASSWORD")
    parser.add_argument("--password-file", type=Path, default=None)
    expiry = parser.add_mutually_exclusive_group()
    expiry.add_argument("--expires-at", default="", help="ISO-8601 account expiry; empty means no expiry")
    expiry.add_argument("--expires-in-hours", type=int, default=0, help="Expire the account after 1-8760 hours")


def _expiry_from_arguments(expires_at: str, expires_in_hours: int) -> str:
    raw = str(expires_at or "").strip()
    hours = int(expires_in_hours)
    if raw:
        return raw
    if hours == 0:
        return ""
    if not 1 <= hours <= 8_760:
        raise ValueError("--expires-in-hours must be between 1 and 8760")
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat(timespec="microseconds")


def _user_expiry(store: PlatformStore, user_id: str) -> str:
    with store.database.connect() as connection:
        row = connection.execute("SELECT expires_at FROM users WHERE id = ?", (user_id,)).fetchone()
    return str(row["expires_at"] if row is not None else "")


def _read_password_secret(*, password_env: str, password_file: Path | None) -> str:
    if password_file is not None:
        path = Path(password_file).resolve()
        if not path.exists() or not path.is_file():
            raise ValueError(f"password secret file is not readable: {path}")
        return path.read_text(encoding="utf-8").rstrip("\r\n")
    env_name = str(password_env or "").strip()
    if not env_name:
        raise ValueError("password environment variable name is required")
    password = os.environ.get(env_name)
    if password is None:
        raise ValueError(f"password environment variable is not set: {env_name}")
    return password


def _set_model_quota(
    database_path: Path,
    *,
    slug: str,
    scope_user_id: str,
    request_limit: int,
    token_limit: int,
    cost_limit_microunits: int,
    actor_user_id: str,
) -> dict[str, Any]:
    store = _initialized_store(database_path)
    organization = store.get_organization_by_slug(slug)
    limits = ModelUsageStore(store).set_quota(
        organization.id,
        scope_user_id=scope_user_id,
        request_limit=request_limit,
        token_limit=token_limit,
        cost_limit_microunits=cost_limit_microunits,
        actor_user_id=actor_user_id,
    )
    return {
        "schema_version": "scheduler.model_quota.v1",
        "organization_id": organization.id,
        "scope_user_id": scope_user_id,
        "period": "monthly",
        "request_limit": limits.request_limit,
        "token_limit": limits.token_limit,
        "cost_limit_microunits": limits.cost_limit_microunits,
    }


def _model_usage(database_path: Path, *, slug: str, scope_user_id: str) -> dict[str, Any]:
    store = _initialized_store(database_path)
    organization = store.get_organization_by_slug(slug)
    return ModelUsageStore(store).summary(organization.id, user_id=scope_user_id)


def _initialized_store(database_path: Path) -> PlatformStore:
    store = PlatformStore(PlatformDatabase(PlatformDatabaseSettings(path=database_path)))
    store.initialize()
    return store


if __name__ == "__main__":
    main()
