from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request

from ..authz import require_admin
from ..deps import get_repo
from fastapi import HTTPException

from ..schemas import UserApprovalRequest, UserListItem
from ...data.repositories import Repository
from ...core.config import settings

router = APIRouter(prefix="/v1/users", tags=["users"])
PENDING_REQUEST_TTL_MINUTES = 15


@router.get("", response_model=list[UserListItem])
async def list_users(
    request: Request,
    repo: Repository = Depends(get_repo),
    limit: int = Query(default=200, ge=1, le=500),
) -> list[UserListItem]:
    require_admin(request)
    await repo.delete_stale_pending_users(PENDING_REQUEST_TTL_MINUTES)
    users = await repo.list_users(limit=limit)
    items: list[UserListItem] = []
    for user in users:
        default_profile = await repo.get_default_agent_profile(user.id)
        items.append(
            UserListItem(
                id=user.id,
                transport_user_id=user.transport_user_id,
                display_name=user.display_name or (user.meta or {}).get("display_name"),
                username=(user.meta or {}).get("username"),
                avatar_url=(user.meta or {}).get("avatar_url"),
                approved=user.approved,
                default_profile_id=getattr(default_profile, "id", None),
                default_profile_slug=getattr(default_profile, "slug", None),
            )
        )
    return items


@router.patch("/{user_id}")
async def update_user(
    user_id: str,
    payload: UserApprovalRequest,
    request: Request,
    repo: Repository = Depends(get_repo),
) -> dict:
    require_admin(request)
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


@router.delete("/{user_id}")
async def deny_user(
    user_id: str,
    request: Request,
    repo: Repository = Depends(get_repo),
) -> dict:
    require_admin(request)
    existing = await repo.get_user_by_id(user_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="User not found")
    if existing.approved:
        raise HTTPException(status_code=400, detail="Approved users cannot be denied")
    deleted = await repo.delete_pending_user(user_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="User not found")
    return {"id": user_id, "deleted": True}
