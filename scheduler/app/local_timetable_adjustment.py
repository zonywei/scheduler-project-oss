# -*- coding: utf-8 -*-
from __future__ import annotations

import copy
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from openpyxl import load_workbook

from scheduler.app.config_service import PROJECT_ROOT
from scheduler.app.local_timetable_repair import (
    LocalTimetableRepairError,
    ScheduleCell,
    _affected_teacher_schedules,
    _cell_key,
    _cell_text,
    _change,
    _destination_type,
    _extract_subject,
    _extract_teachers,
    _normalize_day,
    _normalize_slot,
    _replace_teacher,
    _safe_id,
    _scan_schedule_cells,
    _select_schedule_workbook,
    _slot_rank,
    _teacher_busy_at,
    _write_adjusted_workbook,
)
from scheduler.output.constants import DAYS


MANUAL_ADJUSTMENT_SCHEMA = "scheduler.manual_timetable_adjustment.v1"
LOCAL_ADJUSTMENT_DIR_NAME = "local_adjustments"
MAX_ALTERNATIVE_SLOTS = 8


def preview_manual_timetable_adjustment(
    *,
    status: dict[str, Any],
    academic_payload: dict[str, Any] | None = None,
    request: dict[str, Any] | None = None,
    project_root: Path = PROJECT_ROOT,
) -> dict[str, Any]:
    return _build_manual_adjustment(
        status=status,
        academic_payload=academic_payload or {},
        request=request or {},
        project_root=project_root,
        apply_changes=False,
    )


def apply_manual_timetable_adjustment(
    *,
    status: dict[str, Any],
    academic_payload: dict[str, Any] | None = None,
    request: dict[str, Any] | None = None,
    output_dir: Path | None = None,
    project_root: Path = PROJECT_ROOT,
) -> dict[str, Any]:
    return _build_manual_adjustment(
        status=status,
        academic_payload=academic_payload or {},
        request=request or {},
        project_root=project_root,
        output_dir=output_dir,
        apply_changes=True,
    )


