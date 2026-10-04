"""统一运行入口。

功能：
- 支持白天、晚自习、串行、联合四种模式
- 统一读取 io.yaml 与 rules.yaml
- 负责日志开关与参数解析
"""



# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import copy
from contextlib import nullcontext
import logging
import os
import sys
from pathlib import Path

import yaml

from scheduler.config.loader import (
    build_runtime_solver_overrides,
    runtime_config_overrides,
)
from scheduler.app.service import run as run_service

logger = logging.getLogger(__name__)


def _positive_int(raw: str) -> int:
    value = int(raw)
    if value <= 0:
        raise argparse.ArgumentTypeError("time limit must be a positive integer")
    return value


def _non_negative_int(raw: str) -> int:
    value = int(raw)
    if value < 0:
        raise argparse.ArgumentTypeError("seed must be a non-negative integer")
    return value


def _parse_args():
    """解析命令行参数。"""
    p = argparse.ArgumentParser(description="统一入口：白天/晚自习排课与导出")
    p.add_argument(
        "--mode",
        choices=["day", "night", "both", "joint"],
        default="both",
        help="运行模式：day=白天，night=晚自习，both=串行，joint=联合求解",
    )
    p.add_argument(
        "--config",
        default=str(Path("scheduler") / "config" / "io.yaml"),
        help="配置文件路径（用于白天与晚自习读取路径）",
    )
    p.add_argument(
        "--grade",
        default="高二",
        help="班级课表年级前缀（仅白天导出使用）",
    )
    p.add_argument(
        "--verbose",
        action="store_true",
        help="输出详细日志",
    )
    p.add_argument(
        "--time-limit-seconds",
        "--time-limit",
        dest="time_limit_seconds",
        type=_positive_int,
        default=None,
        help="可选：覆盖本次运行的 time_limit_seconds（默认不覆盖）",
    )
    p.add_argument(
        "--seed",
        dest="seed",
        type=_non_negative_int,
        default=None,
        help="可选：覆盖本次运行的求解随机种子（默认不覆盖）",
    )
    p.add_argument(
        "--overrides",
        "--profile",
        dest="overrides_path",
        default=None,
        help="可选：覆盖配置 YAML 路径（支持 io/rules 分区，不修改默认配置文件）",
    )
    return p.parse_args()


def _setup_logging(verbose: bool) -> None:
    """根据 --verbose 设置日志级别。"""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="[%(levelname)s] %(message)s")
    # Keep project debug logs while suppressing Pillow PNG chunk noise
    # (e.g., "STREAM b'IHDR' ...") when verbose mode is enabled.
    logging.getLogger("PIL").setLevel(logging.INFO)
    logging.getLogger("PIL.PngImagePlugin").setLevel(logging.INFO)


def _setup_console_utf8() -> None:
    """在 Windows 控制台优先使用 UTF-8，降低中文日志乱码概率。"""
    if os.name != "nt":
        return
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def _apply_solver_overrides(
    io_cfg: dict,
    rules_cfg: dict,
    *,
    time_limit_seconds: int | None = None,
    seed: int | None = None,
) -> tuple[dict, dict]:
    """Return copied configs with optional solver overrides for this run only."""
    io_new = copy.deepcopy(io_cfg or {})
    rules_new = copy.deepcopy(rules_cfg or {})

    if time_limit_seconds is not None:
        joint_cfg = dict((io_new.get("joint_solve", {}) or {}))
        joint_cfg["time_limit_seconds"] = int(time_limit_seconds)
        io_new["joint_solve"] = joint_cfg

        solve_cfg = dict((rules_new.get("solve", {}) or {}))
        solve_cfg["time_limit_seconds"] = int(time_limit_seconds)
        rules_new["solve"] = solve_cfg

    if seed is not None:
        joint_cfg = dict((io_new.get("joint_solve", {}) or {}))
        joint_cfg["random_seed"] = int(seed)
        io_new["joint_solve"] = joint_cfg

        solve_cfg = dict((rules_new.get("solve", {}) or {}))
        solve_cfg["random_seed"] = int(seed)
        rules_new["solve"] = solve_cfg

    return io_new, rules_new


