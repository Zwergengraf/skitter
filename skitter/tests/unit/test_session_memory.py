from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from skitter.core.events import EventBus
from skitter.core.runtime import AgentRuntime
from skitter.core.session_memory import DEFAULT_SESSION_MEMORY_TEMPLATE, SessionMemoryService
import skitter.core.session_memory as session_memory_module


@dataclass
class _SessionRow:
    id: str
    user_id: str
    scope_type: str = "private"
    model: str | None = "provider/main"
    last_model: str | None = None
    last_input_tokens: int = 0
    session_memory_status: str | None = None
    session_memory_checkpoint: datetime | None = None
    session_memory_input_tokens: int | None = None
    session_memory_last_error: str | None = None
    session_memory_path: str | None = None
    session_memory_updated_at: datetime | None = None


@dataclass
class _MessageRow:
    role: str
    content: str
    created_at: datetime
    meta: dict = field(default_factory=dict)


@dataclass
class _ToolRunRow:
    created_at: datetime
    run_id: str | None = None


class _FakeRepo:
    def __init__(self, row: _SessionRow, messages: list[_MessageRow], tool_runs: list[_ToolRunRow] | None = None) -> None:
        self.row = row
        self.messages = list(messages)
        self.tool_runs = list(tool_runs or [])

    async def get_session(self, session_id: str) -> _SessionRow | None:
        return self.row if session_id == self.row.id else None

    async def list_messages(self, session_id: str) -> list[_MessageRow]:
        assert session_id == self.row.id
        return list(self.messages)

    async def list_tool_runs_by_session(self, session_id: str) -> list[_ToolRunRow]:
        assert session_id == self.row.id
        return list(self.tool_runs)

    async def begin_session_memory_update(self, session_id: str, *, path: str) -> _SessionRow | None:
        assert session_id == self.row.id
        self.row.session_memory_status = "running"
        self.row.session_memory_last_error = None
        self.row.session_memory_path = path
        return self.row

    async def complete_session_memory_update(
        self,
        session_id: str,
        *,
        path: str,
        checkpoint: datetime | None,
        input_tokens: int | None,
    ) -> _SessionRow | None:
        assert session_id == self.row.id
        self.row.session_memory_status = "completed"
        self.row.session_memory_last_error = None
        self.row.session_memory_path = path
        self.row.session_memory_checkpoint = checkpoint
        self.row.session_memory_input_tokens = input_tokens
        self.row.session_memory_updated_at = datetime.now(UTC)
        return self.row

    async def fail_session_memory_update(self, session_id: str, *, error: str) -> _SessionRow | None:
        assert session_id == self.row.id
        self.row.session_memory_status = "failed"
        self.row.session_memory_last_error = error
        return self.row


class _SessionCtx:
    def __init__(self, token: object) -> None:
        self.token = token

    async def __aenter__(self) -> object:
        return self.token

    async def __aexit__(self, exc_type, exc, tb) -> None:
        _ = exc_type, exc, tb
        return None


class _MemoryLLM:
    def __init__(self, content: str) -> None:
        self.content = content
        self.prompts = []

    async def ainvoke(self, prompt):
        self.prompts.append(prompt)
        return AIMessage(content=self.content)


class _ArchiveLLM:
    def __init__(self, content: str) -> None:
        self.content = content
        self.prompts = []

    async def ainvoke(self, prompt):
        self.prompts.append(prompt)
        return AIMessage(content=self.content)


class _EventBusStub:
    def __init__(self) -> None:
        self.events: list[dict] = []

    async def emit_admin(self, **kwargs) -> None:
        self.events.append(kwargs)


class _SessionMemoryStub:
    def __init__(self, content: str) -> None:
        self.content = content
        self.calls: list[tuple[str, str | None, bool]] = []

    async def refresh_session_memory(self, session_id: str, *, model_name: str | None = None, force: bool = False):
        self.calls.append((session_id, model_name, force))
        return self.content


