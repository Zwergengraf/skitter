from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .profiles import private_profile_scope_id


@dataclass(frozen=True)
class ConversationScope:
    scope_type: str
    scope_id: str
    is_private: bool
    target_origin: str
    target_destination_id: str


def private_scope_id(owner_id: str) -> str:
    return private_profile_scope_id(owner_id)


def group_scope_id(origin: str, external_channel_id: str) -> str:
    return f"group:{origin}:{external_channel_id}"


def resolve_conversation_scope(
    *,
    origin: str,
    channel_id: str,
    internal_user_id: str,
    metadata: dict[str, Any] | None = None,
) -> ConversationScope:
    meta = metadata or {}
    explicit_type = str(meta.get("scope_type") or "").strip().lower()
    explicit_id = str(meta.get("scope_id") or "").strip()
    if explicit_type and explicit_id:
        return ConversationScope(
            scope_type=explicit_type,
            scope_id=explicit_id,
            is_private=explicit_type == "private",
            target_origin=origin,
            target_destination_id=channel_id,
        )

    raw_private = meta.get("is_private")
    if isinstance(raw_private, bool):
        is_private = raw_private
    elif origin in {"menubar", "tui", "web", "cli", "heartbeat", "scheduler"}:
        is_private = True
    else:
        is_private = True

    if origin == "discord" and not is_private:
        scope_type = "group"
        scope_id = group_scope_id(origin, channel_id)
    else:
        scope_type = "private"
        scope_id = private_scope_id(internal_user_id)
        is_private = True

    return ConversationScope(
        scope_type=scope_type,
        scope_id=scope_id,
        is_private=is_private,
        target_origin=origin,
        target_destination_id=channel_id,
    )
