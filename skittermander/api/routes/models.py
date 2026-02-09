from __future__ import annotations

from fastapi import APIRouter

from ..schemas import ModelOut
from ...core.llm import list_models

router = APIRouter(prefix="/v1/models", tags=["models"])


@router.get("", response_model=list[ModelOut])
async def get_models() -> list[ModelOut]:
    return [ModelOut(name=model.name, model=model.model) for model in list_models()]
