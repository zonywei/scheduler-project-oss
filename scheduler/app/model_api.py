"""Administrative API payloads for metered model usage and quota controls."""
from __future__ import annotations

import copy
from typing import Any, Mapping

from scheduler.app.model_router import build_metered_model_client
from scheduler.platform.model_usage import ModelUsageStore
from scheduler.platform.runtime import runtime_organization_id, runtime_store


def model_usage_summary(*, scope_user_id: str = "") -> dict[str, Any]:
    organization_id = runtime_organization_id()
    return ModelUsageStore(runtime_store()).summary(
        organization_id,
        user_id=str(scope_user_id or ""),
    )


def update_model_quota(payload: Mapping[str, Any], *, actor_user_id: str) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise ValueError("model quota payload must be an object")
    organization_id = runtime_organization_id()
    scope_user_id = str(payload.get("scope_user_id") or "").strip()
    usage = ModelUsageStore(runtime_store())
    limits = usage.set_quota(
        organization_id,
        scope_user_id=scope_user_id,
        request_limit=_quota_value(payload.get("request_limit", 0), "request_limit"),
        token_limit=_quota_value(payload.get("token_limit", 0), "token_limit"),
        cost_limit_microunits=_quota_value(
            payload.get("cost_limit_microunits", 0),
            "cost_limit_microunits",
        ),
        actor_user_id=actor_user_id,
    )
    return {
        "schema_version": "scheduler.model_quota.v1",
        "scope_user_id": scope_user_id,
        "period": "monthly",
        "request_limit": limits.request_limit,
        "token_limit": limits.token_limit,
        "cost_limit_microunits": limits.cost_limit_microunits,
    }


def test_model_connection(
    settings: Mapping[str, Any],
    *,
    organization_id: str,
    user_id: str,
) -> dict[str, Any]:
    """Run a small metered JSON probe without accepting credentials from the browser."""
    if not isinstance(settings, Mapping) or not settings.get("enabled"):
        raise ValueError("请先启用并保存 AI 服务")
    probe_settings = copy.deepcopy(dict(settings))
    providers = probe_settings.get("providers")
    if isinstance(providers, list):
        for provider in providers:
            if isinstance(provider, dict):
                provider["max_completion_tokens"] = min(
                    256,
                    max(128, int(provider.get("max_completion_tokens") or 256)),
                )
    else:
        probe_settings["max_completion_tokens"] = min(
            256,
            max(128, int(probe_settings.get("max_completion_tokens") or 256)),
        )
    result = build_metered_model_client(
        probe_settings,
        organization_id=str(organization_id),
        user_id=str(user_id or ""),
        operation="provider.connection_test",
    ).complete_json(
        system_prompt="你是课有序 AI 服务连通性检查器。只输出一个 JSON 对象。",
        user_payload={"task": "return connection status", "expected": {"ok": True}},
    )
    return {
        "schema_version": "scheduler.model_connection_test.v1",
        "status": "ready",
        "status_label": "连接正常",
        "message": "AI 服务已通过真实 JSON 请求验证。",
        "provider_id": result.provider_id,
        "model": result.model,
        "request_id": result.request_id,
        "usage": result.usage or {},
    }


def _quota_value(value: Any, label: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be an integer") from exc
    if not 0 <= parsed <= 10**15:
        raise ValueError(f"{label} must be between 0 and 1000000000000000")
    return parsed
