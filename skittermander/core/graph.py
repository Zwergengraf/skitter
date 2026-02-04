from __future__ import annotations

import json
import math
from contextvars import ContextVar, Token
from typing import Optional

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
        return ApprovalDecision(tool_run_id="", approved=True)
    if approval_service is None:
        return ApprovalDecision(tool_run_id="", approved=False)
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

    def _normalize_action(action: str) -> Optional[str]:
        value = action.strip().lower()
        if value in {"read", "write", "list", "delete"}:
            return value
        if value in {"read_file", "readfile", "open", "get"}:
            return "read"
        if value in {"write_file", "writefile", "save", "put"}:
            return "write"
        if value in {"ls", "dir"}:
            return "list"
        if value in {"rm", "remove", "del", "delete_file"}:
            return "delete"
        return None

    @tool("filesystem")
    async def filesystem(
        action: str, path: str, content: Optional[str] = None, recursive: Optional[bool] = None
    ) -> str:
        """Read/write/list files in the sandboxed workspace. Paths should be relative to the workspace root."""
        if not path:
            return "filesystem error: path is required"
        normalized = _normalize_action(action)
        if normalized is None:
            return "filesystem error: action must be one of read, write, list, delete"
        payload = {"action": normalized, "path": path}
        if content is not None:
            payload["content"] = content
        if recursive is not None:
            payload["recursive"] = bool(recursive)
        force_approval = normalized == "delete" and bool(recursive)
        if force_approval:
            if approval_service is None:
                return "filesystem error: recursive delete requires approval"
            decision = await approval_service.request(
                session_id=_session_id(),
                channel_id=_channel_id(),
                tool_name="filesystem",
                payload=payload,
                requested_by=_user_id(),
            )
        else:
            decision = await _maybe_approve("filesystem", payload, approval_service, policy)
        if not decision.approved:
            return "filesystem error: tool execution denied"
        try:
            result = await client.execute(_session_id(), "filesystem", payload)
        except httpx.HTTPStatusError as exc:
            return f"filesystem error: {exc.response.text}"
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
            result = await client.execute(_session_id(), "http_fetch", payload)
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
    ) -> str:
        """Open a page in a headless browser (if enabled in the sandbox)."""
        payload = {"url": url, "max_chars": max_chars, "screenshot": screenshot, "width": width, "height": height}
        decision = await _maybe_approve("browser", payload, approval_service, policy)
        if not decision.approved:
            return "browser error: tool execution denied"
        try:
            result = await client.execute(_session_id(), "browser", payload)
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
            result = await client.execute(_session_id(), "browser_action", payload, timeout=timeout_s)
        except httpx.HTTPStatusError as exc:
            return f"browser_action error: {exc.response.text}"
        except httpx.ReadTimeout:
            return "browser_action error: sandbox timed out"
        if decision.tool_run_id and approval_service is not None:
            await approval_service.complete(decision.tool_run_id, "completed", result)
        return json.dumps(result)

    @tool("shell")
    async def shell(cmd: str, cwd: Optional[str] = None) -> str:
        """Run a shell command in the sandboxed workspace."""
        payload = {"cmd": cmd}
        if cwd:
            payload["cwd"] = cwd
        decision = await _maybe_approve("shell", payload, approval_service, policy)
        if not decision.approved:
            return "shell error: tool execution denied"
        try:
            result = await client.execute(_session_id(), "shell", payload)
        except httpx.HTTPStatusError as exc:
            return f"shell error: {exc.response.text}"
        if decision.tool_run_id and approval_service is not None:
            await approval_service.complete(decision.tool_run_id, "completed", result)
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
            user = await repo.get_or_create_user(_user_id())
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
            user = await repo.get_or_create_user(_user_id())
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
            user = await repo.get_or_create_user(_user_id())
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
    system_prompt = (
        "You are Skittermander, a helpful assistant. For web automation, use the browser tools.\n"
        "Use browser_action for multi-step flows: open -> snapshot(include_elements=true) -> click/type/fill -> wait -> "
        "snapshot/screenshot. Do not guess selectors; obtain them from snapshot elements or use stable attributes "
        "(id, data-testid, aria-label). If the page changes, re-snapshot.\n"
        "Use browser_action screenshot with selector to capture a specific element. Use full_page if needed. "
        "Screenshots are saved under workspace/screenshots and the tool returns screenshot_path. "
        "Do not include screenshot file paths or markdown image links in the final response; just say that the screenshot is attached.\n"
        "For tabs, use browser_action action=tabs to list, action=focus with index to switch, and action=close_tab to close.\n"
        "Use web_search for fast discovery, web_fetch for lightweight content extraction, and browser only when needed.\n"
    )
    return create_agent(
        model,
        tools=[
            filesystem,
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
        system_prompt=system_prompt,
    )
