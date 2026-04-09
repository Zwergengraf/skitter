from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from ..authz import require_admin, resolve_target_user_id
from ..deps import get_repo
from ..schemas import (
    ChannelListItem,
    TransportAccountCreateRequest,
    TransportAccountOut,
    TransportAccountUpdateRequest,
    TransportSurfaceBindingCreateRequest,
    TransportSurfaceBindingOut,
    TransportSurfaceBindingUpdateRequest,
)
from ...core.profile_service import profile_service
from ...core.secrets import SecretsManager
from ...core.transport_accounts import (
    DEFAULT_DISCORD_ACCOUNT_KEY,
    explicit_transport_account_key,
    runtime_transport_account_from_row,
    serialize_transport_account,
    serialize_transport_binding,
    transport_account_service,
    transport_display_name,
    transport_secret_name,
)
from ...data.repositories import Repository

router = APIRouter(prefix="/v1/transport-accounts", tags=["transport-accounts"])


def _label(kind: str, name: str) -> str:
    if kind == "dm":
        return f"DM: {name}"
    if name.startswith("#"):
        return name
    return f"#{name}"


def _secrets_manager() -> SecretsManager:
    manager = SecretsManager()
    manager.ensure_ready()
    return manager


def _overlay_runtime_state(request: Request, account_data: dict[str, object]) -> dict[str, object]:
    states = {}
    transport_manager = getattr(request.app.state, "transport_manager", None)
    if transport_manager is not None and hasattr(transport_manager, "snapshot_states"):
        states = transport_manager.snapshot_states()
    state = states.get(str(account_data.get("account_key") or "").strip()) or {}
    if not state:
        return account_data
    merged = dict(account_data)
    for key in ("status", "last_error", "external_account_id", "external_label", "last_seen_at"):
        value = state.get(key)
        if value is None:
            continue
        if key == "last_seen_at" and isinstance(value, datetime):
            merged[key] = value.isoformat()
        else:
            merged[key] = value
    return merged


async def _reconcile_transports(request: Request) -> None:
    reconcile = getattr(request.app.state, "reconcile_transports", None)
    if reconcile is not None:
        await reconcile()


async def _profile_slug_map(repo: Repository, user_id: str) -> dict[str, str]:
    rows = await repo.list_agent_profiles(user_id, include_archived=True)
    return {row.id: row.slug for row in rows}


@router.get("", response_model=list[TransportAccountOut])
async def list_transport_accounts(
    request: Request,
    repo: Repository = Depends(get_repo),
    user_id: str | None = Query(default=None),
    agent_profile_id: str | None = Query(default=None),
    transport: str | None = Query(default=None),
) -> list[TransportAccountOut]:
    require_admin(request)
    target_user_id = resolve_target_user_id(request, user_id)
    accounts = await transport_account_service.list_accounts(
        repo,
        user_id=target_user_id,
        agent_profile_id=agent_profile_id,
        transport=transport,
    )
    slug_map = await _profile_slug_map(repo, target_user_id) if target_user_id else {}
    items: list[TransportAccountOut] = []
    for account in accounts:
        data = serialize_transport_account(
            account,
            agent_profile_slug=slug_map.get(str(account.agent_profile_id or "").strip()),
        )
        items.append(TransportAccountOut(**_overlay_runtime_state(request, data)))
    return items


@router.post("", response_model=TransportAccountOut)
async def create_transport_account(
    payload: TransportAccountCreateRequest,
    request: Request,
    repo: Repository = Depends(get_repo),
) -> TransportAccountOut:
    require_admin(request)
    target_user_id = resolve_target_user_id(request, payload.user_id)
    transport = str(payload.transport or "").strip().lower() or "discord"
    if transport != "discord":
        raise HTTPException(status_code=400, detail="Only Discord transport overrides are supported right now.")
    profile = await profile_service.resolve_profile(
        repo,
        target_user_id,
        agent_profile_id=payload.agent_profile_id,
    )
    account_key = explicit_transport_account_key(transport, profile.id)
    existing = await repo.get_transport_account_by_key(account_key)
    if existing is not None:
        raise HTTPException(status_code=400, detail="This profile already has a dedicated transport account.")
    try:
        fingerprint = await transport_account_service.validate_explicit_token(
            repo,
            transport=transport,
            token=payload.credential_value,
        )
        secret_name = transport_secret_name(transport, profile.id)
        manager = _secrets_manager()
        encrypted = manager.encrypt(payload.credential_value)
        await repo.upsert_secret(profile.user_id, secret_name, encrypted, agent_profile_id=profile.id)
        row = await repo.create_transport_account(
            account_key=account_key,
            user_id=profile.user_id,
            agent_profile_id=profile.id,
            transport=transport,
            display_name=str(payload.display_name or "").strip() or transport_display_name(transport, profile.name),
            enabled=bool(payload.enabled),
            status="configured",
            credential_secret_name=secret_name,
            credential_fingerprint=fingerprint,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc) or "Invalid transport account") from exc
    await _reconcile_transports(request)
    return TransportAccountOut(
        **serialize_transport_account(runtime_transport_account_from_row(row), agent_profile_slug=profile.slug)
    )


