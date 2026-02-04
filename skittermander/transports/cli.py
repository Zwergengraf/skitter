from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Iterable

from ..core.models import Attachment, MessageEnvelope
from .base import EventHandler, TransportAdapter


class CliTransport(TransportAdapter):
    def __init__(self) -> None:
        self._handler: EventHandler | None = None
        self._running = False

    def on_event(self, handler: EventHandler) -> None:
        self._handler = handler

    async def start(self) -> None:
        self._running = True
        await self._loop()

    async def stop(self) -> None:
        self._running = False

    async def send_message(
        self,
        channel_id: str,
        content: str,
        attachments: Iterable[Attachment] | None = None,
        metadata: dict | None = None,
    ) -> None:
        print(content)

    async def send_typing(self, channel_id: str) -> None:
        return

    async def _loop(self) -> None:
        if self._handler is None:
            raise RuntimeError("CLI handler not set")
        while self._running:
            text = await asyncio.get_event_loop().run_in_executor(None, input, "> ")
            envelope = MessageEnvelope(
                message_id="cli",
                channel_id="cli",
                user_id="cli",
                timestamp=datetime.utcnow(),
                text=text,
                origin="cli",
            )
            await self._handler(envelope)
