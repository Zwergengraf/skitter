from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

from ..authz import resolve_target_user_id
from ...core.skills import SkillRegistry
from ..schemas import SkillOut

router = APIRouter(prefix="/v1/skills", tags=["skills"])


@router.get("", response_model=list[SkillOut])
async def list_skills(
    request: Request,
    user_id: str | None = Query(default=None),
) -> list[SkillOut]:
    target_user_id = resolve_target_user_id(request, user_id)
    registry = SkillRegistry()
    skills = registry.list_skills(user_id=target_user_id)
    return [SkillOut(name=s.name, description=s.description, path=str(s.path)) for s in skills]


@router.get("/{name}", response_model=SkillOut)
async def get_skill(
    name: str,
    request: Request,
    user_id: str | None = Query(default=None),
) -> SkillOut:
    target_user_id = resolve_target_user_id(request, user_id)
    registry = SkillRegistry()
    skill = registry.load_skill(name, user_id=target_user_id)
    if skill is None:
        raise HTTPException(status_code=404, detail="Skill not found")
    return SkillOut(name=skill.name, description=skill.description, path=str(skill.path))
