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
    "embeddings": "Embeddings",
    "web_search": "Web Search",
    "prompt": "Prompt",
    "logging": "Logging",
    "context": "Context",
    "limits": "Limits",
    "jobs": "Jobs",
    "browser": "Browser",
    "scheduler": "Scheduler",
    "discord": "Discord",
    "models": "Models",
    "reasoning": "Reasoning",
    "heartbeat": "Heartbeat",
    "users": "Users",
    "workspace": "Workspace",
    "sandbox": "Sandbox",
    "cors": "CORS",
    "tools": "Tools",
    "sub_agents": "Sub-agents",
}


FIELDS: list[ConfigFieldSpec] = [
    ConfigFieldSpec(
        key="log_level",
        path=("logging", "level"),
        category="logging",
        label="Log level",
        field_type="string",
        description="Python + app log level (e.g. DEBUG, INFO, WARNING, ERROR).",
    ),
    ConfigFieldSpec(
        key="admin_event_buffer_size",
        path=("logging", "admin_event_buffer_size"),
        category="logging",
        label="Live event buffer size",
        field_type="number",
        description="How many recent admin live events to keep in memory for the Live view.",
        minimum=10,
        maximum=10000,
        step=10,
    ),
    ConfigFieldSpec(
        key="prompt_path",
        path=("prompt", "path"),
        category="prompt",
        label="System prompt file",
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
        key="context_max_tool_messages",
        path=("context", "max_tool_messages"),
        category="context",
        label="Max tool messages",
        field_type="number",
        minimum=0,
        maximum=500,
        step=1,
    ),
    ConfigFieldSpec(
        key="context_max_input_tokens",
        path=("context", "max_input_tokens"),
        category="context",
        label="Compaction trigger tokens",
        field_type="number",
        description="Start compacting when the last prompt input reaches at least this many tokens.",
        minimum=1000,
        maximum=1000000,
        step=500,
    ),
    ConfigFieldSpec(
        key="context_compact_every_tokens",
        path=("context", "compact_every_tokens"),
        category="context",
        label="Compaction token batch",
        field_type="number",
        description="After a compaction, wait for at least this many additional input tokens before compacting again.",
        minimum=500,
        maximum=1000000,
        step=500,
    ),
    ConfigFieldSpec(
        key="context_preserve_recent_messages",
        path=("context", "preserve_recent_messages"),
        category="context",
        label="Preserve recent messages",
        field_type="number",
        description="Always keep at least this many recent chat messages verbatim after compaction.",
        minimum=1,
        maximum=200,
        step=1,
    ),
    ConfigFieldSpec(
        key="context_preserve_recent_tokens",
        path=("context", "preserve_recent_tokens"),
        category="context",
        label="Preserve recent tokens",
        field_type="number",
        description="Also keep enough recent chat messages to preserve at least this many estimated raw-chat tokens.",
        minimum=500,
        maximum=200000,
        step=500,
    ),
    ConfigFieldSpec(
        key="session_memory_enabled",
        path=("context", "session_memory", "enabled"),
        category="context",
        label="Session memory enabled",
        field_type="boolean",
        description="Maintain a structured sidecar note for active private sessions.",
    ),
    ConfigFieldSpec(
        key="session_memory_init_tokens",
        path=("context", "session_memory", "init_tokens"),
        category="context",
        label="Session memory init tokens",
        field_type="number",
        description="Approximate token threshold before the session sidecar is created.",
        minimum=100,
        maximum=100000,
        step=100,
    ),
    ConfigFieldSpec(
        key="session_memory_update_tokens",
        path=("context", "session_memory", "update_tokens"),
        category="context",
        label="Session memory update tokens",
        field_type="number",
        description="Additional prompt-input tokens required before refreshing the sidecar again.",
        minimum=100,
        maximum=100000,
        step=100,
    ),
    ConfigFieldSpec(
        key="limits_max_tool_calls",
        path=("limits", "max_tool_calls"),
        category="limits",
        label="Max tool calls per run",
        field_type="number",
        minimum=1,
        maximum=200,
        step=1,
    ),
    ConfigFieldSpec(
        key="limits_max_runtime_seconds",
        path=("limits", "max_runtime_seconds"),
        category="limits",
        label="Max runtime seconds",
        field_type="number",
        minimum=5,
        maximum=3600,
        step=1,
    ),
    ConfigFieldSpec(
        key="limits_max_cost_usd",
        path=("limits", "max_cost_usd"),
        category="limits",
        label="Max run cost (USD)",
        field_type="number",
        minimum=0,
        maximum=1000,
        step=0.01,
    ),
    ConfigFieldSpec(
        key="jobs_enabled",
        path=("jobs", "enabled"),
        category="jobs",
        label="Enabled",
        field_type="boolean",
    ),
    ConfigFieldSpec(
        key="jobs_poll_interval_seconds",
        path=("jobs", "poll_interval_seconds"),
        category="jobs",
        label="Poll interval (sec)",
        field_type="number",
        minimum=1,
        maximum=60,
        step=1,
    ),
    ConfigFieldSpec(
        key="jobs_max_concurrent",
        path=("jobs", "max_concurrent"),
        category="jobs",
        label="Max concurrent workers",
        field_type="number",
        minimum=1,
        maximum=32,
        step=1,
    ),
    ConfigFieldSpec(
        key="job_limits_max_tool_calls",
        path=("jobs", "limits", "max_tool_calls"),
        category="jobs",
        label="Job max tool calls",
        field_type="number",
        minimum=1,
        maximum=500,
        step=1,
    ),
    ConfigFieldSpec(
        key="job_limits_max_runtime_seconds",
        path=("jobs", "limits", "max_runtime_seconds"),
        category="jobs",
        label="Job max runtime (sec)",
        field_type="number",
        minimum=10,
        maximum=86400,
        step=5,
    ),
    ConfigFieldSpec(
        key="job_limits_max_cost_usd",
        path=("jobs", "limits", "max_cost_usd"),
        category="jobs",
        label="Job max cost (USD)",
        field_type="number",
        minimum=0.0,
        maximum=1000,
        step=0.01,
    ),
    ConfigFieldSpec(
        key="discord_progress_updates",
        path=("discord", "progress_updates"),
        category="discord",
        label="Progress updates",
        field_type="boolean",
        description="Send and update a temporary progress message while processing.",
    ),
    ConfigFieldSpec(
        key="discord_progress_interval_seconds",
        path=("discord", "progress_interval_seconds"),
        category="discord",
        label="Progress interval (sec)",
        field_type="number",
        minimum=1,
        maximum=60,
        step=1,
    ),
    ConfigFieldSpec(
        key="db_url",
        path=("database", "url"),
        category="database",
        label="Database URL",
        field_type="string",
    ),
    ConfigFieldSpec(
        key="main_model",
        path=("main_model",),
        category="models",
        label="Main model chain",
        field_type="list",
        description="Ordered model selectors for normal runs (format: provider/model). First success wins.",
    ),
    ConfigFieldSpec(
        key="heartbeat_model",
        path=("heartbeat_model",),
        category="models",
        label="Heartbeat model chain",
        field_type="list",
        description="Ordered model selectors for heartbeat runs (format: provider/model). Falls back to main chain when empty.",
    ),
    ConfigFieldSpec(
        key="reasoning_enabled",
        path=("reasoning", "enabled"),
        category="reasoning",
        label="Enable reasoning",
        field_type="boolean",
    ),
    ConfigFieldSpec(
        key="openai_use_responses_api",
        path=("reasoning", "openai", "use_responses_api"),
        category="reasoning",
        label="OpenAI responses API",
        field_type="boolean",
    ),
    ConfigFieldSpec(
        key="openai_output_version",
        path=("reasoning", "openai", "output_version"),
        category="reasoning",
        label="OpenAI output version",
        field_type="string",
    ),
    ConfigFieldSpec(
        key="openai_reasoning_effort",
        path=("reasoning", "openai", "effort"),
        category="reasoning",
        label="OpenAI effort",
        field_type="string",
    ),
    ConfigFieldSpec(
        key="openai_reasoning_summary",
        path=("reasoning", "openai", "summary"),
        category="reasoning",
        label="OpenAI summary mode",
        field_type="string",
    ),
    ConfigFieldSpec(
        key="anthropic_thinking_budget_tokens",
        path=("reasoning", "anthropic", "budget_tokens"),
        category="reasoning",
        label="Anthropic thinking budget tokens",
        field_type="number",
        minimum=256,
        maximum=128000,
        step=256,
    ),
    ConfigFieldSpec(
        key="anthropic_output_version",
        path=("reasoning", "anthropic", "output_version"),
        category="reasoning",
        label="Anthropic output version",
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
        key="embeddings_target_chunk_chars",
        path=("embeddings", "target_chunk_chars"),
        category="embeddings",
        label="Target chunk chars",
        field_type="number",
        minimum=100,
        maximum=5000,
        step=50,
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
        key="memory_max_distance",
        path=("embeddings", "max_distance"),
        category="embeddings",
        label="Memory max distance",
        field_type="number",
        minimum=0.0,
        maximum=2.0,
        step=0.01,
        description="Cosine distance threshold for memory retrieval (lower is stricter).",
    ),
    ConfigFieldSpec(
        key="web_search_engine",
        path=("web_search", "engine"),
        category="web_search",
        label="Search engine",
        field_type="string",
        description="Select `brave` or `searxng`.",
    ),
    ConfigFieldSpec(
        key="web_search_searxng_api_base",
        path=("web_search", "searxng", "api_base"),
        category="web_search",
        label="SearXNG API base",
        field_type="string",
        description="Base search endpoint, usually ending with /search.",
    ),
    ConfigFieldSpec(
        key="brave_api_key",
        path=("web_search", "brave", "api_key"),
        category="web_search",
        label="Brave API key",
        field_type="string",
        secret=True,
    ),
    ConfigFieldSpec(
        key="brave_api_base",
        path=("web_search", "brave", "api_base"),
        category="web_search",
        label="Brave API base",
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
        key="discord_enabled",
        path=("discord", "enabled"),
        category="discord",
        label="Enabled",
        field_type="boolean",
        description="Start the Discord transport when the API server launches.",
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
        key="heartbeat_enabled",
        path=("heartbeat", "enabled"),
        category="heartbeat",
        label="Enabled",
        field_type="boolean",
    ),
    ConfigFieldSpec(
        key="heartbeat_interval_minutes",
        path=("heartbeat", "interval_minutes"),
        category="heartbeat",
        label="Interval (minutes)",
        field_type="number",
        minimum=5,
        maximum=1440,
        step=5,
    ),
    ConfigFieldSpec(
        key="heartbeat_history_runs",
        path=("heartbeat", "history_runs"),
        category="heartbeat",
        label="History runs",
        field_type="number",
        minimum=1,
        maximum=100,
        step=1,
    ),
    ConfigFieldSpec(
        key="heartbeat_prompt",
        path=("heartbeat", "prompt"),
        category="heartbeat",
        label="Prompt",
        field_type="string",
    ),
    ConfigFieldSpec(
        key="heartbeat_quiet_hours_start",
        path=("heartbeat", "quiet_hours_start"),
        category="heartbeat",
        label="Quiet hours start",
        field_type="string",
    ),
    ConfigFieldSpec(
        key="heartbeat_quiet_hours_end",
        path=("heartbeat", "quiet_hours_end"),
        category="heartbeat",
        label="Quiet hours end",
        field_type="string",
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
        key="executors_auto_docker_default",
        path=("executors", "auto_docker_default"),
        category="sandbox",
        label="Auto Docker default executor",
        field_type="boolean",
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
        key="approval_secrets_required",
        path=("tools", "approval_secrets_required"),
        category="tools",
        label="Secrets approval mode",
        field_type="string",
        description=(
            "Set to the magic bypass token to disable forced approval for secret_refs shell runs. "
            "Any other value keeps forced approval enabled."
        ),
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
    ConfigFieldSpec(
        key="subagent_timeout_seconds",
        path=("sub_agents", "timeout_seconds"),
        category="sub_agents",
        label="Worker timeout (sec)",
        field_type="number",
        minimum=10,
        maximum=3600,
        step=5,
    ),
    ConfigFieldSpec(
        key="subagent_max_tasks_per_batch",
        path=("sub_agents", "max_tasks_per_batch"),
        category="sub_agents",
        label="Max batch size",
        field_type="number",
        minimum=1,
        maximum=64,
        step=1,
    ),
    ConfigFieldSpec(
        key="subagent_transcript_chars",
        path=("sub_agents", "transcript_chars"),
        category="sub_agents",
        label="Transcript chars",
        field_type="number",
        minimum=1000,
        maximum=200000,
        step=500,
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
    if hasattr(current, "providers"):
        try:
            providers = [provider.model_dump() for provider in current.providers]
        except Exception:
            providers = []
        if providers:
            data["providers"] = providers
    if hasattr(current, "models"):
        try:
            models = [model.model_dump(by_alias=True) for model in current.models]
        except Exception:
            models = []
        if models:
            data["models"] = models
    if hasattr(current, "main_model") and getattr(current, "main_model"):
        data["main_model"] = getattr(current, "main_model")
    if hasattr(current, "heartbeat_model") and getattr(current, "heartbeat_model"):
        data["heartbeat_model"] = getattr(current, "heartbeat_model")
    if hasattr(current, "mcp_servers"):
        try:
            servers = [server.model_dump() for server in current.mcp_servers]
        except Exception:
            servers = []
        if servers:
            data.setdefault("mcp", {})["servers"] = servers
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
