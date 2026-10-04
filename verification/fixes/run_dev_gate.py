from __future__ import annotations

import argparse
import os
import subprocess
import sys
from collections.abc import Sequence

from gate_manifest import LOCAL_SMOKE_GATE, PYTEST_GATE, REPO_ROOT, SCRIPT_GATE, ScriptCheck


def _run(argv: Sequence[str], *, name: str) -> None:
    printable = " ".join(argv)
    print(f"\n=== RUN: {name} ===")
    print(printable)
    env = os.environ.copy()
    env.setdefault("PYTHONUTF8", "1")
    proc = subprocess.run(argv, cwd=REPO_ROOT, env=env, check=False)
    if proc.returncode != 0:
        raise SystemExit(f"{name} failed with exit code {proc.returncode}")


def _ensure_pytest_available() -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "--version"],
        cwd=REPO_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if proc.returncode == 0:
        print(proc.stdout.strip())
        return
    message = (
        "pytest is not installed for this interpreter. "
        "Install developer dependencies first: "
        f"{sys.executable} -m pip install -r requirements-dev.txt"
    )
    raise SystemExit(message)


def _run_script_gate(checks: Sequence[ScriptCheck]) -> None:
    for check in checks:
        _run([sys.executable, *check.argv], name=check.name)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the scheduler project development gate.")
    parser.add_argument(
        "--include-local-smoke",
        action="store_true",
        help="Also run checks that require local school Excel inputs.",
    )
    args = parser.parse_args(argv)

    _ensure_pytest_available()
    _run([sys.executable, "-m", "pytest", "-q", *PYTEST_GATE], name="pytest fast gate")
    _run_script_gate(SCRIPT_GATE)
    if args.include_local_smoke:
        _run_script_gate(LOCAL_SMOKE_GATE)
    print("\nDEV GATE: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
