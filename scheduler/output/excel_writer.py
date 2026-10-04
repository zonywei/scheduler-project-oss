# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Any

import pandas as pd


DEFAULT_XLSX_ENGINE = "openpyxl"


def create_excel_writer(target: Any, **kwargs: Any) -> pd.ExcelWriter:
    """Create the project-standard Excel writer for .xlsx outputs."""
    kwargs.setdefault("engine", DEFAULT_XLSX_ENGINE)
    return pd.ExcelWriter(target, **kwargs)
