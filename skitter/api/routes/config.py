from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from ..authz import require_admin
from ..schemas import ConfigCategoryOut, ConfigFieldOut, ConfigResponse, ConfigUpdate
from ...core import config as config_module
from ...core.config_schema import CATEGORIES, FIELDS, build_config_from_settings

router = APIRouter(prefix="/v1/config", tags=["config"])


def _config_path() -> Path:
    return Path(config_module.settings.config_path)


def _build_response() -> ConfigResponse:
    data = build_config_from_settings(config_module.settings)
    try:
        providers = [provider.model_dump() for provider in getattr(config_module.settings, "providers", []) or []]
    except Exception:
        providers = data.get("providers") if isinstance(data.get("providers"), list) else []
    try:
        models = [model.model_dump(by_alias=True) for model in getattr(config_module.settings, "models", []) or []]
    except Exception:
        models = data.get("models") if isinstance(data.get("models"), list) else []
    try:
        mcp_servers = [server.model_dump() for server in getattr(config_module.settings, "mcp_servers", []) or []]
    except Exception:
        mcp_cfg = data.get("mcp") if isinstance(data.get("mcp"), dict) else {}
        mcp_servers = mcp_cfg.get("servers") if isinstance(mcp_cfg.get("servers"), list) else []

    sanitized_providers: list[dict[str, Any]] = []
    for item in providers:
        if not isinstance(item, dict):
            continue
        row = dict(item)
        row["api_key"] = ""
        sanitized_providers.append(row)

    categories = []
    for category_id, label in CATEGORIES.items():
        fields = []
        for spec in FIELDS:
            if spec.category != category_id:
                continue
            value = data
            for key in spec.path:
                if not isinstance(value, dict):
                    value = None
                    break
                value = value.get(key)
            if spec.secret:
                display_value = ""
            else:
                display_value = value
            fields.append(
                ConfigFieldOut(
                    key=spec.key,
                    label=spec.label,
                    type=spec.field_type,
                    value=display_value,
                    description=spec.description,
                    secret=spec.secret,
                    minimum=spec.minimum,
                    maximum=spec.maximum,
                    step=spec.step,
                )
            )
        categories.append(ConfigCategoryOut(id=category_id, label=label, fields=fields))
    return ConfigResponse(
        categories=categories,
        providers=sanitized_providers,
        models=[dict(item) for item in models if isinstance(item, dict)],
        mcp_servers=[dict(item) for item in mcp_servers if isinstance(item, dict)],
    )


@router.get("", response_model=ConfigResponse)
async def get_config(request: Request) -> ConfigResponse:
    require_admin(request)
    return _build_response()


@router.put("", response_model=ConfigResponse)
async def update_config(payload: ConfigUpdate, request: Request) -> ConfigResponse:
    require_admin(request)
    updates: dict[str, Any] = {}
    for spec in FIELDS:
        if spec.key not in payload.values:
            continue
        value = payload.values.get(spec.key)
        if spec.secret and (value is None or value == "" or value == "******" or value == "********"):
            continue
        if spec.field_type == "list":
            if isinstance(value, list):
                value = ",".join(str(item).strip() for item in value if str(item).strip())
            elif isinstance(value, str):
                value = ",".join([item.strip() for item in value.split(",") if item.strip()])
        updates[spec.key] = value

    current_provider_map = {
        str(provider.name or "").strip().lower(): provider.model_dump()
        for provider in getattr(config_module.settings, "providers", []) or []
        if str(provider.name or "").strip()
    }
    for extra_key in ("providers", "models", "mcp_servers"):
        if extra_key not in payload.values:
            continue
        value = payload.values.get(extra_key)
        if extra_key == "providers" and isinstance(value, list):
            merged_providers: list[dict[str, Any]] = []
            for item in value:
                if not isinstance(item, dict):
                    continue
                row = dict(item)
                name_key = str(row.get("name") or "").strip().lower()
                if name_key and not str(row.get("api_key") or "").strip():
                    existing = current_provider_map.get(name_key)
                    if existing is not None and str(existing.get("api_key") or "").strip():
                        row["api_key"] = existing["api_key"]
                merged_providers.append(row)
            updates[extra_key] = merged_providers
            continue
        updates[extra_key] = value
    try:
        validated = config_module.apply_settings_update(updates)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    runtime = getattr(request.app.state, "runtime", None)
    if runtime is not None and hasattr(runtime, "refresh_model_configuration"):
        runtime.refresh_model_configuration()

    config_path = _config_path()
    try:
        config_module._write_yaml_config(config_path, build_config_from_settings(validated))
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Failed to write config: {exc}") from exc
    return _build_response()
