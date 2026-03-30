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
    _normalize_tools,
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
