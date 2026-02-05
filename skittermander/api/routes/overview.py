from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Request

from ..deps import get_repo
from ..schemas import (
    OverviewCostPoint,
    OverviewOut,
    OverviewServiceStatus,
    OverviewSessionOut,
    OverviewToolRunOut,
)
from ...core.config import settings
from ...data.repositories import Repository

router = APIRouter(prefix="/v1/overview", tags=["overview"])


def _cost_trajectory() -> list[OverviewCostPoint]:
    today = datetime.utcnow().date()
    points: list[OverviewCostPoint] = []
    for i in range(6, -1, -1):
        day = today - timedelta(days=i)
        points.append(OverviewCostPoint(label=day.strftime("%a"), cost=0.0))
    return points


def _system_health(request: Request) -> list[OverviewServiceStatus]:
    scheduler = request.app.state.scheduler_service
    scheduler_status = "healthy" if getattr(scheduler, "_started", False) else "warning"
    scheduler_detail = "running" if scheduler_status == "healthy" else "stopped"

    browser_detail = settings.browser_executable or "default"
    browser_status = "healthy" if settings.browser_executable else "warning"

    return [
        OverviewServiceStatus(name="API", status="healthy", detail="online"),
        OverviewServiceStatus(name="Scheduler", status=scheduler_status, detail=scheduler_detail),
        OverviewServiceStatus(name="Sandbox", status="warning", detail="not checked"),
        OverviewServiceStatus(name="Browser", status=browser_status, detail=browser_detail),
    ]


@router.get("", response_model=OverviewOut)
async def get_overview(request: Request, repo: Repository = Depends(get_repo)) -> OverviewOut:
    sessions = await repo.list_recent_sessions(limit=8, status="active")
    tool_runs = await repo.list_pending_tool_runs(limit=6)

    live_sessions = [
        OverviewSessionOut(
            id=session.id,
            user=transport_user_id,
            transport="discord",
            status=session.status,
            last_active_at=last_active_at,
        )
        for session, transport_user_id, last_active_at in sessions
    ]

    approvals = [
        OverviewToolRunOut(
            id=tool_run.id,
            tool=tool_run.tool_name,
            status=tool_run.status,
            requested_by=transport_user_id,
            created_at=tool_run.created_at,
        )
        for tool_run, transport_user_id in tool_runs
    ]

    return OverviewOut(
        cost_trajectory=_cost_trajectory(),
        system_health=_system_health(request),
        live_sessions=live_sessions,
        tool_approvals=approvals,
    )
