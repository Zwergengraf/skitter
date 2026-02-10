from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from ..deps import get_repo
from ..schemas import ToolApprovalRequest, ToolRunListItem
from ...data.repositories import Repository

router = APIRouter(prefix="/v1/tools", tags=["tools"])


@router.get("", response_model=list[ToolRunListItem])
async def list_tool_runs(
    repo: Repository = Depends(get_repo),
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[ToolRunListItem]:
    tool_runs = await repo.list_tool_runs(limit=limit, status=status)
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
    approval_service = getattr(request.app.state, "approval_service", None)
    if approval_service is not None:
        resolved = await approval_service.resolve(tool_run_id, approved=True, decided_by=payload.approved_by)
        if not resolved:
            raise HTTPException(status_code=404, detail="Tool run not found")
        return {"id": tool_run_id, "status": "approved", "approved_by": payload.approved_by}

    tool_run = await repo.approve_tool_run(tool_run_id, payload.approved_by)
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
    approval_service = getattr(request.app.state, "approval_service", None)
    if approval_service is not None:
        resolved = await approval_service.resolve(tool_run_id, approved=False, decided_by=payload.approved_by)
        if not resolved:
            raise HTTPException(status_code=404, detail="Tool run not found")
        return {"id": tool_run_id, "status": "denied", "approved_by": payload.approved_by}

    tool_run = await repo.deny_tool_run(tool_run_id, payload.approved_by)
    if tool_run is None:
        raise HTTPException(status_code=404, detail="Tool run not found")
    return {"id": tool_run.id, "status": tool_run.status, "approved_by": tool_run.approved_by}
