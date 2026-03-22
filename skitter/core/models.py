from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Dict, List, Optional


@dataclass
class Attachment:
    filename: str
    content_type: str
    url: Optional[str] = None
    bytes_data: Optional[bytes] = None
    path: Optional[str] = None


@dataclass
class MessageEnvelope:
    message_id: str
    channel_id: str
    user_id: str
    timestamp: datetime
    text: str
    attachments: List[Attachment] = field(default_factory=list)
    origin: str = "unknown"
    command: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class StreamEvent:
    session_id: str
    type: str
    data: Dict[str, Any]
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class AdminEvent:
    kind: str
    title: str
    message: str
    level: str = "info"
    data: Dict[str, Any] = field(default_factory=dict)
    session_id: str | None = None
    user_id: str | None = None
    run_id: str | None = None
    job_id: str | None = None
    tool_run_id: str | None = None
    executor_id: str | None = None
    transport: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    id: str = field(default_factory=lambda: str(uuid.uuid4()))


@dataclass
class PendingUserPrompt:
    prompt_id: str
    question: str
    choices: List[str] = field(default_factory=list)
    allow_free_text: bool = True


@dataclass
class AgentResponse:
    text: str
    attachments: List[Attachment] = field(default_factory=list)
    run_id: str | None = None
    reasoning: List[str] = field(default_factory=list)
    pending_prompt: PendingUserPrompt | None = None
