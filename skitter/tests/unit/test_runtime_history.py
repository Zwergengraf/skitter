from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from skitter.core.config import settings
from skitter.core.events import EventBus
from skitter.core.graph import UserPromptRequired
from skitter.core.llm import ResolvedModel
from skitter.core.memory_provider import ContextContribution, MemoryContext, MemoryContextResult
from skitter.core.models import MessageEnvelope, SKITTER_NO_REPLY
from skitter.core.plugins import HookBus
from skitter.core.runtime import AgentRuntime


def _runtime() -> AgentRuntime:
    return AgentRuntime(event_bus=EventBus(), graph=object())


def test_get_graph_passes_hook_bus_and_rebuilds_when_it_changes(monkeypatch) -> None:
    calls: list[dict] = []
    first_bus = HookBus()
    second_bus = HookBus()
    runtime = AgentRuntime(event_bus=EventBus(), hook_bus=first_bus)
    resolved = ResolvedModel(
        name="provider/main",
        provider="provider",
        provider_api_type="openai",
        model="test-model",
        api_base="http://localhost",
        api_key="test-key",
    )

    def _fake_build_graph(**kwargs):
        calls.append(kwargs)
        return object()

    monkeypatch.setattr("skitter.core.runtime.build_graph", _fake_build_graph)

    first_graph = runtime._get_graph("provider/main", resolved_model=resolved)
    cached_graph = runtime._get_graph("provider/main", resolved_model=resolved)
    runtime.set_hook_bus(second_bus)
    rebuilt_graph = runtime._get_graph("provider/main", resolved_model=resolved)

    assert first_graph is cached_graph
    assert rebuilt_graph is not first_graph
    assert len(calls) == 2
    assert calls[0]["hook_bus"] is first_bus
    assert calls[1]["hook_bus"] is second_bus


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


def test_prepare_envelope_content_renders_sender_context_for_public_discord_messages() -> None:
    runtime = _runtime()
    envelope = MessageEnvelope(
        message_id="msg-1",
        channel_id="chan-1",
        user_id="transport-user",
        timestamp=datetime.now(UTC),
        text="Can you summarize this?",
        origin="discord",
        metadata={
            "is_private": False,
            "sender_transport_user_id": "123",
            "sender_display_name": "Alice",
            "sender_username": "alice",
            "sender_mention": "<@123>",
            "sender_is_bot": False,
            "sender_role_names": ["Moderator", "Builder"],
        },
    )

    content, is_command, attachments_meta = runtime._prepare_envelope_content(envelope)

    assert is_command is False
    assert attachments_meta == []
    assert content.startswith("[Discord sender: Alice | @alice | <@123> | roles: Moderator, Builder]\n")
    assert content.endswith("Can you summarize this?")


def test_prepare_envelope_content_renders_coalesced_public_discord_messages() -> None:
    runtime = _runtime()
    envelope = MessageEnvelope(
        message_id="batch-1",
        channel_id="chan-1",
        user_id="transport-user",
        timestamp=datetime.now(UTC),
        text="[Alice] first\n[Bob] second",
        origin="discord",
        metadata={
            "is_private": False,
            "coalesced_messages": [
                {
                    "origin": "discord",
                    "is_private": False,
                    "text": "first",
                    "sender_transport_user_id": "123",
                    "sender_display_name": "Alice",
                    "sender_username": "alice",
                    "sender_mention": "<@123>",
                },
                {
                    "origin": "discord",
                    "is_private": False,
                    "text": "second",
                    "sender_transport_user_id": "456",
                    "sender_display_name": "Bob",
                    "sender_username": "bob",
                    "sender_mention": "<@456>",
                },
            ],
        },
    )

    content, is_command, attachments_meta = runtime._prepare_envelope_content(envelope)

    assert is_command is False
    assert attachments_meta == []
    assert content.startswith("[Messages received while you were busy. Reply once to the full batch.]")
    assert "Alice | @alice | <@123>" in content
    assert "Bob | @bob | <@456>" in content
    assert "first" in content
    assert "second" in content


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


class _ContextSummaryLLM:
    def __init__(self, content: str) -> None:
        self.content = content
        self.prompts = []

    async def ainvoke(self, prompt):
        self.prompts.append(prompt)
        return AIMessage(content=self.content)


@dataclass
class _RuntimeSessionRow:
    session_memory_message_id: str | None = None
    session_memory_checkpoint: datetime | None = None
    context_summary: str | None = None
    context_summary_checkpoint: datetime | None = None
    context_summary_input_tokens: int | None = None
    last_input_tokens: int = 0


