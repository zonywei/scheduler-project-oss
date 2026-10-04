from __future__ import annotations

import sys
from pathlib import Path

from ortools.sat.python import cp_model
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scheduler.app.conflict_detection import detect_rule_conflicts
from scheduler.app.academic_affairs import normalize_academic_affairs, summarize_academic_affairs
from scheduler.app.business_rules import build_business_rule_groups
from scheduler.app.nl_rules import apply_patch_to_mapping, parse_natural_language_rule, parse_rule_with_ai_settings
from scheduler.app import config_service
from scheduler.config.loader import load_effective_config
from scheduler.data.day_rules_reader import load_day_inputs
from scheduler.data.teacher_table_reader import read_teacher_table
from scheduler.joint_solver import build_night_model


def test_web_ai_settings_are_hidden_from_ordinary_users() -> None:
    html = (REPO_ROOT / "scheduler" / "app" / "static" / "index.html").read_text(encoding="utf-8")

    assert "AI 助手设置" not in html
    assert "由管理员填写" not in html
    assert "AI 助手接口设置" not in html
    assert "OPENAI_API_KEY" not in html
    assert "密钥环境变量" not in html
    assert "https://api.example.com/v1" not in html


def test_parse_night_teacher_day_ban_patch() -> None:
    rule = parse_natural_language_rule("教师A 周日晚自习禁排", known_teachers=["教师A"])
    assert rule["solver_supported"] is True
    assert rule["scope"] == "night"
    assert rule["day"] == "星期日"
    assert rule["target_teachers"] == ["教师A"]

    target: dict = {}
    for patch in rule["patches"]:
        apply_patch_to_mapping(target, patch)
    assert target["hard_bans"]["teacher_day_bans"]["星期日"] == ["教师A"]


def test_parse_day_am1_ban_patch() -> None:
    rule = parse_natural_language_rule("教师B 工作日上午1禁排", known_teachers=["教师B"])
    assert rule["solver_supported"] is True
    assert rule["scope"] == "day"

    target: dict = {}
    for patch in rule["patches"]:
        apply_patch_to_mapping(target, patch)
    pcfg = target["personalized_constraints"]
    assert pcfg["enable_custom_no_am1_teachers"] is True
    assert pcfg["custom_no_am1_teachers"] == ["教师B"]


def test_ai_rule_parser_falls_back_when_disabled() -> None:
    rule = parse_rule_with_ai_settings("教师A 周日晚自习禁排", known_teachers=["教师A"], settings={"enabled": False})
    assert rule["ai_used"] is False
    assert rule["solver_supported"] is True
    assert rule["target_teachers"] == ["教师A"]


def test_rule_field_updates_are_saved_to_web_overrides(tmp_path: Path, monkeypatch) -> None:
    web_path = tmp_path / "web_overrides.yaml"
    monkeypatch.setattr(config_service, "WEB_OVERRIDES_PATH", web_path)
    result = config_service.save_rule_field_updates(
        [
            {"store": "rules", "path": "personalized_constraints.enable_custom_no_am1_teachers", "type": "bool", "value": "true"},
            {"store": "rules", "path": "personalized_constraints.custom_no_am1_teachers", "type": "list", "value": "教师A、教师B"},
            {"store": "io", "path": "day.grade_group_duty.w_min_once", "type": "int", "value": "2000"},
            {"store": "rules", "path": "rule_application.personal.enable_custom_no_am1_teachers.target_scope", "type": "choice", "value": "selected_teachers"},
            {"store": "rules", "path": "rule_application.personal.enable_custom_no_am1_teachers.exception_teachers", "type": "list", "value": "教师C"},
        ]
    )
    assert result["rules"]["personalized_constraints"]["enable_custom_no_am1_teachers"] is True
    assert result["rules"]["personalized_constraints"]["custom_no_am1_teachers"] == ["教师A", "教师B"]
    assert result["io"]["day"]["grade_group_duty"]["w_min_once"] == 2000
    app = result["rules"]["rule_application"]["personal"]["enable_custom_no_am1_teachers"]
    assert app["target_scope"] == "selected_teachers"
    assert app["exception_teachers"] == ["教师C"]


def test_checkin_extra_heads_field_updates_are_normalized(tmp_path: Path, monkeypatch) -> None:
    web_path = tmp_path / "web_overrides.yaml"
    monkeypatch.setattr(config_service, "WEB_OVERRIDES_PATH", web_path)

    result = config_service.save_rule_field_updates(
        [
            {
                "label": "额外候选名单",
                "store": "rules",
                "path": "checkin.extra_heads",
                "type": "checkin_extra_heads",
                "value": '[{"name":"教师C","gender":"男","days":["星期五","星期日"]},{"name":"教师B","gender":"女"},{"name":"","gender":"男"},{"name":"未知老师","gender":"其他"}]',
            }
        ]
    )

    assert result["rules"]["checkin"]["extra_heads"] == [
        {"name": "教师C", "gender": "男", "days": ["星期五", "星期日"]},
        {"name": "教师B", "gender": "女"},
        {"name": "未知老师", "gender": ""},
    ]
    entry = result["change_audit"]["entries"][0]
    assert entry["changes"][0]["full_path"] == "rules.checkin.extra_heads"
    assert entry["changes"][0]["after"][0] == {"name": "教师C", "gender": "男", "days": ["星期五", "星期日"]}


