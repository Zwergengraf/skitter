from __future__ import annotations

from typing import Iterable

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from .llm import resolve_model
from .profile_context import current_agent_profile_id
from ..data.db import SessionLocal
from ..data.repositories import Repository


def usage_from_message(msg: AIMessage) -> tuple[int, int, int] | None:
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


def collect_usage(messages: Iterable[BaseMessage], message_id: str | None = None) -> dict | None:
    message_list = list(messages)
    if not message_list:
        return None

    start_idx = None
    if message_id:
        for idx in range(len(message_list) - 1, -1, -1):
            msg = message_list[idx]
            if isinstance(msg, HumanMessage) and msg.additional_kwargs.get("message_id") == message_id:
                start_idx = idx
                break

    slice_messages = message_list[start_idx + 1 :] if start_idx is not None else message_list
    total_input = 0
    total_output = 0
    total_tokens = 0
    last = None
    for msg in slice_messages:
        if not isinstance(msg, AIMessage):
            continue
        usage = usage_from_message(msg)
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


async def record_usage(
    session_id: str,
    user_id: str,
    model_name: str,
    usage: dict,
    agent_profile_id: str | None = None,
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
            agent_profile_id=agent_profile_id or (current_agent_profile_id().strip() or None),
            model=resolved.name,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            cost=cost,
            last_input_tokens=int(usage.get("last_input_tokens") or 0),
            last_output_tokens=int(usage.get("last_output_tokens") or 0),
            last_total_tokens=int(usage.get("last_total_tokens") or 0),
        )
