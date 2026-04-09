from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from ..authz import resolve_target_user_id
from ..deps import get_repo
from ..schemas import AgentProfileCreateRequest, AgentProfileOut, AgentProfileUpdateRequest
from ..security import get_auth_principal
from ...core.llm import list_models, resolve_model_name
from ...core.profile_service import profile_service, serialize_profile
from ...data.repositories import Repository

router = APIRouter(prefix="/v1/profiles", tags=["profiles"])


def _normalize_profile_default_model(value: str | None) -> str | None:
    raw = str(value or "").strip()
    if not raw or raw.lower() == "default":
        return None
    available = list_models()
    if not available:
        raise HTTPException(status_code=400, detail="No models configured")
    normalized = resolve_model_name(raw, purpose="main")
    match = next((model for model in available if model.name.lower() == normalized.lower()), None)
    if match is None:
        raise HTTPException(status_code=400, detail=f"Unknown model '{value}'")
    return match.name


@router.get("", response_model=list[AgentProfileOut])
async def list_profiles(
    request: Request,
    repo: Repository = Depends(get_repo),
    user_id: str | None = Query(default=None),
    include_archived: bool = Query(default=False),
) -> list[AgentProfileOut]:
    target_user_id = resolve_target_user_id(request, user_id)
    default_profile = await profile_service.ensure_default_profile(repo, target_user_id)
    rows = await profile_service.list_profiles(repo, target_user_id, include_archived=include_archived)
    return [
        AgentProfileOut(**serialize_profile(row, default_profile_id=default_profile.id))
        for row in rows
    ]


def _profile_owner_user_id(request: Request, profile) -> str:
    principal = get_auth_principal(request)
    if principal.is_user:
        if principal.user_id != profile.user_id:
            raise HTTPException(status_code=404, detail="Profile not found")
        return profile.user_id
    if principal.is_admin:
        return profile.user_id
    raise HTTPException(status_code=401, detail="Authentication required.")


@router.post("", response_model=AgentProfileOut)
async def create_profile(
    payload: AgentProfileCreateRequest,
    request: Request,
    repo: Repository = Depends(get_repo),
) -> AgentProfileOut:
    target_user_id = resolve_target_user_id(request, payload.user_id)
    source_slug = str(payload.source_profile_slug or "").strip() or None
    mode = str(payload.mode or "").strip().lower() or ("settings" if source_slug else "blank")
    try:
        row = await profile_service.create_profile(
            repo,
            target_user_id,
            name=payload.name,
            source_slug=source_slug,
            mode=mode,
            make_default=payload.make_default,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc) or "Invalid request") from exc
    default_profile = await profile_service.ensure_default_profile(repo, target_user_id)
    return AgentProfileOut(**serialize_profile(row, default_profile_id=default_profile.id))


@router.patch("/{profile_id}", response_model=AgentProfileOut)
async def update_profile(
    profile_id: str,
    payload: AgentProfileUpdateRequest,
    request: Request,
    repo: Repository = Depends(get_repo),
) -> AgentProfileOut:
    current = await repo.get_agent_profile(profile_id)
    if current is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    owner_user_id = _profile_owner_user_id(request, current)
    fields_set = getattr(payload, "model_fields_set", set()) or set()
    default_model_provided = "default_model" in fields_set

    if payload.archived is None and payload.make_default is None and payload.name is None and not default_model_provided:
        raise HTTPException(status_code=400, detail="No profile updates were provided.")
    if payload.archived and payload.make_default:
        raise HTTPException(status_code=400, detail="Archived profiles cannot be set as default.")

    updated = current
    try:
        if payload.archived is not None:
            if payload.archived:
                updated = await profile_service.archive_profile(repo, owner_user_id, updated.slug)
            else:
                updated = await profile_service.unarchive_profile(repo, owner_user_id, updated.slug)
        if payload.name is not None:
            updated = await profile_service.rename_profile(repo, owner_user_id, updated.slug, payload.name)
        if payload.make_default:
            updated = await profile_service.set_default_profile(repo, owner_user_id, updated.slug)
        if default_model_provided:
            normalized_default_model = _normalize_profile_default_model(payload.default_model)
            updated = await repo.set_profile_default_model_name(updated.id, normalized_default_model) or updated
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc) or "Invalid request") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc) or "Invalid request") from exc

    default_profile = await profile_service.ensure_default_profile(repo, owner_user_id)
    final = await repo.get_agent_profile(updated.id) or updated
    return AgentProfileOut(**serialize_profile(final, default_profile_id=default_profile.id))


@router.delete("/{profile_id}")
async def delete_profile(
    profile_id: str,
    request: Request,
    repo: Repository = Depends(get_repo),
) -> dict:
    current = await repo.get_agent_profile(profile_id)
    if current is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    owner_user_id = _profile_owner_user_id(request, current)
    try:
        deleted = await profile_service.delete_profile(repo, owner_user_id, current.slug)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc) or "Invalid request") from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="Profile not found")
    return {"id": profile_id, "deleted": True}
