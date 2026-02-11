from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from ..authz import require_session_access
from ..deps import get_repo
from ...data.repositories import Repository

router = APIRouter(prefix="/v1/events", tags=["events"])


@router.get("/stream")
async def stream_events(session_id: str, request: Request, repo: Repository = Depends(get_repo)) -> StreamingResponse:
    await require_session_access(request, repo, session_id)
    event_bus = request.app.state.event_bus

    async def event_generator():
        async for event in event_bus.subscribe(session_id):
            if await request.is_disconnected():
                break
            payload = json.dumps(
                {"type": event.type, "data": event.data, "created_at": event.created_at.isoformat()}
            )
            yield f"event: {event.type}\n" f"data: {payload}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
