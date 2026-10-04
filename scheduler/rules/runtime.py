# -*- coding: utf-8 -*-
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, replace
from datetime import datetime
from typing import Any, Callable

from ai_orchestrated_optimization import (
    ai_or_model_rule_context,
    build_agent_migration_task_plan,
    build_legacy_rule_migration_backlog,
    get_existing_cp_model_operation_count,
    get_existing_cp_model_operation_trace,
)
from scheduler.rules.defaults import build_default_rule_registry, get_module_rule_bindings
from scheduler.rules.registry import RuleRegistry, resolve_effective_rule
from scheduler.rules.spec import RuleSpec


_RULE_RUNTIME_CTX: ContextVar[dict[str, Any] | None] = ContextVar(
    "rule_runtime_context",
    default=None,
)

_WRAPPED_MARK = "__rule_runtime_wrapped__"


def _now_ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _ensure_rule_spec_with_callable(
    registry: RuleRegistry,
    rule_id: str,
    fn: Callable[..., Any],
) -> None:
    spec = registry.get(rule_id)
    if spec is None:
        return
    if spec.apply_fn is fn:
        return
    registry.register(replace(spec, apply_fn=fn), overwrite=True)


@contextmanager
def rule_runtime_context(
    *,
    mode: str,
    run_id: str,
    effective_cfg: dict[str, Any],
    registry: RuleRegistry | None = None,
    trace: list[dict[str, Any]] | None = None,
) -> Any:
    payload = {
        "mode": str(mode),
        "run_id": str(run_id or ""),
        "effective_cfg": dict(effective_cfg or {}),
        "registry": registry or build_default_rule_registry(),
        "trace": trace if trace is not None else [],
    }
    token = _RULE_RUNTIME_CTX.set(payload)
    try:
        yield payload
    finally:
        _RULE_RUNTIME_CTX.reset(token)


def current_rule_trace() -> list[dict[str, Any]]:
    payload = _RULE_RUNTIME_CTX.get()
    if not payload:
        return []
    trace = payload.get("trace")
    return trace if isinstance(trace, list) else []


def _make_rule_wrapper(
    *,
    rule_id: str,
    fn_name: str,
    fn: Callable[..., Any],
) -> Callable[..., Any]:
    def _wrapped(*args: Any, **kwargs: Any) -> Any:
        payload = _RULE_RUNTIME_CTX.get()
        if not payload:
            return fn(*args, **kwargs)
        registry: RuleRegistry = payload["registry"]
        effective_cfg: dict[str, Any] = payload["effective_cfg"]
        trace: list[dict[str, Any]] = payload["trace"]
        mode = payload.get("mode", "")
        run_id = payload.get("run_id", "")

        _ensure_rule_spec_with_callable(registry, rule_id, fn)
        spec = registry.get(rule_id)
        if spec is None:
            return fn(*args, **kwargs)
        state = resolve_effective_rule(spec, effective_cfg)
        # Audit-only: record the resolved enabled/mode/weight state, but keep
        # the existing explicit solver call path as the source of execution.
        event = {
            "timestamp": _now_ts(),
            "mode": mode,
            "run_id": run_id,
            "rule_id": state.rule_id,
            "name": state.name,
            "stage": state.stage,
            "order": state.order,
            "enabled": state.enabled,
            "rule_mode": state.mode,
            "weight": state.weight,
            "callable": fn_name,
            "status": "ok",
        }
        model_counts_before = _model_operation_counts(args, kwargs)
        try:
            with ai_or_model_rule_context(
                state.rule_id,
                role_id="scheduler_rule_runtime",
                source=f"scheduler.rules.runtime:{fn_name}",
                metadata={"mode": mode, "run_id": run_id, "stage": state.stage},
            ):
                return fn(*args, **kwargs)
        except Exception as exc:
            event["status"] = "error"
            event["error"] = str(exc)
            raise
        finally:
            if model_counts_before:
                model_counts_after = _model_operation_counts(args, kwargs)
                event["ai_or_operation_count"] = sum(model_counts_after.values())
                event["ai_or_operation_delta"] = sum(
                    model_counts_after.get(key, 0) - before
                    for key, before in model_counts_before.items()
                )
                operations_by_type = _model_operation_deltas_by_type(args, kwargs, model_counts_before)
                if operations_by_type:
                    event["ai_or_operations_by_type"] = operations_by_type
            trace.append(event)

    setattr(_wrapped, _WRAPPED_MARK, True)
    setattr(_wrapped, "__name__", getattr(fn, "__name__", fn_name))
    setattr(_wrapped, "__doc__", getattr(fn, "__doc__", ""))
    return _wrapped


def _model_operation_counts(args: tuple[Any, ...], kwargs: dict[str, Any]) -> dict[int, int]:
    counts: dict[int, int] = {}
    for model_id, value in _ai_or_models(args, kwargs).items():
        counts[model_id] = get_existing_cp_model_operation_count(value)
    return counts


def _model_operation_deltas_by_type(
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    before_counts: dict[int, int],
) -> dict[str, int]:
    operations: dict[str, int] = {}
    for model_id, value in _ai_or_models(args, kwargs).items():
        if model_id not in before_counts:
            continue
        trace = get_existing_cp_model_operation_trace(value)
        for item in trace[before_counts[model_id]:]:
            operation = str(item.operation or "").strip()
            if not operation:
                continue
            operations[operation] = int(operations.get(operation, 0)) + 1
    return {operation: operations[operation] for operation in sorted(operations)}


