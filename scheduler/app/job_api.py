"""Web-facing durable solve job contract."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from scheduler.app.readiness import build_solve_readiness
from scheduler.app.solve_service import runtime_web_run_root
from scheduler.platform.jobs import ACTIVE_JOB_STATUSES, JobNotFound, SolveJob, SolveJobStore, job_payload
from scheduler.platform.runtime import runtime_organization_id, runtime_store, uses_sqlite_workspace


_ALLOWED_REQUEST_FIELDS = {
    "mode",
    "time_limit_seconds",
    "workers",
    "max_keep",
    "snapshot_interval_sec",
    "enable_snapshots",
    "grade_prefix",
    "random_seed",
    "seed",
    "relative_gap_limit",
    "absolute_gap_limit",
    "log_search_progress",
    "continue_from_best",
    "solver_profile",
    "optimization_profile",
    "diagnostic_trial",
    "diagnostic_plan_id",
    "diagnostic_plan_title",
}


def async_solve_enabled() -> bool:
    default = "async" if uses_sqlite_workspace() else "inline"
    value = str(os.environ.get("SCHEDULER_SOLVE_MODE") or default).strip().lower()
    if value not in {"inline", "async"}:
        raise ValueError("SCHEDULER_SOLVE_MODE must be inline or async")
    if value == "async" and not uses_sqlite_workspace():
        raise RuntimeError("async solve mode requires SCHEDULER_STATE_BACKEND=sqlite")
    return value == "async"


def enqueue_solve_job(
    payload: Mapping[str, Any],
    *,
    actor_user_id: str,
    idempotency_key: str = "",
    expected_workspace_revision: int | None = None,
) -> dict[str, Any]:
    request = normalize_solve_request(payload)
    expected_revision = _optional_workspace_revision(expected_workspace_revision)
    readiness = build_solve_readiness(str(request["mode"]))
    if not readiness.get("summary", {}).get("can_start_solver", False):
        blocking = [
            item
            for item in readiness.get("items", [])
            if isinstance(item, dict) and item.get("blocking") and item.get("severity") == "error"
        ]
        titles = "；".join(str(item.get("title") or "求解前校验未通过") for item in blocking[:3])
        raise RuntimeError(f"求解前校验未通过：{titles or '存在阻断项'}")
    organization_id = runtime_organization_id()
    store = runtime_store()
    workspace = store.load_workspace(organization_id)
    if workspace is None:
        raise RuntimeError("当前学校尚未初始化工作区")
    enqueue_revision = expected_revision if expected_revision is not None else workspace.revision
    created = SolveJobStore(store).create_job(
        organization_id,
        request,
        created_by=actor_user_id,
        workspace_revision=enqueue_revision,
        idempotency_key=idempotency_key,
        expected_workspace_revision=expected_revision,
    )
    result = job_payload(created.job)
    result["created"] = created.created
    result["message"] = "求解任务已进入队列" if created.created else "已返回同一幂等请求创建的任务"
    return result


def list_solve_jobs(*, limit: int = 50) -> dict[str, Any]:
    organization_id = runtime_organization_id()
    jobs = SolveJobStore(runtime_store()).list_jobs(organization_id, limit=limit)
    return {
        "schema_version": "scheduler.solve_job_list.v1",
        "jobs": [job_payload(job) for job in jobs],
        "count": len(jobs),
    }


def get_solve_job(job_id: str) -> dict[str, Any]:
    organization_id = runtime_organization_id()
    job = SolveJobStore(runtime_store()).get_job(organization_id, job_id)
    return _with_live_status(job)


def cancel_solve_job(job_id: str, *, actor_user_id: str) -> dict[str, Any]:
    organization_id = runtime_organization_id()
    job = SolveJobStore(runtime_store()).request_cancel(
        organization_id,
        job_id,
        actor_user_id=actor_user_id,
    )
    result = job_payload(job)
    result["message"] = "已请求取消任务" if job.status == "cancel_requested" else "任务已取消"
    return result


def cancel_latest_solve_job(*, actor_user_id: str) -> dict[str, Any]:
    organization_id = runtime_organization_id()
    jobs = SolveJobStore(runtime_store())
    active = next(
        (job for job in jobs.list_jobs(organization_id, limit=100) if job.status in ACTIVE_JOB_STATUSES),
        None,
    )
    if active is None:
        latest = jobs.latest_job(organization_id)
        if latest is None:
            return {"status": "idle", "message": "暂无可取消的求解任务", "files": []}
        result = job_payload(latest)
        result["message"] = "最近任务已经结束"
        return result
    return cancel_solve_job(active.id, actor_user_id=actor_user_id)


def current_solve_status() -> dict[str, Any]:
    organization_id = runtime_organization_id()
    latest = SolveJobStore(runtime_store()).latest_job(organization_id)
    if latest is None:
        return {
            "schema_version": "scheduler.solve_job_status.v1",
            "status": "idle",
            "message": "暂无求解任务",
            "files": [],
        }
    return _with_live_status(latest)


def normalize_solve_request(payload: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise ValueError("solve request must be an object")
    unknown = sorted(str(key) for key in payload if str(key) not in _ALLOWED_REQUEST_FIELDS)
    if unknown:
        raise ValueError("unsupported solve request fields: " + ", ".join(unknown))
    mode = str(payload.get("mode") or "joint").strip().lower()
    if mode not in {"course", "day", "joint", "night"}:
        raise ValueError("mode must be course, day, joint or night")
    request = dict(payload)
    request["mode"] = mode
    request["time_limit_seconds"] = _bounded_int(payload.get("time_limit_seconds", 300), 10, 21_600, "time_limit_seconds")
    request["workers"] = _bounded_int(payload.get("workers", 8), 1, 32, "workers")
    request["max_keep"] = _bounded_int(payload.get("max_keep", 10), 1, 50, "max_keep")
    request["snapshot_interval_sec"] = _bounded_int(
        payload.get("snapshot_interval_sec", 30), 5, 3_600, "snapshot_interval_sec"
    )
    if "random_seed" in request or "seed" in request:
        raw_seed = request.get("random_seed", request.get("seed"))
        if raw_seed is not None and str(raw_seed).strip():
            request["random_seed"] = _bounded_int(raw_seed, 0, 2_147_483_647, "random_seed")
            request.pop("seed", None)
    return json.loads(json.dumps(request, ensure_ascii=False))


def solve_job_id_from_path(path: str, *, suffix: str = "") -> str | None:
    prefix = "/api/solve/jobs/"
    value = str(path or "")
    if not value.startswith(prefix):
        return None
    remainder = value[len(prefix):]
    if suffix:
        marker = "/" + suffix.strip("/")
        if not remainder.endswith(marker):
            return None
        remainder = remainder[: -len(marker)]
    if not remainder or "/" in remainder or len(remainder) > 80:
        return None
    return remainder


def _with_live_status(job: SolveJob) -> dict[str, Any]:
    result: dict[str, Any] = {}
    status_path = _safe_status_path(job)
    if status_path is not None and status_path.exists():
        try:
            loaded = json.loads(status_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                result.update(loaded)
        except (OSError, ValueError):
            pass
    result.update(job_payload(job))
    result["job_id"] = job.id
    result["status"] = job.status
    result.setdefault("files", [])
    result["elapsed_seconds"] = _job_elapsed_seconds(job)
    result["last_update_seconds"] = _seconds_since(job.updated_at)
    result["time_limit_seconds"] = int(job.request.get("time_limit_seconds") or 0)
    result["timing"] = {
        "created_at": job.created_at,
        "started_at": job.started_at,
        "completed_at": job.completed_at,
        "heartbeat_at": job.heartbeat_at,
        "elapsed_seconds": result["elapsed_seconds"],
        "last_update_seconds": result["last_update_seconds"],
    }
    result["execution_phase"] = _infer_execution_phase(result, job)
    failure = _failure_summary(job)
    if failure:
        result["failure"] = failure
        result["failed_phase"] = failure["phase"]
    running_messages = {
        "validating": "正在核验数据与规则",
        "compiling": "正在创建求解变量与约束",
        "finding_feasible": "工业级求解引擎正在搜索可行课表",
        "optimizing": "已找到候选课表，正在继续全局优化",
        "packaging": "求解已结束，正在生成课表预览与下载文件",
    }
    messages = {
        "queued": "求解任务正在排队，等待 Worker",
        "running": running_messages.get(result["execution_phase"], "求解任务正在独立 Worker 中运行"),
        "cancel_requested": "已请求取消，Worker 正在安全停止求解进程",
        "completed": "求解任务已完成",
        "failed": failure["message"] if failure else "求解任务失败，请重新排课或联系管理员",
        "cancelled": "求解任务已取消",
    }
    result["message"] = messages.get(job.status, str(result.get("message") or ""))
    return result


def _infer_execution_phase(result: Mapping[str, Any], job: SolveJob) -> str:
    if job.status == "queued":
        return "validating"
    if job.status != "running":
        return ""
    status_path = _safe_status_path(job)
    if status_path is None:
        return "validating"
    log_path = status_path.parent / "run.log"
    tail = ""
    if log_path.exists():
        try:
            with log_path.open("rb") as handle:
                handle.seek(0, os.SEEK_END)
                size = handle.tell()
                handle.seek(max(0, size - 32_000), os.SEEK_SET)
                tail = handle.read().decode("utf-8", errors="ignore")
        except OSError:
            tail = ""
    if "status = " in tail or "求解完成时间" in tail:
        return "packaging"
    if int(result.get("solution_count") or 0) > 0:
        return "optimizing"
    if "开始求解时间" in tail:
        return "finding_feasible"
    return "compiling"


def _failure_summary(job: SolveJob) -> dict[str, str] | None:
    if job.status != "failed":
        return None
    detail = str(job.error_message or "").strip()
    lowered = detail.lower()
    if "solvewithsolutioncallback" in lowered:
        return {
            "phase": "finding_feasible",
            "title": "求解未完成",
            "message": "任务在开始搜索候选课表时遇到求解引擎兼容故障。系统组件已修复，请重新排课。",
            "action": "重新启动 AI 智能排课",
            "technical_detail": detail,
        }
    if job.error_code == "worker_lease_expired":
        return {
            "phase": "finding_feasible",
            "title": "求解进程失去连接",
            "message": "后台求解进程长时间没有响应，本次任务已安全中止。请重新排课。",
            "action": "重新启动 AI 智能排课",
            "technical_detail": detail,
        }
    return {
        "phase": "finding_feasible" if job.error_code.startswith("solver_") else "compiling",
        "title": "求解未完成",
        "message": "本次排课已中止，系统保留了任务记录。请重新排课；若再次失败，可展开技术信息交给管理员。",
        "action": "重新启动 AI 智能排课",
        "technical_detail": detail,
    }


def _job_elapsed_seconds(job: SolveJob) -> int:
    started = _parse_timestamp(job.started_at or job.created_at)
    if started is None:
        return 0
    terminal = job.status in {"completed", "failed", "cancelled"}
    ended = _parse_timestamp(job.completed_at) if terminal else datetime.now(timezone.utc)
    return max(0, int(((ended or datetime.now(timezone.utc)) - started).total_seconds()))


def _seconds_since(value: str) -> int:
    parsed = _parse_timestamp(value)
    return max(0, int((datetime.now(timezone.utc) - parsed).total_seconds())) if parsed else 0


def _parse_timestamp(value: str) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _safe_status_path(job: SolveJob) -> Path | None:
    if not job.run_dir:
        return None
    target = (Path(job.run_dir) / "status.json").resolve()
    root = runtime_web_run_root().resolve()
    if root not in target.parents:
        return None
    return target


def _bounded_int(value: Any, minimum: int, maximum: int, label: str) -> int:
    try:
        parsed = int(float(value))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be an integer") from exc
    if not minimum <= parsed <= maximum:
        raise ValueError(f"{label} must be between {minimum} and {maximum}")
    return parsed


def _optional_workspace_revision(value: Any) -> int | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        revision = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("expected_workspace_revision must be an integer") from exc
    if revision <= 0:
        raise ValueError("expected_workspace_revision must be positive")
    return revision
