# -*- coding: utf-8 -*-
"""Helpers for configurable teacher-targeted constraints."""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any


def norm_teacher_name(value: object) -> str:
    """Normalize teacher names for matching while preserving display names elsewhere."""
    return "".join(str(value or "").split())


def teacher_names(raw: Any) -> list[str]:
    """Return a clean list from YAML-style strings, lists, tuples, or sets."""
    if raw is None:
        return []
    if isinstance(raw, str):
        parts = raw.replace("，", ",").replace("、", ",").split(",")
        return [p.strip() for p in parts if p.strip()]
    if isinstance(raw, Iterable) and not isinstance(raw, (bytes, bytearray, dict)):
        out: list[str] = []
        for item in raw:
            out.extend(teacher_names(item))
        return out
    text = str(raw).strip()
    return [text] if text else []


def teacher_name_set(raw: Any) -> set[str]:
    return {name for name in teacher_names(raw) if name}


def teacher_norm_set(raw: Any) -> set[str]:
    return {norm_teacher_name(name) for name in teacher_names(raw) if norm_teacher_name(name)}


def teacher_pairs(raw: Any) -> list[tuple[str, str]]:
    """Return configured teacher pairs from [[a,b]], {left,right}, or comma strings."""
    if raw is None:
        return []
    pairs: list[tuple[str, str]] = []
    if isinstance(raw, dict):
        left = raw.get("left") or raw.get("a") or raw.get("teacher_a")
        right = raw.get("right") or raw.get("b") or raw.get("teacher_b")
        names = teacher_names([left, right])
        return [(names[0], names[1])] if len(names) >= 2 else []
    if isinstance(raw, str):
        names = teacher_names(raw)
        return [(names[0], names[1])] if len(names) >= 2 else []
    if isinstance(raw, Iterable) and not isinstance(raw, (bytes, bytearray)):
        items = list(raw)
        if len(items) == 2 and not any(isinstance(x, (list, tuple, set, dict)) for x in items):
            names = teacher_names(items)
            return [(names[0], names[1])] if len(names) >= 2 else []
        for item in items:
            pairs.extend(teacher_pairs(item))
    return pairs
