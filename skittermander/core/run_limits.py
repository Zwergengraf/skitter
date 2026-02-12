from __future__ import annotations

from dataclasses import dataclass, field
from contextvars import ContextVar, Token
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler


@dataclass
class RunLimitsState:
    max_tool_calls: int
    max_runtime_seconds: int
    max_cost_usd: float
    input_cost_per_1m: float
    output_cost_per_1m: float
    start_time: float
    tool_calls_used: int = 0
    spent_cost_usd: float = 0.0
    input_tokens_used: int = 0
    output_tokens_used: int = 0
    total_tokens_used: int = 0
    seen_llm_run_ids: set[str] = field(default_factory=set)


class RunCancelledError(RuntimeError):
    """Raised when a run is cancelled and should terminate immediately."""


_CURRENT_RUN_LIMITS: ContextVar[RunLimitsState | None] = ContextVar("skitter_run_limits", default=None)


def set_current_run_limits(limits: RunLimitsState | None) -> Token:
    return _CURRENT_RUN_LIMITS.set(limits)


def reset_current_run_limits(token: Token) -> None:
    _CURRENT_RUN_LIMITS.reset(token)


def get_current_run_limits() -> RunLimitsState | None:
    return _CURRENT_RUN_LIMITS.get()


class RunBudgetUsageCallback(BaseCallbackHandler):
    def __init__(self, input_cost_per_1m: float | None = None, output_cost_per_1m: float | None = None) -> None:
        super().__init__()
        self._input_cost_per_1m = input_cost_per_1m
        self._output_cost_per_1m = output_cost_per_1m

    @staticmethod
    def _extract_tokens_from_dict(payload: dict) -> tuple[int, int]:
        input_tokens = int(payload.get("prompt_tokens") or payload.get("input_tokens") or 0)
        output_tokens = int(payload.get("completion_tokens") or payload.get("output_tokens") or 0)
        return input_tokens, output_tokens

    @staticmethod
    def _run_id_str(run_id: UUID | str) -> str:
        return str(run_id)

    def on_llm_end(self, response, *, run_id, parent_run_id=None, tags=None, **kwargs):  # type: ignore[override]
        limits = get_current_run_limits()
        if limits is None:
            return

        run_id_value = self._run_id_str(run_id)
        if run_id_value in limits.seen_llm_run_ids:
            return
        limits.seen_llm_run_ids.add(run_id_value)

        input_tokens = 0
        output_tokens = 0
        llm_output = getattr(response, "llm_output", None) or {}
        if isinstance(llm_output, dict):
            usage = llm_output.get("token_usage") or llm_output.get("usage") or {}
            if isinstance(usage, dict):
                input_tokens, output_tokens = self._extract_tokens_from_dict(usage)

        if input_tokens == 0 and output_tokens == 0:
            generations = getattr(response, "generations", None) or []
            for generation_batch in generations:
                for generation in generation_batch:
                    message = getattr(generation, "message", None)
                    usage_meta = getattr(message, "usage_metadata", None) if message is not None else None
                    if isinstance(usage_meta, dict):
                        delta_in, delta_out = self._extract_tokens_from_dict(usage_meta)
                        input_tokens += delta_in
                        output_tokens += delta_out

        if input_tokens == 0 and output_tokens == 0:
            return

        limits.input_tokens_used += int(input_tokens)
        limits.output_tokens_used += int(output_tokens)
        limits.total_tokens_used += int(input_tokens + output_tokens)
        input_cost_per_1m = (
            limits.input_cost_per_1m if self._input_cost_per_1m is None else float(self._input_cost_per_1m)
        )
        output_cost_per_1m = (
            limits.output_cost_per_1m if self._output_cost_per_1m is None else float(self._output_cost_per_1m)
        )
        limits.spent_cost_usd += (input_tokens / 1_000_000.0) * input_cost_per_1m
        limits.spent_cost_usd += (output_tokens / 1_000_000.0) * output_cost_per_1m
