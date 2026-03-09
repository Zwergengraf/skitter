from __future__ import annotations

import base64
import hashlib
import json
import logging
import mimetypes
import re
import asyncio
import uuid
from collections import defaultdict
from datetime import UTC, datetime
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
    reset_current_scope_id,
    reset_current_scope_type,
    reset_current_session_id,
    reset_current_user_id,
    reset_current_message_id,
    reset_current_run_id,
    set_current_channel_id,
    set_current_message_id,
    set_current_origin,
    set_current_run_id,
    set_current_scope_id,
    set_current_scope_type,
    set_current_session_id,
    set_current_user_id,
)
from .models import AgentResponse, Attachment, MessageEnvelope, StreamEvent
from .llm import ResolvedModel, build_llm, list_models, resolve_model, resolve_model_candidates, resolve_model_name
from .llm_debug import ThinkingDebugCallback
from .prompting import build_system_prompt
from .usage import collect_usage, record_usage
from .run_limits import RunBudgetUsageCallback, RunLimitsState, reset_current_run_limits, set_current_run_limits
from ..tools.approval_service import ToolApprovalService
from ..tools.executors import executor_router
from ..tools.sandbox_client import ToolRunnerClient
from ..core.embeddings import EmbeddingsClient
from ..data.db import SessionLocal
from ..data.repositories import Repository

_MEDIA_DIRECTIVE_RE = re.compile(
    r"MEDIA\s*:\s*(?P<path>`[^`\n]+`|'[^'\n]+'|\"[^\"\n]+\"|[^\s]+)",
    re.IGNORECASE,
)
_THINKING_TAG_RE = re.compile(r"<thinking>.*?</thinking>", re.IGNORECASE | re.DOTALL)
_REASONING_TAG_RE = re.compile(r"<reasoning>.*?</reasoning>", re.IGNORECASE | re.DOTALL)
_logger = logging.getLogger(__name__)


