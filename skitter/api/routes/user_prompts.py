from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request

from ..authz import require_session_access
from ..deps import get_repo
from ..schemas import UserPromptOut
from ...data.repositories import Repository

router = APIRouter(prefix="/v1/user-prompts", tags=["user-prompts"])


@router.get("", response_model=list[UserPromptOut])
async def list_user_prompts(
    request: Request,
    session_id: str = Query(...),
    repo: Repository = Depends(get_repo),
) -> list[UserPromptOut]:
    session = await require_session_access(request, repo, session_id)
    prompts = await repo.list_pending_user_prompts(session_id=session.id, limit=50)
    return [
        UserPromptOut(
            id=prompt.id,
            session_id=prompt.session_id,
            question=prompt.question,
            choices=list(prompt.choices or []),
            allow_free_text=bool(prompt.allow_free_text),
            status=prompt.status,
            created_at=prompt.created_at,
        )
        for prompt in prompts
    ]
