from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Query, HTTPException

from ..deps import get_repo
from ..schemas import MemoryEntryOut, MemoryForgetRequest
from ...core.config import settings
from ...core.sessions import SessionManager
from ...core.runtime import AgentRuntime
from ...data.repositories import Repository

router = APIRouter(prefix="/v1/memory", tags=["memory"])


def _extract_tag(tags: list, prefix: str) -> list[str]:
    values = []
    for tag in tags:
        if isinstance(tag, str) and tag.startswith(prefix):
            values.append(tag.replace(prefix, "", 1))
    return values


def _memory_root() -> Path:
    return Path(settings.workspace_root) / "memory"


def _safe_memory_path(source: str) -> Path:
    if "/" in source or "\\" in source or source.startswith("."):
        raise HTTPException(status_code=400, detail="Invalid source")
    path = _memory_root() / source
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="Memory file not found")
    return path


@router.get("", response_model=list[MemoryEntryOut])
async def list_memory(
    repo: Repository = Depends(get_repo),
    user_id: str = Query(...),
    limit: int = Query(default=200, ge=1, le=1000),
) -> list[MemoryEntryOut]:
    entries = await repo.list_memory_entries(user_id)
    grouped: dict[str, dict] = {}
    for entry in entries:
        sources = _extract_tag(entry.tags or [], "file:")
        if not sources:
            continue
        source = sources[0]
        sessions = _extract_tag(entry.tags or [], "session:")
        record = grouped.setdefault(
            source,
            {
                "id": source,
                "summary": "",
                "tags": [],
                "created_at": entry.created_at,
                "source": source,
                "session_ids": set(),
            },
        )
        record["session_ids"].update(sessions)
        if entry.created_at > record["created_at"]:
            record["created_at"] = entry.created_at
    results = []
    for record in grouped.values():
        results.append(
            MemoryEntryOut(
                id=record["id"],
                summary=record["summary"],
                tags=[],
                created_at=record["created_at"],
                source=record["source"],
                session_ids=sorted(record["session_ids"]),
            )
        )
    results.sort(key=lambda item: item.created_at, reverse=True)
    return results[:limit]


@router.get("/file")
async def get_memory_file(source: str) -> dict:
    path = _safe_memory_path(source)
    content = path.read_text(encoding="utf-8")
    return {"source": source, "content": content}


@router.post("/reindex")
async def reindex_memory(
    repo: Repository = Depends(get_repo),
    user_id: str = Query(...),
) -> dict:
    user = await repo.get_user_by_id(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    runtime: AgentRuntime | None = repo.session.info.get("runtime")
    if runtime is None:
        raise HTTPException(status_code=500, detail="Runtime not available")
    session_manager = SessionManager(runtime, settings.workspace_root)
    stats = await session_manager.reindex_memories(user.transport_user_id)
    return stats


@router.post("/forget")
async def forget_memory(payload: MemoryForgetRequest, repo: Repository = Depends(get_repo)) -> dict:
    deleted = await repo.delete_memory(payload.user_id)
    return {"deleted": deleted}
