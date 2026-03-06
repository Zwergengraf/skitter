from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

from ..authz import require_admin
from ..schemas import MCPServerOut, MCPServersOut, MCPServerToggleRequest
from ...core import config as config_module
from ...core.config_schema import build_config_from_settings
from ...core.mcp import mcp_registry

router = APIRouter(prefix="/v1/mcp", tags=["mcp"])


def _config_path() -> Path:
    return Path(config_module.settings.config_path)


@router.get("/servers", response_model=MCPServersOut)
async def list_mcp_servers(request: Request) -> MCPServersOut:
    require_admin(request)
    servers = await mcp_registry.list_servers()
    items = [MCPServerOut(**row) for row in servers]
    return MCPServersOut(servers=items)


@router.put("/servers/{server_name}", response_model=MCPServersOut)
async def toggle_mcp_server(
    server_name: str,
    payload: MCPServerToggleRequest,
    request: Request,
) -> MCPServersOut:
    require_admin(request)
    target = (server_name or "").strip().lower()
    if not target:
        raise HTTPException(status_code=400, detail="server_name is required")

    current = list(getattr(config_module.settings, "mcp_servers", []) or [])
    updated: list[dict] = []
    found = False
    for server in current:
        data = server.model_dump()
        name_key = str(data.get("name") or "").strip().lower()
        if name_key == target:
            data["enabled"] = bool(payload.enabled)
            found = True
        updated.append(data)

    if not found:
        raise HTTPException(status_code=404, detail=f"MCP server not found: {server_name}")

    try:
        validated = config_module.apply_settings_update({"mcp_servers": updated})
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    runtime = getattr(request.app.state, "runtime", None)
    if runtime is not None and hasattr(runtime, "refresh_model_configuration"):
        runtime.refresh_model_configuration()

    await mcp_registry.sync()

    config_path = _config_path()
    try:
        config_module._write_yaml_config(config_path, build_config_from_settings(validated))
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Failed to write config: {exc}") from exc

    servers = await mcp_registry.list_servers()
    items = [MCPServerOut(**row) for row in servers]
    return MCPServersOut(servers=items)
