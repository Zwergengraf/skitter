from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from typing import Any, AsyncIterator, Dict, List

from .models import AdminEvent, StreamEvent


class EventBus:
    def __init__(self, admin_buffer_size: int = 1000) -> None:
        self._queues: Dict[str, List[asyncio.Queue[StreamEvent]]] = defaultdict(list)
        self._admin_queues: list[asyncio.Queue[AdminEvent]] = []
        self._admin_buffer = deque(maxlen=max(1, int(admin_buffer_size)))

    async def publish(self, event: StreamEvent) -> None:
        queues = list(self._queues.get(event.session_id, []))
        for queue in queues:
            self._queue_with_drop(queue, event)

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

    async def publish_admin(self, event: AdminEvent) -> None:
        self._admin_buffer.append(event)
        for queue in list(self._admin_queues):
            self._queue_with_drop(queue, event)

    async def emit_admin(
        self,
        *,
        kind: str,
        title: str,
        message: str,
        level: str = "info",
        data: dict[str, Any] | None = None,
        session_id: str | None = None,
        user_id: str | None = None,
        run_id: str | None = None,
        job_id: str | None = None,
        tool_run_id: str | None = None,
        executor_id: str | None = None,
        transport: str | None = None,
    ) -> AdminEvent:
        event = AdminEvent(
            kind=kind,
            title=title,
            message=message,
            level=level,
            data=data or {},
            session_id=session_id,
            user_id=user_id,
            run_id=run_id,
            job_id=job_id,
            tool_run_id=tool_run_id,
            executor_id=executor_id,
            transport=transport,
        )
        await self.publish_admin(event)
        return event

    def recent_admin_events(self, limit: int | None = None) -> list[AdminEvent]:
        items = list(self._admin_buffer)
        if limit is None or limit <= 0 or limit >= len(items):
            return items
        return items[-limit:]

    async def subscribe_admin(self) -> AsyncIterator[AdminEvent]:
        queue: asyncio.Queue[AdminEvent] = asyncio.Queue(maxsize=512)
        self._admin_queues.append(queue)
        try:
            while True:
                event = await queue.get()
                yield event
        finally:
            if queue in self._admin_queues:
                self._admin_queues.remove(queue)

    @staticmethod
    def _queue_with_drop(queue: asyncio.Queue, event: Any) -> None:
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                pass
