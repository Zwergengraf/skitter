from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ..deps import get_repo
from ..schemas import SessionCreate, SessionOut
from ...data.repositories import Repository

router = APIRouter(prefix="/v1/sessions", tags=["sessions"])


@router.post("", response_model=SessionOut)
async def create_session(payload: SessionCreate, repo: Repository = Depends(get_repo)) -> SessionOut:
    user = await repo.get_or_create_user(payload.user_id)
    session = await repo.create_session(user.id)
    return SessionOut(id=session.id, user_id=session.user_id, created_at=session.created_at, status=session.status)


@router.get("/{session_id}", response_model=SessionOut)
async def get_session(session_id: str, repo: Repository = Depends(get_repo)) -> SessionOut:
    session = await repo.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return SessionOut(id=session.id, user_id=session.user_id, created_at=session.created_at, status=session.status)