VALID_UPDATED_NOTES = """
# Session Title
_A short, distinctive title for this session._

Trip planning for Lisbon

# Current State
_What is actively happening right now, including the immediate next step or what Skitter is waiting on._

Waiting for the user to choose between spring and summer travel dates.

# User Goal
_What the user is trying to achieve in this session._

Plan a personal Lisbon trip with a clear shortlist and timing recommendation.

# Preferences And Constraints
_User preferences, boundaries, style, tools, environments, or workflow constraints that matter._

The user prefers mild weather, walkable neighborhoods, and low-stress planning.

# Important Context
_Durable facts, services, files, people, places, or environments that are relevant to this session._

Lisbon and Porto were compared, but Lisbon remained the main focus.

# Decisions
_Important choices that were made and why._

We narrowed the trip to Lisbon because it better matched the user's goals.

# Open Loops
_Follow-ups, unresolved questions, pending approvals, or next actions._

Confirm travel month and budget ceiling.

# Errors And Corrections
_What went wrong, what was corrected, and what should be avoided next time._

Avoid overloading the user with too many city options at once.

# Key Results
_Exact important outputs, decisions, or conclusions from this session._

Lisbon is the recommended destination so far.

# Worklog
_Very terse step-by-step notes on what was done._

Compared destinations, extracted preferences, and proposed the next decision.
""".strip() + "\n"


