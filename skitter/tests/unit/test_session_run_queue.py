from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from skitter.core.models import MessageEnvelope
from skitter.core.session_run_queue import SessionRunQueue, SessionRunWork


def _envelope(message_id: str, text: str) -> MessageEnvelope:
    return MessageEnvelope(
        message_id=message_id,
        channel_id="channel-1",
        user_id="user-1",
        timestamp=datetime.now(UTC),
        text=text,
        origin="discord",
        transport_account_key="discord:default",
        metadata={"is_private": False},
    )


@pytest.mark.asyncio
async def test_session_run_queue_serializes_and_coalesces_backlog() -> None:
    queue = SessionRunQueue()
    started = asyncio.Event()
    release = asyncio.Event()
    processed: list[MessageEnvelope] = []

    async def process(envelope: MessageEnvelope):
        processed.append(envelope)
        if envelope.message_id == "m1":
            started.set()
            await release.wait()
        return {}

    first = await queue.submit(
        SessionRunWork(
            session_id="session-1",
            envelope=_envelope("m1", "first"),
            process=process,
            coalescible=True,
        )
    )
    await started.wait()
    second = await queue.submit(
        SessionRunWork(
            session_id="session-1",
            envelope=_envelope("m2", "second"),
            process=process,
            coalescible=True,
        )
    )
    third = await queue.submit(
        SessionRunWork(
            session_id="session-1",
            envelope=_envelope("m3", "third"),
            process=process,
            coalescible=True,
        )
    )
    release.set()

    await asyncio.gather(first, second, third)

    assert len(processed) == 2
    assert processed[0].message_id == "m1"
    assert processed[1].message_id.startswith("coalesced:session-1:")
    assert processed[1].metadata["coalesced_message_count"] == 2
    assert [item["text"] for item in processed[1].metadata["coalesced_messages"]] == ["second", "third"]


@pytest.mark.asyncio
async def test_session_run_queue_does_not_coalesce_non_coalescible_messages() -> None:
    queue = SessionRunQueue()
    processed: list[str] = []

    async def process(envelope: MessageEnvelope):
        processed.append(envelope.message_id)
        await asyncio.sleep(0)
        return {}

    first = await queue.submit(
        SessionRunWork(
            session_id="session-2",
            envelope=_envelope("m1", "first"),
            process=process,
            coalescible=True,
        )
    )
    second = await queue.submit(
        SessionRunWork(
            session_id="session-2",
            envelope=_envelope("m2", "attachment-like"),
            process=process,
            coalescible=False,
        )
    )

    await asyncio.gather(first, second)

    assert processed == ["m1", "m2"]


@pytest.mark.asyncio
async def test_session_run_queue_cancel_discards_pending_without_stopping_active() -> None:
    queue = SessionRunQueue()
    started = asyncio.Event()
    release = asyncio.Event()
    processed: list[str] = []

    async def process(envelope: MessageEnvelope):
        processed.append(envelope.message_id)
        if envelope.message_id == "m1":
            started.set()
            await release.wait()
        return {}

    first = await queue.submit(
        SessionRunWork(
            session_id="session-3",
            envelope=_envelope("m1", "first"),
            process=process,
            coalescible=True,
        )
    )
    await started.wait()
    second = await queue.submit(
        SessionRunWork(
            session_id="session-3",
            envelope=_envelope("m2", "second"),
            process=process,
            coalescible=True,
        )
    )

    result = await queue.cancel_session("session-3", cancel_active=False)
    release.set()

    assert result == {"session_id": "session-3", "active": True, "discarded_pending": 1}
    assert await first == {
        "session_id": "session-3",
        "coalesced": False,
        "count": 1,
        "message_id": "m1",
    }
    assert await second == {
        "session_id": "session-3",
        "cancelled": True,
        "discarded_by_stop": True,
        "message_id": "m2",
    }
    assert processed == ["m1"]
