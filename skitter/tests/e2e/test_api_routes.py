from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
import base64

import pytest
from fastapi.testclient import TestClient

from skitter.api.app import create_app
from skitter.api.deps import get_repo
from skitter.core.models import AdminEvent, AgentResponse, PendingUserPrompt
from skitter.core.config import ModelConfig, ProviderConfig, settings
import skitter.core.command_service as command_service_module


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


@pytest.fixture(autouse=True)
def configured_workspace_root(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setattr(settings, "workspace_root", str(tmp_path / "workspace"))


def _client_with_repo(repo: Any) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_repo] = lambda: repo
    return TestClient(app)


def _app_with_repo(repo: Any):
    app = create_app()
    app.dependency_overrides[get_repo] = lambda: repo
    return app


def test_admin_events_recent_returns_buffered_events(admin_api_key: str) -> None:
    app = create_app()
    asyncio.run(
        app.state.event_bus.publish_admin(
            AdminEvent(
                kind="job.started",
                title="Background job started",
                message="Job demo started.",
                level="info",
                job_id="job-1",
            )
        )
    )
    client = TestClient(app)
    response = client.get("/v1/admin/events/recent?limit=10", headers={"X-API-Key": admin_api_key})
    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["kind"] == "job.started"
    assert payload[0]["job_id"] == "job-1"


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


@dataclass
class _AgentProfileRow:
    id: str = "profile-default"
    user_id: str = "user-1"
    slug: str = "default"
    name: str = "Default"
    status: str = "active"
    meta: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))


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
        self.profile = _AgentProfileRow()
        self.profile_defaults: dict[str, str | None] = {self.profile.id: "exec-1"}

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

    async def list_agent_profiles(self, user_id: str, *, include_archived: bool = False) -> list[_AgentProfileRow]:
        _ = include_archived
        return [self.profile] if user_id == self.profile.user_id else []

    async def get_profile_default_executor_id(self, profile_id: str) -> str | None:
        return self.profile_defaults.get(profile_id)

    async def set_profile_default_executor(self, profile_id: str, executor_id: str | None):
        self.profile_defaults[profile_id] = executor_id
        return self.profile if profile_id == self.profile.id else None

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
    transport_user_id: str = "discord-user-1"
    display_name: str | None = "Test User"
    meta: dict[str, Any] = field(default_factory=dict)
    default_profile_id: str = "profile-default"


@dataclass
class _SessionRow:
    id: str
    model: str
    user_id: str = "user-1"
    agent_profile_id: str = "profile-default"
    status: str = "active"
    scope_type: str = "private"
    scope_id: str = "private:profile-default"
    created_at: datetime = datetime.now(UTC)
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    total_cost: float = 0.0
    last_input_tokens: int = 0
    last_output_tokens: int = 0
    last_total_tokens: int = 0
    last_cost: float = 0.0
    last_model: str | None = None
    last_usage_at: datetime | None = None
    summary_status: str | None = None
    summary_attempts: int | None = None
    summary_next_retry_at: datetime | None = None
    summary_last_error: str | None = None
    summary_path: str | None = None
    summary_completed_at: datetime | None = None


@dataclass
class _ModelRow:
    name: str
    model: str


