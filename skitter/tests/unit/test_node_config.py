from __future__ import annotations

from pathlib import Path

import yaml

from skitter.node.__main__ import (
    DEVICE_CAPABILITY_TOOL_KEYS,
    DEFAULT_NODE_TOOLS,
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
