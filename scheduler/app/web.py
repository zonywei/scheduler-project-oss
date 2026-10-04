# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import ipaddress
import json
import logging
import mimetypes
import os
import re
import signal
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.parse import parse_qs, quote, urlparse

from scheduler.app.access_control import (
    PermissionDenied,
    assert_request_allowed,
    build_access_context,
)
from scheduler.app.auth_http import (
    auth_required,
    authenticate_headers,
    login_from_payload,
    logout_from_headers,
    session_payload,
)
from scheduler.app.config_service import (
    DAY_RULE_TABLE_LABELS,
    PROJECT_ROOT,
    build_day_rule_table_template_csv,
    build_day_rule_table_template_xlsx,
    build_teacher_subject_template,
    build_teacher_subject_template_csv,
    parse_teacher_subject_csv,
    parse_teacher_subject_xlsx,
    parse_day_rule_table_csv,
    parse_day_rule_table_xlsx,
    load_day_rule_tables,
    load_academic_affairs_payload,
    load_effective_payload,
    load_profile_catalog_payload,
    load_school_problem_preview_payload,
    list_config_change_audit,
    preview_academic_affairs_payload,
    list_teacher_subject_rows,
    load_web_overrides,
    rollback_config_change,
    save_web_overrides,
    save_ai_rule_assistant,
    save_academic_affairs_payload,
    save_day_rule_table,
    save_rule_field_updates,
    save_teacher_subject_rows,
)
from scheduler.app.academic_affairs_io import (
    build_academic_table_template_csv,
    build_academic_table_template_xlsx,
    build_academic_workbook_template_xlsx,
    parse_academic_table_csv,
    parse_academic_table_xlsx,
    parse_academic_workbook_xlsx,
)
from scheduler.app.conflict_detection import detect_rule_conflicts
from scheduler.app.diagnostic_relaxation import apply_relaxation_plan, remove_relaxation_plan
from scheduler.app.nl_rules import parse_natural_language_rule, parse_rule_with_ai_settings
from scheduler.app.multipart import MultipartForm, parse_multipart_form
from scheduler.app.conversational_scheduler import (
    PremiumFeatureRequired,
    add_conversation_message,
    attach_conversation_solve_job,
    confirm_conversation_model,
    conversation_feature_access,
    conversation_route,
    create_conversation_session,
    get_conversation_session,
    list_conversation_sessions,
    prepare_conversation_solve,
    upload_conversation_file,
)
from scheduler.data.teacher_table_schema import teacher_subject_columns
from scheduler.app.model_api import model_usage_summary, test_model_connection, update_model_quota
from scheduler.app.model_gateway import ModelGatewayError
from scheduler.app.model_router import build_metered_model_client
from scheduler.app.formal_product import (
    activate_saved_rule_v2,
    attach_formal_solve_phase,
    build_project_state,
    delete_rule_v2,
    flatten_catalog_rules,
    load_project_settings,
    load_publish_state,
    load_rule_v2_payload,
    parse_rule_v2_with_ai,
    publish_current_candidate,
    review_readiness_blockers_with_ai,
    save_rule_v2,
    save_project_settings,
    set_rule_v2_enabled,
)
from scheduler.app.job_api import (
    async_solve_enabled,
    cancel_latest_solve_job,
    cancel_solve_job,
    current_solve_status,
    enqueue_solve_job,
    get_solve_job,
    list_solve_jobs,
    solve_job_id_from_path,
)
from scheduler.domain.rule_drafts import (
    NATURAL_LANGUAGE_RULE_KIND,
    RULE_DRAFT_SCHEMA_VERSION,
    activate_rule_draft,
    validate_rule_draft,
)
from scheduler.platform.auth import AuthenticationError, AuthenticatedUser, CsrfValidationError
from scheduler.platform.jobs import (
    ACTIVE_JOB_STATUSES,
    COMPLETED,
    JobIdempotencyConflict,
    JobNotFound,
    JobQueueFull,
    SolveJobStore,
)
from scheduler.platform.runtime import runtime_organization_id, runtime_store, uses_sqlite_workspace
from scheduler.platform.health import platform_health
from scheduler.platform.store import RevisionConflict
from scheduler.platform.model_usage import ModelQuotaExceeded
from scheduler.app.readiness import build_solve_readiness, build_solve_readiness_preview
from scheduler.app.result_preview import build_result_preview
from scheduler.app.result_exports import build_result_pdf, build_result_xlsx, resolve_result_excel, result_export_name
from scheduler.app.solve_service import (
    build_package_for_download,
    build_package_for_latest_run,
    file_download_name,
    force_stop_solve,
    get_solve_status,
    package_download_name,
    pause_solve,
    apply_leave_substitution_repair,
    apply_manual_timetable_adjustment,
    preview_leave_substitution_repair,
    preview_manual_timetable_adjustment,
    runtime_web_run_root,
    start_solve,
)


STATIC_DIR = Path(__file__).resolve().parent / "static"
logger = logging.getLogger(__name__)
RESULT_PREVIEW_PATHS = {
    "/api/results/preview",
    "/api/result-preview",
    "/api/solve/result-preview",
    "/api/solve/preview",
}
JSON_BODY_DEFAULT_LIMIT = 1024 * 1024


class RequestTooLarge(ValueError):
    pass


def _json_bytes(payload: Any, status: int = 200) -> tuple[int, bytes, str]:
    return status, json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"), "application/json; charset=utf-8"


