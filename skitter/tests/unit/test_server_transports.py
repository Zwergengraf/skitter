from __future__ import annotations

from types import SimpleNamespace

import pytest

from skitter.core.models import MessageEnvelope
from skitter.server import _load_transport_account_token, _resolve_trusted_discord_sender_internal_user_id


class _Repo:
    def __init__(self, secret) -> None:
        self.secret = secret
        self.touched = None

    async def get_secret_exact(self, user_id: str, name: str, agent_profile_id: str | None = None):
        _ = user_id, name, agent_profile_id
        return self.secret

    async def touch_secret(self, secret) -> None:
        self.touched = secret


class _SecretsManager:
    def __init__(self) -> None:
        self.seen = None

    def decrypt(self, value: str) -> str:
        self.seen = value
        return "discord-bot-token"


@pytest.mark.asyncio
async def test_load_transport_account_token_decrypts_value_encrypted() -> None:
    secret = SimpleNamespace(value_encrypted="encrypted-token")
    row = SimpleNamespace(
        user_id="user-1",
        agent_profile_id="profile-1",
        credential_secret_name="discord.profile-1.token",
    )
    repo = _Repo(secret)
    manager = _SecretsManager()

    token, error = await _load_transport_account_token(
        repo=repo,
        row=row,
        secrets_manager=manager,
    )

    assert error is None
    assert token == "discord-bot-token"
    assert manager.seen == "encrypted-token"
    assert repo.touched is secret


class _TrustedSenderRepo:
    def __init__(self, row=None, row_by_key=None) -> None:
        self.row = row
        self.row_by_key = row_by_key or {}
        self.calls: list[tuple[str, str]] = []
        self.key_calls: list[str] = []

    async def get_transport_account_by_external_account_id(self, transport: str, external_account_id: str):
        self.calls.append((transport, external_account_id))
        return self.row

    async def get_transport_account_by_key(self, account_key: str):
        self.key_calls.append(account_key)
        return self.row_by_key.get(account_key)


@pytest.mark.asyncio
async def test_resolve_trusted_discord_sender_uses_tracked_metadata_first() -> None:
    repo = _TrustedSenderRepo()
    envelope = MessageEnvelope(
        message_id="msg-1",
        channel_id="channel-1",
        user_id="discord-bot-1",
        timestamp=None,  # type: ignore[arg-type]
        text="hello",
        origin="discord",
        metadata={
            "sender_is_bot": True,
            "skitter_sender_internal_user_id": "user-1",
        },
    )

    resolved = await _resolve_trusted_discord_sender_internal_user_id(repo=repo, envelope=envelope)

    assert resolved == "user-1"
    assert repo.calls == []


@pytest.mark.asyncio
async def test_resolve_trusted_discord_sender_accepts_known_transport_bot() -> None:
    repo = _TrustedSenderRepo(
        SimpleNamespace(
            user_id="owner-1",
            agent_profile_id="profile-1",
            account_key="discord:profile:profile-1",
            enabled=True,
        )
    )
    envelope = MessageEnvelope(
        message_id="msg-2",
        channel_id="channel-1",
        user_id="discord-bot-2",
        timestamp=None,  # type: ignore[arg-type]
        text="hello",
        origin="discord",
        metadata={"sender_is_bot": True},
    )

    resolved = await _resolve_trusted_discord_sender_internal_user_id(repo=repo, envelope=envelope)

    assert resolved == "owner-1"
    assert envelope.metadata["skitter_sender_profile_id"] == "profile-1"
    assert envelope.metadata["skitter_transport_account_key"] == "discord:profile:profile-1"


@pytest.mark.asyncio
async def test_resolve_trusted_discord_sender_uses_runtime_state_fallback_for_active_bot() -> None:
    row = SimpleNamespace(
        user_id="owner-2",
        agent_profile_id="profile-2",
        account_key="discord:profile:profile-2",
        enabled=True,
    )
    repo = _TrustedSenderRepo(
        row=None,
        row_by_key={
            "discord:profile:profile-2": row,
        },
    )
    envelope = MessageEnvelope(
        message_id="msg-3",
        channel_id="channel-1",
        user_id="discord-bot-3",
        timestamp=None,  # type: ignore[arg-type]
        text="hello",
        origin="discord",
        metadata={"sender_is_bot": True},
    )

    resolved = await _resolve_trusted_discord_sender_internal_user_id(
        repo=repo,
        envelope=envelope,
        runtime_states={
            "discord:profile:profile-2": {
                "external_account_id": "discord-bot-3",
            }
        },
    )

    assert resolved == "owner-2"
    assert repo.key_calls == ["discord:profile:profile-2"]
    assert envelope.metadata["skitter_sender_profile_id"] == "profile-2"
    assert envelope.metadata["skitter_transport_account_key"] == "discord:profile:profile-2"


@pytest.mark.asyncio
async def test_resolve_trusted_discord_sender_marks_shared_default_bot_as_trusted() -> None:
    repo = _TrustedSenderRepo(row=None, row_by_key={})
    envelope = MessageEnvelope(
        message_id="msg-4",
        channel_id="channel-1",
        user_id="discord-bot-default",
        timestamp=None,  # type: ignore[arg-type]
        text="hello",
        origin="discord",
        metadata={"sender_is_bot": True},
    )

    resolved = await _resolve_trusted_discord_sender_internal_user_id(
        repo=repo,
        envelope=envelope,
        runtime_states={
            "discord:default": {
                "external_account_id": "discord-bot-default",
            }
        },
    )

    assert resolved is None
    assert envelope.metadata["trusted_transport_bot"] is True
    assert envelope.metadata["skitter_transport_account_key"] == "discord:default"
    assert repo.key_calls == []
