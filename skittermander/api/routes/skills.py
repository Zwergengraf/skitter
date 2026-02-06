from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ...core.skills import SkillRegistry
from ..schemas import SkillOut

router = APIRouter(prefix="/v1/skills", tags=["skills"])


@router.get("", response_model=list[SkillOut])
async def list_skills(user_id: str | None = None) -> list[SkillOut]:
    if not user_id:
        return []
    registry = SkillRegistry()
    skills = registry.list_skills(user_id=user_id)
    return [SkillOut(name=s.name, description=s.description, path=str(s.path)) for s in skills]


@router.get("/{name}", response_model=SkillOut)
async def get_skill(name: str, user_id: str | None = None) -> SkillOut:
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id is required")
    registry = SkillRegistry()
    skill = registry.load_skill(name, user_id=user_id)
    if skill is None:
        raise HTTPException(status_code=404, detail="Skill not found")
    return SkillOut(name=skill.name, description=skill.description, path=str(skill.path))
