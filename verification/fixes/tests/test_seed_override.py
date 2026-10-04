import os
import subprocess
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import run as run_entry  # noqa: E402
from scheduler.config.loader import load_effective_config, runtime_solver_overrides  # noqa: E402


def _assert_help_has_seed_flag() -> None:
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
    assert "--seed" in proc.stdout, "missing --seed in help output"


def _assert_override_is_pure_function() -> None:
    io_path = REPO_ROOT / "scheduler" / "config" / "io.yaml"
    rules_path = REPO_ROOT / "scheduler" / "config" / "rules.yaml"
    io_cfg = yaml.safe_load(io_path.read_text(encoding="utf-8")) or {}
    rules_cfg = yaml.safe_load(rules_path.read_text(encoding="utf-8")) or {}

    original_io_seed = ((io_cfg.get("joint_solve", {}) or {}).get("random_seed"))
    original_rules_seed = ((rules_cfg.get("solve", {}) or {}).get("random_seed"))

    new_io, new_rules = run_entry._apply_seed_overrides(io_cfg, rules_cfg, 7)

    assert ((new_io.get("joint_solve", {}) or {}).get("random_seed")) == 7
    assert ((new_rules.get("solve", {}) or {}).get("random_seed")) == 7
    assert ((io_cfg.get("joint_solve", {}) or {}).get("random_seed")) == original_io_seed
    assert ((rules_cfg.get("solve", {}) or {}).get("random_seed")) == original_rules_seed


def _assert_loader_runtime_override() -> None:
    io_path = REPO_ROOT / "scheduler" / "config" / "io.yaml"
    rules_path = REPO_ROOT / "scheduler" / "config" / "rules.yaml"
    paths = {"io_path": io_path, "rules_path": rules_path}

    base = load_effective_config("joint", paths)
    base_io_seed = ((base.io_cfg.get("joint_solve", {}) or {}).get("random_seed"))
    base_rules_seed = ((base.rules_cfg.get("solve", {}) or {}).get("random_seed"))

    test_seed = 12345
    if base_io_seed == test_seed and base_rules_seed == test_seed:
        test_seed = 12346

    with runtime_solver_overrides(seed=test_seed):
        overridden = load_effective_config("joint", paths)
        assert ((overridden.io_cfg.get("joint_solve", {}) or {}).get("random_seed")) == test_seed
        assert ((overridden.rules_cfg.get("solve", {}) or {}).get("random_seed")) == test_seed
        assert ((overridden.effective_cfg.get("solve", {}) or {}).get("random_seed")) == test_seed

    restored = load_effective_config("joint", paths)
    assert ((restored.io_cfg.get("joint_solve", {}) or {}).get("random_seed")) == base_io_seed
    assert ((restored.rules_cfg.get("solve", {}) or {}).get("random_seed")) == base_rules_seed


def main() -> None:
    _assert_help_has_seed_flag()
    _assert_override_is_pure_function()
    _assert_loader_runtime_override()
    print("test_seed_override: PASS")

if __name__ == "__main__":
    raise SystemExit(main())
