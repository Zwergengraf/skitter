from __future__ import annotations

from typing import Any, Dict, Optional

from .executors import executor_router


class ToolRunnerClient:
    def __init__(self, base_url: Optional[str] = None, api_key: Optional[str] = None) -> None:
        _ = base_url, api_key

    async def execute(
        self,
        user_id: str,
        session_id: str,
        tool_name: str,
        payload: Dict[str, Any],
        timeout: Optional[float] = None,
        target_machine: Optional[str] = None,
    ) -> tuple[Dict[str, Any], dict[str, Any]]:
        return await executor_router.execute(
            user_id=user_id,
            session_id=session_id,
            tool_name=tool_name,
            payload=payload,
            timeout=timeout,
            target_machine=target_machine,
        )
