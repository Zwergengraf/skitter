from __future__ import annotations

from dataclasses import dataclass

from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI

from .config import settings


@dataclass
class ResolvedModel:
    name: str
    provider: str
    provider_api_type: str
    model: str
    api_base: str
    api_key: str
    input_cost_per_1m: float = 0.0
    output_cost_per_1m: float = 0.0


def _normalized_name(provider: str, model_name: str) -> str:
    return f"{provider}/{model_name}"


def _resolve_all_models() -> list[ResolvedModel]:
    if not settings.providers or not settings.models:
        return []
    provider_map = {provider.name.lower(): provider for provider in settings.providers}
    resolved: list[ResolvedModel] = []
    for model in settings.models:
        provider = provider_map.get(model.provider.lower())
        if provider is None:
            continue
        resolved.append(
            ResolvedModel(
                name=_normalized_name(provider.name, model.name),
                provider=provider.name,
                provider_api_type=provider.api_type,
                model=model.model,
                api_base=provider.api_base,
                api_key=provider.api_key,
                input_cost_per_1m=model.input_cost_per_1m,
                output_cost_per_1m=model.output_cost_per_1m,
            )
        )
    return resolved


def list_models() -> list[ResolvedModel]:
    return _resolve_all_models()


def _find_model(name: str) -> ResolvedModel | None:
    all_models = _resolve_all_models()
    if not all_models:
        return None
    for model in all_models:
        if model.name.lower() == name.lower():
            return model
    if "/" not in name:
        matches = [model for model in all_models if model.name.split("/", 1)[1].lower() == name.lower()]
        if len(matches) == 1:
            return matches[0]
    return None


def resolve_model_name(name: str | None, purpose: str = "main") -> str:
    if name:
        match = _find_model(name)
        if match is not None:
            return match.name
        return name
    if purpose == "heartbeat" and settings.heartbeat_model:
        match = _find_model(settings.heartbeat_model)
        if match is not None:
            return match.name
        return settings.heartbeat_model
    if settings.main_model:
        match = _find_model(settings.main_model)
        if match is not None:
            return match.name
        return settings.main_model
    all_models = _resolve_all_models()
    if all_models:
        return all_models[0].name
    return "default"


def resolve_model(name: str | None = None, purpose: str = "main") -> ResolvedModel:
    all_models = _resolve_all_models()
    if not all_models:
        raise RuntimeError("No models are configured.")
    resolved_name = resolve_model_name(name, purpose=purpose)
    model = _find_model(resolved_name)
    if model is not None:
        return model
    return all_models[0]


def _build_openai_llm(resolved: ResolvedModel) -> BaseChatModel:
    return ChatOpenAI(
        model=resolved.model,
        base_url=resolved.api_base,
        api_key=resolved.api_key,
    )


def _build_anthropic_llm(resolved: ResolvedModel) -> BaseChatModel:
    try:
        from langchain_anthropic import ChatAnthropic
    except ImportError as exc:
        raise RuntimeError(
            "Anthropic provider configured but 'langchain-anthropic' is not installed. "
            "Install it to use providers with api_type=anthropic."
        ) from exc

    kwargs = {"model": resolved.model}
    if resolved.api_key:
        kwargs["api_key"] = resolved.api_key
    if resolved.api_base:
        kwargs["base_url"] = resolved.api_base
    try:
        return ChatAnthropic(**kwargs)
    except TypeError:
        # Compatibility fallback for older versions that use anthropic_* keyword names.
        fallback = {"model": resolved.model}
        if resolved.api_key:
            fallback["anthropic_api_key"] = resolved.api_key
        if resolved.api_base:
            fallback["anthropic_api_url"] = resolved.api_base
        return ChatAnthropic(**fallback)


def build_llm(model_name: str | None = None, purpose: str = "main") -> BaseChatModel:
    resolved = resolve_model(model_name, purpose=purpose)
    if resolved.provider_api_type == "anthropic":
        return _build_anthropic_llm(resolved)
    return _build_openai_llm(resolved)
