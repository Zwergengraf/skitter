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
from .llm import resolve_model_name
from .workspace import user_workspace_root
from .models import MessageEnvelope


DeliverFunc = Callable[[str, str, list], Awaitable[None]]


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

    def _load_heartbeat_content(self, user_id: str) -> str | None:
        path = user_workspace_root(user_id) / "HEARTBEAT.md"
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
            lock = self._locks.get(user.id)
            if lock is None:
                lock = asyncio.Lock()
                self._locks[user.id] = lock
            if lock.locked():
                continue
            asyncio.create_task(self._run_for_user(user.id, lock))

    async def _run_for_user(self, user_id: str, lock: asyncio.Lock) -> None:
        async with lock:
            try:
                async with SessionLocal() as session:
                    repo = Repository(session)
                    user = await repo.get_user_by_id(user_id)
                    if user is None or not user.approved:
                        return
                    meta = user.meta or {}
                    channel_id = meta.get("last_channel_id")
                    origin = meta.get("last_origin")
                    if not channel_id or (origin and origin != "discord"):
                        self._logger.warning(f"Skipping heartbeat for user {user_id} due to missing or unsupported channel/origin")
                        return
                    session_obj = await repo.get_latest_session_by_status(user_id, "heartbeat")
                    if session_obj is None:
                        model_name = resolve_model_name(None, purpose="heartbeat")
                        session_obj = await repo.create_session(user_id=user_id, status="heartbeat", model=model_name)
                    heartbeat_content = self._load_heartbeat_content(user_id)
                    if not heartbeat_content:
                        return
                    prompt = f"{settings.heartbeat_prompt}\n\n{heartbeat_content}".strip()
                    envelope = MessageEnvelope(
                        message_id=str(uuid.uuid4()),
                        channel_id=str(channel_id),
                        user_id=user.transport_user_id,
                        timestamp=datetime.utcnow(),
                        text=prompt,
                        origin="heartbeat",
                        metadata={"internal_user_id": user.id},
                    )

                # Keep heartbeat context isolated to persisted heartbeat messages only.
                self.runtime.clear_history(session_obj.id)
                response = await self.runtime.handle_message(session_obj.id, envelope)
                if response.text.strip() == "HEARTBEAT_OK" and not response.attachments:
                    self._logger.info(f"Heartbeat for user {user_id} returned HEARTBEAT_OK with no attachments, skipping delivery")
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

                if self.deliver is not None:
                    self._logger.info(f"Delivering heartbeat response to user {user_id} in channel {channel_id}")
                    await self.deliver(str(channel_id), response.text, response.attachments)

                async with SessionLocal() as session:
                    repo = Repository(session)
                    await repo.add_message(
                        session_obj.id,
                        role="assistant",
                        content=response.text,
                        metadata={"origin": "heartbeat", "response_to": envelope.message_id},
                    )
                    keep_messages = max(1, int(settings.heartbeat_history_runs)) * 2
                    await repo.prune_messages_keep_latest(session_obj.id, keep_messages)
                self.runtime.clear_history(session_obj.id)
            except Exception as exc:
                self._logger.exception("Heartbeat failed for user %s: %s", user_id, exc)
