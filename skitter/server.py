from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import UTC, datetime

import uvicorn

from .api.app import create_app
from .core.command_service import command_service
from .core.config import settings
from .core.conversation_scope import group_scope_id, resolve_conversation_scope
from .core.discord_mentions import DiscordMentionService
from .core.graph import build_graph
from .core.heartbeat import HeartbeatService
from .core.jobs import JobService
from .core.models import MessageEnvelope
from .core.profile_service import profile_service
from .core.runtime import AgentRuntime
from .core.scheduler import SchedulerService
from .core.secrets import SecretsManager
from .core.session_finalizer import SessionFinalizerService
from .core.session_run_queue import SessionRunQueue, SessionRunWork
from .core.sessions import SessionManager
from .core.transport_accounts import (
    DEFAULT_DISCORD_ACCOUNT_KEY,
    SURFACE_MODE_ALL_MESSAGES,
    discord_surface_kind,
    is_shared_default_account_key,
    transport_account_service,
)
from .data.db import SessionLocal
from .data.repositories import Repository
from .transports.discord import DiscordTransport
from .transports.manager import TransportManager
from .tools.sandbox_manager import sandbox_manager

_logger = logging.getLogger(__name__)


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


def _truncate_log_text(content: str | None, max_len: int = 160) -> str:
    text = str(content or "").strip()
    if len(text) <= max_len:
        return text
    if max_len <= 3:
        return text[:max_len]
    return f"{text[: max_len - 3]}..."


def _log_discord_drop(reason: str, envelope: MessageEnvelope, **extra: object) -> None:
    payload = {
        "reason": reason,
        "account": envelope.transport_account_key or DEFAULT_DISCORD_ACCOUNT_KEY,
        "message_id": envelope.message_id,
        "channel_id": envelope.channel_id,
        "guild_id": envelope.metadata.get("guild_id"),
        "user_id": envelope.user_id,
        "sender_is_bot": bool(envelope.metadata.get("sender_is_bot")),
        "is_private": bool(envelope.metadata.get("is_private")),
        "command": envelope.command or "",
        "text": _truncate_log_text(envelope.text),
    }
    payload.update(extra)
    ordered = " ".join(f"{key}={value!r}" for key, value in payload.items())
    _logger.info("Dropped Discord inbound after handler handoff: %s", ordered)


async def _load_transport_account_token(
    *,
    repo: Repository,
    row,
    secrets_manager: SecretsManager | None,
    secrets_error: str | None = None,
) -> tuple[str, str | None]:
    if secrets_manager is None:
        return "", f"Transport secrets are unavailable: {secrets_error or 'unknown error'}"
    if not str(getattr(row, "credential_secret_name", "") or "").strip():
        return "", "Transport account is missing its credential secret."
    secret = await repo.get_secret_exact(
        row.user_id,
        row.credential_secret_name,
        agent_profile_id=row.agent_profile_id,
    )
    if secret is None:
        return "", "Transport account credential secret was not found."
    try:
        token = secrets_manager.decrypt(secret.value_encrypted)
        await repo.touch_secret(secret)
        return token, None
    except Exception as exc:
        return "", f"Transport account credential decryption failed: {exc}"


