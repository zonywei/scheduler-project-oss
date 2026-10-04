from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
STATIC_ROOT = REPO_ROOT / "scheduler" / "app" / "static"


def test_saas_shell_exposes_real_authentication_and_session_controls() -> None:
    html = (STATIC_ROOT / "index.html").read_text(encoding="utf-8")
    script = (STATIC_ROOT / "app.js").read_text(encoding="utf-8")

    for contract in ("authGate", "loginForm", "loginUsername", "loginPassword", "logoutBtn"):
        assert contract in html
    for brand in ("课有序", "CourseOrder AI"):
        assert brand in html
    for login_surface in ("auth-showcase", "auth-login-panel", "open-login-help", "请输入账号", "请输入密码"):
        assert login_surface in html
    assert "loginOrganization" not in html
    assert "学校标识" not in html
    assert "auth-first-use" not in html
    assert "auth-security" not in html
    assert "organization_slug" not in script
    assert "/api/auth/session" in script
    assert "/api/auth/login" in script
    assert "/api/auth/logout" in script
    assert 'credentials: "same-origin"' in script
    assert 'headers["X-CSRF-Token"]' in script
    assert "authIsRequired()" in script


def test_saas_shell_exposes_durable_jobs_and_idempotent_solve_start() -> None:
    html = (STATIC_ROOT / "index.html").read_text(encoding="utf-8")
    script = (STATIC_ROOT / "app.js").read_text(encoding="utf-8")

    assert 'data-view="jobs"' in html
    assert "排课记录" in html
    assert 'id="navMore"' in html
    assert "/api/solve/jobs?limit=30" in script
    assert '"Idempotency-Key": createIdempotencyKey()' in script
    assert "renderJobQueueCard" in script
    assert "workspace_revision" in script
    assert "/cancel" in script


def test_saas_shell_keeps_metered_ai_internal_without_browser_secrets_or_user_configuration() -> None:
    html = (STATIC_ROOT / "index.html").read_text(encoding="utf-8")
    script = (STATIC_ROOT / "app.js").read_text(encoding="utf-8")

    assert 'data-view="usage"' not in html
    assert "AI 助手设置" not in html
    assert "模型服务接入" in script
    assert "/api/model/usage" in script
    assert "/api/model/quota" in script
    assert "/api/ai-settings" in script
    assert "/api/ai-settings/test" in script
    assert 'id="aiWireApi"' in script
    assert 'value="responses"' in script
    assert "disable_response_storage: true" in script
    assert "aiApiKeyEnv" in script
    assert 'placeholder="https://.../v1"' in script
    assert 'name="api_key"' not in html
    assert 'id="aiApiKey"' not in script
    assert "不发送整份教师表，也不保存原始提示词" in script
    assert "usage-probe-note" in script


def test_rule_workspace_uses_business_titles_and_hides_technical_ids_by_default() -> None:
    script = (STATIC_ROOT / "app.js").read_text(encoding="utf-8")

    assert "group.title || group.label" in script
    assert "rule.title || rule.label" in script
    assert "rule.explanation || rule.description" in script
    assert "rule-tech-meta" in script
    assert "先展示最常用的" in script
    assert "show-more-rules" in script


