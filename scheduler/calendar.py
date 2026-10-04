# -*- coding: utf-8 -*-
"""Canonical calendar and time-scope helpers for scheduler rules.

Keep day names in one place so constraint modules do not drift when the
weekday/weekend/night calendars evolve independently.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Sequence, Tuple


MONDAY = "星期一"
TUESDAY = "星期二"
WEDNESDAY = "星期三"
THURSDAY = "星期四"
FRIDAY = "星期五"
SATURDAY = "星期六"
SUNDAY = "星期日"

DAY_ORDER: Tuple[str, ...] = (
    MONDAY,
    TUESDAY,
    WEDNESDAY,
    THURSDAY,
    FRIDAY,
    SATURDAY,
    SUNDAY,
)
WEEKDAY_DAYS: Tuple[str, ...] = DAY_ORDER[:5]
WEEKEND_DAYS: Tuple[str, ...] = DAY_ORDER[5:]
ALL_DAYS: Tuple[str, ...] = DAY_ORDER
TUESDAY_TO_FRIDAY: Tuple[str, ...] = (TUESDAY, WEDNESDAY, THURSDAY, FRIDAY)
DEFAULT_NIGHT_DAYS: Tuple[str, ...] = (*WEEKDAY_DAYS, SUNDAY)
DAY_NAME_SET = frozenset(DAY_ORDER)


def normalize_day(day: object) -> str:
    return str(day).strip()


def is_weekday_day(day: object) -> bool:
    return normalize_day(day) in WEEKDAY_DAYS


def is_weekend_day(day: object) -> bool:
    return normalize_day(day) in WEEKEND_DAYS


def ordered_days(days: Iterable[object]) -> List[str]:
    present = {normalize_day(day) for day in days if normalize_day(day)}
    return [day for day in DAY_ORDER if day in present]


def day_rank(day: object, default: int = 99) -> int:
    """Return the one-based rank in Monday..Sunday order."""
    normalized = normalize_day(day)
    try:
        return DAY_ORDER.index(normalized) + 1
    except ValueError:
        return default


def previous_day(day: object, *, wrap: bool = True) -> str | None:
    """Return the previous day in canonical week order."""
    normalized = normalize_day(day)
    try:
        index = DAY_ORDER.index(normalized)
    except ValueError:
        return None
    if index == 0:
        return DAY_ORDER[-1] if wrap else None
    return DAY_ORDER[index - 1]


def adjacent_day_pairs(days: Sequence[str], include_sun_mon: bool = True) -> List[Tuple[str, str]]:
    """Return adjacent day pairs in canonical Monday..Sunday order."""
    present = set(ordered_days(days))
    pairs: List[Tuple[str, str]] = []
    for d1, d2 in zip(DAY_ORDER, DAY_ORDER[1:]):
        if d1 in present and d2 in present:
            pairs.append((d1, d2))
    if include_sun_mon and SUNDAY in present and MONDAY in present:
        pairs.append((SUNDAY, MONDAY))
    return pairs


def day_night_bridge_days(night_days: Sequence[str] | None = None) -> Tuple[str, ...]:
    """Days whose daytime load can participate in day-night bridge rules.

    Existing defaults use Monday-Friday plus Sunday night. If the night calendar
    later explicitly enables Saturday, Saturday daytime is included as well.
    """
    if night_days is None:
        enabled_weekend_nights = {SUNDAY}
    else:
        enabled_weekend_nights = set(ordered_days(night_days)) & set(WEEKEND_DAYS)
    return WEEKDAY_DAYS + tuple(day for day in WEEKEND_DAYS if day in enabled_weekend_nights)


@dataclass(frozen=True)
class CalendarScope:
    """Small value object for code that needs named calendar scopes."""

    day_order: Tuple[str, ...] = DAY_ORDER
    weekday_days: Tuple[str, ...] = WEEKDAY_DAYS
    weekend_days: Tuple[str, ...] = WEEKEND_DAYS

    def ordered(self, days: Iterable[object]) -> List[str]:
        return ordered_days(days)

    def day_rank(self, day: object, default: int = 99) -> int:
        return day_rank(day, default=default)

    def previous_day(self, day: object, *, wrap: bool = True) -> str | None:
        return previous_day(day, wrap=wrap)

    def adjacent_pairs(self, days: Sequence[str], include_sun_mon: bool = True) -> List[Tuple[str, str]]:
        return adjacent_day_pairs(days, include_sun_mon=include_sun_mon)

    def day_night_bridge_days(self, night_days: Sequence[str] | None = None) -> Tuple[str, ...]:
        return day_night_bridge_days(night_days)
