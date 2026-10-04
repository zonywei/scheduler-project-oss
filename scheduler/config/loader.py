# -*- coding: utf-8 -*-
from __future__ import annotations

import copy
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from scheduler.domain.rule_drafts import materialize_active_rule_drafts
from scheduler.platform.runtime import load_runtime_workspace, uses_sqlite_workspace

_RUNTIME_CONFIG_OVERRIDE: ContextVar[dict[str, Any] | None] = ContextVar(
    "runtime_config_override",
    default=None,
)

_DEFAULT_ONLY_IO_RULE_PATHS = (
    ("day", "weekend_constraints"),
    ("day", "weekday_constraints"),
    ("day", "pe_tech_constraints"),
    ("day", "head_duty_constraints"),
    ("day", "noon_dorm_duty"),
    ("day", "duty_joint_constraints"),
    ("day", "grade_group_duty"),
    ("day_night_link",),
    ("personalized_constraints",),
)

_DEFAULT_ONLY_RULE_PATHS = (
    ("hard_bans",),
    ("checkin",),
    ("soft",),
    ("evening_constraints",),
    ("day_constraints",),
    ("day_night_link",),
    ("personalized_constraints",),
)


@dataclass(frozen=True)
class EffectiveConfig:
    mode: str
    io_path: Path
    rules_path: Path
    io_cfg: dict[str, Any]
    rules_cfg: dict[str, Any]
    effective_cfg: dict[str, Any]
    config_diff_text: str


