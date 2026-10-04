from __future__ import annotations

from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[3]


def test_container_runs_as_non_root_and_keeps_runtime_data_outside_image_layer() -> None:
    dockerfile = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "USER 10001:10001" in dockerfile
    assert 'ENTRYPOINT ["/usr/bin/tini", "-g", "--"]' in dockerfile
    assert "COPY . " not in dockerfile
    assert "COPY deploy/seed ./deploy/seed" in dockerfile
    assert "/app/outputs" in dockerfile

    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert '"config/*.yaml"' not in pyproject
    assert '"config/io.yaml"' in pyproject and '"config/rules.yaml"' in pyproject
    assert "include-package-data = false" in pyproject
    assert '"scheduler.config" = ["web_overrides.yaml"]' in pyproject


def test_compose_separates_web_worker_bootstrap_and_persistent_data() -> None:
    compose = yaml.safe_load((REPO_ROOT / "deploy" / "compose.yaml").read_text(encoding="utf-8"))
    services = compose["services"]

    assert {"bootstrap", "admin-bootstrap", "web", "worker", "caddy"} <= set(services)
    assert services["web"]["read_only"] is True
    assert services["worker"]["read_only"] is True
    assert services["web"]["environment"]["SCHEDULER_AUTH_MODE"] == "required"
    assert services["web"]["environment"]["SCHEDULER_SOLVE_MODE"] == "async"
    assert services["web"]["volumes"] == ["scheduler_data:/app/outputs"]
    assert services["web"]["depends_on"]["admin-bootstrap"]["condition"] == "service_completed_successfully"
    assert services["admin-bootstrap"]["secrets"] == ["scheduler_admin_password"]
    assert "/run/secrets/scheduler_admin_password" in services["admin-bootstrap"]["command"]
    assert "/app/deploy/seed/blank_school.yaml" in services["bootstrap"]["command"]
    assert "/app/scheduler/config/web_overrides.yaml" not in services["bootstrap"]["command"]
    assert "healthcheck" in services["web"] and "healthcheck" in services["worker"]
    assert services["caddy"]["profiles"] == ["tls"]


def test_deployment_examples_do_not_embed_a_real_secret() -> None:
    env_example = (REPO_ROOT / "deploy" / ".env.example").read_text(encoding="utf-8")
    compose_text = (REPO_ROOT / "deploy" / "compose.yaml").read_text(encoding="utf-8")

    assert "DOMESTIC_AI_API_KEY=" in env_example
    assert "SCHEDULER_ADMIN_PASSWORD_FILE=" in env_example
    assert "SCHEDULER_BOOTSTRAP_PASSWORD=" not in env_example
    assert "replace-with-a-long-random-secret" in env_example
    assert "sk-" not in env_example
    assert "sk-" not in compose_text
    assert "deploy/.env" in (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")


def test_deployment_seed_is_empty_and_privacy_audit_passes() -> None:
    from verification.fixes.deployment_privacy_audit import run_audit

    seed = yaml.safe_load((REPO_ROOT / "deploy" / "seed" / "blank_school.yaml").read_text(encoding="utf-8"))
    assert seed["io"] == {}
    assert seed["rules"] == {}
    assert seed["temporary_rules"]["active"] == []
    assert seed["academic_affairs"]["tables"] == {}
    assert seed["change_audit"]["entries"] == []
    assert run_audit(REPO_ROOT)["status"] == "passed"


def test_release_workflow_runs_python_gate_builds_wheel_and_smokes_containers() -> None:
    workflow = (REPO_ROOT / ".github" / "workflows" / "release-gate.yml").read_text(encoding="utf-8")

    assert "permissions:\n  contents: read" in workflow
    assert "persist-credentials: false" in workflow
    assert "verification/fixes/run_dev_gate.py" in workflow
    assert "python -m pip wheel" in workflow
    assert "docker compose" in workflow and "--wait-timeout 180" in workflow
    assert "/api/health/ready" in workflow
    assert "--require-worker" in workflow
    assert "actions/checkout@d23441a48e516b6c34aea4fa41551a30e30af803" in workflow
