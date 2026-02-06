from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ...core.secrets import SecretsManager
from ...data.db import SessionLocal
from ...data.repositories import Repository
from ..schemas import SecretCreate, SecretOut

router = APIRouter(prefix="/v1/secrets", tags=["secrets"])


def _require_secrets() -> SecretsManager:
    manager = SecretsManager()
    try:
        manager.ensure_ready()
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return manager


@router.get("", response_model=list[SecretOut])
async def list_secrets(user_id: str) -> list[SecretOut]:
    _require_secrets()
    async with SessionLocal() as session:
        repo = Repository(session)
        secrets = await repo.list_secrets(user_id)
    return [
        SecretOut(
            name=secret.name,
            created_at=secret.created_at,
            updated_at=secret.updated_at,
            last_used_at=secret.last_used_at,
        )
        for secret in secrets
    ]


@router.post("", response_model=SecretOut)
async def create_secret(payload: SecretCreate) -> SecretOut:
    manager = _require_secrets()
    encrypted = manager.encrypt(payload.value)
    async with SessionLocal() as session:
        repo = Repository(session)
        secret = await repo.upsert_secret(payload.user_id, payload.name, encrypted)
    return SecretOut(
        name=secret.name,
        created_at=secret.created_at,
        updated_at=secret.updated_at,
        last_used_at=secret.last_used_at,
    )


@router.put("/{name}", response_model=SecretOut)
async def update_secret(name: str, payload: SecretCreate) -> SecretOut:
    manager = _require_secrets()
    encrypted = manager.encrypt(payload.value)
    async with SessionLocal() as session:
        repo = Repository(session)
        secret = await repo.upsert_secret(payload.user_id, name, encrypted)
    return SecretOut(
        name=secret.name,
        created_at=secret.created_at,
        updated_at=secret.updated_at,
        last_used_at=secret.last_used_at,
    )


@router.delete("/{name}")
async def delete_secret(name: str, user_id: str) -> dict:
    _require_secrets()
    async with SessionLocal() as session:
        repo = Repository(session)
        deleted = await repo.delete_secret(user_id, name)
    return {"deleted": deleted}
