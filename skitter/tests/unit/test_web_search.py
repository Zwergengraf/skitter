from __future__ import annotations

import pytest

from skitter.core.config import settings
from skitter.core.web_search import (
    WebSearchConfigError,
    _parse_brave_results,
    _parse_searxng_results,
    _selected_engine,
)


def test_parse_brave_results() -> None:
    payload = {
        "web": {
            "results": [
                {"title": "One", "url": "https://example.com/1", "description": "First"},
                {"title": "Two", "url": "https://example.com/2", "description": "Second"},
            ]
        }
    }

    results = _parse_brave_results(payload)

    assert len(results) == 2
    assert results[0]["title"] == "One"
    assert results[1]["url"] == "https://example.com/2"


def test_parse_searxng_results() -> None:
    payload = {
        "results": [
            {"title": "One", "url": "https://example.com/1", "content": "First"},
            {"title": "Two", "url": "https://example.com/2", "description": "Second"},
        ]
    }

    results = _parse_searxng_results(payload)

    assert len(results) == 2
    assert results[0]["snippet"] == "First"
    assert results[1]["snippet"] == "Second"


def test_selected_engine_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "web_search_engine", "searxng")
    assert _selected_engine() == "searxng"

    monkeypatch.setattr(settings, "web_search_engine", "brave")
    assert _selected_engine() == "brave"

    monkeypatch.setattr(settings, "web_search_engine", "duckduckgo")
    with pytest.raises(WebSearchConfigError):
        _selected_engine()
