from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from skitter.api.app import create_app
from skitter.api.deps import get_repo
from skitter.api.routes import commands as commands_routes
from skitter.core.config import ModelConfig, ProviderConfig, settings


@pytest.fixture
def admin_api_key(monkeypatch: pytest.MonkeyPatch) -> str:
    key = "test-admin-key"
    monkeypatch.setattr(settings, "api_key", key)
    return key


@pytest.fixture(autouse=True)
def configured_models(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        settings,
        "providers",
        [
            ProviderConfig(
                name="provider",
                api_type="openai",
                api_base="http://localhost:12345",
                api_key="test-key",
            )
        ],
    )
    monkeypatch.setattr(
        settings,
        "models",
        [
            ModelConfig(
                name="main",
                provider="provider",
                model_id="test-model",
                input_cost_per_1m=0.0,
                output_cost_per_1m=0.0,
            )
        ],
    )
    monkeypatch.setattr(settings, "main_model", "provider/main")
    monkeypatch.setattr(settings, "heartbeat_model", "provider/main")


def _client_with_repo(repo: Any) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_repo] = lambda: repo
    return TestClient(app)


@dataclass
class _RunTrace:
    id: str
    session_id: str
    user_id: str
    message_id: str
    origin: str
    status: str
    model: str
    started_at: datetime
    finished_at: datetime | None = None
    duration_ms: int | None = None
    tool_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cost: float = 0.0
    error: str | None = None
    limit_reason: str | None = None
    input_text: str = ""
    output_text: str = ""
    limit_detail: str | None = None


class _RunsRepo:
    def __init__(self) -> None:
        self.trace = _RunTrace(
            id="run-1",
            session_id="session-1",
            user_id="user-1",
            message_id="msg-1",
            origin="discord",
            status="completed",
            model="provider/main",
            started_at=datetime.now(UTC),
            finished_at=datetime.now(UTC),
            duration_ms=1234,
            tool_calls=1,
            input_tokens=10,
            output_tokens=20,
            total_tokens=30,
            cost=0.01,
            input_text="input",
            output_text="output",
            limit_detail=None,
        )
        self.tool_run = SimpleNamespace(
            id="tool-1",
            tool_name="shell",
            status="completed",
            executor_id="exec-1",
            input={"cmd": "echo hi"},
            output={"status": "ok"},
            approved_by="user-1",
            created_at=datetime.now(UTC),
        )
        self.event = SimpleNamespace(
            id="event-1",
            event_type="message_response",
            payload={"status": "completed"},
            created_at=datetime.now(UTC),
        )

    async def list_run_traces(self, **_: Any) -> list[_RunTrace]:
        return [self.trace]

    async def get_run_trace(self, run_id: str) -> _RunTrace | None:
        return self.trace if run_id == self.trace.id else None

    async def list_tool_runs_by_run(self, run_id: str) -> list[Any]:
        if run_id != self.trace.id:
            return []
        return [self.tool_run]

    async def list_run_trace_events(self, run_id: str, limit: int) -> list[Any]:
        _ = limit
        if run_id != self.trace.id:
            return []
        return [self.event]


@dataclass
class _ExecutorRow:
    id: str
    owner_user_id: str
    name: str
    kind: str
    platform: str | None
    hostname: str | None
    status: str
    capabilities: dict[str, Any]
    last_seen_at: datetime | None
    created_at: datetime
    disabled: bool = False


class _ExecutorsRepo:
    def __init__(self) -> None:
        self.row = _ExecutorRow(
            id="exec-1",
            owner_user_id="user-1",
            name="macbook",
            kind="node",
            platform="darwin",
            hostname="macbook.local",
            status="online",
            capabilities={"tools": ["read", "shell"]},
            last_seen_at=datetime.now(UTC),
            created_at=datetime.now(UTC),
            disabled=False,
        )
        self.user_default = "exec-1"
        self.restored: list[str] = []
        self.deleted: list[str] = []
        self.cleared_defaults: list[tuple[str, str | None]] = []

    async def get_executor(self, executor_id: str) -> _ExecutorRow | None:
        if executor_id != self.row.id:
            return None
        return self.row

    async def update_executor(self, executor_id: str, **fields: Any) -> _ExecutorRow | None:
        if executor_id != self.row.id:
            return None
        for key, value in fields.items():
            if value is not None:
                setattr(self.row, key, value)
        return self.row

    async def get_user_default_executor_id(self, user_id: str) -> str | None:
        _ = user_id
        return self.user_default

    async def set_user_default_executor(self, user_id: str, executor_id: str | None):
        self.cleared_defaults.append((user_id, executor_id))
        self.user_default = executor_id
        return None

    async def restore_executor_tokens(self, executor_id: str) -> None:
        self.restored.append(executor_id)

    async def delete_executor(self, executor_id: str) -> bool:
        if executor_id != self.row.id:
            return False
        self.deleted.append(executor_id)
        return True


@dataclass
class _UserRow:
    id: str
    approved: bool


@dataclass
class _SessionRow:
    id: str
    model: str


@dataclass
class _ModelRow:
    name: str
    model: str


