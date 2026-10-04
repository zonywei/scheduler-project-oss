from __future__ import annotations

import json
import sys
from pathlib import Path

from openpyxl import Workbook


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


from scheduler.app.publish_assessment import build_publish_assessment


def _readiness(*, can_publish: bool = True, warnings: int = 0, errors: int = 0) -> dict:
    return {
        "summary": {
            "can_publish": can_publish,
            "warnings": warnings,
            "errors": errors,
            "message": "校验完成",
        }
    }


def test_publish_assessment_allows_complete_result_with_required_artifacts(tmp_path: Path) -> None:
    package = tmp_path / "result_package.zip"
    package.write_text("zip", encoding="utf-8")
    status = {
        "status": "completed",
        "mode": "joint",
        "package_file": str(package),
        "log_tail": "多解输出完成：run_dir=x, top_count=1, best=课表.xlsx, diagnostics=诊断.xlsx",
        "files": [
            {"label": "outputs/课表及值班安排.xlsx", "path": str(tmp_path / "课表及值班安排.xlsx")},
            {"label": "outputs/诊断/约束审计.txt", "path": str(tmp_path / "约束审计.txt")},
        ],
        "config_fingerprint": {"hash": "a" * 64},
        "current_config_fingerprint": {"hash": "a" * 64},
        "config_fingerprint_match": True,
    }

    assessment = build_publish_assessment(status, _readiness())

    assert assessment["summary"]["status"] == "ready"
    assert assessment["summary"]["can_publish"] is True
    assert assessment["file_categories"]["schedule"] == 1
    assert assessment["file_categories"]["diagnostic"] == 1
    assert assessment["outcome"]["solution_count"] == 1


def test_publish_assessment_blocks_failed_result() -> None:
    assessment = build_publish_assessment(
        {
            "status": "failed",
            "message": "未读取到班主任名单",
            "files": [{"label": "outputs/run.log", "path": "run.log"}],
        },
        _readiness(can_publish=False, errors=1),
    )

    assert assessment["summary"]["status"] == "blocked"
    titles = {gate["title"] for gate in assessment["gates"] if gate["severity"] == "error"}
    assert "求解失败" in titles
    assert "缺少课表文件" in titles
    assert "发布校验未通过" in titles


def test_publish_assessment_blocks_completed_run_without_solution_or_schedule() -> None:
    assessment = build_publish_assessment(
        {
            "status": "completed",
            "log_tail": "多解输出完成：run_dir=x, top_count=0, best=, diagnostics=",
            "files": [{"label": "outputs/诊断/约束审计.txt", "path": "约束审计.txt"}],
        },
        _readiness(),
    )

    assert assessment["summary"]["status"] == "blocked"
    assert any(gate["title"] == "未捕获可行解" for gate in assessment["gates"])
    assert any(gate["title"] == "缺少课表文件" for gate in assessment["gates"])


def test_publish_assessment_treats_formal_best_workbook_as_schedule() -> None:
    assessment = build_publish_assessment(
        {
            "status": "completed",
            "log_tail": "status = FEASIBLE\n回调捕获解数量：1",
            "files": [
                {
                    "label": "outputs/web_runs/run_x/solutions/best/最终全局最优解_正式版.xlsx",
                    "path": "最终全局最优解_正式版.xlsx",
                },
                {"label": "outputs/诊断/约束审计.txt", "path": "约束审计.txt"},
            ],
        },
        _readiness(),
    )

    assert assessment["file_categories"]["schedule"] == 1
    assert not any(gate["title"] == "缺少课表文件" for gate in assessment["gates"])


def test_publish_assessment_prefers_numeric_best_objective_over_best_file_path(tmp_path: Path) -> None:
    summary_path = tmp_path / "run_summary.json"
    summary_path.write_text('{"best_objective": 541950.0, "captured": 1}', encoding="utf-8")

    assessment = build_publish_assessment(
        {
            "status": "completed",
            "log_tail": r"status = FEASIBLE\nbest=C:\runs\best\最终全局最优解.xlsx",
            "files": [
                {"label": "outputs/run_summary.json", "path": str(summary_path)},
                {"label": "outputs/课表及值班安排.xlsx", "path": str(tmp_path / "课表.xlsx")},
                {"label": "outputs/诊断/约束审计.txt", "path": str(tmp_path / "约束审计.txt")},
            ],
            "config_fingerprint": {"hash": "a" * 64},
            "current_config_fingerprint": {"hash": "a" * 64},
            "config_fingerprint_match": True,
        },
        _readiness(),
    )

    assert assessment["outcome"]["best_objective"] == "541950.0"