def test_rule_field_updates_write_change_audit_with_before_after(tmp_path: Path, monkeypatch) -> None:
    web_path = tmp_path / "web_overrides.yaml"
    monkeypatch.setattr(config_service, "WEB_OVERRIDES_PATH", web_path)
    web_path.write_text(
        yaml.safe_dump({"rules": {"checkin": {"per_teacher_max_times": 1}}}, allow_unicode=True),
        encoding="utf-8",
    )

    result = config_service.save_rule_field_updates(
        [
            {
                "label": "每位班主任每周查寝次数上限",
                "store": "rules",
                "path": "checkin.per_teacher_max_times",
                "type": "int",
                "value": "2",
            }
        ],
        source="readiness.remediation",
        reason="晚查寝男班主任容量不足",
    )

    assert result["rules"]["checkin"]["per_teacher_max_times"] == 2
    entry = result["change_audit"]["entries"][0]
    assert entry["source"] == "readiness.remediation"
    assert entry["reason"] == "晚查寝男班主任容量不足"
    assert entry["changes"][0]["full_path"] == "rules.checkin.per_teacher_max_times"
    assert entry["changes"][0]["before"] == 1
    assert entry["changes"][0]["after"] == 2
    assert config_service.list_config_change_audit()["entries"][0]["id"] == entry["id"]


def test_rule_field_update_preview_does_not_persist(tmp_path: Path, monkeypatch) -> None:
    web_path = tmp_path / "web_overrides.yaml"
    monkeypatch.setattr(config_service, "WEB_OVERRIDES_PATH", web_path)
    web_path.write_text(
        yaml.safe_dump({"rules": {"checkin": {"per_teacher_max_times": 1}}}, allow_unicode=True),
        encoding="utf-8",
    )

    preview = config_service.preview_rule_field_updates(
        [{"store": "rules", "path": "checkin.per_teacher_max_times", "type": "int", "value": "2"}]
    )

    assert preview["persisted"] is False
    assert preview["overrides"]["rules"]["checkin"]["per_teacher_max_times"] == 2
    assert preview["changes"][0]["before"] == 1
    assert preview["changes"][0]["after"] == 2
    reloaded = config_service.load_web_overrides()
    assert reloaded["rules"]["checkin"]["per_teacher_max_times"] == 1
    assert reloaded["change_audit"]["entries"] == []


def test_change_audit_rollback_restores_previous_value(tmp_path: Path, monkeypatch) -> None:
    web_path = tmp_path / "web_overrides.yaml"
    monkeypatch.setattr(config_service, "WEB_OVERRIDES_PATH", web_path)
    first = config_service.save_rule_field_updates(
        [
            {
                "store": "rules",
                "path": "checkin.per_teacher_max_times",
                "type": "int",
                "value": "2",
            }
        ],
        source="readiness.remediation",
    )
    entry_id = first["change_audit"]["entries"][0]["id"]

    restored = config_service.rollback_config_change(entry_id, reason="教务员撤回自动修复")

    assert "checkin" not in restored["rules"]
    rollback_entry = restored["change_audit"]["entries"][0]
    assert rollback_entry["source"] == "config.rollback"
    assert rollback_entry["rollback_of"] == entry_id
    assert rollback_entry["reason"] == "教务员撤回自动修复"
    assert rollback_entry["changes"][0]["before"] == 2
    assert rollback_entry["changes"][0]["after"] is None
    assert restored["change_audit"]["entries"][1]["id"] == entry_id


def test_academic_affairs_save_writes_change_audit_and_rolls_back(tmp_path: Path, monkeypatch) -> None:
    web_path = tmp_path / "web_overrides.yaml"
    monkeypatch.setattr(config_service, "WEB_OVERRIDES_PATH", web_path)

    result = config_service.save_academic_affairs_payload(
        {
            "academic_affairs": {
                "tables": {
                    "rooms": [
                        {"场地": "综合楼报告厅", "类型": "报告厅", "容量": "300", "可用时段": "全天"},
                    ]
                }
            }
        },
        source="academic_affairs.save",
        reason="场地资源保存 1 行",
        actor="教务员",
    )

    entry = result["change_audit"]["entries"][0]
    change = entry["changes"][0]
    assert entry["source"] == "academic_affairs.save"
    assert entry["actor"] == "教务员"
    assert entry["reason"] == "场地资源保存 1 行"
    assert change["label"] == "教务表：场地资源"
    assert change["store"] == "academic_affairs"
    assert change["full_path"] == "academic_affairs.tables.rooms"
    assert change["row_count_before"] == 0
    assert change["row_count_after"] == 1
    assert result["academic_affairs"]["tables"]["rooms"][0]["场地"] == "综合楼报告厅"

    restored = config_service.rollback_config_change(entry["id"], reason="撤回误导入场地")

    rollback_entry = restored["change_audit"]["entries"][0]
    assert rollback_entry["rollback_of"] == entry["id"]
    assert rollback_entry["changes"][0]["store"] == "academic_affairs"
    assert rollback_entry["changes"][0]["row_count_before"] == 1
    assert rollback_entry["changes"][0]["row_count_after"] == 0
    assert restored["academic_affairs"]["tables"]["rooms"] == []


