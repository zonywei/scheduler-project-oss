from __future__ import annotations

import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


from scheduler.config.loader import load_effective_config  # noqa: E402
from scheduler.domain.profile_catalog import profile_catalog_payload, validate_profile_catalog  # noqa: E402


def main() -> int:
    effective = load_effective_config(
        "joint",
        {
            "io_path": REPO_ROOT / "scheduler" / "config" / "io.yaml",
            "rules_path": REPO_ROOT / "scheduler" / "config" / "rules.yaml",
        },
    )
    report = validate_profile_catalog(REPO_ROOT / "profiles", effective.effective_cfg, mode="joint")
    payload = profile_catalog_payload(report)
    print(json.dumps(payload["summary"], ensure_ascii=False, sort_keys=True))
    if not report.ok:
        for issue in report.issues:
            print(f"{issue.severity.upper()} {issue.profile_id} {issue.path}: {issue.message}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
