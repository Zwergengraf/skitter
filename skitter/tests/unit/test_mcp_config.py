from pydantic import ValidationError

from skitter.core.config import MCPServerConfig


def test_mcp_server_config_allows_disabled_stub() -> None:
    config = MCPServerConfig(name="stub", enabled=False, transport="stdio", command="")
    assert config.enabled is False


def test_mcp_server_config_requires_command_for_enabled_stdio() -> None:
    try:
        MCPServerConfig(name="stdio", enabled=True, transport="stdio", command="")
    except ValidationError as exc:
        assert "command is required for stdio transport" in str(exc)
    else:  # pragma: no cover - defensive
        raise AssertionError("expected validation error for missing stdio command")


def test_mcp_server_config_requires_url_for_enabled_http() -> None:
    try:
        MCPServerConfig(name="remote", enabled=True, transport="http", url="")
    except ValidationError as exc:
        assert "url is required for http transport" in str(exc)
    else:  # pragma: no cover - defensive
        raise AssertionError("expected validation error for missing http url")


def test_mcp_server_config_accepts_http_server() -> None:
    config = MCPServerConfig(
        name="remote",
        enabled=True,
        transport="http",
        url="https://mcp.example.com/rpc",
        headers={"Authorization": "Bearer token"},
    )
    assert config.transport == "http"
    assert config.url == "https://mcp.example.com/rpc"
