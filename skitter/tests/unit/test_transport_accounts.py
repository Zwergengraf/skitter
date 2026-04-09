from __future__ import annotations

from types import SimpleNamespace

import pytest

from skitter.core.command_service import command_service
from skitter.core.transport_accounts import (
    DEFAULT_DISCORD_ACCOUNT_KEY,
    RuntimeTransportAccount,
    transport_account_service,
)
from skitter.core.config import settings


class _FingerprintRepo:
    async def get_transport_account_by_fingerprint(self, transport: str, fingerprint: str):
        _ = transport, fingerprint
        return None


class _SharedDefaultFallbackRepo:
    def __init__(self) -> None:
        self.default_profile = SimpleNamespace(
            id="profile-default",
            user_id="user-1",
            slug="default",
            name="Default",
            status="active",
        )
        self.fallback_profile = SimpleNamespace(
            id="profile-helper",
            user_id="user-1",
            slug="helper",
            name="Helper",
            status="active",
        )

    async def get_surface_profile_override(
        self,
        *,
        user_id: str,
        origin: str,
        transport_account_key: str,
        surface_kind: str,
        surface_id: str,
    ):
        _ = user_id, origin, transport_account_key, surface_kind, surface_id
        return None

    async def get_agent_profile(self, profile_id: str):
        if profile_id == self.default_profile.id:
            return self.default_profile
        if profile_id == self.fallback_profile.id:
            return self.fallback_profile
        return None

    async def get_default_agent_profile(self, user_id: str):
        return self.default_profile if user_id == "user-1" else None

    async def list_agent_profiles(self, user_id: str, include_archived: bool = False):
        _ = include_archived
        if user_id != "user-1":
            return []
        return [self.default_profile, self.fallback_profile]


@pytest.mark.asyncio
async def test_validate_explicit_token_rejects_shared_default_discord_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "discord_token", "shared-default-token")

    with pytest.raises(ValueError, match="shared default Discord bot token"):
        await transport_account_service.validate_explicit_token(
            _FingerprintRepo(),
            transport="discord",
            token="shared-default-token",
        )


@pytest.mark.asyncio
async def test_resolve_shared_default_dm_profile_falls_back_from_dedicated_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _SharedDefaultFallbackRepo()

    async def _has_explicit(repo_obj, *, agent_profile_id: str, transport: str) -> bool:
        _ = repo_obj, transport
        return agent_profile_id == "profile-default"

    monkeypatch.setattr(transport_account_service, "has_explicit_account_for_profile", _has_explicit)

    profile, notice = await transport_account_service.resolve_shared_default_dm_profile(
        repo,
        user_id="user-1",
        channel_id="dm-1",
        transport_account_key=DEFAULT_DISCORD_ACCOUNT_KEY,
    )

    assert profile is not None
    assert profile.id == "profile-helper"
    assert "shared default bot switched" in str(notice)


@pytest.mark.asyncio
async def test_profile_use_rejects_dedicated_profile_on_shared_default_dm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current_profile = SimpleNamespace(
        id="profile-default",
        slug="default",
        name="Default",
        status="active",
        user_id="user-1",
    )
    dedicated_profile = SimpleNamespace(
        id="profile-dedicated",
        slug="dedicated",
        name="Dedicated",
        status="active",
        user_id="user-1",
    )

    async def _ensure_default_profile(repo, user_id: str):
        _ = repo, user_id
        return current_profile

    async def _list_profiles(repo, user_id: str, include_archived: bool = False):
        _ = repo, user_id, include_archived
        return [current_profile, dedicated_profile]

    async def _resolve_profile(repo, user_id: str, **kwargs):
        _ = repo, user_id
        slug = kwargs.get("agent_profile_slug")
        if slug == "dedicated":
            return dedicated_profile
        return current_profile

    async def _explicit_accounts(repo, *, user_id: str, transport: str):
        _ = repo, user_id, transport
        return {
            dedicated_profile.id: RuntimeTransportAccount(
                account_key="discord:profile:profile-dedicated",
                transport="discord",
                user_id="user-1",
                agent_profile_id=dedicated_profile.id,
                display_name="Dedicated Discord",
                enabled=True,
                status="online",
            )
        }

    monkeypatch.setattr("skitter.core.command_service.profile_service.ensure_default_profile", _ensure_default_profile)
    monkeypatch.setattr("skitter.core.command_service.profile_service.list_profiles", _list_profiles)
    monkeypatch.setattr("skitter.core.command_service.profile_service.resolve_profile", _resolve_profile)
    monkeypatch.setattr(
        "skitter.core.command_service.transport_account_service.list_explicit_accounts_by_profile",
        _explicit_accounts,
    )

    with pytest.raises(RuntimeError, match="dedicated Discord bot"):
        await command_service._execute_profile_command(
            repo=SimpleNamespace(),
            user_id="user-1",
            origin="discord",
            surface_id="dm-1",
            persist_surface_profile=True,
            current_profile=current_profile,
            raw="use dedicated",
            transport_account_key=DEFAULT_DISCORD_ACCOUNT_KEY,
            surface_is_private=True,
        )


@pytest.mark.asyncio
async def test_profile_use_rejects_in_guild_channel_and_dedicated_bot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current_profile = SimpleNamespace(
        id="profile-default",
        slug="default",
        name="Default",
        status="active",
        user_id="user-1",
    )

    async def _ensure_default_profile(repo, user_id: str):
        _ = repo, user_id
        return current_profile

    async def _list_profiles(repo, user_id: str, include_archived: bool = False):
        _ = repo, user_id, include_archived
        return [current_profile]

    async def _resolve_profile(repo, user_id: str, **kwargs):
        _ = repo, user_id, kwargs
        return current_profile

    monkeypatch.setattr("skitter.core.command_service.profile_service.ensure_default_profile", _ensure_default_profile)
    monkeypatch.setattr("skitter.core.command_service.profile_service.list_profiles", _list_profiles)
    monkeypatch.setattr("skitter.core.command_service.profile_service.resolve_profile", _resolve_profile)
    async def _no_explicit_accounts(repo, *, user_id: str, transport: str):
        _ = repo, user_id, transport
        return {}

    monkeypatch.setattr(
        "skitter.core.command_service.transport_account_service.list_explicit_accounts_by_profile",
        _no_explicit_accounts,
    )

    with pytest.raises(RuntimeError, match="bound by admin"):
        await command_service._execute_profile_command(
            repo=SimpleNamespace(),
            user_id="user-1",
            origin="discord",
            surface_id="guild-1",
            persist_surface_profile=True,
            current_profile=current_profile,
            raw="use default",
            transport_account_key=DEFAULT_DISCORD_ACCOUNT_KEY,
            surface_is_private=False,
        )

    with pytest.raises(RuntimeError, match="pinned to profile"):
        await command_service._execute_profile_command(
            repo=SimpleNamespace(),
            user_id="user-1",
            origin="discord",
            surface_id="dm-1",
            persist_surface_profile=True,
            current_profile=current_profile,
            raw="use default",
            transport_account_key="discord:profile:profile-default",
            surface_is_private=True,
        )
