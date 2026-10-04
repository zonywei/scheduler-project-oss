from __future__ import annotations

import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


from scheduler.app.publish_assessment import build_publish_assessment
from scheduler.app.solve_diagnostics import build_solve_diagnostics


def _file_item(path: Path, label: str) -> dict:
    return {
        "label": label,
        "path": str(path),
        "size": path.stat().st_size,
        "modified_at": "2026-05-06 08:00:00",
    }


def test_publish_assessment_parses_solver_status_with_spaces() -> None:
    assessment = build_publish_assessment(
        {
            "status": "completed",
            "log_tail": "status = INFEASIBLE\n回调捕获解数量：0",
            "files": [],
        },
        {"summary": {"can_publish": True, "warnings": 0, "errors": 0}},
    )

    assert assessment["outcome"]["solver_status"] == "INFEASIBLE"
    assert any(gate["title"] == "规则组合不可行" for gate in assessment["gates"])


def test_solve_diagnostics_prioritizes_infeasible_hint_files(tmp_path: Path) -> None:
    diag_dir = tmp_path / "outputs" / "诊断"
    diag_dir.mkdir(parents=True)
    joint = diag_dir / "联合求解_不可行提示_1.txt"
    joint.write_text(
        "[Joint Infeasible Hints]\n"
        "可能冲突来源：\n"
        "- 联动硬约束：周日+周日晚自习 与 周一上午1/2 禁止组合\n"
        "- 联动硬约束：白天无课不得安排晚自习/晚查寝\n",
        encoding="utf-8",
    )
    low = diag_dir / "白天_周中少课学科每日上限_1.txt"
    low.write_text("[Low Weekday Subject Max1 Per Day]\nTotalHits=68\n", encoding="utf-8")
    status = {
        "status": "completed",
        "log_tail": "status = INFEASIBLE\n回调捕获解数量：0",
        "files": [
            _file_item(joint, "outputs/诊断/联合求解_不可行提示_1.txt"),
            _file_item(low, "outputs/诊断/白天_周中少课学科每日上限_1.txt"),
        ],
    }

    diagnostics = build_solve_diagnostics(status, project_root=tmp_path)

    assert diagnostics["summary"]["status"] == "blocked"
    assert diagnostics["summary"]["errors"] >= 2
    titles = [issue["title"] for issue in diagnostics["issues"]]
    assert titles[0] == "求解器判定规则组合不可行"
    assert "联合求解 不可行提示" in titles
    assert any(issue["severity"] == "warning" and "68" in issue["detail"] for issue in diagnostics["issues"])
    assert diagnostics["next_actions"][0]["severity"] == "error"
    plan_ids = {plan["id"] for plan in diagnostics["relaxation_plans"]}
    assert "relax.day_night_link" in plan_ids
    assert "relax.low_hour_subject_daily_cap" in plan_ids
    day_night_plan = next(plan for plan in diagnostics["relaxation_plans"] if plan["id"] == "relax.day_night_link")
    assert {patch["path_label"] for patch in day_night_plan["patches"]} == {
        "day_night_link.night_requires_day_mode",
        "day_night_link.sun_night_no_mon_am1_mode",
        "day_night_link.sun_pm_night_no_mon_am_mode",
    }


def test_solve_diagnostics_warns_when_feasible_gap_remains() -> None:
    diagnostics = build_solve_diagnostics(
        {
            "status": "completed",
            "log_tail": "status = FEASIBLE\n回调捕获解数量：1",
            "objective_value": 100,
            "best_bound": 70,
            "files": [],
        },
        project_root=REPO_ROOT,
    )

    assert diagnostics["summary"]["status"] == "review"
    quality_issue = next(issue for issue in diagnostics["issues"] if issue["domain"] == "求解质量")
    assert quality_issue["severity"] == "warning"
    assert "尚未证明全局最优" in quality_issue["title"]
    assert "30.00%" in quality_issue["detail"]
    quality_plan = diagnostics["quality_plan"]
    assert quality_plan["status"] == "recommended"
    assert quality_plan["current"]["objective_gap"] == 30.0
    assert [step["id"] for step in quality_plan["steps"]] == [
        "quality.improve_incumbent",
        "quality.prove_bound",
        "quality.strict_gap_5pct",
    ]
    improve = quality_plan["steps"][0]["start_solve_payload"]
    assert improve["solver_profile"] == "improve_incumbent"
    assert improve["continue_from_best"] is True
    assert improve["time_limit_seconds"] == 600
    prove = quality_plan["steps"][1]["start_solve_payload"]
    assert prove["solver_profile"] == "prove_bound"
    assert prove["log_search_progress"] is True


