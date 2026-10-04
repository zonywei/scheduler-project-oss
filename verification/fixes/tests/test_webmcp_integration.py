from pathlib import Path

from scheduler.app.web import _security_headers


ROOT = Path(__file__).resolve().parents[3]
STATIC = ROOT / "scheduler" / "app" / "static"


def test_webmcp_script_registers_bounded_human_in_the_loop_tools() -> None:
    source = (STATIC / "webmcp.js").read_text(encoding="utf-8")

    expected_tools = {
        "inspect_schedule_project",
        "list_schedule_rules",
        "diagnose_schedule_conflicts",
        "draft_schedule_rule",
        "prepare_schedule_run",
    }
    for tool_name in expected_tools:
        assert f'name: "{tool_name}"' in source

    assert "document.modelContext.registerTool(tool)" in source
    assert "readOnlyHint" in source
    assert "untrustedContentHint" in source
    assert "consequentialHint" in source
    assert 'status: "draft_saved_for_human_review"' in source
    assert '"not activated"' in source
    assert '"no solve started"' in source
    assert 'api("/api/solve/start"' not in source
    assert 'api("/api/rules/v2/activate"' not in source
    assert 'api("/api/project/publish"' not in source


def test_webmcp_script_loads_after_the_application_shell() -> None:
    html = (STATIC / "index.html").read_text(encoding="utf-8")

    assert 'id="webMcpStatus"' in html
    assert html.index('/app.js') < html.index('/formal-v2.js') < html.index('/webmcp.js')


def test_webmcp_security_headers_enable_same_origin_tools() -> None:
    headers = dict(_security_headers())

    assert "tools=(self)" in headers["Permissions-Policy"]
    assert headers["Origin-Agent-Cluster"] == "?1"
    assert "script-src 'self'" in headers["Content-Security-Policy"]
