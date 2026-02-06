from __future__ import annotations

import json
import math
import base64
from pathlib import Path
from contextvars import ContextVar, Token
from typing import Optional, Any

import httpx
from bs4 import BeautifulSoup
from readability import Document
from markdownify import markdownify as md
from langchain.agents import create_agent
from langchain.tools import tool

from .config import settings
from .llm import build_llm
from ..tools.approval_service import ApprovalDecision, ToolApprovalService
from ..core.scheduler import SchedulerService
from ..tools.middleware import ToolApprovalPolicy
from ..tools.sandbox_client import ToolRunnerClient
from ..data.db import SessionLocal
from ..data.repositories import Repository
from .embeddings import EmbeddingsClient
from .workspace import user_workspace_root


_CURRENT_SESSION_ID: ContextVar[str] = ContextVar("skitter_session_id", default="default")
_CURRENT_CHANNEL_ID: ContextVar[str] = ContextVar("skitter_channel_id", default="default")
_CURRENT_USER_ID: ContextVar[str] = ContextVar("skitter_user_id", default="default")
_CURRENT_ORIGIN: ContextVar[str] = ContextVar("skitter_origin", default="unknown")


def set_current_session_id(session_id: str) -> Token:
    return _CURRENT_SESSION_ID.set(session_id)


def reset_current_session_id(token: Token) -> None:
    _CURRENT_SESSION_ID.reset(token)


def set_current_channel_id(channel_id: str) -> Token:
    return _CURRENT_CHANNEL_ID.set(channel_id)


def reset_current_channel_id(token: Token) -> None:
    _CURRENT_CHANNEL_ID.reset(token)


def set_current_user_id(user_id: str) -> Token:
    return _CURRENT_USER_ID.set(user_id)


def reset_current_user_id(token: Token) -> None:
    _CURRENT_USER_ID.reset(token)


def set_current_origin(origin: str) -> Token:
    return _CURRENT_ORIGIN.set(origin)


def reset_current_origin(token: Token) -> None:
    _CURRENT_ORIGIN.reset(token)


def _session_id() -> str:
    return _CURRENT_SESSION_ID.get()

def _channel_id() -> str:
    return _CURRENT_CHANNEL_ID.get()


def _user_id() -> str:
    return _CURRENT_USER_ID.get()


def _origin() -> str:
    return _CURRENT_ORIGIN.get()


def current_user_id() -> str:
    return _user_id()


async def _maybe_approve(
    tool_name: str,
    payload: dict,
    approval_service: ToolApprovalService | None,
    policy: ToolApprovalPolicy,
) -> ApprovalDecision:
    if not policy.requires_approval(tool_name):
        async with SessionLocal() as session:
            repo = Repository(session)
            tool_run = await repo.create_tool_run(
                session_id=_session_id(),
                tool_name=tool_name,
                status="approved",
                input_payload=payload,
                approved_by="auto",
            )
        return ApprovalDecision(tool_run_id=tool_run.id, approved=True)
    if approval_service is None:
        async with SessionLocal() as session:
            repo = Repository(session)
            tool_run = await repo.create_tool_run(
                session_id=_session_id(),
                tool_name=tool_name,
                status="denied",
                input_payload=payload,
                approved_by="system",
            )
        return ApprovalDecision(tool_run_id=tool_run.id, approved=False)
    return await approval_service.request(
        session_id=_session_id(),
        channel_id=_channel_id(),
        tool_name=tool_name,
        payload=payload,
        requested_by=_user_id(),
    )


