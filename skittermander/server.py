from __future__ import annotations

import asyncio
import os
import json
from datetime import datetime

import uvicorn

from .api.app import create_app
from .core.runtime import AgentRuntime
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
                        "last_seen_at": datetime.utcnow().isoformat(),
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
        if envelope.origin == "discord" and envelope.command == "schedule_list":
            async with SessionLocal() as session:
                repo = Repository(session)
                user = await repo.get_or_create_user(envelope.user_id)
            jobs = await scheduler.list_jobs(user.id)
            lines = [f"{j['id']} | {j['name']} | {j['cron']} | {'on' if j['enabled'] else 'off'}" for j in jobs]
            await transport.send_message(envelope.channel_id, "Scheduled jobs:\n" + "\n".join(lines))
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

        response = await runtime.handle_message(session_id, envelope)
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
