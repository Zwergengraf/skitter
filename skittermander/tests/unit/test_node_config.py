from __future__ import annotations

from pathlib import Path

import yaml

from skittermander.node.__main__ import (
    DEFAULT_NODE_TOOLS,
    _build_arg_parser,
    _normalize_tools,
    _resolve_config,
)


def test_normalize_tools_filters_unknown_and_dedupes() -> None:
    tools = _normalize_tools(["read", "write", "read", "unknown"])
    assert tools == ("read", "write")


def test_normalize_tools_fallbacks_to_default_when_empty() -> None:
    assert _normalize_tools([]) == DEFAULT_NODE_TOOLS
    assert _normalize_tools(",,,") == DEFAULT_NODE_TOOLS


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