def test_quality_plan_skips_seed_attempts_already_tried(tmp_path: Path) -> None:
    improve_status = tmp_path / "outputs" / "web_runs" / "run_improve_10" / "status.json"
    improve_status.parent.mkdir(parents=True)
    improve_status.write_text(
        json.dumps(
            {
                "run_id": "run_improve_10",
                "solver_profile": "improve_incumbent",
                "random_seed": 10,
                "best_objective": 125,
                "best_bound": 80,
                "objective_gap": 45,
                "completed_at": "2026-05-12 10:00:00",
                "config_fingerprint": {"hash": "same-config"},
            }
        ),
        encoding="utf-8",
    )
    prove_status = tmp_path / "outputs" / "web_runs" / "run_prove_9" / "status.json"
    prove_status.parent.mkdir(parents=True)
    prove_status.write_text(
        json.dumps(
            {
                "run_id": "run_prove_9",
                "solver_profile": "prove_bound",
                "random_seed": 9,
                "best_objective": 130,
                "best_bound": 82,
                "objective_gap": 48,
                "completed_at": "2026-05-12 10:30:00",
                "config_fingerprint": {"hash": "same-config"},
            }
        ),
        encoding="utf-8",
    )
    unlisted_status = tmp_path / "outputs" / "web_runs" / "run_improve_11" / "status.json"
    unlisted_status.parent.mkdir(parents=True)
    unlisted_status.write_text(
        json.dumps(
            {
                "run_id": "run_improve_11",
                "solver_profile": "improve_incumbent",
                "random_seed": 11,
                "best_objective": 128,
                "best_bound": 83,
                "objective_gap": 45,
                "completed_at": "2026-05-12 11:00:00",
                "config_fingerprint": {"hash": "same-config"},
            }
        ),
        encoding="utf-8",
    )

    diagnostics = build_solve_diagnostics(
        {
            "status": "completed",
            "solver_status": "FEASIBLE",
            "solution_count": 1,
            "run_id": "current_best",
            "objective_value": 100,
            "best_bound": 70,
            "random_seed": 9,
            "solver_profile": "improve_incumbent",
            "config_fingerprint": {"hash": "same-config"},
            "recommended_formal_candidate": {
                "config_hash": "same-config",
                "candidate": {
                    "run_id": "current_best",
                    "solver_profile": "improve_incumbent",
                    "random_seed": 9,
                },
                "alternatives": [
                    {"status_file": str(improve_status)},
                    {"status_file": str(prove_status)},
                ],
            },
            "files": [],
        },
        project_root=tmp_path,
    )

    quality_plan = diagnostics["quality_plan"]
    payloads = {step["id"]: step["start_solve_payload"] for step in quality_plan["steps"]}
    assert payloads["quality.improve_incumbent"]["random_seed"] == 12
    assert payloads["quality.prove_bound"]["random_seed"] == 10
    assert payloads["quality.strict_gap_5pct"]["random_seed"] == 11
    assert quality_plan["current"]["attempt_count"] == 4
    assert {row["run_id"] for row in quality_plan["current"]["attempt_history"]} == {
        "current_best",
        "run_improve_10",
        "run_improve_11",
        "run_prove_9",
    }


