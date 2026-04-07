from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from .config import SECRETS_APPROVAL_BYPASS_MAGIC, settings
from .conversation_scope import private_scope_id
from .llm import list_models, resolve_model_name
from .models import StreamEvent
from .profile_service import parse_profile_command, profile_service, serialize_profile
from .sessions import SessionManager
from .transport_accounts import (
    DEFAULT_DISCORD_ACCOUNT_KEY,
    is_shared_default_account_key,
    transport_account_service,
)
from ..api.security import hash_pair_code, make_pair_code
from ..data.models import AgentProfile
from ..data.repositories import Repository
from ..tools.executors import executor_router, node_executor_hub
from ..tools.sandbox_manager import sandbox_manager


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


async def _publish_session_switch(
    *,
    event_bus,
    old_session_id: str,
    new_session_id: str,
    scope_type: str,
    scope_id: str,
    initiated_by_origin: str,
) -> None:
    if event_bus is None:
        return
    payload = {
        "old_session_id": old_session_id,
        "new_session_id": new_session_id,
        "scope_type": scope_type,
        "scope_id": scope_id,
        "initiated_by_origin": initiated_by_origin,
    }
    now = datetime.utcnow()
    await event_bus.publish(
        StreamEvent(
            session_id=old_session_id,
            type="session_switched",
            data=payload,
            created_at=now,
        )
    )
    await event_bus.publish(
        StreamEvent(
            session_id=new_session_id,
            type="session_switched",
            data=payload,
            created_at=now,
        )
    )


@dataclass(slots=True)
class CommandExecutionResult:
    ok: bool = True
    message: str = ""
    data: dict[str, Any] = field(default_factory=dict)


