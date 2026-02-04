from __future__ import annotations

from langchain_openai import ChatOpenAI

from .config import settings


def build_llm() -> ChatOpenAI:
    return ChatOpenAI(
        model=settings.openai_model,
        base_url=settings.openai_api_base,
        api_key=settings.openai_api_key,
        temperature=0.2,
    )
