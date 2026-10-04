import json
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scheduler.app import service as service_mod

NO_SOURCE_MSG = "Current run did not expose penalty breakdown data source."


def _prepare_evidence(meta_dir: Path, out_dir: Path) -> None:
    payload = {
        "timestamp": "2026-02-28 05:00:00",
        "git_commit": "test-commit-penalty",
        "mode": "joint",
        "cli_args": ["--mode", "joint"],
        "python_version": "3.10",
        "platform": "windows",
        "config_paths": {"io_yaml": "C:/repo/scheduler/config/io.yaml", "rules_yaml": "C:/repo/scheduler/config/rules.yaml"},
        "effective_solver_settings": {
            "active_for_mode": "day_joint",
            "day_joint": {"time_limit_seconds": 300, "workers": 8, "random_seed": 0},
            "night": {"time_limit_seconds": 3000, "workers": 8, "random_seed": 0},
        },
        "input_files": [],
        "outputs_dir": str(out_dir.resolve()),
        "solve_result_summary": {"status": "FEASIBLE", "wall_time": 1.0, "objective": 35, "penalty": 35},
    }
    (meta_dir / "run_evidence_latest.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _assert_breakdown_with_data() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        out_dir = root / "outputs"
        meta_dir = out_dir / "meta"
        out_dir.mkdir(parents=True, exist_ok=True)
        meta_dir.mkdir(parents=True, exist_ok=True)
        _prepare_evidence(meta_dir, out_dir)

        (out_dir / "event_log.csv").write_text(
            (
                "constraint_id,constraint_name,teacher_name,unit_penalty,count_value,penalty,mode\n"
                "r1,Rule A,T1,10,2,20,soft\n"
                "r1,Rule A,T2,10,1,10,soft\n"
                "r2,Rule B,T1,5,1,5,soft\n"
            ),
            encoding="utf-8",
        )

        service_mod.write_explain_summary(
            mode="joint",
            run_id="run_penalty",
            outputs_dir=out_dir,
            solve_result_summary={"status": "FEASIBLE", "wall_time": 1.0, "objective": 35, "penalty": 35},
        )
        text = (meta_dir / "explain_summary_latest.md").read_text(encoding="utf-8")
        assert "## D. Penalty Breakdown" in text, "penalty section missing"
        assert "total_penalty: 35.0" in text, "total penalty missing"
        assert "rule_id=r1, rule_name=Rule A, penalty_sum=30.0, violation_count=3.0" in text, "rule-level top entry missing"
        assert "top_offenders=T1(20.0), T2(10.0)" in text, "top offenders missing"
        assert "rule_id=r2, rule_name=Rule B, penalty_sum=5.0, violation_count=1.0" in text, "second rule entry missing"


def _assert_breakdown_without_data() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        out_dir = root / "outputs"
        meta_dir = out_dir / "meta"
        out_dir.mkdir(parents=True, exist_ok=True)
        meta_dir.mkdir(parents=True, exist_ok=True)
        _prepare_evidence(meta_dir, out_dir)

        service_mod.write_explain_summary(
            mode="joint",
            run_id="run_no_penalty",
            outputs_dir=out_dir,
            solve_result_summary={"status": "FEASIBLE", "wall_time": 1.0, "objective": None, "penalty": None},
        )
        text = (meta_dir / "explain_summary_latest.md").read_text(encoding="utf-8")
        assert NO_SOURCE_MSG in text, "missing no-source message"


def main() -> None:
    _assert_breakdown_with_data()
    _assert_breakdown_without_data()
    print("test_explain_penalty_breakdown: PASS")

if __name__ == "__main__":
    raise SystemExit(main())
