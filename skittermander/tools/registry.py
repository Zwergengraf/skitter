from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List


@dataclass
class ToolSpec:
    name: str
    description: str
    input_schema: Dict[str, Any]
    requires_approval: bool = True


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: Dict[str, ToolSpec] = {}

    def register(self, tool: ToolSpec) -> None:
        self._tools[tool.name] = tool

    def list(self) -> List[ToolSpec]:
        return list(self._tools.values())

    def get(self, name: str) -> ToolSpec | None:
        return self._tools.get(name)


def default_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="read",
            description="Read the contents of a file. Relative paths resolve from /workspace. Absolute paths are literal sandbox paths. Supports text files and images (jpg, png, gif, webp). For text files, output is truncated to 2000 lines or 50KB (whichever is hit first). Use offset/limit for large files.",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "offset": {"type": "number"},
                    "limit": {"type": "number"},
                    "file_path": {"type": "string"},
                },
            },
            requires_approval=True,
        )
    )
    registry.register(
        ToolSpec(
            name="list",
            description="List files and folders. Relative paths resolve from /workspace; absolute paths are literal sandbox paths.",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "file_path": {"type": "string"},
                },
            },
            requires_approval=False,
        )
    )
    registry.register(
        ToolSpec(
            name="delete",
            description="Delete a file or folder. Relative paths resolve from /workspace; absolute paths are literal sandbox paths. Use recursive=true to delete non-empty folders.",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "recursive": {"type": "boolean"},
                    "file_path": {"type": "string"},
                },
            },
            requires_approval=True,
        )
    )
    registry.register(
        ToolSpec(
            name="download",
            description="Download a file from a URL into the workspace. Optional path can be relative (from /workspace) or absolute sandbox path.",
            input_schema={
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                    "path": {"type": "string"},
                },
                "required": ["url"],
            },
            requires_approval=True,
        )
    )
    registry.register(
        ToolSpec(
            name="edit",
            description="Edit a file by replacing exact text. Relative paths resolve from /workspace; absolute paths are literal sandbox paths. oldText must match exactly (including whitespace).",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "oldText": {"type": "string"},
                    "newText": {"type": "string"},
                    "file_path": {"type": "string"},
                    "old_string": {"type": "string"},
                    "new_string": {"type": "string"},
                },
            },
            requires_approval=True,
        )
    )
    registry.register(
        ToolSpec(
            name="write",
            description="Write content to a file. Relative paths resolve from /workspace; absolute paths are literal sandbox paths. Creates the file if it doesn't exist and parent directories as needed.",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                    "file_path": {"type": "string"},
                },
            },
            requires_approval=True,
        )
    )
    registry.register(
        ToolSpec(
            name="browser",
            description="Headless browser for web pages",
            input_schema={
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                    "max_chars": {"type": "number"},
                    "screenshot": {"type": "boolean"},
                    "width": {"type": "number"},
                    "height": {"type": "number"},
                },
            },
            requires_approval=True,
        )
    )
    registry.register(
        ToolSpec(
            name="browser_action",
            description="Stateful browser automation actions (open/navigate/click/hover/move_mouse/click_at/type/fill/press/wait/snapshot/screenshot/tabs/focus/close_tab/close/status)",
            input_schema={
                "type": "object",
                "properties": {
                    "action": {"type": "string"},
                    "url": {"type": "string"},
                    "selector": {"type": "string"},
                    "text": {"type": "string"},
                    "x": {"type": "number"},
                    "y": {"type": "number"},
                    "button": {"type": "string"},
                    "click_count": {"type": "number"},
                    "mouse_steps": {"type": "number"},
                    "key": {"type": "string"},
                    "fields": {"type": "array"},
                    "submit": {"type": "boolean"},
                    "submit_selector": {"type": "string"},
                    "username": {"type": "string"},
                    "password": {"type": "string"},
                    "username_selector": {"type": "string"},
                    "password_selector": {"type": "string"},
                    "wait_for": {"type": "string"},
                    "index": {"type": "number"},
                    "width": {"type": "number"},
                    "height": {"type": "number"},
                    "timeout_ms": {"type": "number"},
                    "wait_until": {"type": "string"},
                    "full_page": {"type": "boolean"},
                    "max_chars": {"type": "number"},
                    "mode": {"type": "string"},
                    "include_elements": {"type": "boolean"},
                    "max_elements": {"type": "number"},
                },
            },
            requires_approval=True,
        )
    )
    registry.register(
        ToolSpec(
            name="http_fetch",
            description="HTTP fetch for APIs",
            input_schema={"type": "object", "properties": {"url": {"type": "string"}}},
            requires_approval=False,
        )
    )
    registry.register(
        ToolSpec(
            name="sub_agent",
            description="Spawn a sub-agent",
            input_schema={
                "type": "object",
                "properties": {
                    "task": {"type": "string"},
                    "name": {"type": "string"},
                    "context": {"type": "string"},
                    "acceptance_criteria": {"type": "string"},
                },
            },
            requires_approval=True,
        )
    )
    registry.register(
        ToolSpec(
            name="sub_agent_batch",
            description="Run multiple sub-agent tasks concurrently",
            input_schema={
                "type": "object",
                "properties": {
                    "tasks": {
                        "type": "array",
                        "items": {"type": "object"},
                    }
                },
            },
            requires_approval=True,
        )
    )
    registry.register(
        ToolSpec(
            name="shell",
            description="Run a shell command in the sandbox. Relative paths resolve from /workspace (default cwd). Absolute paths are literal sandbox paths.",
            input_schema={
                "type": "object",
                "properties": {"cmd": {"type": "string"}, "cwd": {"type": "string"}},
            },
            requires_approval=True,
        )
    )
    registry.register(
        ToolSpec(
            name="memory_search",
            description="Search stored memory embeddings",
            input_schema={
                "type": "object",
                "properties": {"query": {"type": "string"}, "top_k": {"type": "integer"}},
            },
            requires_approval=False,
        )
    )
    registry.register(
        ToolSpec(
            name="web_search",
            description="Search the web using Brave Search API",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "count": {"type": "number"},
                    "country": {"type": "string"},
                    "search_lang": {"type": "string"},
                    "ui_lang": {"type": "string"},
                    "freshness": {"type": "string"},
                },
            },
            requires_approval=False,
        )
    )
    registry.register(
        ToolSpec(
            name="web_fetch",
            description="Fetch and extract readable content from a URL",
            input_schema={
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                    "extractMode": {"type": "string"},
                    "maxChars": {"type": "number"},
                },
            },
            requires_approval=False,
        )
    )
    registry.register(
        ToolSpec(
            name="schedule_create",
            description="Create a scheduled job",
            input_schema={
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "prompt": {"type": "string"},
                    "cron": {"type": "string"},
                    "run_at": {"type": "string"},
                    "channel_id": {"type": "string"},
                },
            },
            requires_approval=False,
        )
    )
    registry.register(
        ToolSpec(
            name="schedule_update",
            description="Update a scheduled job",
            input_schema={
                "type": "object",
                "properties": {
                    "job_id": {"type": "string"},
                    "cron": {"type": "string"},
                    "run_at": {"type": "string"},
                    "prompt": {"type": "string"},
                    "enabled": {"type": "boolean"},
                },
            },
            requires_approval=False,
        )
    )
    registry.register(
        ToolSpec(
            name="schedule_delete",
            description="Delete a scheduled job",
            input_schema={
                "type": "object",
                "properties": {"job_id": {"type": "string"}},
            },
            requires_approval=False,
        )
    )
    registry.register(
        ToolSpec(
            name="schedule_list",
            description="List scheduled jobs",
            input_schema={"type": "object", "properties": {}},
            requires_approval=False,
        )
    )
    return registry