class _RuntimeRepo:
    def __init__(self, row: _RuntimeSessionRow) -> None:
        self.row = row
        self.saved_summary: str | None = None
        self.saved_checkpoint: datetime | None = None

    async def get_session(self, _session_id: str) -> _RuntimeSessionRow:
        return self.row

    async def set_session_context_summary(self, _session_id: str, summary: str, checkpoint: datetime | None, input_tokens: int | None):
        self.saved_summary = summary
        self.saved_checkpoint = checkpoint
        self.row.context_summary = summary
        self.row.context_summary_checkpoint = checkpoint
        self.row.context_summary_input_tokens = input_tokens
        return self.row


class _RuntimeSessionCtx:
    def __init__(self, token: object) -> None:
        self.token = token

    async def __aenter__(self) -> object:
        return self.token

    async def __aexit__(self, exc_type, exc, tb) -> None:
        _ = exc_type, exc, tb
        return None


class _SessionMemoryRefreshStub:
    def __init__(self, content: str | None) -> None:
        self.content = content
        self.calls: list[tuple[str, str | None, bool]] = []

    async def refresh_session_memory(self, session_id: str, *, model_name: str | None = None, force: bool = False):
        self.calls.append((session_id, model_name, force))
        return self.content


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


@pytest.mark.asyncio
async def test_compact_history_prefers_session_memory_and_preserves_recent_raw_tail(monkeypatch) -> None:
    runtime = _runtime()
    row = _RuntimeSessionRow(
        session_memory_message_id="m5",
        session_memory_checkpoint=datetime(2026, 3, 2, 9, 4, tzinfo=UTC),
        last_input_tokens=12000,
    )
    repo = _RuntimeRepo(row)
    token = object()
    monkeypatch.setattr("skitter.core.runtime.SessionLocal", lambda: _RuntimeSessionCtx(token))
    monkeypatch.setattr("skitter.core.runtime.Repository", lambda _session: repo)
    monkeypatch.setattr(settings, "context_max_input_tokens", 10000)
    monkeypatch.setattr(settings, "context_compact_every_tokens", 1000)
    monkeypatch.setattr(settings, "context_preserve_recent_messages", 2)
    monkeypatch.setattr(settings, "context_preserve_recent_tokens", 2)
    llm = _ContextSummaryLLM("## Current State\n- Waiting for the user's final confirmation.")
    monkeypatch.setattr("skitter.core.runtime.list_models", lambda: [object()])
    monkeypatch.setattr("skitter.core.runtime.build_llm", lambda model_name, purpose="main": llm)

    async def _should_not_run(*_args, **_kwargs):
        raise AssertionError("raw transcript compaction should not run when session memory is available")

    monkeypatch.setattr(runtime, "_summarize_chat_messages", _should_not_run)
    memory = _SessionMemoryRefreshStub(
        "# Session Title\n_Title_\n\n# Current State\n_State_\n\nWaiting for the user's final confirmation.\n"
    )
    runtime.set_session_memory_service(memory)

    history = [
        SystemMessage(content="Main system", additional_kwargs={"system_prompt": True}),
        HumanMessage(content="First request", additional_kwargs={"_db_message_id": "m1", "_db_created_at": datetime(2026, 3, 2, 9, 0, tzinfo=UTC).isoformat()}),
        AIMessage(content="First reply", additional_kwargs={"_db_message_id": "m2", "_db_created_at": datetime(2026, 3, 2, 9, 1, tzinfo=UTC).isoformat()}),
        HumanMessage(content="Second request", additional_kwargs={"_db_message_id": "m3", "_db_created_at": datetime(2026, 3, 2, 9, 2, tzinfo=UTC).isoformat()}),
        AIMessage(content="Second reply", additional_kwargs={"_db_message_id": "m4", "_db_created_at": datetime(2026, 3, 2, 9, 3, tzinfo=UTC).isoformat()}),
        HumanMessage(content="Third request", additional_kwargs={"_db_message_id": "m5", "_db_created_at": datetime(2026, 3, 2, 9, 4, tzinfo=UTC).isoformat()}),
    ]

    await runtime._compact_history_for_context("session-compact", history, "provider/main")

    assert memory.calls == [("session-compact", "provider/main", True)]
    assert isinstance(history[0], SystemMessage)
    assert isinstance(history[1], SystemMessage)
    assert history[1].additional_kwargs["summary_source"] == "session_memory"
    assert history[1].additional_kwargs["summary_checkpoint"] == datetime(2026, 3, 2, 9, 4, tzinfo=UTC).isoformat()
    assert history[1].content == "## Current State\n- Waiting for the user's final confirmation."
    assert isinstance(history[2], AIMessage)
    assert history[2].content == "Second reply"
    assert isinstance(history[3], HumanMessage)
    assert history[3].content == "Third request"
    assert repo.saved_summary == "## Current State\n- Waiting for the user's final confirmation."
    assert repo.saved_checkpoint == datetime(2026, 3, 2, 9, 4, tzinfo=UTC)
    assert row.context_summary_input_tokens == 12000
    final_human = llm.prompts[0][1].content
    assert "Structured session memory:" in final_human
    assert "Waiting for the user's final confirmation." in final_human


