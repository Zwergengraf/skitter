from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import httpx


class ApiError(RuntimeError):
    """Raised when the API returns an unexpected response."""


@dataclass(slots=True)
class StreamEvent:
    event: str
    data: dict[str, Any]


class SkitterApiClient:
    def __init__(self, api_url: str, api_key: str | None = None, timeout: float = 180.0) -> None:
        base = api_url.rstrip("/")
        headers: dict[str, str] = {}
        if api_key:
            headers["x-api-key"] = api_key
        self._http = httpx.AsyncClient(base_url=base, timeout=timeout, headers=headers)

    async def aclose(self) -> None:
        await self._http.aclose()

    async def create_session(
        self,
        user_id: str,
        *,
        origin: str = "tui",
        reuse_active: bool = True,
    ) -> str:
        response = await self._http.post(
            "/v1/sessions",
            json={"user_id": user_id, "origin": origin, "reuse_active": reuse_active},
        )
        self._raise(response)
        payload = response.json()
        session_id = str(payload.get("id") or "").strip()
        if not session_id:
            raise ApiError("Missing session id in /v1/sessions response")
        return session_id

    async def send_message(
        self,
        *,
        session_id: str,
        user_id: str,
        text: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = {
            "session_id": session_id,
            "user_id": user_id,
            "text": text,
            "metadata": metadata or {},
        }
        response = await self._http.post("/v1/messages", json=payload)
        self._raise(response)
        body = response.json()
        if not isinstance(body, dict):
            raise ApiError("Invalid /v1/messages response payload")
        return body

    async def get_session_detail(self, session_id: str) -> dict[str, Any]:
        response = await self._http.get(f"/v1/sessions/{session_id}/detail")
        self._raise(response)
        body = response.json()
        if not isinstance(body, dict):
            raise ApiError("Invalid /v1/sessions/{id}/detail response payload")
        return body

    async def download_attachment(self, path_or_url: str) -> bytes:
        target = (path_or_url or "").strip()
        if not target:
            raise ApiError("Attachment URL is missing")
        response = await self._http.get(target)
        self._raise(response)
        return response.content

    async def stream_events(
        self,
        *,
        session_id: str,
        stop_event: asyncio.Event,
    ) -> AsyncIterator[StreamEvent]:
        params = {"session_id": session_id}
        headers = {"accept": "text/event-stream"}
        async with self._http.stream("GET", "/v1/events/stream", params=params, headers=headers) as response:
            self._raise(response)
            current_event = "message"
            data_lines: list[str] = []

            async for line in response.aiter_lines():
                if stop_event.is_set():
                    return
                if line == "":
                    if data_lines:
                        raw = "\n".join(data_lines)
                        data_lines.clear()
                        payload = self._decode_event_data(raw)
                        yield StreamEvent(event=current_event, data=payload)
                    current_event = "message"
                    continue
                if line.startswith(":"):
                    continue
                if line.startswith("event:"):
                    current_event = line[6:].strip() or "message"
                    continue
                if line.startswith("data:"):
                    data_lines.append(line[5:].lstrip())

    def absolute_url(self, path_or_url: str) -> str:
        value = (path_or_url or "").strip()
        if not value:
            return value
        if value.startswith("http://") or value.startswith("https://"):
            return value
        if not value.startswith("/"):
            value = "/" + value
        return str(self._http.base_url.join(value))

    @staticmethod
    def _decode_event_data(raw: str) -> dict[str, Any]:
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            return {"raw": raw}
        if isinstance(value, dict):
            return value
        return {"value": value}

    @staticmethod
    def _raise(response: httpx.Response) -> None:
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text.strip()
            message = f"API {exc.response.status_code}: {detail or exc!s}"
            raise ApiError(message) from exc
