from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
TEXT_SUFFIXES = {
    ".cfg",
    ".css",
    ".html",
    ".js",
    ".json",
    ".md",
    ".ps1",
    ".py",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}
FORBIDDEN_RELEASE_SUFFIXES = {
    ".csv",
    ".db",
    ".sqlite",
    ".sqlite3",
    ".xls",
    ".xlsx",
    ".zip",
}
FORBIDDEN_RELEASE_PREFIXES = (
    "deploy/secrets/",
    "output/",
    "outputs/",
    "scheduler/outputs/",
    "tmp/",
    "var/",
)
PERSONAL_PATTERNS = {
    "windows_user_path": re.compile(r"\b[A-Za-z]:\\Users\\[^\s\\/:*?\"<>|]+"),
    "mainland_mobile": re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"),
    "mainland_id_number": re.compile(r"(?<!\d)\d{17}[0-9Xx](?!\d)"),
}
EMAIL_PATTERN = re.compile(r"[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})")
SAFE_EXAMPLE_DOMAINS = {"example.cn", "example.com", "example.test"}


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit the deployable source boundary for private data and secrets")
    parser.add_argument("--output", type=Path, default=None, help="Optional JSON evidence file")
    args = parser.parse_args()
    result = run_audit(REPO_ROOT)
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output is not None:
        output_path = Path(args.output).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered + "\n", encoding="utf-8")
    sys.stdout.write(rendered + "\n")
    if result["status"] != "passed":
        raise SystemExit(1)


def run_audit(repo_root: Path) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    release_paths = _release_candidate_paths(root)
    checks = [
        _release_file_hygiene_check(release_paths),
        _personal_marker_check(root, release_paths),
        _deidentified_ui_examples_check(root),
        _deployment_seed_check(root),
        _container_boundary_check(root),
        _secret_example_check(root),
    ]
    return {
        "schema_version": "scheduler.deployment-privacy-audit.v1",
        "status": "passed" if all(check["status"] == "passed" for check in checks) else "failed",
        "release_candidate_files": len(release_paths),
        "checks": checks,
    }


def _release_candidate_paths(root: Path) -> tuple[Path, ...]:
    completed = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.decode("utf-8", errors="replace").strip())
    relative_paths = sorted(
        {
            item.decode("utf-8", errors="strict").replace("\\", "/")
            for item in completed.stdout.split(b"\0")
            if item
        }
    )
    return tuple(root / relative for relative in relative_paths if (root / relative).is_file())


def _release_file_hygiene_check(paths: tuple[Path, ...]) -> dict[str, Any]:
    violations: list[dict[str, str]] = []
    for path in paths:
        relative = path.relative_to(REPO_ROOT).as_posix()
        lowered = relative.lower()
        if lowered == "deploy/.env" or any(lowered.startswith(prefix) for prefix in FORBIDDEN_RELEASE_PREFIXES):
            violations.append({"path": relative, "reason": "runtime_or_secret_path"})
        elif path.suffix.lower() in FORBIDDEN_RELEASE_SUFFIXES:
            violations.append({"path": relative, "reason": "raw_or_generated_data_type"})
    return _check(
        "release_file_hygiene",
        not violations,
        candidate_files=len(paths),
        violations=violations,
    )


def _personal_marker_check(root: Path, paths: tuple[Path, ...]) -> dict[str, Any]:
    violations: list[dict[str, str]] = []
    scanned = 0
    for path in paths:
        if path.suffix.lower() not in TEXT_SUFFIXES or path.stat().st_size > 2_000_000:
            continue
        scanned += 1
        text = path.read_text(encoding="utf-8-sig")
        relative = path.relative_to(root).as_posix()
        for label, pattern in PERSONAL_PATTERNS.items():
            if pattern.search(text):
                violations.append({"path": relative, "reason": label})
        for match in EMAIL_PATTERN.finditer(text):
            domain = match.group(1).lower()
            if domain not in SAFE_EXAMPLE_DOMAINS:
                violations.append({"path": relative, "reason": "non_example_email"})
                break
    return _check(
        "personal_marker_scan",
        not violations,
        text_files_scanned=scanned,
        violations=violations,
    )


