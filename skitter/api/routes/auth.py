from __future__ import annotations

import secrets as stdlib_secrets
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from ..deps import get_repo
from ..schemas import (
    AuthBootstrapRequest,
    AuthPairCodeCreateRequest,
    AuthPairCodeOut,
    AuthPairCompleteRequest,
    AuthTokenOut,
    AuthUserOut,
)
from ..security import (
    AuthPrincipal,
    get_auth_principal,
    hash_secret,
    hash_pair_code,
    make_client_token,
    make_pair_code,
    require_user_principal,
    token_prefix,
    utcnow,
)
from ...core.config import settings
from ...data.repositories import Repository

router = APIRouter(prefix="/v1/auth", tags=["auth"])


def _user_out(user) -> AuthUserOut:
    display = (user.display_name or (user.meta or {}).get("display_name") or user.transport_user_id or "User").strip()
    return AuthUserOut(
        id=user.id,
        display_name=display,
        approved=bool(user.approved),
    )


def _validate_bootstrap_code(code: str) -> None:
    expected = settings.bootstrap_code.strip()
    if not expected:
        raise HTTPException(status_code=503, detail="Bootstrap auth is not configured on this server.")
    provided = (code or "").strip()
    if not provided or not stdlib_secrets.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="Invalid bootstrap code.")


async def _issue_token(
    repo: Repository,
    user,
    *,
    device_name: str | None,
    device_type: str | None,
    created_via: str,
) -> AuthTokenOut:
    raw_token = make_client_token()
    hashed = hash_secret(raw_token)
    await repo.create_auth_token(
        user_id=user.id,
        token_hash=hashed,
        token_prefix=token_prefix(raw_token),
        device_name=device_name,
        device_type=device_type,
        created_via=created_via,
        expires_at=None,
    )
    return AuthTokenOut(token=raw_token, user=_user_out(user))


@router.post("/bootstrap", response_model=AuthTokenOut)
async def bootstrap_auth(
    payload: AuthBootstrapRequest,
    repo: Repository = Depends(get_repo),
) -> AuthTokenOut:
    _validate_bootstrap_code(payload.bootstrap_code)
    await repo.delete_stale_pending_users(repo.PENDING_USER_TTL_MINUTES)
    user = await repo.get_or_create_local_primary_user(payload.display_name)
    updated = await repo.update_user_display_name(user.id, payload.display_name)
    if updated is not None:
        user = updated
    return await _issue_token(
        repo,
        user,
        device_name=payload.device_name,
        device_type=payload.device_type,
        created_via="bootstrap",
    )


@router.post("/pair/complete", response_model=AuthTokenOut)
async def complete_pair(
    payload: AuthPairCompleteRequest,
    repo: Repository = Depends(get_repo),
) -> AuthTokenOut:
    code_hash = hash_pair_code(payload.pair_code)
    pair = await repo.get_pair_code_by_hash(code_hash, flow_type="pair")
    now = utcnow()
    if pair is None:
        raise HTTPException(status_code=400, detail="Invalid or expired pair code.")
    await repo.mark_pair_code_attempt(pair)
    if pair.consumed_at is not None or pair.expires_at <= now:
        raise HTTPException(status_code=400, detail="Invalid or expired pair code.")
    if not pair.user_id:
        raise HTTPException(status_code=400, detail="Pair code is not bound to a user.")
    user = await repo.get_user_by_id(pair.user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found.")
    if not user.approved:
        raise HTTPException(status_code=403, detail="Your account is not yet approved. An admin has to approve it first.")
    await repo.consume_pair_code(pair)
    return await _issue_token(
        repo,
        user,
        device_name=payload.device_name,
        device_type=payload.device_type,
        created_via="pair_code",
    )


@router.get("/me", response_model=AuthUserOut)
async def auth_me(
    request: Request,
    user_id: str | None = Query(default=None),
    repo: Repository = Depends(get_repo),
) -> AuthUserOut:
    principal: AuthPrincipal = get_auth_principal(request)
    target_user_id = principal.user_id
    if principal.is_admin:
        target_user_id = user_id or target_user_id
    if not target_user_id:
        raise HTTPException(status_code=400, detail="user_id is required for admin requests.")
    user = await repo.get_user_by_id(target_user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found.")
    return _user_out(user)


@router.post("/pair-codes", response_model=AuthPairCodeOut)
async def create_pair_code(
    payload: AuthPairCodeCreateRequest,
    request: Request,
    repo: Repository = Depends(get_repo),
) -> AuthPairCodeOut:
    principal = require_user_principal(request)
    user = await repo.get_user_by_id(principal.user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found.")
    if not user.approved:
        raise HTTPException(status_code=403, detail="Your account is not yet approved. An admin has to approve it first.")

    raw_code = make_pair_code()
    expires_at = utcnow() + timedelta(minutes=payload.expires_minutes)
    await repo.create_pair_code(
        hash_pair_code(raw_code),
        flow_type="pair",
        user_id=user.id,
        display_name=None,
        created_by_user_id=user.id,
        created_via=(payload.device_name or "api"),
        expires_at=expires_at,
    )
    return AuthPairCodeOut(code=raw_code, expires_at=expires_at, user=_user_out(user))
