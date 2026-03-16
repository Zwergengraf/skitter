from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, UTC
from pathlib import Path
from typing import Any

import httpx

from .config import MCPServerConfig, settings

_logger = logging.getLogger(__name__)


class MCPError(RuntimeError):
    """Raised for MCP session/transport/protocol failures."""


@dataclass(slots=True)
class MCPToolInfo:
    server: str
    name: str
    description: str
    input_schema: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "server": self.server,
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }


class _MCPServerSession:
    def __init__(self, config: MCPServerConfig) -> None:
        self.config = config
        self._process: asyncio.subprocess.Process | None = None
        self._client: httpx.AsyncClient | None = None
        self._http_session_id: str | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        self._pending: dict[int, asyncio.Future[Any]] = {}
        self._next_id = 1
        self._initialized = False
        self._io_lock = asyncio.Lock()
        self._start_lock = asyncio.Lock()
        self._tools_cache: list[MCPToolInfo] | None = None
        self._tools_cache_at: datetime | None = None
        self.last_error: str | None = None
        self.last_seen_at: datetime | None = None

    def _signature(self) -> tuple[Any, ...]:
        return (
            self.config.transport,
            self.config.command,
            tuple(self.config.args),
            self.config.url,
            tuple(sorted(self.config.headers.items())),
            tuple(sorted(self.config.env.items())),
            self.config.cwd,
            float(self.config.startup_timeout_seconds),
            float(self.config.request_timeout_seconds),
        )

    def is_same_config(self, other: MCPServerConfig) -> bool:
        return self._signature() == _MCPServerSession(other)._signature()

    @property
    def is_running(self) -> bool:
        if self.config.transport == "http":
            return self._client is not None and self._initialized
        return bool(self._process and self._process.returncode is None)

    async def ensure_started(self) -> None:
        if self.is_running and self._initialized:
            return
        async with self._start_lock:
            if self.is_running and self._initialized:
                return
            await self.close()

            if self.config.transport == "http":
                self._client = httpx.AsyncClient()
                try:
                    await self._initialize()
                except Exception:
                    await self.close()
                    raise
                return

            command = self.config.command.strip()
            if not command:
                raise MCPError(f"MCP server `{self.config.name}` has no command configured")

            env = os.environ.copy()
            if self.config.env:
                for key, value in self.config.env.items():
                    env[str(key)] = str(value)

            cwd = self.config.cwd.strip() if self.config.cwd else ""
            if cwd:
                try:
                    Path(cwd).mkdir(parents=True, exist_ok=True)
                except Exception:
                    # If cwd does not exist and cannot be created, process launch will fail.
                    pass

            try:
                self._process = await asyncio.create_subprocess_exec(
                    command,
                    *self.config.args,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=env,
                    cwd=(cwd or None),
                )
            except Exception as exc:  # pragma: no cover - depends on runtime env
                self.last_error = f"Failed to start process: {exc}"
                raise MCPError(f"Failed to start MCP server `{self.config.name}`: {exc}") from exc

            self._reader_task = asyncio.create_task(self._reader_loop(), name=f"mcp-reader:{self.config.name}")
            self._stderr_task = asyncio.create_task(self._stderr_loop(), name=f"mcp-stderr:{self.config.name}")

            try:
                await self._initialize()
            except Exception:
                await self.close()
                raise

    async def close(self) -> None:
        self._initialized = False
        self._tools_cache = None
        self._tools_cache_at = None
        self._http_session_id = None

        if self._reader_task:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except BaseException:
                pass
            self._reader_task = None

        if self._stderr_task:
            self._stderr_task.cancel()
            try:
                await self._stderr_task
            except BaseException:
                pass
            self._stderr_task = None

        process = self._process
        self._process = None
        if process is not None and process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=2.0)
            except Exception:
                process.kill()
                try:
                    await asyncio.wait_for(process.wait(), timeout=2.0)
                except Exception:
                    pass

        client = self._client
        self._client = None
        if client is not None:
            try:
                await client.aclose()
            except Exception:
                pass

        for future in list(self._pending.values()):
            if not future.done():
                future.set_exception(MCPError(f"MCP server `{self.config.name}` disconnected"))
        self._pending.clear()

    async def list_tools(self, *, force_refresh: bool = False) -> list[MCPToolInfo]:
        await self.ensure_started()
        if not force_refresh and self._tools_cache is not None:
            return list(self._tools_cache)

        result = await self._request("tools/list", params={})
        raw_tools = result.get("tools")
        tools: list[MCPToolInfo] = []
        if isinstance(raw_tools, list):
            for item in raw_tools:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name") or "").strip()
                if not name:
                    continue
                description = str(item.get("description") or "").strip()
                input_schema = item.get("inputSchema")
                if not isinstance(input_schema, dict):
                    input_schema = {}
                tools.append(
                    MCPToolInfo(
                        server=self.config.name,
                        name=name,
                        description=description,
                        input_schema=input_schema,
                    )
                )

        self._tools_cache = list(tools)
        self._tools_cache_at = datetime.now(UTC)
        return tools

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        await self.ensure_started()
        result = await self._request(
            "tools/call",
            params={
                "name": tool_name,
                "arguments": arguments,
            },
        )
        if not isinstance(result, dict):
            raise MCPError("MCP tools/call returned invalid payload")
        self.last_seen_at = datetime.now(UTC)
        self.last_error = None
        return result

    async def _initialize(self) -> None:
        protocol_candidates = ["2024-11-05", "2024-10-07"]
        last_exc: Exception | None = None
        for protocol_version in protocol_candidates:
            try:
                await self._request(
                    "initialize",
                    {
                        "protocolVersion": protocol_version,
                        "capabilities": {"tools": {}},
                        "clientInfo": {"name": "skitter", "version": "0.1.0"},
                    },
                    timeout=max(1.0, float(self.config.startup_timeout_seconds)),
                )
                await self._notify("notifications/initialized", {})
                self._initialized = True
                self.last_error = None
                self.last_seen_at = datetime.now(UTC)
                return
            except Exception as exc:
                last_exc = exc
                # Retry with next protocol candidate.
                continue
        self.last_error = str(last_exc) if last_exc else "initialize failed"
        raise MCPError(f"Failed to initialize MCP server `{self.config.name}`: {self.last_error}")

    async def _stderr_loop(self) -> None:
        process = self._process
        if process is None or process.stderr is None:
            return
        try:
            while True:
                line = await process.stderr.readline()
                if not line:
                    return
                text = line.decode("utf-8", errors="replace").rstrip()
                if text:
                    _logger.info("mcp[%s] stderr: %s", self.config.name, text)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # pragma: no cover - defensive
            _logger.debug("mcp[%s] stderr loop ended: %s", self.config.name, exc)

    async def _reader_loop(self) -> None:
        process = self._process
        if process is None or process.stdout is None:
            return
        try:
            while True:
                message = await self._read_message(process.stdout)
                await self._handle_message(message)
        except asyncio.IncompleteReadError:
            pass
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            _logger.warning("mcp[%s] reader loop failed: %s", self.config.name, exc)
            self.last_error = str(exc)
        finally:
            err = MCPError(f"MCP server `{self.config.name}` disconnected")
            for future in list(self._pending.values()):
                if not future.done():
                    future.set_exception(err)
            self._pending.clear()

    async def _request(self, method: str, params: dict[str, Any], timeout: float | None = None) -> dict[str, Any]:
        if self.config.transport == "http":
            wait_timeout = timeout if timeout is not None else max(1.0, float(self.config.request_timeout_seconds))
            return await self._request_http(method=method, params=params, timeout=wait_timeout)

        request_id = self._next_id
        self._next_id += 1
        loop = asyncio.get_running_loop()
        future: asyncio.Future[Any] = loop.create_future()
        self._pending[request_id] = future
        payload = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params,
        }

        async with self._io_lock:
            await self._send_message(payload)

        try:
            wait_timeout = timeout if timeout is not None else max(1.0, float(self.config.request_timeout_seconds))
            result = await asyncio.wait_for(future, timeout=wait_timeout)
            if isinstance(result, dict):
                return result
            return {}
        except asyncio.TimeoutError as exc:
            raise MCPError(f"MCP request timed out: {method}") from exc
        finally:
            self._pending.pop(request_id, None)

    async def _notify(self, method: str, params: dict[str, Any]) -> None:
        if self.config.transport == "http":
            await self._notify_http(method=method, params=params)
            return
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        }
        async with self._io_lock:
            await self._send_message(payload)

    async def _send_message(self, payload: dict[str, Any]) -> None:
        process = self._process
        if process is None or process.stdin is None:
            raise MCPError(f"MCP server `{self.config.name}` is not running")
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
        process.stdin.write(header)
        process.stdin.write(body)
        await process.stdin.drain()

    @staticmethod
    async def _read_message(reader: asyncio.StreamReader) -> dict[str, Any]:
        header_bytes = await reader.readuntil(b"\r\n\r\n")
        header_text = header_bytes.decode("utf-8", errors="replace")
        content_length: int | None = None
        for line in header_text.split("\r\n"):
            if not line or ":" not in line:
                continue
            key, value = line.split(":", 1)
            if key.strip().lower() == "content-length":
                try:
                    content_length = int(value.strip())
                except ValueError as exc:
                    raise MCPError(f"Invalid Content-Length header: {value!r}") from exc
        if content_length is None:
            raise MCPError("Missing Content-Length header in MCP message")
        body = await reader.readexactly(content_length)
        try:
            payload = json.loads(body.decode("utf-8"))
        except Exception as exc:
            raise MCPError("Failed to decode MCP JSON message") from exc
        if not isinstance(payload, dict):
            raise MCPError("Invalid MCP payload type")
        return payload

    async def _handle_message(self, payload: dict[str, Any]) -> None:
        if "id" not in payload:
            return
        try:
            response_id = int(payload.get("id"))
        except Exception:
            return
        future = self._pending.get(response_id)
        if future is None or future.done():
            return

        if "error" in payload:
            error_obj = payload.get("error")
            if isinstance(error_obj, dict):
                message = str(error_obj.get("message") or json.dumps(error_obj, ensure_ascii=False))
            else:
                message = str(error_obj)
            future.set_exception(MCPError(message))
            self.last_error = message
            return

        future.set_result(payload.get("result") or {})
        self.last_seen_at = datetime.now(UTC)

    def _http_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {
            "content-type": "application/json",
        }
        for key, value in self.config.headers.items():
            clean_key = str(key).strip()
            if not clean_key:
                continue
            headers[clean_key] = str(value)
        existing_accept = ""
        for key, value in headers.items():
            if key.lower() == "accept":
                existing_accept = str(value)
                break
        accept_values = {
            item.strip().lower()
            for item in existing_accept.split(",")
            if item.strip()
        }
        accept_values.update({"application/json", "text/event-stream"})
        headers["accept"] = ", ".join(sorted(accept_values))
        if self._http_session_id:
            headers["mcp-session-id"] = self._http_session_id
        return headers

    @staticmethod
    def _parse_sse_response(text: str) -> dict[str, Any] | list[Any]:
        data_chunks: list[str] = []
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line or line.startswith(":"):
                continue
            if line.startswith("data:"):
                data_chunks.append(line[5:].lstrip())
        if not data_chunks:
            raise MCPError("MCP server returned SSE without any data payload")
        payload_text = "\n".join(data_chunks).strip()
        try:
            parsed = json.loads(payload_text)
        except Exception as exc:
            raise MCPError(
                f"MCP server returned SSE with non-JSON data: {payload_text[:200]}"
            ) from exc
        if isinstance(parsed, (dict, list)):
            return parsed
        raise MCPError("MCP server returned SSE with invalid JSON payload type")

    async def _request_http(self, *, method: str, params: dict[str, Any], timeout: float) -> dict[str, Any]:
        client = self._client
        if client is None:
            raise MCPError(f"MCP server `{self.config.name}` is not running")

        request_id = self._next_id
        self._next_id += 1
        payload = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params,
        }
        url = self.config.url.strip()
        if not url:
            raise MCPError(f"MCP server `{self.config.name}` has no url configured")

        try:
            response = await client.post(url, json=payload, headers=self._http_headers(), timeout=timeout)
        except Exception as exc:
            raise MCPError(f"MCP HTTP request failed ({method}): {exc}") from exc

        session_id = response.headers.get("mcp-session-id")
        if session_id:
            self._http_session_id = session_id

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            body = exc.response.text.strip()
            if body:
                body = body[:400]
            raise MCPError(f"MCP HTTP {exc.response.status_code} for `{method}`: {body or exc}") from exc

        if not response.content:
            self.last_seen_at = datetime.now(UTC)
            self.last_error = None
            return {}

        content_type = response.headers.get("content-type", "").lower()
        try:
            if "text/event-stream" in content_type:
                payload_json = self._parse_sse_response(response.text)
            else:
                payload_json = response.json()
        except Exception as exc:
            text = response.text.strip()
            raise MCPError(
                f"MCP server `{self.config.name}` returned unsupported response for `{method}`: {text[:200]}"
            ) from exc

        if isinstance(payload_json, list):
            matched: dict[str, Any] | None = None
            for item in payload_json:
                if isinstance(item, dict) and item.get("id") == request_id:
                    matched = item
                    break
            if matched is None:
                raise MCPError(f"MCP server `{self.config.name}` returned unexpected batch response for `{method}`")
            payload_json = matched

        if not isinstance(payload_json, dict):
            raise MCPError(f"MCP server `{self.config.name}` returned invalid response type for `{method}`")

        if "error" in payload_json:
            error_obj = payload_json.get("error")
            if isinstance(error_obj, dict):
                message = str(error_obj.get("message") or json.dumps(error_obj, ensure_ascii=False))
            else:
                message = str(error_obj)
            self.last_error = message
            raise MCPError(message)

        result = payload_json.get("result")
        self.last_seen_at = datetime.now(UTC)
        self.last_error = None
        if isinstance(result, dict):
            return result
        if result is None:
            return {}
        return {"value": result}

    async def _notify_http(self, *, method: str, params: dict[str, Any]) -> None:
        client = self._client
        if client is None:
            raise MCPError(f"MCP server `{self.config.name}` is not running")
        url = self.config.url.strip()
        if not url:
            raise MCPError(f"MCP server `{self.config.name}` has no url configured")
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        }
        timeout = max(1.0, float(self.config.request_timeout_seconds))
        try:
            response = await client.post(url, json=payload, headers=self._http_headers(), timeout=timeout)
        except Exception as exc:
            raise MCPError(f"MCP HTTP notification failed ({method}): {exc}") from exc

        session_id = response.headers.get("mcp-session-id")
        if session_id:
            self._http_session_id = session_id

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            body = exc.response.text.strip()
            if body:
                body = body[:400]
            raise MCPError(f"MCP HTTP {exc.response.status_code} for notify `{method}`: {body or exc}") from exc


