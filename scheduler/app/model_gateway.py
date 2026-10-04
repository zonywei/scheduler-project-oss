# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import ipaddress
import os
import re
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Iterable, Protocol
from urllib.parse import urlparse


_ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_MAX_PROMPT_CHARS = 20_000
_MAX_INPUT_CHARS = 64_000
_MAX_RESPONSE_BYTES = 2 * 1024 * 1024
_WIRE_API_ALIASES = {
    "chat": "chat_completions",
    "chat_completion": "chat_completions",
    "chat_completions": "chat_completions",
    "responses": "responses",
    "response": "responses",
}
_REASONING_EFFORTS = {"", "minimal", "low", "medium", "high", "xhigh"}
_USER_AGENT = "CourseOrderAI/1.0"


class ModelGatewayError(RuntimeError):
    """A provider failed without exposing credentials or raw transport details."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "provider_request_failed",
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = str(code or "provider_request_failed")
        self.status_code = status_code


@dataclass(frozen=True)
class ModelProviderConfig:
    provider_id: str
    base_url: str
    model: str
    api_key_env: str = ""
    timeout_seconds: float = 30.0
    max_completion_tokens: int = 2_048
    wire_api: str = "chat_completions"
    reasoning_effort: str = ""
    disable_response_storage: bool = True

    @classmethod
    def from_settings(cls, settings: dict[str, Any]) -> "ModelProviderConfig":
        provider_id = str(settings.get("provider_name") or "openai-compatible").strip()
        base_url = str(settings.get("base_url") or "").strip().rstrip("/")
        model = str(settings.get("model") or "").strip()
        api_key_env = str(settings.get("api_key_env") or "").strip()
        raw_wire_api = str(settings.get("wire_api") or "chat_completions").strip().lower().replace("-", "_")
        wire_api = _WIRE_API_ALIASES.get(raw_wire_api, raw_wire_api)
        reasoning_effort = str(settings.get("reasoning_effort") or "").strip().lower()
        disable_response_storage = _setting_bool(
            settings.get("disable_response_storage"),
            default=True,
            label="disable_response_storage",
        )
        try:
            timeout_seconds = float(settings.get("timeout_seconds") or 30)
        except (TypeError, ValueError) as exc:
            raise ValueError("AI provider timeout_seconds must be numeric") from exc
        try:
            max_completion_tokens = int(settings.get("max_completion_tokens") or 2_048)
        except (TypeError, ValueError) as exc:
            raise ValueError("AI provider max_completion_tokens must be an integer") from exc

        config = cls(
            provider_id=provider_id,
            base_url=base_url,
            model=model,
            api_key_env=api_key_env,
            timeout_seconds=timeout_seconds,
            max_completion_tokens=max_completion_tokens,
            wire_api=wire_api,
            reasoning_effort=reasoning_effort,
            disable_response_storage=disable_response_storage,
        )
        config.validate()
        return config

    def validate(self) -> None:
        if not self.provider_id or len(self.provider_id) > 80:
            raise ValueError("AI provider_name is required and must be at most 80 characters")
        if not self.model or len(self.model) > 160:
            raise ValueError("AI model is required and must be at most 160 characters")
        if self.api_key_env and not _ENV_NAME_RE.fullmatch(self.api_key_env):
            raise ValueError("AI api_key_env must be a valid environment variable name")
        if not 1 <= float(self.timeout_seconds) <= 120:
            raise ValueError("AI timeout_seconds must be between 1 and 120")
        if not 128 <= int(self.max_completion_tokens) <= 8_192:
            raise ValueError("AI max_completion_tokens must be between 128 and 8192")
        if self.wire_api not in set(_WIRE_API_ALIASES.values()):
            raise ValueError("AI wire_api must be chat_completions or responses")
        if self.reasoning_effort not in _REASONING_EFFORTS:
            raise ValueError("AI reasoning_effort must be minimal, low, medium, high, or xhigh")

        parsed = urlparse(self.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("AI base_url must be an absolute HTTP(S) URL")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("AI base_url must not contain credentials, query parameters, or fragments")
        if parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError("non-local AI providers must use HTTPS")


@dataclass(frozen=True)
class JsonModelResult:
    value: dict[str, Any]
    provider_id: str
    model: str
    request_id: str = ""
    usage: dict[str, int] | None = None


class JsonModelClient(Protocol):
    def complete_json(self, *, system_prompt: str, user_payload: dict[str, Any]) -> JsonModelResult:
        ...


def pseudonymize_teacher_context(
    text: str,
    known_teachers: Iterable[str],
) -> tuple[str, list[str], dict[str, str]]:
    """Replace locally known teacher names before a payload crosses the model boundary.

    Returns the redacted text, aliases mentioned by the source text, and an
    alias-to-original map for the complete caller-provided teacher context.
    The complete map is intentional: a model may refer to a second teacher
    while explaining a conflict even when that teacher was not named in the
    original sentence.  The second return value keeps its historical meaning
    for callers that only want aliases mentioned by the source.
    """
    source = str(text or "")
    teachers = sorted(
        {
            str(value).strip()
            for value in known_teachers
            if str(value).strip() and len(str(value).strip()) <= 100
        },
        key=lambda value: (-len(value), value),
    )
    teacher_to_alias = {
        teacher: f"教师代号_{index:03d}"
        for index, teacher in enumerate(teachers, start=1)
    }
    mentioned_aliases = [
        teacher_to_alias[teacher]
        for teacher in teachers
        if teacher in source
    ]
    redacted = replace_model_tokens(source, teacher_to_alias)
    return redacted, mentioned_aliases, {
        alias: teacher for teacher, alias in teacher_to_alias.items()
    }


def replace_model_tokens(value: Any, replacements: dict[str, str]) -> Any:
    """Recursively replace text tokens in JSON-compatible model data."""
    if isinstance(value, str):
        result = value
        for source, target in sorted(
            replacements.items(),
            key=lambda item: (-len(item[0]), item[0]),
        ):
            if source:
                result = result.replace(source, target)
        return result
    if isinstance(value, list):
        return [replace_model_tokens(item, replacements) for item in value]
    if isinstance(value, tuple):
        return tuple(replace_model_tokens(item, replacements) for item in value)
    if isinstance(value, dict):
        return {
            replace_model_tokens(key, replacements) if isinstance(key, str) else key:
            replace_model_tokens(item, replacements)
            for key, item in value.items()
        }
    return value


class OpenAICompatibleJsonClient:
    """Minimal server-side adapter for domestic OpenAI-compatible chat APIs."""

    def __init__(self, config: ModelProviderConfig) -> None:
        config.validate()
        self._config = config

    def complete_json(self, *, system_prompt: str, user_payload: dict[str, Any]) -> JsonModelResult:
        prompt = str(system_prompt or "").strip()
        if not prompt or len(prompt) > _MAX_PROMPT_CHARS:
            raise ValueError(f"system prompt must contain 1-{_MAX_PROMPT_CHARS} characters")
        serialized_input = json.dumps(user_payload, ensure_ascii=False)
        if len(serialized_input) > _MAX_INPUT_CHARS:
            raise ValueError(f"model input exceeds {_MAX_INPUT_CHARS} characters")
        _assert_provider_destination(self._config)

        api_key = os.environ.get(self._config.api_key_env, "") if self._config.api_key_env else ""
        if self._config.api_key_env and not api_key:
            raise ModelGatewayError(
                "AI 服务密钥尚未配置到服务器环境变量",
                code="provider_credential_missing",
            )
        if self._config.wire_api == "responses":
            endpoint = f"{self._config.base_url}/responses"
            body: dict[str, Any] = {
                "model": self._config.model,
                "instructions": prompt,
                "input": serialized_input,
                "max_output_tokens": self._config.max_completion_tokens,
                "store": not self._config.disable_response_storage,
                "stream": True,
            }
            if self._config.reasoning_effort:
                body["reasoning"] = {"effort": self._config.reasoning_effort}
            accept = "text/event-stream, application/json"
        else:
            endpoint = f"{self._config.base_url}/chat/completions"
            body = {
                "model": self._config.model,
                "messages": [
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": serialized_input},
                ],
                "temperature": 0,
                "max_tokens": self._config.max_completion_tokens,
            }
            accept = "application/json"
        request = urllib.request.Request(
            endpoint,
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Accept": accept,
                "User-Agent": _USER_AGENT,
                **({"Authorization": f"Bearer {api_key}"} if api_key else {}),
            },
            method="POST",
        )

        try:
            opener = urllib.request.build_opener(_RejectRedirects())
            with opener.open(request, timeout=self._config.timeout_seconds) as response:
                raw = response.read(_MAX_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as exc:
            message, code = _http_error_summary(exc.code)
            raise ModelGatewayError(message, code=code, status_code=exc.code) from exc
        except TimeoutError as exc:
            raise ModelGatewayError("AI 服务请求超时", code="provider_timeout") from exc
        except (urllib.error.URLError, OSError) as exc:
            raise ModelGatewayError("无法连接 AI 服务", code="provider_unreachable") from exc
        if len(raw) > _MAX_RESPONSE_BYTES:
            raise ModelGatewayError("AI 服务响应过大", code="provider_response_too_large")

        try:
            if self._config.wire_api == "responses":
                payload, content = _decode_responses_api(raw)
            else:
                payload = json.loads(raw.decode("utf-8"))
                content = str(payload["choices"][0]["message"]["content"]).strip()
            value = _decode_json_object(content)
        except (KeyError, IndexError, TypeError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            raise ModelGatewayError(
                "AI 服务没有返回有效的 JSON 规则",
                code="provider_invalid_response",
            ) from exc

        return JsonModelResult(
            value=value,
            provider_id=self._config.provider_id,
            model=str(payload.get("model") or self._config.model),
            request_id=str(payload.get("id") or ""),
            usage=_normalize_usage(payload.get("usage")),
        )


class _RejectRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> None:
        return None


def _assert_provider_destination(config: ModelProviderConfig) -> None:
    parsed = urlparse(config.base_url)
    host = str(parsed.hostname or "").strip().lower()
    allowlist = {
        item.strip().lower()
        for item in str(os.environ.get("SCHEDULER_AI_ALLOWED_HOSTS") or "").split(",")
        if item.strip()
    }
    if allowlist and host not in allowlist:
        raise ModelGatewayError("AI provider host is not in SCHEDULER_AI_ALLOWED_HOSTS")
    if host in allowlist or not _env_bool("SCHEDULER_AI_ENFORCE_PUBLIC_NETWORK", False):
        return
    try:
        addresses = {ipaddress.ip_address(host)}
    except ValueError:
        try:
            addresses = {
                ipaddress.ip_address(str(item[4][0]).split("%", 1)[0])
                for item in socket.getaddrinfo(host, parsed.port or 443, type=socket.SOCK_STREAM)
            }
        except (OSError, ValueError) as exc:
            raise ModelGatewayError("AI provider host could not be resolved safely") from exc
    if not addresses or any(not address.is_global for address in addresses):
        raise ModelGatewayError("AI provider resolves to a non-public network address")


def _env_bool(name: str, default: bool) -> bool:
    value = str(os.environ.get(name) or ("true" if default else "false")).strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be true or false")


def _decode_json_object(content: str) -> dict[str, Any]:
    value = str(content or "").strip()
    if value.startswith("```"):
        value = re.sub(r"^```(?:json)?\s*", "", value, flags=re.IGNORECASE)
        value = re.sub(r"\s*```$", "", value)
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise ValueError("model output must be a JSON object")
    return parsed


def _decode_responses_api(raw: bytes) -> tuple[dict[str, Any], str]:
    text = raw.decode("utf-8").strip()
    if not text:
        raise ValueError("empty Responses API payload")
    lines = text.splitlines()
    is_event_stream = any(line.strip().startswith("data:") for line in lines)
    if not is_event_stream:
        payload = json.loads(text)
        if not isinstance(payload, dict):
            raise ValueError("Responses API payload must be an object")
        return payload, _responses_output_text(payload)

    response_payload: dict[str, Any] = {}
    deltas: list[str] = []
    for raw_line in lines:
        line = raw_line.strip()
        if not line.startswith("data:"):
            continue
        event_data = line[5:].strip()
        if not event_data or event_data == "[DONE]":
            continue
        event = json.loads(event_data)
        if not isinstance(event, dict):
            continue
        event_type = str(event.get("type") or "")
        if event_type == "response.output_text.delta" and isinstance(event.get("delta"), str):
            deltas.append(str(event["delta"]))
        elif event_type in {"response.created", "response.completed"} and isinstance(event.get("response"), dict):
            response_payload = dict(event["response"])
        elif event_type in {"error", "response.failed", "response.incomplete"}:
            raise ValueError("Responses API reported a failed response")
    content = "".join(deltas).strip() or _responses_output_text(response_payload)
    if not response_payload:
        response_payload = {"object": "response", "output_text": content}
    return response_payload, content


def _responses_output_text(payload: dict[str, Any]) -> str:
    direct = payload.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()
    parts: list[str] = []
    for item in payload.get("output") if isinstance(payload.get("output"), list) else []:
        if not isinstance(item, dict):
            continue
        content = item.get("content") if isinstance(item.get("content"), list) else []
        for part in content:
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                parts.append(str(part["text"]))
    if not parts:
        raise ValueError("Responses API output text is missing")
    return "".join(parts).strip()


def _http_error_summary(status_code: int) -> tuple[str, str]:
    if status_code in {401, 403}:
        return "AI 服务拒绝了当前密钥，请检查或轮换密钥", "provider_auth_failed"
    if status_code == 429:
        return "AI 服务额度不足或请求过于频繁", "provider_rate_limited"
    if status_code >= 500:
        return "AI 服务上游暂时不可用", "provider_unavailable"
    return "AI 服务请求未被接受", "provider_request_failed"


def _setting_bool(value: Any, *, default: bool, label: str) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"AI {label} must be true or false")


def _normalize_usage(value: Any) -> dict[str, int] | None:
    if not isinstance(value, dict):
        return None
    usage: dict[str, int] = {}
    aliases = {
        "prompt_tokens": ("prompt_tokens", "input_tokens"),
        "completion_tokens": ("completion_tokens", "output_tokens"),
        "total_tokens": ("total_tokens",),
    }
    for key, candidates in aliases.items():
        raw = next((value.get(candidate) for candidate in candidates if value.get(candidate) is not None), None)
        if isinstance(raw, int) and raw >= 0:
            usage[key] = raw
    if "total_tokens" not in usage and {"prompt_tokens", "completion_tokens"} <= set(usage):
        usage["total_tokens"] = usage["prompt_tokens"] + usage["completion_tokens"]
    return usage or None
