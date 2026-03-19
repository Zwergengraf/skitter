from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional

from ..core.events import EventBus
from ..core.models import StreamEvent
from ..data.db import SessionLocal
from ..data.repositories import Repository

_logger = logging.getLogger(__name__)

UserPromptNotifier = Callable[[str, str, str, list[str], bool], Awaitable[None]]


def _looks_like_discord_channel_id(channel_id: str) -> bool:
    value = (channel_id or "").strip()
    return bool(value and value.isdigit())


@dataclass(slots=True)
class UserPromptRequest:
    prompt_id: str
    session_id: str
    question: str
    choices: list[str]
    allow_free_text: bool


class UserPromptService:
    def __init__(self, event_bus: EventBus, notifier: Optional[UserPromptNotifier] = None) -> None:
        self.event_bus = event_bus
        self._notifier = notifier

    def set_notifier(self, notifier: Optional[UserPromptNotifier]) -> None:
        self._notifier = notifier

    async def request(
        self,
        *,
        session_id: str,
        channel_id: str,
        question: str,
        choices: list[str] | None = None,
        allow_free_text: bool = True,
        run_id: str | None = None,
        message_id: str | None = None,
    ) -> UserPromptRequest:
        async with SessionLocal() as session:
            repo = Repository(session)
            prompt = await repo.create_user_prompt(
                session_id=session_id,
                question=question,
                choices=choices or [],
                allow_free_text=allow_free_text,
                run_id=run_id,
                message_id=message_id,
            )

        payload = {
            "prompt_id": prompt.id,
            "question": prompt.question,
            "choices": list(prompt.choices or []),
            "allow_free_text": bool(prompt.allow_free_text),
        }
        await self.event_bus.publish(
            StreamEvent(
                session_id=session_id,
                type="user_prompt_requested",
                data=payload,
            )
        )
        if self._notifier is not None and _looks_like_discord_channel_id(channel_id):
            try:
                await self._notifier(
                    prompt.id,
                    channel_id,
                    prompt.question,
                    list(prompt.choices or []),
                    bool(prompt.allow_free_text),
                )
            except Exception:
                _logger.exception(
                    "Failed to deliver user prompt request (prompt_id=%s, channel_id=%s)",
                    prompt.id,
                    channel_id,
                )

        return UserPromptRequest(
            prompt_id=prompt.id,
            session_id=session_id,
            question=prompt.question,
            choices=list(prompt.choices or []),
            allow_free_text=bool(prompt.allow_free_text),
        )
