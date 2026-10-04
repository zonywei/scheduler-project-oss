from __future__ import annotations

import argparse
import importlib
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
MIN_VERSION = (3, 11)
MAX_VERSION = (3, 15)
RUNTIME_IMPORTS = (
    ("ortools.sat.python.cp_model", "ortools"),
    ("pandas", "pandas"),
    ("openpyxl", "openpyxl"),
    ("yaml", "PyYAML"),
)
DEV_IMPORTS = (
    ("pytest", "pytest"),
)


def _version_text(version: tuple[int, int]) -> str:
    return ".".join(str(x) for x in version)


def _check_python_version() -> None:
    current = sys.version_info[:2]
    if current < MIN_VERSION or current >= MAX_VERSION:
        raise SystemExit(
            "Unsupported Python version "
            f"{sys.version.split()[0]}; expected >= {_version_text(MIN_VERSION)} "
            f"and < {_version_text(MAX_VERSION)}."
        )
    print(f"python: PASS ({sys.version.split()[0]})")


def _check_imports(imports: Sequence[tuple[str, str]]) -> None:
    for module_name, package_name in imports:
        importlib.import_module(module_name)
        print(f"import {package_name}: PASS")


def _run_entrypoint_help() -> None:
    proc = subprocess.run(
        [sys.executable, "run.py", "--help"],
        cwd=REPO_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if proc.returncode != 0:
        print(proc.stdout)
        raise SystemExit(f"run.py --help failed with exit code {proc.returncode}")
    if "--mode" not in proc.stdout:
        raise SystemExit("run.py --help did not expose the expected --mode option")
    print("run.py --help: PASS")


def _run_pip_check() -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "pip", "check"],
        cwd=REPO_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if proc.returncode != 0:
        print(proc.stdout)
        raise SystemExit(f"pip check failed with exit code {proc.returncode}")
    print("pip check: PASS")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate the scheduler project Python environment.")
    parser.add_argument("--dev", action="store_true", help="Also require developer/test dependencies.")
    parser.add_argument("--skip-entrypoint", action="store_true", help="Skip run.py --help.")
    parser.add_argument("--pip-check", action="store_true", help="Run python -m pip check.")
    args = parser.parse_args(argv)

    _check_python_version()
    _check_imports(RUNTIME_IMPORTS)
    if args.dev:
        _check_imports(DEV_IMPORTS)
    if not args.skip_entrypoint:
        _run_entrypoint_help()
    if args.pip_check:
        _run_pip_check()
    print("ENVIRONMENT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
