from __future__ import annotations

import asyncio
from typing import List

from .base import EventHandler, TransportAdapter


class TransportManager:
    def __init__(self, transports: List[TransportAdapter]) -> None:
        self.transports = transports
        self._handler: EventHandler | None = None

    def on_event(self, handler: EventHandler) -> None:
        self._handler = handler
        for transport in self.transports:
            transport.on_event(handler)

    async def start(self) -> None:
        await asyncio.gather(*(transport.start() for transport in self.transports))

    async def stop(self) -> None:
        await asyncio.gather(*(transport.stop() for transport in self.transports))
