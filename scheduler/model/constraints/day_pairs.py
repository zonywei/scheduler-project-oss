# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import List, Sequence, Tuple

from scheduler.calendar import DAY_ORDER, adjacent_day_pairs as _adjacent_day_pairs


def adjacent_day_pairs(days: Sequence[str], include_sun_mon: bool = True) -> List[Tuple[str, str]]:
    """
    Return adjacent day pairs within a week.

    - Uses the canonical order Monday..Sunday.
    - Only yields pairs where both days exist in the provided `days`.
    - When include_sun_mon=True, ("星期日","星期一") is treated as adjacent (week wrap).
    """
    return _adjacent_day_pairs(days, include_sun_mon=include_sun_mon)
