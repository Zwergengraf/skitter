from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from skitter.core.config import settings
from skitter.core.events import EventBus
from skitter.core.runtime import AgentRuntime


def _runtime() -> AgentRuntime:
    return AgentRuntime(event_bus=EventBus(), graph=object())


def test_sanitize_tool_sequence_removes_orphan_and_incomplete_tool_messages() -> None:
    runtime = _runtime()
    history = [
        HumanMessage(content="start"),
        AIMessage(content="", tool_calls=[{"id": "call-ok", "name": "read", "args": {}}]),
        ToolMessage(content='{"status":"ok"}', tool_call_id="call-ok"),
        AIMessage(content="", tool_calls=[{"id": "call-missing", "name": "write", "args": {}}]),
        ToolMessage(content='{"status":"ok"}', tool_call_id="orphan-call"),
        AIMessage(content="final answer"),
    ]

    runtime._sanitize_tool_sequence(history)

    assert len(history) == 4
    assert isinstance(history[0], HumanMessage)
    assert isinstance(history[1], AIMessage)
    assert isinstance(history[2], ToolMessage)
    assert isinstance(history[3], AIMessage)
    assert history[1].tool_calls[0]["id"] == "call-ok"
    assert history[2].tool_call_id == "call-ok"


def test_trim_tool_messages_keeps_only_latest_tool_chatter(monkeypatch) -> None:
    runtime = _runtime()
    monkeypatch.setattr(settings, "context_max_tool_messages", 2)
    history = [
        HumanMessage(content="start"),
        AIMessage(content="", tool_calls=[{"id": "c1", "name": "read", "args": {}}]),
        ToolMessage(content='{"status":"ok"}', tool_call_id="c1"),
        AIMessage(content="", tool_calls=[{"id": "c2", "name": "write", "args": {}}]),
        ToolMessage(content='{"status":"ok"}', tool_call_id="c2"),
        AIMessage(content="done"),
    ]

    runtime._trim_tool_messages(history)

    assert len(history) == 4
    # Only latest two tool chatter messages are kept.
    assert isinstance(history[1], AIMessage)
    assert history[1].tool_calls[0]["id"] == "c2"
    assert isinstance(history[2], ToolMessage)
    assert history[2].tool_call_id == "c2"


def test_message_content_to_text_strips_reasoning_blocks() -> None:
    runtime = _runtime()
    content = [
        {"type": "reasoning", "text": "internal"},
        {"type": "text", "text": "Visible text"},
        {"type": "output_text", "text": "<thinking>hidden</thinking> final"},
    ]

    text = runtime._message_content_to_text(content)

    assert "internal" not in text
    assert "<thinking>" not in text
    assert text == "Visible text\nfinal"
