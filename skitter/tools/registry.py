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
            description=(
                "Read the contents of a file. Relative paths resolve from /workspace. Absolute paths are literal sandbox paths. "
                "For text files, output is truncated to 2000 lines or 50KB (whichever is hit first). "
                "Set include_base64=true to return raw bytes for any file type."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "offset": {"type": "number"},
                    "limit": {"type": "number"},
                    "include_base64": {"type": "boolean"},
                    "file_path": {"type": "string"},
                    "target_machine": {"type": "string"},
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
                    "show_hidden_files": {"type": "boolean"},
                    "target_machine": {"type": "string"},
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
                    "target_machine": {"type": "string"},
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
                    "target_machine": {"type": "string"},
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
                    "target_machine": {"type": "string"},
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
                    "base64": {"type": "string"},
                    "overwrite": {"type": "boolean"},
                    "file_path": {"type": "string"},
                    "target_machine": {"type": "string"},
                },
            },
            requires_approval=True,
        )
    )
    registry.register(
        ToolSpec(
            name="transfer_file",
            description=(
                "Transfer a file between executors. Use source_machine/destination_machine to route between machines. "
                "Use machine value 'api' for the API-server workspace."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "source_path": {"type": "string"},
                    "destination_path": {"type": "string"},
                    "source_machine": {"type": "string"},
                    "destination_machine": {"type": "string"},
                    "overwrite": {"type": "boolean"},
                },
                "required": ["source_path", "destination_path"],
            },
            requires_approval=True,
        )
    )
    registry.register(
        ToolSpec(
            name="attach_file",
            description=(
                "Attach a file to the next assistant response. Supports images, audio, PDFs, archives, and other file types."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "file_path": {"type": "string"},
                    "target_machine": {"type": "string"},
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
                    "target_machine": {"type": "string"},
                },
            },
            requires_approval=True,
        )
    )
    registry.register(
        ToolSpec(
            name="browser_action",
            description="Stateful browser automation actions (open/navigate/click/hover/move_mouse/click_at/type/fill/press/wait/evaluate/snapshot/screenshot/tabs/focus/close_tab/close/status)",
            input_schema={
                "type": "object",
                "properties": {
                    "action": {"type": "string"},
                    "url": {"type": "string"},
                    "selector": {"type": "string"},
                    "text": {"type": "string"},
                    "script": {"type": "string"},
                    "arg": {},
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
                    "target_machine": {"type": "string"},
                },
            },
            requires_approval=True,
        )
    )
    registry.register(
        ToolSpec(
            name="http_fetch",
            description="HTTP fetch for APIs",
            input_schema={
                "type": "object",
                "properties": {"url": {"type": "string"}, "target_machine": {"type": "string"}},
            },
            requires_approval=False,
        )
    )
    registry.register(
        ToolSpec(
            name="sub_agent",
            description="Run one synchronous delegated task and wait for the result in the current reply. Use job_start instead for long-running background work.",
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
            description="Run multiple synchronous delegated tasks concurrently and wait for all results in the current reply. Use job_start instead for long-running background work.",
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
                "properties": {
                    "cmd": {"type": "string"},
                    "cwd": {"type": "string"},
                    "background": {"type": "boolean"},
                    "secret_refs": {"type": "array"},
                    "target_machine": {"type": "string"},
                },
            },
            requires_approval=True,
        )
    )
    registry.register(
        ToolSpec(
            name="machine_list",
            description="List available execution machines for the current user.",
            input_schema={
                "type": "object",
                "properties": {
                    "include_disabled": {"type": "boolean"},
                },
            },
            requires_approval=False,
        )
    )
    registry.register(
        ToolSpec(
            name="machine_status",
            description="Get status and capabilities for a machine (or current default).",
            input_schema={
                "type": "object",
                "properties": {
                    "target_machine": {"type": "string"},
                },
            },
            requires_approval=False,
        )
    )
    registry.register(
        ToolSpec(
            name="list_secrets",
            description="List available per-user secret names (values are never returned). Useful before using shell secret_refs.",
            input_schema={"type": "object", "properties": {}},
            requires_approval=False,
        )
    )
    registry.register(
        ToolSpec(
            name="model_list",
            description="List available model selectors for explicit model choices. Use only when a specific model is requested; otherwise rely on defaults.",
            input_schema={"type": "object", "properties": {}},
            requires_approval=False,
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
            description="Search the web using the configured engine (Brave or SearXNG).",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "count": {"type": "number"},
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
            description="Create a scheduled job. Normally omit model so the dynamic main model chain is used. If the user explicitly requests a specific model, use model_list first and pass a valid selector.",
            input_schema={
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "prompt": {"type": "string"},
                    "cron": {"type": "string"},
                    "run_at": {"type": "string"},
                    "channel_id": {"type": "string"},
                    "model": {"type": "string"},
                },
            },
            requires_approval=False,
        )
    )
    registry.register(
        ToolSpec(
            name="schedule_update",
            description="Update a scheduled job. Only set model when the user explicitly asks for one; use model_list first if needed.",
            input_schema={
                "type": "object",
                "properties": {
                    "job_id": {"type": "string"},
                    "cron": {"type": "string"},
                    "run_at": {"type": "string"},
                    "prompt": {"type": "string"},
                    "enabled": {"type": "boolean"},
                    "model": {"type": "string"},
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
            name="job_start",
            description="Start a background job for longer-running work and return a job ID immediately. Use this when the user does not need the result in the current reply.",
            input_schema={
                "type": "object",
                "properties": {
                    "task": {"type": "string"},
                    "name": {"type": "string"},
                    "context": {"type": "string"},
                    "acceptance_criteria": {"type": "string"},
                    "model_name": {"type": "string"},
                },
            },
            requires_approval=True,
        )
    )
    registry.register(
        ToolSpec(
            name="job_status",
            description="Get current status and result details for a background job.",
            input_schema={"type": "object", "properties": {"job_id": {"type": "string"}}},
            requires_approval=False,
        )
    )
    registry.register(
        ToolSpec(
            name="job_list",
            description="List recent background jobs for the current user.",
            input_schema={
                "type": "object",
                "properties": {"status": {"type": "string"}, "limit": {"type": "integer"}},
            },
            requires_approval=False,
        )
    )
    registry.register(
        ToolSpec(
            name="job_cancel",
            description="Cancel a queued background job or request cancellation for a running one.",
            input_schema={"type": "object", "properties": {"job_id": {"type": "string"}}},
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
