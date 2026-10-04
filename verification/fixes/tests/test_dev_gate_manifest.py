from __future__ import annotations

import ast
from pathlib import Path

from verification.fixes.gate_manifest import (
    LOCAL_SMOKE_GATE,
    PYTEST_GATE,
    REPO_ROOT,
    SCRIPT_GATE,
    all_manifest_paths,
)


def test_gate_manifest_paths_exist() -> None:
    missing = [path for path in all_manifest_paths() if not (REPO_ROOT / path).exists()]
    assert not missing, f"gate manifest points to missing files: {missing}"


def test_gate_manifest_has_no_duplicates() -> None:
    paths = all_manifest_paths()
    assert len(paths) == len(set(paths)), "gate manifest contains duplicate checks"


def test_gate_manifest_keeps_local_smoke_explicit() -> None:
    assert LOCAL_SMOKE_GATE, "local smoke tier should stay visible"
    assert all(check.requires_local_inputs for check in LOCAL_SMOKE_GATE)
    assert all(not check.requires_local_inputs for check in SCRIPT_GATE)


def test_gate_manifest_uses_pytest_files_only() -> None:
    assert PYTEST_GATE, "pytest gate must not be empty"
    assert all(path.startswith("verification/fixes/tests/test_") for path in PYTEST_GATE)
    assert all(path.endswith(".py") for path in PYTEST_GATE)


def test_run_dev_gate_imports_manifest() -> None:
    runner_path = REPO_ROOT / "verification" / "fixes" / "run_dev_gate.py"
    tree = ast.parse(runner_path.read_text(encoding="utf-8"))
    imported_names = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "gate_manifest"
        for alias in node.names
    }
    assert {"PYTEST_GATE", "SCRIPT_GATE", "LOCAL_SMOKE_GATE"} <= imported_names


def test_verify_release_runs_strict_commercial_acceptance() -> None:
    script = (REPO_ROOT / "verify_release.ps1").read_text(encoding="utf-8-sig")
    assert "commercial_acceptance_audit.py --strict-release" in script
    assert "strict commercial acceptance audit" in script


def test_verify_release_runs_generic_ai_or_acceptance() -> None:
    script = (REPO_ROOT / "verify_release.ps1").read_text(encoding="utf-8-sig")
    assert "ai_or_acceptance_audit.py" in script
    assert "generic AI OR framework acceptance audit" in script
