from __future__ import annotations

import json
import base64
import mimetypes
import logging
from pathlib import Path
from contextvars import ContextVar, Token
from typing import Optional, Any
import time

import httpx
from bs4 import BeautifulSoup
from readability import Document
from markdownify import markdownify as md
from langchain.agents import create_agent
from langchain.agents.middleware import ToolRetryMiddleware, ModelRetryMiddleware
from langchain.tools import tool

from .config import SECRETS_APPROVAL_BYPASS_MAGIC, settings
from .llm import build_llm
from .llm import list_models, resolve_model_name
from .prompting import build_system_prompt
from .subagents import SubAgentResult, SubAgentService, SubAgentTaskSpec
from .run_limits import RunCancelledError, get_current_run_limits
from ..tools.approval_service import ApprovalDecision, ToolApprovalService
from ..core.scheduler import SchedulerService
from ..tools.middleware import ToolApprovalPolicy
from ..tools.executors import executor_router, node_executor_hub
from ..tools.sandbox_client import ToolRunnerClient
from ..data.db import SessionLocal
from ..data.models import SCHEDULED_JOB_MODEL_MAIN
from ..data.repositories import Repository
from .embeddings import EmbeddingsClient
from .memory_service import MemoryService
from .workspace import user_workspace_root
from .secrets import SecretsManager
from .mcp import MCPError, extract_mcp_text, mcp_registry
from .web_search import WebSearchConfigError, WebSearchError, search_web

_logger = logging.getLogger(__name__)


_CURRENT_SESSION_ID: ContextVar[str] = ContextVar("skitter_session_id", default="default")
_CURRENT_CHANNEL_ID: ContextVar[str] = ContextVar("skitter_channel_id", default="default")
_CURRENT_USER_ID: ContextVar[str] = ContextVar("skitter_user_id", default="default")
_CURRENT_ORIGIN: ContextVar[str] = ContextVar("skitter_origin", default="unknown")
_CURRENT_SCOPE_TYPE: ContextVar[str] = ContextVar("skitter_scope_type", default="private")
_CURRENT_SCOPE_ID: ContextVar[str] = ContextVar("skitter_scope_id", default="default")
_CURRENT_RUN_ID: ContextVar[str] = ContextVar("skitter_run_id", default="")
_CURRENT_MESSAGE_ID: ContextVar[str] = ContextVar("skitter_message_id", default="")


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


def set_current_scope_type(scope_type: str) -> Token:
    return _CURRENT_SCOPE_TYPE.set(scope_type)


def reset_current_scope_type(token: Token) -> None:
    _CURRENT_SCOPE_TYPE.reset(token)


def set_current_scope_id(scope_id: str) -> Token:
    return _CURRENT_SCOPE_ID.set(scope_id)


def reset_current_scope_id(token: Token) -> None:
    _CURRENT_SCOPE_ID.reset(token)


def set_current_run_id(run_id: str) -> Token:
    return _CURRENT_RUN_ID.set(run_id)


def reset_current_run_id(token: Token) -> None:
    _CURRENT_RUN_ID.reset(token)


def set_current_message_id(message_id: str) -> Token:
    return _CURRENT_MESSAGE_ID.set(message_id)


def reset_current_message_id(token: Token) -> None:
    _CURRENT_MESSAGE_ID.reset(token)


def _session_id() -> str:
    return _CURRENT_SESSION_ID.get()

def _channel_id() -> str:
    return _CURRENT_CHANNEL_ID.get()


def _user_id() -> str:
    return _CURRENT_USER_ID.get()


def _origin() -> str:
    return _CURRENT_ORIGIN.get()


def _scope_type() -> str:
    return _CURRENT_SCOPE_TYPE.get()


def _scope_id() -> str:
    return _CURRENT_SCOPE_ID.get()


def _run_id() -> str:
    return _CURRENT_RUN_ID.get()


def _message_id() -> str:
    return _CURRENT_MESSAGE_ID.get()


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
                run_id=_run_id() or None,
                message_id=_message_id() or None,
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
                run_id=_run_id() or None,
                message_id=_message_id() or None,
            )
        return ApprovalDecision(tool_run_id=tool_run.id, approved=False)
    return await approval_service.request(
        session_id=_session_id(),
        channel_id=_channel_id(),
        tool_name=tool_name,
        payload=payload,
        requested_by=_user_id(),
        run_id=_run_id() or None,
        message_id=_message_id() or None,
    )


