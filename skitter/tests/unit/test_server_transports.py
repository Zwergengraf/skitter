from __future__ import annotations

from types import SimpleNamespace

import pytest

from skitter.server import _load_transport_account_token


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
