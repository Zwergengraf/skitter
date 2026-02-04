from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Awaitable, Callable, Iterable

from ..core.models import Attachment, MessageEnvelope


EventHandler = Callable[[MessageEnvelope], Awaitable[None]]


class TransportAdapter(ABC):
    @abstractmethod
    async def start(self) -> None:
        raise NotImplementedError

    @abstractmethod
    async def stop(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def on_event(self, handler: EventHandler) -> None:
        raise NotImplementedError

    @abstractmethod
    async def send_message(
        self,
        channel_id: str,
        content: str,
        attachments: Iterable[Attachment] | None = None,
        metadata: dict | None = None,
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    async def send_typing(self, channel_id: str) -> None:
        raise NotImplementedError