def test_publish_assessment_requires_review_when_feasible_gap_remains(tmp_path: Path) -> None:
    package = tmp_path / "result_package.zip"
    package.write_text("zip", encoding="utf-8")

    assessment = build_publish_assessment(
        {
            "status": "completed",
            "mode": "joint",
            "package_file": str(package),
            "log_tail": "status = FEASIBLE\n回调捕获解数量：1",
            "objective_value": 100,
            "best_bound": 70,
            "files": [
                {"label": "outputs/课表及值班安排.xlsx", "path": str(tmp_path / "课表.xlsx")},
                {"label": "outputs/诊断/约束审计.txt", "path": str(tmp_path / "约束审计.txt")},
            ],
            "config_fingerprint": {"hash": "a" * 64},
            "current_config_fingerprint": {"hash": "a" * 64},
            "config_fingerprint_match": True,
        },
        _readiness(),
    )

    assert assessment["summary"]["status"] == "ready"
    quality_gate = next(item for item in assessment["gates"] if item["domain"] == "求解质量")
    assert quality_gate["severity"] == "warning"
    assert "尚未证明全局最优" in quality_gate["title"]
    assert "30.00%" in quality_gate["detail"]
    assert {point["label"] for point in quality_gate["decision_points"]} == {"目标值", "最优界", "最优性缺口", "建议动作"}
    gap_point = next(point for point in quality_gate["decision_points"] if point["label"] == "最优性缺口")
    assert gap_point["value"] == "30.0（约 30.00%）"
    assert "release_preflight" not in assessment
    assert "review_confirmation" not in assessment


