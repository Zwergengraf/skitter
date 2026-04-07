from __future__ import annotations

import shlex
import shutil
from pathlib import Path

from ..data.models import AgentProfile
from ..data.repositories import Repository
from .profiles import DEFAULT_AGENT_PROFILE_NAME, DEFAULT_AGENT_PROFILE_SLUG, normalize_profile_slug
from .transport_accounts import discord_surface_kind
from .workspace import ensure_profile_workspace, profile_workspace_root

PROFILE_SETTINGS_DIRS = ("skills",)

def serialize_profile(profile: AgentProfile, *, default_profile_id: str | None = None) -> dict[str, object]:
    return {
        "id": profile.id,
        "slug": profile.slug,
        "name": profile.name,
        "status": profile.status,
        "is_default": bool(default_profile_id and profile.id == default_profile_id),
        "created_at": profile.created_at.isoformat(),
        "updated_at": profile.updated_at.isoformat(),
    }


def parse_profile_command(raw: str) -> dict[str, object]:
    tokens = shlex.split(str(raw or "").strip())
    if not tokens:
        return {"action": "show"}
    action = tokens[0].lower()
    rest = tokens[1:]
    if action in {"list", "show"}:
        return {"action": "show"}
    if action in {"use", "default", "archive", "unarchive"}:
        if not rest:
            raise ValueError(f"`{action}` requires a profile slug.")
        return {"action": action, "slug": rest[0]}
    if action == "create":
        if not rest:
            raise ValueError("`create` requires a profile name.")
        make_default = False
        filtered: list[str] = []
        for token in rest:
            if token == "--default":
                make_default = True
                continue
            filtered.append(token)
        return {
            "action": "create",
            "name": " ".join(filtered).strip(),
            "make_default": make_default,
        }
    if action == "clone":
        if len(rest) < 2:
            raise ValueError("`clone` requires a source slug and new profile name.")
        mode = "settings"
        make_default = False
        filtered: list[str] = []
        for token in rest[1:]:
            lowered = token.lower()
            if lowered in {"--default", "default"}:
                make_default = True
                continue
            if lowered.startswith("--mode="):
                mode = lowered.split("=", 1)[1] or mode
                continue
            if lowered.startswith("mode="):
                mode = lowered.split("=", 1)[1] or mode
                continue
            filtered.append(token)
        return {
            "action": "clone",
            "source_slug": rest[0],
            "name": " ".join(filtered).strip(),
            "mode": mode,
            "make_default": make_default,
        }
    if action == "rename":
        if len(rest) < 2:
            raise ValueError("`rename` requires a profile slug and a new name.")
        return {"action": "rename", "slug": rest[0], "name": " ".join(rest[1:]).strip()}
    raise ValueError(f"Unknown profile action `{action}`.")


