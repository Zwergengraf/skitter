from __future__ import annotations

from types import SimpleNamespace

import pytest

from skitter.core import discord_mentions as mentions_module
from skitter.core.discord_mentions import DiscordMentionService


class _FakeSessionCtx:
    async def __aenter__(self) -> object:
        return object()

    async def __aexit__(self, exc_type, exc, tb) -> None:
        _ = exc_type, exc, tb
        return None


class _FakeRepo:
    def __init__(self, _session: object) -> None:
        pass

    async def list_users(self, limit: int = 500):
        _ = limit
        return [
            SimpleNamespace(
                display_name="Alice Example",
                transport_user_id="111",
                meta={"username": "alice"},
            ),
            SimpleNamespace(
                display_name="Bob Example",
                transport_user_id="222",
                meta={"username": "bob"},
            ),
        ]

    async def list_channels(self, origin: str, transport_account_key: str, limit: int = 500):
        _ = origin, transport_account_key, limit
        return [
            SimpleNamespace(
                kind="text",
                transport_channel_id="555",
                name="general",
                guild_id="42",
                guild_name="Guild One",
            ),
            SimpleNamespace(
                kind="text",
                transport_channel_id="666",
                name="ops-bots",
                guild_id="42",
                guild_name="Guild One",
            ),
            SimpleNamespace(
                kind="text",
                transport_channel_id="777",
                name="other-guild",
                guild_id="99",
                guild_name="Guild Two",
            ),
        ]


class _FakeRole:
    def __init__(self, role_id: int, name: str, *, is_default: bool = False) -> None:
        self.id = role_id
        self.name = name
        self._is_default = is_default
        self.mention = f"<@&{role_id}>"

    def is_default(self) -> bool:
        return self._is_default


class _FakeGuild:
    def __init__(self) -> None:
        self.roles = [
            _FakeRole(1, "@everyone", is_default=True),
            _FakeRole(77, "Moderators"),
            _FakeRole(88, "Bots"),
        ]


class _FakeDiscordTransport:
    def __init__(self) -> None:
        self.client = SimpleNamespace(get_guild=lambda guild_id: _FakeGuild() if guild_id == 42 else None)


class _FakeTransportManager:
    def get(self, account_key: str):
        _ = account_key
        return _FakeDiscordTransport()


@pytest.mark.asyncio
async def test_discord_mention_service_resolves_users(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mentions_module, "SessionLocal", lambda: _FakeSessionCtx())
    monkeypatch.setattr(mentions_module, "Repository", _FakeRepo)

    service = DiscordMentionService(_FakeTransportManager())
    matches = await service.resolve_mentions(account_key="discord:default", kind="user", query="alice")

    assert matches[0]["id"] == "111"
    assert matches[0]["mention"] == "<@111>"
    assert matches[0]["display_name"] == "Alice Example"

    direct = await service.resolve_mentions(account_key="discord:default", kind="user", query="<@222>")
    assert direct == [{"kind": "user", "id": "222", "label": "222", "mention": "<@222>"}]


@pytest.mark.asyncio
async def test_discord_mention_service_resolves_roles_and_channels(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mentions_module, "SessionLocal", lambda: _FakeSessionCtx())
    monkeypatch.setattr(mentions_module, "Repository", _FakeRepo)
    monkeypatch.setattr(mentions_module, "DiscordTransport", _FakeDiscordTransport)

    service = DiscordMentionService(_FakeTransportManager())

    role_matches = await service.resolve_mentions(
        account_key="discord:default",
        kind="role",
        query="mod",
        guild_id="42",
    )
    assert role_matches[0]["id"] == "77"
    assert role_matches[0]["mention"] == "<@&77>"

    channel_matches = await service.resolve_mentions(
        account_key="discord:default",
        kind="channel",
        query="ops",
        guild_id="42",
    )
    assert channel_matches[0]["id"] == "666"
    assert channel_matches[0]["mention"] == "<#666>"
    assert channel_matches[0]["guild_id"] == "42"
