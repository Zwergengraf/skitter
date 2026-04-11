from __future__ import annotations

from pathlib import Path

import yaml
import skitter.node.__main__ as node_main

from skitter.node.__main__ import (
    DEVICE_CAPABILITY_TOOL_KEYS,
    DEFAULT_NODE_TOOLS,
    NodeConfig,
    _capabilities_payload,
    _build_arg_parser,
    _default_config_path,
    _host_permissions,
    _normalize_tools,
    _node_platform,
    _resolve_config,
    _tool_enabled,
)


def test_normalize_tools_filters_unknown_and_dedupes() -> None:
    tools = _normalize_tools(["read", "apply_patch", "read", "unknown"])
    assert tools == ("read", "apply_patch")


def test_normalize_tools_fallbacks_to_default_when_empty() -> None:
    assert _normalize_tools([]) == DEFAULT_NODE_TOOLS
    assert _normalize_tools(",,,") == DEFAULT_NODE_TOOLS


def test_default_node_tools_matches_runner_surface() -> None:
    assert "apply_patch" in DEFAULT_NODE_TOOLS


def test_default_config_path_uses_appdata_on_windows(monkeypatch, tmp_path: Path) -> None:
    appdata = tmp_path / "AppData" / "Roaming"
    monkeypatch.setattr(node_main.sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", str(appdata))

    assert _default_config_path() == appdata / "skitter-node" / "config.yaml"


def test_default_config_path_uses_xdg_style_path_off_windows(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(node_main.sys, "platform", "linux")
    monkeypatch.setattr(node_main.Path, "home", lambda: tmp_path)

    assert _default_config_path() == tmp_path / ".config" / "skitter-node" / "config.yaml"


def test_node_platform_normalizes_windows(monkeypatch) -> None:
    monkeypatch.setattr(node_main.sys, "platform", "win32")

    assert _node_platform() == "windows"


def test_device_capability_tools_are_separate_from_default_allowlist() -> None:
    for tool_name in DEVICE_CAPABILITY_TOOL_KEYS:
        assert tool_name not in DEFAULT_NODE_TOOLS


def test_resolve_config_reads_capabilities_tools(tmp_path: Path) -> None:
    config_path = tmp_path / "node-config.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "api_url": "http://localhost:8000",
                "token": "token-1",
                "name": "node-1",
                "workspace_root": str(tmp_path / "workspace"),
                "capabilities": {"tools": ["read", "shell"]},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    parser = _build_arg_parser()
    args = parser.parse_args(["--config", str(config_path)])

    cfg, _ = _resolve_config(args)

    assert cfg.api_url == "http://localhost:8000"
    assert cfg.enabled_tools == ("read", "shell")
    assert cfg.notify_enabled is True


def test_resolve_config_reads_device_capabilities(tmp_path: Path) -> None:
    config_path = tmp_path / "node-config.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "api_url": "http://localhost:8000",
                "token": "token-1",
                "name": "node-1",
                "workspace_root": str(tmp_path / "workspace"),
                "capabilities": {
                    "tools": ["read", "shell"],
                    "notify": True,
                    "screenshot": True,
                    "mouse": False,
                    "keyboard": True,
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    parser = _build_arg_parser()
    args = parser.parse_args(["--config", str(config_path)])

    cfg, _ = _resolve_config(args)

    assert cfg.notify_enabled is True
    assert cfg.screenshot_enabled is True
    assert cfg.mouse_enabled is False
    assert cfg.keyboard_enabled is True


def test_tool_enabled_accepts_enabled_device_tools(tmp_path: Path) -> None:
    config_path = tmp_path / "node-config.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "api_url": "http://localhost:8000",
                "token": "token-1",
                "name": "node-1",
                "workspace_root": str(tmp_path / "workspace"),
                "capabilities": {
                    "tools": ["read"],
                    "notify": True,
                    "screenshot": False,
                    "mouse": True,
                    "keyboard": True,
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    parser = _build_arg_parser()
    args = parser.parse_args(["--config", str(config_path)])
    cfg, _ = _resolve_config(args)

    assert _tool_enabled(cfg, "notify") == (True, None)
    assert _tool_enabled(cfg, "mouse_click") == (True, None)
    assert _tool_enabled(cfg, "keyboard_press") == (True, None)
    enabled, hint = _tool_enabled(cfg, "screenshot")
    assert enabled is False
    assert hint == "Update node config capabilities.screenshot to true to allow it."


def test_notify_is_enabled_by_default_when_capability_is_omitted(tmp_path: Path) -> None:
    config_path = tmp_path / "node-config.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "api_url": "http://localhost:8000",
                "token": "token-1",
                "name": "node-1",
                "workspace_root": str(tmp_path / "workspace"),
                "capabilities": {
                    "tools": ["read"],
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    parser = _build_arg_parser()
    args = parser.parse_args(["--config", str(config_path)])

    cfg, _ = _resolve_config(args)

    assert cfg.notify_enabled is True
    assert cfg.screenshot_enabled is False
    assert cfg.mouse_enabled is False
    assert cfg.keyboard_enabled is False


def test_capabilities_payload_reports_device_feature_states(monkeypatch) -> None:
    cfg = NodeConfig(
        api_url="http://localhost:8000",
        token="token-1",
        name="node-1",
        workspace_root="workspace",
        notify_enabled=True,
        screenshot_enabled=True,
        mouse_enabled=True,
        keyboard_enabled=False,
    )

    monkeypatch.setattr(node_main.sys, "platform", "darwin")
    monkeypatch.setattr(node_main, "_supports_notify", lambda: True)
    monkeypatch.setattr(node_main, "_supports_screenshot", lambda: True)
    monkeypatch.setattr(node_main, "_supports_mouse_keyboard", lambda: True)
    monkeypatch.setattr(
        node_main,
        "_host_permissions",
        lambda: {
            "accessibility": {"label": "Accessibility", "status": "missing", "detail": "Enable Accessibility."},
            "screen_recording": {"label": "Screen Recording", "status": "granted"},
        },
    )

    payload = _capabilities_payload(cfg)

    assert payload["notify"] is True
    assert payload["screenshot"] is True
    assert payload["mouse"] is True
    assert payload["keyboard"] is False
    assert payload["permissions"]["accessibility"]["status"] == "missing"
    assert payload["device_features"]["notify"]["state"] == "ready"
    assert payload["device_features"]["screenshot"]["state"] == "ready"
    assert payload["device_features"]["mouse"]["state"] == "needs_permission"
    assert payload["device_features"]["mouse"]["permission"] == "accessibility"
    assert payload["device_features"]["keyboard"]["state"] == "disabled"


def test_capabilities_payload_reports_unsupported_platform_helpers(monkeypatch) -> None:
    cfg = NodeConfig(
        api_url="http://localhost:8000",
        token="token-1",
        name="node-1",
        workspace_root="workspace",
        notify_enabled=True,
        screenshot_enabled=True,
        mouse_enabled=True,
        keyboard_enabled=True,
    )

    monkeypatch.setattr(node_main.sys, "platform", "linux")
    monkeypatch.setattr(node_main, "_supports_notify", lambda: True)
    monkeypatch.setattr(node_main, "_supports_screenshot", lambda: True)
    monkeypatch.setattr(node_main, "_supports_mouse_keyboard", lambda: False)
    monkeypatch.setattr(
        node_main,
        "_host_permissions",
        lambda: {
            "accessibility": {"label": "Accessibility", "status": "unsupported"},
            "screen_recording": {"label": "Screen Recording", "status": "not_required"},
        },
    )

    payload = _capabilities_payload(cfg)

    assert payload["device_features"]["screenshot"]["state"] == "ready"
    assert payload["device_features"]["mouse"]["state"] == "unsupported"
    assert payload["device_features"]["keyboard"]["state"] == "unsupported"


def test_windows_host_permissions_include_desktop_interaction(monkeypatch) -> None:
    monkeypatch.setattr(node_main.sys, "platform", "win32")

    permissions = _host_permissions()

    assert permissions["desktop_interaction"]["label"] == "Desktop Interaction"
    assert permissions["desktop_interaction"]["status"] == "not_required"
    assert "interactive user session" in permissions["desktop_interaction"]["detail"]


def test_capabilities_payload_reports_ready_windows_helpers(monkeypatch) -> None:
    cfg = NodeConfig(
        api_url="http://localhost:8000",
        token="token-1",
        name="node-1",
        workspace_root="workspace",
        notify_enabled=True,
        screenshot_enabled=True,
        mouse_enabled=True,
        keyboard_enabled=True,
    )

    monkeypatch.setattr(node_main.sys, "platform", "win32")
    monkeypatch.setattr(node_main, "_supports_notify", lambda: True)
    monkeypatch.setattr(node_main, "_supports_screenshot", lambda: True)
    monkeypatch.setattr(node_main, "_supports_mouse_keyboard", lambda: True)

    payload = _capabilities_payload(cfg)

    assert payload["permissions"]["desktop_interaction"]["status"] == "not_required"
    assert payload["device_features"]["notify"]["state"] == "ready"
    assert payload["device_features"]["screenshot"]["state"] == "ready"
    assert payload["device_features"]["screenshot"]["permission"] == "desktop_interaction"
    assert payload["device_features"]["mouse"]["state"] == "ready"
    assert payload["device_features"]["mouse"]["permission"] == "desktop_interaction"
    assert payload["device_features"]["keyboard"]["state"] == "ready"
    assert payload["device_features"]["keyboard"]["permission"] == "desktop_interaction"


def test_capabilities_payload_reports_unsupported_windows_helpers(monkeypatch) -> None:
    cfg = NodeConfig(
        api_url="http://localhost:8000",
        token="token-1",
        name="node-1",
        workspace_root="workspace",
        notify_enabled=True,
        screenshot_enabled=True,
        mouse_enabled=True,
        keyboard_enabled=True,
    )

    monkeypatch.setattr(node_main.sys, "platform", "win32")
    monkeypatch.setattr(node_main, "_supports_notify", lambda: False)
    monkeypatch.setattr(node_main, "_supports_screenshot", lambda: False)
    monkeypatch.setattr(node_main, "_supports_mouse_keyboard", lambda: False)

    payload = _capabilities_payload(cfg)

    assert payload["device_features"]["notify"]["state"] == "unsupported"
    assert payload["device_features"]["screenshot"]["state"] == "unsupported"
    assert payload["device_features"]["mouse"]["state"] == "unsupported"
    assert payload["device_features"]["keyboard"]["state"] == "unsupported"
