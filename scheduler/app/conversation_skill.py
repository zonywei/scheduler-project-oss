# -*- coding: utf-8 -*-
"""Deterministic intake orchestration, not a natural-language AI parser.

Only complete, allowlisted statements can be compiled. Every other clause is
retained in an auditable ledger until the user explicitly clarifies or withdraws
it. School entities and tables come exclusively from the caller's user sources.
"""
from __future__ import annotations

import copy
import re
from typing import Any, Iterable, Mapping

from scheduler.domain.rule_v2 import parse_rule_v2_local, validate_rule_v2

CONVERSATION_SKILL_VERSION = "scheduler.conversation_skill.v2"
HOUR_FIELDS = ("早自习课时", "周中课时", "周末课时")
DAYS = tuple("星期" + day for day in "一二三四五六日")
DEFAULT_COMMANDS = {"按基础约束直接排课", "没有额外要求", "没有其他要求", "直接排课", "按默认约束排课"}
MAX_SUPPORTED_RULES = 6


def compile_skill_statement(text: str, *, teachers=(), subjects=(), classes=()) -> dict[str, Any] | None:
    """Full-match grammars guard the legacy parser's substring heuristics."""
    source = text.strip()
    teacher = next((t for t in sorted(teachers, key=len, reverse=True)
                    if re.fullmatch(re.escape(t) + r"(?:周[一二三四五六日]|星期[一二三四五六日])(?:不排课|不能上课|不上课)", source)), None)
    subject = next((s for s in sorted(subjects, key=len, reverse=True)
                    if re.fullmatch(re.escape(s) + r"(?:尽量|优先)安排在上午", source)), None)
    maximum = re.fullmatch(r"(?:每位教师|所有教师)每天(?:最多|不超过)([0-9]+)节课?", source)
    if not (teacher or subject or maximum):
        return None
    draft = parse_rule_v2_local(source, known_teachers=[teacher] if teacher else [],
                                known_subjects=[subject] if subject else [], known_classes=[])
    # Full entity matches above avoid substring collisions (e.g. 艺术 / 表演艺术).
    if not validate_rule_v2(draft).valid or draft["solver_support"]["status"] != "supported":
        return None
    return draft


def _question(key: str, text: str, why: str = "", options=()) -> dict[str, Any]:
    return {"id": key, "question": text, "why": why, "required": True,
            "answer_type": "choice_or_text" if options else "text", "options": list(options)}


def _hour_input(text: str, subjects: list[str]) -> tuple[str, dict[str, int]] | None:
    for subject in sorted(subjects, key=len, reverse=True):
        match = re.fullmatch(re.escape(subject) + r"\s*[=＝:：]\s*(\d+)\s*/\s*(\d+)\s*/\s*(\d+)", text)
        if match:
            return subject, dict(zip(HOUR_FIELDS, map(int, match.groups())))
        match = re.fullmatch(re.escape(subject) + r"\s+(早自习|周中|周末)(?:课时)?\s*[=＝:：]\s*(\d+)", text)
        if match:
            return subject, {match[1] + "课时": int(match[2])}
    return None


def _calendar_input(text: str) -> dict[str, Any] | None:
    # The user explicitly enumerates all available weekdays for this slot.
    match = re.fullmatch(r"作息[：:]\s*((?:早自习|上午|下午|晚自习)[1-9]\d*)\s*=\s*(星期[一二三四五六日](?:/星期[一二三四五六日])*)", text)
    if not match:
        return None
    days = match[2].split("/")
    return {"时段节次": match[1], **{day: int(day in days) for day in DAYS}}


def _teacher_assignment_input(text: str, teachers: list[str], subjects: list[str]) -> tuple[str, str] | None:
    """Recognize a user restatement of an uploaded teacher mapping as data."""
    for teacher in sorted(teachers, key=len, reverse=True):
        for subject in sorted(subjects, key=len, reverse=True):
            if re.fullmatch(re.escape(teacher) + r"\s*(?:任|教授|负责)\s*" + re.escape(subject), text):
                return teacher, subject
    return None


