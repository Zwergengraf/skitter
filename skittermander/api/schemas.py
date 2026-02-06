from __future__ import annotations

from datetime import datetime
from typing import Any, Dict

from pydantic import BaseModel, Field


class SessionCreate(BaseModel):
    user_id: str


class SessionOut(BaseModel):
    id: str
    user_id: str
    created_at: datetime
    status: str


class SessionListItem(BaseModel):
    id: str
    user: str
    transport: str
    status: str
    last_active_at: datetime | None = None


class SessionMessageOut(BaseModel):
    id: str
    role: str
    content: str
    created_at: datetime
    meta: dict


class SessionToolRunOut(BaseModel):
    id: str
    tool: str
    status: str
    input: dict
    output: dict
    approved_by: str | None = None
    created_at: datetime


class SessionDetailOut(BaseModel):
    id: str
    user_id: str
    user: str
    status: str
    created_at: datetime
    last_active_at: datetime | None = None
    messages: list[SessionMessageOut]
    tool_runs: list[SessionToolRunOut]


class MemoryEntryOut(BaseModel):
    id: str
    summary: str
    tags: list
    created_at: datetime
    source: str | None = None
    session_ids: list[str] = []


class MessageCreate(BaseModel):
    session_id: str
    user_id: str
    text: str
    metadata: Dict[str, Any] = Field(default_factory=dict)


class MessageOut(BaseModel):
    id: str
    session_id: str
    role: str
    content: str
    created_at: datetime


class ToolApprovalRequest(BaseModel):
    approved_by: str


class SkillOut(BaseModel):
    name: str
    description: str
    path: str


class SecretCreate(BaseModel):
    user_id: str
    name: str
    value: str


class SecretOut(BaseModel):
    name: str
    created_at: datetime
    updated_at: datetime
    last_used_at: datetime | None = None


class MemoryForgetRequest(BaseModel):
    user_id: str


class ArtifactOut(BaseModel):
    id: str
    session_id: str
    path: str
    mime_type: str
    created_at: datetime


class EventOut(BaseModel):
    type: str
    data: Dict[str, Any]
    created_at: datetime


class HealthOut(BaseModel):
    status: str


class OverviewCostPoint(BaseModel):
    label: str
    cost: float


class OverviewServiceStatus(BaseModel):
    name: str
    status: str
    detail: str | None = None


class OverviewSessionOut(BaseModel):
    id: str
    user: str
    transport: str
    status: str
    last_active_at: datetime | None = None


class OverviewToolRunOut(BaseModel):
    id: str
    tool: str
    status: str
    requested_by: str
    created_at: datetime


class OverviewOut(BaseModel):
    cost_trajectory: list[OverviewCostPoint]
    system_health: list[OverviewServiceStatus]
    live_sessions: list[OverviewSessionOut]
    tool_approvals: list[OverviewToolRunOut]


class ToolRunListItem(BaseModel):
    id: str
    tool: str
    status: str
    requested_by: str
    created_at: datetime
    session_id: str
    approved_by: str | None = None
    input: dict
    output: dict


class ScheduledJobCreate(BaseModel):
    user_id: str
    channel_id: str
    name: str
    prompt: str
    schedule_type: str = "cron"
    schedule_expr: str
    enabled: bool = True


class ScheduledJobUpdate(BaseModel):
    name: str | None = None
    prompt: str | None = None
    schedule_type: str | None = None
    schedule_expr: str | None = None
    enabled: bool | None = None
    channel_id: str | None = None


class ScheduledJobOut(BaseModel):
    id: str
    user_id: str
    channel_id: str
    name: str
    prompt: str
    schedule_type: str
    schedule_expr: str
    timezone: str
    enabled: bool
    created_at: datetime
    updated_at: datetime
    last_run_at: datetime | None = None
    next_run_at: datetime | None = None


class UserListItem(BaseModel):
    id: str
    transport_user_id: str
    display_name: str | None = None
    username: str | None = None
    avatar_url: str | None = None
    approved: bool


class UserApprovalRequest(BaseModel):
    approved: bool


class ChannelListItem(BaseModel):
    id: str
    name: str
    kind: str
    label: str
    guild_name: str | None = None


class SandboxWorkspaceOut(BaseModel):
    user_id: str
    path: str
    size_bytes: int
    size_human: str
    updated_at: datetime


class SandboxContainerOut(BaseModel):
    id: str
    name: str
    status: str
    user_id: str | None = None
    created_at: datetime | None = None
    base_url: str | None = None
    ports: list[str] = []
    last_activity_at: datetime | None = None


class SandboxStatusOut(BaseModel):
    workspaces: list[SandboxWorkspaceOut]
    containers: list[SandboxContainerOut]
    total_workspace_bytes: int
    total_workspace_human: str


class ConfigFieldOut(BaseModel):
    key: str
    label: str
    type: str
    value: Any
    description: str | None = None
    secret: bool = False
    minimum: float | None = None
    maximum: float | None = None
    step: float | None = None


class ConfigCategoryOut(BaseModel):
    id: str
    label: str
    fields: list[ConfigFieldOut]


class ConfigResponse(BaseModel):
    categories: list[ConfigCategoryOut]


class ConfigUpdate(BaseModel):
    values: dict[str, Any]
