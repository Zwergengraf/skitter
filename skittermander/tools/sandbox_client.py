from __future__ import annotations

from typing import Any, Dict, Optional

import httpx

from ..core.config import settings


class ToolRunnerClient:
    def __init__(self, base_url: Optional[str] = None, api_key: Optional[str] = None) -> None:
        self.base_url = base_url or settings.sandbox_base_url
        self.api_key = api_key or settings.sandbox_api_key

    async def execute(
        self, session_id: str, tool_name: str, payload: Dict[str, Any], timeout: Optional[float] = None
    ) -> Dict[str, Any]:
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        async with httpx.AsyncClient(timeout=timeout or 60) as client:
            response = await client.post(
                f"{self.base_url}/execute",
                json={"session_id": session_id, "tool": tool_name, "payload": payload},
                headers=headers,
            )
            response.raise_for_status()
            return response.json()
