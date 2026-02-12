from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, Float, JSON, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from pgvector.sqlalchemy import Vector


class Base(DeclarativeBase):
    pass


def utcnow() -> datetime:
    return datetime.now(UTC)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    transport_user_id: Mapped[str] = mapped_column(String, index=True)
    display_name: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    approved: Mapped[bool] = mapped_column(default=False)


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    status: Mapped[str] = mapped_column(String, default="active")
    scope_type: Mapped[str] = mapped_column(String, default="private")
    scope_id: Mapped[str] = mapped_column(String, default="")
    origin: Mapped[str] = mapped_column(String, default="discord")
    model: Mapped[str | None] = mapped_column(String, nullable=True)
    context_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    context_summary_checkpoint: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_cost: Mapped[float] = mapped_column(Float, default=0.0)
    last_input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    last_output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    last_total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    last_cost: Mapped[float] = mapped_column(Float, default=0.0)
    last_model: Mapped[str | None] = mapped_column(String, nullable=True)
    last_usage_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    session_id: Mapped[str] = mapped_column(String, index=True)
    role: Mapped[str] = mapped_column(String)
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)


class LlmUsage(Base):
    __tablename__ = "llm_usage"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    session_id: Mapped[str] = mapped_column(String, index=True)
    user_id: Mapped[str] = mapped_column(String, index=True)
    model: Mapped[str] = mapped_column(String)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ToolRun(Base):
    __tablename__ = "tool_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    session_id: Mapped[str] = mapped_column(String, index=True)
    run_id: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    message_id: Mapped[str | None] = mapped_column(String, nullable=True)
    tool_name: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String)
    input: Mapped[dict] = mapped_column(JSON, default=dict)
    output: Mapped[dict] = mapped_column(JSON, default=dict)
    approved_by: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RunTrace(Base):
    __tablename__ = "run_traces"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    session_id: Mapped[str] = mapped_column(String, index=True)
    user_id: Mapped[str] = mapped_column(String, index=True)
    message_id: Mapped[str] = mapped_column(String, index=True)
    origin: Mapped[str] = mapped_column(String, default="unknown")
    status: Mapped[str] = mapped_column(String, default="running")
    model: Mapped[str | None] = mapped_column(String, nullable=True)
    input_text: Mapped[str] = mapped_column(Text, default="")
    output_text: Mapped[str] = mapped_column(Text, default="")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    limit_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    limit_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    tool_calls: Mapped[int] = mapped_column(Integer, default=0)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost: Mapped[float] = mapped_column(Float, default=0.0)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)


class RunTraceEvent(Base):
    __tablename__ = "run_trace_events"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    run_id: Mapped[str] = mapped_column(String, index=True)
    session_id: Mapped[str] = mapped_column(String, index=True)
    event_type: Mapped[str] = mapped_column(String, index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class MemoryEntry(Base):
    __tablename__ = "memory_entries"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, index=True)
    embedding: Mapped[list[float]] = mapped_column(Vector(), nullable=False)
    summary: Mapped[str] = mapped_column(Text)
    tags: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Secret(Base):
    __tablename__ = "secrets"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, index=True)
    name: Mapped[str] = mapped_column(String, index=True)
    value_encrypted: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AuthToken(Base):
    __tablename__ = "auth_tokens"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, index=True)
    token_hash: Mapped[str] = mapped_column(String, unique=True, index=True)
    token_prefix: Mapped[str] = mapped_column(String, unique=True, index=True)
    device_name: Mapped[str | None] = mapped_column(String, nullable=True)
    device_type: Mapped[str | None] = mapped_column(String, nullable=True)
    created_via: Mapped[str] = mapped_column(String, default="unknown")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PairCode(Base):
    __tablename__ = "pair_codes"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    code_hash: Mapped[str] = mapped_column(String, unique=True, index=True)
    user_id: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    flow_type: Mapped[str] = mapped_column(String, default="pair")
    display_name: Mapped[str | None] = mapped_column(String, nullable=True)
    created_by_user_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_via: Mapped[str] = mapped_column(String, default="unknown")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)


class Channel(Base):
    __tablename__ = "channels"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    transport_channel_id: Mapped[str] = mapped_column(String, index=True)
    name: Mapped[str] = mapped_column(String)
    kind: Mapped[str] = mapped_column(String)
    guild_id: Mapped[str | None] = mapped_column(String, nullable=True)
    guild_name: Mapped[str | None] = mapped_column(String, nullable=True)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ScheduledJob(Base):
    __tablename__ = "scheduled_jobs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, index=True)
    channel_id: Mapped[str] = mapped_column(String)
    target_scope_type: Mapped[str] = mapped_column(String, default="private")
    target_scope_id: Mapped[str] = mapped_column(String, default="")
    target_origin: Mapped[str | None] = mapped_column(String, nullable=True)
    target_destination_id: Mapped[str | None] = mapped_column(String, nullable=True)
    name: Mapped[str] = mapped_column(String)
    prompt: Mapped[str] = mapped_column(Text)
    schedule_type: Mapped[str] = mapped_column(String, default="cron")
    schedule_expr: Mapped[str] = mapped_column(String)
    timezone: Mapped[str] = mapped_column(String, default="UTC")
    enabled: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ScheduledRun(Base):
    __tablename__ = "scheduled_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    job_id: Mapped[str] = mapped_column(String, index=True)
    status: Mapped[str] = mapped_column(String)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    output: Mapped[str | None] = mapped_column(Text, nullable=True)
    attachments: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AgentJob(Base):
    __tablename__ = "agent_jobs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, index=True)
    session_id: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    kind: Mapped[str] = mapped_column(String, default="sub_agent")
    name: Mapped[str] = mapped_column(String, default="Background job")
    status: Mapped[str] = mapped_column(String, default="queued")
    model: Mapped[str | None] = mapped_column(String, nullable=True)
    target_scope_type: Mapped[str] = mapped_column(String, default="private")
    target_scope_id: Mapped[str] = mapped_column(String, default="")
    target_origin: Mapped[str | None] = mapped_column(String, nullable=True)
    target_destination_id: Mapped[str | None] = mapped_column(String, nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    limits: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancel_requested: Mapped[bool] = mapped_column(default=False)
    tool_calls_used: Mapped[int] = mapped_column(Integer, default=0)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivery_error: Mapped[str | None] = mapped_column(Text, nullable=True)
