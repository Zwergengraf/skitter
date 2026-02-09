import asyncio
from datetime import UTC, datetime

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
    # Ensure the subscriber queue is registered before publishing,
    # otherwise publish can race and drop the event.
    for _ in range(100):
        if bus._queues.get(session_id):
            break
        await asyncio.sleep(0)
    assert bus._queues.get(session_id)

    await bus.publish(StreamEvent(session_id=session_id, type="test", data={}, created_at=datetime.now(UTC)))
    result = await asyncio.wait_for(task, timeout=1.0)
    assert result.type == "test"
