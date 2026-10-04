from __future__ import annotations

import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


from scheduler.app.access_control import (  # noqa: E402
    PermissionDenied,
    assert_request_allowed,
    build_access_context,
    request_permission,
)


def test_access_context_lists_roles_and_campus_scope() -> None:
    context = build_access_context(
        "grade_lead",
        {
            "data": {
                "settings": {"campuses": ["东校区", "西校区"]},
                "tables": {
                    "campus_supervision": [
                        {"区域": "东校区/教学楼"},
                        {"区域": "西校区/宿舍区"},
                    ]
                },
            }
        },
    )

    assert context["role"]["key"] == "grade_lead"
    assert context["campus_scope"]["mode"] == "multi_campus"
    assert context["campus_scope"]["campuses"] == ["东校区", "西校区"]
    assert {role["key"] for role in context["roles"]} >= {"academic_admin", "grade_lead", "viewer"}
    trial = build_access_context("trial_operator")
    assert trial["role"]["label"] == "教务测试员"
    assert "solve.run" in trial["permissions"]
    assert "system.manage" not in trial["permissions"]


def test_viewer_is_read_only_for_write_endpoints() -> None:
    assert request_permission("GET", "/api/config") == "read"
    assert_request_allowed("GET", "/api/config", "viewer")

    with pytest.raises(PermissionDenied, match="只读查看"):
        assert_request_allowed("POST", "/api/teacher-subjects", "viewer")


def test_role_permissions_separate_grade_rules_dorm_and_solver() -> None:
    assert_request_allowed("POST", "/api/academic-affairs", "grade_lead")
    assert_request_allowed("POST", "/api/academic-affairs/timetable-adjustment/apply", "grade_lead")

    with pytest.raises(PermissionDenied, match="年级组"):
        assert_request_allowed("POST", "/api/rules/configure", "grade_lead")
    with pytest.raises(PermissionDenied, match="宿管/值周"):
        assert_request_allowed("POST", "/api/solve/start", "dorm_supervisor")
    with pytest.raises(PermissionDenied, match="宿管/值周"):
        assert_request_allowed("POST", "/api/publish-review/draft", "dorm_supervisor")


def test_model_cost_and_quota_controls_are_server_authorized() -> None:
    assert_request_allowed("POST", "/api/nl-rules/parse", "scheduler_operator")
    assert_request_allowed("GET", "/api/model/usage", "academic_admin")
    assert_request_allowed("POST", "/api/model/quota", "academic_admin")
    assert_request_allowed("POST", "/api/ai-settings/test", "academic_admin")

    with pytest.raises(PermissionDenied, match="只读查看"):
        assert_request_allowed("POST", "/api/nl-rules/parse", "viewer")
    with pytest.raises(PermissionDenied, match="排课操作员"):
        assert_request_allowed("GET", "/api/model/usage", "scheduler_operator")


def test_trial_operator_can_run_the_flow_but_cannot_manage_system_settings() -> None:
    for path in (
        "/api/teacher-subjects/import",
        "/api/day-rules",
        "/api/rules/v2",
        "/api/rules/v2/activate",
        "/api/solve/start",
        "/api/project/publish",
    ):
        assert_request_allowed("POST", path, "trial_operator")

    for path in ("/api/config", "/api/ai-settings", "/api/ai-settings/test", "/api/model/quota"):
        with pytest.raises(PermissionDenied, match="教务测试员"):
            assert_request_allowed("POST", path, "trial_operator")


def test_conversational_scheduling_is_a_premium_write_capability() -> None:
    path = "/api/conversation-scheduler/sessions/9f1ddfea-9cc2-48ac-a101-22b55cb37ea3/messages"
    assert request_permission("POST", path) == "conversation.schedule"
    assert_request_allowed("POST", path, "academic_admin")
    assert_request_allowed("POST", path, "scheduler_operator")
    with pytest.raises(PermissionDenied, match="年级组"):
        assert_request_allowed("POST", path, "grade_lead")


def test_frontend_exposes_simple_role_switcher() -> None:
    html = (REPO_ROOT / "scheduler" / "app" / "static" / "index.html").read_text(encoding="utf-8")
    script = (REPO_ROOT / "scheduler" / "app" / "static" / "app.js").read_text(encoding="utf-8")
    web = (REPO_ROOT / "scheduler" / "app" / "web.py").read_text(encoding="utf-8")

    assert "accessRoleSelect" in html
    assert "只读查看" in html
    assert "/api/access/context" in script
    assert "X-Scheduler-Role" in script
    assert "applyAccessPermissions" in script
    assert "工作身份" in script
    assert "/api/access/context" in web
    assert "assert_request_allowed" in web
