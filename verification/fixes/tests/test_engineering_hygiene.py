from __future__ import annotations

import ast
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]

ROOT_TEMP_PATTERNS = (
    "temp*",
    "tmp*",
    "debug*",
    "dump*",
    "scratch*",
    "*.tmp",
    "*.bak",
    "*.log",
)
ROOT_GENERATED_ARTIFACT_PATTERNS = (
    "*.png",
    "*snapshot*.md",
)
TRACKED_GENERATED_PREFIXES = (
    "tmp/",
    "outputs/",
    "scheduler/outputs/",
)
PUBLIC_STATIC_IMAGE_PATHS = {
    "scheduler/app/static/assets/brand/courseorder-mark-v2.png",
    "scheduler/app/static/assets/formal-project-preview.png",
}

TRACKED_GENERATED_EXTENSIONS = (
    ".err",
    ".jpg",
    ".jpeg",
    ".log",
    ".out",
    ".png",
    ".xlsx",
    ".zip",
)


def _is_allowed_print_file(path: Path) -> bool:
    rel = path.relative_to(REPO_ROOT).as_posix()
    return (
        "/tests/" in f"/{rel}"
        or rel.endswith("_smoke_test.py")
        or rel == "scheduler/smoke_check.py"
        or rel.startswith("verification/")
    )


def _contains_print_call(path: Path) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and func.id == "print":
            return True
    return False


def test_no_temp_artifacts_in_repo_root() -> None:
    hits: list[str] = []
    for pattern in ROOT_TEMP_PATTERNS:
        hits.extend(
            sorted(
                str(path.relative_to(REPO_ROOT))
                for path in REPO_ROOT.glob(pattern)
                if path.is_file()
            )
        )
    assert not sorted(set(hits)), f"repo-root temp artifacts should not be committed: {sorted(set(hits))}"


def test_no_generated_snapshots_in_repo_root() -> None:
    hits: list[str] = []
    for pattern in ROOT_GENERATED_ARTIFACT_PATTERNS:
        hits.extend(
            sorted(
                str(path.relative_to(REPO_ROOT))
                for path in REPO_ROOT.glob(pattern)
                if path.is_file()
            )
        )
    assert not sorted(set(hits)), (
        "generated screenshots/snapshots belong under output/web/screenshots or tmp, "
        f"not repo root: {sorted(set(hits))}"
    )


def test_gitignore_keeps_runtime_artifacts_out_of_core_tree() -> None:
    ignore_text = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    for pattern in (
        "outputs/",
        "scheduler/outputs/",
        "tmp/",
        ".cache/",
        "cache/",
        "output/web/screenshots/",
        "/*.png",
        "/*snapshot*.md",
    ):
        assert pattern in ignore_text, f"missing generated-artifact ignore pattern: {pattern}"


def test_generated_artifacts_are_not_tracked_by_git() -> None:
    proc = subprocess.run(
        ["git", "-c", f"safe.directory={REPO_ROOT.as_posix()}", "ls-files"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    tracked = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    offenders = [
        path
        for path in tracked
        if path.startswith(TRACKED_GENERATED_PREFIXES)
        or (path.lower().endswith(TRACKED_GENERATED_EXTENSIONS) and path not in PUBLIC_STATIC_IMAGE_PATHS)
    ]
    assert not offenders, f"generated artifacts must not be tracked in the open-source repo: {offenders[:20]}"


def test_no_print_calls_in_production_scheduler_modules() -> None:
    offenders = []
    for path in sorted((REPO_ROOT / "scheduler").rglob("*.py")):
        if _is_allowed_print_file(path):
            continue
        if _contains_print_call(path):
            offenders.append(path.relative_to(REPO_ROOT).as_posix())
    assert not offenders, f"use logger instead of print in production modules: {offenders}"
