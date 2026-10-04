"""Metered multi-provider model routing for domestic OpenAI-compatible APIs."""
from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from scheduler.app.model_gateway import (
    JsonModelClient,
    JsonModelResult,
    ModelGatewayError,
    ModelProviderConfig,
    OpenAICompatibleJsonClient,
)
from scheduler.platform.model_usage import ModelUsageStore
from scheduler.platform.runtime import runtime_store


@dataclass(frozen=True)
class RoutedProvider:
    config: ModelProviderConfig
    priority: int = 100
    input_price_microunits_per_million: int = 0
    output_price_microunits_per_million: int = 0
    circuit_failure_threshold: int = 3
    circuit_cooldown_seconds: int = 60


ClientFactory = Callable[[ModelProviderConfig], JsonModelClient]


class MeteredModelRouter:
    def __init__(
        self,
        providers: list[RoutedProvider],
        *,
        usage_store: ModelUsageStore,
        organization_id: str,
        user_id: str,
        operation: str,
        client_factory: ClientFactory | None = None,
    ) -> None:
        if not providers:
            raise ValueError("at least one enabled AI provider is required")
        self.providers = sorted(providers, key=lambda item: (item.priority, item.config.provider_id))
        self.usage_store = usage_store
        self.organization_id = str(organization_id)
        self.user_id = str(user_id or "")
        self.operation = str(operation or "model.complete_json")
        self.client_factory = client_factory or OpenAICompatibleJsonClient

    def complete_json(self, *, system_prompt: str, user_payload: dict[str, Any]) -> JsonModelResult:
        prompt_estimate = _estimate_tokens(str(system_prompt or "")) + _estimate_tokens(
            json.dumps(user_payload, ensure_ascii=False, separators=(",", ":"))
        )
        completion_reserve = max(item.config.max_completion_tokens for item in self.providers)
        reserve_cost = max(
            _cost_microunits(item, prompt_estimate, completion_reserve)
            for item in self.providers
        )
        reservation = self.usage_store.reserve(
            self.organization_id,
            user_id=self.user_id,
            operation=self.operation,
            estimated_prompt_tokens=prompt_estimate,
            estimated_completion_tokens=completion_reserve,
            estimated_cost_microunits=reserve_cost,
            metadata={"provider_count": len(self.providers)},
        )
        started = time.perf_counter()
        attempts: list[dict[str, str]] = []
        last_gateway_error: ModelGatewayError | None = None
        for provider in self.providers:
            provider_id = provider.config.provider_id
            if not self.usage_store.provider_available(self.organization_id, provider_id):
                attempts.append({"provider_id": provider_id, "status": "circuit_open"})
                continue
            try:
                result = self.client_factory(provider.config).complete_json(
                    system_prompt=system_prompt,
                    user_payload=user_payload,
                )
            except Exception as exc:
                if isinstance(exc, ModelGatewayError):
                    last_gateway_error = exc
                error_code = (
                    exc.code
                    if isinstance(exc, ModelGatewayError) and str(getattr(exc, "code", "")).strip()
                    else "provider_request_failed"
                )
                self.usage_store.record_provider_failure(
                    self.organization_id,
                    provider_id,
                    error_code=error_code,
                    threshold=provider.circuit_failure_threshold,
                    cooldown_seconds=provider.circuit_cooldown_seconds,
                )
                attempts.append({"provider_id": provider_id, "status": "failed"})
                continue
            self.usage_store.record_provider_success(self.organization_id, provider_id)
            attempts.append({"provider_id": provider_id, "status": "succeeded"})
            usage = result.usage or {}
            prompt_tokens = _usage_value(usage, "prompt_tokens", prompt_estimate)
            completion_tokens = _usage_value(
                usage,
                "completion_tokens",
                _estimate_tokens(json.dumps(result.value, ensure_ascii=False, separators=(",", ":"))),
            )
            total_tokens = _usage_value(usage, "total_tokens", prompt_tokens + completion_tokens)
            estimated = not {"prompt_tokens", "completion_tokens"} <= set(usage)
            self.usage_store.finalize_success(
                reservation,
                provider_id=result.provider_id or provider_id,
                model=result.model or provider.config.model,
                request_id=result.request_id,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                cost_microunits=_cost_microunits(provider, prompt_tokens, completion_tokens),
                latency_ms=_latency_ms(started),
                estimated=estimated,
                metadata={"attempts": attempts},
            )
            return result
        self.usage_store.finalize_failure(
            reservation,
            error_code="all_providers_unavailable",
            latency_ms=_latency_ms(started),
            metadata={"attempts": attempts},
        )
        if last_gateway_error is not None:
            raise ModelGatewayError(
                str(last_gateway_error),
                code=last_gateway_error.code,
                status_code=last_gateway_error.status_code,
            ) from last_gateway_error
        raise ModelGatewayError("所有已配置 AI 供应商当前均不可用")


