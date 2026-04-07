from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, WebSocket, WebSocketDisconnect, status

from ..authz import require_admin, require_authenticated_user, resolve_target_user_id
from ..deps import get_repo
from ..schemas import (
    ExecutorCreateRequest,
    ExecutorOut,
    ExecutorSetDefaultRequest,
    ExecutorTokenCreateOut,
    ExecutorTokenCreateRequest,
    ExecutorUpdateRequest,
)
from ..security import get_auth_principal, hash_secret, make_client_token, token_prefix
from ...core.config import settings
from ...data.db import SessionLocal
from ...data.repositories import Repository
from ...tools.executors import executor_router, node_executor_hub
from ...tools.sandbox_manager import sandbox_manager

router = APIRouter(prefix="/v1/executors", tags=["executors"])


def _parse_auth_header(value: str | None) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    if raw.lower().startswith("bearer "):
        return raw[7:].strip()
    return raw


def _executor_to_out(row, online: bool) -> ExecutorOut:
    status = "online" if online else (row.status or "offline")
    return ExecutorOut(
        id=row.id,
        owner_user_id=row.owner_user_id,
        name=row.name,
        kind=row.kind,
        platform=row.platform,
        hostname=row.hostname,
        status=status,
        capabilities=row.capabilities or {},
        last_seen_at=row.last_seen_at,
        created_at=row.created_at,
        disabled=bool(row.disabled),
        online=online,
    )


async def _running_docker_users() -> set[str]:
    if sandbox_manager is None:
        return set()
    try:
        containers = await sandbox_manager.list_containers()
    except Exception:
        return set()
    running_users: set[str] = set()
    for container in containers:
        if str(container.get("status") or "").lower() != "running":
            continue
        user_id = str(container.get("user_id") or "").strip()
        if user_id:
            running_users.add(user_id)
    return running_users


async def _resolve_executor_for_user(repo: Repository, user_id: str, target: str):
    key = (target or "").strip()
    if not key:
        return None
    if key.lower() in {"docker", "docker-default"}:
        if settings.executors_auto_docker_default:
            return await repo.get_or_create_docker_executor(user_id)
        return await repo.get_docker_executor_for_user(user_id)
    row = await repo.get_executor_for_user(user_id, key)
    if row is not None:
        return row
    return await repo.get_executor_for_user_by_name(user_id, key)


async def _require_executor_access(request: Request, repo: Repository, executor_id: str):
    principal = get_auth_principal(request)
    if not principal.is_admin and not principal.is_user:
        raise HTTPException(status_code=401, detail="Authentication required.")
    row = await repo.get_executor(executor_id)
    if row is None or not row.owner_user_id:
        raise HTTPException(status_code=404, detail="Executor not found")
    if principal.is_user and row.owner_user_id != principal.user_id:
        raise HTTPException(status_code=404, detail="Executor not found")
    return row


@router.get("", response_model=list[ExecutorOut])
async def list_executors(
    request: Request,
    repo: Repository = Depends(get_repo),
    user_id: str | None = Query(default=None),
    include_disabled: bool = Query(default=True),
) -> list[ExecutorOut]:
    require_admin(request)
    rows = await repo.list_executors_all(user_id=user_id, include_disabled=include_disabled, limit=500)
    online_ids = set(await node_executor_hub.online_executor_ids())
    running_docker_users = await _running_docker_users()
    return [
        _executor_to_out(
            row,
            online=(row.id in online_ids) or (row.kind == "docker" and row.owner_user_id in running_docker_users),
        )
        for row in rows
    ]


@router.get("/me", response_model=list[ExecutorOut])
async def list_my_executors(
    request: Request,
    repo: Repository = Depends(get_repo),
    include_disabled: bool = Query(default=False),
) -> list[ExecutorOut]:
    principal = require_authenticated_user(request)
    rows = await repo.list_executors_for_user(principal.user_id or "", include_disabled=include_disabled)
    online_ids = set(await node_executor_hub.online_executor_ids())
    running_docker_users = await _running_docker_users()
    return [
        _executor_to_out(
            row,
            online=(row.id in online_ids) or (row.kind == "docker" and row.owner_user_id in running_docker_users),
        )
        for row in rows
    ]


