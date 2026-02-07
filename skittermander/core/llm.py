from __future__ import annotations

from dataclasses import dataclass

from langchain_openai import ChatOpenAI

from .config import settings


@dataclass
class ResolvedModel:
    name: str
    model: str
    api_base: str
    api_key: str
    input_cost_per_1m: float = 0.0
    output_cost_per_1m: float = 0.0


def list_models() -> list[ResolvedModel]:
    if not settings.models:
        return []
    return [
        ResolvedModel(
            name=model.name,
            model=model.model,
            api_base=model.api_base,
            api_key=model.api_key,
            input_cost_per_1m=model.input_cost_per_1m,
            output_cost_per_1m=model.output_cost_per_1m,
        )
        for model in settings.models
    ]


def _find_model(name: str) -> ResolvedModel | None:
    if not settings.models:
        return None
    for model in settings.models:
        if model.name.lower() == name.lower():
            return ResolvedModel(
                name=model.name,
                model=model.model,
                api_base=model.api_base,
                api_key=model.api_key,
                input_cost_per_1m=model.input_cost_per_1m,
                output_cost_per_1m=model.output_cost_per_1m,
            )
    return None


def resolve_model_name(name: str | None, purpose: str = "main") -> str:
    if name:
        return name
    if purpose == "heartbeat" and settings.heartbeat_model:
        return settings.heartbeat_model
    if settings.main_model:
        return settings.main_model
    if settings.models:
        return settings.models[0].name
    return "default"


def resolve_model(name: str | None = None, purpose: str = "main") -> ResolvedModel:
    if not settings.models:
        raise RuntimeError("No models are configured.")
    resolved_name = resolve_model_name(name, purpose=purpose)
    model = _find_model(resolved_name)
    if model is not None:
        return model
    fallback = settings.models[0]
    return ResolvedModel(
        name=fallback.name,
        model=fallback.model,
        api_base=fallback.api_base,
        api_key=fallback.api_key,
        input_cost_per_1m=fallback.input_cost_per_1m,
        output_cost_per_1m=fallback.output_cost_per_1m,
    )


def build_llm(model_name: str | None = None, purpose: str = "main") -> ChatOpenAI:
    resolved = resolve_model(model_name, purpose=purpose)
    return ChatOpenAI(
        model=resolved.model,
        base_url=resolved.api_base,
        api_key=resolved.api_key,
        temperature=0.2,
    )
