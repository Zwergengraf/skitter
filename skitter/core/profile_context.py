from __future__ import annotations

from contextvars import ContextVar, Token


_CURRENT_AGENT_PROFILE_ID: ContextVar[str] = ContextVar("skitter_agent_profile_id", default="")
_CURRENT_AGENT_PROFILE_SLUG: ContextVar[str] = ContextVar("skitter_agent_profile_slug", default="")


def set_current_agent_profile_id(profile_id: str) -> Token:
    return _CURRENT_AGENT_PROFILE_ID.set(str(profile_id or ""))


def reset_current_agent_profile_id(token: Token) -> None:
    _CURRENT_AGENT_PROFILE_ID.reset(token)


def set_current_agent_profile_slug(profile_slug: str) -> Token:
    return _CURRENT_AGENT_PROFILE_SLUG.set(str(profile_slug or ""))


def reset_current_agent_profile_slug(token: Token) -> None:
    _CURRENT_AGENT_PROFILE_SLUG.reset(token)


def current_agent_profile_id() -> str:
    return _CURRENT_AGENT_PROFILE_ID.get()


def current_agent_profile_slug() -> str:
    return _CURRENT_AGENT_PROFILE_SLUG.get()