@router.post("", response_model=ExecutorOut)
async def create_executor(
    payload: ExecutorCreateRequest,
    request: Request,
    repo: Repository = Depends(get_repo),
) -> ExecutorOut:
    owner_user_id = resolve_target_user_id(request, payload.user_id)
    name = (payload.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")
    row = await repo.create_executor(
        owner_user_id=owner_user_id,
        name=name,
        kind=(payload.kind or "node").strip() or "node",
        platform=(payload.platform or "").strip() or None,
        hostname=(payload.hostname or "").strip() or None,
        status="offline",
        capabilities=payload.capabilities or {},
        disabled=False,
    )
    online_ids = set(await node_executor_hub.online_executor_ids())
    return _executor_to_out(row, online=row.id in online_ids)


@router.patch("/{executor_id}", response_model=ExecutorOut)
async def update_executor(
    executor_id: str,
    payload: ExecutorUpdateRequest,
    request: Request,
    repo: Repository = Depends(get_repo),
) -> ExecutorOut:
    await _require_executor_access(request, repo, executor_id)
    updated = await repo.update_executor(
        executor_id,
        name=payload.name,
        platform=payload.platform,
        hostname=payload.hostname,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="Executor not found")
    online_ids = set(await node_executor_hub.online_executor_ids())
    running_docker_users = await _running_docker_users()
    online = (updated.id in online_ids) or (updated.kind == "docker" and updated.owner_user_id in running_docker_users)
    return _executor_to_out(updated, online=online)


@router.post("/default")
async def set_default_executor(
    payload: ExecutorSetDefaultRequest,
    request: Request,
    repo: Repository = Depends(get_repo),
) -> dict:
    user_id = resolve_target_user_id(request, payload.user_id)
    target = (payload.executor_id or "").strip()
    executor_id: str | None = None
    if target:
        row = await _resolve_executor_for_user(repo, user_id, target)
        if row is None:
            raise HTTPException(status_code=404, detail="Executor not found")
        if row.disabled:
            raise HTTPException(status_code=400, detail="Executor is disabled")
        executor_id = row.id
    if payload.agent_profile_id:
        await repo.set_profile_default_executor(payload.agent_profile_id, executor_id)
    else:
        await repo.set_user_default_executor(user_id, executor_id)
    return {"user_id": user_id, "agent_profile_id": payload.agent_profile_id, "executor_id": executor_id}


@router.post("/tokens", response_model=ExecutorTokenCreateOut)
async def create_executor_token(
    payload: ExecutorTokenCreateRequest,
    request: Request,
    repo: Repository = Depends(get_repo),
) -> ExecutorTokenCreateOut:
    user_id = resolve_target_user_id(request, payload.user_id)
    row = None
    if payload.executor_id:
        row = await _resolve_executor_for_user(repo, user_id, payload.executor_id)
    elif payload.executor_name:
        row = await repo.get_executor_for_user_by_name(user_id, payload.executor_name)
        if row is None:
            row = await repo.create_executor(
                owner_user_id=user_id,
                name=payload.executor_name.strip(),
                kind="node",
                status="offline",
                capabilities={"tools": "all"},
                disabled=False,
            )
    if row is None:
        raise HTTPException(status_code=400, detail="executor_id or executor_name is required")
    if row.owner_user_id != user_id:
        raise HTTPException(status_code=404, detail="Executor not found")
    if row.disabled:
        raise HTTPException(status_code=400, detail="Executor is disabled")

    token = make_client_token()
    token_hash = hash_secret(token)
    prefix = token_prefix(token)
    await repo.create_executor_token(executor_id=row.id, token_hash=token_hash, token_prefix=prefix)
    return ExecutorTokenCreateOut(
        executor_id=row.id,
        executor_name=row.name,
        token=token,
        token_prefix=prefix,
    )


@router.post("/{executor_id}/disable", response_model=ExecutorOut)
async def disable_executor(
    executor_id: str,
    request: Request,
    repo: Repository = Depends(get_repo),
) -> ExecutorOut:
    row = await _require_executor_access(request, repo, executor_id)
    await repo.update_executor(executor_id, disabled=True, status="offline")
    owner_default = await repo.get_user_default_executor_id(row.owner_user_id)
    if owner_default == executor_id:
        await repo.set_user_default_executor(row.owner_user_id, None)
    for profile in await repo.list_agent_profiles(row.owner_user_id, include_archived=True):
        if await repo.get_profile_default_executor_id(profile.id) == executor_id:
            await repo.set_profile_default_executor(profile.id, None)
    await executor_router.clear_session_defaults_for_executor(executor_id)
    await node_executor_hub.close_executor(executor_id)
    updated = await repo.get_executor(executor_id)
    if updated is None:
        raise HTTPException(status_code=404, detail="Executor not found")
    return _executor_to_out(updated, online=False)


@router.post("/{executor_id}/enable", response_model=ExecutorOut)
async def enable_executor(
    executor_id: str,
    request: Request,
    repo: Repository = Depends(get_repo),
) -> ExecutorOut:
    await _require_executor_access(request, repo, executor_id)
    # Re-enable any previously revoked tokens from temporary disable actions,
    # so nodes can reconnect without rotating credentials.
    await repo.restore_executor_tokens(executor_id)
    updated = await repo.update_executor(executor_id, disabled=False)
    if updated is None:
        raise HTTPException(status_code=404, detail="Executor not found")
    online_ids = set(await node_executor_hub.online_executor_ids())
    running_docker_users = await _running_docker_users()
    online = (updated.id in online_ids) or (updated.kind == "docker" and updated.owner_user_id in running_docker_users)
    return _executor_to_out(updated, online=online)


@router.delete("/{executor_id}")
async def delete_executor(
    executor_id: str,
    request: Request,
    repo: Repository = Depends(get_repo),
) -> dict:
    row = await _require_executor_access(request, repo, executor_id)
    owner_default = await repo.get_user_default_executor_id(row.owner_user_id)
    if owner_default == executor_id:
        await repo.set_user_default_executor(row.owner_user_id, None)
    for profile in await repo.list_agent_profiles(row.owner_user_id, include_archived=True):
        if await repo.get_profile_default_executor_id(profile.id) == executor_id:
            await repo.set_profile_default_executor(profile.id, None)
    await executor_router.clear_session_defaults_for_executor(executor_id)
    await node_executor_hub.close_executor(executor_id)
    deleted = await repo.delete_executor(executor_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Executor not found")
    return {"id": executor_id, "deleted": True}


@router.websocket("/connect")
async def executors_connect(websocket: WebSocket) -> None:
    token = (
        (websocket.query_params.get("token") or "").strip()
        or _parse_auth_header(websocket.headers.get("authorization"))
        or (websocket.headers.get("x-api-key") or "").strip()
    )
    if not token:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    token_hash = hash_secret(token)
    async with SessionLocal() as session:
        repo = Repository(session)
        token_row = await repo.get_executor_token_by_hash(token_hash)
        if token_row is None or token_row.revoked_at is not None:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
        row = await repo.get_executor(token_row.executor_id)
        if row is None or row.disabled:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

    executor_id = row.id
    await node_executor_hub.register(executor_id, websocket)
    async with SessionLocal() as session:
        repo = Repository(session)
        await repo.update_executor(
            executor_id,
            status="online",
            last_seen_at=datetime.now(UTC),
        )
    await websocket.app.state.event_bus.emit_admin(
        kind="executor.connected",
        level="info",
        title="Executor connected",
        message=f"Executor {row.name} connected.",
        executor_id=executor_id,
        user_id=row.owner_user_id,
        data={"kind": row.kind, "name": row.name},
    )

    try:
        while True:
            message = await websocket.receive_json()
            async with SessionLocal() as session:
                repo = Repository(session)
                token_current = await repo.get_executor_token_by_hash(token_hash)
                if token_current is None or token_current.revoked_at is not None:
                    await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
                    break
            msg_type = str(message.get("type") or "").strip().lower()

            if msg_type == "heartbeat":
                capabilities = message.get("capabilities")
                name = message.get("name")
                platform = message.get("platform")
                hostname = message.get("hostname")
                async with SessionLocal() as session:
                    repo = Repository(session)
                    await repo.update_executor(
                        executor_id,
                        status="online",
                        last_seen_at=datetime.now(UTC),
                        capabilities=capabilities if isinstance(capabilities, dict) else None,
                        name=str(name).strip() if isinstance(name, str) and name.strip() else None,
                        platform=str(platform).strip() if isinstance(platform, str) and platform.strip() else None,
                        hostname=str(hostname).strip() if isinstance(hostname, str) and hostname.strip() else None,
                    )
            await node_executor_hub.handle_message(executor_id, message)
    except WebSocketDisconnect:
        pass
    finally:
        await node_executor_hub.unregister(executor_id, websocket=websocket)
        async with SessionLocal() as session:
            repo = Repository(session)
            await repo.update_executor(executor_id, status="offline", last_seen_at=datetime.now(UTC))
        await websocket.app.state.event_bus.emit_admin(
            kind="executor.disconnected",
            level="warning",
            title="Executor disconnected",
            message=f"Executor {row.name} disconnected.",
            executor_id=executor_id,
            user_id=row.owner_user_id,
            data={"kind": row.kind, "name": row.name},
        )
