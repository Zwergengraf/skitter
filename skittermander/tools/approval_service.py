from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, Optional

from ..core.events import EventBus
from ..core.models import StreamEvent
from ..data.db import SessionLocal
from ..data.repositories import Repository


ApprovalNotifier = Callable[[str, str, str, Dict[str, Any]], Awaitable[None]]


@dataclass
class ApprovalDecision:
    tool_run_id: str
    approved: bool


class ToolApprovalService:
    def __init__(self, event_bus: EventBus, notifier: Optional[ApprovalNotifier] = None) -> None:
        self.event_bus = event_bus
        self._notifier = notifier
        self._pending: dict[str, asyncio.Future[bool]] = {}

    def set_notifier(self, notifier: Optional[ApprovalNotifier]) -> None:
        self._notifier = notifier

    async def request(
        self,
        session_id: str,
        channel_id: str,
        tool_name: str,
        payload: Dict[str, Any],
        requested_by: str,
    ) -> ApprovalDecision:
        async with SessionLocal() as session:
            repo = Repository(session)
            tool_run = await repo.create_tool_run(
                session_id=session_id,
                tool_name=tool_name,
                status="pending",
                input_payload=payload,
                approved_by=None,
            )

        future: asyncio.Future[bool] = asyncio.get_event_loop().create_future()
        self._pending[tool_run.id] = future

        await self.event_bus.publish(
            StreamEvent(
                session_id=session_id,
                type="tool_approval_requested",
                data={
                    "tool_run_id": tool_run.id,
                    "tool_name": tool_name,
                    "payload": payload,
                    "channel_id": channel_id,
                    "requested_by": requested_by,
                },
            )
        )

        if self._notifier is not None:
            await self._notifier(tool_run.id, channel_id, tool_name, payload)
        else:
            # If no notifier is configured, auto-approve to avoid blocking.
            future.set_result(True)

        approved = await future
        return ApprovalDecision(tool_run_id=tool_run.id, approved=approved)

    async def resolve(self, tool_run_id: str, approved: bool, decided_by: str) -> bool:
        future = self._pending.pop(tool_run_id, None)
        tool_run = None
        async with SessionLocal() as session:
            repo = Repository(session)
            if approved:
                tool_run = await repo.approve_tool_run(tool_run_id, decided_by)
            else:
                tool_run = await repo.deny_tool_run(tool_run_id, decided_by)
        if future and not future.done():
            future.set_result(approved)
        return tool_run is not None

    async def complete(self, tool_run_id: str, status: str, output: Dict[str, Any]) -> None:
        async with SessionLocal() as session:
            repo = Repository(session)
            await repo.complete_tool_run(tool_run_id, status, output)
