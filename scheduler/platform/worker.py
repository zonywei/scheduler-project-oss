"""Independent worker process for durable solve jobs."""
from __future__ import annotations

import argparse
import logging
import os
import socket
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Iterator, Mapping

from scheduler.platform.jobs import (
    CANCELLED,
    COMPLETED,
    FAILED,
    JobLeaseLost,
    SolveJob,
    SolveJobStore,
)
from scheduler.platform.runtime import runtime_organization_id, runtime_store
from scheduler.platform.health import record_service_heartbeat


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ExecutionOutcome:
    status: str
    result: dict[str, Any]
    error_code: str = ""
    error_message: str = ""


class WorkerControl:
    def __init__(self, jobs: SolveJobStore, job: SolveJob, worker_id: str) -> None:
        self.jobs = jobs
        self.job = job
        self.worker_id = worker_id

    def heartbeat(self) -> None:
        self.jobs.heartbeat(self.job.id, worker_id=self.worker_id)
        record_service_heartbeat(
            self.jobs.store,
            self.job.organization_id,
            service_kind="solve-worker",
            instance_id=self.worker_id,
            metadata={"status": "running", "job_id": self.job.id},
        )

    def cancellation_requested(self) -> bool:
        return self.jobs.cancellation_requested(self.job.id, worker_id=self.worker_id)

    def attach_execution(self, *, run_dir: str, process_id: int | None) -> None:
        self.jobs.attach_execution(
            self.job.id,
            worker_id=self.worker_id,
            run_dir=run_dir,
            process_id=process_id,
        )


JobExecutor = Callable[[SolveJob, WorkerControl], ExecutionOutcome]


class SolveWorker:
    def __init__(
        self,
        jobs: SolveJobStore,
        *,
        organization_id: str,
        worker_id: str,
        executor: JobExecutor | None = None,
        poll_seconds: float = 2.0,
    ) -> None:
        self.jobs = jobs
        self.organization_id = str(organization_id)
        self.worker_id = str(worker_id)
        self.poll_seconds = max(0.1, float(poll_seconds))
        self.executor = executor or self._execute_solver

    def run_once(self) -> bool:
        self._heartbeat(status="idle")
        job = self.jobs.claim_next(self.organization_id, worker_id=self.worker_id)
        if job is None:
            return False
        self._heartbeat(status="running", job_id=job.id)
        control = WorkerControl(self.jobs, job, self.worker_id)
        try:
            outcome = self.executor(job, control)
        except JobLeaseLost:
            raise
        except Exception as exc:
            outcome = ExecutionOutcome(
                status=FAILED,
                result={},
                error_code="worker_execution_error",
                error_message=str(exc),
            )
        self.jobs.finish(
            job.id,
            worker_id=self.worker_id,
            status=outcome.status,
            result=outcome.result,
            error_code=outcome.error_code,
            error_message=outcome.error_message,
        )
        self._heartbeat(status="idle")
        return True

    def run_forever(self) -> None:
        while True:
            if not self.run_once():
                time.sleep(self.poll_seconds)

    def _heartbeat(self, *, status: str, job_id: str = "") -> None:
        metadata = {"status": str(status)}
        if job_id:
            metadata["job_id"] = str(job_id)
        record_service_heartbeat(
            self.jobs.store,
            self.organization_id,
            service_kind="solve-worker",
            instance_id=self.worker_id,
            metadata=metadata,
        )

    def _execute_solver(self, job: SolveJob, control: WorkerControl) -> ExecutionOutcome:
        from scheduler.app import solve_service

        if control.cancellation_requested():
            return ExecutionOutcome(status=CANCELLED, result={"message": "任务在启动前取消"})
        with _workspace_revision(job.workspace_revision):
            solver_started = False
            try:
                status = solve_service.start_solve(dict(job.request))
                solver_started = True
                control.attach_execution(
                    run_dir=str(status.get("run_dir") or ""),
                    process_id=_optional_int(status.get("process_id")),
                )
                while True:
                    control.heartbeat()
                    if control.cancellation_requested():
                        stopped = solve_service.force_stop_solve()
                        return ExecutionOutcome(status=CANCELLED, result=_result_summary(stopped))
                    status = solve_service.get_solve_status()
                    solver_status = str(status.get("status") or "").lower()
                    if solver_status == "completed":
                        return ExecutionOutcome(status=COMPLETED, result=_result_summary(status))
                    if solver_status in {"failed", "stopped", "error", "unknown"}:
                        return ExecutionOutcome(
                            status=FAILED,
                            result=_result_summary(status),
                            error_code=f"solver_{solver_status}",
                            error_message=str(status.get("message") or "求解任务未正常完成"),
                        )
                    time.sleep(self.poll_seconds)
            except BaseException:
                if solver_started:
                    try:
                        solve_service.force_stop_solve()
                    except Exception:
                        pass
                raise


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
    parser = argparse.ArgumentParser(description="Scheduler durable solve worker")
    parser.add_argument("--once", action="store_true", help="Process at most one queued job")
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    parser.add_argument("--lease-timeout-seconds", type=int, default=120)
    parser.add_argument("--worker-id", default="")
    args = parser.parse_args()

    organization_id = runtime_organization_id()
    jobs = SolveJobStore(runtime_store())
    worker_id = str(args.worker_id or _default_worker_id())
    timeout = max(30, int(args.lease_timeout_seconds))
    jobs.fail_stale_leases(
        organization_id,
        heartbeat_before=datetime.now(timezone.utc) - timedelta(seconds=timeout),
    )
    worker = SolveWorker(
        jobs,
        organization_id=organization_id,
        worker_id=worker_id,
        poll_seconds=float(args.poll_seconds),
    )
    logger.info("Scheduler solve worker started: %s", worker_id)
    if args.once:
        worker.run_once()
    else:
        worker.run_forever()


def _default_worker_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"


@contextmanager
def _workspace_revision(revision: int) -> Iterator[None]:
    name = "SCHEDULER_WORKSPACE_REVISION"
    previous = os.environ.get(name)
    os.environ[name] = str(int(revision))
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = previous


def _result_summary(status: Mapping[str, Any]) -> dict[str, Any]:
    keys = (
        "status",
        "run_id",
        "run_dir",
        "message",
        "completed_at",
        "package_path",
        "publish_state",
        "objective_value",
    )
    return {key: status.get(key) for key in keys if status.get(key) is not None}


def _optional_int(value: Any) -> int | None:
    if value is None or str(value).strip() == "":
        return None
    return int(value)


if __name__ == "__main__":
    main()
