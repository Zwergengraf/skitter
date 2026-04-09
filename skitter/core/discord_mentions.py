from __future__ import annotations

import re
from typing import Any

from ..data.db import SessionLocal
from ..data.repositories import Repository
from ..transports.discord import DiscordTransport
from ..transports.manager import TransportManager

_USER_MENTION_RE = re.compile(r"<@!?(\d+)>")
_ROLE_MENTION_RE = re.compile(r"<@&(\d+)>")
_CHANNEL_MENTION_RE = re.compile(r"<#(\d+)>")


def _normalize_query(value: str | None) -> str:
    return str(value or "").strip()


def _search_score(query: str, *candidates: str | None) -> int:
    cleaned = query.casefold()
    best = -1
    for candidate in candidates:
        value = str(candidate or "").strip()
        if not value:
            continue
        lowered = value.casefold()
        if lowered == cleaned:
            return 300
        if lowered.startswith(cleaned):
            best = max(best, 200)
        elif cleaned in lowered:
            best = max(best, 100)
    return best


def _match_mention_or_id(query: str, kind: str) -> str | None:
    if query.isdigit():
        return query
    matcher = {
        "user": _USER_MENTION_RE,
        "role": _ROLE_MENTION_RE,
        "channel": _CHANNEL_MENTION_RE,
    }.get(kind)
    if matcher is None:
        return None
    match = matcher.fullmatch(query)
    if match:
        return match.group(1)
    return None


class DiscordMentionService:
    def __init__(self, transport_manager: TransportManager) -> None:
        self._transport_manager = transport_manager

    def _discord_transport(self, account_key: str) -> DiscordTransport:
        transport = self._transport_manager.get(account_key)
        if transport is None or not isinstance(transport, DiscordTransport):
            raise RuntimeError(f"Discord transport `{account_key}` is not available.")
        return transport

    async def resolve_mentions(
        self,
        *,
        account_key: str,
        kind: str,
        query: str,
        guild_id: str | None = None,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        cleaned_kind = _normalize_query(kind).lower() or "user"
        cleaned_query = _normalize_query(query)
        if cleaned_kind not in {"user", "role", "channel"}:
            raise RuntimeError("kind must be one of: user, role, channel")
        if not cleaned_query:
            raise RuntimeError("query is required")
        if cleaned_kind == "user":
            return await self._resolve_users(account_key, cleaned_query, limit=max(1, min(limit, 20)))
        if cleaned_kind == "role":
            return await self._resolve_roles(
                account_key,
                cleaned_query,
                guild_id=_normalize_query(guild_id) or None,
                limit=max(1, min(limit, 20)),
            )
        return await self._resolve_channels(
            account_key,
            cleaned_query,
            guild_id=_normalize_query(guild_id) or None,
            limit=max(1, min(limit, 20)),
        )

    async def _resolve_users(self, account_key: str, query: str, *, limit: int) -> list[dict[str, Any]]:
        direct_id = _match_mention_or_id(query, "user")
        if direct_id:
            return [
                {
                    "kind": "user",
                    "id": direct_id,
                    "label": direct_id,
                    "mention": f"<@{direct_id}>",
                }
            ]
        async with SessionLocal() as session:
            repo = Repository(session)
            users = await repo.list_users(limit=500)
        scored: list[tuple[int, dict[str, Any]]] = []
        for user in users:
            meta = dict(user.meta or {})
            display_name = str(user.display_name or meta.get("display_name") or "").strip()
            username = str(meta.get("username") or "").strip()
            transport_user_id = str(user.transport_user_id or "").strip()
            score = _search_score(query, display_name, username, transport_user_id)
            if score < 0:
                continue
            label = display_name or username or transport_user_id
            scored.append(
                (
                    score,
                    {
                        "kind": "user",
                        "id": transport_user_id,
                        "label": label,
                        "mention": f"<@{transport_user_id}>",
                        "display_name": display_name or None,
                        "username": username or None,
                    },
                )
            )
        scored.sort(key=lambda item: (-item[0], str(item[1].get("label") or "").casefold(), str(item[1].get("id") or "")))
        return [item for _, item in scored[:limit]]

    async def _resolve_roles(
        self,
        account_key: str,
        query: str,
        *,
        guild_id: str | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        transport = self._discord_transport(account_key)
        guild_key = guild_id or ""
        if not guild_key:
            raise RuntimeError("guild_id is required to resolve Discord roles.")
        guild = transport.client.get_guild(int(guild_key))
        if guild is None:
            raise RuntimeError(f"Discord guild `{guild_key}` is not available on bot `{account_key}`.")
        direct_id = _match_mention_or_id(query, "role")
        matches: list[tuple[int, dict[str, Any]]] = []
        for role in guild.roles:
            if role.is_default():
                continue
            if direct_id and str(role.id) == direct_id:
                return [
                    {
                        "kind": "role",
                        "id": str(role.id),
                        "label": role.name,
                        "mention": role.mention,
                        "guild_id": guild_key,
                    }
                ]
            score = _search_score(query, role.name, str(role.id))
            if score < 0:
                continue
            matches.append(
                (
                    score,
                    {
                        "kind": "role",
                        "id": str(role.id),
                        "label": role.name,
                        "mention": role.mention,
                        "guild_id": guild_key,
                    },
                )
            )
        matches.sort(key=lambda item: (-item[0], str(item[1].get("label") or "").casefold(), str(item[1].get("id") or "")))
        return [item for _, item in matches[:limit]]

    async def _resolve_channels(
        self,
        account_key: str,
        query: str,
        *,
        guild_id: str | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        direct_id = _match_mention_or_id(query, "channel")
        async with SessionLocal() as session:
            repo = Repository(session)
            channels = await repo.list_channels(origin="discord", transport_account_key=account_key, limit=500)
        matches: list[tuple[int, dict[str, Any]]] = []
        for channel in channels:
            if channel.kind == "dm":
                continue
            if guild_id and str(channel.guild_id or "") != guild_id:
                continue
            if direct_id and str(channel.transport_channel_id) == direct_id:
                return [
                    {
                        "kind": "channel",
                        "id": str(channel.transport_channel_id),
                        "label": channel.name,
                        "mention": f"<#{channel.transport_channel_id}>",
                        "guild_id": channel.guild_id,
                        "guild_name": channel.guild_name,
                    }
                ]
            score = _search_score(query, channel.name, str(channel.transport_channel_id))
            if score < 0:
                continue
            matches.append(
                (
                    score,
                    {
                        "kind": "channel",
                        "id": str(channel.transport_channel_id),
                        "label": channel.name,
                        "mention": f"<#{channel.transport_channel_id}>",
                        "guild_id": channel.guild_id,
                        "guild_name": channel.guild_name,
                    },
                )
            )
        matches.sort(key=lambda item: (-item[0], str(item[1].get("label") or "").casefold(), str(item[1].get("id") or "")))
        return [item for _, item in matches[:limit]]
