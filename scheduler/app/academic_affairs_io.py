# -*- coding: utf-8 -*-
from __future__ import annotations

import csv
from io import BytesIO, StringIO
from typing import Any

import pandas as pd

from scheduler.app.academic_affairs import ACADEMIC_TABLES
from scheduler.output.excel_writer import create_excel_writer


def build_academic_table_template_csv(table_key: str) -> bytes:
    schema = _table_schema(table_key)
    return _rows_to_csv_bytes(schema["columns"], [schema.get("sample") or {}])


def build_academic_table_template_xlsx(table_key: str) -> bytes:
    schema = _table_schema(table_key)
    columns = [str(column) for column in schema["columns"]]
    buffer = BytesIO()
    with create_excel_writer(buffer) as writer:
        pd.DataFrame([schema.get("sample") or {}], columns=columns).to_excel(
            writer,
            index=False,
            sheet_name=_safe_sheet_name(str(schema.get("label") or table_key)),
        )
    return buffer.getvalue()


def build_academic_workbook_template_xlsx() -> bytes:
    buffer = BytesIO()
    with create_excel_writer(buffer) as writer:
        for table_key, schema in ACADEMIC_TABLES.items():
            columns = [str(column) for column in schema["columns"]]
            sample = schema.get("sample") or {}
            pd.DataFrame([sample], columns=columns).to_excel(
                writer,
                index=False,
                sheet_name=_safe_sheet_name(str(schema.get("label") or table_key)),
            )
    return buffer.getvalue()


def parse_academic_table_csv(table_key: str, csv_text: str) -> dict[str, Any]:
    schema = _table_schema(table_key)
    columns = [str(column) for column in schema["columns"]]
    text = str(csv_text or "").lstrip("\ufeff")
    if not text.strip():
        raise ValueError("上传的教务 CSV 文件为空")

    reader = csv.DictReader(StringIO(text))
    fieldnames = [str(name or "").strip().lstrip("\ufeff") for name in (reader.fieldnames or [])]
    if not fieldnames:
        raise ValueError("教务 CSV 缺少表头")
    missing = [column for column in columns if column not in fieldnames]
    if missing:
        label = str(schema.get("label") or table_key)
        raise ValueError(f"{label} CSV 缺少必需列：{', '.join(missing)}")

    rows, ignored = _records_to_rows(columns, reader)
    return _import_result(table_key, schema, columns, rows, ignored)


def parse_academic_table_xlsx(table_key: str, content: bytes) -> dict[str, Any]:
    schema = _table_schema(table_key)
    if not content:
        raise ValueError("上传的教务 Excel 文件为空")
    try:
        df = pd.read_excel(BytesIO(content), sheet_name=0)
    except Exception as exc:
        raise ValueError(f"教务 Excel 读取失败：{exc}") from exc
    return _parse_table_frame(table_key, schema, df, source_label="Excel")


def parse_academic_workbook_xlsx(content: bytes) -> dict[str, Any]:
    if not content:
        raise ValueError("上传的教务工作簿为空")
    try:
        sheets = pd.read_excel(BytesIO(content), sheet_name=None)
    except Exception as exc:
        raise ValueError(f"教务工作簿读取失败：{exc}") from exc
    if not sheets:
        raise ValueError("教务工作簿没有可读取的工作表")

    sheet_map = _academic_sheet_map()
    tables: dict[str, list[dict[str, str]]] = {}
    table_results: list[dict[str, Any]] = []
    unknown_sheets: list[str] = []
    for sheet_name, df in sheets.items():
        raw_sheet_name = str(sheet_name or "").strip()
        table_key = sheet_map.get(raw_sheet_name)
        if not table_key:
            if not _frame_is_empty(df):
                unknown_sheets.append(raw_sheet_name)
            continue
        if _frame_is_empty(df):
            continue
        schema = _table_schema(table_key)
        parsed = _parse_table_frame(table_key, schema, df, source_label=f"工作表“{raw_sheet_name}”", allow_empty=True)
        if not parsed["rows"]:
            continue
        tables[table_key] = parsed["rows"]
        table_results.append(
            {
                "table": table_key,
                "label": parsed["label"],
                "row_count": parsed["row_count"],
                "ignored_columns": parsed["ignored_columns"],
                "sheet_name": raw_sheet_name,
            }
        )
    if not tables:
        raise ValueError("教务工作簿没有可导入的有效行")
    row_count = sum(item["row_count"] for item in table_results)
    import_summary = _workbook_import_summary(table_results, unknown_sheets)
    return {
        "schema_version": "scheduler.academic_affairs_workbook_import.v1",
        "tables": tables,
        "table_results": table_results,
        "import_summary": import_summary,
        "table_count": len(table_results),
        "row_count": row_count,
        "unknown_sheets": unknown_sheets,
        "persisted": False,
        "message": f"已解析 {len(table_results)} 张教务表、{row_count} 行，请核对后保存教务配置。",
    }


