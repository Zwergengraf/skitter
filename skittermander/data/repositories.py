from __future__ import annotations

import uuid
from datetime import datetime
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import (
    Artifact,
    MemoryEntry,
    Message,
    ScheduledJob,
    ScheduledRun,
    Session,
    Skill,
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
        user = User(id=str(uuid.uuid4()), transport_user_id=transport_user_id, meta={})
        self.session.add(user)
        await self.session.commit()
        return user

    async def get_user_by_id(self, user_id: str) -> Optional[User]:
        result = await self.session.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()

    async def create_session(self, user_id: str, status: str = "active") -> Session:
        session = Session(id=str(uuid.uuid4()), user_id=user_id, status=status)
        self.session.add(session)
        await self.session.commit()
        return session

    async def get_session(self, session_id: str) -> Optional[Session]:
        result = await self.session.execute(select(Session).where(Session.id == session_id))
        return result.scalar_one_or_none()

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

    async def list_messages(self, session_id: str) -> List[Message]:
        result = await self.session.execute(
            select(Message).where(Message.session_id == session_id).order_by(Message.created_at.asc())
        )
        return list(result.scalars().all())

    async def create_tool_run(
        self,
        session_id: str,
        tool_name: str,
        status: str,
        input_payload: dict,
        output_payload: dict | None = None,
    ) -> ToolRun:
        tool_run = ToolRun(
            id=str(uuid.uuid4()),
            session_id=session_id,
            tool_name=tool_name,
            status=status,
            input=input_payload,
            output=output_payload or {},
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