@pytest.mark.asyncio
async def test_compact_history_falls_back_to_transcript_when_session_memory_boundary_is_missing(monkeypatch) -> None:
    runtime = _runtime()
    row = _RuntimeSessionRow(
        session_memory_message_id=None,
        session_memory_checkpoint=datetime(2026, 3, 2, 9, 4, tzinfo=UTC),
        last_input_tokens=12000,
    )
    repo = _RuntimeRepo(row)
    token = object()
    monkeypatch.setattr("skitter.core.runtime.SessionLocal", lambda: _RuntimeSessionCtx(token))
    monkeypatch.setattr("skitter.core.runtime.Repository", lambda _session: repo)
    monkeypatch.setattr(settings, "context_max_input_tokens", 10000)
    monkeypatch.setattr(settings, "context_compact_every_tokens", 1000)
    monkeypatch.setattr(settings, "context_preserve_recent_messages", 2)
    monkeypatch.setattr(settings, "context_preserve_recent_tokens", 2)

    calls: list[tuple[str, list[str], str]] = []

    async def _fallback_summary(previous_summary: str, messages: list, model_name: str) -> str:
        calls.append((previous_summary, [getattr(msg, "content", "") for msg in messages], model_name))
        return "Fallback compact summary"

    monkeypatch.setattr(runtime, "_summarize_chat_messages", _fallback_summary)
    memory = _SessionMemoryRefreshStub("# Current State\n_State_\n\nPossibly stale notes.")
    runtime.set_session_memory_service(memory)

    history = [
        SystemMessage(content="Main system", additional_kwargs={"system_prompt": True}),
        HumanMessage(content="First request", additional_kwargs={"_db_message_id": "m1", "_db_created_at": datetime(2026, 3, 2, 9, 0, tzinfo=UTC).isoformat()}),
        AIMessage(content="First reply", additional_kwargs={"_db_message_id": "m2", "_db_created_at": datetime(2026, 3, 2, 9, 1, tzinfo=UTC).isoformat()}),
        HumanMessage(content="Second request", additional_kwargs={"_db_message_id": "m3", "_db_created_at": datetime(2026, 3, 2, 9, 2, tzinfo=UTC).isoformat()}),
        AIMessage(content="Second reply", additional_kwargs={"_db_message_id": "m4", "_db_created_at": datetime(2026, 3, 2, 9, 3, tzinfo=UTC).isoformat()}),
        HumanMessage(content="Third request", additional_kwargs={"_db_message_id": "m5", "_db_created_at": datetime(2026, 3, 2, 9, 4, tzinfo=UTC).isoformat()}),
    ]

    await runtime._compact_history_for_context("session-compact", history, "provider/main")

    assert memory.calls == [("session-compact", "provider/main", True)]
    assert len(calls) == 1
    assert calls[0][2] == "provider/main"
    assert calls[0][1] == ["First request", "First reply", "Second request"]
    assert history[1].additional_kwargs["summary_source"] == "transcript"
    assert history[1].content == "Fallback compact summary"


