from __future__ import annotations

from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

from openpyxl import Workbook

from scheduler.app import conversational_scheduler
from scheduler.app.conversational_scheduler import (
    add_conversation_message,
    confirm_conversation_model,
    conversation_feature_access,
    conversation_route,
    create_conversation_session,
    get_conversation_session,
    inspect_scheduling_file,
    list_conversation_sessions,
    prepare_conversation_solve,
)
from scheduler.app.model_gateway import JsonModelResult
from scheduler.platform import PlatformDatabase, PlatformDatabaseSettings, PlatformStore


def _runtime(tmp_path: Path, monkeypatch) -> tuple[PlatformStore, str]:
    database_path = tmp_path / "scheduler.db"
    store = PlatformStore(PlatformDatabase(PlatformDatabaseSettings(path=database_path)))
    store.initialize()
    organization = store.create_organization(slug="school-a", name="学校A")
    store.save_workspace(
        organization.id,
        {"io": {}, "rules": {}, "temporary_rules": {"active": []}, "academic_affairs": {}},
        expected_revision=0,
        actor_user_id="bootstrap",
    )
    monkeypatch.setenv("SCHEDULER_STATE_BACKEND", "sqlite")
    monkeypatch.setenv("SCHEDULER_DATABASE_PATH", str(database_path))
    monkeypatch.setenv("SCHEDULER_ORGANIZATION_ID", organization.id)
    monkeypatch.setenv("SCHEDULER_CONVERSATIONAL_SCHEDULING_ENABLED", "true")
    return store, organization.id


def _workbook_bytes() -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "已有课表明细"
    sheet.append(["班级", "学科", "星期", "节次", "教师"])
    sheet.append(["高一1班", "语文", "星期一", "上午1", "教师A"])
    sheet.append(["高一1班", "数学", "星期一", "下午2", "教师B"])
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def test_existing_timetable_is_converted_to_solver_warm_start() -> None:
    summary, warm_start = inspect_scheduling_file("已有课表.xlsx", _workbook_bytes())

    assert summary["classification"] == "existing_timetable"
    assert summary["warm_start_capable"] is True
    assert summary["warm_start_records"] == 2
    assert warm_start["day"]["x1"] == [
        ["高一1班", "语文", "星期一", "上午", "1"],
        ["高一1班", "数学", "星期一", "下午", "2"],
    ]


def test_conversation_sessions_are_persistent_and_owner_scoped(tmp_path: Path, monkeypatch) -> None:
    _runtime(tmp_path, monkeypatch)

    created = create_conversation_session(
        {"entry_mode": "direct", "source_mode": "current_project"},
        actor_user_id="user-a",
    )
    loaded = get_conversation_session(created["id"], actor_user_id="user-a")
    listing = list_conversation_sessions(actor_user_id="user-a")

    assert conversation_feature_access()["enabled"] is True
    assert loaded["id"] == created["id"]
    assert loaded["messages"][0]["role"] == "assistant"
    assert listing["count"] == 1
    assert list_conversation_sessions(actor_user_id="user-b")["sessions"] == []


def test_model_failure_is_explicit_and_never_fakes_ai_participation(tmp_path: Path, monkeypatch) -> None:
    _runtime(tmp_path, monkeypatch)
    session = create_conversation_session(
        {"entry_mode": "direct", "source_mode": "current_project"},
        actor_user_id="user-a",
    )

    updated = add_conversation_message(
        session["id"],
        {"content": "数学尽量安排在上午，教师A周三不能上课。"},
        actor_user_id="user-a",
    )

    assert updated["phase"] == "data_needed"
    assert updated["model"]["ai"]["used"] is False
    assert updated["model"]["ai"]["mode"] == "local_skill"
    assert updated["model"]["limitations"][0]["title"] == "AI 建模未完成"
    assert "不会" in updated["messages"][-1]["content"]


def test_conversation_route_only_accepts_known_session_actions() -> None:
    session_id = "9f1ddfea-9cc2-48ac-a101-22b55cb37ea3"
    assert conversation_route(f"/api/conversation-scheduler/sessions/{session_id}") == (session_id, "detail")
    assert conversation_route(f"/api/conversation-scheduler/sessions/{session_id}/messages") == (session_id, "messages")
    assert conversation_route(f"/api/conversation-scheduler/sessions/{session_id}/unknown") is None
    assert conversation_route("/api/conversation-scheduler/sessions/not-a-uuid") is None


