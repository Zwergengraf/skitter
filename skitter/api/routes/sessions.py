from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from ..authz import require_admin, require_session_access, resolve_target_user_id
from ..deps import get_repo
from ..schemas import (
    CommandExecuteOut,
    SessionCreate,
    SessionDetailOut,
    SessionListItem,
    SessionModelSetOut,
    SessionModelUpdate,
    SessionMessageOut,
    SessionOut,
    SessionToolRunOut,
    SessionUserPromptOut,
)
from ...core.llm import list_models, resolve_model_name
from ...core.conversation_scope import private_scope_id
from ...core.profile_service import profile_service
from ...core.models import StreamEvent
from ...core.sessions import SessionManager
from ...data.repositories import Repository

router = APIRouter(prefix="/v1/sessions", tags=["sessions"])


def _require_approved_user(approved: bool) -> None:
    if not approved:
        raise HTTPException(
            status_code=403,
            detail="Your account is not yet approved. An admin has to approve it first.",
        )


async def _session_profile(repo: Repository, session) -> object | None:
    profile_id = str(getattr(session, "agent_profile_id", "") or "").strip()
    if profile_id:
        profile = await repo.get_agent_profile(profile_id)
        if profile is not None:
            return profile
    return await repo.get_default_agent_profile(session.user_id)


