from __future__ import annotations

import pytest

import skittermander.core.llm as llm
from skittermander.core.config import ModelConfig, ProviderConfig, settings


def _set_models(
    monkeypatch: pytest.MonkeyPatch,
    *,
    providers: list[ProviderConfig],
    models: list[ModelConfig],
    main_model: str = "",
    heartbeat_model: str = "",
) -> None:
    monkeypatch.setattr(settings, "providers", providers)
    monkeypatch.setattr(settings, "models", models)
    monkeypatch.setattr(settings, "main_model", main_model)
    monkeypatch.setattr(settings, "heartbeat_model", heartbeat_model)


def test_resolve_model_name_and_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_models(
        monkeypatch,
        providers=[
            ProviderConfig(name="provider", api_type="openai", api_base="http://localhost:1", api_key="x"),
        ],
        models=[
            ModelConfig(name="main", provider="provider", model_id="m-main"),
            ModelConfig(name="fast", provider="provider", model_id="m-fast"),
        ],
        main_model="provider/main",
        heartbeat_model="provider/fast",
    )

    assert llm.resolve_model_name(None, purpose="main") == "provider/main"
    assert llm.resolve_model_name(None, purpose="heartbeat") == "provider/fast"
    assert llm.resolve_model_name("main", purpose="main") == "provider/main"
    assert llm.resolve_model_name("provider/fast", purpose="main") == "provider/fast"
    assert [item.name for item in llm.list_models()] == ["provider/main", "provider/fast"]


def test_resolve_model_raises_when_no_models(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_models(monkeypatch, providers=[], models=[])

    with pytest.raises(RuntimeError, match="No models are configured"):
        llm.resolve_model()


def test_build_llm_dispatches_by_provider_type(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_models(
        monkeypatch,
        providers=[
            ProviderConfig(name="openai-p", api_type="openai", api_base="http://localhost:1", api_key="k1"),
            ProviderConfig(name="anthropic-p", api_type="anthropic", api_base="http://localhost:2", api_key="k2"),
        ],
        models=[
            ModelConfig(name="chat", provider="openai-p", model_id="openai-chat"),
            ModelConfig(name="reasoning", provider="anthropic-p", model_id="anthropic-reasoning"),
        ],
    )
    monkeypatch.setattr(llm, "_build_openai_llm", lambda resolved: {"provider": "openai", "name": resolved.name})
    monkeypatch.setattr(
        llm,
        "_build_anthropic_llm",
        lambda resolved: {"provider": "anthropic", "name": resolved.name},
    )

    openai_result = llm.build_llm("openai-p/chat")
    anthropic_result = llm.build_llm("anthropic-p/reasoning")

    assert openai_result == {"provider": "openai", "name": "openai-p/chat"}
    assert anthropic_result == {"provider": "anthropic", "name": "anthropic-p/reasoning"}


def test_reasoning_overrides_are_deep_merged() -> None:
    resolved = llm.ResolvedModel(
        name="provider/main",
        provider="provider",
        provider_api_type="openai",
        model="m",
        api_base="http://localhost",
        api_key="x",
        reasoning={
            "openai": {"summary": "detailed", "thinking": {"budget_tokens": 2048}},
            "enabled": False,
            "thinking": {"type": "enabled"},
        },
    )

    override = llm._model_reasoning_override(resolved, "openai")

    assert override["summary"] == "detailed"
    assert override["enabled"] is False
    assert override["thinking"] == {"budget_tokens": 2048, "type": "enabled"}
