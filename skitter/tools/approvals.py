from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Dict, Optional


@dataclass
class ToolApproval:
    tool_run_id: str
    approved_by: Optional[str]
    approved_at: Optional[datetime]
    status: str


class InMemoryApprovalStore:
    def __init__(self) -> None:
        self._approvals: Dict[str, ToolApproval] = {}

    def create_pending(self, tool_run_id: str) -> ToolApproval:
        approval = ToolApproval(tool_run_id=tool_run_id, approved_by=None, approved_at=None, status="pending")
        self._approvals[tool_run_id] = approval
        return approval

    def approve(self, tool_run_id: str, approved_by: str) -> ToolApproval:
        approval = self._approvals.get(tool_run_id)
        if approval is None:
            approval = self.create_pending(tool_run_id)
        approval.status = "approved"
        approval.approved_by = approved_by
        approval.approved_at = datetime.now(UTC)
        return approval

    def get(self, tool_run_id: str) -> Optional[ToolApproval]:
        return self._approvals.get(tool_run_id)
