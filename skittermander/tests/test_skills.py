from pathlib import Path

from skittermander.core.skills import SkillLoader


def test_skill_loader(tmp_path: Path) -> None:
    skill_dir = tmp_path / "sample"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        """---\nname: Sample Skill\ndescription: Test skill\n---\nBody text\n""",
        encoding="utf-8",
    )

    loader = SkillLoader(tmp_path)
    skills = loader.list_skills()
    assert len(skills) == 1
    assert skills[0].name == "Sample Skill"

    detail = loader.load_skill("Sample Skill")
    assert detail is not None
    assert "Body text" in detail.body
