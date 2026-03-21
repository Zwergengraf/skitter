from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request

from ..authz import resolve_target_user_id
from ..deps import get_repo
from ..schemas import CommandExecuteOut, CommandExecuteRequest
from ...core.config import SECRETS_APPROVAL_BYPASS_MAGIC, settings
from ...core.conversation_scope import private_scope_id
from ...core.llm import list_models, resolve_model_name
from ...core.models import StreamEvent
from ...core.sessions import SessionManager
from ...tools.executors import executor_router, node_executor_hub
from ...tools.sandbox_manager import sandbox_manager
from ...data.repositories import Repository
from ..security import hash_pair_code, make_pair_code

router = APIRouter(prefix="/v1/commands", tags=["commands"])


def _format_memory_search_results(query: str, results: list[dict]) -> str:
    if not results:
        return f"No memory results found for query: `{query}`"
    lines = [f"Memory search results for `{query}`:"]
    for idx, item in enumerate(results, start=1):
        score = float(item.get("score", 0.0))
        source = str(item.get("source") or "(unknown)")
        summary = str(item.get("summary") or "").strip().replace("\n", " ")
        if len(summary) > 260:
            summary = summary[:257] + "..."
        lines.append(f"{idx}. similarity={score:.4f} | source={source}")
        lines.append(f"   {summary}")
    text = "\n".join(lines)
    if len(text) > 1900:
        text = text[:1897] + "..."
    return text


async def _running_docker_users() -> set[str]:
    if sandbox_manager is None:
        return set()
    try:
        containers = await sandbox_manager.list_containers()
    except Exception:
        return set()
    out: set[str] = set()
    for container in containers:
        if str(container.get("status") or "").lower() != "running":
            continue
        user_id = str(container.get("user_id") or "").strip()
        if user_id:
            out.add(user_id)
    return out


async def _resolve_machine_for_user(
    repo: Repository,
    user_id: str,
    target_machine: str,
):
    target = (target_machine or "").strip()
    if not target:
        return None
    if target.lower() in {"docker", "docker-default"}:
        if settings.executors_auto_docker_default:
            return await repo.get_or_create_docker_executor(user_id)
        return await repo.get_docker_executor_for_user(user_id)
    row = await repo.get_executor_for_user(user_id, target)
    if row is not None:
        return row
    return await repo.get_executor_for_user_by_name(user_id, target)


