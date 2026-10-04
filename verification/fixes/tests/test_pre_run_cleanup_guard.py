from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scheduler.app.service import _is_safe_cleanup_target


def main() -> None:
    repo_root = REPO_ROOT
    io_path = repo_root / "scheduler" / "config" / "io.yaml"
    assert io_path.exists(), f"missing io.yaml: {io_path}"

    ok, reason = _is_safe_cleanup_target(repo_root / "outputs", io_path)
    assert ok, f"expected safe for outputs dir, got {reason}"

    ok, reason = _is_safe_cleanup_target(repo_root, io_path)
    assert not ok and reason == "target_is_repo_root", f"expected repo root rejection, got {ok}/{reason}"

    ok, reason = _is_safe_cleanup_target(repo_root / "scheduler" / "outputs", io_path)
    assert not ok and reason == "target_is_scheduler_outputs", f"expected scheduler outputs rejection, got {ok}/{reason}"

    ok, reason = _is_safe_cleanup_target(repo_root.parent / "tmp_cleanup_target", io_path)
    assert not ok and reason == "target_outside_repo_root", f"expected outside-repo rejection, got {ok}/{reason}"

    print("test_pre_run_cleanup_guard: PASS")

if __name__ == "__main__":
    raise SystemExit(main())
