import os
import subprocess
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import run as run_entry  # noqa: E402


def _assert_help_has_flag() -> None:
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    proc = subprocess.run(
        [sys.executable, str(REPO_ROOT / "run.py"), "--help"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        env=env,
    )
    assert proc.returncode == 0, f"--help failed: {proc.returncode}\n{proc.stdout}\n{proc.stderr}"
    assert "--time-limit-seconds" in proc.stdout, "missing --time-limit-seconds in help output"
    assert "--time-limit" in proc.stdout, "missing --time-limit alias in help output"


def _assert_override_applies() -> None:
    io_path = REPO_ROOT / "scheduler" / "config" / "io.yaml"
    rules_path = REPO_ROOT / "scheduler" / "config" / "rules.yaml"
    io_cfg = yaml.safe_load(io_path.read_text(encoding="utf-8")) or {}
    rules_cfg = yaml.safe_load(rules_path.read_text(encoding="utf-8")) or {}
    config_dir = REPO_ROOT / "scheduler" / "config"

    original_io_limit = ((io_cfg.get("joint_solve", {}) or {}).get("time_limit_seconds"))
    original_rules_limit = ((rules_cfg.get("solve", {}) or {}).get("time_limit_seconds"))
    before_temp_files = sorted(config_dir.glob(".*runtime_override*"))
    assert not before_temp_files, f"unexpected runtime override temp files before test: {before_temp_files}"

    new_io, new_rules = run_entry._apply_time_limit_overrides(io_cfg, rules_cfg, 30)

    assert ((new_io.get("joint_solve", {}) or {}).get("time_limit_seconds")) == 30
    assert ((new_rules.get("solve", {}) or {}).get("time_limit_seconds")) == 30
    assert ((io_cfg.get("joint_solve", {}) or {}).get("time_limit_seconds")) == original_io_limit
    assert ((rules_cfg.get("solve", {}) or {}).get("time_limit_seconds")) == original_rules_limit
    after_temp_files = sorted(config_dir.glob(".*runtime_override*"))
    assert not after_temp_files, f"unexpected runtime override temp files after test: {after_temp_files}"


def main() -> None:
    _assert_help_has_flag()
    _assert_override_applies()
    print("test_time_limit_override: PASS")

if __name__ == "__main__":
    raise SystemExit(main())
