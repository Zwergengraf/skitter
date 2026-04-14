from __future__ import annotations

import argparse
import asyncio
import ctypes
import ctypes.util
import json
import logging
import os
import platform
import shutil
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


logger = logging.getLogger("skitter.node")

_application_services_permissions: Any | None = None
_core_graphics_permissions: Any | None = None


DEFAULT_NODE_TOOLS: tuple[str, ...] = (
    "read",
    "write",
    "edit",
    "apply_patch",
    "list",
    "delete",
    "download",
    "http_fetch",
    "shell",
    "browser",
    "browser_action",
)

DEVICE_CAPABILITY_TOOL_KEYS: dict[str, str] = {
    "notify": "notify",
    "screenshot": "screenshot",
    "mouse_move": "mouse",
    "mouse_click": "mouse",
    "keyboard_type": "keyboard",
    "keyboard_press": "keyboard",
}


def _http_error_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        payload = None
    if isinstance(payload, dict):
        detail = payload.get("detail")
        if isinstance(detail, str) and detail.strip():
            return detail.strip()
        if detail is not None:
            return json.dumps(detail, ensure_ascii=False)
    text = (response.text or "").strip()
    if text:
        return text
    return f"HTTP {response.status_code}"


@dataclass(slots=True)
class NodeConfig:
    api_url: str
    token: str
    name: str
    workspace_root: str
    enabled_tools: tuple[str, ...] = DEFAULT_NODE_TOOLS
    notify_enabled: bool = True
    screenshot_enabled: bool = False
    mouse_enabled: bool = False
    keyboard_enabled: bool = False
    heartbeat_seconds: int = 10
    reconnect_seconds: int = 3
    request_timeout_seconds: int = 600


def _default_config_path() -> Path:
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / "skitter-node" / "config.yaml"
        return Path.home() / "AppData" / "Roaming" / "skitter-node" / "config.yaml"
    home = Path.home()
    return home / ".config" / "skitter-node" / "config.yaml"


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


def _normalize_tools(raw: Any) -> tuple[str, ...]:
    if raw is None:
        return DEFAULT_NODE_TOOLS
    items: list[str] = []
    if isinstance(raw, str):
        items = [part.strip().lower() for part in raw.split(",")]
    elif isinstance(raw, list):
        items = [str(part).strip().lower() for part in raw]
    allowed: list[str] = []
    seen: set[str] = set()
    known = set(DEFAULT_NODE_TOOLS)
    for item in items:
        if not item or item in seen or item not in known:
            continue
        seen.add(item)
        allowed.append(item)
    if not allowed:
        return DEFAULT_NODE_TOOLS
    return tuple(allowed)


