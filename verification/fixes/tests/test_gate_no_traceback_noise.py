import subprocess
import sys
from pathlib import Path


def main() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    cmd = [sys.executable, "verification/fixes/tests/test_run_evidence_writer.py"]
    proc = subprocess.run(
        cmd,
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=False,
    )
    combined = (proc.stdout or "") + (proc.stderr or "")
    assert proc.returncode == 0, f"test_run_evidence_writer.py failed:\n{combined}"
    assert "Traceback" not in combined, f"traceback noise found:\n{combined}"
    assert "test_run_evidence_writer: PASS" in combined, "PASS marker missing"
    print("test_gate_no_traceback_noise: PASS")

if __name__ == "__main__":
    raise SystemExit(main())
