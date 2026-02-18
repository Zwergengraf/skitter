from __future__ import annotations

from dataclasses import dataclass
from typing import Any

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
    reasoning: dict[str, Any] | None = None


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
                reasoning=dict(model.reasoning or {}),
            )
        )
    return resolved


def _deep_merge_dict(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if (
            key in merged
            and isinstance(merged[key], dict)
            and isinstance(value, dict)
        ):
            merged[key] = _deep_merge_dict(merged[key], value)
        else:
            merged[key] = value
    return merged


def _model_reasoning_override(resolved: ResolvedModel, provider_api_type: str) -> dict[str, Any]:
    raw = resolved.reasoning or {}
    if not isinstance(raw, dict):
        return {}
    provider = provider_api_type.lower().strip()
    scoped: dict[str, Any] = {}
    provider_specific = raw.get(provider)
    if isinstance(provider_specific, dict):
        scoped = _deep_merge_dict(scoped, provider_specific)
    top_level = {k: v for k, v in raw.items() if k not in {"openai", "anthropic"}}
    if top_level:
        scoped = _deep_merge_dict(scoped, top_level)
    return scoped


def _openai_reasoning_config(resolved: ResolvedModel) -> dict[str, Any]:
    defaults = {
        "enabled": bool(settings.reasoning_enabled),
        "use_responses_api": bool(settings.openai_use_responses_api),
        "output_version": str(settings.openai_output_version or "").strip(),
        "effort": str(settings.openai_reasoning_effort or "").strip(),
        "summary": str(settings.openai_reasoning_summary or "").strip(),
    }
    return _deep_merge_dict(defaults, _model_reasoning_override(resolved, "openai"))


def _anthropic_reasoning_config(resolved: ResolvedModel) -> dict[str, Any]:
    defaults = {
        "enabled": bool(settings.reasoning_enabled),
        "output_version": str(settings.anthropic_output_version or "").strip(),
        "thinking": {
            "type": "enabled",
            "budget_tokens": max(256, int(settings.anthropic_thinking_budget_tokens)),
        },
    }
    merged = _deep_merge_dict(defaults, _model_reasoning_override(resolved, "anthropic"))
    # Allow direct budget_tokens override without nesting.
    if "budget_tokens" in merged:
        thinking = dict(merged.get("thinking") or {})
        thinking["budget_tokens"] = merged["budget_tokens"]
        merged["thinking"] = thinking
    return merged


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


def _normalize_selector(name: str) -> str:
    selector = (name or "").strip()
    if not selector:
        return ""
    match = _find_model(selector)
    if match is not None:
        return match.name
    return selector


def _selectors_from_config(value: Any) -> list[str]:
    if not value:
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


def _default_model_chain(purpose: str) -> list[str]:
    def normalize_many(items: list[str]) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()
        for item in items:
            normalized = _normalize_selector(item)
            if not normalized:
                continue
            key = normalized.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(normalized)
        return out

    if purpose == "heartbeat":
        preferred = _selectors_from_config(settings.heartbeat_model)
        if preferred:
            return normalize_many(preferred)
    preferred = _selectors_from_config(settings.main_model)
    if preferred:
        return normalize_many(preferred)
    all_models = _resolve_all_models()
    if all_models:
        return [all_models[0].name]
    return []


def resolve_model_candidates(name: str | None, purpose: str = "main") -> list[str]:
    chain = _default_model_chain(purpose)
    if name:
        primary = _normalize_selector(name)
        if not primary:
            return chain
        if not chain:
            return [primary]
        for idx, candidate in enumerate(chain):
            if candidate.lower() == primary.lower():
                return chain[idx:]
        return [primary]
    if chain:
        return chain
    all_models = _resolve_all_models()
    if all_models:
        return [all_models[0].name]
    return ["default"]


def resolve_model_name(name: str | None, purpose: str = "main") -> str:
    candidates = resolve_model_candidates(name, purpose=purpose)
    if candidates:
        return candidates[0]
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
    kwargs: dict[str, object] = {
        "model": resolved.model,
        "base_url": resolved.api_base,
        "api_key": resolved.api_key,
    }
    reasoning_cfg = _openai_reasoning_config(resolved)
    if bool(reasoning_cfg.get("enabled")):
        effort = str(reasoning_cfg.get("effort") or "").strip()
        summary = str(reasoning_cfg.get("summary") or "").strip()
        if bool(reasoning_cfg.get("use_responses_api")):
            kwargs["use_responses_api"] = True
            output_version = str(reasoning_cfg.get("output_version") or "").strip()
            if output_version:
                kwargs["output_version"] = output_version
            reasoning: dict[str, str] = {}
            if effort:
                reasoning["effort"] = effort
            if summary:
                reasoning["summary"] = summary
            if reasoning:
                kwargs["reasoning"] = reasoning
        elif effort:
            kwargs["reasoning_effort"] = effort
    return ChatOpenAI(**kwargs)


def _build_anthropic_llm(resolved: ResolvedModel) -> BaseChatModel:
    try:
        from langchain_anthropic import ChatAnthropic
    except ImportError as exc:
        raise RuntimeError(
            "Anthropic provider configured but 'langchain-anthropic' is not installed. "
            "Install it to use providers with api_type=anthropic."
        ) from exc

    kwargs: dict[str, object] = {"model": resolved.model}
    if resolved.api_key:
        kwargs["api_key"] = resolved.api_key
    if resolved.api_base:
        kwargs["base_url"] = resolved.api_base
    reasoning_cfg = _anthropic_reasoning_config(resolved)
    if bool(reasoning_cfg.get("enabled")):
        thinking = dict(reasoning_cfg.get("thinking") or {})
        budget_tokens = max(256, int(thinking.get("budget_tokens", settings.anthropic_thinking_budget_tokens)))
        thinking["budget_tokens"] = budget_tokens
        thinking["type"] = str(thinking.get("type") or "enabled")
        kwargs["thinking"] = thinking
        output_version = str(reasoning_cfg.get("output_version") or "").strip()
        if output_version:
            kwargs["output_version"] = output_version
    try:
        return ChatAnthropic(**kwargs)
    except TypeError:
        # Compatibility fallback for older versions that use anthropic_* keyword names.
        fallback: dict[str, object] = {"model": resolved.model}
        if resolved.api_key:
            fallback["anthropic_api_key"] = resolved.api_key
        if resolved.api_base:
            fallback["anthropic_api_url"] = resolved.api_base
        if bool(reasoning_cfg.get("enabled")):
            thinking = dict(reasoning_cfg.get("thinking") or {})
            budget_tokens = max(256, int(thinking.get("budget_tokens", settings.anthropic_thinking_budget_tokens)))
            thinking["budget_tokens"] = budget_tokens
            thinking["type"] = str(thinking.get("type") or "enabled")
            fallback["thinking"] = thinking
            output_version = str(reasoning_cfg.get("output_version") or "").strip()
            if output_version:
                fallback["output_version"] = output_version
        return ChatAnthropic(**fallback)


def build_llm(model_name: str | None = None, purpose: str = "main") -> BaseChatModel:
    resolved = resolve_model(model_name, purpose=purpose)
    if resolved.provider_api_type == "anthropic":
        return _build_anthropic_llm(resolved)
    return _build_openai_llm(resolved)