def test_current_snapshot_exposes_actionable_blockers_to_ai(monkeypatch) -> None:
    monkeypatch.setattr(conversational_scheduler, "list_teacher_subject_rows", lambda: [])
    monkeypatch.setattr(
        conversational_scheduler,
        "load_day_rule_tables",
        lambda: {"time_grid": [], "subject_hours": [], "fixed_slots": []},
    )
    monkeypatch.setattr(conversational_scheduler, "load_rule_v2_payload", lambda: {"summary": {"active": 0}})
    monkeypatch.setattr(
        conversational_scheduler,
        "build_solve_readiness",
        lambda _mode: {
            "summary": {"can_start_solver": False, "blocking_errors": 1},
            "items": [{
                "severity": "error",
                "blocking": True,
                "domain": "值班/查寝",
                "title": "晚查寝候选人数不足",
                "detail": "需求 6 次，容量 5 次。",
                "suggestion": "增加候选人或提高周上限。",
                "remediation_options": [{"title": "把周上限调到 2 次", "detail": "补足容量", "risk": "负荷增加"}],
            }],
        },
    )

    snapshot = conversational_scheduler._current_data_snapshot(context={}, files=[])

    blocker = snapshot["readiness"]["blocking_items"][0]
    assert blocker["title"] == "晚查寝候选人数不足"
    assert blocker["suggestion"] == "增加候选人或提高周上限。"
    assert blocker["remediation_options"][0]["title"] == "把周上限调到 2 次"


def test_upload_base_uses_only_uploaded_subjects_and_ignores_repository_defaults(monkeypatch) -> None:
    def forbidden_default_loader(*_args, **_kwargs):
        raise AssertionError("upload_base must not read repository defaults")

    monkeypatch.setattr(conversational_scheduler, "list_teacher_subject_rows", forbidden_default_loader)
    monkeypatch.setattr(conversational_scheduler, "load_day_rule_tables", forbidden_default_loader)
    monkeypatch.setattr(conversational_scheduler, "load_rule_v2_payload", forbidden_default_loader)
    monkeypatch.setattr(conversational_scheduler, "build_solve_readiness", forbidden_default_loader)
    monkeypatch.setattr(
        conversational_scheduler,
        "load_web_overrides",
        lambda: {
            "io": {
                "web_tables": {
                    "day_rules": {
                        "time_grid": [{"时段节次": "上午1", "星期一": 1}],
                        "subject_hours": [
                            {"学科": "语文", "周中课时": 4},
                            {"学科": "数学", "周中课时": 4},
                        ],
                        "fixed_slots": [],
                    },
                    "teacher_subjects": [{
                        "班级": "示例班级1",
                        "班主任": "",
                        "班主任性别": "",
                        "语文": "Teacher001",
                        "数学": "Teacher002",
                    }],
                }
            }
        },
    )

    snapshot = conversational_scheduler._current_data_snapshot(
        context={"source_mode": "upload_base"},
        files=[],
    )

    assert snapshot["slot_context"]["subjects"] == ["语文", "数学"]
    assert "技术" not in snapshot["slot_context"]["subjects"]
    assert snapshot["slot_context"]["status"] == "available"
    assert snapshot["readiness"]["can_start_solver"] is False


def test_ai_payload_redacts_teacher_names_inside_blocker_details(monkeypatch) -> None:
    captured: dict = {}

    class FakeClient:
        def complete_json(self, *, system_prompt: str, user_payload: dict) -> JsonModelResult:
            captured["system_prompt"] = system_prompt
            captured["payload"] = user_payload
            return JsonModelResult(
                value={
                    "assistant_message": "建模信息足够，请确认。",
                    "phase": "model_ready",
                    "questions": [],
                    "facts": {},
                    "requirements": [{
                        "statement": "教师每天最多 4 节",
                        "strength": "hard",
                        "scope": "全校教师",
                        "effective_time": "当前学期",
                        "exceptions": [],
                    }],
                    "rule_statements": ["每位教师每天最多安排4节课"],
                    "limitations": [],
                    "recommendations": [],
                    "solve_mode": "joint",
                },
                provider_id="test",
                model="test-model",
            )

    monkeypatch.setattr(conversational_scheduler, "_build_model_client", lambda *_args, **_kwargs: FakeClient())
    monkeypatch.setattr(conversational_scheduler, "_known_teachers", lambda: ["教师001"])
    session = {
        "entry_mode": "direct",
        "source_mode": "current_project",
        "model": {},
        "messages": [{"role": "user", "content": "教师001周三不排课"}],
    }
    data = {
        "readiness": {
            "can_start_solver": False,
            "blocking_errors": 1,
            "blocking_items": [{"title": "教师001固定课冲突", "detail": "教师001周三已有固定课"}],
        }
    }
    checklist = [{"id": "requirements", "required": True, "status": "ready"}]

    model = conversational_scheduler._run_conversation_model(
        session=session,
        data=data,
        checklist=checklist,
        actor_user_id="user-a",
    )

    serialized = str(captured["payload"])
    assert "教师001" not in serialized
    assert "教师代号_001" in serialized
    assert model["phase"] == "clarifying"
    assert model["unparsed_inputs"]
    assert model["ai"]["used"] is True


