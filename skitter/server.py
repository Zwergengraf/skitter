from __future__ import annotations

import asyncio
import json
import contextlib
from datetime import datetime, UTC, timedelta

import uvicorn

from .api.app import create_app
from .core.command_service import command_service
from .core.runtime import AgentRuntime
from .core.graph import build_graph
from .core.llm import resolve_model_name
from .core.scheduler import SchedulerService
from .core.heartbeat import HeartbeatService
from .core.jobs import JobService
from .core.session_finalizer import SessionFinalizerService
from .core.conversation_scope import resolve_conversation_scope
from .core.config import settings
from .core.models import MessageEnvelope, StreamEvent
from .core.profile_service import profile_service
from .core.sessions import SessionManager
from .data.db import SessionLocal
from .data.repositories import Repository
from .transports.discord import DiscordTransport
from .transports.manager import TransportManager
from .tools.executors import executor_router, node_executor_hub
from .tools.sandbox_manager import sandbox_manager


def _serialize_attachments(attachments: list) -> list[dict]:
    serialized = []
    for attachment in attachments:
        url = getattr(attachment, "url", None)
        path = getattr(attachment, "path", None)
        if not url and not path:
            continue
        serialized.append(
            {
                "filename": getattr(attachment, "filename", ""),
                "content_type": getattr(attachment, "content_type", "") or "",
                "url": url,
                "path": path,
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
    user_prompt_service = app.state.user_prompt_service
    scheduler: SchedulerService = app.state.scheduler_service
    heartbeat_service = HeartbeatService(runtime)
    session_finalizer_service = SessionFinalizerService(runtime)
    job_service = JobService(
        runtime=runtime,
        graph_factory=lambda worker_model: build_graph(
            approval_service=approval_service,
            scheduler_service=scheduler,
            job_service=None,
            event_bus=app.state.event_bus,
            model_name=worker_model,
            purpose="main",
            include_subagent_tools=False,
            include_user_prompt_tools=False,
        ),
    )
    app.state.job_service = job_service
    app.state.session_finalizer_service = session_finalizer_service
    runtime.set_job_service(job_service)
    session_manager = SessionManager(runtime)
    if sandbox_manager is not None:
        await sandbox_manager.start()

    discord_enabled = settings.discord_enabled

    transports = []
    transport_by_origin = {}

    if discord_enabled:
        discord_transport = DiscordTransport()
        transports.append(discord_transport)
        transport_by_origin["discord"] = discord_transport
        approval_service.set_notifier(discord_transport.send_approval_request)
        discord_transport.set_approval_service(approval_service)
        user_prompt_service.set_notifier(discord_transport.send_user_prompt_request)
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
    await session_finalizer_service.start()
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

    async def _persist_user_message(session_id: str, envelope, internal_user_id: str):
        metadata = _build_message_metadata(envelope, internal_user_id)
        async with SessionLocal() as session:
            repo = Repository(session)
            answered_prompt = await repo.answer_pending_user_prompt_for_session(
                session_id,
                answer=envelope.text,
                answered_by=internal_user_id,
            )
            if answered_prompt is not None:
                metadata["answered_prompt_id"] = answered_prompt.id
            await repo.add_message(session_id, role="user", content=envelope.text, metadata=metadata)
        if answered_prompt is not None:
            await app.state.event_bus.emit_admin(
                kind="user_prompt.answered",
                level="info",
                title="User prompt answered",
                message=envelope.text or "The user answered a pending prompt.",
                session_id=session_id,
                user_id=internal_user_id,
                data={"prompt_id": answered_prompt.id},
            )
        return answered_prompt

    async def _persist_assistant_message(
        session_id: str,
        response_text: str,
        response_to: str,
        run_id: str | None = None,
        reasoning: list[str] | None = None,
        attachments: list | None = None,
        extra_metadata: dict[str, object] | None = None,
    ) -> None:
        metadata: dict[str, object] = {"response_to": response_to}
        if run_id:
            metadata["run_id"] = run_id
        if reasoning:
            metadata["reasoning"] = reasoning
        if extra_metadata:
            metadata.update(extra_metadata)
        if attachments:
            serialized = _serialize_attachments(attachments)
            if serialized:
                metadata["attachments"] = serialized
        async with SessionLocal() as session:
            repo = Repository(session)
            await repo.add_message(
                session_id,
                role="assistant",
                content=response_text,
                metadata=metadata,
            )
        session_memory_service = getattr(app.state, "session_memory_service", None)
        if session_memory_service is not None:
            await session_memory_service.maybe_schedule_update(session_id)

    async def _submit_prompt_reply(
        prompt_id: str,
        answer: str,
        transport_user_id: str,
        channel_id: str,
    ) -> None:
        async with SessionLocal() as session:
            repo = Repository(session)
            prompt = await repo.get_user_prompt(prompt_id)
            if prompt is None or prompt.status != "pending":
                return
            prompt_session = await repo.get_session(prompt.session_id)
            user = await repo.get_user_by_transport_id(transport_user_id)
            if prompt_session is None or user is None or user.id != prompt_session.user_id or not user.approved:
                return
        envelope = MessageEnvelope(
            message_id=f"prompt:{prompt_id}:{int(datetime.now(UTC).timestamp() * 1000)}",
            channel_id=channel_id,
            user_id=transport_user_id,
            timestamp=datetime.now(UTC),
            text=answer,
            origin="discord",
            metadata={},
        )
        await handler(envelope)

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

    async def _update_user_last_seen(internal_user_id: str, profile, envelope, scope) -> None:
        if envelope.origin != "discord":
            return
        async with SessionLocal() as session:
            repo = Repository(session)
            await repo.set_user_meta(internal_user_id, {"last_seen_at": datetime.now(UTC).isoformat()})
            if scope.is_private and profile is not None:
                await repo.update_agent_profile(
                    profile.id,
                    meta_updates={
                        "last_private_origin": scope.target_origin,
                        "last_private_destination_id": scope.target_destination_id,
                        "last_channel_id": envelope.channel_id,
                        "last_origin": envelope.origin,
                        "last_seen_at": datetime.now(UTC).isoformat(),
                    },
                )

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

    async def _handle_discord_command(
        envelope,
        transport: DiscordTransport,
        scope,
        internal_user_id: str,
        profile,
    ) -> bool:
        if envelope.origin != "discord" or not envelope.command:
            return False
        async with SessionLocal() as session:
            repo = Repository(session)
            user = await repo.get_user_by_id(internal_user_id)
            if user is None:
                return True
            try:
                result = await command_service.execute(
                    repo=repo,
                    user=user,
                    runtime=runtime,
                    scheduler=scheduler,
                    event_bus=app.state.event_bus,
                    command=envelope.command,
                    args=envelope.metadata or {},
                    origin=envelope.origin,
                    agent_profile_id=profile.id,
                    agent_profile_slug=profile.slug,
                    scope_type=scope.scope_type,
                    scope_id=scope.scope_id,
                    surface_id=envelope.channel_id,
                    persist_surface_profile=True,
                )
            except (LookupError, RuntimeError, ValueError) as exc:
                if envelope.metadata.get("interaction_response"):
                    envelope.metadata["ephemeral_response"] = str(exc)
                    envelope.metadata["suppress_ack"] = True
                else:
                    await transport.send_message(envelope.channel_id, str(exc))
                return True
        if envelope.metadata.get("interaction_response"):
            envelope.metadata["ephemeral_response"] = result.message or "Command completed."
            envelope.metadata["suppress_ack"] = True
        elif result.message:
            await transport.send_message(envelope.channel_id, result.message)
        return True

    async def handler(envelope):
        transport = transport_by_origin.get(envelope.origin)
        if transport is None:
            return

        internal_user_id = await _resolve_internal_user_id(envelope, transport)
        if internal_user_id is None:
            return

        async with SessionLocal() as session:
            repo = Repository(session)
            profile = await profile_service.current_surface_profile(
                repo,
                internal_user_id,
                origin=envelope.origin,
                channel_id=envelope.channel_id,
                agent_profile_id=str(envelope.metadata.get("agent_profile_id") or "").strip() or None,
                agent_profile_slug=str(envelope.metadata.get("agent_profile_slug") or "").strip() or None,
            )

        envelope.metadata["agent_profile_id"] = profile.id
        envelope.metadata["agent_profile_slug"] = profile.slug
        scope = resolve_conversation_scope(
            origin=envelope.origin,
            channel_id=envelope.channel_id,
            internal_user_id=profile.id,
            metadata=envelope.metadata,
        )
        envelope.metadata["internal_user_id"] = internal_user_id
        envelope.metadata["scope_type"] = scope.scope_type
        envelope.metadata["scope_id"] = scope.scope_id
        envelope.metadata["is_private"] = scope.is_private

        await _update_user_last_seen(internal_user_id, profile, envelope, scope)

        await transport.send_typing(envelope.channel_id)
        if isinstance(transport, DiscordTransport):
            handled = await _handle_discord_command(envelope, transport, scope, internal_user_id, profile)
            if handled:
                return

        session_id = await session_manager.get_or_create_session_for_scope(
            user_id=internal_user_id,
            agent_profile_id=profile.id,
            agent_profile_slug=profile.slug,
            scope_type=scope.scope_type,
            scope_id=scope.scope_id,
            origin=envelope.origin,
            cache_key=scope.scope_id if scope.is_private else envelope.channel_id,
        )

        progress_stop, progress_task = await _start_progress_tracking(envelope, transport, session_id)
        answered_prompt = await _persist_user_message(session_id, envelope, internal_user_id)
        if answered_prompt is not None and isinstance(transport, DiscordTransport):
            await transport.clear_user_prompt(answered_prompt.id)

        try:
            response = await runtime.handle_message(session_id, envelope)
        finally:
            await _stop_progress_tracking(progress_stop, progress_task)
        prompt_metadata: dict[str, object] | None = None
        if response.pending_prompt is not None:
            prompt_metadata = {
                "user_prompt": True,
                "user_prompt_id": response.pending_prompt.prompt_id,
                "user_prompt_question": response.pending_prompt.question,
                "user_prompt_choices": list(response.pending_prompt.choices),
                "user_prompt_allow_free_text": bool(response.pending_prompt.allow_free_text),
            }
        if response.pending_prompt is None and (response.text or response.attachments):
            await transport.send_message(envelope.channel_id, response.text, attachments=response.attachments)
        if response.text or response.attachments:
            await _persist_assistant_message(
                session_id,
                response.text,
                envelope.message_id,
                run_id=response.run_id,
                reasoning=response.reasoning,
                attachments=response.attachments,
                extra_metadata=prompt_metadata,
            )

    manager.on_event(handler)
    if discord_enabled:
        discord_transport.set_user_prompt_responder(_submit_prompt_reply)

    uvicorn_log_level = str(settings.log_level or "INFO").lower()
    config = uvicorn.Config(app, host="0.0.0.0", port=8000, log_level=uvicorn_log_level)
    server = uvicorn.Server(config)

    try:
        await asyncio.gather(server.serve(), manager.start())
    finally:
        await session_finalizer_service.stop()
        await job_service.stop()


if __name__ == "__main__":
    asyncio.run(main())
