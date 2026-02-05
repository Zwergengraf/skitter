from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request

from ..deps import get_repo
from ..schemas import MessageCreate, MessageOut
from ...core.models import MessageEnvelope
from ...data.repositories import Repository

router = APIRouter(prefix="/v1/messages", tags=["messages"])


@router.post("", response_model=MessageOut)
async def send_message(
    payload: MessageCreate,
    request: Request,
    repo: Repository = Depends(get_repo),
) -> MessageOut:
    session = await repo.get_session(payload.session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    envelope = MessageEnvelope(
        message_id=str(uuid.uuid4()),
        channel_id=payload.session_id,
        user_id=payload.user_id,
        timestamp=datetime.utcnow(),
        text=payload.text,
        origin="web",
        metadata=payload.metadata,
    )
    metadata = dict(payload.metadata)
    metadata.update(
        {
            "message_id": envelope.message_id,
            "origin": "web",
            "internal_user_id": session.user_id,
        }
    )
    await repo.add_message(payload.session_id, role="user", content=payload.text, metadata=metadata)

    envelope.metadata.update({"internal_user_id": session.user_id})

    runtime = request.app.state.runtime
    response = await runtime.handle_message(payload.session_id, envelope)
    assistant_msg = await repo.add_message(
        payload.session_id, role="assistant", content=response.text, metadata={"response_to": envelope.message_id}
    )
    return MessageOut(
        id=assistant_msg.id,
        session_id=assistant_msg.session_id,
        role=assistant_msg.role,
        content=assistant_msg.content,
        created_at=assistant_msg.created_at,
    )
