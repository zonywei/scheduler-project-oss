from __future__ import annotations

import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


from scheduler.app.formal_run_history import build_formal_run_comparison, build_recommended_formal_candidate  # noqa: E402


def _write_status(
    root: Path,
    run_id: str,
    *,
    objective: float,
    config_hash: str = "hash-a",
    best_bound: float = 100.0,
) -> dict:
    run_dir = root / "outputs" / "web_runs" / run_id
    run_dir.mkdir(parents=True)
    status = {
        "run_id": run_id,
        "status": "completed",
        "solver_status": "FEASIBLE",
        "objective_value": objective,
        "best_bound": best_bound,
        "objective_gap": objective - best_bound,
        "gap_percent": round((objective - best_bound) / objective * 100, 2),
        "completed_at": "2026-05-12 04:00:00",
        "run_dir": str(run_dir),
        "package_file": str(run_dir / "result_package.zip"),
        "config_fingerprint": {"hash": config_hash, "mode": "joint"},
        "publish_assessment": {"summary": {"status": "ready"}},
    }
    (run_dir / "status.json").write_text(json.dumps(status, ensure_ascii=False), encoding="utf-8")
    return status


def test_formal_run_comparison_flags_regression_against_same_config_prior(tmp_path: Path) -> None:
    _write_status(tmp_path, "run_20260512_010000", objective=341200.0)
    current = _write_status(tmp_path, "run_20260512_020000", objective=426570.0)

    comparison = build_formal_run_comparison(current, tmp_path)

    assert comparison["summary"]["status"] == "regressed"
    assert comparison["best_prior"]["run_id"] == "run_20260512_010000"
    assert comparison["best_prior"]["objective_value"] == 341200.0
    assert comparison["delta_objective"] == 85370.0
    assert "不应自动替代" in comparison["summary"]["message"]


def test_formal_run_history_follows_current_tenant_run_directory(tmp_path: Path) -> None:
    tenant_root = tmp_path / "outputs" / "tenants" / "school-a"
    prior = _write_status(tenant_root, "run_20260512_010000", objective=100.0)
    current = _write_status(tenant_root, "run_20260512_020000", objective=200.0)
    _write_status(tmp_path, "run_20260512_000000", objective=1.0)

    comparison = build_formal_run_comparison(current, tmp_path)

    assert comparison["summary"]["status"] == "regressed"
    assert comparison["best_prior"]["run_id"] == prior["run_id"]


def test_formal_run_comparison_ignores_different_config_hash(tmp_path: Path) -> None:
    _write_status(tmp_path, "run_20260512_010000", objective=341200.0, config_hash="old")
    current = _write_status(tmp_path, "run_20260512_020000", objective=426570.0, config_hash="new")

    comparison = build_formal_run_comparison(current, tmp_path)

    assert comparison["summary"]["status"] == "no_comparable_prior"
    assert comparison["best_prior"] == {}


def test_recommended_formal_candidate_keeps_historical_best_when_current_regresses(tmp_path: Path) -> None:
    _write_status(tmp_path, "run_20260512_010000", objective=341200.0)
    current = _write_status(tmp_path, "run_20260512_020000", objective=426570.0)

    recommendation = build_recommended_formal_candidate(current, tmp_path)

    assert recommendation["summary"]["status"] == "historical_best"
    assert recommendation["summary"]["selected_run_id"] == "run_20260512_010000"
    assert recommendation["candidate"]["objective_value"] == 341200.0
    assert recommendation["current"]["run_id"] == "run_20260512_020000"


def test_recommended_formal_candidate_selects_current_when_it_improves(tmp_path: Path) -> None:
    _write_status(tmp_path, "run_20260512_010000", objective=426570.0)
    current = _write_status(tmp_path, "run_20260512_020000", objective=341200.0)

    recommendation = build_recommended_formal_candidate(current, tmp_path)

    assert recommendation["summary"]["status"] == "current_best"
    assert recommendation["summary"]["selected_run_id"] == "run_20260512_020000"
    assert recommendation["candidate"]["objective_value"] == 341200.0


def test_recommended_formal_candidate_uses_current_config_hash(tmp_path: Path) -> None:
    _write_status(tmp_path, "run_20260512_010000", objective=100.0, config_hash="old")
    current = _write_status(tmp_path, "run_20260512_020000", objective=200.0, config_hash="new")

    recommendation = build_recommended_formal_candidate(current, tmp_path)

    assert recommendation["summary"]["status"] == "current_best"
    assert recommendation["summary"]["candidate_count"] == 1
    assert recommendation["candidate"]["run_id"] == "run_20260512_020000"


def test_recommended_formal_candidate_keeps_bound_evidence_from_nonselected_run(tmp_path: Path) -> None:
    _write_status(tmp_path, "run_20260512_010000", objective=200.0, best_bound=90.0)
    current = _write_status(tmp_path, "run_20260512_020000", objective=220.0, best_bound=150.0)

    recommendation = build_recommended_formal_candidate(current, tmp_path)

    assert recommendation["summary"]["status"] == "historical_best"
    assert recommendation["summary"]["selected_run_id"] == "run_20260512_010000"
    quality = recommendation["quality_evidence"]
    assert quality["summary"]["status"] == "bound_improved"
    assert quality["summary"]["proof_run_id"] == "run_20260512_020000"
    assert quality["summary"]["proof_best_bound"] == 150.0
    assert quality["summary"]["candidate_objective_gap"] == 50.0
    assert quality["summary"]["candidate_gap_percent"] == 25.0
    assert quality["summary"]["bound_improvement_over_candidate_run"] == 60.0