def test_publish_assessment_shows_stronger_bound_proof_when_available(tmp_path: Path) -> None:
    package = tmp_path / "result_package.zip"
    package.write_text("zip", encoding="utf-8")

    assessment = build_publish_assessment(
        {
            "status": "completed",
            "mode": "joint",
            "package_file": str(package),
            "log_tail": "status = FEASIBLE\n回调捕获解数量：1",
            "objective_value": 120,
            "best_bound": 90,
            "objective_gap": 30,
            "gap_percent": 25,
            "recommended_formal_candidate": {
                "candidate": {"run_id": "run_candidate", "objective_value": 100, "best_bound": 70, "objective_gap": 30},
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
            "files": [
                {"label": "outputs/课表及值班安排.xlsx", "path": str(tmp_path / "课表.xlsx")},
                {"label": "outputs/诊断/约束审计.txt", "path": str(tmp_path / "约束审计.txt")},
            ],
            "config_fingerprint": {"hash": "a" * 64},
            "current_config_fingerprint": {"hash": "a" * 64},
            "config_fingerprint_match": True,
        },
        _readiness(),
    )

    quality_gate = next(item for item in assessment["gates"] if item["domain"] == "求解质量")
    assert "推荐正式候选目标值 100" in quality_gate["detail"]
    assert "同配置复跑提供更强证明界 75" in quality_gate["detail"]
    proof_point = next(point for point in quality_gate["decision_points"] if point["label"] == "更强证明")
    assert proof_point["value"] == "候选目标值 100 / 最优界 75 / 重算缺口 25（约 25.00%）"


def test_publish_assessment_reads_quality_gap_from_final_solver_overview(tmp_path: Path) -> None:
    package = tmp_path / "result_package.zip"
    package.write_text("zip", encoding="utf-8")
    overview = tmp_path / "final_solver_overview.json"
    overview.write_text(
        json.dumps(
            {
                "solver_status": "FEASIBLE",
                "objective_value": 200,
                "best_bound": 150,
            }
        ),
        encoding="utf-8",
    )

    assessment = build_publish_assessment(
        {
            "status": "completed",
            "mode": "joint",
            "package_file": str(package),
            "log_tail": "回调捕获解数量：1",
            "files": [
                {"label": "outputs/final_solver_overview.json", "path": str(overview)},
                {"label": "outputs/课表及值班安排.xlsx", "path": str(tmp_path / "课表.xlsx")},
                {"label": "outputs/诊断/约束审计.txt", "path": str(tmp_path / "约束审计.txt")},
            ],
            "config_fingerprint": {"hash": "a" * 64},
            "current_config_fingerprint": {"hash": "a" * 64},
            "config_fingerprint_match": True,
        },
        _readiness(),
    )

    assert assessment["outcome"]["solver_status"] == "FEASIBLE"
    assert assessment["outcome"]["best_bound"] == 150
    assert assessment["summary"]["status"] == "ready"
    quality_gate = next(item for item in assessment["gates"] if item["domain"] == "求解质量")
    assert quality_gate["decision_points"][0]["label"] == "目标值"


def test_publish_assessment_blocks_diagnostic_trial_even_with_schedule() -> None:
    assessment = build_publish_assessment(
        {
            "status": "completed",
            "run_purpose": "diagnostic_trial",
            "diagnostic_plan_title": "关闭班主任值班与晚查寝链路",
            "log_tail": "status = FEASIBLE\n回调捕获解数量：1",
            "files": [
                {"label": "outputs/课表及值班安排.xlsx", "path": "课表及值班安排.xlsx"},
                {"label": "outputs/诊断/约束审计.txt", "path": "约束审计.txt"},
            ],
        },
        _readiness(),
    )

    assert assessment["summary"]["status"] == "blocked"
    assert assessment["summary"]["can_publish"] is False
    gate = next(item for item in assessment["gates"] if item["title"] == "诊断试跑结果不可发布")
    assert gate["blocking"] is True
    assert "关闭班主任值班与晚查寝链路" in gate["detail"]
    solution_gate = next(item for item in assessment["gates"] if item["domain"] == "候选解")
    assert solution_gate["title"] == "诊断试跑捕获 1 个候选解"
    assert "不进入发布流程" in solution_gate["suggestion"]
    schedule_gate = next(item for item in assessment["gates"] if item["domain"] == "候选课表")
    assert schedule_gate["title"] == "已发现 1 个候选课表文件"
    assert "只能用于定位无解来源" in schedule_gate["detail"]
    assert "不要作为正式课表交付" in schedule_gate["suggestion"]
    diagnostic_gate = next(item for item in assessment["gates"] if item["domain"] == "诊断材料")
    assert "诊断试跑" in diagnostic_gate["detail"]


def test_publish_assessment_labels_diagnostic_package_as_troubleshooting_archive(tmp_path: Path) -> None:
    package = tmp_path / "result_package.zip"
    package.write_text("zip", encoding="utf-8")

    assessment = build_publish_assessment(
        {
            "status": "completed",
            "run_purpose": "diagnostic_trial",
            "diagnostic_plan_title": "关闭班主任值班与晚查寝链路",
            "package_file": str(package),
            "log_tail": "status = FEASIBLE\n回调捕获解数量：1",
            "files": [
                {"label": "outputs/课表及值班安排.xlsx", "path": str(tmp_path / "课表及值班安排.xlsx")},
                {"label": "outputs/诊断/约束审计.txt", "path": str(tmp_path / "约束审计.txt")},
            ],
        },
        _readiness(),
    )

    package_gate = next(item for item in assessment["gates"] if item["domain"] == "排障包")
    assert package_gate["title"] == "排障包可用"
    assert "仅用于排障" in package_gate["detail"]
    assert "重新正式求解" in package_gate["suggestion"]


def test_publish_assessment_blocks_stale_config_result(tmp_path: Path) -> None:
    package = tmp_path / "result_package.zip"
    package.write_text("zip", encoding="utf-8")
    assessment = build_publish_assessment(
        {
            "status": "completed",
            "package_file": str(package),
            "log_tail": "status = FEASIBLE\n回调捕获解数量：1",
            "files": [
                {"label": "outputs/课表及值班安排.xlsx", "path": str(tmp_path / "课表及值班安排.xlsx")},
                {"label": "outputs/诊断/约束审计.txt", "path": str(tmp_path / "约束审计.txt")},
            ],
            "config_fingerprint": {"hash": "a" * 64},
            "current_config_fingerprint": {"hash": "b" * 64},
            "config_fingerprint_match": False,
            "config_changed_after_run": True,
        },
        _readiness(),
    )

    assert assessment["summary"]["status"] == "blocked"
    assert assessment["summary"]["can_publish"] is False
    gate = next(item for item in assessment["gates"] if item["title"] == "当前配置已变更")
    assert gate["blocking"] is True
    assert "aaaaaaaaaaaa" in gate["detail"]
    assert "bbbbbbbbbbbb" in gate["detail"]


def test_publish_assessment_warns_when_config_fingerprint_missing(tmp_path: Path) -> None:
    package = tmp_path / "result_package.zip"
    package.write_text("zip", encoding="utf-8")
    assessment = build_publish_assessment(
        {
            "status": "completed",
            "package_file": str(package),
            "log_tail": "status = FEASIBLE\n回调捕获解数量：1",
            "files": [
                {"label": "outputs/课表及值班安排.xlsx", "path": str(tmp_path / "课表及值班安排.xlsx")},
                {"label": "outputs/诊断/约束审计.txt", "path": str(tmp_path / "约束审计.txt")},
            ],
            "config_fingerprint_match": None,
            "config_freshness": {"status": "unknown", "message": "本批次未记录配置版本。"},
        },
        _readiness(),
    )

    assert assessment["summary"]["status"] == "ready"
    gate = next(item for item in assessment["gates"] if item["title"] == "配置版本未校验")
    assert gate["severity"] == "warning"


def test_publish_assessment_names_readiness_blocking_items() -> None:
    readiness = _readiness(can_publish=False, errors=1)
    readiness["items"] = [
        {
            "severity": "error",
            "title": "晚查寝候选人数不足",
            "suggestion": "增加男班主任候选。",
        }
    ]

    assessment = build_publish_assessment({"status": "idle", "files": []}, readiness)

    gate = next(item for item in assessment["gates"] if item["title"] == "发布校验未通过")
    assert "晚查寝候选人数不足" in gate["detail"]
    assert gate["suggestion"] == "增加男班主任候选。"


def test_publish_assessment_warns_when_checkin_same_day_policy_is_soft(tmp_path: Path) -> None:
    effective = tmp_path / "effective_config.yaml"
    effective.write_text(
        "checkin:\n"
        "  require_teacher_has_class_that_day_mode: soft\n"
        "  w_require_teacher_has_class_that_day: 3000\n",
        encoding="utf-8",
    )

    assessment = build_publish_assessment(
        {
            "status": "completed",
            "mode": "night",
            "log_tail": "status = OPTIMAL\n回调捕获解数量：1",
            "files": [
                {"label": "outputs/effective_config.yaml", "path": str(effective)},
                {"label": "outputs/晚自习课表.xlsx", "path": str(tmp_path / "晚自习课表.xlsx")},
                {"label": "outputs/诊断/约束审计.txt", "path": str(tmp_path / "约束审计.txt")},
            ],
            "config_fingerprint": {"hash": "a" * 64},
            "current_config_fingerprint": {"hash": "a" * 64},
            "config_fingerprint_match": True,
        },
        _readiness(),
    )

    assert assessment["summary"]["status"] == "ready"
    gate = next(item for item in assessment["gates"] if item["title"] == "晚查寝当天有课为软约束")
    assert gate["severity"] == "warning"
    assert "权重 3000" in gate["detail"]


def test_publish_assessment_surfaces_checkin_same_day_violation_events(tmp_path: Path) -> None:
    effective = tmp_path / "effective_config.yaml"
    effective.write_text(
        "checkin:\n"
        "  require_teacher_has_class_that_day_mode: soft\n"
        "  w_require_teacher_has_class_that_day: 3000\n",
        encoding="utf-8",
    )
    event_log = tmp_path / "event_log.csv"
    event_log.write_text(
        "constraint_id,constraint_name,teacher_name,day,period,penalty\n"
        "night_checkin_need_same_day_class,晚查寝教师需当日有晚自习,肖祥宠,星期五,男晚查寝,3000\n"
        "night_checkin_need_same_day_class,晚查寝教师需当日有晚自习,肖祥宠,星期日,男晚查寝,3000\n",
        encoding="utf-8-sig",
    )

    assessment = build_publish_assessment(
        {
            "status": "completed",
            "mode": "night",
            "log_tail": "status = OPTIMAL\n回调捕获解数量：1",
            "files": [
                {"label": "outputs/effective_config.yaml", "path": str(effective)},
                {"label": "outputs/event_log.csv", "path": str(event_log)},
                {"label": "outputs/晚自习课表.xlsx", "path": str(tmp_path / "晚自习课表.xlsx")},
                {"label": "outputs/诊断/约束审计.txt", "path": str(tmp_path / "约束审计.txt")},
            ],
            "config_fingerprint": {"hash": "a" * 64},
            "current_config_fingerprint": {"hash": "a" * 64},
            "config_fingerprint_match": True,
        },
        _readiness(),
    )

    gate = next(item for item in assessment["gates"] if item["title"] == "存在当天无晚自习查寝安排")
    assert gate["severity"] == "warning"
    assert "2 条" in gate["detail"]
    assert "总罚分 6000" in gate["detail"]
    assert "肖祥宠" in gate["detail"]


def test_publish_assessment_binds_checkin_events_to_final_best_solution(tmp_path: Path) -> None:
    effective = tmp_path / "effective_config.yaml"
    effective.write_text(
        "checkin:\n"
        "  require_teacher_has_class_that_day_mode: soft\n"
        "  w_require_teacher_has_class_that_day: 20000\n",
        encoding="utf-8",
    )
    stale_event_log = tmp_path / "pool_cache" / "sol_0026" / "event_log.csv"
    stale_event_log.parent.mkdir(parents=True)
    stale_event_log.write_text(
        "constraint_id,constraint_name,teacher_name,day,period,penalty\n"
        "night_checkin_need_same_day_class,晚查寝教师需当日有晚自习,肖祥宠,星期日,男晚查寝,20000\n",
        encoding="utf-8-sig",
    )
    best_solution = tmp_path / "pool_cache" / "sol_0035" / "sol_0035.json"
    best_solution.parent.mkdir(parents=True)
    best_solution.write_text("{}", encoding="utf-8")
    best_event_log = best_solution.with_name("event_log.csv")
    best_event_log.write_text(
        "constraint_id,constraint_name,teacher_name,day,period,penalty\n"
        "night_checkin_need_same_day_class,晚查寝教师需当日有晚自习,严昆,星期日,男晚查寝,20000\n",
        encoding="utf-8-sig",
    )
    best_meta = tmp_path / "best" / "最终全局最优解_meta.json"
    best_meta.parent.mkdir()
    best_meta.write_text(
        json.dumps(
            {
                "seq_id": 35,
                "source_solution_file": str(best_solution),
                "solution_hash": "best",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    assessment = build_publish_assessment(
        {
            "status": "completed",
            "mode": "joint",
            "log_tail": "status = FEASIBLE\n回调捕获解数量：2",
            "files": [
                {"label": "outputs/effective_config.yaml", "path": str(effective)},
                {"label": "outputs/web_runs/run_x/solutions/run_x/pool_cache/sol_0026/event_log.csv", "path": str(stale_event_log)},
                {"label": "outputs/web_runs/run_x/solutions/run_x/best/最终全局最优解_meta.json", "path": str(best_meta)},
                {"label": "outputs/web_runs/run_x/solutions/run_x/pool_cache/sol_0035/event_log.csv", "path": str(best_event_log)},
                {"label": "outputs/web_runs/run_x/solutions/run_x/best/最终全局最优解.xlsx", "path": str(tmp_path / "最终全局最优解.xlsx")},
                {"label": "outputs/诊断/约束审计.txt", "path": str(tmp_path / "约束审计.txt")},
            ],
            "config_fingerprint": {"hash": "a" * 64},
            "current_config_fingerprint": {"hash": "a" * 64},
            "config_fingerprint_match": True,
        },
        _readiness(),
    )

    gate = next(item for item in assessment["gates"] if item["title"] == "存在当天无晚自习查寝安排")
    assert "严昆/星期日/男晚查寝" in gate["detail"]
    assert "肖祥宠" not in gate["detail"]
    assert gate["evidence_source"] == str(best_event_log)


def test_publish_assessment_explains_checkin_violation_candidate_gap(tmp_path: Path) -> None:
    effective = tmp_path / "effective_config.yaml"
    effective.write_text(
        "checkin:\n"
        "  require_teacher_has_class_that_day_mode: soft\n"
        "  w_require_teacher_has_class_that_day: 20000\n",
        encoding="utf-8",
    )
    event_log = tmp_path / "event_log.csv"
    event_log.write_text(
        "constraint_id,constraint_name,teacher_name,day,period,penalty\n"
        "night_checkin_need_same_day_class,晚查寝教师需当日有晚自习,严昆,星期五,男晚查寝,20000\n"
        "night_checkin_need_same_day_class,晚查寝教师需当日有晚自习,严昆,星期日,男晚查寝,20000\n",
        encoding="utf-8-sig",
    )
    workbook = tmp_path / "最终全局最优解.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = "班主任课表"
    ws.append(["男班主任课表"])
    ws.append(["节次", "星期五", "星期日"])
    ws.append(["晚自习1", None, None])
    ws.append(["晚自习2", None, None])
    ws.append(["女班主任课表"])
    ws.append(["节次", "星期五", "星期日"])
    ws.append(["晚自习1", "惠文君", "曹诗琪"])
    ws.append(["晚自习2", "刘梦", "米瑞娟"])
    night_ws = wb.create_sheet("晚自习课表")
    night_ws.append(["班级", "星期五", "星期日"])
    night_ws.append(["1班", "历史-周波", "语文-袁金成"])
    wb.save(workbook)

    assessment = build_publish_assessment(
        {
            "status": "completed",
            "mode": "joint",
            "log_tail": "status = FEASIBLE\n回调捕获解数量：1",
            "files": [
                {"label": "outputs/effective_config.yaml", "path": str(effective)},
                {"label": "outputs/event_log.csv", "path": str(event_log)},
                {"label": "outputs/web_runs/run_x/solutions/run_x/best/最终全局最优解.xlsx", "path": str(workbook)},
                {"label": "outputs/诊断/约束审计.txt", "path": str(tmp_path / "约束审计.txt")},
            ],
            "config_fingerprint": {"hash": "a" * 64},
            "current_config_fingerprint": {"hash": "a" * 64},
            "config_fingerprint_match": True,
        },
        _readiness(),
    )

    gate = next(item for item in assessment["gates"] if item["title"] == "存在当天无晚自习查寝安排")
    assert "严昆/星期五/男晚查寝；严昆/星期日/男晚查寝" in gate["detail"]
    assert "星期五、星期日没有男班主任晚自习可直接承接男寝晚查" in gate["detail"]
    assert "现有可用人力不足" in gate["suggestion"]
    assert "引入可负责查寝的新教师、宿管或行政值守人员" in gate["suggestion"]
    ledger = gate["checkin_supply_ledger"]
    assert len(ledger) == 2
    friday = next(item for item in ledger if item["day"] == "星期五")
    assert friday["duty"] == "男寝晚查"
    assert friday["exception_count"] == 1
    assert friday["penalty_sum"] == 20000
    assert friday["potential_penalty_reduction"] == 20000
    assert friday["assigned_teachers"] == ["严昆"]
    assert friday["direct_candidate_count"] == 0
    assert friday["suggested_candidate_count"] == 1
    assert friday["pending_candidate_count"] == 1
    assert friday["shortage"] == 1
    assert friday["status"] == "现有人力不足，需引入新候选"
    assert "待确认名单不能视为已确认可用人力" in friday["capacity_note"]
    assert [option["id"] for option in gate["remediation_options"]] == [
        "publish.checkin.add_same_day_candidate",
        "publish.checkin.adjust_evening_assignment",
        "publish.checkin.record_external_exception",
    ]
    assert gate["remediation_options"][0]["title"] == "引入新晚查候选"
    assert gate["remediation_options"][0]["decision_points"][1]["value"] == "40000"
    assert gate["remediation_options"][0]["decision_points"][3]["value"] == "星期五、星期日男寝"
    assert gate["remediation_options"][0]["quick_actions"][0] == {
        "id": "open-extra-heads-rule",
        "label": "维护额外候选人",
        "action": "open_rule_editor",
        "view": "rules",
        "rule_id": "duty.night_checkin.extra_heads",
        "search": "额外晚查寝候选人",
    }
    assert gate["remediation_options"][0]["quick_actions"][1]["view"] == "teachers"
    suggestions = gate["remediation_options"][0]["candidate_suggestions"]
    assert {item["teacher"] for item in suggestions} == {"周波", "袁金成"}
    assert all(item["status"] == "needs_confirmation" for item in suggestions)
    assert any(item["day"] == "星期五" and item["required_gender"] == "男" for item in suggestions)
    requirements = gate["candidate_data_requirements"]
    assert {item["teacher"] for item in requirements} == {"周波", "袁金成"}
    assert requirements[0]["missing_fields"] == ["性别", "查寝资格", "值守口径"]
    assert requirements[0]["action"] == "补齐后再确认是否加入额外晚查寝候选名单"
    assert '{"name": "周波", "gender": "男", "days": ["星期五"]}' in {item["config_hint"] for item in suggestions}
    assert "周波(星期五男)" in gate["remediation_options"][0]["manual_hint"]
    assert "额外晚查寝候选名单" in gate["remediation_options"][0]["manual_hint"]
    assert "不必继续围绕严昆/星期五/男晚查寝、严昆/星期日/男晚查寝当前安排反复优化" in gate["remediation_options"][0]["manual_hint"]
    assert "学校既有 OA 或线下流程" in gate["remediation_options"][2]["manual_hint"]


def test_publish_assessment_ignores_legacy_release_review_signoff(tmp_path: Path) -> None:
    effective = tmp_path / "effective_config.yaml"
    package = tmp_path / "result_package.zip"
    package.write_text("zip", encoding="utf-8")
    effective.write_text(
        "checkin:\n"
        "  require_teacher_has_class_that_day_mode: soft\n"
        "  w_require_teacher_has_class_that_day: 3000\n",
        encoding="utf-8",
    )

    assessment = build_publish_assessment(
        {
            "run_id": "run_20260506_094310",
            "status": "completed",
            "mode": "night",
            "package_file": str(package),
            "log_tail": "status = OPTIMAL\n回调捕获解数量：1",
            "files": [
                {"label": "outputs/effective_config.yaml", "path": str(effective)},
                {"label": "outputs/晚自习课表.xlsx", "path": str(tmp_path / "晚自习课表.xlsx")},
                {"label": "outputs/诊断/约束审计.txt", "path": str(tmp_path / "约束审计.txt")},
            ],
            "release_review": {
                "run_id": "run_20260506_094310",
                "confirmed": True,
                "reviewer": "教务主任",
                "note": "同意作为本周临时例外。",
                "responsible_person": "高二年级组",
                "alternative_arrangement": "年级组安排专人到校完成晚查。",
                "attendance_policy": "按临时值守记录纳入考勤。",
                "confirmed_at": "2026-05-06 10:20:00",
                "acknowledged_gate_keys": ["晚查寝策略|晚查寝当天有课为软约束"],
            },
            "config_fingerprint": {"hash": "a" * 64},
            "current_config_fingerprint": {"hash": "a" * 64},
            "config_fingerprint_match": True,
        },
        _readiness(),
    )

    assert assessment["summary"]["status"] == "ready"
    assert assessment["summary"]["status_label"] == "可发布（含风险提示）"
    assert assessment["summary"]["warnings"] == 1
    gate = next(item for item in assessment["gates"] if item["title"] == "晚查寝当天有课为软约束")
    assert "acknowledged" not in gate
    assert "review_confirmation" not in assessment
    assert "release_preflight" not in assessment
    assert [item["title"] for item in assessment["next_actions"]] == ["晚查寝当天有课为软约束"]


def test_publish_assessment_keeps_aggregate_readiness_warning_as_advisory(tmp_path: Path) -> None:
    effective = tmp_path / "effective_config.yaml"
    package = tmp_path / "result_package.zip"
    package.write_text("zip", encoding="utf-8")
    effective.write_text(
        "checkin:\n"
        "  require_teacher_has_class_that_day_mode: soft\n"
        "  w_require_teacher_has_class_that_day: 3000\n",
        encoding="utf-8",
    )

    assessment = build_publish_assessment(
        {
            "run_id": "run_20260506_102257",
            "status": "completed",
            "mode": "night",
            "package_file": str(package),
            "log_tail": "status = OPTIMAL\n回调捕获解数量：1",
            "files": [
                {"label": "outputs/effective_config.yaml", "path": str(effective)},
                {"label": "outputs/晚自习课表.xlsx", "path": str(tmp_path / "晚自习课表.xlsx")},
                {"label": "outputs/诊断/约束审计.txt", "path": str(tmp_path / "约束审计.txt")},
            ],
            "config_fingerprint": {"hash": "a" * 64},
            "current_config_fingerprint": {"hash": "a" * 64},
            "config_fingerprint_match": True,
        },
        _readiness(warnings=2),
    )

    aggregate = next(item for item in assessment["gates"] if item["title"] == "当前配置存在风险提示")
    assert aggregate["severity"] == "warning"
    assert assessment["summary"]["status"] == "ready"
    assert assessment["summary"]["warnings"] == 2
    assert [item["title"] for item in assessment["next_actions"]] == ["晚查寝当天有课为软约束", "当前配置存在风险提示"]
    assert "review_confirmation" not in assessment
    assert "release_preflight" not in assessment


def test_publish_assessment_does_not_require_structured_release_signoff(tmp_path: Path) -> None:
    effective = tmp_path / "effective_config.yaml"
    package = tmp_path / "result_package.zip"
    package.write_text("zip", encoding="utf-8")
    effective.write_text(
        "checkin:\n"
        "  require_teacher_has_class_that_day_mode: soft\n"
        "  w_require_teacher_has_class_that_day: 3000\n",
        encoding="utf-8",
    )

    assessment = build_publish_assessment(
        {
            "run_id": "run_20260506_094310",
            "status": "completed",
            "mode": "night",
            "package_file": str(package),
            "log_tail": "status = OPTIMAL\n回调捕获解数量：1",
            "files": [
                {"label": "outputs/effective_config.yaml", "path": str(effective)},
                {"label": "outputs/晚自习课表.xlsx", "path": str(tmp_path / "晚自习课表.xlsx")},
                {"label": "outputs/诊断/约束审计.txt", "path": str(tmp_path / "约束审计.txt")},
            ],
            "release_review": {
                "run_id": "run_20260506_094310",
                "confirmed": True,
                "reviewer": "教务主任",
                "acknowledged_gate_keys": ["晚查寝策略|晚查寝当天有课为软约束"],
            },
            "config_fingerprint": {"hash": "a" * 64},
            "current_config_fingerprint": {"hash": "a" * 64},
            "config_fingerprint_match": True,
        },
        _readiness(),
    )

    assert assessment["summary"]["status"] == "ready"
    assert "review_confirmation" not in assessment
    assert "release_preflight" not in assessment
    assert not any(gate.get("acknowledged") for gate in assessment["gates"])


def test_publish_assessment_ignores_template_signoff_text_after_review_removal(tmp_path: Path) -> None:
    effective = tmp_path / "effective_config.yaml"
    package = tmp_path / "result_package.zip"
    package.write_text("zip", encoding="utf-8")
    effective.write_text(
        "checkin:\n"
        "  require_teacher_has_class_that_day_mode: soft\n"
        "  w_require_teacher_has_class_that_day: 3000\n",
        encoding="utf-8",
    )

    assessment = build_publish_assessment(
        {
            "run_id": "run_20260506_094310",
            "status": "completed",
            "mode": "night",
            "package_file": str(package),
            "log_tail": "status = OPTIMAL\n回调捕获解数量：1",
            "files": [
                {"label": "outputs/effective_config.yaml", "path": str(effective)},
                {"label": "outputs/晚自习课表.xlsx", "path": str(tmp_path / "晚自习课表.xlsx")},
                {"label": "outputs/诊断/约束审计.txt", "path": str(tmp_path / "约束审计.txt")},
            ],
            "release_review": {
                "run_id": "run_20260506_094310",
                "confirmed": True,
                "reviewer": "教务主任",
                "responsible_person": "高二年级组",
                "alternative_arrangement": "由年级组安排严昆专门到校完成男寝晚查。",
                "attendance_policy": "按临时晚查值守记录纳入行政值班考勤。",
                "note": "人工补充：请补全具体责任人、替代方式、考勤口径、审批人和审批时间。",
                "acknowledged_gate_keys": ["晚查寝策略|晚查寝当天有课为软约束"],
            },
            "config_fingerprint": {"hash": "a" * 64},
            "current_config_fingerprint": {"hash": "a" * 64},
            "config_fingerprint_match": True,
        },
        _readiness(),
    )

    assert assessment["summary"]["status"] == "ready"
    assert "review_confirmation" not in assessment
    assert "release_preflight" not in assessment


def test_publish_assessment_ignores_stale_legacy_review_confirmation(tmp_path: Path) -> None:
    effective = tmp_path / "effective_config.yaml"
    package = tmp_path / "result_package.zip"
    package.write_text("zip", encoding="utf-8")
    effective.write_text(
        "checkin:\n"
        "  require_teacher_has_class_that_day_mode: soft\n",
        encoding="utf-8",
    )

    assessment = build_publish_assessment(
        {
            "run_id": "run_new",
            "status": "completed",
            "mode": "night",
            "package_file": str(package),
            "log_tail": "status = OPTIMAL\n回调捕获解数量：1",
            "files": [
                {"label": "outputs/effective_config.yaml", "path": str(effective)},
                {"label": "outputs/晚自习课表.xlsx", "path": str(tmp_path / "晚自习课表.xlsx")},
                {"label": "outputs/诊断/约束审计.txt", "path": str(tmp_path / "约束审计.txt")},
            ],
            "release_review": {
                "run_id": "run_old",
                "confirmed": True,
                "reviewer": "教务主任",
                "acknowledged_gate_keys": ["晚查寝策略|晚查寝当天有课为软约束"],
            },
        },
        _readiness(),
    )

    assert assessment["summary"]["status"] == "ready"
    assert "review_confirmation" not in assessment
    assert not any(gate.get("acknowledged") for gate in assessment["gates"])
