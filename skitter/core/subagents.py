from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Callable

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage

from .config import settings
from .llm import resolve_model
from .llm_debug import ThinkingDebugCallback
from .run_limits import (
    RunBudgetUsageCallback,
    RunCancelledError,
    RunLimitsState,
    get_current_run_limits,
    reset_current_run_limits,
    set_current_run_limits,
)
from .usage import collect_usage, record_usage


GraphFactory = Callable[[str], object]
_logger = logging.getLogger(__name__)


@dataclass
class SubAgentTaskSpec:
    task: str
    name: str | None = None
    context: str | None = None
    acceptance_criteria: str | None = None


@dataclass
class SubAgentResult:
    name: str
    status: str
    final_text: str = ""
    error: str | None = None
    usage: dict[str, Any] = field(default_factory=dict)
    transcript: list[dict[str, str]] = field(default_factory=list)
    artifacts: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class SubAgentService:
    def __init__(self, graph_factory: GraphFactory) -> None:
        self._graph_factory = graph_factory
        self._semaphore = asyncio.Semaphore(max(1, int(settings.max_sub_agents)))
        self._graphs: dict[str, object] = {}

    def _worker_graph(self, model_name: str) -> object:
        graph = self._graphs.get(model_name)
        if graph is None:
            graph = self._graph_factory(model_name)
            self._graphs[model_name] = graph
        return graph

    async def run_one(
        self,
        user_id: str,
        session_id: str,
        model_name: str,
        system_prompt: str,
        spec: SubAgentTaskSpec,
        *,
        max_runtime_seconds: int | None = None,
        limits_override: dict[str, float | int] | None = None,
    ) -> SubAgentResult:
        name = (spec.name or "").strip() or "sub-agent"
        timeout_seconds = max(1, int(max_runtime_seconds or settings.subagent_timeout_seconds))
        try:
            async with self._semaphore:
                return await asyncio.wait_for(
                    self._run_one_internal(
                        user_id,
                        session_id,
                        model_name,
                        system_prompt,
                        spec,
                        limits_override=limits_override,
                    ),
                    timeout=timeout_seconds,
                )
        except asyncio.TimeoutError:
            return SubAgentResult(
                name=name,
                status="timeout",
                error=f"Timed out after {timeout_seconds} seconds.",
            )
        except Exception as exc:
            if isinstance(exc, RunCancelledError) or "cancellation requested" in str(exc).lower():
                return SubAgentResult(name=name, status="cancelled", error=str(exc))
            return SubAgentResult(name=name, status="failed", error=str(exc))

    async def run_batch(
        self,
        user_id: str,
        session_id: str,
        model_name: str,
        system_prompt: str,
        specs: list[SubAgentTaskSpec],
    ) -> list[SubAgentResult]:
        coroutines = [self.run_one(user_id, session_id, model_name, system_prompt, spec) for spec in specs]
        return await asyncio.gather(*coroutines)

    async def _run_one_internal(
        self,
        user_id: str,
        session_id: str,
        model_name: str,
        system_prompt: str,
        spec: SubAgentTaskSpec,
        *,
        limits_override: dict[str, float | int] | None = None,
    ) -> SubAgentResult:
        graph = self._worker_graph(model_name)
        worker_name = (spec.name or "").strip() or "sub-agent"
        worker_instruction = self._worker_instruction()
        worker_prompt = self._build_worker_prompt(spec)
        request_id = str(uuid.uuid4())
        resolved_model = resolve_model(model_name, purpose="main")
        active_limits = get_current_run_limits()
        applied_limits = active_limits
        limit_token = None
        if limits_override is not None:
            applied_limits = RunLimitsState(
                max_tool_calls=max(0, int(limits_override.get("max_tool_calls", settings.job_limits_max_tool_calls))),
                max_runtime_seconds=max(
                    1,
                    int(limits_override.get("max_runtime_seconds", settings.job_limits_max_runtime_seconds)),
                ),
                max_cost_usd=max(0.0, float(limits_override.get("max_cost_usd", settings.job_limits_max_cost_usd))),
                input_cost_per_1m=float(resolved_model.input_cost_per_1m),
                output_cost_per_1m=float(resolved_model.output_cost_per_1m),
                start_time=asyncio.get_running_loop().time(),
            )
            limit_token = set_current_run_limits(applied_limits)
        input_messages: list[BaseMessage] = []
        if system_prompt:
            input_messages.append(SystemMessage(content=system_prompt))
        input_messages.append(SystemMessage(content=worker_instruction))
        input_messages.append(HumanMessage(content=worker_prompt, additional_kwargs={"message_id": request_id}))
        per_worker_tool_budget = max(
            1,
            int(applied_limits.max_tool_calls if applied_limits is not None else settings.limits_max_tool_calls),
        )
        invoke_config = {
            "callbacks": [
                RunBudgetUsageCallback(
                    input_cost_per_1m=float(resolved_model.input_cost_per_1m),
                    output_cost_per_1m=float(resolved_model.output_cost_per_1m),
                ),
                ThinkingDebugCallback(
                    logger=_logger,
                    provider_api_type=resolved_model.provider_api_type,
                    model_name=model_name,
                    session_id=session_id,
                    run_id=request_id,
                ),
            ],
            "recursion_limit": max(16, per_worker_tool_budget * 2 + 8),
        }
        try:
            result = await graph.ainvoke({"messages": input_messages}, config=invoke_config)
            messages = result.get("messages", input_messages)
            final_text = self._extract_final_text(messages)
            usage = collect_usage(messages, request_id) or {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
            input_tokens = int(usage.get("input_tokens") or 0)
            output_tokens = int(usage.get("output_tokens") or 0)
            total_tokens = int(usage.get("total_tokens") or 0)
            if applied_limits is not None:
                input_tokens = max(input_tokens, int(applied_limits.input_tokens_used or 0))
                output_tokens = max(output_tokens, int(applied_limits.output_tokens_used or 0))
                total_tokens = max(total_tokens, int(applied_limits.total_tokens_used or (input_tokens + output_tokens)))
            usage_for_record = {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": total_tokens,
                "last_input_tokens": int(usage.get("last_input_tokens") or 0),
                "last_output_tokens": int(usage.get("last_output_tokens") or 0),
                "last_total_tokens": int(usage.get("last_total_tokens") or 0),
            }
            if input_tokens > 0 or output_tokens > 0 or total_tokens > 0:
                await record_usage(session_id, user_id, model_name, usage_for_record)
            run_cost = (input_tokens / 1_000_000.0) * float(resolved_model.input_cost_per_1m) + (
                output_tokens / 1_000_000.0
            ) * float(resolved_model.output_cost_per_1m)
            transcript = self._compact_transcript(messages)
            artifacts = self._extract_artifacts(messages)
            return SubAgentResult(
                name=worker_name,
                status="completed",
                final_text=final_text,
                usage={
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "total_tokens": total_tokens,
                    "cost_usd": run_cost,
                    "tool_calls_used": int(applied_limits.tool_calls_used) if applied_limits is not None else 0,
                    "spent_cost_usd": float(applied_limits.spent_cost_usd) if applied_limits is not None else run_cost,
                },
                transcript=transcript,
                artifacts=artifacts,
            )
        finally:
            if limit_token is not None:
                reset_current_run_limits(limit_token)

    def _worker_instruction(self) -> str:
        return (
            "You are a delegated worker sub-agent.\n"
            "1. Complete only the delegated task.\n"
            "2. Use tools as needed.\n"
            "3. Return concise output with check notes/evidence.\n"
            "4. If blocked, state the blocker explicitly.\n"
            "Do not ask for unrelated work."
        )

    def _build_worker_prompt(self, spec: SubAgentTaskSpec) -> str:
        parts = [f"Task:\n{spec.task.strip()}"]
        if spec.context and spec.context.strip():
            parts.append(f"Context:\n{spec.context.strip()}")
        if spec.acceptance_criteria and spec.acceptance_criteria.strip():
            parts.append(f"Acceptance criteria:\n{spec.acceptance_criteria.strip()}")
        parts.append("Return final result now.")
        return "\n\n".join(parts)

    def _extract_final_text(self, messages: list[BaseMessage]) -> str:
        for msg in reversed(messages):
            if isinstance(msg, AIMessage):
                return self._message_text(msg.content)
        return ""

    def _message_text(self, content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for block in content:
                if isinstance(block, str):
                    parts.append(block)
                    continue
                if isinstance(block, dict):
                    kind = str(block.get("type") or "").lower()
                    if kind == "text":
                        parts.append(str(block.get("text") or ""))
                    elif kind == "image":
                        parts.append("[image]")
                    elif kind == "file":
                        parts.append("[file]")
                    else:
                        parts.append(str(block))
                    continue
                parts.append(str(block))
            return "\n".join(item for item in parts if item).strip()
        return str(content)

    def _role_name(self, msg: BaseMessage) -> str:
        if isinstance(msg, HumanMessage):
            return "user"
        if isinstance(msg, AIMessage):
            return "assistant"
        if isinstance(msg, ToolMessage):
            return "tool"
        if isinstance(msg, SystemMessage):
            return "system"
        return "message"

    def _compact_transcript(self, messages: list[BaseMessage]) -> list[dict[str, str]]:
        limit = max(500, int(settings.subagent_transcript_chars))
        transcript: list[dict[str, str]] = []
        consumed = 0
        for msg in messages:
            role = self._role_name(msg)
            text = self._message_text(getattr(msg, "content", ""))
            if not text:
                continue
            remaining = limit - consumed
            if remaining <= 0:
                break
            if len(text) > remaining:
                text = text[:remaining].rstrip() + "...[truncated]"
            consumed += len(text)
            transcript.append({"role": role, "content": text})
            if consumed >= limit:
                break
        return transcript

    def _extract_artifacts(self, messages: list[BaseMessage]) -> list[str]:
        artifacts: list[str] = []
        for msg in messages:
            if not isinstance(msg, ToolMessage):
                continue
            if not isinstance(msg.content, str):
                continue
            raw = msg.content.strip()
            if not raw.startswith("{"):
                continue
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if not isinstance(payload, dict):
                continue
            for key in ("screenshot_path", "file_path"):
                value = payload.get(key)
                if isinstance(value, str) and value:
                    artifacts.append(value)
            paths = payload.get("screenshot_paths")
            if isinstance(paths, list):
                for item in paths:
                    if isinstance(item, str) and item:
                        artifacts.append(item)
        # Keep order stable, remove duplicates.
        deduped: list[str] = []
        seen: set[str] = set()
        for path in artifacts:
            if path in seen:
                continue
            seen.add(path)
            deduped.append(path)
        return deduped
