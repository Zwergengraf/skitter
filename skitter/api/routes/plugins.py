from __future__ import annotations

from fastapi import APIRouter, Request

from ..authz import require_admin

router = APIRouter(prefix="/v1/plugins", tags=["plugins"])


@router.get("")
async def list_plugins(request: Request) -> dict:
    require_admin(request)
    registry = getattr(request.app.state, "plugin_registry", None)
    if registry is None:
        return {"plugins": [], "hooks": {}, "memory_providers": [], "diagnostics": []}
    return registry.snapshot()