def test_model_ready_requires_an_executable_rule_statement() -> None:
    model = conversational_scheduler._normalize_model(
        {
            "assistant_message": "可以确认",
            "phase": "model_ready",
            "questions": [],
            "requirements": [{"statement": "数学尽量安排在上午", "strength": "soft"}],
            "rule_statements": [],
        },
        checklist=[{"id": "requirements", "required": True, "status": "ready"}],
    )

    assert model["phase"] == "clarifying"
    assert model["questions"][0]["id"] == "executable-rules"


def test_model_ready_allows_explicit_current_data_default_plan_without_new_rules() -> None:
    model = conversational_scheduler._normalize_model(
        {
            "assistant_message": "已理解，将按当前数据和已生效规则排课。",
            "phase": "model_ready",
            "questions": [],
            "requirements": [{"statement": "按当前数据和已生效规则排课", "strength": "advisory"}],
            "rule_statements": [],
            "default_constraints_only": True,
        },
        checklist=[{"id": "requirements", "required": True, "status": "ready"}],
    )

    assert model["phase"] == "model_ready"
    assert model["default_constraints_only"] is True
    assert model["rule_statements"] == []


def test_default_plan_without_explicit_intent_stays_clarifying() -> None:
    model = conversational_scheduler._normalize_model(
        {
            "assistant_message": "信息足够。",
            "phase": "model_ready",
            "questions": [],
            "requirements": [{"statement": "按当前数据排课", "strength": "advisory"}],
            "rule_statements": [],
            "default_constraints_only": False,
        },
        checklist=[{"id": "requirements", "required": True, "status": "ready"}],
    )

    assert model["phase"] == "clarifying"
    assert model["questions"][0]["id"] == "executable-rules"


def test_ai_failure_cannot_become_model_ready_from_local_parse(monkeypatch) -> None:
    monkeypatch.setattr(conversational_scheduler, "_build_model_client", lambda *_args, **_kwargs: None)
    model = conversational_scheduler._run_conversation_model(
        session={"entry_mode": "direct", "source_mode": "current_project", "messages": [{"role": "user", "content": "数学安排在上午"}]},
        data={},
        checklist=[{"id": "requirements", "required": True, "status": "ready"}],
        actor_user_id="user-a",
    )

    assert model["phase"] == "clarifying"
    assert model["ai"]["used"] is False
    assert model["limitations"][0]["title"] == "AI 建模未完成"


def test_ai_model_ready_with_unparsed_input_is_demoted(monkeypatch) -> None:
    class FakeClient:
        def complete_json(self, *, system_prompt: str, user_payload: dict) -> JsonModelResult:
            return JsonModelResult(
                value={
                    "assistant_message": "已理解。",
                    "phase": "model_ready",
                    "questions": [],
                    "requirements": [{"statement": "按当前数据和已生效规则排课", "strength": "advisory"}],
                    "rule_statements": [],
                    "default_constraints_only": True,
                },
                provider_id="test",
                model="test-model",
            )

    monkeypatch.setattr(conversational_scheduler, "_build_model_client", lambda *_args, **_kwargs: FakeClient())
    model = conversational_scheduler._run_conversation_model(
        session={"entry_mode": "direct", "source_mode": "current_project", "messages": [{"role": "user", "content": "按情况安排，除外特殊情况"}]},
        data={},
        checklist=[{"id": "requirements", "required": True, "status": "ready"}],
        actor_user_id="user-a",
    )

    assert model["phase"] == "clarifying"
    assert model["ai"]["used"] is True
    assert model["unparsed_inputs"]


