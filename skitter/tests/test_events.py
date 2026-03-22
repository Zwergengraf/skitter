import asyncio
from datetime import UTC, datetime

import pytest

from skitter.core.events import EventBus
from skitter.core.models import AdminEvent, StreamEvent


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


@pytest.mark.asyncio
async def test_event_bus_keeps_recent_admin_events() -> None:
    bus = EventBus(admin_buffer_size=2)

    await bus.publish_admin(AdminEvent(kind="one", title="One", message="first"))
    await bus.publish_admin(AdminEvent(kind="two", title="Two", message="second"))
    await bus.publish_admin(AdminEvent(kind="three", title="Three", message="third"))

    recent = bus.recent_admin_events()
    assert [event.kind for event in recent] == ["two", "three"]
