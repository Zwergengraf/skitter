from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request

from ..authz import require_admin
from ..deps import get_repo
from ..schemas import ChannelListItem
from ...data.repositories import Repository

router = APIRouter(prefix="/v1/channels", tags=["channels"])


def _label(kind: str, name: str) -> str:
    if kind == "dm":
        return f"DM: {name}"
    if name.startswith("#"):
        return name
    return f"#{name}"


@router.get("", response_model=list[ChannelListItem])
async def list_channels(
    request: Request,
    repo: Repository = Depends(get_repo),
    origin: str | None = Query(default=None),
    transport_account_key: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=500),
) -> list[ChannelListItem]:
    require_admin(request)
    channels = await repo.list_channels(
        limit=limit,
        origin=origin,
        transport_account_key=transport_account_key,
    )
    return [
        ChannelListItem(
            id=channel.transport_channel_id,
            origin=channel.origin,
            transport_account_key=channel.transport_account_key,
            name=channel.name,
            kind=channel.kind,
            label=_label(channel.kind, channel.name),
            guild_id=channel.guild_id,
            guild_name=channel.guild_name,
        )
        for channel in channels
    ]
