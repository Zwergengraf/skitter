from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Optional

import docker
from docker.errors import DockerException
import httpx

from ..core.config import settings
from ..core.workspace import ensure_user_workspace, host_user_workspace_root
from ..data.db import SessionLocal
from ..data.repositories import Repository


@dataclass
class SandboxInfo:
    user_id: str
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
            self._logger.warning("Docker not available. Sandbox manager disabled.")
            return
        if settings.sandbox_network and not self._inside_docker:
            self._logger.warning(
                "Sandbox network is set but server is not running in Docker; using host port mapping instead."
            )
        if self._monitor_task is None:
            self._monitor_task = asyncio.create_task(self._monitor_loop())

    async def get_base_url(self, user_id: str) -> str:
        info = await self.ensure(user_id)
        await self.record_activity(user_id)
        return info.base_url

    async def record_activity(self, user_id: str) -> None:
        self._last_activity[user_id] = datetime.utcnow()

    async def ensure(self, user_id: str) -> SandboxInfo:
        if not self._ready or self._client is None:
            raise RuntimeError("Docker is not available. Set SKITTER_SANDBOX_BASE_URL to a running sandbox.")
        if user_id in self._cache:
            info = self._cache[user_id]
            return info
        lock = self._locks.get(user_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[user_id] = lock
        async with lock:
            if user_id in self._cache:
                return self._cache[user_id]
            return await asyncio.to_thread(self._ensure_sync, user_id)

    async def stop(self, user_id: str) -> None:
        await asyncio.to_thread(self._stop_sync, user_id)
        self._cache.pop(user_id, None)
        self._last_activity.pop(user_id, None)

    def _container_name(self, user_id: str) -> str:
        safe_id = "".join(ch if ch.isalnum() or ch in ("-", "_") else "-" for ch in user_id)
        return f"{settings.sandbox_container_prefix}-{safe_id}"

    def _ensure_sync(self, user_id: str) -> SandboxInfo:
        if self._client is None:
            raise RuntimeError("Docker is not available.")
        ensure_user_workspace(user_id)
        host_workspace = host_user_workspace_root(user_id)
        host_workspace.mkdir(parents=True, exist_ok=True)
        browser_root = host_workspace / "browser"
        browser_root.mkdir(parents=True, exist_ok=True)

        name = self._container_name(user_id)
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
                        labels={"skitter_user_id": user_id, "skitter_role": "sandbox"},
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
        base_url = self._base_url_for_container(container, user_id)
        self._wait_ready(base_url)
        info = SandboxInfo(
            user_id=user_id,
            container_id=container.id,
            name=name,
            base_url=base_url,
            last_activity=self._last_activity.get(user_id, datetime.utcnow()),
        )
        self._cache[user_id] = info
        return info

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

    def _stop_sync(self, user_id: str) -> None:
        name = self._container_name(user_id)
        try:
            container = self._client.containers.get(name)
        except docker.errors.NotFound:
            return
        try:
            container.stop(timeout=10)
        except docker.errors.APIError:
            pass

    def _base_url_for_container(self, container, user_id: str) -> str:
        if settings.sandbox_network and self._inside_docker:
            return f"http://{self._container_name(user_id)}:{settings.sandbox_port}"
        container.reload()
        ports = container.attrs.get("NetworkSettings", {}).get("Ports", {})
        mapping = ports.get(f"{settings.sandbox_port}/tcp")
        if not mapping:
            return settings.sandbox_base_url
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
            if not user_id:
                continue
            last_activity = self._last_activity.get(user_id)
            if last_activity is None:
                self._last_activity[user_id] = now
                last_activity = now
            if now - last_activity < idle_delta:
                continue
            base_url = self._base_url_for_container(container, user_id)
            busy = await self._has_active_tasks(user_id, base_url)
            if busy:
                continue
            await asyncio.to_thread(container.stop)
            self._cache.pop(user_id, None)

    async def _has_active_tasks(self, user_id: str, base_url: str) -> bool:
        async with SessionLocal() as session:
            repo = Repository(session)
            tasks = await repo.list_active_sandbox_tasks(user_id)
        if not tasks:
            return False
        pids = [task.pid for task in tasks]
        running = set()
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(f"{base_url}/tasks/status", json={"pids": pids})
                resp.raise_for_status()
                payload = resp.json()
                running = set(payload.get("running", []))
        except Exception:
            return True
        if running:
            return True
        async with SessionLocal() as session:
            repo = Repository(session)
            for task in tasks:
                await repo.update_sandbox_task(task.id, status="completed")
        return False

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
                    base_url = self._base_url_for_container(container, user_id)
                except Exception:
                    base_url = None
            last_activity = self._last_activity.get(user_id) if user_id else None
            results.append(
                {
                    "id": container.id,
                    "name": container.name,
                    "status": container.status,
                    "user_id": user_id,
                    "created_at": created_at,
                    "base_url": base_url,
                    "ports": ports,
                    "last_activity_at": last_activity,
                }
            )
        return results


sandbox_manager: SandboxManager | None = SandboxManager()
