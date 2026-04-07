from __future__ import annotations

import re


DEFAULT_AGENT_PROFILE_SLUG = "default"
DEFAULT_AGENT_PROFILE_NAME = "Default"

_PROFILE_SLUG_RE = re.compile(r"[^a-z0-9]+")


def normalize_profile_slug(value: str, *, fallback: str = "agent") -> str:
    cleaned = _PROFILE_SLUG_RE.sub("-", str(value or "").strip().lower()).strip("-")
    return cleaned or fallback


def private_profile_scope_id(agent_profile_id: str) -> str:
    return f"private:{agent_profile_id}"
