from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]


def test_edu_ops_console_is_the_production_ui_source_of_truth() -> None:
    source_root = REPO_ROOT / "edu-ops-scheduler-console"
    assert (source_root / "index.html").exists()
    assert (source_root / "assets" / "ui.css").exists()
    assert (source_root / "assets" / "layout-polish.css").exists()
    assert (source_root / "assets" / "layout-repair.css").exists()
    for screen in (
        "01-workbench.html",
        "02-data-intake.html",
        "03-rule-intake.html",
        "04-diagnostics.html",
        "05-solver-run.html",
        "06-results-delivery.html",
        "07-timetable-preview.html",
    ):
        assert (source_root / "screens" / screen).exists()

    docs = (REPO_ROOT / "docs" / "ui" / "edu_ops_console_integration.md").read_text(encoding="utf-8")
    assert "`edu-ops-scheduler-console/` is the source of truth" in docs
    assert "Do not treat `scheduler/app/static/legacy/` as a design source or compatibility archive" in docs


def test_main_static_shell_tracks_edu_ops_console_contract() -> None:
    html = (REPO_ROOT / "scheduler" / "app" / "static" / "index.html").read_text(encoding="utf-8")
    script = (REPO_ROOT / "scheduler" / "app" / "static" / "app.js").read_text(encoding="utf-8")
    formal_script = (REPO_ROOT / "scheduler" / "app" / "static" / "formal-v2.js").read_text(encoding="utf-8")
    styles = (REPO_ROOT / "scheduler" / "app" / "static" / "styles.css").read_text(encoding="utf-8")
    formal_styles = (REPO_ROOT / "scheduler" / "app" / "static" / "formal-v2.css").read_text(encoding="utf-8")

    assert 'data-ui-source="edu-ops-scheduler-console"' in html
    assert "课有序" in html
    assert "CourseOrder AI" in html
    assert "本学期排课工作台" in html
    for label in ("项目概览", "基础设置", "规则中心", "求解与优化", "课表发布", "问题处理"):
        assert label in html

    for positioning in ("不必让学校迁就固定规则", "让 AI 读懂你的排课要求", "工业级求解引擎"):
        assert positioning in html

    for contract in (
        "formalWorkflow",
        "formalRuleDraftPanel",
        "formalSolveTimeline",
        'ACTION_PERMISSIONS["publish-candidate"]',
        "/api/rules/v2",
        "/api/project/state",
    ):
        assert contract in formal_script

    for selector in (
        ".welcome-gate",
        ".formal-workflow",
        ".foundation-layout",
        ".rule-workbench",
        ".solve-engine-card",
        ".publish-grid",
    ):
        assert selector in formal_styles

    assert "const VIEW_BODY_CLASSES" in script
    assert "syncEduOpsBodyClass" in script
    assert 'document.body.dataset.uiSource = "edu-ops-scheduler-console"' in script
    assert "home-page page-home" in script
    assert "screen-page page-release" in script

    assert "UI source-of-truth: edu-ops-scheduler-console" in styles
    assert ".rail.sidebar" in styles
    assert ".nav-item.nav-link.is-active" in styles
    assert ".nav-more" in styles
    assert ".home-focus" in styles
    assert ".data-source-grid" in styles
    assert ".brand-logo" in styles


def test_edu_ops_mobile_shell_overrides_follow_source_of_truth_rules() -> None:
    styles = (REPO_ROOT / "scheduler" / "app" / "static" / "styles.css").read_text(encoding="utf-8")

    source_marker = styles.index("/* UI source-of-truth: edu-ops-scheduler-console */")
    source_tail = styles[source_marker:]
    media_marker = source_tail.index("@media (max-width: 760px)")
    mobile_tail = source_tail[media_marker:]

    assert "body[data-ui-source=\"edu-ops-scheduler-console\"] .app-shell" in mobile_tail
    assert "grid-template-columns: minmax(0, 1fr)" in mobile_tail
    assert "body[data-ui-source=\"edu-ops-scheduler-console\"] .rail.sidebar" in mobile_tail
    assert "body[data-ui-source=\"edu-ops-scheduler-console\"] .nav-list.nav" in mobile_tail
    assert "body[data-ui-source=\"edu-ops-scheduler-console\"] .nav-item.nav-link" in mobile_tail
    assert "body[data-ui-source=\"edu-ops-scheduler-console\"] .content" in mobile_tail
    assert "max-width: 100vw" in mobile_tail
