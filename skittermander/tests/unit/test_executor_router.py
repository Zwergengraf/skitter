from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pytest

from skittermander.core.config import settings
from skittermander.tools.executors import ExecutorRouter, NodeExecutorHub
import skittermander.tools.executors as executors_module


@dataclass
class _ExecutorRow:
    id: str
    name: str
    kind: str
    owner_user_id: str = "user-1"
    disabled: bool = False
    status: str = "online"
    capabilities: dict[str, Any] | None = None
    created_at: datetime = datetime.now(UTC)
    last_seen_at: datetime | None = None
    platform: str | None = None
    hostname: str | None = None


class _FakeRepo:
    def __init__(self) -> None:
        self.user_default_executor_id: str | None = None
        self.executors_by_id: dict[str, _ExecutorRow] = {}
        self.executors_by_name: dict[str, _ExecutorRow] = {}
        self.docker_executor = _ExecutorRow(id="docker-exec", name="docker-default", kind="docker")

    async def get_user_default_executor_id(self, user_id: str) -> str | None:
        _ = user_id
        return self.user_default_executor_id

    async def get_or_create_docker_executor(self, user_id: str) -> _ExecutorRow:
        _ = user_id
        return self.docker_executor

    async def get_docker_executor_for_user(self, user_id: str) -> _ExecutorRow | None:
        _ = user_id
        return self.docker_executor

    async def get_executor_for_user(self, user_id: str, executor_id: str) -> _ExecutorRow | None:
        _ = user_id
        return self.executors_by_id.get(executor_id)

    async def get_executor_for_user_by_name(self, user_id: str, name: str) -> _ExecutorRow | None:
        _ = user_id
        return self.executors_by_name.get(name)

    async def update_executor(self, executor_id: str, **fields: Any) -> _ExecutorRow | None:
        row = self.executors_by_id.get(executor_id)
        if row is None:
            return None
        for key, value in fields.items():
            if value is not None:
                setattr(row, key, value)
        return row

    async def list_executors_for_user(self, user_id: str, include_disabled: bool = False):
        _ = user_id, include_disabled
        return list(self.executors_by_id.values())


class _SessionCtx:
    def __init__(self, token: object) -> None:
        self.token = token

    async def __aenter__(self) -> object:
        return self.token

    async def __aexit__(self, exc_type, exc, tb) -> None:
        _ = exc_type, exc, tb
        return None


@pytest.fixture
def fake_repo(monkeypatch: pytest.MonkeyPatch) -> _FakeRepo:
    repo = _FakeRepo()
    token = object()

    monkeypatch.setattr(executors_module, "SessionLocal", lambda: _SessionCtx(token))
    monkeypatch.setattr(executors_module, "Repository", lambda session: repo)
    return repo


@pytest.mark.asyncio
async def test_resolve_executor_precedence_target_then_session_then_user_default(
    fake_repo: _FakeRepo,
) -> None:
    router = ExecutorRouter(NodeExecutorHub())
    target = _ExecutorRow(id="exec-target", name="target", kind="node")
    session_default = _ExecutorRow(id="exec-session", name="session", kind="node")
    user_default = _ExecutorRow(id="exec-user", name="user", kind="node")
    fake_repo.executors_by_id = {
        target.id: target,
        session_default.id: session_default,
        user_default.id: user_default,
    }
    fake_repo.executors_by_name = {row.name: row for row in fake_repo.executors_by_id.values()}
    fake_repo.user_default_executor_id = user_default.id

    await router.set_session_default("session-1", session_default.id)
    resolved = await router._resolve_executor(
        user_id="user-1",
        session_id="session-1",
        target_machine=target.id,
    )
    assert resolved.id == target.id

    resolved = await router._resolve_executor(
        user_id="user-1",
        session_id="session-1",
        target_machine=None,
    )
    assert resolved.id == session_default.id

    await router.set_session_default("session-1", None)
    resolved = await router._resolve_executor(
        user_id="user-1",
        session_id="session-1",
        target_machine=None,
    )
    assert resolved.id == user_default.id


@pytest.mark.asyncio
async def test_resolve_executor_unknown_target_raises(fake_repo: _FakeRepo) -> None:
    router = ExecutorRouter(NodeExecutorHub())
    with pytest.raises(RuntimeError, match="Unknown target machine"):
        await router._resolve_executor(
            user_id="user-1",
            session_id="session-1",
            target_machine="missing",
        )


@pytest.mark.asyncio
async def test_resolve_executor_no_default_and_auto_docker_disabled_raises(
    fake_repo: _FakeRepo,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    router = ExecutorRouter(NodeExecutorHub())
    fake_repo.user_default_executor_id = None
    fake_repo.docker_executor = None  # type: ignore[assignment]
    monkeypatch.setattr(settings, "executors_auto_docker_default", False)

    with pytest.raises(RuntimeError, match="No default executor configured"):
        await router._resolve_executor(
            user_id="user-1",
            session_id="session-1",
            target_machine=None,
        )