class AgentRuntime:
    def __init__(
        self,
        event_bus: EventBus,
        graph: Optional[object] = None,
        approval_service: ToolApprovalService | None = None,
        scheduler_service=None,
        job_service=None,
    ) -> None:
        self.event_bus = event_bus
        self._approval_service = approval_service
        self._scheduler_service = scheduler_service
        self._job_service = job_service
        self._fixed_graph = graph
        self._graphs: dict[tuple[str, str, str, str, str], object] = {}
        self._tool_client = ToolRunnerClient()
        self._history: dict[str, list[BaseMessage]] = defaultdict(list)
        self._session_models: dict[str, str] = {}

    def set_scheduler_service(self, scheduler_service) -> None:
        self._scheduler_service = scheduler_service
        # Force graph rebuild so scheduler-aware tools are wired correctly.
        self._graphs.clear()

    def set_job_service(self, job_service) -> None:
        self._job_service = job_service
        # Force graph rebuild so job tools are wired correctly.
        self._graphs.clear()

    def refresh_model_configuration(self) -> None:
        # Config edits can change model selectors/provider endpoints.
        # Drop graph/model caches so the next run always uses fresh settings.
        self._graphs.clear()
        self._session_models.clear()

    @staticmethod
    def _purpose_for_origin(origin: str) -> str:
        return "heartbeat" if origin == "heartbeat" else "main"

    @staticmethod
    def _format_message_datetime(value: datetime) -> str:
        dt = value
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        local_dt = dt.astimezone()
        hour_12 = local_dt.hour % 12 or 12
        am_pm = "am" if local_dt.hour < 12 else "pm"
        return (
            f"{local_dt.strftime('%A')}, "
            f"{local_dt.strftime('%B')} {local_dt.day} {local_dt.year}, "
            f"{hour_12}:{local_dt.minute:02d} {am_pm}"
        )

    def _prepare_envelope_content(self, envelope: MessageEnvelope) -> tuple[str, bool, list[dict]]:
        content = envelope.text
        is_command = False
        attachments_meta: list[dict] = []
        if envelope.command:
            is_command = True
            content = f"/{envelope.command} {envelope.metadata}".strip()
        elif envelope.attachments:
            attachments_meta = self._serialize_attachments(envelope.attachments)
        if not is_command:
            timestamp_text = self._format_message_datetime(envelope.timestamp)
            prefix = f"Current date and time: {timestamp_text}"
            content = f"{prefix}\n\n{content}".strip() if content else prefix
        return content, is_command, attachments_meta

    def _push_request_context(
        self,
        *,
        session_id: str,
        envelope: MessageEnvelope,
        run_id: str,
    ) -> tuple[str, str, str, dict[str, object]]:
        internal_user_id = str(envelope.metadata.get("internal_user_id", envelope.user_id))
        scope_type = str(envelope.metadata.get("scope_type") or "private")
        scope_id = str(envelope.metadata.get("scope_id") or f"private:{internal_user_id}")
        tokens: dict[str, object] = {
            "session": set_current_session_id(session_id),
            "channel": set_current_channel_id(envelope.channel_id),
            "user": set_current_user_id(internal_user_id),
            "origin": set_current_origin(envelope.origin),
            "run_id": set_current_run_id(run_id),
            "message_id": set_current_message_id(envelope.message_id),
            "scope_type": set_current_scope_type(scope_type),
            "scope_id": set_current_scope_id(scope_id),
        }
        return internal_user_id, scope_type, scope_id, tokens

    def _pop_request_context(self, tokens: dict[str, object]) -> None:
        reset_current_scope_id(tokens["scope_id"])
        reset_current_scope_type(tokens["scope_type"])
        reset_current_origin(tokens["origin"])
        reset_current_user_id(tokens["user"])
        reset_current_message_id(tokens["message_id"])
        reset_current_run_id(tokens["run_id"])
        reset_current_channel_id(tokens["channel"])
        reset_current_session_id(tokens["session"])

    @staticmethod
    def _extract_limit_from_response(text: str) -> tuple[str | None, str | None]:
        match = re.match(r"^LIMIT_REACHED \(([^)]+)\):\s*(.+)$", text.strip())
        if not match:
            return None, None
        return match.group(1).strip(), match.group(2).strip()

    async def _publish_stream_event(self, session_id: str, event_type: str, data: dict) -> None:
        await self.event_bus.publish(
            StreamEvent(
                session_id=session_id,
                type=event_type,
                data=data,
                created_at=datetime.now(UTC),
            )
        )

    @staticmethod
    def _collect_debug_text(value: object, *, max_chunks: int = 32) -> list[str]:
        chunks: list[str] = []

        def visit(node: object) -> None:
            if len(chunks) >= max_chunks:
                return
            if node is None:
                return
            if isinstance(node, str):
                text = node.strip()
                if text:
                    chunks.append(text)
                return
            if isinstance(node, list):
                for item in node:
                    visit(item)
                    if len(chunks) >= max_chunks:
                        return
                return
            if isinstance(node, dict):
                for key in (
                    "text",
                    "content",
                    "summary",
                    "thinking",
                    "reasoning",
                    "explanation",
                    "output_text",
                ):
                    if key in node:
                        visit(node.get(key))
                        if len(chunks) >= max_chunks:
                            return

        visit(value)
        return chunks

    def _extract_thinking_from_ai_message(self, message: AIMessage) -> list[str]:
        chunks: list[str] = []
        content = getattr(message, "content", None)
        if isinstance(content, list):
            for block in content:
                if not isinstance(block, dict):
                    continue
                block_type = str(block.get("type") or "").lower()
                if "thinking" in block_type or "reasoning" in block_type:
                    chunks.extend(self._collect_debug_text(block))

        additional = getattr(message, "additional_kwargs", {}) or {}
        if isinstance(additional, dict):
            for key in ("thinking", "reasoning", "reasoning_content", "thinking_content", "reasoning_text"):
                if key in additional:
                    chunks.extend(self._collect_debug_text(additional.get(key)))

        metadata = getattr(message, "response_metadata", {}) or {}
        if isinstance(metadata, dict):
            for key in ("thinking", "reasoning", "reasoning_content", "thinking_content", "reasoning_text"):
                if key in metadata:
                    chunks.extend(self._collect_debug_text(metadata.get(key)))

        deduped: list[str] = []
        seen: set[str] = set()
        for chunk in chunks:
            normalized = chunk.strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            deduped.append(normalized)
        return deduped

    def _log_model_thinking_debug(
        self,
        *,
        model_name: str,
        run_id: str,
        session_id: str,
        messages: list[BaseMessage],
    ) -> None:
        ai_messages = [msg for msg in messages if isinstance(msg, AIMessage)]
        if not ai_messages:
            return

        thinking_lines: list[str] = []
        for idx, message in enumerate(ai_messages, start=1):
            extracted = self._extract_thinking_from_ai_message(message)
            if not extracted:
                continue
            joined = " | ".join(text.replace("\n", " ") for text in extracted)
            thinking_lines.append(f"ai#{idx}: {joined}")

        if not thinking_lines:
            return

        try:
            resolved = resolve_model(model_name)
            provider_type = resolved.provider_api_type
        except Exception:
            provider_type = "unknown"

        preview = "\n".join(thinking_lines)
        if len(preview) > 8000:
            preview = preview[:7997] + "..."
        _logger.info(
            "LLM thinking output (provider=%s session=%s run=%s model=%s):\n%s",
            provider_type,
            session_id,
            run_id,
            model_name,
            preview,
        )

    def _extract_reasoning_for_storage(
        self,
        messages: list[BaseMessage],
        *,
        max_chunks: int = 12,
        max_total_chars: int = 32000,
    ) -> list[str]:
        chunks: list[str] = []
        seen: set[str] = set()
        total_chars = 0
        for message in messages:
            if not isinstance(message, AIMessage):
                continue
            for chunk in self._extract_thinking_from_ai_message(message):
                normalized = chunk.strip()
                if not normalized or normalized in seen:
                    continue
                if total_chars + len(normalized) > max_total_chars:
                    remaining = max_total_chars - total_chars
                    if remaining <= 0:
                        return chunks
                    normalized = normalized[: max(0, remaining - 3)].rstrip() + "..."
                seen.add(normalized)
                chunks.append(normalized)
                total_chars += len(normalized)
                if len(chunks) >= max_chunks or total_chars >= max_total_chars:
                    return chunks
        return chunks

    async def _postprocess_response(
        self,
        *,
        user_id: str,
        messages: list[BaseMessage],
        message_id: str,
        response: object,
        session_id: str,
    ) -> tuple[str, list[Attachment]]:
        response_text = self._message_content_to_text(response)
        attachments = await self._extract_attachments(user_id, session_id, messages, message_id)
        response_text, media_attachments = await self._extract_media_directive_attachments(
            user_id,
            session_id,
            response_text,
            messages=messages,
            message_id=message_id,
        )
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
                message_id,
            )
        attachments = self._materialize_runtime_attachments(user_id, attachments)
        cleaned = self._strip_attachment_paths(response_text) if attachments else response_text
        return cleaned, attachments

    async def handle_message(self, session_id: str, envelope: MessageEnvelope) -> AgentResponse:
        if not envelope.text and not envelope.command and not envelope.attachments:
            return AgentResponse(text="")
        if not list_models():
            return AgentResponse(text="LLM is not configured. Define at least one model in config.yaml.")

        content, is_command, attachments_meta = self._prepare_envelope_content(envelope)

        run_id = str(uuid.uuid4())
        run_started_at = datetime.now(UTC)
        run_status = "running"
        run_error: str | None = None
        run_limit_reason: str | None = None
        run_limit_detail: str | None = None
        run_input_tokens = 0
        run_output_tokens = 0
        run_total_tokens = 0
        run_cost = 0.0
        run_reasoning: list[str] = []
        history_len_before_invoke = 0
        await self._publish_stream_event(
            session_id,
            "message_received",
            {"run_id": run_id, "message_id": envelope.message_id, "user_id": envelope.user_id},
        )
        internal_user_id, _scope_type, _scope_id, context_tokens = self._push_request_context(
            session_id=session_id,
            envelope=envelope,
            run_id=run_id,
        )
        response: object = ""
        messages: list[BaseMessage] = []
        purpose = self._purpose_for_origin(envelope.origin)
        model_name = resolve_model_name(None, purpose=purpose)
        await self._trace_create(
            run_id=run_id,
            session_id=session_id,
            user_id=internal_user_id,
            message_id=envelope.message_id,
            origin=envelope.origin,
            model=model_name,
            input_text=content or "",
        )
        await self._trace_event(
            run_id=run_id,
            session_id=session_id,
            event_type="message_received",
            payload={
                "origin": envelope.origin,
                "channel_id": envelope.channel_id,
                "message_id": envelope.message_id,
                "has_attachments": bool(attachments_meta),
                "is_command": bool(is_command),
            },
        )
        limit_token = None
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
            selected_model = await self._get_session_model(session_id, envelope)
            await self._trace_update(run_id, model=selected_model)
            await self._compact_history_for_context(session_id, history, selected_model)
            history_len_before_invoke = len(history)
            candidate_models = resolve_model_candidates(selected_model, purpose=purpose)
            baseline_history = list(history)
            result: dict[str, object] | None = None
            model_name = selected_model
            for attempt_index, candidate_model in enumerate(candidate_models):
                model_name = candidate_model
                _logger.info(
                    "model_attempt: using model %s (attempt %d/%d, session=%s)",
                    candidate_model,
                    attempt_index + 1,
                    len(candidate_models),
                    session_id,
                )
                await self._trace_event(
                    run_id=run_id,
                    session_id=session_id,
                    event_type="model_attempt",
                    payload={
                        "attempt": attempt_index + 1,
                        "total": len(candidate_models),
                        "model": candidate_model,
                    },
                )
                resolved_model = resolve_model(candidate_model, purpose=purpose)
                limits = RunLimitsState(
                    max_tool_calls=max(0, int(settings.limits_max_tool_calls)),
                    max_runtime_seconds=max(1, int(settings.limits_max_runtime_seconds)),
                    max_cost_usd=max(0.0, float(settings.limits_max_cost_usd)),
                    input_cost_per_1m=float(resolved_model.input_cost_per_1m),
                    output_cost_per_1m=float(resolved_model.output_cost_per_1m),
                    start_time=asyncio.get_running_loop().time(),
                )
                limit_token = set_current_run_limits(limits)
                callbacks = [
                    RunBudgetUsageCallback(
                        input_cost_per_1m=float(resolved_model.input_cost_per_1m),
                        output_cost_per_1m=float(resolved_model.output_cost_per_1m),
                    ),
                    ThinkingDebugCallback(
                        logger=_logger,
                        provider_api_type=resolved_model.provider_api_type,
                        model_name=candidate_model,
                        session_id=session_id,
                        run_id=run_id,
                    ),
                ]
                invoke_config = {
                    "callbacks": callbacks,
                    "recursion_limit": max(32, int(settings.limits_max_tool_calls) * 4 + 16),
                }
                try:
                    graph = self._get_graph(candidate_model, purpose=purpose, resolved_model=resolved_model)
                    result = await asyncio.wait_for(
                        graph.ainvoke({"messages": history}, config=invoke_config),
                        timeout=max(1, int(settings.limits_max_runtime_seconds) + 5),
                    )
                    await self._trace_update(run_id, model=candidate_model)
                    break
                except asyncio.TimeoutError:
                    timeout_text = await self._build_limit_fallback_response(
                        model_name=candidate_model,
                        history=history,
                        reason="runtime",
                        detail=f"max runtime exceeded ({int(settings.limits_max_runtime_seconds)}s)",
                    )
                    run_limit_reason = "runtime"
                    run_limit_detail = f"max runtime exceeded ({int(settings.limits_max_runtime_seconds)}s)"
                    await self._trace_event(
                        run_id=run_id,
                        session_id=session_id,
                        event_type="limit_reached",
                        payload={"reason": run_limit_reason, "detail": run_limit_detail},
                    )
                    result = {
                        "messages": history
                        + [
                            AIMessage(content=timeout_text)
                        ]
                    }
                    await self._trace_update(run_id, model=candidate_model)
                    break
                except Exception as exc:
                    should_repair = self._is_tool_sequence_error(exc)
                    if not should_repair and self._is_model_bad_request(exc):
                        should_repair = any(self._is_tool_chatter_message(msg) for msg in history)
                    if should_repair:
                        _logger.warning(
                            "tool_sequence_repair: repairing model request state (session=%s, error=%s)",
                            session_id,
                            str(exc),
                        )
                        await self._trace_event(
                            run_id=run_id,
                            session_id=session_id,
                            event_type="tool_sequence_repair",
                            payload={"error": str(exc), "model": candidate_model},
                        )
                        self._sanitize_tool_sequence(history)
                        result = await asyncio.wait_for(
                            graph.ainvoke({"messages": history}, config=invoke_config),
                            timeout=max(1, int(settings.limits_max_runtime_seconds) + 5),
                        )
                        await self._trace_update(run_id, model=candidate_model)
                        break

                    has_next = attempt_index + 1 < len(candidate_models)
                    safe_to_failover = len(history) == len(baseline_history)
                    if has_next and safe_to_failover and self._is_retryable_model_http_error(exc):
                        next_model = candidate_models[attempt_index + 1]
                        _logger.warning(
                            "model_failover: switching model %s -> %s (session=%s, error=%s)",
                            candidate_model,
                            next_model,
                            session_id,
                            str(exc),
                        )
                        await self._trace_event(
                            run_id=run_id,
                            session_id=session_id,
                            event_type="model_failover",
                            payload={
                                "from_model": candidate_model,
                                "to_model": next_model,
                                "error": str(exc),
                                "status_code": self._extract_http_status_code(exc),
                            },
                        )
                        history[:] = list(baseline_history)
                        continue
                    raise
                finally:
                    if limit_token is not None:
                        reset_current_run_limits(limit_token)
                        limit_token = None

            if result is None:
                raise RuntimeError("Model invocation failed without a result.")
            messages = result.get("messages", history)
            self._history[session_id] = list(messages)
            # Disable thinking debug logs for now since they can be noisy and not always useful.
            # self._log_model_thinking_debug(
            #     model_name=model_name,
            #     run_id=run_id,
            #     session_id=session_id,
            #     messages=messages,
            # )
            new_messages = messages[history_len_before_invoke:] if history_len_before_invoke < len(messages) else []
            run_reasoning = self._extract_reasoning_for_storage(new_messages)
            if run_reasoning:
                await self._trace_event(
                    run_id=run_id,
                    session_id=session_id,
                    event_type="reasoning",
                    payload={"chunks": run_reasoning},
                )

            for msg in reversed(messages):
                if isinstance(msg, AIMessage):
                    response = msg.content
                    break

            usage = collect_usage(messages, envelope.message_id)
            if usage is not None:
                await record_usage(session_id, internal_user_id, model_name, usage)
                run_input_tokens = int(usage.get("input_tokens") or 0)
                run_output_tokens = int(usage.get("output_tokens") or 0)
                run_total_tokens = int(usage.get("total_tokens") or 0)
                resolved_for_cost = resolve_model(model_name, purpose=purpose)
                run_cost = (run_input_tokens / 1_000_000.0) * float(resolved_for_cost.input_cost_per_1m) + (
                    run_output_tokens / 1_000_000.0
                ) * float(resolved_for_cost.output_cost_per_1m)
                await self._trace_event(
                    run_id=run_id,
                    session_id=session_id,
                    event_type="llm_usage",
                    payload={
                        "input_tokens": run_input_tokens,
                        "output_tokens": run_output_tokens,
                        "total_tokens": run_total_tokens,
                        "cost": run_cost,
                        "model": model_name,
                    },
                )
        except Exception as exc:
            _logger.exception("Agent runtime failed for session=%s", session_id)
            # Graph execution can fail after partially mutating in-memory history.
            # Rebuild from DB to drop incomplete tool-use/tool-result sequences.
            self.clear_history(session_id)
            await self._ensure_history(session_id)
            messages = self._history.get(session_id, [])
            run_status = "failed"
            run_error = str(exc)
            validation_hint = self._tool_input_validation_hint(exc)
            if validation_hint:
                response = validation_hint
                _logger.warning(
                    "tool_call_failed: session=%s run=%s reason=tool_input_validation error=%s",
                    session_id,
                    run_id,
                    run_error,
                )
                await self._trace_event(
                    run_id=run_id,
                    session_id=session_id,
                    event_type="tool_call_failed",
                    payload={
                        "error": run_error,
                        "failure_type": "tool_input_validation",
                        "hint": validation_hint,
                    },
                )
            else:
                response = (
                    "I hit an internal error while processing your request. "
                    f"Details: {exc}. Please retry or simplify the task."
                )
                await self._trace_event(
                    run_id=run_id,
                    session_id=session_id,
                    event_type="error",
                    payload={"error": run_error},
                )
        finally:
            if limit_token is not None:
                reset_current_run_limits(limit_token)
            self._pop_request_context(context_tokens)
        await self._publish_stream_event(
            session_id,
            "message_response",
            {"run_id": run_id, "response": response},
        )
        cleaned, attachments = await self._postprocess_response(
            user_id=internal_user_id,
            messages=messages,
            message_id=envelope.message_id,
            response=response,
            session_id=session_id,
        )
        if run_limit_reason is None:
            run_limit_reason, run_limit_detail = self._extract_limit_from_response(cleaned)
        if run_status == "running":
            run_status = "limited" if run_limit_reason else "completed"
        finished_at = datetime.now(UTC)
        duration_ms = max(0, int((finished_at - run_started_at).total_seconds() * 1000))
        await self._trace_update(
            run_id,
            status=run_status,
            output_text=cleaned,
            error=run_error,
            limit_reason=run_limit_reason,
            limit_detail=run_limit_detail,
            input_tokens=run_input_tokens,
            output_tokens=run_output_tokens,
            total_tokens=run_total_tokens,
            cost=run_cost,
            finished_at=finished_at,
            duration_ms=duration_ms,
        )
        await self._trace_event(
            run_id=run_id,
            session_id=session_id,
            event_type="message_response",
            payload={
                "status": run_status,
                "response_preview": cleaned[:600],
                "duration_ms": duration_ms,
            },
        )
        return AgentResponse(text=cleaned, attachments=attachments, run_id=run_id, reasoning=run_reasoning)

    def clear_history(self, session_id: str) -> None:
        self._history.pop(session_id, None)

    def set_session_model(self, session_id: str, model_name: str) -> None:
        if model_name:
            self._session_models[session_id] = model_name

    async def _trace_create(
        self,
        *,
        run_id: str,
        session_id: str,
        user_id: str,
        message_id: str,
        origin: str,
        model: str | None,
        input_text: str,
    ) -> None:
        try:
            async with SessionLocal() as session:
                repo = Repository(session)
                await repo.create_run_trace(
                    run_id=run_id,
                    session_id=session_id,
                    user_id=user_id,
                    message_id=message_id,
                    origin=origin,
                    model=model,
                    input_text=input_text,
                    status="running",
                )
        except Exception:
            _logger.debug("run trace create failed (run_id=%s)", run_id, exc_info=True)

    async def _trace_update(self, run_id: str, **fields) -> None:
        try:
            async with SessionLocal() as session:
                repo = Repository(session)
                await repo.update_run_trace(run_id, **fields)
        except Exception:
            _logger.debug("run trace update failed (run_id=%s)", run_id, exc_info=True)

    async def _trace_event(
        self,
        *,
        run_id: str,
        session_id: str,
        event_type: str,
        payload: dict | None = None,
    ) -> None:
        try:
            async with SessionLocal() as session:
                repo = Repository(session)
                await repo.append_run_trace_event(
                    run_id=run_id,
                    session_id=session_id,
                    event_type=event_type,
                    payload=payload or {},
                )
        except Exception:
            _logger.debug(
                "run trace event failed (run_id=%s, event_type=%s)",
                run_id,
                event_type,
                exc_info=True,
            )

    async def _get_session_model(self, session_id: str, envelope: MessageEnvelope) -> str:
        if envelope.origin == "heartbeat":
            return resolve_model_name(None, purpose="heartbeat")
        metadata = envelope.metadata or {}
        model_override = str(metadata.get("model_name") or "").strip()
        if model_override:
            try:
                return resolve_model_name(model_override, purpose="main")
            except Exception:
                _logger.warning(
                    "Ignoring invalid per-message model override '%s' for session=%s",
                    model_override,
                    session_id,
                )
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

    def _get_graph(
        self,
        model_name: str,
        purpose: str = "main",
        resolved_model: ResolvedModel | None = None,
    ) -> object:
        if self._fixed_graph is not None:
            return self._fixed_graph
        resolved = resolved_model or resolve_model(model_name, purpose=purpose)
        cache_key = (
            purpose,
            resolved.name.lower(),
            resolved.provider_api_type.lower(),
            resolved.model,
            resolved.api_base,
        )
        if cache_key not in self._graphs:
            self._graphs[cache_key] = build_graph(
                approval_service=self._approval_service,
                scheduler_service=self._scheduler_service,
                job_service=self._job_service,
                model_name=resolved.name,
                purpose=purpose,
            )
        return self._graphs[cache_key]

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
            if self._extract_tool_call_ids(msg):
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
        content = getattr(msg, "content", None)
        if isinstance(content, list):
            for block in content:
                if not isinstance(block, dict):
                    continue
                block_type = str(block.get("type") or "").strip().lower()
                if block_type not in {"tool_use", "tool_call"}:
                    continue
                call_id = block.get("id") or block.get("tool_use_id") or block.get("tool_call_id")
                if call_id:
                    ids.add(str(call_id))
        return ids

    def _sanitize_tool_sequence(self, history: list[BaseMessage]) -> None:
        sanitized: list[BaseMessage] = []
        invalid_tool_ids: set[str] = set()
        idx = 0

        while idx < len(history):
            msg = history[idx]
            if isinstance(msg, AIMessage):
                call_ids = self._extract_tool_call_ids(msg)
                if not call_ids:
                    sanitized.append(msg)
                    idx += 1
                    continue

                j = idx + 1
                contiguous_results: list[ToolMessage] = []
                contiguous_ids: list[str] = []
                while j < len(history) and isinstance(history[j], ToolMessage):
                    tool_msg = history[j]
                    tool_call_id = str(getattr(tool_msg, "tool_call_id", "") or "").strip()
                    if tool_call_id:
                        contiguous_results.append(tool_msg)
                        contiguous_ids.append(tool_call_id)
                    j += 1

                contiguous_id_set = set(contiguous_ids)
                if call_ids and call_ids.issubset(contiguous_id_set):
                    sanitized.append(msg)
                    seen_ids: set[str] = set()
                    for tool_msg in contiguous_results:
                        tool_call_id = str(getattr(tool_msg, "tool_call_id", "") or "").strip()
                        if not tool_call_id or tool_call_id not in call_ids:
                            continue
                        if tool_call_id in seen_ids:
                            continue
                        seen_ids.add(tool_call_id)
                        sanitized.append(tool_msg)
                else:
                    invalid_tool_ids.update(call_ids)
                idx = j
                continue

            if isinstance(msg, ToolMessage):
                # Orphan tool messages are unsafe to keep; only contiguous tool results
                # directly following a tool-use AI message survive.
                tool_call_id = str(getattr(msg, "tool_call_id", "") or "").strip()
                if tool_call_id:
                    invalid_tool_ids.add(tool_call_id)
                idx += 1
                continue

            sanitized.append(msg)
            idx += 1

        history[:] = sanitized

    def _message_content_to_text(self, content: object) -> str:
        def strip_reasoning_markup(text: str) -> str:
            cleaned = _THINKING_TAG_RE.sub("", text)
            cleaned = _REASONING_TAG_RE.sub("", cleaned)
            return cleaned.strip()

        def block_text(item: dict) -> str | None:
            kind = str(item.get("type") or "").lower()
            # Drop provider reasoning/thinking blocks from user-visible output.
            if kind in {
                "thinking",
                "reasoning",
                "reasoning_text",
                "reasoning_summary",
                "reasoning_content",
                "summary_text",
            }:
                return None
            if kind in {"text", "output_text"}:
                text = item.get("text")
                if isinstance(text, str):
                    return strip_reasoning_markup(text)
                content_value = item.get("content")
                if isinstance(content_value, str):
                    return strip_reasoning_markup(content_value)
                return None
            if kind == "image":
                return "[image]"
            if kind == "file":
                return "[file]"
            # Fallback: include plain text-like fields for unknown blocks, but never stringify full dicts.
            text = item.get("text")
            if isinstance(text, str):
                return strip_reasoning_markup(text)
            content_value = item.get("content")
            if isinstance(content_value, str):
                return strip_reasoning_markup(content_value)
            return None

        if isinstance(content, str):
            return strip_reasoning_markup(content)
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, str):
                    stripped = strip_reasoning_markup(item)
                    if stripped:
                        parts.append(stripped)
                    continue
                if isinstance(item, dict):
                    text = block_text(item)
                    if text:
                        parts.append(text)
                    continue
                parts.append(str(item))
            return "\n".join(part for part in parts if part).strip()
        return str(content)

    def _exception_text_chain(self, exc: Exception) -> str:
        parts: list[str] = []
        for current in self._iter_exception_chain(exc):
            text = str(current).strip()
            if text:
                parts.append(text)
            response = getattr(current, "response", None)
            if response is not None:
                resp_text = str(getattr(response, "text", "") or "").strip()
                if resp_text:
                    parts.append(resp_text)
        return "\n".join(parts).lower()

    def _iter_exception_chain(self, exc: BaseException) -> list[BaseException]:
        queue: list[BaseException] = [exc]
        seen: set[int] = set()
        ordered: list[BaseException] = []
        while queue:
            current = queue.pop(0)
            current_id = id(current)
            if current_id in seen:
                continue
            seen.add(current_id)
            ordered.append(current)

            cause = getattr(current, "__cause__", None)
            if isinstance(cause, BaseException):
                queue.append(cause)
            context = getattr(current, "__context__", None)
            if isinstance(context, BaseException):
                queue.append(context)

            # tenacity RetryError wraps the terminal exception in `last_attempt`.
            last_attempt = getattr(current, "last_attempt", None)
            if last_attempt is not None:
                try:
                    last_exc = last_attempt.exception()
                except Exception:
                    last_exc = None
                if isinstance(last_exc, BaseException):
                    queue.append(last_exc)

            grouped = getattr(current, "exceptions", None)
            if isinstance(grouped, (list, tuple)):
                for item in grouped:
                    if isinstance(item, BaseException):
                        queue.append(item)
        return ordered

    def _is_tool_sequence_error(self, exc: Exception) -> bool:
        text = self._exception_text_chain(exc)
        markers = (
            "tool_use ids were found without tool_result blocks",
            "must be a response to a preceeding message with 'tool_calls'",
            "must be a response to a preceding message with 'tool_calls'",
        )
        return any(marker in text for marker in markers)

    def _is_model_bad_request(self, exc: Exception) -> bool:
        text = self._exception_text_chain(exc)
        if " 400 " in f" {text} ":
            return True
        name = type(exc).__name__.lower()
        return "badrequest" in name or "invalid_request" in text

    def _extract_http_status_code(self, exc: Exception) -> int | None:
        for current in self._iter_exception_chain(exc):
            for key in ("status_code", "status", "http_status", "code"):
                direct = getattr(current, key, None)
                if isinstance(direct, int) and 400 <= direct <= 599:
                    return direct
                if isinstance(direct, str) and direct.isdigit():
                    parsed = int(direct)
                    if 400 <= parsed <= 599:
                        return parsed
                value = getattr(direct, "value", None)
                if isinstance(value, int) and 400 <= value <= 599:
                    return value
            response = getattr(current, "response", None)
            if response is not None:
                response_code = getattr(response, "status_code", None)
                if isinstance(response_code, int) and 400 <= response_code <= 599:
                    return response_code

        text = self._exception_text_chain(exc)
        for match in re.finditer(r"\b([45]\d{2})\b", text):
            value = int(match.group(1))
            if 400 <= value <= 599:
                return value
        return None

    def _is_retryable_model_http_error(self, exc: Exception) -> bool:
        status_code = self._extract_http_status_code(exc)
        if status_code is None:
            return False
        return 400 <= status_code <= 599

    def _tool_input_validation_hint(self, exc: Exception) -> str | None:
        text = self._exception_text_chain(exc)
        is_validation = (
            "validationerror" in text
            or "validation error" in text
            or "input should be" in text
            or "errors.pydantic.dev" in text
        )
        if not is_validation:
            return None
        if "secret_refs" in text and "valid list" in text:
            return (
                "Tool input validation failed: `shell.secret_refs` must be a list of secret names, "
                "for example `[\"MOLTBOOK_API_KEY\"]`, not a quoted JSON string."
            )
        return (
            "Tool input validation failed: a tool call used arguments that do not match the expected schema "
            "(wrong type or shape)."
        )

    async def _build_limit_fallback_response(
        self,
        model_name: str,
        history: list[BaseMessage],
        reason: str,
        detail: str,
    ) -> str:
        latest_user_text = ""
        for msg in reversed(history):
            if isinstance(msg, HumanMessage):
                latest_user_text = self._message_content_to_text(msg.content)
                if latest_user_text:
                    break
        if not list_models():
            return (
                f"LIMIT_REACHED ({reason}): {detail}. "
                "I stopped execution for safety. Please refine the request or split it into smaller steps."
            )
        llm = build_llm(model_name=model_name, purpose="main")
        prompt = [
            SystemMessage(
                content=(
                    "A run limit was reached while processing a user request. "
                    "Produce a concise user-facing status update. "
                    "Do not call tools. Include what was attempted and what the user should do next."
                )
            ),
            HumanMessage(
                content=(
                    f"Limit reached: {reason}\n"
                    f"Detail: {detail}\n"
                    f"Latest user request: {latest_user_text or '(not available)'}"
                )
            ),
        ]
        try:
            result = await asyncio.wait_for(llm.ainvoke(prompt), timeout=15)
            text = self._message_content_to_text(getattr(result, "content", ""))
            if text.strip():
                return text.strip()
        except Exception:
            pass
        return (
            f"LIMIT_REACHED ({reason}): {detail}. "
            "I stopped execution for safety. Please refine the request or split it into smaller steps."
        )

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
        if not list_models():
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

    async def summarize_session(self, session_id: str, model_name: str | None = None) -> str:
        await self._ensure_history(session_id)
        messages = self._history.get(session_id, [])
        if not messages:
            return "No messages to summarize."
        previous_summary = ""
        previous_checkpoint: datetime | None = None
        chat_messages: list[BaseMessage] = []

        for msg in messages:
            if isinstance(msg, SystemMessage) and msg.additional_kwargs.get("conversation_summary"):
                previous_summary = self._message_content_to_text(msg.content).strip()
                previous_checkpoint = self._summary_checkpoint(msg)
                continue
            if self._is_chat_message(msg):
                chat_messages.append(msg)

        new_messages: list[BaseMessage] = []
        for msg in chat_messages:
            dt = self._message_datetime(msg)
            if previous_checkpoint is not None and dt is not None and dt <= previous_checkpoint:
                continue
            new_messages.append(msg)

        if not new_messages and previous_summary:
            return previous_summary
        if not new_messages:
            return "No messages to summarize."

        if not list_models():
            transcript_lines = []
            for msg in new_messages:
                role = "user" if isinstance(msg, HumanMessage) else "assistant"
                content = self._message_content_to_text(getattr(msg, "content", ""))
                if content:
                    transcript_lines.append(f"{role}: {content}")
            transcript = "\n".join(transcript_lines).strip()
            merged = f"{previous_summary}\n{transcript}".strip()
            return merged or "No messages to summarize."

        llm = build_llm(model_name=model_name, purpose="main")
        transcript_lines = []
        for msg in new_messages:
            role = "user" if isinstance(msg, HumanMessage) else "assistant"
            content = self._message_content_to_text(getattr(msg, "content", ""))
            if content:
                transcript_lines.append(f"{role}: {content}")
        transcript = "\n".join(transcript_lines).strip()
        prompt = [
            SystemMessage(
                content=("""
Create long-term memory notes for semantic retrieval.
Keep only information likely useful in future sessions.

Include only:
- Stable user preferences and working style
- Important project decisions and rationale
- Lasting technical setup facts
- Open commitments / follow-ups

Exclude:
- IDs, hashes, timestamps, URLs, raw logs, transient debugging details
- Step-by-step chronology of the session
- Tool call noise unless it defines a durable rule

If an existing summary is provided, merge it with the new transcript and return a single updated summary.

Output concise Markdown bullets under these headings (not all headings are necessary, include only relevant ones):
## Preferences
## Decisions
## Open Loops
Each bullet must be self-contained, explicit, and searchable.
                """.strip())
            ),
            HumanMessage(
                content=(
                    f"Existing summary:\n{previous_summary or '(none)'}\n\n"
                    f"Session messages to summarize:\n{transcript}\n\n"
                    "Return the merged summary only."
                )
            ),
        ]
        result = await llm.ainvoke(prompt)
        if hasattr(result, "content"):
            text = self._message_content_to_text(result.content).strip()
            return text or previous_summary or "No messages to summarize."
        text = str(result).strip()
        return text or previous_summary or "No messages to summarize."

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
        _logger.debug("Loaded system prompt for user_id=%s (%d chars)", user_id, len(prompt))
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

    def _mime_for_file(self, filename: str, fallback: str = "application/octet-stream") -> str:
        guessed, _ = mimetypes.guess_type(filename)
        return guessed or fallback

    def _executor_hint_from_tool_payload(self, data: dict) -> str | None:
        executor = data.get("_executor")
        if isinstance(executor, dict):
            hint = str(executor.get("executor_id") or executor.get("executor_name") or "").strip()
            if hint:
                return hint
        direct = str(data.get("target_machine") or data.get("executor_id") or data.get("executor_name") or "").strip()
        return direct or None

    async def _read_remote_attachment(
        self,
        *,
        user_id: str,
        session_id: str,
        raw_path: str,
        target_machine: str | None,
        images_only: bool = False,
    ) -> Attachment | None:
        machine_candidates = await self._executor_candidates(
            user_id=user_id,
            session_id=session_id,
            preferred=target_machine,
        )
        path_candidates = self._remote_path_candidates(raw_path)
        for machine in machine_candidates:
            for candidate_path in path_candidates:
                payload: dict[str, object] = {"path": candidate_path, "include_base64": True}
                try:
                    result, _dispatch = await self._tool_client.execute(
                        user_id=user_id,
                        session_id=session_id,
                        tool_name="read",
                        payload=payload,
                        timeout=30,
                        target_machine=machine,
                    )
                except Exception:
                    continue
                if not isinstance(result, dict):
                    continue
                content_type = str(result.get("content_type") or "").strip().lower()
                if images_only and not content_type.startswith("image/"):
                    continue
                raw_b64 = str(result.get("base64") or "")
                if not raw_b64:
                    continue
                try:
                    data = base64.b64decode(raw_b64)
                except Exception:
                    continue
                file_path = str(result.get("file_path") or candidate_path).strip() or candidate_path
                filename = Path(file_path).name or Path(candidate_path).name or "image"
                if not content_type:
                    content_type = self._mime_for_file(filename)
                return Attachment(
                    filename=filename,
                    content_type=content_type,
                    bytes_data=data,
                )
        _logger.debug(
            "Remote media fetch failed for path=%s user_id=%s session_id=%s preferred_machine=%s",
            raw_path,
            user_id,
            session_id,
            target_machine,
        )
        return None

    async def _executor_candidates(
        self,
        *,
        user_id: str,
        session_id: str,
        preferred: str | None,
    ) -> list[str | None]:
        candidates: list[str | None] = []
        seen: set[str] = set()

        def _add(value: str | None) -> None:
            normalized = str(value or "").strip()
            if not normalized:
                if "__default__" in seen:
                    return
                seen.add("__default__")
                candidates.append(None)
                return
            if normalized in seen:
                return
            seen.add(normalized)
            candidates.append(normalized)

        _add(preferred)
        _add(await executor_router.get_session_default(session_id))
        async with SessionLocal() as session:
            repo = Repository(session)
            _add(await repo.get_user_default_executor_id(user_id))
            rows = await repo.list_executors_for_user(user_id, include_disabled=False)
            for row in rows:
                _add(row.id)
        return candidates or [None]

    def _remote_path_candidates(self, raw_path: str) -> list[str]:
        base = str(raw_path or "").strip()
        if not base:
            return []
        candidates: list[str] = [base]
        if base == "/workspace":
            candidates.append(".")
        elif base.startswith("/workspace/"):
            candidates.append(base.removeprefix("/workspace/"))
        elif base.startswith("workspace/"):
            candidates.append(base.removeprefix("workspace/"))
        seen: set[str] = set()
        out: list[str] = []
        for item in candidates:
            norm = item.strip()
            if not norm or norm in seen:
                continue
            seen.add(norm)
            out.append(norm)
        return out

    async def _extract_attachments(
        self,
        user_id: str,
        session_id: str,
        messages: list[BaseMessage],
        message_id: str,
    ) -> list[Attachment]:
        attachments: list[Attachment] = []
        seen_resolved_paths: set[str] = set()
        image_exts = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tiff"}
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
            if not isinstance(data, dict):
                continue
            target_machine = self._executor_hint_from_tool_payload(data)
            path_specs: list[tuple[str, bool]] = []
            if "screenshot_path" in data:
                path_specs.append((str(data["screenshot_path"]), True))
            if "screenshot_paths" in data and isinstance(data["screenshot_paths"], list):
                path_specs.extend((str(p), True) for p in data["screenshot_paths"])
            file_path = data.get("file_path")
            if isinstance(file_path, str):
                content_type = str(data.get("content_type", "")).lower()
                ext = Path(file_path).suffix.lower()
                if content_type.startswith("image/") or ext in image_exts:
                    path_specs.append((file_path, True))
            if "file_paths" in data and isinstance(data["file_paths"], list):
                for item in data["file_paths"]:
                    if not isinstance(item, str):
                        continue
                    ext = Path(item).suffix.lower()
                    if ext in image_exts:
                        path_specs.append((item, True))
            attachment_path = data.get("attachment_path")
            if isinstance(attachment_path, str) and attachment_path.strip():
                path_specs.append((attachment_path, False))
            attachment_paths = data.get("attachment_paths")
            if isinstance(attachment_paths, list):
                for item in attachment_paths:
                    if not isinstance(item, str):
                        continue
                    if item.strip():
                        path_specs.append((item, False))
            for raw_path, images_only in path_specs:
                resolved = self._resolve_workspace_path(user_id, raw_path)
                if resolved and resolved.exists():
                    path_key = str(resolved)
                    if path_key in seen_resolved_paths:
                        continue
                    if not resolved.is_file():
                        continue
                    content_type = self._mime_for_file(resolved.name)
                    if images_only and not content_type.startswith("image/"):
                        continue
                    seen_resolved_paths.add(path_key)
                    attachments.append(
                        Attachment(
                            filename=resolved.name,
                            content_type=content_type,
                            path=str(resolved),
                        )
                    )
                    continue
                remote_attachment = await self._read_remote_attachment(
                    user_id=user_id,
                    session_id=session_id,
                    raw_path=raw_path,
                    target_machine=target_machine,
                    images_only=images_only,
                )
                if remote_attachment is None:
                    continue
                attachments.append(remote_attachment)
        return attachments

    async def _extract_media_directive_attachments(
        self,
        user_id: str,
        session_id: str,
        text: str,
        *,
        messages: list[BaseMessage],
        message_id: str,
    ) -> tuple[str, list[Attachment]]:
        if not text:
            return text, []
        attachments: list[Attachment] = []
        seen: set[str] = set()
        kept_lines: list[str] = []
        target_machine = self._latest_executor_hint(messages, message_id)
        for line in text.splitlines():
            matches = list(_MEDIA_DIRECTIVE_RE.finditer(line))
            if not matches:
                kept_lines.append(line)
                continue

            cursor = 0
            rebuilt_parts: list[str] = []
            removed_any_directive = False

            for match in matches:
                raw_path = self._normalize_media_path(match.group("path"))
                if not raw_path:
                    continue
                resolved = self._resolve_user_workspace_file(user_id, raw_path)
                if resolved and resolved.exists() and resolved.is_file():
                    rebuilt_parts.append(line[cursor : match.start()])
                    cursor = match.end()
                    removed_any_directive = True
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
                    continue
                remote_attachment = await self._read_remote_attachment(
                    user_id=user_id,
                    session_id=session_id,
                    raw_path=raw_path,
                    target_machine=target_machine,
                    images_only=False,
                )
                if remote_attachment is None:
                    continue
                rebuilt_parts.append(line[cursor : match.start()])
                cursor = match.end()
                removed_any_directive = True
                dedupe_key = f"bytes:{hashlib.sha256(remote_attachment.bytes_data or b'').hexdigest()}:{remote_attachment.filename}"
                if dedupe_key in seen:
                    continue
                seen.add(dedupe_key)
                attachments.append(remote_attachment)

            if not removed_any_directive:
                kept_lines.append(line)
                continue

            rebuilt_parts.append(line[cursor:])
            cleaned_line = "".join(rebuilt_parts)
            cleaned_line = re.sub(r"\s{2,}", " ", cleaned_line)
            cleaned_line = re.sub(r"\s+([,.;:!?])", r"\1", cleaned_line)
            cleaned_line = cleaned_line.strip()
            if cleaned_line:
                kept_lines.append(cleaned_line)
        cleaned = "\n".join(kept_lines).strip()
        return cleaned, attachments

    def _latest_executor_hint(self, messages: list[BaseMessage], message_id: str) -> str | None:
        start_index = 0
        if message_id:
            for idx in range(len(messages) - 1, -1, -1):
                msg = messages[idx]
                if isinstance(msg, HumanMessage) and msg.additional_kwargs.get("message_id") == message_id:
                    start_index = idx + 1
                    break
        hint: str | None = None
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
            if not isinstance(data, dict):
                continue
            candidate = self._executor_hint_from_tool_payload(data)
            if candidate:
                hint = candidate
        return hint

    def _materialize_runtime_attachments(self, user_id: str, attachments: list[Attachment]) -> list[Attachment]:
        if not attachments:
            return attachments
        from .workspace import user_workspace_root

        workspace_root = user_workspace_root(user_id).resolve()
        out_dir = workspace_root / ".attachments"
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            return attachments
        for attachment in attachments:
            if attachment.path or not attachment.bytes_data:
                continue
            filename = Path(attachment.filename or "attachment.bin").name or "attachment.bin"
            stem = Path(filename).stem or "attachment"
            suffix = Path(filename).suffix
            safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._")
            if not safe_stem:
                safe_stem = "attachment"
            target = out_dir / f"{safe_stem}-{uuid.uuid4().hex[:8]}{suffix}"
            try:
                target.write_bytes(attachment.bytes_data)
            except OSError:
                continue
            attachment.path = str(target)
        return attachments

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
            candidate_path = "/" + candidate_path.removeprefix("sandbox:/workspace/")
        if candidate_path == "/workspace":
            candidate_path = "/"
        elif candidate_path.startswith("/workspace/"):
            # Backward compatibility for older path formats.
            candidate_path = "/" + str(Path(candidate_path).relative_to("/workspace"))

        from .workspace import user_workspace_root

        workspace = user_workspace_root(user_id).resolve()
        as_path = Path(candidate_path)
        if as_path.is_absolute():
            candidate = workspace / Path(str(as_path).lstrip("/"))
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
        # Keep all attachment resolution confined to the current user's workspace.
        return self._resolve_user_workspace_file(user_id, raw_path)

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
        return "Attachment added."