async def _resolve_trusted_discord_sender_internal_user_id(
    *,
    repo: Repository,
    envelope: MessageEnvelope,
    runtime_states: dict[str, dict[str, object]] | None = None,
) -> str | None:
    tracked_user_id = str(envelope.metadata.get("skitter_sender_internal_user_id") or "").strip()
    if tracked_user_id:
        return tracked_user_id
    if not bool(envelope.metadata.get("sender_is_bot")):
        return None
    external_account_id = str(envelope.user_id or "").strip()
    row = await repo.get_transport_account_by_external_account_id("discord", external_account_id)
    if row is None and runtime_states:
        for account_key, state in runtime_states.items():
            if str(state.get("external_account_id") or "").strip() != external_account_id:
                continue
            envelope.metadata["trusted_transport_bot"] = True
            envelope.metadata["skitter_transport_account_key"] = account_key
            if is_shared_default_account_key(account_key):
                return None
            row = await repo.get_transport_account_by_key(account_key)
            if row is not None:
                break
    if row is None or not bool(getattr(row, "enabled", True)):
        return None
    envelope.metadata["trusted_transport_bot"] = True
    envelope.metadata["skitter_sender_internal_user_id"] = row.user_id
    envelope.metadata["skitter_sender_profile_id"] = row.agent_profile_id
    envelope.metadata["skitter_transport_account_key"] = row.account_key
    return str(row.user_id or "").strip() or None


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
            discord_mention_service=app.state.discord_mention_service,
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
    session_run_queue = SessionRunQueue()
    app.state.session_run_queue = session_run_queue
    app.state.transport_runtime_states = {}
    if sandbox_manager is not None:
        await sandbox_manager.start()

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
        recent_runs = [run for run in tool_runs if _to_utc_naive(run.created_at) >= started_at_naive]
        if recent_runs:
            latest = recent_runs[-1]
            return f"Working... {elapsed_seconds}s\nLast tool: `{latest.tool_name}` ({latest.status})"
        return f"Working... {elapsed_seconds}s\nLast step: thinking"

    async def _persist_transport_runtime_state(account_key: str, payload: dict[str, object]) -> None:
        states = dict(getattr(app.state, "transport_runtime_states", {}) or {})
        current = dict(states.get(account_key, {}) or {})
        current.update(payload)
        states[account_key] = current
        app.state.transport_runtime_states = states
        async with SessionLocal() as session:
            repo = Repository(session)
            row = await repo.get_transport_account_by_key(account_key)
            if row is None:
                return
            fields = {
                key: current.get(key)
                for key in ("status", "last_error", "external_account_id", "external_label", "last_seen_at")
                if key in current
            }
            if fields:
                await repo.update_transport_account(account_key, **fields)

    manager = TransportManager(runtime_state_notifier=_persist_transport_runtime_state)
    app.state.transport_manager = manager
    app.state.discord_mention_service = DiscordMentionService(manager)
    runtime.set_discord_mention_service(app.state.discord_mention_service)

    async def _submit_prompt_reply(
        prompt_id: str,
        answer: str,
        transport_user_id: str,
        channel_id: str,
        transport_account_key: str,
        is_private: bool,
    ) -> None:
        async with SessionLocal() as session:
            repo = Repository(session)
            prompt = await repo.get_user_prompt(prompt_id)
            if prompt is None or prompt.status != "pending":
                return
            prompt_session = await repo.get_session(prompt.session_id)
            user = await repo.get_user_by_transport_id(transport_user_id)
            if prompt_session is None or user is None or not user.approved:
                return
            if user.id != prompt_session.user_id:
                expected_group_scope = group_scope_id("discord", transport_account_key, channel_id)
                if prompt_session.scope_type != "group" or (prompt_session.scope_id or "") != expected_group_scope:
                    return
            if prompt_session.scope_type == "group" and (prompt_session.scope_id or "") != group_scope_id(
                "discord",
                transport_account_key,
                channel_id,
            ):
                return
        envelope = MessageEnvelope(
            message_id=f"prompt:{prompt_id}:{int(datetime.now(UTC).timestamp() * 1000)}",
            channel_id=channel_id,
            user_id=transport_user_id,
            timestamp=datetime.now(UTC),
            text=answer,
            origin="discord",
            transport_account_key=transport_account_key,
            metadata={"is_private": is_private},
        )
        await handler(envelope)

    def _configure_discord_transport(transport: DiscordTransport) -> None:
        transport.set_approval_service(approval_service)
        transport.set_user_prompt_responder(_submit_prompt_reply)

    async def _build_transport_instances() -> dict[str, DiscordTransport]:
        transports: dict[str, DiscordTransport] = {}
        if settings.discord_enabled and str(settings.discord_token or "").strip():
            default_transport = DiscordTransport(
                account_key=DEFAULT_DISCORD_ACCOUNT_KEY,
                token=str(settings.discord_token or "").strip(),
                display_name="Shared Default Discord Bot",
            )
            _configure_discord_transport(default_transport)
            transports[DEFAULT_DISCORD_ACCOUNT_KEY] = default_transport

        secrets_manager: SecretsManager | None = None
        secrets_error: str | None = None
        try:
            secrets_manager = SecretsManager()
            secrets_manager.ensure_ready()
        except Exception as exc:
            secrets_error = str(exc)

        async with SessionLocal() as session:
            repo = Repository(session)
            rows = await repo.list_transport_accounts(transport="discord")
            for row in rows:
                if not row.enabled:
                    continue
                token, error = await _load_transport_account_token(
                    repo=repo,
                    row=row,
                    secrets_manager=secrets_manager,
                    secrets_error=secrets_error,
                )
                if error:
                    await repo.update_transport_account(row.account_key, status="error", last_error=error)
                    continue
                transport = DiscordTransport(
                    account_key=row.account_key,
                    token=token,
                    pinned_profile_id=row.agent_profile_id,
                    display_name=row.display_name,
                )
                _configure_discord_transport(transport)
                transports[row.account_key] = transport
                await repo.update_transport_account(row.account_key, status="configured", last_error=None)
        return transports

    async def _reconcile_transports() -> None:
        await manager.reconcile(await _build_transport_instances())

    app.state.reconcile_transports = _reconcile_transports

    async def _resolve_delivery_transport(origin: str, transport_account_key: str | None) -> tuple[str, DiscordTransport]:
        if origin != "discord":
            raise RuntimeError(f"Unsupported delivery origin `{origin}`.")
        account_key = str(transport_account_key or "").strip() or DEFAULT_DISCORD_ACCOUNT_KEY
        transport = manager.get(account_key)
        if transport is None:
            raise RuntimeError(f"Unknown transport account `{account_key}`.")
        if not isinstance(transport, DiscordTransport):
            raise RuntimeError(f"Transport account `{account_key}` is not a Discord transport.")
        return account_key, transport

    async def _deliver(
        origin: str,
        transport_account_key: str | None,
        destination_id: str,
        text: str,
        attachments: list,
    ) -> None:
        account_key, _ = await _resolve_delivery_transport(origin, transport_account_key)
        await manager.send_message(account_key, destination_id, text, attachments)

    async def _notify_user(
        transport_user_id: str,
        message: str,
        attachments: list | None = None,
        *,
        origin: str = "discord",
        transport_account_key: str | None = None,
    ) -> None:
        account_key, _ = await _resolve_delivery_transport(origin, transport_account_key)
        await manager.send_user_message(account_key, transport_user_id, message, attachments=attachments)

    approval_service.set_notifier(
        lambda tool_run_id, channel_id, tool_name, account_key, payload: manager.send_approval_request(
            tool_run_id,
            channel_id,
            tool_name,
            account_key or DEFAULT_DISCORD_ACCOUNT_KEY,
            payload,
        )
    )
    user_prompt_service.set_notifier(
        lambda prompt_id, channel_id, account_key, question, choices, allow_free_text: manager.send_user_prompt_request(
            prompt_id,
            channel_id,
            account_key or DEFAULT_DISCORD_ACCOUNT_KEY,
            question,
            choices,
            allow_free_text,
        )
    )
    app.state.user_notifier = _notify_user

    scheduler.set_deliver(_deliver)
    heartbeat_service.set_deliver(_deliver)
    job_service.set_deliver(_deliver)
    await scheduler.start()
    await heartbeat_service.start()
    await session_finalizer_service.start()
    await job_service.start()

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

    def _should_show_progress(envelope: MessageEnvelope, transport: DiscordTransport) -> bool:
        return (
            envelope.origin == "discord"
            and isinstance(transport, DiscordTransport)
            and not envelope.command
            and settings.discord_progress_updates
        )

    async def _start_progress_tracking(
        envelope: MessageEnvelope,
        transport: DiscordTransport,
        session_id: str,
    ) -> tuple[asyncio.Event | None, asyncio.Task | None]:
        if not _should_show_progress(envelope, transport):
            return None, None
        stop_event = asyncio.Event()
        task = asyncio.create_task(_run_progress_loop(transport, envelope.channel_id, session_id, stop_event))
        return stop_event, task

    async def _stop_progress_tracking(stop_event: asyncio.Event | None, task: asyncio.Task | None) -> None:
        if stop_event is not None:
            stop_event.set()
        if task is not None:
            with contextlib.suppress(Exception):
                await task

    def _observe_queued_turn(future: asyncio.Future[dict[str, object]]) -> None:
        def _done(done: asyncio.Future[dict[str, object]]) -> None:
            with contextlib.suppress(asyncio.CancelledError):
                exc = done.exception()
                if exc is not None:
                    _logger.exception("Queued session run failed", exc_info=exc)

        future.add_done_callback(_done)

    def _build_message_metadata(
        envelope: MessageEnvelope,
        owner_internal_user_id: str,
        sender_internal_user_id: str | None = None,
    ) -> dict:
        metadata = dict(envelope.metadata)
        sender_value = sender_internal_user_id or owner_internal_user_id
        if sender_internal_user_id is None and bool(envelope.metadata.get("trusted_transport_bot")):
            sender_value = None
        metadata.update(
            {
                "internal_user_id": owner_internal_user_id,
                "sender_internal_user_id": sender_value,
                "message_id": envelope.message_id,
                "origin": envelope.origin,
                "transport_account_key": envelope.transport_account_key,
            }
        )
        if envelope.attachments:
            attachments_meta = _serialize_attachments(envelope.attachments)
            if attachments_meta:
                metadata["attachments"] = attachments_meta
                envelope.metadata["attachments"] = attachments_meta
        return metadata

    async def _persist_user_message(
        session_id: str,
        envelope: MessageEnvelope,
        owner_internal_user_id: str,
        sender_internal_user_id: str | None = None,
    ):
        answered_by = sender_internal_user_id or owner_internal_user_id
        metadata = _build_message_metadata(envelope, owner_internal_user_id, sender_internal_user_id)
        async with SessionLocal() as session:
            repo = Repository(session)
            answered_prompt = await repo.answer_pending_user_prompt_for_session(
                session_id,
                answer=envelope.text,
                answered_by=answered_by,
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
                user_id=owner_internal_user_id,
                data={"prompt_id": answered_prompt.id, "answered_by": answered_by},
            )
        return answered_prompt

    async def _session_has_pending_user_prompt(session_id: str) -> bool:
        async with SessionLocal() as session:
            repo = Repository(session)
            return await repo.get_pending_user_prompt_for_session(session_id) is not None

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
            await repo.add_message(session_id, role="assistant", content=response_text, metadata=metadata)
        session_memory_service = getattr(app.state, "session_memory_service", None)
        if session_memory_service is not None:
            await session_memory_service.maybe_schedule_update(session_id)

    async def _resolve_internal_user_id(envelope: MessageEnvelope, transport: DiscordTransport) -> str | None:
        if envelope.origin != "discord":
            return envelope.user_id
        async with SessionLocal() as session:
            repo = Repository(session)
            trusted_user_id = await _resolve_trusted_discord_sender_internal_user_id(
                repo=repo,
                envelope=envelope,
                runtime_states=manager.snapshot_states(),
            )
            if trusted_user_id:
                return trusted_user_id
            if bool(envelope.metadata.get("trusted_transport_bot")):
                return None
            user = await repo.get_or_create_user(envelope.user_id)
            if not user.approved:
                if bool(envelope.metadata.get("is_private")):
                    notified_accounts = set((user.meta or {}).get("approval_notified_accounts") or [])
                    if envelope.transport_account_key not in notified_accounts:
                        await transport.send_message(
                            envelope.channel_id,
                            "Your account is not yet approved. An admin has to approve it first.",
                            metadata={"suppress_agent_processing": True},
                        )
                        await repo.mark_user_notified(user.id, envelope.transport_account_key)
                _log_discord_drop("unapproved_sender", envelope, internal_user_id=user.id)
                envelope.metadata["suppress_ack"] = True
                return None
            return user.id

    async def _resolve_profile_for_envelope(
        repo: Repository,
        sender_internal_user_id: str | None,
        envelope: MessageEnvelope,
    ) -> tuple[object | None, str | None]:
        if envelope.origin != "discord":
            if not sender_internal_user_id:
                return None, None
            profile = await profile_service.current_surface_profile(
                repo,
                sender_internal_user_id,
                origin=envelope.origin,
                channel_id=envelope.channel_id,
                agent_profile_id=str(envelope.metadata.get("agent_profile_id") or "").strip() or None,
                agent_profile_slug=str(envelope.metadata.get("agent_profile_slug") or "").strip() or None,
                transport_account_key=envelope.transport_account_key,
            )
            return profile, None

        if bool(envelope.metadata.get("is_private")):
            if not sender_internal_user_id:
                _log_discord_drop("trusted_transport_bot_private_message_unsupported", envelope)
                return None, None
            pinned_profile_id = str(envelope.metadata.get("pinned_profile_id") or "").strip()
            if pinned_profile_id:
                profile = await repo.get_agent_profile(pinned_profile_id)
                if profile is None or profile.user_id != sender_internal_user_id or profile.status == "archived":
                    _log_discord_drop(
                        "pinned_profile_unavailable",
                        envelope,
                        pinned_profile_id=pinned_profile_id,
                        sender_internal_user_id=sender_internal_user_id,
                    )
                    return None, None
                return profile, None
            profile, notice = await transport_account_service.resolve_shared_default_dm_profile(
                repo,
                user_id=sender_internal_user_id,
                channel_id=envelope.channel_id,
                origin="discord",
                transport_account_key=envelope.transport_account_key or DEFAULT_DISCORD_ACCOUNT_KEY,
            )
            if profile is not None and notice:
                await repo.upsert_surface_profile_override(
                    user_id=sender_internal_user_id,
                    agent_profile_id=profile.id,
                    origin="discord",
                    transport_account_key=envelope.transport_account_key or DEFAULT_DISCORD_ACCOUNT_KEY,
                    surface_kind=discord_surface_kind(),
                    surface_id=envelope.channel_id,
                )
            if profile is None:
                _log_discord_drop(
                    "shared_default_dm_profile_unavailable",
                    envelope,
                    sender_internal_user_id=sender_internal_user_id,
                )
            return profile, notice

        binding = await repo.get_transport_surface_binding_for_surface(
            origin="discord",
            transport_account_key=envelope.transport_account_key or DEFAULT_DISCORD_ACCOUNT_KEY,
            surface_kind=discord_surface_kind(),
            surface_id=envelope.channel_id,
        )
        binding_surface_id = envelope.channel_id
        if binding is None:
            parent_channel_id = str(envelope.metadata.get("parent_channel_id") or "").strip()
            if parent_channel_id:
                binding = await repo.get_transport_surface_binding_for_surface(
                    origin="discord",
                    transport_account_key=envelope.transport_account_key or DEFAULT_DISCORD_ACCOUNT_KEY,
                    surface_kind=discord_surface_kind(),
                    surface_id=parent_channel_id,
                )
                if binding is not None:
                    binding_surface_id = parent_channel_id
        if binding is None:
            _log_discord_drop("no_channel_binding", envelope)
            return None, None
        if not binding.enabled:
            _log_discord_drop("channel_binding_disabled", envelope, binding_surface_id=binding_surface_id)
            return None, None
        mode = str(binding.mode or SURFACE_MODE_ALL_MESSAGES).strip().lower()
        if mode != SURFACE_MODE_ALL_MESSAGES:
            explicit = bool(envelope.metadata.get("is_explicit_interaction"))
            mentions_bot = bool(envelope.metadata.get("mentions_bot"))
            reply_to_bot = bool(envelope.metadata.get("reply_to_bot"))
            if not (explicit or mentions_bot or reply_to_bot):
                _log_discord_drop(
                    "mention_only_not_triggered",
                    envelope,
                    binding_surface_id=binding_surface_id,
                    mode=mode,
                    mentions_bot=mentions_bot,
                    reply_to_bot=reply_to_bot,
                    explicit=explicit,
                )
                return None, None
        profile = await repo.get_agent_profile(binding.agent_profile_id)
        if profile is None:
            _log_discord_drop(
                "bound_profile_missing",
                envelope,
                binding_surface_id=binding_surface_id,
                profile_id=binding.agent_profile_id,
            )
            return None, None
        if profile.status == "archived":
            _log_discord_drop(
                "bound_profile_archived",
                envelope,
                binding_surface_id=binding_surface_id,
                profile_id=profile.id,
            )
            return None, None
        if is_shared_default_account_key(envelope.transport_account_key):
            explicit_account = await repo.get_transport_account_for_profile(profile.id, "discord")
            if explicit_account is not None and explicit_account.enabled:
                _log_discord_drop(
                    "shared_default_blocked_by_dedicated_bot",
                    envelope,
                    binding_surface_id=binding_surface_id,
                    profile_id=profile.id,
                    dedicated_account_key=explicit_account.account_key,
                )
                return None, None
        return profile, None

    async def _update_user_last_seen(internal_user_id: str, profile, envelope: MessageEnvelope, scope) -> None:
        if not internal_user_id:
            return
        if envelope.origin != "discord":
            return
        async with SessionLocal() as session:
            repo = Repository(session)
            user = await repo.get_user_by_id(internal_user_id)
            user_meta = dict(getattr(user, "meta", {}) or {})
            per_origin = dict(user_meta.get("last_transport_account_key_by_origin") or {})
            per_origin[envelope.origin] = envelope.transport_account_key
            await repo.set_user_meta(
                internal_user_id,
                {
                    "last_seen_at": datetime.now(UTC).isoformat(),
                    "last_transport_account_key_by_origin": per_origin,
                },
            )
            if scope.is_private and profile is not None:
                await repo.update_agent_profile(
                    profile.id,
                    meta_updates={
                        "last_private_origin": scope.target_origin,
                        "last_private_destination_id": scope.target_destination_id,
                        "last_private_transport_account_key": envelope.transport_account_key,
                        "last_channel_id": envelope.channel_id,
                        "last_origin": envelope.origin,
                        "last_seen_at": datetime.now(UTC).isoformat(),
                    },
                )

    async def _handle_discord_command(
        envelope: MessageEnvelope,
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
                    persist_surface_profile=bool(scope.is_private),
                    transport_account_key=envelope.transport_account_key,
                    surface_is_private=scope.is_private,
                )
            except (LookupError, RuntimeError, ValueError) as exc:
                if envelope.metadata.get("interaction_response"):
                    envelope.metadata["ephemeral_response"] = str(exc)
                    envelope.metadata["suppress_ack"] = True
                else:
                    await transport.send_message(
                        envelope.channel_id,
                        str(exc),
                        metadata={"suppress_agent_processing": True},
                    )
                return True
        if envelope.metadata.get("interaction_response"):
            envelope.metadata["ephemeral_response"] = result.message or "Command completed."
            envelope.metadata["suppress_ack"] = True
        elif result.message:
            await transport.send_message(
                envelope.channel_id,
                result.message,
                metadata={"suppress_agent_processing": True},
            )
        return True

    async def _process_runtime_turn(
        *,
        session_id: str,
        envelope: MessageEnvelope,
        transport: DiscordTransport,
        owner_internal_user_id: str,
    ) -> dict[str, object]:
        sender_internal_user_id = None
        if not envelope.metadata.get("coalesced_messages"):
            sender_internal_user_id = str(envelope.metadata.get("sender_internal_user_id") or "").strip() or None
        await transport.send_typing(envelope.channel_id)
        progress_stop, progress_task = await _start_progress_tracking(envelope, transport, session_id)
        answered_prompt = await _persist_user_message(
            session_id,
            envelope,
            owner_internal_user_id,
            sender_internal_user_id,
        )
        if answered_prompt is not None:
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
            await transport.send_message(
                envelope.channel_id,
                response.text,
                attachments=response.attachments,
                metadata={
                    "skitter_sender_internal_user_id": owner_internal_user_id,
                    "skitter_sender_profile_id": str(envelope.metadata.get("agent_profile_id") or "").strip() or None,
                    "skitter_sender_profile_slug": str(envelope.metadata.get("agent_profile_slug") or "").strip() or None,
                    "skitter_transport_account_key": envelope.transport_account_key,
                    "skitter_message_kind": "agent_reply",
                },
            )
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
        return {
            "pending_prompt": bool(response.pending_prompt is not None),
            "response_sent": bool(response.text or response.attachments),
        }

    async def handler(envelope: MessageEnvelope) -> None:
        account_key = envelope.transport_account_key or DEFAULT_DISCORD_ACCOUNT_KEY
        transport = manager.get(account_key)
        if transport is None or not isinstance(transport, DiscordTransport):
            if envelope.origin == "discord":
                _log_discord_drop("missing_transport_instance", envelope, requested_account_key=account_key)
            return

        sender_internal_user_id = await _resolve_internal_user_id(envelope, transport)
        if sender_internal_user_id is None and not bool(envelope.metadata.get("trusted_transport_bot")):
            return

        async with SessionLocal() as session:
            repo = Repository(session)
            profile, routing_notice = await _resolve_profile_for_envelope(repo, sender_internal_user_id, envelope)
        if profile is None:
            return
        if routing_notice:
            with contextlib.suppress(Exception):
                await transport.send_message(
                    envelope.channel_id,
                    routing_notice,
                    metadata={"suppress_agent_processing": True},
                )

        owner_internal_user_id = profile.user_id
        envelope.metadata["agent_profile_id"] = profile.id
        envelope.metadata["agent_profile_slug"] = profile.slug
        envelope.metadata["transport_account_key"] = account_key
        scope = resolve_conversation_scope(
            origin=envelope.origin,
            channel_id=envelope.channel_id,
            internal_user_id=profile.id,
            metadata=envelope.metadata,
        )
        envelope.metadata["internal_user_id"] = owner_internal_user_id
        envelope.metadata["sender_internal_user_id"] = sender_internal_user_id
        envelope.metadata["scope_type"] = scope.scope_type
        envelope.metadata["scope_id"] = scope.scope_id
        envelope.metadata["is_private"] = scope.is_private

        await _update_user_last_seen(sender_internal_user_id, profile, envelope, scope)

        handled = await _handle_discord_command(envelope, transport, scope, owner_internal_user_id, profile)
        if handled:
            return

        session_id = await session_manager.get_or_create_session_for_scope(
            user_id=owner_internal_user_id,
            agent_profile_id=profile.id,
            agent_profile_slug=profile.slug,
            scope_type=scope.scope_type,
            scope_id=scope.scope_id,
            origin=envelope.origin,
            cache_key=scope.scope_id if scope.is_private else f"{account_key}:{envelope.channel_id}",
        )
        coalescible = (
            envelope.origin == "discord"
            and not scope.is_private
            and not envelope.command
            and not envelope.attachments
            and not bool(envelope.metadata.get("interaction_response"))
            and not bool(envelope.metadata.get("is_explicit_interaction"))
            and bool(str(envelope.text or "").strip())
            and not await _session_has_pending_user_prompt(session_id)
        )

        queued_future = await session_run_queue.submit(
            SessionRunWork(
                session_id=session_id,
                envelope=envelope,
                process=lambda queued_envelope: _process_runtime_turn(
                    session_id=session_id,
                    envelope=queued_envelope,
                    transport=transport,
                    owner_internal_user_id=owner_internal_user_id,
                ),
                coalescible=coalescible,
            )
        )
        _observe_queued_turn(queued_future)

    await _reconcile_transports()
    manager.on_event(handler)

    uvicorn_log_level = str(settings.log_level or "INFO").lower()
    config = uvicorn.Config(app, host="0.0.0.0", port=8000, log_level=uvicorn_log_level)
    server = uvicorn.Server(config)
    server_task = asyncio.create_task(server.serve(), name="skitter-uvicorn")
    manager_task = asyncio.create_task(manager.start(), name="skitter-transports")

    try:
        await server_task
    finally:
        await manager.stop()
        manager_task.cancel()
        with contextlib.suppress(BaseException):
            await manager_task
        await session_finalizer_service.stop()
        await heartbeat_service.shutdown()
        await scheduler.shutdown()
        await job_service.stop()


if __name__ == "__main__":
    asyncio.run(main())
