# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

RuleApplyFn = Callable[..., Any]


@dataclass(frozen=True)
class RuleSpec:
    rule_id: str
    name: str
    category_path: str
    stage: str = "constraints"
    order: int = 0
    tags: tuple[str, ...] = field(default_factory=tuple)
    default_mode: str = "hard"
    default_weight: float | int | None = None
    config_key: str = ""
    explanation_template: str = ""
    apply_fn: RuleApplyFn | None = None
    apply_fn_ref: str = ""
    enabled_path: str | None = None
    mode_path: str | None = None
    weight_path: str | None = None


@dataclass(frozen=True)
class EffectiveRule:
    rule_id: str
    name: str
    category_path: str
    stage: str
    order: int
    tags: tuple[str, ...]
    config_key: str
    enabled: bool
    mode: str
    weight: float | int | None
    explanation_template: str
    apply_fn_name: str
    enabled_path: str | None
    mode_path: str | None
    weight_path: str | None
