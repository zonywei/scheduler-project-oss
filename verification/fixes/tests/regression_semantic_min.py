from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
OUTPUTS_META = REPO_ROOT / "outputs" / "meta"
BASELINE_PATH = REPO_ROOT / "verification" / "fixes" / "baseline_joint_metrics.json"


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _run_joint(config: Path, time_limit_seconds: int, seed: int) -> None:
    cmd = [
        sys.executable,
        "run.py",
        "--mode",
        "joint",
        "--config",
        str(config),
        "--time-limit-seconds",
        str(time_limit_seconds),
        "--seed",
        str(seed),
        "--verbose",
    ]
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    proc = subprocess.run(
        cmd,
        cwd=str(REPO_ROOT),
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
        env=env,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            "joint regression run failed\n"
            f"exit={proc.returncode}\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
        )


def _assert_required_artifacts() -> dict[str, Path]:
    required = {
        "run_evidence": OUTPUTS_META / "run_evidence_latest.json",
        "explain_summary": OUTPUTS_META / "explain_summary_latest.md",
        "effective_rules_snapshot": OUTPUTS_META / "effective_rules_snapshot.json",
        "solver_params_snapshot": OUTPUTS_META / "solver_params_snapshot.json",
        "inputs_fingerprint": OUTPUTS_META / "inputs_fingerprint.json",
        "applied_rules_trace": OUTPUTS_META / "applied_rules_trace.json",
    }
    missing = [name for name, path in required.items() if not path.exists()]
    if missing:
        raise AssertionError(f"missing required artifacts: {missing}")
    return required


def _extract_metrics() -> dict[str, Any]:
    evidence = _load_json(OUTPUTS_META / "run_evidence_latest.json")
    solver_overview = _load_json(OUTPUTS_META / "final_solver_overview.json")
    status = str((evidence.get("solve_result_summary") or {}).get("status") or "")
    objective = float(solver_overview.get("objective_value", 0.0) or 0.0)
    wall_time = float(solver_overview.get("wall_time", 0.0) or 0.0)
    return {
        "status": status,
        "objective": objective,
        "wall_time": wall_time,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def _assert_metrics(metrics: dict[str, Any], objective_tolerance_ratio: float) -> None:
    if metrics["status"] not in {"FEASIBLE", "OPTIMAL"}:
        raise AssertionError(f"unexpected status: {metrics['status']}")

    if BASELINE_PATH.exists():
        baseline = _load_json(BASELINE_PATH)
        baseline_obj = float(baseline.get("objective", 0.0) or 0.0)
        if baseline_obj > 0:
            max_allowed = baseline_obj * (1.0 + float(objective_tolerance_ratio))
            if metrics["objective"] > max_allowed:
                raise AssertionError(
                    f"objective degraded beyond tolerance: current={metrics['objective']} baseline={baseline_obj} max={max_allowed}"
                )


def _maybe_update_baseline(metrics: dict[str, Any], update_baseline: bool) -> None:
    if not update_baseline:
        return
    BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
    BASELINE_PATH.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")


def _append_benchmark(metrics: dict[str, Any]) -> None:
    OUTPUTS_META.mkdir(parents=True, exist_ok=True)
    bench_path = OUTPUTS_META / "platform_benchmark_history.jsonl"
    with bench_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(metrics, ensure_ascii=False) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Minimum semantic regression + benchmark for joint mode")
    parser.add_argument("--config", default=str(REPO_ROOT / "scheduler" / "config" / "io.yaml"))
    parser.add_argument("--time-limit-seconds", type=int, default=30)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--objective-tolerance-ratio", type=float, default=0.10)
    parser.add_argument("--update-baseline", action="store_true")
    args = parser.parse_args()

    config = Path(args.config)
    if not config.is_absolute():
        config = (REPO_ROOT / config).resolve()

    _run_joint(config, int(args.time_limit_seconds), int(args.seed))
    _assert_required_artifacts()
    metrics = _extract_metrics()
    _assert_metrics(metrics, float(args.objective_tolerance_ratio))
    _maybe_update_baseline(metrics, bool(args.update_baseline))
    _append_benchmark(metrics)

    print("regression_semantic_min: PASS")
    print(json.dumps(metrics, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    raise SystemExit(main())