def _apply_time_limit_overrides(io_cfg: dict, rules_cfg: dict, seconds: int) -> tuple[dict, dict]:
    return _apply_solver_overrides(io_cfg, rules_cfg, time_limit_seconds=seconds)


def _apply_seed_overrides(io_cfg: dict, rules_cfg: dict, seed: int) -> tuple[dict, dict]:
    return _apply_solver_overrides(io_cfg, rules_cfg, seed=seed)


def _deep_merge(base: dict | None, override: dict | None) -> dict:
    if not isinstance(base, dict):
        base = {}
    if not isinstance(override, dict):
        return dict(base)
    out = dict(base)
    for key, value in override.items():
        if isinstance(out.get(key), dict) and isinstance(value, dict):
            out[key] = _deep_merge(out.get(key), value)
        else:
            out[key] = value
    return out


def _load_overrides_yaml(path: Path) -> tuple[dict | None, dict | None]:
    text = path.read_text(encoding="utf-8")
    raw = yaml.safe_load(text) or {}
    if not isinstance(raw, dict):
        raise ValueError("overrides YAML must be a mapping")
    if any(k in raw for k in ("io", "io_cfg", "rules", "rules_cfg")):
        io_override = raw.get("io_cfg", raw.get("io"))
        rules_override = raw.get("rules_cfg", raw.get("rules"))
        if io_override is not None and not isinstance(io_override, dict):
            raise ValueError("overrides.io must be a mapping")
        if rules_override is not None and not isinstance(rules_override, dict):
            raise ValueError("overrides.rules must be a mapping")
        return io_override, rules_override
    # fallback: treat top-level keys as rules overrides
    return None, raw


def main():
    """程序入口：按 mode 选择白天/晚自习/联合求解流程。"""
    _setup_console_utf8()
    args = _parse_args()
    _setup_logging(args.verbose)

    io_path = Path(args.config)
    if not io_path.is_absolute():
        # 相对路径按项目根目录解析，避免在子目录运行导致路径偏移
        project_root = Path(__file__).resolve().parent
        io_path = (project_root / io_path).resolve()
    rules_path = io_path.with_name("rules.yaml")
    # 与 io.yaml 同目录

    override_context = nullcontext()
    has_time_limit_override = args.time_limit_seconds is not None
    has_seed_override = args.seed is not None
    has_profile_override = bool(args.overrides_path)

    io_override: dict = {}
    rules_override: dict = {}
    if has_profile_override:
        override_path = Path(str(args.overrides_path))
        if not override_path.is_absolute():
            override_path = (Path(__file__).resolve().parent / override_path).resolve()
        if not override_path.exists():
            raise FileNotFoundError(f"overrides file not found: {override_path}")
        io_from_file, rules_from_file = _load_overrides_yaml(override_path)
        io_override = _deep_merge(io_override, io_from_file if isinstance(io_from_file, dict) else {})
        rules_override = _deep_merge(rules_override, rules_from_file if isinstance(rules_from_file, dict) else {})
        logger.info("CLI 覆盖 overrides = %s", str(override_path))

    solver_io_override, solver_rules_override = build_runtime_solver_overrides(
        time_limit_seconds=int(args.time_limit_seconds) if has_time_limit_override else None,
        seed=int(args.seed) if has_seed_override else None,
    )
    io_override = _deep_merge(io_override, solver_io_override)
    rules_override = _deep_merge(rules_override, solver_rules_override)
    if io_override or rules_override:
        override_context = runtime_config_overrides(
            io_cfg=io_override or None,
            rules_cfg=rules_override or None,
        )
    if has_time_limit_override:
        logger.info("CLI 覆盖 time_limit_seconds = %s", int(args.time_limit_seconds))
    if has_seed_override:
        logger.info("CLI 覆盖 seed = %s", int(args.seed))
    with override_context:
        result = run_service(
            args.mode,
            io_path=io_path,
            rules_path=rules_path,
            grade_prefix=args.grade,
            cli_args=list(sys.argv[1:]),
        )

    if result.run_id:
        logger.info("run_id = %s", result.run_id)
if __name__ == "__main__":
    main()
