import asyncio
from datetime import datetime

import pytest

from skittermander.core.events import EventBus
from skittermander.core.models import StreamEvent


@pytest.mark.asyncio
async def test_event_bus_publish_subscribe() -> None:
    bus = EventBus()
    session_id = "session-1"

    async def reader():
        async for event in bus.subscribe(session_id):
            return event

    task = asyncio.create_task(reader())
    await bus.publish(StreamEvent(session_id=session_id, type="test", data={}, created_at=datetime.utcnow()))
    result = await task
    assert result.type == "test"
