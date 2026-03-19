from __future__ import annotations

from datetime import UTC, datetime

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from skitter.core.config import settings
from skitter.core.events import EventBus
from skitter.core.graph import UserPromptRequired
from skitter.core.models import MessageEnvelope
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


def test_messages_for_invoke_merges_non_consecutive_system_messages_for_anthropic() -> None:
    runtime = _runtime()
    history = [
        SystemMessage(content="Main system prompt", additional_kwargs={"system_prompt": True}),
        HumanMessage(content="First question"),
        SystemMessage(content="ask_user interaction:\nQuestion: Pick one", additional_kwargs={"user_prompt_context": True}),
        AIMessage(content="Assistant reply"),
    ]

    prepared = runtime._messages_for_invoke(history, "anthropic")

    assert len([msg for msg in prepared if isinstance(msg, SystemMessage)]) == 1
    assert isinstance(prepared[0], SystemMessage)
    assert "Main system prompt" in prepared[0].content
    assert "ask_user interaction" in prepared[0].content
    assert isinstance(prepared[1], HumanMessage)
    assert isinstance(prepared[2], AIMessage)


class _ApiStatusError(Exception):
    def __init__(self, status_code: int) -> None:
        super().__init__(f"status={status_code}")
        self.status_code = status_code


class _LastAttempt:
    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    def exception(self) -> Exception:
        return self._exc


class _RetryWrapper(Exception):
    def __init__(self, exc: Exception) -> None:
        super().__init__("retry wrapper")
        self.last_attempt = _LastAttempt(exc)


def test_extract_http_status_code_from_retry_wrapper() -> None:
    runtime = _runtime()
    wrapped = _RetryWrapper(_ApiStatusError(500))
    assert runtime._extract_http_status_code(wrapped) == 500
    assert runtime._is_retryable_model_http_error(wrapped) is True


class _SummaryLLM:
    def __init__(self) -> None:
        self.prompts = []

    async def ainvoke(self, prompt):
        self.prompts.append(prompt)
        return AIMessage(content="## Decisions\n- Durable merged summary")


@pytest.mark.asyncio
async def test_summarize_session_uses_previous_summary_and_skips_tool_chatter(
    monkeypatch,
) -> None:
    runtime = _runtime()
    llm = _SummaryLLM()
    monkeypatch.setattr("skitter.core.runtime.list_models", lambda: [object()])
    monkeypatch.setattr("skitter.core.runtime.build_llm", lambda model_name, purpose="main": llm)

    runtime._history["session-1"] = [
        SystemMessage(
            content="Older durable summary",
            additional_kwargs={
                "conversation_summary": True,
                "summary_checkpoint": datetime(2026, 3, 1, 10, 0, tzinfo=UTC).isoformat(),
            },
        ),
        HumanMessage(
            content="Old message already summarized",
            additional_kwargs={"_db_created_at": datetime(2026, 3, 1, 9, 0, tzinfo=UTC).isoformat()},
        ),
        HumanMessage(
            content="We decided to use MCP for Trello sync.",
            additional_kwargs={"_db_created_at": datetime(2026, 3, 2, 9, 0, tzinfo=UTC).isoformat()},
        ),
        AIMessage(
            content="I will inspect the MCP tools now.",
            additional_kwargs={"_db_created_at": datetime(2026, 3, 2, 9, 1, tzinfo=UTC).isoformat()},
        ),
        AIMessage(
            content="",
            tool_calls=[{"id": "call-1", "name": "mcp_list_tools", "args": {"server_name": "trello"}}],
            additional_kwargs={"_db_created_at": datetime(2026, 3, 2, 9, 2, tzinfo=UTC).isoformat()},
        ),
        ToolMessage(
            content='{"tools":["boards.list"]}',
            tool_call_id="call-1",
            additional_kwargs={"_db_created_at": datetime(2026, 3, 2, 9, 2, tzinfo=UTC).isoformat()},
        ),
        AIMessage(
            content="Final short reply",
            additional_kwargs={"_db_created_at": datetime(2026, 3, 2, 9, 3, tzinfo=UTC).isoformat()},
        ),
    ]

    result = await runtime.summarize_session("session-1", model_name="provider/main")

    assert result == "## Decisions\n- Durable merged summary"
    assert len(llm.prompts) == 1
    prompt = llm.prompts[0]
    final_human = prompt[1].content
    assert "Existing summary:\nOlder durable summary" in final_human
    assert "We decided to use MCP for Trello sync." in final_human
    assert "I will inspect the MCP tools now." in final_human
    assert "Final short reply" in final_human
    assert "mcp_list_tools" not in final_human
    assert "boards.list" not in final_human
    assert "Old message already summarized" not in final_human


