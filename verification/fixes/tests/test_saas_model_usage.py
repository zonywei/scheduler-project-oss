from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scheduler.app import config_service
from scheduler.app.model_gateway import JsonModelResult, ModelGatewayError
from scheduler.app.model_router import MeteredModelRouter, providers_from_settings
from scheduler.platform import (
    AuthService,
    ModelQuotaExceeded,
    ModelUsageStore,
    PasswordHasher,
    PlatformDatabase,
    PlatformDatabaseSettings,
    PlatformStore,
)


PASSWORD = "Correct-Horse-2026!"


def _store(tmp_path: Path) -> tuple[PlatformStore, object]:
    store = PlatformStore(PlatformDatabase(PlatformDatabaseSettings(path=tmp_path / "scheduler.db")))
    assert store.initialize() == (1, 2, 3, 4, 5, 6)
    organization = store.create_organization(slug="school-a", name="学校 A")
    return store, organization


def _user(store: PlatformStore, organization_id: str, username: str) -> object:
    return AuthService(store, password_hasher=PasswordHasher(iterations=100_000)).create_user(
        organization_id,
        username=username,
        display_name=username,
        role="scheduler_operator",
        password=PASSWORD,
    )


def test_organization_and_user_quotas_are_reserved_atomically_and_denials_are_ledgered(tmp_path: Path) -> None:
    store, organization = _store(tmp_path)
    user_a = _user(store, organization.id, "operator-a")  # type: ignore[attr-defined]
    user_b = _user(store, organization.id, "operator-b")  # type: ignore[attr-defined]
    clock = [datetime(2026, 7, 26, 8, 0, tzinfo=timezone.utc)]
    usage = ModelUsageStore(store, now=lambda: clock[0])
    usage.set_quota(
        organization.id,  # type: ignore[attr-defined]
        request_limit=2,
        actor_user_id="admin",
    )
    usage.set_quota(
        organization.id,  # type: ignore[attr-defined]
        scope_user_id=user_a.user_id,  # type: ignore[attr-defined]
        request_limit=1,
        actor_user_id="admin",
    )

    first = usage.reserve(
        organization.id,  # type: ignore[attr-defined]
        user_id=user_a.user_id,  # type: ignore[attr-defined]
        operation="rule.parse",
        estimated_prompt_tokens=20,
        estimated_completion_tokens=50,
        estimated_cost_microunits=70,
    )
    usage.finalize_success(
        first,
        provider_id="zhipu",
        model="glm-test",
        request_id="req-1",
        prompt_tokens=10,
        completion_tokens=5,
        total_tokens=15,
        cost_microunits=15,
        latency_ms=12,
        estimated=False,
    )
    with pytest.raises(ModelQuotaExceeded, match="请求次数") as user_denied:
        usage.reserve(
            organization.id,  # type: ignore[attr-defined]
            user_id=user_a.user_id,  # type: ignore[attr-defined]
            operation="rule.parse",
            estimated_prompt_tokens=1,
            estimated_completion_tokens=1,
            estimated_cost_microunits=1,
        )
    assert user_denied.value.code == "request_quota_exceeded"

    second = usage.reserve(
        organization.id,  # type: ignore[attr-defined]
        user_id=user_b.user_id,  # type: ignore[attr-defined]
        operation="rule.parse",
        estimated_prompt_tokens=2,
        estimated_completion_tokens=3,
        estimated_cost_microunits=5,
    )
    usage.finalize_success(
        second,
        provider_id="dashscope",
        model="qwen-test",
        request_id="req-2",
        prompt_tokens=2,
        completion_tokens=3,
        total_tokens=5,
        cost_microunits=5,
        latency_ms=9,
        estimated=False,
    )
    with pytest.raises(ModelQuotaExceeded) as organization_denied:
        usage.reserve(
            organization.id,  # type: ignore[attr-defined]
            user_id="third-user",
            operation="rule.parse",
            estimated_prompt_tokens=1,
            estimated_completion_tokens=1,
            estimated_cost_microunits=1,
        )
    assert organization_denied.value.code == "request_quota_exceeded"

    summary = usage.summary(organization.id)  # type: ignore[attr-defined]
    assert summary["totals"] == {
        "requests": 2,
        "tokens": 20,
        "cost_microunits": 20,
        "failed_requests": 0,
        "denied_requests": 2,
    }


