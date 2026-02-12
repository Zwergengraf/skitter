from __future__ import annotations

import asyncio
import os
import json
import contextlib
from datetime import datetime, UTC, timedelta

import uvicorn

from .api.app import create_app
from .api.security import hash_pair_code, make_pair_code
from .core.runtime import AgentRuntime
from .core.graph import build_graph
from .core.llm import list_models, resolve_model_name
from .core.scheduler import SchedulerService
from .core.heartbeat import HeartbeatService
from .core.jobs import JobService
from .core.conversation_scope import resolve_conversation_scope
from .core.config import SECRETS_APPROVAL_BYPASS_MAGIC, settings
from .core.models import StreamEvent
from .core.sessions import SessionManager
from .data.db import SessionLocal
from .data.repositories import Repository
from .transports.discord import DiscordTransport
from .transports.manager import TransportManager
from .tools.sandbox_manager import sandbox_manager


def _serialize_attachments(attachments: list) -> list[dict]:
    serialized = []
    for attachment in attachments:
        url = getattr(attachment, "url", None)
        if not url:
            continue
        serialized.append(
            {
                "filename": getattr(attachment, "filename", ""),
                "url": url,
                "content_type": getattr(attachment, "content_type", "") or "",
            }
        )
    return serialized


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


async def main() -> None:
    app = create_app()
    runtime: AgentRuntime = app.state.runtime
    approval_service = app.state.approval_service
    scheduler: SchedulerService = app.state.scheduler_service
    heartbeat_service = HeartbeatService(runtime)
    job_service = JobService(
        runtime=runtime,
        graph_factory=lambda worker_model: build_graph(
            approval_service=approval_service,
            scheduler_service=scheduler,
            job_service=None,
            model_name=worker_model,
            purpose="main",
            include_subagent_tools=False,
        ),
    )
    app.state.job_service = job_service
    runtime.set_job_service(job_service)
    session_manager = SessionManager(runtime, settings.workspace_root)
    if sandbox_manager is not None:
        await sandbox_manager.start()

    discord_enabled = os.environ.get("SKITTER_ENABLE_DISCORD", "true").lower() == "true"

    transports = []
    transport_by_origin = {}

    if discord_enabled:
        discord_transport = DiscordTransport()
        transports.append(discord_transport)
        transport_by_origin["discord"] = discord_transport
        approval_service.set_notifier(discord_transport.send_approval_request)
        discord_transport.set_approval_service(approval_service)
        app.state.user_notifier = discord_transport.send_user_message

    async def _deliver(origin: str, destination_id: str, text: str, attachments: list) -> None:
        transport = transport_by_origin.get(origin)
        if transport is None:
            return
        await transport.send_message(destination_id, text, attachments)

    scheduler.set_deliver(_deliver)
    heartbeat_service.set_deliver(_deliver)
    job_service.set_deliver(_deliver)
    await scheduler.start()
    await heartbeat_service.start()
    await job_service.start()

    manager = TransportManager(transports)

    def _to_utc_naive(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value
        return value.astimezone(UTC).replace(tzinfo=None)

    async def _progress_status_text(session_id: str, started_at: datetime) -> str:
        async with SessionLocal() as session:
            repo = Repository(session)
            tool_runs = await repo.list_tool_runs_by_session(session_id)
        started_at_naive = _to_utc_naive(started_at)
        elapsed_seconds = max(0, int((datetime.now(UTC) - started_at).total_seconds()))
        recent_runs = [
            run
            for run in tool_runs
            if _to_utc_naive(run.created_at) >= started_at_naive
        ]
        if recent_runs:
            latest = recent_runs[-1]
            return f"Working... {elapsed_seconds}s\nLast tool: `{latest.tool_name}` ({latest.status})"
        return f"Working... {elapsed_seconds}s\nLast step: thinking"

    async def _run_progress_loop(
        transport: DiscordTransport,
        channel_id: str,
        session_id: str,
        stop_event: asyncio.Event,
    ) -> None:
        if not settings.discord_progress_updates:
            return
        message = await transport.start_progress_message(channel_id, "Working...\nLast step: thinking")
        if message is None:
            return
        interval = max(1, int(settings.discord_progress_interval_seconds))
        started_at = datetime.now(UTC)
        try:
            while not stop_event.is_set():
                content = await _progress_status_text(session_id, started_at)
                await transport.update_progress_message(message, content)
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=interval)
                except asyncio.TimeoutError:
                    continue
        finally:
            await transport.stop_progress_message(message)

    def _should_show_progress(envelope, transport) -> bool:
        return (
            envelope.origin == "discord"
            and isinstance(transport, DiscordTransport)
            and not envelope.command
            and settings.discord_progress_updates
        )

    async def _start_progress_tracking(envelope, transport, session_id: str) -> tuple[asyncio.Event | None, asyncio.Task | None]:
        if not _should_show_progress(envelope, transport):
            return None, None
        stop_event = asyncio.Event()
        task = asyncio.create_task(
            _run_progress_loop(transport, envelope.channel_id, session_id, stop_event)
        )
        return stop_event, task

    async def _stop_progress_tracking(stop_event: asyncio.Event | None, task: asyncio.Task | None) -> None:
        if stop_event is not None:
            stop_event.set()
        if task is not None:
            with contextlib.suppress(Exception):
                await task

    def _build_message_metadata(envelope, internal_user_id: str) -> dict:
        metadata = dict(envelope.metadata)
        metadata.update({"internal_user_id": internal_user_id})
        metadata.update({"message_id": envelope.message_id, "origin": envelope.origin})
        if envelope.attachments:
            attachments_meta = _serialize_attachments(envelope.attachments)
            if attachments_meta:
                metadata["attachments"] = attachments_meta
                envelope.metadata["attachments"] = attachments_meta
        return metadata

    async def _persist_user_message(session_id: str, envelope, internal_user_id: str) -> None:
        metadata = _build_message_metadata(envelope, internal_user_id)
        async with SessionLocal() as session:
            repo = Repository(session)
            await repo.add_message(session_id, role="user", content=envelope.text, metadata=metadata)

    async def _persist_assistant_message(
        session_id: str,
        response_text: str,
        response_to: str,
        run_id: str | None = None,
        reasoning: list[str] | None = None,
    ) -> None:
        metadata: dict[str, object] = {"response_to": response_to}
        if run_id:
            metadata["run_id"] = run_id
        if reasoning:
            metadata["reasoning"] = reasoning
        async with SessionLocal() as session:
            repo = Repository(session)
            await repo.add_message(
                session_id,
                role="assistant",
                content=response_text,
                metadata=metadata,
            )

    async def _resolve_internal_user_id(envelope, transport) -> str | None:
        if envelope.origin != "discord":
            return envelope.user_id
        async with SessionLocal() as session:
            repo = Repository(session)
            user = await repo.get_or_create_user(envelope.user_id)
            if not user.approved:
                if not (user.meta or {}).get("approval_notified"):
                    await transport.send_message(
                        envelope.channel_id,
                        "Your account is not yet approved. An admin has to approve it first.",
                    )
                    await repo.mark_user_notified(user.id)
                envelope.metadata["suppress_ack"] = True
                return None
            return user.id

    async def _update_user_last_seen(internal_user_id: str, envelope, scope) -> None:
        if envelope.origin != "discord":
            return
        async with SessionLocal() as session:
            repo = Repository(session)
            updates = {
                "last_seen_at": datetime.now(UTC).isoformat(),
            }
            if scope.is_private:
                updates.update(
                    {
                        "last_private_origin": scope.target_origin,
                        "last_private_destination_id": scope.target_destination_id,
                        "last_channel_id": envelope.channel_id,
                        "last_origin": envelope.origin,
                    }
                )
            await repo.set_user_meta(internal_user_id, updates)

    async def _publish_session_switch(
        old_session_id: str,
        new_session_id: str,
        scope,
        initiated_by_origin: str,
    ) -> None:
        payload = {
            "old_session_id": old_session_id,
            "new_session_id": new_session_id,
            "scope_type": scope.scope_type,
            "scope_id": scope.scope_id,
            "initiated_by_origin": initiated_by_origin,
        }
        now = datetime.utcnow()
        await app.state.event_bus.publish(
            StreamEvent(
                session_id=old_session_id,
                type="session_switched",
                data=payload,
                created_at=now,
            )
        )
        await app.state.event_bus.publish(
            StreamEvent(
                session_id=new_session_id,
                type="session_switched",
                data=payload,
                created_at=now,
            )
        )

    async def _handle_discord_command(
        envelope,
        transport: DiscordTransport,
        scope,
        internal_user_id: str,
    ) -> bool:
        if envelope.origin != "discord" or not envelope.command:
            return False
        if envelope.command == "new":
            old_session_id: str | None = None
            async with SessionLocal() as session:
                repo = Repository(session)
                active = await repo.get_active_session_by_scope(scope.scope_type, scope.scope_id)
                if active is not None:
                    old_session_id = active.id
            summary_path, new_session_id = await session_manager.start_new_session_for_scope(
                user_id=internal_user_id,
                scope_type=scope.scope_type,
                scope_id=scope.scope_id,
                origin=envelope.origin,
                channel_id=envelope.channel_id,
            )
            if old_session_id and old_session_id != new_session_id:
                await _publish_session_switch(
                    old_session_id=old_session_id,
                    new_session_id=new_session_id,
                    scope=scope,
                    initiated_by_origin=envelope.origin,
                )
            if summary_path:
                await transport.send_message(
                    envelope.channel_id, f"Started a new session. Summary saved to `{summary_path.name}`."
                )
            else:
                await transport.send_message(envelope.channel_id, "Started a new session.")
            return True
        if envelope.command == "memory_reindex":
            stats = await session_manager.reindex_memories(internal_user_id)
            await transport.send_message(
                envelope.channel_id,
                f"Memory reindex complete. Indexed: {stats['indexed']}, skipped: {stats['skipped']}, removed: {stats['removed']}.",
            )
            return True
        if envelope.command == "memory_search":
            query = str((envelope.metadata or {}).get("query") or "").strip()
            if not query:
                envelope.metadata["ephemeral_response"] = "Query is required."
                envelope.metadata["suppress_ack"] = True
                return True
            results = await session_manager.search_memories(internal_user_id, query, top_k=5)
            envelope.metadata["ephemeral_response"] = _format_memory_search_results(query, results)
            envelope.metadata["suppress_ack"] = True
            return True
        if envelope.command == "schedule_list":
            jobs = await scheduler.list_jobs(internal_user_id)
            lines = [f"{j['id']} | {j['name']} | {j['cron']} | {'on' if j['enabled'] else 'off'}" for j in jobs]
            await transport.send_message(envelope.channel_id, "Scheduled jobs:\n" + "\n".join(lines))
            return True
        if envelope.command == "tools":
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
            await transport.send_message(envelope.channel_id, text)
            return True
        if envelope.command == "model":
            requested = envelope.metadata.get("model_name") if envelope.metadata else None
            models = list_models()
            if not models:
                await transport.send_message(envelope.channel_id, "No models are configured.")
                return True
            if not requested:
                async with SessionLocal() as session:
                    repo = Repository(session)
                    active = await repo.get_active_session_by_scope(scope.scope_type, scope.scope_id)
                current = active.model if active and active.model else None
                if current is None:
                    current = resolve_model_name(None, purpose="main")
                else:
                    current = resolve_model_name(current, purpose="main")
                lines = []
                for item in models:
                    suffix = " (active)" if current and item.name.lower() == current.lower() else ""
                    lines.append(f"- {item.name}{suffix}")
                await transport.send_message(envelope.channel_id, "Available models:\n" + "\n".join(lines))
                return True
            requested_name = resolve_model_name(str(requested), purpose="main")
            match = None
            for item in models:
                if item.name.lower() == requested_name.lower():
                    match = item
                    break
            if match is None:
                await transport.send_message(
                    envelope.channel_id,
                    f"Unknown model `{requested}`. Use /model to list available models.",
                )
                return True
            async with SessionLocal() as session:
                repo = Repository(session)
                active = await repo.get_active_session_by_scope(scope.scope_type, scope.scope_id)
                if active is None:
                    active = await repo.create_session(
                        internal_user_id,
                        model=match.name,
                        origin=envelope.origin,
                        scope_type=scope.scope_type,
                        scope_id=scope.scope_id,
                    )
                else:
                    await repo.set_session_model(active.id, match.name)
            runtime.set_session_model(active.id, match.name)
            await transport.send_message(
                envelope.channel_id,
                f"Active model set to `{match.name}`.",
            )
            return True
        if envelope.command == "pair":
            code = make_pair_code()
            expires_at = datetime.now(UTC) + timedelta(minutes=10)
            async with SessionLocal() as session:
                repo = Repository(session)
                await repo.create_pair_code(
                    hash_pair_code(code),
                    flow_type="pair",
                    user_id=internal_user_id,
                    display_name=None,
                    created_by_user_id=internal_user_id,
                    created_via="discord",
                    expires_at=expires_at,
                )
            envelope.metadata["ephemeral_response"] = (
                f"Pair code: `{code}`\n"
                f"Expires at: {expires_at.strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
                "Use this code in the menubar/TUI pairing flow."
            )
            envelope.metadata["suppress_ack"] = True
            return True
        if envelope.command == "info":
            async with SessionLocal() as session:
                repo = Repository(session)
                active = await repo.get_active_session_by_scope(scope.scope_type, scope.scope_id)
            if active is None:
                await transport.send_message(envelope.channel_id, "No active session found.")
                return True
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
            await transport.send_message(envelope.channel_id, "\n".join(lines))
            return True
        if envelope.command in {"schedule_delete", "schedule_pause", "schedule_resume"}:
            job_id = envelope.metadata.get("job_id")
            if not job_id:
                await transport.send_message(envelope.channel_id, "Job id is required.")
                return True
            if envelope.command == "schedule_delete":
                result = await scheduler.delete_job(job_id)
            elif envelope.command == "schedule_pause":
                result = await scheduler.update_job(job_id, enabled=False)
            else:
                result = await scheduler.update_job(job_id, enabled=True)
            await transport.send_message(envelope.channel_id, json.dumps(result))
            return True
        return False

    async def handler(envelope):
        transport = transport_by_origin.get(envelope.origin)
        if transport is None:
            return

        internal_user_id = await _resolve_internal_user_id(envelope, transport)
        if internal_user_id is None:
            return

        scope = resolve_conversation_scope(
            origin=envelope.origin,
            channel_id=envelope.channel_id,
            internal_user_id=internal_user_id,
            metadata=envelope.metadata,
        )
        envelope.metadata["internal_user_id"] = internal_user_id
        envelope.metadata["scope_type"] = scope.scope_type
        envelope.metadata["scope_id"] = scope.scope_id
        envelope.metadata["is_private"] = scope.is_private

        await _update_user_last_seen(internal_user_id, envelope, scope)

        await transport.send_typing(envelope.channel_id)
        if isinstance(transport, DiscordTransport):
            handled = await _handle_discord_command(envelope, transport, scope, internal_user_id)
            if handled:
                return

        session_id = await session_manager.get_or_create_session_for_scope(
            user_id=internal_user_id,
            scope_type=scope.scope_type,
            scope_id=scope.scope_id,
            origin=envelope.origin,
            cache_key=scope.scope_id if scope.is_private else envelope.channel_id,
        )

        progress_stop, progress_task = await _start_progress_tracking(envelope, transport, session_id)
        await _persist_user_message(session_id, envelope, internal_user_id)

        try:
            response = await runtime.handle_message(session_id, envelope)
        finally:
            await _stop_progress_tracking(progress_stop, progress_task)
        if response.text or response.attachments:
            await transport.send_message(envelope.channel_id, response.text, attachments=response.attachments)
            await _persist_assistant_message(
                session_id,
                response.text,
                envelope.message_id,
                run_id=response.run_id,
                reasoning=response.reasoning,
            )

    manager.on_event(handler)

    config = uvicorn.Config(app, host="0.0.0.0", port=8000, log_level="info")
    server = uvicorn.Server(config)

    try:
        await asyncio.gather(server.serve(), manager.start())
    finally:
        await job_service.stop()


if __name__ == "__main__":
    asyncio.run(main())