class MCPRegistry:
    def __init__(self) -> None:
        self._sessions: dict[str, _MCPServerSession] = {}
        self._lock = asyncio.Lock()

    async def sync(self) -> None:
        async with self._lock:
            active_configs = self._enabled_configs()
            active_names = set(active_configs.keys())

            for name in list(self._sessions.keys()):
                if name not in active_names:
                    session = self._sessions.pop(name)
                    await session.close()

            for name, config in active_configs.items():
                existing = self._sessions.get(name)
                if existing is None:
                    self._sessions[name] = _MCPServerSession(config)
                    continue
                if not existing.is_same_config(config):
                    await existing.close()
                    self._sessions[name] = _MCPServerSession(config)

    async def shutdown(self) -> None:
        async with self._lock:
            for session in list(self._sessions.values()):
                await session.close()
            self._sessions.clear()

    async def list_servers(self) -> list[dict[str, Any]]:
        await self.sync()
        configured = self._all_configs_by_name()
        items: list[dict[str, Any]] = []
        for name, config in configured.items():
            session = self._sessions.get(name)
            running = bool(session and session.is_running)
            item = {
                "name": config.name,
                "enabled": bool(config.enabled),
                "transport": config.transport,
                "command": config.command,
                "args": list(config.args),
                "url": config.url,
                "cwd": config.cwd,
                "running": running,
                "last_error": session.last_error if session else None,
                "last_seen_at": session.last_seen_at.isoformat() if session and session.last_seen_at else None,
            }
            items.append(item)
        items.sort(key=lambda row: str(row.get("name") or "").lower())
        return items

    async def list_tools(self, server_name: str | None = None) -> dict[str, Any]:
        await self.sync()
        target = (server_name or "").strip().lower()

        sessions: list[_MCPServerSession] = []
        if target:
            session = self._sessions.get(target)
            if session is None:
                raise MCPError(f"MCP server not found or disabled: {server_name}")
            sessions = [session]
        else:
            sessions = list(self._sessions.values())

        tools: list[dict[str, Any]] = []
        errors: list[dict[str, str]] = []
        for session in sessions:
            try:
                for item in await session.list_tools():
                    tools.append(item.to_dict())
            except Exception as exc:
                message = str(exc)
                session.last_error = message
                errors.append({"server": session.config.name, "error": message})
        return {
            "tools": tools,
            "errors": errors,
            "server_count": len(sessions),
        }

    async def call_tool(self, *, server_name: str, tool_name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        await self.sync()
        target = server_name.strip().lower()
        if not target:
            raise MCPError("server_name is required")
        session = self._sessions.get(target)
        if session is None:
            raise MCPError(f"MCP server not found or disabled: {server_name}")
        result = await session.call_tool(tool_name.strip(), arguments or {})
        return result

    def _enabled_configs(self) -> dict[str, MCPServerConfig]:
        out: dict[str, MCPServerConfig] = {}
        for config in getattr(settings, "mcp_servers", []) or []:
            if not config.enabled:
                continue
            key = config.name.strip().lower()
            if not key:
                continue
            if key in out:
                _logger.warning("Duplicate MCP server name in config: %s", config.name)
                continue
            out[key] = config
        return out

    def _all_configs_by_name(self) -> dict[str, MCPServerConfig]:
        out: dict[str, MCPServerConfig] = {}
        for config in getattr(settings, "mcp_servers", []) or []:
            key = config.name.strip().lower()
            if not key:
                continue
            if key in out:
                continue
            out[key] = config
        return out


mcp_registry = MCPRegistry()


def extract_mcp_text(result: dict[str, Any]) -> str:
    """Extract user-facing text from MCP tool result payload."""
    content = result.get("content")
    chunks: list[str] = []
    if isinstance(content, list):
        for item in content:
            if not isinstance(item, dict):
                continue
            item_type = str(item.get("type") or "").strip().lower()
            if item_type == "text":
                text = str(item.get("text") or "").strip()
                if text:
                    chunks.append(text)
                continue
            if item_type == "image":
                mime_type = str(item.get("mimeType") or "image/*")
                chunks.append(f"[MCP image content: {mime_type}]")
                continue
            if item_type == "resource":
                uri = str(item.get("uri") or "").strip()
                if uri:
                    chunks.append(f"[MCP resource: {uri}]")
                continue

    if chunks:
        return "\n".join(chunks).strip()

    structured = {
        "isError": bool(result.get("isError")),
        "content": content,
        "structuredContent": result.get("structuredContent"),
    }
    return json.dumps(structured, ensure_ascii=False)
