from __future__ import annotations

import asyncio
import os
import json
import contextlib
from datetime import datetime, UTC

import uvicorn

from .api.app import create_app
from .core.runtime import AgentRuntime
from .core.llm import list_models, resolve_model_name
from .core.scheduler import SchedulerService
from .core.heartbeat import HeartbeatService
from .core.config import settings
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
        async def _deliver(channel_id: str, text: str, attachments: list) -> None:
            await discord_transport.send_message(channel_id, text, attachments)
        scheduler.set_deliver(_deliver)
        heartbeat_service.set_deliver(_deliver)
        await scheduler.start()
        await heartbeat_service.start()

    manager = TransportManager(transports)

    async def _progress_status_text(session_id: str, started_at: datetime) -> str:
        async with SessionLocal() as session:
            repo = Repository(session)
            tool_runs = await repo.list_tool_runs_by_session(session_id)
        elapsed_seconds = max(0, int((datetime.now(UTC) - started_at).total_seconds()))
        if tool_runs:
            latest = tool_runs[-1]
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

    async def handler(envelope):
        transport = transport_by_origin.get(envelope.origin)
        if transport is None:
            return

        internal_user_id = envelope.user_id
        if envelope.origin == "discord":
            async with SessionLocal() as session:
                repo = Repository(session)
                user = await repo.get_or_create_user(envelope.user_id)
                internal_user_id = user.id
                await repo.set_user_meta(
                    user.id,
                    {
                        "last_channel_id": envelope.channel_id,
                        "last_origin": envelope.origin,
                        "last_seen_at": datetime.now(UTC).isoformat(),
                    },
                )
                if not user.approved:
                    if not (user.meta or {}).get("approval_notified"):
                        await transport.send_message(
                            envelope.channel_id,
                            "Your account is not yet approved. An admin has to approve it first.",
                        )
                        await repo.mark_user_notified(user.id)
                    envelope.metadata["suppress_ack"] = True
                    return

        envelope.metadata["internal_user_id"] = internal_user_id

        await transport.send_typing(envelope.channel_id)

        if envelope.origin == "discord" and envelope.command == "new":
            summary_path, _ = await session_manager.start_new_session(internal_user_id, envelope.channel_id)
            if summary_path:
                await transport.send_message(
                    envelope.channel_id, f"Started a new session. Summary saved to `{summary_path.name}`."
                )
            else:
                await transport.send_message(envelope.channel_id, "Started a new session.")
            return
        if envelope.origin == "discord" and envelope.command == "memory_reindex":
            stats = await session_manager.reindex_memories(internal_user_id)
            await transport.send_message(
                envelope.channel_id,
                f"Memory reindex complete. Indexed: {stats['indexed']}, skipped: {stats['skipped']}, removed: {stats['removed']}.",
            )
            return
        if envelope.origin == "discord" and envelope.command == "memory_search":
            query = str((envelope.metadata or {}).get("query") or "").strip()
            if not query:
                envelope.metadata["ephemeral_response"] = "Query is required."
                envelope.metadata["suppress_ack"] = True
                return
            results = await session_manager.search_memories(internal_user_id, query, top_k=5)
            envelope.metadata["ephemeral_response"] = _format_memory_search_results(query, results)
            envelope.metadata["suppress_ack"] = True
            return
        if envelope.origin == "discord" and envelope.command == "schedule_list":
            async with SessionLocal() as session:
                repo = Repository(session)
                user = await repo.get_or_create_user(envelope.user_id)
            jobs = await scheduler.list_jobs(user.id)
            lines = [f"{j['id']} | {j['name']} | {j['cron']} | {'on' if j['enabled'] else 'off'}" for j in jobs]
            await transport.send_message(envelope.channel_id, "Scheduled jobs:\n" + "\n".join(lines))
            return
        if envelope.origin == "discord" and envelope.command == "model":
            requested = envelope.metadata.get("model_name") if envelope.metadata else None
            models = list_models()
            if not models:
                await transport.send_message(envelope.channel_id, "No models are configured.")
                return
            if not requested:
                async with SessionLocal() as session:
                    repo = Repository(session)
                    active = await repo.get_active_session(internal_user_id)
                current = active.model if active and active.model else None
                if current is None:
                    current = resolve_model_name(None, purpose="main")
                lines = []
                for item in models:
                    suffix = " (active)" if current and item.name.lower() == current.lower() else ""
                    lines.append(f"- {item.name}{suffix}")
                await transport.send_message(envelope.channel_id, "Available models:\n" + "\n".join(lines))
                return
            match = None
            for item in models:
                if item.name.lower() == str(requested).lower():
                    match = item
                    break
            if match is None:
                await transport.send_message(
                    envelope.channel_id,
                    f"Unknown model `{requested}`. Use /model to list available models.",
                )
                return
            async with SessionLocal() as session:
                repo = Repository(session)
                active = await repo.get_active_session(internal_user_id)
                if active is None:
                    active = await repo.create_session(internal_user_id, model=match.name)
                else:
                    await repo.set_session_model(active.id, match.name)
            runtime.set_session_model(active.id, match.name)
            await transport.send_message(
                envelope.channel_id,
                f"Active model set to `{match.name}`.",
            )
            return
        if envelope.origin == "discord" and envelope.command == "info":
            async with SessionLocal() as session:
                repo = Repository(session)
                active = await repo.get_active_session(internal_user_id)
            if active is None:
                await transport.send_message(envelope.channel_id, "No active session found.")
                return
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
            return
        if envelope.origin == "discord" and envelope.command in {"schedule_delete", "schedule_pause", "schedule_resume"}:
            job_id = envelope.metadata.get("job_id")
            if not job_id:
                await transport.send_message(envelope.channel_id, "Job id is required.")
                return
            if envelope.command == "schedule_delete":
                result = await scheduler.delete_job(job_id)
            elif envelope.command == "schedule_pause":
                result = await scheduler.update_job(job_id, enabled=False)
            else:
                result = await scheduler.update_job(job_id, enabled=True)
            await transport.send_message(envelope.channel_id, json.dumps(result))
            return

        session_id = envelope.channel_id
        if envelope.origin == "discord":
            session_id = await session_manager.get_or_create_session(internal_user_id, envelope.channel_id)

        progress_stop: asyncio.Event | None = None
        progress_task: asyncio.Task | None = None
        if (
            envelope.origin == "discord"
            and isinstance(transport, DiscordTransport)
            and not envelope.command
            and settings.discord_progress_updates
        ):
            progress_stop = asyncio.Event()
            progress_task = asyncio.create_task(
                _run_progress_loop(transport, envelope.channel_id, session_id, progress_stop)
            )

        async with SessionLocal() as session:
            repo = Repository(session)
            metadata = dict(envelope.metadata)
            metadata.update({"internal_user_id": internal_user_id})
            metadata.update({"message_id": envelope.message_id, "origin": envelope.origin})
            if envelope.attachments:
                attachments_meta = _serialize_attachments(envelope.attachments)
                if attachments_meta:
                    metadata["attachments"] = attachments_meta
                    envelope.metadata["attachments"] = attachments_meta
            await repo.add_message(session_id, role="user", content=envelope.text, metadata=metadata)

        try:
            response = await runtime.handle_message(session_id, envelope)
        finally:
            if progress_stop is not None:
                progress_stop.set()
            if progress_task is not None:
                with contextlib.suppress(Exception):
                    await progress_task
        if response.text or response.attachments:
            await transport.send_message(envelope.channel_id, response.text, attachments=response.attachments)
            async with SessionLocal() as session:
                repo = Repository(session)
                await repo.add_message(
                    session_id, role="assistant", content=response.text, metadata={"response_to": envelope.message_id}
                )

    manager.on_event(handler)

    config = uvicorn.Config(app, host="0.0.0.0", port=8000, log_level="info")
    server = uvicorn.Server(config)

    await asyncio.gather(server.serve(), manager.start())


if __name__ == "__main__":
    asyncio.run(main())
