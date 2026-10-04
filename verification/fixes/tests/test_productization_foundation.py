from __future__ import annotations

import json
import threading
import tomllib
from http.server import ThreadingHTTPServer
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from scheduler.app import config_service, model_gateway
from scheduler.app.model_gateway import (
    JsonModelResult,
    ModelGatewayError,
    ModelProviderConfig,
    OpenAICompatibleJsonClient,
    _assert_provider_destination,
    pseudonymize_teacher_context,
    replace_model_tokens,
)
from scheduler.app.multipart import parse_multipart_form
from scheduler.app.nl_rules import parse_natural_language_rule, parse_rule_with_ai_settings
from scheduler.domain.rule_drafts import (
    RULE_DRAFT_SCHEMA_VERSION,
    activate_rule_draft,
    materialize_active_rule_drafts,
    validate_rule_draft,
)
from scheduler.app.web import SchedulerWebHandler
from scheduler.config.loader import load_effective_config


REPO_ROOT = Path(__file__).resolve().parents[3]


class _FakeJsonClient:
    def __init__(self, value: dict[str, Any]) -> None:
        self.value = value

    def complete_json(self, *, system_prompt: str, user_payload: dict[str, Any]) -> JsonModelResult:
        assert system_prompt
        assert user_payload["text"]
        return JsonModelResult(
            value=self.value,
            provider_id="test-provider",
            model="test-model",
            request_id="request-001",
            usage={"total_tokens": 42},
        )


def test_model_boundary_pseudonymizes_only_mentioned_teachers_and_restores_json() -> None:
    redacted, mentioned, restore_map = pseudonymize_teacher_context(
        "样例教师A周一不能排课",
        ["样例教师A", "样例教师B"],
    )

    assert "样例教师A" not in redacted
    assert "样例教师B" not in redacted
    assert mentioned == [next(alias for alias, teacher in restore_map.items() if teacher == "样例教师A")]
    restored = replace_model_tokens(
        {"teachers": mentioned, "description": f"{mentioned[0]}周一不能排课"},
        restore_map,
    )
    assert restored == {"teachers": ["样例教师A"], "description": "样例教师A周一不能排课"}


def test_web_module_imports_without_removed_cgi_module() -> None:
    from scheduler.app import web

    assert web.SchedulerWebHandler.server_version == "SchedulerWeb/0.2"


def test_stdlib_multipart_parser_reads_text_and_file_fields() -> None:
    boundary = "scheduler-boundary"
    body = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="table"\r\n\r\n'
        "teacher_subjects\r\n"
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="file"; filename="teachers.csv"\r\n'
        "Content-Type: text/csv\r\n\r\n"
        "班级,语文\r\n1班,教师A\r\n"
        f"--{boundary}--\r\n"
    ).encode("utf-8")

    form = parse_multipart_form(
        BytesIO(body),
        content_type=f"multipart/form-data; boundary={boundary}",
        content_length=len(body),
    )

    upload = form.get_file("file")
    assert form.getfirst("table") == "teacher_subjects"
    assert upload is not None
    assert upload.filename == "teachers.csv"
    assert "教师A" in upload.content.decode("utf-8")


def test_multipart_parser_enforces_request_size_limit() -> None:
    with pytest.raises(ValueError, match="exceeds"):
        parse_multipart_form(
            BytesIO(b"x" * 11),
            content_type="multipart/form-data; boundary=x",
            content_length=11,
            max_bytes=10,
        )


def test_local_rule_parser_emits_versioned_draft_that_requires_confirmation() -> None:
    rule = parse_natural_language_rule("教师A 周日晚自习禁排", known_teachers=["教师A"])

    assert rule["schema_version"] == RULE_DRAFT_SCHEMA_VERSION
    assert rule["status"] == "draft"
    assert rule["validation"]["valid"] is True
    assert rule["validation"]["requires_confirmation"] is True
    assert rule["confirmation"] == {"required": True, "confirmed": False}
    assert rule["provenance"]["parser"] == "local"

    with pytest.raises(ValueError, match="明确确认"):
        activate_rule_draft(rule, confirmed=False, actor="tester", known_targets=["教师A"])

    active = activate_rule_draft(rule, confirmed=True, actor="tester", known_targets=["教师A"])
    assert active["status"] == "active"
    assert active["confirmation"]["confirmed"] is True
    assert active["confirmation"]["confirmed_by"] == "tester"


