from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, Optional

from ..core.events import EventBus
from ..core.models import StreamEvent
from ..data.db import SessionLocal
from ..data.repositories import Repository


ApprovalNotifier = Callable[[str, str, str, Dict[str, Any]], Awaitable[None]]
_logger = logging.getLogger(__name__)


def _looks_like_discord_channel_id(channel_id: str) -> bool:
    value = (channel_id or "").strip()
    if not value:
        return False
    return value.isdigit()


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
        run_id: str | None = None,
        message_id: str | None = None,
    ) -> ApprovalDecision:
        async with SessionLocal() as session:
            repo = Repository(session)
            tool_run = await repo.create_tool_run(
                session_id=session_id,
                tool_name=tool_name,
                status="pending",
                input_payload=payload,
                approved_by=None,
                run_id=run_id,
                message_id=message_id,
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
        await self.event_bus.emit_admin(
            kind="tool.approval_requested",
            level="warning",
            title="Tool approval requested",
            message=f"{tool_name} is waiting for user approval.",
            session_id=session_id,
            run_id=run_id,
            tool_run_id=tool_run.id,
            user_id=requested_by,
            data={"tool_name": tool_name, "channel_id": channel_id, "payload": payload},
        )

        should_notify = self._notifier is not None and _looks_like_discord_channel_id(channel_id)
        if should_notify:
            try:
                await self._notifier(tool_run.id, channel_id, tool_name, payload)
            except Exception:
                _logger.exception(
                    "Failed to deliver tool approval request (tool_run_id=%s, channel_id=%s, tool=%s)",
                    tool_run.id,
                    channel_id,
                    tool_name,
                )
                async with SessionLocal() as session:
                    repo = Repository(session)
                    await repo.deny_tool_run(tool_run.id, "system")
                pending = self._pending.pop(tool_run.id, None)
                if pending is not None and not pending.done():
                    pending.set_result(False)
        elif self._notifier is None:
            # If no notifier is configured at all, auto-approve to avoid blocking.
            future.set_result(True)
        else:
            # Non-discord channels (e.g. web/menubar): keep request pending for API-driven approval.
            _logger.info(
                "Queued tool approval without notifier (tool_run_id=%s, channel_id=%s, tool=%s)",
                tool_run.id,
                channel_id,
                tool_name,
            )

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
        if tool_run is not None:
            await self.event_bus.emit_admin(
                kind="tool.approval_resolved",
                level="info" if approved else "warning",
                title="Tool approval resolved",
                message=f"{tool_run.tool_name} was {'approved' if approved else 'denied'}.",
                session_id=tool_run.session_id,
                tool_run_id=tool_run_id,
                user_id=decided_by,
                data={"approved": approved, "tool_name": tool_run.tool_name},
            )
        return tool_run is not None

    async def complete(self, tool_run_id: str, status: str, output: Dict[str, Any]) -> None:
        async with SessionLocal() as session:
            repo = Repository(session)
            await repo.complete_tool_run(tool_run_id, status, output)
