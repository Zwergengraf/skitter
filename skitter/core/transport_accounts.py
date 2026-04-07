from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime

from ..data.models import AgentProfile, TransportAccount, TransportSurfaceBinding
from ..data.repositories import Repository
from .config import settings

DEFAULT_DISCORD_ACCOUNT_KEY = "discord:default"
SURFACE_MODE_MENTION_ONLY = "mention_only"
SURFACE_MODE_ALL_MESSAGES = "all_messages"


def transport_surface_kind(origin: str) -> str:
    normalized = str(origin or "").strip().lower() or "unknown"
    return f"{normalized}_channel"


def discord_surface_kind() -> str:
    return transport_surface_kind("discord")


def explicit_transport_account_key(transport: str, agent_profile_id: str) -> str:
    normalized_transport = str(transport or "").strip().lower() or "transport"
    return f"{normalized_transport}:profile:{agent_profile_id}"


def transport_secret_name(transport: str, agent_profile_id: str) -> str:
    base = explicit_transport_account_key(transport, agent_profile_id)
    safe = re.sub(r"[^a-zA-Z0-9_.-]+", "_", base).strip("._-") or "transport_account"
    return f"{safe}.token"


def credential_fingerprint(value: str) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()


def is_shared_default_account_key(account_key: str | None) -> bool:
    return str(account_key or "").strip() == DEFAULT_DISCORD_ACCOUNT_KEY


@dataclass(slots=True)
class RuntimeTransportAccount:
    account_key: str
    transport: str
    user_id: str | None
    agent_profile_id: str | None
    display_name: str
    enabled: bool
    status: str
    is_shared_default: bool = False
    credential_secret_name: str | None = None
    external_account_id: str | None = None
    external_label: str | None = None
    last_seen_at: datetime | None = None
    last_error: str | None = None
    meta: dict | None = None
    id: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


def transport_display_name(transport: str, profile_name: str | None = None) -> str:
    label = str(transport or "").strip().title() or "Transport"
    if profile_name:
        return f"{profile_name} {label}"
    return label


