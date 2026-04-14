from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Query, HTTPException, Request

from ..authz import require_admin
from ..deps import get_repo
from ..schemas import MemoryEntryOut, MemoryForgetRequest
from ...core.profile_service import profile_service
from ...core.workspace import user_workspace_root
from ...core.sessions import SessionManager
from ...core.runtime import AgentRuntime
from ...core.memory_provider import MemoryForgetRequest as ProviderMemoryForgetRequest
from ...core.memory_provider import MemoryForgetSelector
from ...data.repositories import Repository

router = APIRouter(prefix="/v1/memory", tags=["memory"])


def _extract_tag(tags: list, prefix: str) -> list[str]:
    values = []
    for tag in tags:
        if isinstance(tag, str) and tag.startswith(prefix):
            values.append(tag.replace(prefix, "", 1))
    return values


def _safe_memory_path(user_id: str, source: str, profile_slug: str | None = None) -> Path:
    if "/" in source or "\\" in source or source.startswith("."):
        raise HTTPException(status_code=400, detail="Invalid source")
    path = user_workspace_root(user_id, profile_slug) / "memory" / source
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="Memory file not found")
    return path


@router.get("/status")
async def memory_status(request: Request) -> dict:
    require_admin(request)
    memory_hub = getattr(request.app.state, "memory_hub", None)
    if memory_hub is None:
        return {"providers": [], "started": False, "external_provider_id": None}
    return await memory_hub.status()


@router.get("", response_model=list[MemoryEntryOut])
async def list_memory(
    request: Request,
    repo: Repository = Depends(get_repo),
    user_id: str = Query(...),
    agent_profile_id: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
) -> list[MemoryEntryOut]:
    require_admin(request)
    entries = await repo.list_memory_entries(user_id, agent_profile_id=agent_profile_id)
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
async def get_memory_file(
    request: Request,
    source: str,
    repo: Repository = Depends(get_repo),
    user_id: str = Query(...),
    agent_profile_id: str | None = Query(default=None),
) -> dict:
    require_admin(request)
    profile_slug: str | None = None
    if agent_profile_id:
        profile = await repo.get_agent_profile(agent_profile_id)
        profile_slug = getattr(profile, "slug", None)
    path = _safe_memory_path(user_id, source, profile_slug)
    content = path.read_text(encoding="utf-8")
    return {"source": source, "content": content}


@router.post("/reindex")
async def reindex_memory(
    request: Request,
    repo: Repository = Depends(get_repo),
    user_id: str = Query(...),
    agent_profile_id: str | None = Query(default=None),
) -> dict:
    require_admin(request)
    user = await repo.get_user_by_id(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    profile = await profile_service.resolve_profile(
        repo,
        user.id,
        agent_profile_id=agent_profile_id,
    )
    runtime: AgentRuntime | None = repo.session.info.get("runtime")
    if runtime is None:
        raise HTTPException(status_code=500, detail="Runtime not available")
    session_manager = SessionManager(runtime)
    stats = await session_manager.reindex_memories(
        user.id,
        agent_profile_id=profile.id,
        agent_profile_slug=profile.slug,
    )
    return stats


@router.post("/forget")
async def forget_memory(payload: MemoryForgetRequest, request: Request, repo: Repository = Depends(get_repo)) -> dict:
    require_admin(request)
    user = await repo.get_user_by_id(payload.user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    profile_slug: str | None = None
    if payload.agent_profile_id:
        profile = await repo.get_agent_profile(payload.agent_profile_id)
        if profile is None or profile.user_id != payload.user_id:
            raise HTTPException(status_code=404, detail="Profile not found")
        profile_slug = profile.slug
    memory_hub = getattr(request.app.state, "memory_hub", None)
    if memory_hub is None:
        if payload.provider_id and payload.provider_id != "builtin":
            return {"deleted": 0, "errors": {payload.provider_id: "memory hub unavailable"}, "unsupported": True}
        deleted = await repo.delete_memory(payload.user_id, agent_profile_id=payload.agent_profile_id)
        return {"deleted": deleted, "errors": {}, "unsupported": False}
    ctx = memory_hub.context_for(
        user_id=payload.user_id,
        agent_profile_id=payload.agent_profile_id or "",
        agent_profile_slug=profile_slug or "",
        origin="api",
        scope_type="private",
        scope_id=f"private:{payload.agent_profile_id or payload.user_id}",
    )
    result = await memory_hub.forget(
        ctx,
        ProviderMemoryForgetRequest(
            selector=MemoryForgetSelector(
                user_id=payload.user_id,
                agent_profile_id=payload.agent_profile_id or "",
                provider_id=payload.provider_id,
                all_for_profile=True,
            )
        ),
    )
    return {"deleted": result.deleted, "errors": result.errors, "unsupported": result.unsupported}
