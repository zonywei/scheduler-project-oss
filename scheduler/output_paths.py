# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCHEDULER_OUTPUTS_NAME = "scheduler/outputs"


def project_root_from_io_path(io_path: str | Path | None = None) -> Path:
    if io_path is None:
        return PROJECT_ROOT.resolve()
    path = Path(io_path).resolve()
    if path.name == "io.yaml" and path.parent.name == "config" and path.parent.parent.name == "scheduler":
        return path.parent.parent.parent.resolve()
    return PROJECT_ROOT.resolve()


def project_output_dir(project_root: str | Path | None = None) -> Path:
    return (Path(project_root).resolve() if project_root is not None else PROJECT_ROOT.resolve()) / "outputs"


def resolve_project_path(
    raw_path: Any,
    *,
    project_root: str | Path | None = None,
    label: str = "path",
    reject_scheduler_outputs: bool = False,
) -> Path:
    root = Path(project_root).resolve() if project_root is not None else PROJECT_ROOT.resolve()
    path = Path(str(raw_path or ""))
    resolved = path.resolve() if path.is_absolute() else (root / path).resolve()
    if reject_scheduler_outputs and is_scheduler_outputs_path(resolved, project_root=root):
        raise ValueError(f"{label} resolves to {SCHEDULER_OUTPUTS_NAME}; use project-root outputs/ instead.")
    return resolved


def resolve_output_dir(
    io_cfg: dict[str, Any] | None,
    io_path: str | Path | None,
    *,
    default: str = "outputs",
) -> Path:
    raw = ((io_cfg or {}).get("output", {}) or {}).get("dir", default)
    return resolve_project_path(
        raw,
        project_root=project_root_from_io_path(io_path),
        label="output.dir",
        reject_scheduler_outputs=True,
    )


def is_scheduler_outputs_path(path: str | Path, *, project_root: str | Path | None = None) -> bool:
    root = Path(project_root).resolve() if project_root is not None else PROJECT_ROOT.resolve()
    target = Path(path).resolve()
    scheduler_outputs = (root / "scheduler" / "outputs").resolve()
    return target == scheduler_outputs or scheduler_outputs in target.parents
