from __future__ import annotations

from pathlib import Path

from .config import settings
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
        sections.append(f"###{filename}\n{content}")
    if not sections:
        return None
    return "\n\n".join(sections)


def build_system_prompt(user_id: str) -> str:
    bootstrap_file = user_workspace_root(user_id) / "BOOTSTRAP.md"
    if bootstrap_file.exists():
        try:
            content = bootstrap_file.read_text(encoding="utf-8").strip()
        except OSError:
            content = None
        if content:
            return content
    
    base = load_base_prompt().strip()
    context = build_context_block(user_id)
    if context:
        return f"{base}\n\n{context}".strip()
    return base