@router.patch("/{account_key}", response_model=TransportAccountOut)
async def update_transport_account(
    account_key: str,
    payload: TransportAccountUpdateRequest,
    request: Request,
    repo: Repository = Depends(get_repo),
) -> TransportAccountOut:
    require_admin(request)
    row = await repo.get_transport_account_by_key(account_key)
    if row is None:
        raise HTTPException(status_code=404, detail="Transport account not found")
    updates: dict[str, object] = {}
    if payload.display_name is not None:
        updates["display_name"] = str(payload.display_name or "").strip() or transport_display_name(row.transport)
    if payload.enabled is not None:
        updates["enabled"] = bool(payload.enabled)
    if payload.credential_value is not None:
        try:
            fingerprint = await transport_account_service.validate_explicit_token(
                repo,
                transport=row.transport,
                token=payload.credential_value,
                ignore_account_key=row.account_key,
            )
            manager = _secrets_manager()
            encrypted = manager.encrypt(payload.credential_value)
            await repo.upsert_secret(
                row.user_id,
                row.credential_secret_name,
                encrypted,
                agent_profile_id=row.agent_profile_id,
            )
            updates["credential_fingerprint"] = fingerprint
            updates["status"] = "configured"
            updates["last_error"] = None
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc) or "Invalid transport account") from exc
    updated = await repo.update_transport_account(account_key, **updates)
    if updated is None:
        raise HTTPException(status_code=404, detail="Transport account not found")
    profile = await repo.get_agent_profile(updated.agent_profile_id)
    await _reconcile_transports(request)
    return TransportAccountOut(
        **serialize_transport_account(
            runtime_transport_account_from_row(updated),
            agent_profile_slug=getattr(profile, "slug", None),
        )
    )


@router.delete("/{account_key}")
async def delete_transport_account(
    account_key: str,
    request: Request,
    repo: Repository = Depends(get_repo),
) -> dict:
    require_admin(request)
    if account_key == DEFAULT_DISCORD_ACCOUNT_KEY:
        raise HTTPException(status_code=400, detail="The shared default Discord bot is configured in config.yaml.")
    row = await repo.get_transport_account_by_key(account_key)
    if row is None:
        raise HTTPException(status_code=404, detail="Transport account not found")
    deleted = await repo.delete_transport_account(account_key)
    if row.credential_secret_name:
        await repo.delete_secret(row.user_id, row.credential_secret_name, agent_profile_id=row.agent_profile_id)
    await _reconcile_transports(request)
    return {"account_key": account_key, "deleted": bool(deleted)}


@router.get("/{account_key}/surfaces", response_model=list[ChannelListItem])
async def list_transport_surfaces(
    account_key: str,
    request: Request,
    repo: Repository = Depends(get_repo),
    limit: int = Query(default=200, ge=1, le=500),
) -> list[ChannelListItem]:
    require_admin(request)
    account = await transport_account_service.get_account(repo, account_key=account_key)
    if account is None:
        raise HTTPException(status_code=404, detail="Transport account not found")
    channels = await repo.list_channels(
        limit=limit,
        origin=account.transport,
        transport_account_key=account.account_key,
    )
    return [
        ChannelListItem(
            id=channel.transport_channel_id,
            origin=channel.origin,
            transport_account_key=channel.transport_account_key,
            name=channel.name,
            kind=channel.kind,
            label=_label(channel.kind, channel.name),
            guild_name=channel.guild_name,
        )
        for channel in channels
    ]


@router.get("/{account_key}/bindings", response_model=list[TransportSurfaceBindingOut])
async def list_transport_bindings(
    account_key: str,
    request: Request,
    repo: Repository = Depends(get_repo),
) -> list[TransportSurfaceBindingOut]:
    require_admin(request)
    account = await transport_account_service.get_account(repo, account_key=account_key)
    if account is None:
        raise HTTPException(status_code=404, detail="Transport account not found")
    bindings = await repo.list_transport_surface_bindings(transport_account_key=account.account_key)
    slug_map = await _profile_slug_map(repo, bindings[0].user_id) if bindings else {}
    return [
        TransportSurfaceBindingOut(
            **serialize_transport_binding(
                binding,
                agent_profile_slug=slug_map.get(binding.agent_profile_id),
            )
        )
        for binding in bindings
    ]