def test_model_rule_draft_records_provider_and_usage_after_allowlist_validation() -> None:
    client = _FakeJsonClient(
        {
            "action": "ban",
            "scope": "night",
            "target_teachers": ["教师A"],
            "day": "星期日",
            "slot": "晚自习",
            "solver_supported": True,
            "patches": [
                {
                    "target": "rules",
                    "path": ["hard_bans", "teacher_day_bans", "星期日"],
                    "operation": "append_unique",
                    "values": ["教师A"],
                }
            ],
            "description": "教师A星期日晚自习禁排",
            "confidence": 0.86,
        }
    )

    rule = parse_rule_with_ai_settings(
        "教师A 周日晚自习禁排",
        known_teachers=["教师A"],
        settings={
            "enabled": True,
            "provider_name": "test-provider",
            "base_url": "https://models.example.test/v1",
            "model": "test-model",
        },
        client=client,
    )

    assert rule["ai_used"] is True
    assert rule["provenance"]["parser"] == "model"
    assert rule["provenance"]["provider_id"] == "test-provider"
    assert rule["model_request_id"] == "request-001"
    assert rule["model_usage"] == {"total_tokens": 42}
    assert validate_rule_draft(rule, known_targets=["教师A"]).valid is True


def test_model_rule_with_non_allowlisted_patch_falls_back_to_local_parser() -> None:
    client = _FakeJsonClient(
        {
            "action": "ban",
            "scope": "night",
            "target_teachers": ["教师A"],
            "day": "星期日",
            "slot": "晚自习",
            "solver_supported": True,
            "patches": [
                {
                    "target": "rules",
                    "path": ["runtime", "shell_command"],
                    "operation": "set",
                    "value": "remove everything",
                }
            ],
        }
    )

    rule = parse_rule_with_ai_settings(
        "教师A 周日晚自习禁排",
        known_teachers=["教师A"],
        settings={
            "enabled": True,
            "provider_name": "test-provider",
            "base_url": "https://models.example.test/v1",
            "model": "test-model",
        },
        client=client,
    )

    assert rule["ai_used"] is False
    assert rule["provenance"]["parser"] == "local"
    assert rule["solver_supported"] is True
    assert "安全校验" in rule["ai_note"]


def test_model_rule_with_semantically_mismatched_patch_falls_back() -> None:
    client = _FakeJsonClient(
        {
            "action": "require",
            "scope": "night",
            "target_teachers": ["教师A"],
            "day": "星期日",
            "slot": "晚自习",
            "solver_supported": True,
            "patches": [
                {
                    "target": "rules",
                    "path": ["hard_bans", "teacher_day_bans", "星期一"],
                    "operation": "append_unique",
                    "values": ["教师A"],
                }
            ],
        }
    )

    rule = parse_rule_with_ai_settings(
        "教师A 周日晚自习禁排",
        known_teachers=["教师A"],
        settings={
            "enabled": True,
            "provider_name": "test-provider",
            "base_url": "https://models.example.test/v1",
            "model": "test-model",
        },
        client=client,
    )

    assert rule["ai_used"] is False
    assert rule["provenance"]["parser"] == "local"
    assert "安全校验" in rule["ai_note"]


def test_confirmed_rule_drafts_overlay_without_mutating_base_rules() -> None:
    draft = parse_natural_language_rule("教师A 周日晚自习禁排", known_teachers=["教师A"])
    active = activate_rule_draft(draft, confirmed=True, actor="tester", known_targets=["教师A"])
    base = {
        "hard_bans": {"teacher_day_bans": {"星期日": ["原有教师"]}},
        "temporary_rules": {"active": [active]},
    }

    materialized = materialize_active_rule_drafts(base)

    assert materialized["hard_bans"]["teacher_day_bans"]["星期日"] == ["原有教师", "教师A"]
    assert base["hard_bans"]["teacher_day_bans"]["星期日"] == ["原有教师"]


def test_web_add_and_remove_rule_preserves_manual_base_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config_service, "WEB_OVERRIDES_PATH", tmp_path / "web_overrides.yaml")
    config_service.save_web_overrides(
        {
            "rules": {"hard_bans": {"teacher_day_bans": {"星期日": ["原有教师"]}}},
            "temporary_rules": {"active": []},
        }
    )
    handler = object.__new__(SchedulerWebHandler)
    draft = parse_natural_language_rule("教师A 周日晚自习禁排", known_teachers=["教师A"])

    added = handler._apply_temp_rule(
        {"rule": draft, "confirm": True, "actor": "tester"},
        reverse=False,
    )
    effective = materialize_active_rule_drafts(
        {**added["rules"], "temporary_rules": added["temporary_rules"]}
    )

    assert added["rules"]["hard_bans"]["teacher_day_bans"]["星期日"] == ["原有教师"]
    assert effective["hard_bans"]["teacher_day_bans"]["星期日"] == ["原有教师", "教师A"]
    assert added["temporary_rules"]["active"][0]["kind"] == "natural_language_rule"

    removed = handler._apply_temp_rule({"rule": draft}, reverse=True)

    assert removed["rules"]["hard_bans"]["teacher_day_bans"]["星期日"] == ["原有教师"]
    assert removed["temporary_rules"]["active"] == []