def test_failed_reservation_releases_quota_and_actual_usage_replaces_estimate(tmp_path: Path) -> None:
    store, organization = _store(tmp_path)
    usage = ModelUsageStore(store)
    usage.set_quota(
        organization.id,  # type: ignore[attr-defined]
        token_limit=100,
        actor_user_id="admin",
    )
    failed = usage.reserve(
        organization.id,  # type: ignore[attr-defined]
        user_id="",
        operation="rule.parse",
        estimated_prompt_tokens=40,
        estimated_completion_tokens=50,
        estimated_cost_microunits=0,
    )
    usage.finalize_failure(failed, error_code="provider_failed", latency_ms=10)
    successful = usage.reserve(
        organization.id,  # type: ignore[attr-defined]
        user_id="",
        operation="rule.parse",
        estimated_prompt_tokens=40,
        estimated_completion_tokens=50,
        estimated_cost_microunits=0,
    )
    usage.finalize_success(
        successful,
        provider_id="zhipu",
        model="glm-test",
        request_id="req-ok",
        prompt_tokens=5,
        completion_tokens=5,
        total_tokens=10,
        cost_microunits=0,
        latency_ms=10,
        estimated=False,
    )
    next_reservation = usage.reserve(
        organization.id,  # type: ignore[attr-defined]
        user_id="",
        operation="rule.parse",
        estimated_prompt_tokens=40,
        estimated_completion_tokens=50,
        estimated_cost_microunits=0,
    )
    assert next_reservation.event_id


