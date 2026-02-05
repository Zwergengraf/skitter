from __future__ import annotations

from typing import Any, Dict, Optional
import asyncio

import httpx

from ..core.config import settings
from .sandbox_manager import sandbox_manager


class ToolRunnerClient:
    def __init__(self, base_url: Optional[str] = None, api_key: Optional[str] = None) -> None:
        self.base_url = base_url or settings.sandbox_base_url
        self.api_key = api_key or settings.sandbox_api_key

    async def execute(
        self,
        user_id: str,
        session_id: str,
        tool_name: str,
        payload: Dict[str, Any],
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        base_url = self.base_url
        if sandbox_manager is not None:
            try:
                base_url = await sandbox_manager.get_base_url(user_id)
            except RuntimeError:
                base_url = self.base_url
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        retries = max(1, settings.sandbox_connect_retries)
        backoff = max(0.1, settings.sandbox_connect_backoff)
        async with httpx.AsyncClient(timeout=timeout or 60) as client:
            for attempt in range(retries):
                try:
                    response = await client.post(
                        f"{base_url}/execute",
                        json={"session_id": session_id, "tool": tool_name, "payload": payload},
                        headers=headers,
                    )
                    response.raise_for_status()
                    return response.json()
                except httpx.ConnectError:
                    if attempt >= retries - 1:
                        raise
                    await asyncio.sleep(backoff * (attempt + 1))
