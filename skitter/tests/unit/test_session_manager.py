from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from skitter.core.sessions import SessionManager
import skitter.core.sessions as sessions_module


@dataclass
class _SessionRow:
    id: str
    user_id: str
    agent_profile_id: str
    status: str
    scope_type: str
    scope_id: str
    model: str = "provider/main"
    last_model: str | None = None
    summary_status: str | None = None
    summary_attempts: int | None = None


class _FakeRepo:
    def __init__(self) -> None:
        self.sessions: dict[str, _SessionRow] = {}
        self.create_calls = 0
        self.queued_summary_ids: list[str] = []
        self.profile_default_models: dict[str, str | None] = {}

    async def get_session(self, session_id: str) -> _SessionRow | None:
        return self.sessions.get(session_id)

    async def get_active_session_by_scope(
        self,
        scope_type: str,
        scope_id: str,
        agent_profile_id: str | None = None,
    ) -> _SessionRow | None:
        for row in self.sessions.values():
            if (
                row.status == "active"
                and row.scope_type == scope_type
                and row.scope_id == scope_id
                and (agent_profile_id is None or row.agent_profile_id == agent_profile_id)
            ):
                return row
        return None

    async def create_session(
        self,
        user_id: str,
        agent_profile_id: str | None = None,
        status: str = "active",
        model: str | None = None,
        origin: str = "discord",
        scope_type: str = "private",
        scope_id: str | None = None,
    ) -> _SessionRow:
        _ = origin
        self.create_calls += 1
        session_id = f"created-{self.create_calls}"
        normalized_scope_id = scope_id or f"{scope_type}:{agent_profile_id or user_id}"
        row = _SessionRow(
            id=session_id,
            user_id=user_id,
            agent_profile_id=agent_profile_id or "profile-default",
            status=status,
            scope_type=scope_type,
            scope_id=normalized_scope_id,
            model=model or "provider/main",
        )
        self.sessions[row.id] = row
        return row

    async def end_session(self, session_id: str, status: str = "ended") -> _SessionRow | None:
        row = self.sessions.get(session_id)
        if row is None:
            return None
        row.status = status
        self.sessions[session_id] = row
        return row

    async def queue_session_summary(self, session_id: str) -> _SessionRow | None:
        row = self.sessions.get(session_id)
        if row is None:
            return None
        row.summary_status = "pending"
        row.summary_attempts = 0
        self.queued_summary_ids.append(session_id)
        self.sessions[session_id] = row
        return row

    async def get_profile_default_model_name(self, profile_id: str) -> str | None:
        return self.profile_default_models.get(profile_id)


class _SessionCtx:
    def __init__(self, token: object) -> None:
        self.token = token

    async def __aenter__(self) -> object:
        return self.token

    async def __aexit__(self, exc_type, exc, tb) -> None:
        _ = exc_type, exc, tb
        return None


class _RuntimeStub:
    class _EventBusStub:
        async def emit_admin(self, **kwargs) -> None:
            _ = kwargs

    event_bus = _EventBusStub()

    async def summarize_session(self, session_id: str, model_name: str | None = None) -> str:
        _ = model_name
        _ = session_id
        return "summary"

    def clear_history(self, session_id: str) -> None:
        _ = session_id


@pytest.mark.asyncio
async def test_get_or_create_session_refreshes_stale_cached_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _FakeRepo()
    old_session = _SessionRow(
        id="session-old",
        user_id="user-1",
        agent_profile_id="profile-default",
        status="ended",
        scope_type="private",
        scope_id="private:profile-default",
    )
    new_session = _SessionRow(
        id="session-new",
        user_id="user-1",
        agent_profile_id="profile-default",
        status="active",
        scope_type="private",
        scope_id="private:profile-default",
    )
    repo.sessions = {
        old_session.id: old_session,
        new_session.id: new_session,
    }

    token = object()
    monkeypatch.setattr(sessions_module, "SessionLocal", lambda: _SessionCtx(token))
    monkeypatch.setattr(sessions_module, "Repository", lambda _session: repo)
    monkeypatch.setattr(sessions_module, "ensure_profile_workspace", lambda _user_id, _profile_slug=None: None)
    monkeypatch.setattr(sessions_module, "resolve_model_name", lambda _value, purpose: f"{purpose}-model")

    manager = SessionManager(runtime=_RuntimeStub())
    manager._scope_session["profile-default:private:profile-default"] = old_session.id

    resolved = await manager.get_or_create_session_for_scope(
        user_id="user-1",
        agent_profile_id="profile-default",
        agent_profile_slug="default",
        scope_type="private",
        scope_id="private:profile-default",
        origin="discord",
        cache_key="private:profile-default",
    )

    assert resolved == new_session.id
    assert manager._scope_session["profile-default:private:profile-default"] == new_session.id
    assert repo.create_calls == 0


