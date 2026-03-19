from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
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