def load_yaml_config(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    with p.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data if isinstance(data, dict) else {}


def _load_yaml(path: str | Path) -> dict[str, Any]:
    return load_yaml_config(path)


def _merge_section_values(
    io_cfg: dict[str, Any] | None,
    rules_cfg: dict[str, Any] | None,
    section: str,
) -> dict[str, Any]:
    io_part = ((io_cfg or {}).get(section, {}) or {})
    rules_part = ((rules_cfg or {}).get(section, {}) or {})
    merged = dict(io_part)
    merged.update(dict(rules_part))
    return merged


def _as_path(value: Any) -> Path | None:
    if value is None:
        return None
    p = Path(str(value))
    return p


def _resolve_paths(mode: str, config_paths: dict[str, Any] | None = None) -> tuple[Path, Path]:
    cfg = config_paths or {}
    io_path = _as_path(cfg.get("io_path"))
    rules_path = _as_path(cfg.get("rules_path"))
    project_root = _as_path(cfg.get("project_root"))

    if io_path is None:
        if rules_path is not None:
            io_path = rules_path.with_name("io.yaml")
        elif project_root is not None:
            cand1 = (project_root / "scheduler" / "config" / "io.yaml").resolve()
            cand2 = (project_root / "config" / "io.yaml").resolve()
            io_path = cand1 if cand1.exists() else cand2
        else:
            io_path = Path("scheduler/config/io.yaml")

    if rules_path is None:
        rules_path = io_path.with_name("rules.yaml")

    if not io_path.is_absolute():
        io_path = io_path.resolve()
    if not rules_path.is_absolute():
        rules_path = rules_path.resolve()

    if not io_path.exists():
        raise FileNotFoundError(f"io.yaml not found: {io_path}")
    if not rules_path.exists():
        # 与既有行为对齐：允许 rules 缺失，按空配置处理
        rules_path = rules_path

    return io_path, rules_path


def _deep_merge(base: Any, override: Any) -> Any:
    if isinstance(base, dict) and isinstance(override, dict):
        out: dict[str, Any] = {}
        keys = set(base.keys()) | set(override.keys())
        for key in keys:
            if key in base and key in override:
                out[key] = _deep_merge(base[key], override[key])
            elif key in override:
                out[key] = override[key]
            else:
                out[key] = base[key]
        return out
    return override if override is not None else base


def _apply_runtime_overrides(io_cfg: dict[str, Any], rules_cfg: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    payload = _RUNTIME_CONFIG_OVERRIDE.get()
    if not payload:
        return io_cfg, rules_cfg
    io_override = payload.get("io_cfg")
    rules_override = payload.get("rules_cfg")
    io_new = _deep_merge(io_cfg, io_override) if isinstance(io_override, dict) else io_cfg
    rules_new = _deep_merge(rules_cfg, rules_override) if isinstance(rules_override, dict) else rules_cfg
    return io_new, rules_new


def _apply_default_only_rule_policy(
    io_cfg: dict[str, Any],
    rules_cfg: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Disable every school-specific legacy rule when the product reset flag is active.

    The structural timetable constraints are implemented outside these optional
    sections and remain active.  This keeps a reset reversible without editing
    the repository's legacy YAML defaults.
    """
    product = rules_cfg.get("product_rules") if isinstance(rules_cfg.get("product_rules"), dict) else {}
    if product.get("defaults_only") is not True:
        return io_cfg, rules_cfg
    io_new = copy.deepcopy(io_cfg)
    rules_new = copy.deepcopy(rules_cfg)
    for path in _DEFAULT_ONLY_IO_RULE_PATHS:
        _disable_feature_flags_at_path(io_new, path)
    for path in _DEFAULT_ONLY_RULE_PATHS:
        _disable_feature_flags_at_path(rules_new, path)
    rules_new.setdefault("global_binding", {})["enable_8_chem_9_bio"] = False
    return io_new, rules_new


def _disable_feature_flags_at_path(root: dict[str, Any], path: tuple[str, ...]) -> None:
    node: Any = root
    for key in path:
        if not isinstance(node, dict) or key not in node:
            return
        node = node[key]
    _disable_feature_flags(node)


def _disable_feature_flags(value: Any) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "enabled" or key.startswith("enable_"):
                value[key] = False
            else:
                _disable_feature_flags(item)
    elif isinstance(value, list):
        for item in value:
            _disable_feature_flags(item)


def _load_web_overrides(io_path: Path) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Load optional Web UI overrides without changing the Excel/YAML base files."""
    if uses_sqlite_workspace():
        workspace = load_runtime_workspace()
        raw = workspace.payload if workspace is not None else {}
    else:
        overrides_path = io_path.with_name("web_overrides.yaml")
        if not overrides_path.exists():
            return None, None
        raw = _load_yaml(overrides_path)
    if not isinstance(raw, dict):
        return None, None
    io_override = raw.get("io")
    rules_override = raw.get("rules")
    if "temporary_rules" in raw:
        rules_override = dict(rules_override or {})
        rules_override["temporary_rules"] = raw.get("temporary_rules")
    return (
        io_override if isinstance(io_override, dict) else None,
        rules_override if isinstance(rules_override, dict) else None,
    )


@contextmanager
def runtime_config_overrides(
    *,
    io_cfg: dict[str, Any] | None = None,
    rules_cfg: dict[str, Any] | None = None,
):
    payload: dict[str, Any] = {}
    if isinstance(io_cfg, dict):
        payload["io_cfg"] = copy.deepcopy(io_cfg)
    if isinstance(rules_cfg, dict):
        payload["rules_cfg"] = copy.deepcopy(rules_cfg)
    token = _RUNTIME_CONFIG_OVERRIDE.set(payload or None)
    try:
        yield
    finally:
        _RUNTIME_CONFIG_OVERRIDE.reset(token)


def build_runtime_solver_overrides(
    *,
    time_limit_seconds: int | None = None,
    seed: int | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    io_override: dict[str, Any] = {}
    rules_override: dict[str, Any] = {}

    if time_limit_seconds is not None:
        io_override["joint_solve"] = {"time_limit_seconds": int(time_limit_seconds)}
        rules_override["solve"] = {"time_limit_seconds": int(time_limit_seconds)}

    if seed is not None:
        io_joint = dict(io_override.get("joint_solve", {}) or {})
        io_joint["random_seed"] = int(seed)
        io_override["joint_solve"] = io_joint

        rules_solve = dict(rules_override.get("solve", {}) or {})
        rules_solve["random_seed"] = int(seed)
        rules_override["solve"] = rules_solve

    return io_override, rules_override


@contextmanager
def runtime_solver_overrides(
    *,
    time_limit_seconds: int | None = None,
    seed: int | None = None,
):
    io_override, rules_override = build_runtime_solver_overrides(
        time_limit_seconds=time_limit_seconds,
        seed=seed,
    )
    with runtime_config_overrides(
        io_cfg=io_override or None,
        rules_cfg=rules_override or None,
    ):
        yield


def _diff_lines(io_cfg: Any, rules_cfg: Any, prefix: str = "") -> list[str]:
    lines: list[str] = []
    if isinstance(io_cfg, dict) and isinstance(rules_cfg, dict):
        keys = sorted(set(io_cfg.keys()) | set(rules_cfg.keys()), key=lambda x: str(x))
        for key in keys:
            path = f"{prefix}.{key}" if prefix else str(key)
            has_io = key in io_cfg
            has_rules = key in rules_cfg
            if has_io and has_rules:
                lines.extend(_diff_lines(io_cfg[key], rules_cfg[key], path))
            elif has_rules:
                lines.append(f"+ {path}: rules_only={rules_cfg[key]!r}")
            else:
                lines.append(f"= {path}: io_only={io_cfg[key]!r}")
        return lines

    if io_cfg != rules_cfg:
        lines.append(f"~ {prefix}: io={io_cfg!r} | rules={rules_cfg!r}")
    return lines


def load_effective_config(mode: str, config_paths: dict[str, Any] | None = None) -> EffectiveConfig:
    io_path, rules_path = _resolve_paths(mode, config_paths)
    io_cfg = _load_yaml(io_path)
    rules_cfg = _load_yaml(rules_path) if rules_path.exists() else {}
    web_io_override, web_rules_override = _load_web_overrides(io_path)
    if web_io_override:
        io_cfg = _deep_merge(io_cfg, web_io_override)
    if web_rules_override:
        rules_cfg = _deep_merge(rules_cfg, web_rules_override)
        rules_cfg = materialize_active_rule_drafts(rules_cfg)
    io_cfg, rules_cfg = _apply_default_only_rule_policy(io_cfg, rules_cfg)
    io_cfg, rules_cfg = _apply_runtime_overrides(io_cfg, rules_cfg)
    effective_cfg = _deep_merge(io_cfg, rules_cfg)
    diff = _diff_lines(io_cfg, rules_cfg)
    diff_text = "\n".join(diff) if diff else "NO_DIFF"
    return EffectiveConfig(
        mode=str(mode),
        io_path=io_path,
        rules_path=rules_path,
        io_cfg=io_cfg,
        rules_cfg=rules_cfg,
        effective_cfg=effective_cfg,
        config_diff_text=diff_text,
    )


def merge_section(
    effective_or_io: EffectiveConfig | dict[str, Any] | None,
    rules_or_section: dict[str, Any] | str | None,
    section: str | None = None,
) -> dict[str, Any]:
    """兼容两种调用：
    1) merge_section(effective, "section")
    2) merge_section(io_cfg, rules_cfg, "section")
    """
    if isinstance(effective_or_io, EffectiveConfig):
        sec = str(rules_or_section or "").strip()
        return _merge_section_values(effective_or_io.io_cfg, effective_or_io.rules_cfg, sec)
    if section is None:
        raise TypeError("merge_section(io_cfg, rules_cfg, section) requires section")
    io_cfg = effective_or_io if isinstance(effective_or_io, dict) else {}
    rules_cfg = rules_or_section if isinstance(rules_or_section, dict) else {}
    return _merge_section_values(io_cfg, rules_cfg, str(section))


def write_effective_config_meta(target_dir: Path, effective: EffectiveConfig) -> tuple[Path, Path]:
    target_dir.mkdir(parents=True, exist_ok=True)
    effective_path = target_dir / "effective_config.yaml"
    diff_path = target_dir / "config_diff.txt"
    effective_path.write_text(
        yaml.safe_dump(effective.effective_cfg, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    diff_path.write_text(effective.config_diff_text, encoding="utf-8")
    return effective_path, diff_path