@pytest.mark.asyncio
async def test_compact_history_skips_when_input_token_delta_is_below_threshold(monkeypatch) -> None:
    runtime = _runtime()
    row = _RuntimeSessionRow(
        context_summary="Existing compact summary",
        context_summary_checkpoint=datetime(2026, 3, 2, 9, 2, tzinfo=UTC),
        context_summary_input_tokens=11000,
        last_input_tokens=11800,
    )
    repo = _RuntimeRepo(row)
    token = object()
    monkeypatch.setattr("skitter.core.runtime.SessionLocal", lambda: _RuntimeSessionCtx(token))
    monkeypatch.setattr("skitter.core.runtime.Repository", lambda _session: repo)
    monkeypatch.setattr(settings, "context_max_input_tokens", 10000)
    monkeypatch.setattr(settings, "context_compact_every_tokens", 1000)
    monkeypatch.setattr(settings, "context_preserve_recent_messages", 2)
    monkeypatch.setattr(settings, "context_preserve_recent_tokens", 2)

    history = [
        SystemMessage(content="Main system", additional_kwargs={"system_prompt": True}),
        SystemMessage(
            content="Existing compact summary",
            additional_kwargs={
                "conversation_summary": True,
                "summary_checkpoint": datetime(2026, 3, 2, 9, 2, tzinfo=UTC).isoformat(),
            },
        ),
        HumanMessage(content="Recent request", additional_kwargs={"_db_message_id": "m1", "_db_created_at": datetime(2026, 3, 2, 9, 3, tzinfo=UTC).isoformat()}),
        AIMessage(content="Recent reply", additional_kwargs={"_db_message_id": "m2", "_db_created_at": datetime(2026, 3, 2, 9, 4, tzinfo=UTC).isoformat()}),
    ]

    await runtime._compact_history_for_context("session-compact", history, "provider/main")

    assert [type(msg).__name__ for msg in history] == ["SystemMessage", "SystemMessage", "HumanMessage", "AIMessage"]
    assert repo.saved_summary is None


class _PromptGraph:
    async def ainvoke(self, *_args, **_kwargs):
        raise UserPromptRequired(
            prompt_id="prompt-1",
            question="Which machine should I use?",
            choices=["docker", "macbook"],
            allow_free_text=True,
        )


class _MaxTokensGraph:
    async def ainvoke(self, payload, **_kwargs):
        messages = list(payload["messages"])
        messages.append(AIMessage(content="", response_metadata={"stop_reason": "max_tokens"}))
        return {"messages": messages}


class _NoReplyGraph:
    async def ainvoke(self, *_args, **_kwargs):
        return {"messages": [AIMessage(content=SKITTER_NO_REPLY)]}


class _MemoryContextGraph:
    def __init__(self) -> None:
        self.invocations = []

    async def ainvoke(self, payload, **_kwargs):
        messages = list(payload["messages"])
        self.invocations.append(messages)
        return {"messages": messages + [AIMessage(content="Used memory context.")]}


class _SimpleGraph:
    async def ainvoke(self, payload, **_kwargs):
        messages = list(payload["messages"])
        return {"messages": messages + [AIMessage(content="Hooked response.")]}


class _RecordingGraph:
    def __init__(self) -> None:
        self.invocations = []

    async def ainvoke(self, payload, **_kwargs):
        messages = list(payload["messages"])
        self.invocations.append(messages)
        return {"messages": messages + [AIMessage(content="Original response.")]}


