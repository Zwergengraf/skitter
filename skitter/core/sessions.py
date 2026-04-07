from __future__ import annotations

import re
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Optional

from ..data.db import SessionLocal
from ..data.repositories import Repository
from .memory_service import MemoryService
from .runtime import AgentRuntime
from .llm import resolve_model_name
from .profiles import private_profile_scope_id
from .workspace import ensure_profile_workspace, user_workspace_root


def normalize_session_summary(summary: object) -> str:
    if isinstance(summary, str):
        normalized = summary
    elif isinstance(summary, list):
        normalized = "\n".join(str(item) for item in summary)
    else:
        normalized = str(summary)
    return normalized.strip() + "\n"


def current_summary_date() -> date:
    return datetime.now(UTC).date()


def session_summary_relative_path(target_date: date | None = None) -> Path:
    resolved_date = target_date or current_summary_date()
    return Path("memory") / "session-summaries" / f"{resolved_date.isoformat()}.md"


def _session_summary_section(session_id: str, summary: object) -> str:
    return f"# Session Summary ({session_id})\n\n{normalize_session_summary(summary)}"


def _replace_or_append_session_summary(existing: str, session_id: str, summary: object) -> str:
    section = _session_summary_section(session_id, summary).strip()
    pattern = re.compile(
        rf"(?ms)^# Session Summary \({re.escape(session_id)}\)\n.*?(?=^# Session Summary \(|\Z)"
    )
    cleaned_existing = existing.strip()
    if not cleaned_existing:
        return section + "\n"
    if pattern.search(cleaned_existing):
        updated = pattern.sub(section + "\n\n", cleaned_existing, count=1).strip()
        return updated + "\n"
    return cleaned_existing + "\n\n" + section + "\n"


def write_session_summary_file(
    user_id: str,
    session_id: str,
    summary: object,
    *,
    profile_slug: str | None = None,
    target_date: date | None = None,
) -> tuple[Path, str]:
    path = user_workspace_root(user_id, profile_slug) / session_summary_relative_path(target_date)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = ""
    if path.exists():
        existing = path.read_text(encoding="utf-8")
    body = normalize_session_summary(summary)
    content = _replace_or_append_session_summary(existing, session_id, summary)
    path.write_text(content, encoding="utf-8")
    return path, body


