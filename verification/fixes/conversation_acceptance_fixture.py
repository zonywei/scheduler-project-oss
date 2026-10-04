"""Create an isolated, synthetic fixture for conversational GUI acceptance.

This script never edits repository configuration or the existing runtime database.
Every generated artifact is placed below a fresh ``tempfile.mkdtemp`` directory.
It intentionally leaves AI provider settings absent: the application can exercise
the local conversation skill without making an external model request.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import Any

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scheduler.data.day_rules_reader import (  # noqa: E402
    ALL_DAYS,
    SHEET_FIXED,
    SHEET_HOURS,
    SHEET_OVERRIDES,
    SHEET_SUBJECT_BANS,
    SHEET_TIME_GRID,
    load_fixed_slots,
    load_subject_hours,
    load_teacher_positioning,
    load_time_grid_rules,
)
from scheduler.platform.database import PlatformDatabase, PlatformDatabaseSettings  # noqa: E402
from scheduler.platform.store import PlatformStore  # noqa: E402


FIXTURE_SLUG = "gui-conversation-acceptance"
ORGANIZATION_ID = "00000000-0000-4000-8000-000000000187"


def _teacher_workbook(path: Path) -> None:
    # Deliberately omit 技术、班主任、班主任性别: the reader treats every other
    # non-structural column as a subject and must not require these optional fields.
    frame = pd.DataFrame(
        [
            {"班级": "ClassA", "机器人": "Teacher001", "天文": "Teacher002"},
            {"班级": "ClassB", "机器人": "Teacher001", "天文": "Teacher002"},
        ],
        columns=["班级", "机器人", "天文"],
    )
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        frame.to_excel(writer, index=False, sheet_name="Sheet1")


def _rules_workbook(path: Path) -> None:
    days = list(ALL_DAYS)
    time_rows: list[dict[str, Any]] = []
    for label in ("上午1", "上午2", "下午1", "下午2"):
        time_rows.append(
            {"时段节次": label, **{day: int(day in days[:5]) for day in days}}
        )
    hours = pd.DataFrame(
        [
            {"学科": "机器人", "早自习课时": 0, "周中课时": 2, "周末课时": 0},
            {"学科": "天文", "早自习课时": 0, "周中课时": 2, "周末课时": 0},
        ],
        columns=["学科", "早自习课时", "周中课时", "周末课时"],
    )
    # Include all current reader sheet names, with valid empty schemas for the
    # optional rule tables. This keeps upload/inspection behavior realistic.
    fixed = pd.DataFrame(columns=["作用范围", "班级", "星期", "时段", "节次", "学科"])
    bans = pd.DataFrame(columns=["学科", "禁排星期", "禁排时段", "节次"])
    overrides = pd.DataFrame(columns=["班级", "学科", "早自习课时", "周中课时", "周末课时"])
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        pd.DataFrame(time_rows, columns=["时段节次", *days]).to_excel(
            writer, index=False, sheet_name=SHEET_TIME_GRID
        )
        fixed.to_excel(writer, index=False, sheet_name=SHEET_FIXED)
        hours.to_excel(writer, index=False, sheet_name=SHEET_HOURS)
        bans.to_excel(writer, index=False, sheet_name=SHEET_SUBJECT_BANS)
        overrides.to_excel(writer, index=False, sheet_name=SHEET_OVERRIDES)


def _new_sqlite_workspace(database_path: Path) -> dict[str, Any]:
    database = PlatformDatabase(PlatformDatabaseSettings(path=database_path))
    applied = database.initialize()
    store = PlatformStore(database)
    organization = store.create_organization(
        slug=FIXTURE_SLUG,
        name="GUI对话验收合成组织",
        organization_id=ORGANIZATION_ID,
    )
    workspace = store.save_workspace(
        organization.id,
        {},
        expected_revision=None,
        actor_user_id="fixture",
        reason="isolated conversation GUI acceptance fixture",
    )
    assert workspace.payload == {}, "fixture workspace must remain empty"
    assert database.integrity_check() == "ok"
    with sqlite3.connect(database_path) as connection:
        org_count = connection.execute("SELECT COUNT(*) FROM organizations").fetchone()[0]
        workspace_count = connection.execute("SELECT COUNT(*) FROM workspace_snapshots").fetchone()[0]
    assert (org_count, workspace_count) == (1, 1)
    return {
        "database_schema_versions": list(applied),
        "organization_id": organization.id,
        "organization_slug": organization.slug,
        "workspace_revision": workspace.revision,
        "workspace_payload": workspace.payload,
    }


def build_fixture() -> dict[str, Any]:
    root = Path(tempfile.mkdtemp(prefix="scheduler-conversation-gui-"))
    uploads = root / "conversation_uploads"
    uploads.mkdir()
    database_path = root / "fixture.sqlite3"
    teacher_path = root / "synthetic_teacher_subjects.xlsx"
    rules_path = root / "synthetic_day_rules.xlsx"
    env_path = root / "web.env.json"
    _teacher_workbook(teacher_path)
    _rules_workbook(rules_path)

    # Reader-level verification uses the same public reader functions as the app.
    classes, relations = load_teacher_positioning(teacher_path)
    slots = load_time_grid_rules(rules_path)
    subject_hours = load_subject_hours(rules_path)
    fixed = load_fixed_slots(rules_path, classes)
    assert classes == ["ClassA", "ClassB"]
    assert relations[("ClassA", "机器人")] == "Teacher001"
    assert relations[("ClassB", "天文")] == "Teacher002"
    assert len(slots) == 20
    assert subject_hours == {"机器人": (0, 2, 0), "天文": (0, 2, 0)}
    assert fixed == {}

    database = _new_sqlite_workspace(database_path)
    env = {
        "SCHEDULER_STATE_BACKEND": "sqlite",
        "SCHEDULER_DATABASE_PATH": str(database_path),
        "SCHEDULER_DATA_DIR": str(root),
        "SCHEDULER_ORGANIZATION_ID": database["organization_id"],
        "SCHEDULER_ORGANIZATION_SLUG": database["organization_slug"],
        "SCHEDULER_WORKSPACE_REVISION": str(database["workspace_revision"]),
        "SCHEDULER_AUTH_MODE": "disabled",
        "SCHEDULER_CONVERSATIONAL_SCHEDULING_ENABLED": "true",
        "SCHEDULER_SOLVE_MODE": "async",
        "SCHEDULER_ALLOW_INSECURE_HTTP": "true",
        "SCHEDULER_GUI_HOST": "127.0.0.1",
        "SCHEDULER_GUI_PORT": "18765",
        "SCHEDULER_AI_PROVIDER_CONFIGURED": "false",
        "SCHEDULER_EXTERNAL_MODEL_REQUESTS": "disabled",
    }
    env_path.write_text(json.dumps(env, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest = {
        "fixture_root": str(root),
        "environment_json": str(env_path),
        "database": str(database_path),
        "teacher_workbook": str(teacher_path),
        "rules_workbook": str(rules_path),
        "conversation_upload_root": str(uploads),
        "cwd": str(PROJECT_ROOT),
        "interpreter": sys.executable,
        "web": {"host": "127.0.0.1", "port": 18765, "auth": "disabled-loopback-only"},
        "web_start": {
            "command": f"\"{sys.executable}\" -m scheduler.app.web --host 127.0.0.1 --port 18765",
            "cwd": str(PROJECT_ROOT),
        },
        "verified": {
            "sqlite_integrity": "ok",
            "organization_count": 1,
            "empty_workspace": True,
            "classes": classes,
            "teachers": ["Teacher001", "Teacher002"],
            "subjects": ["机器人", "天文"],
            "time_grid_slots": len(slots),
            "subject_hours": subject_hours,
            "fixed_slots": len(fixed),
        },
        "scope_boundary": [
            "Only a new fixture directory under tempfile.mkdtemp was written.",
            "No repository config, existing SQLite, outputs, or server process was changed.",
            "No external model provider is configured or called.",
            "This prepares browser acceptance; it does not claim complete AI or solver success.",
        ],
    }
    return manifest


def main() -> None:
    manifest = build_fixture()
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