@router.post("/execute", response_model=CommandExecuteOut)
async def execute_command(
    payload: CommandExecuteRequest,
    request: Request,
    repo: Repository = Depends(get_repo),
) -> CommandExecuteOut:
    command = (payload.command or "").strip().lower()
    if not command:
        raise HTTPException(status_code=400, detail="command is required")

    target_user_id = resolve_target_user_id(request, payload.user_id)
    user = await repo.get_user_by_id(target_user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    if not user.approved:
        raise HTTPException(
            status_code=403,
            detail="Your account is not yet approved. An admin has to approve it first.",
        )

    runtime = request.app.state.runtime
    scheduler = request.app.state.scheduler_service
    event_bus = request.app.state.event_bus
    session_manager = SessionManager(runtime, settings.workspace_root)

    origin = (payload.origin or "api").strip() or "api"
    args = payload.args or {}
    scope_type = "private"
    scope_id = private_scope_id(user.id)

    if command == "new":
        active = await repo.get_active_session_by_scope(scope_type, scope_id)
        old_session_id = active.id if active is not None else None
        _, new_session_id = await session_manager.start_new_session_for_scope(
            user_id=user.id,
            scope_type=scope_type,
            scope_id=scope_id,
            origin=origin,
        )
        if old_session_id and old_session_id != new_session_id:
            payload_data = {
                "old_session_id": old_session_id,
                "new_session_id": new_session_id,
                "scope_type": scope_type,
                "scope_id": scope_id,
                "initiated_by_origin": origin,
            }
            now = datetime.utcnow()
            await event_bus.publish(
                StreamEvent(
                    session_id=old_session_id,
                    type="session_switched",
                    data=payload_data,
                    created_at=now,
                )
            )
            await event_bus.publish(
                StreamEvent(
                    session_id=new_session_id,
                    type="session_switched",
                    data=payload_data,
                    created_at=now,
                )
            )
        return CommandExecuteOut(
            message="Started a new session.",
            data={"session_id": new_session_id},
        )

    if command == "memory_reindex":
        stats = await session_manager.reindex_memories(user.id)
        return CommandExecuteOut(
            message=f"Memory reindex complete. Indexed: {stats['indexed']}, skipped: {stats['skipped']}, removed: {stats['removed']}.",
            data=stats,
        )

    if command == "memory_search":
        query = str(args.get("query") or "").strip()
        if not query:
            raise HTTPException(status_code=400, detail="query is required for memory_search")
        results = await session_manager.search_memories(user.id, query, top_k=5)
        return CommandExecuteOut(
            message=_format_memory_search_results(query, results),
            data={"query": query, "results": results},
        )

    if command == "schedule_list":
        jobs = await scheduler.list_jobs(user.id)
        lines = [f"{j['id']} | {j['name']} | {j['cron']} | {'on' if j['enabled'] else 'off'}" for j in jobs]
        message = "Scheduled jobs:\n" + ("\n".join(lines) if lines else "(none)")
        return CommandExecuteOut(message=message, data={"jobs": jobs})

    if command in {"schedule_delete", "schedule_pause", "schedule_resume"}:
        job_id = str(args.get("job_id") or "").strip()
        if not job_id:
            raise HTTPException(status_code=400, detail="job_id is required")
        job = await repo.get_scheduled_job(job_id)
        if job is None or job.user_id != user.id:
            raise HTTPException(status_code=404, detail="Job not found")
        if command == "schedule_delete":
            result = await scheduler.delete_job(job_id)
        elif command == "schedule_pause":
            result = await scheduler.update_job(job_id, enabled=False)
        else:
            result = await scheduler.update_job(job_id, enabled=True)
        if result.get("error"):
            raise HTTPException(status_code=400, detail=str(result["error"]))
        return CommandExecuteOut(message=str(result), data=result)

    if command == "tools":
        tool_list = [item.strip() for item in settings.tool_approval_tools.split(",") if item.strip()]
        mode = "required" if settings.tool_approval_required else "optional"
        secrets_mode = (
            "bypassed (unsafe)"
            if str(settings.approval_secrets_required or "").strip() == SECRETS_APPROVAL_BYPASS_MAGIC
            else "forced"
        )
        text = (
            f"Tool approvals are {mode}.\n"
            f"Secret-ref approvals are {secrets_mode}.\n"
            f"Configured approval tools ({len(tool_list)}): {', '.join(tool_list) if tool_list else '(none)'}"
        )
        return CommandExecuteOut(
            message=text,
            data={
                "approval_required": settings.tool_approval_required,
                "approval_secrets_required": settings.approval_secrets_required,
                "secrets_forced": secrets_mode.startswith("forced"),
                "tools": tool_list,
            },
        )

    if command == "model":
        requested = str(args.get("model_name") or "").strip()
        models = list_models()
        if not models:
            return CommandExecuteOut(ok=False, message="No models are configured.", data={})
        if not requested:
            active = await repo.get_active_session_by_scope(scope_type, scope_id)
            current = active.model if active and active.model else resolve_model_name(None, purpose="main")
            current = resolve_model_name(current, purpose="main")
            lines = []
            for item in models:
                suffix = " (active)" if current and item.name.lower() == current.lower() else ""
                lines.append(f"- {item.name}{suffix}")
            return CommandExecuteOut(
                message="Available models:\n" + "\n".join(lines),
                data={"models": [m.name for m in models], "current": current},
            )
        requested_name = resolve_model_name(requested, purpose="main")
        match = next((m for m in models if m.name.lower() == requested_name.lower()), None)
        if match is None:
            raise HTTPException(status_code=400, detail=f"Unknown model '{requested}'.")
        active = await repo.get_active_session_by_scope(scope_type, scope_id)
        if active is None:
            active = await repo.create_session(
                user.id,
                model=match.name,
                origin=origin,
                scope_type=scope_type,
                scope_id=scope_id,
            )
        else:
            await repo.set_session_model(active.id, match.name)
        runtime.set_session_model(active.id, match.name)
        return CommandExecuteOut(
            message=f"Active model set to `{match.name}`.",
            data={"model": match.name, "session_id": active.id},
        )

    if command == "pair":
        code = make_pair_code()
        expires_at = datetime.now(UTC) + timedelta(minutes=10)
        await repo.create_pair_code(
            hash_pair_code(code),
            flow_type="pair",
            user_id=user.id,
            display_name=None,
            created_by_user_id=user.id,
            created_via=origin,
            expires_at=expires_at,
        )
        return CommandExecuteOut(
            message=(
                f"Pair code: `{code}`\n"
                f"Expires at: {expires_at.strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
                "Use this code in the menubar/TUI pairing flow."
            ),
            data={"code": code, "expires_at": expires_at.isoformat()},
        )

    if command == "machine":
        requested = str(args.get("target_machine") or "").strip()
        if requested:
            row = await _resolve_machine_for_user(repo, user.id, requested)
            if row is None:
                raise HTTPException(status_code=404, detail=f"Machine not found: {requested}")
            if row.disabled:
                raise HTTPException(status_code=400, detail=f"Machine is disabled: {row.name}")
            await repo.set_user_default_executor(user.id, row.id)
            active = await repo.get_active_session_by_scope(scope_type, scope_id)
            if active is not None:
                await executor_router.set_session_default(active.id, row.id)
            return CommandExecuteOut(
                message=f"Default machine set to `{row.name}`.",
                data={"machine_id": row.id, "machine_name": row.name},
            )

        if settings.executors_auto_docker_default:
            await repo.get_or_create_docker_executor(user.id)
        rows = await repo.list_executors_for_user(user.id, include_disabled=False)
        online_ids = set(await node_executor_hub.online_executor_ids())
        running_docker = await _running_docker_users()
        user_default_id = await repo.get_user_default_executor_id(user.id)
        lines: list[str] = ["Available machines:"]
        for row in rows:
            online = (row.id in online_ids) or (row.kind == "docker" and user.id in running_docker)
            marker = " (default)" if user_default_id == row.id else ""
            status = "online" if online else "offline"
            lines.append(f"- {row.name} [{row.kind}] `{row.id}` · {status}{marker}")
        if len(lines) == 1:
            lines.append("(none)")
        lines.append("Use `/machine <name_or_id>` to set the default machine.")
        return CommandExecuteOut(
            message="\n".join(lines),
            data={
                "default_executor_id": user_default_id,
                "machines": [
                    {
                        "id": row.id,
                        "name": row.name,
                        "kind": row.kind,
                        "online": (row.id in online_ids) or (row.kind == "docker" and user.id in running_docker),
                    }
                    for row in rows
                ],
            },
        )

    if command == "info":
        active = await repo.get_active_session_by_scope(scope_type, scope_id)
        if active is None:
            return CommandExecuteOut(ok=False, message="No active session found.", data={})
        model_name = active.last_model or active.model or resolve_model_name(None, purpose="main")
        lines = [
            f"Session: `{active.id}`",
            f"Model: `{model_name}`",
            f"Context tokens (last input): {active.last_input_tokens or 0}",
            f"Last output tokens: {active.last_output_tokens or 0}",
            f"Last total tokens: {active.last_total_tokens or 0}",
            f"Total input tokens: {active.input_tokens or 0}",
            f"Total output tokens: {active.output_tokens or 0}",
            f"Total tokens: {active.total_tokens or 0}",
            f"Total cost: ${active.total_cost or 0.0:.4f}",
        ]
        return CommandExecuteOut(
            message="\n".join(lines),
            data={
                "session_id": active.id,
                "model": model_name,
                "last_input_tokens": active.last_input_tokens or 0,
                "last_output_tokens": active.last_output_tokens or 0,
                "last_total_tokens": active.last_total_tokens or 0,
                "total_tokens": active.total_tokens or 0,
                "total_cost": active.total_cost or 0.0,
            },
        )

    raise HTTPException(status_code=400, detail=f"Unknown command '{command}'")
