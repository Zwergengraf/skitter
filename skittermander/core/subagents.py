from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Awaitable, Callable, List


@dataclass
class SubAgentTask:
    name: str
    coro: Callable[[], Awaitable[str]]


class SubAgentPool:
    def __init__(self, max_concurrency: int = 4) -> None:
        self._semaphore = asyncio.Semaphore(max_concurrency)

    async def run(self, tasks: List[SubAgentTask]) -> List[str]:
        async def _run_task(task: SubAgentTask) -> str:
            async with self._semaphore:
                return await task.coro()

        return await asyncio.gather(*(_run_task(t) for t in tasks))