def test_router_falls_back_records_real_cost_and_opens_persistent_circuit(tmp_path: Path) -> None:
    store, organization = _store(tmp_path)
    clock = [datetime(2026, 7, 26, 8, 0, tzinfo=timezone.utc)]
    usage = ModelUsageStore(store, now=lambda: clock[0])
    settings = {
        "providers": [
            {
                "provider_name": "zhipu",
                "base_url": "https://zhipu.example/v1",
                "model": "glm-test",
                "api_key_env": "ZHIPU_API_KEY",
                "priority": 10,
                "circuit_failure_threshold": 1,
                "circuit_cooldown_seconds": 120,
                "input_price_microunits_per_million": 500_000,
                "output_price_microunits_per_million": 500_000,
                "max_completion_tokens": 256,
            },
            {
                "provider_name": "dashscope",
                "base_url": "https://dashscope.example/v1",
                "model": "qwen-test",
                "api_key_env": "DASHSCOPE_API_KEY",
                "priority": 20,
                "input_price_microunits_per_million": 1_000_000,
                "output_price_microunits_per_million": 2_000_000,
                "max_completion_tokens": 256,
            },
        ]
    }
    calls: list[str] = []

    class FakeClient:
        def __init__(self, provider_id: str) -> None:
            self.provider_id = provider_id

        def complete_json(self, *, system_prompt: str, user_payload: dict[str, object]) -> JsonModelResult:
            calls.append(self.provider_id)
            if self.provider_id == "zhipu":
                raise ModelGatewayError("synthetic outage")
            return JsonModelResult(
                value={"ok": True},
                provider_id="dashscope",
                model="qwen-test",
                request_id="req-fallback",
                usage={"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
            )

    router = MeteredModelRouter(
        providers_from_settings(settings),
        usage_store=usage,
        organization_id=organization.id,  # type: ignore[attr-defined]
        user_id="operator",
        operation="rule.parse",
        client_factory=lambda config: FakeClient(config.provider_id),
    )
    result = router.complete_json(system_prompt="return json", user_payload={"text": "test"})

    assert result.provider_id == "dashscope"
    assert calls == ["zhipu", "dashscope"]
    assert usage.provider_available(organization.id, "zhipu") is False  # type: ignore[attr-defined]
    with store.database.connect() as connection:
        event = connection.execute(
            "SELECT provider_id, model, total_tokens, cost_microunits, status, metadata_json FROM model_usage_events"
        ).fetchone()
    assert event is not None
    assert {key: event[key] for key in ("provider_id", "model", "total_tokens", "cost_microunits", "status")} == {
        "provider_id": "dashscope",
        "model": "qwen-test",
        "total_tokens": 120,
        "cost_microunits": 140,
        "status": "succeeded",
    }
    attempts = json.loads(str(event["metadata_json"]))["attempts"]
    assert attempts == [
        {"provider_id": "zhipu", "status": "failed"},
        {"provider_id": "dashscope", "status": "succeeded"},
    ]
    clock[0] += timedelta(seconds=121)
    assert usage.provider_available(organization.id, "zhipu") is True  # type: ignore[attr-defined]


def test_router_enforces_cost_quota_before_contacting_any_provider(tmp_path: Path) -> None:
    store, organization = _store(tmp_path)
    usage = ModelUsageStore(store)
    usage.set_quota(
        organization.id,  # type: ignore[attr-defined]
        cost_limit_microunits=1,
        actor_user_id="admin",
    )
    providers = providers_from_settings(
        {
            "provider_name": "dashscope",
            "base_url": "https://dashscope.example/v1",
            "model": "qwen-test",
            "max_completion_tokens": 256,
            "input_price_microunits_per_million": 1_000_000,
            "output_price_microunits_per_million": 2_000_000,
        }
    )
    contacted = False

    def factory(_config):
        nonlocal contacted
        contacted = True
        raise AssertionError("provider must not be contacted")

    router = MeteredModelRouter(
        providers,
        usage_store=usage,
        organization_id=organization.id,  # type: ignore[attr-defined]
        user_id="operator",
        operation="rule.parse",
        client_factory=factory,
    )
    with pytest.raises(ModelQuotaExceeded) as exc:
        router.complete_json(system_prompt="json", user_payload={"text": "test"})
    assert exc.value.code == "cost_quota_exceeded"
    assert contacted is False
    assert usage.summary(organization.id)["totals"]["denied_requests"] == 1  # type: ignore[attr-defined]


def test_ai_settings_preserve_provider_routing_but_never_store_raw_keys(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "web_overrides.yaml"
    monkeypatch.setattr(config_service, "WEB_OVERRIDES_PATH", config_path)
    saved = config_service.save_ai_rule_assistant(
        {
            "enabled": True,
            "api_key": "raw-secret-must-not-be-stored",
            "providers": [
                {
                    "provider_id": "dashscope",
                    "base_url": "https://dashscope.example/v1",
                    "model": "qwen-test",
                    "api_key_env": "DASHSCOPE_API_KEY",
                    "wire_api": "responses",
                    "reasoning_effort": "high",
                    "disable_response_storage": True,
                    "priority": 10,
                    "input_price_microunits_per_million": 1_000_000,
                }
            ],
        }
    )
    settings = saved["rules"]["ai_rule_assistant"]
    assert settings["providers"][0]["provider_name"] == "dashscope"
    assert settings["providers"][0]["api_key_env"] == "DASHSCOPE_API_KEY"
    assert settings["providers"][0]["wire_api"] == "responses"
    assert settings["providers"][0]["reasoning_effort"] == "high"
    assert settings["providers"][0]["disable_response_storage"] is True
    assert "raw-secret-must-not-be-stored" not in config_path.read_text(encoding="utf-8")
    assert "api_key" not in settings["providers"][0]
