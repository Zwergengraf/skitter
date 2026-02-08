from __future__ import annotations

import hashlib
import json
import logging
import mimetypes
import re
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
from .llm import build_llm, resolve_model, resolve_model_name
from .prompting import build_system_prompt
from ..tools.approval_service import ToolApprovalService
from ..core.embeddings import EmbeddingsClient
from ..data.db import SessionLocal
from ..data.repositories import Repository

_MEDIA_DIRECTIVE_RE = re.compile(r"^\s*MEDIA\s*:\s*(.+?)\s*$", re.IGNORECASE)
_logger = logging.getLogger(__name__)


class AgentRuntime:
    def __init__(
        self,
        event_bus: EventBus,
        graph: Optional[object] = None,
        approval_service: ToolApprovalService | None = None,
        scheduler_service=None,
    ) -> None:
        self.event_bus = event_bus
        self._approval_service = approval_service
        self._scheduler_service = scheduler_service
        self._fixed_graph = graph
        self._graphs: dict[str, object] = {}
        if graph is None:
            default_name = resolve_model_name(None, purpose="main")
            self._graphs[default_name] = build_graph(
                approval_service=approval_service,
                scheduler_service=scheduler_service,
                model_name=default_name,
                purpose="main",
            )
        self._history: dict[str, list[BaseMessage]] = defaultdict(list)
        self._session_models: dict[str, str] = {}

    def set_scheduler_service(self, scheduler_service) -> None:
        self._scheduler_service = scheduler_service
        # Force graph rebuild so scheduler-aware tools are wired correctly.
        self._graphs.clear()

    async def handle_message(self, session_id: str, envelope: MessageEnvelope) -> AgentResponse:
        if not envelope.text and not envelope.command and not envelope.attachments:
            return AgentResponse(text="")
        if not settings.models:
            return AgentResponse(text="LLM is not configured. Define at least one model in config.yaml.")

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
            model_name = await self._get_session_model(session_id, envelope)
            await self._compact_history_for_context(session_id, history, model_name)
            graph = self._get_graph(model_name, purpose="heartbeat" if envelope.origin == "heartbeat" else "main")
            result = await graph.ainvoke({"messages": history})
            messages = result.get("messages", history)
            self._history[session_id] = list(messages)

            response: object = ""
            for msg in reversed(messages):
                if isinstance(msg, AIMessage):
                    response = msg.content
                    break

            usage = self._collect_usage(messages, envelope.message_id)
            if usage is not None:
                await self._record_usage(session_id, internal_user_id, model_name, usage)
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
        response_text = self._message_content_to_text(response)
        attachments = self._extract_attachments(internal_user_id, messages, envelope.message_id)
        response_text, media_attachments = self._extract_media_directive_attachments(internal_user_id, response_text)
        if media_attachments:
            seen_paths = {a.path for a in attachments if a.path}
            for attachment in media_attachments:
                if attachment.path and attachment.path in seen_paths:
                    continue
                attachments.append(attachment)
                if attachment.path:
                    seen_paths.add(attachment.path)
        attachments, dropped_count = self._dedupe_attachments(attachments)
        if dropped_count > 0:
            _logger.debug(
                "Removed %d duplicate attachment(s) for session=%s message_id=%s",
                dropped_count,
                session_id,
                envelope.message_id,
            )
        cleaned = self._strip_attachment_paths(response_text) if attachments else response_text
        return AgentResponse(text=cleaned, attachments=attachments)

    def clear_history(self, session_id: str) -> None:
        self._history.pop(session_id, None)

    def set_session_model(self, session_id: str, model_name: str) -> None:
        if model_name:
            self._session_models[session_id] = model_name

    async def _get_session_model(self, session_id: str, envelope: MessageEnvelope) -> str:
        if envelope.origin == "heartbeat":
            return resolve_model_name(None, purpose="heartbeat")
        cached = self._session_models.get(session_id)
        if cached:
            return cached
        async with SessionLocal() as session:
            repo = Repository(session)
            record = await repo.get_session(session_id)
        if record and getattr(record, "model", None):
            self._session_models[session_id] = record.model
            return record.model
        default_name = resolve_model_name(None, purpose="main")
        self._session_models[session_id] = default_name
        return default_name

    def _get_graph(self, model_name: str, purpose: str = "main") -> object:
        if self._fixed_graph is not None:
            return self._fixed_graph
        if model_name not in self._graphs:
            self._graphs[model_name] = build_graph(
                approval_service=self._approval_service,
                scheduler_service=self._scheduler_service,
                model_name=model_name,
                purpose=purpose,
            )
        return self._graphs[model_name]

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

    def _is_tool_chatter_message(self, msg: BaseMessage) -> bool:
        if isinstance(msg, ToolMessage):
            return True
        if isinstance(msg, AIMessage):
            tool_calls = getattr(msg, "tool_calls", None)
            if tool_calls:
                return True
            meta = getattr(msg, "additional_kwargs", None) or {}
            if isinstance(meta, dict) and meta.get("tool_calls"):
                return True
        return False

    def _is_chat_message(self, msg: BaseMessage) -> bool:
        if isinstance(msg, HumanMessage):
            return True
        if isinstance(msg, AIMessage) and not self._is_tool_chatter_message(msg):
            return True
        return False

    def _trim_tool_messages(self, history: list[BaseMessage]) -> None:
        max_tool = max(0, int(settings.context_max_tool_messages))
        if max_tool <= 0:
            history[:] = [msg for msg in history if not self._is_tool_chatter_message(msg)]
            return
        tool_indices = [idx for idx, msg in enumerate(history) if self._is_tool_chatter_message(msg)]
        if len(tool_indices) <= max_tool:
            return
        keep_indices = set(tool_indices[-max_tool:])
        compacted: list[BaseMessage] = []
        for idx, msg in enumerate(history):
            if self._is_tool_chatter_message(msg) and idx not in keep_indices:
                continue
            compacted.append(msg)
        history[:] = compacted

    def _extract_tool_call_ids(self, msg: AIMessage) -> set[str]:
        ids: set[str] = set()
        tool_calls = getattr(msg, "tool_calls", None)
        if isinstance(tool_calls, list):
            for call in tool_calls:
                if isinstance(call, dict):
                    call_id = call.get("id")
                    if call_id:
                        ids.add(str(call_id))
                else:
                    call_id = getattr(call, "id", None)
                    if call_id:
                        ids.add(str(call_id))
        meta = getattr(msg, "additional_kwargs", None) or {}
        if isinstance(meta, dict):
            raw_calls = meta.get("tool_calls")
            if isinstance(raw_calls, list):
                for call in raw_calls:
                    if isinstance(call, dict):
                        call_id = call.get("id")
                        if call_id:
                            ids.add(str(call_id))
        return ids

    def _sanitize_tool_sequence(self, history: list[BaseMessage]) -> None:
        ai_tool_ids_by_index: dict[int, set[str]] = {}
        seen_ai_tool_ids: set[str] = set()
        responded_ids: set[str] = set()

        for idx, msg in enumerate(history):
            if isinstance(msg, AIMessage):
                call_ids = self._extract_tool_call_ids(msg)
                if call_ids:
                    ai_tool_ids_by_index[idx] = call_ids
                    seen_ai_tool_ids.update(call_ids)
                continue
            if isinstance(msg, ToolMessage):
                tool_call_id = getattr(msg, "tool_call_id", None)
                if tool_call_id and str(tool_call_id) in seen_ai_tool_ids:
                    responded_ids.add(str(tool_call_id))

        valid_ai_indices: set[int] = set()
        valid_tool_ids: set[str] = set()
        for idx, call_ids in ai_tool_ids_by_index.items():
            if call_ids and call_ids.issubset(responded_ids):
                valid_ai_indices.add(idx)
                valid_tool_ids.update(call_ids)

        sanitized: list[BaseMessage] = []
        for idx, msg in enumerate(history):
            if isinstance(msg, AIMessage):
                call_ids = self._extract_tool_call_ids(msg)
                if call_ids and idx not in valid_ai_indices:
                    continue
                sanitized.append(msg)
                continue
            if isinstance(msg, ToolMessage):
                tool_call_id = getattr(msg, "tool_call_id", None)
                if not tool_call_id or str(tool_call_id) not in valid_tool_ids:
                    continue
                sanitized.append(msg)
                continue
            sanitized.append(msg)
        history[:] = sanitized

    def _message_content_to_text(self, content: object) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                    continue
                if isinstance(item, dict):
                    kind = str(item.get("type") or "").lower()
                    if kind == "text":
                        parts.append(str(item.get("text") or ""))
                    elif kind == "image":
                        parts.append("[image]")
                    elif kind == "file":
                        parts.append("[file]")
                    else:
                        parts.append(str(item))
                    continue
                parts.append(str(item))
            return "\n".join(part for part in parts if part).strip()
        return str(content)

    def _message_datetime(self, msg: BaseMessage) -> datetime | None:
        meta = getattr(msg, "additional_kwargs", None) or {}
        if not isinstance(meta, dict):
            return None
        raw = meta.get("_db_created_at")
        if not raw:
            return None
        if isinstance(raw, datetime):
            return raw
        if not isinstance(raw, str):
            return None
        try:
            return datetime.fromisoformat(raw)
        except ValueError:
            return None

    def _summary_checkpoint(self, msg: BaseMessage) -> datetime | None:
        meta = getattr(msg, "additional_kwargs", None) or {}
        if not isinstance(meta, dict):
            return None
        raw = meta.get("summary_checkpoint")
        if isinstance(raw, datetime):
            return raw
        if isinstance(raw, str):
            try:
                return datetime.fromisoformat(raw)
            except ValueError:
                return None
        return None

    async def _summarize_chat_messages(
        self,
        previous_summary: str,
        messages: list[BaseMessage],
        model_name: str,
    ) -> str:
        lines: list[str] = []
        for msg in messages:
            role = "user" if isinstance(msg, HumanMessage) else "assistant"
            text = self._message_content_to_text(getattr(msg, "content", ""))
            if not text:
                continue
            lines.append(f"{role}: {text}")
        if not lines:
            return previous_summary.strip()
        transcript = "\n".join(lines)
        if not settings.models:
            merged = f"{previous_summary.strip()}\n{transcript}".strip()
            return merged[:4000]
        llm = build_llm(model_name=model_name, purpose="main")
        prompt = [
            SystemMessage(
                content=(
                    "You distill older conversation context for a chat agent. "
                    "Produce a short summary of only the most important facts, decisions, and events. Do not include unimportant details (e.g. IDs), small talk or intermediary steps."
                    "Avoid speculation and keep it compact."
                )
            ),
            HumanMessage(
                content=(
                    f"Existing summary:\n{previous_summary or '(none)'}\n\n"
                    f"New older messages to fold in:\n{transcript}\n\n"
                    "Return an updated merged summary only."
                )
            ),
        ]
        try:
            result = await llm.ainvoke(prompt)
            text = self._message_content_to_text(getattr(result, "content", ""))
            return text.strip() or previous_summary.strip()
        except Exception:
            merged = f"{previous_summary.strip()}\n{transcript}".strip()
            return merged[:4000]

    async def _compact_history_for_context(self, session_id: str, history: list[BaseMessage], model_name: str) -> None:
        self._sanitize_tool_sequence(history)
        self._trim_tool_messages(history)
        self._sanitize_tool_sequence(history)
        max_chat = max(1, int(settings.context_max_chat_messages))
        compact_every = max(1, int(settings.context_compact_every_messages))
        chat_indices = [idx for idx, msg in enumerate(history) if self._is_chat_message(msg)]
        overflow_count = len(chat_indices) - max_chat
        if overflow_count <= 0:
            return
        # Avoid summarizing on every turn once the cap is reached.
        # We summarize only when the overflow has accumulated into a batch.
        if overflow_count < compact_every:
            return
        old_chat_indices = chat_indices[:-max_chat]
        if not old_chat_indices:
            return

        summary_indices = [
            idx
            for idx, msg in enumerate(history)
            if isinstance(msg, SystemMessage) and msg.additional_kwargs.get("conversation_summary")
        ]
        previous_summary = ""
        previous_checkpoint: datetime | None = None
        if summary_indices:
            latest_summary = history[summary_indices[-1]]
            previous_summary = self._message_content_to_text(latest_summary.content)
            previous_checkpoint = self._summary_checkpoint(latest_summary)
        to_summarize = [history[idx] for idx in old_chat_indices if idx < len(history)]
        new_slice: list[BaseMessage] = []
        for msg in to_summarize:
            dt = self._message_datetime(msg)
            if previous_checkpoint is not None and dt is not None and dt <= previous_checkpoint:
                continue
            new_slice.append(msg)
        new_summary = await self._summarize_chat_messages(previous_summary, new_slice, model_name)
        if not new_slice and previous_summary:
            new_summary = previous_summary
        if not new_summary and not previous_summary:
            return

        checkpoint = previous_checkpoint
        for msg in new_slice:
            dt = self._message_datetime(msg)
            if dt is None:
                continue
            if checkpoint is None or dt > checkpoint:
                checkpoint = dt

        remove_indices = sorted(set(old_chat_indices + summary_indices), reverse=True)
        for idx in remove_indices:
            if 0 <= idx < len(history):
                del history[idx]

        insert_idx = 0
        for idx, msg in enumerate(history):
            if isinstance(msg, SystemMessage) and msg.additional_kwargs.get("system_prompt"):
                insert_idx = idx + 1
                break
        history.insert(
            insert_idx,
            SystemMessage(
                content=new_summary,
                additional_kwargs={
                    "conversation_summary": True,
                    "summary_checkpoint": checkpoint.isoformat() if checkpoint else "",
                },
            ),
        )
        async with SessionLocal() as session:
            repo = Repository(session)
            await repo.set_session_context_summary(session_id, new_summary, checkpoint)

    def _usage_from_message(self, msg: AIMessage) -> tuple[int, int, int] | None:
        usage_meta = getattr(msg, "usage_metadata", None)
        if isinstance(usage_meta, dict):
            input_tokens = usage_meta.get("input_tokens") or usage_meta.get("prompt_tokens") or 0
            output_tokens = usage_meta.get("output_tokens") or usage_meta.get("completion_tokens") or 0
            total_tokens = usage_meta.get("total_tokens")
            if total_tokens is None:
                total_tokens = input_tokens + output_tokens
            if input_tokens or output_tokens or total_tokens:
                return int(input_tokens), int(output_tokens), int(total_tokens)
        meta = getattr(msg, "response_metadata", None) or {}
        if isinstance(meta, dict):
            token_usage = meta.get("token_usage") or meta.get("usage") or {}
            if isinstance(token_usage, dict):
                input_tokens = token_usage.get("prompt_tokens") or token_usage.get("input_tokens") or 0
                output_tokens = token_usage.get("completion_tokens") or token_usage.get("output_tokens") or 0
                total_tokens = token_usage.get("total_tokens")
                if total_tokens is None:
                    total_tokens = input_tokens + output_tokens
                if input_tokens or output_tokens or total_tokens:
                    return int(input_tokens), int(output_tokens), int(total_tokens)
        return None

    def _collect_usage(self, messages: list[BaseMessage], message_id: str | None) -> dict | None:
        if not messages:
            return None
        start_idx = None
        if message_id:
            for idx in range(len(messages) - 1, -1, -1):
                msg = messages[idx]
                if isinstance(msg, HumanMessage) and msg.additional_kwargs.get("message_id") == message_id:
                    start_idx = idx
                    break
        slice_messages = messages[start_idx + 1 :] if start_idx is not None else messages
        total_input = 0
        total_output = 0
        total_tokens = 0
        last = None
        for msg in slice_messages:
            if not isinstance(msg, AIMessage):
                continue
            usage = self._usage_from_message(msg)
            if usage is None:
                continue
            input_tokens, output_tokens, total = usage
            total_input += input_tokens
            total_output += output_tokens
            total_tokens += total
            last = usage
        if total_input == 0 and total_output == 0 and total_tokens == 0:
            return None
        last_input, last_output, last_total = last if last else (0, 0, 0)
        return {
            "input_tokens": total_input,
            "output_tokens": total_output,
            "total_tokens": total_tokens,
            "last_input_tokens": last_input,
            "last_output_tokens": last_output,
            "last_total_tokens": last_total,
        }

    async def _record_usage(
        self,
        session_id: str,
        user_id: str,
        model_name: str,
        usage: dict,
    ) -> None:
        try:
            resolved = resolve_model(model_name)
        except RuntimeError:
            return
        input_tokens = int(usage.get("input_tokens") or 0)
        output_tokens = int(usage.get("output_tokens") or 0)
        total_tokens = int(usage.get("total_tokens") or 0)
        cost = (input_tokens / 1_000_000.0) * resolved.input_cost_per_1m + (
            output_tokens / 1_000_000.0
        ) * resolved.output_cost_per_1m
        async with SessionLocal() as session:
            repo = Repository(session)
            await repo.record_llm_usage(
                session_id=session_id,
                user_id=user_id,
                model=resolved.name,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=total_tokens,
                cost=cost,
                last_input_tokens=int(usage.get("last_input_tokens") or 0),
                last_output_tokens=int(usage.get("last_output_tokens") or 0),
                last_total_tokens=int(usage.get("last_total_tokens") or 0),
            )

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

        if not settings.models:
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
            session_record = await repo.get_session(session_id)
            records = await repo.list_messages(session_id)
        history: list[BaseMessage] = []
        for record in records:
            role = record.role
            content = record.content
            meta = dict(record.meta or {})
            meta["_db_message_id"] = record.id
            meta["_db_created_at"] = record.created_at.isoformat()
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
        if session_record and session_record.context_summary:
            checkpoint = session_record.context_summary_checkpoint
            history.insert(
                0,
                SystemMessage(
                    content=session_record.context_summary,
                    additional_kwargs={
                        "conversation_summary": True,
                        "summary_checkpoint": checkpoint.isoformat() if checkpoint else "",
                    },
                ),
            )
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
        seen_resolved_paths: set[str] = set()
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
                path_key = str(resolved)
                if path_key in seen_resolved_paths:
                    continue
                try:
                    payload = resolved.read_bytes()
                except OSError:
                    continue
                seen_resolved_paths.add(path_key)
                attachments.append(
                    Attachment(
                        filename=resolved.name,
                        content_type="image/png",
                        bytes_data=payload,
                        path=str(resolved),
                    )
                )
        return attachments

    def _extract_media_directive_attachments(self, user_id: str, text: str) -> tuple[str, list[Attachment]]:
        if not text:
            return text, []
        attachments: list[Attachment] = []
        seen: set[str] = set()
        kept_lines: list[str] = []
        for line in text.splitlines():
            match = _MEDIA_DIRECTIVE_RE.match(line)
            if not match:
                kept_lines.append(line)
                continue
            raw_path = self._normalize_media_path(match.group(1))
            if not raw_path:
                continue
            resolved = self._resolve_user_workspace_file(user_id, raw_path)
            if not resolved or not resolved.exists() or not resolved.is_file():
                continue
            path_key = str(resolved)
            if path_key in seen:
                continue
            seen.add(path_key)
            mime_type, _ = mimetypes.guess_type(resolved.name)
            attachments.append(
                Attachment(
                    filename=resolved.name,
                    content_type=mime_type or "application/octet-stream",
                    path=path_key,
                )
            )
        cleaned = "\n".join(kept_lines).strip()
        return cleaned, attachments

    def _dedupe_attachments(self, attachments: list[Attachment]) -> tuple[list[Attachment], int]:
        unique: list[Attachment] = []
        seen: set[tuple] = set()
        dropped = 0
        for attachment in attachments:
            key = self._attachment_key(attachment)
            if key in seen:
                dropped += 1
                continue
            seen.add(key)
            unique.append(attachment)
        return unique, dropped

    def _attachment_key(self, attachment: Attachment) -> tuple:
        if attachment.path:
            return ("path", str(Path(attachment.path).resolve()))
        if attachment.bytes_data:
            digest = hashlib.sha256(attachment.bytes_data).hexdigest()
            return ("bytes", digest, attachment.filename)
        if attachment.url:
            return ("url", attachment.url, attachment.filename)
        return ("name", attachment.filename)

    def _normalize_media_path(self, raw_path: str) -> str:
        value = str(raw_path or "").strip().strip("`").strip()
        if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
            value = value[1:-1].strip()
        return value

    def _resolve_user_workspace_file(self, user_id: str, raw_path: str) -> Path | None:
        if not raw_path:
            return None
        candidate_path = raw_path.strip()
        if candidate_path.startswith("sandbox:/workspace/"):
            candidate_path = "/workspace/" + candidate_path.removeprefix("sandbox:/workspace/")

        from .workspace import user_workspace_root

        workspace = user_workspace_root(user_id).resolve()
        as_path = Path(candidate_path)
        if candidate_path.startswith("/workspace/"):
            candidate = workspace / Path(candidate_path).relative_to("/workspace")
        elif as_path.is_absolute():
            candidate = as_path
        else:
            candidate = workspace / as_path
        try:
            resolved = candidate.resolve(strict=False)
        except OSError:
            return None
        try:
            resolved.relative_to(workspace)
        except ValueError:
            return None
        return resolved

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