class CommandService:
    async def execute(
        self,
        *,
        repo: Repository,
        user,
        runtime,
        scheduler,
        event_bus,
        command: str,
        args: dict[str, Any] | None = None,
        origin: str = "api",
        agent_profile_id: str | None = None,
        agent_profile_slug: str | None = None,
        scope_type: str | None = None,
        scope_id: str | None = None,
        surface_id: str | None = None,
        persist_surface_profile: bool = False,
        transport_account_key: str | None = None,
        surface_is_private: bool | None = None,
    ) -> CommandExecutionResult:
        normalized_command = (command or "").strip().lower()
        if not normalized_command:
            raise ValueError("command is required")

        args = args or {}
        profile = await profile_service.resolve_profile(
            repo,
            user.id,
            agent_profile_id=agent_profile_id,
            agent_profile_slug=agent_profile_slug,
            origin=origin,
            channel_id=surface_id,
            transport_account_key=transport_account_key,
        )
        resolved_scope_type = (scope_type or "private").strip() or "private"
        resolved_scope_id = (scope_id or "").strip()
        if not resolved_scope_id:
            if resolved_scope_type == "private":
                resolved_scope_id = private_scope_id(profile.id)
            else:
                resolved_scope_id = f"{resolved_scope_type}:{user.id}"

        session_manager = SessionManager(runtime)

        if normalized_command == "profile":
            return await self._execute_profile_command(
                repo=repo,
                user_id=user.id,
                origin=origin,
                surface_id=surface_id,
                persist_surface_profile=persist_surface_profile,
                current_profile=profile,
                raw=str(args.get("raw") or "").strip(),
                transport_account_key=transport_account_key,
                surface_is_private=surface_is_private,
            )

        if normalized_command == "new":
            active = await repo.get_active_session_by_scope(
                resolved_scope_type,
                resolved_scope_id,
                agent_profile_id=profile.id,
            )
            old_session_id = active.id if active is not None else None
            cache_key = None
            if surface_id:
                cache_key = surface_id
                if origin == "discord" and resolved_scope_type != "private":
                    cleaned_account_key = str(transport_account_key or "").strip()
                    if cleaned_account_key:
                        cache_key = f"{cleaned_account_key}:{surface_id}"
            _, new_session_id = await session_manager.start_new_session_for_scope(
                user_id=user.id,
                agent_profile_id=profile.id,
                agent_profile_slug=profile.slug,
                scope_type=resolved_scope_type,
                scope_id=resolved_scope_id,
                origin=origin,
                channel_id=surface_id,
                cache_key=cache_key,
            )
            if old_session_id and old_session_id != new_session_id:
                await _publish_session_switch(
                    event_bus=event_bus,
                    old_session_id=old_session_id,
                    new_session_id=new_session_id,
                    scope_type=resolved_scope_type,
                    scope_id=resolved_scope_id,
                    initiated_by_origin=origin,
                )
            return CommandExecutionResult(
                message="Started a new session.",
                data={
                    "session_id": new_session_id,
                    "agent_profile_id": profile.id,
                    "agent_profile_slug": profile.slug,
                },
            )

        if normalized_command == "memory_reindex":
            stats = await session_manager.reindex_memories(
                user.id,
                agent_profile_id=profile.id,
                agent_profile_slug=profile.slug,
            )
            return CommandExecutionResult(
                message=(
                    "Memory reindex complete. "
                    f"Indexed: {stats['indexed']}, skipped: {stats['skipped']}, removed: {stats['removed']}."
                ),
                data=stats,
            )

        if normalized_command == "memory_search":
            query = str(args.get("query") or "").strip()
            if not query:
                raise ValueError("query is required for memory_search")
            results = await session_manager.search_memories(
                user.id,
                query,
                agent_profile_id=profile.id,
                top_k=5,
            )
            return CommandExecutionResult(
                message=_format_memory_search_results(query, results),
                data={"query": query, "results": results},
            )

        if normalized_command == "schedule_list":
            jobs = await scheduler.list_jobs(user.id, agent_profile_id=profile.id)
            lines = [
                f"{j['id']} | {j['name']} | {j['cron']} | {'on' if j['enabled'] else 'off'}"
                for j in jobs
            ]
            message = "Scheduled jobs:\n" + ("\n".join(lines) if lines else "(none)")
            return CommandExecutionResult(message=message, data={"jobs": jobs})

        if normalized_command in {"schedule_delete", "schedule_pause", "schedule_resume"}:
            job_id = str(args.get("job_id") or "").strip()
            if not job_id:
                raise ValueError("job_id is required")
            job = await repo.get_scheduled_job(job_id)
            if job is None or job.user_id != user.id or (job.agent_profile_id or "") != profile.id:
                raise LookupError("Job not found")
            if normalized_command == "schedule_delete":
                result = await scheduler.delete_job(job_id)
            elif normalized_command == "schedule_pause":
                result = await scheduler.update_job(job_id, enabled=False)
            else:
                result = await scheduler.update_job(job_id, enabled=True)
            error = str(result.get("error") or "").strip()
            if error:
                raise ValueError(error)
            return CommandExecutionResult(message=str(result), data=result)

        if normalized_command == "tools":
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
            return CommandExecutionResult(
                message=text,
                data={
                    "approval_required": settings.tool_approval_required,
                    "approval_secrets_required": settings.approval_secrets_required,
                    "secrets_forced": secrets_mode.startswith("forced"),
                    "tools": tool_list,
                },
            )

        if normalized_command == "model":
            requested = str(args.get("model_name") or "").strip()
            models = list_models()
            if not models:
                return CommandExecutionResult(ok=False, message="No models are configured.", data={})
            if not requested:
                active = await repo.get_active_session_by_scope(
                    resolved_scope_type,
                    resolved_scope_id,
                    agent_profile_id=profile.id,
                )
                current = active.model if active and active.model else resolve_model_name(None, purpose="main")
                current = resolve_model_name(current, purpose="main")
                lines = []
                for item in models:
                    suffix = " (active)" if current and item.name.lower() == current.lower() else ""
                    lines.append(f"- {item.name}{suffix}")
                return CommandExecutionResult(
                    message="Available models:\n" + "\n".join(lines),
                    data={"models": [m.name for m in models], "current": current},
                )
            requested_name = resolve_model_name(requested, purpose="main")
            match = next((m for m in models if m.name.lower() == requested_name.lower()), None)
            if match is None:
                raise ValueError(f"Unknown model '{requested}'.")
            active = await repo.get_active_session_by_scope(
                resolved_scope_type,
                resolved_scope_id,
                agent_profile_id=profile.id,
            )
            if active is None:
                active = await repo.create_session(
                    user.id,
                    agent_profile_id=profile.id,
                    model=match.name,
                    origin=origin,
                    scope_type=resolved_scope_type,
                    scope_id=resolved_scope_id,
                )
            else:
                await repo.set_session_model(active.id, match.name)
            runtime.set_session_model(active.id, match.name)
            return CommandExecutionResult(
                message=f"Active model set to `{match.name}`.",
                data={"model": match.name, "session_id": active.id},
            )

        if normalized_command == "pair":
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
            return CommandExecutionResult(
                message=(
                    f"Pair code: `{code}`\n"
                    f"Expires at: {expires_at.strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
                    "Use this code in the menubar/TUI pairing flow."
                ),
                data={"code": code, "expires_at": expires_at.isoformat()},
            )

        if normalized_command == "machine":
            requested = str(args.get("target_machine") or "").strip()
            if requested:
                row = await _resolve_machine_for_user(repo, user.id, requested)
                if row is None:
                    raise LookupError(f"Machine not found: {requested}")
                if row.disabled:
                    raise ValueError(f"Machine is disabled: {row.name}")
                await repo.set_profile_default_executor(profile.id, row.id)
                active = await repo.get_active_session_by_scope(
                    resolved_scope_type,
                    resolved_scope_id,
                    agent_profile_id=profile.id,
                )
                if active is not None:
                    await executor_router.set_session_default(active.id, row.id)
                return CommandExecutionResult(
                    message=f"Default machine set to `{row.name}`.",
                    data={"machine_id": row.id, "machine_name": row.name},
                )

            if settings.executors_auto_docker_default:
                await repo.get_or_create_docker_executor(user.id)
            rows = await repo.list_executors_for_user(user.id, include_disabled=False)
            online_ids = set(await node_executor_hub.online_executor_ids())
            running_docker = await _running_docker_users()
            profile_default_id = await repo.get_profile_default_executor_id(profile.id)
            lines: list[str] = ["Available machines:"]
            for row in rows:
                online = (row.id in online_ids) or (row.kind == "docker" and user.id in running_docker)
                marker = " (default)" if profile_default_id == row.id else ""
                status = "online" if online else "offline"
                lines.append(f"- {row.name} [{row.kind}] `{row.id}` · {status}{marker}")
            if len(lines) == 1:
                lines.append("(none)")
            lines.append("Use `/machine <name_or_id>` to set the default machine.")
            return CommandExecutionResult(
                message="\n".join(lines),
                data={
                    "default_executor_id": profile_default_id,
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

        if normalized_command == "info":
            active = await repo.get_active_session_by_scope(
                resolved_scope_type,
                resolved_scope_id,
                agent_profile_id=profile.id,
            )
            if active is None:
                return CommandExecutionResult(ok=False, message="No active session found.", data={})
            model_name = active.last_model or active.model or resolve_model_name(None, purpose="main")
            lines = [
                f"Session: `{active.id}`",
                f"Profile: `{profile.slug}`",
                f"Model: `{model_name}`",
                f"Context tokens (last input): {active.last_input_tokens or 0}",
                f"Last output tokens: {active.last_output_tokens or 0}",
                f"Last total tokens: {active.last_total_tokens or 0}",
                f"Total input tokens: {active.input_tokens or 0}",
                f"Total output tokens: {active.output_tokens or 0}",
                f"Total tokens: {active.total_tokens or 0}",
                f"Total cost: ${active.total_cost or 0.0:.4f}",
            ]
            return CommandExecutionResult(
                message="\n".join(lines),
                data={
                    "session_id": active.id,
                    "model": model_name,
                    "agent_profile_id": profile.id,
                    "agent_profile_slug": profile.slug,
                    "last_input_tokens": active.last_input_tokens or 0,
                    "last_output_tokens": active.last_output_tokens or 0,
                    "last_total_tokens": active.last_total_tokens or 0,
                    "total_tokens": active.total_tokens or 0,
                    "total_cost": active.total_cost or 0.0,
                },
            )

        raise ValueError(f"Unknown command '{normalized_command}'")

    async def _execute_profile_command(
        self,
        *,
        repo: Repository,
        user_id: str,
        origin: str,
        surface_id: str | None,
        persist_surface_profile: bool,
        current_profile: AgentProfile,
        raw: str,
        transport_account_key: str | None,
        surface_is_private: bool | None,
    ) -> CommandExecutionResult:
        parsed = parse_profile_command(raw)
        action = str(parsed.get("action") or "show").strip().lower()
        default_profile = await profile_service.ensure_default_profile(repo, user_id)
        discord_accounts_by_profile = await transport_account_service.list_explicit_accounts_by_profile(
            repo,
            user_id=user_id,
            transport="discord",
        )
        is_shared_default_discord = origin == "discord" and is_shared_default_account_key(
            transport_account_key or DEFAULT_DISCORD_ACCOUNT_KEY
        )

        if action == "show":
            rows = await profile_service.list_profiles(repo, user_id, include_archived=True)
            profile_rows = [serialize_profile(row, default_profile_id=default_profile.id) for row in rows]
            lines = [
                f"Current profile: `{current_profile.slug}` ({current_profile.name})",
                f"Default profile: `{default_profile.slug}` ({default_profile.name})",
                "Profiles:",
            ]
            for item in profile_rows:
                suffix_parts: list[str] = []
                if item["id"] == current_profile.id:
                    suffix_parts.append("active")
                if item["id"] == default_profile.id:
                    suffix_parts.append("default")
                if item["status"] != "active":
                    suffix_parts.append(str(item["status"]))
                if origin == "discord" and is_shared_default_discord and item["id"] in discord_accounts_by_profile:
                    suffix_parts.append("dedicated bot only")
                suffix = f" [{' / '.join(suffix_parts)}]" if suffix_parts else ""
                lines.append(f"- `{item['slug']}`: {item['name']}{suffix}")
            return CommandExecutionResult(
                message="\n".join(lines),
                data={
                    "profiles": profile_rows,
                    "current_profile": serialize_profile(current_profile, default_profile_id=default_profile.id),
                    "default_profile": serialize_profile(default_profile, default_profile_id=default_profile.id),
                },
            )

        if action == "use":
            slug = str(parsed.get("slug") or "").strip()
            target = await profile_service.resolve_profile(repo, user_id, agent_profile_slug=slug)
            if origin == "discord":
                if not bool(surface_is_private):
                    raise RuntimeError("This Discord channel is bound by admin. Use the admin UI to change its profile.")
                if not is_shared_default_discord:
                    raise RuntimeError(f"This bot is pinned to profile `{current_profile.slug}`.")
                if target.id in discord_accounts_by_profile:
                    raise RuntimeError(
                        f"Profile `{target.slug}` uses a dedicated Discord bot and cannot be selected on the shared default bot."
                    )
                if persist_surface_profile and surface_id:
                    target = await profile_service.set_surface_override(
                        repo,
                        user_id,
                        origin=origin,
                        transport_account_key=str(transport_account_key or DEFAULT_DISCORD_ACCOUNT_KEY).strip()
                        or DEFAULT_DISCORD_ACCOUNT_KEY,
                        channel_id=surface_id,
                        slug=slug,
                    )
                    return CommandExecutionResult(
                        message=f"This Discord DM now uses profile `{target.slug}`.",
                        data={
                            "profile": serialize_profile(target, default_profile_id=default_profile.id),
                            "agent_profile_id": target.id,
                            "agent_profile_slug": target.slug,
                            "surface_override": True,
                        },
                    )
            return CommandExecutionResult(
                message=f"Active profile switched to `{target.slug}`.",
                data={
                    "profile": serialize_profile(target, default_profile_id=default_profile.id),
                    "agent_profile_id": target.id,
                    "agent_profile_slug": target.slug,
                    "apply_client_selection": True,
                },
            )

        if action == "default":
            target = await profile_service.set_default_profile(repo, user_id, str(parsed.get("slug") or "").strip())
            return CommandExecutionResult(
                message=f"Default profile set to `{target.slug}`.",
                data={"profile": serialize_profile(target, default_profile_id=target.id)},
            )

        if action == "create":
            target = await profile_service.create_profile(
                repo,
                user_id,
                name=str(parsed.get("name") or "").strip(),
                make_default=bool(parsed.get("make_default")),
            )
            refreshed_default = await profile_service.ensure_default_profile(repo, user_id)
            return CommandExecutionResult(
                message=f"Created profile `{target.slug}`.",
                data={
                    "profile": serialize_profile(target, default_profile_id=refreshed_default.id),
                    "agent_profile_id": target.id,
                    "agent_profile_slug": target.slug,
                    "apply_client_selection": True,
                },
            )

        if action == "clone":
            target = await profile_service.create_profile(
                repo,
                user_id,
                name=str(parsed.get("name") or "").strip(),
                source_slug=str(parsed.get("source_slug") or "").strip(),
                mode=str(parsed.get("mode") or "settings").strip() or "settings",
                make_default=bool(parsed.get("make_default")),
            )
            refreshed_default = await profile_service.ensure_default_profile(repo, user_id)
            return CommandExecutionResult(
                message=f"Cloned profile into `{target.slug}`.",
                data={
                    "profile": serialize_profile(target, default_profile_id=refreshed_default.id),
                    "agent_profile_id": target.id,
                    "agent_profile_slug": target.slug,
                    "apply_client_selection": True,
                },
            )

        if action == "rename":
            target = await profile_service.rename_profile(
                repo,
                user_id,
                str(parsed.get("slug") or "").strip(),
                str(parsed.get("name") or "").strip(),
            )
            refreshed_default = await profile_service.ensure_default_profile(repo, user_id)
            return CommandExecutionResult(
                message=f"Renamed profile `{target.slug}` to `{target.name}`.",
                data={"profile": serialize_profile(target, default_profile_id=refreshed_default.id)},
            )

        if action == "archive":
            target = await profile_service.archive_profile(repo, user_id, str(parsed.get("slug") or "").strip())
            refreshed_default = await profile_service.ensure_default_profile(repo, user_id)
            return CommandExecutionResult(
                message=f"Archived profile `{target.slug}`.",
                data={"profile": serialize_profile(target, default_profile_id=refreshed_default.id)},
            )

        if action == "unarchive":
            target = await profile_service.unarchive_profile(repo, user_id, str(parsed.get("slug") or "").strip())
            refreshed_default = await profile_service.ensure_default_profile(repo, user_id)
            return CommandExecutionResult(
                message=f"Restored profile `{target.slug}`.",
                data={"profile": serialize_profile(target, default_profile_id=refreshed_default.id)},
            )

        raise ValueError(f"Unknown profile action `{action}`.")


command_service = CommandService()
