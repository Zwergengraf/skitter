from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, Protocol, runtime_checkable

MemoryCapability = Literal[
    "health",
    "build_context",
    "recall",
    "store",
    "forget",
    "observe_turn",
    "session_memory_updated",
    "session_archived",
]

MemorySource = Literal[
    "tool",
    "command",
    "api",
    "context",
    "scheduler",
    "heartbeat",
    "archive",
    "session_memory",
    "import",
]


@dataclass(frozen=True)
class MemorySystemContext:
    plugin_id: str | None = None
    config: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MemoryContext:
    user_id: str
    agent_profile_id: str
    agent_profile_slug: str
    session_id: str | None = None
    run_id: str | None = None
    origin: str = ""
    transport_account_key: str | None = None
    scope_type: str = "private"
    scope_id: str = ""
    workspace_root: Path | None = None


@dataclass
class ContextContribution:
    provider_id: str
    title: str
    content: str
    priority: int = 100
    token_estimate: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class MemoryContextRequest:
    query: str
    recent_messages: list[dict[str, Any]] = field(default_factory=list)
    max_tokens: int = 1200
    filters: dict[str, Any] = field(default_factory=dict)


@dataclass
class MemoryContextResult:
    contributions: list[ContextContribution] = field(default_factory=list)


@dataclass
class MemoryRecallRequest:
    query: str
    top_k: int = 5
    source: MemorySource = "tool"
    max_tokens: int | None = None
    filters: dict[str, Any] = field(default_factory=dict)


@dataclass
class MemoryHit:
    id: str
    provider_id: str
    content: str
    score: float | None = None
    kind: str | None = None
    tags: list[str] = field(default_factory=list)
    source: str | None = None
    created_at: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_legacy_dict(self) -> dict[str, Any]:
        data = {
            "score": self.score if self.score is not None else 0.0,
            "summary": self.content,
            "tags": list(self.tags),
            "source": self.source or "(unknown)",
            "created_at": self.created_at,
            "provider_id": self.provider_id,
        }
        if self.kind:
            data["kind"] = self.kind
        if self.metadata:
            data["metadata"] = dict(self.metadata)
        return data


@dataclass
class MemoryRecallResult:
    hits: list[MemoryHit] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)


@dataclass
class MemoryItem:
    content: str
    kind: str = "fact"
    importance: float | None = None
    confidence: float | None = None
    tags: list[str] = field(default_factory=list)
    source: MemorySource = "api"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class MemoryStoreRequest:
    items: list[MemoryItem]
    source: MemorySource = "api"


@dataclass
class MemoryStoreResult:
    stored: int = 0
    errors: dict[str, str] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class MemoryForgetSelector:
    user_id: str
    agent_profile_id: str
    provider_id: str | None = None
    memory_ids: list[str] | None = None
    tags: list[str] | None = None
    source: str | None = None
    all_for_profile: bool = False


@dataclass
class MemoryForgetRequest:
    selector: MemoryForgetSelector
    include_builtin: bool = True


@dataclass
class MemoryForgetResult:
    deleted: int = 0
    unsupported: bool = False
    errors: dict[str, str] = field(default_factory=dict)


@dataclass
class MemoryHealth:
    status: Literal["ok", "degraded", "error", "disabled"] = "ok"
    message: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ConversationTurn:
    user_message_id: str | None
    assistant_message_id: str | None
    user_text: str
    assistant_text: str
    attachments: list[dict[str, Any]]
    created_at: datetime
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class SessionMemoryUpdated:
    session_id: str
    path: str
    content: str


@dataclass
class SessionArchived:
    session_id: str
    archive_summary: str
    session_memory_path: str | None = None
    previous_archive_summary: str | None = None


@runtime_checkable
class MemoryProvider(Protocol):
    id: str
    name: str
    capabilities: set[str]


class BaseMemoryProvider:
    id = "base"
    name = "Base Memory Provider"
    capabilities: set[str] = set()

    async def startup(self, ctx: MemorySystemContext) -> None:
        _ = ctx

    async def shutdown(self, ctx: MemorySystemContext) -> None:
        _ = ctx

    async def health(self, ctx: MemoryContext) -> MemoryHealth:
        _ = ctx
        return MemoryHealth()

    async def build_context(
        self,
        ctx: MemoryContext,
        request: MemoryContextRequest,
    ) -> MemoryContextResult:
        _ = ctx, request
        return MemoryContextResult()

    async def recall(
        self,
        ctx: MemoryContext,
        request: MemoryRecallRequest,
    ) -> MemoryRecallResult:
        _ = ctx, request
        return MemoryRecallResult()

    async def store(
        self,
        ctx: MemoryContext,
        request: MemoryStoreRequest,
    ) -> MemoryStoreResult:
        _ = ctx, request
        return MemoryStoreResult()

    async def forget(
        self,
        ctx: MemoryContext,
        request: MemoryForgetRequest,
    ) -> MemoryForgetResult:
        _ = ctx, request
        return MemoryForgetResult(unsupported=True)

    async def observe_turn(
        self,
        ctx: MemoryContext,
        turn: ConversationTurn,
    ) -> None:
        _ = ctx, turn

    async def on_session_memory_updated(
        self,
        ctx: MemoryContext,
        event: SessionMemoryUpdated,
    ) -> None:
        _ = ctx, event

    async def on_session_archived(
        self,
        ctx: MemoryContext,
        event: SessionArchived,
    ) -> None:
        _ = ctx, event