class _CommandsRepo:
    def __init__(self, approved: bool = True) -> None:
        self.user = _UserRow(id="user-1", approved=approved)
        self.session = _SessionRow(id="session-1", model="provider/main")
        self.profile = _AgentProfileRow()
        self.profile_by_slug: dict[str, _AgentProfileRow] = {self.profile.slug: self.profile}
        self.set_calls: list[tuple[str, str]] = []

    async def get_user_by_id(self, user_id: str) -> _UserRow | None:
        if user_id != self.user.id:
            return None
        return self.user

    async def list_users(self, limit: int = 200):
        _ = limit
        return [self.user]

    async def delete_stale_pending_users(self, ttl_minutes: int):
        _ = ttl_minutes
        return 0

    async def get_default_agent_profile(self, user_id: str) -> _AgentProfileRow | None:
        if user_id != self.user.id:
            return None
        return await self.get_agent_profile(self.user.default_profile_id)

    async def list_agent_profiles(self, user_id: str, *, include_archived: bool = False) -> list[_AgentProfileRow]:
        if user_id != self.user.id:
            return []
        rows = list(self.profile_by_slug.values())
        if not include_archived:
            rows = [row for row in rows if row.status != "archived"]
        return rows

    async def get_agent_profile(self, profile_id: str) -> _AgentProfileRow | None:
        if self.profile is not None and profile_id == self.profile.id:
            return self.profile
        return next((row for row in self.profile_by_slug.values() if row.id == profile_id), None)

    async def get_agent_profile_by_slug(self, user_id: str, slug: str) -> _AgentProfileRow | None:
        if user_id != self.user.id:
            return None
        return self.profile_by_slug.get(slug)

    async def create_agent_profile(
        self,
        *,
        user_id: str,
        name: str,
        slug: str,
        make_default: bool = False,
        meta: dict | None = None,
    ) -> _AgentProfileRow:
        row = _AgentProfileRow(
            id=f"profile-{slug}",
            user_id=user_id,
            slug=slug,
            name=name,
            meta=meta or {},
        )
        self.profile_by_slug[row.slug] = row
        if make_default:
            self.user.default_profile_id = row.id
        return row

    async def update_agent_profile(self, profile_id: str, **fields: Any) -> _AgentProfileRow | None:
        row = await self.get_agent_profile(profile_id)
        if row is None:
            return None
        for key, value in fields.items():
            if key == "meta_updates" and value:
                merged = dict(row.meta)
                merged.update(value)
                row.meta = merged
            elif value is not None and hasattr(row, key):
                setattr(row, key, value)
        return row

    async def get_profile_default_model_name(self, profile_id: str) -> str | None:
        row = await self.get_agent_profile(profile_id)
        if row is None:
            return None
        raw = str(row.meta.get("default_model") or "").strip()
        return raw or None

    async def set_profile_default_model_name(self, profile_id: str, model_name: str | None):
        row = await self.get_agent_profile(profile_id)
        if row is None:
            return None
        row.meta["default_model"] = model_name or ""
        return row

    async def set_default_agent_profile(self, user_id: str, profile_id: str):
        if user_id == self.user.id:
            self.user.default_profile_id = profile_id
            return self.user
        return None

    async def delete_agent_profile(self, profile_id: str) -> bool:
        row = await self.get_agent_profile(profile_id)
        if row is None:
            return False
        self.profile_by_slug.pop(row.slug, None)
        if self.profile.id == profile_id:
            self.profile = None
        return True

    async def get_active_session_by_scope(
        self,
        scope_type: str,
        scope_id: str,
        agent_profile_id: str | None = None,
    ) -> _SessionRow | None:
        _ = scope_type, scope_id
        if agent_profile_id and self.session.agent_profile_id != agent_profile_id:
            return None
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
        agent_profile_id: str | None = None,
        status: str = "active",
        model: str | None = None,
        origin: str = "api",
        scope_type: str = "private",
        scope_id: str | None = None,
    ) -> _SessionRow:
        _ = user_id, status, origin, scope_type
        self.session = _SessionRow(
            id="session-2",
            model=model or "provider/main",
            agent_profile_id=agent_profile_id or self.profile.id,
            scope_id=scope_id or f"private:{agent_profile_id or self.profile.id}",
        )
        return self.session


class _SessionDetailRepo:
    def __init__(self) -> None:
        self.session = _SessionRow(
            id="session-1",
            model="provider/main",
            last_model="provider/main",
            summary_status="pending",
            summary_attempts=2,
            summary_next_retry_at=datetime.now(UTC),
            summary_last_error="embedding timeout",
            summary_path="memory/session-summaries/2026-03-25.md",
            summary_completed_at=None,
        )
        self.user = SimpleNamespace(id="user-1", display_name="Gabriel", transport_user_id="discord-user")
        self.profile = _AgentProfileRow()

    async def get_session(self, session_id: str):
        return self.session if session_id == self.session.id else None

    async def get_user_by_id(self, user_id: str):
        return self.user if user_id == self.user.id else None

    async def get_agent_profile(self, profile_id: str):
        return self.profile if profile_id == self.profile.id else None

    async def get_default_agent_profile(self, user_id: str):
        return self.profile if user_id == self.user.id else None

    async def list_messages(self, session_id: str):
        if session_id != self.session.id:
            return []
        return [
            SimpleNamespace(
                id="msg-1",
                role="user",
                content="hello",
                created_at=datetime.now(UTC),
                meta={},
            )
        ]

    async def list_tool_runs_by_session(self, session_id: str):
        _ = session_id
        return []

    async def list_pending_user_prompts(self, *, session_id: str | None = None, user_id: str | None = None, limit: int = 20):
        _ = session_id, user_id, limit
        return []


