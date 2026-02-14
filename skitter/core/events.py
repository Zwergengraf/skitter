from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import AsyncIterator, Dict, List

from .models import StreamEvent


class EventBus:
    def __init__(self) -> None:
        self._queues: Dict[str, List[asyncio.Queue[StreamEvent]]] = defaultdict(list)

    async def publish(self, event: StreamEvent) -> None:
        queues = list(self._queues.get(event.session_id, []))
        for queue in queues:
            await queue.put(event)

    async def subscribe(self, session_id: str) -> AsyncIterator[StreamEvent]:
        queue: asyncio.Queue[StreamEvent] = asyncio.Queue(maxsize=256)
        self._queues[session_id].append(queue)
        try:
            while True:
                event = await queue.get()
                yield event
        finally:
            self._queues[session_id].remove(queue)
            if not self._queues[session_id]:
                self._queues.pop(session_id, None)