def _ai_or_models(args: tuple[Any, ...], kwargs: dict[str, Any]) -> dict[int, Any]:
    models: dict[int, Any] = {}
    for value in tuple(args) + tuple(kwargs.values()):
        if not hasattr(value, "ai_or_model_factory"):
            continue
        models[id(value)] = value
    return models


def bind_rule_wrappers_for_module(
    module_name: str,
    namespace: dict[str, Any],
    *,
    registry: RuleRegistry | None = None,
) -> None:
    reg = registry or build_default_rule_registry()
    bindings = get_module_rule_bindings(module_name)
    if not bindings:
        return
    for binding in bindings:
        symbol = str(binding.symbol)
        fn = namespace.get(symbol)
        if not callable(fn):
            continue
        if getattr(fn, _WRAPPED_MARK, False):
            continue
        spec = reg.get(binding.rule_id)
        if spec is not None:
            patched = replace(
                spec,
                stage=binding.stage,
                order=int(binding.order),
                apply_fn=fn,
            )
            reg.register(patched, overwrite=True)
        namespace[symbol] = _make_rule_wrapper(
            rule_id=binding.rule_id,
            fn_name=symbol,
            fn=fn,
        )


def runtime_rules_snapshot_payload(
    *,
    mode: str,
    run_id: str,
    git_commit: str | None,
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "timestamp": _now_ts(),
        "mode": str(mode),
        "run_id": str(run_id or ""),
        "git_commit": git_commit,
        "rules": rows,
    }


def runtime_trace_payload(
    *,
    mode: str,
    run_id: str,
    git_commit: str | None,
    trace: list[dict[str, Any]],
    generic_rule_ids: tuple[str, ...] = (),
) -> dict[str, Any]:
    operation_summary = _runtime_trace_operation_summary(trace)
    migration_backlog = _runtime_trace_migration_backlog(
        operation_summary,
        generic_rule_ids=generic_rule_ids,
    )
    return {
        "timestamp": _now_ts(),
        "mode": str(mode),
        "run_id": str(run_id or ""),
        "git_commit": git_commit,
        "ai_or_operation_summary": operation_summary,
        "ai_or_migration_backlog": migration_backlog,
        "ai_or_agent_migration_plan": _runtime_trace_agent_migration_plan(migration_backlog),
        "trace": [dict(x) for x in trace],
    }


def _runtime_trace_operation_summary(trace: list[dict[str, Any]]) -> dict[str, Any]:
    total = 0
    rules: dict[str, dict[str, Any]] = {}
    for item in trace:
        rule_id = str(item.get("rule_id") or "__unscoped__").strip() or "__unscoped__"
        try:
            delta = int(item.get("ai_or_operation_delta") or 0)
        except (TypeError, ValueError):
            delta = 0
        if delta <= 0:
            continue
        total += delta
        row = rules.setdefault(rule_id, {"operation_delta": 0, "call_count": 0, "operations": {}})
        row["operation_delta"] += delta
        row["call_count"] += 1
        operations = row["operations"]
        for operation, count in _coerce_operation_counts(item.get("ai_or_operations_by_type")).items():
            operations[operation] = int(operations.get(operation, 0)) + count
    return {
        "total_operation_delta": total,
        "rules": {
            rule_id: {
                "operation_delta": int(rules[rule_id]["operation_delta"]),
                "call_count": int(rules[rule_id]["call_count"]),
                "operations": dict(sorted(rules[rule_id]["operations"].items())),
            }
            for rule_id in sorted(rules)
        },
    }


def _coerce_operation_counts(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    operations: dict[str, int] = {}
    for raw_operation, raw_count in value.items():
        operation = str(raw_operation or "").strip()
        if not operation:
            continue
        try:
            count = int(raw_count or 0)
        except (TypeError, ValueError):
            continue
        if count <= 0:
            continue
        operations[operation] = operations.get(operation, 0) + count
    return {operation: operations[operation] for operation in sorted(operations)}


def _runtime_trace_migration_backlog(
    operation_summary: dict[str, Any],
    *,
    generic_rule_ids: tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    rule_summaries = {
        rule_id: {
            "operation_count": int(row.get("operation_delta") or 0),
            "operations": dict(row.get("operations") or {}),
        }
        for rule_id, row in (operation_summary.get("rules") or {}).items()
    }
    return [
        asdict(item)
        for item in build_legacy_rule_migration_backlog(
            rule_summaries,
            generic_rule_ids=generic_rule_ids,
        )
    ]


def _runtime_trace_agent_migration_plan(migration_backlog: list[dict[str, Any]]) -> list[dict[str, Any]]:
    backlog_items = [
        build_legacy_rule_migration_backlog(
            {
                str(item.get("rule_id") or "__unscoped__"): {
                    "operation_count": int(item.get("operation_count") or 0),
                    "operations": {operation: 1 for operation in item.get("operation_types") or ()},
                }
            },
            generic_rule_ids=(str(item.get("rule_id")),)
            if item.get("generic_contract_status") == "covered_by_generic_contract"
            else (),
        )[0]
        for item in migration_backlog
    ]
    return [asdict(item) for item in build_agent_migration_task_plan(tuple(backlog_items))]
