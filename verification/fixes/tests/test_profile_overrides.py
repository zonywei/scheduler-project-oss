from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import run as run_entry  # noqa: E402
from scheduler.config.loader import load_effective_config, runtime_config_overrides  # noqa: E402


def _assert_profile_overrides_roundtrip() -> None:
    io_path = (REPO_ROOT / "scheduler" / "config" / "io.yaml").resolve()
    rules_path = io_path.with_name("rules.yaml")
    base = load_effective_config("joint", {"io_path": io_path, "rules_path": rules_path})

    baseline_time_limit = ((base.io_cfg.get("joint_solve", {}) or {}).get("time_limit_seconds"))
    baseline_seed = ((base.io_cfg.get("joint_solve", {}) or {}).get("random_seed"))
    baseline_weekend = ((base.rules_cfg.get("day_constraints", {}) or {}).get("enable_weekend_halfday_constraint"))

    with tempfile.TemporaryDirectory() as td:
        override_path = Path(td) / "overrides.yaml"
        payload = {
            "io": {
                "joint_solve": {
                    "time_limit_seconds": 45,
                    "random_seed": 999,
                }
            },
            "rules": {
                "day_constraints": {
                    "enable_weekend_halfday_constraint": False,
                }
            },
        }
        override_path.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8")

        io_override, rules_override = run_entry._load_overrides_yaml(override_path)
        assert isinstance(io_override, dict)
        assert isinstance(rules_override, dict)

        with runtime_config_overrides(io_cfg=io_override, rules_cfg=rules_override):
            effective = load_effective_config("joint", {"io_path": io_path, "rules_path": rules_path})
            assert ((effective.io_cfg.get("joint_solve", {}) or {}).get("time_limit_seconds")) == 45
            assert ((effective.io_cfg.get("joint_solve", {}) or {}).get("random_seed")) == 999
            assert ((effective.rules_cfg.get("day_constraints", {}) or {}).get("enable_weekend_halfday_constraint")) is False

    restored = load_effective_config("joint", {"io_path": io_path, "rules_path": rules_path})
    assert ((restored.io_cfg.get("joint_solve", {}) or {}).get("time_limit_seconds")) == baseline_time_limit
    assert ((restored.io_cfg.get("joint_solve", {}) or {}).get("random_seed")) == baseline_seed
    assert ((restored.rules_cfg.get("day_constraints", {}) or {}).get("enable_weekend_halfday_constraint")) == baseline_weekend


def main() -> None:
    _assert_profile_overrides_roundtrip()
    print("test_profile_overrides: PASS")

if __name__ == "__main__":
    raise SystemExit(main())
