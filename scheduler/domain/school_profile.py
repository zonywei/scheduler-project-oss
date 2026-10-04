# -*- coding: utf-8 -*-
"""School profile contracts for cross-school reuse.

This module is intentionally side-effect free. It gives the existing solver a
stable product-facing vocabulary before the current Excel/YAML inputs are
gradually adapted into profile-backed problem instances.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from scheduler.calendar import ALL_DAYS, DEFAULT_NIGHT_DAYS, ordered_days


SUPPORTED_STAGES = frozenset({"primary", "junior", "senior", "mixed"})


@dataclass(frozen=True)
class PeriodSpec:
    id: str
    label: str
    group: str
    index: int
    teaching: bool = True


@dataclass(frozen=True)
class PeriodGroup:
    id: str
    label: str
    periods: tuple[PeriodSpec, ...]


@dataclass(frozen=True)
class CalendarSpec:
    teaching_days: tuple[str, ...] = ALL_DAYS
    night_days: tuple[str, ...] = ()
    period_groups: tuple[PeriodGroup, ...] = ()

    @property
    def period_ids(self) -> tuple[str, ...]:
        return tuple(period.id for group in self.period_groups for period in group.periods)


@dataclass(frozen=True)
class SchoolProfile:
    profile_id: str
    name: str
    stage: str
    calendar: CalendarSpec
    campuses: tuple[str, ...] = ("main",)
    tags: tuple[str, ...] = ()
    source: str = "in_memory"
    metadata: Mapping[str, Any] = field(default_factory=dict)


def _day_tuple(days: Sequence[str] | None, *, default: tuple[str, ...]) -> tuple[str, ...]:
    if not days:
        return default
    return tuple(ordered_days(days))


def _default_day_periods() -> tuple[PeriodGroup, ...]:
    early = PeriodGroup(
        id="early",
        label="早自习",
        periods=(PeriodSpec(id="early.1", label="早自习1", group="early", index=1),),
    )
    morning = PeriodGroup(
        id="morning",
        label="上午",
        periods=tuple(
            PeriodSpec(id=f"morning.{index}", label=f"上午{index}", group="morning", index=index)
            for index in range(1, 5)
        ),
    )
    afternoon = PeriodGroup(
        id="afternoon",
        label="下午",
        periods=tuple(
            PeriodSpec(id=f"afternoon.{index}", label=f"下午{index}", group="afternoon", index=index)
            for index in range(1, 5)
        ),
    )
    return (early, morning, afternoon)


def _night_period_group(period_labels: Sequence[str]) -> PeriodGroup:
    periods = tuple(
        PeriodSpec(
            id=f"night.{index}",
            label=str(label).strip() or f"晚自习{index}",
            group="night",
            index=index,
        )
        for index, label in enumerate(period_labels, start=1)
    )
    return PeriodGroup(id="night", label="晚自习", periods=periods)


def default_high_school_profile() -> SchoolProfile:
    night_group = _night_period_group(("晚自习1", "晚自习2"))
    return SchoolProfile(
        profile_id="base_high_school",
        name="通用高中模板",
        stage="senior",
        calendar=CalendarSpec(
            teaching_days=ALL_DAYS,
            night_days=DEFAULT_NIGHT_DAYS,
            period_groups=(*_default_day_periods(), night_group),
        ),
        tags=("boarding_optional", "excel_friendly"),
        source="built_in",
    )


def profile_from_legacy_config(
    effective_config: Mapping[str, Any],
    *,
    profile_id: str = "legacy_current_school",
    name: str = "当前学校",
    stage: str = "senior",
) -> SchoolProfile:
    """Build a profile shell from today's merged config without changing solver behavior."""
    calendar_cfg = effective_config.get("calendar") or {}
    night_days = _day_tuple(calendar_cfg.get("days"), default=())
    night_periods = tuple(str(item).strip() for item in (calendar_cfg.get("periods") or ()) if str(item).strip())
    groups = _default_day_periods()
    if night_periods:
        groups = (*groups, _night_period_group(night_periods))
    return SchoolProfile(
        profile_id=profile_id,
        name=name,
        stage=stage,
        calendar=CalendarSpec(teaching_days=ALL_DAYS, night_days=night_days, period_groups=groups),
        source="legacy_config",
    )


def profile_from_mapping(data: Mapping[str, Any], *, source: str = "mapping") -> SchoolProfile:
    """Build a profile from a persisted profile mapping without touching solver config."""
    calendar_cfg = data.get("calendar") or {}
    groups = tuple(_period_group_from_mapping(group) for group in (calendar_cfg.get("period_groups") or ()))
    if not groups:
        groups = _default_day_periods()
    return SchoolProfile(
        profile_id=str(data.get("profile_id") or "").strip(),
        name=str(data.get("name") or "").strip(),
        stage=str(data.get("stage") or "").strip(),
        calendar=CalendarSpec(
            teaching_days=_day_tuple(calendar_cfg.get("teaching_days"), default=ALL_DAYS),
            night_days=_day_tuple(calendar_cfg.get("night_days"), default=()),
            period_groups=groups,
        ),
        campuses=tuple(str(item).strip() for item in (data.get("campuses") or ("main",)) if str(item).strip()),
        tags=tuple(str(item).strip() for item in (data.get("tags") or ()) if str(item).strip()),
        source=source,
        metadata=dict(data.get("metadata") or {}),
    )


def _period_group_from_mapping(group: Mapping[str, Any]) -> PeriodGroup:
    group_id = str(group.get("id") or "").strip()
    group_label = str(group.get("label") or group_id).strip()
    periods: list[PeriodSpec] = []
    for index, item in enumerate(group.get("periods") or (), start=1):
        if isinstance(item, Mapping):
            label = str(item.get("label") or item.get("id") or "").strip()
            period_id = str(item.get("id") or f"{group_id}.{index}").strip()
            teaching = bool(item.get("teaching", True))
        else:
            label = str(item).strip()
            period_id = f"{group_id}.{index}"
            teaching = True
        periods.append(
            PeriodSpec(
                id=period_id,
                label=label or f"{group_label}{index}",
                group=group_id,
                index=index,
                teaching=teaching,
            )
        )
    return PeriodGroup(id=group_id, label=group_label, periods=tuple(periods))


def validate_school_profile(profile: SchoolProfile) -> tuple[str, ...]:
    errors: list[str] = []
    if not profile.profile_id.strip():
        errors.append("profile_id is required")
    if not profile.name.strip():
        errors.append("name is required")
    if profile.stage not in SUPPORTED_STAGES:
        errors.append(f"unsupported stage: {profile.stage}")
    if not profile.campuses:
        errors.append("at least one campus is required")

    valid_days = set(ALL_DAYS)
    for field_name, days in (
        ("teaching_days", profile.calendar.teaching_days),
        ("night_days", profile.calendar.night_days),
    ):
        unknown = [day for day in days if day not in valid_days]
        if unknown:
            errors.append(f"{field_name} contains unknown days: {unknown}")

    period_ids = profile.calendar.period_ids
    if len(period_ids) != len(set(period_ids)):
        errors.append("period ids must be unique")
    if not period_ids:
        errors.append("at least one period is required")
    return tuple(errors)
