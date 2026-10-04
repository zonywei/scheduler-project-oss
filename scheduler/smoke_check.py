# -*- coding: utf-8 -*-
from __future__ import annotations

import logging
from pathlib import Path

from scheduler.config.loader import load_effective_config
from scheduler.data.teacher_table_reader import read_teacher_table
from scheduler.data.day_rules_reader import load_day_inputs
from scheduler.output_paths import resolve_output_dir

logger = logging.getLogger(__name__)


def run_smoke_check(io_path: Path | None = None, rules_path: Path | None = None) -> None:
    if io_path is None and rules_path is None:
        base_dir = Path(__file__).resolve().parent
        effective = load_effective_config("joint", {"project_root": base_dir})
    else:
        effective = load_effective_config("joint", {"rules_path": rules_path, "io_path": io_path})

    rules = effective.rules_cfg
    io_cfg = effective.io_cfg
    io_p = effective.io_path
    base_dir = io_p.parent.parent

    logger.info("读取配置 OK")

    # 晚自习：教师定位表
    if "teacher_table" in io_cfg and "path" in io_cfg["teacher_table"]:
        tt_path = Path(io_cfg["teacher_table"]["path"])
        if not tt_path.is_absolute():
            io_cfg["teacher_table"]["path"] = str((base_dir / tt_path).resolve())
    read_teacher_table(io_cfg, rules)
    logger.info("读取教师定位表 OK")

    # 白天：规则表 + 定位表
    day_cfg = io_cfg.get("day", {})
    day_rules = base_dir / day_cfg.get("rules_path", "白天规则.xlsx")
    day_pos = base_dir / day_cfg.get("teacher_table_path", "教师定位表.xlsx")
    load_day_inputs(str(day_rules), str(day_pos))
    logger.info("读取白天规则 OK")

    # 输出目录可写
    out_dir = resolve_output_dir(io_cfg, io_p)
    out_dir.mkdir(parents=True, exist_ok=True)
    probe = out_dir / ".smoke_check.tmp"
    probe.write_text("ok", encoding="utf-8")
    probe.unlink(missing_ok=True)
    logger.info("输出目录可写 OK")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
    run_smoke_check()
