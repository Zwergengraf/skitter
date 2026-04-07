from __future__ import annotations

import asyncio
import logging
import os
import shutil
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Optional

import docker
from docker.errors import DockerException
import httpx

from ..core.config import settings
from ..core.profile_context import current_agent_profile_slug
from ..core.profiles import DEFAULT_AGENT_PROFILE_SLUG
from ..core.workspace import ensure_profile_workspace, host_profile_workspace_root


@dataclass
class SandboxInfo:
    user_id: str
    profile_slug: str
    container_id: str
    name: str
    base_url: str
    last_activity: datetime


class SandboxManager:
    def __init__(self) -> None:
        self._client = None
        self._ready = False
        self._inside_docker = Path("/.dockerenv").exists()
        self._init_client()
        self._cache: Dict[str, SandboxInfo] = {}
        self._last_activity: Dict[str, datetime] = {}
        self._monitor_task: Optional[asyncio.Task] = None
        self._logger = logging.getLogger(__name__)
        self._locks: Dict[str, asyncio.Lock] = {}

    @staticmethod
    def _resolve_profile_slug(profile_slug: str | None = None) -> str:
        cleaned = str(profile_slug or current_agent_profile_slug() or DEFAULT_AGENT_PROFILE_SLUG).strip()
        return cleaned or DEFAULT_AGENT_PROFILE_SLUG

    def _workspace_key(self, user_id: str, profile_slug: str | None = None) -> str:
        return f"{user_id}:{self._resolve_profile_slug(profile_slug)}"

    def _init_client(self) -> None:
        try:
            self._client = docker.from_env()
            self._client.ping()
            self._ready = True
            return
        except DockerException:
            pass
        candidates = [
            "/var/run/docker.sock",
            str(Path.home() / ".docker/run/docker.sock"),
            str(Path.home() / ".docker/desktop/docker.sock"),
        ]
        for path in candidates:
            if not Path(path).exists():
                continue
            try:
                client = docker.DockerClient(base_url=f"unix://{path}")
                client.ping()
                self._client = client
                self._ready = True
                return
            except DockerException:
                continue
        self._client = None
        self._ready = False

    async def start(self) -> None:
        if not self._ready:
            self._logger.warning("Docker not available. Docker executor mode is unavailable.")
            return
        if settings.sandbox_network and not self._inside_docker:
            self._logger.warning(
                "Sandbox network is set but server is not running in Docker; using host port mapping instead."
            )
        if self._monitor_task is None:
            self._monitor_task = asyncio.create_task(self._monitor_loop())

    async def get_base_url(self, user_id: str, profile_slug: str | None = None) -> str:
        info = await self.ensure(user_id, profile_slug=profile_slug)
        await self.record_activity(user_id, profile_slug=profile_slug)
        return info.base_url

    async def record_activity(self, user_id: str, profile_slug: str | None = None) -> None:
        self._last_activity[self._workspace_key(user_id, profile_slug)] = datetime.utcnow()

    async def ensure(self, user_id: str, profile_slug: str | None = None) -> SandboxInfo:
        if not self._ready or self._client is None:
            raise RuntimeError("Docker is not available. Docker executor mode requires managed sandboxes.")
        resolved_profile_slug = self._resolve_profile_slug(profile_slug)
        cache_key = self._workspace_key(user_id, resolved_profile_slug)
        if cache_key in self._cache:
            info = self._cache[cache_key]
            return info
        lock = self._locks.get(cache_key)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[cache_key] = lock
        async with lock:
            if cache_key in self._cache:
                return self._cache[cache_key]
            return await asyncio.to_thread(self._ensure_sync, user_id, resolved_profile_slug)

    async def stop(self, user_id: str, profile_slug: str | None = None) -> None:
        resolved_profile_slug = self._resolve_profile_slug(profile_slug)
        cache_key = self._workspace_key(user_id, resolved_profile_slug)
        await asyncio.to_thread(self._stop_sync, user_id, resolved_profile_slug)
        self._cache.pop(cache_key, None)
        self._last_activity.pop(cache_key, None)

    def _container_name(self, user_id: str, profile_slug: str | None = None) -> str:
        safe_id = "".join(ch if ch.isalnum() or ch in ("-", "_") else "-" for ch in user_id)
        safe_slug = "".join(
            ch if ch.isalnum() or ch in ("-", "_") else "-"
            for ch in self._resolve_profile_slug(profile_slug)
        )
        return f"{settings.sandbox_container_prefix}-{safe_id}-{safe_slug}"

    def _ensure_sync(self, user_id: str, profile_slug: str) -> SandboxInfo:
        if self._client is None:
            raise RuntimeError("Docker is not available.")
        ensure_profile_workspace(user_id, profile_slug)
        host_workspace = self._resolve_host_workspace_root(user_id, profile_slug)
        host_workspace.mkdir(parents=True, exist_ok=True)
        browser_root = host_workspace / ".browser"
        browser_root.mkdir(parents=True, exist_ok=True)

        name = self._container_name(user_id, profile_slug)
        container = None
        for attempt in range(3):
            try:
                container = self._client.containers.get(name)
                container.reload()
                if container.status != "running":
                    try:
                        container.start()
                    except docker.errors.APIError:
                        container.remove(force=True)
                        container = None
                if container is not None and not self._inside_docker:
                    ports = container.attrs.get("NetworkSettings", {}).get("Ports", {})
                    mapping = ports.get(f"{settings.sandbox_port}/tcp")
                    if not mapping:
                        container.remove(force=True)
                        container = None
            except docker.errors.NotFound:
                container = None

            if container is None:
                try:
                    container = self._client.containers.run(
                        settings.sandbox_image,
                        name=name,
                        detach=True,
                        labels={
                            "skitter_user_id": user_id,
                            "skitter_profile_slug": profile_slug,
                            "skitter_role": "sandbox",
                        },
                        environment={
                            "SKITTER_WORKSPACE_ROOT": "/workspace",
                            "SKITTER_BROWSER_DATA_ROOT": "/browser-data",
                            "SKITTER_BROWSER_EXECUTABLE": settings.browser_executable or "",
                        },
                        volumes={
                            str(host_workspace): {"bind": "/workspace", "mode": "rw"},
                            str(browser_root): {"bind": "/browser-data", "mode": "rw"},
                        },
                        network=settings.sandbox_network if self._inside_docker else None,
                        ports=None
                        if settings.sandbox_network and self._inside_docker
                        else {f"{settings.sandbox_port}/tcp": None},
                    )
                except docker.errors.APIError as exc:
                    status_code = getattr(exc, "status_code", None)
                    if status_code == 409:
                        time.sleep(0.3 * (attempt + 1))
                        try:
                            container = self._client.containers.get(name)
                            container.reload()
                        except docker.errors.NotFound:
                            container = None
                    else:
                        if container is not None:
                            try:
                                container.remove(force=True)
                            except docker.errors.APIError:
                                pass
                        raise exc

            if container is not None:
                break

        if container is None:
            raise RuntimeError(f"Failed to ensure sandbox container for {user_id}")

        container.reload()
        base_url = self._base_url_for_container(container, user_id, profile_slug)
        self._wait_ready(base_url)
        cache_key = self._workspace_key(user_id, profile_slug)
        info = SandboxInfo(
            user_id=user_id,
            profile_slug=profile_slug,
            container_id=container.id,
            name=name,
            base_url=base_url,
            last_activity=self._last_activity.get(cache_key, datetime.utcnow()),
        )
        self._cache[cache_key] = info
        return info

    def _resolve_host_workspace_root(self, user_id: str, profile_slug: str) -> Path:
        """Resolve the host path used for sandbox bind mounts.

        When running inside Docker, prefer deriving the real host source path from
        this API container's `/workspace` bind mount. This avoids brittle CWD-based
        path construction and prevents accidental mounts from package subfolders.
        """
        fallback = host_profile_workspace_root(user_id, profile_slug)
        if not self._inside_docker or self._client is None:
            return fallback
        try:
            current_container_id = os.environ.get("HOSTNAME", "").strip()
            if not current_container_id:
                return fallback
            current = self._client.containers.get(current_container_id)
            current.reload()
            mounts = current.attrs.get("Mounts", [])
            for mount in mounts:
                if mount.get("Destination") == settings.workspace_root:
                    source = mount.get("Source")
                    if source:
                        return Path(source).resolve() / "users" / user_id / profile_slug
        except Exception:
            return fallback
        return fallback

    def _wait_ready(self, base_url: str) -> None:
        retries = max(1, settings.sandbox_connect_retries)
        backoff = max(0.1, settings.sandbox_connect_backoff)
        try:
            import httpx
        except Exception:
            return
        with httpx.Client(timeout=5) as client:
            for attempt in range(retries):
                try:
                    resp = client.get(f"{base_url}/health")
                    if resp.status_code == 200:
                        return
                except httpx.HTTPError:
                    pass
                if attempt < retries - 1:
                    time_sleep = backoff * (attempt + 1)
                    try:
                        import time

                        time.sleep(time_sleep)
                    except Exception:
                        pass

    def _stop_sync(self, user_id: str, profile_slug: str) -> None:
        name = self._container_name(user_id, profile_slug)
        try:
            container = self._client.containers.get(name)
        except docker.errors.NotFound:
            return
        try:
            container.stop(timeout=10)
        except docker.errors.APIError:
            pass

    def _base_url_for_container(self, container, user_id: str, profile_slug: str) -> str:
        if settings.sandbox_network and self._inside_docker:
            return f"http://{self._container_name(user_id, profile_slug)}:{settings.sandbox_port}"
        container.reload()
        ports = container.attrs.get("NetworkSettings", {}).get("Ports", {})
        mapping = ports.get(f"{settings.sandbox_port}/tcp")
        if not mapping:
            raise RuntimeError(
                f"Sandbox container {self._container_name(user_id, profile_slug)} has no reachable port mapping."
            )
        host_port = mapping[0].get("HostPort")
        return f"http://localhost:{host_port}"

    async def _monitor_loop(self) -> None:
        interval = max(5, settings.sandbox_idle_check_seconds)
        while True:
            await asyncio.sleep(interval)
            try:
                await self._check_idle_containers()
            except Exception as exc:  # pragma: no cover
                self._logger.exception("Sandbox idle check failed: %s", exc)

    async def _check_idle_containers(self) -> None:
        if self._client is None:
            return
        containers = await asyncio.to_thread(
            lambda: self._client.containers.list(filters={"label": "skitter_role=sandbox"})
        )
        now = datetime.utcnow()
        idle_delta = timedelta(seconds=max(60, settings.sandbox_idle_seconds))
        for container in containers:
            labels = container.labels or {}
            user_id = labels.get("skitter_user_id")
            profile_slug = labels.get("skitter_profile_slug") or DEFAULT_AGENT_PROFILE_SLUG
            if not user_id:
                continue
            workspace_key = self._workspace_key(user_id, profile_slug)
            last_activity = self._last_activity.get(workspace_key)
            if last_activity is None:
                self._last_activity[workspace_key] = now
                last_activity = now
            if now - last_activity < idle_delta:
                continue
            base_url = self._base_url_for_container(container, user_id, profile_slug)
            busy = await self._has_active_processes(base_url)
            if busy is not False:
                # Be conservative for unknown/error states; only stop when explicitly idle.
                continue
            await asyncio.to_thread(container.stop)
            self._cache.pop(workspace_key, None)

    async def _has_active_processes(self, base_url: str) -> bool | None:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(f"{base_url}/processes/active")
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            payload = resp.json()
            return bool(payload.get("active"))
        except Exception:
            # Be conservative: if the sandbox cannot be queried, assume it may still be busy.
            return True

    async def list_containers(self) -> list[dict]:
        if not self._ready or self._client is None:
            return []
        containers = await asyncio.to_thread(
            lambda: self._client.containers.list(all=True, filters={"label": "skitter_role=sandbox"})
        )
        results: list[dict] = []
        for container in containers:
            try:
                container.reload()
            except docker.errors.APIError:
                continue
            labels = container.labels or {}
            user_id = labels.get("skitter_user_id")
            profile_slug = labels.get("skitter_profile_slug") or DEFAULT_AGENT_PROFILE_SLUG
            ports = []
            mapping = container.attrs.get("NetworkSettings", {}).get("Ports", {})
            for key, host_info in mapping.items():
                if host_info:
                    for entry in host_info:
                        ports.append(f"{entry.get('HostIp','localhost')}:{entry.get('HostPort')}/{key}")
                else:
                    ports.append(str(key))
            created_at = None
            created_raw = container.attrs.get("Created")
            if created_raw:
                try:
                    created_at = datetime.fromisoformat(created_raw.replace("Z", "+00:00"))
                except ValueError:
                    created_at = None
            base_url = None
            if user_id:
                try:
                    base_url = self._base_url_for_container(container, user_id, profile_slug)
                except Exception:
                    base_url = None
            last_activity = self._last_activity.get(self._workspace_key(user_id, profile_slug)) if user_id else None
            results.append(
                {
                    "id": container.id,
                    "name": container.name,
                    "status": container.status,
                    "user_id": user_id,
                    "profile_slug": profile_slug,
                    "created_at": created_at,
                    "base_url": base_url,
                    "ports": ports,
                    "last_activity_at": last_activity,
                }
            )
        return results


sandbox_manager: SandboxManager | None = SandboxManager()
