from __future__ import annotations

import shutil
from pathlib import Path

from .config import settings


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


def users_root() -> Path:
    return _base_workspace_root() / "users"


def user_workspace_root(user_id: str) -> Path:
    return users_root() / user_id


def host_users_root() -> Path:
    return _host_workspace_root() / "users"


def host_user_workspace_root(user_id: str) -> Path:
    return host_users_root() / user_id


def ensure_user_workspace(user_id: str) -> Path:
    root = user_workspace_root(user_id)
    if not root.exists():
        skeleton = Path(settings.workspace_skeleton_root)
        if skeleton.exists():
            shutil.copytree(skeleton, root)
        else:
            root.mkdir(parents=True, exist_ok=True)
    (root / "memory").mkdir(parents=True, exist_ok=True)
    (root / "screenshots").mkdir(parents=True, exist_ok=True)
    (root / "skills").mkdir(parents=True, exist_ok=True)
    return root
