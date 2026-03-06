from skitter.core.mcp import extract_mcp_text


def test_extract_mcp_text_prefers_text_blocks() -> None:
    payload = {
        "content": [
            {"type": "text", "text": "hello"},
            {"type": "text", "text": "world"},
        ]
    }
    assert extract_mcp_text(payload) == "hello\nworld"


def test_extract_mcp_text_handles_resource_blocks() -> None:
    payload = {
        "content": [
            {"type": "resource", "uri": "file:///tmp/example.txt"},
        ]
    }
    text = extract_mcp_text(payload)
    assert "file:///tmp/example.txt" in text
