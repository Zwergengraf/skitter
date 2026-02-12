from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from ..authz import require_tool_run_access
from ..deps import get_repo
from ..security import get_auth_principal
from ..schemas import ToolApprovalRequest, ToolRunListItem
from ...data.repositories import Repository

router = APIRouter(prefix="/v1/tools", tags=["tools"])


@router.get("", response_model=list[ToolRunListItem])
async def list_tool_runs(
    request: Request,
    repo: Repository = Depends(get_repo),
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[ToolRunListItem]:
    principal = get_auth_principal(request)
    if principal.is_user:
        tool_runs = await repo.list_tool_runs_for_user(principal.user_id or "", limit=limit, status=status)
    else:
        tool_runs = await repo.list_tool_runs(limit=limit, status=status)
    run_ids = [tool_run.run_id for tool_run, _ in tool_runs if tool_run.run_id]
    reasoning_by_run = await repo.get_reasoning_by_run_ids([str(run_id) for run_id in run_ids])
    return [
        ToolRunListItem(
            id=tool_run.id,
            run_id=tool_run.run_id,
            tool=tool_run.tool_name,
            status=tool_run.status,
            requested_by=transport_user_id,
            created_at=tool_run.created_at,
            session_id=tool_run.session_id,
            approved_by=tool_run.approved_by,
            input=tool_run.input or {},
            output=tool_run.output or {},
            reasoning=reasoning_by_run.get(str(tool_run.run_id), []) if tool_run.run_id else [],
        )
        for tool_run, transport_user_id in tool_runs
    ]


@router.post("/{tool_run_id}/approve")
async def approve_tool_run(
    tool_run_id: str,
    payload: ToolApprovalRequest,
    request: Request,
    repo: Repository = Depends(get_repo),
) -> dict:
    principal = get_auth_principal(request)
    tool_run, _session = await require_tool_run_access(request, repo, tool_run_id)
    decided_by = payload.approved_by
    if principal.is_user:
        decided_by = principal.user_id or payload.approved_by
    approval_service = getattr(request.app.state, "approval_service", None)
    if approval_service is not None:
        resolved = await approval_service.resolve(tool_run_id, approved=True, decided_by=decided_by)
        if not resolved:
            raise HTTPException(status_code=404, detail="Tool run not found")
        return {"id": tool_run_id, "status": "approved", "approved_by": decided_by}

    tool_run = await repo.approve_tool_run(tool_run.id, decided_by)
    if tool_run is None:
        raise HTTPException(status_code=404, detail="Tool run not found")
    return {"id": tool_run.id, "status": tool_run.status, "approved_by": tool_run.approved_by}


@router.post("/{tool_run_id}/deny")
async def deny_tool_run(
    tool_run_id: str,
    payload: ToolApprovalRequest,
    request: Request,
    repo: Repository = Depends(get_repo),
) -> dict:
    principal = get_auth_principal(request)
    tool_run, _session = await require_tool_run_access(request, repo, tool_run_id)
    decided_by = payload.approved_by
    if principal.is_user:
        decided_by = principal.user_id or payload.approved_by
    approval_service = getattr(request.app.state, "approval_service", None)
    if approval_service is not None:
        resolved = await approval_service.resolve(tool_run_id, approved=False, decided_by=decided_by)
        if not resolved:
            raise HTTPException(status_code=404, detail="Tool run not found")
        return {"id": tool_run_id, "status": "denied", "approved_by": decided_by}

    tool_run = await repo.deny_tool_run(tool_run.id, decided_by)
    if tool_run is None:
        raise HTTPException(status_code=404, detail="Tool run not found")
    return {"id": tool_run.id, "status": tool_run.status, "approved_by": tool_run.approved_by}
