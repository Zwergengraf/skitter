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
    return ConfigResponse(categories=categories)


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
    try:
        validated = config_module.apply_settings_update(updates)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    config_path = _config_path()
    try:
        config_module._write_yaml_config(config_path, build_config_from_settings(validated))
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Failed to write config: {exc}") from exc
    return _build_response()
