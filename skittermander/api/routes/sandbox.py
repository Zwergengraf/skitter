from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path

from fastapi import APIRouter, Request

from ..authz import require_admin
from ..schemas import SandboxContainerOut, SandboxStatusOut, SandboxWorkspaceOut
from ...core.workspace import users_root
from ...tools.sandbox_manager import sandbox_manager

router = APIRouter(prefix="/v1/sandbox", tags=["sandbox"])


def _human_bytes(value: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(value)
    unit = units[0]
    for next_unit in units[1:]:
        if size < 1024:
            break
        size /= 1024
        unit = next_unit
    return f"{size:.1f} {unit}"


def _dir_size(path: Path) -> int:
    total = 0
    for root, _, files in os.walk(path):
        for name in files:
            try:
                total += (Path(root) / name).stat().st_size
            except OSError:
                continue
    return total


@router.get("", response_model=SandboxStatusOut)
async def sandbox_status(request: Request) -> SandboxStatusOut:
    require_admin(request)
    workspace_entries: list[SandboxWorkspaceOut] = []
    total_bytes = 0
    root = users_root()
    if root.exists():
        for child in sorted(root.iterdir()):
            if not child.is_dir():
                continue
            size = _dir_size(child)
            total_bytes += size
            updated_at = datetime.utcfromtimestamp(child.stat().st_mtime)
            workspace_entries.append(
                SandboxWorkspaceOut(
                    user_id=child.name,
                    path=str(child),
                    size_bytes=size,
                    size_human=_human_bytes(size),
                    updated_at=updated_at,
                )
            )

    containers = []
    if sandbox_manager is not None:
        containers = await sandbox_manager.list_containers()

    return SandboxStatusOut(
        workspaces=workspace_entries,
        containers=[SandboxContainerOut(**item) for item in containers],
        total_workspace_bytes=total_bytes,
        total_workspace_human=_human_bytes(total_bytes),
    )
