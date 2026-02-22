from __future__ import annotations

from pathlib import Path

from .config import settings
from .skills import SkillRegistry
from .workspace import user_workspace_root


DEFAULT_PROMPT = (
    "You are Skitter, a helpful assistant.\n"
)


def load_base_prompt() -> str:
    path = Path(settings.prompt_path)
    if path.exists():
        try:
            content = path.read_text(encoding="utf-8").strip()
            if content:
                return content
        except OSError:
            pass
    return DEFAULT_PROMPT


def _parse_context_files() -> list[str]:
    raw = settings.prompt_context_files
    if isinstance(raw, str):
        return [item.strip() for item in raw.split(",") if item.strip()]
    if isinstance(raw, list):
        return [str(item).strip() for item in raw if str(item).strip()]
    return []


def _render_context_template(content: str, user_id: str) -> str:
    rendered = content
    variables = {
        "WORKSPACE_ROOT": "/workspace",
        "INTERNAL_USER_ID": user_id,
    }
    for key, value in variables.items():
        rendered = rendered.replace(f"{{{{{key}}}}}", value)
    return rendered


def build_context_block(user_id: str) -> str | None:
    files = _parse_context_files()
    if not files:
        return None
    root = user_workspace_root(user_id)
    sections = []
    for filename in files:
        path = root / filename
        if not path.exists() or not path.is_file():
            continue
        try:
            content = path.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if not content:
            continue
        sections.append(f"###{filename}\n{_render_context_template(content, user_id)}")
    if not sections:
        return None
    return "\n\n".join(sections)


def build_skills_index(user_id: str) -> str | None:
    registry = SkillRegistry()
    skills = registry.list_skills(user_id)
    if not skills:
        return None
    lines = [
        "## Skills",
        """Before replying: scan <available_skills> <description> entries.
- If exactly one skill clearly applies: read its SKILL.md at <location> with `read`, then follow it.
- If multiple could apply: choose the most specific one, then read/follow it.
- If none clearly apply: do not read any SKILL.md.
Constraints: never read more than one skill up front; only read after selecting.
The following skills provide specialized instructions for specific tasks.
Use the read tool to load a skill's file when the task matches its description.
When a skill file references a relative path, resolve it against the skill directory (parent of SKILL.md / dirname of the path) and use that absolute path in tool commands.
**Important:** Secret environment variables (API keys, credentials, etc) are automatically injected, make sure to list them in `secret_refs` when using the shell tool to run skill commands.
Use `list_secrets` to check which secret names are available before setting `secret_refs`.
"""
    ]
    lines.append("<available_skills>")
    for skill in skills:
        lines.append(f"  <skill>")
        lines.append(f"    <name>{skill.name}</name>")
        lines.append(f"    <description>{skill.description}</description>")
        lines.append(f"    <location>{skill.container_path}/SKILL.md</location>")
        lines.append(f"  </skill>")
    lines.append("</available_skills>")
    return "\n".join(lines)


def build_system_prompt(user_id: str) -> str:
    # Important: Only include the BOOTSTRAP.md content if it's present.
    # This allows for one-time setup instructions without affecting the prompt on subsequent runs.
    # The BOOTSTRAP.md can be used to set up the agent's identity, initial goals, or any other necessary context that should only be provided once.
    bootstrap_file = user_workspace_root(user_id) / "BOOTSTRAP.md"
    if bootstrap_file.exists():
        try:
            content = bootstrap_file.read_text(encoding="utf-8").strip()
        except OSError:
            content = None
        if content:
            return content

    base = load_base_prompt().strip()
    parts = [base]
    skills_index = build_skills_index(user_id)
    if skills_index:
        parts.append(skills_index)
    context = build_context_block(user_id)
    if context:
        parts.append(context)
    return "\n\n".join(part for part in parts if part).strip()