def build_local_skill_model(
    *, messages: Iterable[Mapping[str, Any]], checklist: list[dict[str, Any]],
    previous_model: Mapping[str, Any] | None = None, known_teachers: Iterable[str] = (),
    known_subjects: Iterable[str] = (), known_classes: Iterable[str] = (),
    user_tables: Mapping[str, Any] | None = None, data_issues: Iterable[str] = (),
    provenance: Iterable[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    previous = dict(previous_model or {})
    trusted_previous = (previous.get("modeling") or {}).get("version") == CONVERSATION_SKILL_VERSION
    previous_facts = previous.get("facts", {}) if trusted_previous else {}
    texts = list(previous_facts.get("user_texts", []))
    for message in messages:
        if message.get("role") == "user":
            text = str(message.get("content") or "").strip()
            if text and text not in texts:
                texts.append(text)
    subjects, teachers, classes = (sorted(set(values)) for values in (known_subjects, known_teachers, known_classes))
    tables = copy.deepcopy(dict(user_tables or {}))
    hours = {str(row.get("学科") or ""): dict(row) for row in tables.get("subject_hours", [])}
    calendar = {str(row.get("时段节次") or ""): dict(row) for row in tables.get("time_grid", [])}
    ledger: list[dict[str, Any]] = []
    default_only = False
    text_sources = []
    guided_hour_input = False
    calendar_confirmed = bool(calendar)
    for text in texts:
        # A clarification is one atomic replacement, including any punctuation.
        clauses = [text] if re.match(r"(?:澄清|撤回)需求R\d+", text) else re.split(r"[\n，,；;。]+", text)
        for raw in clauses:
            clause = raw.strip()
            if not clause:
                continue
            if clause in DEFAULT_COMMANDS:
                default_only = True
                continue
            assignment = _teacher_assignment_input(clause, teachers, subjects)
            if assignment:
                text_sources.append({"component": "teacher_subjects", "teacher": assignment[0], "subject": assignment[1], "text": clause})
                continue
            if re.fullmatch(r"(?:我)?(?:准备|打算)(?:要)?输入课时了?", clause):
                # This is an intent to enter data, not data itself. Keep it in
                # the ledger and expose a concrete next question so it cannot
                # accidentally unlock default-only scheduling.
                guided_hour_input = True
                ledger.append({"id": f"R{len(ledger) + 1}", "statement": clause,
                               "status": "needs_clarification", "kind": "data_intent"})
                continue
            if clause == "作息录入完成":
                calendar_confirmed = bool(calendar)
                continue
            incoming = _hour_input(clause, subjects)
            if incoming:
                subject, fields = incoming
                hours.setdefault(subject, {"学科": subject}).update(fields)
                text_sources.append({"component": "subject_hours", "subject": subject, "fields": list(fields), "text": clause})
                continue
            slot = _calendar_input(clause)
            if slot:
                calendar[slot["时段节次"]] = slot
                calendar_confirmed = False
                text_sources.append({"component": "time_grid", "text": clause})
                continue
            command = re.fullmatch(r"(撤回|澄清)需求(R\d+)(?:[：:](.+))?", clause, re.S)
            if command:
                target = next((row for row in ledger if row["id"] == command[2]), None)
                if target and ((command[1] == "撤回" and not command[3]) or (command[1] == "澄清" and command[3])):
                    target["status"] = "withdrawn" if command[1] == "撤回" else "replaced"
                    target["resolution"] = clause
                    if command[1] == "撤回":
                        continue
                    clause = command[3].strip()
            ledger.append({"id": f"R{len(ledger) + 1}", "statement": clause, "status": "pending"})
            default_only = False

    tables["subject_hours"] = list(hours.values())
    tables["time_grid"] = list(calendar.values())
    statements, requirements, drafts = [], [], []
    questions = []
    for item in ledger:
        if item["status"] in {"withdrawn", "replaced"}:
            continue
        draft = compile_skill_statement(item["statement"], teachers=teachers, subjects=subjects, classes=classes)
        if draft is None:
            item["status"] = "needs_clarification"
            questions.append(_question(
                "requirement-" + item["id"],
                f'需求{item["id"]}“{item["statement"]}”尚未建模。请说明对象、时间、必须满足还是偏好。回复“澄清需求{item["id"]}：完整要求”；若取消，回复“撤回需求{item["id"]}”。',
                "本地只支持明确的教师整日禁排、学科上午偏好和全体教师每日上限；其他要求需要模型解释或扩展编译器。"))
        else:
            item["status"] = "supported"
            item["constraint_type"] = draft["constraint"]["type"]
            if item["statement"] not in statements:
                statements.append(item["statement"])
                drafts.append(draft)
                requirements.append({"statement": item["statement"], "strength": draft["strength"],
                                     "scope": "、".join(draft["scope"]["teachers"] + draft["scope"]["subjects"]) or "全体教师",
                                     "effective_time": "、".join(draft["effective_time"]["days"]) or "当前项目周期",
                                     "exceptions": []})

    checks = [dict(item) for item in checklist if item.get("id") != "model"]
    missing_hours = []
    for subject in subjects:
        row = hours.get(subject, {})
        absent = [key for key in HOUR_FIELDS if not _nonnegative_integer(row.get(key))]
        if absent:
            missing_hours.append(subject + "：" + "、".join(absent))
    for item in checks:
        if item.get("id") == "hours":
            item.update(status="ready" if subjects and not missing_hours else "pending",
                        detail="全部实际学科课时已提供" if subjects and not missing_hours else "；".join(missing_hours) or "先提供任课关系以确定实际学科")
        elif item.get("id") == "calendar":
            item.update(status="ready" if calendar and calendar_confirmed else "pending")
        elif item.get("id") == "requirements":
            item.update(status="ready" if texts else "pending")
    missing = [item for item in checks if item.get("required") and item.get("status") != "ready"]
    data_questions = []
    for issue in data_issues:
        data_questions.append(_question("data-issue-" + str(len(data_questions)), str(issue), "该数据尚未纳入可执行输入"))
    if missing:
        item = missing[0]
        key = item.get("id", "")
        prompt = {
            "source": "请上传本次用户提供的基础数据。当前项目来源未经核实的数据不会自动使用。",
            "teachers": "请上传含班级和实际学科任课教师列的表格；班主任及性别可不提供。",
            "calendar": "请上传作息表；或逐行输入“作息：上午1=星期一/星期二”（列全该节可排星期），所有节次录完后回复“作息录入完成”。",
            "hours": "请补充课时：" + "；".join(missing_hours) + "。可逐行输入“实际学科 周中=5”，或“实际学科=早自习/周中/周末”三个整数；也可上传含学科及这三类课时的表。",
            "baseline": "请上传含班级、学科、星期、明确时段节次的已有课表明细。",
            "requirements": "请描述额外要求；没有额外要求可回复“按基础约束直接排课”。",
        }.get(key, "请补充：" + str(item.get("detail") or item.get("label")))
        data_questions.insert(0, _question(str(key), prompt))
    if guided_hour_input:
        data_questions.insert(0, _question(
            "hours-entry",
            "好的，请进入课时录入：按“实际学科 周中=5”或“实际学科=早自习/周中/周末”逐行提供课时；仅说准备录入还不算已提供。",
            "课时是可排课的必要数据，不能从意图或默认值推断。",
        ))
    if len(statements) > MAX_SUPPORTED_RULES:
        questions.append(_question("rule-capacity", f"已保留全部 {len(statements)} 条规则，超过当前交接上限 {MAX_SUPPORTED_RULES}；请明确撤回部分要求，或等待上层扩展。"))
    if not statements and not default_only and not questions and not data_questions:
        questions.append(_question("goal-or-defaults", "是否有额外要求？没有可选择按基础约束直接排课。",
                                   options=["按基础约束直接排课"]))
    all_questions = data_questions + questions
    phase = "data_needed" if data_questions else "clarifying" if questions else "model_ready"
    message = ("会话数据和可支持规则已整理，请核对数据来源与规则后确认。确认不代表已求解。"
               if phase == "model_ready" else "仍有数据或需求待确认，未解析的内容已保留，尚未全部建模。")
    checks.append({"id": "model", "label": "会话输入整理", "required": True,
                   "status": "ready" if phase == "model_ready" else "pending", "detail": message})
    return {
        "schema_version": "scheduler.conversation_model.v1", "phase": phase,
        "status": "ready" if phase == "model_ready" else "collecting", "assistant_message": message,
        "facts": {"user_texts": texts, "staged_tables": tables,
                  "entity_inventory": {"subjects": subjects, "classes": classes, "teacher_count": len(teachers)},
                  "provenance": [dict(row) for row in provenance] + text_sources},
        "requirements": requirements, "requirement_ledger": ledger,
        "unparsed_inputs": [dict(item) for item in ledger if item.get("status") not in {"withdrawn", "replaced", "supported"}],
        "rule_statements": statements, "rule_drafts": drafts,
        "questions": all_questions[:3], "pending_question_count": len(all_questions),
        "limitations": [], "recommendations": [], "solve_mode": "joint", "checklist": checks,
        "default_constraints_only": default_only,
        "default_constraint_source": {
            "label": "现有求解器默认约束（CP-SAT）",
            "preserved": True,
            "applies": bool(default_only),
            "note": "仅表示没有新增用户要求；不会删除、绕过或用旧演示数据替换默认约束。",
        },
        "modeling": {"engine": "local_skill", "version": CONVERSATION_SKILL_VERSION, "ready": phase == "model_ready"},
        "ai": {"used": False, "optional": True, "note": "使用确定性数据编排和限定语法，外部语言模型未参与。"},
    }


def _nonnegative_integer(value: Any) -> bool:
    if isinstance(value, bool) or value is None or str(value).strip() == "":
        return False
    try:
        return float(value).is_integer() and float(value) >= 0
    except (ValueError, TypeError, OverflowError):
        return False


def build_local_conversation_model(
    *, session: Mapping[str, Any], data: Mapping[str, Any],
    checklist: list[dict[str, Any]], notice: str = "",
) -> dict[str, Any]:
    """Adapt the persisted conversation to the deterministic, conservative skill.

    The snapshot contains counts and readiness findings, not raw school tables.
    Do not guess entity inventories from those counts or from a model response.
    """
    model = build_local_skill_model(
        messages=session.get("messages") or (),
        checklist=checklist,
        previous_model=session.get("model") if isinstance(session.get("model"), Mapping) else None,
        data_issues=(
            str(item.get("title") or "")
            for item in ((data.get("readiness") or {}).get("blocking_items") or ())
            if isinstance(item, Mapping) and str(item.get("title") or "")
        ),
    )
    if notice:
        model["assistant_message"] = f"{notice} 本轮不会自动确认规则或开始求解；请补充信息或稍后重试。"
    return model
