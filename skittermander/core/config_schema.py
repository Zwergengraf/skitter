from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ConfigFieldSpec:
    key: str
    path: tuple[str, ...]
    category: str
    label: str
    field_type: str
    description: str | None = None
    secret: bool = False
    minimum: float | None = None
    maximum: float | None = None
    step: float | None = None


CATEGORIES = {
    "database": "Database",
    "openai": "OpenAI",
    "embeddings": "Embeddings",
    "brave": "Brave Search",
    "prompt": "Prompt",
    "browser": "Browser",
    "scheduler": "Scheduler",
    "discord": "Discord",
    "users": "Users",
    "workspace": "Workspace",
    "sandbox": "Sandbox",
    "cors": "CORS",
    "tools": "Tools",
    "sub_agents": "Sub-agents",
}


FIELDS: list[ConfigFieldSpec] = [
    ConfigFieldSpec(
        key="prompt_path",
        path=("prompt", "path"),
        category="prompt",
        label="System prompt file",
        field_type="string",
    ),
    ConfigFieldSpec(
        key="prompt_context_title",
        path=("prompt", "context_title"),
        category="prompt",
        label="Context title",
        field_type="string",
    ),
    ConfigFieldSpec(
        key="prompt_context_files",
        path=("prompt", "context_files"),
        category="prompt",
        label="Context files",
        field_type="list",
        description="Files in each user workspace to append to the system prompt.",
    ),
    ConfigFieldSpec(
        key="db_url",
        path=("database", "url"),
        category="database",
        label="Database URL",
        field_type="string",
    ),
    ConfigFieldSpec(
        key="openai_api_base",
        path=("openai", "api_base"),
        category="openai",
        label="API Base",
        field_type="string",
    ),
    ConfigFieldSpec(
        key="openai_api_key",
        path=("openai", "api_key"),
        category="openai",
        label="API Key",
        field_type="string",
        secret=True,
    ),
    ConfigFieldSpec(
        key="openai_model",
        path=("openai", "model"),
        category="openai",
        label="Model",
        field_type="string",
    ),
    ConfigFieldSpec(
        key="embeddings_api_base",
        path=("embeddings", "api_base"),
        category="embeddings",
        label="API Base",
        field_type="string",
    ),
    ConfigFieldSpec(
        key="embeddings_api_key",
        path=("embeddings", "api_key"),
        category="embeddings",
        label="API Key",
        field_type="string",
        secret=True,
    ),
    ConfigFieldSpec(
        key="embeddings_model",
        path=("embeddings", "model"),
        category="embeddings",
        label="Model",
        field_type="string",
    ),
    ConfigFieldSpec(
        key="embeddings_max_chunk_chars",
        path=("embeddings", "max_chunk_chars"),
        category="embeddings",
        label="Max chunk chars",
        field_type="number",
        minimum=100,
        maximum=5000,
        step=50,
    ),
    ConfigFieldSpec(
        key="memory_min_similarity",
        path=("embeddings", "min_similarity"),
        category="embeddings",
        label="Memory min similarity",
        field_type="number",
        minimum=0.0,
        maximum=1.0,
        step=0.05,
    ),
    ConfigFieldSpec(
        key="brave_api_key",
        path=("brave", "api_key"),
        category="brave",
        label="API Key",
        field_type="string",
        secret=True,
    ),
    ConfigFieldSpec(
        key="brave_api_base",
        path=("brave", "api_base"),
        category="brave",
        label="API Base",
        field_type="string",
    ),
    ConfigFieldSpec(
        key="browser_executable",
        path=("browser", "executable"),
        category="browser",
        label="Executable",
        field_type="string",
    ),
    ConfigFieldSpec(
        key="scheduler_timezone",
        path=("scheduler", "timezone"),
        category="scheduler",
        label="Timezone",
        field_type="string",
    ),
    ConfigFieldSpec(
        key="discord_token",
        path=("discord", "token"),
        category="discord",
        label="Bot token",
        field_type="string",
        secret=True,
    ),
    ConfigFieldSpec(
        key="user_approved_message",
        path=("users", "approved_message"),
        category="users",
        label="Approval message",
        field_type="string",
        description="Message sent to users when they are approved.",
    ),
    ConfigFieldSpec(
        key="workspace_root",
        path=("workspace", "root"),
        category="workspace",
        label="Root",
        field_type="string",
    ),
    ConfigFieldSpec(
        key="workspace_skeleton_root",
        path=("workspace", "skeleton_root"),
        category="workspace",
        label="Skeleton root",
        field_type="string",
    ),
    ConfigFieldSpec(
        key="host_workspace_root",
        path=("workspace", "host_root"),
        category="workspace",
        label="Host root",
        field_type="string",
    ),
    ConfigFieldSpec(
        key="skills_root",
        path=("workspace", "skills_root"),
        category="workspace",
        label="Skills root",
        field_type="string",
    ),
    ConfigFieldSpec(
        key="host_skills_root",
        path=("workspace", "host_skills_root"),
        category="workspace",
        label="Host skills root",
        field_type="string",
    ),
    ConfigFieldSpec(
        key="sandbox_base_url",
        path=("sandbox", "base_url"),
        category="sandbox",
        label="Base URL",
        field_type="string",
    ),
    ConfigFieldSpec(
        key="sandbox_api_key",
        path=("sandbox", "api_key"),
        category="sandbox",
        label="API Key",
        field_type="string",
        secret=True,
    ),
    ConfigFieldSpec(
        key="sandbox_image",
        path=("sandbox", "image"),
        category="sandbox",
        label="Image",
        field_type="string",
    ),
    ConfigFieldSpec(
        key="sandbox_network",
        path=("sandbox", "network"),
        category="sandbox",
        label="Network",
        field_type="string",
    ),
    ConfigFieldSpec(
        key="sandbox_port",
        path=("sandbox", "port"),
        category="sandbox",
        label="Port",
        field_type="number",
        minimum=1,
        maximum=65535,
        step=1,
    ),
    ConfigFieldSpec(
        key="sandbox_idle_seconds",
        path=("sandbox", "idle_seconds"),
        category="sandbox",
        label="Idle timeout (sec)",
        field_type="number",
        minimum=60,
        maximum=86400,
        step=30,
    ),
    ConfigFieldSpec(
        key="sandbox_idle_check_seconds",
        path=("sandbox", "idle_check_seconds"),
        category="sandbox",
        label="Idle check interval (sec)",
        field_type="number",
        minimum=5,
        maximum=3600,
        step=5,
    ),
    ConfigFieldSpec(
        key="sandbox_container_prefix",
        path=("sandbox", "container_prefix"),
        category="sandbox",
        label="Container prefix",
        field_type="string",
    ),
    ConfigFieldSpec(
        key="sandbox_connect_retries",
        path=("sandbox", "connect_retries"),
        category="sandbox",
        label="Connect retries",
        field_type="number",
        minimum=1,
        maximum=20,
        step=1,
    ),
    ConfigFieldSpec(
        key="sandbox_connect_backoff",
        path=("sandbox", "connect_backoff"),
        category="sandbox",
        label="Connect backoff (sec)",
        field_type="number",
        minimum=0.1,
        maximum=10.0,
        step=0.1,
    ),
    ConfigFieldSpec(
        key="cors_origins",
        path=("cors", "origins"),
        category="cors",
        label="Allowed origins",
        field_type="list",
        description="Comma-separated origins.",
    ),
    ConfigFieldSpec(
        key="tool_approval_required",
        path=("tools", "approval_required"),
        category="tools",
        label="Approval required",
        field_type="boolean",
    ),
    ConfigFieldSpec(
        key="tool_approval_tools",
        path=("tools", "approval_tools"),
        category="tools",
        label="Tools requiring approval",
        field_type="list",
        description="Comma-separated tool names.",
    ),
    ConfigFieldSpec(
        key="max_sub_agents",
        path=("sub_agents", "max_concurrent"),
        category="sub_agents",
        label="Max sub-agents",
        field_type="number",
        minimum=1,
        maximum=32,
        step=1,
    ),
]


def _get_nested(container: dict, path: tuple[str, ...]) -> Any:
    node = container
    for key in path:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    return node


def _set_nested(container: dict, path: tuple[str, ...], value: Any) -> None:
    node = container
    for key in path[:-1]:
        node = node.setdefault(key, {})
    node[path[-1]] = value


def build_config_from_settings(current: Any) -> dict:
    data: dict[str, Any] = {}
    for field in FIELDS:
        value = getattr(current, field.key)
        if field.field_type == "list" and isinstance(value, str):
            value = [item.strip() for item in value.split(",") if item.strip()]
        _set_nested(data, field.path, value)
    return data


def flatten_config(data: dict) -> dict[str, Any]:
    flat: dict[str, Any] = {}
    for field in FIELDS:
        value = _get_nested(data, field.path)
        if value is None:
            continue
        if field.field_type == "list":
            if isinstance(value, list):
                value = ",".join(str(item).strip() for item in value if str(item).strip())
            elif isinstance(value, str):
                value = value
        flat[field.key] = value
    return flat
