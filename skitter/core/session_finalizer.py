from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

from ..data.db import SessionLocal
from ..data.repositories import Repository
from .memory_provider import MemoryItem, MemoryStoreRequest, SessionArchived
from .memory_service import MemoryService
from .session_memory import current_session_memory_path, session_memory_relative_path
from .sessions import current_summary_date, session_summary_relative_path, write_session_summary_file


class SessionFinalizerService:
    BACKOFF_MINUTES = (1, 5, 15, 60)
    MAX_ATTEMPTS = 5

    def __init__(
        self,
        runtime,
        *,
        memory_service: MemoryService | None = None,
        poll_interval_seconds: float = 5.0,
    ) -> None:
        self.runtime = runtime
        self.memory_service = memory_service or MemoryService()
        self.poll_interval_seconds = max(1.0, float(poll_interval_seconds))
        self._logger = logging.getLogger(__name__)
        self._stop_event = asyncio.Event()
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        if self._task is not None:
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self._worker_loop(), name="skitter-session-finalizer")

    async def stop(self) -> None:
        self._stop_event.set()
        task = self._task
        self._task = None
        if task is None:
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    async def run_once(self) -> bool:
        async with SessionLocal() as session:
            repo = Repository(session)
            target = await repo.claim_next_session_summary()
        if target is None:
            return False
        await self._finalize_session(target)
        return True

    async def _worker_loop(self) -> None:
        while not self._stop_event.is_set():
            handled = await self.run_once()
            if handled:
                continue
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self.poll_interval_seconds)
            except asyncio.TimeoutError:
                continue

    async def _finalize_session(self, session_row) -> None:
        session_id = str(session_row.id)
        user_id = str(session_row.user_id)
        model_name = (
            str(getattr(session_row, "last_model", "") or "").strip()
            or str(getattr(session_row, "model", "") or "").strip()
            or None
        )
        session_memory_relative = (
            str(getattr(session_row, "session_memory_path", "") or "").strip()
            or session_memory_relative_path(session_id).as_posix()
        )
        await self.runtime.event_bus.emit_admin(
            kind="session.summary_started",
            level="info",
            title="Session summary started",
            message="Background session summarization is running.",
            session_id=session_id,
            user_id=user_id,
            data={"model": model_name},
        )
        agent_profile_id = str(getattr(session_row, "agent_profile_id", "") or "").strip()
        try:
            agent_profile_slug = await self._resolve_agent_profile_slug(session_row)
            memory_hub = getattr(self.runtime, "memory_hub", None)
            memory_ctx = None
            if memory_hub is not None:
                memory_ctx = memory_hub.context_for(
                    user_id=user_id,
                    agent_profile_id=agent_profile_id or None,
                    agent_profile_slug=agent_profile_slug,
                    session_id=session_id,
                    origin="archive",
                    scope_type=str(getattr(session_row, "scope_type", "private") or "private"),
                    scope_id=str(getattr(session_row, "scope_id", "") or ""),
                )
                await memory_hub.before_session_archive(memory_ctx, session_id)
            summary_date = current_summary_date()
            summary = await self.runtime.summarize_session(session_id, model_name=model_name)
            summary_path, _ = write_session_summary_file(
                user_id,
                session_id,
                summary,
                profile_slug=agent_profile_slug,
                target_date=summary_date,
            )
            if memory_hub is not None and memory_ctx is not None:
                store_result = await memory_hub.store(
                    memory_ctx,
                    MemoryStoreRequest(
                        items=[
                            MemoryItem(
                                content=str(summary),
                                kind="summary",
                                tags=["archive", f"session:{session_id}"],
                                source="archive",
                                metadata={
                                    "source": summary_path.name,
                                    "path": str(summary_path),
                                    "index_file": True,
                                },
                            )
                        ],
                        source="archive",
                    ),
                )
                indexed = store_result.stored > 0
            else:
                indexed = await self.memory_service.index_file(
                    user_id,
                    session_id,
                    summary_path,
                    force=True,
                    agent_profile_id=agent_profile_id or None,
                )
            if not indexed:
                raise RuntimeError("summary embedding/indexing did not produce any memory entries")
            if memory_hub is not None and memory_ctx is not None:
                await memory_hub.on_session_archived(
                    memory_ctx,
                    SessionArchived(
                        session_id=session_id,
                        archive_summary=str(summary),
                        session_memory_path=session_memory_relative,
                    ),
                )
        except Exception as exc:  # pragma: no cover - covered via service tests
            await self._record_failure(session_id, exc)
            return

        relative_path = session_summary_relative_path(summary_date).as_posix()
        async with SessionLocal() as session:
            repo = Repository(session)
            await repo.complete_session_summary(session_id, summary_path=relative_path)
        deleted_session_memory_path = await self._delete_session_memory_file(session_row, agent_profile_slug)
        self._logger.info("Completed background session finalization for %s", session_id)
        await self.runtime.event_bus.emit_admin(
            kind="session.summary_completed",
            level="success",
            title="Session summary completed",
            message="Background session summarization and embedding completed.",
            session_id=session_id,
            user_id=user_id,
            data={"summary_path": relative_path, "deleted_session_memory_path": deleted_session_memory_path},
        )

    async def _resolve_agent_profile_slug(self, session_row) -> str | None:
        agent_profile_id = str(getattr(session_row, "agent_profile_id", "") or "").strip()
        if not agent_profile_id:
            return None

        session_id = str(session_row.id)
        user_id = str(session_row.user_id)
        async with SessionLocal() as session:
            repo = Repository(session)
            profile = await repo.get_agent_profile(agent_profile_id)
        if profile is None:
            raise RuntimeError(f"agent profile for session {session_id} was not found")

        profile_user_id = str(getattr(profile, "user_id", "") or "").strip()
        if profile_user_id and profile_user_id != user_id:
            raise RuntimeError(f"agent profile for session {session_id} belongs to a different user")

        profile_slug = str(getattr(profile, "slug", "") or "").strip()
        if not profile_slug:
            raise RuntimeError(f"agent profile for session {session_id} has no slug")
        return profile_slug

    async def _delete_session_memory_file(self, session_row, profile_slug: str | None) -> str | None:
        session_id = str(session_row.id)
        user_id = str(session_row.user_id)
        path = current_session_memory_path(user_id, session_id, profile_slug)
        try:
            path.unlink()
        except FileNotFoundError:
            return None
        except OSError as exc:
            self._logger.warning("Failed to delete session memory sidecar for %s: %s", session_id, exc)
            return None
        return str(path)

    async def _record_failure(self, session_id: str, exc: Exception) -> None:
        message = str(exc).strip() or exc.__class__.__name__
        async with SessionLocal() as session:
            repo = Repository(session)
            current = await repo.get_session(session_id)
            attempts = int(getattr(current, "summary_attempts", 0) or 0)
            terminal = attempts >= self.MAX_ATTEMPTS
            retry_at = None if terminal else self._retry_at_for_attempt(attempts)
            await repo.fail_session_summary(
                session_id,
                error=message,
                retry_at=retry_at,
                terminal=terminal,
            )
        if terminal:
            self._logger.warning("Session finalization failed permanently for %s: %s", session_id, message)
            await self.runtime.event_bus.emit_admin(
                kind="session.summary_failed",
                level="error",
                title="Session summary failed",
                message=message,
                session_id=session_id,
                data={"attempts": attempts, "terminal": True},
            )
        else:
            self._logger.warning("Session finalization failed for %s (attempt %s): %s", session_id, attempts, message)
            await self.runtime.event_bus.emit_admin(
                kind="session.summary_retry_scheduled",
                level="warning",
                title="Session summary retry scheduled",
                message=message,
                session_id=session_id,
                data={
                    "attempts": attempts,
                    "terminal": False,
                    "retry_at": retry_at.isoformat() if retry_at else None,
                },
            )

    @classmethod
    def _retry_at_for_attempt(cls, attempts: int) -> datetime:
        index = max(0, min(attempts - 1, len(cls.BACKOFF_MINUTES) - 1))
        return datetime.now(UTC) + timedelta(minutes=cls.BACKOFF_MINUTES[index])
