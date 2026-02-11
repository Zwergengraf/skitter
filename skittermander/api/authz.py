from __future__ import annotations

from fastapi import HTTPException, Request

from .security import AuthPrincipal, get_auth_principal
from ..data.repositories import Repository


def require_admin(request: Request) -> AuthPrincipal:
    principal = get_auth_principal(request)
    if not principal.is_admin:
        raise HTTPException(status_code=403, detail="Admin API key required.")
    return principal


def require_authenticated_user(request: Request) -> AuthPrincipal:
    principal = get_auth_principal(request)
    if principal.is_user:
        return principal
    if principal.is_admin:
        raise HTTPException(status_code=400, detail="user_id is required for admin requests.")
    raise HTTPException(status_code=401, detail="Authentication required.")


def resolve_target_user_id(request: Request, payload_user_id: str | None) -> str:
    principal = get_auth_principal(request)
    if principal.is_user:
        if payload_user_id and payload_user_id != principal.user_id:
            raise HTTPException(status_code=403, detail="Token is not allowed to act as another user.")
        return principal.user_id or ""
    if principal.is_admin:
        if not payload_user_id:
            raise HTTPException(status_code=400, detail="user_id is required for admin requests.")
        return payload_user_id
    raise HTTPException(status_code=401, detail="Authentication required.")


async def require_session_access(request: Request, repo: Repository, session_id: str):
    session = await repo.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    principal = get_auth_principal(request)
    if principal.is_user and session.user_id != principal.user_id:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


async def require_tool_run_access(request: Request, repo: Repository, tool_run_id: str):
    tool_run = await repo.get_tool_run(tool_run_id)
    if tool_run is None:
        raise HTTPException(status_code=404, detail="Tool run not found")
    session = await repo.get_session(tool_run.session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    principal = get_auth_principal(request)
    if principal.is_user and session.user_id != principal.user_id:
        raise HTTPException(status_code=404, detail="Tool run not found")
    return tool_run, session
