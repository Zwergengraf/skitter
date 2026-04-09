from pathlib import Path

from skitter.core.config import MCPServerConfig, settings
from skitter.core.prompting import build_mcp_index, build_system_prompt


def test_build_mcp_index_lists_enabled_servers_with_descriptions(monkeypatch) -> None:
    monkeypatch.setattr(
        settings,
        "mcp_servers",
        [
            MCPServerConfig(
                name="trello",
                description="Use for boards, lists, cards, and comments.",
                enabled=True,
                transport="http",
                url="http://example.invalid/mcp",
            ),
            MCPServerConfig(
                name="disabled",
                description="Should not appear.",
                enabled=False,
                transport="stdio",
                command="npx",
            ),
        ],
    )

    text = build_mcp_index()

    assert text is not None
    assert "<name>trello</name>" in text
    assert "Use for boards, lists, cards, and comments." in text
    assert "mcp_list_tools" in text
    assert "mcp_call" in text
    assert "disabled" not in text


def test_build_system_prompt_places_mcp_index_before_context(monkeypatch, tmp_path: Path) -> None:
    user_id = "user-1"
    workspace_root = tmp_path / "workspace"
    user_root = workspace_root / "users" / user_id / "default"
    user_root.mkdir(parents=True, exist_ok=True)
    (user_root / "TOOLS.md").write_text("Tool notes.", encoding="utf-8")

    monkeypatch.setattr(settings, "workspace_root", str(workspace_root))
    monkeypatch.setattr(settings, "prompt_context_files", "TOOLS.md")
    monkeypatch.setattr(
        settings,
        "mcp_servers",
        [
            MCPServerConfig(
                name="github",
                description="Use for repositories, issues, and pull requests.",
                enabled=True,
                transport="http",
                url="http://example.invalid/mcp",
            )
        ],
    )

    prompt = build_system_prompt(user_id)

    assert "## MCP Servers" in prompt
    assert "Use for repositories, issues, and pull requests." in prompt
    assert "###TOOLS.md" in prompt
    assert prompt.index("## MCP Servers") < prompt.index("###TOOLS.md")
