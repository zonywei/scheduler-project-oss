from __future__ import annotations

import copy
import json

import pytest

from scheduler.app import formal_product
from scheduler.app.model_gateway import JsonModelResult


def _store(monkeypatch: pytest.MonkeyPatch) -> dict:
    state = {"payload": {"io": {}, "rules": {}, "temporary_rules": {"active": []}, "academic_affairs": {}}}

    def load() -> dict:
        return copy.deepcopy(state["payload"])

    def save(payload: dict, **_kwargs) -> dict:
        state["payload"] = copy.deepcopy(payload)
        return copy.deepcopy(payload)

    monkeypatch.setattr(formal_product, "load_web_overrides", load)
    monkeypatch.setattr(formal_product, "save_web_overrides", save)
    return state


def _draft() -> dict:
    return {
        "title": "数学尽量排上午",
        "strength": "soft",
        "scope": {"subjects": ["数学"]},
        "effective_time": {"mode": "project_term", "week_pattern": "all"},
        "constraint": {"type": "prefer_period", "params": {"period": "morning"}},
        "solver_support": {"status": "supported", "compiler": "day.rule_v2.v1"},
    }


def test_ruleset_uses_revision_and_immutable_snapshots(monkeypatch: pytest.MonkeyPatch) -> None:
    _store(monkeypatch)
    saved = formal_product.save_rule_v2(_draft(), expected_revision=0, actor="tester")
    assert saved["revision"] == 1
    assert saved["summary"]["drafts"] == 1
    rule_id = saved["rules"][0]["id"]
    activated = formal_product.activate_saved_rule_v2(
        rule_id,
        expected_revision=1,
        confirmed=True,
        actor="tester",
    )
    assert activated["revision"] == 2
    assert activated["summary"]["active"] == 1
    assert [item["revision"] for item in activated["snapshots"]] == [1, 2]
    assert activated["snapshots"][0]["rules"][0]["status"] == "draft"


def test_project_settings_force_one_repeating_week_and_persist_period_counts(monkeypatch: pytest.MonkeyPatch) -> None:
    store = _store(monkeypatch)
    saved = formal_product.save_project_settings(
        {
            "term_name": "2026 秋季学期",
            "term_start": "2026-09-01",
            "term_end": "2027-01-20",
            "week_mode": "ab",
            "active_days": ["星期一", "星期三", "星期六"],
            "public_rest": "周日",
            "period_counts": {"early": 1, "morning": 5, "afternoon": 4, "evening": 0},
        },
        actor="tester",
    )

    assert saved["week_mode"] == "weekly"
    assert saved["active_days"] == ["星期一", "星期三", "星期六"]
    assert saved["period_counts"] == {"early": 1, "morning": 5, "afternoon": 4, "evening": 0}
    assert store["payload"]["rules"]["product_state"]["project_settings"]["term_name"] == "2026 秋季学期"


def test_new_project_requires_education_office_to_define_period_counts(monkeypatch: pytest.MonkeyPatch) -> None:
    _store(monkeypatch)
    settings = formal_product.load_project_settings()

    assert settings["week_mode"] == "weekly"
    assert settings["period_counts"] == {"early": 0, "morning": 0, "afternoon": 0, "evening": 0}


def test_ruleset_rejects_stale_revision(monkeypatch: pytest.MonkeyPatch) -> None:
    _store(monkeypatch)
    formal_product.save_rule_v2(_draft(), expected_revision=0, actor="tester")
    with pytest.raises(ValueError, match="刷新后重试"):
        formal_product.save_rule_v2(_draft(), expected_revision=0, actor="tester")


def test_editing_active_rule_resets_confirmation(monkeypatch: pytest.MonkeyPatch) -> None:
    _store(monkeypatch)
    saved = formal_product.save_rule_v2(_draft(), expected_revision=0, actor="tester")
    active = formal_product.activate_saved_rule_v2(
        saved["rules"][0]["id"], expected_revision=1, confirmed=True, actor="tester"
    )
    changed = copy.deepcopy(active["rules"][0])
    changed["description"] = "变更后的业务语义"
    result = formal_product.save_rule_v2(changed, expected_revision=2, actor="tester")
    assert result["rules"][0]["status"] == "draft"
    assert result["rules"][0]["confirmation"]["confirmed"] is False


