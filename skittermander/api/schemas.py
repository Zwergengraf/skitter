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
