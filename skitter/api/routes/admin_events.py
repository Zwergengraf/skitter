from __future__ import annotations

import json

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse

from ..authz import require_admin
from ..schemas import AdminEventOut

router = APIRouter(prefix="/v1/admin/events", tags=["admin-events"])


@router.get("/recent", response_model=list[AdminEventOut])
async def list_recent_admin_events(
    request: Request,
    limit: int = Query(default=200, ge=1, le=5000),
) -> list[AdminEventOut]:
    require_admin(request)
    event_bus = request.app.state.event_bus
    return [AdminEventOut(**event.__dict__) for event in event_bus.recent_admin_events(limit)]


@router.get("/stream")
async def stream_admin_events(request: Request) -> StreamingResponse:
    require_admin(request)
    event_bus = request.app.state.event_bus

    async def event_generator():
        yield ": connected\n\n"
        async for event in event_bus.subscribe_admin():
            if await request.is_disconnected():
                break
            payload = json.dumps(AdminEventOut(**event.__dict__).model_dump(mode="json"))
            yield f"event: {event.kind}\n" f"data: {payload}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