class _MemoryHubStub:
    def __init__(self) -> None:
        self.requests = []

    def context_for(self, **kwargs):
        return MemoryContext(
            user_id=kwargs["user_id"],
            agent_profile_id=str(kwargs.get("agent_profile_id") or ""),
            agent_profile_slug=str(kwargs.get("agent_profile_slug") or ""),
            session_id=kwargs.get("session_id"),
            run_id=kwargs.get("run_id"),
            origin=str(kwargs.get("origin") or ""),
            transport_account_key=kwargs.get("transport_account_key"),
            scope_type=str(kwargs.get("scope_type") or "private"),
            scope_id=str(kwargs.get("scope_id") or ""),
        )

    async def build_context(self, ctx, request):
        self.requests.append((ctx, request))
        return MemoryContextResult(
            contributions=[
                ContextContribution(
                    provider_id="external",
                    title="Preference",
                    content="The user prefers concise implementation plans.",
                    priority=10,
                )
            ]
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


@pytest.mark.asyncio
async def test_handle_message_injects_memory_context_without_persisting_it(monkeypatch) -> None:
    graph = _MemoryContextGraph()
    memory_hub = _MemoryHubStub()
    runtime = AgentRuntime(event_bus=EventBus(), graph=graph, memory_hub=memory_hub)

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
                "model": "provider/main",
                "name": "provider/main",
                "api_base": "",
            },
        )(),
    )
    monkeypatch.setattr("skitter.core.runtime.collect_usage", lambda _messages, _message_id: None)
    monkeypatch.setattr(runtime, "_ensure_history", _fake_ensure_history)
    monkeypatch.setattr(runtime, "_get_session_model", _fake_get_session_model)
    monkeypatch.setattr(runtime, "_ensure_system_prompt", lambda history, _user_id: None)
    monkeypatch.setattr(runtime, "_compact_history_for_context", _noop_async)
    monkeypatch.setattr(runtime, "_trace_create", _noop_async)
    monkeypatch.setattr(runtime, "_trace_update", _noop_async)
    monkeypatch.setattr(runtime, "_trace_event", _noop_async)

    envelope = MessageEnvelope(
        message_id="msg-memory",
        channel_id="chan-1",
        user_id="user-1",
        timestamp=datetime.now(UTC),
        text="What should I do next?",
        origin="tui",
        metadata={
            "internal_user_id": "user-1",
            "agent_profile_id": "profile-1",
            "agent_profile_slug": "coder",
        },
    )

    response = await runtime.handle_message("session-memory", envelope)

    assert response.text == "Used memory context."
    invoked_messages = graph.invocations[0]
    memory_messages = [
        msg for msg in invoked_messages if getattr(msg, "additional_kwargs", {}).get("memory_context")
    ]
    assert len(memory_messages) == 1
    assert "The user prefers concise implementation plans." in memory_messages[0].content
    assert all(
        not getattr(msg, "additional_kwargs", {}).get("memory_context")
        for msg in runtime._history["session-memory"]
    )
    assert [type(msg).__name__ for msg in runtime._history["session-memory"]] == [
        "SystemMessage",
        "HumanMessage",
        "AIMessage",
    ]
    assert memory_hub.requests[0][1].query == "What should I do next?"


@pytest.mark.asyncio
async def test_handle_message_emits_run_hooks(monkeypatch) -> None:
    events: list[tuple[str, dict]] = []
    hook_bus = HookBus(default_timeout_seconds=1.0)
    hook_bus.register(
        "run.started",
        lambda event: events.append(("started", dict(event))),
        plugin_id="test",
    )
    hook_bus.register(
        "run.finished",
        lambda event: events.append(("finished", dict(event))),
        plugin_id="test",
    )
    runtime = AgentRuntime(event_bus=EventBus(), graph=_SimpleGraph(), hook_bus=hook_bus)

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
                "model": "provider/main",
                "name": "provider/main",
                "api_base": "",
            },
        )(),
    )
    monkeypatch.setattr("skitter.core.runtime.collect_usage", lambda _messages, _message_id: None)
    monkeypatch.setattr(runtime, "_ensure_history", _fake_ensure_history)
    monkeypatch.setattr(runtime, "_get_session_model", _fake_get_session_model)
    monkeypatch.setattr(runtime, "_ensure_system_prompt", lambda history, _user_id: None)
    monkeypatch.setattr(runtime, "_compact_history_for_context", _noop_async)
    monkeypatch.setattr(runtime, "_trace_create", _noop_async)
    monkeypatch.setattr(runtime, "_trace_update", _noop_async)
    monkeypatch.setattr(runtime, "_trace_event", _noop_async)

    envelope = MessageEnvelope(
        message_id="msg-hooks",
        channel_id="chan-1",
        user_id="transport-user",
        timestamp=datetime.now(UTC),
        text="Please handle this.",
        origin="tui",
        metadata={
            "internal_user_id": "user-1",
            "agent_profile_id": "profile-1",
            "agent_profile_slug": "coder",
            "scope_type": "private",
            "scope_id": "private:profile-1",
        },
    )

    response = await runtime.handle_message("session-hooks", envelope)

    assert response.text == "Hooked response."
    assert [name for name, _event in events] == ["started", "finished"]
    assert events[0][1]["run_id"] == response.run_id
    assert events[0][1]["model"] == "provider/main"
    assert events[0][1]["agent_profile_id"] == "profile-1"
    assert events[0][1]["scope_id"] == "private:profile-1"
    assert events[1][1]["status"] == "completed"
    assert events[1][1]["response_text"] == "Hooked response."
    assert events[1][1]["duration_ms"] >= 0