@pytest.mark.asyncio
async def test_start_new_session_queues_background_summary_without_blocking(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    repo = _FakeRepo()
    active_session = _SessionRow(
        id="session-active",
        user_id="user-1",
        agent_profile_id="profile-default",
        status="active",
        scope_type="private",
        scope_id="private:profile-default",
        model="provider/session-model",
    )
    repo.sessions = {active_session.id: active_session}

    token = object()
    monkeypatch.setattr(sessions_module, "SessionLocal", lambda: _SessionCtx(token))
    monkeypatch.setattr(sessions_module, "Repository", lambda _session: repo)
    monkeypatch.setattr(sessions_module, "ensure_profile_workspace", lambda _user_id, _profile_slug=None: None)
    monkeypatch.setattr(
        sessions_module,
        "user_workspace_root",
        lambda user_id, profile_slug=None: tmp_path / user_id / (profile_slug or "default"),
    )
    monkeypatch.setattr(sessions_module, "resolve_model_name", lambda _value, purpose: f"{purpose}-model")

    class _RuntimeCapture:
        class _EventBusStub:
            async def emit_admin(self, **kwargs) -> None:
                _ = kwargs

        event_bus = _EventBusStub()

        async def summarize_session(self, session_id: str, model_name: str | None = None) -> str:
            raise AssertionError("summarize_session should not run inline when starting a new session")

        def clear_history(self, session_id: str) -> None:
            _ = session_id

    class _MemoryStub:
        async def index_file(self, user_id: str, session_id: str, summary_path: object, force: bool = False) -> None:
            raise AssertionError("memory indexing should not run inline when starting a new session")

    manager = SessionManager(runtime=_RuntimeCapture(), memory_service=_MemoryStub())

    summary_path, new_session_id = await manager.start_new_session_for_scope(
        user_id="user-1",
        agent_profile_id="profile-default",
        agent_profile_slug="default",
        scope_type="private",
        scope_id="private:profile-default",
        origin="discord",
        channel_id=None,
    )

    assert summary_path is None
    assert new_session_id.startswith("created-")
    assert repo.sessions["session-active"].status == "ended"
    assert repo.sessions["session-active"].summary_status == "pending"
    assert repo.queued_summary_ids == ["session-active"]


@pytest.mark.asyncio
async def test_new_sessions_use_profile_default_model_when_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _FakeRepo()

    token = object()
    monkeypatch.setattr(sessions_module, "SessionLocal", lambda: _SessionCtx(token))
    monkeypatch.setattr(sessions_module, "Repository", lambda _session: repo)
    monkeypatch.setattr(sessions_module, "ensure_profile_workspace", lambda _user_id, _profile_slug=None: None)
    monkeypatch.setattr(sessions_module, "resolve_model_name", lambda value=None, purpose="main": value or f"{purpose}-model")
    async def _profile_default_model(_repo, profile_id: str | None, *, purpose: str = "main") -> str | None:
        _ = _repo, purpose
        if profile_id == "profile-default":
            return "provider/fast"
        return None
    monkeypatch.setattr(sessions_module, "resolve_profile_default_model_name", _profile_default_model)

    manager = SessionManager(runtime=_RuntimeStub())

    session_id = await manager.get_or_create_session_for_scope(
        user_id="user-1",
        agent_profile_id="profile-default",
        agent_profile_slug="default",
        scope_type="private",
        scope_id="private:profile-default",
        origin="discord",
        cache_key="private:profile-default",
    )

    assert session_id == "created-1"
    assert repo.sessions[session_id].model == "provider/fast"
