"""Real authenticated Web + SQLite + Worker acceptance, using synthetic schools.

Runs a clean copy of runtime sources, never copying school Excel, overrides,
credentials or output history. No external AI service is configured.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import time
from collections import Counter
from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request
from zipfile import ZipFile

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scheduler.platform.auth import AuthService, PasswordHasher
from scheduler.platform.database import PlatformDatabase, PlatformDatabaseSettings
from scheduler.platform.store import PlatformStore
from verification.fixes.saas_release_candidate_audit import _HttpClient, _free_port, _stop_process, _wait_json


def scenarios():
    specs = [
        ("primary", "小学", "三年级", 2, ["课程1", "课程2", "活动课程1", "活动课程2"], ["语文", "数学", "科学", "艺术"], [5, 5, 5, 4]),
        ("junior", "初中", "七年级", 3, ["课程1", "课程2", "课程3", "拓展1", "拓展2"], ["语文", "数学", "外语", "综合实践"], [6, 6, 6, 6]),
        ("senior", "高中行政班", "高一", 2, ["课程1", "课程2", "课程3", "选修1", "选修2", "自主学习1"], ["语文", "数学", "外语", "物理", "历史"], [6, 6, 6, 6, 5]),
    ]
    days = ["星期一", "星期二", "星期三", "星期四", "星期五"]
    for slug, stage, grade, class_count, labels, subjects, hours in specs:
        # Senior custom period spans Saturday instead of Friday: there is no
        # hard-coded weekday/weekend quota and no assumption of day vs evening.
        active_days = days if slug != "senior" else days[:4] + ["星期六"]
        if slug == "senior":
            labels[-1] = "夜间研学1"
        teachers = [{"班级": f"{grade}{i + 1}班", **{subj: (f"{slug}共享教师" if j == 0 else f"{slug}教师{i + 1}_{j + 1}") for j, subj in enumerate(subjects)}} for i in range(class_count)]
        tables = {
            "time_grid": [{"时段": re.fullmatch(r"(.+?)(\d+)", label)[1], "节次": int(re.fullmatch(r"(.+?)(\d+)", label)[2]), **{day: 1 for day in active_days}} for label in labels],
            "subject_hours": [{"学科": subject, "周期课时": count} for subject, count in zip(subjects, hours)],
            "fixed_slots": [{"作用范围": "ALL", "班级": "", "星期": active_days[-1], "时段": re.fullmatch(r"(.+?)(\d+)", labels[-1])[1], "节次": 1 if slug == "senior" else 2, "学科": "班会"}],
            "subject_bans": [{"学科": subjects[-1], "禁排星期": "星期一", "禁排时段": "课程", "节次": 2}],
            "class_overrides": [],
        }
        if slug == "junior":
            tables["class_overrides"] = [{"班级": teachers[1]["班级"], "学科": subjects[0], "周期课时": 7}, {"班级": teachers[1]["班级"], "学科": subjects[-1], "周期课时": 5}]
        hard = {"title": "共享教师周一课程1不可排", "strength": "hard", "scope": {"teachers": [f"{slug}共享教师"]}, "effective_time": {"mode": "project_term", "week_pattern": "all", "days": ["星期一"], "slots": ["课程1"]}, "constraint": {"type": "teacher_unavailable", "params": {}}, "solver_support": {"status": "supported", "compiler": "day.rule_v2.v1"}}
        cap = {"title": "共享教师每日上限", "strength": "hard", "scope": {"teachers": [f"{slug}共享教师"]}, "constraint": {"type": "max_daily_lessons", "params": {"max": 4}}, "solver_support": {"status": "supported", "compiler": "day.rule_v2.v1"}}
        soft = {"title": "共享教师尽量避免课程2", "strength": "soft", "weight": 70, "scope": {"teachers": [f"{slug}共享教师"]}, "effective_time": {"mode": "project_term", "week_pattern": "all", "slots": ["课程2"]}, "constraint": {"type": "teacher_unavailable", "params": {}}, "solver_support": {"status": "supported", "compiler": "day.rule_v2.v1"}}
        if slug == "primary":
            soft["title"] = "共享教师优先课程1，其他课位有软代价"
            soft["effective_time"]["slots"] = labels[1:]
        yield {"id": slug, "stage": stage, "grade": grade, "teachers": teachers, "tables": tables, "rules": [hard, cap, soft], "days": active_days, "labels": labels}


def verify_workbook(content: bytes, scenario: dict) -> dict:
    """Independent checks against input rows; no solver/adapter imports."""
    frame = pd.read_excel(BytesIO(content), sheet_name="课程课表_宽表", index_col=0).fillna("")
    teachers = {row["班级"]: {k: v for k, v in row.items() if k != "班级"} for row in scenario["teachers"]}
    expected_cols = {f"{day}_{label}" for day in scenario["days"] for label in scenario["labels"]}
    errors = []
    if set(frame.index) != set(teachers) or set(frame.columns) != expected_cols:
        errors.append("class_or_slot_set")
    hours = {row["学科"]: row["周期课时"] for row in scenario["tables"]["subject_hours"]}
    fixed = scenario["tables"]["fixed_slots"][0]
    fixed_col = f"{fixed['星期']}_{fixed['时段']}{fixed['节次']}"
    teacher_slots = Counter()
    teacher_days = Counter()
    soft_units = 0
    assignment_count = 0
    for cls, row in frame.iterrows():
        counts = Counter()
        for column, text in row.items():
            if column == fixed_col:
                if text != "班会": errors.append("fixed_activity")
                continue
            match = re.fullmatch(r"(.+)\((.+)\)", str(text))
            if not match:
                errors.append("empty_or_invalid_assignment")
                continue
            subject, teacher = match.groups()
            if teachers.get(cls, {}).get(subject) != teacher:
                errors.append("teacher_mapping")
            day, label = column.split("_", 1)
            teacher_slots[(teacher, column)] += 1
            teacher_days[(teacher, day)] += 1
            counts[subject] += 1
            assignment_count += 1
            if subject == scenario["tables"]["subject_bans"][0]["学科"] and column == "星期一_课程2":
                errors.append("subject_ban")
            if teacher == f"{scenario['id']}共享教师":
                if column == "星期一_课程1": errors.append("teacher_unavailable")
                if label in scenario["rules"][2]["effective_time"]["slots"]: soft_units += 1
        required = dict(hours)
        for override in scenario["tables"]["class_overrides"]:
            if override["班级"] == cls: required[override["学科"]] = override["周期课时"]
        if dict(counts) != required: errors.append("cycle_hours")
    if any(count > 1 for count in teacher_slots.values()): errors.append("teacher_conflict")
    if any(count > 4 for (teacher, _), count in teacher_days.items() if teacher == f"{scenario['id']}共享教师"):
        errors.append("max_daily_lessons")
    return {"hard_violations": sorted(set(errors)), "assignments": assignment_count, "soft_penalty": soft_units * 70}


def _copy_runtime(target: Path):
    manifest = {}
    for package in ("scheduler", "ai_orchestrated_optimization", "profiles"):
        for src in (ROOT / package).rglob("*"):
            rel = src.relative_to(ROOT)
            if not src.is_file() or "__pycache__" in rel.parts or src.suffix.lower() not in {".py", ".yaml", ".json", ".js", ".css", ".html", ".svg", ".woff2", ".png"}:
                continue
            if src.name == "web_overrides.yaml" or "outputs" in rel.parts:
                continue
            dst = target / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
            manifest[str(rel)] = hashlib.sha256(src.read_bytes()).hexdigest()
    return manifest


def _upload(client, endpoint, rows, columns, table=None):
    buffer = BytesIO()
    pd.DataFrame(rows, columns=columns).to_excel(buffer, index=False)
    boundary = "k12-" + secrets.token_hex(16)
    parts = []
    if table:
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="table"\r\n\r\n{table}\r\n'.encode())
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="synthetic.xlsx"\r\nContent-Type: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet\r\n\r\n'.encode() + buffer.getvalue() + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    request = Request(client.base_url + endpoint, data=b"".join(parts), headers={"Content-Type": f"multipart/form-data; boundary={boundary}", "X-CSRF-Token": client.cookie("scheduler_csrf")}, method="POST")
    with client.opener.open(request, timeout=20) as response:
        return json.loads(response.read())


def run_scenario(runtime: Path, scenario: dict, evidence: Path):
    root = evidence / scenario["id"]
    root.mkdir(parents=True)
    # Separate runtime root also prevents outputs from another school's acceptance
    # being collected by the legacy artifact scanner.
    code = root / "runtime"
    shutil.copytree(runtime, code)
    store = PlatformStore(PlatformDatabase(PlatformDatabaseSettings(path=root / "school.sqlite3")))
    store.initialize()
    org = store.create_organization(slug=scenario["id"], name=scenario["stage"] + "匿名验收")
    store.save_workspace(org.id, {}, expected_revision=None, actor_user_id="acceptance", reason="empty synthetic workspace")
    password = secrets.token_urlsafe(24)
    AuthService(store, password_hasher=PasswordHasher(iterations=100_000)).create_user(org.id, username="admin", display_name="验收管理员", role="academic_admin", password=password)
    env = os.environ.copy()
    for key in ("SCHEDULER_WORKSPACE_REVISION", "SCHEDULER_DATA_DIR"):
        env.pop(key, None)
    env.update({"PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": str(code), "SCHEDULER_STATE_BACKEND": "sqlite", "SCHEDULER_DATABASE_PATH": str(root / "school.sqlite3"), "SCHEDULER_ORGANIZATION_ID": org.id, "SCHEDULER_ORGANIZATION_SLUG": org.slug, "SCHEDULER_AUTH_MODE": "required", "SCHEDULER_COOKIE_SECURE": "false", "SCHEDULER_SOLVE_MODE": "async", "SCHEDULER_LOGIN_RATE_LIMIT_SECRET": secrets.token_urlsafe(32)})
    port = _free_port()
    client = _HttpClient(f"http://127.0.0.1:{port}")
    processes = []
    logs = []
    def start(module, args):
        log = (root / f"{module.rsplit('.', 1)[-1]}.log").open("w", encoding="utf-8")
        logs.append(log)
        process = subprocess.Popen([sys.executable, "-m", module, *args], cwd=code, env=env, stdout=log, stderr=subprocess.STDOUT)
        processes.append(process)
    def api(method, path, body=None):
        return client.json_request(method, path, body, headers={"X-CSRF-Token": client.cookie("scheduler_csrf")})[0]
    try:
        start("scheduler.app.web", ["--host", "127.0.0.1", "--port", str(port)])
        _wait_json(client, "/api/health/live", expected_status=200)
        api("POST", "/api/auth/login", {"organization_slug": org.slug, "username": "admin", "password": password})
        api("POST", "/api/config", {"io": {"web_tables": {"teacher_subjects": [], "day_rules": {k: [] for k in scenario["tables"]}}}, "rules": {"product_rules": {"defaults_only": True}, "ai_rule_assistant": {"enabled": False}}})
        preview = _upload(client, "/api/teacher-subjects/import-file", scenario["teachers"], list(scenario["teachers"][0]))
        assert preview["persisted"] is False
        assert api("GET", "/api/teacher-subjects")["rows"] == []
        api("POST", "/api/teacher-subjects", {"rows": preview["rows"]})
        schemas = {"fixed_slots": ["作用范围", "班级", "星期", "时段", "节次", "学科"], "subject_bans": ["学科", "禁排星期", "禁排时段", "节次"], "class_overrides": ["班级", "学科", "周期课时"]}
        for table, rows in scenario["tables"].items():
            columns = list(rows[0]) if rows else schemas[table]
            preview = _upload(client, "/api/day-rules/import-file", rows, columns, table)
            assert preview["persisted"] is False
            api("POST", "/api/day-rules", {"table": table, "rows": preview["rows"]})
        ruleset = api("GET", "/api/rules/v2")
        parsed = api("POST", "/api/rules/v2/parse", {"text": f"{scenario['id']}共享教师周一课程1不能排课"})["rule"]
        assert parsed["solver_support"]["status"] == "supported", parsed
        assert parsed["effective_time"]["slots"] == ["课程1"]
        scenario["rules"][0] = parsed
        rule_ids = []
        for rule in scenario["rules"]:
            ruleset = api("POST", "/api/rules/v2", {"rule": rule, "expected_revision": ruleset["revision"]})
            rid = ruleset["rules"][-1]["id"]
            assert ruleset["rules"][-1]["confirmation"]["confirmed"] is False
            try:
                api("POST", "/api/rules/v2/activate", {"rule_id": rid, "expected_revision": ruleset["revision"], "confirm": False})
                raise AssertionError("unconfirmed rule activated")
            except RuntimeError as exc:
                assert "HTTP 400" in str(exc)
            ruleset = api("POST", "/api/rules/v2/activate", {"rule_id": rid, "expected_revision": ruleset["revision"], "confirm": True})
            rule_ids.append(rid)
        readiness = api("GET", "/api/readiness?mode=course")
        (root / "readiness.json").write_text(json.dumps(readiness, ensure_ascii=False, indent=2), encoding="utf-8")
        assert readiness["summary"]["can_start_solver"], json.dumps([i for i in readiness["items"] if i.get("blocking")], ensure_ascii=False)
        start("scheduler.platform.worker", ["--poll-seconds", "0.2"])
        job = api("POST", "/api/solve/jobs", {"mode": "course", "time_limit_seconds": 10, "workers": 1, "grade_prefix": scenario["grade"], "max_keep": 1})
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            status = api("GET", f"/api/solve/jobs/{job['id']}")
            if status["status"] in {"completed", "failed", "cancelled"}: break
            time.sleep(0.25)
        assert status["status"] == "completed", status
        assert status["solver_status"] == "OPTIMAL", status
        for endpoint, filename in [("/api/results/export?format=xlsx", "课程课表.xlsx"), ("/api/solve/package", "结果包.zip")]:
            with client.opener.open(client.base_url + endpoint, timeout=30) as response:
                (root / filename).write_bytes(response.read())
        checked = verify_workbook((root / "课程课表.xlsx").read_bytes(), scenario)
        assert not checked["hard_violations"], checked
        with ZipFile(root / "结果包.zip") as package:
            assert package.testzip() is None
            assert any(name.endswith("course_explanation.json") for name in package.namelist())
            explanation = json.loads(package.read(next(name for name in package.namelist() if name.endswith("course_explanation.json"))))
        assert {r["rule_id"] for r in explanation["rules"]} == set(rule_ids)
        assert explanation["objective_value"] == checked["soft_penalty"]
        if scenario["id"] == "primary":
            assert checked["soft_penalty"] == 420
        preview = api("GET", "/api/results/preview")
        assert preview["summary"]["class_views"] == len(scenario["teachers"]), preview["summary"]
        # Demonstrate that the independent verifier can reject a corrupted output.
        corrupt = pd.read_excel(root / "课程课表.xlsx", index_col=0)
        corrupt.iloc[0, 0] = "错误课程(错误教师)"
        buffer = BytesIO()
        with pd.ExcelWriter(buffer) as writer: corrupt.to_excel(writer, sheet_name="课程课表_宽表")
        assert verify_workbook(buffer.getvalue(), scenario)["hard_violations"]
        infeasible_evidence = None
        if scenario["id"] == "primary":
            impossible = {**scenario["rules"][0], "id": "acceptance.block_shared_teacher", "title": "共享教师在全部可排时间不可用", "effective_time": {"mode": "project_term", "week_pattern": "all", "days": scenario["days"], "slots": scenario["labels"]}}
            ruleset = api("POST", "/api/rules/v2", {"rule": impossible, "expected_revision": ruleset["revision"]})
            ruleset = api("POST", "/api/rules/v2/activate", {"rule_id": impossible["id"], "expected_revision": ruleset["revision"], "confirm": True})
            time.sleep(1.1)  # Legacy run IDs have one-second resolution.
            negative = api("POST", "/api/solve/jobs", {"mode": "course", "time_limit_seconds": 10, "workers": 1, "grade_prefix": scenario["grade"]})
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline:
                negative_status = api("GET", f"/api/solve/jobs/{negative['id']}")
                if negative_status["status"] in {"completed", "failed"}: break
                time.sleep(0.25)
            assert negative_status["solver_status"] == "INFEASIBLE", negative_status
            assert not negative_status["release_state"]["can_publish_candidate"]
            assert api("GET", "/api/results/preview")["summary"]["class_views"] == 0
            infeasible_evidence = {"job_id": negative["id"], "solver_status": "INFEASIBLE", "conflicting_rule_id": impossible["id"], "stale_schedule_not_reused": True, "can_publish": False}
        api("POST", "/api/teacher-subjects", {"rows": []})
        assert api("GET", "/api/teacher-subjects")["rows"] == []
        assert not api("GET", "/api/readiness?mode=course")["summary"]["can_start_solver"]
        result = {"id": scenario["id"], "stage": scenario["stage"], "status": "passed", "classes": len(scenario["teachers"]), "slots_per_class": len(scenario["days"]) * len(scenario["labels"]), "solver_status": status["solver_status"], "job_id": job["id"], "workspace_revision": job["workspace_revision"], "verification": checked, "explanation": explanation, "xlsx": str(root / "课程课表.xlsx"), "zip": str(root / "结果包.zip"), "coverage": ["import_preview_confirmation", "cycle_hours", "class_overrides" if scenario["tables"]["class_overrides"] else "cycle_hours", "fixed_activity", "subject_ban", "teacher_conflict", "teacher_unavailable", "max_daily_lessons", "soft_penalty", "rule_confirmation", "custom_blocks", "excel_export", "zip_export", "empty_source_blocks"]}
        if infeasible_evidence:
            result["infeasible_case"] = infeasible_evidence
            result["coverage"].append("infeasible_without_relaxation_or_stale_export")
        print(f"{scenario['stage']}: {status['solver_status']}, {checked['assignments']} assignments, 0 hard violations", flush=True)
        return result
    finally:
        for process in reversed(processes): _stop_process(process)
        for log in logs: log.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=False)
    runtime = output / "source"
    manifest = _copy_runtime(runtime)
    result = {"schema_version": "scheduler.k12_api_acceptance.v1", "status": "running", "source_hashes": manifest, "scenarios": []}
    try:
        for scenario in scenarios():
            (output / f"{scenario['id']}_input.json").write_text(json.dumps(scenario, ensure_ascii=False, indent=2), encoding="utf-8")
            result["scenarios"].append(run_scenario(runtime, scenario, output))
        result["coverage_matrix"] = {rule: [s["id"] for s in result["scenarios"] if rule in s["coverage"]] for rule in sorted({r for s in result["scenarios"] for r in s["coverage"]})}
        result["status"] = "passed"
    except Exception as exc:
        result["status"] = "failed"
        result["error"] = str(exc)
        raise
    finally:
        (output / "report.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