def _deidentified_ui_examples_check(root: Path) -> dict[str, Any]:
    static_root = root / "scheduler" / "app" / "static"
    forbidden_teacher_examples = ("张" + "老师", "李" + "老师", "王" + "老师", "刘" + "老师", "陈" + "老师")
    violations: list[dict[str, str]] = []
    scanned = 0
    for path in sorted(static_root.glob("*")):
        if not path.is_file() or path.suffix.lower() not in {".html", ".js"}:
            continue
        scanned += 1
        text = path.read_text(encoding="utf-8-sig")
        for marker in forbidden_teacher_examples:
            if marker in text:
                violations.append({
                    "path": path.relative_to(root).as_posix(),
                    "reason": f"named_teacher_example:{marker}",
                })
    return _check(
        "deidentified_ui_examples",
        not violations,
        static_files_scanned=scanned,
        violations=violations,
    )


def _deployment_seed_check(root: Path) -> dict[str, Any]:
    seed_path = root / "deploy" / "seed" / "blank_school.yaml"
    payload = yaml.safe_load(seed_path.read_text(encoding="utf-8")) if seed_path.exists() else None
    failures: list[str] = []
    if not isinstance(payload, dict):
        failures.append("missing_or_invalid_seed")
        payload = {}
    if payload.get("io") != {} or payload.get("rules") != {}:
        failures.append("base_overrides_not_empty")
    temporary = payload.get("temporary_rules") if isinstance(payload.get("temporary_rules"), dict) else {}
    if temporary.get("active") != []:
        failures.append("temporary_rules_not_empty")
    academic = payload.get("academic_affairs") if isinstance(payload.get("academic_affairs"), dict) else {}
    tables = academic.get("tables") if isinstance(academic.get("tables"), dict) else None
    if tables is None or any(value not in (None, [], {}) for value in tables.values()):
        failures.append("academic_tables_not_empty")
    audit = payload.get("change_audit") if isinstance(payload.get("change_audit"), dict) else {}
    if audit.get("entries") != []:
        failures.append("change_history_not_empty")
    return _check(
        "blank_deployment_seed",
        not failures,
        path="deploy/seed/blank_school.yaml",
        failures=failures,
    )


def _container_boundary_check(root: Path) -> dict[str, Any]:
    dockerfile = (root / "Dockerfile").read_text(encoding="utf-8")
    compose = (root / "deploy" / "compose.yaml").read_text(encoding="utf-8")
    dockerignore = (root / ".dockerignore").read_text(encoding="utf-8")
    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
    required = {
        "explicit_seed_copy": "COPY deploy/seed ./deploy/seed" in dockerfile,
        "no_broad_copy": "COPY . " not in dockerfile,
        "blank_seed_import": "/app/deploy/seed/blank_school.yaml" in compose,
        "no_local_override_import": "/app/scheduler/config/web_overrides.yaml" not in compose,
        "password_secret_mount": "/run/secrets/scheduler_admin_password" in compose,
        "local_overrides_excluded": "scheduler/config/web_overrides.yaml" in dockerignore,
        "deployment_secrets_excluded": "deploy/secrets" in dockerignore,
        "wheel_excludes_local_overrides": '"config/*.yaml"' not in pyproject
        and '"config/io.yaml"' in pyproject
        and '"config/rules.yaml"' in pyproject
        and 'include-package-data = false' in pyproject
        and '"scheduler.config" = ["web_overrides.yaml"]' in pyproject,
    }
    return _check(
        "container_release_boundary",
        all(required.values()),
        assertions=required,
    )


def _secret_example_check(root: Path) -> dict[str, Any]:
    env_text = (root / "deploy" / ".env.example").read_text(encoding="utf-8")
    compose_text = (root / "deploy" / "compose.yaml").read_text(encoding="utf-8")
    required = {
        "password_value_not_in_example": "SCHEDULER_BOOTSTRAP_PASSWORD=" not in env_text,
        "password_value_not_in_compose": "SCHEDULER_BOOTSTRAP_PASSWORD" not in compose_text,
        "password_file_declared": "SCHEDULER_ADMIN_PASSWORD_FILE=" in env_text,
        "model_key_empty": re.search(r"(?m)^DOMESTIC_AI_API_KEY=$", env_text) is not None,
        "login_secret_placeholder": "SCHEDULER_LOGIN_RATE_LIMIT_SECRET=replace-with-a-long-random-secret" in env_text,
    }
    return _check(
        "secret_examples_only",
        all(required.values()),
        assertions=required,
    )


def _check(check_id: str, passed: bool, **evidence: Any) -> dict[str, Any]:
    return {"id": check_id, "status": "passed" if passed else "failed", **evidence}


if __name__ == "__main__":
    main()
