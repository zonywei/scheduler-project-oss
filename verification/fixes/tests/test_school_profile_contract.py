from __future__ import annotations

import sys
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


from scheduler.app.academic_affairs import SCHOOL_DAYS  # noqa: E402
from scheduler.calendar import ALL_DAYS, DEFAULT_NIGHT_DAYS, SUNDAY  # noqa: E402
from scheduler.domain.school_profile import (  # noqa: E402
    CalendarSpec,
    SchoolProfile,
    default_high_school_profile,
    profile_from_legacy_config,
    profile_from_mapping,
    validate_school_profile,
)


def test_default_high_school_profile_is_valid_and_excel_friendly() -> None:
    profile = default_high_school_profile()

    assert validate_school_profile(profile) == ()
    assert profile.profile_id == "base_high_school"
    assert profile.stage == "senior"
    assert profile.calendar.teaching_days == ALL_DAYS
    assert profile.calendar.night_days == DEFAULT_NIGHT_DAYS
    assert "excel_friendly" in profile.tags


def test_legacy_config_profile_preserves_night_calendar_without_solver_side_effects() -> None:
    profile = profile_from_legacy_config(
        {
            "calendar": {
                "days": ["星期三", "星期一", SUNDAY],
                "periods": ["晚自习A", "晚自习B"],
            }
        }
    )

    assert validate_school_profile(profile) == ()
    assert profile.source == "legacy_config"
    assert profile.calendar.teaching_days == ALL_DAYS
    assert profile.calendar.night_days == ("星期一", "星期三", SUNDAY)
    assert {"night.1", "night.2"} <= set(profile.calendar.period_ids)


def test_school_profile_validation_blocks_unknown_days_and_empty_periods() -> None:
    profile = SchoolProfile(
        profile_id="bad",
        name="Bad School",
        stage="senior",
        calendar=CalendarSpec(teaching_days=("星期八",), night_days=(), period_groups=()),
    )

    errors = validate_school_profile(profile)
    assert any("unknown days" in error for error in errors)
    assert "at least one period is required" in errors


def test_academic_affairs_uses_canonical_school_days() -> None:
    assert SCHOOL_DAYS == list(ALL_DAYS)


def test_current_school_profile_is_persisted_and_matches_legacy_calendar() -> None:
    profile_path = REPO_ROOT / "profiles" / "current_school" / "profile.yaml"
    rules_path = REPO_ROOT / "scheduler" / "config" / "rules.yaml"

    profile_data = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    rules_data = yaml.safe_load(rules_path.read_text(encoding="utf-8"))
    profile_source = profile_path.relative_to(REPO_ROOT).as_posix()
    profile = profile_from_mapping(profile_data, source=profile_source)

    assert validate_school_profile(profile) == ()
    assert profile.profile_id == "current_school"
    assert profile.source == "profiles/current_school/profile.yaml"
    assert profile.calendar.teaching_days == ALL_DAYS
    assert profile.calendar.night_days == tuple(rules_data["calendar"]["days"])
    assert {"early.1", "morning.1", "afternoon.1", "night.1", "night.2"} <= set(profile.calendar.period_ids)
    assert profile_data["rule_instance_sources"]["legacy_rules_file"] == "scheduler/config/rules.yaml"
    assert profile_data["metadata"]["migration_note"].startswith("匿名示例 Profile")
    assert "真实学校" in profile_data["metadata"]["open_source_note"]


def test_anonymous_cross_school_profile_fixtures_are_valid() -> None:
    expected = {
        "base_high_school": "senior",
        "junior_day_school": "junior",
        "primary_after_school": "primary",
    }
    for profile_id, stage in expected.items():
        path = REPO_ROOT / "profiles" / profile_id / "profile.yaml"
        profile = profile_from_mapping(yaml.safe_load(path.read_text(encoding="utf-8")), source=path.relative_to(REPO_ROOT).as_posix())

        assert validate_school_profile(profile) == ()
        assert profile.profile_id == profile_id
        assert profile.stage == stage
        assert profile.calendar.teaching_days
        assert profile.calendar.period_ids
