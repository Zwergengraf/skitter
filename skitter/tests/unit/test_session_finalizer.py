from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from skitter.core.session_finalizer import SessionFinalizerService
import skitter.core.session_finalizer as finalizer_module
import skitter.core.sessions as sessions_module


@dataclass
class _SessionRow:
    id: str
    user_id: str
    created_at: datetime
    agent_profile_id: str | None = None
    last_model: str | None = None
    model: str | None = None
    summary_status: str | None = None
    summary_attempts: int | None = None
    summary_next_retry_at: datetime | None = None
    summary_last_error: str | None = None
    summary_path: str | None = None
    summary_completed_at: datetime | None = None
    session_memory_path: str | None = None


@dataclass
class _ProfileRow:
    id: str
    user_id: str
    slug: str


class _FakeRepo:
    def __init__(self, row: _SessionRow, profiles: dict[str, _ProfileRow] | None = None) -> None:
        self.row = row
        self.profiles = profiles or {}

    async def claim_next_session_summary(self) -> _SessionRow | None:
        now = datetime.now(UTC)
        if self.row.summary_status != "pending":
            return None
        if self.row.summary_next_retry_at is not None and self.row.summary_next_retry_at > now:
            return None
        self.row.summary_status = "running"
        self.row.summary_attempts = int(self.row.summary_attempts or 0) + 1
        self.row.summary_next_retry_at = None
        return self.row

    async def complete_session_summary(self, session_id: str, *, summary_path: str) -> _SessionRow | None:
        assert session_id == self.row.id
        self.row.summary_status = "completed"
        self.row.summary_last_error = None
        self.row.summary_path = summary_path
        self.row.summary_completed_at = datetime.now(UTC)
        return self.row

    async def fail_session_summary(
        self,
        session_id: str,
        *,
        error: str,
        retry_at: datetime | None,
        terminal: bool,
    ) -> _SessionRow | None:
        assert session_id == self.row.id
        self.row.summary_status = "failed" if terminal else "pending"
        self.row.summary_last_error = error
        self.row.summary_next_retry_at = retry_at
        self.row.summary_completed_at = None
        return self.row

    async def get_session(self, session_id: str) -> _SessionRow | None:
        return self.row if session_id == self.row.id else None

    async def get_agent_profile(self, profile_id: str) -> _ProfileRow | None:
        return self.profiles.get(profile_id)


class _SessionCtx:
    def __init__(self, token: object) -> None:
        self.token = token

    async def __aenter__(self) -> object:
        return self.token

    async def __aexit__(self, exc_type, exc, tb) -> None:
        _ = exc_type, exc, tb
        return None


class _MemoryStub:
    def __init__(self, *, fail_once: bool = False) -> None:
        self.fail_once = fail_once
        self.calls: list[tuple[str, str, Path, bool, str | None]] = []

    async def index_file(
        self,
        user_id: str,
        session_id: str | None,
        path: Path,
        force: bool = False,
        *,
        agent_profile_id: str | None = None,
    ) -> bool:
        self.calls.append((user_id, str(session_id), path, force, agent_profile_id))
        if self.fail_once:
            self.fail_once = False
            raise RuntimeError("embed failed")
        return True


class _EventBusStub:
    async def emit_admin(self, **kwargs) -> None:
        _ = kwargs


class _MemoryHubStub:
    def __init__(self) -> None:
        self.contexts = []
        self.archiving = []
        self.stores = []
        self.archived = []

    def context_for(self, **kwargs):
        self.contexts.append(kwargs)
        return kwargs

    async def before_session_archive(self, ctx, session_id: str) -> None:
        self.archiving.append((ctx, session_id))

    async def store(self, ctx, request):
        self.stores.append((ctx, request))
        return type("StoreResult", (), {"stored": 1, "errors": {}})()

    async def on_session_archived(self, ctx, event) -> None:
        self.archived.append((ctx, event))


def _patch_repo(monkeypatch: pytest.MonkeyPatch, repo: _FakeRepo) -> None:
    token = object()
    monkeypatch.setattr(finalizer_module, "SessionLocal", lambda: _SessionCtx(token))
    monkeypatch.setattr(finalizer_module, "Repository", lambda _session: repo)


