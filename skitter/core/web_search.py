from __future__ import annotations

from typing import Any

import httpx

from .config import settings


class WebSearchError(RuntimeError):
    pass


class WebSearchConfigError(WebSearchError):
    pass


def _selected_engine() -> str:
    engine = str(settings.web_search_engine or "brave").strip().lower()
    if engine in {"brave", "searxng"}:
        return engine
    raise WebSearchConfigError(
        f"Unsupported web search engine '{engine}'. Expected one of: brave, searxng."
    )


def _normalize_count(count: int) -> int:
    return max(1, min(int(count), 10))


def _parse_brave_results(data: dict[str, Any]) -> list[dict[str, str | None]]:
    results: list[dict[str, str | None]] = []
    for item in (data.get("web", {}).get("results") or []):
        if not isinstance(item, dict):
            continue
        results.append(
            {
                "title": item.get("title"),
                "url": item.get("url"),
                "snippet": item.get("description"),
            }
        )
    return results


def _parse_searxng_results(data: dict[str, Any]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for item in (data.get("results") or []):
        if not isinstance(item, dict):
            continue
        score = item.get("score")
        if not isinstance(score, (int, float)):
            score = None
        results.append(
            {
                "title": item.get("title"),
                "url": item.get("url"),
                "snippet": item.get("content") or item.get("description"),
                "score": score,
            }
        )
    return results


async def _brave_search(
    *,
    query: str,
    count: int,
) -> dict[str, Any]:
    if not settings.brave_api_key:
        raise WebSearchConfigError("Brave is selected but web_search.brave.api_key is not set.")
    params: dict[str, Any] = {
        "q": query,
        "count": _normalize_count(count),
        "country": "US",
    }

    headers = {"Accept": "application/json", "X-Subscription-Token": settings.brave_api_key}
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.get(settings.brave_api_base, params=params, headers=headers)
        resp.raise_for_status()
        data = resp.json()
    return {"engine": "brave", "query": query, "results": _parse_brave_results(data)}


async def _searxng_search(
    *,
    query: str,
    count: int,
) -> dict[str, Any]:
    base_url = str(settings.web_search_searxng_api_base or "").strip()
    if not base_url:
        raise WebSearchConfigError("SearXNG is selected but web_search.searxng.api_base is not set.")

    params: dict[str, Any] = {
        "q": query,
        "format": "json",
    }
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.get(base_url, params=params, headers={"Accept": "application/json"})
        resp.raise_for_status()
        data = resp.json()
    results = _parse_searxng_results(data)
    results.sort(
        key=lambda item: float(item.get("score"))
        if isinstance(item.get("score"), (int, float))
        else float("-inf"),
        reverse=True,
    )
    return {"engine": "searxng", "query": query, "results": results[: _normalize_count(count)]}


async def search_web(
    *,
    query: str,
    count: int = 5,
) -> dict[str, Any]:
    engine = _selected_engine()
    try:
        if engine == "searxng":
            return await _searxng_search(
                query=query,
                count=count,
            )
        return await _brave_search(
            query=query,
            count=count,
        )
    except httpx.HTTPStatusError as exc:
        detail = (exc.response.text or "").strip() or f"HTTP {exc.response.status_code}"
        raise WebSearchError(
            f"{engine} HTTP {exc.response.status_code}: {detail}"
        ) from exc
    except httpx.RequestError as exc:
        raise WebSearchError(f"{engine} request error: {exc}") from exc