class ProfileService:
    async def ensure_default_profile(self, repo: Repository, user_id: str) -> AgentProfile:
        profile = await repo.get_default_agent_profile(user_id)
        if profile is None:
            raise RuntimeError("Default profile is not available.")
        ensure_profile_workspace(user_id, profile.slug)
        return profile

    async def list_profiles(self, repo: Repository, user_id: str, *, include_archived: bool = False) -> list[AgentProfile]:
        await self.ensure_default_profile(repo, user_id)
        rows = await repo.list_agent_profiles(user_id, include_archived=include_archived)
        for row in rows:
            if row.status != "archived":
                ensure_profile_workspace(user_id, row.slug)
        return rows

    async def resolve_profile(
        self,
        repo: Repository,
        user_id: str,
        *,
        agent_profile_id: str | None = None,
        agent_profile_slug: str | None = None,
        origin: str | None = None,
        channel_id: str | None = None,
        transport_account_key: str | None = None,
    ) -> AgentProfile:
        profile: AgentProfile | None = None
        if agent_profile_id:
            profile = await repo.get_agent_profile(agent_profile_id)
        elif agent_profile_slug:
            profile = await repo.get_agent_profile_by_slug(user_id, agent_profile_slug)
        elif origin == "discord" and channel_id:
            override = await repo.get_surface_profile_override(
                user_id=user_id,
                origin=origin,
                transport_account_key=str(transport_account_key or "").strip() or "discord:default",
                surface_kind=discord_surface_kind(),
                surface_id=channel_id,
            )
            if override is not None:
                profile = await repo.get_agent_profile(override.agent_profile_id)
        if profile is None:
            profile = await self.ensure_default_profile(repo, user_id)
        if profile.user_id != user_id:
            raise RuntimeError("Profile does not belong to this user.")
        if profile.status == "archived":
            raise RuntimeError("Profile is archived.")
        ensure_profile_workspace(user_id, profile.slug)
        return profile

    async def create_profile(
        self,
        repo: Repository,
        user_id: str,
        *,
        name: str,
        source_slug: str | None = None,
        mode: str = "blank",
        make_default: bool = False,
    ) -> AgentProfile:
        cleaned_name = str(name or "").strip()
        if not cleaned_name:
            raise ValueError("Profile name is required.")
        slug = await self._unique_slug(repo, user_id, cleaned_name)
        row = await repo.create_agent_profile(
            user_id=user_id,
            name=cleaned_name,
            slug=slug,
            make_default=make_default,
        )
        ensure_profile_workspace(user_id, row.slug)
        if source_slug:
            source = await repo.get_agent_profile_by_slug(user_id, source_slug)
            if source is None:
                raise ValueError(f"Unknown source profile `{source_slug}`.")
            self._clone_profile_workspace(
                user_id=user_id,
                source_slug=source.slug,
                target_slug=row.slug,
                mode=mode,
            )
        return row

    async def set_default_profile(self, repo: Repository, user_id: str, slug: str) -> AgentProfile:
        profile = await self.resolve_profile(repo, user_id, agent_profile_slug=slug)
        await repo.set_default_agent_profile(user_id, profile.id)
        return profile

    async def rename_profile(self, repo: Repository, user_id: str, slug: str, name: str) -> AgentProfile:
        profile = await self.resolve_profile(repo, user_id, agent_profile_slug=slug)
        updated = await repo.update_agent_profile(profile.id, name=name)
        if updated is None:
            raise ValueError("Profile not found.")
        return updated

    async def archive_profile(self, repo: Repository, user_id: str, slug: str) -> AgentProfile:
        profile = await self.resolve_profile(repo, user_id, agent_profile_slug=slug)
        default_profile = await self.ensure_default_profile(repo, user_id)
        if profile.id == default_profile.id:
            raise ValueError("The default profile cannot be archived.")
        updated = await repo.update_agent_profile(profile.id, status="archived")
        if updated is None:
            raise ValueError("Profile not found.")
        if hasattr(repo, "disable_transport_accounts_for_profile"):
            await repo.disable_transport_accounts_for_profile(profile.id)
        if hasattr(repo, "disable_transport_surface_bindings_for_profile"):
            await repo.disable_transport_surface_bindings_for_profile(profile.id)
        return updated

    async def unarchive_profile(self, repo: Repository, user_id: str, slug: str) -> AgentProfile:
        profile = await repo.get_agent_profile_by_slug(user_id, slug)
        if profile is None:
            raise ValueError("Profile not found.")
        updated = await repo.update_agent_profile(profile.id, status="active")
        if updated is None:
            raise ValueError("Profile not found.")
        ensure_profile_workspace(user_id, updated.slug)
        return updated

    async def delete_profile(self, repo: Repository, user_id: str, slug: str) -> bool:
        profile = await repo.get_agent_profile_by_slug(user_id, slug)
        if profile is None:
            raise ValueError("Profile not found.")
        default_profile = await self.ensure_default_profile(repo, user_id)
        if profile.id == default_profile.id:
            raise ValueError("The default profile cannot be deleted.")
        if profile.status != "archived":
            raise ValueError("Only archived profiles can be deleted.")
        deleted = await repo.delete_agent_profile(profile.id)
        if deleted:
            self._delete_profile_workspace(user_id=user_id, profile_slug=profile.slug)
        return deleted

    async def set_surface_override(
        self,
        repo: Repository,
        user_id: str,
        *,
        origin: str,
        transport_account_key: str,
        channel_id: str,
        slug: str,
    ) -> AgentProfile:
        profile = await self.resolve_profile(repo, user_id, agent_profile_slug=slug)
        await repo.upsert_surface_profile_override(
            user_id=user_id,
            agent_profile_id=profile.id,
            origin=origin,
            transport_account_key=transport_account_key,
            surface_kind=discord_surface_kind(),
            surface_id=channel_id,
        )
        return profile

    async def current_surface_profile(
        self,
        repo: Repository,
        user_id: str,
        *,
        origin: str | None,
        channel_id: str | None,
        agent_profile_id: str | None = None,
        agent_profile_slug: str | None = None,
        transport_account_key: str | None = None,
    ) -> AgentProfile:
        return await self.resolve_profile(
            repo,
            user_id,
            agent_profile_id=agent_profile_id,
            agent_profile_slug=agent_profile_slug,
            origin=origin,
            channel_id=channel_id,
            transport_account_key=transport_account_key,
        )

    async def _unique_slug(self, repo: Repository, user_id: str, value: str) -> str:
        base = normalize_profile_slug(value, fallback="agent")
        candidate = base
        counter = 2
        while await repo.get_agent_profile_by_slug(user_id, candidate) is not None:
            candidate = f"{base}-{counter}"
            counter += 1
        return candidate

    def _clone_profile_workspace(self, *, user_id: str, source_slug: str, target_slug: str, mode: str) -> None:
        source_root = profile_workspace_root(user_id, source_slug)
        target_root = ensure_profile_workspace(user_id, target_slug)
        normalized_mode = str(mode or "settings").strip().lower()
        if normalized_mode not in {"blank", "settings", "all"}:
            raise ValueError("Clone mode must be one of: blank, settings, all.")
        if normalized_mode == "blank":
            return
        if normalized_mode == "all":
            for child in source_root.iterdir():
                if child.name in {".uploads", ".browser", ".attachments"}:
                    continue
                self._copy_path(child, target_root / child.name)
            return
        for child in source_root.iterdir():
            if child.name in PROFILE_SETTINGS_DIRS:
                self._copy_path(child, target_root / child.name)
                continue
            if child.is_file() and child.suffix.lower() == ".md":
                self._copy_path(child, target_root / child.name)

    @staticmethod
    def _copy_path(source: Path, target: Path) -> None:
        if source.is_dir():
            shutil.copytree(source, target, dirs_exist_ok=True)
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)

    @staticmethod
    def _delete_profile_workspace(*, user_id: str, profile_slug: str) -> None:
        root = profile_workspace_root(user_id, profile_slug)
        if root.exists():
            shutil.rmtree(root)


profile_service = ProfileService()
