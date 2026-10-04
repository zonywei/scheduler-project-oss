# -*- coding: utf-8 -*-
from __future__ import annotations

from scheduler.model.constraints.personalized_rules import (
    link_rules,
    weekend_preference_rules,
    weekday_special_rules,
)

PERSONALIZED_RULE_MODULES = (
    link_rules,
    weekend_preference_rules,
    weekday_special_rules,
)

__all__ = ["PERSONALIZED_RULE_MODULES"]
