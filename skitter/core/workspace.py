from __future__ import annotations

import shutil
from pathlib import Path

from .config import settings
from .profile_context import current_agent_profile_slug
from .profiles import DEFAULT_AGENT_PROFILE_SLUG


def _project_root() -> Path:
    # workspace.py lives at <repo>/skitter/core/workspace.py
    return Path(__file__).resolve().parents[2]


def _base_workspace_root() -> Path:
    root = Path(settings.workspace_root)
    if root.is_absolute():
        return root
    return (_project_root() / root).resolve()


def _host_workspace_root() -> Path:
    root_value = settings.host_workspace_root or settings.workspace_root
    root = Path(root_value)
    if root.is_absolute():
        return root
    return (_project_root() / root).resolve()


def _workspace_skeleton_root() -> Path:
    root = Path(settings.workspace_skeleton_root)
    if root.is_absolute():
        return root
    return (_project_root() / root).resolve()


def users_root() -> Path:
    return _base_workspace_root() / "users"


def _resolve_profile_slug(profile_slug: str | None = None) -> str:
    cleaned = str(profile_slug or current_agent_profile_slug() or DEFAULT_AGENT_PROFILE_SLUG).strip()
    return cleaned or DEFAULT_AGENT_PROFILE_SLUG


def user_profiles_root(user_id: str) -> Path:
    return users_root() / user_id


def profile_workspace_root(user_id: str, profile_slug: str | None = None) -> Path:
    return user_profiles_root(user_id) / _resolve_profile_slug(profile_slug)


def user_workspace_root(user_id: str, profile_slug: str | None = None) -> Path:
    return profile_workspace_root(user_id, profile_slug)


def host_users_root() -> Path:
    return _host_workspace_root() / "users"


def host_user_profiles_root(user_id: str) -> Path:
    return host_users_root() / user_id


def host_profile_workspace_root(user_id: str, profile_slug: str | None = None) -> Path:
    return host_user_profiles_root(user_id) / _resolve_profile_slug(profile_slug)


def host_user_workspace_root(user_id: str, profile_slug: str | None = None) -> Path:
    return host_profile_workspace_root(user_id, profile_slug)


def ensure_profile_workspace(user_id: str, profile_slug: str | None = None) -> Path:
    slug = _resolve_profile_slug(profile_slug)
    root = profile_workspace_root(user_id, slug)
    if not root.exists():
        skeleton = _workspace_skeleton_root()
        if not root.exists() and skeleton.exists():
            shutil.copytree(skeleton, root)
        elif not root.exists():
            root.mkdir(parents=True, exist_ok=True)
    return root


def ensure_user_workspace(user_id: str, profile_slug: str | None = None) -> Path:
    return ensure_profile_workspace(user_id, profile_slug)