@pytest.mark.asyncio
async def test_handle_message_applies_llm_transform_hook_patches(monkeypatch) -> None:
    graph = _RecordingGraph()
    hook_bus = HookBus(default_timeout_seconds=1.0)
    hook_bus.register(
        "before_llm_call",
        lambda event: {"append_messages": [SystemMessage(content=f"hook saw {event['model']}")]},
        plugin_id="before",
    )
    hook_bus.register(
        "llm.after_call",
        lambda event: {
            "messages": list(event["result_messages"]) + [AIMessage(content="Patched response.")]
        },
        plugin_id="after",
    )
    runtime = AgentRuntime(event_bus=EventBus(), graph=graph, hook_bus=hook_bus)

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
                "model": "provider/main",
                "name": "provider/main",
                "api_base": "",
            },
        )(),
    )
    monkeypatch.setattr("skitter.core.runtime.collect_usage", lambda _messages, _message_id: None)
    monkeypatch.setattr(runtime, "_ensure_history", _fake_ensure_history)
    monkeypatch.setattr(runtime, "_get_session_model", _fake_get_session_model)
    monkeypatch.setattr(runtime, "_ensure_system_prompt", lambda history, _user_id: None)
    monkeypatch.setattr(runtime, "_compact_history_for_context", _noop_async)
    monkeypatch.setattr(runtime, "_trace_create", _noop_async)
    monkeypatch.setattr(runtime, "_trace_update", _noop_async)
    monkeypatch.setattr(runtime, "_trace_event", _noop_async)

    envelope = MessageEnvelope(
        message_id="msg-llm-hooks",
        channel_id="chan-1",
        user_id="transport-user",
        timestamp=datetime.now(UTC),
        text="Please handle this.",
        origin="tui",
        metadata={
            "internal_user_id": "user-1",
            "agent_profile_id": "profile-1",
            "agent_profile_slug": "coder",
        },
    )

    response = await runtime.handle_message("session-llm-hooks", envelope)

    assert response.text == "Patched response."
    assert any(
        isinstance(msg, SystemMessage) and msg.content == "hook saw provider/main"
        for msg in graph.invocations[0]
    )
    assert isinstance(runtime._history["session-llm-hooks"][-1], AIMessage)
    assert runtime._history["session-llm-hooks"][-1].content == "Patched response."


@pytest.mark.asyncio
async def test_handle_message_returns_fallback_when_model_stops_at_max_tokens(monkeypatch) -> None:
    runtime = AgentRuntime(event_bus=EventBus(), graph=_MaxTokensGraph())

    async def _fake_ensure_history(session_id: str) -> None:
        runtime._history.setdefault(session_id, [SystemMessage(content="system")])

    async def _noop_async(*_args, **_kwargs) -> None:
        return None

    async def _fake_get_session_model(_session_id: str, _envelope) -> str:
        return "provider/main"

    async def _fake_limit_fallback(*_args, **_kwargs) -> str:
        return "LIMIT_REACHED (max_tokens): The model hit its output token limit before finishing."

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
                "provider_api_type": "anthropic",
            },
        )(),
    )
    monkeypatch.setattr("skitter.core.runtime.collect_usage", lambda _messages, _message_id: None)
    monkeypatch.setattr(runtime, "_ensure_history", _fake_ensure_history)
    monkeypatch.setattr(runtime, "_get_session_model", _fake_get_session_model)
    monkeypatch.setattr(runtime, "_ensure_system_prompt", lambda history, _user_id: None)
    monkeypatch.setattr(runtime, "_compact_history_for_context", _noop_async)
    monkeypatch.setattr(runtime, "_trace_create", _noop_async)
    monkeypatch.setattr(runtime, "_trace_update", _noop_async)
    monkeypatch.setattr(runtime, "_trace_event", _noop_async)
    monkeypatch.setattr(runtime, "_build_limit_fallback_response", _fake_limit_fallback)

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

    assert response.text == "LIMIT_REACHED (max_tokens): The model hit its output token limit before finishing."
    assert isinstance(runtime._history["session-1"][-1], AIMessage)
    assert runtime._history["session-1"][-1].content == response.text


@pytest.mark.asyncio
async def test_handle_message_treats_skitter_no_reply_as_empty_response(monkeypatch) -> None:
    runtime = AgentRuntime(event_bus=EventBus(), graph=_NoReplyGraph())

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
                "model": "provider/main",
                "name": "provider/main",
                "api_base": "",
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
        message_id="msg-no-reply",
        channel_id="chan-1",
        user_id="user-1",
        timestamp=datetime.now(UTC),
        text="Say nothing if you have nothing to add.",
        origin="tui",
        metadata={"internal_user_id": "user-1"},
    )

    response = await runtime.handle_message("session-no-reply", envelope)

    assert response.text == ""
    assert response.attachments == []
