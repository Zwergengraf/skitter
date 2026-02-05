from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request

from ..deps import get_repo
from fastapi import HTTPException

from ..schemas import UserApprovalRequest, UserListItem
from ...data.repositories import Repository
from ...core.config import settings

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
async def update_user(
    user_id: str,
    payload: UserApprovalRequest,
    request: Request,
    repo: Repository = Depends(get_repo),
) -> dict:
    existing = await repo.get_user_by_id(user_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="User not found")
    was_approved = bool(existing.approved)
    user = await repo.set_user_approved(user_id, payload.approved)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    if payload.approved and not was_approved:
        notifier = getattr(request.app.state, "user_notifier", None)
        if notifier:
            message = settings.user_approved_message
            try:
                await notifier(user.transport_user_id, message, attachments=None)
            except Exception:
                pass
    return {"id": user.id, "approved": user.approved}
