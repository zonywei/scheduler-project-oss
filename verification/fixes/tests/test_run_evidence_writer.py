import hashlib
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scheduler.app import service as service_mod


def _unicode_text(*codepoints: int) -> str:
    return "".join(chr(c) for c in codepoints)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _assert_write_success() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        base_dir = root / "scheduler"
        cfg_dir = base_dir / "config"
        out_dir = root / "outputs"
        cfg_dir.mkdir(parents=True, exist_ok=True)
        out_dir.mkdir(parents=True, exist_ok=True)

        io_path = cfg_dir / "io.yaml"
        rules_path = cfg_dir / "rules.yaml"
        teacher_name = _unicode_text(0x6559, 0x5E08, 0x5B9A, 0x4F4D, 0x8868) + ".xlsx"
        day_rules_name = _unicode_text(0x767D, 0x5929, 0x89C4, 0x5219) + ".xlsx"
        teacher_table = base_dir / teacher_name
        day_rules = base_dir / day_rules_name
        teacher_table.write_text("teacher-table", encoding="utf-8")
        day_rules.write_text("day-rules", encoding="utf-8")
        io_path.write_text("io: 1\n", encoding="utf-8")
        rules_path.write_text("rules: 1\n", encoding="utf-8")

        io_cfg = {
            "teacher_table": {"path": teacher_name},
            "day": {"rules_path": day_rules_name, "teacher_table_path": teacher_name},
            "joint_solve": {
                "time_limit_seconds": 30,
                "workers": 4,
                "random_seed": 11,
                "relative_gap_limit": 0.02,
                "absolute_gap_limit": 3,
                "log_search_progress": True,
            },
            "output": {"dir": "outputs"},
        }
        rules_cfg = {
            "solve": {
                "time_limit_seconds": 60,
                "workers": 2,
                "random_seed": 22,
                "relative_gap_limit": 0.05,
                "absolute_gap_limit": 5,
                "log_search_progress": False,
            }
        }

        service_mod.write_run_evidence(
            mode="joint",
            cli_args=["--mode", "joint", "--seed", "11"],
            io_cfg=io_cfg,
            rules_cfg=rules_cfg,
            io_path=io_path,
            rules_path=rules_path,
            outputs_dir=out_dir,
            run_id="run_test",
            solve_result_summary={"status": "FEASIBLE", "wall_time": 1.23, "objective": 10, "penalty": 10},
        )

        latest = out_dir / "meta" / "run_evidence_latest.json"
        by_run = out_dir / "meta" / "run_evidence_run_test.json"
        assert latest.exists(), "run_evidence_latest.json missing"
        assert by_run.exists(), "run_evidence_<run_id>.json missing"

        raw = latest.read_bytes()
        assert not raw.startswith(b"\xef\xbb\xbf"), "json should be utf-8 without BOM"
        raw_text = raw.decode("utf-8")
        assert teacher_name in raw_text, "json should keep Chinese path text"
        assert "\\u" not in raw_text, "json should not escape unicode as \\uXXXX"
        payload = json.loads(raw_text)

        required_keys = {
            "timestamp",
            "git_commit",
            "mode",
            "cli_args",
            "python_version",
            "platform",
            "config_paths",
            "effective_solver_settings",
            "input_files",
            "outputs_dir",
            "solve_result_summary",
        }
        missing = required_keys - set(payload.keys())
        assert not missing, f"missing keys: {sorted(missing)}"

        teacher_item = next((x for x in payload["input_files"] if x.get("label") == "teacher_table"), None)
        assert teacher_item is not None, "teacher_table evidence missing"
        assert teacher_item.get("exists") is True, "teacher_table should exist"
        assert teacher_item.get("sha256") == _sha256(teacher_table), "teacher_table sha256 mismatch"
        assert payload["effective_solver_settings"]["day_joint"]["relative_gap_limit"] == 0.02
        assert payload["effective_solver_settings"]["day_joint"]["absolute_gap_limit"] == 3
        assert payload["effective_solver_settings"]["day_joint"]["log_search_progress"] is True
        assert payload["effective_solver_settings"]["night"]["relative_gap_limit"] == 0.05
        assert payload["effective_solver_settings"]["night"]["absolute_gap_limit"] == 5
        assert payload["effective_solver_settings"]["night"]["log_search_progress"] is False


def _assert_write_failure_does_not_raise() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        cfg_dir = root / "scheduler" / "config"
        out_dir = root / "outputs"
        cfg_dir.mkdir(parents=True, exist_ok=True)
        out_dir.mkdir(parents=True, exist_ok=True)
        io_path = cfg_dir / "io.yaml"
        rules_path = cfg_dir / "rules.yaml"
        io_path.write_text("io: 1\n", encoding="utf-8")
        rules_path.write_text("rules: 1\n", encoding="utf-8")
        io_cfg = {"output": {"dir": "outputs"}}
        rules_cfg = {"solve": {}}

        with patch.object(service_mod, "_write_json_file", side_effect=OSError("disk full")):
            with patch.object(service_mod.logger, "warning") as warning_mock:
                service_mod.write_run_evidence(
                    mode="night",
                    cli_args=["--mode", "night"],
                    io_cfg=io_cfg,
                    rules_cfg=rules_cfg,
                    io_path=io_path,
                    rules_path=rules_path,
                    outputs_dir=out_dir,
                    run_id="",
                    solve_result_summary={"status": None, "wall_time": None, "objective": None, "penalty": None},
                )
                assert warning_mock.called, "write failure should emit warning"


def main() -> None:
    _assert_write_success()
    _assert_write_failure_does_not_raise()
    print("test_run_evidence_writer: PASS")

if __name__ == "__main__":
    raise SystemExit(main())