def test_base_data_saves_write_change_audit_and_roll_back(tmp_path: Path, monkeypatch) -> None:
    web_path = tmp_path / "web_overrides.yaml"
    monkeypatch.setattr(config_service, "WEB_OVERRIDES_PATH", web_path)

    teachers = config_service.save_teacher_subject_rows(
        [{"班级": "初一1班", "班主任": "教师C", "班主任性别": "女", "数学": "教师B"}],
        source="base_data.teacher_subjects.save",
        reason="教师定位表保存 1 行",
        actor="教务员",
    )
    teacher_entry = teachers["change_audit"]["entries"][0]
    teacher_change = teacher_entry["changes"][0]

    assert teacher_entry["source"] == "base_data.teacher_subjects.save"
    assert teacher_change["label"] == "教师定位表"
    assert teacher_change["full_path"] == "io.web_tables.teacher_subjects"
    assert teacher_change["before_exists"] is False
    assert teacher_change["row_count_before"] == 0
    assert teacher_change["row_count_after"] == 1

    restored_teachers = config_service.rollback_config_change(teacher_entry["id"], reason="撤回教师定位误保存")
    restored_web_tables = restored_teachers["io"].get("web_tables", {})
    assert "teacher_subjects" not in restored_web_tables
    assert restored_teachers["change_audit"]["entries"][0]["changes"][0]["row_count_after"] == 0

    day_rules = config_service.save_day_rule_table(
        "subject_hours",
        [{"班级": "初一1班", "数学": "5", "语文": "5"}],
        source="base_data.day_rules.save",
        reason="学科课时保存 1 行",
        actor="教务员",
    )
    day_entry = day_rules["change_audit"]["entries"][0]
    day_change = day_entry["changes"][0]

    assert day_entry["source"] == "base_data.day_rules.save"
    assert day_change["label"] == "白天规则表：学科课时"
    assert day_change["full_path"] == "io.web_tables.day_rules.subject_hours"
    assert day_change["row_count_before"] == 0
    assert day_change["row_count_after"] == 1

    restored_day_rules = config_service.rollback_config_change(day_entry["id"], reason="撤回白天规则误保存")
    restored_day_rule_tables = restored_day_rules["io"].get("web_tables", {}).get("day_rules", {})
    assert "subject_hours" not in restored_day_rule_tables


def test_day_rule_table_templates_import_as_preview() -> None:
    xlsx_template = config_service.build_day_rule_table_template_xlsx("subject_hours")
    assert xlsx_template.startswith(b"PK")

    imported_xlsx = config_service.parse_day_rule_table_xlsx("subject_hours", xlsx_template)

    assert imported_xlsx["persisted"] is False
    assert imported_xlsx["table"] == "subject_hours"
    assert imported_xlsx["row_count"] >= 1
    assert "row_index" not in imported_xlsx["rows"][0]
    assert imported_xlsx["message"] == f"已解析 {imported_xlsx['row_count']} 行，请核对后保存当前白天规则表。"

    csv_template = config_service.build_day_rule_table_template_csv("subject_hours").decode("utf-8-sig")
    imported_csv = config_service.parse_day_rule_table_csv("subject_hours", csv_template)

    assert imported_csv["persisted"] is False
    assert imported_csv["table"] == "subject_hours"
    assert imported_csv["row_count"] == imported_xlsx["row_count"]

    header, *body = csv_template.splitlines()
    trimmed_header = ",".join(header.split(",")[:-1])
    try:
        config_service.parse_day_rule_table_csv("subject_hours", "\n".join([trimmed_header, *body]))
    except ValueError as exc:
        assert "导入缺少必需列" in str(exc)
    else:
        raise AssertionError("CSV without a required day-rule column should be rejected")


def test_teacher_subject_templates_import_as_preview() -> None:
    xlsx_template = config_service.build_teacher_subject_template()
    assert xlsx_template.startswith(b"PK")

    imported_xlsx = config_service.parse_teacher_subject_xlsx(xlsx_template)

    assert imported_xlsx["persisted"] is False
    assert imported_xlsx["table"] == "teacher_subjects"
    assert imported_xlsx["label"] == "教师定位表"
    assert imported_xlsx["row_count"] == len(imported_xlsx["rows"])
    assert imported_xlsx["row_count"] >= 1
    assert "班级" in imported_xlsx["rows"][0]
    assert imported_xlsx["message"] == f"已解析 {imported_xlsx['row_count']} 行，请核对后保存教师定位表。"

    csv_template = config_service.build_teacher_subject_template_csv().decode("utf-8-sig")
    imported_csv = config_service.parse_teacher_subject_csv(csv_template)

    assert imported_csv["persisted"] is False
    assert imported_csv["table"] == "teacher_subjects"
    assert imported_csv["row_count"] == imported_xlsx["row_count"]

    header, *body = csv_template.splitlines()
    extra_csv = "\n".join([f"{header},备注", *[f"{line},忽略" for line in body if line.strip()]])
    imported_extra = config_service.parse_teacher_subject_csv(extra_csv)
    assert imported_extra["ignored_columns"] == ["备注"]
    assert "备注" in imported_extra["rows"][0]

    try:
        config_service.parse_teacher_subject_csv("班级\n示例班级")
    except ValueError as exc:
        assert "至少需要一列实际学科/任课教师列" in str(exc)
    else:
        raise AssertionError("CSV without any user-provided subject column should be rejected")


def test_teacher_subject_import_uses_uploaded_subject_headers_without_optional_metadata() -> None:
    imported = config_service.parse_teacher_subject_csv(
        "班级,语文,自定义课程,信息技术\n"
        "1班,教师A,教师B,教师C\n"
        "2班,教师D,,教师E\n"
    )

    assert imported["ignored_columns"] == []
    assert imported["row_count"] == 2
    assert list(imported["rows"][0]) == ["row_index", "班级", "语文", "自定义课程", "信息技术"]
    assert "班主任" not in imported["rows"][0]
    assert "班主任性别" not in imported["rows"][0]


def test_business_rule_editors_expose_target_scope_and_exceptions() -> None:
    groups = build_business_rule_groups(
        {
            "personalized_constraints": {
                "enable_custom_no_am1_teachers": True,
                "custom_no_am1_teachers": ["教师A"],
                "rule_application": {},
            }
        }
    )
    rules = [rule for group in groups for rule in group["rules"]]
    assert rules
    for rule in rules:
        if rule.get("locked"):
            assert rule["editor"]["fields"] == []
            assert rule["mode"] == "硬规则"
            continue
        labels = {field["label"] for field in rule["editor"]["fields"]}
        assert "作用对象" in labels
        assert "例外教师" in labels


