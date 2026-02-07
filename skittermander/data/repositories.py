from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import List, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import (
    Artifact,
    Channel,
    LlmUsage,
    MemoryEntry,
    Message,
    ScheduledJob,
    ScheduledRun,
    SandboxTask,
    Session,
    Skill,
    Secret,
    ToolRun,
    User,
)


class Repository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_or_create_user(self, transport_user_id: str) -> User:
        result = await self.session.execute(select(User).where(User.transport_user_id == transport_user_id))
        user = result.scalar_one_or_none()
        if user:
            return user
        user = User(id=str(uuid.uuid4()), transport_user_id=transport_user_id, meta={}, approved=False)
        self.session.add(user)
        await self.session.commit()
        return user

    async def get_user_by_transport_id(self, transport_user_id: str) -> Optional[User]:
        result = await self.session.execute(select(User).where(User.transport_user_id == transport_user_id))
        return result.scalar_one_or_none()

    async def upsert_user_profile(
        self,
        transport_user_id: str,
        display_name: str | None,
        username: str | None,
        avatar_url: str | None = None,
    ) -> User:
        user = await self.get_or_create_user(transport_user_id)
        meta = dict(user.meta or {})
        if display_name:
            meta["display_name"] = display_name
        if username:
            meta["username"] = username
        if avatar_url:
            meta["avatar_url"] = avatar_url
        user.meta = meta
        await self.session.commit()
        return user

    async def set_user_approved(self, user_id: str, approved: bool) -> Optional[User]:
        result = await self.session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if user is None:
            return None
        user.approved = approved
        await self.session.commit()
        return user

    async def set_user_meta(self, user_id: str, updates: dict) -> Optional[User]:
        result = await self.session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if user is None:
            return None
        meta = dict(user.meta or {})
        meta.update(updates)
        user.meta = meta
        await self.session.commit()
        return user

    async def mark_user_notified(self, user_id: str) -> None:
        result = await self.session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if user is None:
            return
        meta = dict(user.meta or {})
        meta["approval_notified"] = True
        user.meta = meta
        await self.session.commit()

    async def get_user_by_id(self, user_id: str) -> Optional[User]:
        result = await self.session.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()

    async def create_session(self, user_id: str, status: str = "active", model: str | None = None) -> Session:
        session = Session(id=str(uuid.uuid4()), user_id=user_id, status=status, model=model)
        self.session.add(session)
        await self.session.commit()
        return session

    async def get_session(self, session_id: str) -> Optional[Session]:
        result = await self.session.execute(select(Session).where(Session.id == session_id))
        return result.scalar_one_or_none()

    async def set_session_model(self, session_id: str, model: str) -> Optional[Session]:
        result = await self.session.execute(select(Session).where(Session.id == session_id))
        session = result.scalar_one_or_none()
        if session is None:
            return None
        session.model = model
        await self.session.commit()
        return session

    async def get_active_session(self, user_id: str) -> Optional[Session]:
        result = await self.session.execute(
            select(Session).where(Session.user_id == user_id, Session.status == "active").order_by(Session.created_at.desc())
        )
        return result.scalars().first()

    async def end_session(self, session_id: str, status: str = "ended") -> Optional[Session]:
        result = await self.session.execute(select(Session).where(Session.id == session_id))
        session = result.scalar_one_or_none()
        if session is None:
            return None
        session.status = status
        await self.session.commit()
        return session

    async def add_message(self, session_id: str, role: str, content: str, metadata: dict | None = None) -> Message:
        message = Message(
            id=str(uuid.uuid4()),
            session_id=session_id,
            role=role,
            content=content,
            meta=metadata or {},
        )
        self.session.add(message)
        await self.session.commit()
        return message

    async def record_llm_usage(
        self,
        session_id: str,
        user_id: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        total_tokens: int,
        cost: float,
        last_input_tokens: int | None = None,
        last_output_tokens: int | None = None,
        last_total_tokens: int | None = None,
    ) -> LlmUsage:
        usage = LlmUsage(
            id=str(uuid.uuid4()),
            session_id=session_id,
            user_id=user_id,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            cost=cost,
        )
        self.session.add(usage)
        result = await self.session.execute(select(Session).where(Session.id == session_id))
        session = result.scalar_one_or_none()
        if session is not None:
            session.input_tokens = (session.input_tokens or 0) + input_tokens
            session.output_tokens = (session.output_tokens or 0) + output_tokens
            session.total_tokens = (session.total_tokens or 0) + total_tokens
            session.total_cost = (session.total_cost or 0.0) + cost
            session.last_input_tokens = last_input_tokens if last_input_tokens is not None else input_tokens
            session.last_output_tokens = last_output_tokens if last_output_tokens is not None else output_tokens
            session.last_total_tokens = last_total_tokens if last_total_tokens is not None else total_tokens
            session.last_cost = cost
            session.last_model = model
            session.last_usage_at = datetime.utcnow()
        await self.session.commit()
        return usage

    async def list_messages(self, session_id: str) -> List[Message]:
        result = await self.session.execute(
            select(Message).where(Message.session_id == session_id).order_by(Message.created_at.asc())
        )
        return list(result.scalars().all())

    async def list_recent_sessions(self, limit: int = 10, status: str | None = "active") -> List[tuple]:
        last_active_subq = (
            select(Message.session_id, func.max(Message.created_at).label("last_active_at"))
            .group_by(Message.session_id)
            .subquery()
        )
        stmt = (
            select(Session, User.transport_user_id, last_active_subq.c.last_active_at)
            .join(User, User.id == Session.user_id)
            .outerjoin(last_active_subq, Session.id == last_active_subq.c.session_id)
            .order_by(Session.created_at.desc())
            .limit(limit)
        )
        if status:
            stmt = stmt.where(Session.status == status)
        result = await self.session.execute(stmt)
        return list(result.all())

    async def list_sessions(self, limit: int = 50, status: str | None = None) -> List[tuple]:
        last_active_subq = (
            select(Message.session_id, func.max(Message.created_at).label("last_active_at"))
            .group_by(Message.session_id)
            .subquery()
        )
        stmt = (
            select(Session, User.transport_user_id, last_active_subq.c.last_active_at)
            .join(User, User.id == Session.user_id)
            .outerjoin(last_active_subq, Session.id == last_active_subq.c.session_id)
            .order_by(Session.created_at.desc())
            .limit(limit)
        )
        if status:
            stmt = stmt.where(Session.status == status)
        result = await self.session.execute(stmt)
        return list(result.all())

    async def list_cost_trajectory(self, days: int = 7) -> list[tuple[datetime, float]]:
        if days < 1:
            return []
        start = datetime.utcnow().date() - timedelta(days=days - 1)
        stmt = (
            select(
                func.date_trunc("day", LlmUsage.created_at).label("day"),
                func.coalesce(func.sum(LlmUsage.cost), 0.0).label("cost"),
            )
            .where(LlmUsage.created_at >= start)
            .group_by("day")
            .order_by("day")
        )
        result = await self.session.execute(stmt)
        return list(result.all())

    async def list_pending_tool_runs(self, limit: int = 10) -> List[tuple]:
        stmt = (
            select(ToolRun, User.transport_user_id)
            .join(Session, Session.id == ToolRun.session_id)
            .join(User, User.id == Session.user_id)
            .where(ToolRun.status == "pending")
            .order_by(ToolRun.created_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.all())

    async def list_tool_runs(self, limit: int = 50, status: str | None = None) -> List[tuple]:
        stmt = (
            select(ToolRun, User.transport_user_id)
            .join(Session, Session.id == ToolRun.session_id)
            .join(User, User.id == Session.user_id)
            .order_by(ToolRun.created_at.desc())
            .limit(limit)
        )
        if status:
            stmt = stmt.where(ToolRun.status == status)
        result = await self.session.execute(stmt)
        return list(result.all())

    async def list_tool_runs_by_session(self, session_id: str) -> List[ToolRun]:
        result = await self.session.execute(
            select(ToolRun).where(ToolRun.session_id == session_id).order_by(ToolRun.created_at.asc())
        )
        return list(result.scalars().all())

    async def upsert_channel(
        self,
        transport_channel_id: str,
        name: str,
        kind: str,
        guild_id: str | None = None,
        guild_name: str | None = None,
        meta: dict | None = None,
    ) -> Channel:
        result = await self.session.execute(
            select(Channel).where(Channel.transport_channel_id == transport_channel_id)
        )
        channel = result.scalar_one_or_none()
        if channel is None:
            channel = Channel(
                id=str(uuid.uuid4()),
                transport_channel_id=transport_channel_id,
                name=name,
                kind=kind,
                guild_id=guild_id,
                guild_name=guild_name,
                meta=meta or {},
                updated_at=datetime.utcnow(),
            )
            self.session.add(channel)
        else:
            channel.name = name
            channel.kind = kind
            channel.guild_id = guild_id
            channel.guild_name = guild_name
            channel.meta = meta or channel.meta or {}
            channel.updated_at = datetime.utcnow()
        await self.session.commit()
        return channel

    async def list_channels(self, limit: int = 200) -> List[Channel]:
        result = await self.session.execute(select(Channel).order_by(Channel.name.asc()).limit(limit))
        return list(result.scalars().all())

    async def list_users(self, limit: int = 200) -> List[User]:
        result = await self.session.execute(select(User).order_by(User.transport_user_id.asc()).limit(limit))
        return list(result.scalars().all())

    async def list_approved_users(self) -> List[User]:
        result = await self.session.execute(select(User).where(User.approved == True))  # noqa: E712
        return list(result.scalars().all())

    async def create_tool_run(
        self,
        session_id: str,
        tool_name: str,
        status: str,
        input_payload: dict,
        output_payload: dict | None = None,
        approved_by: str | None = None,
    ) -> ToolRun:
        tool_run = ToolRun(
            id=str(uuid.uuid4()),
            session_id=session_id,
            tool_name=tool_name,
            status=status,
            input=input_payload,
            output=output_payload or {},
            approved_by=approved_by,
        )
        self.session.add(tool_run)
        await self.session.commit()
        return tool_run

    async def approve_tool_run(self, tool_run_id: str, approved_by: str) -> Optional[ToolRun]:
        result = await self.session.execute(select(ToolRun).where(ToolRun.id == tool_run_id))
        tool_run = result.scalar_one_or_none()
        if tool_run is None:
            return None
        tool_run.status = "approved"
        tool_run.approved_by = approved_by
        await self.session.commit()
        return tool_run

    async def deny_tool_run(self, tool_run_id: str, decided_by: str) -> Optional[ToolRun]:
        result = await self.session.execute(select(ToolRun).where(ToolRun.id == tool_run_id))
        tool_run = result.scalar_one_or_none()
        if tool_run is None:
            return None
        tool_run.status = "denied"
        tool_run.approved_by = decided_by
        await self.session.commit()
        return tool_run

    async def complete_tool_run(self, tool_run_id: str, status: str, output_payload: dict | None = None) -> Optional[ToolRun]:
        result = await self.session.execute(select(ToolRun).where(ToolRun.id == tool_run_id))
        tool_run = result.scalar_one_or_none()
        if tool_run is None:
            return None
        tool_run.status = status
        tool_run.output = output_payload or {}
        await self.session.commit()
        return tool_run

    async def list_skills(self) -> List[Skill]:
        result = await self.session.execute(select(Skill))
        return list(result.scalars().all())

    async def upsert_skill(self, name: str, path: str, description: str, metadata: dict | None = None) -> Skill:
        result = await self.session.execute(select(Skill).where(Skill.name == name))
        skill = result.scalar_one_or_none()
        if skill is None:
            skill = Skill(name=name, path=path, description=description, meta=metadata or {})
            self.session.add(skill)
        else:
            skill.path = path
            skill.description = description
            skill.meta = metadata or {}
        await self.session.commit()
        return skill

    async def add_memory(self, user_id: str, summary: str, embedding: list, tags: list | None = None) -> MemoryEntry:
        entry = MemoryEntry(
            id=str(uuid.uuid4()),
            user_id=user_id,
            summary=summary,
            embedding=embedding,
            tags=tags or [],
        )
        self.session.add(entry)
        await self.session.commit()
        return entry

    async def list_memory_entries(self, user_id: str) -> List[MemoryEntry]:
        result = await self.session.execute(select(MemoryEntry).where(MemoryEntry.user_id == user_id))
        return list(result.scalars().all())

    async def delete_memory_by_tag(self, user_id: str, tag: str) -> int:
        entries = await self.list_memory_entries(user_id)
        to_delete = [entry for entry in entries if tag in (entry.tags or [])]
        for entry in to_delete:
            await self.session.delete(entry)
        await self.session.commit()
        return len(to_delete)

    async def delete_memory(self, user_id: str) -> int:
        result = await self.session.execute(select(MemoryEntry).where(MemoryEntry.user_id == user_id))
        entries = list(result.scalars().all())
        for entry in entries:
            await self.session.delete(entry)
        await self.session.commit()
        return len(entries)

    async def add_artifact(self, session_id: str, path: str, mime_type: str) -> Artifact:
        artifact = Artifact(id=str(uuid.uuid4()), session_id=session_id, path=path, mime_type=mime_type)
        self.session.add(artifact)
        await self.session.commit()
        return artifact

    async def get_artifact(self, artifact_id: str) -> Optional[Artifact]:
        result = await self.session.execute(select(Artifact).where(Artifact.id == artifact_id))
        return result.scalar_one_or_none()

    async def create_scheduled_job(
        self,
        user_id: str,
        channel_id: str,
        name: str,
        prompt: str,
        cron: str,
        timezone: str,
        enabled: bool = True,
        schedule_type: str = "cron",
    ) -> ScheduledJob:
        job = ScheduledJob(
            id=str(uuid.uuid4()),
            user_id=user_id,
            channel_id=channel_id,
            name=name,
            prompt=prompt,
            schedule_expr=cron,
            timezone=timezone,
            schedule_type=schedule_type,
            enabled=enabled,
        )
        self.session.add(job)
        await self.session.commit()
        return job

    async def update_scheduled_job(self, job_id: str, **fields) -> Optional[ScheduledJob]:
        result = await self.session.execute(select(ScheduledJob).where(ScheduledJob.id == job_id))
        job = result.scalar_one_or_none()
        if job is None:
            return None
        for key, value in fields.items():
            if hasattr(job, key) and value is not None:
                if isinstance(value, datetime) and value.tzinfo is not None:
                    value = value.replace(tzinfo=None)
                setattr(job, key, value)
        job.updated_at = datetime.utcnow()
        await self.session.commit()
        return job

    async def delete_scheduled_job(self, job_id: str) -> bool:
        result = await self.session.execute(select(ScheduledJob).where(ScheduledJob.id == job_id))
        job = result.scalar_one_or_none()
        if job is None:
            return False
        await self.session.delete(job)
        await self.session.commit()
        return True

    async def list_scheduled_jobs(self, user_id: str) -> List[ScheduledJob]:
        result = await self.session.execute(select(ScheduledJob).where(ScheduledJob.user_id == user_id))
        return list(result.scalars().all())

    async def list_scheduled_jobs_all(self) -> List[ScheduledJob]:
        result = await self.session.execute(select(ScheduledJob))
        return list(result.scalars().all())

    async def get_scheduled_job(self, job_id: str) -> Optional[ScheduledJob]:
        result = await self.session.execute(select(ScheduledJob).where(ScheduledJob.id == job_id))
        return result.scalar_one_or_none()

    async def create_scheduled_run(self, job_id: str, status: str) -> ScheduledRun:
        run = ScheduledRun(id=str(uuid.uuid4()), job_id=job_id, status=status, created_at=datetime.utcnow())
        self.session.add(run)
        await self.session.commit()
        return run

    async def update_scheduled_run(self, run_id: str, **fields) -> Optional[ScheduledRun]:
        result = await self.session.execute(select(ScheduledRun).where(ScheduledRun.id == run_id))
        run = result.scalar_one_or_none()
        if run is None:
            return None
        for key, value in fields.items():
            if hasattr(run, key) and value is not None:
                if isinstance(value, datetime) and value.tzinfo is not None:
                    value = value.replace(tzinfo=None)
                setattr(run, key, value)
        await self.session.commit()
        return run

    async def list_secrets(self, user_id: str) -> List[Secret]:
        result = await self.session.execute(select(Secret).where(Secret.user_id == user_id))
        return list(result.scalars().all())

    async def get_secret(self, user_id: str, name: str) -> Optional[Secret]:
        result = await self.session.execute(
            select(Secret).where(Secret.user_id == user_id, Secret.name == name)
        )
        return result.scalar_one_or_none()

    async def create_secret(self, user_id: str, name: str, value_encrypted: str) -> Optional[Secret]:
        existing = await self.get_secret(user_id, name)
        if existing is not None:
            return None
        secret = Secret(
            id=str(uuid.uuid4()),
            user_id=user_id,
            name=name,
            value_encrypted=value_encrypted,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        self.session.add(secret)
        await self.session.commit()
        return secret

    async def upsert_secret(self, user_id: str, name: str, value_encrypted: str) -> Secret:
        secret = await self.get_secret(user_id, name)
        if secret is None:
            secret = Secret(
                id=str(uuid.uuid4()),
                user_id=user_id,
                name=name,
                value_encrypted=value_encrypted,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
            self.session.add(secret)
        else:
            secret.value_encrypted = value_encrypted
            secret.updated_at = datetime.utcnow()
        await self.session.commit()
        return secret

    async def delete_secret(self, user_id: str, name: str) -> bool:
        secret = await self.get_secret(user_id, name)
        if secret is None:
            return False
        await self.session.delete(secret)
        await self.session.commit()
        return True

    async def touch_secret(self, secret: Secret) -> Secret:
        secret.last_used_at = datetime.utcnow()
        await self.session.commit()
        return secret

    async def create_sandbox_task(
        self,
        user_id: str,
        session_id: str,
        pid: int,
        command: str,
        status: str = "running",
    ) -> SandboxTask:
        task = SandboxTask(
            id=str(uuid.uuid4()),
            user_id=user_id,
            session_id=session_id,
            pid=pid,
            command=command,
            status=status,
        )
        self.session.add(task)
        await self.session.commit()
        return task

    async def list_active_sandbox_tasks(self, user_id: str) -> List[SandboxTask]:
        result = await self.session.execute(
            select(SandboxTask).where(SandboxTask.user_id == user_id, SandboxTask.status == "running")
        )
        return list(result.scalars().all())

    async def update_sandbox_task(self, task_id: str, **fields) -> Optional[SandboxTask]:
        result = await self.session.execute(select(SandboxTask).where(SandboxTask.id == task_id))
        task = result.scalar_one_or_none()
        if task is None:
            return None
        for key, value in fields.items():
            if hasattr(task, key) and value is not None:
                setattr(task, key, value)
        task.updated_at = datetime.utcnow()
        await self.session.commit()
        return task
