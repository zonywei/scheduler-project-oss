import json
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scheduler.app import service as service_mod


def _assert_json_writer_utf8_and_no_ascii_escape(tmp_root: Path) -> None:
    json_path = tmp_root / "meta" / "proof.json"
    payload = {"path": "C:/测试/教师定位表.xlsx"}
    service_mod._write_json_file(json_path, payload)
    raw = json_path.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf"), "json should be utf-8 without BOM"
    text = raw.decode("utf-8")
    assert "测试" in text, "json should keep Chinese characters"
    assert "\\u" not in text, "json should not escape unicode as \\uXXXX"
    assert json.loads(text)["path"] == payload["path"], "json payload mismatch"


def _assert_explain_summary_utf8_and_readable(tmp_root: Path) -> None:
    outputs_dir = tmp_root / "outputs"
    meta_dir = outputs_dir / "meta"
    outputs_dir.mkdir(parents=True, exist_ok=True)
    meta_dir.mkdir(parents=True, exist_ok=True)

    evidence_payload = {
        "timestamp": "2026-02-28 05:10:00",
        "git_commit": "proof-commit",
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
        "outputs_dir": str(outputs_dir.resolve()),
        "solve_result_summary": {"status": "FEASIBLE", "wall_time": 1.0, "objective": 0, "penalty": 0},
    }
    service_mod._write_json_file(meta_dir / "run_evidence_latest.json", evidence_payload)

    service_mod.write_explain_summary(
        mode="joint",
        run_id="run_proof",
        outputs_dir=outputs_dir,
        solve_result_summary={"status": "FEASIBLE", "wall_time": 1.0, "objective": 0, "penalty": 0},
    )

    summary_path = meta_dir / "explain_summary_latest.md"
    raw = summary_path.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf"), "summary should be utf-8 without BOM"
    text = raw.decode("utf-8")
    assert "## A. Run Metadata" in text, "missing run metadata heading"
    assert "\\u" not in text, "summary should not contain unicode escape sequences"
    assert "PowerShell 5.1 requires -Encoding UTF8" in text, "missing PowerShell 5.1 hint"


def main() -> None:
    with tempfile.TemporaryDirectory() as td:
        tmp_root = Path(td)
        _assert_json_writer_utf8_and_no_ascii_escape(tmp_root)
        _assert_explain_summary_utf8_and_readable(tmp_root)
    print("test_explain_summary_real_run_proof: PASS")

if __name__ == "__main__":
    raise SystemExit(main())
