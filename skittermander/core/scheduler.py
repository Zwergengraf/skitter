from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Awaitable, Callable, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from ..data.db import SessionLocal
from ..data.repositories import Repository
from .config import settings
from .models import MessageEnvelope


DeliverFunc = Callable[[str, str, list], Awaitable[None]]


class SchedulerService:
    def __init__(self, runtime, deliver: Optional[DeliverFunc] = None) -> None:
        self.runtime = runtime
        self.deliver = deliver
        self.scheduler = AsyncIOScheduler(timezone=settings.scheduler_timezone)
        self._started = False

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

    async def _load_jobs(self) -> None:
        async with SessionLocal() as session:
            repo = Repository(session)
            jobs = await repo.list_scheduled_jobs_all()
        for job in jobs:
            if job.enabled:
                self._schedule_job(job.id, job.schedule_expr, job.timezone)

    def _schedule_job(self, job_id: str, cron: str, timezone: str) -> None:
        trigger = CronTrigger.from_crontab(cron, timezone=timezone)
        self.scheduler.add_job(self._run_job, trigger, args=[job_id], id=job_id, replace_existing=True)

    async def create_job(self, user_id: str, channel_id: str, name: str, prompt: str, cron: str) -> dict:
        try:
            CronTrigger.from_crontab(cron, timezone=settings.scheduler_timezone)
        except Exception as exc:
            return {"error": f"invalid cron: {exc}"}
        async with SessionLocal() as session:
            repo = Repository(session)
            job = await repo.create_scheduled_job(
                user_id=user_id,
                channel_id=channel_id,
                name=name,
                prompt=prompt,
                cron=cron,
                timezone=settings.scheduler_timezone,
                enabled=True,
            )
        self._schedule_job(job.id, cron, job.timezone)
        next_run = self.scheduler.get_job(job.id).next_run_time  # type: ignore[union-attr]
        async with SessionLocal() as session:
            repo = Repository(session)
            await repo.update_scheduled_job(job.id, next_run_at=next_run)
        return {"id": job.id, "name": job.name, "cron": job.schedule_expr, "next_run_at": str(next_run)}

    async def update_job(self, job_id: str, **fields) -> dict:
        if "schedule_expr" in fields:
            try:
                CronTrigger.from_crontab(fields["schedule_expr"], timezone=settings.scheduler_timezone)
            except Exception as exc:
                return {"error": f"invalid cron: {exc}"}
        async with SessionLocal() as session:
            repo = Repository(session)
            job = await repo.update_scheduled_job(job_id, **fields)
        if job is None:
            return {"error": "job not found"}
        if job.enabled:
            self._schedule_job(job.id, job.schedule_expr, job.timezone)
            next_run = self.scheduler.get_job(job.id).next_run_time  # type: ignore[union-attr]
        else:
            self.scheduler.remove_job(job.id)
            next_run = None
        async with SessionLocal() as session:
            repo = Repository(session)
            await repo.update_scheduled_job(job.id, next_run_at=next_run)
        return {"id": job.id, "name": job.name, "cron": job.schedule_expr, "enabled": job.enabled}

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
        return [
            {
                "id": job.id,
                "name": job.name,
                "cron": job.schedule_expr,
                "enabled": job.enabled,
                "next_run_at": job.next_run_at.isoformat() if job.next_run_at else None,
            }
            for job in jobs
        ]

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
            await repo.update_scheduled_run(run.id, started_at=datetime.utcnow())
            await repo.update_scheduled_job(job_id, last_run_at=datetime.utcnow())

        session_id = None
        try:
            async with SessionLocal() as session:
                repo = Repository(session)
                session_obj = await repo.create_session(job.user_id, status="scheduled")
                session_id = session_obj.id
                await repo.add_message(session_id, role="user", content=job.prompt)

            envelope = MessageEnvelope(
                message_id=run.id,
                channel_id=job.channel_id,
                user_id=user.transport_user_id,
                timestamp=datetime.utcnow(),
                text=job.prompt,
                origin="scheduler",
            )
            response = await self.runtime.handle_message(session_id, envelope)
            if self.deliver is not None:
                await self.deliver(job.channel_id, response.text, response.attachments)

            async with SessionLocal() as session:
                repo = Repository(session)
                await repo.add_message(session_id, role="assistant", content=response.text)
                await repo.update_scheduled_run(
                    run.id,
                    status="success",
                    finished_at=datetime.utcnow(),
                    output=response.text,
                    attachments={"count": len(response.attachments)},
                )
        except Exception as exc:
            async with SessionLocal() as session:
                repo = Repository(session)
                await repo.update_scheduled_run(
                    run.id,
                    status="failed",
                    finished_at=datetime.utcnow(),
                    error=str(exc),
                )
