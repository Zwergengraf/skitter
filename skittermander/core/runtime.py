from __future__ import annotations

import json
import uuid
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Optional

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage

from .config import settings
from .events import EventBus
from .graph import (
    build_graph,
    current_user_id,
    reset_current_channel_id,
    reset_current_origin,
    reset_current_session_id,
    reset_current_user_id,
    set_current_channel_id,
    set_current_origin,
    set_current_session_id,
    set_current_user_id,
)
from .models import AgentResponse, Attachment, MessageEnvelope, StreamEvent
from .llm import build_llm
from .prompting import build_system_prompt
from ..tools.approval_service import ToolApprovalService
from ..core.embeddings import EmbeddingsClient
from ..data.db import SessionLocal
from ..data.repositories import Repository


class AgentRuntime:
    def __init__(
        self,
        event_bus: EventBus,
        graph: Optional[object] = None,
        approval_service: ToolApprovalService | None = None,
        scheduler_service=None,
    ) -> None:
        self.event_bus = event_bus
        self.graph = graph or build_graph(approval_service=approval_service, scheduler_service=scheduler_service)
        self._history: dict[str, list[BaseMessage]] = defaultdict(list)

    async def handle_message(self, session_id: str, envelope: MessageEnvelope) -> AgentResponse:
        if not envelope.text and not envelope.command and not envelope.attachments:
            return AgentResponse(text="")
        if not settings.openai_api_key:
            return AgentResponse(text="LLM is not configured. Set SKITTER_OPENAI_API_KEY to enable responses.")

        content = envelope.text
        is_command = False
        attachments_meta: list[dict] = []
        if envelope.command:
            is_command = True
            content = f"/{envelope.command} {envelope.metadata}".strip()
        elif envelope.attachments:
            attachments_meta = self._serialize_attachments(envelope.attachments)

        run_id = str(uuid.uuid4())
        await self.event_bus.publish(
            StreamEvent(
                session_id=session_id,
                type="message_received",
                data={"run_id": run_id, "message_id": envelope.message_id, "user_id": envelope.user_id},
                created_at=datetime.utcnow(),
            )
        )
        token_session = set_current_session_id(session_id)
        token_channel = set_current_channel_id(envelope.channel_id)
        internal_user_id = envelope.metadata.get("internal_user_id", envelope.user_id)
        token_user = set_current_user_id(internal_user_id)
        token_origin = set_current_origin(envelope.origin)
        try:
            await self._ensure_history(session_id)
            history = self._history[session_id]
            self._ensure_system_prompt(history, internal_user_id)
            if content or attachments_meta:
                last = history[-1] if history else None
                last_id = getattr(last, "additional_kwargs", {}).get("message_id") if last else None
                if last_id != envelope.message_id:
                    if attachments_meta:
                        blocks = self._build_content_blocks(content, attachments_meta)
                        history.append(
                            HumanMessage(
                                content_blocks=blocks,
                                additional_kwargs={"message_id": envelope.message_id},
                            )
                        )
                    else:
                        history.append(
                            HumanMessage(content=content, additional_kwargs={"message_id": envelope.message_id})
                        )
            result = await self.graph.ainvoke({"messages": history})
            messages = result.get("messages", history)
            self._history[session_id] = list(messages)

            response = ""
            for msg in reversed(messages):
                if isinstance(msg, AIMessage):
                    response = msg.content
                    break
        finally:
            reset_current_origin(token_origin)
            reset_current_user_id(token_user)
            reset_current_channel_id(token_channel)
            reset_current_session_id(token_session)
        await self.event_bus.publish(
            StreamEvent(
                session_id=session_id,
                type="message_response",
                data={"run_id": run_id, "response": response},
                created_at=datetime.utcnow(),
            )
        )
        attachments = self._extract_attachments(internal_user_id, messages, envelope.message_id)
        cleaned = self._strip_attachment_paths(response) if attachments else response
        return AgentResponse(text=cleaned, attachments=attachments)

    def clear_history(self, session_id: str) -> None:
        self._history.pop(session_id, None)

    def drop_messages_since(self, session_id: str, message_id: str) -> None:
        if not message_id:
            return
        history = self._history.get(session_id)
        if not history:
            return
        for idx in range(len(history) - 1, -1, -1):
            msg = history[idx]
            if isinstance(msg, HumanMessage) and msg.additional_kwargs.get("message_id") == message_id:
                del history[idx:]
                break

    async def summarize_session(self, session_id: str) -> str:
        await self._ensure_history(session_id)
        messages = self._history.get(session_id, [])
        if not messages:
            return "No messages to summarize."
        transcript_lines = []
        for msg in messages[-50:]:
            role = msg.type if hasattr(msg, "type") else msg.__class__.__name__
            content = msg.content if hasattr(msg, "content") else str(msg)
            transcript_lines.append(f"{role}: {content}")
        transcript = "\n".join(transcript_lines)

        if not settings.openai_api_key:
            return transcript

        llm = build_llm()
        prompt = [
            SystemMessage(
                content=(
                    "Summarize the session focusing only on important facts, events, decisions, and user preferences. "
                    "Use concise bullet points."
                )
            ),
            HumanMessage(content=transcript),
        ]
        result = await llm.ainvoke(prompt)
        return result.content if hasattr(result, "content") else str(result)

    async def _ensure_history(self, session_id: str) -> None:
        if session_id in self._history:
            return
        async with SessionLocal() as session:
            repo = Repository(session)
            records = await repo.list_messages(session_id)
        history: list[BaseMessage] = []
        for record in records:
            role = record.role
            content = record.content
            meta = record.meta or {}
            if role == "user":
                attachments_meta = meta.get("attachments")
                if isinstance(attachments_meta, list) and attachments_meta:
                    blocks = self._build_content_blocks(content, attachments_meta)
                    history.append(HumanMessage(content_blocks=blocks, additional_kwargs=meta))
                else:
                    history.append(HumanMessage(content=content, additional_kwargs=meta))
            elif role == "assistant":
                history.append(AIMessage(content=content, additional_kwargs=meta))
            elif role == "system":
                history.append(SystemMessage(content=content, additional_kwargs=meta))
        self._history[session_id] = history

    def _ensure_system_prompt(self, history: list[BaseMessage], user_id: str) -> None:
        prompt = build_system_prompt(user_id)
        history[:] = [
            msg
            for msg in history
            if not (isinstance(msg, SystemMessage) and msg.additional_kwargs.get("system_prompt"))
        ]
        if not prompt:
            return
        print("Using system prompt:"
              f"\n{'-'*40}\n{prompt}\n{'-'*40}")
        history.insert(0, SystemMessage(content=prompt, additional_kwargs={"system_prompt": True}))

    def _serialize_attachments(self, attachments: list[Attachment]) -> list[dict]:
        serialized: list[dict] = []
        for attachment in attachments:
            if not attachment.url:
                continue
            serialized.append(
                {
                    "filename": attachment.filename,
                    "url": attachment.url,
                    "content_type": attachment.content_type or "",
                }
            )
        return serialized

    def _build_content_blocks(self, content: str, attachments: list[dict]) -> list[dict]:
        blocks: list[dict] = []
        if content:
            blocks.append({"type": "text", "text": content})
        else:
            blocks.append({"type": "text", "text": "User uploaded files."})

        for attachment in attachments:
            url = str(attachment.get("url") or "")
            if not url:
                continue
            filename = str(attachment.get("filename") or "")
            content_type = str(attachment.get("content_type") or "").lower()
            ext = Path(filename).suffix.lower()
            label_parts = []
            if filename:
                label_parts.append(f"Filename: {filename}")
            if content_type:
                label_parts.append(f"Type: {content_type}")
            label = " ".join(label_parts) if label_parts else "Attachment"
            blocks.append({"type": "text", "text": f"{label}. URL: {url}"})
            if content_type.startswith("image/") or ext in {".png", ".jpg", ".jpeg", ".gif", ".webp"}:
                block: dict[str, object] = {"type": "image", "url": url}
                if content_type:
                    block["mime_type"] = content_type
                blocks.append(block)
                continue
        return blocks

    def _extract_attachments(
        self, user_id: str, messages: list[BaseMessage], message_id: str
    ) -> list[Attachment]:
        attachments: list[Attachment] = []
        image_exts = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
        start_index = 0
        if message_id:
            for idx in range(len(messages) - 1, -1, -1):
                msg = messages[idx]
                if isinstance(msg, HumanMessage) and msg.additional_kwargs.get("message_id") == message_id:
                    start_index = idx + 1
                    break
        for msg in messages[start_index:]:
            if not isinstance(msg, ToolMessage):
                continue
            content = msg.content if isinstance(msg.content, str) else ""
            content = content.strip()
            if not content.startswith("{"):
                continue
            try:
                data = json.loads(content)
            except json.JSONDecodeError:
                continue
            paths: list[str] = []
            if isinstance(data, dict):
                if "screenshot_path" in data:
                    paths.append(data["screenshot_path"])
                if "screenshot_paths" in data and isinstance(data["screenshot_paths"], list):
                    paths.extend([str(p) for p in data["screenshot_paths"]])
                file_path = data.get("file_path")
                if isinstance(file_path, str):
                    content_type = str(data.get("content_type", "")).lower()
                    ext = Path(file_path).suffix.lower()
                    if content_type.startswith("image/") or ext in image_exts:
                        paths.append(file_path)
                if "file_paths" in data and isinstance(data["file_paths"], list):
                    for item in data["file_paths"]:
                        if not isinstance(item, str):
                            continue
                        ext = Path(item).suffix.lower()
                        if ext in image_exts:
                            paths.append(item)
            for raw_path in paths:
                resolved = self._resolve_workspace_path(user_id, raw_path)
                if not resolved or not resolved.exists():
                    continue
                try:
                    payload = resolved.read_bytes()
                except OSError:
                    continue
                attachments.append(
                    Attachment(
                        filename=resolved.name,
                        content_type="image/png",
                        bytes_data=payload,
                        path=str(resolved),
                    )
                )
        return attachments

    def _resolve_workspace_path(self, user_id: str, raw_path: str) -> Path | None:
        if not raw_path:
            return None
        path = Path(raw_path)
        from .workspace import user_workspace_root

        workspace = user_workspace_root(user_id)
        if raw_path.startswith("/workspace/"):
            return workspace / Path(raw_path).relative_to("/workspace")
        if path.is_absolute():
            return path
        return workspace / path

    def _strip_attachment_paths(self, text: str) -> str:
        if not text:
            return text
        lines = []
        for line in text.splitlines():
            lowered = line.lower()
            if "sandbox:/workspace/screenshots" in lowered:
                continue
            if "screenshots/" in lowered and "](" in line:
                continue
            lines.append(line)
        cleaned = "\n".join(lines).strip()
        if cleaned:
            return cleaned
        return "Screenshot attached."
