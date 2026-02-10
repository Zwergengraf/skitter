from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from ..deps import get_repo
from ..schemas import (
    SessionCreate,
    SessionDetailOut,
    SessionListItem,
    SessionModelSetOut,
    SessionModelUpdate,
    SessionMessageOut,
    SessionOut,
    SessionToolRunOut,
)
from ...core.llm import list_models
from ...core.config import settings
from ...core.conversation_scope import private_scope_id
from ...core.sessions import SessionManager
from ...data.repositories import Repository

router = APIRouter(prefix="/v1/sessions", tags=["sessions"])


def _require_approved_user(approved: bool) -> None:
    if not approved:
        raise HTTPException(
            status_code=403,
            detail="Your account is not yet approved. An admin has to approve it first.",
        )


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
            transport=session.origin or "unknown",
            status=session.status,
            scope_type=session.scope_type or "private",
            scope_id=session.scope_id or "",
            last_active_at=last_active_at,
            total_tokens=session.total_tokens or 0,
            total_cost=session.total_cost or 0.0,
            last_input_tokens=session.last_input_tokens or 0,
        )
        for session, transport_user_id, last_active_at in sessions
    ]


@router.post("", response_model=SessionOut)
async def create_session(
    payload: SessionCreate,
    request: Request,
    repo: Repository = Depends(get_repo),
) -> SessionOut:
    user = await repo.get_or_create_user(payload.user_id)
    _require_approved_user(user.approved)
    origin = (payload.origin or "web").strip() or "web"
    scope_type = (payload.scope_type or "private").strip() or "private"
    scope_id = (payload.scope_id or "").strip()
    if not scope_id and scope_type == "private":
        scope_id = private_scope_id(user.id)
    if not scope_id:
        scope_id = f"{scope_type}:{user.id}"
    session = None
    if payload.reuse_active:
        session = await repo.get_active_session_by_scope(scope_type, scope_id)
    if session is None:
        if not payload.reuse_active:
            runtime = getattr(request.app.state, "runtime", None)
            if runtime is not None:
                manager = SessionManager(runtime, settings.workspace_root)
                _, new_session_id = await manager.start_new_session_for_scope(
                    user_id=user.id,
                    scope_type=scope_type,
                    scope_id=scope_id,
                    origin=origin,
                )
                session = await repo.get_session(new_session_id)
        if session is None:
            session = await repo.create_session(
                user.id,
                origin=origin,
                scope_type=scope_type,
                scope_id=scope_id,
            )
    return SessionOut(
        id=session.id,
        user_id=session.user_id,
        created_at=session.created_at,
        status=session.status,
        scope_type=session.scope_type or "private",
        scope_id=session.scope_id or "",
        model=session.model,
        input_tokens=session.input_tokens or 0,
        output_tokens=session.output_tokens or 0,
        total_tokens=session.total_tokens or 0,
        total_cost=session.total_cost or 0.0,
        last_input_tokens=session.last_input_tokens or 0,
        last_output_tokens=session.last_output_tokens or 0,
        last_total_tokens=session.last_total_tokens or 0,
        last_cost=session.last_cost or 0.0,
        last_model=session.last_model,
        last_usage_at=session.last_usage_at,
    )


@router.get("/{session_id}", response_model=SessionOut)
async def get_session(session_id: str, repo: Repository = Depends(get_repo)) -> SessionOut:
    session = await repo.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return SessionOut(
        id=session.id,
        user_id=session.user_id,
        created_at=session.created_at,
        status=session.status,
        scope_type=session.scope_type or "private",
        scope_id=session.scope_id or "",
        model=session.model,
        input_tokens=session.input_tokens or 0,
        output_tokens=session.output_tokens or 0,
        total_tokens=session.total_tokens or 0,
        total_cost=session.total_cost or 0.0,
        last_input_tokens=session.last_input_tokens or 0,
        last_output_tokens=session.last_output_tokens or 0,
        last_total_tokens=session.last_total_tokens or 0,
        last_cost=session.last_cost or 0.0,
        last_model=session.last_model,
        last_usage_at=session.last_usage_at,
    )


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
        scope_type=session.scope_type or "private",
        scope_id=session.scope_id or "",
        created_at=session.created_at,
        last_active_at=last_active_at,
        input_tokens=session.input_tokens or 0,
        output_tokens=session.output_tokens or 0,
        total_tokens=session.total_tokens or 0,
        total_cost=session.total_cost or 0.0,
        last_input_tokens=session.last_input_tokens or 0,
        last_output_tokens=session.last_output_tokens or 0,
        last_total_tokens=session.last_total_tokens or 0,
        last_cost=session.last_cost or 0.0,
        last_model=session.last_model,
        last_usage_at=session.last_usage_at,
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


@router.post("/{session_id}/model", response_model=SessionModelSetOut)
async def set_session_model(
    session_id: str,
    payload: SessionModelUpdate,
    request: Request,
    repo: Repository = Depends(get_repo),
) -> SessionModelSetOut:
    session = await repo.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    available = list_models()
    if not available:
        raise HTTPException(status_code=400, detail="No models configured")

    selected = None
    for model in available:
        if model.name.lower() == payload.model_name.lower():
            selected = model.name
            break
    if selected is None:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown model '{payload.model_name}'",
        )

    updated = await repo.set_session_model(session_id, selected)
    if updated is None:
        raise HTTPException(status_code=404, detail="Session not found")

    runtime = getattr(request.app.state, "runtime", None)
    if runtime is not None:
        runtime.set_session_model(session_id, selected)
    return SessionModelSetOut(session_id=session_id, model=selected)
