from __future__ import annotations

import logging
import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest

from skitter.core.memory_hub import MemoryHub
from skitter.core.memory_provider import (
    BaseMemoryProvider,
    ContextContribution,
    ConversationTurn,
    MemoryContext,
    MemoryContextRequest,
    MemoryContextResult,
    MemoryForgetRequest,
    MemoryForgetResult,
    MemoryForgetSelector,
    MemoryHit,
    MemoryItem,
    MemoryRecallRequest,
    MemoryRecallResult,
    MemoryStoreRequest,
    MemoryStoreResult,
)
from skitter.core.plugins import HookBus, PluginRegistry


@pytest.mark.asyncio
async def test_hook_bus_orders_handlers_and_collects_results() -> None:
    calls: list[str] = []
    bus = HookBus(default_timeout_seconds=1.0)

    async def later(event):
        calls.append(f"later:{event['value']}")
        return "later-result"

    def earlier(event):
        calls.append(f"earlier:{event['value']}")
        return "earlier-result"

    bus.register("demo.hook", later, plugin_id="plugin-b", priority=20)
    bus.register("demo.hook", earlier, plugin_id="plugin-a", priority=10)

    results = await bus.emit("demo.hook", {"value": "ok"})

    assert calls == ["earlier:ok", "later:ok"]
    assert [result.value for result in results] == ["earlier-result", "later-result"]
    assert all(result.ok for result in results)


@pytest.mark.asyncio
async def test_hook_bus_normalizes_underscore_hook_aliases() -> None:
    bus = HookBus(default_timeout_seconds=1.0)
    request = type("Request", (), {"query": "base"})()
    bus.register(
        "before_memory_recall",
        lambda event: {"query": event["request"].query + " patched"},
        plugin_id="alias",
    )

    results = await bus.emit("memory.recall.before", {"request": request})

    assert results[0].value == {"query": "base patched"}


@pytest.mark.asyncio
async def test_plugin_registry_loads_manifest_and_registers_capabilities(tmp_path: Path) -> None:
    plugin_root = tmp_path / "plugins"
    plugin_root.mkdir()
    plugin_dir = plugin_root / "demo_plugin"
    plugin_dir.mkdir()
    (plugin_dir / "plugin.yaml").write_text(
        """
id: demo
enabled: true
version: 0.1.0
description: Demo memory plugin
entrypoint: demo_plugin_module:register
capabilities:
  hooks:
    - demo.hook
  memory_provider: demo-memory
config:
  flag: enabled
""".strip(),
        encoding="utf-8",
    )
    (plugin_dir / "demo_plugin_module.py").write_text(
        """
from skitter.core.memory_provider import BaseMemoryProvider


class DemoMemoryProvider(BaseMemoryProvider):
    id = "demo-memory"
    name = "Demo Memory"
    capabilities = {"recall"}


def register(ctx):
    ctx.register_hook("demo.hook", lambda event: {"config": ctx.config["flag"], "event": event})
    ctx.register_memory_provider(DemoMemoryProvider())
""".strip(),
        encoding="utf-8",
    )

    bus = HookBus()
    registry = PluginRegistry(
        hook_bus=bus,
        plugin_root=plugin_root,
    )

    await registry.load()
    hook_results = await bus.emit("demo.hook", {"hello": "world"})
    snapshot = registry.snapshot()

    assert "demo" in registry.plugins
    assert hook_results[0].value == {"config": "enabled", "event": {"hello": "world"}}
    assert snapshot["memory_providers"] == [{"plugin_id": "demo", "provider_id": "demo-memory"}]
    assert snapshot["diagnostics"] == []


def _example_hook_event(fields: tuple[str, ...]) -> dict[str, object]:
    event: dict[str, object] = {}
    for field in fields:
        if field in {"messages", "result_messages"}:
            event[field] = []
        elif field == "result":
            event[field] = {"messages": []}
        elif field in {"input", "output"}:
            event[field] = {"ok": True}
        elif field in {"has_attachments", "is_command"}:
            event[field] = False
        elif field in {
            "plugin_count",
            "attempt",
            "total_attempts",
            "duration_ms",
            "input_tokens",
            "output_tokens",
            "total_tokens",
        }:
            event[field] = 1
        elif field == "cost":
            event[field] = 0.0
        else:
            event[field] = f"value-{field}"
    return event


