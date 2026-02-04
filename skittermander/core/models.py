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
class ToolCall:
    name: str
    input: Dict[str, Any]
    approval_required: bool = True


@dataclass
class ToolResult:
    name: str
    output: Dict[str, Any]
    status: str


@dataclass
class StreamEvent:
    session_id: str
    type: str
    data: Dict[str, Any]
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class AgentResponse:
    text: str
    attachments: List[Attachment] = field(default_factory=list)