def _parse_table_frame(
    table_key: str,
    schema: dict[str, Any],
    df: pd.DataFrame,
    *,
    source_label: str,
    allow_empty: bool = False,
) -> dict[str, Any]:
    columns = [str(column) for column in schema["columns"]]
    fieldnames = [str(name or "").strip().lstrip("\ufeff") for name in df.columns]
    missing = [column for column in columns if column not in fieldnames]
    if missing:
        label = str(schema.get("label") or table_key)
        raise ValueError(f"{label} {source_label}缺少必需列：{', '.join(missing)}")

    records = []
    for _, row in df.fillna("").iterrows():
        records.append({str(column or "").strip().lstrip("\ufeff"): _cell_text(row.get(column, "")) for column in df.columns})
    rows, ignored = _records_to_rows(columns, records)
    if allow_empty:
        return _import_result(table_key, schema, columns, rows, ignored, allow_empty=True)
    return _import_result(table_key, schema, columns, rows, ignored)


def _import_result(
    table_key: str,
    schema: dict[str, Any],
    columns: list[str],
    rows: list[dict[str, str]],
    ignored: list[str],
    *,
    allow_empty: bool = False,
) -> dict[str, Any]:
    if not rows and not allow_empty:
        raise ValueError("教务表没有可导入的有效行")
    return {
        "table": table_key,
        "label": str(schema.get("label") or table_key),
        "columns": columns,
        "rows": rows,
        "row_count": len(rows),
        "ignored_columns": ignored,
        "import_summary": {
            "schema_version": "scheduler.academic_affairs_import_summary.v1",
            "table_count": 1,
            "row_count": len(rows),
            "ignored_column_count": len(ignored),
            "unknown_sheet_count": 0,
            "save_required": True,
            "status": "pending_save",
            "status_label": "待核对保存",
            "message": "已导入到页面，尚未保存，保存后才会进入正式配置。",
        },
        "persisted": False,
        "message": f"已解析 {len(rows)} 行，请核对后保存教务配置。",
    }


def _records_to_rows(columns: list[str], records: Any) -> tuple[list[dict[str, str]], list[str]]:
    rows: list[dict[str, str]] = []
    ignored_order: list[str] = []
    for row in records:
        normalized_row = {
            str(key or "").strip().lstrip("\ufeff"): _cell_text(value)
            for key, value in dict(row).items()
            if key is not None
        }
        for name in normalized_row:
            if name and name not in columns and name not in ignored_order:
                ignored_order.append(name)
        clean = {column: str(normalized_row.get(column) or "").strip() for column in columns}
        if any(clean.values()):
            rows.append(clean)
    return rows, ignored_order


def _cell_text(value: Any) -> str:
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value or "").strip()


def _workbook_import_summary(table_results: list[dict[str, Any]], unknown_sheets: list[str]) -> dict[str, Any]:
    ignored_tables = [
        str(item.get("label") or item.get("table") or "")
        for item in table_results
        if item.get("ignored_columns")
    ]
    ignored_column_count = sum(len(item.get("ignored_columns") or []) for item in table_results)
    return {
        "schema_version": "scheduler.academic_affairs_import_summary.v1",
        "table_count": len(table_results),
        "row_count": sum(int(item.get("row_count") or 0) for item in table_results),
        "ignored_column_count": ignored_column_count,
        "unknown_sheet_count": len(unknown_sheets),
        "tables_with_ignored_columns": ignored_tables,
        "save_required": True,
        "status": "pending_save",
        "status_label": "待核对保存",
        "message": "已导入到页面，尚未保存，保存后才会进入正式配置。",
    }


def _safe_sheet_name(label: str) -> str:
    invalid = set('[]:*?/\\')
    cleaned = "".join("_" if ch in invalid else ch for ch in label).strip()
    return (cleaned or "教务表")[:31]


def _academic_sheet_map() -> dict[str, str]:
    mapping: dict[str, str] = {}
    for table_key, schema in ACADEMIC_TABLES.items():
        label = str(schema.get("label") or table_key)
        mapping[table_key] = table_key
        mapping[label] = table_key
        mapping[_safe_sheet_name(label)] = table_key
    return mapping


def _frame_is_empty(df: pd.DataFrame) -> bool:
    if df is None or df.empty:
        return True
    text_values = df.fillna("").astype(str)
    return not text_values.apply(lambda column: column.str.strip().astype(bool)).to_numpy().any()


def _table_schema(table_key: str) -> dict[str, Any]:
    key = str(table_key or "").strip()
    if key not in ACADEMIC_TABLES:
        raise ValueError(f"未知教务表：{key or '未指定'}")
    return ACADEMIC_TABLES[key]


def _rows_to_csv_bytes(columns: list[str], rows: list[dict[str, Any]]) -> bytes:
    buffer = StringIO()
    writer = csv.DictWriter(buffer, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({column: str(row.get(column) or "") for column in columns})
    return ("\ufeff" + buffer.getvalue()).encode("utf-8")
