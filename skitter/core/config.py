from __future__ import annotations

import os
from pathlib import Path
from datetime import datetime
from typing import Any, Literal

import yaml
from pydantic import Field, BaseModel
from pydantic import ConfigDict
from pydantic import field_validator
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .config_schema import flatten_config, build_config_from_settings

SECRETS_APPROVAL_BYPASS_MAGIC = "i_have_read_the_warnings_and_im_probably_doing_something_cursed"


class ModelConfig(BaseModel):
    name: str
    provider: str
    model: str = Field(alias="model_id")
    input_cost_per_1m: float = Field(default=0.0)
    output_cost_per_1m: float = Field(default=0.0)
    reasoning: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(populate_by_name=True, extra="ignore")


class ProviderConfig(BaseModel):
    name: str
    api_type: Literal["openai", "anthropic"] = Field(default="openai")
    api_base: str = Field(default="")
    api_key: str = Field(default="")

    model_config = ConfigDict(extra="ignore")

    @field_validator("api_type", mode="before")
    @classmethod
    def _normalize_api_type(cls, value: Any) -> str:
        if value is None:
            return "openai"
        text = str(value).strip().lower()
        if not text:
            return "openai"
        return text


class MCPServerConfig(BaseModel):
    name: str
    description: str = Field(default="")
    transport: Literal["stdio", "http"] = Field(default="stdio")
    command: str = Field(default="")
    args: list[str] = Field(default_factory=list)
    url: str = Field(default="")
    headers: dict[str, str] = Field(default_factory=dict)
    env: dict[str, str] = Field(default_factory=dict)
    cwd: str = Field(default="")
    enabled: bool = Field(default=True)
    startup_timeout_seconds: float = Field(default=15.0)
    request_timeout_seconds: float = Field(default=120.0)

    model_config = ConfigDict(extra="ignore")

    @field_validator("name", mode="before")
    @classmethod
    def _normalize_name(cls, value: Any) -> str:
        return str(value or "").strip()

    @field_validator("description", mode="before")
    @classmethod
    def _normalize_description(cls, value: Any) -> str:
        return str(value or "").strip()

    @field_validator("command", mode="before")
    @classmethod
    def _normalize_command(cls, value: Any) -> str:
        return str(value or "").strip()

    @field_validator("transport", mode="before")
    @classmethod
    def _normalize_transport(cls, value: Any) -> str:
        text = str(value or "stdio").strip().lower()
        return text or "stdio"

    @field_validator("args", mode="before")
    @classmethod
    def _normalize_args(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [item for item in value.split(" ") if item]
        if isinstance(value, (list, tuple, set)):
            out: list[str] = []
            for item in value:
                text = str(item).strip()
                if text:
                    out.append(text)
            return out
        text = str(value).strip()
        return [text] if text else []

    @field_validator("env", mode="before")
    @classmethod
    def _normalize_env(cls, value: Any) -> dict[str, str]:
        if value is None:
            return {}
        if isinstance(value, dict):
            out: dict[str, str] = {}
            for key, item in value.items():
                k = str(key).strip()
                if not k:
                    continue
                out[k] = str(item)
            return out
        return {}

    @field_validator("headers", mode="before")
    @classmethod
    def _normalize_headers(cls, value: Any) -> dict[str, str]:
        if value is None:
            return {}
        if isinstance(value, dict):
            out: dict[str, str] = {}
            for key, item in value.items():
                k = str(key).strip()
                if not k:
                    continue
                out[k] = str(item)
            return out
        return {}

    @field_validator("url", mode="before")
    @classmethod
    def _normalize_url(cls, value: Any) -> str:
        return str(value or "").strip()

    @field_validator("cwd", mode="before")
    @classmethod
    def _normalize_cwd(cls, value: Any) -> str:
        return str(value or "").strip()

    @model_validator(mode="after")
    def _validate_transport_config(self) -> MCPServerConfig:
        if not self.enabled:
            return self
        if self.transport == "stdio":
            if not self.command.strip():
                raise ValueError("mcp server command is required for stdio transport")
            return self
        if not self.url.strip():
            raise ValueError("mcp server url is required for http transport")
        return self


def _normalize_model_reference(provider: str, model_name: str) -> str:
    return f"{provider.strip()}/{model_name.strip()}"


def _looks_like_legacy_model_config(raw: Any) -> bool:
    if not isinstance(raw, dict):
        return False
    return "provider" not in raw and any(key in raw for key in ("api_base", "api_key"))


def _convert_legacy_model_layout(raw_models: list[Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    providers: dict[str, dict[str, Any]] = {}
    converted_models: list[dict[str, Any]] = []

    for item in raw_models:
        if not isinstance(item, dict):
            continue
        model_name = str(item.get("name") or "").strip()
        if not model_name:
            continue
        api_base = str(item.get("api_base") or "").strip()
        api_key = str(item.get("api_key") or "")
        provider_name = str(item.get("provider") or "").strip()
        if not provider_name:
            provider_name = model_name
        provider_key = provider_name.lower()
        provider = providers.get(provider_key)
        if provider is None:
            provider = {
                "name": provider_name,
                "api_type": str(item.get("api_type") or "openai").strip().lower() or "openai",
                "api_base": api_base,
                "api_key": api_key,
            }
            providers[provider_key] = provider
        else:
            # Prefer explicit provider details if present in this entry.
            if api_base:
                provider["api_base"] = api_base
            if api_key:
                provider["api_key"] = api_key
            if item.get("api_type"):
                provider["api_type"] = str(item.get("api_type")).strip().lower() or provider.get("api_type", "openai")

        converted_models.append(
            {
                "name": model_name,
                "provider": provider_name,
                "model_id": item.get("model_id") or item.get("model") or "",
                "input_cost_per_1m": item.get("input_cost_per_1m", 0.0),
                "output_cost_per_1m": item.get("output_cost_per_1m", 0.0),
                "reasoning": item.get("reasoning") if isinstance(item.get("reasoning"), dict) else {},
            }
        )
    return list(providers.values()), converted_models


def _normalize_model_selector(value: str | None, models: list[ModelConfig]) -> str:
    if not value:
        return ""
    selector = value.strip()
    if not selector:
        return ""
    if "/" in selector:
        return selector
    matches = [model for model in models if model.name.lower() == selector.lower()]
    if len(matches) == 1:
        selected = matches[0]
        return _normalize_model_reference(selected.provider, selected.name)
    return selector


def _normalize_model_selector_list(value: Any, models: list[ModelConfig]) -> list[str]:
    if value is None:
        return []
    raw_items: list[str] = []
    if isinstance(value, str):
        raw_items = [item.strip() for item in value.split(",") if item.strip()]
    elif isinstance(value, (list, tuple, set)):
        for item in value:
            text = str(item).strip()
            if text:
                raw_items.append(text)
    else:
        text = str(value).strip()
        if text:
            raw_items = [text]

    normalized: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        selector = _normalize_model_selector(item, models)
        key = selector.lower()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(selector)
    return normalized


def _detect_system_timezone() -> str:
    # Prefer explicit system TZ configuration when available.
    env_tz = os.environ.get("TZ", "").strip()
    if env_tz:
        try:
            ZoneInfo(env_tz)
            return env_tz
        except ZoneInfoNotFoundError:
            pass

    local_tz = datetime.now().astimezone().tzinfo
    zone_key = getattr(local_tz, "key", None)
    if isinstance(zone_key, str) and zone_key:
        return zone_key

    tz_name = datetime.now().astimezone().tzname() or ""
    if tz_name:
        try:
            ZoneInfo(tz_name)
            return tz_name
        except ZoneInfoNotFoundError:
            pass
    return "UTC"


class Settings(BaseSettings):
    # Ignore unrelated keys in .env (e.g. frontend-only variables) so API startup
    # does not fail when the repository uses a shared dotenv file.
    model_config = SettingsConfigDict(
        env_prefix="SKITTER_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    db_url: str = Field(default="postgresql+asyncpg://postgres:postgres@localhost:5432/skitter")
    providers: list[ProviderConfig] = Field(default_factory=list)
    models: list[ModelConfig] = Field(default_factory=list)
    mcp_servers: list[MCPServerConfig] = Field(default_factory=list)
    main_model: list[str] = Field(default_factory=list)
    heartbeat_model: list[str] = Field(default_factory=list)
    reasoning_enabled: bool = Field(default=True)
    openai_use_responses_api: bool = Field(default=True)
    openai_output_version: str = Field(default="responses/v1")
    openai_reasoning_effort: str = Field(default="medium")
    openai_reasoning_summary: str = Field(default="auto")
    anthropic_thinking_budget_tokens: int = Field(default=2048)
    anthropic_output_version: str = Field(default="")

    embeddings_api_base: str = Field(default="")
    embeddings_api_key: str = Field(default="")
    embeddings_model: str = Field(default="text-embedding-3-small")
    embeddings_target_chunk_chars: int = Field(default=600)
    embeddings_max_chunk_chars: int = Field(default=800)
    memory_max_distance: float = Field(default=0.7)

    brave_api_key: str = Field(default="")
    brave_api_base: str = Field(default="https://api.search.brave.com/res/v1/web/search")
    web_search_engine: str = Field(default="brave")
    web_search_searxng_api_base: str = Field(default="http://localhost:8080/search")
    browser_executable: str = Field(default="")

    scheduler_timezone: str = Field(default_factory=_detect_system_timezone)

    discord_token: str = Field(default="")
    user_approved_message: str = Field(default="Hey! I just came online. Who am I? Who are you?")

    heartbeat_enabled: bool = Field(default=True)
    heartbeat_interval_minutes: int = Field(default=30)
    heartbeat_history_runs: int = Field(default=5)
    heartbeat_prompt: str = Field(
        default=(
            "Read HEARTBEAT.md if it exists (workspace context). Follow it strictly. "
            "Do not infer or repeat old tasks from prior chats. If nothing needs attention, reply HEARTBEAT_OK."
        )
    )
    heartbeat_quiet_hours_start: str = Field(default="23:00")
    heartbeat_quiet_hours_end: str = Field(default="08:00")

    workspace_root: str = Field(default="workspace")
    workspace_skeleton_root: str = Field(default="workspace-skeleton")
    host_workspace_root: str = Field(default="")
    skills_root: str = Field(default="skills")
    host_skills_root: str = Field(default="")

    sandbox_base_url: str = Field(default="http://localhost:9080")
    sandbox_api_key: str = Field(default="")
    sandbox_image: str = Field(default="skitter-sandbox")
    sandbox_network: str = Field(default="")
    sandbox_port: int = Field(default=9080)
    sandbox_idle_seconds: int = Field(default=900)
    sandbox_idle_check_seconds: int = Field(default=60)
    sandbox_container_prefix: str = Field(default="skitter-sandbox")
    sandbox_connect_retries: int = Field(default=5)
    sandbox_connect_backoff: float = Field(default=0.5)
    executors_auto_docker_default: bool = Field(default=True)

    max_sub_agents: int = Field(default=4)
    subagent_timeout_seconds: int = Field(default=180)
    subagent_max_tasks_per_batch: int = Field(default=8)
    subagent_transcript_chars: int = Field(default=12000)
    tool_approval_required: bool = Field(default=True)
    tool_approval_tools: str = Field(
        default=(
            "read,write,edit,list,delete,download,transfer_file,attach_file,"
            "browser,browser_action,sub_agent,sub_agent_batch,job_start,shell,create_secret,mcp_call"
        )
    )
    approval_secrets_required: str = Field(default="always")
    cors_origins: str = Field(default="http://localhost:5173")
    # Env-only: API key required for /v1/* HTTP endpoints.
    api_key: str = Field(default="", exclude=True)
    # Env-only: one-time bootstrap code to initialize first non-discord client.
    bootstrap_code: str = Field(default="", exclude=True)
    config_path: str = Field(default="config.yaml")
    prompt_path: str = Field(default="system_prompt.md")
    prompt_context_files: str = Field(
        default="AGENTS.md,TOOLS.md,IDENTITY.md,USER.md,BOOTSTRAP.md"
    )
    context_max_tool_messages: int = Field(default=10)
    context_max_chat_messages: int = Field(default=80)
    context_compact_every_messages: int = Field(default=8)
    log_level: str = Field(default="INFO")
    limits_max_tool_calls: int = Field(default=12)
    limits_max_runtime_seconds: int = Field(default=180)
    limits_max_cost_usd: float = Field(default=2.0)
    jobs_enabled: bool = Field(default=True)
    jobs_poll_interval_seconds: int = Field(default=2)
    jobs_max_concurrent: int = Field(default=2)
    job_limits_max_tool_calls: int = Field(default=32)
    job_limits_max_runtime_seconds: int = Field(default=900)
    job_limits_max_cost_usd: float = Field(default=5.0)
    discord_progress_updates: bool = Field(default=True)
    discord_progress_interval_seconds: int = Field(default=3)

    # Env-only: do not add to config schema or UI.
    secrets_master_key: str = Field(default="", exclude=True)

    @field_validator("log_level", mode="before")
    @classmethod
    def _normalize_log_level(cls, value: Any) -> str:
        text = str(value or "INFO").strip().upper()
        return text or "INFO"

    @field_validator("web_search_engine", mode="before")
    @classmethod
    def _normalize_web_search_engine(cls, value: Any) -> str:
        text = str(value or "brave").strip().lower()
        return text or "brave"

    @field_validator("main_model", "heartbeat_model", mode="before")
    @classmethod
    def _normalize_model_selector_field(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        if isinstance(value, (list, tuple, set)):
            out: list[str] = []
            for item in value:
                text = str(item).strip()
                if text:
                    out.append(text)
            return out
        text = str(value).strip()
        return [text] if text else []


def _config_path() -> Path:
    return Path(settings.config_path)


def _load_yaml_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError:
        return {}
    if not isinstance(data, dict):
        return {}
    return data


def _write_yaml_config(path: Path, data: dict[str, Any]) -> None:
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def apply_settings_update(values: dict[str, Any]) -> Settings:
    incoming = dict(values)
    raw_models = incoming.get("models")
    raw_providers = incoming.get("providers")
    if isinstance(raw_models, list):
        if (not isinstance(raw_providers, list) or not raw_providers) and any(
            _looks_like_legacy_model_config(item) for item in raw_models
        ):
            converted_providers, converted_models = _convert_legacy_model_layout(raw_models)
            incoming["providers"] = converted_providers
            incoming["models"] = converted_models

    base = settings.model_dump()
    merged = {**base, **incoming}
    validated = Settings.model_validate(merged)
    validated.main_model = _normalize_model_selector_list(validated.main_model, validated.models)
    validated.heartbeat_model = _normalize_model_selector_list(validated.heartbeat_model, validated.models)
    for field_name in Settings.model_fields:
        setattr(settings, field_name, getattr(validated, field_name))
    return validated


settings = Settings()
_env_overrides = {
    field_name: getattr(settings, field_name)
    for field_name in settings.model_fields_set
    if field_name in Settings.model_fields
}
_yaml_config = _load_yaml_config(_config_path())
if _yaml_config:
    flat = flatten_config(_yaml_config)
    if "providers" in _yaml_config:
        flat["providers"] = _yaml_config.get("providers")
    if "models" in _yaml_config:
        flat["models"] = _yaml_config.get("models")
    if "main_model" in _yaml_config:
        flat["main_model"] = _yaml_config.get("main_model")
    if "heartbeat_model" in _yaml_config:
        flat["heartbeat_model"] = _yaml_config.get("heartbeat_model")
    mcp_cfg = _yaml_config.get("mcp")
    if isinstance(mcp_cfg, dict) and isinstance(mcp_cfg.get("servers"), list):
        flat["mcp_servers"] = mcp_cfg.get("servers")
    elif "mcp_servers" in _yaml_config and isinstance(_yaml_config.get("mcp_servers"), list):
        flat["mcp_servers"] = _yaml_config.get("mcp_servers")
    apply_settings_update(flat)
    # Keep explicit SKITTER_* env vars authoritative over YAML values.
    if _env_overrides:
        apply_settings_update(_env_overrides)
else:
    try:
        _write_yaml_config(_config_path(), build_config_from_settings(settings))
    except OSError:
        pass