class SessionManager:
    def __init__(self, runtime: AgentRuntime, memory_service: MemoryService | None = None) -> None:
        self.runtime = runtime
        self._scope_session: dict[str, str] = {}
        self.memory_service = memory_service or MemoryService()

    async def get_or_create_session(
        self,
        user_id: str,
        channel_id: str,
        *,
        agent_profile_id: str,
        agent_profile_slug: str,
    ) -> str:
        return await self.get_or_create_session_for_scope(
            user_id=user_id,
            agent_profile_id=agent_profile_id,
            agent_profile_slug=agent_profile_slug,
            scope_type="private",
            scope_id=private_profile_scope_id(agent_profile_id),
            origin="discord",
            cache_key=channel_id,
        )

    async def get_or_create_session_for_scope(
        self,
        user_id: str,
        agent_profile_id: str,
        agent_profile_slug: str,
        scope_type: str,
        scope_id: str,
        origin: str,
        cache_key: str | None = None,
    ) -> str:
        key = f"{agent_profile_id}:{cache_key or scope_id}"
        cached = self._scope_session.get(key)
        ensure_profile_workspace(user_id, agent_profile_slug)
        async with SessionLocal() as session:
            repo = Repository(session)
            if cached:
                cached_session = await repo.get_session(cached)
                if (
                    cached_session is not None
                    and cached_session.status == "active"
                    and cached_session.user_id == user_id
                    and (cached_session.agent_profile_id or "") == agent_profile_id
                    and (cached_session.scope_type or "private") == scope_type
                    and (cached_session.scope_id or "") == scope_id
                ):
                    self._scope_session[f"{agent_profile_id}:{scope_id}"] = cached_session.id
                    return cached_session.id
                self._scope_session.pop(key, None)
                if key != f"{agent_profile_id}:{scope_id}":
                    self._scope_session.pop(f"{agent_profile_id}:{scope_id}", None)
            active = await repo.get_active_session_by_scope(scope_type, scope_id, agent_profile_id=agent_profile_id)
            if active is None:
                model_name = resolve_model_name(None, purpose="main")
                active = await repo.create_session(
                    user_id,
                    agent_profile_id=agent_profile_id,
                    model=model_name,
                    origin=origin,
                    scope_type=scope_type,
                    scope_id=scope_id,
                )
        self._scope_session[key] = active.id
        self._scope_session[f"{agent_profile_id}:{scope_id}"] = active.id
        return active.id

    async def start_new_session(
        self,
        user_id: str,
        channel_id: str,
        *,
        agent_profile_id: str,
        agent_profile_slug: str,
    ) -> tuple[Optional[Path], str]:
        return await self.start_new_session_for_scope(
            user_id=user_id,
            agent_profile_id=agent_profile_id,
            agent_profile_slug=agent_profile_slug,
            scope_type="private",
            scope_id=private_profile_scope_id(agent_profile_id),
            origin="discord",
            channel_id=channel_id,
        )

    async def start_new_session_for_origin(
        self,
        user_id: str,
        agent_profile_id: str,
        agent_profile_slug: str,
        origin: str,
        channel_id: str | None = None,
    ) -> tuple[Optional[Path], str]:
        return await self.start_new_session_for_scope(
            user_id=user_id,
            agent_profile_id=agent_profile_id,
            agent_profile_slug=agent_profile_slug,
            scope_type="private",
            scope_id=private_profile_scope_id(agent_profile_id),
            origin=origin,
            channel_id=channel_id,
        )

    async def start_new_session_for_scope(
        self,
        user_id: str,
        agent_profile_id: str,
        agent_profile_slug: str,
        scope_type: str,
        scope_id: str,
        origin: str,
        channel_id: str | None = None,
        cache_key: str | None = None,
    ) -> tuple[Optional[Path], str]:
        ensure_profile_workspace(user_id, agent_profile_slug)
        async with SessionLocal() as session:
            repo = Repository(session)
            active = await repo.get_active_session_by_scope(scope_type, scope_id, agent_profile_id=agent_profile_id)
            if active is not None:
                await repo.end_session(active.id, status="ended")
                if scope_type == "private":
                    await repo.queue_session_summary(active.id)
                    await self.runtime.event_bus.emit_admin(
                        kind="session.summary_queued",
                        level="info",
                        title="Session summary queued",
                        message="Archived session summarization was moved to the background queue.",
                        session_id=active.id,
                        user_id=user_id,
                        data={"scope_type": scope_type, "scope_id": scope_id},
                    )
                self.runtime.clear_history(active.id)
            model_name = resolve_model_name(None, purpose="main")
            new_session = await repo.create_session(
                user_id,
                agent_profile_id=agent_profile_id,
                model=model_name,
                origin=origin,
                scope_type=scope_type,
                scope_id=scope_id,
            )
        if channel_id or cache_key:
            self._scope_session[f"{agent_profile_id}:{cache_key or channel_id}"] = new_session.id
        self._scope_session[f"{agent_profile_id}:{scope_id}"] = new_session.id
        await self.runtime.event_bus.emit_admin(
            kind="session.started",
            level="info",
            title="Session started",
            message="Started a new active session.",
            session_id=new_session.id,
            user_id=user_id,
            transport=origin,
            data={"scope_type": scope_type, "scope_id": scope_id},
        )
        return None, new_session.id

    async def reindex_memories(self, user_id: str, *, agent_profile_id: str, agent_profile_slug: str) -> dict:
        memory_root = user_workspace_root(user_id, agent_profile_slug) / "memory"
        return await self.memory_service.reindex_all(user_id, memory_root, agent_profile_id=agent_profile_id)

    async def search_memories(
        self,
        user_id: str,
        query: str,
        *,
        agent_profile_id: str,
        top_k: int = 5,
    ) -> list[dict]:
        return await self.memory_service.search(user_id, query, top_k, agent_profile_id=agent_profile_id)