def _read_body(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    try:
        length = int(handler.headers.get("Content-Length") or 0)
    except ValueError as exc:
        raise ValueError("invalid Content-Length") from exc
    if length <= 0:
        return {}
    maximum = _bounded_env_int(
        "SCHEDULER_MAX_JSON_BYTES",
        JSON_BODY_DEFAULT_LIMIT,
        16 * 1024,
        10 * 1024 * 1024,
    )
    if length > maximum:
        raise RequestTooLarge(f"JSON request exceeds the {maximum} byte limit")
    raw = handler.rfile.read(length).decode("utf-8")
    data = json.loads(raw or "{}")
    if not isinstance(data, dict):
        raise ValueError("request body must be a JSON object")
    return data


def _bounded_env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = str(os.environ.get(name) or default).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


def _env_bool(name: str, default: bool) -> bool:
    raw = str(os.environ.get(name) or ("true" if default else "false")).strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be true or false")


def _security_headers() -> list[tuple[str, str]]:
    headers = [
        ("X-Content-Type-Options", "nosniff"),
        ("X-Frame-Options", "DENY"),
        ("Referrer-Policy", "no-referrer"),
        ("Permissions-Policy", "tools=(self), camera=(), microphone=(), geolocation=(), payment=()"),
        ("Origin-Agent-Cluster", "?1"),
        ("Cross-Origin-Opener-Policy", "same-origin"),
        (
            "Content-Security-Policy",
            "default-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'; "
            "object-src 'none'; img-src 'self' data:; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'",
        ),
    ]
    if _env_bool("SCHEDULER_ENABLE_HSTS", False):
        headers.append(("Strict-Transport-Security", "max-age=31536000; includeSubDomains"))
    return headers


class SchedulerWebHandler(BaseHTTPRequestHandler):
    server_version = "SchedulerWeb/0.2"

    def version_string(self) -> str:
        return self.server_version

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        try:
            if parsed.path == "/api/health/live":
                self._send(*_json_bytes({"schema_version": "scheduler.liveness.v1", "status": "up"}))
                return
            if parsed.path == "/api/health/ready":
                try:
                    payload = platform_health(runtime_store(), runtime_organization_id())
                except Exception:
                    logger.warning("Scheduler readiness check failed", exc_info=True)
                    payload = {
                        "schema_version": "scheduler.platform_health.v1",
                        "status": "not_ready",
                        "ready": False,
                        "checks": {"database": "unavailable"},
                    }
                self._send(*_json_bytes(payload, status=200 if payload.get("ready") else 503))
                return
            if parsed.path == "/api/auth/session":
                identity: AuthenticatedUser | None = None
                if auth_required():
                    try:
                        identity = authenticate_headers(self.headers)
                    except AuthenticationError:
                        identity = None
                self._send(*_json_bytes(session_payload(identity)), headers={"Cache-Control": "no-store"})
                return
            if parsed.path.startswith("/api/"):
                self._assert_access("GET", parsed.path)
            if parsed.path == "/api/access/context":
                self._send(*_json_bytes(self._build_access_context()))
            elif parsed.path == "/api/config":
                self._send(*_json_bytes(load_effective_payload("joint")))
            elif parsed.path == "/api/profiles/catalog":
                mode = str((query.get("mode") or ["joint"])[0])
                self._send(*_json_bytes(load_profile_catalog_payload(mode)))
            elif parsed.path == "/api/school-problem/preview":
                mode = str((query.get("mode") or ["joint"])[0])
                self._send(*_json_bytes(load_school_problem_preview_payload(mode)))
            elif parsed.path == "/api/teacher-subjects":
                self._send(*_json_bytes({"rows": list_teacher_subject_rows()}))
            elif parsed.path == "/api/teacher-subjects/template":
                if str((query.get("format") or ["xlsx"])[0]).lower() == "csv":
                    self._send_file_bytes(
                        build_teacher_subject_template_csv(),
                        "text/csv; charset=utf-8",
                        "教师定位表_导入模板.csv",
                    )
                else:
                    self._send_file_bytes(
                        build_teacher_subject_template(),
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        "教师定位表_导入模板.xlsx",
                    )
            elif parsed.path == "/api/day-rules":
                self._send(*_json_bytes(load_day_rule_tables()))
            elif parsed.path == "/api/day-rules/template":
                table_key = str((query.get("table") or [""])[0])
                label = DAY_RULE_TABLE_LABELS.get(table_key, table_key)
                if str((query.get("format") or ["xlsx"])[0]).lower() == "csv":
                    self._send_file_bytes(
                        build_day_rule_table_template_csv(table_key),
                        "text/csv; charset=utf-8",
                        f"{label}_导入模板.csv",
                    )
                else:
                    self._send_file_bytes(
                        build_day_rule_table_template_xlsx(table_key),
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        f"{label}_导入模板.xlsx",
                    )
            elif parsed.path == "/api/conflicts":
                payload = load_effective_payload("joint")
                self._send(*_json_bytes(detect_rule_conflicts(payload.get("effective", {}), list_teacher_subject_rows())))
            elif parsed.path == "/api/rules/v2":
                self._send(*_json_bytes(load_rule_v2_payload()))
            elif parsed.path == "/api/project/state":
                status = self._solve_status()
                day_payload = load_day_rule_tables()
                day_tables = day_payload.get("tables") if isinstance(day_payload.get("tables"), dict) else day_payload
                self._send(*_json_bytes(build_project_state(
                    teacher_rows=list_teacher_subject_rows(),
                    day_rules=day_tables,
                    readiness=build_solve_readiness("joint"),
                    solve_status=status,
                    result_preview=build_result_preview(status),
                )))
            elif parsed.path == "/api/project/settings":
                self._send(*_json_bytes(load_project_settings()))
            elif parsed.path == "/api/project/publish":
                self._send(*_json_bytes(load_publish_state()))
            elif parsed.path == "/api/conversation-scheduler/access":
                self._send(*_json_bytes(conversation_feature_access()))
            elif parsed.path == "/api/conversation-scheduler/sessions":
                limit = int((query.get("limit") or ["30"])[0] or 30)
                self._send(*_json_bytes(list_conversation_sessions(
                    actor_user_id=self._actor(),
                    limit=limit,
                )))
            elif conversation_route(parsed.path):
                session_id, action = conversation_route(parsed.path) or ("", "")
                if action != "detail":
                    self._send(*_json_bytes({"error": "not found"}, status=404))
                else:
                    self._send(*_json_bytes(get_conversation_session(
                        session_id,
                        actor_user_id=self._actor(),
                    )))
            elif parsed.path == "/api/readiness":
                mode = (query.get("mode") or ["joint"])[0]
                self._send(*_json_bytes(build_solve_readiness(str(mode))))
            elif parsed.path == "/api/academic-affairs":
                self._send(*_json_bytes(load_academic_affairs_payload()))
            elif parsed.path == "/api/academic-affairs/template":
                table_key = str((query.get("table") or [""])[0])
                label = str(load_academic_affairs_payload().get("summary", {}).get("schema", {}).get(table_key, {}).get("label") or table_key)
                if str((query.get("format") or ["xlsx"])[0]).lower() == "csv":
                    self._send_file_bytes(
                        build_academic_table_template_csv(table_key),
                        "text/csv; charset=utf-8",
                        f"{label}_导入模板.csv",
                    )
                else:
                    self._send_file_bytes(
                        build_academic_table_template_xlsx(table_key),
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        f"{label}_导入模板.xlsx",
                    )
            elif parsed.path == "/api/academic-affairs/workbook-template":
                self._send_file_bytes(
                    build_academic_workbook_template_xlsx(),
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    "教务全量工作簿_导入模板.xlsx",
                )
            elif parsed.path == "/api/config/audit":
                limit = int((query.get("limit") or ["30"])[0] or 30)
                self._send(*_json_bytes(list_config_change_audit(limit)))
            elif parsed.path in {"/api/model/usage", "/api/model/quota"}:
                scope_user_id = str((query.get("scope_user_id") or [""])[0])
                self._send(*_json_bytes(model_usage_summary(scope_user_id=scope_user_id)))
            elif parsed.path == "/api/solve/jobs":
                limit = int((query.get("limit") or ["50"])[0] or 50)
                self._send(*_json_bytes(list_solve_jobs(limit=limit)))
            elif parsed.path.startswith("/api/solve/jobs/"):
                job_id = solve_job_id_from_path(parsed.path)
                if job_id is None:
                    self._send(*_json_bytes({"error": "not found"}, status=404))
                else:
                    self._send(*_json_bytes(get_solve_job(job_id)))
            elif parsed.path == "/api/solve/status":
                self._send(*_json_bytes(self._solve_status()))
            elif parsed.path == "/api/solve/diagnostics":
                self._send(*_json_bytes(self._solve_status().get("solve_diagnostics", {})))
            elif parsed.path in RESULT_PREVIEW_PATHS:
                self._send(*_json_bytes(build_result_preview(self._solve_status())))
            elif parsed.path == "/api/results/export":
                export_format = str((query.get("format") or ["xlsx"])[0]).strip().lower()
                export_view = str((query.get("view") or ["all"])[0]).strip().lower()
                status = self._solve_status()
                if export_format == "pdf":
                    self._send_file_bytes(
                        build_result_pdf(status, view=export_view),
                        "application/pdf",
                        result_export_name("pdf", export_view),
                    )
                elif export_format in {"xlsx", "excel"}:
                    if export_view in {"class", "teacher"}:
                        self._send_file_bytes(
                            build_result_xlsx(status, view=export_view),
                            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            result_export_name("xlsx", export_view),
                        )
                    else:
                        target = resolve_result_excel(status)
                        self._serve_download_path(target, download_name=result_export_name("xlsx", "academic"))
                else:
                    raise ValueError("仅支持 PDF 或 Excel 下载")
            elif parsed.path == "/api/solve/package":
                package, package_status = build_package_for_download()
                self._serve_download_path(package, download_name=package_download_name(package_status))
            elif parsed.path == "/api/file":
                raw_path = (query.get("path") or [""])[0]
                if not raw_path:
                    raise ValueError("missing file path")
                target = Path(raw_path)
                self._serve_download_path(target, download_name=file_download_name(target, self._solve_status()))
            elif parsed.path in {"/", "/index.html"}:
                self._serve_static("index.html")
            else:
                self._serve_static(parsed.path.lstrip("/"))
        except AuthenticationError as exc:
            self._send(*_json_bytes({"error": str(exc), "authentication_required": True}, status=401))
        except CsrfValidationError as exc:
            self._send(*_json_bytes({"error": str(exc), "csrf_failed": True}, status=403))
        except PermissionDenied as exc:
            self._send(*_json_bytes({"error": str(exc), "permission_denied": True}, status=403))
        except PremiumFeatureRequired as exc:
            self._send(*_json_bytes({"error": str(exc), "upgrade_required": True}, status=402))
        except JobNotFound as exc:
            self._send(*_json_bytes({"error": str(exc)}, status=404))
        except RequestTooLarge as exc:
            self._send(*_json_bytes({"error": str(exc)}, status=413))
        except ValueError as exc:
            self._send(*_json_bytes({"error": str(exc)}, status=400))
        except Exception as exc:
            error_id = uuid.uuid4().hex[:12]
            logger.exception("Unhandled GET request failure: %s error_id=%s", parsed.path, error_id)
            self._send(*_json_bytes({"error": "服务器内部错误", "error_id": error_id}, status=500))

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/api/auth/login":
                issued, response_headers = login_from_payload(
                    _read_body(self),
                    client_ip=self._client_ip(),
                )
                payload = session_payload(issued.user)
                payload["expires_at"] = issued.expires_at
                self._send(*_json_bytes(payload), headers=response_headers)
                return
            if parsed.path == "/api/auth/logout":
                response_headers = logout_from_headers(self.headers)
                self._send(*_json_bytes(session_payload(None)), headers=response_headers)
                return
            self._assert_access("POST", parsed.path)
            if parsed.path in {"/api/teacher-subjects/import", "/api/teacher-subjects/import-file"}:
                self._send(*_json_bytes(self._read_teacher_subject_upload()))
                return
            if parsed.path == "/api/day-rules/import-file":
                self._send(*_json_bytes(self._read_day_rule_upload()))
                return
            if parsed.path == "/api/academic-affairs/import-file":
                self._send(*_json_bytes(self._read_academic_affairs_upload()))
                return
            if parsed.path == "/api/academic-affairs/import-workbook":
                self._send(*_json_bytes(self._read_academic_affairs_workbook_upload()))
                return
            conversation_target = conversation_route(parsed.path)
            if conversation_target and conversation_target[1] == "files":
                session_id, _action = conversation_target
                form = self._read_multipart_form("请使用 multipart/form-data 上传排课数据文件")
                field = form.get_file("file")
                if field is None:
                    raise ValueError("缺少 file 字段")
                self._send(*_json_bytes(upload_conversation_file(
                    session_id,
                    field,
                    purpose=form.getfirst("purpose", "base_data"),
                    actor_user_id=self._actor(),
                )))
                return
            body = _read_body(self)
            if parsed.path == "/api/config":
                self._send(*_json_bytes({"overrides": save_web_overrides(
                    body,
                    actor_user_id=self._actor(body),
                    reason=str(body.get("reason") or "direct config save"),
                )}))
            elif parsed.path == "/api/teacher-subjects":
                rows = body.get("rows")
                if not isinstance(rows, list):
                    raise ValueError("rows must be a list")
                self._send(*_json_bytes({"overrides": save_teacher_subject_rows(
                    rows,
                    source=str(body.get("source") or "base_data.teacher_subjects.save"),
                    reason=str(body.get("reason") or ""),
                    actor=self._actor(body),
                )}))
            elif parsed.path == "/api/day-rules":
                rows = body.get("rows")
                table_key = str(body.get("table") or "")
                if not isinstance(rows, list):
                    raise ValueError("rows must be a list")
                self._send(*_json_bytes({"overrides": save_day_rule_table(
                    table_key,
                    rows,
                    source=str(body.get("source") or "base_data.day_rules.save"),
                    reason=str(body.get("reason") or ""),
                    actor=self._actor(body),
                )}))
            elif parsed.path == "/api/ai-settings":
                settings = dict(body)
                settings["actor"] = self._actor(body)
                self._send(*_json_bytes({"overrides": save_ai_rule_assistant(settings)}))
            elif parsed.path == "/api/ai-settings/test":
                ai_settings = ((load_web_overrides().get("rules") or {}).get("ai_rule_assistant") or {})
                identity = self._request_identity() if auth_required() else None
                try:
                    result = test_model_connection(
                        ai_settings if isinstance(ai_settings, dict) else {},
                        organization_id=(
                            identity.organization_id if identity is not None else runtime_organization_id()
                        ),
                        user_id=identity.user_id if identity is not None else "",
                    )
                except ModelQuotaExceeded as exc:
                    self._send(*_json_bytes({
                        "status": "blocked",
                        "status_label": "额度不足",
                        "error": str(exc),
                        "error_code": exc.code,
                    }, status=429))
                except ModelGatewayError as exc:
                    self._send(*_json_bytes({
                        "status": "unavailable",
                        "status_label": "连接失败",
                        "error": str(exc),
                        "error_code": exc.code,
                        "provider_status": exc.status_code,
                    }, status=503))
                else:
                    self._send(*_json_bytes(result))
            elif parsed.path == "/api/model/quota":
                self._send(*_json_bytes(update_model_quota(body, actor_user_id=self._actor(body))))
            elif parsed.path == "/api/conversation-scheduler/sessions":
                preview = build_result_preview(self._solve_status())
                has_current_result = bool(
                    preview.get("has_schedule")
                    or preview.get("class_views")
                    or preview.get("teacher_views")
                    or (preview.get("summary") or {}).get("schedule_files")
                )
                self._send(*_json_bytes(create_conversation_session(
                    body,
                    actor_user_id=self._actor(body),
                    has_current_result=has_current_result,
                ), status=201))
            elif conversation_route(parsed.path):
                session_id, action = conversation_route(parsed.path) or ("", "")
                if action == "messages":
                    response = add_conversation_message(
                        session_id,
                        body,
                        actor_user_id=self._actor(body),
                    )
                    self._send(*_json_bytes(response))
                elif action == "confirm-model":
                    response = confirm_conversation_model(
                        session_id,
                        body,
                        actor_user_id=self._actor(body),
                    )
                    self._send(*_json_bytes(response))
                elif action == "solve":
                    prepared = prepare_conversation_solve(
                        session_id,
                        body,
                        actor_user_id=self._actor(body),
                    )
                    if not async_solve_enabled():
                        raise RuntimeError("AI 对话排课需要启用持久化异步求解")
                    expected_workspace_revision = prepared.get("expected_workspace_revision")
                    if expected_workspace_revision is None:
                        raise RuntimeError("当前会话缺少确认时 workspace 版本，必须重新确认建模方案")
                    solve_request = dict(prepared)
                    solve_request.pop("expected_workspace_revision", None)
                    attempt = solve_request.pop("attempt", None)
                    attempt = body.get("conversation_attempt", body.get("attempt", attempt))
                    job = enqueue_solve_job(
                        solve_request,
                        actor_user_id=self._actor(body),
                        idempotency_key=_conversation_idempotency_key(
                            session_id,
                            expected_workspace_revision,
                            attempt=attempt,
                        ),
                        expected_workspace_revision=expected_workspace_revision,
                    )
                    response = attach_conversation_solve_job(
                        session_id,
                        str(job.get("id") or job.get("job_id") or ""),
                        actor_user_id=self._actor(body),
                    )
                    self._send(*_json_bytes({"session": response, "job": job}, status=202))
                else:
                    self._send(*_json_bytes({"error": "not found"}, status=404))
            elif parsed.path == "/api/rules/configure":
                fields = body.get("fields")
                if not isinstance(fields, list):
                    raise ValueError("fields must be a list")
                self._send(*_json_bytes({"overrides": save_rule_field_updates(
                    fields,
                    source=str(body.get("source") or "rules.configure"),
                    reason=str(body.get("reason") or ""),
                    actor=self._actor(body),
                )}))
            elif parsed.path == "/api/rules/v2/parse":
                teacher_rows = list_teacher_subject_rows()
                known = [str(value).strip() for value in body.get("known_teachers", []) if str(value).strip()]
                if not known:
                    known = sorted({
                        str(value).strip()
                        for row in teacher_rows
                        if isinstance(row, dict)
                        for key in teacher_subject_columns(row.keys())
                        for value in [row.get(key)]
                        if str(value or "").strip()
                    })
                known_subjects = sorted({
                    key
                    for row in teacher_rows
                    if isinstance(row, dict)
                    for key in teacher_subject_columns(row.keys())
                })
                known_classes = sorted({
                    str(row.get("班级") or "").strip()
                    for row in teacher_rows
                    if isinstance(row, dict) and str(row.get("班级") or "").strip()
                })
                ai_settings = ((load_web_overrides().get("rules") or {}).get("ai_rule_assistant") or {})
                model_client = None
                if isinstance(ai_settings, dict) and ai_settings.get("enabled"):
                    try:
                        identity = self._request_identity() if auth_required() else None
                        model_client = build_metered_model_client(
                            ai_settings,
                            organization_id=identity.organization_id if identity is not None else runtime_organization_id(),
                            user_id=identity.user_id if identity is not None else "",
                            operation="rule.v2.parse",
                        )
                    except (ValueError, RuntimeError):
                        model_client = None
                config_payload = load_effective_payload("joint")
                catalog = flatten_catalog_rules(config_payload.get("business_rule_groups") or [])
                day_rules = load_day_rule_tables()
                rule = parse_rule_v2_with_ai(
                    str(body.get("text") or ""),
                    known_teachers=known,
                    known_subjects=known_subjects,
                    known_classes=known_classes,
                    client=model_client,
                    catalog=catalog,
                    slot_context=_slot_context_from_time_grid(day_rules.get("time_grid", [])),
                )
                self._send(*_json_bytes({"rule": rule}))
            elif parsed.path == "/api/rules/v2":
                action = str(body.get("action") or "save")
                expected_revision = body.get("expected_revision")
                if action == "save":
                    rule = body.get("rule")
                    if not isinstance(rule, dict):
                        raise ValueError("rule must be an object")
                    payload = save_rule_v2(
                        rule,
                        expected_revision=int(expected_revision) if expected_revision is not None else None,
                        actor=self._actor(body),
                        reason=str(body.get("reason") or "rule.v2.save"),
                    )
                elif action == "toggle":
                    payload = set_rule_v2_enabled(
                        str(body.get("rule_id") or ""),
                        enabled=body.get("enabled") is True,
                        expected_revision=int(expected_revision) if expected_revision is not None else None,
                        actor=self._actor(body),
                    )
                elif action == "delete":
                    payload = delete_rule_v2(
                        str(body.get("rule_id") or ""),
                        expected_revision=int(expected_revision) if expected_revision is not None else None,
                        actor=self._actor(body),
                    )
                else:
                    raise ValueError(f"unsupported Rule V2 action: {action}")
                self._send(*_json_bytes(payload))
            elif parsed.path == "/api/rules/v2/activate":
                expected_revision = body.get("expected_revision")
                self._send(*_json_bytes(activate_saved_rule_v2(
                    str(body.get("rule_id") or ""),
                    expected_revision=int(expected_revision) if expected_revision is not None else None,
                    confirmed=body.get("confirm") is True,
                    actor=self._actor(body),
                )))
            elif parsed.path == "/api/project/publish":
                status = self._solve_status()
                self._send(*_json_bytes(publish_current_candidate(
                    status,
                    actor=self._actor(body),
                    note=str(body.get("note") or ""),
                    version_label=str(body.get("version") or ""),
                    result_preview=build_result_preview(status),
                )))
            elif parsed.path == "/api/project/settings":
                self._send(*_json_bytes(save_project_settings(body, actor=self._actor(body))))
            elif parsed.path == "/api/readiness/ai-review":
                mode = str(body.get("mode") or "joint")
                readiness = build_solve_readiness(mode)
                teacher_rows = list_teacher_subject_rows()
                known = sorted({
                    str(value).strip()
                    for row in teacher_rows
                    if isinstance(row, dict)
                    for key in teacher_subject_columns(row.keys())
                    for value in [row.get(key)]
                    if str(value or "").strip()
                })
                ai_settings = ((load_web_overrides().get("rules") or {}).get("ai_rule_assistant") or {})
                model_client = None
                if isinstance(ai_settings, dict) and ai_settings.get("enabled"):
                    try:
                        identity = self._request_identity() if auth_required() else None
                        model_client = build_metered_model_client(
                            ai_settings,
                            organization_id=identity.organization_id if identity is not None else runtime_organization_id(),
                            user_id=identity.user_id if identity is not None else "",
                            operation="readiness.ai_review",
                        )
                    except (ValueError, RuntimeError):
                        model_client = None
                self._send(*_json_bytes(review_readiness_blockers_with_ai(
                    readiness,
                    known_teachers=known,
                    client=model_client,
                )))
            elif parsed.path == "/api/readiness/preview-remediation":
                fields = body.get("fields")
                if not isinstance(fields, list):
                    raise ValueError("fields must be a list")
                mode = str(body.get("mode") or "joint")
                self._send(*_json_bytes(build_solve_readiness_preview(mode, fields)))
            elif parsed.path == "/api/config/audit/rollback":
                self._send(*_json_bytes({"overrides": rollback_config_change(
                    str(body.get("entry_id") or ""),
                    source="config.rollback",
                    reason=str(body.get("reason") or ""),
                    actor=self._actor(body),
                )}))
            elif parsed.path == "/api/academic-affairs":
                self._send(*_json_bytes({"overrides": save_academic_affairs_payload(
                    body,
                    source=str(body.get("source") or "academic_affairs.save"),
                    reason=str(body.get("reason") or ""),
                    actor=self._actor(body),
                )}))
            elif parsed.path == "/api/academic-affairs/preview":
                self._send(*_json_bytes(preview_academic_affairs_payload(body)))
            elif parsed.path == "/api/academic-affairs/leave-repair/preview":
                self._send(*_json_bytes(preview_leave_substitution_repair(body)))
            elif parsed.path == "/api/academic-affairs/leave-repair/apply":
                self._send(*_json_bytes(apply_leave_substitution_repair(body)))
            elif parsed.path == "/api/academic-affairs/timetable-adjustment/preview":
                self._send(*_json_bytes(preview_manual_timetable_adjustment(body)))
            elif parsed.path == "/api/academic-affairs/timetable-adjustment/apply":
                self._send(*_json_bytes(apply_manual_timetable_adjustment(body)))
            elif parsed.path == "/api/academic-affairs/import-csv":
                self._send(*_json_bytes(parse_academic_table_csv(
                    str(body.get("table") or ""),
                    str(body.get("csv_text") or ""),
                )))
            elif parsed.path in {"/api/solve/start", "/api/solve/jobs"}:
                if async_solve_enabled():
                    solve_request = dict(body)
                    expected_workspace_revision = solve_request.pop("expected_workspace_revision", None)
                    self._send(*_json_bytes(enqueue_solve_job(
                        solve_request,
                        actor_user_id=self._actor(body),
                        idempotency_key=str(self.headers.get("Idempotency-Key") or ""),
                        expected_workspace_revision=expected_workspace_revision,
                    ), status=202))
                elif parsed.path == "/api/solve/start":
                    self._send(*_json_bytes(start_solve(body)))
                else:
                    raise RuntimeError("持久化 Job API 需要启用 async solve mode")
            elif parsed.path.startswith("/api/solve/jobs/") and parsed.path.endswith("/cancel"):
                job_id = solve_job_id_from_path(parsed.path, suffix="cancel")
                if job_id is None:
                    self._send(*_json_bytes({"error": "not found"}, status=404))
                else:
                    self._send(*_json_bytes(cancel_solve_job(job_id, actor_user_id=self._actor(body))))
            elif parsed.path == "/api/solve/pause":
                self._send(*_json_bytes(
                    cancel_latest_solve_job(actor_user_id=self._actor(body))
                    if async_solve_enabled()
                    else pause_solve()
                ))
            elif parsed.path == "/api/solve/stop":
                self._send(*_json_bytes(
                    cancel_latest_solve_job(actor_user_id=self._actor(body))
                    if async_solve_enabled()
                    else force_stop_solve()
                ))
            elif parsed.path == "/api/solve/relaxation/apply":
                self._send(*_json_bytes(self._apply_diagnostic_relaxation(body)))
            elif parsed.path == "/api/solve/relaxation/remove":
                plan_id = str(body.get("plan_id") or "").strip()
                self._send(*_json_bytes(remove_relaxation_plan(plan_id)))
            elif parsed.path == "/api/nl-rules/parse":
                known = [str(x).strip() for x in body.get("known_teachers", []) if str(x).strip()]
                text = str(body.get("text", ""))
                ai_settings = ((load_web_overrides().get("rules") or {}).get("ai_rule_assistant") or {})
                configured_ai = bool(ai_settings.get("enabled")) if isinstance(ai_settings, dict) else False
                use_ai = configured_ai if "use_ai" not in body else bool(body.get("use_ai"))
                if use_ai:
                    model_client = None
                    if uses_sqlite_workspace() and isinstance(ai_settings, dict):
                        identity = self._request_identity() if auth_required() else None
                        try:
                            model_client = build_metered_model_client(
                                ai_settings,
                                organization_id=identity.organization_id if identity is not None else runtime_organization_id(),
                                user_id=identity.user_id if identity is not None else "",
                                operation="rule.parse",
                            )
                        except (ValueError, RuntimeError):
                            model_client = None
                    rule = parse_rule_with_ai_settings(
                        text,
                        known_teachers=known,
                        settings=ai_settings if isinstance(ai_settings, dict) else {},
                        client=model_client,
                    )
                else:
                    rule = parse_natural_language_rule(text, known_teachers=known)
                self._send(*_json_bytes({"rule": rule}))
            elif parsed.path == "/api/nl-rules/add":
                self._send(*_json_bytes({"overrides": self._apply_temp_rule(body, reverse=False)}))
            elif parsed.path == "/api/nl-rules/remove":
                self._send(*_json_bytes({"overrides": self._apply_temp_rule(body, reverse=True)}))
            else:
                self._send(*_json_bytes({"error": "not found"}, status=404))
        except AuthenticationError as exc:
            self._send(*_json_bytes({"error": str(exc), "authentication_required": True}, status=401))
        except CsrfValidationError as exc:
            self._send(*_json_bytes({"error": str(exc), "csrf_failed": True}, status=403))
        except PermissionDenied as exc:
            self._send(*_json_bytes({"error": str(exc), "permission_denied": True}, status=403))
        except PremiumFeatureRequired as exc:
            self._send(*_json_bytes({"error": str(exc), "upgrade_required": True}, status=402))
        except JobIdempotencyConflict as exc:
            self._send(*_json_bytes({"error": str(exc), "idempotency_conflict": True}, status=409))
        except RevisionConflict as exc:
            self._send(*_json_bytes({"error": str(exc), "revision_conflict": True}, status=409))
        except JobNotFound as exc:
            self._send(*_json_bytes({"error": str(exc)}, status=404))
        except JobQueueFull as exc:
            self._send(*_json_bytes({"error": str(exc)}, status=429))
        except RequestTooLarge as exc:
            self._send(*_json_bytes({"error": str(exc)}, status=413))
        except RuntimeError as exc:
            self._send(*_json_bytes({"error": str(exc)}, status=409))
        except ValueError as exc:
            self._send(*_json_bytes({"error": str(exc)}, status=400))
        except Exception as exc:
            error_id = uuid.uuid4().hex[:12]
            logger.exception("Unhandled POST request failure: %s error_id=%s", parsed.path, error_id)
            self._send(*_json_bytes({"error": "服务器内部错误", "error_id": error_id}, status=500))

    def log_message(self, fmt: str, *args: Any) -> None:
        return

    def _request_role(self) -> str:
        if auth_required():
            return self._request_identity().role
        return str(self.headers.get("X-Scheduler-Role") or self.headers.get("X-Scheduler-User-Role") or "")

    def _assert_access(self, method: str, path: str) -> None:
        if auth_required():
            self._authenticated_user = authenticate_headers(
                self.headers,
                require_csrf=str(method or "").upper() not in {"GET", "HEAD", "OPTIONS"},
            )
        assert_request_allowed(method, path, self._request_role())

    def _request_identity(self) -> AuthenticatedUser:
        identity = getattr(self, "_authenticated_user", None)
        if identity is None:
            identity = authenticate_headers(self.headers)
            if identity is None:
                raise AuthenticationError("请先登录")
            self._authenticated_user = identity
        return identity

    def _actor(self, body: Mapping[str, Any] | None = None) -> str:
        if auth_required():
            return self._request_identity().user_id
        return str((body or {}).get("actor") or "web")

    def _client_ip(self) -> str:
        direct = str(self.client_address[0] if self.client_address else "unknown")
        if not _env_bool("SCHEDULER_TRUST_PROXY_HEADERS", False):
            return direct
        forwarded = str(self.headers.get("X-Forwarded-For") or "").split(",", 1)[0].strip()
        try:
            return str(ipaddress.ip_address(forwarded)) if forwarded else direct
        except ValueError:
            return direct

    def _build_access_context(self) -> dict[str, Any]:
        payload = build_access_context(self._request_role(), load_academic_affairs_payload())
        payload["authentication"] = session_payload(
            self._request_identity() if auth_required() else None
        )
        return payload

    def _solve_status(self) -> dict[str, Any]:
        return attach_formal_solve_phase(current_solve_status() if async_solve_enabled() else get_solve_status())

    def _send(
        self,
        status: int,
        content: bytes,
        content_type: str,
        headers: Mapping[str, str] | Iterable[tuple[str, str]] | None = None,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        header_items = list(headers.items()) if isinstance(headers, Mapping) else list(headers or [])
        if self.path.startswith("/api/") and not any(name.lower() == "cache-control" for name, _ in header_items):
            header_items.append(("Cache-Control", "no-store"))
        existing_names = {name.lower() for name, _ in header_items}
        header_items.extend((name, value) for name, value in _security_headers() if name.lower() not in existing_names)
        for name, value in header_items:
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(content)

    def _send_file_bytes(self, content: bytes, content_type: str, download_name: str) -> None:
        safe_name = download_name.replace("\r", "").replace("\n", "")
        quoted = quote(safe_name)
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header(
            "Content-Disposition",
            f"attachment; filename*=UTF-8''{quoted}",
        )
        self.send_header("Cache-Control", "no-store")
        for name, value in _security_headers():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(content)

    def _serve_download_path(self, path: Path, *, download_name: str | None = None) -> None:
        target = path.resolve()
        artifact_root = (
            runtime_web_run_root().parent.resolve()
            if auth_required()
            else (PROJECT_ROOT / "outputs").resolve()
        )
        if artifact_root not in target.parents:
            self._send(*_json_bytes({"error": "invalid download path"}, status=403))
            return
        if not target.exists() or not target.is_file():
            self._send(*_json_bytes({"error": "file not found"}, status=404))
            return
        content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        self._send_file_bytes(target.read_bytes(), content_type, download_name or target.name)

    def _serve_static(self, relative: str) -> None:
        target = (STATIC_DIR / relative).resolve()
        if STATIC_DIR.resolve() not in target.parents and target != STATIC_DIR.resolve():
            self._send(*_json_bytes({"error": "invalid static path"}, status=403))
            return
        if not target.exists() or not target.is_file():
            self._send(*_json_bytes({"error": "not found"}, status=404))
            return
        ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        self._send(200, target.read_bytes(), ctype, headers={"Cache-Control": "no-store"})

    def _read_teacher_subject_upload(self) -> dict[str, Any]:
        form = self._read_multipart_form("请使用 multipart/form-data 上传教师定位表文件")
        field = form.get_file("file")
        if field is None:
            raise ValueError("缺少 file 字段")
        filename = field.filename.lower()
        content = field.content
        if filename.endswith(".csv"):
            return parse_teacher_subject_csv(content.decode("utf-8-sig"))
        if filename.endswith((".xlsx", ".xls")):
            return parse_teacher_subject_xlsx(content)
        raise ValueError("仅支持 .xlsx、.xls 或 .csv 教师定位表导入")

    def _read_academic_affairs_upload(self) -> dict[str, Any]:
        form = self._read_multipart_form("请使用 multipart/form-data 上传教务表文件")
        field = form.get_file("file")
        if field is None:
            raise ValueError("缺少 file 字段")
        table_key = str(form.getfirst("table", "") or "").strip()
        filename = field.filename.lower()
        content = field.content
        if filename.endswith(".csv"):
            return parse_academic_table_csv(table_key, content.decode("utf-8-sig"))
        if filename.endswith(".xlsx"):
            return parse_academic_table_xlsx(table_key, content)
        raise ValueError("仅支持 .xlsx 或 .csv 教务表导入")

    def _read_academic_affairs_workbook_upload(self) -> dict[str, Any]:
        form = self._read_multipart_form("请使用 multipart/form-data 上传教务全量工作簿")
        field = form.get_file("file")
        if field is None:
            raise ValueError("缺少 file 字段")
        filename = field.filename.lower()
        content = field.content
        if filename.endswith(".xlsx"):
            return parse_academic_workbook_xlsx(content)
        raise ValueError("仅支持 .xlsx 教务全量工作簿导入")

    def _read_day_rule_upload(self) -> dict[str, Any]:
        form = self._read_multipart_form("请使用 multipart/form-data 上传白天规则表文件")
        field = form.get_file("file")
        if field is None:
            raise ValueError("缺少 file 字段")
        table_key = str(form.getfirst("table", "") or "").strip()
        filename = field.filename.lower()
        content = field.content
        if filename.endswith(".csv"):
            return parse_day_rule_table_csv(table_key, content.decode("utf-8-sig"))
        if filename.endswith(".xlsx"):
            return parse_day_rule_table_xlsx(table_key, content)
        raise ValueError("仅支持 .xlsx 或 .csv 白天规则表导入")

    def _read_multipart_form(self, error_message: str) -> MultipartForm:
        ctype = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in ctype:
            raise ValueError(error_message)
        return parse_multipart_form(
            self.rfile,
            content_type=ctype,
            content_length=self.headers.get("Content-Length", "0"),
        )

    def _apply_temp_rule(self, body: dict[str, Any], *, reverse: bool) -> dict[str, Any]:
        rule = body.get("rule")
        if not isinstance(rule, dict):
            raise ValueError("rule must be an object")
        overrides = load_web_overrides()
        temporary = overrides.setdefault("temporary_rules", {"active": []})
        if not isinstance(temporary, dict):
            temporary = {"active": []}
            overrides["temporary_rules"] = temporary
        active = temporary.get("active")
        if not isinstance(active, list):
            active = []
        rid = str(rule.get("id") or "")
        if reverse:
            active = [
                item
                for item in active
                if not (
                    isinstance(item, dict)
                    and str(item.get("id") or "") == rid
                    and (
                        str(item.get("kind") or "") == NATURAL_LANGUAGE_RULE_KIND
                        or str(item.get("schema_version") or "") == RULE_DRAFT_SCHEMA_VERSION
                    )
                )
            ]
        else:
            validation = validate_rule_draft(rule)
            if not validation.valid:
                raise ValueError("规则草案校验失败：" + "；".join(validation.errors))
            next_rule = activate_rule_draft(
                rule,
                confirmed=body.get("confirm") is True,
                actor=self._actor(body),
            )
            replaced = False
            revised_active = []
            for item in active:
                same_rule = (
                    isinstance(item, dict)
                    and str(item.get("id") or "") == rid
                    and (
                        str(item.get("kind") or "") == NATURAL_LANGUAGE_RULE_KIND
                        or str(item.get("schema_version") or "") == RULE_DRAFT_SCHEMA_VERSION
                    )
                )
                if same_rule:
                    if not replaced:
                        revised_active.append(next_rule)
                        replaced = True
                else:
                    revised_active.append(item)
            if not replaced:
                revised_active.append(next_rule)
            active = revised_active
        temporary["active"] = active
        return save_web_overrides(
            overrides,
            actor_user_id=self._actor(body),
            reason="remove natural-language rule" if reverse else "activate natural-language rule",
        )

    def _apply_diagnostic_relaxation(self, body: dict[str, Any]) -> dict[str, Any]:
        plan_id = str(body.get("plan_id") or "").strip()
        if not plan_id:
            raise ValueError("plan_id is required")
        diagnostics = self._solve_status().get("solve_diagnostics", {})
        plans = diagnostics.get("relaxation_plans") if isinstance(diagnostics, dict) else []
        plan = next((item for item in plans if isinstance(item, dict) and str(item.get("id") or "") == plan_id), None)
        if plan is None:
            raise ValueError(f"unknown relaxation plan: {plan_id}")
        return apply_relaxation_plan(plan)


def _conversation_idempotency_key(
    session_id: str,
    confirmed_workspace_revision: Any,
    *,
    attempt: Any = None,
) -> str:
    try:
        revision = int(confirmed_workspace_revision)
    except (TypeError, ValueError) as exc:
        raise ValueError("expected_workspace_revision must be an integer") from exc
    if revision <= 0:
        raise ValueError("expected_workspace_revision must be positive")
    base = f"conversation-{str(session_id)}-r{revision}"
    explicit_attempt = str(attempt or "").strip()
    if explicit_attempt:
        if not re.fullmatch(r"[A-Za-z0-9._:-]{1,64}", explicit_attempt):
            raise ValueError("conversation attempt must contain 1-64 safe ASCII characters")
        return f"{base}-a{explicit_attempt}"

    organization_id = runtime_organization_id()
    candidates = [
        job
        for job in SolveJobStore(runtime_store()).list_jobs(organization_id, limit=200)
        if job.idempotency_key == base or job.idempotency_key.startswith(base + "-a")
    ]
    if not candidates:
        return base
    latest = candidates[0]
    if latest.status in ACTIVE_JOB_STATUSES or latest.status == COMPLETED:
        return latest.idempotency_key
    attempts = [0]
    for job in candidates:
        suffix = job.idempotency_key[len(base):]
        if suffix.startswith("-a"):
            try:
                attempts.append(int(suffix[2:]))
            except ValueError:
                continue
    return f"{base}-a{max(attempts) + 1}"


def _slot_context_from_time_grid(rows: Any) -> dict[str, list[str]]:
    """Build parser aliases from the configured time-grid labels and counts."""
    context: dict[str, list[str]] = {}
    if not isinstance(rows, list):
        return context
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        label = str(row.get("时段节次") or row.get("节次") or "").strip()
        if not label:
            continue
        context.setdefault(label, []).append(label)
        match = re.fullmatch(r"(.+?)(\d+)$", label)
        if match:
            block, number = match.groups()
            context.setdefault(block, []).append(label)
            context.setdefault(f"第{int(number)}节", []).append(label)
    return {key: list(dict.fromkeys(values)) for key, values in context.items()}


class SchedulerThreadingHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def _validate_server_startup(host: str) -> None:
    loopback = _host_is_loopback(host)
    if not loopback and not auth_required():
        raise RuntimeError("non-loopback Web binding requires SCHEDULER_AUTH_MODE=required")
    if auth_required() and not uses_sqlite_workspace():
        raise RuntimeError("required authentication needs SCHEDULER_STATE_BACKEND=sqlite")
    if not loopback:
        login_secret = str(os.environ.get("SCHEDULER_LOGIN_RATE_LIMIT_SECRET") or "").strip()
        if len(login_secret) < 32 or any(marker in login_secret.lower() for marker in ("replace", "change-me")):
            raise RuntimeError("non-loopback Web binding requires a random SCHEDULER_LOGIN_RATE_LIMIT_SECRET")
    if not loopback and not _env_bool("SCHEDULER_COOKIE_SECURE", True) and not _env_bool(
        "SCHEDULER_ALLOW_INSECURE_HTTP", False
    ):
        raise RuntimeError("non-loopback Web binding requires secure cookies or explicit insecure-HTTP override")
    if auth_required():
        payload = platform_health(runtime_store(), runtime_organization_id())
        if not payload.get("ready"):
            raise RuntimeError("platform database, organization, or workspace is not ready")


def _host_is_loopback(host: str) -> bool:
    value = str(host or "").strip().lower()
    if value == "localhost":
        return True
    try:
        return ipaddress.ip_address(value).is_loopback
    except ValueError:
        return False


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
    parser = argparse.ArgumentParser(description="Scheduler configuration Web UI")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    _validate_server_startup(str(args.host))
    server = SchedulerThreadingHTTPServer((args.host, int(args.port)), SchedulerWebHandler)
    def request_shutdown(signum: int, _frame: object) -> None:
        logger.info("Scheduler Web UI received signal %s; stopping", signum)
        threading.Thread(target=server.shutdown, daemon=True).start()

    for signal_name in ("SIGTERM", "SIGINT"):
        handled_signal = getattr(signal, signal_name, None)
        if handled_signal is not None:
            signal.signal(handled_signal, request_shutdown)
    logger.info("Scheduler Web UI: http://%s:%s", args.host, args.port)
    logger.info("Project root: %s", PROJECT_ROOT)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Scheduler Web UI stopping")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
