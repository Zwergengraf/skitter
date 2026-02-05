from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from ..deps import get_repo
from fastapi import HTTPException

from ..schemas import UserApprovalRequest, UserListItem
from ...data.repositories import Repository

router = APIRouter(prefix="/v1/users", tags=["users"])


@router.get("", response_model=list[UserListItem])
async def list_users(
    repo: Repository = Depends(get_repo),
    limit: int = Query(default=200, ge=1, le=500),
) -> list[UserListItem]:
    users = await repo.list_users(limit=limit)
    return [
        UserListItem(
            id=user.id,
            transport_user_id=user.transport_user_id,
            display_name=(user.meta or {}).get("display_name"),
            username=(user.meta or {}).get("username"),
            avatar_url=(user.meta or {}).get("avatar_url"),
            approved=user.approved,
        )
        for user in users
    ]


@router.patch("/{user_id}")
async def update_user(user_id: str, payload: UserApprovalRequest, repo: Repository = Depends(get_repo)) -> dict:
    user = await repo.set_user_approved(user_id, payload.approved)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return {"id": user.id, "approved": user.approved}
