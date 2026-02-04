from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ..deps import get_repo
from ..schemas import ToolApprovalRequest
from ...data.repositories import Repository

router = APIRouter(prefix="/v1/tools", tags=["tools"])


@router.post("/{tool_run_id}/approve")
async def approve_tool_run(
    tool_run_id: str, payload: ToolApprovalRequest, repo: Repository = Depends(get_repo)
) -> dict:
    tool_run = await repo.approve_tool_run(tool_run_id, payload.approved_by)
    if tool_run is None:
        raise HTTPException(status_code=404, detail="Tool run not found")
    return {"id": tool_run.id, "status": tool_run.status, "approved_by": tool_run.approved_by}
