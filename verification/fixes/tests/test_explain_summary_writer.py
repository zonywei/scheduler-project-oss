import json
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scheduler.app import service as service_mod


def _assert_summary_write() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        out_dir = root / "outputs"
        meta_dir = out_dir / "meta"
        out_dir.mkdir(parents=True, exist_ok=True)
        meta_dir.mkdir(parents=True, exist_ok=True)

        evidence_payload = {
            "timestamp": "2026-02-28 04:00:00",
            "git_commit": "test-commit",
            "mode": "joint",
            "cli_args": ["--mode", "joint"],
            "python_version": "3.10",
            "platform": "windows",
            "config_paths": {"io_yaml": "C:/repo/scheduler/config/io.yaml", "rules_yaml": "C:/repo/scheduler/config/rules.yaml"},
            "effective_solver_settings": {
                "active_for_mode": "day_joint",
                "day_joint": {"time_limit_seconds": 300, "workers": 8, "random_seed": 11},
                "night": {"time_limit_seconds": 3000, "workers": 8, "random_seed": 0},
            },
            "input_files": [
                {
                    "label": "teacher_table",
                    "path": "C:/repo/scheduler/teacher_table.xlsx",
                    "exists": True,
                    "size_bytes": 123,
                    "mtime": "2026-02-28 03:00:00",
                    "sha256": "abc123",
                }
            ],
            "outputs_dir": str(out_dir.resolve()),
            "solve_result_summary": {"status": "FEASIBLE", "wall_time": 1.0, "objective": 100, "penalty": 100},
        }
        (meta_dir / "run_evidence_latest.json").write_text(
            json.dumps(evidence_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (out_dir / "event_log.csv").write_text(
            (
                "constraint_id,constraint_name,teacher_name,unit_penalty,count_value,penalty,mode\n"
                "rule_a,Rule A,T1,30,1,30,soft\n"
                "rule_b,Rule B,T2,10,2,10,soft\n"
            ),
            encoding="utf-8",
        )

        service_mod.write_explain_summary(
            mode="joint",
            run_id="run_test",
            outputs_dir=out_dir,
            solve_result_summary={"status": "FEASIBLE", "wall_time": 1.0, "objective": 100, "penalty": 100},
        )

        summary_path = meta_dir / "explain_summary_latest.md"
        assert summary_path.exists(), "explain_summary_latest.md missing"
        raw = summary_path.read_bytes()
        assert not raw.startswith(b"\xef\xbb\xbf"), "summary should be utf-8 without BOM"
        text = raw.decode("utf-8")
        assert "mode: joint" in text, "mode field missing"
        assert "git_commit: test-commit" in text, "git_commit field missing"
        assert "status: FEASIBLE" in text, "status field missing"


def main() -> None:
    _assert_summary_write()
    print("test_explain_summary_writer: PASS")

if __name__ == "__main__":
    raise SystemExit(main())