def runtime_transport_account_from_row(row: TransportAccount) -> RuntimeTransportAccount:
    return RuntimeTransportAccount(
        id=row.id,
        account_key=row.account_key,
        transport=row.transport,
        user_id=row.user_id,
        agent_profile_id=row.agent_profile_id,
        display_name=row.display_name or transport_display_name(row.transport),
        enabled=bool(row.enabled),
        status=str(row.status or "offline"),
        is_shared_default=False,
        credential_secret_name=row.credential_secret_name,
        external_account_id=row.external_account_id,
        external_label=row.external_label,
        last_seen_at=row.last_seen_at,
        last_error=row.last_error,
        meta=dict(row.meta or {}),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def shared_default_discord_account() -> RuntimeTransportAccount | None:
    if not settings.discord_enabled or not str(settings.discord_token or "").strip():
        return None
    return RuntimeTransportAccount(
        id=None,
        account_key=DEFAULT_DISCORD_ACCOUNT_KEY,
        transport="discord",
        user_id=None,
        agent_profile_id=None,
        display_name="Shared Default Discord Bot",
        enabled=True,
        status="configured",
        is_shared_default=True,
        credential_secret_name=None,
        external_account_id=None,
        external_label=None,
        last_seen_at=None,
        last_error=None,
        meta={},
        created_at=None,
        updated_at=None,
    )


def serialize_transport_account(
    account: RuntimeTransportAccount,
    *,
    agent_profile_slug: str | None = None,
) -> dict[str, object]:
    return {
        "id": account.id,
        "account_key": account.account_key,
        "transport": account.transport,
        "user_id": account.user_id,
        "agent_profile_id": account.agent_profile_id,
        "agent_profile_slug": agent_profile_slug,
        "display_name": account.display_name,
        "enabled": bool(account.enabled),
        "status": account.status,
        "is_shared_default": bool(account.is_shared_default),
        "external_account_id": account.external_account_id,
        "external_label": account.external_label,
        "last_seen_at": account.last_seen_at.isoformat() if account.last_seen_at else None,
        "last_error": account.last_error,
        "created_at": account.created_at.isoformat() if account.created_at else None,
        "updated_at": account.updated_at.isoformat() if account.updated_at else None,
    }


def serialize_transport_binding(
    binding: TransportSurfaceBinding,
    *,
    agent_profile_slug: str | None = None,
) -> dict[str, object]:
    return {
        "id": binding.id,
        "transport_account_key": binding.transport_account_key,
        "user_id": binding.user_id,
        "agent_profile_id": binding.agent_profile_id,
        "agent_profile_slug": agent_profile_slug,
        "origin": binding.origin,
        "surface_kind": binding.surface_kind,
        "surface_id": binding.surface_id,
        "mode": binding.mode,
        "enabled": bool(binding.enabled),
        "created_at": binding.created_at.isoformat(),
        "updated_at": binding.updated_at.isoformat(),
    }


class TransportAccountService:
    async def list_accounts(
        self,
        repo: Repository,
        *,
        user_id: str | None = None,
        agent_profile_id: str | None = None,
        transport: str | None = None,
    ) -> list[RuntimeTransportAccount]:
        rows = await repo.list_transport_accounts(
            user_id=user_id,
            agent_profile_id=agent_profile_id,
            transport=transport,
        )
        accounts = [runtime_transport_account_from_row(row) for row in rows]
        normalized_transport = str(transport or "").strip().lower()
        if not normalized_transport or normalized_transport == "discord":
            shared_default = shared_default_discord_account()
            if shared_default is not None:
                accounts.insert(0, shared_default)
        return accounts

    async def get_account(
        self,
        repo: Repository,
        *,
        account_key: str | None,
    ) -> RuntimeTransportAccount | None:
        if is_shared_default_account_key(account_key):
            return shared_default_discord_account()
        row = await repo.get_transport_account_by_key(str(account_key or "").strip())
        if row is None:
            return None
        return runtime_transport_account_from_row(row)

    async def get_explicit_account_for_profile(
        self,
        repo: Repository,
        *,
        agent_profile_id: str,
        transport: str,
    ) -> TransportAccount | None:
        if not hasattr(repo, "get_transport_account_for_profile"):
            return None
        return await repo.get_transport_account_for_profile(agent_profile_id, transport)

    async def has_explicit_account_for_profile(
        self,
        repo: Repository,
        *,
        agent_profile_id: str,
        transport: str,
    ) -> bool:
        return await self.get_explicit_account_for_profile(
            repo,
            agent_profile_id=agent_profile_id,
            transport=transport,
        ) is not None

    async def list_explicit_accounts_by_profile(
        self,
        repo: Repository,
        *,
        user_id: str,
        transport: str,
    ) -> dict[str, RuntimeTransportAccount]:
        if not hasattr(repo, "list_transport_accounts"):
            return {}
        rows = await repo.list_transport_accounts(user_id=user_id, transport=transport)
        return {row.agent_profile_id: runtime_transport_account_from_row(row) for row in rows}

    async def validate_explicit_token(
        self,
        repo: Repository,
        *,
        transport: str,
        token: str,
        ignore_account_key: str | None = None,
    ) -> str:
        cleaned = str(token or "").strip()
        if not cleaned:
            raise ValueError("A transport token is required.")
        fingerprint = credential_fingerprint(cleaned)
        if transport == "discord":
            default_token = str(settings.discord_token or "").strip()
            if default_token and credential_fingerprint(default_token) == fingerprint:
                raise ValueError("This token matches the shared default Discord bot token.")
        existing = await repo.get_transport_account_by_fingerprint(transport, fingerprint)
        if existing is not None and existing.account_key != str(ignore_account_key or "").strip():
            raise ValueError("This transport token is already attached to another account.")
        return fingerprint

    async def resolve_transport_account_for_profile(
        self,
        repo: Repository,
        *,
        profile: AgentProfile,
        transport: str,
    ) -> RuntimeTransportAccount | None:
        explicit = await repo.get_transport_account_for_profile(profile.id, transport)
        if explicit is not None and explicit.enabled:
            return runtime_transport_account_from_row(explicit)
        if transport == "discord":
            return shared_default_discord_account()
        return None

    async def resolve_shared_default_dm_profile(
        self,
        repo: Repository,
        *,
        user_id: str,
        channel_id: str,
        origin: str = "discord",
        transport_account_key: str = DEFAULT_DISCORD_ACCOUNT_KEY,
    ) -> tuple[AgentProfile | None, str | None]:
        override = await repo.get_surface_profile_override(
            user_id=user_id,
            origin=origin,
            transport_account_key=transport_account_key,
            surface_kind=discord_surface_kind(),
            surface_id=channel_id,
        )
        if override is not None:
            profile = await repo.get_agent_profile(override.agent_profile_id)
            if (
                profile is not None
                and profile.user_id == user_id
                and profile.status != "archived"
                and not await self.has_explicit_account_for_profile(
                    repo,
                    agent_profile_id=profile.id,
                    transport="discord",
                )
            ):
                return profile, None

        default_profile = await repo.get_default_agent_profile(user_id)
        if (
            default_profile is not None
            and default_profile.status != "archived"
            and not await self.has_explicit_account_for_profile(
                repo,
                agent_profile_id=default_profile.id,
                transport="discord",
            )
        ):
            return default_profile, None

        profiles = await repo.list_agent_profiles(user_id, include_archived=False)
        for profile in profiles:
            if await self.has_explicit_account_for_profile(
                repo,
                agent_profile_id=profile.id,
                transport="discord",
            ):
                continue
            return profile, (
                "Your default profile uses a dedicated Discord bot, so the shared default bot switched to "
                f"`{profile.slug}` instead."
            )
        return None, (
            "No profile is available on the shared default Discord bot. Use your dedicated bot or create a profile "
            "without a dedicated Discord override."
        )


transport_account_service = TransportAccountService()
