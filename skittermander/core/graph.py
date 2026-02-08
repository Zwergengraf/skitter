from __future__ import annotations

import json
import base64
from pathlib import Path
from contextvars import ContextVar, Token
from typing import Optional, Any
import time

import httpx
from bs4 import BeautifulSoup
from readability import Document
from markdownify import markdownify as md
from langchain.agents import create_agent
from langchain.tools import tool

from .config import settings
from .llm import build_llm
from .llm import resolve_model_name
from .prompting import build_system_prompt
from .subagents import SubAgentResult, SubAgentService, SubAgentTaskSpec
from .run_limits import get_current_run_limits
from ..tools.approval_service import ApprovalDecision, ToolApprovalService
from ..core.scheduler import SchedulerService
from ..tools.middleware import ToolApprovalPolicy
from ..tools.sandbox_client import ToolRunnerClient
from ..data.db import SessionLocal
from ..data.repositories import Repository
from .embeddings import EmbeddingsClient
from .memory_service import MemoryService
from .workspace import user_workspace_root
from .secrets import SecretsManager


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


def build_graph(
    approval_service: ToolApprovalService | None = None,
    scheduler_service: SchedulerService | None = None,
    model_name: str | None = None,
    purpose: str = "main",
    include_subagent_tools: bool = True,
):
    client = ToolRunnerClient()
    policy = ToolApprovalPolicy()
    embedder = EmbeddingsClient()
    memory_service = MemoryService(embedder=embedder)
    worker_model_name = model_name or resolve_model_name(None, purpose="main")
    subagent_service: SubAgentService | None = None
    if include_subagent_tools:
        subagent_service = SubAgentService(
            graph_factory=lambda worker_model: build_graph(
                approval_service=approval_service,
                scheduler_service=scheduler_service,
                model_name=worker_model,
                purpose="main",
                include_subagent_tools=False,
            )
        )

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

    def _normalize_secret_refs(secret_refs: Any) -> list[str]:
        if not secret_refs:
            return []
        if isinstance(secret_refs, str):
            return [item.strip() for item in secret_refs.split(",") if item.strip()]
        if isinstance(secret_refs, list):
            return [str(item).strip() for item in secret_refs if str(item).strip()]
        return []

    def _secret_env_key(name: str) -> str:
        key = "".join(ch if ch.isalnum() else "_" for ch in name.strip()).upper()
        if not key:
            key = "SECRET"
        if key[0].isdigit():
            key = f"_{key}"
        #return f"SKITTER_SECRET_{key}" # Disabled so Skills get the ENVs they expect without needing to know about the SKITTER_ prefix
        return f"{key}"

    def _denied_message(tool_name: str) -> str:
        return f"{tool_name} denied: Request was denied by the user, please ask them for clarification."

    def _limit_message(reason: str, detail: str) -> str:
        return (
            f"LIMIT_REACHED ({reason}): {detail}. "
            "Stop calling tools and provide the best possible final response from current context."
        )

    def _consume_tool_budget(tool_name: str) -> str | None:
        limits = get_current_run_limits()
        if limits is None:
            return None
        elapsed = time.monotonic() - limits.start_time
        if elapsed > max(1, limits.max_runtime_seconds):
            return _limit_message(
                "runtime",
                f"runtime exceeded ({limits.max_runtime_seconds}s) before tool `{tool_name}`",
            )
        if limits.max_cost_usd > 0 and limits.spent_cost_usd >= limits.max_cost_usd:
            return _limit_message(
                "cost",
                f"run cost budget exceeded (${limits.max_cost_usd:.2f}) before tool `{tool_name}`",
            )
        if limits.max_tool_calls >= 0 and limits.tool_calls_used >= limits.max_tool_calls:
            return _limit_message(
                "tool_calls",
                f"max tool calls reached ({limits.max_tool_calls}) before tool `{tool_name}`",
            )
        limits.tool_calls_used += 1
        return None

    def _subagent_manager_result(result: SubAgentResult) -> dict[str, Any]:
        return {
            "name": result.name,
            "status": result.status,
            "final_text": result.final_text,
            "error": result.error,
            "usage": result.usage,
            "artifacts": result.artifacts,
        }

    def _subagent_summary(result: SubAgentResult) -> str:
        if result.status == "completed":
            text = (result.final_text or "").strip()
            if len(text) > 320:
                text = text[:317].rstrip() + "..."
            return text or "Completed with no final text."
        return result.error or "Sub-agent did not complete."

    async def _create_auto_tool_run(tool_name: str, payload: dict[str, Any]) -> str:
        async with SessionLocal() as session:
            repo = Repository(session)
            tool_run = await repo.create_tool_run(
                session_id=_session_id(),
                tool_name=tool_name,
                status="approved",
                input_payload=payload,
                approved_by="auto",
            )
        return tool_run.id

    async def _enforce_tool_budget(tool_name: str, payload: dict[str, Any]) -> str | None:
        message = _consume_tool_budget(tool_name)
        if message is None:
            return None
        tool_run_id = await _create_auto_tool_run(tool_name, payload)
        await _complete_tool_run(
            tool_run_id,
            "denied",
            {"error": message, "reason": "limit_reached"},
        )
        return message

    async def _complete_tool_run(tool_run_id: str | None, status: str, output: dict[str, Any]) -> None:
        if not tool_run_id:
            return
        async with SessionLocal() as session:
            repo = Repository(session)
            await repo.complete_tool_run(tool_run_id, status, output)

    async def _fail_untracked_call(tool_name: str, payload: dict[str, Any], message: str) -> str:
        tool_run_id = await _create_auto_tool_run(tool_name, payload)
        await _complete_tool_run(tool_run_id, "failed", {"error": message})
        return message

    async def _execute_sandbox_tool(
        tool_name: str,
        tool_run_id: str | None,
        payload: dict[str, Any],
        timeout: float | None = None,
    ) -> tuple[Any | None, str | None]:
        try:
            result = await client.execute(_user_id(), _session_id(), tool_name, payload, timeout=timeout)
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text
            await _complete_tool_run(tool_run_id, "failed", {"error": detail})
            return None, f"{tool_name} error: {detail}"
        except httpx.RequestError as exc:
            detail = str(exc)
            await _complete_tool_run(tool_run_id, "failed", {"error": detail})
            return None, f"{tool_name} error: {detail}"
        except Exception as exc:
            detail = str(exc)
            await _complete_tool_run(tool_run_id, "failed", {"error": detail})
            return None, f"{tool_name} unexpected error: {detail}"
        await _complete_tool_run(tool_run_id, "completed", result if isinstance(result, dict) else {"result": result})
        return result, None

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
            return await _fail_untracked_call("read", {"path": path, "file_path": file_path}, "read error: path is required")
        payload: dict[str, Any] = {"path": target}
        if offset is not None:
            payload["offset"] = offset
        if limit is not None:
            payload["limit"] = limit
        budget_message = await _enforce_tool_budget("read", payload)
        if budget_message:
            return budget_message
        decision = await _maybe_approve("read", payload, approval_service, policy)
        if not decision.approved:
            return _denied_message("read")
        result, error = await _execute_sandbox_tool("read", decision.tool_run_id, payload)
        if error:
            return error
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
            return await _fail_untracked_call("write", {"path": path, "file_path": file_path}, "write error: path is required")
        if content is None:
            return await _fail_untracked_call("write", {"path": target}, "write error: content is required")
        payload = {"path": target, "content": content}
        budget_message = await _enforce_tool_budget("write", payload)
        if budget_message:
            return budget_message
        decision = await _maybe_approve("write", payload, approval_service, policy)
        if not decision.approved:
            return _denied_message("write")
        result, error = await _execute_sandbox_tool("write", decision.tool_run_id, payload)
        if error:
            return error
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
            return await _fail_untracked_call("edit", {"path": path, "file_path": file_path}, "edit error: path is required")
        old_value = oldText if oldText is not None else old_string
        new_value = newText if newText is not None else new_string
        if old_value is None:
            return await _fail_untracked_call("edit", {"path": target}, "edit error: oldText is required")
        if new_value is None:
            return await _fail_untracked_call("edit", {"path": target}, "edit error: newText is required")
        payload = {"path": target, "oldText": old_value, "newText": new_value}
        budget_message = await _enforce_tool_budget("edit", payload)
        if budget_message:
            return budget_message
        decision = await _maybe_approve("edit", payload, approval_service, policy)
        if not decision.approved:
            return _denied_message("edit")
        result, error = await _execute_sandbox_tool("edit", decision.tool_run_id, payload)
        if error:
            return error
        return json.dumps(result)

    @tool("list")
    async def list_files(
        path: Optional[str] = None,
        file_path: Optional[str] = None,
        show_hidden_files: Optional[bool] = None,
    ) -> str:
        """List files and folders at a path in the workspace. Hidden files are excluded by default; set show_hidden_files=true to include them."""
        target = _coalesce_path(path, file_path)
        if not target:
            return await _fail_untracked_call("list", {"path": path, "file_path": file_path}, "list error: path is required")
        payload = {"path": target, "show_hidden_files": bool(show_hidden_files)}
        budget_message = await _enforce_tool_budget("list", payload)
        if budget_message:
            return budget_message
        decision = await _maybe_approve("list", payload, approval_service, policy)
        if not decision.approved:
            return _denied_message("list")
        result, error = await _execute_sandbox_tool("list", decision.tool_run_id, payload)
        if error:
            return error
        return json.dumps(result)

    @tool("delete")
    async def delete(
        path: Optional[str] = None, recursive: Optional[bool] = None, file_path: Optional[str] = None
    ) -> str:
        """Delete a file or folder. Use recursive=true to delete non-empty folders."""
        target = _coalesce_path(path, file_path)
        if not target:
            return await _fail_untracked_call("delete", {"path": path, "file_path": file_path}, "delete error: path is required")
        payload = {"path": target, "recursive": bool(recursive)}
        budget_message = await _enforce_tool_budget("delete", payload)
        if budget_message:
            return budget_message
        if payload["recursive"] and approval_service is None:
            return await _fail_untracked_call("delete", payload, "delete error: recursive delete requires approval")
        decision = await _maybe_approve("delete", payload, approval_service, policy)
        if not decision.approved:
            return _denied_message("delete")
        result, error = await _execute_sandbox_tool("delete", decision.tool_run_id, payload)
        if error:
            return error
        return json.dumps(result)

    @tool("download")
    async def download(url: str, path: Optional[str] = None) -> str:
        """Download a file from a URL into the workspace. Optionally specify a target path."""
        if not url:
            return await _fail_untracked_call("download", {"url": url, "path": path}, "download error: url is required")
        payload: dict[str, Any] = {"url": url}
        if path:
            payload["path"] = path
        budget_message = await _enforce_tool_budget("download", payload)
        if budget_message:
            return budget_message
        decision = await _maybe_approve("download", payload, approval_service, policy)
        if not decision.approved:
            return _denied_message("download")
        result, error = await _execute_sandbox_tool("download", decision.tool_run_id, payload)
        if error:
            return error
        return json.dumps(result)

    @tool("http_fetch")
    async def http_fetch(url: str) -> str:
        """Fetch a URL over HTTP."""
        payload = {"url": url}
        budget_message = await _enforce_tool_budget("http_fetch", payload)
        if budget_message:
            return budget_message
        decision = await _maybe_approve("http_fetch", payload, approval_service, policy)
        if not decision.approved:
            return _denied_message("http_fetch")
        result, error = await _execute_sandbox_tool("http_fetch", decision.tool_run_id, payload)
        if error:
            return error
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
        budget_message = await _enforce_tool_budget("browser", payload)
        if budget_message:
            return budget_message
        decision = await _maybe_approve("browser", payload, approval_service, policy)
        if not decision.approved:
            return _denied_message("browser")
        result, error = await _execute_sandbox_tool("browser", decision.tool_run_id, payload)
        if error:
            return error
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
        budget_message = await _enforce_tool_budget("browser_action", payload)
        if budget_message:
            return budget_message
        decision = await _maybe_approve("browser_action", payload, approval_service, policy)
        if not decision.approved:
            return _denied_message("browser_action")
        timeout_s = max(60, int(timeout_ms / 1000) + 15)
        result, error = await _execute_sandbox_tool(
            "browser_action",
            decision.tool_run_id,
            payload,
            timeout=timeout_s,
        )
        if error:
            return error
        return json.dumps(result)

    @tool("shell")
    async def shell(
        cmd: str,
        cwd: Optional[str] = None,
        background: bool = False,
        secret_refs: Optional[list[str]] = None,
    ) -> str:
        """Run a shell command in the sandboxed workspace. Use background=true for long-running tasks. Use secret_refs to inject per-user secrets as env vars."""
        payload = {"cmd": cmd, "background": bool(background)}
        if cwd:
            payload["cwd"] = cwd
        budget_message = await _enforce_tool_budget("shell", payload)
        if budget_message:
            return budget_message
        secrets = _normalize_secret_refs(secret_refs)
        if secrets:
            if background:
                return await _fail_untracked_call("shell", payload, "shell error: secret_refs cannot be used with background commands")
            if approval_service is None:
                return await _fail_untracked_call("shell", payload, "shell error: secret execution requires approval")
            manager = SecretsManager()
            try:
                manager.ensure_ready()
            except RuntimeError as exc:
                return await _fail_untracked_call("shell", payload, f"shell error: {exc}")
            env: dict[str, str] = {}
            redact: list[str] = []
            missing: list[str] = []
            async with SessionLocal() as session:
                repo = Repository(session)
                for name in secrets:
                    secret = await repo.get_secret(_user_id(), name)
                    if secret is None:
                        missing.append(name)
                        continue
                    try:
                        value = manager.decrypt(secret.value_encrypted)
                    except RuntimeError:
                        return await _fail_untracked_call("shell", payload, f"shell error: failed to decrypt secret {name}")
                    env[_secret_env_key(name)] = value
                    if value:
                        redact.append(value)
                    await repo.touch_secret(secret)
            if missing:
                return await _fail_untracked_call("shell", payload, f"shell error: missing secrets: {', '.join(missing)}")
            approval_payload = {**payload, "secret_refs": secrets}
            decision = await approval_service.request(
                session_id=_session_id(),
                channel_id=_channel_id(),
                tool_name="shell",
                payload=approval_payload,
                requested_by=_user_id(),
            )
            if not decision.approved:
                return _denied_message("shell")
            exec_payload = {**payload, "env": env, "redact": redact}
        else:
            decision = await _maybe_approve("shell", payload, approval_service, policy)
            if not decision.approved:
                return _denied_message("shell")
            exec_payload = payload
        result, error = await _execute_sandbox_tool("shell", decision.tool_run_id, exec_payload)
        if error:
            return error
        return json.dumps(result)

    @tool("create_secret")
    async def create_secret(name: str, value: str) -> str:
        """Create a new per-user secret (name + value). Existing secrets cannot be overwritten."""
        secret_name = (name or "").strip()
        if not secret_name:
            return await _fail_untracked_call("create_secret", {"name": name}, "create_secret error: name is required")
        if value is None or value == "":
            return await _fail_untracked_call("create_secret", {"name": secret_name}, "create_secret error: value is required")

        manager = SecretsManager()
        try:
            manager.ensure_ready()
        except RuntimeError as exc:
            return await _fail_untracked_call("create_secret", {"name": secret_name}, f"create_secret error: {exc}")

        approval_payload = {"name": secret_name, "value": "[REDACTED]", "value_length": len(value)}
        budget_message = await _enforce_tool_budget("create_secret", approval_payload)
        if budget_message:
            return budget_message
        decision = await _maybe_approve("create_secret", approval_payload, approval_service, policy)
        if not decision.approved:
            return _denied_message("create_secret")

        encrypted = manager.encrypt(value)
        async with SessionLocal() as session:
            repo = Repository(session)
            secret = await repo.create_secret(_user_id(), secret_name, encrypted)
        if secret is None:
            await _complete_tool_run(
                decision.tool_run_id,
                "failed",
                {"error": f"secret '{secret_name}' already exists"},
            )
            return f"create_secret error: secret '{secret_name}' already exists"
        await _complete_tool_run(decision.tool_run_id, "completed", {"name": secret_name, "status": "created"})
        return json.dumps({"name": secret_name, "status": "created"})

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
        payload: dict[str, Any] = {
            "query": query,
            "count": count,
            "country": country,
            "search_lang": search_lang,
            "ui_lang": ui_lang,
            "freshness": freshness,
        }
        budget_message = await _enforce_tool_budget("web_search", payload)
        if budget_message:
            return budget_message
        tool_run_id = await _create_auto_tool_run("web_search", payload)
        if not query.strip():
            await _complete_tool_run(tool_run_id, "failed", {"error": "query is required"})
            return "web_search error: query is required"
        if not settings.brave_api_key:
            await _complete_tool_run(tool_run_id, "failed", {"error": "SKITTER_BRAVE_API_KEY is not set"})
            return "web_search error: SKITTER_BRAVE_API_KEY is not set"
        params = {"q": query, "count": max(1, min(int(count), 10)), "country": country}
        if search_lang:
            params["search_lang"] = search_lang
        if ui_lang:
            params["ui_lang"] = ui_lang
        if freshness:
            params["freshness"] = freshness
        headers = {"Accept": "application/json", "X-Subscription-Token": settings.brave_api_key}
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                resp = await client.get(settings.brave_api_base, params=params, headers=headers)
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPStatusError as exc:
            await _complete_tool_run(tool_run_id, "failed", {"error": exc.response.text})
            return f"web_search error: {exc.response.text}"
        except httpx.RequestError as exc:
            await _complete_tool_run(tool_run_id, "failed", {"error": str(exc)})
            return f"web_search error: {exc}"
        results = []
        for item in (data.get("web", {}).get("results") or []):
            results.append(
                {
                    "title": item.get("title"),
                    "url": item.get("url"),
                    "snippet": item.get("description"),
                }
            )
        output = {"query": query, "results": results}
        await _complete_tool_run(tool_run_id, "completed", output)
        return json.dumps(output)

    @tool("web_fetch")
    async def web_fetch(url: str, extractMode: str = "markdown", maxChars: int = 20000) -> str:
        """Fetch and extract readable content from a URL (HTML → markdown/text)."""
        payload: dict[str, Any] = {"url": url, "extractMode": extractMode, "maxChars": maxChars}
        budget_message = await _enforce_tool_budget("web_fetch", payload)
        if budget_message:
            return budget_message
        tool_run_id = await _create_auto_tool_run("web_fetch", payload)
        if not url:
            await _complete_tool_run(tool_run_id, "failed", {"error": "url is required"})
            return "web_fetch error: url is required"
        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                html = resp.text
        except httpx.HTTPStatusError as exc:
            await _complete_tool_run(tool_run_id, "failed", {"error": exc.response.text})
            return f"web_fetch error: {exc.response.text}"
        except httpx.RequestError as exc:
            await _complete_tool_run(tool_run_id, "failed", {"error": str(exc)})
            return f"web_fetch error: {exc}"
        doc = Document(html)
        content_html = doc.summary()
        if extractMode == "text":
            text = BeautifulSoup(content_html, "html.parser").get_text("\n")
            text = text.strip()
            output = {"url": url, "content": text[:maxChars]}
            await _complete_tool_run(tool_run_id, "completed", output)
            return json.dumps(output)
        markdown = md(content_html, heading_style="ATX")
        markdown = markdown.strip()
        output = {"url": url, "content": markdown[:maxChars]}
        await _complete_tool_run(tool_run_id, "completed", output)
        return json.dumps(output)

    @tool("schedule_create")
    async def schedule_create(
        name: str,
        prompt: str,
        cron: Optional[str] = None,
        run_at: Optional[str] = None,
        channel_id: Optional[str] = None,
    ) -> str:
        """Create a scheduled job using a cron expression or run_at timestamp (ISO-8601)."""
        payload: dict[str, Any] = {
            "name": name,
            "prompt": prompt,
            "cron": cron,
            "run_at": run_at,
            "channel_id": channel_id,
        }
        budget_message = await _enforce_tool_budget("schedule_create", payload)
        if budget_message:
            return budget_message
        tool_run_id = await _create_auto_tool_run("schedule_create", payload)
        if scheduler_service is None:
            await _complete_tool_run(tool_run_id, "failed", {"error": "scheduler not configured"})
            return "schedule_create error: scheduler not configured"
        if not prompt:
            await _complete_tool_run(tool_run_id, "failed", {"error": "prompt is required"})
            return "schedule_create error: prompt is required"
        if not cron and not run_at:
            await _complete_tool_run(tool_run_id, "failed", {"error": "cron or run_at is required"})
            return "schedule_create error: cron or run_at is required"
        if run_at:
            cron = f"DATE:{run_at}"
        target_channel = channel_id or _channel_id()
        async with SessionLocal() as session:
            repo = Repository(session)
            user = await repo.get_user_by_id(_user_id())
            if user is None:
                await _complete_tool_run(tool_run_id, "failed", {"error": "user not found"})
                return "schedule_create error: user not found"
        result = await scheduler_service.create_job(user.id, target_channel, name or "Scheduled job", prompt, cron)
        await _complete_tool_run(tool_run_id, "failed" if isinstance(result, dict) and result.get("error") else "completed", result if isinstance(result, dict) else {"result": result})
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
        payload: dict[str, Any] = {
            "job_id": job_id,
            "cron": cron,
            "run_at": run_at,
            "prompt": prompt,
            "enabled": enabled,
        }
        budget_message = await _enforce_tool_budget("schedule_update", payload)
        if budget_message:
            return budget_message
        tool_run_id = await _create_auto_tool_run("schedule_update", payload)
        if scheduler_service is None:
            await _complete_tool_run(tool_run_id, "failed", {"error": "scheduler not configured"})
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
        await _complete_tool_run(tool_run_id, "failed" if isinstance(result, dict) and result.get("error") else "completed", result if isinstance(result, dict) else {"result": result})
        return json.dumps(result)

    @tool("schedule_delete")
    async def schedule_delete(job_id: str) -> str:
        """Delete a scheduled job."""
        payload: dict[str, Any] = {"job_id": job_id}
        budget_message = await _enforce_tool_budget("schedule_delete", payload)
        if budget_message:
            return budget_message
        tool_run_id = await _create_auto_tool_run("schedule_delete", payload)
        if scheduler_service is None:
            await _complete_tool_run(tool_run_id, "failed", {"error": "scheduler not configured"})
            return "schedule_delete error: scheduler not configured"
        result = await scheduler_service.delete_job(job_id)
        await _complete_tool_run(tool_run_id, "failed" if isinstance(result, dict) and result.get("error") else "completed", result if isinstance(result, dict) else {"result": result})
        return json.dumps(result)

    @tool("schedule_list")
    async def schedule_list() -> str:
        """List scheduled jobs for the current user."""
        payload: dict[str, Any] = {"user_id": _user_id()}
        budget_message = await _enforce_tool_budget("schedule_list", payload)
        if budget_message:
            return budget_message
        tool_run_id = await _create_auto_tool_run("schedule_list", payload)
        if scheduler_service is None:
            await _complete_tool_run(tool_run_id, "failed", {"error": "scheduler not configured"})
            return "schedule_list error: scheduler not configured"
        async with SessionLocal() as session:
            repo = Repository(session)
            user = await repo.get_user_by_id(_user_id())
            if user is None:
                await _complete_tool_run(tool_run_id, "failed", {"error": "user not found"})
                return "schedule_list error: user not found"
        jobs = await scheduler_service.list_jobs(user.id)
        output = {"jobs": jobs}
        await _complete_tool_run(tool_run_id, "completed", output)
        return json.dumps(output)

    @tool("memory_search")
    async def memory_search(query: str, top_k: int = 5) -> str:
        """Search memories (content of the folder `memory`) by semantic similarity."""
        payload: dict[str, Any] = {"query": query, "top_k": top_k}
        budget_message = await _enforce_tool_budget("memory_search", payload)
        if budget_message:
            return budget_message
        tool_run_id = await _create_auto_tool_run("memory_search", payload)
        if not query.strip():
            await _complete_tool_run(tool_run_id, "failed", {"error": "query is required"})
            return "memory_search error: query is required"
        try:
            results = await memory_service.search(_user_id(), query, top_k)
        except Exception as exc:
            await _complete_tool_run(tool_run_id, "failed", {"error": str(exc)})
            return f"memory_search error: {exc}"
        output = {"query": query, "results": results}
        await _complete_tool_run(tool_run_id, "completed", output)
        return json.dumps(output)

    @tool("sub_agent")
    async def sub_agent(
        task: str,
        name: Optional[str] = None,
        context: Optional[str] = None,
        acceptance_criteria: Optional[str] = None,
    ) -> str:
        """Delegate a focused task to a single sub-agent worker."""
        payload: dict[str, Any] = {
            "task": task,
            "name": name,
            "context": context,
            "acceptance_criteria": acceptance_criteria,
        }
        budget_message = await _enforce_tool_budget("sub_agent", payload)
        if budget_message:
            return budget_message
        if not task or not task.strip():
            return await _fail_untracked_call("sub_agent", payload, "sub_agent error: task is required")
        if subagent_service is None:
            return await _fail_untracked_call("sub_agent", payload, "sub_agent error: sub-agent service unavailable")
        decision = await _maybe_approve("sub_agent", payload, approval_service, policy)
        if not decision.approved:
            return _denied_message("sub_agent")

        spec = SubAgentTaskSpec(
            task=task.strip(),
            name=(name or "").strip() or None,
            context=(context or "").strip() or None,
            acceptance_criteria=(acceptance_criteria or "").strip() or None,
        )
        result = await subagent_service.run_one(
            user_id=_user_id(),
            session_id=_session_id(),
            model_name=worker_model_name,
            system_prompt=build_system_prompt(_user_id()),
            spec=spec,
        )
        output = {
            "worker": result.to_dict(),
            "summary": _subagent_summary(result),
        }
        status = "completed" if result.status == "completed" else "failed"
        await _complete_tool_run(decision.tool_run_id, status, output)
        return json.dumps(
            {
                "worker": _subagent_manager_result(result),
                "summary": _subagent_summary(result),
            }
        )

    @tool("sub_agent_batch")
    async def sub_agent_batch(tasks: list[dict[str, Any]]) -> str:
        """Delegate multiple focused tasks to sub-agents and run them concurrently."""
        payload: dict[str, Any] = {"tasks": tasks}
        budget_message = await _enforce_tool_budget("sub_agent_batch", payload)
        if budget_message:
            return budget_message
        if subagent_service is None:
            return await _fail_untracked_call(
                "sub_agent_batch",
                payload,
                "sub_agent_batch error: sub-agent service unavailable",
            )
        if not isinstance(tasks, list) or not tasks:
            return await _fail_untracked_call(
                "sub_agent_batch",
                payload,
                "sub_agent_batch error: tasks must be a non-empty list",
            )
        max_batch = max(1, int(settings.subagent_max_tasks_per_batch))
        if len(tasks) > max_batch:
            return await _fail_untracked_call(
                "sub_agent_batch",
                payload,
                f"sub_agent_batch error: batch size exceeds configured max ({max_batch})",
            )

        specs: list[SubAgentTaskSpec] = []
        for idx, item in enumerate(tasks, start=1):
            if not isinstance(item, dict):
                return await _fail_untracked_call(
                    "sub_agent_batch",
                    payload,
                    f"sub_agent_batch error: task #{idx} must be an object",
                )
            task_value = str(item.get("task") or "").strip()
            if not task_value:
                return await _fail_untracked_call(
                    "sub_agent_batch",
                    payload,
                    f"sub_agent_batch error: task #{idx} is missing task text",
                )
            specs.append(
                SubAgentTaskSpec(
                    task=task_value,
                    name=str(item.get("name") or "").strip() or None,
                    context=str(item.get("context") or "").strip() or None,
                    acceptance_criteria=str(item.get("acceptance_criteria") or "").strip() or None,
                )
            )

        decision = await _maybe_approve("sub_agent_batch", payload, approval_service, policy)
        if not decision.approved:
            return _denied_message("sub_agent_batch")

        results = await subagent_service.run_batch(
            user_id=_user_id(),
            session_id=_session_id(),
            model_name=worker_model_name,
            system_prompt=build_system_prompt(_user_id()),
            specs=specs,
        )
        summary_rows = [
            {
                "name": result.name,
                "status": result.status,
                "summary": _subagent_summary(result),
            }
            for result in results
        ]
        completed_count = sum(1 for result in results if result.status == "completed")
        failed_count = sum(1 for result in results if result.status == "failed")
        timeout_count = sum(1 for result in results if result.status == "timeout")
        aggregate = {
            "total": len(results),
            "completed": completed_count,
            "failed": failed_count,
            "timeout": timeout_count,
        }
        output = {
            "results": [result.to_dict() for result in results],
            "summary": summary_rows,
            "aggregate": aggregate,
        }
        status = "completed" if failed_count == 0 and timeout_count == 0 else "failed"
        await _complete_tool_run(decision.tool_run_id, status, output)
        return json.dumps({"results": summary_rows, "aggregate": aggregate})

    model = build_llm(model_name=model_name, purpose=purpose)
    tools = [
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
        create_secret,
        memory_search,
        web_search,
        web_fetch,
        schedule_create,
        schedule_update,
        schedule_delete,
        schedule_list,
    ]
    if include_subagent_tools:
        tools.extend([sub_agent, sub_agent_batch])
    return create_agent(
        model,
        tools=tools,
        system_prompt=None,
    )
