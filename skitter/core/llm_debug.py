from __future__ import annotations

import logging
import re
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler


_THINKING_TAG_RE = re.compile(r"<thinking>(.*?)</thinking>", re.IGNORECASE | re.DOTALL)


def _walk_reasoning_values(value: Any, out: list[str], *, depth: int = 0, max_items: int = 64) -> None:
    if len(out) >= max_items or depth > 8:
        return
    if value is None:
        return
    if isinstance(value, str):
        text = value.strip()
        if text:
            out.append(text)
        return
    if isinstance(value, list):
        for item in value:
            _walk_reasoning_values(item, out, depth=depth + 1, max_items=max_items)
            if len(out) >= max_items:
                return
        return
    if isinstance(value, dict):
        block_type = str(value.get("type") or "").lower()
        is_reasoning_block = "reason" in block_type or "think" in block_type
        for key, nested in value.items():
            key_lower = str(key).lower()
            if "reason" in key_lower or "think" in key_lower:
                _walk_reasoning_values(nested, out, depth=depth + 1, max_items=max_items)
            elif is_reasoning_block and key_lower in {"text", "content", "summary", "output_text", "explanation"}:
                _walk_reasoning_values(nested, out, depth=depth + 1, max_items=max_items)
            if len(out) >= max_items:
                return
        return


class ThinkingDebugCallback(BaseCallbackHandler):
    """Debug callback to log provider reasoning/thinking payloads from raw LLM results."""

    def __init__(
        self,
        *,
        logger: logging.Logger,
        provider_api_type: str,
        model_name: str,
        session_id: str,
        run_id: str,
        max_chars: int = 8000,
    ) -> None:
        super().__init__()
        self._logger = logger
        self._provider_api_type = provider_api_type
        self._model_name = model_name
        self._session_id = session_id
        self._run_id = run_id
        self._max_chars = max(256, int(max_chars))

    def _extract_from_content(self, content: Any, out: list[str]) -> None:
        if isinstance(content, str):
            for match in _THINKING_TAG_RE.findall(content):
                _walk_reasoning_values(match, out)
            return
        if not isinstance(content, list):
            return
        for block in content:
            if not isinstance(block, dict):
                continue
            block_type = str(block.get("type") or "").lower()
            if "reason" in block_type or "think" in block_type:
                _walk_reasoning_values(block, out)

    @staticmethod
    def _extract_reasoning_fields(payload: Any, out: list[str]) -> None:
        if not isinstance(payload, dict):
            return
        for key, value in payload.items():
            key_lower = str(key).lower()
            if "reason" in key_lower or "think" in key_lower:
                _walk_reasoning_values(value, out)

    def _extract_reasoning(self, response: Any) -> list[str]:
        chunks: list[str] = []

        llm_output = getattr(response, "llm_output", None)
        self._extract_reasoning_fields(llm_output, chunks)

        generations = getattr(response, "generations", None) or []
        for batch in generations:
            for generation in batch:
                message = getattr(generation, "message", None)
                if message is not None:
                    self._extract_from_content(getattr(message, "content", None), chunks)
                    self._extract_reasoning_fields(getattr(message, "additional_kwargs", None), chunks)
                    self._extract_reasoning_fields(getattr(message, "response_metadata", None), chunks)
                self._extract_reasoning_fields(getattr(generation, "generation_info", None), chunks)
                self._extract_reasoning_fields(getattr(generation, "reasoning_content", None), chunks)
                self._extract_reasoning_fields(getattr(generation, "reasoning", None), chunks)

        deduped: list[str] = []
        seen: set[str] = set()
        for chunk in chunks:
            normalized = chunk.strip()
            if not normalized:
                continue
            if normalized in seen:
                continue
            seen.add(normalized)
            deduped.append(normalized)
        return deduped

    def on_llm_end(self, response, *, run_id, parent_run_id=None, tags=None, **kwargs):  # type: ignore[override]
        chunks = self._extract_reasoning(response)
        if not chunks:
            self._logger.info(
                "LLM thinking debug: no reasoning content found (provider=%s model=%s session=%s run=%s llm_run=%s)",
                self._provider_api_type,
                self._model_name,
                self._session_id,
                self._run_id,
                str(run_id),
            )
            return
        preview = " | ".join(chunk.replace("\n", " ") for chunk in chunks)
        if len(preview) > self._max_chars:
            preview = preview[: self._max_chars - 3] + "..."
        self._logger.info(
            "LLM thinking debug (provider=%s model=%s session=%s run=%s llm_run=%s): %s",
            self._provider_api_type,
            self._model_name,
            self._session_id,
            self._run_id,
            str(run_id),
            preview,
        )
