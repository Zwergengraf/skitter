from __future__ import annotations

from typing import List


class MemorySummarizer:
    def summarize(self, messages: List[str]) -> str:
        return "\n".join(messages[-5:])
