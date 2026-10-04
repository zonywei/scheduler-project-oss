from __future__ import annotations

import ast
import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]


def test_pyproject_declares_supported_python_range() -> None:
    text = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'requires-python = ">=3.11,<3.15"' in text
    assert (REPO_ROOT / ".python-version").read_text(encoding="utf-8").strip() == "3.14"


def test_verify_environment_script_checks_version_and_core_imports() -> None:
    script_path = REPO_ROOT / "verification" / "fixes" / "verify_environment.py"
    tree = ast.parse(script_path.read_text(encoding="utf-8"))
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    assert {"MIN_VERSION", "MAX_VERSION", "RUNTIME_IMPORTS", "DEV_IMPORTS"} <= names
    assignments = {
        node.targets[0].id: ast.literal_eval(node.value)
        for node in tree.body
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id in {"MIN_VERSION", "MAX_VERSION"}
    }
    assert assignments == {"MIN_VERSION": (3, 11), "MAX_VERSION": (3, 15)}
    text = script_path.read_text(encoding="utf-8")
    for module_name in ("ortools.sat.python.cp_model", "pandas", "openpyxl", "yaml", "pytest"):
        assert module_name in text
    assert "run.py" in text and "--help" in text


def test_verify_environment_powershell_wrapper_uses_local_venv_when_available() -> None:
    script = (REPO_ROOT / "verify_environment.ps1").read_text(encoding="utf-8")
    assert ".venv\\Scripts\\python.exe" in script
    assert "verification\\fixes\\verify_environment.py" in script
    assert re.search(r"--dev", script, re.IGNORECASE)
