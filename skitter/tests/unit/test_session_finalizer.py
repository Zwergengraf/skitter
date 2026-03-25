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
    last_model: str | None = None
    model: str | None = None
    summary_status: str | None = None
    summary_attempts: int | None = None
    summary_next_retry_at: datetime | None = None
    summary_last_error: str | None = None
    summary_path: str | None = None
    summary_completed_at: datetime | None = None


class _FakeRepo:
    def __init__(self, row: _SessionRow) -> None:
        self.row = row

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
        self.calls: list[tuple[str, str, Path, bool]] = []

    async def index_file(self, user_id: str, session_id: str | None, path: Path, force: bool = False) -> bool:
        self.calls.append((user_id, str(session_id), path, force))
        if self.fail_once:
            self.fail_once = False
            raise RuntimeError("embed failed")
        return True


class _EventBusStub:
    async def emit_admin(self, **kwargs) -> None:
        _ = kwargs


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
    assert memory.calls == [("user-1", "session-1", summary_file, True)]


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
