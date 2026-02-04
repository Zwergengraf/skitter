from __future__ import annotations

from fastapi import APIRouter, Depends

from ..deps import get_repo
from ..schemas import MemoryForgetRequest
from ...data.repositories import Repository

router = APIRouter(prefix="/v1/memory", tags=["memory"])


@router.post("/forget")
async def forget_memory(payload: MemoryForgetRequest, repo: Repository = Depends(get_repo)) -> dict:
    deleted = await repo.delete_memory(payload.user_id)
    return {"deleted": deleted}
