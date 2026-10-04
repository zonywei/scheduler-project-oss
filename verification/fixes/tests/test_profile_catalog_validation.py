from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


from scheduler.config.loader import load_effective_config  # noqa: E402
from scheduler.app.config_service import load_profile_catalog_payload, load_school_problem_preview_payload  # noqa: E402
from scheduler.domain.profile_catalog import profile_catalog_payload, validate_profile_catalog  # noqa: E402


def _effective_cfg() -> dict:
    return load_effective_config(
        "joint",
        {
            "io_path": REPO_ROOT / "scheduler" / "config" / "io.yaml",
            "rules_path": REPO_ROOT / "scheduler" / "config" / "rules.yaml",
        },
    ).effective_cfg


def test_profile_catalog_validator_covers_all_persisted_school_shapes() -> None:
    report = validate_profile_catalog(REPO_ROOT / "profiles", _effective_cfg(), mode="joint")
    payload = profile_catalog_payload(report)

    assert report.ok
    assert payload["summary"]["profiles"] == 4
    assert payload["summary"]["sample_problems"] == 3
    assert payload["summary"]["profile_ids"] == [
        "base_high_school",
        "current_school",
        "junior_day_school",
        "primary_after_school",
    ]
    coverage = payload["rule_coverage"]
    assert coverage["schema_version"] == "scheduler.rule_coverage_matrix.v1"
    assert coverage["solver_effect"] == "none"
    assert coverage["summary"]["profiles"] == 4
    assert coverage["summary"]["sample_problem_profiles"] == 3
    assert coverage["summary"]["template_rules"] == 47
    assert coverage["summary"]["cross_profile_templates"] == 2
    assert coverage["summary"]["current_school_only_templates"] == 45
    by_id = {item["profile_id"]: item for item in payload["profiles"]}
    assert by_id["current_school"]["sample_problem"] is None
    assert by_id["current_school"]["rule_instances"] == 46
    assert by_id["current_school"]["personalized_rule_catalog"]["solver_effect"] == "none"
    assert by_id["current_school"]["personalized_rule_catalog"]["migration_status"] == "granular_profile_rule_instances_present"
    assert by_id["current_school"]["personalized_rule_catalog"]["summary"]["legacy_group_declared"] is True
    assert by_id["current_school"]["personalized_rule_catalog"]["summary"]["profile_rule_instances"] == 43
    assert by_id["current_school"]["personalized_rule_catalog"]["summary"]["granular_profile_rule_instances"] == 42
    assert by_id["base_high_school"]["sample_problem"]["classes"] == 2
    assert by_id["junior_day_school"]["sample_problem"]["stage"] == "junior"
    assert by_id["primary_after_school"]["sample_problem"]["rule_instances"] == 1
    assert all(item["execution_plan_items"] > 0 for item in payload["profiles"])
    coverage_by_profile = {item["profile_id"]: item for item in coverage["profiles"]}
    assert coverage_by_profile["current_school"]["rule_families"]["personalized"] == 42
    coverage_by_template = {item["template_id"]: item for item in coverage["templates"]}
    assert coverage_by_template["night.fri_sun_mutex"]["profile_ids"] == ["base_high_school", "current_school"]
    assert coverage_by_template["day.am1_pm1_mutex"]["profile_ids"] == ["junior_day_school", "primary_after_school"]
    assert coverage_by_template["personalized.xhd_night_no_pm3"]["current_school_only"] is True


def test_validate_profiles_script_is_a_machine_checkable_gate() -> None:
    result = subprocess.run(
        [sys.executable, "verification/fixes/validate_profiles.py"],
        cwd=REPO_ROOT,
        check=True,
        text=True,
        capture_output=True,
    )
    summary = json.loads(result.stdout)

    assert summary["ok"] is True
    assert summary["profiles"] == 4
    assert summary["sample_problems"] == 3


def test_profile_catalog_web_payload_is_visibility_only() -> None:
    payload = load_profile_catalog_payload("joint")

    assert payload["schema_version"] == "scheduler.profile_catalog.web.v1"
    assert payload["source"] == "profile_catalog"
    assert payload["summary"]["ok"] is True
    assert payload["summary"]["profiles"] == 4
    assert payload["contract"] == {
        "scope": "cross_school_profile_validation",
        "solver_effect": "none",
        "can_block_solver": False,
    }
    assert payload["rule_coverage"]["contract"] == {
        "scope": "cross_school_rule_instance_coverage",
        "solver_effect": "none",
        "can_block_solver": False,
    }
    assert payload["paths"]["profiles_root"].endswith("profiles")


def test_school_problem_preview_web_payload_is_visibility_only() -> None:
    payload = load_school_problem_preview_payload("joint")

    assert payload["schema_version"] == "scheduler.school_problem_preview.v1"
    assert payload["source"] == "web_preview"
    assert payload["solver_effect"] == "none"
    assert payload["mode"] == "joint"
    assert payload["adapter"]["source"] == "DayInputData"
    assert "summary" in payload
    assert "validation" in payload


def test_main_web_exposes_profile_catalog_without_solver_coupling() -> None:
    web = (REPO_ROOT / "scheduler" / "app" / "web.py").read_text(encoding="utf-8")
    script = (REPO_ROOT / "scheduler" / "app" / "static" / "app.js").read_text(encoding="utf-8")

    assert '"/api/profiles/catalog"' in web
    assert "/api/profiles/catalog?mode=" in script
    assert 'data-contract="cross-school-profile-catalog"' in script
    assert "cross_school_profile_validation" in (REPO_ROOT / "scheduler" / "app" / "config_service.py").read_text(encoding="utf-8")


def test_main_web_exposes_school_problem_preview_without_solver_coupling() -> None:
    web = (REPO_ROOT / "scheduler" / "app" / "web.py").read_text(encoding="utf-8")
    script = (REPO_ROOT / "scheduler" / "app" / "static" / "app.js").read_text(encoding="utf-8")
    config_service = (REPO_ROOT / "scheduler" / "app" / "config_service.py").read_text(encoding="utf-8")
    preview_service = (REPO_ROOT / "scheduler" / "app" / "school_problem_preview.py").read_text(encoding="utf-8")

    assert '"/api/school-problem/preview"' in web
    assert "/api/school-problem/preview?mode=" in script
    assert 'data-contract="school-problem-preview"' in script
    assert "load_school_problem_preview_payload" in config_service
    assert '"solver_effect": "none"' in preview_service
