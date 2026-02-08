from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field, BaseModel
from pydantic import ConfigDict
from pydantic_settings import BaseSettings, SettingsConfigDict

from .config_schema import flatten_config, build_config_from_settings


class ModelConfig(BaseModel):
    name: str
    model: str = Field(alias="model_id")
    api_base: str = Field(default="")
    api_key: str = Field(default="")
    input_cost_per_1m: float = Field(default=0.0)
    output_cost_per_1m: float = Field(default=0.0)

    model_config = ConfigDict(populate_by_name=True, extra="ignore")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SKITTER_", env_file=".env", env_file_encoding="utf-8")

    db_url: str = Field(default="postgresql+asyncpg://postgres:postgres@localhost:5432/skittermander")
    models: list[ModelConfig] = Field(default_factory=list)
    main_model: str = Field(default="")
    heartbeat_model: str = Field(default="")

    embeddings_api_base: str = Field(default="")
    embeddings_api_key: str = Field(default="")
    embeddings_model: str = Field(default="text-embedding-3-small")
    embeddings_target_chunk_chars: int = Field(default=600)
    embeddings_max_chunk_chars: int = Field(default=800)
    memory_min_similarity: float = Field(default=0.3)

    brave_api_key: str = Field(default="")
    brave_api_base: str = Field(default="https://api.search.brave.com/res/v1/web/search")
    browser_executable: str = Field(default="")

    scheduler_timezone: str = Field(default="UTC")

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
    sandbox_image: str = Field(default="skittermander-sandbox")
    sandbox_network: str = Field(default="")
    sandbox_port: int = Field(default=9080)
    sandbox_idle_seconds: int = Field(default=900)
    sandbox_idle_check_seconds: int = Field(default=60)
    sandbox_container_prefix: str = Field(default="skitter-sandbox")
    sandbox_connect_retries: int = Field(default=5)
    sandbox_connect_backoff: float = Field(default=0.5)

    max_sub_agents: int = Field(default=4)
    subagent_timeout_seconds: int = Field(default=180)
    subagent_max_tasks_per_batch: int = Field(default=8)
    subagent_transcript_chars: int = Field(default=12000)
    tool_approval_required: bool = Field(default=True)
    tool_approval_tools: str = Field(
        default="read,write,edit,list,delete,download,browser,browser_action,sub_agent,sub_agent_batch,shell,create_secret"
    )
    cors_origins: str = Field(default="http://localhost:5173")
    # Env-only: API key required for /v1/* HTTP endpoints.
    api_key: str = Field(default="", exclude=True)
    config_path: str = Field(default="config.yaml")
    prompt_path: str = Field(default="system_prompt.md")
    prompt_context_files: str = Field(
        default="AGENTS.md,TOOLS.md,IDENTITY.md,USER.md,BOOTSTRAP.md"
    )
    context_max_tool_messages: int = Field(default=10)
    context_max_chat_messages: int = Field(default=80)
    context_compact_every_messages: int = Field(default=8)
    limits_max_tool_calls: int = Field(default=12)
    limits_max_runtime_seconds: int = Field(default=180)
    limits_max_cost_usd: float = Field(default=2.0)
    discord_progress_updates: bool = Field(default=True)
    discord_progress_interval_seconds: int = Field(default=3)

    # Env-only: do not add to config schema or UI.
    secrets_master_key: str = Field(default="", exclude=True)


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
    base = settings.model_dump()
    merged = {**base, **values}
    validated = Settings.model_validate(merged)
    for field_name in Settings.model_fields:
        setattr(settings, field_name, getattr(validated, field_name))
    return validated


settings = Settings()
_yaml_config = _load_yaml_config(_config_path())
if _yaml_config:
    flat = flatten_config(_yaml_config)
    if "models" in _yaml_config:
        flat["models"] = _yaml_config.get("models")
    if "main_model" in _yaml_config:
        flat["main_model"] = _yaml_config.get("main_model")
    if "heartbeat_model" in _yaml_config:
        flat["heartbeat_model"] = _yaml_config.get("heartbeat_model")
    apply_settings_update(flat)
else:
    try:
        _write_yaml_config(_config_path(), build_config_from_settings(settings))
    except OSError:
        pass