@router.get("", response_model=list[SessionListItem])
async def list_sessions(
    request: Request,
    repo: Repository = Depends(get_repo),
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[SessionListItem]:
    require_admin(request)
    sessions = await repo.list_sessions(limit=limit, status=status)
    items: list[SessionListItem] = []
    for session, transport_user_id, last_active_at in sessions:
        profile = await _session_profile(repo, session)
        items.append(
            SessionListItem(
                id=session.id,
                user=transport_user_id,
                transport=session.origin or "unknown",
                agent_profile_id=getattr(session, "agent_profile_id", None),
                agent_profile_slug=getattr(profile, "slug", None),
                status=session.status,
                scope_type=session.scope_type or "private",
                scope_id=session.scope_id or "",
                last_active_at=last_active_at,
                total_tokens=session.total_tokens or 0,
                total_cost=session.total_cost or 0.0,
                last_input_tokens=session.last_input_tokens or 0,
            )
        )
    return items


@router.post("", response_model=SessionOut)
async def create_session(
    payload: SessionCreate,
    request: Request,
    repo: Repository = Depends(get_repo),
) -> SessionOut:
    target_user_id = resolve_target_user_id(request, payload.user_id)
    user = await repo.get_user_by_id(target_user_id)
    if user is None and payload.user_id:
        user = await repo.get_or_create_user(payload.user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    _require_approved_user(user.approved)
    origin = (payload.origin or "web").strip() or "web"
    profile = await profile_service.resolve_profile(
        repo,
        user.id,
        agent_profile_id=payload.agent_profile_id,
        agent_profile_slug=payload.agent_profile_slug,
        origin=origin,
    )
    scope_type = (payload.scope_type or "private").strip() or "private"
    scope_id = (payload.scope_id or "").strip()
    if not scope_id and scope_type == "private":
        scope_id = private_scope_id(profile.id)
    if not scope_id:
        scope_id = f"{scope_type}:{user.id}"
    session = None
    previous_active_id: str | None = None
    if not payload.reuse_active:
        previous = await repo.get_active_session_by_scope(scope_type, scope_id, agent_profile_id=profile.id)
        if previous is not None:
            previous_active_id = previous.id
    if payload.reuse_active:
        session = await repo.get_active_session_by_scope(scope_type, scope_id, agent_profile_id=profile.id)
    if session is None:
        if not payload.reuse_active:
            runtime = getattr(request.app.state, "runtime", None)
            if runtime is not None:
                manager = SessionManager(runtime)
                _, new_session_id = await manager.start_new_session_for_scope(
                    user_id=user.id,
                    agent_profile_id=profile.id,
                    agent_profile_slug=profile.slug,
                    scope_type=scope_type,
                    scope_id=scope_id,
                    origin=origin,
                )
                session = await repo.get_session(new_session_id)
        if session is None:
            session = await repo.create_session(
                user.id,
                agent_profile_id=profile.id,
                origin=origin,
                scope_type=scope_type,
                scope_id=scope_id,
            )
    if not payload.reuse_active and previous_active_id and previous_active_id != session.id:
        event_bus = getattr(request.app.state, "event_bus", None)
        if event_bus is not None:
            event_payload = {
                "old_session_id": previous_active_id,
                "new_session_id": session.id,
                "scope_type": scope_type,
                "scope_id": scope_id,
                "initiated_by_origin": origin,
            }
            now = datetime.now(UTC)
            await event_bus.publish(
                StreamEvent(
                    session_id=previous_active_id,
                    type="session_switched",
                    data=event_payload,
                    created_at=now,
                )
            )
            await event_bus.publish(
                StreamEvent(
                    session_id=session.id,
                    type="session_switched",
                    data=event_payload,
                    created_at=now,
                )
            )
    return SessionOut(
        id=session.id,
        user_id=session.user_id,
        agent_profile_id=getattr(session, "agent_profile_id", None),
        agent_profile_slug=profile.slug,
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
async def get_session(session_id: str, request: Request, repo: Repository = Depends(get_repo)) -> SessionOut:
    session = await require_session_access(request, repo, session_id)
    profile = await _session_profile(repo, session)
    return SessionOut(
        id=session.id,
        user_id=session.user_id,
        agent_profile_id=getattr(session, "agent_profile_id", None),
        agent_profile_slug=getattr(profile, "slug", None),
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
async def get_session_detail(session_id: str, request: Request, repo: Repository = Depends(get_repo)) -> SessionDetailOut:
    session = await require_session_access(request, repo, session_id)
    user = await repo.get_user_by_id(session.user_id)
    profile = await _session_profile(repo, session)
    messages = await repo.list_messages(session_id)
    tool_runs = await repo.list_tool_runs_by_session(session_id)
    pending_user_prompts = await repo.list_pending_user_prompts(session_id=session_id, limit=20)
    last_active_at = messages[-1].created_at if messages else None
    return SessionDetailOut(
        id=session.id,
        user_id=session.user_id,
        agent_profile_id=getattr(session, "agent_profile_id", None),
        agent_profile_slug=getattr(profile, "slug", None),
        user=(user.display_name or user.transport_user_id) if user else session.user_id,
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
        summary_status=session.summary_status,
        summary_attempts=session.summary_attempts,
        summary_next_retry_at=session.summary_next_retry_at,
        summary_last_error=session.summary_last_error,
        summary_path=session.summary_path,
        summary_completed_at=session.summary_completed_at,
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
                executor_id=tool_run.executor_id,
                input=tool_run.input or {},
                output=tool_run.output or {},
                approved_by=tool_run.approved_by,
                created_at=tool_run.created_at,
            )
            for tool_run in tool_runs
        ],
        pending_user_prompts=[
            SessionUserPromptOut(
                id=prompt.id,
                question=prompt.question,
                choices=list(prompt.choices or []),
                allow_free_text=bool(prompt.allow_free_text),
                status=prompt.status,
                created_at=prompt.created_at,
            )
            for prompt in pending_user_prompts
        ],
    )


@router.post("/{session_id}/stop", response_model=CommandExecuteOut)
async def stop_session_run(
    session_id: str,
    request: Request,
    repo: Repository = Depends(get_repo),
) -> CommandExecuteOut:
    session = await require_session_access(request, repo, session_id)
    principal = getattr(request.state, "auth_principal", None)
    requested_by = getattr(principal, "user_id", None) or session.user_id
    discarded_pending = 0
    queue = getattr(request.app.state, "session_run_queue", None)
    if queue is not None and hasattr(queue, "cancel_session"):
        queue_result = await queue.cancel_session(session_id, cancel_active=False)
        discarded_pending = int(queue_result.get("discarded_pending") or 0)
    runtime = getattr(request.app.state, "runtime", None)
    stopped_active = False
    if runtime is not None and hasattr(runtime, "cancel_session_run"):
        stopped_active = bool(
            runtime.cancel_session_run(
                session_id,
                requested_by=requested_by,
                reason="User requested stop.",
                discarded_pending=discarded_pending,
            )
        )
    if not stopped_active and queue is not None and hasattr(queue, "cancel_session"):
        queue_result = await queue.cancel_session(session_id, cancel_active=True)
        discarded_pending = max(discarded_pending, int(queue_result.get("discarded_pending") or 0))
        stopped_active = bool(queue_result.get("active"))
    cancelled_prompt = await repo.cancel_pending_user_prompt_for_session(
        session_id,
        cancelled_by=requested_by,
        reason="Stopped by user.",
    )
    if stopped_active:
        message = "Stopping the current turn."
    elif discarded_pending:
        message = f"Stopped {discarded_pending} pending queued turn{'s' if discarded_pending != 1 else ''}."
    elif cancelled_prompt is not None:
        message = "Cancelled the pending user prompt."
    else:
        message = "No active turn is running for this session."
    return CommandExecuteOut(
        ok=bool(stopped_active or discarded_pending or cancelled_prompt is not None),
        message=message,
        data={
            "stopped": bool(stopped_active),
            "discarded_pending": discarded_pending,
            "cancelled_prompt_id": getattr(cancelled_prompt, "id", None),
            "session_id": session_id,
        },
    )


@router.post("/{session_id}/model", response_model=SessionModelSetOut)
async def set_session_model(
    session_id: str,
    payload: SessionModelUpdate,
    request: Request,
    repo: Repository = Depends(get_repo),
) -> SessionModelSetOut:
    await require_session_access(request, repo, session_id)

    available = list_models()
    if not available:
        raise HTTPException(status_code=400, detail="No models configured")

    requested_name = resolve_model_name(payload.model_name, purpose="main")
    selected = None
    for model in available:
        if model.name.lower() == requested_name.lower():
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
