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


def test_extract_tool_call_ids_from_content_blocks() -> None:
    runtime = _runtime()
    msg = AIMessage(
        content=[
            {"type": "text", "text": "Working"},
            {"type": "tool_use", "id": "call-abc", "name": "read", "input": {"path": "x"}},
        ]
    )

    ids = runtime._extract_tool_call_ids(msg)

    assert ids == {"call-abc"}
    assert runtime._is_tool_chatter_message(msg) is True


def test_sanitize_tool_sequence_handles_anthropic_tool_use_blocks() -> None:
    runtime = _runtime()
    history = [
        HumanMessage(content="start"),
        AIMessage(content=[{"type": "tool_use", "id": "call-a", "name": "read", "input": {}}]),
        ToolMessage(content='{"status":"ok"}', tool_call_id="call-a"),
        AIMessage(content=[{"type": "tool_use", "id": "call-missing", "name": "write", "input": {}}]),
        AIMessage(content="final answer"),
    ]

    runtime._sanitize_tool_sequence(history)

    assert len(history) == 4
    assert isinstance(history[1], AIMessage)
    assert isinstance(history[2], ToolMessage)
    assert isinstance(history[3], AIMessage)


def test_sanitize_tool_sequence_requires_immediate_tool_results() -> None:
    runtime = _runtime()
    history = [
        HumanMessage(content="start"),
        AIMessage(content=[{"type": "tool_use", "id": "call-a", "name": "read", "input": {}}]),
        HumanMessage(content="interleaved"),
        ToolMessage(content='{"status":"ok"}', tool_call_id="call-a"),
        AIMessage(content="final"),
    ]

    runtime._sanitize_tool_sequence(history)

    # The tool_use/tool_result pair is invalid (not immediate), so both are dropped.
    assert len(history) == 3
    assert isinstance(history[0], HumanMessage)
    assert isinstance(history[1], HumanMessage)
    assert isinstance(history[2], AIMessage)


def test_tool_sequence_error_detection() -> None:
    runtime = _runtime()
    err = Exception(
        "tool_use ids were found without tool_result blocks immediately after: call_123"
    )
    assert runtime._is_tool_sequence_error(err) is True
    assert runtime._is_tool_sequence_error(Exception("some other failure")) is False


def test_model_bad_request_detection() -> None:
    runtime = _runtime()
    assert runtime._is_model_bad_request(Exception("Error code: 400 - invalid_request_error")) is True
    assert runtime._is_model_bad_request(Exception("network timeout")) is False
