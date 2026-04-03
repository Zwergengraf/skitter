from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, List, Optional

from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from .models import (
    AgentJob,
    AuthToken,
    Channel,
    Executor,
    ExecutorToken,
    LlmUsage,
    MemoryEntry,
    Message,
    PairCode,
    RunTrace,
    RunTraceEvent,
    ScheduledJob,
    ScheduledRun,
    Session,
    Secret,
    ToolRun,
    UserPrompt,
    User,
)


class Repository:
    PENDING_USER_TTL_MINUTES = 15

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    @staticmethod
    def _utcnow() -> datetime:
        return datetime.now(UTC)

    async def get_or_create_user(self, transport_user_id: str) -> User:
        result = await self.session.execute(select(User).where(User.transport_user_id == transport_user_id))
        user = result.scalar_one_or_none()
        if user:
            if not user.approved:
                cutoff = self._utcnow() - timedelta(minutes=self.PENDING_USER_TTL_MINUTES)
                if user.created_at < cutoff:
                    await self.session.delete(user)
                    await self.session.commit()
                else:
                    return user
            else:
                return user
        user = User(id=str(uuid.uuid4()), transport_user_id=transport_user_id, meta={}, approved=False)
        self.session.add(user)
        await self.session.commit()
        return user

    async def get_or_create_local_primary_user(self, display_name: str | None = None) -> User:
        user = await self.get_or_create_user("local.primary")
        if display_name:
            user.display_name = display_name
            meta = dict(user.meta or {})
            meta.setdefault("display_name", display_name)
            user.meta = meta
        if not user.approved:
            user.approved = True
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
            user.display_name = display_name
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

    async def set_user_default_executor(self, user_id: str, executor_id: str | None) -> Optional[User]:
        updates = {"default_executor_id": executor_id or ""}
        return await self.set_user_meta(user_id, updates)

    async def get_user_default_executor_id(self, user_id: str) -> str | None:
        user = await self.get_user_by_id(user_id)
        if user is None:
            return None
        meta = dict(user.meta or {})
        raw = str(meta.get("default_executor_id") or "").strip()
        return raw or None

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

    async def create_session(
        self,
        user_id: str,
        status: str = "active",
        model: str | None = None,
        origin: str = "discord",
        scope_type: str = "private",
        scope_id: str | None = None,
    ) -> Session:
        if not scope_id:
            if scope_type == "private":
                scope_id = f"private:{user_id}"
            else:
                scope_id = f"{scope_type}:{user_id}"
        # Enforce a single active session per scope.
        if status == "active":
            existing_result = await self.session.execute(
                select(Session).where(
                    Session.status == "active",
                    Session.scope_type == scope_type,
                    Session.scope_id == scope_id,
                )
            )
            for existing in existing_result.scalars().all():
                existing.status = "ended"
        session = Session(
            id=str(uuid.uuid4()),
            user_id=user_id,
            status=status,
            model=model,
            origin=origin,
            scope_type=scope_type,
            scope_id=scope_id,
        )
        self.session.add(session)
        await self.session.commit()
        return session

    async def get_session(self, session_id: str) -> Optional[Session]:
        result = await self.session.execute(select(Session).where(Session.id == session_id))
        return result.scalar_one_or_none()

    async def get_message(self, message_id: str) -> Optional[Message]:
        result = await self.session.execute(select(Message).where(Message.id == message_id))
        return result.scalar_one_or_none()

    async def set_session_model(self, session_id: str, model: str) -> Optional[Session]:
        result = await self.session.execute(select(Session).where(Session.id == session_id))
        session = result.scalar_one_or_none()
        if session is None:
            return None
        session.model = model
        session.last_model = model
        await self.session.commit()
        return session

    async def set_session_context_summary(
        self,
        session_id: str,
        summary: str,
        checkpoint: datetime | None,
        input_tokens: int | None,
    ) -> Optional[Session]:
        result = await self.session.execute(select(Session).where(Session.id == session_id))
        session = result.scalar_one_or_none()
        if session is None:
            return None
        session.context_summary = summary
        session.context_summary_checkpoint = checkpoint
        session.context_summary_input_tokens = input_tokens
        await self.session.commit()
        return session

    async def begin_session_memory_update(self, session_id: str, *, path: str) -> Session | None:
        result = await self.session.execute(select(Session).where(Session.id == session_id))
        session = result.scalar_one_or_none()
        if session is None:
            return None
        session.session_memory_status = "running"
        session.session_memory_last_error = None
        session.session_memory_path = path
        await self.session.commit()
        return session

    async def complete_session_memory_update(
        self,
        session_id: str,
        *,
        path: str,
        checkpoint: datetime | None,
        input_tokens: int | None,
        message_id: str | None,
    ) -> Session | None:
        result = await self.session.execute(select(Session).where(Session.id == session_id))
        session = result.scalar_one_or_none()
        if session is None:
            return None
        session.session_memory_status = "completed"
        session.session_memory_last_error = None
        session.session_memory_path = path
        session.session_memory_checkpoint = checkpoint
        session.session_memory_input_tokens = input_tokens
        session.session_memory_message_id = message_id
        session.session_memory_updated_at = self._utcnow()
        await self.session.commit()
        return session

    async def fail_session_memory_update(self, session_id: str, *, error: str) -> Session | None:
        result = await self.session.execute(select(Session).where(Session.id == session_id))
        session = result.scalar_one_or_none()
        if session is None:
            return None
        session.session_memory_status = "failed"
        session.session_memory_last_error = error
        await self.session.commit()
        return session

    async def queue_session_summary(self, session_id: str) -> Session | None:
        result = await self.session.execute(select(Session).where(Session.id == session_id))
        session = result.scalar_one_or_none()
        if session is None:
            return None
        session.summary_status = "pending"
        session.summary_attempts = 0
        session.summary_next_retry_at = None
        session.summary_last_error = None
        session.summary_path = None
        session.summary_completed_at = None
        await self.session.commit()
        return session

    async def claim_next_session_summary(self) -> Session | None:
        now = self._utcnow()
        stmt = (
            select(Session)
            .where(
                Session.summary_status == "pending",
                (Session.summary_next_retry_at.is_(None)) | (Session.summary_next_retry_at <= now),
            )
            .order_by(Session.created_at.asc())
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        result = await self.session.execute(stmt)
        session = result.scalars().first()
        if session is None:
            return None
        session.summary_status = "running"
        session.summary_attempts = int(session.summary_attempts or 0) + 1
        session.summary_next_retry_at = None
        await self.session.commit()
        return session

    async def complete_session_summary(self, session_id: str, *, summary_path: str) -> Session | None:
        result = await self.session.execute(select(Session).where(Session.id == session_id))
        session = result.scalar_one_or_none()
        if session is None:
            return None
        session.summary_status = "completed"
        session.summary_next_retry_at = None
        session.summary_last_error = None
        session.summary_path = summary_path
        session.summary_completed_at = self._utcnow()
        await self.session.commit()
        return session

    async def fail_session_summary(
        self,
        session_id: str,
        *,
        error: str,
        retry_at: datetime | None,
        terminal: bool,
    ) -> Session | None:
        result = await self.session.execute(select(Session).where(Session.id == session_id))
        session = result.scalar_one_or_none()
        if session is None:
            return None
        session.summary_status = "failed" if terminal else "pending"
        session.summary_last_error = error
        session.summary_next_retry_at = None if terminal else retry_at
        session.summary_completed_at = None
        await self.session.commit()
        return session

    async def get_active_session_by_scope(self, scope_type: str, scope_id: str) -> Optional[Session]:
        result = await self.session.execute(
            select(Session)
            .where(
                Session.scope_type == scope_type,
                Session.scope_id == scope_id,
                Session.status == "active",
            )
            .order_by(Session.created_at.desc())
        )
        return result.scalars().first()

    async def get_latest_session_by_scope(
        self,
        scope_type: str,
        scope_id: str,
        status: str | None = None,
    ) -> Optional[Session]:
        stmt = select(Session).where(Session.scope_type == scope_type, Session.scope_id == scope_id)
        if status:
            stmt = stmt.where(Session.status == status)
        result = await self.session.execute(stmt.order_by(Session.created_at.desc()))
        return result.scalars().first()

    async def get_active_session(self, user_id: str, origin: str | None = None) -> Optional[Session]:
        if origin == "heartbeat":
            result = await self.session.execute(
                select(Session)
                .where(Session.user_id == user_id, Session.status == "heartbeat")
                .order_by(Session.created_at.desc())
            )
            return result.scalars().first()
        if origin == "scheduler":
            result = await self.session.execute(
                select(Session)
                .where(Session.user_id == user_id, Session.status == "scheduled")
                .order_by(Session.created_at.desc())
            )
            return result.scalars().first()
        return await self.get_active_session_by_scope("private", f"private:{user_id}")

    async def get_latest_session_by_status(self, user_id: str, status: str) -> Optional[Session]:
        result = await self.session.execute(
            select(Session)
            .where(Session.user_id == user_id, Session.status == status)
            .order_by(Session.created_at.desc())
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
            session.last_usage_at = self._utcnow()
        await self.session.commit()
        return usage

    async def list_messages(self, session_id: str) -> List[Message]:
        result = await self.session.execute(
            select(Message).where(Message.session_id == session_id).order_by(Message.created_at.asc())
        )
        return list(result.scalars().all())

    async def prune_messages_keep_latest(self, session_id: str, keep: int) -> int:
        if keep < 0:
            keep = 0
        result = await self.session.execute(
            select(Message).where(Message.session_id == session_id).order_by(Message.created_at.desc(), Message.id.desc())
        )
        messages = list(result.scalars().all())
        to_delete = messages[keep:]
        for message in to_delete:
            await self.session.delete(message)
        if to_delete:
            await self.session.commit()
        return len(to_delete)

    async def get_user_prompt(self, prompt_id: str) -> UserPrompt | None:
        result = await self.session.execute(select(UserPrompt).where(UserPrompt.id == prompt_id))
        return result.scalar_one_or_none()

    async def get_pending_user_prompt_for_session(self, session_id: str) -> UserPrompt | None:
        result = await self.session.execute(
            select(UserPrompt)
            .where(
                UserPrompt.session_id == session_id,
                UserPrompt.status == "pending",
            )
            .order_by(UserPrompt.created_at.desc())
        )
        return result.scalars().first()

    async def list_pending_user_prompts(
        self,
        *,
        session_id: str | None = None,
        user_id: str | None = None,
        limit: int = 50,
    ) -> List[UserPrompt]:
        stmt = (
            select(UserPrompt)
            .join(Session, Session.id == UserPrompt.session_id)
            .where(UserPrompt.status == "pending")
            .order_by(UserPrompt.created_at.asc())
            .limit(limit)
        )
        if session_id:
            stmt = stmt.where(UserPrompt.session_id == session_id)
        if user_id:
            stmt = stmt.where(Session.user_id == user_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_user_prompts_for_session(self, session_id: str) -> List[UserPrompt]:
        result = await self.session.execute(
            select(UserPrompt)
            .where(UserPrompt.session_id == session_id)
            .order_by(UserPrompt.created_at.asc(), UserPrompt.id.asc())
        )
        return list(result.scalars().all())

    async def create_user_prompt(
        self,
        *,
        session_id: str,
        question: str,
        choices: list[str] | None = None,
        allow_free_text: bool = True,
        run_id: str | None = None,
        message_id: str | None = None,
    ) -> UserPrompt:
        existing = await self.get_pending_user_prompt_for_session(session_id)
        if existing is not None:
            return existing
        prompt = UserPrompt(
            id=str(uuid.uuid4()),
            session_id=session_id,
            run_id=run_id,
            message_id=message_id,
            question=question,
            choices=choices or [],
            allow_free_text=allow_free_text,
            status="pending",
            created_at=self._utcnow(),
        )
        self.session.add(prompt)
        await self.session.commit()
        if run_id:
            await self.append_run_trace_event(
                run_id=run_id,
                session_id=session_id,
                event_type="user_prompt_created",
                payload={
                    "prompt_id": prompt.id,
                    "question": question,
                    "choices": prompt.choices or [],
                    "allow_free_text": bool(prompt.allow_free_text),
                },
            )
        return prompt

    async def answer_user_prompt(
        self,
        prompt_id: str,
        *,
        answer: str,
        answered_by: str | None = None,
    ) -> UserPrompt | None:
        result = await self.session.execute(select(UserPrompt).where(UserPrompt.id == prompt_id))
        prompt = result.scalar_one_or_none()
        if prompt is None:
            return None
        prompt.status = "answered"
        prompt.answer = answer
        prompt.answered_by = answered_by
        prompt.answered_at = self._utcnow()
        await self.session.commit()
        if prompt.run_id:
            await self.append_run_trace_event(
                run_id=prompt.run_id,
                session_id=prompt.session_id,
                event_type="user_prompt_answered",
                payload={
                    "prompt_id": prompt.id,
                    "answer": answer,
                    "answered_by": answered_by,
                },
            )
        return prompt

    async def answer_pending_user_prompt_for_session(
        self,
        session_id: str,
        *,
        answer: str,
        answered_by: str | None = None,
    ) -> UserPrompt | None:
        prompt = await self.get_pending_user_prompt_for_session(session_id)
        if prompt is None:
            return None
        return await self.answer_user_prompt(prompt.id, answer=answer, answered_by=answered_by)

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
        start = self._utcnow().date() - timedelta(days=days - 1)
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

    async def list_tool_runs_for_user(self, user_id: str, limit: int = 50, status: str | None = None) -> List[tuple]:
        stmt = (
            select(ToolRun, User.transport_user_id)
            .join(Session, Session.id == ToolRun.session_id)
            .join(User, User.id == Session.user_id)
            .where(Session.user_id == user_id)
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

    async def list_tool_runs_by_run(self, run_id: str) -> List[ToolRun]:
        result = await self.session.execute(
            select(ToolRun).where(ToolRun.run_id == run_id).order_by(ToolRun.created_at.asc())
        )
        return list(result.scalars().all())

    async def create_run_trace(
        self,
        *,
        run_id: str,
        session_id: str,
        user_id: str,
        message_id: str,
        origin: str,
        model: str | None,
        input_text: str,
        status: str = "running",
    ) -> RunTrace:
        trace = RunTrace(
            id=run_id,
            session_id=session_id,
            user_id=user_id,
            message_id=message_id,
            origin=origin,
            status=status,
            model=model,
            input_text=input_text,
            started_at=self._utcnow(),
        )
        self.session.add(trace)
        await self.session.commit()
        return trace

    async def get_run_trace(self, run_id: str) -> RunTrace | None:
        result = await self.session.execute(select(RunTrace).where(RunTrace.id == run_id))
        return result.scalar_one_or_none()

    async def list_run_traces(
        self,
        limit: int = 100,
        status: str | None = None,
        user_id: str | None = None,
        session_id: str | None = None,
    ) -> List[RunTrace]:
        stmt = select(RunTrace).order_by(RunTrace.started_at.desc()).limit(limit)
        if status:
            stmt = stmt.where(RunTrace.status == status)
        if user_id:
            stmt = stmt.where(RunTrace.user_id == user_id)
        if session_id:
            stmt = stmt.where(RunTrace.session_id == session_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def update_run_trace(self, run_id: str, **fields) -> RunTrace | None:
        result = await self.session.execute(select(RunTrace).where(RunTrace.id == run_id))
        trace = result.scalar_one_or_none()
        if trace is None:
            return None
        for key, value in fields.items():
            if hasattr(trace, key) and value is not None:
                setattr(trace, key, value)
        await self.session.commit()
        return trace

    async def increment_run_trace_tool_calls(self, run_id: str, by: int = 1) -> RunTrace | None:
        result = await self.session.execute(select(RunTrace).where(RunTrace.id == run_id))
        trace = result.scalar_one_or_none()
        if trace is None:
            return None
        trace.tool_calls = max(0, int(trace.tool_calls or 0) + int(by))
        await self.session.commit()
        return trace

    async def append_run_trace_event(
        self,
        *,
        run_id: str,
        session_id: str,
        event_type: str,
        payload: dict | None = None,
    ) -> RunTraceEvent:
        event = RunTraceEvent(
            id=str(uuid.uuid4()),
            run_id=run_id,
            session_id=session_id,
            event_type=event_type,
            payload=payload or {},
            created_at=self._utcnow(),
        )
        self.session.add(event)
        await self.session.commit()
        return event

    async def list_run_trace_events(self, run_id: str, limit: int = 1000) -> List[RunTraceEvent]:
        stmt = (
            select(RunTraceEvent)
            .where(RunTraceEvent.run_id == run_id)
            .order_by(RunTraceEvent.created_at.asc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_reasoning_by_run_ids(self, run_ids: list[str]) -> dict[str, list[str]]:
        unique_ids = [str(run_id) for run_id in dict.fromkeys(run_ids or []) if str(run_id).strip()]
        if not unique_ids:
            return {}
        stmt = (
            select(RunTraceEvent)
            .where(
                RunTraceEvent.run_id.in_(unique_ids),
                RunTraceEvent.event_type == "reasoning",
            )
            .order_by(RunTraceEvent.created_at.asc())
        )
        result = await self.session.execute(stmt)
        reasoning_by_run: dict[str, list[str]] = {run_id: [] for run_id in unique_ids}
        for event in result.scalars().all():
            payload = event.payload or {}
            raw_chunks = payload.get("chunks") if isinstance(payload, dict) else None
            if isinstance(raw_chunks, str):
                chunks = [raw_chunks]
            elif isinstance(raw_chunks, list):
                chunks = [str(item).strip() for item in raw_chunks if str(item).strip()]
            else:
                chunks = []
            if not chunks:
                continue
            bucket = reasoning_by_run.setdefault(event.run_id, [])
            seen = set(bucket)
            for chunk in chunks:
                if chunk in seen:
                    continue
                bucket.append(chunk)
                seen.add(chunk)
        return {key: value for key, value in reasoning_by_run.items() if value}

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
                updated_at=self._utcnow(),
            )
            self.session.add(channel)
        else:
            channel.name = name
            channel.kind = kind
            channel.guild_id = guild_id
            channel.guild_name = guild_name
            channel.meta = meta or channel.meta or {}
            channel.updated_at = self._utcnow()
        await self.session.commit()
        return channel

    async def list_channels(self, limit: int = 200) -> List[Channel]:
        result = await self.session.execute(select(Channel).order_by(Channel.name.asc()).limit(limit))
        return list(result.scalars().all())

    async def list_users(self, limit: int = 200) -> List[User]:
        result = await self.session.execute(select(User).order_by(User.transport_user_id.asc()).limit(limit))
        return list(result.scalars().all())

    async def update_user_display_name(self, user_id: str, display_name: str | None) -> Optional[User]:
        result = await self.session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if user is None:
            return None
        cleaned = (display_name or "").strip() or None
        user.display_name = cleaned
        meta = dict(user.meta or {})
        if cleaned:
            meta["display_name"] = cleaned
        elif "display_name" in meta:
            meta.pop("display_name", None)
        user.meta = meta
        await self.session.commit()
        return user

    async def delete_pending_user(self, user_id: str) -> bool:
        result = await self.session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if user is None or user.approved:
            return False
        await self.session.delete(user)
        await self.session.commit()
        return True

    async def delete_stale_pending_users(self, older_than_minutes: int) -> int:
        cutoff = self._utcnow() - timedelta(minutes=max(1, int(older_than_minutes)))
        result = await self.session.execute(
            select(User).where(
                User.approved == False,  # noqa: E712
                User.created_at < cutoff,
            )
        )
        stale_users = list(result.scalars().all())
        if not stale_users:
            return 0
        for user in stale_users:
            await self.session.delete(user)
        await self.session.commit()
        return len(stale_users)

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
        run_id: str | None = None,
        message_id: str | None = None,
        executor_id: str | None = None,
    ) -> ToolRun:
        tool_run = ToolRun(
            id=str(uuid.uuid4()),
            session_id=session_id,
            executor_id=executor_id,
            run_id=run_id,
            message_id=message_id,
            tool_name=tool_name,
            status=status,
            input=input_payload,
            output=output_payload or {},
            approved_by=approved_by,
        )
        self.session.add(tool_run)
        await self.session.commit()
        if run_id:
            await self.increment_run_trace_tool_calls(run_id, by=1)
            await self.append_run_trace_event(
                run_id=run_id,
                session_id=session_id,
                event_type="tool_created",
                payload={
                    "tool_run_id": tool_run.id,
                    "tool": tool_name,
                    "status": status,
                    "input": input_payload,
                },
            )
        return tool_run

    async def get_tool_run(self, tool_run_id: str) -> Optional[ToolRun]:
        result = await self.session.execute(select(ToolRun).where(ToolRun.id == tool_run_id))
        return result.scalar_one_or_none()

    async def approve_tool_run(self, tool_run_id: str, approved_by: str) -> Optional[ToolRun]:
        result = await self.session.execute(select(ToolRun).where(ToolRun.id == tool_run_id))
        tool_run = result.scalar_one_or_none()
        if tool_run is None:
            return None
        tool_run.status = "approved"
        tool_run.approved_by = approved_by
        await self.session.commit()
        if tool_run.run_id:
            await self.append_run_trace_event(
                run_id=tool_run.run_id,
                session_id=tool_run.session_id,
                event_type="tool_approved",
                payload={"tool_run_id": tool_run.id, "approved_by": approved_by},
            )
        return tool_run

    async def deny_tool_run(self, tool_run_id: str, decided_by: str) -> Optional[ToolRun]:
        result = await self.session.execute(select(ToolRun).where(ToolRun.id == tool_run_id))
        tool_run = result.scalar_one_or_none()
        if tool_run is None:
            return None
        tool_run.status = "denied"
        tool_run.approved_by = decided_by
        await self.session.commit()
        if tool_run.run_id:
            await self.append_run_trace_event(
                run_id=tool_run.run_id,
                session_id=tool_run.session_id,
                event_type="tool_denied",
                payload={"tool_run_id": tool_run.id, "denied_by": decided_by},
            )
        return tool_run

    async def complete_tool_run(
        self,
        tool_run_id: str,
        status: str,
        output_payload: dict | None = None,
        executor_id: str | None = None,
    ) -> Optional[ToolRun]:
        result = await self.session.execute(select(ToolRun).where(ToolRun.id == tool_run_id))
        tool_run = result.scalar_one_or_none()
        if tool_run is None:
            return None
        tool_run.status = status
        tool_run.output = output_payload or {}
        if executor_id is not None:
            tool_run.executor_id = executor_id
        await self.session.commit()
        if tool_run.run_id:
            await self.append_run_trace_event(
                run_id=tool_run.run_id,
                session_id=tool_run.session_id,
                event_type="tool_completed",
                payload={
                    "tool_run_id": tool_run.id,
                    "status": status,
                    "output": output_payload or {},
                    "executor_id": tool_run.executor_id,
                },
            )
        return tool_run

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

    async def search_memory_entries_pgvector(
        self,
        user_id: str,
        query_embedding: list[float],
        top_k: int,
        max_distance: float,
    ) -> list[dict[str, Any]]:
        if not query_embedding:
            return []
        limit = max(1, min(int(top_k), 10))
        query_vector = "[" + ",".join(f"{float(value):.12g}" for value in query_embedding) + "]"
        stmt = text(
            """
            WITH q AS (
              SELECT CAST(:query_vector AS vector) AS v
            ),
            ranked AS (
              SELECT
                id,
                user_id,
                embedding,
                summary,
                tags,
                created_at,
                (embedding <=> q.v) AS distance
              FROM memory_entries, q
              WHERE user_id = :user_id
                AND embedding IS NOT NULL
            )
            SELECT
              id,
              user_id,
              embedding,
              summary,
              tags,
              created_at,
              distance,
              (1 - distance) AS score
            FROM ranked
            WHERE distance <= :max_distance
            ORDER BY distance ASC
            LIMIT :limit
            """
        )
        result = await self.session.execute(
            stmt,
            {
                "user_id": user_id,
                "query_vector": query_vector,
                "max_distance": float(max_distance),
                "limit": limit,
            },
        )
        return [dict(row) for row in result.mappings().all()]

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

    async def create_scheduled_job(
        self,
        user_id: str,
        channel_id: str,
        name: str,
        prompt: str,
        cron: str,
        timezone: str,
        model: str,
        enabled: bool = True,
        schedule_type: str = "cron",
        target_scope_type: str = "private",
        target_scope_id: str | None = None,
        target_origin: str | None = None,
        target_destination_id: str | None = None,
    ) -> ScheduledJob:
        if not target_scope_id:
            target_scope_id = f"private:{user_id}"
        job = ScheduledJob(
            id=str(uuid.uuid4()),
            user_id=user_id,
            channel_id=channel_id,
            target_scope_type=target_scope_type,
            target_scope_id=target_scope_id,
            target_origin=target_origin,
            target_destination_id=target_destination_id,
            name=name,
            prompt=prompt,
            model=model,
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
            if not hasattr(job, key):
                continue
            if key == "next_run_at":
                # Allow explicitly clearing next run timestamps for paused/one-shot jobs.
                setattr(job, key, value)
                continue
            if value is not None:
                setattr(job, key, value)
        job.updated_at = self._utcnow()
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
        run = ScheduledRun(id=str(uuid.uuid4()), job_id=job_id, status=status, created_at=self._utcnow())
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
                setattr(run, key, value)
        await self.session.commit()
        return run

    async def create_agent_job(
        self,
        *,
        user_id: str,
        session_id: str | None,
        kind: str,
        name: str,
        model: str | None,
        payload: dict[str, Any] | None = None,
        limits: dict[str, Any] | None = None,
        target_scope_type: str = "private",
        target_scope_id: str = "",
        target_origin: str | None = None,
        target_destination_id: str | None = None,
    ) -> AgentJob:
        job = AgentJob(
            id=str(uuid.uuid4()),
            user_id=user_id,
            session_id=session_id,
            kind=kind,
            name=name,
            status="queued",
            model=model,
            payload=payload or {},
            limits=limits or {},
            target_scope_type=target_scope_type,
            target_scope_id=target_scope_id,
            target_origin=target_origin,
            target_destination_id=target_destination_id,
            created_at=self._utcnow(),
        )
        self.session.add(job)
        await self.session.commit()
        return job

    async def get_agent_job(self, job_id: str) -> Optional[AgentJob]:
        result = await self.session.execute(select(AgentJob).where(AgentJob.id == job_id))
        return result.scalar_one_or_none()

    async def list_agent_jobs(
        self,
        user_id: str,
        limit: int = 50,
        status: str | None = None,
    ) -> List[AgentJob]:
        stmt = (
            select(AgentJob)
            .where(AgentJob.user_id == user_id)
            .order_by(AgentJob.created_at.desc())
            .limit(limit)
        )
        if status:
            stmt = stmt.where(AgentJob.status == status)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_agent_jobs_all(
        self,
        *,
        limit: int = 100,
        status: str | None = None,
        user_id: str | None = None,
    ) -> List[AgentJob]:
        stmt = select(AgentJob).order_by(AgentJob.created_at.desc()).limit(limit)
        if status:
            stmt = stmt.where(AgentJob.status == status)
        if user_id:
            stmt = stmt.where(AgentJob.user_id == user_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def claim_next_agent_job(self) -> Optional[AgentJob]:
        stmt = (
            select(AgentJob)
            .where(
                AgentJob.status == "queued",
                AgentJob.cancel_requested == False,  # noqa: E712
            )
            .order_by(AgentJob.created_at.asc())
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        result = await self.session.execute(stmt)
        job = result.scalars().first()
        if job is None:
            return None
        job.status = "running"
        job.started_at = self._utcnow()
        await self.session.commit()
        return job

    async def complete_agent_job(
        self,
        job_id: str,
        *,
        status: str,
        result_payload: dict[str, Any] | None = None,
        error: str | None = None,
        tool_calls_used: int | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        total_tokens: int | None = None,
        cost: float | None = None,
    ) -> Optional[AgentJob]:
        result = await self.session.execute(select(AgentJob).where(AgentJob.id == job_id))
        job = result.scalar_one_or_none()
        if job is None:
            return None
        job.status = status
        job.result = result_payload or {}
        job.error = error
        job.finished_at = self._utcnow()
        if tool_calls_used is not None:
            job.tool_calls_used = int(tool_calls_used)
        if input_tokens is not None:
            job.input_tokens = int(input_tokens)
        if output_tokens is not None:
            job.output_tokens = int(output_tokens)
        if total_tokens is not None:
            job.total_tokens = int(total_tokens)
        if cost is not None:
            job.cost = float(cost)
        await self.session.commit()
        return job

    async def mark_agent_job_delivered(self, job_id: str, delivery_error: str | None = None) -> Optional[AgentJob]:
        result = await self.session.execute(select(AgentJob).where(AgentJob.id == job_id))
        job = result.scalar_one_or_none()
        if job is None:
            return None
        job.delivered_at = self._utcnow()
        job.delivery_error = delivery_error
        await self.session.commit()
        return job

    async def request_cancel_agent_job(self, user_id: str, job_id: str) -> Optional[AgentJob]:
        result = await self.session.execute(
            select(AgentJob).where(AgentJob.id == job_id, AgentJob.user_id == user_id)
        )
        job = result.scalar_one_or_none()
        if job is None:
            return None
        if job.status in {"completed", "failed", "timeout", "cancelled"}:
            return job
        if job.status == "queued":
            job.status = "cancelled"
            job.cancel_requested = True
            job.finished_at = self._utcnow()
        else:
            job.cancel_requested = True
        await self.session.commit()
        return job

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
            created_at=self._utcnow(),
            updated_at=self._utcnow(),
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
                created_at=self._utcnow(),
                updated_at=self._utcnow(),
            )
            self.session.add(secret)
        else:
            secret.value_encrypted = value_encrypted
            secret.updated_at = self._utcnow()
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
        secret.last_used_at = self._utcnow()
        await self.session.commit()
        return secret

    async def create_auth_token(
        self,
        user_id: str,
        token_hash: str,
        token_prefix: str,
        device_name: str | None,
        device_type: str | None,
        created_via: str,
        expires_at: datetime | None = None,
    ) -> AuthToken:
        token = AuthToken(
            id=str(uuid.uuid4()),
            user_id=user_id,
            token_hash=token_hash,
            token_prefix=token_prefix,
            device_name=(device_name or "").strip() or None,
            device_type=(device_type or "").strip() or None,
            created_via=(created_via or "").strip() or "unknown",
            created_at=self._utcnow(),
            expires_at=expires_at,
        )
        self.session.add(token)
        await self.session.commit()
        return token

    async def get_auth_token_by_hash(self, token_hash: str) -> Optional[AuthToken]:
        result = await self.session.execute(select(AuthToken).where(AuthToken.token_hash == token_hash))
        return result.scalar_one_or_none()

    async def touch_auth_token(self, token: AuthToken) -> AuthToken:
        token.last_used_at = self._utcnow()
        await self.session.commit()
        return token

    async def revoke_auth_token(self, token_id: str) -> bool:
        result = await self.session.execute(select(AuthToken).where(AuthToken.id == token_id))
        token = result.scalar_one_or_none()
        if token is None:
            return False
        token.revoked_at = self._utcnow()
        await self.session.commit()
        return True

    async def list_auth_tokens(self, user_id: str) -> List[AuthToken]:
        result = await self.session.execute(
            select(AuthToken)
            .where(AuthToken.user_id == user_id)
            .order_by(AuthToken.created_at.desc())
        )
        return list(result.scalars().all())

    async def create_executor(
        self,
        *,
        owner_user_id: str,
        name: str,
        kind: str,
        platform: str | None = None,
        hostname: str | None = None,
        status: str = "offline",
        capabilities: dict | None = None,
        disabled: bool = False,
    ) -> Executor:
        normalized_name = name.strip()
        existing = await self.get_executor_for_user_by_name(owner_user_id, normalized_name)
        if existing is not None:
            existing.kind = kind.strip() or existing.kind
            existing.platform = (platform or "").strip() or existing.platform
            existing.hostname = (hostname or "").strip() or existing.hostname
            existing.status = (status or "").strip() or existing.status
            existing.capabilities = capabilities or existing.capabilities or {}
            existing.disabled = bool(disabled)
            await self.session.commit()
            return existing
        row = Executor(
            id=str(uuid.uuid4()),
            owner_user_id=owner_user_id,
            name=normalized_name,
            kind=kind.strip() or "docker",
            platform=(platform or "").strip() or None,
            hostname=(hostname or "").strip() or None,
            status=(status or "").strip() or "offline",
            capabilities=capabilities or {},
            created_at=self._utcnow(),
            disabled=bool(disabled),
        )
        self.session.add(row)
        await self.session.commit()
        return row

    async def get_executor(self, executor_id: str) -> Optional[Executor]:
        result = await self.session.execute(select(Executor).where(Executor.id == executor_id))
        return result.scalar_one_or_none()

    async def get_executor_for_user(self, user_id: str, executor_id: str) -> Optional[Executor]:
        result = await self.session.execute(
            select(Executor).where(Executor.id == executor_id, Executor.owner_user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def get_executor_for_user_by_name(self, user_id: str, name: str) -> Optional[Executor]:
        lowered = (name or "").strip().lower()
        if not lowered:
            return None
        result = await self.session.execute(
            select(Executor).where(
                Executor.owner_user_id == user_id,
                func.lower(Executor.name) == lowered,
            )
        )
        return result.scalar_one_or_none()

    async def get_docker_executor_for_user(self, user_id: str) -> Optional[Executor]:
        result = await self.session.execute(
            select(Executor).where(
                Executor.owner_user_id == user_id,
                Executor.kind == "docker",
                func.lower(Executor.name) == "docker-default",
            )
        )
        return result.scalar_one_or_none()

    async def list_executors_for_user(self, user_id: str, *, include_disabled: bool = False) -> List[Executor]:
        stmt = select(Executor).where(Executor.owner_user_id == user_id)
        if not include_disabled:
            stmt = stmt.where(Executor.disabled == False)  # noqa: E712
        result = await self.session.execute(stmt.order_by(Executor.created_at.desc()))
        return list(result.scalars().all())

    async def list_executors_all(
        self,
        *,
        user_id: str | None = None,
        include_disabled: bool = True,
        kind: str | None = None,
        limit: int = 200,
    ) -> List[Executor]:
        stmt = select(Executor)
        if user_id:
            stmt = stmt.where(Executor.owner_user_id == user_id)
        if kind:
            stmt = stmt.where(Executor.kind == kind)
        if not include_disabled:
            stmt = stmt.where(Executor.disabled == False)  # noqa: E712
        result = await self.session.execute(stmt.order_by(Executor.created_at.desc()).limit(limit))
        return list(result.scalars().all())

    async def update_executor(
        self,
        executor_id: str,
        *,
        name: str | None = None,
        platform: str | None = None,
        hostname: str | None = None,
        status: str | None = None,
        capabilities: dict | None = None,
        disabled: bool | None = None,
        last_seen_at: datetime | None = None,
    ) -> Optional[Executor]:
        row = await self.get_executor(executor_id)
        if row is None:
            return None
        if name is not None:
            row.name = (name or "").strip() or row.name
        if platform is not None:
            row.platform = (platform or "").strip() or None
        if hostname is not None:
            row.hostname = (hostname or "").strip() or None
        if status is not None:
            row.status = (status or "").strip() or row.status
        if capabilities is not None:
            row.capabilities = capabilities
        if disabled is not None:
            row.disabled = bool(disabled)
        if last_seen_at is not None:
            row.last_seen_at = last_seen_at
        await self.session.commit()
        return row

    async def get_or_create_docker_executor(self, user_id: str) -> Executor:
        result = await self.session.execute(
            select(Executor).where(
                Executor.owner_user_id == user_id,
                Executor.kind == "docker",
                func.lower(Executor.name) == "docker-default",
            )
        )
        row = result.scalar_one_or_none()
        if row is not None:
            return row
        return await self.create_executor(
            owner_user_id=user_id,
            name="docker-default",
            kind="docker",
            platform="linux",
            hostname="docker",
            status="online",
            capabilities={"tools": "all"},
            disabled=False,
        )

    async def create_executor_token(
        self,
        *,
        executor_id: str,
        token_hash: str,
        token_prefix: str,
    ) -> ExecutorToken:
        row = ExecutorToken(
            id=str(uuid.uuid4()),
            executor_id=executor_id,
            token_hash=token_hash,
            token_prefix=token_prefix,
            created_at=self._utcnow(),
        )
        self.session.add(row)
        await self.session.commit()
        return row

    async def get_executor_token_by_hash(self, token_hash: str) -> Optional[ExecutorToken]:
        result = await self.session.execute(select(ExecutorToken).where(ExecutorToken.token_hash == token_hash))
        return result.scalar_one_or_none()

    async def list_executor_tokens(self, executor_id: str) -> List[ExecutorToken]:
        result = await self.session.execute(
            select(ExecutorToken)
            .where(ExecutorToken.executor_id == executor_id)
            .order_by(ExecutorToken.created_at.desc())
        )
        return list(result.scalars().all())

    async def revoke_executor_token(self, token_id: str) -> bool:
        result = await self.session.execute(select(ExecutorToken).where(ExecutorToken.id == token_id))
        row = result.scalar_one_or_none()
        if row is None:
            return False
        row.revoked_at = self._utcnow()
        await self.session.commit()
        return True

    async def revoke_executor_tokens(self, executor_id: str) -> int:
        result = await self.session.execute(
            select(ExecutorToken).where(
                ExecutorToken.executor_id == executor_id,
                ExecutorToken.revoked_at == None,  # noqa: E711
            )
        )
        rows = list(result.scalars().all())
        if not rows:
            return 0
        now = self._utcnow()
        for row in rows:
            row.revoked_at = now
        await self.session.commit()
        return len(rows)

    async def restore_executor_tokens(self, executor_id: str) -> int:
        result = await self.session.execute(
            select(ExecutorToken).where(
                ExecutorToken.executor_id == executor_id,
                ExecutorToken.revoked_at != None,  # noqa: E711
            )
        )
        rows = list(result.scalars().all())
        if not rows:
            return 0
        for row in rows:
            row.revoked_at = None
        await self.session.commit()
        return len(rows)

    async def delete_executor(self, executor_id: str) -> bool:
        result = await self.session.execute(select(Executor).where(Executor.id == executor_id))
        row = result.scalar_one_or_none()
        if row is None:
            return False
        await self.session.execute(delete(ExecutorToken).where(ExecutorToken.executor_id == executor_id))
        await self.session.delete(row)
        await self.session.commit()
        return True

    async def create_pair_code(
        self,
        code_hash: str,
        *,
        flow_type: str,
        user_id: str | None,
        display_name: str | None,
        created_by_user_id: str | None,
        created_via: str,
        expires_at: datetime,
    ) -> PairCode:
        pair = PairCode(
            id=str(uuid.uuid4()),
            code_hash=code_hash,
            user_id=user_id,
            flow_type=flow_type,
            display_name=(display_name or "").strip() or None,
            created_by_user_id=(created_by_user_id or "").strip() or None,
            created_via=(created_via or "").strip() or "unknown",
            created_at=self._utcnow(),
            expires_at=expires_at,
            consumed_at=None,
            attempts=0,
        )
        self.session.add(pair)
        await self.session.commit()
        return pair

    async def get_pair_code_by_hash(self, code_hash: str, *, flow_type: str | None = None) -> Optional[PairCode]:
        stmt = select(PairCode).where(PairCode.code_hash == code_hash)
        if flow_type:
            stmt = stmt.where(PairCode.flow_type == flow_type)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def mark_pair_code_attempt(self, pair: PairCode) -> PairCode:
        pair.attempts = int(pair.attempts or 0) + 1
        await self.session.commit()
        return pair

    async def consume_pair_code(self, pair: PairCode) -> PairCode:
        pair.consumed_at = self._utcnow()
        await self.session.commit()
        return pair

    async def delete_expired_pair_codes(self) -> int:
        now = self._utcnow()
        result = await self.session.execute(
            select(PairCode).where(PairCode.expires_at < now)
        )
        rows = list(result.scalars().all())
        if not rows:
            return 0
        for row in rows:
            await self.session.delete(row)
        await self.session.commit()
        return len(rows)
