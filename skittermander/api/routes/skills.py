from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException

from ...core.config import settings
from ...core.skills import SkillLoader
from ..schemas import SkillOut

router = APIRouter(prefix="/v1/skills", tags=["skills"])


@router.get("", response_model=list[SkillOut])
async def list_skills() -> list[SkillOut]:
    loader = SkillLoader(Path(settings.skills_root))
    skills = loader.list_skills()
    return [SkillOut(name=s.name, description=s.description, path=str(s.path)) for s in skills]


@router.get("/{name}", response_model=SkillOut)
async def get_skill(name: str) -> SkillOut:
    loader = SkillLoader(Path(settings.skills_root))
    skill = loader.load_skill(name)
    if skill is None:
        raise HTTPException(status_code=404, detail="Skill not found")
    return SkillOut(name=skill.name, description=skill.description, path=str(skill.path))