def test_solve_diagnostics_turns_objective_breakdown_into_actions() -> None:
    diagnostics = build_solve_diagnostics(
        {
            "status": "completed",
            "solver_status": "FEASIBLE",
            "solution_count": 1,
            "objective_value": 341200,
            "best_bound": 86820,
            "objective_breakdown": {
                "schema_version": "scheduler.result_rule_explain.v1",
                "summary": {
                    "status": "warning",
                    "total_penalty": 367900,
                    "reward_credit": 7200,
                    "net_event_penalty": 360700,
                    "solver_objective_value": 341200,
                    "objective_explain_delta": -19500,
                    "objective_reconciliation_status": "unmatched",
                    "source": str(REPO_ROOT / "outputs" / "event_log.csv"),
                    "source_label": "outputs/event_log.csv",
                },
                "top": [
                    {
                        "rank": 1,
                        "rule_id": "lang_tue_fri_pm2_penalty",
                        "rule_name": "语文外语周二至周五下午2惩罚",
                        "penalty_sum": 54000,
                        "share": 14.7,
                        "top_offenders": [{"entity": "教师A", "penalty_sum": 12000}],
                        "action": "核对该学科在对应星期和节次的偏好是否过强。",
                    },
                    {
                        "rank": 2,
                        "rule_id": "night_checkin_need_same_day_class",
                        "rule_name": "晚查寝教师需当日有晚自习",
                        "penalty_sum": 40000,
                        "share": 10.9,
                        "top_offenders": [{"entity": "严昆", "penalty_sum": 40000}],
                        "action": "优先补充同日可用候选。",
                    },
                    {
                        "rank": 3,
                        "rule_id": "night_subject_sync",
                        "rule_name": "同学科同步偏好",
                        "penalty_sum": 34000,
                        "share": 9.2,
                        "top_offenders": [{"entity": "GLOBAL", "penalty_sum": 34000}],
                        "action": "核对晚自习同学科同步规则。",
                    },
                ],
            },
            "files": [],
        },
        project_root=REPO_ROOT,
    )

    assert diagnostics["summary"]["status"] == "review"
    titles = [issue["title"] for issue in diagnostics["issues"]]
    assert "目标值解释未完全对账" in titles
    assert "主导软约束代价：语文外语周二至周五下午2惩罚" in titles
    assert "主导软约束代价：晚查寝教师需当日有晚自习" in titles
    lang_issue = next(issue for issue in diagnostics["issues"] if issue["domain"] == "学科时段偏好")
    assert "54000" in lang_issue["detail"]
    assert "教师A(12000)" in lang_issue["detail"]
    sync_issue = next(issue for issue in diagnostics["issues"] if issue["title"] == "主导软约束代价：同学科同步偏好")
    assert "全局规则(34000)" in sync_issue["detail"]
    assert "GLOBAL" not in sync_issue["detail"]
    plan_ids = {plan["id"] for plan in diagnostics["relaxation_plans"]}
    assert "tune.lang_tue_fri_pm_penalty" in plan_ids
    assert "relax.checkin_same_day_class" in plan_ids
    lang_plan = next(plan for plan in diagnostics["relaxation_plans"] if plan["id"] == "tune.lang_tue_fri_pm_penalty")
    assert {patch["path_label"] for patch in lang_plan["patches"]} == {
        "day.weekday_constraints.w_lang_tue_fri_pm1_penalty",
        "day.weekday_constraints.w_lang_tue_fri_pm2_penalty",
        "day.weekday_constraints.w_lang_tue_fri_pm3_penalty",
    }


def test_solve_diagnostics_explains_checkin_supply_floor() -> None:
    diagnostics = build_solve_diagnostics(
        {
            "status": "completed",
            "solver_status": "FEASIBLE",
            "solution_count": 1,
            "objective_value": 193050,
            "best_bound": 135600,
            "objective_breakdown": {
                "summary": {"total_penalty": 193050},
                "top": [
                    {
                        "rule_id": "night_checkin_need_same_day_class",
                        "rule_name": "晚查寝教师需当日有晚自习",
                        "penalty_sum": 40000,
                        "share": 20.7,
                    }
                ],
            },
            "publish_assessment": {
                "gates": [
                    {
                        "key": "晚查寝策略|存在当天无晚自习查寝安排",
                        "checkin_supply_ledger": [
                            {
                                "day": "星期五",
                                "gender": "男",
                                "assigned_teachers": ["肖祥宠"],
                                "shortage": 1,
                                "potential_penalty_reduction": 20000,
                                "suggested_candidates": ["万晶晶", "席斯颖"],
                            },
                            {
                                "day": "星期日",
                                "gender": "男",
                                "assigned_teachers": ["严昆"],
                                "shortage": 1,
                                "potential_penalty_reduction": 20000,
                                "suggested_candidates": ["周波", "刘靖"],
                            },
                        ],
                    }
                ]
            },
            "files": [],
        },
        project_root=REPO_ROOT,
    )

    note = diagnostics["business_floor_notes"][0]
    assert note["id"] == "business_floor.checkin_same_day_supply"
    assert note["penalty_sum"] == 40000
    assert note["shortage_count"] == 2
    assert note["potential_penalty_reduction"] == 40000
    assert note["assigned_teachers"] == ["严昆", "肖祥宠"]
    assert "新增/确认候选" in note["message"]
    assert note["ledger"][0]["day"] == "星期五"
    adjusted = diagnostics["business_floor_adjusted_quality"]
    assert adjusted["status"] == "action_required"
    assert adjusted["raw_objective_gap"] == 57450.0
    assert adjusted["business_floor_gap_explained"] == 40000.0
    assert adjusted["adjusted_objective_gap"] == 17450.0
    assert round(adjusted["adjusted_gap_percent"], 2) == 9.04
    assert adjusted["business_floor_note_ids"] == ["business_floor.checkin_same_day_supply"]
    assert adjusted["business_floor_note_summaries"][0]["pending_candidates"] == ["万晶晶", "刘靖", "周波", "席斯颖"]
    assert adjusted["business_floor_note_summaries"][0]["ledger"][0]["day"] == "星期五"
    assert adjusted["business_floor_note_summaries"][0]["ledger"][0]["suggested_candidates"] == ["万晶晶", "席斯颖"]
    assert "至少 40000" in adjusted["message"]
    quality_issue = next(issue for issue in diagnostics["issues"] if issue["domain"] == "求解质量")
    assert "业务下限解释" in quality_issue["detail"]
    assert "剩余缺口约 17450" in quality_issue["detail"]
    quality_plan = diagnostics["quality_plan"]
    assert "业务人力或规则口径" in quality_plan["message"]
    assert quality_plan["status_label"] == "先处理业务下限"
    assert quality_plan["current"]["business_floor_adjusted_quality"]["adjusted_objective_gap"] == 17450.0
    assert [step["id"] for step in quality_plan["steps"]] == [
        "quality.resolve_business_floor",
        "quality.improve_incumbent",
        "quality.prove_bound",
        "quality.strict_gap_5pct",
    ]
    business_step = quality_plan["steps"][0]
    assert "继续求解前先把这些事项补充" in business_step["purpose"]
    assert business_step["manual_action"]["business_floor_gap_explained"] == 40000.0
    assert business_step["manual_action"]["adjusted_objective_gap"] == 17450.0
    assert business_step["manual_action"]["business_floor_note_ids"] == ["business_floor.checkin_same_day_supply"]
    assert business_step["manual_action"]["business_floor_note_summaries"][0]["days"] == ["星期五", "星期日"]


