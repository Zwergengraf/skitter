from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable, Optional

from ..data.db import SessionLocal
from ..data.repositories import Repository
from .graph import (
    reset_current_channel_id,
    reset_current_message_id,
    reset_current_origin,
    reset_current_run_id,
    reset_current_scope_id,
    reset_current_scope_type,
    reset_current_session_id,
    reset_current_user_id,
    set_current_channel_id,
    set_current_message_id,
    set_current_origin,
    set_current_run_id,
    set_current_scope_id,
    set_current_scope_type,
    set_current_session_id,
    set_current_user_id,
)
from .config import settings
from .llm import resolve_model_name
from .prompting import build_system_prompt
from .subagents import SubAgentService, SubAgentTaskSpec


DeliverFunc = Callable[[str, str, str, list], Awaitable[None]]
_logger = logging.getLogger(__name__)


def job_run_id(job_id: str) -> str:
    return f"job:{job_id}"


def job_message_id(job_id: str) -> str:
    return f"job:{job_id}"


class JobService:
    def __init__(self, runtime, graph_factory: Callable[[str], object], deliver: Optional[DeliverFunc] = None) -> None:
        self.runtime = runtime
        self._deliver = deliver
        self._subagents = SubAgentService(graph_factory=graph_factory)
        self._workers: list[asyncio.Task] = []
        self._started = False
        self._stop_event = asyncio.Event()

    def set_deliver(self, deliver: DeliverFunc) -> None:
        self._deliver = deliver

    async def start(self) -> None:
        if self._started or not settings.jobs_enabled:
            return
        self._started = True
        self._stop_event.clear()
        worker_count = max(1, int(settings.jobs_max_concurrent))
        self._workers = [
            asyncio.create_task(self._worker_loop(index), name=f"skitter-job-worker-{index}")
            for index in range(worker_count)
        ]

    async def stop(self) -> None:
        if not self._started:
            return
        self._stop_event.set()
        for task in self._workers:
            task.cancel()
        for task in self._workers:
            try:
                await task
            except BaseException:
                pass
        self._workers = []
        self._started = False

    async def enqueue_subagent_job(
        self,
        *,
        user_id: str,
        session_id: str,
        name: str,
        task: str,
        context: str | None,
        acceptance_criteria: str | None,
        model_name: str,
        target_scope_type: str,
        target_scope_id: str,
        target_origin: str | None,
        target_destination_id: str | None,
    ) -> str:
        limits = {
            "max_tool_calls": max(1, int(settings.job_limits_max_tool_calls)),
            "max_runtime_seconds": max(1, int(settings.job_limits_max_runtime_seconds)),
            "max_cost_usd": max(0.0, float(settings.job_limits_max_cost_usd)),
        }
        payload = {
            "task": task,
            "context": context or "",
            "acceptance_criteria": acceptance_criteria or "",
        }
        async with SessionLocal() as session:
            repo = Repository(session)
            job = await repo.create_agent_job(
                user_id=user_id,
                session_id=session_id,
                kind="sub_agent",
                name=name,
                model=model_name,
                payload=payload,
                limits=limits,
                target_scope_type=target_scope_type,
                target_scope_id=target_scope_id,
                target_origin=target_origin,
                target_destination_id=target_destination_id,
            )
        return job.id

    async def get_job(self, user_id: str, job_id: str):
        async with SessionLocal() as session:
            repo = Repository(session)
            job = await repo.get_agent_job(job_id)
            if job is None or job.user_id != user_id:
                return None
            return job

    async def list_jobs(self, user_id: str, limit: int = 20, status: str | None = None):
        async with SessionLocal() as session:
            repo = Repository(session)
            return await repo.list_agent_jobs(user_id, limit=limit, status=status)

    async def cancel_job(self, user_id: str, job_id: str):
        async with SessionLocal() as session:
            repo = Repository(session)
            return await repo.request_cancel_agent_job(user_id, job_id)

    async def _worker_loop(self, worker_index: int) -> None:
        poll_interval = max(1, int(settings.jobs_poll_interval_seconds))
        while not self._stop_event.is_set():
            try:
                job = await self._claim_next_job()
                if job is None:
                    await asyncio.sleep(poll_interval)
                    continue
                await self._run_job(job)
            except asyncio.CancelledError:
                raise
            except Exception:
                _logger.exception("Job worker %s failed while processing queue", worker_index)
                await asyncio.sleep(poll_interval)

    async def _claim_next_job(self):
        async with SessionLocal() as session:
            repo = Repository(session)
            return await repo.claim_next_agent_job()

    async def _ensure_target_session(self, job, model_name: str) -> str:
        async with SessionLocal() as session:
            repo = Repository(session)
            target = await repo.get_active_session_by_scope(job.target_scope_type, job.target_scope_id)
            if target is None:
                target = await repo.create_session(
                    job.user_id,
                    status="active",
                    model=model_name,
                    origin=job.target_origin or "job",
                    scope_type=job.target_scope_type,
                    scope_id=job.target_scope_id,
                )
            return target.id

    @staticmethod
    def _summary_text(job_name: str, status: str, body: str) -> str:
        status_label = {
            "completed": "completed",
            "failed": "failed",
            "timeout": "timed out",
            "cancelled": "cancelled",
        }.get(status, status)
        if body.strip():
            return f"Background job `{job_name}` {status_label}.\n\n{body.strip()}"
        return f"Background job `{job_name}` {status_label}."

    async def _run_job(self, job) -> None:
        try:
            model_name = resolve_model_name(job.model, purpose="main")
            target_session_id = await self._ensure_target_session(job, model_name)
            execution_session_id = job.session_id or target_session_id
            payload = dict(job.payload or {})
            task = str(payload.get("task") or "").strip()
            spec = SubAgentTaskSpec(
                task=task,
                name=job.name,
                context=str(payload.get("context") or "").strip() or None,
                acceptance_criteria=str(payload.get("acceptance_criteria") or "").strip() or None,
            )
            limits = dict(job.limits or {})
            run_id = job_run_id(job.id)
            message_id = job_message_id(job.id)
            context_tokens = {
                "session": set_current_session_id(execution_session_id),
                "channel": set_current_channel_id(job.target_destination_id or ""),
                "user": set_current_user_id(job.user_id),
                "origin": set_current_origin(job.target_origin or "job"),
                "run_id": set_current_run_id(run_id),
                "message_id": set_current_message_id(message_id),
                "scope_type": set_current_scope_type(job.target_scope_type or "private"),
                "scope_id": set_current_scope_id(job.target_scope_id or f"private:{job.user_id}"),
            }
            try:
                result = await self._subagents.run_one(
                    user_id=job.user_id,
                    session_id=execution_session_id,
                    model_name=model_name,
                    system_prompt=build_system_prompt(job.user_id),
                    spec=spec,
                    max_runtime_seconds=int(limits.get("max_runtime_seconds") or settings.job_limits_max_runtime_seconds),
                    limits_override=limits,
                )
            finally:
                reset_current_scope_id(context_tokens["scope_id"])
                reset_current_scope_type(context_tokens["scope_type"])
                reset_current_origin(context_tokens["origin"])
                reset_current_user_id(context_tokens["user"])
                reset_current_message_id(context_tokens["message_id"])
                reset_current_run_id(context_tokens["run_id"])
                reset_current_channel_id(context_tokens["channel"])
                reset_current_session_id(context_tokens["session"])
            status = result.status
            error = result.error
            async with SessionLocal() as session:
                repo = Repository(session)
                current = await repo.get_agent_job(job.id)
                if current is not None and current.cancel_requested and current.status == "running":
                    status = "cancelled"
                    error = "Cancellation requested by user."
                await repo.complete_agent_job(
                    job.id,
                    status=status,
                    result_payload={
                        "worker": result.to_dict(),
                        "summary": (result.final_text or "").strip(),
                    },
                    error=error,
                    tool_calls_used=int(result.usage.get("tool_calls_used") or 0),
                    input_tokens=int(result.usage.get("input_tokens") or 0),
                    output_tokens=int(result.usage.get("output_tokens") or 0),
                    total_tokens=int(result.usage.get("total_tokens") or 0),
                    cost=float(result.usage.get("cost_usd") or 0.0),
                )

            text_body = result.final_text if status == "completed" else (error or result.final_text or "")
            delivery_text = self._summary_text(job.name, status, text_body)
            delivery_error: str | None = None
            try:
                async with SessionLocal() as session:
                    repo = Repository(session)
                    await repo.add_message(
                        target_session_id,
                        role="assistant",
                        content=delivery_text,
                        metadata={
                            "origin": "job",
                            "job_id": job.id,
                            "job_status": status,
                        },
                    )
                self.runtime.clear_history(target_session_id)
                if self._deliver is not None and job.target_origin and job.target_destination_id:
                    try:
                        await self._deliver(job.target_origin, job.target_destination_id, delivery_text, [])
                    except Exception as exc:  # pragma: no cover - transport-specific failure path
                        delivery_error = str(exc)
            finally:
                async with SessionLocal() as session:
                    repo = Repository(session)
                    await repo.mark_agent_job_delivered(job.id, delivery_error=delivery_error)
        except Exception as exc:
            _logger.exception("Background job %s failed unexpectedly", job.id)
            async with SessionLocal() as session:
                repo = Repository(session)
                await repo.complete_agent_job(
                    job.id,
                    status="failed",
                    result_payload={},
                    error=str(exc),
                )
