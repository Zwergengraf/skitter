from __future__ import annotations

import shutil
from pathlib import Path

from .config import settings


def _base_workspace_root() -> Path:
    return Path(settings.workspace_root)


def _host_workspace_root() -> Path:
    root = settings.host_workspace_root or settings.workspace_root
    return Path(root).resolve()


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
    return root