def test_business_rule_editor_exposes_checkin_extra_heads() -> None:
    groups = build_business_rule_groups(
        {
            "checkin": {
                "enabled": True,
                "extra_heads": [
                    {"name": "教师C", "gender": "男", "days": ["星期五"]},
                    {"name": "教师B", "gender": "女"},
                ],
            }
        }
    )
    rules = [rule for group in groups for rule in group["rules"]]
    rule = next((item for item in rules if item["id"] == "duty.night_checkin.extra_heads"), None)

    assert rule is not None
    assert rule["enabled"] is True
    assert "教师C(男/星期五)" in rule["targets"]
    fields = {field["path"]: field for field in rule["editor"]["fields"]}
    field = fields["checkin.extra_heads"]
    assert field["label"] == "额外候选名单"
    assert field["type"] == "checkin_extra_heads"
    assert field["ui"] == "checkin-extra-heads"
    assert field["value"] == [
        {"name": "教师C", "gender": "男", "days": ["星期五"]},
        {"name": "教师B", "gender": "女"},
    ]


def test_candidate_suggestions_do_not_trial_unconfirmed_people() -> None:
    script = (REPO_ROOT / "scheduler" / "app" / "static" / "app.js").read_text(encoding="utf-8")

    assert 'candidate.status === "ready_to_add"' in script
    assert "确认候选" in script
    assert "确认后试跑" in script
    assert "需先确认性别与查寝资格后再试跑" in script
    assert "确认无误后保存额外候选名单" in script
    assert "Boolean(options.startTrial && readyToAdd)" in script
    assert "待确认候选草稿" in script
    assert "mergeExtraHeadDraft(originalHeads, draft)" in script
    assert "data-extra-head-days" in script
    assert "parseExtraHeadDays" in script
    assert "candidateExtraHeadEntry" in script
    assert "确认后加入晚查寝候选名单" in script
    assert "当前结果包仍保持需确认状态" in script
    assert "const scopedEntry = candidateExtraHeadEntry(candidate)" in script
    assert "...(scopedEntry.days || [])" in script
    assert 'source: isCandidateReview ? "publish.checkin.candidate_review" : "rules.modal"' in script
    assert "已预填" in script
    function_start = script.index("async function applyRemediationCandidate")
    function_end = script.index("async function startCandidateVerificationTrial", function_start)
    function_body = script[function_start:function_end]
    unconfirmed_branch = function_body.index("if (!readyToAdd)")
    configure_call = function_body.index('await api("/api/rules/configure"')
    draft_open = function_body.index("openExtraHeadsRuleEditor({", unconfirmed_branch)
    assert unconfirmed_branch < configure_call
    assert unconfirmed_branch < draft_open < configure_call

    styles = (REPO_ROOT / "scheduler" / "app" / "static" / "styles.css").read_text(encoding="utf-8")
    assert ".remediation-candidate-config" in styles


