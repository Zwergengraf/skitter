from __future__ import annotations
import asyncio
import io
import json
import re
from datetime import datetime
from typing import Iterable, Optional

import discord
from discord import app_commands

from ..core.config import settings
from ..data.db import SessionLocal
from ..data.repositories import Repository
from ..tools.approval_service import ToolApprovalService
from ..core.models import Attachment, MessageEnvelope
from .base import EventHandler, TransportAdapter

DISCORD_MESSAGE_CHAR_LIMIT = 2000
LINK_WRAP_THRESHOLD = 3
URL_PATTERN = re.compile(r"https?://[^\s<>]+")
UNWRAPPED_URL_PATTERN = re.compile(r"(?<!<)(https?://[^\s<>]+)(?!>)")
PARAGRAPH_BREAK_PATTERN = re.compile(r"\n{2,}")
SENTENCE_BREAK_PATTERN = re.compile(r"[.!?](?:[\"')\]]+)?\s+")


def _count_links(content: str) -> int:
    return len(URL_PATTERN.findall(content))


def _split_trailing_url_punctuation(url: str) -> tuple[str, str]:
    suffix = ""
    while url:
        last = url[-1]
        if last in ",.!?;:":
            suffix = last + suffix
            url = url[:-1]
            continue
        if last == ")" and url.count("(") < url.count(")"):
            suffix = last + suffix
            url = url[:-1]
            continue
        if last == "]" and url.count("[") < url.count("]"):
            suffix = last + suffix
            url = url[:-1]
            continue
        break
    return url, suffix


def _wrap_links_for_discord(content: str) -> str:
    def _replace(match: re.Match[str]) -> str:
        raw = match.group(1)
        clean_url, suffix = _split_trailing_url_punctuation(raw)
        if not clean_url:
            return raw
        return f"<{clean_url}>{suffix}"

    return UNWRAPPED_URL_PATTERN.sub(_replace, content)


def _prepare_discord_content(content: str) -> str:
    if _count_links(content) < LINK_WRAP_THRESHOLD:
        return content
    return _wrap_links_for_discord(content)


def _find_last_regex_break(pattern: re.Pattern[str], content: str, min_index: int) -> int:
    last_end = -1
    for match in pattern.finditer(content):
        if match.end() >= min_index:
            last_end = match.end()
    return last_end


def _find_best_split_index(content: str, max_len: int) -> int:
    if len(content) <= max_len:
        return len(content)

    search = content[:max_len]
    preferred_min = max(1, int(max_len * 0.6))

    for min_index in (preferred_min, 1):
        paragraph_break = _find_last_regex_break(PARAGRAPH_BREAK_PATTERN, search, min_index)
        if paragraph_break != -1:
            return paragraph_break

        line_break = search.rfind("\n", min_index)
        if line_break != -1:
            return line_break + 1

        sentence_break = _find_last_regex_break(SENTENCE_BREAK_PATTERN, search, min_index)
        if sentence_break != -1:
            return sentence_break

        for separator in ("; ", ": ", ", "):
            separator_index = search.rfind(separator, min_index)
            if separator_index != -1:
                return separator_index + len(separator)

        space_index = search.rfind(" ", min_index)
        if space_index != -1:
            return space_index + 1

    return max_len


