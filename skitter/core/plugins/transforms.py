from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from .hooks import HookCallResult


def result_to_patch(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, dict):
        raw = value.get("patch", value)
        return dict(raw) if isinstance(raw, dict) else None
    if is_dataclass(value):
        return asdict(value)
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        raw = model_dump()
        return dict(raw) if isinstance(raw, dict) else None
    return None


def patches_from_results(results: list[HookCallResult]) -> list[dict[str, Any]]:
    patches: list[dict[str, Any]] = []
    for result in results:
        if not result.ok:
            continue
        patch = result_to_patch(result.value)
        if patch:
            patches.append(patch)
    return patches


def merge_filters(base: dict[str, Any], patch: Any) -> dict[str, Any]:
    if not isinstance(patch, dict):
        return dict(base)
    merged = dict(base)
    for key, value in patch.items():
        if value is None:
            merged.pop(str(key), None)
        else:
            merged[str(key)] = value
    return merged


def normalized_string_set(value: Any) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, str):
        return {item.strip() for item in value.split(",") if item.strip()}
    if isinstance(value, (list, tuple, set)):
        return {str(item).strip() for item in value if str(item).strip()}
    text = str(value).strip()
    return {text} if text else set()


def normalized_int(value: Any, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback
