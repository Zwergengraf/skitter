from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from ..deps import get_repo
from ..schemas import (
    SessionCreate,
    SessionDetailOut,
    SessionListItem,
    SessionMessageOut,
    SessionOut,
    SessionToolRunOut,
)
from ...data.repositories import Repository

router = APIRouter(prefix="/v1/sessions", tags=["sessions"])


@router.get("", response_model=list[SessionListItem])
async def list_sessions(
    repo: Repository = Depends(get_repo),
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[SessionListItem]:
    sessions = await repo.list_sessions(limit=limit, status=status)
    return [
        SessionListItem(
            id=session.id,
            user=transport_user_id,
            transport="discord",
            status=session.status,
            last_active_at=last_active_at,
        )
        for session, transport_user_id, last_active_at in sessions
    ]


@router.post("", response_model=SessionOut)
async def create_session(payload: SessionCreate, repo: Repository = Depends(get_repo)) -> SessionOut:
    user = await repo.get_or_create_user(payload.user_id)
    session = await repo.create_session(user.id)
    return SessionOut(id=session.id, user_id=session.user_id, created_at=session.created_at, status=session.status)


@router.get("/{session_id}", response_model=SessionOut)
async def get_session(session_id: str, repo: Repository = Depends(get_repo)) -> SessionOut:
    session = await repo.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return SessionOut(id=session.id, user_id=session.user_id, created_at=session.created_at, status=session.status)


@router.get("/{session_id}/detail", response_model=SessionDetailOut)
async def get_session_detail(session_id: str, repo: Repository = Depends(get_repo)) -> SessionDetailOut:
    session = await repo.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    user = await repo.get_user_by_id(session.user_id)
    messages = await repo.list_messages(session_id)
    tool_runs = await repo.list_tool_runs_by_session(session_id)
    last_active_at = messages[-1].created_at if messages else None
    return SessionDetailOut(
        id=session.id,
        user_id=session.user_id,
        user=user.transport_user_id if user else session.user_id,
        status=session.status,
        created_at=session.created_at,
        last_active_at=last_active_at,
        messages=[
            SessionMessageOut(
                id=message.id,
                role=message.role,
                content=message.content,
                created_at=message.created_at,
                meta=message.meta or {},
            )
            for message in messages
        ],
        tool_runs=[
            SessionToolRunOut(
                id=tool_run.id,
                tool=tool_run.tool_name,
                status=tool_run.status,
                input=tool_run.input or {},
                output=tool_run.output or {},
                approved_by=tool_run.approved_by,
                created_at=tool_run.created_at,
            )
            for tool_run in tool_runs
        ],
    )
