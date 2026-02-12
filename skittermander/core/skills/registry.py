from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from .loader import SkillDetail, SkillLoader, SkillMetadata
from ..workspace import user_workspace_root


@dataclass
class SkillRecord(SkillMetadata):
    origin: str
    dir_name: str
    container_path: str


class SkillRegistry:
    def list_skills(self, user_id: Optional[str] = None) -> List[SkillRecord]:
        if not user_id:
            return []
        user_root = user_workspace_root(user_id) / "skills"
        return self._load_from_root(user_root, origin="user")

    def load_skill(self, name: str, user_id: Optional[str] = None) -> Optional[SkillDetail]:
        if not user_id:
            return None
        user_root = user_workspace_root(user_id) / "skills"
        return SkillLoader(user_root).load_skill(name)

    def _load_from_root(self, root: Path, origin: str) -> List[SkillRecord]:
        loader = SkillLoader(root)
        records: List[SkillRecord] = []
        for skill in loader.list_skills():
            dir_name = skill.path.name
            container_path = f"skills/{dir_name}"
            records.append(
                SkillRecord(
                    name=skill.name,
                    description=skill.description,
                    path=skill.path,
                    origin=origin,
                    dir_name=dir_name,
                    container_path=container_path,
                )
            )
        return records