def build_graph(
    approval_service: ToolApprovalService | None = None,
    scheduler_service: SchedulerService | None = None,
    job_service=None,
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
                job_service=None,
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
        normalized = str(raw_path).strip()
        if normalized.startswith("sandbox:/workspace/"):
            normalized = str(Path("/workspace") / Path(normalized.removeprefix("sandbox:/workspace/")))
        elif normalized == "sandbox:/workspace":
            normalized = "/workspace"
        path = Path(normalized)
        if str(path) == "/workspace":
            resolved = workspace
        elif str(path).startswith("/workspace/"):
            resolved = workspace / Path(str(path).replace("/workspace/", "", 1))
        elif path.is_absolute():
            # Non-workspace absolute paths are literal sandbox host paths and should
            # not be remapped into the workspace.
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

    def _normalize_target_machine(target_machine: str | None) -> str | None:
        value = str(target_machine or "").strip()
        return value or None

    def _normalize_machine_target(target_machine: str | None) -> str | None:
        value = _normalize_target_machine(target_machine)
        if not value:
            return None
        if value.lower() in {"api", "server", "api-server", "local-api"}:
            return "api"
        return value

    def _is_api_target(target_machine: str | None) -> bool:
        return _normalize_machine_target(target_machine) == "api"

    def _with_target_machine(payload: dict[str, Any], target_machine: str | None) -> dict[str, Any]:
        machine = _normalize_machine_target(target_machine)
        if not machine:
            return payload
        merged = dict(payload)
        merged["target_machine"] = machine
        return merged

    def _workspace_relative_path(path: Path) -> str:
        workspace = user_workspace_root(_user_id()).resolve()
        try:
            rel = path.resolve(strict=False).relative_to(workspace)
        except ValueError:
            return str(path).replace("\\", "/")
        value = str(rel).replace("\\", "/")
        return value if value and value != "." else "."

    def _resolve_api_workspace_file(raw_path: str) -> Path | None:
        return _resolve_workspace_path(_user_id(), raw_path)

    def _local_mime_type(path: Path) -> str:
        return mimetypes.guess_type(path.name)[0] or "application/octet-stream"

    async def _read_blob_from_target(
        *,
        path: str,
        target_machine: str | None,
    ) -> tuple[bytes, str, str, dict[str, Any] | None]:
        machine = _normalize_machine_target(target_machine)
        if _is_api_target(machine):
            resolved = _resolve_api_workspace_file(path)
            if resolved is None or not resolved.exists() or not resolved.is_file():
                raise RuntimeError(f"Source file not found in API workspace: {path}")
            data = resolved.read_bytes()
            return data, _local_mime_type(resolved), _workspace_relative_path(resolved), None

        payload = {"path": path, "include_base64": True}
        result, dispatch = await client.execute(
            _user_id(),
            _session_id(),
            "read",
            payload,
            target_machine=machine,
        )
        if not isinstance(result, dict):
            raise RuntimeError("read returned an invalid response")
        raw_b64 = str(result.get("base64") or "")
        if not raw_b64:
            raise RuntimeError(
                f"read did not return file bytes for `{path}`. Use a file path (not a directory) and try again."
            )
        try:
            data = base64.b64decode(raw_b64)
        except Exception as exc:  # pragma: no cover - defensive
            raise RuntimeError("read returned invalid base64 data") from exc
        content_type = str(result.get("content_type") or "").strip() or "application/octet-stream"
        file_path = str(result.get("file_path") or path).strip() or path
        return data, content_type, file_path, dispatch if isinstance(dispatch, dict) else None

    async def _write_blob_to_target(
        *,
        path: str,
        data: bytes,
        target_machine: str | None,
        overwrite: bool,
    ) -> tuple[str, dict[str, Any] | None]:
        machine = _normalize_machine_target(target_machine)
        if _is_api_target(machine):
            resolved = _resolve_api_workspace_file(path)
            if resolved is None:
                raise RuntimeError(f"Destination path is not allowed in API workspace: {path}")
            if resolved.exists() and not overwrite:
                raise RuntimeError(f"Destination already exists: {path}")
            resolved.parent.mkdir(parents=True, exist_ok=True)
            resolved.write_bytes(data)
            return _workspace_relative_path(resolved), None

        payload = {
            "path": path,
            "base64": base64.b64encode(data).decode("ascii"),
            "overwrite": overwrite,
        }
        result, dispatch = await client.execute(
            _user_id(),
            _session_id(),
            "write",
            payload,
            target_machine=machine,
        )
        if not isinstance(result, dict):
            raise RuntimeError("write returned an invalid response")
        written_path = str(result.get("path") or result.get("file_path") or path).strip() or path
        return written_path, dispatch if isinstance(dispatch, dict) else None

    def _secrets_approval_required() -> bool:
        value = str(settings.approval_secrets_required or "").strip()
        return value != SECRETS_APPROVAL_BYPASS_MAGIC

    def _secret_env_key(name: str) -> str:
        key = "".join(ch if ch.isalnum() else "_" for ch in name.strip()).upper()
        if not key:
            key = "SECRET"
        if key[0].isdigit():
            key = f"_{key}"
        return f"{key}"

    def _denied_message(tool_name: str) -> str:
        return f"{tool_name} denied: Request was denied by the user, please ask them for clarification."

    def _limit_message(reason: str, detail: str) -> str:
        return (
            f"LIMIT_REACHED ({reason}): {detail}. "
            "Stop calling tools and provide the best possible final response from current context."
        )

    async def _job_cancel_requested() -> bool:
        run_id = (_run_id() or "").strip()
        if not run_id.startswith("job:"):
            return False
        job_id = run_id.split(":", 1)[1].strip()
        if not job_id:
            return False
        async with SessionLocal() as session:
            repo = Repository(session)
            job = await repo.get_agent_job(job_id)
        return bool(job and job.cancel_requested)

    async def _consume_tool_budget(tool_name: str) -> str | None:
        if await _job_cancel_requested():
            raise RunCancelledError("Background job cancellation requested by user.")
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

    def _serialize_job(job: Any) -> dict[str, Any]:
        return {
            "id": job.id,
            "name": job.name,
            "kind": job.kind,
            "status": job.status,
            "model": job.model,
            "target_scope_type": job.target_scope_type,
            "target_scope_id": job.target_scope_id,
            "target_origin": job.target_origin,
            "target_destination_id": job.target_destination_id,
            "payload": job.payload or {},
            "limits": job.limits or {},
            "result": job.result or {},
            "error": job.error,
            "cancel_requested": bool(job.cancel_requested),
            "tool_calls_used": int(job.tool_calls_used or 0),
            "input_tokens": int(job.input_tokens or 0),
            "output_tokens": int(job.output_tokens or 0),
            "total_tokens": int(job.total_tokens or 0),
            "cost": float(job.cost or 0.0),
            "created_at": job.created_at.isoformat() if job.created_at else None,
            "started_at": job.started_at.isoformat() if job.started_at else None,
            "finished_at": job.finished_at.isoformat() if job.finished_at else None,
            "delivered_at": job.delivered_at.isoformat() if job.delivered_at else None,
            "delivery_error": job.delivery_error,
        }

    async def _resolve_machine_row(repo: Repository, target_machine: str | None):
        target = (target_machine or "").strip()
        if not target:
            target = (
                await executor_router.get_session_default(_session_id())
                or await repo.get_user_default_executor_id(_user_id())
            )
        if not target and settings.executors_auto_docker_default:
            target = "docker-default"
        if not target:
            return None
        if target.lower() in {"docker", "docker-default"}:
            if settings.executors_auto_docker_default:
                return await repo.get_or_create_docker_executor(_user_id())
            return await repo.get_docker_executor_for_user(_user_id())
        row = await repo.get_executor_for_user(_user_id(), target)
        if row is None:
            row = await repo.get_executor_for_user_by_name(_user_id(), target)
        return row

    async def _serialize_machine(row: Any, *, session_default_id: str | None, user_default_id: str | None) -> dict[str, Any]:
        online_ids = set(await node_executor_hub.online_executor_ids())
        online = row.kind == "docker" or row.id in online_ids
        status = "online" if online else (row.status or "offline")
        return {
            "id": row.id,
            "name": row.name,
            "kind": row.kind,
            "platform": row.platform,
            "hostname": row.hostname,
            "status": status,
            "online": online,
            "disabled": bool(row.disabled),
            "last_seen_at": row.last_seen_at.isoformat() if row.last_seen_at else None,
            "capabilities": row.capabilities or {},
            "is_session_default": row.id == session_default_id,
            "is_user_default": row.id == user_default_id,
        }

    async def _create_auto_tool_run(tool_name: str, payload: dict[str, Any]) -> str:
        async with SessionLocal() as session:
            repo = Repository(session)
            tool_run = await repo.create_tool_run(
                session_id=_session_id(),
                tool_name=tool_name,
                status="approved",
                input_payload=payload,
                approved_by="auto",
                run_id=_run_id() or None,
                message_id=_message_id() or None,
            )
        return tool_run.id

    async def _enforce_tool_budget(tool_name: str, payload: dict[str, Any]) -> str | None:
        try:
            message = await _consume_tool_budget(tool_name)
        except RunCancelledError as exc:
            tool_run_id = await _create_auto_tool_run(tool_name, payload)
            await _complete_tool_run(
                tool_run_id,
                "denied",
                {"error": str(exc), "reason": "cancelled"},
            )
            raise
        if message is None:
            return None
        tool_run_id = await _create_auto_tool_run(tool_name, payload)
        await _complete_tool_run(
            tool_run_id,
            "denied",
            {"error": message, "reason": "limit_reached"},
        )
        return message

    async def _complete_tool_run(
        tool_run_id: str | None,
        status: str,
        output: dict[str, Any],
        executor_id: str | None = None,
    ) -> None:
        if not tool_run_id:
            return
        async with SessionLocal() as session:
            repo = Repository(session)
            await repo.complete_tool_run(tool_run_id, status, output, executor_id=executor_id)

    async def _fail_untracked_call(tool_name: str, payload: dict[str, Any], message: str) -> str:
        tool_run_id = await _create_auto_tool_run(tool_name, payload)
        await _complete_tool_run(tool_run_id, "failed", {"error": message})
        return message

    def _http_error_detail(response: httpx.Response) -> str:
        detail = ""
        try:
            payload = response.json()
        except ValueError:
            payload = None
        if isinstance(payload, dict):
            raw_detail = payload.get("detail")
            if isinstance(raw_detail, str):
                detail = raw_detail.strip()
            elif raw_detail is not None:
                detail = json.dumps(raw_detail, ensure_ascii=False)
        if not detail:
            detail = (response.text or "").strip()
        if not detail:
            detail = "No error body returned."
        return f"{response.status_code} {response.reason_phrase}: {detail}"

    async def _execute_sandbox_tool(
        tool_name: str,
        tool_run_id: str | None,
        payload: dict[str, Any],
        timeout: float | None = None,
        target_machine: str | None = None,
    ) -> tuple[Any | None, str | None]:
        try:
            result, dispatch = await client.execute(
                _user_id(),
                _session_id(),
                tool_name,
                payload,
                timeout=timeout,
                target_machine=target_machine,
            )
        except httpx.HTTPStatusError as exc:
            detail = _http_error_detail(exc.response)
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
        output_payload = result if isinstance(result, dict) else {"result": result}
        executor_id = None
        if isinstance(dispatch, dict):
            executor_id = str(dispatch.get("executor_id") or "").strip() or None
        await _complete_tool_run(tool_run_id, "completed", output_payload, executor_id=executor_id)
        return result, None

    @tool("read")
    async def read(
        path: Optional[str] = None,
        offset: Optional[int] = None,
        limit: Optional[int] = None,
        file_path: Optional[str] = None,
        target_machine: Optional[str] = None,
    ) -> str:
        """Read a file. Returns the file content for text files, and allows you to see images for image files. Relative paths are resolved from workspace root (/workspace). Absolute paths are treated as literal sandbox paths."""
        target = _coalesce_path(path, file_path)
        if not target:
            return await _fail_untracked_call("read", {"path": path, "file_path": file_path}, "read error: path is required")
        payload: dict[str, Any] = {"path": target}
        if offset is not None:
            payload["offset"] = offset
        if limit is not None:
            payload["limit"] = limit
        machine = _normalize_target_machine(target_machine)
        approval_payload = _with_target_machine(payload, machine)
        budget_message = await _enforce_tool_budget("read", approval_payload)
        if budget_message:
            return budget_message
        decision = await _maybe_approve("read", approval_payload, approval_service, policy)
        if not decision.approved:
            return _denied_message("read")
        result, error = await _execute_sandbox_tool(
            "read",
            decision.tool_run_id,
            payload,
            target_machine=machine,
        )
        if error:
            return error
        if isinstance(result, dict):
            content_type = str(result.get("content_type") or "").lower()
            file_path = str(result.get("file_path") or "")
            if content_type.startswith("image/") and file_path:
                data: bytes | None = None
                resolved = _resolve_workspace_path(_user_id(), file_path)
                if resolved and resolved.exists():
                    try:
                        data = resolved.read_bytes()
                    except OSError:
                        data = None
                if data is None:
                    fetch_payload = {"path": target, "include_base64": True}
                    try:
                        fetched, _dispatch = await client.execute(
                            _user_id(),
                            _session_id(),
                            "read",
                            fetch_payload,
                            target_machine=machine,
                        )
                    except Exception:
                        fetched = None
                    if isinstance(fetched, dict):
                        remote_b64 = str(fetched.get("base64") or "")
                        if remote_b64:
                            try:
                                data = base64.b64decode(remote_b64)
                            except Exception:
                                data = None
                if data is not None:
                    b64 = base64.b64encode(data).decode("ascii")
                    _logger.debug(
                        "read returned multimodal image block (user_id=%s session_id=%s path=%s content_type=%s bytes=%d)",
                        _user_id(),
                        _session_id(),
                        file_path,
                        content_type,
                        len(data),
                    )
                    return [
                        {"type": "text", "text": f"Read image: {file_path} ({content_type})"},
                        {"type": "image", "base64": b64, "mime_type": content_type},
                    ]
        return json.dumps(result)

    @tool("write")
    async def write(
        path: Optional[str] = None,
        content: Optional[str] = None,
        file_path: Optional[str] = None,
        target_machine: Optional[str] = None,
    ) -> str:
        """Write content to a file. Relative paths are resolved from workspace root (/workspace). Absolute paths are treated as literal sandbox paths."""
        target = _coalesce_path(path, file_path)
        if not target:
            return await _fail_untracked_call("write", {"path": path, "file_path": file_path}, "write error: path is required")
        if content is None:
            return await _fail_untracked_call("write", {"path": target}, "write error: content is required")
        payload = {"path": target, "content": content}
        machine = _normalize_target_machine(target_machine)
        approval_payload = _with_target_machine(payload, machine)
        budget_message = await _enforce_tool_budget("write", approval_payload)
        if budget_message:
            return budget_message
        decision = await _maybe_approve("write", approval_payload, approval_service, policy)
        if not decision.approved:
            return _denied_message("write")
        result, error = await _execute_sandbox_tool(
            "write",
            decision.tool_run_id,
            payload,
            target_machine=machine,
        )
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
        target_machine: Optional[str] = None,
    ) -> str:
        """Edit a file by exact text replacement. Relative paths are resolved from workspace root (/workspace). Absolute paths are treated as literal sandbox paths."""
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
        machine = _normalize_target_machine(target_machine)
        approval_payload = _with_target_machine(payload, machine)
        budget_message = await _enforce_tool_budget("edit", approval_payload)
        if budget_message:
            return budget_message
        decision = await _maybe_approve("edit", approval_payload, approval_service, policy)
        if not decision.approved:
            return _denied_message("edit")
        result, error = await _execute_sandbox_tool(
            "edit",
            decision.tool_run_id,
            payload,
            target_machine=machine,
        )
        if error:
            return error
        return json.dumps(result)

    @tool("list")
    async def list_files(
        path: Optional[str] = None,
        file_path: Optional[str] = None,
        show_hidden_files: Optional[bool] = None,
        target_machine: Optional[str] = None,
    ) -> str:
        """List files/folders. Relative paths are resolved from workspace root (/workspace). Absolute paths are treated as literal sandbox paths. Hidden files are excluded by default."""
        target = _coalesce_path(path, file_path)
        if not target:
            return await _fail_untracked_call("list", {"path": path, "file_path": file_path}, "list error: path is required")
        payload = {"path": target, "show_hidden_files": bool(show_hidden_files)}
        machine = _normalize_target_machine(target_machine)
        approval_payload = _with_target_machine(payload, machine)
        budget_message = await _enforce_tool_budget("list", approval_payload)
        if budget_message:
            return budget_message
        decision = await _maybe_approve("list", approval_payload, approval_service, policy)
        if not decision.approved:
            return _denied_message("list")
        result, error = await _execute_sandbox_tool(
            "list",
            decision.tool_run_id,
            payload,
            target_machine=machine,
        )
        if error:
            return error
        return json.dumps(result)

    @tool("delete")
    async def delete(
        path: Optional[str] = None,
        recursive: Optional[bool] = None,
        file_path: Optional[str] = None,
        target_machine: Optional[str] = None,
    ) -> str:
        """Delete a file/folder. Relative paths are resolved from workspace root (/workspace). Absolute paths are treated as literal sandbox paths. Use recursive=true for non-empty folders."""
        target = _coalesce_path(path, file_path)
        if not target:
            return await _fail_untracked_call("delete", {"path": path, "file_path": file_path}, "delete error: path is required")
        payload = {"path": target, "recursive": bool(recursive)}
        machine = _normalize_target_machine(target_machine)
        approval_payload = _with_target_machine(payload, machine)
        budget_message = await _enforce_tool_budget("delete", approval_payload)
        if budget_message:
            return budget_message
        if payload["recursive"] and approval_service is None:
            return await _fail_untracked_call("delete", payload, "delete error: recursive delete requires approval")
        decision = await _maybe_approve("delete", approval_payload, approval_service, policy)
        if not decision.approved:
            return _denied_message("delete")
        result, error = await _execute_sandbox_tool(
            "delete",
            decision.tool_run_id,
            payload,
            target_machine=machine,
        )
        if error:
            return error
        return json.dumps(result)

    @tool("download")
    async def download(
        url: str,
        path: Optional[str] = None,
        target_machine: Optional[str] = None,
    ) -> str:
        """Download a URL into the workspace. Optional path can be relative (resolved from /workspace) or absolute sandbox path."""
        if not url:
            return await _fail_untracked_call("download", {"url": url, "path": path}, "download error: url is required")
        payload: dict[str, Any] = {"url": url}
        if path:
            payload["path"] = path
        machine = _normalize_target_machine(target_machine)
        approval_payload = _with_target_machine(payload, machine)
        budget_message = await _enforce_tool_budget("download", approval_payload)
        if budget_message:
            return budget_message
        decision = await _maybe_approve("download", approval_payload, approval_service, policy)
        if not decision.approved:
            return _denied_message("download")
        result, error = await _execute_sandbox_tool(
            "download",
            decision.tool_run_id,
            payload,
            target_machine=machine,
        )
        if error:
            return error
        return json.dumps(result)

    @tool("transfer_file")
    async def transfer_file(
        source_path: str,
        destination_path: str,
        source_machine: Optional[str] = None,
        destination_machine: Optional[str] = None,
        overwrite: Optional[bool] = None,
    ) -> str:
        """Transfer a file between executors. Use target machine `api` to transfer to/from the API server workspace."""
        source = str(source_path or "").strip()
        destination = str(destination_path or "").strip()
        if not source:
            return await _fail_untracked_call(
                "transfer_file",
                {"source_path": source_path, "destination_path": destination_path},
                "transfer_file error: source_path is required",
            )
        if not destination:
            return await _fail_untracked_call(
                "transfer_file",
                {"source_path": source_path, "destination_path": destination_path},
                "transfer_file error: destination_path is required",
            )

        source_target = _normalize_machine_target(source_machine)
        destination_target = _normalize_machine_target(destination_machine)
        should_overwrite = bool(overwrite)
        payload: dict[str, Any] = {
            "source_path": source,
            "destination_path": destination,
            "overwrite": should_overwrite,
        }
        if source_target:
            payload["source_machine"] = source_target
        if destination_target:
            payload["destination_machine"] = destination_target

        budget_message = await _enforce_tool_budget("transfer_file", payload)
        if budget_message:
            return budget_message
        decision = await _maybe_approve("transfer_file", payload, approval_service, policy)
        if not decision.approved:
            return _denied_message("transfer_file")

        source_dispatch: dict[str, Any] | None = None
        destination_dispatch: dict[str, Any] | None = None
        try:
            data, content_type, source_file_path, source_dispatch = await _read_blob_from_target(
                path=source,
                target_machine=source_target,
            )
            destination_file_path, destination_dispatch = await _write_blob_to_target(
                path=destination,
                data=data,
                target_machine=destination_target,
                overwrite=should_overwrite,
            )
        except Exception as exc:
            detail = str(exc)
            await _complete_tool_run(decision.tool_run_id, "failed", {"error": detail})
            return f"transfer_file error: {detail}"

        executor_id = None
        if isinstance(destination_dispatch, dict):
            executor_id = str(destination_dispatch.get("executor_id") or "").strip() or None
        if not executor_id and isinstance(source_dispatch, dict):
            executor_id = str(source_dispatch.get("executor_id") or "").strip() or None

        output = {
            "status": "ok",
            "source_path": source_file_path,
            "destination_path": destination_file_path,
            "bytes": len(data),
            "content_type": content_type or "application/octet-stream",
            "source_machine": source_target or "default",
            "destination_machine": destination_target or "default",
        }
        await _complete_tool_run(decision.tool_run_id, "completed", output, executor_id=executor_id)
        return json.dumps(output)

    @tool("attach_file")
    async def attach_file(
        path: Optional[str] = None,
        file_path: Optional[str] = None,
        target_machine: Optional[str] = None,
    ) -> str:
        """Attach a file to the next assistant message. Works for images, audio, PDFs, archives, and other files."""
        target = _coalesce_path(path, file_path)
        if not target:
            return await _fail_untracked_call(
                "attach_file",
                {"path": path, "file_path": file_path},
                "attach_file error: path is required",
            )
        machine = _normalize_machine_target(target_machine)
        payload = _with_target_machine({"path": target}, machine)
        budget_message = await _enforce_tool_budget("attach_file", payload)
        if budget_message:
            return budget_message
        decision = await _maybe_approve("attach_file", payload, approval_service, policy)
        if not decision.approved:
            return _denied_message("attach_file")

        executor_id = None
        content_type = "application/octet-stream"
        size = None
        resolved_attachment_path = target
        machine_hint = machine
        try:
            if _is_api_target(machine):
                resolved = _resolve_api_workspace_file(target)
                if resolved is None or not resolved.exists() or not resolved.is_file():
                    raise RuntimeError(f"File not found in API workspace: {target}")
                resolved_attachment_path = _workspace_relative_path(resolved)
                content_type = _local_mime_type(resolved)
                size = resolved.stat().st_size
            else:
                check_result, dispatch = await client.execute(
                    _user_id(),
                    _session_id(),
                    "read",
                    {"path": target},
                    target_machine=machine,
                )
                if isinstance(dispatch, dict):
                    executor_id = str(dispatch.get("executor_id") or "").strip() or None
                    if not machine_hint:
                        machine_hint = (
                            str(dispatch.get("executor_id") or dispatch.get("executor_name") or "").strip() or None
                        )
                if isinstance(check_result, dict):
                    maybe_type = str(check_result.get("content_type") or "").strip()
                    if maybe_type:
                        content_type = maybe_type
                    maybe_path = str(check_result.get("file_path") or "").strip()
                    if maybe_path:
                        resolved_attachment_path = maybe_path
                    maybe_size = check_result.get("size")
                    if isinstance(maybe_size, int):
                        size = maybe_size
        except Exception as exc:
            detail = str(exc)
            await _complete_tool_run(decision.tool_run_id, "failed", {"error": detail})
            return f"attach_file error: {detail}"

        output: dict[str, Any] = {
            "status": "ok",
            "attachment_path": resolved_attachment_path,
            "content_type": content_type,
        }
        if size is not None:
            output["size"] = size
        if machine_hint:
            output["target_machine"] = machine_hint
        await _complete_tool_run(decision.tool_run_id, "completed", output, executor_id=executor_id)
        return json.dumps(output)

    @tool("http_fetch")
    async def http_fetch(url: str, target_machine: Optional[str] = None) -> str:
        """Fetch a URL over HTTP."""
        payload = {"url": url}
        machine = _normalize_machine_target(target_machine)
        approval_payload = _with_target_machine(payload, machine)
        budget_message = await _enforce_tool_budget("http_fetch", approval_payload)
        if budget_message:
            return budget_message
        decision = await _maybe_approve("http_fetch", approval_payload, approval_service, policy)
        if not decision.approved:
            return _denied_message("http_fetch")
        result, error = await _execute_sandbox_tool(
            "http_fetch",
            decision.tool_run_id,
            payload,
            target_machine=machine,
        )
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
        target_machine: Optional[str] = None,
    ) -> str:
        """Open a page in a headless browser."""
        payload = {
            "url": url,
            "max_chars": max_chars,
            "screenshot": screenshot,
            "width": width,
            "height": height,
            "timeout_ms": timeout_ms,
            "wait_until": wait_until,
        }
        machine = _normalize_target_machine(target_machine)
        approval_payload = _with_target_machine(payload, machine)
        budget_message = await _enforce_tool_budget("browser", approval_payload)
        if budget_message:
            return budget_message
        decision = await _maybe_approve("browser", approval_payload, approval_service, policy)
        if not decision.approved:
            return _denied_message("browser")
        result, error = await _execute_sandbox_tool(
            "browser",
            decision.tool_run_id,
            payload,
            target_machine=machine,
        )
        if error:
            return error
        return json.dumps(result)

    @tool("browser_action")
    async def browser_action(
        action: str,
        url: Optional[str] = None,
        selector: Optional[str] = None,
        text: Optional[str] = None,
        script: Optional[str] = None,
        arg: Optional[Any] = None,
        x: Optional[float] = None,
        y: Optional[float] = None,
        button: str = "left",
        click_count: int = 1,
        mouse_steps: int = 15,
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
        target_machine: Optional[str] = None,
    ) -> str:
        """Stateful browser automation.

        Actions:
        - Navigation/session: open, navigate, tabs, focus, close_tab, close, status
        - Element actions: click, hover, type, fill, fill_form, login, press, wait
        - Pointer actions: move_mouse, click_at (use x/y or selector/text target)
        - Script action: evaluate (run JavaScript with optional arg and return result)
        - Page capture: snapshot, screenshot
        """
        payload = {
            "action": action,
            "url": url,
            "selector": selector,
            "text": text,
            "script": script,
            "arg": arg,
            "x": x,
            "y": y,
            "button": button,
            "click_count": click_count,
            "mouse_steps": mouse_steps,
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
        machine = _normalize_target_machine(target_machine)
        approval_payload = _with_target_machine(payload, machine)
        budget_message = await _enforce_tool_budget("browser_action", approval_payload)
        if budget_message:
            return budget_message
        decision = await _maybe_approve("browser_action", approval_payload, approval_service, policy)
        if not decision.approved:
            return _denied_message("browser_action")
        timeout_s = max(60, int(timeout_ms / 1000) + 15)
        result, error = await _execute_sandbox_tool(
            "browser_action",
            decision.tool_run_id,
            payload,
            timeout=timeout_s,
            target_machine=machine,
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
        target_machine: Optional[str] = None,
    ) -> str:
        """Run a shell command. Relative paths resolve from the workspace. Absolute paths are literal sandbox paths. Use background=true for long-running tasks. Use secret_refs to inject per-user secrets (e.g. API keys) as env vars. You simply have to reference the secret name and it will be injected."""
        payload = {"cmd": cmd, "background": bool(background)}
        if cwd:
            payload["cwd"] = cwd
        machine = _normalize_target_machine(target_machine)
        approval_payload = _with_target_machine(payload, machine)
        budget_message = await _enforce_tool_budget("shell", approval_payload)
        if budget_message:
            return budget_message
        secrets = _normalize_secret_refs(secret_refs)
        if secrets:
            if background:
                return await _fail_untracked_call("shell", payload, "shell error: secret_refs cannot be used with background commands")
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
            approval_payload = {**approval_payload, "secret_refs": secrets}
            if _secrets_approval_required():
                if approval_service is None:
                    return await _fail_untracked_call("shell", payload, "shell error: secret execution requires approval")
                decision = await approval_service.request(
                    session_id=_session_id(),
                    channel_id=_channel_id(),
                    tool_name="shell",
                    payload=approval_payload,
                    requested_by=_user_id(),
                    run_id=_run_id() or None,
                    message_id=_message_id() or None,
                )
            else:
                decision = await _maybe_approve("shell", approval_payload, approval_service, policy)
            if not decision.approved:
                return _denied_message("shell")
            exec_payload = {**payload, "env": env, "redact": redact}
        else:
            decision = await _maybe_approve("shell", approval_payload, approval_service, policy)
            if not decision.approved:
                return _denied_message("shell")
            exec_payload = payload
        result, error = await _execute_sandbox_tool(
            "shell",
            decision.tool_run_id,
            exec_payload,
            target_machine=machine,
        )
        if error:
            return error
        return json.dumps(result)

    @tool("machine_list")
    async def machine_list(include_disabled: bool = False) -> str:
        """List available execution machines for the current user."""
        payload: dict[str, Any] = {"include_disabled": bool(include_disabled)}
        budget_message = await _enforce_tool_budget("machine_list", payload)
        if budget_message:
            return budget_message
        tool_run_id = await _create_auto_tool_run("machine_list", payload)
        async with SessionLocal() as session:
            repo = Repository(session)
            if settings.executors_auto_docker_default:
                await repo.get_or_create_docker_executor(_user_id())
            rows = await repo.list_executors_for_user(_user_id(), include_disabled=bool(include_disabled))
            user_default_id = await repo.get_user_default_executor_id(_user_id())
        session_default_id = await executor_router.get_session_default(_session_id())
        machines = [
            await _serialize_machine(
                row,
                session_default_id=session_default_id,
                user_default_id=user_default_id,
            )
            for row in rows
        ]
        output = {"machines": machines}
        await _complete_tool_run(tool_run_id, "completed", output)
        return json.dumps(output)

    @tool("machine_status")
    async def machine_status(target_machine: Optional[str] = None) -> str:
        """Get status and capabilities for a specific machine (or current default)."""
        payload: dict[str, Any] = {}
        if target_machine:
            payload["target_machine"] = target_machine
        budget_message = await _enforce_tool_budget("machine_status", payload)
        if budget_message:
            return budget_message
        tool_run_id = await _create_auto_tool_run("machine_status", payload)
        async with SessionLocal() as session:
            repo = Repository(session)
            row = await _resolve_machine_row(repo, target_machine)
            if row is None or row.disabled:
                await _complete_tool_run(tool_run_id, "failed", {"error": "machine not found"})
                return "machine_status error: machine not found"
            user_default_id = await repo.get_user_default_executor_id(_user_id())
        session_default_id = await executor_router.get_session_default(_session_id())
        machine = await _serialize_machine(
            row,
            session_default_id=session_default_id,
            user_default_id=user_default_id,
        )
        output = {"machine": machine}
        await _complete_tool_run(tool_run_id, "completed", output, executor_id=row.id)
        return json.dumps(output)

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

    @tool("list_secrets")
    async def list_secrets() -> str:
        """List available per-user secret names (values are never returned)."""
        payload: dict[str, Any] = {}
        budget_message = await _enforce_tool_budget("list_secrets", payload)
        if budget_message:
            return budget_message
        tool_run_id = await _create_auto_tool_run("list_secrets", payload)

        manager = SecretsManager()
        try:
            manager.ensure_ready()
        except RuntimeError as exc:
            await _complete_tool_run(tool_run_id, "failed", {"error": str(exc)})
            return f"list_secrets error: {exc}"

        async with SessionLocal() as session:
            repo = Repository(session)
            secrets = await repo.list_secrets(_user_id())
        names = sorted(
            {
                name
                for name in ((secret.name or "").strip() for secret in secrets)
                if name
            }
        )
        output = {"secret_names": names, "count": len(names)}
        await _complete_tool_run(tool_run_id, "completed", output)
        return json.dumps(output)

    @tool("model_list")
    async def model_list() -> str:
        """List available model selectors for explicit model choices, including the currently active model for this session. Use this before schedule_create or schedule_update only if the user specifically wants a particular model; otherwise omit model so the main model chain is used."""
        payload: dict[str, Any] = {}
        budget_message = await _enforce_tool_budget("model_list", payload)
        if budget_message:
            return budget_message
        tool_run_id = await _create_auto_tool_run("model_list", payload)
        current_model = None
        async with SessionLocal() as session:
            repo = Repository(session)
            record = await repo.get_session(_session_id())
            if record and getattr(record, "model", None):
                current_model = resolve_model_name(record.model, purpose="main")
            else:
                current_model = resolve_model_name(None, purpose="main")
        models = list_models()
        output = {
            "current_model": current_model,
            "models": [
                {
                    "selector": model.name,
                    "is_current": bool(current_model and model.name.lower() == current_model.lower()),
                }
                for model in models
            ],
            "count": len(models),
        }
        await _complete_tool_run(tool_run_id, "completed", output)
        return json.dumps(output)

    @tool("mcp_list_tools")
    async def mcp_list_tools(server_name: str | None = None) -> str:
        """List tools from configured and enabled MCP servers."""
        payload: dict[str, Any] = {}
        if server_name:
            payload["server_name"] = server_name
        budget_message = await _enforce_tool_budget("mcp_list_tools", payload)
        if budget_message:
            return budget_message
        tool_run_id = await _create_auto_tool_run("mcp_list_tools", payload)
        try:
            output = await mcp_registry.list_tools(server_name=server_name)
        except Exception as exc:
            await _complete_tool_run(tool_run_id, "failed", {"error": str(exc)})
            return f"mcp_list_tools error: {exc}"
        await _complete_tool_run(tool_run_id, "completed", output)
        return json.dumps(output)

    @tool("mcp_call")
    async def mcp_call(
        server_name: str,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
    ) -> str:
        """Call a tool exposed by an MCP server."""
        payload: dict[str, Any] = {
            "server_name": server_name,
            "tool_name": tool_name,
            "arguments": arguments or {},
        }
        budget_message = await _enforce_tool_budget("mcp_call", payload)
        if budget_message:
            return budget_message
        if not (server_name or "").strip():
            return await _fail_untracked_call("mcp_call", payload, "mcp_call error: server_name is required")
        if not (tool_name or "").strip():
            return await _fail_untracked_call("mcp_call", payload, "mcp_call error: tool_name is required")
        decision = await _maybe_approve("mcp_call", payload, approval_service, policy)
        if not decision.approved:
            return _denied_message("mcp_call")
        try:
            result = await mcp_registry.call_tool(
                server_name=server_name.strip(),
                tool_name=tool_name.strip(),
                arguments=arguments or {},
            )
        except MCPError as exc:
            await _complete_tool_run(decision.tool_run_id, "failed", {"error": str(exc)})
            return f"mcp_call error: {exc}"
        except Exception as exc:  # pragma: no cover - defensive
            await _complete_tool_run(decision.tool_run_id, "failed", {"error": str(exc)})
            return f"mcp_call error: {exc}"

        output = {
            "server_name": server_name.strip(),
            "tool_name": tool_name.strip(),
            "result": result,
        }
        await _complete_tool_run(decision.tool_run_id, "completed", output)
        text = extract_mcp_text(result)
        if text.strip():
            return text
        return json.dumps(output)

    @tool("web_search")
    async def web_search(
        query: str,
        count: int = 5,
    ) -> str:
        """Search the web using the configured search engine (Brave or SearXNG)."""
        payload: dict[str, Any] = {
            "query": query,
            "count": count,
            "engine": settings.web_search_engine,
        }
        budget_message = await _enforce_tool_budget("web_search", payload)
        if budget_message:
            return budget_message
        tool_run_id = await _create_auto_tool_run("web_search", payload)
        if not query.strip():
            await _complete_tool_run(tool_run_id, "failed", {"error": "query is required"})
            return "web_search error: query is required"
        try:
            output = await search_web(
                query=query,
                count=count,
            )
        except WebSearchConfigError as exc:
            await _complete_tool_run(tool_run_id, "failed", {"error": str(exc)})
            return f"web_search error: {exc}"
        except WebSearchError as exc:
            await _complete_tool_run(tool_run_id, "failed", {"error": str(exc)})
            return f"web_search error: {exc}"
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
        model: Optional[str] = SCHEDULED_JOB_MODEL_MAIN,
    ) -> str:
        """Create a scheduled job using a cron expression or run_at timestamp (ISO-8601). Usually omit model so the dynamic main model chain is used. If the user explicitly requests a specific model, use model_list first and pass either a valid selector or '__main_chain__'."""
        payload: dict[str, Any] = {
            "name": name,
            "prompt": prompt,
            "cron": cron,
            "run_at": run_at,
            "channel_id": channel_id,
            "model": model,
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
        target_scope_type = _scope_type()
        target_scope_id = _scope_id()
        if target_scope_type not in {"private", "group"}:
            target_scope_type = "private"
            target_scope_id = f"private:{user.id}"
        result = await scheduler_service.create_job(
            user.id,
            target_channel,
            name or "Scheduled job",
            prompt,
            cron,
            model=model or SCHEDULED_JOB_MODEL_MAIN,
            target_scope_type=target_scope_type,
            target_scope_id=target_scope_id,
            target_origin=_origin(),
            target_destination_id=target_channel,
        )
        await _complete_tool_run(tool_run_id, "failed" if isinstance(result, dict) and result.get("error") else "completed", result if isinstance(result, dict) else {"result": result})
        return json.dumps(result)

    @tool("schedule_update")
    async def schedule_update(
        job_id: str,
        cron: Optional[str] = None,
        run_at: Optional[str] = None,
        prompt: Optional[str] = None,
        enabled: Optional[bool] = None,
        model: Optional[str] = None,
    ) -> str:
        """Update a scheduled job. Usually leave model unchanged unless the user explicitly asks. Use model_list if you need valid selectors. Set model='__main_chain__' to reset to the dynamic main model chain."""
        payload: dict[str, Any] = {
            "job_id": job_id,
            "cron": cron,
            "run_at": run_at,
            "prompt": prompt,
            "enabled": enabled,
            "model": model,
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
        if model is not None:
            fields["model"] = model
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
        """Search memory files by semantic similarity.

        Use this tool sparingly:
        - Use only when the user asks to recall past details, or when needed context is not in current chat/file reads.
        - Do not call it for routine replies, greetings, or tasks that can proceed without historical recall.
        - Do not repeat the same query multiple times unless new information changes the need.

        Prefer direct `read` of known files first. `top_k` should stay small (usually 3-5).
        """
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

    @tool("job_start")
    async def job_start(
        task: str,
        name: Optional[str] = None,
        context: Optional[str] = None,
        acceptance_criteria: Optional[str] = None,
        model_name: Optional[str] = None,
    ) -> str:
        """Start a background sub-agent job for long-running work and return a job ID immediately."""
        payload: dict[str, Any] = {
            "task": task,
            "name": name,
            "context": context,
            "acceptance_criteria": acceptance_criteria,
            "model_name": model_name,
        }
        budget_message = await _enforce_tool_budget("job_start", payload)
        if budget_message:
            return budget_message
        if not task or not task.strip():
            return await _fail_untracked_call("job_start", payload, "job_start error: task is required")
        if not settings.jobs_enabled:
            return await _fail_untracked_call("job_start", payload, "job_start error: background jobs are disabled")
        if job_service is None:
            return await _fail_untracked_call("job_start", payload, "job_start error: job service unavailable")
        selected_model = resolve_model_name(model_name or worker_model_name, purpose="main")
        decision = await _maybe_approve("job_start", payload, approval_service, policy)
        if not decision.approved:
            return _denied_message("job_start")
        try:
            job_id = await job_service.enqueue_subagent_job(
                user_id=_user_id(),
                session_id=_session_id(),
                name=(name or "").strip() or "Background sub-agent job",
                task=task.strip(),
                context=(context or "").strip() or None,
                acceptance_criteria=(acceptance_criteria or "").strip() or None,
                model_name=selected_model,
                target_scope_type=_scope_type(),
                target_scope_id=_scope_id(),
                target_origin=_origin(),
                target_destination_id=_channel_id(),
            )
        except Exception as exc:
            await _complete_tool_run(decision.tool_run_id, "failed", {"error": str(exc)})
            return f"job_start error: {exc}"
        output = {
            "job_id": job_id,
            "status": "queued",
            "model": selected_model,
        }
        await _complete_tool_run(decision.tool_run_id, "completed", output)
        return json.dumps(output)

    @tool("job_status")
    async def job_status(job_id: str) -> str:
        """Get current status and result details for a background job."""
        payload: dict[str, Any] = {"job_id": job_id}
        budget_message = await _enforce_tool_budget("job_status", payload)
        if budget_message:
            return budget_message
        tool_run_id = await _create_auto_tool_run("job_status", payload)
        if not job_id.strip():
            await _complete_tool_run(tool_run_id, "failed", {"error": "job_id is required"})
            return "job_status error: job_id is required"
        if job_service is None:
            await _complete_tool_run(tool_run_id, "failed", {"error": "job service unavailable"})
            return "job_status error: job service unavailable"
        job = await job_service.get_job(_user_id(), job_id.strip())
        if job is None:
            await _complete_tool_run(tool_run_id, "failed", {"error": "job not found"})
            return "job_status error: job not found"
        output = {"job": _serialize_job(job)}
        await _complete_tool_run(tool_run_id, "completed", output)
        return json.dumps(output)

    @tool("job_list")
    async def job_list(status: Optional[str] = None, limit: int = 10) -> str:
        """List recent background jobs for the current user."""
        payload: dict[str, Any] = {"status": status, "limit": limit}
        budget_message = await _enforce_tool_budget("job_list", payload)
        if budget_message:
            return budget_message
        tool_run_id = await _create_auto_tool_run("job_list", payload)
        if job_service is None:
            await _complete_tool_run(tool_run_id, "failed", {"error": "job service unavailable"})
            return "job_list error: job service unavailable"
        jobs = await job_service.list_jobs(_user_id(), limit=max(1, min(int(limit), 100)), status=(status or "").strip() or None)
        output = {"jobs": [_serialize_job(job) for job in jobs]}
        await _complete_tool_run(tool_run_id, "completed", output)
        return json.dumps(output)

    @tool("job_cancel")
    async def job_cancel(job_id: str) -> str:
        """Cancel a queued background job or request cancellation for a running one."""
        payload: dict[str, Any] = {"job_id": job_id}
        budget_message = await _enforce_tool_budget("job_cancel", payload)
        if budget_message:
            return budget_message
        tool_run_id = await _create_auto_tool_run("job_cancel", payload)
        if not job_id.strip():
            await _complete_tool_run(tool_run_id, "failed", {"error": "job_id is required"})
            return "job_cancel error: job_id is required"
        if job_service is None:
            await _complete_tool_run(tool_run_id, "failed", {"error": "job service unavailable"})
            return "job_cancel error: job service unavailable"
        job = await job_service.cancel_job(_user_id(), job_id.strip())
        if job is None:
            await _complete_tool_run(tool_run_id, "failed", {"error": "job not found"})
            return "job_cancel error: job not found"
        output = {"job": _serialize_job(job)}
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
        transfer_file,
        attach_file,
        http_fetch,
        browser,
        browser_action,
        shell,
        machine_list,
        machine_status,
        create_secret,
        list_secrets,
        model_list,
        mcp_list_tools,
        mcp_call,
        memory_search,
        web_search,
        web_fetch,
        schedule_create,
        schedule_update,
        schedule_delete,
        schedule_list,
    ]
    if include_subagent_tools:
        tools.extend([job_start, job_status, job_list, job_cancel, sub_agent, sub_agent_batch])

    def _should_retry_tool_exception(exc: Exception) -> bool:
        # Cancellation must short-circuit immediately; do not retry cancelled tool calls.
        return not isinstance(exc, RunCancelledError)

    def _tool_retry_on_failure(exc: Exception) -> str:
        # Raise cancellation through the graph so job runs terminate promptly.
        if isinstance(exc, RunCancelledError):
            raise exc
        error_text = str(exc).strip()
        lowered = error_text.lower()
        is_validation_error = (
            "validationerror" in lowered
            or "validation error" in lowered
            or "input should be" in lowered
            or "for further information visit https://errors.pydantic.dev" in lowered
        )
        if is_validation_error:
            _logger.warning(
                "tool_call_failed: session=%s run=%s reason=tool_input_validation error=%s",
                _session_id(),
                _run_id() or "-",
                error_text,
            )
            if "secret_refs" in lowered and "valid list" in lowered:
                return (
                    "Tool input validation failed: `shell.secret_refs` must be a JSON array of secret names, "
                    "for example `{\"secret_refs\": [\"MOLTBOOK_API_KEY\"]}`. "
                    "Do not pass a quoted JSON string like `\"[\\\"MOLTBOOK_API_KEY\\\"]\"`. "
                    f"Validation detail: {error_text}"
                )
            return (
                "Tool input validation failed: one or more tool arguments have the wrong type/shape for the schema. "
                "Retry the tool call with correctly typed fields. "
                f"Validation detail: {error_text}"
            )
        return (
            f"Tool call failed after retries with {type(exc).__name__}: {error_text}. "
            "Please adjust strategy and continue."
        )

    return create_agent(
        model,
        tools=tools,
        system_prompt=None,
        middleware=[
            ModelRetryMiddleware(
                max_retries=3,
                backoff_factor=2.0,
                initial_delay=3.0,
                # Bubble model failures to runtime so provider/model failover can run.
                on_failure="error",
            ),
            ToolRetryMiddleware(
                max_retries=3,
                backoff_factor=2.0,
                initial_delay=3.0,
                retry_on=_should_retry_tool_exception,
                on_failure=_tool_retry_on_failure,
            )
        ]
    )
