from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable

from ..core.models import Attachment
from .base import EventHandler, TransportAdapter

_logger = logging.getLogger(__name__)
RuntimeStateNotifier = Callable[[str, dict[str, object]], Awaitable[None]]


class TransportManager:
    def __init__(
        self,
        transports: dict[str, TransportAdapter] | None = None,
        *,
        runtime_state_notifier: RuntimeStateNotifier | None = None,
    ) -> None:
        self._transports: dict[str, TransportAdapter] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self._handler: EventHandler | None = None
        self._started = False
        self._stop_event = asyncio.Event()
        self._lock = asyncio.Lock()
        self._runtime_state_notifier = runtime_state_notifier
        self._runtime_states: dict[str, dict[str, object]] = {}
        if transports:
            self._transports = dict(transports)

    @property
    def transports(self) -> dict[str, TransportAdapter]:
        return dict(self._transports)

    def on_event(self, handler: EventHandler) -> None:
        self._handler = handler
        for account_key, transport in self._transports.items():
            transport.on_event(handler)
            transport.set_runtime_state_callback(
                lambda payload, account_key=account_key: self._record_runtime_state(account_key, payload)
            )

    def get(self, account_key: str | None) -> TransportAdapter | None:
        return self._transports.get(str(account_key or "").strip())

    def snapshot_states(self) -> dict[str, dict[str, object]]:
        return {key: dict(value) for key, value in self._runtime_states.items()}

    async def _record_runtime_state(self, account_key: str, payload: dict[str, object]) -> None:
        current = dict(self._runtime_states.get(account_key, {}))
        current.update(payload)
        self._runtime_states[account_key] = current
        if self._runtime_state_notifier is not None:
            try:
                await self._runtime_state_notifier(account_key, dict(current))
            except Exception:  # pragma: no cover - defensive notifier path
                _logger.exception("Failed to persist transport runtime state for %s", account_key)

    async def _run_transport(self, account_key: str, transport: TransportAdapter) -> None:
        try:
            await self._record_runtime_state(account_key, {"status": "starting", "last_error": None})
            await transport.start()
            await self._record_runtime_state(account_key, {"status": "offline"})
        except asyncio.CancelledError:
            await self._record_runtime_state(account_key, {"status": "offline"})
            raise
        except Exception as exc:  # pragma: no cover - transport-specific failure path
            await self._record_runtime_state(account_key, {"status": "error", "last_error": str(exc)})
            _logger.exception("Transport %s failed", account_key)

    async def _start_transport(self, account_key: str, transport: TransportAdapter) -> None:
        if self._handler is not None:
            transport.on_event(self._handler)
        transport.set_runtime_state_callback(
            lambda payload, account_key=account_key: self._record_runtime_state(account_key, payload)
        )
        if account_key in self._tasks and not self._tasks[account_key].done():
            return
        self._tasks[account_key] = asyncio.create_task(
            self._run_transport(account_key, transport),
            name=f"skitter-transport-{account_key}",
        )

    async def _stop_transport(self, account_key: str) -> None:
        transport = self._transports.get(account_key)
        task = self._tasks.get(account_key)
        if transport is not None:
            try:
                await transport.stop()
            except Exception:  # pragma: no cover - defensive shutdown path
                _logger.exception("Failed to stop transport %s", account_key)
        if task is not None:
            try:
                await task
            except BaseException:
                pass
            self._tasks.pop(account_key, None)
        await self._record_runtime_state(account_key, {"status": "offline"})

    async def reconcile(self, transports: dict[str, TransportAdapter]) -> None:
        async with self._lock:
            next_transports = dict(transports)
            current_keys = set(self._transports.keys())
            next_keys = set(next_transports.keys())
            remove_keys = current_keys - next_keys
            replace_keys = {
                key for key in current_keys & next_keys if self._transports[key] is not next_transports[key]
            }
            add_keys = next_keys - current_keys

            for key in sorted(remove_keys | replace_keys):
                await self._stop_transport(key)
                self._transports.pop(key, None)

            for key in sorted(add_keys | replace_keys):
                self._transports[key] = next_transports[key]
                if self._started:
                    await self._start_transport(key, next_transports[key])

    async def start(self) -> None:
        async with self._lock:
            if self._started:
                return
            self._started = True
            self._stop_event.clear()
            for account_key, transport in self._transports.items():
                await self._start_transport(account_key, transport)
        await self._stop_event.wait()

    async def stop(self) -> None:
        async with self._lock:
            if not self._started:
                return
            self._started = False
            self._stop_event.set()
            keys = list(self._transports.keys())
        for account_key in keys:
            await self._stop_transport(account_key)

    async def send_message(
        self,
        account_key: str,
        channel_id: str,
        content: str,
        attachments: list[Attachment] | None = None,
        metadata: dict | None = None,
    ) -> None:
        transport = self.get(account_key)
        if transport is None:
            raise RuntimeError(f"Unknown transport account `{account_key}`.")
        await transport.send_message(channel_id, content, attachments=attachments, metadata=metadata)

    async def send_typing(self, account_key: str, channel_id: str) -> None:
        transport = self.get(account_key)
        if transport is None:
            raise RuntimeError(f"Unknown transport account `{account_key}`.")
        await transport.send_typing(channel_id)

    async def send_user_message(
        self,
        account_key: str,
        user_id: str,
        content: str,
        attachments: list[Attachment] | None = None,
        metadata: dict | None = None,
    ) -> None:
        transport = self.get(account_key)
        if transport is None:
            raise RuntimeError(f"Unknown transport account `{account_key}`.")
        await transport.send_user_message(user_id, content, attachments=attachments, metadata=metadata)

    async def send_approval_request(
        self,
        tool_run_id: str,
        channel_id: str,
        tool_name: str,
        account_key: str | None,
        payload: dict,
    ) -> None:
        transport = self.get(account_key)
        if transport is None:
            raise RuntimeError(f"Unknown transport account `{account_key}`.")
        await transport.send_approval_request(tool_run_id, channel_id, tool_name, payload)

    async def send_user_prompt_request(
        self,
        prompt_id: str,
        channel_id: str,
        account_key: str | None,
        question: str,
        choices: list[str],
        allow_free_text: bool,
    ) -> None:
        transport = self.get(account_key)
        if transport is None:
            raise RuntimeError(f"Unknown transport account `{account_key}`.")
        await transport.send_user_prompt_request(prompt_id, channel_id, question, choices, allow_free_text)
