from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Dict

import httpx
from fastapi import WebSocket

from ..core.config import settings
from ..core.profile_context import current_agent_profile_id, current_agent_profile_slug
from ..data.db import SessionLocal
from ..data.repositories import Repository
from .sandbox_manager import sandbox_manager


_logger = logging.getLogger(__name__)


@dataclass
class NodeConnection:
    websocket: WebSocket
    send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    pending: dict[str, asyncio.Future] = field(default_factory=dict)
    last_heartbeat: datetime = field(default_factory=lambda: datetime.now(UTC))


class NodeExecutorHub:
    def __init__(self) -> None:
        self._connections: dict[str, NodeConnection] = {}
        self._lock = asyncio.Lock()

    async def register(self, executor_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            existing = self._connections.get(executor_id)
            self._connections[executor_id] = NodeConnection(websocket=websocket)
        if existing is not None:
            await self._fail_pending(existing, RuntimeError("Executor reconnected."))
            try:
                await existing.websocket.close(code=1012)
            except Exception:
                pass

    async def unregister(self, executor_id: str, websocket: WebSocket | None = None) -> None:
        async with self._lock:
            current = self._connections.get(executor_id)
            if current is None:
                return
            if websocket is not None and current.websocket is not websocket:
                return
            self._connections.pop(executor_id, None)
        await self._fail_pending(current, RuntimeError("Executor disconnected."))

    async def _fail_pending(self, connection: NodeConnection, exc: Exception) -> None:
        for request_id, future in list(connection.pending.items()):
            if not future.done():
                future.set_exception(exc)
            connection.pending.pop(request_id, None)

    async def is_online(self, executor_id: str) -> bool:
        async with self._lock:
            conn = self._connections.get(executor_id)
            if conn is None:
                return False
            return True

    async def online_executor_ids(self) -> list[str]:
        async with self._lock:
            return list(self._connections.keys())

    async def close_executor(self, executor_id: str) -> None:
        async with self._lock:
            conn = self._connections.get(executor_id)
        if conn is None:
            return
        try:
            await conn.websocket.close(code=1000)
        except Exception:
            pass
        await self.unregister(executor_id, websocket=conn.websocket)

    async def execute(
        self,
        *,
        executor_id: str,
        tool: str,
        session_id: str,
        payload: Dict[str, Any],
        timeout_s: float,
    ) -> Dict[str, Any]:
        async with self._lock:
            conn = self._connections.get(executor_id)
        if conn is None:
            raise RuntimeError("Executor is offline.")

        request_id = str(uuid.uuid4())
        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        conn.pending[request_id] = future
        message = {
            "type": "execute",
            "request_id": request_id,
            "tool": tool,
            "session_id": session_id,
            "payload": payload,
            "timeout_s": timeout_s,
        }
        async with conn.send_lock:
            await conn.websocket.send_json(message)
        try:
            result = await asyncio.wait_for(future, timeout=max(1.0, timeout_s))
            if isinstance(result, dict):
                return result
            return {"status": "ok", "result": result}
        except asyncio.TimeoutError as exc:
            await self._send_cancel(conn, request_id)
            raise RuntimeError("Executor request timed out.") from exc
        finally:
            conn.pending.pop(request_id, None)

    async def _send_cancel(self, conn: NodeConnection, request_id: str) -> None:
        try:
            async with conn.send_lock:
                await conn.websocket.send_json({"type": "cancel", "request_id": request_id})
        except Exception:
            pass

    async def handle_message(self, executor_id: str, message: dict) -> dict | None:
        msg_type = str(message.get("type") or "").strip().lower()
        async with self._lock:
            conn = self._connections.get(executor_id)
        if conn is None:
            return None
        if msg_type == "heartbeat":
            conn.last_heartbeat = datetime.now(UTC)
            return {"type": "heartbeat", "payload": message}
        if msg_type == "result":
            request_id = str(message.get("request_id") or "")
            if not request_id:
                return None
            fut = conn.pending.get(request_id)
            if fut is None or fut.done():
                return None
            if bool(message.get("ok", False)):
                fut.set_result(message.get("payload") or {})
            else:
                error = str(message.get("error") or "Executor returned an error.")
                fut.set_exception(RuntimeError(error))
            return {"type": "result"}
        return None


class ExecutorRouter:
    def __init__(self, node_hub: NodeExecutorHub) -> None:
        self._node_hub = node_hub
        self._session_defaults: dict[str, str] = {}
        self._session_defaults_lock = asyncio.Lock()

    async def set_session_default(self, session_id: str, executor_id: str | None) -> None:
        async with self._session_defaults_lock:
            if executor_id:
                self._session_defaults[session_id] = executor_id
            else:
                self._session_defaults.pop(session_id, None)

    async def get_session_default(self, session_id: str) -> str | None:
        async with self._session_defaults_lock:
            return self._session_defaults.get(session_id)

    async def clear_session_defaults_for_executor(self, executor_id: str) -> int:
        removed = 0
        async with self._session_defaults_lock:
            keys = [session_id for session_id, value in self._session_defaults.items() if value == executor_id]
            for session_id in keys:
                self._session_defaults.pop(session_id, None)
                removed += 1
        return removed

    async def execute(
        self,
        *,
        user_id: str,
        session_id: str,
        tool_name: str,
        payload: Dict[str, Any],
        timeout: float | None = None,
        target_machine: str | None = None,
    ) -> tuple[Dict[str, Any], dict[str, Any]]:
        row = await self._resolve_executor(user_id=user_id, session_id=session_id, target_machine=target_machine)
        if row.disabled:
            raise RuntimeError(f"Executor '{row.name}' is disabled.")
        timeout_s = float(timeout or 60.0)

        if row.kind == "docker":
            result = await self._execute_docker(user_id=user_id, session_id=session_id, tool_name=tool_name, payload=payload, timeout=timeout)
            async with SessionLocal() as session:
                repo = Repository(session)
                await repo.update_executor(
                    row.id,
                    status="online",
                    last_seen_at=datetime.now(UTC),
                )
            return result, {
                "executor_id": row.id,
                "executor_name": row.name,
                "executor_kind": row.kind,
            }

        if row.kind == "node":
            online = await self._node_hub.is_online(row.id)
            if not online:
                async with SessionLocal() as session:
                    repo = Repository(session)
                    await repo.update_executor(row.id, status="offline")
                raise RuntimeError(f"Executor '{row.name}' is offline.")
            result = await self._node_hub.execute(
                executor_id=row.id,
                tool=tool_name,
                session_id=session_id,
                payload=payload,
                timeout_s=timeout_s,
            )
            async with SessionLocal() as session:
                repo = Repository(session)
                await repo.update_executor(row.id, status="online", last_seen_at=datetime.now(UTC))
            return result, {
                "executor_id": row.id,
                "executor_name": row.name,
                "executor_kind": row.kind,
            }

        raise RuntimeError(f"Unsupported executor kind: {row.kind}")

    async def _resolve_executor(self, *, user_id: str, session_id: str, target_machine: str | None):
        target = (target_machine or "").strip()
        async with SessionLocal() as session:
            repo = Repository(session)
            active_profile_id = current_agent_profile_id().strip()

            if not target:
                target = (await self.get_session_default(session_id) or "").strip()
            if not target:
                if active_profile_id:
                    target = (await repo.get_profile_default_executor_id(active_profile_id) or "").strip()
            if not target:
                target = (await repo.get_user_default_executor_id(user_id) or "").strip()

            if target:
                if target.lower() in {"docker", "docker-default"}:
                    if settings.executors_auto_docker_default:
                        return await repo.get_or_create_docker_executor(user_id)
                    row = await repo.get_docker_executor_for_user(user_id)
                    if row is None:
                        raise RuntimeError("Docker default executor is disabled by configuration.")
                    return row
                row = await repo.get_executor_for_user(user_id, target)
                if row is None:
                    row = await repo.get_executor_for_user_by_name(user_id, target)
                if row is None:
                    raise RuntimeError(f"Unknown target machine: {target}")
                return row

            if settings.executors_auto_docker_default:
                return await repo.get_or_create_docker_executor(user_id)

            existing_default_id = None
            if active_profile_id:
                existing_default_id = await repo.get_profile_default_executor_id(active_profile_id)
            if not existing_default_id:
                existing_default_id = await repo.get_user_default_executor_id(user_id)
            if existing_default_id:
                row = await repo.get_executor_for_user(user_id, existing_default_id)
                if row is not None:
                    return row
            raise RuntimeError(
                "No default executor configured. Set one with /machine <executor_id_or_name>."
            )

    async def _execute_docker(
        self,
        *,
        user_id: str,
        session_id: str,
        tool_name: str,
        payload: Dict[str, Any],
        timeout: float | None,
    ) -> Dict[str, Any]:
        if sandbox_manager is None:
            raise RuntimeError("Docker sandbox manager is not available. Docker executor mode requires managed sandboxes.")
        base_url = await sandbox_manager.get_base_url(
            user_id,
            profile_slug=current_agent_profile_slug().strip() or None,
        )
        headers = {"Authorization": f"Bearer {settings.sandbox_api_key}"} if settings.sandbox_api_key else {}
        retries = max(1, int(settings.sandbox_connect_retries))
        backoff = max(0.1, float(settings.sandbox_connect_backoff))
        async with httpx.AsyncClient(timeout=timeout or 60) as client:
            for attempt in range(retries):
                try:
                    response = await client.post(
                        f"{base_url}/execute",
                        json={"session_id": session_id, "tool": tool_name, "payload": payload},
                        headers=headers,
                    )
                    response.raise_for_status()
                    return response.json()
                except httpx.ConnectError:
                    if attempt >= retries - 1:
                        raise
                    await asyncio.sleep(backoff * (attempt + 1))
        raise RuntimeError("Failed to reach docker executor.")


node_executor_hub = NodeExecutorHub()
executor_router = ExecutorRouter(node_executor_hub)