def test_result_risk_panel_replaces_publish_review_ui() -> None:
    script = (REPO_ROOT / "scheduler" / "app" / "static" / "app.js").read_text(encoding="utf-8")
    html = (REPO_ROOT / "scheduler" / "app" / "static" / "index.html").read_text(encoding="utf-8")

    assert "function workbenchReadinessCard" in script
    assert "function workbenchResultReleaseCard" in script
    assert "function resultReleaseAction" in script
    assert "function resultFormalCandidateNotice" in script
    assert "function recommendedFormalCandidateSelection" in script
    assert "function renderResultRiskCard" in script
    assert "课表风险提示" in script
    assert "结果页采用质量更好的正式候选" in script
    assert "推荐候选文件" in script
    assert "下载将使用推荐的正式候选批次" in script
    assert "renderWorkbenchSummary();" in script
    assert "不代表课表可直接使用" in script
    assert "当前结果" in script
    assert "查看剩余差距" in script
    assert "resultReleaseAction" in html
    assert "resultFormalCandidateNotice" in html
    assert "deliveryStatus.release_state?.status_label" in script
    assert "releaseState.package_label" in script
    assert "releaseState.next_action" in script
    assert "renderResultRiskCard()" in script
    assert "暂无待展示的风险提示。" in script
    assert "function renderPublishReviewPanel" not in script
    assert "function renderPublishReviewWarningScope" not in script
    assert "function renderPublishReviewPreflight" not in script
    assert "function renderPublishReviewSignoffSummary" not in script
    assert "function publishReviewQuality" not in script
    assert "function renderResultAvailability" in script
    assert "function renderBusinessFloorAdjustedQuality" in script
    assert "function renderPublishGateCandidateRequirements" in script
    assert "需补齐候选资料" in script
    assert "function formatResultNumber" in script
    assert "function formatResultPercent" in script
    assert "function renderResultDeliveryMaterials" in script
    assert "function resultDeliveryMaterialItems" in script
    assert "function renderResultDeliveryMaterialItem" in script
    assert "function resultDeliveryStatus" in script
    assert "const displayStatus = resultDeliveryStatus(status || {})" in script
    assert "status_snapshot" in script
    assert "function normalizeFilePathKey" in script
    assert "function normalizeViewId" in script
    assert "function hashViewId" in script
    assert "function syncViewHash" in script
    assert "function activateInitialView" in script
    assert 'window.addEventListener("hashchange"' in script
    assert "activateInitialView();" in script
    assert "document.getElementById(viewId)?.classList.contains(\"view\")" in script
    assert '"replaceState"' in script
    assert "window.history[method]" in script
    assert '"pushState"' in script
    assert "function clientResultAvailability" in script
    assert "function prioritizedResultFiles" in script
    assert "function renderFileOverflowHint" in script
    assert "result_availability" in script
    assert "primary_schedule_files" in script
    assert "business_floor_adjusted_quality" in script
    assert "相对最优与可优化空间" in script
    assert "当前解牺牲了什么" in script
    assert "仍可优化" in script
    assert "查看剩余差距" in script
    assert "尚未确认已无可优化空间" in script
    assert "候选课表" in script
    assert "当前候选课表继续改善、重新评估剩余差距、收紧目标的顺序复跑" in script
    assert "更严格的差距目标" in script
    assert "已生成课表文件" in script
    assert "结果材料" in script
    assert "排课结果摘要" in script
    assert "课表复盘工作单" in script
    assert "结果清单" in script
    assert "求解状态" in script
    assert "function solverStatusLabel" in script
    assert 'FEASIBLE: "可行解"' in script
    assert 'OPTIMAL: "已证明最优"' in script
    assert "求解状态 ${solverStatusLabel(outcome.solverStatus)}" in script
    assert 'return value ? "开启" : "关闭";' in script
    assert "已设置 ${Object.keys(value).length} 项" in script
    assert '.replace(/\\bPM1\\b/gi, "下午第一节")' in script
    assert "function renderParsedRuleSummary" in script
    assert "JSON.stringify(result.rule, null, 2)" not in script
    assert "release_review_worksheet.csv" not in script
    assert "delivery_manifest.json" in script
    assert "status.json" in script
    assert "这些材料用于核对课表例外、候选缺口和后续微调" in script
    assert "另有" in script
    assert "完整结果包" in script
    assert "resultAvailability" in html
    assert "resultSolverQuality" in html
    assert "resultDeliveryMaterials" in html
    assert "scheduleStatistics" in html
    assert "课表数据驾驶舱" in html
    assert "课表健康洞察" in script
    assert "scheduleVersions" in html
    assert "课表版本时间线" in html
    assert "function renderScheduleStatistics" in script
    assert "function renderScheduleAdjustmentQueue" in script
    assert "function renderScheduleAdjustmentSuggestion" in script
    assert "function renderRuleExplain" in script
    assert "function renderRuleExplainItem" in script
    assert "function renderRuleExplainExamples" in script
    assert "function ruleExplainEntityLabel" in script
    assert "function ruleExplainEventLabel" in script
    assert "影响样例" in script
    assert "全局规则" in script
    assert "值班前连续课限制" in script
    assert "晚查寝安排" in script
    assert "语文外语下午第二节偏好权重" in script
    assert "规则开关" in script
    assert "function renderScheduleStatBars" in script
    assert "function renderScheduleLoadList" in script
    assert "function renderScheduleTeacherDayLoadList" in script
    assert "function renderScheduleInsights" in script
    assert "function renderScheduleVersions" in script
    assert "function renderScheduleVersionItem" in script
    assert "课表风险" in script
    assert "publishReviewQuality" not in script
    assert "publish-review-quality" not in script
    assert "function savePublishReviewDraft" not in script
    assert 'api("/api/publish-review/draft"' not in script
    assert "function importPublishReviewWorksheet" not in script
    assert "function setPublishReviewDraftFields" not in script
    assert "function normalizeReleaseReviewCandidateDraft" not in script
    assert "function renderPublishReviewCandidateDraft" not in script
    assert "function applyPublishReviewCandidateDraft" not in script
    assert 'api("/api/publish-review/worksheet-draft"' not in script
    assert 'api("/api/publish-review/apply-candidate-draft"' not in script
    assert "publishReviewWorksheetInput" not in script
    assert 'data-publish-review-action="save-draft"' not in script
    assert 'data-publish-review-action="apply-candidate-draft"' not in script
    assert "schedulePublishReviewDraftSave" not in script
    assert "release_review_draft" not in script
    assert "release_review_candidate_draft" not in script
    assert "release_preflight" not in script
    assert "function renderPublishGateCheckinLedger" in script
    assert "晚查寝供需账本" in script
    assert "checkin_supply_ledger" in script
    assert "function downloadAcademicTemplate" in script
    assert "function downloadAcademicWorkbookTemplate" in script
    assert "function downloadTeacherCsvTemplate" in script
    assert "function importTeacherFile" in script
    assert "function downloadDayRuleTemplate" in script
    assert "function importDayRuleFile" in script
    assert "function importAcademicFile" in script
    assert "function importAcademicWorkbook" in script
    assert "function buildAcademicWorkbookImportImpact" in script
    assert "function formatSignedDelta" in script
    assert "function importAcademicCsv" in script
    assert "function refreshAcademicPreview" in script
    assert "function formatAuditChangeValue" in script
    assert 'hiddenColumns: ["row_index"]' in script
    assert 'const hiddenColumns = new Set(options.hiddenColumns || ["row_index"]);' in script
    assert "academic_affairs.save" in script
    assert "base_data.teacher_subjects.save" in script
    assert "base_data.day_rules.save" in script
    assert "function dayRuleTableLabel" in script
    assert 'fetch("/api/teacher-subjects/import-file"' in script
    assert 'fetch("/api/academic-affairs/import-file"' in script
    assert 'fetch("/api/academic-affairs/import-workbook"' in script
    assert 'fetch("/api/day-rules/import-file"' in script
    assert "/api/teacher-subjects/template?format=" in script
    assert "/api/academic-affairs/workbook-template" in script
    assert "/api/day-rules/template" in script
    assert 'api("/api/academic-affairs/preview"' in script
    assert "await refreshAcademicPreview();" in script
    assert "teacherImportNotice" in script
    assert "function renderQualityPlanNextStep" in script
    assert "下一轮会换新搜索起点" in script
    assert "academicWorkbookImportNotice" in script
    assert "全量工作簿导入汇总" in script
    assert "风险变化" in script
    assert "尚未保存，保存后才会进入正式配置" in script
    assert "format=xlsx" in script
    assert "下载 Excel 模板" in html
    assert "下载表格模板" in html
    assert "下载全量工作簿" in html
    assert "导入工作簿" in html
    assert "导入表格" in html
    assert "downloadTeacherCsvTemplateBtn" in html
    assert "downloadDayRuleTemplateBtn" in html
    assert "importDayRuleFileBtn" in html
    assert "teacherImportNotice" in html
    assert "academicWorkbookInput" in html
    assert "academicWorkbookImportNotice" in html
    assert "dayRuleFileInput" in html
    assert "dayRuleImportNotice" in html
    assert ".xlsx,.xls,.csv,text/csv" in html
    assert ".xlsx,.csv,text/csv" in html
    assert "academicCsvInput" in html
    assert "academicImportNotice" in html
    web_source = (REPO_ROOT / "scheduler" / "app" / "web.py").read_text(encoding="utf-8")
    assert "RESULT_PREVIEW_PATHS" in web_source
    assert "/api/results/preview" in web_source
    assert "/api/result-preview" in web_source
    assert "/api/solve/result-preview" in web_source
    assert "/api/publish-review/" not in web_source
    assert "DAY_RULE_TABLE_LABELS.get" in web_source
    styles = (REPO_ROOT / "scheduler" / "app" / "static" / "styles.css").read_text(encoding="utf-8")
    assert ".extra-head-draft-note" in styles
    assert ".publish-review-scope" not in styles
    assert ".publish-review-signoff" not in styles
    assert ".publish-review-preflight" not in styles
    assert ".publish-review-quality" not in styles
    assert ".publish-review-quality-grid" not in styles
    assert ".publish-review-draft-status" not in styles
    assert ".publish-review-candidate-draft" not in styles
    assert ".publish-review-candidate-list" not in styles
    assert ".result-formal-candidate" in styles
    assert ".publish-review-actions" not in styles
    assert ".publish-review-import" not in styles
    assert ".result-availability" in styles
    assert ".result-availability-primary" in styles
    assert ".result-file-overflow" in styles
    assert ".result-solver-quality" in styles
    assert ".result-solver-quality-grid" in styles
    assert ".result-solver-quality-next" in styles
    assert ".result-delivery-materials" in styles
    assert ".result-delivery-materials-list" in styles
    assert ".result-delivery-material-item" in styles
    assert ".schedule-statistics" in styles
    assert ".schedule-stat-grid" in styles
    assert ".schedule-adjustment-board" in styles
    assert ".schedule-adjustment-list" in styles
    assert ".schedule-adjustment-item" in styles
    assert ".rule-explain-board" in styles
    assert ".rule-explain-list" in styles
    assert ".rule-explain-item" in styles
    assert ".rule-explain-examples" in styles
    assert ".schedule-stat-bar" in styles
    assert ".schedule-stat-load button" in styles
    assert ".schedule-insight-list" in styles
    assert ".schedule-insight-board" in styles
    assert ".schedule-insight-related" in styles
    assert ".timetable-preview-panel.preview-focus" in styles
    assert "max-height: none" in styles
    assert ".schedule-versions" in styles
    assert ".schedule-version-list" in styles
    assert ".schedule-version-changes" in styles
    assert ".timetable-adjustment-tool" in styles
    assert ".timetable-adjustment-form" in styles
    assert ".timetable-adjustment-summary" in styles
    assert ".timetable-adjustment-plan" in styles
    assert ".academic-import-notice" in styles
    assert ".academic-import-impact" in styles
    assert ".academic-workbook-table-list" in styles
    assert "#teachers > .split.tall" in styles
    assert "#academic > .split.tall" in styles
    assert "grid-auto-rows: auto" in styles
    assert ".timetable-preview-panel" in styles and "min-height: 420px" in styles
    assert "--sidebar-width: clamp(176px, 13vw, 204px)" in styles
    assert "height: 100dvh" in styles
    assert "repeat(auto-fit, minmax(min(100%, 142px), 1fr))" in styles
    assert "grid-template-columns: repeat(2, minmax(0, 1fr));" in styles
    assert "grid-template-columns: repeat(4, minmax(0, 1fr));" in styles
    assert "@media (max-height: 760px) and (min-width: 821px)" in styles
    assert "@media (max-width: 560px)" in styles
    assert ".checkin-ledger-head" in styles and "display: none;" in styles
    assert ".candidate-requirements" in styles
    assert "20260513-director-ui-1" in html
    assert 'data-view="home"' in html
    assert "教务主任工作台" in html
    assert "主任决策看板" in html
    assert "homeDirectorBoard" in html
    assert "homeTodoList" in html
    assert "homeQuickActions" in html
    assert "作息节次" in html
    assert "saveBellScheduleBtn" in html
    assert "bellSchedulePanel" in html
    assert "function renderHomeConsole" in script
    assert "function renderDirectorBoard" in script
    assert "function homeProgressPercent" in script
    assert "function updateTopClock" in script
    assert "function renderBellSchedulePanel" in script
    assert "function saveBellSchedule" in script
    assert "base_data.bell_schedule.save" in script
    assert "calendar.periods" in script
    assert ".home-console" in styles
    assert ".director-board-body" in styles
    assert ".bell-count-grid" in styles
    assert "待确认名单" in script
    assert "manualAdjustmentChange" in html
    assert "manualAdjustClass" in html
    assert "课表微调沙盘" in html
    assert "预览微调影响" in html
    assert "leaveRepairTeacher" in html
    assert "leaveRepairDay" in html
    assert "leaveRepairSlot" in html
    assert "选择请假日志，或直接填写请假教师、星期和节次" in script
    assert "function renderManualAdjustmentTool" in script
    assert "function manualAdjustmentRequestBody" in script
    assert "function renderInsightRelated" in script
    assert "function openPreviewFromInsight" in script
    assert "data-insight-preview-kind" in script
    assert "data-insight-preview-name" in script
    assert "data-stat-preview-kind" in script
    assert "statistics.class_load?.top" in script
    assert "statistics.class_day_load?.top" in script
    assert "statistics.teacher_day_load?.top" in script
    assert "statistics.teacher_consecutive_load?.top" in script
    assert "statistics.rule_explain" in script
    assert "班级课量" in script
    assert "班级日课量" in script
    assert "教师日负荷" in script
    assert "连续课风险" in script
    assert "规则影响解释" in script
    assert "证据源：" not in script
    assert "function renderScheduleClassDayLoadList" in script
    assert "function renderScheduleTeacherDayLoadList" in script
    assert "function renderScheduleTeacherStreakList" in script
    assert "data-schedule-adjustment" in script
    assert "data-consecutive-adjustment" in script
    assert "function prefillManualAdjustmentFromConsecutiveSuggestion" in script
    assert "function prefillManualAdjustmentFromScheduleSuggestion" in script
    assert "manualAdjustmentDraft" in script
    assert "teacher_consecutive_load" in script
    assert "class_day_load_balance" in script
    assert "teacher_day_load_balance" in script
    assert "teacher_day_balance" in script
    assert "教师日负荷均衡" in script
    assert "adjustment_suggestions" in script
    assert "可执行微调建议" in script
    assert "data-schedule-adjustment-label" in script
    assert "$(\"scheduleStatistics\").addEventListener(\"click\"" in script
    assert "教师：" in script
    assert "班级：" in script
    assert "function renderManualAdjustmentClassSchedule" in script
    assert "/api/academic-affairs/timetable-adjustment/preview" in script
    assert "/api/academic-affairs/timetable-adjustment/apply" in script
    assert "function leaveRepairHasSource" in script
    assert "function syncLeaveRepairFieldsFromLog" in script
    assert "function renderLeaveRepairCandidateMatrix" in script
    assert "function renderLeaveRepairCandidateOption" in script
    assert "repair.candidate_options" in script
    assert "代课候选影响矩阵" in script
    assert "系统推荐" in script
    assert ".leave-repair-candidates" in styles
    assert ".leave-repair-candidate" in styles
    assert ".leave-repair-candidate-impact" in styles
    assert "body.teacher = teacher" in script
    assert "body.day = day" in script
    assert "body.slot = slot" in script
    assert "/api/academic-affairs/leave-repair/preview" in script
    assert "/api/academic-affairs/leave-repair/apply" in script