@pytest.mark.asyncio
async def test_example_plugin_registers_non_memory_reference_hooks(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    source = Path(__file__).resolve().parents[3] / "plugins" / "example_plugin"
    assert "enabled: false" in (source / "plugin.yaml").read_text(encoding="utf-8")

    plugin_root = tmp_path / "plugins"
    plugin_root.mkdir()
    target = plugin_root / "example_plugin"
    shutil.copytree(source, target)
    manifest_path = target / "plugin.yaml"
    manifest_path.write_text(
        manifest_path.read_text(encoding="utf-8").replace("enabled: false", "enabled: true"),
        encoding="utf-8",
    )

    bus = HookBus(default_timeout_seconds=1.0)
    registry = PluginRegistry(hook_bus=bus, plugin_root=plugin_root)

    with caplog.at_level(logging.DEBUG, logger="skitter.plugins.example_plugin"):
        await registry.load()
        plugin = registry.plugins["example_plugin"]
        assert plugin.module is not None
        expected_hooks = set(plugin.module.HOOK_FIELDS)
        snapshot = registry.snapshot()

        assert set(snapshot["hooks"]) == expected_hooks
        assert all(not hook_name.startswith("memory.") for hook_name in expected_hooks)
        assert snapshot["memory_providers"] == []

        for hook_name, fields in plugin.module.HOOK_FIELDS.items():
            results = await bus.emit(hook_name, _example_hook_event(fields))
            assert len(results) == 1
            assert results[0].ok is True
            assert results[0].value is None

    messages = [record.getMessage() for record in caplog.records if record.name == "skitter.plugins.example_plugin"]
    for hook_name in expected_hooks:
        assert any(f"hook={hook_name}" in message for message in messages)


@pytest.mark.asyncio
async def test_plugin_registry_skips_disabled_manifest(tmp_path: Path) -> None:
    plugin_root = tmp_path / "plugins"
    plugin_root.mkdir()
    plugin_dir = plugin_root / "disabled_plugin"
    plugin_dir.mkdir()
    (plugin_dir / "plugin.yaml").write_text(
        """
id: disabled
enabled: false
entrypoint: disabled_plugin_module:register
capabilities:
  hooks:
    - demo.hook
""".strip(),
        encoding="utf-8",
    )
    (plugin_dir / "disabled_plugin_module.py").write_text(
        """
def register(ctx):
    raise AssertionError("disabled plugins should not be imported")
""".strip(),
        encoding="utf-8",
    )

    bus = HookBus()
    registry = PluginRegistry(hook_bus=bus, plugin_root=plugin_root)

    await registry.load()

    assert "disabled" in registry.plugins
    assert registry.memory_providers == []
    assert bus.snapshot() == {}


@pytest.mark.asyncio
async def test_plugin_registry_validates_manifest_config_schema(tmp_path: Path) -> None:
    plugin_root = tmp_path / "plugins"
    plugin_root.mkdir()
    plugin_dir = plugin_root / "invalid_plugin"
    plugin_dir.mkdir()
    (plugin_dir / "plugin.yaml").write_text(
        """
id: invalid
enabled: true
entrypoint: invalid_plugin_module:register
config_schema:
  type: object
  required:
    - base_url
  properties:
    base_url:
      type: string
""".strip(),
        encoding="utf-8",
    )
    (plugin_dir / "invalid_plugin_module.py").write_text(
        """
def register(ctx):
    raise AssertionError("invalid config should fail before import")
""".strip(),
        encoding="utf-8",
    )

    registry = PluginRegistry(hook_bus=HookBus(), plugin_root=plugin_root)

    await registry.load()

    assert registry.memory_providers == []
    assert registry.diagnostics[0].plugin_id == "invalid"
    assert "missing required field: base_url" in registry.diagnostics[0].detail


@pytest.mark.asyncio
async def test_plugin_registry_reports_malformed_manifest(tmp_path: Path) -> None:
    plugin_root = tmp_path / "plugins"
    plugin_root.mkdir()
    plugin_dir = plugin_root / "broken_plugin"
    plugin_dir.mkdir()
    (plugin_dir / "plugin.yaml").write_text("id: [broken", encoding="utf-8")

    registry = PluginRegistry(hook_bus=HookBus(), plugin_root=plugin_root)

    await registry.load()

    assert registry.memory_providers == []
    assert registry.diagnostics[0].plugin_id == "broken_plugin"
    assert registry.diagnostics[0].message == "Plugin registration failed"


class _FakeBuiltInProvider(BaseMemoryProvider):
    id = "builtin"
    name = "Built-in"
    capabilities = {"recall"}

    async def recall(self, ctx: MemoryContext, request: MemoryRecallRequest) -> MemoryRecallResult:
        return MemoryRecallResult(
            hits=[
                MemoryHit(
                    id="builtin-1",
                    provider_id=self.id,
                    content=f"builtin:{ctx.agent_profile_id}:{request.query}",
                    score=0.2,
                    source="builtin.md",
                )
            ]
        )


class _FakeExternalProvider(BaseMemoryProvider):
    id = "external"
    name = "External"
    capabilities = {"recall"}

    async def recall(self, ctx: MemoryContext, request: MemoryRecallRequest) -> MemoryRecallResult:
        return MemoryRecallResult(
            hits=[
                MemoryHit(
                    id="external-1",
                    provider_id=self.id,
                    content=f"external:{ctx.agent_profile_slug}:{request.query}",
                    score=0.9,
                    source="external",
                )
            ]
        )


class _ContextProvider(BaseMemoryProvider):
    id = "contextual"
    name = "Contextual"
    capabilities = {"build_context"}

    def __init__(self) -> None:
        self.requests: list[MemoryContextRequest] = []

    async def build_context(self, ctx: MemoryContext, request: MemoryContextRequest) -> MemoryContextResult:
        _ = ctx
        self.requests.append(request)
        return MemoryContextResult(
            contributions=[
                ContextContribution(
                    provider_id=self.id,
                    title="Original",
                    content=f"context:{request.query}:{request.filters.get('kind')}",
                    priority=20,
                )
            ]
        )


class _ObservingProvider(BaseMemoryProvider):
    id = "observer"
    name = "Observer"
    capabilities = {"observe_turn"}

    def __init__(self) -> None:
        self.turns: list[ConversationTurn] = []

    async def observe_turn(self, ctx: MemoryContext, turn: ConversationTurn) -> None:
        self.turns.append(turn)


class _ForgettingProvider(BaseMemoryProvider):
    id = "forgetter"
    name = "Forgetter"
    capabilities = {"forget"}

    def __init__(self, deleted: int = 1) -> None:
        self.deleted = deleted
        self.requests: list[MemoryForgetRequest] = []

    async def forget(self, ctx: MemoryContext, request: MemoryForgetRequest) -> MemoryForgetResult:
        _ = ctx
        self.requests.append(request)
        return MemoryForgetResult(deleted=self.deleted)


class _StoringProvider(BaseMemoryProvider):
    id = "storer"
    name = "Storer"
    capabilities = {"store"}

    def __init__(self, stored: int = 1) -> None:
        self.stored = stored
        self.requests: list[MemoryStoreRequest] = []

    async def store(self, ctx: MemoryContext, request: MemoryStoreRequest) -> MemoryStoreResult:
        _ = ctx
        self.requests.append(request)
        return MemoryStoreResult(stored=self.stored)


@pytest.mark.asyncio
async def test_memory_hub_fans_out_recall_and_emits_hooks() -> None:
    calls: list[str] = []
    bus = HookBus()
    bus.register("memory.recall.before", lambda event: calls.append(f"before:{event['request'].query}"), plugin_id="observer")
    bus.register(
        "memory.recall.after",
        lambda event: calls.append(f"after:{len(event['result'].hits)}"),
        plugin_id="observer",
    )
    hub = MemoryHub(
        hook_bus=bus,
        built_in_provider=_FakeBuiltInProvider(),
    )
    hub.add_external_provider("demo", _FakeExternalProvider())
    ctx = hub.context_for(
        user_id="user-1",
        agent_profile_id="profile-1",
        agent_profile_slug="coder",
    )

    result = await hub.recall(ctx, MemoryRecallRequest(query="deploy", top_k=5))

    assert calls == ["before:deploy", "after:2"]
    assert [hit.provider_id for hit in result.hits] == ["external", "builtin"]
    assert result.errors == {}


@pytest.mark.asyncio
async def test_memory_context_hooks_apply_request_and_result_patches() -> None:
    provider = _ContextProvider()
    bus = HookBus()
    bus.register(
        "before_context_build",
        lambda event: {"query": event["request"].query + " refined", "filters": {"kind": "preference"}},
        plugin_id="before",
    )
    bus.register(
        "memory.context.after_build",
        lambda event: {
            "redactions": [
                {
                    "provider_id": "contextual",
                    "title": "Original",
                    "content": "redacted context",
                }
            ],
            "add_contributions": [
                {
                    "provider_id": "hook",
                    "title": "Added",
                    "content": "extra context",
                    "priority": 10,
                }
            ],
        },
        plugin_id="after",
    )
    hub = MemoryHub(hook_bus=bus, built_in_provider=_FakeBuiltInProvider())
    hub.add_external_provider("demo", provider)
    ctx = hub.context_for(user_id="user-1", agent_profile_id="profile-1", agent_profile_slug="coder")

    result = await hub.build_context(ctx, MemoryContextRequest(query="deploy"))

    assert provider.requests[0].query == "deploy refined"
    assert provider.requests[0].filters == {"kind": "preference"}
    assert [item.title for item in result.contributions] == ["Added", "Original"]
    assert result.contributions[1].content == "redacted context"


@pytest.mark.asyncio
async def test_memory_recall_hooks_apply_request_and_result_patches() -> None:
    bus = HookBus()
    bus.register(
        "memory.recall.before",
        lambda event: {"query": "patched", "disabled_providers": ["builtin"], "top_k": 5},
        plugin_id="before",
    )
    bus.register(
        "after_memory_recall",
        lambda event: {
            "drop_provider_ids": ["external"],
            "add_hits": [
                {
                    "id": "hook-1",
                    "provider_id": "hook",
                    "content": "hook supplied memory",
                    "score": 1.0,
                    "source": "hook",
                }
            ],
        },
        plugin_id="after",
    )
    hub = MemoryHub(hook_bus=bus, built_in_provider=_FakeBuiltInProvider())
    hub.add_external_provider("demo", _FakeExternalProvider())
    ctx = hub.context_for(user_id="user-1", agent_profile_id="profile-1", agent_profile_slug="coder")

    result = await hub.recall(ctx, MemoryRecallRequest(query="deploy", top_k=5))

    assert [hit.provider_id for hit in result.hits] == ["hook"]
    assert result.hits[0].content == "hook supplied memory"


@pytest.mark.asyncio
async def test_memory_hub_queues_observe_turns_in_order() -> None:
    provider = _ObservingProvider()
    hub = MemoryHub(built_in_provider=_FakeBuiltInProvider())
    hub.add_external_provider("demo", provider)
    ctx = hub.context_for(user_id="user-1", agent_profile_id="profile-1", session_id="session-1")

    hub.queue_observe_turn(
        ctx,
        ConversationTurn(
            user_message_id="u1",
            assistant_message_id="a1",
            user_text="first",
            assistant_text="one",
            attachments=[],
            created_at=datetime.now(UTC),
        ),
    )
    hub.queue_observe_turn(
        ctx,
        ConversationTurn(
            user_message_id="u2",
            assistant_message_id="a2",
            user_text="second",
            assistant_text="two",
            attachments=[],
            created_at=datetime.now(UTC),
        ),
    )

    await hub.shutdown()

    assert [turn.user_text for turn in provider.turns] == ["first", "second"]


@pytest.mark.asyncio
async def test_memory_hub_forget_fans_out_and_emits_hooks() -> None:
    calls: list[str] = []
    bus = HookBus()
    bus.register(
        "memory.forget.before",
        lambda event: calls.append(f"before:{event['request'].selector.agent_profile_id}"),
        plugin_id="observer",
    )
    bus.register(
        "memory.forget.after",
        lambda event: calls.append(f"after:{event['result'].deleted}"),
        plugin_id="observer",
    )
    built_in = _ForgettingProvider(deleted=2)
    built_in.id = "builtin"
    external = _ForgettingProvider(deleted=3)
    hub = MemoryHub(hook_bus=bus, built_in_provider=built_in)
    hub.add_external_provider("demo", external)
    ctx = hub.context_for(user_id="user-1", agent_profile_id="profile-1", agent_profile_slug="coder")

    result = await hub.forget(
        ctx,
        MemoryForgetRequest(
            selector=MemoryForgetSelector(
                user_id="user-1",
                agent_profile_id="profile-1",
                all_for_profile=True,
            )
        ),
    )

    assert result.deleted == 5
    assert result.errors == {}
    assert calls == ["before:profile-1", "after:5"]
    assert external.requests[0].selector.all_for_profile is True


@pytest.mark.asyncio
async def test_memory_hub_store_fans_out_and_status_reports_background() -> None:
    calls: list[str] = []
    bus = HookBus()
    bus.register("memory.store.before", lambda event: calls.append(event["request"].source), plugin_id="observer")
    bus.register("memory.store.after", lambda event: calls.append(str(event["result"].stored)), plugin_id="observer")
    built_in = _StoringProvider(stored=2)
    built_in.id = "builtin"
    external = _StoringProvider(stored=3)
    hub = MemoryHub(hook_bus=bus, built_in_provider=built_in)
    hub.add_external_provider("demo", external)
    ctx = hub.context_for(user_id="user-1", agent_profile_id="profile-1", agent_profile_slug="coder")

    result = await hub.store(
        ctx,
        MemoryStoreRequest(
            items=[MemoryItem(content="Remember this.", source="tool")],
            source="tool",
        ),
    )
    status = await hub.status(ctx)

    assert result.stored == 5
    assert result.errors == {}
    assert calls == ["tool", "5"]
    assert built_in.requests[0].items[0].content == "Remember this."
    assert external.requests[0].source == "tool"
    assert status["background"]["observe_queue_count"] == 0
    assert status["last_errors"] == {}


@pytest.mark.asyncio
async def test_memory_store_hooks_apply_request_and_result_patches() -> None:
    bus = HookBus()
    bus.register(
        "before_memory_store",
        lambda event: {
            "items": [{"content": "normalized memory", "kind": "decision", "tags": ["normalized"], "source": "tool"}],
            "disabled_providers": ["builtin"],
        },
        plugin_id="before",
    )
    bus.register(
        "memory.store.after",
        lambda event: {"stored_delta": 2, "metadata": {"hook": "after"}},
        plugin_id="after",
    )
    built_in = _StoringProvider(stored=100)
    built_in.id = "builtin"
    external = _StoringProvider(stored=1)
    hub = MemoryHub(hook_bus=bus, built_in_provider=built_in)
    hub.add_external_provider("demo", external)
    ctx = hub.context_for(user_id="user-1", agent_profile_id="profile-1", agent_profile_slug="coder")

    result = await hub.store(ctx, MemoryStoreRequest(items=[MemoryItem(content="raw", source="tool")], source="tool"))

    assert built_in.requests == []
    assert external.requests[0].items[0].content == "normalized memory"
    assert external.requests[0].items[0].kind == "decision"
    assert result.stored == 3
    assert result.metadata == {"hook": "after"}


@pytest.mark.asyncio
async def test_memory_hub_forget_can_skip_builtin_for_profile_deletion() -> None:
    built_in = _ForgettingProvider(deleted=100)
    built_in.id = "builtin"
    external = _ForgettingProvider(deleted=3)
    hub = MemoryHub(built_in_provider=built_in)
    hub.add_external_provider("demo", external)
    ctx = hub.context_for(user_id="user-1", agent_profile_id="profile-1", agent_profile_slug="coder")

    result = await hub.forget(
        ctx,
        MemoryForgetRequest(
            selector=MemoryForgetSelector(
                user_id="user-1",
                agent_profile_id="profile-1",
                all_for_profile=True,
            ),
            include_builtin=False,
        ),
    )

    assert result.deleted == 3
    assert built_in.requests == []
    assert len(external.requests) == 1
