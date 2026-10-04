# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Tuple, Optional


@dataclass
class WarmStartConfig:
    enabled: bool = True
    path: Path | None = None
    best_path: Path | None = None
    pool_dir: Path | None = None
    keep_last_n: int = 10
    prefer_same_rules_hash: bool = True
    prefer_same_data_hash: bool = True


def _hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _hash_file(path: Path) -> str:
    try:
        data = path.read_bytes()
        return _hash_bytes(data)
    except Exception:
        if path.exists():
            stat = path.stat()
            return _hash_bytes(f"{path.resolve()}|{stat.st_mtime}|{stat.st_size}".encode("utf-8"))
        return _hash_bytes(str(path).encode("utf-8"))


def compute_rules_data_hash(
    io_path: Path,
    rules_path: Path,
    day_rules_path: Path,
    teacher_table_path: Path,
    *,
    implementation_paths: Iterable[Path] | None = None,
) -> Tuple[str, str]:
    impl_hash = _hash_implementation_paths(
        implementation_paths if implementation_paths is not None else _default_implementation_paths()
    )
    rules_hash = _hash_bytes(
        (_hash_file(io_path) + _hash_file(rules_path) + _hash_file(day_rules_path) + impl_hash).encode("utf-8")
    )
    data_hash = _hash_bytes((_hash_file(teacher_table_path)).encode("utf-8"))
    return rules_hash, data_hash


def _default_implementation_paths() -> Tuple[Path, ...]:
    root = Path(__file__).resolve().parent
    paths: list[Path] = [
        root / "warm_start.py",
        root / "joint_solver.py",
        root / "joint_pipeline.py",
        root / "solver_params.py",
    ]
    for directory in (root / "model" / "constraints", root / "rules"):
        if directory.exists():
            paths.extend(directory.rglob("*.py"))
    unique = {path.resolve() for path in paths if path.exists() and path.is_file()}
    return tuple(sorted(unique, key=lambda path: str(path).lower()))


def _hash_implementation_paths(paths: Iterable[Path]) -> str:
    parts: list[str] = []
    for path in sorted({Path(path).resolve() for path in paths}, key=lambda item: str(item).lower()):
        parts.append(f"{path.as_posix()}={_hash_file(path)}")
    return _hash_bytes("|".join(parts).encode("utf-8"))


def select_solution_file(
    cfg: WarmStartConfig,
    rules_hash: str,
    data_hash: str,
) -> Optional[Path]:
    if not cfg.enabled:
        return None

    candidates: List[Path] = []
    if cfg.pool_dir and cfg.pool_dir.exists():
        candidates.extend(sorted(cfg.pool_dir.glob("solution_*.json")))
    for path in (cfg.best_path, cfg.path):
        if path and path.exists() and path not in candidates:
            candidates.append(path)

    def score_meta(meta: dict) -> Tuple[int, int, float, str]:
        same_data_score = 1 if cfg.prefer_same_data_hash and meta.get("data_hash") == data_hash else 0
        same_rules_score = 1 if cfg.prefer_same_rules_hash and meta.get("rules_hash") == rules_hash else 0
        obj = meta.get("objective", 0)
        ts = meta.get("timestamp", "")
        return same_data_score, same_rules_score, -float(obj or 0), ts

    best = None
    best_key = None
    for path in candidates:
        try:
            meta = json.loads(path.read_text(encoding="utf-8")).get("meta", {})
        except Exception:
            continue
        key = score_meta(meta)
        if best is None or key > best_key:
            best = path
            best_key = key

    return best


def save_solution_json(
    out_path: Path,
    meta: dict,
    day_x1: List[List[str]],
    night_y1: List[List[str]],
) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "meta": meta,
        "day": {"x1": day_x1},
        "night": {"y1": night_y1},
    }
    out_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def save_best_solution_json(
    out_path: Path | None,
    meta: dict,
    day_x1: List[List[str]],
    night_y1: List[List[str]],
) -> dict:
    if out_path is None:
        return {"status": "disabled", "path": ""}

    current_objective = float(meta.get("objective") or 0.0)
    existing_meta: dict = {}
    if out_path.exists():
        try:
            existing_meta = json.loads(out_path.read_text(encoding="utf-8")).get("meta", {})
        except Exception:
            existing_meta = {}

    same_rules = existing_meta.get("rules_hash") == meta.get("rules_hash")
    same_data = existing_meta.get("data_hash") == meta.get("data_hash")
    if same_data and same_rules:
        try:
            existing_objective = float(existing_meta.get("objective") or 0.0)
        except Exception:
            existing_objective = 0.0
        if existing_objective <= current_objective:
            return {
                "status": "kept",
                "path": str(out_path),
                "objective": current_objective,
                "existing_objective": existing_objective,
                "same_rules": same_rules,
                "reason": "existing_same_data_solution_is_not_worse",
            }

    save_solution_json(out_path, meta, day_x1, night_y1)
    return {
        "status": "updated" if existing_meta else "created",
        "path": str(out_path),
        "objective": current_objective,
        "previous_objective": existing_meta.get("objective"),
        "same_rules": same_rules,
        "same_data": same_data,
    }


def load_solution_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def trim_solution_pool(pool_dir: Path, keep_last_n: int) -> None:
    if keep_last_n <= 0:
        return
    files = sorted(pool_dir.glob("solution_*.json"), key=lambda p: p.stat().st_mtime)
    if len(files) <= keep_last_n:
        return
    for p in files[: len(files) - keep_last_n]:
        try:
            p.unlink()
        except Exception:
            pass
