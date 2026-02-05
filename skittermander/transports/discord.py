from __future__ import annotations

import asyncio
import io
import json
from datetime import datetime
from typing import Iterable, Optional

import discord
from discord import app_commands

from ..core.config import settings
from ..core.events import EventBus
from ..core.runtime import AgentRuntime
from ..core.graph import build_graph
from ..core.sessions import SessionManager
from ..data.db import SessionLocal
from ..data.repositories import Repository
from ..tools.approval_service import ToolApprovalService
from ..tools.sandbox_manager import sandbox_manager
from ..core.models import Attachment, MessageEnvelope
from .base import EventHandler, TransportAdapter


class ApprovalView(discord.ui.View):
    def __init__(self, tool_run_id: str, approval_service: ToolApprovalService | None) -> None:
        super().__init__(timeout=300)
        self.tool_run_id = tool_run_id
        self.approval_service = approval_service
        self.message: Optional[discord.Message] = None

    async def on_timeout(self) -> None:
        if self.approval_service is not None:
            await self.approval_service.resolve(self.tool_run_id, approved=False, decided_by="timeout")
        await self._disable_buttons()

    async def _disable_buttons(self) -> None:
        if self.message is not None:
            await self.message.edit(view=None)

    async def _append_status(self, status: str) -> None:
        if self.message is None:
            return
        updated = f"{self.message.content} -> {status}"
        await self.message.edit(content=updated, view=None)

    @discord.ui.button(label="Approve", style=discord.ButtonStyle.success)
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if self.approval_service is not None:
            await self.approval_service.resolve(self.tool_run_id, approved=True, decided_by=str(interaction.user.id))
        await self._append_status(":white_check_mark: Approved")
        try:
            await interaction.response.defer(thinking=False)
        except discord.HTTPException:
            try:
                await interaction.followup.send("Approved.", delete_after=5)
            except discord.HTTPException:
                pass

    @discord.ui.button(label="Deny", style=discord.ButtonStyle.danger)
    async def deny(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if self.approval_service is not None:
            await self.approval_service.resolve(self.tool_run_id, approved=False, decided_by=str(interaction.user.id))
        await self._append_status(":no_entry_sign: Denied")
        try:
            await interaction.response.defer(thinking=False)
        except discord.HTTPException:
            try:
                await interaction.followup.send("Denied.", delete_after=5)
            except discord.HTTPException:
                pass


class DiscordTransport(TransportAdapter):
    def __init__(self, token: Optional[str] = None) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        intents.guilds = True
        self.client = discord.Client(intents=intents)
        self.tree = app_commands.CommandTree(self.client)
        self._handler: EventHandler | None = None
        self.token = token or settings.discord_token
        self._approval_service: ToolApprovalService | None = None

        @self.client.event
        async def on_ready() -> None:
            await self.tree.sync()
            await self._sync_channels()

        @self.client.event
        async def on_message(message: discord.Message) -> None:
            if message.author.bot:
                return
            if not isinstance(message.channel, discord.DMChannel):
                return
            if self._handler is None:
                return
            await self._record_user_channel(message)
            envelope = MessageEnvelope(
                message_id=str(message.id),
                channel_id=str(message.channel.id),
                user_id=str(message.author.id),
                timestamp=message.created_at or datetime.utcnow(),
                text=message.content,
                attachments=[
                    Attachment(filename=a.filename, content_type=a.content_type or "", url=a.url)
                    for a in message.attachments
                ],
                origin="discord",
            )
            await self._handler(envelope)

        @self.tree.command(name="new", description="Start a new session")
        async def new_session(interaction: discord.Interaction) -> None:
            await self._handle_command(interaction, "new")

        @self.tree.command(name="memory_reindex", description="Rebuild memory embeddings from memory/*.md")
        async def memory_reindex(interaction: discord.Interaction) -> None:
            await self._handle_command(interaction, "memory_reindex")

        @self.tree.command(name="schedule_list", description="List scheduled jobs")
        async def schedule_list(interaction: discord.Interaction) -> None:
            await self._handle_command(interaction, "schedule_list")

        @self.tree.command(name="schedule_delete", description="Delete a scheduled job")
        async def schedule_delete(interaction: discord.Interaction, job_id: str) -> None:
            await self._handle_command(interaction, "schedule_delete", extra={"job_id": job_id})

        @self.tree.command(name="schedule_pause", description="Pause a scheduled job")
        async def schedule_pause(interaction: discord.Interaction, job_id: str) -> None:
            await self._handle_command(interaction, "schedule_pause", extra={"job_id": job_id})

        @self.tree.command(name="schedule_resume", description="Resume a scheduled job")
        async def schedule_resume(interaction: discord.Interaction, job_id: str) -> None:
            await self._handle_command(interaction, "schedule_resume", extra={"job_id": job_id})

        @self.tree.command(name="tools", description="Show tool permissions")
        async def tools(interaction: discord.Interaction) -> None:
            await self._handle_command(interaction, "tools")

    def on_event(self, handler: EventHandler) -> None:
        self._handler = handler

    def set_approval_service(self, approval_service: ToolApprovalService) -> None:
        self._approval_service = approval_service

    async def start(self) -> None:
        if not self.token:
            raise RuntimeError("SKITTER_DISCORD_TOKEN is required to start Discord transport")
        await self.client.start(self.token)

    async def stop(self) -> None:
        await self.client.close()

    async def send_message(
        self,
        channel_id: str,
        content: str,
        attachments: Iterable[Attachment] | None = None,
        metadata: dict | None = None,
    ) -> None:
        channel = await self.client.fetch_channel(int(channel_id))
        if not isinstance(channel, (discord.DMChannel, discord.TextChannel, discord.Thread)):
            return
        files = []
        if attachments:
            for attachment in attachments:
                if attachment.bytes_data:
                    files.append(discord.File(io.BytesIO(attachment.bytes_data), filename=attachment.filename))
                elif attachment.path:
                    files.append(discord.File(attachment.path))
        if files:
            await channel.send(content or "Screenshot:", files=files)
        else:
            await channel.send(content)

    async def send_typing(self, channel_id: str) -> None:
        channel = await self.client.fetch_channel(int(channel_id))
        if not isinstance(channel, (discord.DMChannel, discord.TextChannel, discord.Thread)):
            return
        await channel.typing()

    async def send_approval_request(
        self, tool_run_id: str, channel_id: str, tool_name: str, payload: dict
    ) -> None:
        channel = await self.client.fetch_channel(int(channel_id))
        if not isinstance(channel, discord.DMChannel):
            return
        view = ApprovalView(tool_run_id, self._approval_service)
        formatted = json.dumps(payload, indent=2, ensure_ascii=True)
        content = f"Agent wants to run `{tool_name}` with input:\n```json\n{formatted}\n```\nApprove or deny?"
        message = await channel.send(content, view=view)
        view.message = message

    async def _handle_command(self, interaction: discord.Interaction, command: str, extra: dict | None = None) -> None:
        if self._handler is None:
            await interaction.response.send_message("Handler is not configured.")
            return
        await interaction.response.defer(thinking=True)
        await self._record_interaction(interaction)
        envelope = MessageEnvelope(
            message_id=str(interaction.id),
            channel_id=str(interaction.channel_id),
            user_id=str(interaction.user.id),
            timestamp=datetime.utcnow(),
            text="",
            attachments=[],
            origin="discord",
            command=command,
            metadata=extra or {},
        )
        await self._handler(envelope)
        if envelope.metadata.get("suppress_ack"):
            return
        if interaction.response.is_done():
            await interaction.followup.send("Command received.")

    async def _record_user_channel(self, message: discord.Message) -> None:
        display_name = getattr(message.author, "display_name", None) or message.author.name
        username = message.author.name
        channel_name = f"@{display_name}"
        avatar_url = message.author.display_avatar.url if message.author.display_avatar else None
        async with SessionLocal() as session:
            repo = Repository(session)
            await repo.upsert_user_profile(str(message.author.id), display_name, username, avatar_url)
            await repo.upsert_channel(
                transport_channel_id=str(message.channel.id),
                name=channel_name,
                kind="dm",
            )

    async def _record_interaction(self, interaction: discord.Interaction) -> None:
        display_name = getattr(interaction.user, "display_name", None) or interaction.user.name
        username = interaction.user.name
        channel_name = f"@{display_name}"
        avatar_url = interaction.user.display_avatar.url if interaction.user.display_avatar else None
        async with SessionLocal() as session:
            repo = Repository(session)
            await repo.upsert_user_profile(str(interaction.user.id), display_name, username, avatar_url)
            if interaction.channel_id is not None:
                await repo.upsert_channel(
                    transport_channel_id=str(interaction.channel_id),
                    name=channel_name,
                    kind="dm",
                )

    async def _sync_channels(self) -> None:
        async with SessionLocal() as session:
            repo = Repository(session)
            for guild in self.client.guilds:
                for channel in guild.text_channels:
                    await repo.upsert_channel(
                        transport_channel_id=str(channel.id),
                        name=channel.name,
                        kind="text",
                        guild_id=str(guild.id),
                        guild_name=guild.name,
                    )


async def _run() -> None:
    event_bus = EventBus()
    approval_service = ToolApprovalService(event_bus)
    from ..core.scheduler import SchedulerService

    runtime = AgentRuntime(event_bus, approval_service=approval_service)
    transport = DiscordTransport()
    transport.set_approval_service(approval_service)
    approval_service.set_notifier(transport.send_approval_request)
    scheduler = SchedulerService(runtime)
    async def _deliver(channel_id: str, text: str, attachments: list) -> None:
        await transport.send_message(channel_id, text, attachments)
    scheduler.set_deliver(_deliver)
    await scheduler.start()
    if sandbox_manager is not None:
        await sandbox_manager.start()
    runtime.graph = build_graph(approval_service=approval_service, scheduler_service=scheduler)

    session_manager = SessionManager(runtime, settings.workspace_root)

    async def handler(envelope: MessageEnvelope) -> None:
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
                return
            envelope.metadata["internal_user_id"] = user.id

        await transport.send_typing(envelope.channel_id)

        if envelope.command == "new":
            summary_path, new_session_id = await session_manager.start_new_session(
                user_id=envelope.metadata.get("internal_user_id", envelope.user_id),
                channel_id=envelope.channel_id,
            )
            if summary_path:
                await transport.send_message(
                    envelope.channel_id,
                    f"Started a new session. Summary saved to `{summary_path.name}`.",
                )
            else:
                await transport.send_message(envelope.channel_id, "Started a new session.")
            return

        if envelope.command == "memory_reindex":
            stats = await session_manager.reindex_memories(envelope.metadata.get("internal_user_id", envelope.user_id))
            await transport.send_message(
                envelope.channel_id,
                f"Memory reindex complete. Indexed: {stats['indexed']}, skipped: {stats['skipped']}, removed: {stats['removed']}.",
            )
            return

        if envelope.command == "schedule_list":
            async with SessionLocal() as session:
                repo = Repository(session)
                user = await repo.get_or_create_user(envelope.user_id)
            jobs = await scheduler.list_jobs(user.id)
            lines = [f"{j['id']} | {j['name']} | {j['cron']} | {'on' if j['enabled'] else 'off'}" for j in jobs]
            await transport.send_message(envelope.channel_id, "Scheduled jobs:\n" + "\n".join(lines))
            return

        if envelope.command in {"schedule_delete", "schedule_pause", "schedule_resume"}:
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

        session_id = await session_manager.get_or_create_session(
            envelope.metadata.get("internal_user_id", envelope.user_id),
            envelope.channel_id,
        )

        async with SessionLocal() as session:
            repo = Repository(session)
            metadata = dict(envelope.metadata)
            metadata.update({"message_id": envelope.message_id, "origin": envelope.origin})
            await repo.add_message(session_id, role="user", content=envelope.text, metadata=metadata)

        response = await runtime.handle_message(session_id, envelope)
        if response.text or response.attachments:
            await transport.send_message(envelope.channel_id, response.text, attachments=response.attachments)
            async with SessionLocal() as session:
                repo = Repository(session)
                await repo.add_message(
                    session_id, role="assistant", content=response.text, metadata={"response_to": envelope.message_id}
                )

    transport.on_event(handler)
    await transport.start()


if __name__ == "__main__":
    asyncio.run(_run())
