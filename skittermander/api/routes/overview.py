from __future__ import annotations

from datetime import datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select, text

from ..authz import require_admin
from ..deps import get_repo
from ..schemas import (
    OverviewCostPoint,
    OverviewOut,
    OverviewServiceStatus,
    OverviewSessionOut,
    OverviewToolRunOut,
)
from ...core.llm import list_models
from ...data.models import LlmUsage
from ...data.repositories import Repository
from ...tools.sandbox_manager import sandbox_manager

router = APIRouter(prefix="/v1/overview", tags=["overview"])


OverviewRange = Literal["today", "24h", "week", "month", "year"]


def _month_start(value: datetime) -> datetime:
    return value.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _add_months(value: datetime, months: int) -> datetime:
    month_index = (value.month - 1) + months
    year = value.year + month_index // 12
    month = (month_index % 12) + 1
    return value.replace(year=year, month=month, day=1)


async def _cost_trajectory(repo: Repository, range_key: OverviewRange) -> list[OverviewCostPoint]:
    now = datetime.utcnow()
    bucket_unit = "day"
    bucket_points: list[datetime] = []
    window_start = now
    window_end = now
    label_format = "%b %d"

    if range_key == "today":
        bucket_unit = "hour"
        window_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        window_end = window_start + timedelta(days=1)
        bucket_points = [window_start + timedelta(hours=idx) for idx in range(24)]
        label_format = "%H:00"
    elif range_key == "24h":
        bucket_unit = "hour"
        current_hour = now.replace(minute=0, second=0, microsecond=0)
        window_start = current_hour - timedelta(hours=23)
        window_end = now + timedelta(seconds=1)
        bucket_points = [window_start + timedelta(hours=idx) for idx in range(24)]
        label_format = "%H:00"
    elif range_key == "week":
        bucket_unit = "day"
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        window_start = today_start - timedelta(days=6)
        window_end = now + timedelta(seconds=1)
        bucket_points = [window_start + timedelta(days=idx) for idx in range(7)]
        label_format = "%b %d"
    elif range_key == "month":
        bucket_unit = "day"
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        window_start = today_start - timedelta(days=29)
        window_end = now + timedelta(seconds=1)
        bucket_points = [window_start + timedelta(days=idx) for idx in range(30)]
        label_format = "%b %d"
    else:
        bucket_unit = "month"
        month_zero = _month_start(now)
        window_start = _add_months(month_zero, -11)
        window_end = now + timedelta(seconds=1)
        bucket_points = [_add_months(window_start, idx) for idx in range(12)]
        label_format = "%b %Y"

    stmt = (
        select(
            func.date_trunc(bucket_unit, LlmUsage.created_at).label("bucket"),
            func.coalesce(func.sum(LlmUsage.cost), 0.0).label("cost"),
        )
        .where(LlmUsage.created_at >= window_start, LlmUsage.created_at < window_end)
        .group_by("bucket")
        .order_by("bucket")
    )
    result = await repo.session.execute(stmt)
    rows = result.all()
    cost_by_bucket: dict[datetime, float] = {}
    for bucket, cost in rows:
        if bucket is None:
            continue
        if bucket.tzinfo is not None:
            bucket = bucket.replace(tzinfo=None)
        cost_by_bucket[bucket] = float(cost or 0.0)

    return [
        OverviewCostPoint(label=bucket.strftime(label_format), cost=cost_by_bucket.get(bucket, 0.0))
        for bucket in bucket_points
    ]


async def _system_health(request: Request, repo: Repository) -> list[OverviewServiceStatus]:
    runtime = getattr(request.app.state, "runtime", None)
    started_at = getattr(request.app.state, "started_at", None)
    api_status = "healthy" if bool(getattr(runtime, "ready", False)) else "warning"
    api_detail = "ready"
    if started_at is not None:
        uptime_seconds = max(0, int((datetime.utcnow() - started_at).total_seconds()))
        api_detail = f"ready · uptime {uptime_seconds}s" if api_status == "healthy" else f"not ready · uptime {uptime_seconds}s"

    db_status = "healthy"
    db_detail = "reachable"
    try:
        await repo.session.execute(text("SELECT 1"))
    except Exception as exc:
        db_status = "degraded"
        db_detail = f"error: {exc.__class__.__name__}"

    scheduler = request.app.state.scheduler_service
    scheduler_status = "healthy" if getattr(scheduler, "_started", False) else "warning"
    if scheduler_status == "healthy":
        job_count = len(scheduler.scheduler.get_jobs())
        scheduler_detail = f"running · {job_count} job(s)"
    else:
        scheduler_detail = "stopped"

    sandbox_status = "warning"
    sandbox_detail = "manager unavailable"
    if sandbox_manager is not None:
        if getattr(sandbox_manager, "_ready", False):
            try:
                containers = await sandbox_manager.list_containers()
                running = sum(1 for item in containers if item.get("status") == "running")
                sandbox_status = "healthy"
                sandbox_detail = f"docker connected · {running}/{len(containers)} running"
            except Exception as exc:
                sandbox_status = "degraded"
                sandbox_detail = f"error: {exc.__class__.__name__}"
        else:
            sandbox_detail = "docker unavailable"

    models = list_models()
    model_status = "healthy" if models else "degraded"
    model_detail = f"{len(models)} configured"

    return [
        OverviewServiceStatus(name="API", status=api_status, detail=api_detail),
        OverviewServiceStatus(name="Database", status=db_status, detail=db_detail),
        OverviewServiceStatus(name="Scheduler", status=scheduler_status, detail=scheduler_detail),
        OverviewServiceStatus(name="Sandbox", status=sandbox_status, detail=sandbox_detail),
        OverviewServiceStatus(name="Models", status=model_status, detail=model_detail),
    ]


@router.get("", response_model=OverviewOut)
async def get_overview(
    request: Request,
    repo: Repository = Depends(get_repo),
    range: OverviewRange = Query(default="week"),
) -> OverviewOut:
    require_admin(request)
    sessions = await repo.list_recent_sessions(limit=8, status="active")
    tool_runs = await repo.list_pending_tool_runs(limit=6)

    live_sessions = [
        OverviewSessionOut(
            id=session.id,
            user=transport_user_id,
            transport=session.origin or "unknown",
            status=session.status,
            last_active_at=last_active_at,
            total_tokens=session.total_tokens or 0,
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
        cost_trajectory=await _cost_trajectory(repo, range),
        system_health=await _system_health(request, repo),
        live_sessions=live_sessions,
        tool_approvals=approvals,
    )