def test_external_exception_remediation_is_advisory_only() -> None:
    script = (REPO_ROOT / "scheduler" / "app" / "static" / "app.js").read_text(encoding="utf-8")

    assert "function renderRemediationDecisionPoints" in script
    assert "走学校既有流程记录" in script
    assert "external_record" in script
    assert "function publishReviewDraftFromRemediation" not in script
    assert "function applyPublishReviewDraftFromRemediation" not in script
    assert 'option.id === "publish.checkin.confirm_exception"' not in script

    function_start = script.index("function renderRemediationDecisionPoints")
    function_end = script.index("function parseExtraHeadDays", function_start)
    function_body = script[function_start:function_end]
    assert 'api("/api/publish-review/acknowledge"' not in function_body


def test_conflict_detector_returns_certified_unsat_core_for_night_rules() -> None:
    cfg = {
        "teacher_table": {"columns": {"class": "班级"}},
        "calendar": {"days": ["星期一", "星期日"], "periods": ["晚自习1", "晚自习2"]},
        "evening": {"subjects": ["语文"], "weekly_occurrences_per_subject": 2},
        "hard_bans": {"enabled": True, "teacher_day_bans": {"星期一": ["教师A"], "星期日": ["教师A"]}},
    }
    rows = [{"班级": "1班", "语文": "教师A"}]
    result = detect_rule_conflicts(cfg, rows)
    assert result["summary"]["errors"] == 1
    assert result["conflicts"][0]["id"].startswith("night.unsat_core")
    assert result["conflicts"][0]["certainty"] == "确定冲突"
    assert "night.base.weekly_occurrences_per_subject" in result["conflicts"][0]["rules"]
    assert "hard_bans.teacher_day_bans.星期一.教师A" in result["conflicts"][0]["rules"]
    assert "hard_bans.teacher_day_bans.星期日.教师A" in result["conflicts"][0]["rules"]
    assert result["graph"]["nodes"]


