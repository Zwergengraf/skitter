from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

import yaml

@dataclass
class SkillMetadata:
    name: str
    description: str
    path: Path


@dataclass
class SkillDetail(SkillMetadata):
    body: str


class SkillLoader:
    def __init__(self, root: Path) -> None:
        self.root = root

    def list_skills(self) -> List[SkillMetadata]:
        skills: List[SkillMetadata] = []
        for skill_dir in self._skill_dirs():
            meta = self._read_frontmatter(skill_dir / "SKILL.md")
            if meta is None:
                continue
            skills.append(SkillMetadata(name=meta["name"], description=meta["description"], path=skill_dir))
        return skills

    def load_skill(self, name: str) -> Optional[SkillDetail]:
        for skill_dir in self._skill_dirs():
            skill_file = skill_dir / "SKILL.md"
            meta = self._read_frontmatter(skill_file)
            if meta is None or meta["name"].lower() != name.lower():
                continue
            body = self._read_body(skill_file)
            return SkillDetail(name=meta["name"], description=meta["description"], path=skill_dir, body=body)
        return None

    def _skill_dirs(self) -> List[Path]:
        if not self.root.exists():
            return []
        return [p for p in self.root.iterdir() if p.is_dir()]

    def _read_frontmatter(self, path: Path) -> Optional[Dict[str, str]]:
        if not path.exists():
            return None
        text = path.read_text(encoding="utf-8")
        if not text.startswith("---"):
            return None
        parts = text.split("---", 2)
        if len(parts) < 3:
            return None
        frontmatter_text = parts[1].strip()
        try:
            data = yaml.safe_load(frontmatter_text) or {}
        except Exception:
            return None
        if not isinstance(data, dict):
            return None
        name = data.get("name")
        description = data.get("description")
        if not name or not description:
            return None
        return {"name": str(name).strip(), "description": str(description).strip()}

    def _read_body(self, path: Path) -> str:
        text = path.read_text(encoding="utf-8")
        parts = text.split("---", 2)
        if len(parts) < 3:
            return ""
        return parts[2].lstrip("\n")
