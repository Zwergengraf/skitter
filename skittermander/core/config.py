from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


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

    workspace_root: str = Field(default="workspace")
    skills_root: str = Field(default="skills")

    sandbox_base_url: str = Field(default="http://localhost:9080")
    sandbox_api_key: str = Field(default="")

    max_sub_agents: int = Field(default=4)
    tool_approval_required: bool = Field(default=True)
    tool_approval_tools: str = Field(default="filesystem,browser,browser_action,sub_agent,shell")


settings = Settings()