def build_metered_model_client(
    settings: Mapping[str, Any],
    *,
    organization_id: str,
    user_id: str,
    operation: str,
    client_factory: ClientFactory | None = None,
) -> MeteredModelRouter:
    return MeteredModelRouter(
        providers_from_settings(settings),
        usage_store=ModelUsageStore(runtime_store()),
        organization_id=organization_id,
        user_id=user_id,
        operation=operation,
        client_factory=client_factory,
    )


def providers_from_settings(settings: Mapping[str, Any]) -> list[RoutedProvider]:
    configured = settings.get("providers")
    raw_providers = [item for item in configured if isinstance(item, Mapping)] if isinstance(configured, list) else []
    if not raw_providers and str(settings.get("base_url") or "").strip():
        raw_providers = [settings]
    providers: list[RoutedProvider] = []
    seen: set[str] = set()
    for raw in raw_providers:
        if raw.get("enabled", True) is False:
            continue
        normalized = dict(raw)
        normalized["provider_name"] = str(raw.get("provider_name") or raw.get("provider_id") or "").strip()
        config = ModelProviderConfig.from_settings(normalized)
        if config.provider_id in seen:
            raise ValueError(f"duplicate AI provider_id: {config.provider_id}")
        seen.add(config.provider_id)
        providers.append(
            RoutedProvider(
                config=config,
                priority=_bounded_int(raw.get("priority", 100), 0, 10_000, "priority"),
                input_price_microunits_per_million=_bounded_int(
                    raw.get("input_price_microunits_per_million", 0),
                    0,
                    10**12,
                    "input price",
                ),
                output_price_microunits_per_million=_bounded_int(
                    raw.get("output_price_microunits_per_million", 0),
                    0,
                    10**12,
                    "output price",
                ),
                circuit_failure_threshold=_bounded_int(
                    raw.get("circuit_failure_threshold", 3), 1, 20, "circuit failure threshold"
                ),
                circuit_cooldown_seconds=_bounded_int(
                    raw.get("circuit_cooldown_seconds", 60), 1, 3_600, "circuit cooldown"
                ),
            )
        )
    if not providers:
        raise ValueError("未配置可用的 AI 供应商")
    return providers


def _cost_microunits(provider: RoutedProvider, prompt_tokens: int, completion_tokens: int) -> int:
    numerator = (
        max(0, int(prompt_tokens)) * provider.input_price_microunits_per_million
        + max(0, int(completion_tokens)) * provider.output_price_microunits_per_million
    )
    return math.ceil(numerator / 1_000_000) if numerator else 0


def _estimate_tokens(value: str) -> int:
    return max(1, math.ceil(len(str(value or "")) / 2))


def _usage_value(usage: Mapping[str, Any], key: str, default: int) -> int:
    value = usage.get(key)
    return int(value) if isinstance(value, int) and value >= 0 else max(0, int(default))


def _latency_ms(started: float) -> int:
    return max(0, int((time.perf_counter() - started) * 1_000))


def _bounded_int(value: Any, minimum: int, maximum: int, label: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"AI {label} must be an integer") from exc
    if not minimum <= parsed <= maximum:
        raise ValueError(f"AI {label} must be between {minimum} and {maximum}")
    return parsed