@dataclass
class _PromptRow:
    id: str
    session_id: str
    question: str
    choices: list[str]
    allow_free_text: bool
    status: str
    created_at: datetime


@dataclass
class _UserSessionRow:
    id: str
    user_id: str
    agent_profile_id: str
    origin: str
    scope_type: str
    scope_id: str


@dataclass
class _ApprovedUser:
    id: str
    approved: bool
    meta: dict[str, Any]
    default_profile_id: str = "profile-default"


class _PromptRepo:
    def __init__(self) -> None:
        self.session = _UserSessionRow(
            id="session-1",
            user_id="user-1",
            agent_profile_id="profile-default",
            origin="tui",
            scope_type="private",
            scope_id="private:profile-default",
        )
        self.user = _ApprovedUser(id="user-1", approved=True, meta={})
        self.profile = _AgentProfileRow(meta={})
        self.prompts = [
            _PromptRow(
                id="prompt-1",
                session_id="session-1",
                question="Which machine should I use?",
                choices=["docker", "macbook"],
                allow_free_text=True,
                status="pending",
                created_at=datetime.now(UTC),
            )
        ]
        self.messages: list[tuple[str, str, str, dict[str, Any] | None]] = []

    async def get_session(self, session_id: str) -> _UserSessionRow | None:
        return self.session if session_id == self.session.id else None

    async def get_user_by_id(self, user_id: str) -> _ApprovedUser | None:
        return self.user if user_id == self.user.id else None

    async def get_agent_profile(self, profile_id: str) -> _AgentProfileRow | None:
        return self.profile if profile_id == self.profile.id else None

    async def get_default_agent_profile(self, user_id: str) -> _AgentProfileRow | None:
        return self.profile if user_id == self.user.id else None

    async def set_user_meta(self, user_id: str, updates: dict[str, Any]):
        _ = user_id
        self.user.meta.update(updates)
        return self.user

    async def update_agent_profile(self, profile_id: str, **fields: Any):
        if profile_id != self.profile.id:
            return None
        meta_updates = fields.get("meta_updates") or {}
        if meta_updates:
            merged = dict(self.profile.meta)
            merged.update(meta_updates)
            self.profile.meta = merged
        return self.profile

    async def list_pending_user_prompts(self, *, session_id: str | None = None, user_id: str | None = None, limit: int = 50):
        _ = user_id, limit
        if session_id and session_id != self.session.id:
            return []
        return [prompt for prompt in self.prompts if prompt.status == "pending"]

    async def answer_pending_user_prompt_for_session(
        self,
        session_id: str,
        *,
        answer: str,
        answered_by: str | None = None,
    ):
        _ = answered_by
        if session_id != self.session.id:
            return None
        for prompt in self.prompts:
            if prompt.status == "pending":
                prompt.status = "answered"
                return prompt
        return None

    async def add_message(self, session_id: str, role: str, content: str, metadata: dict | None = None):
        self.messages.append((session_id, role, content, metadata))
        return SimpleNamespace(
            id=f"msg-{len(self.messages)}",
            session_id=session_id,
            role=role,
            content=content,
            created_at=datetime.now(UTC),
            meta=metadata or {},
        )


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
        command_service_module,
        "list_models",
        lambda: [
            _ModelRow(name="provider/main", model="model-a"),
            _ModelRow(name="provider/fast", model="model-b"),
        ],
    )
    monkeypatch.setattr(command_service_module, "resolve_model_name", lambda value, purpose="main": value or "provider/main")

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