def build_graph(approval_service: ToolApprovalService | None = None, scheduler_service: SchedulerService | None = None):
    client = ToolRunnerClient()
    policy = ToolApprovalPolicy()
    embedder = EmbeddingsClient()

    def _coalesce_path(path: Optional[str], file_path: Optional[str]) -> Optional[str]:
        if path and path.strip():
            return path
        if file_path and file_path.strip():
            return file_path
        return None

    def _resolve_workspace_path(user_id: str, raw_path: str) -> Path | None:
        if not raw_path:
            return None
        workspace = user_workspace_root(user_id)
        path = Path(raw_path)
        if raw_path.startswith("/workspace/"):
            resolved = workspace / Path(raw_path).relative_to("/workspace")
        elif path.is_absolute():
            resolved = path
        else:
            resolved = workspace / path
        try:
            resolved = resolved.resolve()
            workspace_resolved = workspace.resolve()
        except OSError:
            return None
        if workspace_resolved not in resolved.parents and resolved != workspace_resolved:
            return None
        return resolved

    @tool("read")
    async def read(
        path: Optional[str] = None,
        offset: Optional[int] = None,
        limit: Optional[int] = None,
        file_path: Optional[str] = None,
    ) -> str:
        """Read the contents of a file. Supports text files and images (jpg, png, gif, webp). Images are sent as attachments. For text files, output is truncated to 2000 lines or 50KB (whichever is hit first). Use offset/limit for large files. When you need the full file, continue with offset until complete."""
        target = _coalesce_path(path, file_path)
        if not target:
            return "read error: path is required"
        payload: dict[str, Any] = {"path": target}
        if offset is not None:
            payload["offset"] = offset
        if limit is not None:
            payload["limit"] = limit
        decision = await _maybe_approve("read", payload, approval_service, policy)
        if not decision.approved:
            return "read error: tool execution denied"
        try:
            result = await client.execute(_user_id(), _session_id(), "read", payload)
        except httpx.HTTPStatusError as exc:
            return f"read error: {exc.response.text}"
        if decision.tool_run_id and approval_service is not None:
            await approval_service.complete(decision.tool_run_id, "completed", result)
        if isinstance(result, dict):
            content_type = str(result.get("content_type") or "").lower()
            file_path = str(result.get("file_path") or "")
            if content_type.startswith("image/") and file_path:
                resolved = _resolve_workspace_path(_user_id(), file_path)
                if resolved and resolved.exists():
                    try:
                        data = resolved.read_bytes()
                    except OSError:
                        return json.dumps(result)
                    b64 = base64.b64encode(data).decode("ascii")
                    return [
                        {"type": "text", "text": f"Read image: {file_path} ({content_type})"},
                        {"type": "image", "base64": b64, "mime_type": content_type},
                    ]
        return json.dumps(result)

    @tool("write")
    async def write(path: Optional[str] = None, content: Optional[str] = None, file_path: Optional[str] = None) -> str:
        """Write content to a file. Creates the file if it doesn't exist, overwrites if it does. Automatically creates parent directories."""
        target = _coalesce_path(path, file_path)
        if not target:
            return "write error: path is required"
        if content is None:
            return "write error: content is required"
        payload = {"path": target, "content": content}
        decision = await _maybe_approve("write", payload, approval_service, policy)
        if not decision.approved:
            return "write error: tool execution denied"
        try:
            result = await client.execute(_user_id(), _session_id(), "write", payload)
        except httpx.HTTPStatusError as exc:
            return f"write error: {exc.response.text}"
        if decision.tool_run_id and approval_service is not None:
            await approval_service.complete(decision.tool_run_id, "completed", result)
        return json.dumps(result)

    @tool("edit")
    async def edit(
        path: Optional[str] = None,
        oldText: Optional[str] = None,
        newText: Optional[str] = None,
        file_path: Optional[str] = None,
        old_string: Optional[str] = None,
        new_string: Optional[str] = None,
    ) -> str:
        """Edit a file by replacing exact text. The oldText must match exactly (including whitespace). Use this for precise, surgical edits."""
        target = _coalesce_path(path, file_path)
        if not target:
            return "edit error: path is required"
        old_value = oldText if oldText is not None else old_string
        new_value = newText if newText is not None else new_string
        if old_value is None:
            return "edit error: oldText is required"
        if new_value is None:
            return "edit error: newText is required"
        payload = {"path": target, "oldText": old_value, "newText": new_value}
        decision = await _maybe_approve("edit", payload, approval_service, policy)
        if not decision.approved:
            return "edit error: tool execution denied"
        try:
            result = await client.execute(_user_id(), _session_id(), "edit", payload)
        except httpx.HTTPStatusError as exc:
            return f"edit error: {exc.response.text}"
        if decision.tool_run_id and approval_service is not None:
            await approval_service.complete(decision.tool_run_id, "completed", result)
        return json.dumps(result)

    @tool("list")
    async def list_files(path: Optional[str] = None, file_path: Optional[str] = None) -> str:
        """List files and folders at a path in the workspace."""
        target = _coalesce_path(path, file_path)
        if not target:
            return "list error: path is required"
        payload = {"path": target}
        decision = await _maybe_approve("list", payload, approval_service, policy)
        if not decision.approved:
            return "list error: tool execution denied"
        try:
            result = await client.execute(_user_id(), _session_id(), "list", payload)
        except httpx.HTTPStatusError as exc:
            return f"list error: {exc.response.text}"
        if decision.tool_run_id and approval_service is not None:
            await approval_service.complete(decision.tool_run_id, "completed", result)
        return json.dumps(result)

    @tool("delete")
    async def delete(
        path: Optional[str] = None, recursive: Optional[bool] = None, file_path: Optional[str] = None
    ) -> str:
        """Delete a file or folder. Use recursive=true to delete non-empty folders."""
        target = _coalesce_path(path, file_path)
        if not target:
            return "delete error: path is required"
        payload = {"path": target, "recursive": bool(recursive)}
        if payload["recursive"] and approval_service is None:
            return "delete error: recursive delete requires approval"
        decision = await _maybe_approve("delete", payload, approval_service, policy)
        if not decision.approved:
            return "delete error: tool execution denied"
        try:
            result = await client.execute(_user_id(), _session_id(), "delete", payload)
        except httpx.HTTPStatusError as exc:
            return f"delete error: {exc.response.text}"
        if decision.tool_run_id and approval_service is not None:
            await approval_service.complete(decision.tool_run_id, "completed", result)
        return json.dumps(result)

    @tool("download")
    async def download(url: str, path: Optional[str] = None) -> str:
        """Download a file from a URL into the workspace. Optionally specify a target path."""
        if not url:
            return "download error: url is required"
        payload: dict[str, Any] = {"url": url}
        if path:
            payload["path"] = path
        decision = await _maybe_approve("download", payload, approval_service, policy)
        if not decision.approved:
            return "download error: tool execution denied"
        try:
            result = await client.execute(_user_id(), _session_id(), "download", payload)
        except httpx.HTTPStatusError as exc:
            return f"download error: {exc.response.text}"
        if decision.tool_run_id and approval_service is not None:
            await approval_service.complete(decision.tool_run_id, "completed", result)
        return json.dumps(result)

    @tool("http_fetch")
    async def http_fetch(url: str) -> str:
        """Fetch a URL over HTTP."""
        payload = {"url": url}
        decision = await _maybe_approve("http_fetch", payload, approval_service, policy)
        if not decision.approved:
            return "http_fetch error: tool execution denied"
        try:
            result = await client.execute(_user_id(), _session_id(), "http_fetch", payload)
        except httpx.HTTPStatusError as exc:
            return f"http_fetch error: {exc.response.text}"
        if decision.tool_run_id and approval_service is not None:
            await approval_service.complete(decision.tool_run_id, "completed", result)
        return json.dumps(result)

    @tool("browser")
    async def browser(
        url: str,
        max_chars: int = 20000,
        screenshot: bool = False,
        width: int = 1920,
        height: int = 1080,
        timeout_ms: int = 30000,
        wait_until: str = "networkidle",
    ) -> str:
        """Open a page in a headless browser (if enabled in the sandbox)."""
        payload = {
            "url": url,
            "max_chars": max_chars,
            "screenshot": screenshot,
            "width": width,
            "height": height,
            "timeout_ms": timeout_ms,
            "wait_until": wait_until,
        }
        decision = await _maybe_approve("browser", payload, approval_service, policy)
        if not decision.approved:
            return "browser error: tool execution denied"
        try:
            result = await client.execute(_user_id(), _session_id(), "browser", payload)
        except httpx.HTTPStatusError as exc:
            return f"browser error: {exc.response.text}"
        if decision.tool_run_id and approval_service is not None:
            await approval_service.complete(decision.tool_run_id, "completed", result)
        return json.dumps(result)

    @tool("browser_action")
    async def browser_action(
        action: str,
        url: Optional[str] = None,
        selector: Optional[str] = None,
        text: Optional[str] = None,
        key: Optional[str] = None,
        fields: Optional[list[dict]] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        username_selector: Optional[str] = None,
        password_selector: Optional[str] = None,
        submit_selector: Optional[str] = None,
        wait_for: Optional[str] = None,
        index: Optional[int] = None,
        width: int = 1920,
        height: int = 1080,
        timeout_ms: int = 30000,
        wait_until: str = "domcontentloaded",
        full_page: bool = True,
        max_chars: int = 20000,
        mode: str = "text",
        include_elements: bool = False,
        max_elements: int = 50,
    ) -> str:
        """Stateful browser automation (open/click/type/fill/press/wait/snapshot/screenshot/close/status)."""
        payload = {
            "action": action,
            "url": url,
            "selector": selector,
            "text": text,
            "key": key,
            "fields": fields,
            "username": username,
            "password": password,
            "username_selector": username_selector,
            "password_selector": password_selector,
            "submit_selector": submit_selector,
            "wait_for": wait_for,
            "index": index,
            "width": width,
            "height": height,
            "timeout_ms": timeout_ms,
            "wait_until": wait_until,
            "full_page": full_page,
            "max_chars": max_chars,
            "mode": mode,
            "include_elements": include_elements,
            "max_elements": max_elements,
        }
        decision = await _maybe_approve("browser_action", payload, approval_service, policy)
        if not decision.approved:
            return "browser_action error: tool execution denied"
        try:
            timeout_s = max(60, int(timeout_ms / 1000) + 15)
            result = await client.execute(_user_id(), _session_id(), "browser_action", payload, timeout=timeout_s)
        except httpx.HTTPStatusError as exc:
            return f"browser_action error: {exc.response.text}"
        except httpx.ReadTimeout:
            return "browser_action error: sandbox timed out"
        if decision.tool_run_id and approval_service is not None:
            await approval_service.complete(decision.tool_run_id, "completed", result)
        return json.dumps(result)

    @tool("shell")
    async def shell(cmd: str, cwd: Optional[str] = None, background: bool = False) -> str:
        """Run a shell command in the sandboxed workspace. Use background=true for long-running tasks."""
        payload = {"cmd": cmd, "background": bool(background)}
        if cwd:
            payload["cwd"] = cwd
        decision = await _maybe_approve("shell", payload, approval_service, policy)
        if not decision.approved:
            return "shell error: tool execution denied"
        try:
            result = await client.execute(_user_id(), _session_id(), "shell", payload)
        except httpx.HTTPStatusError as exc:
            return f"shell error: {exc.response.text}"
        if decision.tool_run_id and approval_service is not None:
            await approval_service.complete(decision.tool_run_id, "completed", result)
        if payload.get("background") and isinstance(result, dict) and "pid" in result:
            async with SessionLocal() as session:
                repo = Repository(session)
                await repo.create_sandbox_task(
                    user_id=_user_id(),
                    session_id=_session_id(),
                    pid=int(result["pid"]),
                    command=cmd,
                )
        return json.dumps(result)

    @tool("web_search")
    async def web_search(
        query: str,
        count: int = 5,
        country: str = "US",
        search_lang: Optional[str] = None,
        ui_lang: Optional[str] = None,
        freshness: Optional[str] = None,
    ) -> str:
        """Search the web using Brave Search API."""
        if not query.strip():
            return "web_search error: query is required"
        if not settings.brave_api_key:
            return "web_search error: SKITTER_BRAVE_API_KEY is not set"
        params = {"q": query, "count": max(1, min(int(count), 10)), "country": country}
        if search_lang:
            params["search_lang"] = search_lang
        if ui_lang:
            params["ui_lang"] = ui_lang
        if freshness:
            params["freshness"] = freshness
        headers = {"Accept": "application/json", "X-Subscription-Token": settings.brave_api_key}
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(settings.brave_api_base, params=params, headers=headers)
            resp.raise_for_status()
            data = resp.json()
        results = []
        for item in (data.get("web", {}).get("results") or []):
            results.append(
                {
                    "title": item.get("title"),
                    "url": item.get("url"),
                    "snippet": item.get("description"),
                }
            )
        return json.dumps({"query": query, "results": results})

    @tool("web_fetch")
    async def web_fetch(url: str, extractMode: str = "markdown", maxChars: int = 20000) -> str:
        """Fetch and extract readable content from a URL (HTML → markdown/text)."""
        if not url:
            return "web_fetch error: url is required"
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            html = resp.text
        doc = Document(html)
        content_html = doc.summary()
        if extractMode == "text":
            text = BeautifulSoup(content_html, "html.parser").get_text("\n")
            text = text.strip()
            return json.dumps({"url": url, "content": text[:maxChars]})
        markdown = md(content_html, heading_style="ATX")
        markdown = markdown.strip()
        return json.dumps({"url": url, "content": markdown[:maxChars]})

    @tool("schedule_create")
    async def schedule_create(
        name: str,
        prompt: str,
        cron: Optional[str] = None,
        run_at: Optional[str] = None,
        channel_id: Optional[str] = None,
    ) -> str:
        """Create a scheduled job using a cron expression or run_at timestamp (ISO-8601)."""
        if scheduler_service is None:
            return "schedule_create error: scheduler not configured"
        if not prompt:
            return "schedule_create error: prompt is required"
        if not cron and not run_at:
            return "schedule_create error: cron or run_at is required"
        if run_at:
            cron = f"DATE:{run_at}"
        target_channel = channel_id or _channel_id()
        async with SessionLocal() as session:
            repo = Repository(session)
            user = await repo.get_user_by_id(_user_id())
            if user is None:
                return "schedule_create error: user not found"
        result = await scheduler_service.create_job(user.id, target_channel, name or "Scheduled job", prompt, cron)
        return json.dumps(result)

    @tool("schedule_update")
    async def schedule_update(
        job_id: str,
        cron: Optional[str] = None,
        run_at: Optional[str] = None,
        prompt: Optional[str] = None,
        enabled: Optional[bool] = None,
    ) -> str:
        """Update a scheduled job."""
        if scheduler_service is None:
            return "schedule_update error: scheduler not configured"
        fields = {}
        if run_at:
            fields["schedule_type"] = "date"
            fields["schedule_expr"] = run_at
        elif cron:
            fields["schedule_type"] = "cron"
            fields["schedule_expr"] = cron
        if prompt:
            fields["prompt"] = prompt
        if enabled is not None:
            fields["enabled"] = enabled
        result = await scheduler_service.update_job(job_id, **fields)
        return json.dumps(result)

    @tool("schedule_delete")
    async def schedule_delete(job_id: str) -> str:
        """Delete a scheduled job."""
        if scheduler_service is None:
            return "schedule_delete error: scheduler not configured"
        result = await scheduler_service.delete_job(job_id)
        return json.dumps(result)

    @tool("schedule_list")
    async def schedule_list() -> str:
        """List scheduled jobs for the current user."""
        if scheduler_service is None:
            return "schedule_list error: scheduler not configured"
        async with SessionLocal() as session:
            repo = Repository(session)
            user = await repo.get_user_by_id(_user_id())
            if user is None:
                return "schedule_list error: user not found"
        jobs = await scheduler_service.list_jobs(user.id)
        return json.dumps({"jobs": jobs})

    def _cosine_similarity(a: list[float], b: list[float]) -> float:
        if not a or not b:
            return 0.0
        if len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(y * y for y in b))
        if norm_a == 0.0 or norm_b == 0.0:
            return 0.0
        return dot / (norm_a * norm_b)

    @tool("memory_search")
    async def memory_search(query: str, top_k: int = 5) -> str:
        """Search session memories by semantic similarity."""
        if not query.strip():
            return "memory_search error: query is required"
        try:
            query_vec = await embedder.embed_query(query)
        except Exception as exc:
            return f"memory_search error: {exc}"
        async with SessionLocal() as session:
            repo = Repository(session)
            user = await repo.get_user_by_id(_user_id())
            if user is None:
                return "memory_search error: user not found"
            entries = await repo.list_memory_entries(user.id)
        scored = []
        for entry in entries:
            score = _cosine_similarity(query_vec, entry.embedding)
            scored.append((score, entry))
        scored.sort(key=lambda item: item[0], reverse=True)
        min_score = settings.memory_min_similarity
        results = []
        for score, entry in scored:
            if score < min_score:
                continue
            results.append(
                {
                    "score": round(score, 4),
                    "summary": entry.summary,
                    "tags": entry.tags,
                    "created_at": entry.created_at.isoformat(),
                }
            )
            if len(results) >= max(1, min(top_k, 10)):
                break
        return json.dumps({"query": query, "results": results})

    model = build_llm()
    return create_agent(
        model,
        tools=[
            read,
            write,
            edit,
            list_files,
            delete,
            download,
            http_fetch,
            browser,
            browser_action,
            shell,
            memory_search,
            web_search,
            web_fetch,
            schedule_create,
            schedule_update,
            schedule_delete,
            schedule_list,
        ],
        system_prompt=None,
    )
