from __future__ import annotations

import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


from scheduler.app.diagnostic_comparison import build_diagnostic_comparison


def _write_status(run_dir: Path, payload: dict) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "status.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_diagnostic_comparison_flags_weight_only_repricing(tmp_path: Path) -> None:
    web_runs = tmp_path / "outputs" / "web_runs"
    baseline_dir = web_runs / "run_20260512_024137"
    diagnostic_dir = web_runs / "run_20260512_031757_lang_tune_diag"
    baseline = {
        "run_id": baseline_dir.name,
        "run_dir": str(baseline_dir),
        "run_purpose": "",
        "status": "completed",
        "started_at": "2026-05-12 02:41:37",
        "solver_status": "FEASIBLE",
        "objective_value": 341200,
        "best_bound": 86820,
        "objective_gap": 254380,
        "gap_percent": 74.55451348182885,
        "optimality_status": "gap_remaining",
        "objective_breakdown": {
            "summary": {"total_penalty": 367900},
            "top": [
                {
                    "rule_id": "lang_tue_fri_pm2_penalty",
                    "rule_name": "语文外语周二至周五下午2惩罚",
                    "penalty_sum": 54000,
                    "count": 18,
                    "share": 14.7,
                },
                {
                    "rule_id": "lang_tue_fri_pm3_penalty",
                    "rule_name": "语文外语周二至周五下午3惩罚",
                    "penalty_sum": 48000,
                    "count": 24,
                    "share": 13.0,
                },
            ],
        },
    }
    diagnostic = {
        "run_id": diagnostic_dir.name,
        "run_dir": str(diagnostic_dir),
        "run_purpose": "diagnostic_trial",
        "status": "completed",
        "started_at": "2026-05-12 03:17:57",
        "solver_status": "FEASIBLE",
        "objective_value": 296100,
        "best_bound": 55220,
        "objective_gap": 240880,
        "gap_percent": 81.35089496791625,
        "optimality_status": "gap_remaining",
        "active_diagnostic_relaxations": [
            {
                "id": "tune.lang_tue_fri_pm_penalty",
                "patches": [
                    {"target": "io", "path_label": "day.weekday_constraints.w_lang_tue_fri_pm2_penalty"},
                    {"target": "io", "path_label": "day.weekday_constraints.w_lang_tue_fri_pm3_penalty"},
                ],
            }
        ],
        "objective_breakdown": {
            "summary": {"total_penalty": 322800},
            "top": [
                {
                    "rule_id": "lang_tue_fri_pm2_penalty",
                    "rule_name": "语文外语周二至周五下午2惩罚",
                    "penalty_sum": 27000,
                    "count": 18,
                    "share": 8.4,
                },
                {
                    "rule_id": "lang_tue_fri_pm3_penalty",
                    "rule_name": "语文外语周二至周五下午3惩罚",
                    "penalty_sum": 24000,
                    "count": 24,
                    "share": 7.4,
                },
            ],
        },
    }
    _write_status(baseline_dir, baseline)
    diagnostic_dir.mkdir(parents=True)

    comparison = build_diagnostic_comparison(diagnostic, tmp_path)

    assert comparison["schema_version"] == "scheduler.diagnostic_comparison.v1"
    assert comparison["summary"]["status"] == "warning"
    assert comparison["summary"]["status_label"] == "仅重定价"
    assert comparison["objective_comparable"] is False
    assert comparison["objective_delta"] == -45100
    assert round(comparison["gap_percent_delta"], 2) == 6.8
    assert comparison["baseline"]["run_id"] == baseline_dir.name
    assert comparison["diagnostic"]["run_id"] == diagnostic_dir.name
    pm2 = next(item for item in comparison["top_changes"] if item["rule_id"] == "lang_tue_fri_pm2_penalty")
    assert pm2["adjusted"] is True
    assert pm2["baseline_count"] == 18
    assert pm2["diagnostic_count"] == 18
    assert pm2["count_delta"] == 0
    assert pm2["penalty_delta"] == -27000
