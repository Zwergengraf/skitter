from __future__ import annotations

import asyncio
import inspect
import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

_logger = logging.getLogger(__name__)

HookHandler = Callable[[Any], Awaitable[Any] | Any]


@dataclass(frozen=True)
class HookHandlerRegistration:
    hook_name: str
    plugin_id: str
    handler: HookHandler
    priority: int = 100
    timeout_seconds: float | None = None


@dataclass
class HookCallResult:
    hook_name: str
    plugin_id: str
    ok: bool
    value: Any = None
    error: str | None = None


@dataclass
class HookBus:
    default_timeout_seconds: float = 5.0
    _handlers: dict[str, list[HookHandlerRegistration]] = field(default_factory=dict)

    def register(
        self,
        hook_name: str,
        handler: HookHandler,
        *,
        plugin_id: str,
        priority: int = 100,
        timeout_seconds: float | None = None,
    ) -> None:
        normalized = self._normalize_hook_name(hook_name)
        registration = HookHandlerRegistration(
            hook_name=normalized,
            plugin_id=(plugin_id or "unknown").strip() or "unknown",
            handler=handler,
            priority=int(priority),
            timeout_seconds=timeout_seconds,
        )
        handlers = self._handlers.setdefault(normalized, [])
        handlers.append(registration)
        handlers.sort(key=lambda item: (item.priority, item.plugin_id))

    def handlers_for(self, hook_name: str) -> list[HookHandlerRegistration]:
        return list(self._handlers.get(self._normalize_hook_name(hook_name), []))

    def snapshot(self) -> dict[str, list[dict[str, Any]]]:
        return {
            name: [
                {
                    "plugin_id": registration.plugin_id,
                    "priority": registration.priority,
                    "timeout_seconds": registration.timeout_seconds,
                }
                for registration in handlers
            ]
            for name, handlers in sorted(self._handlers.items())
        }

    async def emit(self, hook_name: str, event: Any = None) -> list[HookCallResult]:
        normalized = self._normalize_hook_name(hook_name)
        results: list[HookCallResult] = []
        for registration in self.handlers_for(normalized):
            timeout = registration.timeout_seconds
            if timeout is None:
                timeout = self.default_timeout_seconds
            try:
                value = registration.handler(event)
                if inspect.isawaitable(value):
                    value = await asyncio.wait_for(value, timeout=max(0.1, float(timeout)))
                results.append(
                    HookCallResult(
                        hook_name=normalized,
                        plugin_id=registration.plugin_id,
                        ok=True,
                        value=value,
                    )
                )
            except Exception as exc:
                _logger.warning(
                    "Plugin hook failed: hook=%s plugin=%s error=%s",
                    normalized,
                    registration.plugin_id,
                    exc,
                )
                results.append(
                    HookCallResult(
                        hook_name=normalized,
                        plugin_id=registration.plugin_id,
                        ok=False,
                        error=str(exc) or exc.__class__.__name__,
                    )
                )
        return results

    @staticmethod
    def _normalize_hook_name(hook_name: str) -> str:
        normalized = str(hook_name or "").strip().lower()
        aliases = {
            "server_started": "server.started",
            "server_stopping": "server.stopping",
            "session_started": "session.started",
            "run_started": "run.started",
            "run_finished": "run.finished",
            "tool_call_started": "tool_call.started",
            "tool_call_finished": "tool_call.finished",
            "tool_call_failed": "tool_call.failed",
            "session_memory_updated": "memory.session_memory.updated",
            "session_archived": "memory.session.archived",
            "before_context_build": "memory.context.before_build",
            "after_context_build": "memory.context.after_build",
            "before_llm_call": "llm.before_call",
            "after_llm_call": "llm.after_call",
            "before_memory_recall": "memory.recall.before",
            "after_memory_recall": "memory.recall.after",
            "before_memory_store": "memory.store.before",
            "after_memory_store": "memory.store.after",
        }
        return aliases.get(normalized, normalized)
