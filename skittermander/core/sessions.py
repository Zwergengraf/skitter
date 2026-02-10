from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

from ..data.db import SessionLocal
from ..data.repositories import Repository
from .memory_service import MemoryService
from .runtime import AgentRuntime
from .llm import resolve_model_name
from .workspace import ensure_user_workspace, user_workspace_root


class SessionManager:
    def __init__(self, runtime: AgentRuntime, workspace_root: str, memory_service: MemoryService | None = None) -> None:
        self.runtime = runtime
        self.workspace_root = Path(workspace_root)
        self._scope_session: dict[str, str] = {}
        self.memory_service = memory_service or MemoryService()

    async def get_or_create_session(self, user_id: str, channel_id: str) -> str:
        return await self.get_or_create_session_for_scope(
            user_id=user_id,
            scope_type="private",
            scope_id=f"private:{user_id}",
            origin="discord",
            cache_key=channel_id,
        )

    async def get_or_create_session_for_scope(
        self,
        user_id: str,
        scope_type: str,
        scope_id: str,
        origin: str,
        cache_key: str | None = None,
    ) -> str:
        key = cache_key or scope_id
        cached = self._scope_session.get(key)
        if cached:
            return cached
        ensure_user_workspace(user_id)
        async with SessionLocal() as session:
            repo = Repository(session)
            active = await repo.get_active_session_by_scope(scope_type, scope_id)
            if active is None:
                model_name = resolve_model_name(None, purpose="main")
                active = await repo.create_session(
                    user_id,
                    model=model_name,
                    origin=origin,
                    scope_type=scope_type,
                    scope_id=scope_id,
                )
        self._scope_session[key] = active.id
        return active.id

    async def start_new_session(
        self, user_id: str, channel_id: str
    ) -> tuple[Optional[Path], str]:
        return await self.start_new_session_for_scope(
            user_id=user_id,
            scope_type="private",
            scope_id=f"private:{user_id}",
            origin="discord",
            channel_id=channel_id,
        )

    async def start_new_session_for_origin(
        self,
        user_id: str,
        origin: str,
        channel_id: str | None = None,
    ) -> tuple[Optional[Path], str]:
        return await self.start_new_session_for_scope(
            user_id=user_id,
            scope_type="private",
            scope_id=f"private:{user_id}",
            origin=origin,
            channel_id=channel_id,
        )

    async def start_new_session_for_scope(
        self,
        user_id: str,
        scope_type: str,
        scope_id: str,
        origin: str,
        channel_id: str | None = None,
    ) -> tuple[Optional[Path], str]:
        summary_path: Optional[Path] = None
        ensure_user_workspace(user_id)
        async with SessionLocal() as session:
            repo = Repository(session)
            active = await repo.get_active_session_by_scope(scope_type, scope_id)
            if active is not None:
                if scope_type == "private":
                    summary = await self.runtime.summarize_session(active.id)
                    summary_path, _ = self._write_summary(user_id, summary, active.id)
                    if summary_path is not None:
                        await self.memory_service.index_file(user_id, active.id, summary_path, force=True)
                await repo.end_session(active.id, status="ended")
                self.runtime.clear_history(active.id)
            model_name = resolve_model_name(None, purpose="main")
            new_session = await repo.create_session(
                user_id,
                model=model_name,
                origin=origin,
                scope_type=scope_type,
                scope_id=scope_id,
            )
        if channel_id:
            self._scope_session[channel_id] = new_session.id
        self._scope_session[scope_id] = new_session.id
        return summary_path, new_session.id

    async def reindex_memories(self, user_id: str) -> dict:
        memory_root = user_workspace_root(user_id) / "memory"
        return await self.memory_service.reindex_all(user_id, memory_root)

    async def search_memories(self, user_id: str, query: str, top_k: int = 5) -> list[dict]:
        return await self.memory_service.search(user_id, query, top_k)

    def _write_summary(self, user_id: str, summary: str, session_id: str) -> tuple[Path, str]:
        memory_root = user_workspace_root(user_id) / "memory"
        memory_root.mkdir(parents=True, exist_ok=True)
        filename = f"{datetime.utcnow().date().isoformat()}.md"
        path = memory_root / filename
        header = f"# Session Summary ({session_id})\n\n"
        body = summary.strip() + "\n"
        if path.exists():
            content = f"\n---\n\n{header}{body}"
            path.write_text(path.read_text(encoding="utf-8") + content, encoding="utf-8")
        else:
            path.write_text(header + body, encoding="utf-8")
        return path, body