@pytest.mark.asyncio
async def test_session_memory_creates_sidecar_after_init_threshold(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    row = _SessionRow(id="session-1", user_id="user-1", last_input_tokens=5000)
    now = datetime.now(UTC)
    messages = [
        _MessageRow(
            role="user",
            content="I want help planning a relaxed Lisbon trip with good walking neighborhoods and gentle weather.",
            created_at=now - timedelta(minutes=2),
        ),
        _MessageRow(
            role="assistant",
            content="We can compare Lisbon and Porto, then narrow it down based on weather, pace, and neighborhoods.",
            created_at=now - timedelta(minutes=1),
            meta={"run_id": "run-1"},
        ),
    ]
    repo = _FakeRepo(row, messages)
    token = object()
    monkeypatch.setattr(session_memory_module, "SessionLocal", lambda: _SessionCtx(token))
    monkeypatch.setattr(session_memory_module, "Repository", lambda _session: repo)
    monkeypatch.setattr(session_memory_module, "user_workspace_root", lambda user_id: tmp_path / user_id)
    monkeypatch.setattr(session_memory_module, "ensure_user_workspace", lambda user_id: (tmp_path / user_id / "memory").mkdir(parents=True, exist_ok=True) or (tmp_path / user_id))
    monkeypatch.setattr(session_memory_module.settings, "session_memory_enabled", True)
    monkeypatch.setattr(session_memory_module.settings, "session_memory_init_tokens", 10)
    monkeypatch.setattr(session_memory_module.settings, "session_memory_update_tokens", 10)
    monkeypatch.setattr(session_memory_module, "list_models", lambda: [object()])
    llm = _MemoryLLM(VALID_UPDATED_NOTES)
    monkeypatch.setattr(session_memory_module, "build_llm", lambda model_name, purpose="main": llm)

    service = SessionMemoryService(_EventBusStub())
    updated = await service.refresh_session_memory("session-1", model_name="provider/main", force=False)

    assert updated == VALID_UPDATED_NOTES
    path = tmp_path / "user-1" / "memory" / "session-state" / "session-1.md"
    assert path.read_text(encoding="utf-8") == VALID_UPDATED_NOTES
    assert row.session_memory_status == "completed"
    assert row.session_memory_path == "memory/session-state/session-1.md"
    assert row.session_memory_checkpoint == messages[-1].created_at
    assert row.session_memory_input_tokens == 5000
    prompt = llm.prompts[0][1].content
    assert "current file" in prompt.lower()
    assert "user: I want help planning" in prompt
    assert "assistant: We can compare Lisbon and Porto" in prompt


@pytest.mark.asyncio
async def test_session_memory_skips_when_below_init_threshold(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    row = _SessionRow(id="session-2", user_id="user-1", last_input_tokens=50)
    now = datetime.now(UTC)
    messages = [
        _MessageRow(role="user", content="Hi", created_at=now - timedelta(minutes=1)),
        _MessageRow(role="assistant", content="Hello", created_at=now, meta={"run_id": "run-2"}),
    ]
    repo = _FakeRepo(row, messages)
    token = object()
    monkeypatch.setattr(session_memory_module, "SessionLocal", lambda: _SessionCtx(token))
    monkeypatch.setattr(session_memory_module, "Repository", lambda _session: repo)
    monkeypatch.setattr(session_memory_module, "user_workspace_root", lambda user_id: tmp_path / user_id)
    monkeypatch.setattr(session_memory_module, "ensure_user_workspace", lambda user_id: (tmp_path / user_id / "memory").mkdir(parents=True, exist_ok=True) or (tmp_path / user_id))
    monkeypatch.setattr(session_memory_module.settings, "session_memory_enabled", True)
    monkeypatch.setattr(session_memory_module.settings, "session_memory_init_tokens", 1000)
    monkeypatch.setattr(session_memory_module.settings, "session_memory_update_tokens", 1000)

    service = SessionMemoryService(_EventBusStub())
    updated = await service.refresh_session_memory("session-2", model_name="provider/main", force=False)

    assert updated is None
    assert row.session_memory_status is None
    assert not (tmp_path / "user-1" / "memory" / "session-state" / "session-2.md").exists()


@pytest.mark.asyncio
async def test_session_memory_updates_existing_sidecar_on_input_token_delta(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    now = datetime.now(UTC)
    row = _SessionRow(
        id="session-3",
        user_id="user-1",
        last_input_tokens=6000,
        session_memory_checkpoint=now - timedelta(minutes=5),
        session_memory_input_tokens=4500,
        session_memory_path="memory/session-state/session-3.md",
        session_memory_status="completed",
    )
    messages = [
        _MessageRow(role="user", content="Earlier planning context that was already summarized.", created_at=now - timedelta(minutes=6)),
        _MessageRow(role="assistant", content="Earlier recommendation.", created_at=now - timedelta(minutes=5), meta={"run_id": "run-old"}),
        _MessageRow(role="user", content="Please narrow it down to Lisbon and tell me the best travel month.", created_at=now - timedelta(minutes=2)),
        _MessageRow(role="assistant", content="I narrowed it to Lisbon; next we should choose between May and September.", created_at=now - timedelta(minutes=1), meta={"run_id": "run-new"}),
    ]
    repo = _FakeRepo(row, messages, tool_runs=[])
    token = object()
    monkeypatch.setattr(session_memory_module, "SessionLocal", lambda: _SessionCtx(token))
    monkeypatch.setattr(session_memory_module, "Repository", lambda _session: repo)
    monkeypatch.setattr(session_memory_module, "user_workspace_root", lambda user_id: tmp_path / user_id)
    monkeypatch.setattr(session_memory_module, "ensure_user_workspace", lambda user_id: (tmp_path / user_id / "memory").mkdir(parents=True, exist_ok=True) or (tmp_path / user_id))
    monkeypatch.setattr(session_memory_module.settings, "session_memory_enabled", True)
    monkeypatch.setattr(session_memory_module.settings, "session_memory_init_tokens", 10)
    monkeypatch.setattr(session_memory_module.settings, "session_memory_update_tokens", 10)
    monkeypatch.setattr(session_memory_module, "list_models", lambda: [object()])
    llm = _MemoryLLM(VALID_UPDATED_NOTES)
    monkeypatch.setattr(session_memory_module, "build_llm", lambda model_name, purpose="main": llm)

    existing = tmp_path / "user-1" / "memory" / "session-state" / "session-3.md"
    existing.parent.mkdir(parents=True, exist_ok=True)
    existing.write_text(DEFAULT_SESSION_MEMORY_TEMPLATE, encoding="utf-8")

    service = SessionMemoryService(_EventBusStub())
    updated = await service.refresh_session_memory("session-3", model_name="provider/main", force=False)

    assert updated == VALID_UPDATED_NOTES
    assert row.session_memory_status == "completed"
    assert row.session_memory_checkpoint == messages[-1].created_at
    assert row.session_memory_input_tokens == 6000
    prompt = llm.prompts[0][1].content
    assert "user: Please narrow it down to Lisbon" in prompt
    assert "Earlier planning context that was already summarized." not in prompt


@pytest.mark.asyncio
async def test_session_memory_skips_update_when_input_token_delta_is_below_threshold(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    now = datetime.now(UTC)
    row = _SessionRow(
        id="session-4",
        user_id="user-1",
        last_input_tokens=5200,
        session_memory_checkpoint=now - timedelta(minutes=5),
        session_memory_input_tokens=5000,
        session_memory_path="memory/session-state/session-4.md",
        session_memory_status="completed",
    )
    messages = [
        _MessageRow(role="user", content="Earlier context.", created_at=now - timedelta(minutes=6)),
        _MessageRow(role="assistant", content="Earlier reply.", created_at=now - timedelta(minutes=5), meta={"run_id": "run-old"}),
        _MessageRow(role="user", content="A short follow-up.", created_at=now - timedelta(minutes=1)),
        _MessageRow(role="assistant", content="A short answer.", created_at=now, meta={"run_id": "run-new"}),
    ]
    repo = _FakeRepo(row, messages, tool_runs=[])
    token = object()
    monkeypatch.setattr(session_memory_module, "SessionLocal", lambda: _SessionCtx(token))
    monkeypatch.setattr(session_memory_module, "Repository", lambda _session: repo)
    monkeypatch.setattr(session_memory_module, "user_workspace_root", lambda user_id: tmp_path / user_id)
    monkeypatch.setattr(session_memory_module, "ensure_user_workspace", lambda user_id: (tmp_path / user_id / "memory").mkdir(parents=True, exist_ok=True) or (tmp_path / user_id))
    monkeypatch.setattr(session_memory_module.settings, "session_memory_enabled", True)
    monkeypatch.setattr(session_memory_module.settings, "session_memory_update_tokens", 500)

    existing = tmp_path / "user-1" / "memory" / "session-state" / "session-4.md"
    existing.parent.mkdir(parents=True, exist_ok=True)
    existing.write_text(DEFAULT_SESSION_MEMORY_TEMPLATE, encoding="utf-8")

    service = SessionMemoryService(_EventBusStub())
    updated = await service.refresh_session_memory("session-4", model_name="provider/main", force=False)

    assert updated == DEFAULT_SESSION_MEMORY_TEMPLATE
    assert row.session_memory_status == "completed"
    assert row.session_memory_input_tokens == 5000


@pytest.mark.asyncio
async def test_summarize_session_prefers_structured_sidecar(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = AgentRuntime(event_bus=EventBus(), graph=object())
    runtime.set_session_memory_service(
        _SessionMemoryStub(
            "# Session Title\n_Title_\n\n# Current State\n_State_\n\nWaiting for the user's answer about travel dates.\n"
        )
    )
    runtime._history["session-4"] = [
        SystemMessage(
            content="Older archive summary",
            additional_kwargs={
                "conversation_summary": True,
                "summary_checkpoint": datetime(2026, 3, 1, 10, 0, tzinfo=UTC).isoformat(),
            },
        ),
        HumanMessage(content="Raw transcript that should not be the primary archive input."),
    ]
    llm = _ArchiveLLM("## Open Loops\n- Waiting for the user's answer about travel dates")
    monkeypatch.setattr("skitter.core.runtime.list_models", lambda: [object()])
    monkeypatch.setattr("skitter.core.runtime.build_llm", lambda model_name, purpose="main": llm)

    result = await runtime.summarize_session("session-4", model_name="provider/main")

    assert result == "## Open Loops\n- Waiting for the user's answer about travel dates"
    prompt = llm.prompts[0][1].content
    assert "Structured session memory:" in prompt
    assert "Waiting for the user's answer about travel dates." in prompt
    assert "Session messages to summarize:" not in prompt