def _build_manual_adjustment(
    *,
    status: dict[str, Any],
    academic_payload: dict[str, Any],
    request: dict[str, Any],
    project_root: Path,
    apply_changes: bool,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    workbook_path = _select_schedule_workbook(status, request, project_root)
    workbook = load_workbook(workbook_path, read_only=False, data_only=False)
    try:
        cells = _scan_schedule_cells(workbook)
        if not cells:
            raise LocalTimetableRepairError("未在当前课表中识别到可编辑的班级课表网格。")
        adjustment = _resolve_adjustment_request(academic_payload, request)
        payload = _manual_adjustment_payload(workbook_path, adjustment, cells)
        if apply_changes:
            if payload["summary"]["status"] != "ready":
                raise LocalTimetableRepairError(payload["summary"]["message"])
            output_path = _write_adjusted_workbook(
                workbook,
                workbook_path,
                cells,
                [payload["plan"]],
                output_dir,
                suffix="课表微调",
            )
            payload["applied"] = True
            payload["output_file"] = str(output_path)
            payload["record"] = _manual_adjustment_record(payload, output_path)
        return payload
    finally:
        workbook.close()


def _resolve_adjustment_request(academic_payload: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
    data = academic_payload.get("data") if isinstance(academic_payload.get("data"), dict) else academic_payload
    tables = data.get("tables") if isinstance(data, dict) else {}
    rows = tables.get("timetable_changes") if isinstance(tables, dict) and isinstance(tables.get("timetable_changes"), list) else []
    row: dict[str, Any] = {}
    if isinstance(request.get("change"), dict):
        row = copy.deepcopy(request["change"])
    else:
        raw_index = request.get("change_index")
        if raw_index is not None and str(raw_index).strip() != "":
            idx = int(float(raw_index))
            if idx < 0 or idx >= len(rows):
                raise LocalTimetableRepairError("调课单行不存在，请刷新教务工作台后重试。")
            row = copy.deepcopy(rows[idx]) if isinstance(rows[idx], dict) else {}

    def pick(*keys: str) -> str:
        for key in keys:
            value = request.get(key)
            if str(value or "").strip():
                return _cell_text(value)
        for key in keys:
            value = row.get(key)
            if str(value or "").strip():
                return _cell_text(value)
        return ""

    class_name = pick("class_name", "班级")
    from_day = _normalize_day(pick("from_day", "original_day", "原星期"))
    from_slot = _normalize_slot(pick("from_slot", "original_slot", "原节次"))
    to_day = _normalize_day(pick("to_day", "new_day", "新星期") or from_day)
    to_slot = _normalize_slot(pick("to_slot", "new_slot", "新节次") or from_slot)
    if not class_name:
        raise LocalTimetableRepairError("请先填写要微调的班级。")
    if not from_day or not from_slot:
        raise LocalTimetableRepairError("请填写原星期和原节次，才能定位原课位。")
    if not to_day or not to_slot:
        raise LocalTimetableRepairError("请填写新星期和新节次。")

    return {
        "title": pick("title", "变更标题") or f"{class_name} {from_day}{from_slot} 课表微调",
        "change_type": pick("change_type", "变更类型") or "课表微调",
        "class_name": class_name,
        "from_day": from_day,
        "from_slot": from_slot,
        "original_subject": pick("original_subject", "原学科"),
        "original_teacher": pick("original_teacher", "原教师"),
        "to_day": to_day,
        "to_slot": to_slot,
        "new_subject": pick("new_subject", "新学科"),
        "new_teacher": pick("new_teacher", "新教师"),
        "status": pick("status", "状态"),
        "submitter": pick("submitter", "提交人"),
        "note": pick("note", "说明"),
        "row": row,
        "allow_swap": request.get("allow_swap", True) is not False,
    }


def _manual_adjustment_payload(workbook_path: Path, adjustment: dict[str, Any], cells: dict[str, ScheduleCell]) -> dict[str, Any]:
    before_values = {key: cell.value for key, cell in cells.items()}
    plan, after_values = _plan_manual_adjustment(cells, before_values, adjustment)
    ready = plan["status"] == "feasible"
    involved = sorted({teacher for teacher in plan.get("impact", {}).get("involved_teachers", []) if teacher})
    changed_cells = int(plan.get("impact", {}).get("changed_cell_count") or 0)
    message = (
        f"已生成课表微调方案，涉及 {len(involved)} 位教师、{changed_cells} 个课格。"
        if ready
        else plan.get("explanation") or "未找到可执行的课表微调方案。"
    )
    affected_classes = sorted({change.get("class_name") for change in plan.get("changes", []) if change.get("class_name")})
    return {
        "schema_version": MANUAL_ADJUSTMENT_SCHEMA,
        "applied": False,
        "workbook": {"path": str(workbook_path), "label": workbook_path.name},
        "adjustment": adjustment,
        "summary": {
            "status": "ready" if ready else "blocked",
            "message": message,
            "changed_cell_count": changed_cells,
            "involved_teacher_count": len(involved),
            "involved_teachers": involved,
            "affected_classes": affected_classes,
            "alternative_count": len(plan.get("alternatives") or []),
        },
        "plan": plan,
        "affected_teacher_schedules": _affected_teacher_schedules(involved, cells, before_values, after_values),
        "affected_class_schedules": _affected_class_schedules(affected_classes, cells, before_values, after_values),
    }


def _plan_manual_adjustment(
    cells: dict[str, ScheduleCell],
    before_values: dict[str, str],
    adjustment: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, str]]:
    class_name = str(adjustment["class_name"])
    source = cells.get(_cell_key(class_name, str(adjustment["from_day"]), str(adjustment["from_slot"])))
    target = cells.get(_cell_key(class_name, str(adjustment["to_day"]), str(adjustment["to_slot"])))
    if source is None:
        return _blocked_plan(adjustment, [], "未在当前课表中找到原课位。"), dict(before_values)
    if target is None:
        return _blocked_plan(adjustment, [], "未在当前课表中找到新课位。"), dict(before_values)

    source_before = before_values.get(source.key, source.value)
    target_before = before_values.get(target.key, target.value)
    if not source_before:
        return _blocked_plan(adjustment, [], "原课位为空，无法生成微调方案。"), dict(before_values)

    mismatches = _source_mismatch_reasons(source_before, adjustment)
    if mismatches:
        return _blocked_plan(adjustment, [], "调课单原课信息与当前课表不一致：" + "；".join(mismatches)), dict(before_values)

    lesson_after = _adjusted_lesson_value(source_before, adjustment)
    if not lesson_after:
        return _blocked_plan(adjustment, [], "无法识别微调后的课程内容。"), dict(before_values)

    busy_conflicts = _teacher_conflicts_for_value(lesson_after, target, cells, before_values, ignore_keys={source.key, target.key})
    if busy_conflicts:
        alternatives = _alternative_slots(source, lesson_after, cells, before_values, ignore_keys={source.key, target.key})
        names = "；".join(f"{item.class_name} {item.value}" for item in busy_conflicts[:4])
        return _blocked_plan(adjustment, alternatives, f"新教师在目标节次已有课或任务：{names}。"), dict(before_values)

    changes: list[dict[str, Any]] = []
    after_values = dict(before_values)
    if source.key == target.key:
        changes.append(_change(source, source_before, lesson_after, "原课位内调整教师/学科"))
        after_values[source.key] = lesson_after
    else:
        target_type = _destination_type(target_before)
        if target_type:
            changes.append(_change(source, source_before, "", "移出原课位"))
            changes.append(_change(target, target_before, lesson_after, target_type["reason"]))
            after_values[source.key] = ""
            after_values[target.key] = lesson_after
        elif adjustment.get("allow_swap"):
            back_conflicts = _teacher_conflicts_for_value(target_before, source, cells, before_values, ignore_keys={source.key, target.key})
            if back_conflicts:
                names = "；".join(f"{item.class_name} {item.value}" for item in back_conflicts[:4])
                return _blocked_plan(adjustment, [], f"目标课位已有课程，但该课程教师不能换回原课位：{names}。"), dict(before_values)
            changes.append(_change(source, source_before, target_before, "与目标课位课程互换"))
            changes.append(_change(target, target_before, lesson_after, "承接微调课程"))
            after_values[source.key] = target_before
            after_values[target.key] = lesson_after
        else:
            alternatives = _alternative_slots(source, lesson_after, cells, before_values, ignore_keys={source.key, target.key})
            return _blocked_plan(adjustment, alternatives, "目标课位已有课程；请允许换课或选择空课/自习课格。"), dict(before_values)

    involved = _involved_teachers(changes)
    plan = {
        "id": f"manual_{_safe_id(class_name)}_{_safe_id(adjustment['from_day'])}_{_safe_id(adjustment['from_slot'])}_{_safe_id(adjustment['to_day'])}_{_safe_id(adjustment['to_slot'])}",
        "status": "feasible",
        "title": str(adjustment.get("title") or "课表微调方案"),
        "adjustment": _public_adjustment(adjustment),
        "changes": changes,
        "alternatives": [],
        "impact": {
            "score": len(involved) * 100 + len(changes) * 10,
            "involved_teachers": involved,
            "involved_teacher_count": len(involved),
            "changed_cell_count": len(changes),
            "affected_class_count": len({change["class_name"] for change in changes}),
        },
        "explanation": _manual_plan_explanation(adjustment, changes),
    }
    return plan, after_values


def _source_mismatch_reasons(source_before: str, adjustment: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    expected_teacher = str(adjustment.get("original_teacher") or "").strip()
    expected_subject = str(adjustment.get("original_subject") or "").strip()
    if expected_teacher and expected_teacher not in _extract_teachers(source_before):
        reasons.append(f"原教师应为 {expected_teacher}，当前课格为 {source_before}")
    if expected_subject and expected_subject != _extract_subject(source_before):
        reasons.append(f"原学科应为 {expected_subject}，当前课格为 {source_before}")
    return reasons


def _adjusted_lesson_value(source_before: str, adjustment: dict[str, Any]) -> str:
    new_teacher = str(adjustment.get("new_teacher") or "").strip()
    new_subject = str(adjustment.get("new_subject") or "").strip()
    original_teacher = str(adjustment.get("original_teacher") or "").strip()
    subject = new_subject or _extract_subject(source_before)
    if new_teacher:
        if original_teacher:
            return _replace_teacher(source_before, original_teacher, new_teacher, subject)
        return f"{subject}({new_teacher})" if subject else new_teacher
    if new_subject and new_subject != _extract_subject(source_before):
        teachers = _extract_teachers(source_before)
        return f"{new_subject}({teachers[0]})" if teachers else new_subject
    return source_before


def _teacher_conflicts_for_value(
    value: str,
    target: ScheduleCell,
    cells: dict[str, ScheduleCell],
    values: dict[str, str],
    *,
    ignore_keys: set[str],
) -> list[ScheduleCell]:
    conflicts: list[ScheduleCell] = []
    for teacher in _extract_teachers(value):
        conflicts.extend(
            cell
            for cell in cells.values()
            if cell.key not in ignore_keys
            and cell.day == target.day
            and cell.slot == target.slot
            and teacher in _extract_teachers(values.get(cell.key, cell.value))
        )
    return conflicts


def _alternative_slots(
    source: ScheduleCell,
    lesson_value: str,
    cells: dict[str, ScheduleCell],
    values: dict[str, str],
    *,
    ignore_keys: set[str],
) -> list[dict[str, Any]]:
    teachers = _extract_teachers(lesson_value)
    alternatives: list[dict[str, Any]] = []
    for cell in cells.values():
        if cell.class_name != source.class_name or cell.key == source.key or cell.key in ignore_keys:
            continue
        dest = _destination_type(values.get(cell.key, cell.value))
        if not dest:
            continue
        if any(_teacher_busy_at(teacher, cell.day, cell.slot, cells, values, ignore_keys=ignore_keys | {source.key, cell.key}) for teacher in teachers):
            continue
        alternatives.append(
            {
                "class_name": cell.class_name,
                "day": cell.day,
                "slot": cell.slot,
                "reason": dest["reason"],
                "score": (0 if cell.day == source.day else 12) + abs(_slot_rank(cell.slot) - _slot_rank(source.slot)) + int(dest["penalty"]),
            }
        )
    return sorted(alternatives, key=lambda item: (item["score"], DAYS.index(item["day"]) if item["day"] in DAYS else 99, _slot_rank(item["slot"])))[:MAX_ALTERNATIVE_SLOTS]


def _blocked_plan(adjustment: dict[str, Any], alternatives: list[dict[str, Any]], explanation: str) -> dict[str, Any]:
    return {
        "id": f"manual_blocked_{_safe_id(str(adjustment.get('class_name') or 'class'))}",
        "status": "blocked",
        "title": str(adjustment.get("title") or "课表微调方案"),
        "adjustment": _public_adjustment(adjustment),
        "changes": [],
        "alternatives": alternatives,
        "impact": {
            "score": 9999,
            "involved_teachers": [],
            "involved_teacher_count": 0,
            "changed_cell_count": 0,
            "affected_class_count": 0,
        },
        "explanation": explanation,
    }


def _public_adjustment(adjustment: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": adjustment.get("title") or "",
        "change_type": adjustment.get("change_type") or "",
        "class_name": adjustment.get("class_name") or "",
        "from": {"day": adjustment.get("from_day") or "", "slot": adjustment.get("from_slot") or ""},
        "to": {"day": adjustment.get("to_day") or "", "slot": adjustment.get("to_slot") or ""},
        "original_subject": adjustment.get("original_subject") or "",
        "original_teacher": adjustment.get("original_teacher") or "",
        "new_subject": adjustment.get("new_subject") or "",
        "new_teacher": adjustment.get("new_teacher") or "",
        "status": adjustment.get("status") or "",
        "submitter": adjustment.get("submitter") or "",
        "note": adjustment.get("note") or "",
    }


def _manual_plan_explanation(adjustment: dict[str, Any], changes: list[dict[str, Any]]) -> str:
    class_name = adjustment.get("class_name") or ""
    start = f"{adjustment.get('from_day')} {adjustment.get('from_slot')}"
    end = f"{adjustment.get('to_day')} {adjustment.get('to_slot')}"
    if len(changes) == 1:
        return f"{class_name} 在 {start} 原课位内更新教师/学科，只改 1 个课格。"
    if any(change.get("reason") == "与目标课位课程互换" for change in changes):
        return f"{class_name} 将 {start} 与 {end} 互换，保持班级总课时不变。"
    return f"{class_name} 将 {start} 的课程移动到 {end}，优先使用空课或自习课格。"


def _involved_teachers(changes: list[dict[str, Any]]) -> list[str]:
    teachers: set[str] = set()
    for change in changes:
        for value_key in ("before", "after"):
            teachers.update(_extract_teachers(str(change.get(value_key) or "")))
    return sorted(teachers)


def _affected_class_schedules(
    classes: list[str],
    cells: dict[str, ScheduleCell],
    before_values: dict[str, str],
    after_values: dict[str, str],
) -> list[dict[str, Any]]:
    return [
        {
            "class_name": class_name,
            "before": _class_schedule_rows(class_name, cells, before_values),
            "after": _class_schedule_rows(class_name, cells, after_values),
            "changed_slots": _class_changed_slots(class_name, cells, before_values, after_values),
        }
        for class_name in classes
    ]


def _class_schedule_rows(class_name: str, cells: dict[str, ScheduleCell], values: dict[str, str]) -> list[dict[str, Any]]:
    by_slot: dict[str, dict[str, str]] = defaultdict(lambda: {day: "" for day in DAYS})
    for cell in cells.values():
        if cell.class_name != class_name:
            continue
        by_slot[cell.slot][cell.day] = values.get(cell.key, cell.value)
    return [{"slot": slot, "values": by_slot[slot]} for slot in sorted(by_slot, key=_slot_rank)]


def _class_changed_slots(
    class_name: str,
    cells: dict[str, ScheduleCell],
    before_values: dict[str, str],
    after_values: dict[str, str],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for cell in sorted([cell for cell in cells.values() if cell.class_name == class_name], key=lambda item: (DAYS.index(item.day) if item.day in DAYS else 99, _slot_rank(item.slot))):
        before = before_values.get(cell.key, cell.value)
        after = after_values.get(cell.key, cell.value)
        if before != after:
            out.append({"day": cell.day, "slot": cell.slot, "before": before, "after": after})
    return out


def _manual_adjustment_record(payload: dict[str, Any], output_path: Path) -> dict[str, Any]:
    return {
        "schema_version": MANUAL_ADJUSTMENT_SCHEMA,
        "applied_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "active_file": str(output_path),
        "summary": copy.deepcopy(payload.get("summary") or {}),
        "adjustment": copy.deepcopy(payload.get("adjustment") or {}),
        "plan": copy.deepcopy(payload.get("plan") or {}),
        "affected_teacher_schedules": copy.deepcopy(payload.get("affected_teacher_schedules") or []),
        "affected_class_schedules": copy.deepcopy(payload.get("affected_class_schedules") or []),
    }
