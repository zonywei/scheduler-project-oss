"""Online SQLite backups and guarded offline restore operations."""
from __future__ import annotations

import os
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def create_database_backup(database_path: Path, output_path: Path) -> dict[str, Any]:
    source = Path(database_path).resolve()
    target = Path(output_path).resolve()
    if not source.exists() or not source.is_file():
        raise FileNotFoundError(f"database does not exist: {source}")
    if source == target:
        raise ValueError("backup path must differ from the live database")
    if target.exists():
        raise FileExistsError(f"backup already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.tmp-{uuid.uuid4().hex}")
    try:
        _copy_sqlite(source, temporary)
        inspection = inspect_database_backup(temporary)
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()
    return {
        "schema_version": "scheduler.database_backup.v1",
        "backup": str(target),
        "size_bytes": target.stat().st_size,
        **inspection,
    }


def inspect_database_backup(path: Path) -> dict[str, Any]:
    target = Path(path).resolve()
    if not target.exists() or not target.is_file():
        raise FileNotFoundError(f"backup does not exist: {target}")
    uri = f"file:{target.as_posix()}?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as connection:
        integrity_row = connection.execute("PRAGMA integrity_check").fetchone()
        integrity = str(integrity_row[0] if integrity_row else "unknown")
        if integrity != "ok":
            raise ValueError(f"backup integrity check failed: {integrity}")
        tables = {
            str(row[0])
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
        }
        required = {"schema_migrations", "organizations", "workspace_snapshots"}
        missing = sorted(required - tables)
        if missing:
            raise ValueError("backup is missing required tables: " + ", ".join(missing))
        versions = [
            int(row[0])
            for row in connection.execute("SELECT version FROM schema_migrations ORDER BY version").fetchall()
        ]
        organizations = int(connection.execute("SELECT COUNT(*) FROM organizations").fetchone()[0])
        workspaces = int(connection.execute("SELECT COUNT(*) FROM workspace_snapshots").fetchone()[0])
    return {
        "integrity": integrity,
        "migration_versions": versions,
        "organization_count": organizations,
        "workspace_count": workspaces,
    }


def restore_database_backup(
    backup_path: Path,
    database_path: Path,
    *,
    recovery_directory: Path | None = None,
) -> dict[str, Any]:
    backup = Path(backup_path).resolve()
    target = Path(database_path).resolve()
    if backup == target:
        raise ValueError("backup path must differ from the restore target")
    inspection = inspect_database_backup(backup)
    target.parent.mkdir(parents=True, exist_ok=True)
    recovery_backup = ""
    if target.exists():
        _assert_exclusive_database_access(target)
        recovery_root = Path(recovery_directory).resolve() if recovery_directory else target.parent / "backups"
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        recovery_path = recovery_root / f"{target.stem}.pre-restore-{stamp}.db"
        recovery_backup = str(Path(create_database_backup(target, recovery_path)["backup"]))

    temporary = target.with_name(f".{target.name}.restore-{uuid.uuid4().hex}")
    try:
        _copy_sqlite(backup, temporary)
        inspect_database_backup(temporary)
        for suffix in ("-wal", "-shm"):
            sidecar = Path(str(target) + suffix)
            if sidecar.exists():
                sidecar.unlink()
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()
    return {
        "schema_version": "scheduler.database_restore.v1",
        "database": str(target),
        "source_backup": str(backup),
        "recovery_backup": recovery_backup,
        **inspection,
    }


def _copy_sqlite(source: Path, target: Path) -> None:
    source_uri = f"file:{source.as_posix()}?mode=ro"
    with closing(sqlite3.connect(source_uri, uri=True, timeout=10)) as source_connection:
        with closing(sqlite3.connect(str(target), timeout=10)) as target_connection:
            source_connection.backup(target_connection)
            target_connection.commit()


def _assert_exclusive_database_access(path: Path) -> None:
    try:
        with closing(sqlite3.connect(str(path), timeout=0.25, isolation_level=None)) as connection:
            connection.execute("BEGIN EXCLUSIVE")
            connection.rollback()
    except sqlite3.OperationalError as exc:
        raise RuntimeError("database is busy; stop Web and Worker services before restore") from exc
