from __future__ import annotations

import asyncio

import pytest

from skitter.tools.executors import NodeExecutorHub


class _FakeWebSocket:
    def __init__(self) -> None:
        self.accepted = False
        self.closed = False
        self.sent: list[dict] = []

    async def accept(self) -> None:
        self.accepted = True

    async def close(self, code: int = 1000) -> None:
        _ = code
        self.closed = True

    async def send_json(self, payload: dict) -> None:
        self.sent.append(payload)


@pytest.mark.asyncio
async def test_node_executor_hub_roundtrip_execute() -> None:
    hub = NodeExecutorHub()
    ws = _FakeWebSocket()
    await hub.register("exec-1", ws)  # type: ignore[arg-type]

    call = asyncio.create_task(
        hub.execute(
            executor_id="exec-1",
            tool="read",
            session_id="session-1",
            payload={"path": "notes.md"},
            timeout_s=1.0,
        )
    )
    for _ in range(20):
        if ws.sent:
            break
        await asyncio.sleep(0)
    assert ws.sent, "execute should send a request to websocket"
    request = ws.sent[0]
    request_id = request["request_id"]

    await hub.handle_message(
        "exec-1",
        {
            "type": "result",
            "request_id": request_id,
            "ok": True,
            "payload": {"status": "ok", "content": "hello"},
        },
    )

    result = await call
    assert result["status"] == "ok"
    assert result["content"] == "hello"


@pytest.mark.asyncio
async def test_node_executor_hub_timeout_sends_cancel() -> None:
    hub = NodeExecutorHub()
    ws = _FakeWebSocket()
    await hub.register("exec-1", ws)  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="timed out"):
        await hub.execute(
            executor_id="exec-1",
            tool="shell",
            session_id="session-1",
            payload={"cmd": "sleep 10"},
            timeout_s=0.01,
        )

    assert any(item.get("type") == "cancel" for item in ws.sent)