def _coerce_bool(value: Any, *, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if not text:
        return default
    if text in {"1", "true", "yes", "on", "enabled"}:
        return True
    if text in {"0", "false", "no", "off", "disabled"}:
        return False
    return default


def _enabled_device_capabilities(config: NodeConfig) -> dict[str, bool]:
    return {
        "notify": bool(config.notify_enabled),
        "screenshot": bool(config.screenshot_enabled),
        "mouse": bool(config.mouse_enabled),
        "keyboard": bool(config.keyboard_enabled),
    }


def _permission_info(label: str, status: str, detail: str | None = None) -> dict[str, str]:
    payload = {"label": label, "status": status}
    if detail:
        payload["detail"] = detail
    return payload


def _load_application_services_permissions() -> Any | None:
    global _application_services_permissions
    if _application_services_permissions is not None:
        return _application_services_permissions
    library_path = ctypes.util.find_library("ApplicationServices")
    if not library_path:
        return None
    try:
        lib = ctypes.cdll.LoadLibrary(library_path)
    except OSError:
        return None
    checker = getattr(lib, "AXIsProcessTrusted", None)
    if checker is not None:
        checker.restype = ctypes.c_bool
        checker.argtypes = []
    _application_services_permissions = lib
    return lib


def _load_core_graphics_permissions() -> Any | None:
    global _core_graphics_permissions
    if _core_graphics_permissions is not None:
        return _core_graphics_permissions
    library_path = ctypes.util.find_library("CoreGraphics") or ctypes.util.find_library("ApplicationServices")
    if not library_path:
        return None
    try:
        lib = ctypes.cdll.LoadLibrary(library_path)
    except OSError:
        return None
    checker = getattr(lib, "CGPreflightScreenCaptureAccess", None)
    if checker is not None:
        checker.restype = ctypes.c_bool
        checker.argtypes = []
    _core_graphics_permissions = lib
    return lib


def _accessibility_permission_status() -> dict[str, str]:
    if sys.platform != "darwin":
        return _permission_info(
            "Accessibility",
            "unsupported",
            "Accessibility permission reporting is only available on macOS nodes.",
        )
    lib = _load_application_services_permissions()
    if lib is None:
        return _permission_info(
            "Accessibility",
            "unsupported",
            "ApplicationServices is not available on this executor.",
        )
    checker = getattr(lib, "AXIsProcessTrusted", None)
    if checker is None:
        return _permission_info(
            "Accessibility",
            "unknown",
            "This macOS version does not expose accessibility trust checks to the node process.",
        )
    try:
        trusted = bool(checker())
    except Exception as exc:
        return _permission_info("Accessibility", "unknown", f"Could not check accessibility permission: {exc}")
    if trusted:
        return _permission_info("Accessibility", "granted", "Accessibility permission is granted.")
    return _permission_info(
        "Accessibility",
        "missing",
        "Enable it in System Settings > Privacy & Security > Accessibility.",
    )


def _screen_recording_permission_status() -> dict[str, str]:
    if sys.platform == "darwin":
        lib = _load_core_graphics_permissions()
        if lib is None:
            return _permission_info(
                "Screen Recording",
                "unsupported",
                "CoreGraphics is not available on this executor.",
            )
        checker = getattr(lib, "CGPreflightScreenCaptureAccess", None)
        if checker is None:
            return _permission_info(
                "Screen Recording",
                "unknown",
                "This macOS version does not expose screen recording permission checks to the node process.",
            )
        try:
            allowed = bool(checker())
        except Exception as exc:
            return _permission_info("Screen Recording", "unknown", f"Could not check screen recording permission: {exc}")
        if allowed:
            return _permission_info("Screen Recording", "granted", "Screen Recording permission is granted.")
        return _permission_info(
            "Screen Recording",
            "missing",
            "Enable it in System Settings > Privacy & Security > Screen Recording.",
        )
    return _permission_info(
        "Screen Recording",
        "not_required",
        "No separate screen recording permission is required on this platform.",
    )


def _windows_desktop_interaction_permission_status() -> dict[str, str]:
    return _permission_info(
        "Desktop Interaction",
        "not_required",
        (
            "No separate Windows permission is required. The node must run in an interactive user session, "
            "and it can only control elevated windows when the node is also elevated."
        ),
    )


def _powershell_command() -> str | None:
    return shutil.which("pwsh") or shutil.which("powershell.exe") or shutil.which("powershell")


def _supports_notify() -> bool:
    if sys.platform == "win32":
        return _powershell_command() is not None
    if sys.platform == "darwin":
        return shutil.which("osascript") is not None
    return shutil.which("notify-send") is not None


def _supports_screenshot() -> bool:
    if sys.platform == "win32":
        try:
            from PIL import ImageGrab as _image_grab  # noqa: F401
        except ImportError:
            return False
        return True
    if sys.platform == "darwin":
        return shutil.which("screencapture") is not None
    return any(shutil.which(command) for command in ("gnome-screenshot", "grim", "scrot"))


def _supports_mouse_keyboard() -> bool:
    if sys.platform == "win32":
        return bool(getattr(ctypes, "windll", None) and getattr(ctypes.windll, "user32", None))
    if sys.platform != "darwin":
        return False
    return _load_application_services_permissions() is not None


def _permission_key_for(feature: str) -> str | None:
    if sys.platform == "darwin":
        if feature == "screenshot":
            return "screen_recording"
        if feature in {"mouse", "keyboard"}:
            return "accessibility"
    if sys.platform == "win32" and feature in {"screenshot", "mouse", "keyboard"}:
        return "desktop_interaction"
    return None


def _device_feature_state(
    *,
    enabled: bool,
    supported: bool,
    unsupported_detail: str,
    permission_key: str | None = None,
    permission_status: dict[str, dict[str, str]] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "enabled": enabled,
        "supported": supported,
        "ready": False,
        "state": "disabled" if not enabled else "unsupported" if not supported else "ready",
    }
    if not enabled:
        payload["detail"] = "Disabled in this node config."
        return payload
    if not supported:
        payload["detail"] = unsupported_detail
        return payload
    if permission_key:
        permission = (permission_status or {}).get(permission_key) or {}
        permission_state = str(permission.get("status") or "unknown")
        payload["permission"] = permission_key
        payload["permission_status"] = permission_state
        if permission_state in {"granted", "not_required"}:
            payload["ready"] = True
            payload["state"] = "ready"
        elif permission_state == "missing":
            payload["state"] = "needs_permission"
            detail = str(permission.get("detail") or "").strip()
            if detail:
                payload["detail"] = detail
        elif permission_state == "unsupported":
            payload["state"] = "unsupported"
            payload["detail"] = str(permission.get("detail") or unsupported_detail)
        else:
            payload["state"] = "unknown"
            detail = str(permission.get("detail") or "").strip()
            if detail:
                payload["detail"] = detail
        return payload
    payload["ready"] = True
    payload["state"] = "ready"
    return payload


def _host_permissions() -> dict[str, dict[str, str]]:
    permissions = {
        "accessibility": _accessibility_permission_status(),
        "screen_recording": _screen_recording_permission_status(),
    }
    if sys.platform == "win32":
        permissions["desktop_interaction"] = _windows_desktop_interaction_permission_status()
    return permissions


def _device_feature_statuses(
    config: NodeConfig,
    *,
    permissions: dict[str, dict[str, str]] | None = None,
) -> dict[str, dict[str, Any]]:
    resolved_permissions = permissions or _host_permissions()
    return {
        "notify": _device_feature_state(
            enabled=bool(config.notify_enabled),
            supported=_supports_notify(),
            unsupported_detail="Host notifications are not supported on this executor.",
        ),
        "screenshot": _device_feature_state(
            enabled=bool(config.screenshot_enabled),
            supported=_supports_screenshot(),
            unsupported_detail="Host screenshots are not supported on this executor.",
            permission_key=_permission_key_for("screenshot"),
            permission_status=resolved_permissions,
        ),
        "mouse": _device_feature_state(
            enabled=bool(config.mouse_enabled),
            supported=_supports_mouse_keyboard(),
            unsupported_detail="Host mouse control is currently supported on macOS and Windows nodes only.",
            permission_key=_permission_key_for("mouse"),
            permission_status=resolved_permissions,
        ),
        "keyboard": _device_feature_state(
            enabled=bool(config.keyboard_enabled),
            supported=_supports_mouse_keyboard(),
            unsupported_detail="Host keyboard control is currently supported on macOS and Windows nodes only.",
            permission_key=_permission_key_for("keyboard"),
            permission_status=resolved_permissions,
        ),
    }


def _capabilities_payload(config: NodeConfig) -> dict[str, Any]:
    permissions = _host_permissions()
    return {
        "tools": list(config.enabled_tools),
        **_enabled_device_capabilities(config),
        "workspace_root": config.workspace_root,
        "permissions": permissions,
        "device_features": _device_feature_statuses(config, permissions=permissions),
    }


def _node_platform() -> str:
    if sys.platform == "win32":
        return "windows"
    if sys.platform == "darwin":
        return "darwin"
    if sys.platform.startswith("linux"):
        return "linux"
    return platform.system().lower() or sys.platform


def _tool_enabled(config: NodeConfig, tool: str) -> tuple[bool, str | None]:
    normalized = str(tool or "").strip().lower()
    if normalized in set(config.enabled_tools):
        return True, None
    capability_key = DEVICE_CAPABILITY_TOOL_KEYS.get(normalized)
    if capability_key is None:
        return False, "Update node config capabilities.tools to allow it."
    enabled = _enabled_device_capabilities(config).get(capability_key, False)
    if enabled:
        return True, None
    return False, f"Update node config capabilities.{capability_key} to true to allow it."


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
    request_timeout_seconds = int(args.request_timeout_seconds or file_data.get("request_timeout_seconds") or 600)
    raw_file_tools = None
    capabilities_raw = file_data.get("capabilities")
    if isinstance(capabilities_raw, dict):
        raw_file_tools = capabilities_raw.get("tools")
    file_tools = raw_file_tools if raw_file_tools is not None else file_data.get("tools")
    raw_tools = _coalesce(args.tools, os.environ.get("SKITTER_NODE_TOOLS"))
    enabled_tools = _normalize_tools(raw_tools if raw_tools else file_tools)
    notify_enabled = _coerce_bool(
        args.enable_notify,
        default=_coerce_bool(
            os.environ.get("SKITTER_NODE_ENABLE_NOTIFY"),
            default=_coerce_bool(
                capabilities_raw.get("notify") if isinstance(capabilities_raw, dict) else None,
                default=True,
            ),
        ),
    )
    screenshot_enabled = _coerce_bool(
        args.enable_screenshot,
        default=_coerce_bool(
            os.environ.get("SKITTER_NODE_ENABLE_SCREENSHOT"),
            default=_coerce_bool(capabilities_raw.get("screenshot") if isinstance(capabilities_raw, dict) else None),
        ),
    )
    mouse_enabled = _coerce_bool(
        args.enable_mouse,
        default=_coerce_bool(
            os.environ.get("SKITTER_NODE_ENABLE_MOUSE"),
            default=_coerce_bool(capabilities_raw.get("mouse") if isinstance(capabilities_raw, dict) else None),
        ),
    )
    keyboard_enabled = _coerce_bool(
        args.enable_keyboard,
        default=_coerce_bool(
            os.environ.get("SKITTER_NODE_ENABLE_KEYBOARD"),
            default=_coerce_bool(capabilities_raw.get("keyboard") if isinstance(capabilities_raw, dict) else None),
        ),
    )
    cfg = NodeConfig(
        api_url=api_url.rstrip("/"),
        token=token,
        name=name,
        workspace_root=workspace_root,
        enabled_tools=enabled_tools,
        notify_enabled=notify_enabled,
        screenshot_enabled=screenshot_enabled,
        mouse_enabled=mouse_enabled,
        keyboard_enabled=keyboard_enabled,
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
                "capabilities": {
                    "tools": list(cfg.enabled_tools),
                    **_enabled_device_capabilities(cfg),
                },
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
                    except asyncio.CancelledError:
                        pass
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
                "platform": _node_platform(),
                "hostname": socket.gethostname(),
                "capabilities": _capabilities_payload(self._config),
            }
            await self._send_json(websocket, payload)
            await asyncio.sleep(self._config.heartbeat_seconds)

    async def _handle_execute(self, websocket, message: dict[str, Any]) -> None:
        request_id = str(message.get("request_id") or "").strip()
        try:
            tool = str(message.get("tool") or "").strip()
            enabled, hint = _tool_enabled(self._config, tool)
            if not enabled:
                raise RuntimeError(
                    f"Tool '{tool}' is not enabled on this executor. "
                    f"{hint or 'Update node config capabilities to allow it.'}"
                )
            session_id = str(message.get("session_id") or "").strip() or "default"
            payload = message.get("payload") if isinstance(message.get("payload"), dict) else {}
            timeout_s = float(message.get("timeout_s") or self._config.request_timeout_seconds)
            response = await self._http_client.post(
                "/execute",
                json={
                    "session_id": session_id,
                    "tool": tool,
                    "payload": payload,
                    "timeout_s": timeout_s,
                },
                timeout=max(1.0, timeout_s + min(5.0, max(0.1, timeout_s * 0.05))),
            )
            if response.status_code >= 400:
                detail = _http_error_detail(response)
                raise RuntimeError(
                    f"Executor runner error ({response.status_code}): {detail}"
                )
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
    parser = argparse.ArgumentParser(description="Skitter host executor node")
    parser.add_argument("--config", default="", help="Path to config YAML")
    parser.add_argument("--api-url", default="", help="API server base URL")
    parser.add_argument("--token", default="", help="Executor token")
    parser.add_argument("--name", default="", help="Executor display name")
    parser.add_argument("--workspace-root", default="", help="Workspace root for relative paths")
    parser.add_argument("--heartbeat-seconds", type=int, default=0, help="Heartbeat interval seconds")
    parser.add_argument("--reconnect-seconds", type=int, default=0, help="Reconnect delay seconds")
    parser.add_argument("--request-timeout-seconds", type=int, default=0, help="Per-execute timeout")
    parser.add_argument(
        "--tools",
        default="",
        help="Comma-separated enabled tools override (e.g. read,write,shell).",
    )
    parser.add_argument("--enable-notify", default="", help="Enable host notifications (true/false).")
    parser.add_argument("--enable-screenshot", default="", help="Enable host screenshots (true/false).")
    parser.add_argument("--enable-mouse", default="", help="Enable host mouse control (true/false).")
    parser.add_argument("--enable-keyboard", default="", help="Enable host keyboard control (true/false).")
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
