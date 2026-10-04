from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scheduler.config.loader import load_effective_config  # noqa: E402
from scheduler.rules import (  # noqa: E402
    apply_enabled_rules,
    build_default_rule_registry,
    enumerate_effective_rules,
    select_enabled_rules_for_audit,
)


def _assert_apply_enabled_rules_stage_order() -> None:
    effective = load_effective_config(
        "joint",
        {
            "io_path": REPO_ROOT / "scheduler" / "config" / "io.yaml",
            "rules_path": REPO_ROOT / "scheduler" / "config" / "rules.yaml",
        },
    )
    registry = build_default_rule_registry()

    calls: list[tuple[str, str, int]] = []
    selected = select_enabled_rules_for_audit(
        registry,
        effective.effective_cfg,
        mode="joint",
        stage="constraints",
        invoke=lambda row: calls.append((row.rule_id, row.stage, int(row.order))),
    )
    assert selected, "no enabled constraint rules selected"
    assert all(stage == "constraints" for _, stage, _ in calls), "stage filtering failed"

    all_rows = [
        row
        for row in enumerate_effective_rules(registry, effective.effective_cfg, mode="joint", only_enabled=True)
        if row.stage == "constraints"
    ]
    expected_order = [(row.rule_id, row.stage, int(row.order)) for row in all_rows]
    assert calls == expected_order, "apply order mismatch"

    compat_calls: list[str] = []
    compat_selected = apply_enabled_rules(
        registry,
        effective.effective_cfg,
        mode="joint",
        stage="constraints",
        invoke=lambda row: compat_calls.append(row.rule_id),
    )
    assert [row.rule_id for row in compat_selected] == compat_calls == [row.rule_id for row in selected]


def _assert_registry_docs_are_audit_only() -> None:
    doc = (REPO_ROOT / "verification" / "fixes" / "rule_registry_schema.md").read_text(encoding="utf-8")
    assert "audit and trace registry only" in doc
    assert "does not decide whether solver constraints execute" in doc
    assert "select_enabled_rules_for_audit" in doc


def main() -> None:
    _assert_apply_enabled_rules_stage_order()
    _assert_registry_docs_are_audit_only()
    print("test_rule_registry_apply_enabled: PASS")

if __name__ == "__main__":
    raise SystemExit(main())