def _split_discord_content(content: str, max_len: int = DISCORD_MESSAGE_CHAR_LIMIT) -> list[str]:
    if len(content) <= max_len:
        return [content]

    chunks: list[str] = []
    remaining = content
    while len(remaining) > max_len:
        split_index = _find_best_split_index(remaining, max_len)
        if split_index <= 0:
            split_index = max_len
        chunks.append(remaining[:split_index])
        remaining = remaining[split_index:]
    if remaining:
        chunks.append(remaining)
    return chunks


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
            is_private = isinstance(message.channel, discord.DMChannel)
            if not is_private and not isinstance(message.channel, (discord.TextChannel, discord.Thread)):
                return
            if self._handler is None:
                return
            await self._record_user_channel(message, is_private=is_private)
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
                metadata={
                    "is_private": is_private,
                    "external_channel_id": str(message.channel.id),
                    "guild_id": str(message.guild.id) if message.guild else None,
                },
            )
            await self._handler(envelope)

        @self.tree.command(name="new", description="Start a new session")
        async def new_session(interaction: discord.Interaction) -> None:
            await self._handle_command(interaction, "new")

        @self.tree.command(name="memory_reindex", description="Rebuild memory embeddings from memory/*.md")
        async def memory_reindex(interaction: discord.Interaction) -> None:
            await self._handle_command(interaction, "memory_reindex")

        @self.tree.command(name="memory_search", description="Search indexed memory by semantic similarity")
        async def memory_search(interaction: discord.Interaction, query: str) -> None:
            await self._handle_command(
                interaction,
                "memory_search",
                extra={"query": query},
                ephemeral=True,
            )

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

        @self.tree.command(name="model", description="List models or set active model (provider/model)")
        async def model(interaction: discord.Interaction, model_name: Optional[str] = None) -> None:
            await self._handle_command(interaction, "model", extra={"model_name": model_name} if model_name else None)

        @self.tree.command(name="machine", description="List machines or set default machine")
        async def machine(interaction: discord.Interaction, target_machine: Optional[str] = None) -> None:
            await self._handle_command(
                interaction,
                "machine",
                extra={"target_machine": target_machine} if target_machine else None,
            )

        @self.tree.command(name="pair", description="Create a short-lived code to pair another client")
        async def pair(interaction: discord.Interaction) -> None:
            await self._handle_command(interaction, "pair", ephemeral=True)

        @self.tree.command(name="info", description="Show session usage and cost info")
        async def info(interaction: discord.Interaction) -> None:
            await self._handle_command(interaction, "info")

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
    
    async def _send_split_message(
        self,
        channel: discord.abc.Messageable,
        content: str,
        files: list[discord.File] | None = None,
    ) -> None:
        # Discord messages are capped at 2000 chars.
        # Files (if any) are attached only to the first chunk.
        files = files or []
        prepared = _prepare_discord_content(content)
        chunks = _split_discord_content(prepared, DISCORD_MESSAGE_CHAR_LIMIT)
        for i, chunk in enumerate(chunks):
            if i == 0:
                await channel.send(chunk, files=files)
            else:
                await channel.send(chunk)

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
            await self._send_split_message(channel, content or "Screenshot:", files=files)
        else:
            await self._send_split_message(channel, content)

    async def send_user_message(
        self,
        user_id: str,
        content: str,
        attachments: Iterable[Attachment] | None = None,
        metadata: dict | None = None,
    ) -> None:
        user = await self.client.fetch_user(int(user_id))
        if user is None:
            return
        channel = await user.create_dm()
        files = []
        if attachments:
            for attachment in attachments:
                if attachment.bytes_data:
                    files.append(discord.File(io.BytesIO(attachment.bytes_data), filename=attachment.filename))
                elif attachment.path:
                    files.append(discord.File(attachment.path))
        if files:
            await self._send_split_message(channel, content or "Screenshot:", files=files)
        else:
            await self._send_split_message(channel, content)

    async def send_typing(self, channel_id: str) -> None:
        channel = await self.client.fetch_channel(int(channel_id))
        if not isinstance(channel, (discord.DMChannel, discord.TextChannel, discord.Thread)):
            return
        await channel.typing()

    async def start_progress_message(self, channel_id: str, content: str = "Working...") -> discord.Message | None:
        try:
            channel = await self.client.fetch_channel(int(channel_id))
        except Exception:
            return None
        if not isinstance(channel, (discord.DMChannel, discord.TextChannel, discord.Thread)):
            return None
        try:
            return await channel.send(content)
        except Exception:
            return None

    async def update_progress_message(self, message: discord.Message | None, content: str) -> None:
        if message is None:
            return
        try:
            if message.content != content:
                await message.edit(content=content)
        except Exception:
            return

    async def stop_progress_message(self, message: discord.Message | None, keep_seconds: float = 1.5) -> None:
        if message is None:
            return
        if keep_seconds > 0:
            try:
                await asyncio.sleep(keep_seconds)
            except Exception:
                pass
        try:
            await message.delete()
        except Exception:
            return

    async def send_approval_request(
        self, tool_run_id: str, channel_id: str, tool_name: str, payload: dict
    ) -> None:
        channel = await self.client.fetch_channel(int(channel_id))
        if not isinstance(channel, (discord.DMChannel, discord.TextChannel, discord.Thread)):
            return
        view = ApprovalView(tool_run_id, self._approval_service)
        formatted = json.dumps(payload, indent=2, ensure_ascii=True)
        content = f"Agent wants to run `{tool_name}` with input:\n```json\n{formatted}\n```\nApprove or deny?"
        message = await channel.send(content, view=view)
        view.message = message

    async def _handle_command(
        self,
        interaction: discord.Interaction,
        command: str,
        extra: dict | None = None,
        ephemeral: bool = False,
    ) -> None:
        if self._handler is None:
            await interaction.response.send_message("Handler is not configured.")
            return
        await interaction.response.defer(thinking=True, ephemeral=ephemeral)
        await self._record_interaction(interaction)
        is_private = isinstance(interaction.channel, discord.DMChannel)
        metadata = dict(extra or {})
        metadata.update(
            {
                "is_private": is_private,
                "external_channel_id": str(interaction.channel_id) if interaction.channel_id is not None else "",
                "guild_id": str(interaction.guild_id) if interaction.guild_id is not None else None,
            }
        )
        envelope = MessageEnvelope(
            message_id=str(interaction.id),
            channel_id=str(interaction.channel_id),
            user_id=str(interaction.user.id),
            timestamp=datetime.utcnow(),
            text="",
            attachments=[],
            origin="discord",
            command=command,
            metadata=metadata,
        )
        await self._handler(envelope)
        ephemeral_response = envelope.metadata.get("ephemeral_response")
        if ephemeral_response:
            await interaction.followup.send(str(ephemeral_response), ephemeral=True)
            return
        if envelope.metadata.get("suppress_ack"):
            return
        if interaction.response.is_done():
            await interaction.followup.send("Command received.")

    async def _record_user_channel(self, message: discord.Message, is_private: bool) -> None:
        display_name = getattr(message.author, "display_name", None) or message.author.name
        username = message.author.name
        if is_private:
            channel_name = f"@{display_name}"
            kind = "dm"
            guild_id = None
            guild_name = None
        else:
            channel_name = getattr(message.channel, "name", None) or str(message.channel.id)
            kind = "text"
            guild_id = str(message.guild.id) if message.guild else None
            guild_name = message.guild.name if message.guild else None
        avatar_url = message.author.display_avatar.url if message.author.display_avatar else None
        async with SessionLocal() as session:
            repo = Repository(session)
            await repo.upsert_user_profile(str(message.author.id), display_name, username, avatar_url)
            await repo.upsert_channel(
                transport_channel_id=str(message.channel.id),
                name=channel_name,
                kind=kind,
                guild_id=guild_id,
                guild_name=guild_name,
            )

    async def _record_interaction(self, interaction: discord.Interaction) -> None:
        display_name = getattr(interaction.user, "display_name", None) or interaction.user.name
        username = interaction.user.name
        is_private = isinstance(interaction.channel, discord.DMChannel)
        if is_private:
            channel_name = f"@{display_name}"
            kind = "dm"
            guild_id = None
            guild_name = None
        else:
            channel_name = getattr(interaction.channel, "name", None) or str(interaction.channel_id)
            kind = "text"
            guild_id = str(interaction.guild_id) if interaction.guild_id is not None else None
            guild_name = interaction.guild.name if interaction.guild is not None else None
        avatar_url = interaction.user.display_avatar.url if interaction.user.display_avatar else None
        async with SessionLocal() as session:
            repo = Repository(session)
            await repo.upsert_user_profile(str(interaction.user.id), display_name, username, avatar_url)
            if interaction.channel_id is not None:
                await repo.upsert_channel(
                    transport_channel_id=str(interaction.channel_id),
                    name=channel_name,
                    kind=kind,
                    guild_id=guild_id,
                    guild_name=guild_name,
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
