from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from skitter.core.config import settings
from skitter.core.profile_service import profile_service
from skitter.core.workspace import ensure_profile_workspace, profile_workspace_root
import skitter.core.workspace as workspace_module


def _configure_workspace(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    skeleton_root = tmp_path / "workspace-skeleton"
    (skeleton_root / "skills").mkdir(parents=True, exist_ok=True)
    (skeleton_root / "memory").mkdir(parents=True, exist_ok=True)
    (skeleton_root / "screenshots").mkdir(parents=True, exist_ok=True)
    (skeleton_root / "BOOTSTRAP.md").write_text("bootstrap", encoding="utf-8")
    (skeleton_root / "IDENTITY.md").write_text("identity", encoding="utf-8")
    (skeleton_root / "skills" / "starter.md").write_text("starter skill", encoding="utf-8")

    monkeypatch.setattr(workspace_module, "_project_root", lambda: tmp_path)
    monkeypatch.setattr(settings, "workspace_root", "workspace")
    monkeypatch.setattr(settings, "workspace_skeleton_root", "workspace-skeleton")


def _assert_workspace_scaffold(root: Path) -> None:
    assert root.exists()
    assert (root / "BOOTSTRAP.md").read_text(encoding="utf-8") == "bootstrap"
    assert (root / "IDENTITY.md").read_text(encoding="utf-8") == "identity"
    assert (root / "skills" / "starter.md").read_text(encoding="utf-8") == "starter skill"
    assert (root / "memory").is_dir()
    assert (root / "screenshots").is_dir()


class _DefaultProfileRepo:
    async def get_default_agent_profile(self, user_id: str):
        return SimpleNamespace(
            id="profile-default",
            user_id=user_id,
            slug="default",
            status="active",
        )


class _CreateProfileRepo:
    def __init__(self) -> None:
        self.rows: dict[str, SimpleNamespace] = {}

    async def get_agent_profile_by_slug(self, user_id: str, slug: str):
        row = self.rows.get(slug)
        if row is not None and row.user_id == user_id:
            return row
        return None

    async def create_agent_profile(
        self,
        *,
        user_id: str,
        name: str,
        slug: str,
        make_default: bool = False,
        meta: dict | None = None,
    ):
        _ = make_default, meta
        row = SimpleNamespace(
            id=f"profile-{slug}",
            user_id=user_id,
            slug=slug,
            name=name,
            status="active",
        )
        self.rows[slug] = row
        return row


class _DeleteProfileRepo:
    def __init__(self) -> None:
        self.rows = {
            "default": SimpleNamespace(
                id="profile-default",
                user_id="user-1",
                slug="default",
                status="active",
            ),
            "scratch": SimpleNamespace(
                id="profile-scratch",
                user_id="user-1",
                slug="scratch",
                status="archived",
            ),
        }
        self.deleted_ids: list[str] = []

    async def get_default_agent_profile(self, user_id: str):
        return self.rows["default"] if user_id == "user-1" else None

    async def get_agent_profile_by_slug(self, user_id: str, slug: str):
        row = self.rows.get(slug)
        if row is not None and row.user_id == user_id:
            return row
        return None

    async def delete_agent_profile(self, profile_id: str) -> bool:
        for slug, row in list(self.rows.items()):
            if row.id == profile_id:
                self.deleted_ids.append(profile_id)
                del self.rows[slug]
                return True
        return False


@pytest.mark.asyncio
async def test_ensure_default_profile_creates_workspace_from_skeleton(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _configure_workspace(monkeypatch, tmp_path)
    repo = _DefaultProfileRepo()

    root = profile_workspace_root("user-1", "default")
    assert not root.exists()

    profile = await profile_service.ensure_default_profile(repo, "user-1")

    assert profile.slug == "default"
    _assert_workspace_scaffold(root)


@pytest.mark.asyncio
async def test_create_blank_profile_copies_workspace_skeleton(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _configure_workspace(monkeypatch, tmp_path)
    repo = _CreateProfileRepo()

    profile = await profile_service.create_profile(
        repo,
        "user-1",
        name="Research Assistant",
    )

    assert profile.slug == "research-assistant"
    _assert_workspace_scaffold(profile_workspace_root("user-1", profile.slug))


def test_ensure_profile_workspace_does_not_backfill_existing_workspace(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _configure_workspace(monkeypatch, tmp_path)
    root = profile_workspace_root("user-1", "broken")
    root.mkdir(parents=True, exist_ok=True)

    ensured = ensure_profile_workspace("user-1", "broken")

    assert ensured == root
    assert not (root / "BOOTSTRAP.md").exists()
    assert not (root / "IDENTITY.md").exists()
    assert not (root / "skills").exists()
    assert not (root / "memory").exists()
    assert not (root / "screenshots").exists()


@pytest.mark.asyncio
async def test_delete_archived_profile_removes_workspace(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _configure_workspace(monkeypatch, tmp_path)
    repo = _DeleteProfileRepo()

    workspace = profile_workspace_root("user-1", "scratch")
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "IDENTITY.md").write_text("scratch", encoding="utf-8")

    deleted = await profile_service.delete_profile(repo, "user-1", "scratch")

    assert deleted is True
    assert repo.deleted_ids == ["profile-scratch"]
    assert not workspace.exists()
