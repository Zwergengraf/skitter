from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Awaitable, Callable, Iterable

from ..core.models import Attachment, MessageEnvelope


EventHandler = Callable[[MessageEnvelope], Awaitable[None]]
RuntimeStateCallback = Callable[[dict[str, object]], Awaitable[None]]


class TransportAdapter(ABC):
    _runtime_state_callback: RuntimeStateCallback | None = None

    @property
    @abstractmethod
    def origin(self) -> str:
        raise NotImplementedError

    @property
    @abstractmethod
    def account_key(self) -> str:
        raise NotImplementedError

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

    def set_runtime_state_callback(self, callback: RuntimeStateCallback | None) -> None:
        self._runtime_state_callback = callback

    async def send_user_message(
        self,
        user_id: str,
        content: str,
        attachments: Iterable[Attachment] | None = None,
        metadata: dict | None = None,
    ) -> None:
        raise RuntimeError(f"{self.origin} transport does not support direct user messages.")

    async def send_approval_request(
        self,
        tool_run_id: str,
        channel_id: str,
        tool_name: str,
        payload: dict,
    ) -> None:
        raise RuntimeError(f"{self.origin} transport does not support approval requests.")

    async def send_user_prompt_request(
        self,
        prompt_id: str,
        channel_id: str,
        question: str,
        choices: list[str],
        allow_free_text: bool,
    ) -> None:
        raise RuntimeError(f"{self.origin} transport does not support user prompts.")
