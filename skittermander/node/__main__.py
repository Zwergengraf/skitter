from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import platform
import socket
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse

import httpx
import websockets
import yaml

from ..sandbox.runner import create_app


logger = logging.getLogger("skittermander.node")


@dataclass(slots=True)
class NodeConfig:
    api_url: str
    token: str
    name: str
    workspace_root: str
    heartbeat_seconds: int = 10
    reconnect_seconds: int = 3
    request_timeout_seconds: int = 300


def _default_config_path() -> Path:
    home = Path.home()
    if sys.platform == "darwin":
        return home / "Library" / "Application Support" / "SkitterNode" / "config.yaml"
    return home / ".config" / "skitternode" / "config.yaml"


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError:
        return {}
    if not isinstance(data, dict):
        return {}
    return data


def _save_yaml(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def _coalesce(*values: str | None) -> str:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _resolve_config(args: argparse.Namespace) -> tuple[NodeConfig, Path]:
    config_path = Path(args.config).expanduser() if args.config else _default_config_path()
    file_data = _load_yaml(config_path)

    api_url = _coalesce(args.api_url, os.environ.get("SKITTER_NODE_API_URL"), file_data.get("api_url"))
    token = _coalesce(args.token, os.environ.get("SKITTER_NODE_TOKEN"), file_data.get("token"))
    name = _coalesce(args.name, os.environ.get("SKITTER_NODE_NAME"), file_data.get("name"), socket.gethostname())
    workspace_root = _coalesce(
        args.workspace_root,
        os.environ.get("SKITTER_NODE_WORKSPACE_ROOT"),
        file_data.get("workspace_root"),
        "workspace",
    )

    if not api_url:
        raise SystemExit("Missing required config: api_url")
    if not token:
        raise SystemExit("Missing required config: token")

    heartbeat_seconds = int(args.heartbeat_seconds or file_data.get("heartbeat_seconds") or 10)
    reconnect_seconds = int(args.reconnect_seconds or file_data.get("reconnect_seconds") or 3)
    request_timeout_seconds = int(args.request_timeout_seconds or file_data.get("request_timeout_seconds") or 300)
    cfg = NodeConfig(
        api_url=api_url.rstrip("/"),
        token=token,
        name=name,
        workspace_root=workspace_root,
        heartbeat_seconds=max(2, heartbeat_seconds),
        reconnect_seconds=max(1, reconnect_seconds),
        request_timeout_seconds=max(10, request_timeout_seconds),
    )
    if args.write_config:
        _save_yaml(
            config_path,
            {
                "api_url": cfg.api_url,
                "token": cfg.token,
                "name": cfg.name,
                "workspace_root": cfg.workspace_root,
                "heartbeat_seconds": cfg.heartbeat_seconds,
                "reconnect_seconds": cfg.reconnect_seconds,
                "request_timeout_seconds": cfg.request_timeout_seconds,
            },
        )
    return cfg, config_path


def _ws_url(api_url: str) -> str:
    parsed = urlparse(api_url)
    scheme = "wss" if parsed.scheme == "https" else "ws"
    path = parsed.path.rstrip("/")
    ws_path = f"{path}/v1/executors/connect" if path else "/v1/executors/connect"
    return urlunparse((scheme, parsed.netloc, ws_path, "", "", ""))


class NodeClient:
    def __init__(self, config: NodeConfig) -> None:
        self._config = config
        self._app = create_app()
        self._http_client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self._app),
            base_url="http://executor.local",
            timeout=float(config.request_timeout_seconds),
        )
        self._send_lock = asyncio.Lock()
        self._pending: dict[str, asyncio.Task] = {}

    async def close(self) -> None:
        for task in list(self._pending.values()):
            task.cancel()
        self._pending.clear()
        await self._http_client.aclose()

    async def run_forever(self) -> None:
        ws_url = _ws_url(self._config.api_url)
        headers = {"Authorization": f"Bearer {self._config.token}"}
        while True:
            heartbeat_task: asyncio.Task | None = None
            try:
                logger.info("Connecting node to %s as '%s'", ws_url, self._config.name)
                connect_kwargs = dict(
                    open_timeout=20,
                    ping_interval=20,
                    ping_timeout=20,
                    close_timeout=10,
                    max_size=20 * 1024 * 1024,
                )
                try:
                    ws_cm = websockets.connect(ws_url, additional_headers=headers, **connect_kwargs)
                except TypeError:
                    ws_cm = websockets.connect(ws_url, extra_headers=headers, **connect_kwargs)
                async with ws_cm as websocket:
                    logger.info("Executor node connected")
                    heartbeat_task = asyncio.create_task(self._heartbeat_loop(websocket))
                    await self._recv_loop(websocket)
            except Exception as exc:
                logger.warning("Executor node connection dropped: %s", exc)
            finally:
                if heartbeat_task is not None:
                    heartbeat_task.cancel()
                    try:
                        await heartbeat_task
                    except Exception:
                        pass
                await self._cancel_all_pending()
            await asyncio.sleep(self._config.reconnect_seconds)

    async def _cancel_all_pending(self) -> None:
        for task in list(self._pending.values()):
            task.cancel()
        self._pending.clear()

    async def _recv_loop(self, websocket) -> None:
        async for raw in websocket:
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8", errors="replace")
            try:
                message = json.loads(raw)
            except json.JSONDecodeError:
                continue
            msg_type = str(message.get("type") or "").strip().lower()
            if msg_type == "execute":
                request_id = str(message.get("request_id") or "").strip()
                if not request_id:
                    continue
                task = asyncio.create_task(self._handle_execute(websocket, message))
                self._pending[request_id] = task
            elif msg_type == "cancel":
                await self._handle_cancel(websocket, message)

    async def _heartbeat_loop(self, websocket) -> None:
        while True:
            payload = {
                "type": "heartbeat",
                "name": self._config.name,
                "platform": platform.system().lower(),
                "hostname": socket.gethostname(),
                "capabilities": {
                    "tools": [
                        "read",
                        "write",
                        "edit",
                        "list",
                        "delete",
                        "download",
                        "http_fetch",
                        "shell",
                        "browser",
                        "browser_action",
                    ],
                    "workspace_root": self._config.workspace_root,
                },
            }
            await self._send_json(websocket, payload)
            await asyncio.sleep(self._config.heartbeat_seconds)

    async def _handle_execute(self, websocket, message: dict[str, Any]) -> None:
        request_id = str(message.get("request_id") or "").strip()
        try:
            tool = str(message.get("tool") or "").strip()
            session_id = str(message.get("session_id") or "").strip() or "default"
            payload = message.get("payload") if isinstance(message.get("payload"), dict) else {}
            timeout_s = float(message.get("timeout_s") or self._config.request_timeout_seconds)
            response = await self._http_client.post(
                "/execute",
                json={
                    "session_id": session_id,
                    "tool": tool,
                    "payload": payload,
                },
                timeout=max(1.0, timeout_s),
            )
            response.raise_for_status()
            body = response.json()
            await self._send_json(
                websocket,
                {"type": "result", "request_id": request_id, "ok": True, "payload": body},
            )
        except asyncio.CancelledError:
            await self._send_json(
                websocket,
                {"type": "result", "request_id": request_id, "ok": False, "error": "cancelled"},
            )
            raise
        except Exception as exc:
            await self._send_json(
                websocket,
                {"type": "result", "request_id": request_id, "ok": False, "error": str(exc)},
            )
        finally:
            self._pending.pop(request_id, None)

    async def _handle_cancel(self, websocket, message: dict[str, Any]) -> None:
        request_id = str(message.get("request_id") or "").strip()
        if not request_id:
            return
        task = self._pending.get(request_id)
        if task is None:
            await self._send_json(
                websocket,
                {"type": "result", "request_id": request_id, "ok": False, "error": "not_found"},
            )
            return
        task.cancel()

    async def _send_json(self, websocket, payload: dict[str, Any]) -> None:
        async with self._send_lock:
            await websocket.send(json.dumps(payload))


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Skittermander host executor node")
    parser.add_argument("--config", default="", help="Path to config YAML")
    parser.add_argument("--api-url", default="", help="API server base URL")
    parser.add_argument("--token", default="", help="Executor token")
    parser.add_argument("--name", default="", help="Executor display name")
    parser.add_argument("--workspace-root", default="", help="Workspace root for relative paths")
    parser.add_argument("--heartbeat-seconds", type=int, default=0, help="Heartbeat interval seconds")
    parser.add_argument("--reconnect-seconds", type=int, default=0, help="Reconnect delay seconds")
    parser.add_argument("--request-timeout-seconds", type=int, default=0, help="Per-execute timeout")
    parser.add_argument("--write-config", action="store_true", help="Persist resolved config to config file")
    return parser


def main() -> None:
    parser = _build_arg_parser()
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    config, config_path = _resolve_config(args)
    os.environ.setdefault("SKITTER_WORKSPACE_ROOT", config.workspace_root)
    os.environ.setdefault(
        "SKITTER_BROWSER_DATA_ROOT",
        str(Path(config.workspace_root).expanduser() / ".browser-data"),
    )
    logger.info("Using config path: %s", config_path)
    client = NodeClient(config)

    async def _runner() -> None:
        try:
            await client.run_forever()
        finally:
            await client.close()

    asyncio.run(_runner())


if __name__ == "__main__":
    main()