def test_web_reconfirming_rule_replaces_previous_revision(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config_service, "WEB_OVERRIDES_PATH", tmp_path / "web_overrides.yaml")
    config_service.save_web_overrides(
        {
            "rules": {"hard_bans": {"teacher_day_bans": {"星期日": ["原有教师"]}}},
            "temporary_rules": {"active": []},
        }
    )
    handler = object.__new__(SchedulerWebHandler)
    original = parse_natural_language_rule("教师A 周日晚自习禁排", known_teachers=["教师A"])
    first = handler._apply_temp_rule({"rule": original, "confirm": True, "actor": "tester"}, reverse=False)
    revised = parse_natural_language_rule("教师A 周六晚自习禁排", known_teachers=["教师A"])
    revised["id"] = original["id"]

    with pytest.raises(ValueError, match="明确确认"):
        handler._apply_temp_rule({"rule": revised, "confirm": False, "actor": "tester"}, reverse=False)
    assert config_service.load_web_overrides()["temporary_rules"]["active"] == first["temporary_rules"]["active"]

    updated = handler._apply_temp_rule({"rule": revised, "confirm": True, "actor": "tester"}, reverse=False)
    active = updated["temporary_rules"]["active"]
    effective = materialize_active_rule_drafts({**updated["rules"], "temporary_rules": updated["temporary_rules"]})

    assert len(active) == 1
    assert active[0]["id"] == original["id"]
    assert active[0]["day"] == "星期六"
    assert active[0]["confirmation"]["confirmed_by"] == "tester"
    assert effective["hard_bans"]["teacher_day_bans"]["星期日"] == ["原有教师"]
    assert effective["hard_bans"]["teacher_day_bans"]["星期六"] == ["教师A"]