def test_profiles_route_and_profile_commands(admin_api_key: str, monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    repo = _CommandsRepo(approved=True)

    def _tmp_profile_workspace(user_id: str, profile_slug: str | None = None):
        path = tmp_path / user_id / (profile_slug or "default")
        path.mkdir(parents=True, exist_ok=True)
        return path

    monkeypatch.setattr("skitter.core.profile_service.ensure_profile_workspace", _tmp_profile_workspace)

    with _client_with_repo(repo) as client:
        listed = client.get(
            "/v1/profiles",
            headers={"x-api-key": admin_api_key},
            params={"user_id": "user-1"},
        )
        assert listed.status_code == 200
        profiles = listed.json()
        assert profiles == [
            {
                "id": "profile-default",
                "slug": "default",
                "name": "Default",
                "status": "active",
                "default_model": None,
                "is_default": True,
                "created_at": profiles[0]["created_at"],
                "updated_at": profiles[0]["updated_at"],
            }
        ]

        created = client.post(
            "/v1/commands/execute",
            headers={"x-api-key": admin_api_key},
            json={"command": "profile", "user_id": "user-1", "args": {"raw": "create Research Bot"}},
        )
        assert created.status_code == 200
        payload = created.json()
        assert payload["message"] == "Created profile `research-bot`."
        assert payload["data"]["apply_client_selection"] is True
        assert payload["data"]["agent_profile_slug"] == "research-bot"

        switched = client.post(
            "/v1/commands/execute",
            headers={"x-api-key": admin_api_key},
            json={"command": "profile", "user_id": "user-1", "args": {"raw": "default research-bot"}},
        )
        assert switched.status_code == 200
        assert switched.json()["message"] == "Default profile set to `research-bot`."

        relisted = client.get(
            "/v1/profiles",
            headers={"x-api-key": admin_api_key},
            params={"user_id": "user-1"},
        )
        assert relisted.status_code == 200
        profiles = relisted.json()
        assert [item["slug"] for item in profiles] == ["default", "research-bot"]
        created_profile = next(item for item in profiles if item["slug"] == "research-bot")
        assert created_profile["is_default"] is True


def test_profiles_routes_support_create_and_update(admin_api_key: str, monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    repo = _CommandsRepo(approved=True)
    monkeypatch.setattr(
        "skitter.api.routes.profiles.list_models",
        lambda: [
            _ModelRow(name="provider/main", model="model-a"),
            _ModelRow(name="provider/fast", model="model-b"),
        ],
    )
    monkeypatch.setattr("skitter.api.routes.profiles.resolve_model_name", lambda value, purpose="main": value or "provider/main")

    def _tmp_profile_workspace(user_id: str, profile_slug: str | None = None):
        path = tmp_path / user_id / (profile_slug or "default")
        path.mkdir(parents=True, exist_ok=True)
        return path

    monkeypatch.setattr("skitter.core.profile_service.ensure_profile_workspace", _tmp_profile_workspace)

    with _client_with_repo(repo) as client:
        created = client.post(
            "/v1/profiles",
            headers={"x-api-key": admin_api_key},
            json={"user_id": "user-1", "name": "Ops Bot"},
        )
        assert created.status_code == 200
        created_payload = created.json()
        assert created_payload["slug"] == "ops-bot"
        assert created_payload["is_default"] is False

        updated = client.patch(
            f"/v1/profiles/{created_payload['id']}",
            headers={"x-api-key": admin_api_key},
            json={"name": "Operations Bot", "make_default": True},
        )
        assert updated.status_code == 200
        updated_payload = updated.json()
        assert updated_payload["name"] == "Operations Bot"
        assert updated_payload["default_model"] is None
        assert updated_payload["is_default"] is True

        set_model = client.patch(
            f"/v1/profiles/{created_payload['id']}",
            headers={"x-api-key": admin_api_key},
            json={"default_model": "provider/fast"},
        )
        assert set_model.status_code == 200
        assert set_model.json()["default_model"] == "provider/fast"

        restored_default = client.patch(
            f"/v1/profiles/{repo.profile.id}",
            headers={"x-api-key": admin_api_key},
            json={"make_default": True},
        )
        assert restored_default.status_code == 200
        assert restored_default.json()["is_default"] is True

        archived = client.patch(
            f"/v1/profiles/{created_payload['id']}",
            headers={"x-api-key": admin_api_key},
            json={"archived": True},
        )
        assert archived.status_code == 200
        assert archived.json()["status"] == "archived"

        restored = client.patch(
            f"/v1/profiles/{created_payload['id']}",
            headers={"x-api-key": admin_api_key},
            json={"archived": False},
        )
        assert restored.status_code == 200
        assert restored.json()["status"] == "active"

        rearchived = client.patch(
            f"/v1/profiles/{created_payload['id']}",
            headers={"x-api-key": admin_api_key},
            json={"archived": True},
        )
        assert rearchived.status_code == 200
        assert rearchived.json()["status"] == "archived"

        deleted = client.delete(
            f"/v1/profiles/{created_payload['id']}",
            headers={"x-api-key": admin_api_key},
        )
        assert deleted.status_code == 200
        assert deleted.json() == {"id": created_payload["id"], "deleted": True}

        relisted = client.get(
            "/v1/profiles",
            headers={"x-api-key": admin_api_key},
            params={"user_id": "user-1", "include_archived": "true"},
        )
        assert relisted.status_code == 200
        assert [item["slug"] for item in relisted.json()] == ["default"]


def test_profile_command_supports_profile_default_model(admin_api_key: str, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _CommandsRepo(approved=True)

    monkeypatch.setattr(
        command_service_module,
        "list_models",
        lambda: [
            _ModelRow(name="provider/main", model="model-a"),
            _ModelRow(name="provider/fast", model="model-b"),
        ],
    )
    monkeypatch.setattr(command_service_module, "resolve_model_name", lambda value, purpose="main": value or "provider/main")

    with _client_with_repo(repo) as client:
        show_resp = client.post(
            "/v1/commands/execute",
            headers={"x-api-key": admin_api_key},
            json={"command": "profile", "user_id": "user-1", "args": {"raw": "model"}},
        )
        assert show_resp.status_code == 200
        assert "global default" in show_resp.json()["message"]

        set_resp = client.post(
            "/v1/commands/execute",
            headers={"x-api-key": admin_api_key},
            json={"command": "profile", "user_id": "user-1", "args": {"raw": "model provider/fast"}},
        )
        assert set_resp.status_code == 200
        assert set_resp.json()["data"]["default_model"] == "provider/fast"

        reset_resp = client.post(
            "/v1/commands/execute",
            headers={"x-api-key": admin_api_key},
            json={"command": "profile", "user_id": "user-1", "args": {"raw": "model default"}},
        )
        assert reset_resp.status_code == 200
        assert reset_resp.json()["data"]["default_model"] is None


def test_users_route_includes_default_profile(admin_api_key: str) -> None:
    repo = _CommandsRepo(approved=True)

    with _client_with_repo(repo) as client:
        response = client.get("/v1/users", headers={"x-api-key": admin_api_key})

    assert response.status_code == 200
    payload = response.json()
    assert payload[0]["id"] == "user-1"
    assert payload[0]["default_profile_id"] == "profile-default"
    assert payload[0]["default_profile_slug"] == "default"


def test_new_command_returns_immediate_message(admin_api_key: str, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _CommandsRepo(approved=True)

    class _SessionManagerStub:
        def __init__(self, runtime, memory_service=None):
            _ = runtime, memory_service

        async def start_new_session_for_scope(self, **kwargs):
            _ = kwargs
            return None, "session-2"

    monkeypatch.setattr(command_service_module, "SessionManager", _SessionManagerStub)

    with _client_with_repo(repo) as client:
        response = client.post(
            "/v1/commands/execute",
            headers={"x-api-key": admin_api_key},
            json={"command": "new", "user_id": "user-1"},
        )
    assert response.status_code == 200
    payload = response.json()
    assert payload["message"] == "Started a new session."
    assert payload["data"]["session_id"] == "session-2"


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


def test_user_prompts_route_lists_pending_prompts(admin_api_key: str) -> None:
    repo = _PromptRepo()
    with _client_with_repo(repo) as client:
        response = client.get(
            "/v1/user-prompts",
            headers={"x-api-key": admin_api_key},
            params={"session_id": "session-1"},
        )
    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["id"] == "prompt-1"
    assert payload[0]["question"] == "Which machine should I use?"


def test_session_detail_includes_background_summary_state(admin_api_key: str) -> None:
    repo = _SessionDetailRepo()
    with _client_with_repo(repo) as client:
        response = client.get("/v1/sessions/session-1/detail", headers={"x-api-key": admin_api_key})
    assert response.status_code == 200
    payload = response.json()
    assert payload["summary_status"] == "pending"
    assert payload["summary_attempts"] == 2
    assert payload["summary_last_error"] == "embedding timeout"
    assert payload["summary_path"] == "memory/session-summaries/2026-03-25.md"


def test_send_message_persists_assistant_prompt_when_runtime_requests_user_input(admin_api_key: str) -> None:
    repo = _PromptRepo()
    app = _app_with_repo(repo)

    class _RuntimeStub:
        async def handle_message(self, session_id: str, envelope):
            assert session_id == "session-1"
            assert envelope.text == "Use the macbook."
            return AgentResponse(
                text="Anything else?\n\nThe user may also reply with a custom free-text answer.",
                run_id="run-1",
                pending_prompt=PendingUserPrompt(
                    prompt_id="prompt-2",
                    question="Anything else?",
                    choices=[],
                    allow_free_text=True,
                ),
            )

    app.state.runtime = _RuntimeStub()

    with TestClient(app) as client:
        response = client.post(
            "/v1/messages",
            headers={"x-api-key": admin_api_key},
            json={
                "session_id": "session-1",
                "user_id": "user-1",
                "text": "Use the macbook.",
                "metadata": {},
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == "msg-2"
    assert payload["content"] == "Anything else?\n\nThe user may also reply with a custom free-text answer."
    assert repo.prompts[0].status == "answered"
    assert len(repo.messages) == 2
    session_id, role, content, metadata = repo.messages[0]
    assert session_id == "session-1"
    assert role == "user"
    assert content == "Use the macbook."
    assert metadata is not None
    assert metadata["answered_prompt_id"] == "prompt-1"
    session_id, role, content, metadata = repo.messages[1]
    assert session_id == "session-1"
    assert role == "assistant"
    assert content == "Anything else?\n\nThe user may also reply with a custom free-text answer."
    assert metadata is not None
    assert metadata["user_prompt"] is True
    assert metadata["user_prompt_id"] == "prompt-2"
    assert metadata["user_prompt_question"] == "Anything else?"
    assert metadata["user_prompt_choices"] == []


def test_send_message_accepts_uploaded_attachments(admin_api_key: str, monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    repo = _PromptRepo()
    app = _app_with_repo(repo)
    monkeypatch.setattr(
        "skitter.api.routes.messages.user_workspace_root",
        lambda user_id, profile_slug=None: tmp_path / user_id / (profile_slug or "default"),
    )

    payload_bytes = b"fake-image"
    encoded = base64.b64encode(payload_bytes).decode("ascii")

    class _RuntimeStub:
        async def handle_message(self, session_id: str, envelope):
            assert session_id == "session-1"
            assert len(envelope.attachments) == 1
            attachment = envelope.attachments[0]
            assert attachment.filename == "preview.png"
            assert attachment.content_type == "image/png"
            assert attachment.url is not None and attachment.url.startswith("data:image/png;base64,")
            assert attachment.path is not None
            return AgentResponse(text="Uploaded", attachments=[])

    app.state.runtime = _RuntimeStub()

    with TestClient(app) as client:
        response = client.post(
            "/v1/messages",
            headers={"x-api-key": admin_api_key},
            json={
                "session_id": "session-1",
                "user_id": "user-1",
                "text": "",
                "metadata": {},
                "attachments": [
                    {
                        "filename": "preview.png",
                        "content_type": "image/png",
                        "data_base64": encoded,
                    }
                ],
            },
        )

    assert response.status_code == 200
    assert len(repo.messages) == 2
    session_id, role, content, metadata = repo.messages[0]
    assert session_id == "session-1"
    assert role == "user"
    assert content == ""
    stored = metadata["attachments"][0]
    assert stored["filename"] == "preview.png"
    assert stored["content_type"] == "image/png"
    assert "/default/.uploads/" in str(stored["path"])
    assert str(stored["path"]).endswith("preview.png")
