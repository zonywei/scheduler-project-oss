from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scheduler.app import service as service_mod  # noqa: E402


def _assert_run_meta_mirror() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        run_dir = root / "outputs" / "solutions" / "run_20260301_000001"
        out_meta = root / "outputs" / "meta"
        run_meta = run_dir / "_run_meta"
        out_meta.mkdir(parents=True, exist_ok=True)
        run_meta.mkdir(parents=True, exist_ok=True)

        evidence_payload = {
            "timestamp": "2026-03-01 00:00:00",
            "git_commit": "abc",
            "mode": "joint",
            "solve_result_summary": {"status": "FEASIBLE"},
        }
        summary_path = out_meta / "explain_summary_latest.md"
        summary_text = "# explain_summary\n- status: FEASIBLE\n"
        summary_path.write_text(summary_text, encoding="utf-8")

        service_mod._mirror_run_level_meta_to_run_dir(
            run_dir=run_dir,
            run_id="run_20260301_000001",
            evidence_payload=evidence_payload,
            explain_summary_path=summary_path,
        )

        latest_evidence = run_meta / "run_evidence_latest.json"
        run_evidence = run_meta / "run_evidence_run_20260301_000001.json"
        mirrored_summary = run_meta / "explain_summary_latest.md"

        assert latest_evidence.exists(), "run_evidence_latest.json missing in run_dir"
        assert run_evidence.exists(), "run_evidence_<run_id>.json missing in run_dir"
        assert mirrored_summary.exists(), "explain_summary_latest.md missing in run_dir"

        payload = json.loads(latest_evidence.read_text(encoding="utf-8"))
        assert payload.get("git_commit") == "abc"
        assert mirrored_summary.read_text(encoding="utf-8") == summary_text


def main() -> None:
    _assert_run_meta_mirror()
    print("test_run_meta_mirror: PASS")

if __name__ == "__main__":
    raise SystemExit(main())
