from __future__ import annotations

from typing import Optional

from ..core.config import settings


class ToolApprovalPolicy:
    def __init__(self, tool_list: Optional[list[str]] = None) -> None:
        if tool_list is None:
            raw = settings.tool_approval_tools
            tool_list = [name.strip() for name in raw.split(",") if name.strip()]
        self.tool_list = set(tool_list)

    def requires_approval(self, tool_name: str) -> bool:
        if not settings.tool_approval_required:
            return False
        if not self.tool_list:
            return True
        return tool_name in self.tool_list
