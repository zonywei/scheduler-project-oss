from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scheduler.config.loader import load_effective_config
from scheduler.rules import build_default_rule_registry, dump_effective_rules, enumerate_effective_rules


def _assert_registry_skeleton() -> None:
    effective = load_effective_config(
        "joint",
        {
            "io_path": REPO_ROOT / "scheduler" / "config" / "io.yaml",
            "rules_path": REPO_ROOT / "scheduler" / "config" / "rules.yaml",
        },
    )
    registry = build_default_rule_registry()
    all_rows = enumerate_effective_rules(
        registry,
        effective.effective_cfg,
        mode="joint",
        only_enabled=False,
    )
    assert len(all_rows) >= 8, "rule registry skeleton should expose core rules"
    for row in all_rows:
        assert row.rule_id, "rule_id required"
        assert row.name, "name required"
        assert row.category_path, "category_path required"
        assert row.config_key is not None, "config_key required"
        assert row.mode in {"hard", "soft"}, "mode must be hard/soft"
        assert row.apply_fn_name, "apply_fn should point to existing apply_xxx"

    mutex = next((x for x in all_rows if x.rule_id in {"night.fri_sun_mutex", "night.evening.fri_sun_mutex"}), None)
    assert mutex is not None, "night.fri_sun_mutex missing"
    assert mutex.enabled is True, "fri_sun_mutex should be enabled in current config"
    assert str(mutex.mode) == "hard", "fri_sun_mutex mode mismatch"
    assert int(mutex.weight or 0) == 20000, "fri_sun_mutex weight mismatch"

    active_rows = enumerate_effective_rules(
        registry,
        effective.effective_cfg,
        mode="joint",
        only_enabled=True,
    )
    assert all(x.enabled for x in active_rows), "active rows should all be enabled"

    dumped = dump_effective_rules(
        registry,
        effective.effective_cfg,
        mode="joint",
        only_enabled=False,
    )
    assert len(dumped) == len(all_rows), "dumped size mismatch"
    assert all("rule_id" in x and "weight" in x and "enabled" in x for x in dumped), "dumped schema mismatch"


def main() -> None:
    _assert_registry_skeleton()
    print("test_rule_registry_skeleton: PASS")

if __name__ == "__main__":
    raise SystemExit(main())
