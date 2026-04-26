from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Awaitable, Callable

from .models import MessageEnvelope

_logger = logging.getLogger(__name__)

TurnProcessor = Callable[[MessageEnvelope], Awaitable[dict[str, Any] | None]]


@dataclass(slots=True)
class SessionRunWork:
    session_id: str
    envelope: MessageEnvelope
    process: TurnProcessor
    coalescible: bool = False


@dataclass(slots=True)
class _QueuedWork:
    work: SessionRunWork
    future: asyncio.Future[dict[str, Any]]


@dataclass(slots=True)
class _Lane:
    pending: list[_QueuedWork] = field(default_factory=list)
    task: asyncio.Task[None] | None = None
    active: list[_QueuedWork] = field(default_factory=list)


class SessionRunQueue:
    def __init__(self) -> None:
        self._lanes: dict[str, _Lane] = {}
        self._lock = asyncio.Lock()

    async def submit(self, work: SessionRunWork) -> asyncio.Future[dict[str, Any]]:
        loop = asyncio.get_running_loop()
        future: asyncio.Future[dict[str, Any]] = loop.create_future()
        queued = _QueuedWork(work=work, future=future)
        async with self._lock:
            lane = self._lanes.setdefault(work.session_id, _Lane())
            lane.pending.append(queued)
            if lane.task is None or lane.task.done():
                lane.task = asyncio.create_task(
                    self._drain_session(work.session_id),
                    name=f"skitter-session-run:{work.session_id}",
                )
        return future

    async def _drain_session(self, session_id: str) -> None:
        while True:
            batch = await self._pop_next_batch(session_id)
            if not batch:
                async with self._lock:
                    lane = self._lanes.get(session_id)
                    if lane is not None and lane.pending:
                        continue
                    if lane is not None and lane.task is asyncio.current_task() and not lane.pending:
                        self._lanes.pop(session_id, None)
                return
            work = batch[0].work
            envelope = work.envelope if len(batch) == 1 else self._coalesce_batch(session_id, batch)
            async with self._lock:
                lane = self._lanes.get(session_id)
                if lane is not None and lane.task is asyncio.current_task():
                    lane.active = batch
            try:
                result = await work.process(envelope)
            except asyncio.CancelledError:
                payload = {
                    "session_id": session_id,
                    "cancelled": True,
                    "coalesced": len(batch) > 1,
                    "count": len(batch),
                    "message_id": envelope.message_id,
                }
                for item in batch:
                    if not item.future.done():
                        item.future.set_result(payload)
                async with self._lock:
                    lane = self._lanes.get(session_id)
                    if lane is not None and lane.task is asyncio.current_task():
                        lane.active = []
                        if not lane.pending:
                            self._lanes.pop(session_id, None)
                return
            except Exception as exc:
                _logger.exception("Session run processing failed for session %s", session_id)
                for item in batch:
                    if not item.future.done():
                        item.future.set_exception(exc)
            else:
                payload = {
                    "session_id": session_id,
                    "coalesced": len(batch) > 1,
                    "count": len(batch),
                    "message_id": envelope.message_id,
                }
                if isinstance(result, dict):
                    payload.update(result)
                for item in batch:
                    if not item.future.done():
                        item.future.set_result(payload)
            finally:
                async with self._lock:
                    lane = self._lanes.get(session_id)
                    if lane is not None and lane.task is asyncio.current_task():
                        lane.active = []

    async def cancel_session(self, session_id: str, *, cancel_active: bool = True) -> dict[str, object]:
        async with self._lock:
            lane = self._lanes.get(session_id)
            if lane is None:
                return {"session_id": session_id, "active": False, "discarded_pending": 0}
            pending = list(lane.pending)
            lane.pending.clear()
            active = bool(lane.task is not None and not lane.task.done())
            if active and cancel_active and lane.task is not None:
                lane.task.cancel()
            elif not active:
                self._lanes.pop(session_id, None)
        payload = {"session_id": session_id, "cancelled": True, "discarded_by_stop": True}
        for item in pending:
            if not item.future.done():
                item.future.set_result(payload | {"message_id": item.work.envelope.message_id})
        return {"session_id": session_id, "active": active, "discarded_pending": len(pending)}

    async def _pop_next_batch(self, session_id: str) -> list[_QueuedWork]:
        async with self._lock:
            lane = self._lanes.get(session_id)
            if lane is None or not lane.pending:
                return []
            first = lane.pending.pop(0)
            batch = [first]
            if first.work.coalescible:
                while lane.pending and lane.pending[0].work.coalescible:
                    batch.append(lane.pending.pop(0))
            return batch

    @staticmethod
    def _coalesce_batch(session_id: str, batch: list[_QueuedWork]) -> MessageEnvelope:
        base = batch[-1].work.envelope
        metadata = dict(base.metadata)
        for key in (
            "sender_transport_user_id",
            "sender_display_name",
            "sender_username",
            "sender_avatar_url",
            "sender_is_bot",
            "sender_mention",
            "sender_role_names",
            "sender_internal_user_id",
        ):
            metadata.pop(key, None)
        messages: list[dict[str, Any]] = []
        rendered_lines: list[str] = []
        for item in batch:
            envelope = item.work.envelope
            entry = {
                "origin": envelope.origin,
                "is_private": bool(envelope.metadata.get("is_private")),
                "message_id": envelope.message_id,
                "timestamp": envelope.timestamp.astimezone(UTC).isoformat(),
                "text": envelope.text,
                "sender_transport_user_id": envelope.metadata.get("sender_transport_user_id"),
                "sender_internal_user_id": envelope.metadata.get("sender_internal_user_id"),
                "sender_display_name": envelope.metadata.get("sender_display_name"),
                "sender_username": envelope.metadata.get("sender_username"),
                "sender_avatar_url": envelope.metadata.get("sender_avatar_url"),
                "sender_is_bot": bool(envelope.metadata.get("sender_is_bot")),
                "sender_mention": envelope.metadata.get("sender_mention"),
                "sender_role_names": list(envelope.metadata.get("sender_role_names") or []),
            }
            messages.append(entry)
            label = str(entry.get("sender_display_name") or entry.get("sender_username") or entry.get("sender_transport_user_id") or "unknown").strip()
            text = str(envelope.text or "").strip()
            rendered_lines.append(f"[{label}] {text}" if text else f"[{label}]")
        metadata["coalesced_messages"] = messages
        metadata["coalesced_message_count"] = len(messages)
        metadata["coalesced_while_busy"] = True
        return MessageEnvelope(
            message_id=f"coalesced:{session_id}:{int(datetime.now(UTC).timestamp() * 1000)}",
            channel_id=base.channel_id,
            user_id=base.user_id,
            timestamp=base.timestamp,
            text="\n".join(rendered_lines).strip(),
            attachments=[],
            origin=base.origin,
            transport_account_key=base.transport_account_key,
            command=None,
            metadata=metadata,
        )
