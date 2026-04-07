from __future__ import annotations

import asyncio
import json
import base64
import mimetypes
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx


class ApiError(RuntimeError):
    """Raised when the API returns an unexpected response."""


@dataclass(slots=True)
class StreamEvent:
    event: str
    data: dict[str, Any]


@dataclass(slots=True)
class AuthUser:
    id: str
    display_name: str
    approved: bool
    default_profile_id: str | None = None
    default_profile_slug: str | None = None


@dataclass(slots=True)
class AgentProfile:
    id: str
    slug: str
    name: str
    status: str
    is_default: bool


@dataclass(slots=True)
class CommandResult:
    ok: bool
    message: str
    data: dict[str, Any]


@dataclass(slots=True)
class ToolRun:
    id: str
    tool: str
    status: str
    created_at: str
    session_id: str
    requested_by: str
    approved_by: str | None
    input: dict[str, Any]
    output: dict[str, Any]


@dataclass(slots=True)
class UserPrompt:
    id: str
    session_id: str
    question: str
    choices: list[str]
    allow_free_text: bool
    status: str
    created_at: str


class SkitterApiClient:
    def __init__(self, api_url: str, api_key: str | None = None, timeout: float = 180.0) -> None:
        base = api_url.rstrip("/")
        self._token = (api_key or "").strip()
        self._http = httpx.AsyncClient(base_url=base, timeout=timeout)

    async def aclose(self) -> None:
        await self._http.aclose()

    @property
    def has_token(self) -> bool:
        return bool(self._token)

    @property
    def token(self) -> str:
        return self._token

    def set_token(self, token: str | None) -> None:
        self._token = (token or "").strip()

    async def bootstrap(
        self,
        *,
        bootstrap_code: str,
        display_name: str,
        device_name: str | None = None,
        device_type: str = "tui",
    ) -> tuple[str, AuthUser]:
        response = await self._request(
            "POST",
            "/v1/auth/bootstrap",
            json={
                "bootstrap_code": bootstrap_code,
                "display_name": display_name,
                "device_name": device_name,
                "device_type": device_type,
            },
            requires_auth=False,
        )
        payload = response.json()
        token = str(payload.get("token") or "").strip()
        user_payload = payload.get("user") if isinstance(payload, dict) else None
        user = self._parse_auth_user(user_payload)
        if not token:
            raise ApiError("Missing access token in /v1/auth/bootstrap response")
        self._token = token
        return token, user

    async def pair(
        self,
        *,
        pair_code: str,
        device_name: str | None = None,
        device_type: str = "tui",
    ) -> tuple[str, AuthUser]:
        response = await self._request(
            "POST",
            "/v1/auth/pair/complete",
            json={
                "pair_code": pair_code,
                "device_name": device_name,
                "device_type": device_type,
            },
            requires_auth=False,
        )
        payload = response.json()
        token = str(payload.get("token") or "").strip()
        user_payload = payload.get("user") if isinstance(payload, dict) else None
        user = self._parse_auth_user(user_payload)
        if not token:
            raise ApiError("Missing access token in /v1/auth/pair/complete response")
        self._token = token
        return token, user

    async def auth_me(self) -> AuthUser:
        response = await self._request("GET", "/v1/auth/me", requires_auth=True)
        payload = response.json()
        return self._parse_auth_user(payload)

    async def execute_command(
        self,
        *,
        command: str,
        args: dict[str, Any] | None = None,
        origin: str = "tui",
        agent_profile_id: str | None = None,
        agent_profile_slug: str | None = None,
    ) -> CommandResult:
        response = await self._request(
            "POST",
            "/v1/commands/execute",
            json={
                "command": command,
                "args": args or {},
                "origin": origin,
                "agent_profile_id": agent_profile_id,
                "agent_profile_slug": agent_profile_slug,
            },
            requires_auth=True,
        )
        payload = response.json()
        if not isinstance(payload, dict):
            raise ApiError("Invalid /v1/commands/execute response payload")
        return CommandResult(
            ok=bool(payload.get("ok", True)),
            message=str(payload.get("message") or ""),
            data=payload.get("data") if isinstance(payload.get("data"), dict) else {},
        )

    async def create_session(
        self,
        *,
        origin: str = "tui",
        reuse_active: bool = True,
        agent_profile_id: str | None = None,
        agent_profile_slug: str | None = None,
    ) -> str:
        response = await self._request(
            "POST",
            "/v1/sessions",
            json={
                "origin": origin,
                "reuse_active": reuse_active,
                "agent_profile_id": agent_profile_id,
                "agent_profile_slug": agent_profile_slug,
            },
            requires_auth=True,
        )
        payload = response.json()
        session_id = str(payload.get("id") or "").strip()
        if not session_id:
            raise ApiError("Missing session id in /v1/sessions response")
        return session_id

    async def send_message(
        self,
        *,
        session_id: str,
        text: str,
        metadata: dict[str, Any] | None = None,
        attachment_paths: list[Path] | None = None,
    ) -> dict[str, Any]:
        attachments_payload: list[dict[str, str]] = []
        for path in attachment_paths or []:
            filename = path.name or "attachment"
            content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
            attachments_payload.append(
                {
                    "filename": filename,
                    "content_type": content_type,
                    "data_base64": base64.b64encode(path.read_bytes()).decode("ascii"),
                }
            )
        payload = {
            "session_id": session_id,
            "text": text,
            "metadata": metadata or {},
            "attachments": attachments_payload,
        }
        response = await self._request("POST", "/v1/messages", json=payload, requires_auth=True)
        body = response.json()
        if not isinstance(body, dict):
            raise ApiError("Invalid /v1/messages response payload")
        return body

    async def get_session_detail(self, session_id: str) -> dict[str, Any]:
        response = await self._request("GET", f"/v1/sessions/{session_id}/detail", requires_auth=True)
        body = response.json()
        if not isinstance(body, dict):
            raise ApiError("Invalid /v1/sessions/{id}/detail response payload")
        return body

    async def list_profiles(self) -> list[AgentProfile]:
        response = await self._request("GET", "/v1/profiles", requires_auth=True)
        payload = response.json()
        if not isinstance(payload, list):
            raise ApiError("Invalid /v1/profiles response payload")
        items: list[AgentProfile] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            profile_id = str(item.get("id") or "").strip()
            slug = str(item.get("slug") or "").strip()
            if not profile_id or not slug:
                continue
            items.append(
                AgentProfile(
                    id=profile_id,
                    slug=slug,
                    name=str(item.get("name") or slug),
                    status=str(item.get("status") or "active"),
                    is_default=bool(item.get("is_default", False)),
                )
            )
        return items

    async def list_pending_tool_runs(self, *, session_id: str, limit: int = 200) -> list[ToolRun]:
        response = await self._request(
            "GET",
            f"/v1/tools?status=pending&limit={limit}",
            requires_auth=True,
        )
        payload = response.json()
        if not isinstance(payload, list):
            raise ApiError("Invalid /v1/tools response payload")
        items: list[ToolRun] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            if str(item.get("session_id") or "").strip() != session_id:
                continue
            tool_run_id = str(item.get("id") or "").strip()
            if not tool_run_id:
                continue
            items.append(
                ToolRun(
                    id=tool_run_id,
                    tool=str(item.get("tool") or "tool"),
                    status=str(item.get("status") or ""),
                    created_at=str(item.get("created_at") or ""),
                    session_id=str(item.get("session_id") or ""),
                    requested_by=str(item.get("requested_by") or ""),
                    approved_by=str(item.get("approved_by") or "").strip() or None,
                    input=item.get("input") if isinstance(item.get("input"), dict) else {},
                    output=item.get("output") if isinstance(item.get("output"), dict) else {},
                )
            )
        items.sort(key=lambda row: row.created_at)
        return items

    async def list_pending_user_prompts(self, *, session_id: str) -> list[UserPrompt]:
        response = await self._request(
            "GET",
            f"/v1/user-prompts?session_id={session_id}",
            requires_auth=True,
        )
        payload = response.json()
        if not isinstance(payload, list):
            raise ApiError("Invalid /v1/user-prompts response payload")
        items: list[UserPrompt] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            prompt_id = str(item.get("id") or "").strip()
            if not prompt_id:
                continue
            items.append(
                UserPrompt(
                    id=prompt_id,
                    session_id=str(item.get("session_id") or session_id),
                    question=str(item.get("question") or "").strip(),
                    choices=[str(choice).strip() for choice in (item.get("choices") or []) if str(choice).strip()],
                    allow_free_text=bool(item.get("allow_free_text", True)),
                    status=str(item.get("status") or ""),
                    created_at=str(item.get("created_at") or ""),
                )
            )
        items.sort(key=lambda row: row.created_at)
        return items

    async def approve_tool_run(self, *, tool_run_id: str, decided_by: str) -> None:
        await self._request(
            "POST",
            f"/v1/tools/{tool_run_id}/approve",
            json={"approved_by": decided_by},
            requires_auth=True,
        )

    async def deny_tool_run(self, *, tool_run_id: str, decided_by: str) -> None:
        await self._request(
            "POST",
            f"/v1/tools/{tool_run_id}/deny",
            json={"approved_by": decided_by},
            requires_auth=True,
        )

    async def download_attachment(self, path_or_url: str) -> bytes:
        target = (path_or_url or "").strip()
        if not target:
            raise ApiError("Attachment URL is missing")
        if self._is_external_url(target):
            response = await self._http.get(target)
            self._raise(response)
            return response.content
        response = await self._request("GET", target, requires_auth=True)
        return response.content

    async def stream_events(
        self,
        *,
        session_id: str,
        stop_event: asyncio.Event,
    ) -> AsyncIterator[StreamEvent]:
        params = {"session_id": session_id}
        headers = {"accept": "text/event-stream", **self._auth_headers(requires_auth=True)}
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

    def _is_external_url(self, value: str) -> bool:
        if not value.startswith("http://") and not value.startswith("https://"):
            return False
        try:
            target = httpx.URL(value)
            base = self._http.base_url
        except Exception:
            return True
        return (target.scheme, target.host, target.port) != (base.scheme, base.host, base.port)

    @staticmethod
    def _decode_event_data(raw: str) -> dict[str, Any]:
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            return {"raw": raw}
        if isinstance(value, dict):
            return value
        return {"value": value}

    def _auth_headers(self, *, requires_auth: bool) -> dict[str, str]:
        if not requires_auth:
            return {}
        if not self._token:
            raise ApiError("Missing access token. Use /bootstrap or /pair first.")
        return {"authorization": f"Bearer {self._token}"}

    async def _request(
        self,
        method: str,
        path_or_url: str,
        *,
        json: dict[str, Any] | None = None,
        requires_auth: bool,
    ) -> httpx.Response:
        headers = self._auth_headers(requires_auth=requires_auth)
        response = await self._http.request(method, path_or_url, json=json, headers=headers)
        self._raise(response)
        return response

    @staticmethod
    def _parse_auth_user(payload: Any) -> AuthUser:
        if not isinstance(payload, dict):
            raise ApiError("Invalid auth user payload")
        user_id = str(payload.get("id") or "").strip()
        display_name = str(payload.get("display_name") or "").strip() or user_id
        approved = bool(payload.get("approved"))
        default_profile_id = str(payload.get("default_profile_id") or "").strip() or None
        default_profile_slug = str(payload.get("default_profile_slug") or "").strip() or None
        if not user_id:
            raise ApiError("Missing user id in auth response")
        return AuthUser(
            id=user_id,
            display_name=display_name,
            approved=approved,
            default_profile_id=default_profile_id,
            default_profile_slug=default_profile_slug,
        )

    @staticmethod
    def _raise(response: httpx.Response) -> None:
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text.strip()
            message = f"API {exc.response.status_code}: {detail or exc!s}"
            raise ApiError(message) from exc
