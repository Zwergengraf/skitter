from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

from ..data.db import SessionLocal
from ..data.repositories import Repository
from .memory_service import MemoryService
from .runtime import AgentRuntime


class SessionManager:
    def __init__(self, runtime: AgentRuntime, workspace_root: str, memory_service: MemoryService | None = None) -> None:
        self.runtime = runtime
        self.workspace_root = Path(workspace_root)
        self._channel_session: dict[str, str] = {}
        self.memory_service = memory_service or MemoryService()

    async def get_or_create_session(self, transport_user_id: str, channel_id: str) -> str:
        cached = self._channel_session.get(channel_id)
        if cached:
            return cached
        async with SessionLocal() as session:
            repo = Repository(session)
            user = await repo.get_or_create_user(transport_user_id)
            active = await repo.get_active_session(user.id)
            if active is None:
                active = await repo.create_session(user.id)
        self._channel_session[channel_id] = active.id
        return active.id

    async def start_new_session(
        self, transport_user_id: str, channel_id: str
    ) -> tuple[Optional[Path], str]:
        summary_path: Optional[Path] = None
        async with SessionLocal() as session:
            repo = Repository(session)
            user = await repo.get_or_create_user(transport_user_id)
            active = await repo.get_active_session(user.id)
            if active is not None:
                summary = await self.runtime.summarize_session(active.id)
                summary_path, _ = self._write_summary(summary, active.id)
                if summary_path is not None:
                    await self.memory_service.index_file(user.id, active.id, summary_path, force=True)
                await repo.end_session(active.id, status="ended")
                self.runtime.clear_history(active.id)
            new_session = await repo.create_session(user.id)
        self._channel_session[channel_id] = new_session.id
        return summary_path, new_session.id

    async def reindex_memories(self, transport_user_id: str) -> dict:
        memory_root = self.workspace_root / "memory"
        async with SessionLocal() as session:
            repo = Repository(session)
            user = await repo.get_or_create_user(transport_user_id)
        return await self.memory_service.reindex_all(user.id, memory_root)

    def _write_summary(self, summary: str, session_id: str) -> tuple[Path, str]:
        memory_root = self.workspace_root / "memory"
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
