from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any


HOOK_FIELDS: dict[str, tuple[str, ...]] = {
    "server.started": (
        "started_at",
        "plugin_root",
        "plugin_count",
    ),
    "server.stopping": (
        "started_at",
        "stopping_at",
    ),
    "session.started": (
        "session_id",
        "user_id",
        "agent_profile_id",
        "agent_profile_slug",
        "origin",
        "scope_type",
        "scope_id",
    ),
    "run.started": (
        "run_id",
        "session_id",
        "user_id",
        "agent_profile_id",
        "agent_profile_slug",
        "message_id",
        "origin",
        "transport_account_key",
        "scope_type",
        "scope_id",
        "model",
        "input_text",
        "has_attachments",
        "is_command",
        "started_at",
    ),
    "run.finished": (
        "run_id",
        "session_id",
        "user_id",
        "agent_profile_id",
        "agent_profile_slug",
        "message_id",
        "origin",
        "transport_account_key",
        "scope_type",
        "scope_id",
        "status",
        "model",
        "error",
        "limit_reason",
        "limit_detail",
        "duration_ms",
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "cost",
        "response_text",
        "response_preview",
        "finished_at",
    ),
    "tool_call.started": (
        "tool_name",
        "tool_run_id",
        "session_id",
        "run_id",
        "user_id",
        "agent_profile_id",
        "agent_profile_slug",
        "message_id",
        "origin",
        "transport_account_key",
        "scope_type",
        "scope_id",
        "input",
        "status",
    ),
    "tool_call.finished": (
        "tool_name",
        "tool_run_id",
        "session_id",
        "run_id",
        "user_id",
        "agent_profile_id",
        "agent_profile_slug",
        "message_id",
        "origin",
        "transport_account_key",
        "scope_type",
        "scope_id",
        "output",
        "status",
        "executor_id",
    ),
    "tool_call.failed": (
        "tool_name",
        "tool_run_id",
        "session_id",
        "run_id",
        "user_id",
        "agent_profile_id",
        "agent_profile_slug",
        "message_id",
        "origin",
        "transport_account_key",
        "scope_type",
        "scope_id",
        "output",
        "status",
        "executor_id",
    ),
    "llm.before_call": (
        "run_id",
        "session_id",
        "user_id",
        "agent_profile_id",
        "agent_profile_slug",
        "message_id",
        "origin",
        "transport_account_key",
        "scope_type",
        "scope_id",
        "model",
        "attempt",
        "total_attempts",
        "messages",
    ),
    "llm.after_call": (
        "run_id",
        "session_id",
        "user_id",
        "agent_profile_id",
        "agent_profile_slug",
        "message_id",
        "origin",
        "transport_account_key",
        "scope_type",
        "scope_id",
        "model",
        "attempt",
        "total_attempts",
        "messages",
        "result",
        "result_messages",
    ),
}


def register(ctx: Any) -> None:
    logger = logging.getLogger(str(ctx.config.get("logger_name") or "skitter.plugins.example_plugin"))
    logger.setLevel(_log_level(ctx.config.get("log_level")))
    priority = _priority(ctx.config.get("priority"))

    for hook_name, fields in HOOK_FIELDS.items():
        ctx.register_hook(
            hook_name,
            _handler(logger, hook_name, fields),
            priority=priority,
        )

    logger.debug(
        "example_plugin registered hooks=%s priority=%s",
        ",".join(HOOK_FIELDS.keys()),
        priority,
    )


def _handler(logger: logging.Logger, hook_name: str, fields: tuple[str, ...]):
    def handle(event: Any) -> None:
        event_map = event if isinstance(event, Mapping) else {}
        logger.debug("example_plugin hook=%s %s", hook_name, _format_event(event_map, fields))
        return None

    return handle


def _format_event(event: Mapping[str, Any], fields: tuple[str, ...]) -> str:
    parts = [f"{field}={_format_value(event[field])}" if field in event else f"{field}=<missing>" for field in fields]
    summary = " ".join(parts)
    if len(summary) > 1400:
        return summary[:1397].rstrip() + "..."
    return summary


def _format_value(value: Any) -> str:
    if value is None:
        return "None"
    if isinstance(value, Mapping):
        keys = ",".join(str(key) for key in list(value.keys())[:6])
        suffix = ",..." if len(value) > 6 else ""
        return f"dict(keys={keys}{suffix})"
    if isinstance(value, (list, tuple, set)):
        return f"{value.__class__.__name__}(len={len(value)})"
    text = str(value).replace("\n", "\\n")
    if len(text) > 80:
        text = text[:77].rstrip() + "..."
    return repr(text)


def _log_level(value: Any) -> int:
    name = str(value or "DEBUG").strip().upper()
    level = getattr(logging, name, logging.DEBUG)
    return level if isinstance(level, int) else logging.DEBUG


def _priority(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 100