def test_conflict_detector_does_not_report_unproven_config_warning() -> None:
    cfg = {
        "calendar": {"days": ["星期一", "星期日"], "periods": ["晚自习1", "晚自习2"]},
        "hard_bans": {"teacher_day_bans": {"星期一": ["教师A"], "星期日": ["教师A"]}},
    }
    result = detect_rule_conflicts(cfg)
    assert result["summary"]["total"] == 0


def test_web_overrides_file_is_merged(tmp_path: Path) -> None:
    io_path = tmp_path / "io.yaml"
    rules_path = tmp_path / "rules.yaml"
    web_path = tmp_path / "web_overrides.yaml"
    io_path.write_text("teacher_table:\n  path: base.xlsx\n", encoding="utf-8")
    rules_path.write_text(
        "calendar:\n  days: [星期一]\nhard_bans:\n  teacher_day_bans:\n    星期一: []\n",
        encoding="utf-8",
    )
    web_path.write_text(
        yaml.safe_dump(
            {
                "rules": {
                    "hard_bans": {
                        "teacher_day_bans": {
                            "星期一": ["教师A"],
                        }
                    }
                },
                "temporary_rules": {
                    "active": [{"id": "tmp.nl.demo"}],
                },
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    effective = load_effective_config("joint", {"io_path": io_path, "rules_path": rules_path})
    assert effective.rules_cfg["hard_bans"]["teacher_day_bans"]["星期一"] == ["教师A"]
    assert effective.rules_cfg["temporary_rules"]["active"][0]["id"] == "tmp.nl.demo"


def test_teacher_table_reader_prefers_web_rows() -> None:
    io_cfg = {
        "teacher_table": {
            "path": "missing.xlsx",
            "sheet_name": 0,
            "columns": {"class": "班级", "head": "班主任", "head_gender": "班主任性别"},
        },
        "web_tables": {
            "teacher_subjects": [
                {"班级": "1班", "班主任": "教师A", "班主任性别": "男", "语文": "教师B"},
            ]
        },
    }
    rules = {"evening": {"subjects": ["语文"], "max_subjects_per_class": 6}}
    classes, cst, ts, male_heads, female_heads = read_teacher_table(io_cfg, rules)
    assert classes == ["1班"]
    assert cst[("1班", "语文")] == "教师B"
    assert ts[("教师B", "语文")] == ["1班"]
    assert male_heads == ["教师A"]
    assert female_heads == []


def test_uploaded_subject_headers_drive_night_model_without_technical_or_head_columns(tmp_path: Path) -> None:
    io_cfg = {
        "teacher_table": {
            "columns": {"class": "班级", "head": "班主任", "head_gender": "班主任性别"},
        },
        "web_tables": {
            "teacher_subjects": [
                {"班级": "1班", "语文": "教师A", "综合实践": "教师B"},
            ]
        },
    }
    rules = {
        "calendar": {"days": ["星期一", "星期二"], "periods": ["晚自习1", "晚自习2"]},
        "evening": {"subjects": [], "max_subjects_per_class": 6, "weekly_occurrences_per_subject": 2},
        "hard_bans": {"enabled": False},
        "checkin": {"enabled": True, "per_day": {"male": 1, "female": 1}},
        "soft": {"enabled": False},
        "personalized_constraints": {"enabled": False},
        "output": {"result_xlsx": "result.xlsx"},
    }

    classes, cst, _ts, male_heads, female_heads = read_teacher_table(io_cfg, rules)
    assert classes == ["1班"]
    assert set(cst) == {("1班", "语文"), ("1班", "综合实践")}
    assert male_heads == []
    assert female_heads == []

    model = cp_model.CpModel()
    result = build_night_model(
        model,
        tmp_path / "project" / "config" / "rules.yaml",
        tmp_path / "project" / "config" / "io.yaml",
        "uploaded-schema",
        io_cfg=io_cfg,
        rules_cfg=rules,
    )
    assert result.rules["checkin"]["enabled"] is False
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 5
    assert solver.Solve(model) in {cp_model.OPTIMAL, cp_model.FEASIBLE}


def test_day_inputs_prefers_web_rule_tables() -> None:
    web_tables = {
        "teacher_subjects": [
            {"班级": "1班", "班主任": "教师A", "班主任性别": "男", "语文": "教师B"},
        ],
        "day_rules": {
            "time_grid": [
                {"时段节次": "早自习2", "星期一": 1, "星期二": 0, "星期三": 0, "星期四": 0, "星期五": 0, "星期六": 0, "星期日": 0},
                {"时段节次": "上午1", "星期一": 1, "星期二": 0, "星期三": 0, "星期四": 0, "星期五": 0, "星期六": 0, "星期日": 0},
            ],
            "fixed_slots": [],
            "subject_hours": [
                {"学科": "语文", "早自习课时": 0, "周中课时": 1, "周末课时": 0},
            ],
            "subject_bans": [],
            "class_overrides": [],
        },
    }
    data = load_day_inputs("missing-rules.xlsx", "missing-teachers.xlsx", web_tables)
    assert data.classes == ["1班"]
    assert data.cls_subj_teacher[("1班", "语文")] == "教师B"
    assert data.req_hours[("1班", "语文")] == (0, 1, 0)
    assert len(data.available_slots) == 2
    assert any(slot.block == "早自习" and slot.period == 2 for slot in data.available_slots)


def test_time_grid_template_matches_solver_columns() -> None:
    imported = config_service.parse_day_rule_table_csv(
        "time_grid",
        config_service.build_day_rule_table_template_csv("time_grid").decode("utf-8-sig"),
    )

    row = imported["rows"][0]
    assert imported["table"] == "time_grid"
    assert "时段节次" in row
    assert {"星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"} <= set(row)


def test_academic_affairs_summary_detects_k12_admin_risks() -> None:
    payload = normalize_academic_affairs(
        {
            "tables": {
                "substitutions": [
                    {"日期": "2026-05-06", "星期": "星期三", "节次": "上午1", "班级": "1班", "原教师": "教师A", "代课教师": "教师B", "原因": "请假", "状态": "待审批"},
                ],
                "exam_duties": [
                    {"考试名称": "期中考试", "日期": "2026-05-10", "时段": "上午", "科目": "语文", "考场": "一考场", "所需监考数": "2", "已排监考教师": "教师C", "特殊要求": ""},
                ],
                "after_school": [
                    {"课程名称": "篮球", "适用年级": "七年级", "星期": "星期一", "时段": "课后服务1", "负责教师": "赵六", "场地": "操场", "容量": "20", "报名人数": "25", "补贴口径": ""},
                    {"课程名称": "足球", "适用年级": "七年级", "星期": "星期一", "时段": "课后服务1", "负责教师": "钱七", "场地": "操场", "容量": "30", "报名人数": "10", "补贴口径": ""},
                ],
            }
        }
    )
    summary = summarize_academic_affairs(payload)
    titles = {item["title"] for item in summary["risks"]}
    assert "存在未审批调代课" in titles
    assert "监考教师数量不足" in titles
    assert "课后服务报名超容量" in titles
    assert "课后服务场地冲突" in titles
    assert summary["metrics"]["pending_substitutions"] == 1
    assert summary["teacher_load_top"]
