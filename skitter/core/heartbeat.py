from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, time as dt_time
from zoneinfo import ZoneInfo
from typing import Awaitable, Callable, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from ..data.db import SessionLocal
from ..data.repositories import Repository
from .config import settings
from .conversation_scope import private_scope_id
from .llm import resolve_model_name
from .workspace import user_workspace_root
from .models import MessageEnvelope


DeliverFunc = Callable[[str, str, str, list], Awaitable[None]]


class HeartbeatService:
    def __init__(self, runtime, deliver: Optional[DeliverFunc] = None) -> None:
        self.runtime = runtime
        self.deliver = deliver
        self.scheduler = AsyncIOScheduler(timezone=settings.scheduler_timezone)
        self._started = False
        self._locks: dict[str, asyncio.Lock] = {}
        self._logger = logging.getLogger(__name__)

    def set_deliver(self, deliver: DeliverFunc) -> None:
        self.deliver = deliver

    async def start(self) -> None:
        if self._started:
            return
        if not settings.heartbeat_enabled:
            return
        interval = max(1, int(settings.heartbeat_interval_minutes))
        self.scheduler.add_job(self._run_all, "interval", minutes=interval, id="heartbeat", replace_existing=True)
        self.scheduler.start()
        self._started = True

    async def shutdown(self) -> None:
        if self._started:
            self.scheduler.shutdown(wait=False)
            self._started = False

    def _parse_time(self, value: str) -> Optional[dt_time]:
        if not value:
            return None
        try:
            return dt_time.fromisoformat(value)
        except ValueError:
            return None

    def _in_quiet_hours(self, now: datetime) -> bool:
        start = self._parse_time(settings.heartbeat_quiet_hours_start)
        end = self._parse_time(settings.heartbeat_quiet_hours_end)
        if start is None or end is None or start == end:
            return False
        current = now.timetz().replace(tzinfo=None)
        if start < end:
            return start <= current < end
        return current >= start or current < end

    def _load_heartbeat_content(self, user_id: str, profile_slug: str | None) -> str | None:
        path = user_workspace_root(user_id, profile_slug) / "HEARTBEAT.md"
        if not path.exists():
            return None
        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            return None
        meaningful = False
        for line in content.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("#"):
                continue
            meaningful = True
            break
        if not meaningful:
            return None
        return content.strip()

    async def _run_all(self) -> None:
        if not settings.heartbeat_enabled:
            return
        now = datetime.now(ZoneInfo(settings.scheduler_timezone))
        if self._in_quiet_hours(now):
            self._logger.info("Current time %s is within quiet hours, skipping heartbeat run", now)
            return

        async with SessionLocal() as session:
            repo = Repository(session)
            users = await repo.list_approved_users()

        for user in users:
            async with SessionLocal() as session:
                repo = Repository(session)
                profiles = await repo.list_agent_profiles(user.id)
            for profile in profiles:
                lock_key = f"{user.id}:{profile.id}"
                lock = self._locks.get(lock_key)
                if lock is None:
                    lock = asyncio.Lock()
                    self._locks[lock_key] = lock
                if lock.locked():
                    continue
                asyncio.create_task(self._run_for_profile(user.id, profile.id, profile.slug, lock))

    async def _run_for_profile(self, user_id: str, profile_id: str, profile_slug: str, lock: asyncio.Lock) -> None:
        async with lock:
            try:
                async with SessionLocal() as session:
                    repo = Repository(session)
                    user = await repo.get_user_by_id(user_id)
                    if user is None or not user.approved:
                        return
                    profile = await repo.get_agent_profile(profile_id)
                    if profile is None or profile.status == "archived":
                        return
                    meta = profile.meta or {}
                    target_origin = str(meta.get("last_private_origin") or meta.get("last_origin") or "").strip()
                    target_destination = str(meta.get("last_private_destination_id") or meta.get("last_channel_id") or "").strip()
                    session_obj = await repo.get_latest_session_by_status(user_id, "heartbeat", agent_profile_id=profile.id)
                    if session_obj is None:
                        model_name = resolve_model_name(None, purpose="heartbeat")
                        session_obj = await repo.create_session(
                            user_id=user_id,
                            agent_profile_id=profile.id,
                            status="heartbeat",
                            model=model_name,
                            origin="heartbeat",
                            scope_type="system",
                            scope_id=f"system:heartbeat:{profile.id}",
                        )
                    private_scope = private_scope_id(profile.id)
                    private_session = await repo.get_active_session_by_scope(
                        "private",
                        private_scope,
                        agent_profile_id=profile.id,
                    )
                    if private_session is None:
                        model_name = resolve_model_name(None, purpose="main")
                        private_session = await repo.create_session(
                            user.id,
                            agent_profile_id=profile.id,
                            status="active",
                            model=model_name,
                            origin=target_origin or "web",
                            scope_type="private",
                            scope_id=private_scope,
                        )
                    heartbeat_content = self._load_heartbeat_content(user_id, profile_slug)
                    if not heartbeat_content:
                        self._logger.info(
                            "No meaningful heartbeat content found for user %s profile %s, skipping heartbeat run",
                            user_id,
                            profile_slug,
                        )
                        return
                    prompt = f"{settings.heartbeat_prompt}\n\n{heartbeat_content}".strip()
                    envelope = MessageEnvelope(
                        message_id=str(uuid.uuid4()),
                        channel_id=target_destination or private_session.id,
                        user_id=user.transport_user_id,
                        timestamp=datetime.utcnow(),
                        text=prompt,
                        origin="heartbeat",
                        metadata={
                            "internal_user_id": user.id,
                            "agent_profile_id": profile.id,
                            "agent_profile_slug": profile.slug,
                            "scope_type": "system",
                            "scope_id": f"system:heartbeat:{profile.id}",
                            "is_private": False,
                        },
                    )

                # Keep heartbeat context isolated to persisted heartbeat messages only.
                self.runtime.clear_history(session_obj.id)
                response = await self.runtime.handle_message(session_obj.id, envelope)
                if response.text.strip() == "HEARTBEAT_OK" and not response.attachments:
                        self._logger.info(
                            "Heartbeat for user %s profile %s returned HEARTBEAT_OK with no attachments, skipping delivery",
                            user_id,
                            profile_slug,
                        )
                        self.runtime.drop_messages_since(session_obj.id, envelope.message_id)
                        self.runtime.clear_history(session_obj.id)
                        return

                async with SessionLocal() as session:
                    repo = Repository(session)
                    await repo.add_message(
                        session_obj.id,
                        role="user",
                        content=envelope.text,
                        metadata={
                            "origin": "heartbeat",
                            "message_id": envelope.message_id,
                            "internal_user_id": user.id,
                        },
                    )

                async with SessionLocal() as session:
                    repo = Repository(session)
                    assistant_meta: dict[str, object] = {"origin": "heartbeat", "response_to": envelope.message_id}
                    if response.run_id:
                        assistant_meta["run_id"] = response.run_id
                    if response.reasoning:
                        assistant_meta["reasoning"] = response.reasoning
                    await repo.add_message(
                        session_obj.id,
                        role="assistant",
                        content=response.text,
                        metadata=assistant_meta,
                    )
                    keep_messages = max(0, int(settings.heartbeat_history_runs)) * 2
                    await repo.prune_messages_keep_latest(session_obj.id, keep_messages)
                    private_meta: dict[str, object] = {
                        "origin": "heartbeat",
                        "heartbeat_session_id": session_obj.id,
                        "response_to": envelope.message_id,
                    }
                    if response.run_id:
                        private_meta["run_id"] = response.run_id
                    if response.reasoning:
                        private_meta["reasoning"] = response.reasoning
                    await repo.add_message(
                        private_session.id,
                        role="assistant",
                        content=response.text,
                        metadata=private_meta,
                    )
                self.runtime.clear_history(session_obj.id)
                if self.deliver is not None and target_origin and target_destination:
                    self._logger.info(
                        "Delivering heartbeat response to user %s profile %s via %s target %s",
                        user_id,
                        profile_slug,
                        target_origin,
                        target_destination,
                    )
                    try:
                        await self.deliver(target_origin, target_destination, response.text, response.attachments)
                    except Exception as exc:
                        self._logger.exception(
                            "Heartbeat delivery failed for user %s profile %s via %s target %s: %s",
                            user_id,
                            profile_slug,
                            target_origin,
                            target_destination,
                            exc,
                        )
            except Exception as exc:
                self._logger.exception("Heartbeat failed for user %s profile %s: %s", user_id, profile_slug, exc)