def test_current_user_confirmation_writes_rules_then_preserves_solver_blocker(tmp_path: Path, monkeypatch) -> None:
    _runtime(tmp_path, monkeypatch)
    session = create_conversation_session(
        {"entry_mode": "direct", "source_mode": "current_project"},
        actor_user_id="user-a",
    )
    conversational_scheduler._persist_model_and_message(
        session["id"],
        "user-a",
        {
            "phase": "model_ready",
            "status": "ready",
            "assistant_message": "请确认",
            "requirements": [{"statement": "每位教师每天最多 4 节", "strength": "hard"}],
            "rule_statements": ["每位教师每天最多安排4节课"],
            "limitations": [],
            "solve_mode": "joint",
            "ai": {"used": True},
        },
        kind="model",
    )
    calls: list[tuple[str, str]] = []
    draft = {
        "id": "rule.daily.max4",
        "title": "教师每日最多 4 节",
        "ai_used": True,
        "validation": {"valid": True},
        "solver_support": {"status": "supported"},
    }
    monkeypatch.setattr(conversational_scheduler, "_apply_confirmed_uploads", lambda *_args, **_kwargs: {"imported": []})
    monkeypatch.setattr(conversational_scheduler, "_known_teachers", lambda: [])
    monkeypatch.setattr(conversational_scheduler, "_build_model_client", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(conversational_scheduler, "load_effective_payload", lambda _mode: {"business_rule_groups": []})
    monkeypatch.setattr(conversational_scheduler, "parse_rule_v2_with_ai", lambda *_args, **_kwargs: draft)
    monkeypatch.setattr(conversational_scheduler, "load_rule_v2_payload", lambda: {"revision": 0})

    def save_rule(_draft, **_kwargs):
        calls.append(("save", _draft["id"]))
        return {"revision": 1}

    def activate_rule(rule_id, **_kwargs):
        calls.append(("activate", rule_id))
        return {"revision": 2}

    monkeypatch.setattr(conversational_scheduler, "save_rule_v2", save_rule)
    monkeypatch.setattr(conversational_scheduler, "activate_saved_rule_v2", activate_rule)
    monkeypatch.setattr(
        conversational_scheduler,
        "build_solve_readiness",
        lambda _mode: {"summary": {"can_start_solver": False, "blocking_errors": 1}},
    )

    confirmed = confirm_conversation_model(
        session["id"],
        {"confirm": True},
        actor_user_id="user-a",
    )

    assert calls == [("save", "rule.daily.max4"), ("activate", "rule.daily.max4")]
    assert confirmed["phase"] == "blocked"
    assert confirmed["confirmed_at"]
    assert confirmed["model"]["activated_rule_ids"] == ["rule.daily.max4"]
    assert "仍有阻断项" in confirmed["messages"][-1]["content"]


def test_prepare_solve_accepts_only_confirmed_ready_session(monkeypatch) -> None:
    monkeypatch.setenv("SCHEDULER_CONVERSATIONAL_SCHEDULING_ENABLED", "true")
    monkeypatch.setenv("SCHEDULER_ORGANIZATION_ID", "org-a")
    monkeypatch.setattr(
        conversational_scheduler,
        "get_conversation_session",
        lambda *_args, **_kwargs: {
            "phase": "ready_to_solve",
            "model": {
                "solve_mode": "joint",
                "confirmed_workspace_revision": 7,
            },
        },
    )
    monkeypatch.setattr(
        conversational_scheduler,
        "runtime_store",
        lambda: SimpleNamespace(
            load_workspace=lambda _organization_id: SimpleNamespace(revision=7),
        ),
    )
    monkeypatch.setattr(
        conversational_scheduler,
        "build_solve_readiness",
        lambda _mode: {"summary": {"can_start_solver": True}},
    )

    payload = prepare_conversation_solve(
        "session-a",
        {"time_limit_seconds": 900},
        actor_user_id="user-a",
    )

    assert payload == {
        "mode": "joint",
        "time_limit_seconds": 900,
        "_expected_workspace_revision": 7,
    }


def test_prepare_solve_rejects_session_without_confirmed_workspace_revision(monkeypatch) -> None:
    monkeypatch.setenv("SCHEDULER_CONVERSATIONAL_SCHEDULING_ENABLED", "true")
    monkeypatch.setattr(
        conversational_scheduler,
        "get_conversation_session",
        lambda *_args, **_kwargs: {
            "phase": "ready_to_solve",
            "model": {"solve_mode": "joint"},
        },
    )

    try:
        prepare_conversation_solve(
            "session-a",
            {"time_limit_seconds": 900},
            actor_user_id="user-a",
        )
    except ValueError as exc:
        assert "固定工作区版本" in str(exc)
    else:
        raise AssertionError("unconfirmed session must not enter solve preparation")