class _CommandsRepo:
    def __init__(self, approved: bool = True) -> None:
        self.user = _UserRow(id="user-1", approved=approved)
        self.session = _SessionRow(id="session-1", model="provider/main")
        self.set_calls: list[tuple[str, str]] = []

    async def get_user_by_id(self, user_id: str) -> _UserRow | None:
        if user_id != self.user.id:
            return None
        return self.user

    async def get_active_session_by_scope(self, scope_type: str, scope_id: str) -> _SessionRow | None:
        _ = scope_type, scope_id
        return self.session

    async def set_session_model(self, session_id: str, model: str) -> _SessionRow | None:
        if session_id != self.session.id:
            return None
        self.session.model = model
        self.set_calls.append((session_id, model))
        return self.session

    async def create_session(
        self,
        user_id: str,
        status: str = "active",
        model: str | None = None,
        origin: str = "api",
        scope_type: str = "private",
        scope_id: str | None = None,
    ) -> _SessionRow:
        _ = user_id, status, origin, scope_type, scope_id
        self.session = _SessionRow(id="session-2", model=model or "provider/main")
        return self.session


def test_runs_routes_require_auth_and_return_detail(admin_api_key: str) -> None:
    repo = _RunsRepo()
    with _client_with_repo(repo) as client:
        unauthorized = client.get("/v1/runs")
        assert unauthorized.status_code == 401

        listed = client.get("/v1/runs", headers={"x-api-key": admin_api_key})
        assert listed.status_code == 200
        body = listed.json()
        assert len(body) == 1
        assert body[0]["id"] == "run-1"
        assert body[0]["tool_calls"] == 1

        detail = client.get("/v1/runs/run-1", headers={"x-api-key": admin_api_key})
        assert detail.status_code == 200
        payload = detail.json()
        assert payload["run"]["id"] == "run-1"
        assert payload["tool_runs"][0]["id"] == "tool-1"
        assert payload["events"][0]["id"] == "event-1"


def test_executor_disable_enable_delete_flow(admin_api_key: str, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _ExecutorsRepo()
    closed: list[str] = []
    cleared: list[str] = []

    async def _close_executor(executor_id: str) -> None:
        closed.append(executor_id)

    async def _clear_defaults(executor_id: str) -> int:
        cleared.append(executor_id)
        return 1

    async def _no_docker_users() -> set[str]:
        return set()

    monkeypatch.setattr("skitter.tools.executors.node_executor_hub.close_executor", _close_executor)
    monkeypatch.setattr("skitter.tools.executors.executor_router.clear_session_defaults_for_executor", _clear_defaults)
    monkeypatch.setattr("skitter.api.routes.executors._running_docker_users", _no_docker_users)

    with _client_with_repo(repo) as client:
        disabled = client.post("/v1/executors/exec-1/disable", headers={"x-api-key": admin_api_key})
        assert disabled.status_code == 200
        assert disabled.json()["disabled"] is True
        assert repo.user_default is None
        assert closed == ["exec-1"]
        assert cleared == ["exec-1"]

        enabled = client.post("/v1/executors/exec-1/enable", headers={"x-api-key": admin_api_key})
        assert enabled.status_code == 200
        assert enabled.json()["disabled"] is False
        assert repo.restored == ["exec-1"]

        deleted = client.delete("/v1/executors/exec-1", headers={"x-api-key": admin_api_key})
        assert deleted.status_code == 200
        assert deleted.json() == {"id": "exec-1", "deleted": True}
        assert repo.deleted == ["exec-1"]


def test_commands_model_and_tools(admin_api_key: str, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _CommandsRepo(approved=True)

    monkeypatch.setattr(
        commands_routes,
        "list_models",
        lambda: [
            _ModelRow(name="provider/main", model="model-a"),
            _ModelRow(name="provider/fast", model="model-b"),
        ],
    )
    monkeypatch.setattr(commands_routes, "resolve_model_name", lambda value, purpose="main": value or "provider/main")

    with _client_with_repo(repo) as client:
        list_models_resp = client.post(
            "/v1/commands/execute",
            headers={"x-api-key": admin_api_key},
            json={"command": "model", "user_id": "user-1"},
        )
        assert list_models_resp.status_code == 200
        assert "Available models:" in list_models_resp.json()["message"]
        assert "provider/main" in list_models_resp.json()["message"]

        switch_resp = client.post(
            "/v1/commands/execute",
            headers={"x-api-key": admin_api_key},
            json={"command": "model", "user_id": "user-1", "args": {"model_name": "provider/fast"}},
        )
        assert switch_resp.status_code == 200
        assert repo.set_calls[-1] == ("session-1", "provider/fast")

        tools_resp = client.post(
            "/v1/commands/execute",
            headers={"x-api-key": admin_api_key},
            json={"command": "tools", "user_id": "user-1"},
        )
        assert tools_resp.status_code == 200
        assert "Tool approvals are" in tools_resp.json()["message"]


def test_commands_reject_unapproved_user(admin_api_key: str) -> None:
    repo = _CommandsRepo(approved=False)
    with _client_with_repo(repo) as client:
        response = client.post(
            "/v1/commands/execute",
            headers={"x-api-key": admin_api_key},
            json={"command": "tools", "user_id": "user-1"},
        )
    assert response.status_code == 403
    assert "not yet approved" in response.json()["detail"].lower()