def test_solve_diagnostics_uses_stronger_proof_for_business_floor_gap() -> None:
    diagnostics = build_solve_diagnostics(
        {
            "status": "completed",
            "solver_status": "FEASIBLE",
            "solution_count": 1,
            "objective_value": 120,
            "best_bound": 70,
            "objective_gap": 30,
            "gap_percent": 25,
            "recommended_formal_candidate": {
                "candidate": {
                    "run_id": "run_candidate",
                    "objective_value": 100,
                    "best_bound": 70,
                    "objective_gap": 30,
                },
                "quality_evidence": {
                    "summary": {
                        "status": "bound_improved",
                        "proof_run_id": "run_proof",
                        "proof_best_bound": 75,
                        "candidate_objective_gap": 25,
                        "candidate_gap_percent": 25,
                    }
                }
            },
            "objective_breakdown": {
                "summary": {"total_penalty": 100},
                "top": [
                    {
                        "rule_id": "night_checkin_need_same_day_class",
                        "rule_name": "晚查寝教师需当日有晚自习",
                        "penalty_sum": 20,
                        "share": 20,
                    }
                ],
            },
            "publish_assessment": {
                "gates": [
                    {
                        "key": "晚查寝策略|存在当天无晚自习查寝安排",
                        "checkin_supply_ledger": [
                            {
                                "day": "星期五",
                                "gender": "男",
                                "assigned_teachers": ["李政"],
                                "shortage": 1,
                                "potential_penalty_reduction": 20,
                                "suggested_candidates": ["周波"],
                            }
                        ],
                    }
                ]
            },
            "files": [],
        },
        project_root=REPO_ROOT,
    )

    adjusted = diagnostics["business_floor_adjusted_quality"]
    assert adjusted["gap_basis"] == "stronger_proof_bound"
    assert adjusted["raw_objective_gap"] == 30.0
    assert adjusted["basis_objective_value"] == 100.0
    assert adjusted["basis_objective_gap"] == 25.0
    assert adjusted["basis_best_bound"] == 75.0
    assert adjusted["business_floor_gap_explained"] == 20.0
    assert adjusted["adjusted_objective_gap"] == 5.0
    assert adjusted["adjusted_gap_percent"] == 5.0
    assert adjusted["stronger_bound_proof"]["run_id"] == "run_proof"
    assert "更强证明界" in adjusted["message"]
    assert "run_proof" not in adjusted["message"]
    quality_issue = next(issue for issue in diagnostics["issues"] if issue["domain"] == "求解质量")
    assert "推荐正式候选目标值 100" in quality_issue["detail"]
    assert "当前可复核缺口为 25" in quality_issue["detail"]
    assert "剩余缺口约 5" in quality_issue["detail"]
    assert "run_proof" not in quality_issue["detail"]


