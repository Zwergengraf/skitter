from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from zoneinfo import ZoneInfo
from typing import Awaitable, Callable, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger

from ..data.db import SessionLocal
from ..data.repositories import Repository
from .config import settings
from .llm import resolve_model_name
from .models import MessageEnvelope


DeliverFunc = Callable[[str, str, str, list], Awaitable[None]]


class SchedulerService:
    def __init__(self, runtime, deliver: Optional[DeliverFunc] = None) -> None:
        self.runtime = runtime
        self.deliver = deliver
        self.scheduler = AsyncIOScheduler(timezone=settings.scheduler_timezone)
        self._started = False

    @staticmethod
    def _utcnow() -> datetime:
        return datetime.now(UTC)

    @staticmethod
    def _to_utc(value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    def _to_local(self, value: datetime | None, timezone_name: str) -> datetime | None:
        utc_value = self._to_utc(value)
        if utc_value is None:
            return None
        try:
            return utc_value.astimezone(ZoneInfo(timezone_name))
        except Exception:
            return utc_value

    async def start(self) -> None:
        if self._started:
            return
        self.scheduler.start()
        self._started = True
        await self._load_jobs()

    async def shutdown(self) -> None:
        if self._started:
            self.scheduler.shutdown(wait=False)
            self._started = False

    def set_deliver(self, deliver: DeliverFunc) -> None:
        self.deliver = deliver

    @staticmethod
    def _normalize_schedule(cron: str) -> tuple[str, str]:
        schedule_type = "cron"
        expr = cron
        if cron.startswith("DATE:"):
            schedule_type = "date"
            expr = cron.replace("DATE:", "", 1).strip()
        return schedule_type, expr

    def _validate_schedule(self, schedule_type: str, expr: str, timezone: str) -> None:
        if schedule_type == "date":
            self._parse_run_date(expr, timezone)
            return
        CronTrigger.from_crontab(expr, timezone=timezone)

    def _next_run_utc(self, job_id: str) -> datetime | None:
        scheduled = self.scheduler.get_job(job_id)
        if scheduled is None:
            return None
        return self._to_utc(scheduled.next_run_time)

    def _job_response(self, job, next_run_utc: datetime | None) -> dict:
        next_run_local = self._to_local(next_run_utc, job.timezone)
        return {
            "id": job.id,
            "name": job.name,
            "cron": job.schedule_expr,
            "enabled": job.enabled,
            "next_run_at": next_run_local.isoformat() if next_run_local else None,
            "timezone": job.timezone,
        }

    async def _load_jobs(self) -> None:
        async with SessionLocal() as session:
            repo = Repository(session)
            jobs = await repo.list_scheduled_jobs_all()
        for job in jobs:
            next_run: datetime | None = None
            if job.enabled:
                self._schedule_job(job.id, job.schedule_type, job.schedule_expr, job.timezone)
                next_run = self._next_run_utc(job.id)
            async with SessionLocal() as session:
                repo = Repository(session)
                await repo.update_scheduled_job(job.id, next_run_at=next_run)

    def _parse_run_date(self, run_at: str, timezone: str) -> datetime:
        dt = datetime.fromisoformat(run_at)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZoneInfo(timezone))
        return dt

    def _schedule_job(self, job_id: str, schedule_type: str, expr: str, timezone: str) -> None:
        if schedule_type == "date":
            run_date = self._parse_run_date(expr, timezone)
            trigger = DateTrigger(run_date=run_date, timezone=timezone)
        else:
            trigger = CronTrigger.from_crontab(expr, timezone=timezone)
        self.scheduler.add_job(self._run_job, trigger, args=[job_id], id=job_id, replace_existing=True)

    async def create_job(
        self,
        user_id: str,
        channel_id: str,
        name: str,
        prompt: str,
        cron: str,
        target_scope_type: str = "private",
        target_scope_id: str | None = None,
        target_origin: str | None = None,
        target_destination_id: str | None = None,
    ) -> dict:
        schedule_type, expr = self._normalize_schedule(cron)
        try:
            self._validate_schedule(schedule_type, expr, settings.scheduler_timezone)
        except Exception as exc:
            return {"error": f"invalid schedule: {exc}"}
        async with SessionLocal() as session:
            repo = Repository(session)
            job = await repo.create_scheduled_job(
                user_id=user_id,
                channel_id=channel_id,
                name=name,
                prompt=prompt,
                cron=expr,
                timezone=settings.scheduler_timezone,
                enabled=True,
                schedule_type=schedule_type,
                target_scope_type=target_scope_type,
                target_scope_id=target_scope_id,
                target_origin=target_origin,
                target_destination_id=target_destination_id,
            )
        self._schedule_job(job.id, job.schedule_type, job.schedule_expr, job.timezone)
        next_run = self._next_run_utc(job.id)
        async with SessionLocal() as session:
            repo = Repository(session)
            await repo.update_scheduled_job(job.id, next_run_at=next_run)
        response = self._job_response(job, next_run)
        # Keep old response shape for compatibility with existing callers.
        response.pop("enabled", None)
        return response

    async def update_job(self, job_id: str, **fields) -> dict:
        if "schedule_expr" in fields:
            schedule_type = fields.get("schedule_type", "cron")
            try:
                self._validate_schedule(schedule_type, fields["schedule_expr"], settings.scheduler_timezone)
            except Exception as exc:
                return {"error": f"invalid schedule: {exc}"}
        async with SessionLocal() as session:
            repo = Repository(session)
            job = await repo.update_scheduled_job(job_id, **fields)
        if job is None:
            return {"error": "job not found"}
        if job.enabled:
            self._schedule_job(job.id, job.schedule_type, job.schedule_expr, job.timezone)
            next_run = self._next_run_utc(job.id)
        else:
            try:
                self.scheduler.remove_job(job.id)
            except Exception:
                pass
            next_run = None
        async with SessionLocal() as session:
            repo = Repository(session)
            await repo.update_scheduled_job(job.id, next_run_at=next_run)
        return self._job_response(job, next_run)

    async def delete_job(self, job_id: str) -> dict:
        async with SessionLocal() as session:
            repo = Repository(session)
            ok = await repo.delete_scheduled_job(job_id)
        if ok:
            try:
                self.scheduler.remove_job(job_id)
            except Exception:
                pass
        return {"deleted": ok}

    async def list_jobs(self, user_id: str) -> list[dict]:
        async with SessionLocal() as session:
            repo = Repository(session)
            jobs = await repo.list_scheduled_jobs(user_id)
        rows: list[dict] = []
        for job in jobs:
            base = self._job_response(job, job.next_run_at)
            rows.append(
                {
                    "id": base["id"],
                    "name": base["name"],
                    "prompt": job.prompt,
                    "cron": base["cron"],
                    "enabled": base["enabled"],
                    "next_run_at": base["next_run_at"],
                    "timezone": base["timezone"],
                    "target_scope_type": job.target_scope_type,
                    "target_scope_id": job.target_scope_id,
                    "target_origin": job.target_origin,
                    "target_destination_id": job.target_destination_id,
                }
            )
        return rows

    async def _run_job(self, job_id: str) -> None:
        async with SessionLocal() as session:
            repo = Repository(session)
            job = await repo.get_scheduled_job(job_id)
            if job is None or not job.enabled:
                return
            user = await repo.get_user_by_id(job.user_id)
            if user is None:
                return
            run = await repo.create_scheduled_run(job_id, status="running")
            now_utc = self._utcnow()
            await repo.update_scheduled_run(run.id, started_at=now_utc)
            await repo.update_scheduled_job(job_id, last_run_at=now_utc)

        execution_session_id = None
        target_session_id = None
        try:
            async with SessionLocal() as session:
                repo = Repository(session)
                model_name = resolve_model_name(None, purpose="main")
                target_scope_type = job.target_scope_type or "private"
                target_scope_id = job.target_scope_id or f"private:{job.user_id}"
                target_session = await repo.get_active_session_by_scope(target_scope_type, target_scope_id)
                if target_session is None:
                    target_session = await repo.create_session(
                        job.user_id,
                        status="active",
                        model=model_name,
                        origin=job.target_origin or "scheduler",
                        scope_type=target_scope_type,
                        scope_id=target_scope_id,
                    )
                target_session_id = target_session.id
                session_obj = await repo.create_session(
                    job.user_id,
                    status="scheduled",
                    model=model_name,
                    origin="scheduler",
                    scope_type="system",
                    scope_id=f"system:scheduled:{job.id}:{run.id}",
                )
                execution_session_id = session_obj.id

            envelope = MessageEnvelope(
                message_id=run.id,
                channel_id=job.target_destination_id or job.channel_id,
                user_id=user.transport_user_id,
                timestamp=self._utcnow(),
                text=job.prompt,
                origin="scheduler",
                metadata={
                    "internal_user_id": user.id,
                    "scope_type": "system",
                    "scope_id": f"system:scheduled:{job.id}:{run.id}",
                    "is_private": False,
                    "target_scope_type": job.target_scope_type or "private",
                    "target_scope_id": job.target_scope_id or f"private:{job.user_id}",
                },
            )
            # Scheduled runs are intentionally stateless: each run executes with no prior chat history.
            self.runtime.clear_history(execution_session_id)
            response = await self.runtime.handle_message(execution_session_id, envelope)
            if target_session_id is not None:
                attachment_meta = []
                for attachment in response.attachments:
                    attachment_meta.append(
                        {
                            "filename": attachment.filename,
                            "content_type": attachment.content_type or "",
                            "url": attachment.url,
                            "path": attachment.path,
                        }
                    )
                async with SessionLocal() as session:
                    repo = Repository(session)
                    meta = {"origin": "scheduler", "job_id": job.id, "run_id": run.id}
                    if response.reasoning:
                        meta["reasoning"] = response.reasoning
                    if attachment_meta:
                        meta["attachments"] = attachment_meta
                    await repo.add_message(
                        target_session_id,
                        role="assistant",
                        content=response.text,
                        metadata=meta,
                    )
            delivery_error: str | None = None
            if self.deliver is not None and job.target_origin and (job.target_destination_id or job.channel_id):
                try:
                    await self.deliver(
                        job.target_origin,
                        job.target_destination_id or job.channel_id,
                        response.text,
                        response.attachments,
                    )
                except Exception as exc:
                    delivery_error = str(exc)

            async with SessionLocal() as session:
                repo = Repository(session)
                await repo.update_scheduled_run(
                    run.id,
                    status="success",
                    finished_at=self._utcnow(),
                    output=response.text,
                    attachments={
                        "count": len(response.attachments),
                        "delivery_error": delivery_error,
                    },
                )
                if job.schedule_type == "date":
                    await repo.update_scheduled_job(job_id, enabled=False)
            if execution_session_id:
                self.runtime.clear_history(execution_session_id)
        except Exception as exc:
            async with SessionLocal() as session:
                repo = Repository(session)
                await repo.update_scheduled_run(
                    run.id,
                    status="failed",
                    finished_at=self._utcnow(),
                    error=str(exc),
                )
        finally:
            async with SessionLocal() as session:
                repo = Repository(session)
                refreshed = await repo.get_scheduled_job(job_id)
                if refreshed is not None:
                    next_run = self._next_run_utc(job_id) if refreshed.enabled else None
                    await repo.update_scheduled_job(job_id, next_run_at=next_run)