def test_effective_config_materializes_confirmed_drafts_without_persisting_patch(tmp_path: Path) -> None:
    io_path = tmp_path / "io.yaml"
    rules_path = tmp_path / "rules.yaml"
    overrides_path = tmp_path / "web_overrides.yaml"
    io_path.write_text("{}", encoding="utf-8")
    rules_path.write_text(
        json.dumps(
            {"hard_bans": {"teacher_day_bans": {"星期日": ["原有教师"]}}},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    draft = parse_natural_language_rule("教师A 周日晚自习禁排", known_teachers=["教师A"])
    active = activate_rule_draft(draft, confirmed=True, actor="tester", known_targets=["教师A"])
    stored = {"io": {}, "rules": {}, "temporary_rules": {"active": [active]}}
    overrides_path.write_text(json.dumps(stored, ensure_ascii=False), encoding="utf-8")

    effective = load_effective_config("joint", {"io_path": io_path, "rules_path": rules_path})

    assert effective.rules_cfg["hard_bans"]["teacher_day_bans"]["星期日"] == ["原有教师", "教师A"]
    assert json.loads(overrides_path.read_text(encoding="utf-8"))["rules"] == {}


def test_model_provider_rejects_plain_http_for_remote_hosts() -> None:
    with pytest.raises(ValueError, match="HTTPS"):
        ModelProviderConfig.from_settings(
            {
                "provider_name": "unsafe",
                "base_url": "http://models.example.test/v1",
                "model": "model",
            }
        )


def test_responses_api_client_streams_json_without_provider_storage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events = "\n\n".join(
        [
            "event: response.created",
            'data: {"type":"response.created","response":{"id":"resp-001","model":"gpt-5.5"}}',
            "event: response.output_text.delta",
            'data: {"type":"response.output_text.delta","delta":"{\\"ok\\":true}"}',
            "event: response.completed",
            'data: {"type":"response.completed","response":{"id":"resp-001","model":"gpt-5.5","usage":{"input_tokens":12,"output_tokens":5,"total_tokens":17}}}',
            "data: [DONE]",
        ]
    ).encode("utf-8")
    captured: dict[str, Any] = {}

    class FakeResponse(BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    class FakeOpener:
        def open(self, request, timeout):
            captured["url"] = request.full_url
            captured["body"] = json.loads(request.data.decode("utf-8"))
            captured["authorization"] = request.get_header("Authorization")
            captured["user_agent"] = request.get_header("User-agent")
            captured["timeout"] = timeout
            return FakeResponse(events)

    monkeypatch.setenv("TEST_AI_KEY", "secret-value")
    monkeypatch.setattr(model_gateway.urllib.request, "build_opener", lambda *_handlers: FakeOpener())
    client = OpenAICompatibleJsonClient(
        ModelProviderConfig.from_settings(
            {
                "provider_name": "aihub",
                "base_url": "https://aihub.top",
                "model": "gpt-5.5",
                "api_key_env": "TEST_AI_KEY",
                "wire_api": "responses",
                "reasoning_effort": "xhigh",
                "disable_response_storage": True,
                "max_completion_tokens": 512,
            }
        )
    )

    result = client.complete_json(system_prompt="Return JSON", user_payload={"rule": "test"})

    assert result.value == {"ok": True}
    assert result.request_id == "resp-001"
    assert result.model == "gpt-5.5"
    assert result.usage == {"prompt_tokens": 12, "completion_tokens": 5, "total_tokens": 17}
    assert captured["url"] == "https://aihub.top/responses"
    assert captured["authorization"] == "Bearer secret-value"
    assert captured["user_agent"] == "CourseOrderAI/1.0"
    assert captured["body"]["store"] is False
    assert captured["body"]["stream"] is True
    assert captured["body"]["reasoning"] == {"effort": "xhigh"}
    assert captured["body"]["max_output_tokens"] == 512
    assert "secret-value" not in json.dumps(captured["body"])


def test_responses_api_client_requires_server_side_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MISSING_AI_KEY", raising=False)
    client = OpenAICompatibleJsonClient(
        ModelProviderConfig.from_settings(
            {
                "provider_name": "aihub",
                "base_url": "https://aihub.top",
                "model": "gpt-5.5",
                "api_key_env": "MISSING_AI_KEY",
                "wire_api": "responses",
            }
        )
    )

    with pytest.raises(ModelGatewayError) as exc_info:
        client.complete_json(system_prompt="Return JSON", user_payload={"rule": "test"})

    assert exc_info.value.code == "provider_credential_missing"


def test_model_provider_network_guard_blocks_private_targets_unless_exactly_allowlisted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = ModelProviderConfig.from_settings(
        {
            "provider_name": "private-target",
            "base_url": "https://127.0.0.1/v1",
            "model": "model",
        }
    )
    monkeypatch.setenv("SCHEDULER_AI_ENFORCE_PUBLIC_NETWORK", "true")
    monkeypatch.delenv("SCHEDULER_AI_ALLOWED_HOSTS", raising=False)
    with pytest.raises(ModelGatewayError, match="non-public"):
        _assert_provider_destination(config)

    monkeypatch.setenv("SCHEDULER_AI_ALLOWED_HOSTS", "127.0.0.1")
    _assert_provider_destination(config)

    monkeypatch.setenv("SCHEDULER_AI_ALLOWED_HOSTS", "approved.example")
    with pytest.raises(ModelGatewayError, match="not in"):
        _assert_provider_destination(config)


def test_web_rejects_unconfirmed_rule_draft_as_client_error() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), SchedulerWebHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        rule = parse_natural_language_rule("教师A 周日晚自习禁排", known_teachers=["教师A"])
        request = Request(
            f"http://127.0.0.1:{server.server_port}/api/nl-rules/add",
            data=json.dumps({"rule": rule, "confirm": False}, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json", "X-Scheduler-Role": "academic_admin"},
            method="POST",
        )
        with pytest.raises(HTTPError) as exc_info:
            urlopen(request, timeout=5)
        payload = json.loads(exc_info.value.read().decode("utf-8"))
        assert exc_info.value.code == 400
        assert "明确确认" in payload["error"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_pyproject_declares_build_backend_packages_and_runtime_dependencies() -> None:
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert data["build-system"]["build-backend"] == "setuptools.build_meta"
    assert data["project"]["scripts"]["scheduler-web"] == "scheduler.app.web:main"
    assert data["project"]["scripts"]["scheduler-platform"] == "scheduler.platform.cli:main"
    dependencies = set(data["project"]["dependencies"])
    assert {
        "ortools==9.15.6755",
        "pandas==2.3.2",
        "openpyxl==3.1.5",
        "PyYAML==6.0.3",
    } <= dependencies
    assert data["tool"]["setuptools"]["packages"]["find"]["include"] == [
        "ai_orchestrated_optimization*",
        "profiles*",
        "scheduler*",
    ]
    assert data["tool"]["setuptools"]["package-data"]["profiles"] == ["*/*.yaml"]


def test_frontend_and_release_gate_keep_human_confirmation_and_project_python_boundary() -> None:
    script = (REPO_ROOT / "scheduler" / "app" / "static" / "app.js").read_text(encoding="utf-8")
    release = (REPO_ROOT / "verify_release.ps1").read_text(encoding="utf-8-sig")

    assert "确认并加入求解" in script
    assert "confirm: !reverse" in script
    assert "规则草案已生成，请核对后确认" in script
    assert '.venv\\Scripts\\python.exe' in release
    assert "& py -3" not in release
