from skitter.core.config import MCPServerConfig
from skitter.core.mcp import MCPError, _MCPServerSession


def test_http_headers_accept_json_and_sse() -> None:
    session = _MCPServerSession(
        MCPServerConfig(
            name="remote",
            enabled=True,
            transport="http",
            url="https://mcp.example.com/rpc",
        )
    )

    headers = session._http_headers()

    assert headers["accept"] == "application/json, text/event-stream"


def test_http_headers_preserve_custom_headers_and_enforce_required_accept_values() -> None:
    session = _MCPServerSession(
        MCPServerConfig(
            name="remote",
            enabled=True,
            transport="http",
            url="https://mcp.example.com/rpc",
            headers={
                "Authorization": "Bearer token",
                "Accept": "application/json",
            },
        )
    )

    headers = session._http_headers()

    assert headers["Authorization"] == "Bearer token"
    assert headers["accept"] == "application/json, text/event-stream"


def test_parse_sse_response_reads_json_payload() -> None:
    payload = _MCPServerSession._parse_sse_response(
        "event: message\n"
        'data: {"jsonrpc":"2.0","id":1,"result":{"ok":true}}\n\n'
    )

    assert payload == {"jsonrpc": "2.0", "id": 1, "result": {"ok": True}}


def test_parse_sse_response_rejects_missing_data() -> None:
    try:
        _MCPServerSession._parse_sse_response("event: message\n\n")
    except MCPError as exc:
        assert "without any data payload" in str(exc)
    else:  # pragma: no cover - defensive
        raise AssertionError("expected MCPError for empty SSE payload")
