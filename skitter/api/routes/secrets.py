from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from ..authz import require_admin
from ..deps import get_repo
from ..schemas import SecretCreate, SecretOut
from ...core.secrets import SecretsManager
from ...data.repositories import Repository

router = APIRouter(prefix="/v1/secrets", tags=["secrets"])


def _require_secrets() -> SecretsManager:
    manager = SecretsManager()
    try:
        manager.ensure_ready()
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return manager


@router.get("", response_model=list[SecretOut])
async def list_secrets(
    request: Request,
    repo: Repository = Depends(get_repo),
    user_id: str = Query(...),
    agent_profile_id: str | None = Query(default=None),
) -> list[SecretOut]:
    require_admin(request)
    _require_secrets()
    secrets = await repo.list_secrets(user_id, agent_profile_id=agent_profile_id)
    return [
        SecretOut(
            name=secret.name,
            agent_profile_id=secret.agent_profile_id,
            created_at=secret.created_at,
            updated_at=secret.updated_at,
            last_used_at=secret.last_used_at,
        )
        for secret in secrets
    ]


@router.post("", response_model=SecretOut)
async def create_secret(
    payload: SecretCreate,
    request: Request,
    repo: Repository = Depends(get_repo),
) -> SecretOut:
    require_admin(request)
    manager = _require_secrets()
    encrypted = manager.encrypt(payload.value)
    secret = await repo.upsert_secret(
        payload.user_id,
        payload.name,
        encrypted,
        agent_profile_id=payload.agent_profile_id,
    )
    return SecretOut(
        name=secret.name,
        agent_profile_id=secret.agent_profile_id,
        created_at=secret.created_at,
        updated_at=secret.updated_at,
        last_used_at=secret.last_used_at,
    )


@router.put("/{name}", response_model=SecretOut)
async def update_secret(
    name: str,
    payload: SecretCreate,
    request: Request,
    repo: Repository = Depends(get_repo),
) -> SecretOut:
    require_admin(request)
    manager = _require_secrets()
    encrypted = manager.encrypt(payload.value)
    secret = await repo.upsert_secret(
        payload.user_id,
        name,
        encrypted,
        agent_profile_id=payload.agent_profile_id,
    )
    return SecretOut(
        name=secret.name,
        agent_profile_id=secret.agent_profile_id,
        created_at=secret.created_at,
        updated_at=secret.updated_at,
        last_used_at=secret.last_used_at,
    )


@router.delete("/{name}")
async def delete_secret(
    name: str,
    request: Request,
    repo: Repository = Depends(get_repo),
    user_id: str = Query(...),
    agent_profile_id: str | None = Query(default=None),
) -> dict:
    require_admin(request)
    _require_secrets()
    deleted = await repo.delete_secret(user_id, name, agent_profile_id=agent_profile_id)
    return {"deleted": deleted}