def test_solve_diagnostics_uses_structured_status_when_log_tail_missing() -> None:
    diagnostics = build_solve_diagnostics(
        {
            "status": "completed",
            "solver_status": "INFEASIBLE",
            "solution_count": 0,
            "log_tail": "",
            "files": [],
        },
        project_root=REPO_ROOT,
    )

    assert diagnostics["summary"]["status"] == "blocked"
    assert diagnostics["summary"]["errors"] >= 2
    titles = [issue["title"] for issue in diagnostics["issues"]]
    assert "求解器判定规则组合不可行" in titles
    assert "本批次未捕获可行解" in titles


def test_solve_diagnostics_reads_quality_gap_from_final_solver_overview(tmp_path: Path) -> None:
    overview = tmp_path / "final_solver_overview.json"
    overview.write_text(
        json.dumps(
            {
                "solver_status": "FEASIBLE",
                "objective_value": 200,
                "best_bound": 150,
                "solutions_seen": 1,
            }
        ),
        encoding="utf-8",
    )

    diagnostics = build_solve_diagnostics(
        {
            "status": "completed",
            "log_tail": "",
            "files": [_file_item(overview, "outputs/final_solver_overview.json")],
        },
        project_root=tmp_path,
    )

    assert diagnostics["summary"]["status"] == "review"
    quality_issue = next(issue for issue in diagnostics["issues"] if issue["domain"] == "求解质量")
    assert quality_issue["severity"] == "warning"
    assert "50.0" in quality_issue["detail"]
    assert "25.00%" in quality_issue["detail"]


def test_solve_diagnostics_ignores_files_outside_project_root(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside_hint.txt"
    outside.write_text("- 不应读取", encoding="utf-8")
    status = {
        "status": "idle",
        "log_tail": "",
        "files": [_file_item(outside, "outputs/诊断/联合求解_不可行提示_1.txt")],
    }

    diagnostics = build_solve_diagnostics(status, project_root=tmp_path)

    assert diagnostics["summary"]["evidence_files"] == 0
    assert diagnostics["issues"] == []


def test_solve_diagnostics_suggests_head_duty_checkin_chain_relaxation(tmp_path: Path) -> None:
    diag_dir = tmp_path / "outputs" / "诊断"
    diag_dir.mkdir(parents=True)
    hint = diag_dir / "班主任值班_不可行提示_1.txt"
    hint.write_text(
        "[Head Duty Infeasible Hints]\n"
        "- 班主任值班每楼层人数需求可能过紧\n"
        "- 晚查寝联动硬约束可能进一步压缩值班教师集合\n",
        encoding="utf-8",
    )
    status = {
        "status": "completed",
        "log_tail": "status = INFEASIBLE\n回调捕获解数量：0",
        "files": [_file_item(hint, "outputs/诊断/班主任值班_不可行提示_1.txt")],
    }

    diagnostics = build_solve_diagnostics(status, project_root=tmp_path)

    same_day_plan = next(
        item for item in diagnostics["relaxation_plans"] if item["id"] == "relax.checkin_same_day_class"
    )
    assert same_day_plan["domain"] == "晚查寝"
    assert {patch["path_label"] for patch in same_day_plan["patches"]} == {
        "checkin.require_teacher_has_class_that_day_mode",
        "checkin.w_require_teacher_has_class_that_day",
    }
    checkin_plan = next(item for item in diagnostics["relaxation_plans"] if item["id"] == "relax.checkin_only")
    assert checkin_plan["domain"] == "晚查寝"
    assert [patch["path_label"] for patch in checkin_plan["patches"]] == ["checkin.enabled"]
    plan = next(
        item for item in diagnostics["relaxation_plans"] if item["id"] == "relax.head_duty_checkin_chain"
    )
    assert plan["domain"] == "值班规则"
    assert {patch["path_label"] for patch in plan["patches"]} == {
        "day.head_duty_constraints.enable_head_duty",
        "checkin.enabled",
    }


def test_night_infeasible_log_suggests_checkin_same_day_probe() -> None:
    status = {
        "status": "completed",
        "mode": "night",
        "log_tail": "求解状态：INFEASIBLE\n回调捕获解数量：0",
        "files": [],
    }

    diagnostics = build_solve_diagnostics(status, project_root=REPO_ROOT)

    plan_ids = [plan["id"] for plan in diagnostics["relaxation_plans"]]
    assert plan_ids[:2] == ["relax.checkin_same_day_class", "relax.checkin_only"]
