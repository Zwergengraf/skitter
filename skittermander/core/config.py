from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from .config_schema import flatten_config, build_config_from_settings


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SKITTER_", env_file=".env", env_file_encoding="utf-8")

    db_url: str = Field(default="postgresql+asyncpg://postgres:postgres@localhost:5432/skittermander")
    openai_api_base: str = Field(default="https://api.openai.com/v1")
    openai_api_key: str = Field(default="")
    openai_model: str = Field(default="gpt-4o-mini")

    embeddings_api_base: str = Field(default="")
    embeddings_api_key: str = Field(default="")
    embeddings_model: str = Field(default="text-embedding-3-small")
    embeddings_max_chunk_chars: int = Field(default=800)
    memory_min_similarity: float = Field(default=0.3)

    brave_api_key: str = Field(default="")
    brave_api_base: str = Field(default="https://api.search.brave.com/res/v1/web/search")
    browser_executable: str = Field(default="")

    scheduler_timezone: str = Field(default="UTC")

    discord_token: str = Field(default="")
    user_approved_message: str = Field(default="Hey! I just came online. Who am I? Who are you?")

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
    tool_approval_required: bool = Field(default=True)
    tool_approval_tools: str = Field(default="read,write,edit,list,delete,download,browser,browser_action,sub_agent,shell")
    cors_origins: str = Field(default="http://localhost:5173")
    config_path: str = Field(default="config.yaml")
    prompt_path: str = Field(default="system_prompt.md")
    prompt_context_files: str = Field(
        default="AGENTS.md,TOOLS.md,IDENTITY.md,USER.md,BOOTSTRAP.md"
    )


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
    apply_settings_update(flatten_config(_yaml_config))
else:
    try:
        _write_yaml_config(_config_path(), build_config_from_settings(settings))
    except OSError:
        pass
