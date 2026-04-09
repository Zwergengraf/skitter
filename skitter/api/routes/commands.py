from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from ..authz import resolve_target_user_id
from ..deps import get_repo
from ..schemas import CommandExecuteOut, CommandExecuteRequest
from ...core.command_service import command_service
from ...data.repositories import Repository

router = APIRouter(prefix="/v1/commands", tags=["commands"])


@router.post("/execute", response_model=CommandExecuteOut)
async def execute_command(
    payload: CommandExecuteRequest,
    request: Request,
    repo: Repository = Depends(get_repo),
) -> CommandExecuteOut:
    command = (payload.command or "").strip().lower()
    if not command:
        raise HTTPException(status_code=400, detail="command is required")

    target_user_id = resolve_target_user_id(request, payload.user_id)
    user = await repo.get_user_by_id(target_user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    if not user.approved:
        raise HTTPException(
            status_code=403,
            detail="Your account is not yet approved. An admin has to approve it first.",
        )

    try:
        result = await command_service.execute(
            repo=repo,
            user=user,
            runtime=request.app.state.runtime,
            scheduler=request.app.state.scheduler_service,
            event_bus=request.app.state.event_bus,
            command=command,
            args=payload.args or {},
            origin=(payload.origin or "api").strip() or "api",
            agent_profile_id=payload.agent_profile_id,
            agent_profile_slug=payload.agent_profile_slug,
            transport_account_key=payload.transport_account_key,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc) or "Not found") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc) or "Invalid request") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc) or "Invalid request") from exc

    return CommandExecuteOut(ok=result.ok, message=result.message, data=result.data)