class _PromptGraph:
    async def ainvoke(self, *_args, **_kwargs):
        raise UserPromptRequired(
            prompt_id="prompt-1",
            question="Which machine should I use?",
            choices=["docker", "macbook"],
            allow_free_text=True,
        )


@pytest.mark.asyncio
async def test_handle_message_returns_pending_prompt_when_ask_user_is_triggered(monkeypatch) -> None:
    runtime = AgentRuntime(event_bus=EventBus(), graph=_PromptGraph())

    async def _fake_ensure_history(session_id: str) -> None:
        runtime._history.setdefault(session_id, [SystemMessage(content="system")])

    async def _noop_async(*_args, **_kwargs) -> None:
        return None

    async def _fake_get_session_model(_session_id: str, _envelope) -> str:
        return "provider/main"

    monkeypatch.setattr("skitter.core.runtime.list_models", lambda: [object()])
    monkeypatch.setattr("skitter.core.runtime.resolve_model_name", lambda _value=None, purpose="main": "provider/main")
    monkeypatch.setattr("skitter.core.runtime.resolve_model_candidates", lambda _value, purpose="main": ["provider/main"])
    monkeypatch.setattr(
        "skitter.core.runtime.resolve_model",
        lambda _value, purpose="main": type(
            "Resolved",
            (),
            {
                "input_cost_per_1m": 0.0,
                "output_cost_per_1m": 0.0,
                "provider_api_type": "openai",
            },
        )(),
    )
    monkeypatch.setattr(runtime, "_ensure_history", _fake_ensure_history)
    monkeypatch.setattr(runtime, "_get_session_model", _fake_get_session_model)
    monkeypatch.setattr(runtime, "_ensure_system_prompt", lambda history, _user_id: None)
    monkeypatch.setattr(runtime, "_compact_history_for_context", _noop_async)
    monkeypatch.setattr(runtime, "_trace_create", _noop_async)
    monkeypatch.setattr(runtime, "_trace_update", _noop_async)
    monkeypatch.setattr(runtime, "_trace_event", _noop_async)

    envelope = MessageEnvelope(
        message_id="msg-1",
        channel_id="chan-1",
        user_id="user-1",
        timestamp=datetime.now(UTC),
        text="Please continue.",
        origin="tui",
        metadata={"internal_user_id": "user-1"},
    )

    response = await runtime.handle_message("session-1", envelope)

    assert response.text == (
        "Which machine should I use?\n\n"
        "Choices:\n"
        "- docker\n"
        "- macbook\n\n"
        "The user may also reply with a custom free-text answer."
    )
    assert response.pending_prompt is not None
    assert response.pending_prompt.prompt_id == "prompt-1"
    assert response.pending_prompt.question == "Which machine should I use?"
    assert response.pending_prompt.choices == ["docker", "macbook"]
    assert isinstance(runtime._history["session-1"][-1], SystemMessage)
    assert runtime._history["session-1"][-1].content == (
        "ask_user interaction:\n"
        "Question: Which machine should I use?\n"
        "Choices:\n"
        "- docker\n"
        "- macbook\n"
        "Custom free-text replies were allowed."
    )