async def _resolve_binding_profile(
    repo: Repository,
    *,
    account_key: str,
    transport: str,
    user_id: str,
    requested_profile_id: str | None,
) -> tuple[str, str]:
    account = await transport_account_service.get_account(repo, account_key=account_key)
    if account is None:
        raise HTTPException(status_code=404, detail="Transport account not found")
    if account.is_shared_default:
        if not requested_profile_id:
            raise HTTPException(status_code=400, detail="A target profile is required for the shared default account.")
        profile = await profile_service.resolve_profile(repo, user_id, agent_profile_id=requested_profile_id)
        if transport == "discord" and await transport_account_service.has_explicit_account_for_profile(
            repo,
            agent_profile_id=profile.id,
            transport="discord",
        ):
            raise HTTPException(
                status_code=400,
                detail="Profiles with dedicated Discord bots cannot be bound to the shared default Discord bot.",
            )
        return profile.id, profile.slug
    if requested_profile_id and requested_profile_id != account.agent_profile_id:
        raise HTTPException(status_code=400, detail="Dedicated transport accounts are pinned to their profile.")
    profile = await profile_service.resolve_profile(repo, user_id, agent_profile_id=account.agent_profile_id)
    return profile.id, profile.slug


@router.post("/bindings", response_model=TransportSurfaceBindingOut)
async def create_transport_binding(
    payload: TransportSurfaceBindingCreateRequest,
    request: Request,
    repo: Repository = Depends(get_repo),
) -> TransportSurfaceBindingOut:
    require_admin(request)
    target_user_id = resolve_target_user_id(request, payload.user_id)
    if str(payload.surface_kind or "").strip().lower() in {"dm", "discord_dm"}:
        raise HTTPException(status_code=400, detail="DMs do not require surface bindings.")
    account = await transport_account_service.get_account(repo, account_key=payload.transport_account_key)
    if account is None:
        raise HTTPException(status_code=404, detail="Transport account not found")
    agent_profile_id, agent_profile_slug = await _resolve_binding_profile(
        repo,
        account_key=payload.transport_account_key,
        transport=account.transport,
        user_id=target_user_id,
        requested_profile_id=payload.agent_profile_id,
    )
    binding = await repo.upsert_transport_surface_binding(
        transport_account_key=account.account_key,
        user_id=target_user_id,
        agent_profile_id=agent_profile_id,
        origin=str(payload.origin or account.transport).strip().lower() or account.transport,
        surface_kind=str(payload.surface_kind or "").strip(),
        surface_id=str(payload.surface_id or "").strip(),
        mode=str(payload.mode or "mention_only").strip() or "mention_only",
        enabled=bool(payload.enabled),
    )
    return TransportSurfaceBindingOut(
        **serialize_transport_binding(binding, agent_profile_slug=agent_profile_slug)
    )


@router.patch("/bindings/{binding_id}", response_model=TransportSurfaceBindingOut)
async def update_transport_binding(
    binding_id: str,
    payload: TransportSurfaceBindingUpdateRequest,
    request: Request,
    repo: Repository = Depends(get_repo),
) -> TransportSurfaceBindingOut:
    require_admin(request)
    binding = await repo.get_transport_surface_binding(binding_id)
    if binding is None:
        raise HTTPException(status_code=404, detail="Transport binding not found")
    agent_profile_id = binding.agent_profile_id
    agent_profile_slug = None
    if payload.agent_profile_id is not None:
        account = await transport_account_service.get_account(repo, account_key=binding.transport_account_key)
        if account is None:
            raise HTTPException(status_code=404, detail="Transport account not found")
        agent_profile_id, agent_profile_slug = await _resolve_binding_profile(
            repo,
            account_key=binding.transport_account_key,
            transport=account.transport,
            user_id=binding.user_id,
            requested_profile_id=payload.agent_profile_id,
        )
    updated = await repo.upsert_transport_surface_binding(
        transport_account_key=binding.transport_account_key,
        user_id=binding.user_id,
        agent_profile_id=agent_profile_id,
        origin=binding.origin,
        surface_kind=binding.surface_kind,
        surface_id=binding.surface_id,
        mode=str(payload.mode or binding.mode).strip() or binding.mode,
        enabled=binding.enabled if payload.enabled is None else bool(payload.enabled),
    )
    if agent_profile_slug is None:
        profile = await repo.get_agent_profile(updated.agent_profile_id)
        agent_profile_slug = getattr(profile, "slug", None)
    return TransportSurfaceBindingOut(
        **serialize_transport_binding(updated, agent_profile_slug=agent_profile_slug)
    )


@router.delete("/bindings/{binding_id}")
async def delete_transport_binding(
    binding_id: str,
    request: Request,
    repo: Repository = Depends(get_repo),
) -> dict:
    require_admin(request)
    deleted = await repo.delete_transport_surface_binding(binding_id)
    return {"id": binding_id, "deleted": deleted}