def test_edu_facing_shell_uses_the_formal_ai_scheduling_flow() -> None:
    html = (STATIC_ROOT / "index.html").read_text(encoding="utf-8")
    script = (STATIC_ROOT / "app.js").read_text(encoding="utf-8")
    styles = (STATIC_ROOT / "styles.css").read_text(encoding="utf-8")
    formal_script = (STATIC_ROOT / "formal-v2.js").read_text(encoding="utf-8")
    formal_styles = (STATIC_ROOT / "formal-v2.css").read_text(encoding="utf-8")

    for label in ("项目概览", "基础设置", "规则中心", "求解与优化", "课表发布"):
        assert label in html
    for secondary in ("排课记录", "问题处理"):
        assert secondary in html
    assert 'data-view="conversation"' in html
    assert "AI 对话排课" in html
    assert "AI 助手设置" not in html
    for positioning in ("不必让学校迁就固定规则", "让 AI 读懂你的排课要求", "工业级求解引擎"):
        assert positioning in html

    assert "AI 整理规则" in formal_script
    assert "AI 不直接猜课表" in formal_script
    assert "启动 AI 智能排课" in formal_script
    assert "AI 排课工作原理" in formal_script
    assert "本次排课输入" in formal_script
    assert "formalWorkflow" in formal_script
    assert "formal-workflow-summary" in formal_script
    assert "formalRuleDraftPanel" in formal_script
    assert "AI 本次未完成规则整理" in formal_script
    assert "本地安全草案" in formal_script
    assert "AI 正在理解规则" in formal_script
    assert "复杂规则可能需要 1–2 分钟" in formal_script
    assert "next-formal-rule-page" in formal_script
    assert "previous-formal-rule-page" in formal_script
    assert "formalRuleCards" in formal_script
    assert "AI 已实际理解并整理这条规则" in formal_script
    assert "阻断审查" in formal_script
    assert "/api/readiness/ai-review" in formal_script
    assert "download-result-view" in formal_script
    for export_view in ('["class", "班级课表"', '["teacher", "教师课表"', '["academic", "教务总表"'):
        assert export_view in formal_script
    assert "formalSolveTimeline" in formal_script
    assert "结果待核验" in formal_script
    assert "重新启动 AI 智能排课" in formal_script
    assert "content.scrollTop = 0" in formal_script
    assert "/api/rules/v2" in formal_script
    assert "/api/project/state" in formal_script
    assert "publish-candidate" in formal_script
    for selector in (".welcome-gate", ".formal-workflow", ".formal-workflow-summary", ".rule-workbench", ".ai-rule-steps", ".ai-rule-running", ".rule-draft-origin", ".solve-bridge", ".solve-engine-card", ".publish-grid"):
        assert selector in formal_styles

    conversation_script = (STATIC_ROOT / "conversation.js").read_text(encoding="utf-8")
    conversation_styles = (STATIC_ROOT / "conversation.css").read_text(encoding="utf-8")
    for contract in ("upload_base", "existing_timetable", "open-conversation-optimization", "conversation-confirm", "conversation-solve"):
        assert contract in conversation_script
    for copy in ("本地 skill 编排，AI 可选增强", "确认前不会写入正式规则", "工业级求解"):
        assert copy in conversation_script
    for selector in (".conversation-shell", ".conversation-entry-grid", ".conversation-thread", ".conversation-context", ".premium-optimization-entry"):
        assert selector in conversation_styles

    assert "overviewNextAction" in script
    assert "renderHomeTodoCard" in script
    assert "需要逐项修改？展开基础表格" in script
    assert "供应商与计费参数（技术管理员）" in script
    assert "formalRulePageSize: 9" in script
    for foundation_contract in ("一周班级空白课表", "修改节次", "下载 Excel 模板", "每周相同", "大小周"):
        assert foundation_contract in formal_script
    for rule_contract in ("课表设规则", "未发现重合或矛盾", "查看并调整", "AI 助手"):
        assert rule_contract in formal_script
    assert ".home-focus" in styles
    assert ".data-source-grid" in styles
    assert ".secondary-disclosure" in styles


def test_operational_ui_redacts_server_paths_and_limits_file_noise() -> None:
    script = (STATIC_ROOT / "app.js").read_text(encoding="utf-8")

    assert "safeOperationalText" in script
    assert "服务器文件" in script
    assert "fileBaseName" in script
    assert "filePriority" in script
    assert "show-more-files" in script


def test_edu_onboarding_teaches_the_next_action_and_remains_reopenable() -> None:
    html = (STATIC_ROOT / "index.html").read_text(encoding="utf-8")
    formal_script = (STATIC_ROOT / "formal-v2.js").read_text(encoding="utf-8")
    formal_styles = (STATIC_ROOT / "formal-v2.css").read_text(encoding="utf-8")

    assert 'id="openGuideBtn"' in html
    assert "首次使用不用先看说明" not in html
    assert "scheduler.eduOnboarding.v1.completed" in formal_script
    assert "formalMaybeOpenUserGuide" not in formal_script
    assert 'formalOpenUserGuide("automatic")' not in formal_script
    assert "不用懂算法，按这 5 个阶段完成排课" in formal_script
    assert "formalPageHintData" in formal_script
    assert "本页提示" in formal_script
    assert "开始前准备" in formal_script
    assert "做到这里算完成" in formal_script
    assert "formalPageGuide" not in formal_script
    assert "去描述第一条规则" in formal_script
    assert "不知道怎么写？先点一个示例" not in formal_script
    assert "查看规则示例" in formal_script
    assert "toggle-rule-examples" in formal_script
    assert "use-rule-example" in formal_script
    assert "教师A" in formal_script
    assert ("张" + "老师") not in formal_script
    for selector in (".sidebar-guide", ".formal-hint-button", ".formal-page-hint-modal", ".formal-guide-modal", ".ai-rule-help-button", ".ai-rule-examples"):
        assert selector in formal_styles