def test_ai_parser_normalizes_model_output_into_safe_rule() -> None:
    class Client:
        def complete_json(self, **_kwargs) -> JsonModelResult:
            return JsonModelResult(
                value=_draft(),
                provider_id="domestic-test",
                model="test-model",
                request_id="req-1",
                usage={"total_tokens": 42},
            )

    parsed = formal_product.parse_rule_v2_with_ai("数学尽量排在上午", client=Client())
    assert parsed["ai_used"] is True
    assert parsed["schema_version"] == "scheduler.rule.v2"
    assert parsed["constraint"]["type"] == "prefer_period"
    assert parsed["provenance"]["provider_id"] == "domestic-test"
    assert parsed["ai_modeling"]["participated"] is True
    assert parsed["ai_modeling"]["constraint_mapping"][0]["rule_v2_type"] == "prefer_period"
    assert parsed["ai_modeling"]["solver_handoff"]["requires_user_confirmation"] is True
    assert "patches" not in parsed


def test_ai_parser_never_sends_the_full_teacher_roster_or_real_names() -> None:
    class Client:
        def complete_json(self, **kwargs) -> JsonModelResult:
            payload = kwargs["user_payload"]
            serialized = json.dumps(payload, ensure_ascii=False)
            assert "样例教师A" not in serialized
            assert "样例教师B" not in serialized
            assert len(payload["known_teachers"]) == 1
            assert len(set(payload["known_teachers"])) == 1
            teacher_alias = payload["known_teachers"][0]
            return JsonModelResult(
                value={
                    **_draft(),
                    "scope": {"teachers": [teacher_alias], "display": teacher_alias},
                },
                provider_id="domestic-test",
                model="test-model",
            )

    parsed = formal_product.parse_rule_v2_with_ai(
        "样例教师A周一不能排课",
        known_teachers=["样例教师A", "样例教师B"],
        client=Client(),
    )

    assert parsed["ai_used"] is True
    assert parsed["scope"]["teachers"] == ["样例教师A"]


def test_ai_parser_keeps_hard_preference_hard_when_model_downgrades_it() -> None:
    class Client:
        def complete_json(self, **_kwargs) -> JsonModelResult:
            return JsonModelResult(
                value={
                    **_draft(),
                    "strength": "soft",
                    "scope": {"subjects": ["数学"]},
                },
                provider_id="domestic-test",
                model="test-model",
            )

    parsed = formal_product.parse_rule_v2_with_ai(
        "数学必须安排在上午",
        known_subjects=["数学"],
        client=Client(),
    )

    assert parsed["strength"] == "hard"


def test_ai_parser_discards_model_entities_not_present_in_uploaded_inventories() -> None:
    class Client:
        def complete_json(self, **_kwargs) -> JsonModelResult:
            return JsonModelResult(
                value={
                    **_draft(),
                    "scope": {"subjects": ["数学"], "classes": ["高一1班"]},
                },
                provider_id="domestic-test",
                model="test-model",
            )

    parsed = formal_product.parse_rule_v2_with_ai(
        "物理尽量安排在上午",
        known_subjects=["物理"],
        known_classes=["高一2班"],
        client=Client(),
    )

    assert parsed["scope"]["subjects"] == ["物理"]
    assert parsed["scope"]["classes"] == []


def test_formal_solve_phase_exposes_real_phase_timeline() -> None:
    status = formal_product.attach_formal_solve_phase({"status": "running", "solution_count": 2})
    assert status["phase"] == "optimizing"
    assert [item["status"] for item in status["phase_timeline"]] == [
        "completed", "completed", "completed", "active", "pending"
    ]


def test_formal_solve_phase_marks_the_failed_checkpoint() -> None:
    status = formal_product.attach_formal_solve_phase(
        {"status": "failed", "failed_phase": "finding_feasible"}
    )

    assert status["phase_label"] == "求解未完成"
    assert [item["status"] for item in status["phase_timeline"]] == [
        "completed", "completed", "failed", "pending", "pending"
    ]


def test_formal_solve_phase_honors_worker_packaging_phase() -> None:
    status = formal_product.attach_formal_solve_phase(
        {"status": "running", "execution_phase": "packaging"}
    )

    assert status["phase"] == "packaging"
    assert status["phase_label"] == "生成结果与诊断"
    assert [item["status"] for item in status["phase_timeline"]] == [
        "completed", "completed", "completed", "completed", "active"
    ]


def test_publish_records_only_release_ready_fresh_candidate(monkeypatch: pytest.MonkeyPatch) -> None:
    _store(monkeypatch)
    status = {
        "job_id": "job-1",
        "publish_assessment": {"summary": {"status": "ready", "can_publish": True}},
        "config_freshness": {"status": "matched"},
        "config_fingerprint": {"hash": "abc"},
        "files": [{"name": "正式课表.xlsx", "category": "schedule"}],
    }
    published = formal_product.publish_current_candidate(status, actor="tester", note="教务主任已确认")
    assert published["count"] == 1
    assert published["current"]["status"] == "published"
    assert published["current"]["version"] == "课表 V1"


