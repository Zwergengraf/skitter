from __future__ import annotations

from dataclasses import dataclass

import pytest

from skitter.core.sessions import SessionManager
import skitter.core.sessions as sessions_module


@dataclass
class _SessionRow:
    id: str
    user_id: str
    status: str
    scope_type: str
    scope_id: str
    model: str = "provider/main"


class _FakeRepo:
    def __init__(self) -> None:
        self.sessions: dict[str, _SessionRow] = {}
        self.create_calls = 0

    async def get_session(self, session_id: str) -> _SessionRow | None:
        return self.sessions.get(session_id)

    async def get_active_session_by_scope(self, scope_type: str, scope_id: str) -> _SessionRow | None:
        for row in self.sessions.values():
            if row.status == "active" and row.scope_type == scope_type and row.scope_id == scope_id:
                return row
        return None

    async def create_session(
        self,
        user_id: str,
        status: str = "active",
        model: str | None = None,
        origin: str = "discord",
        scope_type: str = "private",
        scope_id: str | None = None,
    ) -> _SessionRow:
        _ = origin
        self.create_calls += 1
        session_id = f"created-{self.create_calls}"
        normalized_scope_id = scope_id or f"{scope_type}:{user_id}"
        row = _SessionRow(
            id=session_id,
            user_id=user_id,
            status=status,
            scope_type=scope_type,
            scope_id=normalized_scope_id,
            model=model or "provider/main",
        )
        self.sessions[row.id] = row
        return row


class _SessionCtx:
    def __init__(self, token: object) -> None:
        self.token = token

    async def __aenter__(self) -> object:
        return self.token

    async def __aexit__(self, exc_type, exc, tb) -> None:
        _ = exc_type, exc, tb
        return None


class _RuntimeStub:
    async def summarize_session(self, session_id: str) -> str:
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
        status="ended",
        scope_type="private",
        scope_id="private:user-1",
    )
    new_session = _SessionRow(
        id="session-new",
        user_id="user-1",
        status="active",
        scope_type="private",
        scope_id="private:user-1",
    )
    repo.sessions = {
        old_session.id: old_session,
        new_session.id: new_session,
    }

    token = object()
    monkeypatch.setattr(sessions_module, "SessionLocal", lambda: _SessionCtx(token))
    monkeypatch.setattr(sessions_module, "Repository", lambda _session: repo)
    monkeypatch.setattr(sessions_module, "ensure_user_workspace", lambda _user_id: None)
    monkeypatch.setattr(sessions_module, "resolve_model_name", lambda _value, purpose: f"{purpose}-model")

    manager = SessionManager(runtime=_RuntimeStub(), workspace_root="workspace")
    manager._scope_session["private:user-1"] = old_session.id

    resolved = await manager.get_or_create_session_for_scope(
        user_id="user-1",
        scope_type="private",
        scope_id="private:user-1",
        origin="discord",
        cache_key="private:user-1",
    )

    assert resolved == new_session.id
    assert manager._scope_session["private:user-1"] == new_session.id
    assert repo.create_calls == 0
