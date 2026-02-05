from __future__ import annotations

from fastapi import APIRouter, Depends, Query

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
    repo: Repository = Depends(get_repo),
    limit: int = Query(default=200, ge=1, le=500),
) -> list[ChannelListItem]:
    channels = await repo.list_channels(limit=limit)
    return [
        ChannelListItem(
            id=channel.transport_channel_id,
            name=channel.name,
            kind=channel.kind,
            label=_label(channel.kind, channel.name),
            guild_name=channel.guild_name,
        )
        for channel in channels
    ]
