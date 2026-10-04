"""Explicit, non-destructive imports from the legacy YAML workspace."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from scheduler.platform.database import PlatformDatabase, PlatformDatabaseSettings
from scheduler.platform.store import PlatformStore, TenantNotFound


def import_yaml_workspace(
    *,
    database_path: Path,
    yaml_path: Path,
    organization_slug: str,
    organization_name: str,
    actor_user_id: str = "migration",
    force: bool = False,
) -> dict[str, Any]:
    source_path = Path(yaml_path).resolve()
    if not source_path.exists() or not source_path.is_file():
        raise FileNotFoundError(f"workspace YAML not found: {source_path}")
    raw = yaml.safe_load(source_path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError("workspace YAML root must be an object")

    store = PlatformStore(PlatformDatabase(PlatformDatabaseSettings(path=Path(database_path).resolve())))
    versions = store.initialize()
    try:
        organization = store.get_organization_by_slug(organization_slug)
    except TenantNotFound:
        organization = store.create_organization(slug=organization_slug, name=organization_name)

    current = store.load_workspace(organization.id)
    if current is not None and not force:
        return {
            "schema_version": "scheduler.workspace-migration.v1",
            "imported": False,
            "reason": "workspace already exists; use --force to create a new revision",
            "database": str(store.database.path),
            "source": str(source_path),
            "organization_id": organization.id,
            "organization_slug": organization.slug,
            "revision": current.revision,
            "migration_versions": list(versions),
        }

    saved = store.save_workspace(
        organization.id,
        raw,
        expected_revision=current.revision if current is not None else 0,
        actor_user_id=actor_user_id,
        reason=f"import legacy YAML: {source_path.name}",
    )
    imported_rule_drafts = 0
    temporary = raw.get("temporary_rules") if isinstance(raw.get("temporary_rules"), dict) else {}
    for item in temporary.get("active") or []:
        if not isinstance(item, dict) or not item.get("schema_version"):
            continue
        try:
            store.save_rule_draft(organization.id, item, actor_user_id=actor_user_id)
        except ValueError:
            continue
        imported_rule_drafts += 1

    return {
        "schema_version": "scheduler.workspace-migration.v1",
        "imported": True,
        "database": str(store.database.path),
        "source": str(source_path),
        "organization_id": organization.id,
        "organization_slug": organization.slug,
        "revision": saved.revision,
        "imported_rule_drafts": imported_rule_drafts,
        "migration_versions": list(versions),
        "source_preserved": source_path.exists(),
    }