@pytest.mark.asyncio
async def test_session_finalizer_completes_summary_and_indexes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    row = _SessionRow(
        id="session-1",
        user_id="user-1",
        created_at=datetime.now(UTC),
        last_model="provider/last",
        model="provider/main",
        summary_status="pending",
        summary_attempts=0,
    )
    repo = _FakeRepo(row)
    _patch_repo(monkeypatch, repo)
    monkeypatch.setattr(sessions_module, "user_workspace_root", lambda user_id: tmp_path / user_id)
    monkeypatch.setattr(finalizer_module, "current_summary_date", lambda: date(2026, 3, 25))

    captured: dict[str, str | None] = {"session_id": None, "model_name": None}

    class _RuntimeStub:
        event_bus = _EventBusStub()

        async def summarize_session(self, session_id: str, model_name: str | None = None) -> str:
            captured["session_id"] = session_id
            captured["model_name"] = model_name
            return "summary text"

    memory = _MemoryStub()
    service = SessionFinalizerService(_RuntimeStub(), memory_service=memory)

    handled = await service.run_once()

    assert handled is True
    assert captured == {"session_id": "session-1", "model_name": "provider/last"}
    assert row.summary_status == "completed"
    assert row.summary_attempts == 1
    assert row.summary_path == "memory/session-summaries/2026-03-25.md"
    summary_file = tmp_path / "user-1" / "memory" / "session-summaries" / "2026-03-25.md"
    assert summary_file.read_text(encoding="utf-8") == "# Session Summary (session-1)\n\nsummary text\n"
    assert memory.calls == [("user-1", "session-1", summary_file, True, None)]