def test_publish_blocks_stale_candidate(monkeypatch: pytest.MonkeyPatch) -> None:
    _store(monkeypatch)
    status = {
        "publish_assessment": {"summary": {"status": "ready", "can_publish": True}},
        "config_freshness": {"status": "stale"},
        "files": [{"name": "正式课表.xlsx", "category": "schedule"}],
    }
    with pytest.raises(ValueError, match="重新求解"):
        formal_product.publish_current_candidate(status, actor="tester")


def test_project_state_does_not_treat_logs_as_a_publishable_schedule(monkeypatch: pytest.MonkeyPatch) -> None:
    _store(monkeypatch)
    payload = formal_product.build_project_state(
        teacher_rows=[{"班级": "高三1班", "数学": "样例教师A"}],
        day_rules={"subject_hours": [{"年级": "高三", "学科": "数学"}]},
        readiness={"summary": {"can_start_solver": True}},
        solve_status={"status": "completed", "files": [{"name": "run.log", "category": "log"}]},
        result_preview={"summary": {"schedule_files": 0}, "workbooks": [], "class_views": [], "teacher_views": []},
    )
    stages = {item["id"]: item for item in payload["stages"]}
    assert payload["phase"] == "solve"
    assert stages["solve"]["completed"] is False
    assert stages["review"]["completed"] is False


def test_publish_blocks_candidate_without_accessible_result_preview(monkeypatch: pytest.MonkeyPatch) -> None:
    _store(monkeypatch)
    status = {
        "publish_assessment": {"summary": {"status": "ready", "can_publish": True}},
        "config_freshness": {"status": "matched"},
        "files": [{"name": "正式课表.xlsx", "category": "schedule"}],
    }
    preview = {"summary": {"schedule_files": 0}, "workbooks": [], "class_views": [], "teacher_views": []}
    with pytest.raises(ValueError, match="可在线核验"):
        formal_product.publish_current_candidate(status, actor="tester", result_preview=preview)


def test_ai_parser_repairs_allowlisted_period_parameter_and_reports_limitations() -> None:
    class Client:
        def complete_json(self, **_kwargs) -> JsonModelResult:
            return JsonModelResult(
                value={
                    **_draft(),
                    "constraint": {"type": "prefer_period", "params": {}},
                    "modeling_report": {
                        "interpreted_requirements": ["高一数学上午优先", "周五第4节作为例外"],
                        "constraint_mapping": [{
                            "requirement": "高一数学上午优先",
                            "rule_v2_type": "prefer_period",
                            "solver_effect": "上午外课位进入软规则代价",
                        }],
                        "limitations": [{
                            "title": "例外节次需要核对",
                            "detail": "第4节口径可能因学校作息不同而变化",
                            "impact": "错误口径会扩大例外范围",
                        }],
                        "recommendations": [{
                            "title": "核对作息节次",
                            "action": "确认第4节对应的实际时段后再激活",
                        }],
                    },
                },
                provider_id="domestic-test",
                model="test-model",
            )

    parsed = formal_product.parse_rule_v2_with_ai(
        "高一数学尽量安排在上午，但周五第4节除外",
        client=Client(),
    )

    assert parsed["constraint"]["params"]["period"] == "morning"
    assert parsed["validation"]["valid"] is True
    assert parsed["ai_modeling"]["limitations"][0]["title"] == "例外节次需要核对"
    assert parsed["ai_modeling"]["recommendations"][0]["action"] == "确认第4节对应的实际时段后再激活"


def test_ai_blocker_review_lists_limitations_and_solutions_without_real_teacher_names() -> None:
    class Client:
        def complete_json(self, **kwargs) -> JsonModelResult:
            serialized = json.dumps(kwargs["user_payload"], ensure_ascii=False)
            assert "样例教师A" not in serialized
            return JsonModelResult(
                value={
                    "summary": "存在一项人力容量局限。",
                    "items": [{
                        "source_title": "教师代号_001候选不足",
                        "limitation": "教师代号_001当前可用次数低于需求。",
                        "solution": "补充可用日期或降低单周次数目标。",
                        "priority": "必须先处理",
                        "solvability": "修改后重新检查",
                    }],
                },
                provider_id="domestic-test",
                model="test-model",
            )

    result = formal_product.review_readiness_blockers_with_ai(
        {
            "items": [{
                "title": "样例教师A候选不足",
                "severity": "error",
                "detail": "样例教师A当前可用次数低于需求。",
                "suggestion": "补充候选。",
            }],
        },
        known_teachers=["样例教师A", "样例教师B"],
        client=Client(),
    )

    assert result["ai_used"] is True
    assert result["items"][0]["source_title"] == "样例教师A候选不足"
    assert result["items"][0]["solution"] == "补充可用日期或降低单周次数目标。"