@pytest.mark.asyncio
async def test_session_finalizer_uses_agent_profile_workspace_for_archive(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    row = _SessionRow(
        id="session-profile",
        user_id="user-1",
        agent_profile_id="profile-2",
        created_at=datetime.now(UTC),
        summary_status="pending",
        summary_attempts=0,
    )
    repo = _FakeRepo(row, {"profile-2": _ProfileRow(id="profile-2", user_id="user-1", slug="work")})
    _patch_repo(monkeypatch, repo)
    monkeypatch.setattr(
        sessions_module,
        "user_workspace_root",
        lambda user_id, profile_slug=None: tmp_path / user_id / (profile_slug or "default"),
    )
    monkeypatch.setattr(finalizer_module, "current_summary_date", lambda: date(2026, 3, 25))

    class _RuntimeStub:
        event_bus = _EventBusStub()

        async def summarize_session(self, session_id: str, model_name: str | None = None) -> str:
            _ = session_id, model_name
            return "profile summary"

    memory = _MemoryStub()
    service = SessionFinalizerService(_RuntimeStub(), memory_service=memory)

    handled = await service.run_once()

    assert handled is True
    assert row.summary_status == "completed"
    assert row.summary_path == "memory/session-summaries/2026-03-25.md"
    profile_summary_file = tmp_path / "user-1" / "work" / "memory" / "session-summaries" / "2026-03-25.md"
    default_summary_file = tmp_path / "user-1" / "default" / "memory" / "session-summaries" / "2026-03-25.md"
    assert profile_summary_file.read_text(encoding="utf-8") == (
        "# Session Summary (session-profile)\n\nprofile summary\n"
    )
    assert not default_summary_file.exists()
    assert memory.calls == [("user-1", "session-profile", profile_summary_file, True, "profile-2")]


@pytest.mark.asyncio
async def test_session_finalizer_does_not_fall_back_to_default_when_profile_is_missing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    row = _SessionRow(
        id="session-missing-profile",
        user_id="user-1",
        agent_profile_id="missing-profile",
        created_at=datetime.now(UTC),
        summary_status="pending",
        summary_attempts=0,
    )
    repo = _FakeRepo(row)
    _patch_repo(monkeypatch, repo)
    monkeypatch.setattr(
        sessions_module,
        "user_workspace_root",
        lambda user_id, profile_slug=None: tmp_path / user_id / (profile_slug or "default"),
    )
    monkeypatch.setattr(finalizer_module, "current_summary_date", lambda: date(2026, 3, 25))

    class _RuntimeStub:
        event_bus = _EventBusStub()

        async def summarize_session(self, session_id: str, model_name: str | None = None) -> str:
            _ = session_id, model_name
            raise AssertionError("summary should not run without a resolvable profile")

    memory = _MemoryStub()
    service = SessionFinalizerService(_RuntimeStub(), memory_service=memory)

    handled = await service.run_once()

    assert handled is True
    assert row.summary_status == "pending"
    assert row.summary_attempts == 1
    assert row.summary_last_error == "agent profile for session session-missing-profile was not found"
    default_summary_file = tmp_path / "user-1" / "default" / "memory" / "session-summaries" / "2026-03-25.md"
    assert not default_summary_file.exists()
    assert memory.calls == []


@pytest.mark.asyncio
async def test_session_finalizer_routes_archive_store_through_memory_hub(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    row = _SessionRow(
        id="session-hub",
        user_id="user-1",
        agent_profile_id="profile-hub",
        created_at=datetime.now(UTC),
        summary_status="pending",
        summary_attempts=0,
    )
    repo = _FakeRepo(row, {"profile-hub": _ProfileRow(id="profile-hub", user_id="user-1", slug="research")})
    _patch_repo(monkeypatch, repo)
    monkeypatch.setattr(
        sessions_module,
        "user_workspace_root",
        lambda user_id, profile_slug=None: tmp_path / user_id / (profile_slug or "default"),
    )
    monkeypatch.setattr(finalizer_module, "current_summary_date", lambda: date(2026, 3, 25))
    memory_hub = _MemoryHubStub()

    class _RuntimeStub:
        event_bus = _EventBusStub()

        async def summarize_session(self, session_id: str, model_name: str | None = None) -> str:
            _ = session_id, model_name
            return "summary through hub"

    _RuntimeStub.memory_hub = memory_hub
    memory = _MemoryStub(fail_once=True)
    service = SessionFinalizerService(_RuntimeStub(), memory_service=memory)

    handled = await service.run_once()

    assert handled is True
    assert row.summary_status == "completed"
    assert memory.calls == []
    assert memory_hub.contexts[0]["agent_profile_id"] == "profile-hub"
    assert memory_hub.contexts[0]["agent_profile_slug"] == "research"
    assert memory_hub.archiving[0][1] == "session-hub"
    assert len(memory_hub.stores) == 1
    store_request = memory_hub.stores[0][1]
    assert store_request.source == "archive"
    assert store_request.items[0].metadata["index_file"] is True
    assert store_request.items[0].metadata["source"] == "2026-03-25.md"
    assert memory_hub.archived[0][1].archive_summary == "summary through hub"
    assert memory_hub.archived[0][1].session_memory_path == "memory/session-state/session-hub.md"


@pytest.mark.asyncio
async def test_session_finalizer_deletes_session_memory_sidecar_after_success(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    row = _SessionRow(
        id="session-sidecar",
        user_id="user-1",
        agent_profile_id="profile-sidecar",
        created_at=datetime.now(UTC),
        summary_status="pending",
        summary_attempts=0,
        session_memory_path="memory/session-state/session-sidecar.md",
    )
    repo = _FakeRepo(
        row,
        {"profile-sidecar": _ProfileRow(id="profile-sidecar", user_id="user-1", slug="sidecar-profile")},
    )
    _patch_repo(monkeypatch, repo)
    monkeypatch.setattr(sessions_module, "user_workspace_root", lambda user_id: tmp_path / user_id)
    monkeypatch.setattr(finalizer_module, "current_summary_date", lambda: date(2026, 3, 25))
    sidecar_path = tmp_path / "user-1" / "memory" / "session-state" / "session-sidecar.md"
    sidecar_path.parent.mkdir(parents=True, exist_ok=True)
    sidecar_path.write_text("temporary session state", encoding="utf-8")
    captured_profile_slugs: list[str | None] = []

    def _current_session_memory_path(user_id: str, session_id: str, profile_slug: str | None = None) -> Path:
        _ = user_id, session_id
        captured_profile_slugs.append(profile_slug)
        return sidecar_path

    monkeypatch.setattr(
        finalizer_module,
        "current_session_memory_path",
        _current_session_memory_path,
    )

    class _RuntimeStub:
        event_bus = _EventBusStub()

        async def summarize_session(self, session_id: str, model_name: str | None = None) -> str:
            _ = session_id, model_name
            return "summary text"

    service = SessionFinalizerService(_RuntimeStub(), memory_service=_MemoryStub())

    handled = await service.run_once()

    assert handled is True
    assert row.summary_status == "completed"
    assert not sidecar_path.exists()
    assert captured_profile_slugs == ["sidecar-profile"]


@pytest.mark.asyncio
async def test_session_finalizer_keeps_session_memory_sidecar_on_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    row = _SessionRow(
        id="session-sidecar-fail",
        user_id="user-1",
        created_at=datetime.now(UTC),
        summary_status="pending",
        summary_attempts=0,
        session_memory_path="memory/session-state/session-sidecar-fail.md",
    )
    repo = _FakeRepo(row)
    _patch_repo(monkeypatch, repo)
    monkeypatch.setattr(sessions_module, "user_workspace_root", lambda user_id: tmp_path / user_id)
    monkeypatch.setattr(finalizer_module, "current_summary_date", lambda: date(2026, 3, 25))
    sidecar_path = tmp_path / "user-1" / "memory" / "session-state" / "session-sidecar-fail.md"
    sidecar_path.parent.mkdir(parents=True, exist_ok=True)
    sidecar_path.write_text("temporary session state", encoding="utf-8")
    monkeypatch.setattr(
        finalizer_module,
        "current_session_memory_path",
        lambda user_id, session_id, profile_slug=None: sidecar_path,
    )

    class _RuntimeStub:
        event_bus = _EventBusStub()

        async def summarize_session(self, session_id: str, model_name: str | None = None) -> str:
            _ = session_id, model_name
            return "summary text"

    service = SessionFinalizerService(_RuntimeStub(), memory_service=_MemoryStub(fail_once=True))

    handled = await service.run_once()

    assert handled is True
    assert row.summary_status == "pending"
    assert sidecar_path.exists()


@pytest.mark.asyncio
async def test_session_finalizer_retries_with_backoff_and_marks_terminal_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = _SessionRow(
        id="session-2",
        user_id="user-1",
        created_at=datetime.now(UTC),
        summary_status="pending",
        summary_attempts=0,
    )
    repo = _FakeRepo(row)
    _patch_repo(monkeypatch, repo)

    class _RuntimeStub:
        event_bus = _EventBusStub()

        async def summarize_session(self, session_id: str, model_name: str | None = None) -> str:
            _ = session_id, model_name
            raise RuntimeError("llm exploded")

    service = SessionFinalizerService(_RuntimeStub(), memory_service=_MemoryStub())
    expected_minutes = [1, 5, 15, 60]

    for index, expected in enumerate(expected_minutes, start=1):
        handled = await service.run_once()
        assert handled is True
        assert row.summary_status == "pending"
        assert row.summary_attempts == index
        assert row.summary_last_error == "llm exploded"
        assert row.summary_next_retry_at is not None
        delta = row.summary_next_retry_at - datetime.now(UTC)
        assert timedelta(minutes=expected - 1) < delta <= timedelta(minutes=expected, seconds=5)
        row.summary_next_retry_at = datetime.now(UTC) - timedelta(seconds=1)

    handled = await service.run_once()
    assert handled is True
    assert row.summary_status == "failed"
    assert row.summary_attempts == 5
    assert row.summary_last_error == "llm exploded"
    assert row.summary_next_retry_at is None


@pytest.mark.asyncio
async def test_session_finalizer_overwrites_summary_file_on_retry(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    row = _SessionRow(
        id="session-3",
        user_id="user-1",
        created_at=datetime.now(UTC),
        summary_status="pending",
        summary_attempts=0,
    )
    repo = _FakeRepo(row)
    _patch_repo(monkeypatch, repo)
    monkeypatch.setattr(sessions_module, "user_workspace_root", lambda user_id: tmp_path / user_id)
    monkeypatch.setattr(finalizer_module, "current_summary_date", lambda: date(2026, 3, 25))

    class _RuntimeStub:
        event_bus = _EventBusStub()

        async def summarize_session(self, session_id: str, model_name: str | None = None) -> str:
            _ = session_id, model_name
            return "stable summary"

    memory = _MemoryStub(fail_once=True)
    service = SessionFinalizerService(_RuntimeStub(), memory_service=memory)

    handled = await service.run_once()
    assert handled is True
    assert row.summary_status == "pending"
    summary_file = tmp_path / "user-1" / "memory" / "session-summaries" / "2026-03-25.md"
    assert summary_file.read_text(encoding="utf-8") == "# Session Summary (session-3)\n\nstable summary\n"

    row.summary_next_retry_at = datetime.now(UTC) - timedelta(seconds=1)
    handled = await service.run_once()
    assert handled is True
    assert row.summary_status == "completed"
    assert summary_file.read_text(encoding="utf-8") == "# Session Summary (session-3)\n\nstable summary\n"
    assert len(memory.calls) == 2


@pytest.mark.asyncio
async def test_session_finalizer_appends_multiple_sessions_into_same_daily_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    row = _SessionRow(
        id="session-4",
        user_id="user-1",
        created_at=datetime.now(UTC),
        summary_status="pending",
        summary_attempts=0,
    )
    repo = _FakeRepo(row)
    _patch_repo(monkeypatch, repo)
    monkeypatch.setattr(sessions_module, "user_workspace_root", lambda user_id: tmp_path / user_id)
    monkeypatch.setattr(finalizer_module, "current_summary_date", lambda: date(2026, 3, 25))

    daily_file = tmp_path / "user-1" / "memory" / "session-summaries" / "2026-03-25.md"
    daily_file.parent.mkdir(parents=True, exist_ok=True)
    daily_file.write_text("# Session Summary (session-1)\n\nfirst summary\n", encoding="utf-8")

    class _RuntimeStub:
        event_bus = _EventBusStub()

        async def summarize_session(self, session_id: str, model_name: str | None = None) -> str:
            _ = session_id, model_name
            return "second summary"

    memory = _MemoryStub()
    service = SessionFinalizerService(_RuntimeStub(), memory_service=memory)

    handled = await service.run_once()

    assert handled is True
    assert daily_file.read_text(encoding="utf-8") == (
        "# Session Summary (session-1)\n\nfirst summary\n\n"
        "# Session Summary (session-4)\n\nsecond summary\n"
    )
