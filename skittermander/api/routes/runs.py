from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from ..deps import get_repo
from ..schemas import (
    RunTraceDetailOut,
    RunTraceEventOut,
    RunTraceListItem,
    SessionToolRunOut,
)
from ...data.repositories import Repository

router = APIRouter(prefix="/v1/runs", tags=["runs"])


def _run_item(trace) -> RunTraceListItem:
    return RunTraceListItem(
        id=trace.id,
        session_id=trace.session_id,
        user_id=trace.user_id,
        message_id=trace.message_id,
        origin=trace.origin,
        status=trace.status,
        model=trace.model,
        started_at=trace.started_at,
        finished_at=trace.finished_at,
        duration_ms=trace.duration_ms,
        tool_calls=trace.tool_calls or 0,
        input_tokens=trace.input_tokens or 0,
        output_tokens=trace.output_tokens or 0,
        total_tokens=trace.total_tokens or 0,
        cost=trace.cost or 0.0,
        error=trace.error,
        limit_reason=trace.limit_reason,
    )


@router.get("", response_model=list[RunTraceListItem])
async def list_runs(
    repo: Repository = Depends(get_repo),
    status: str | None = Query(default=None),
    user_id: str | None = Query(default=None),
    session_id: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[RunTraceListItem]:
    rows = await repo.list_run_traces(limit=limit, status=status, user_id=user_id, session_id=session_id)
    return [_run_item(trace) for trace in rows]


@router.get("/{run_id}", response_model=RunTraceDetailOut)
async def get_run_detail(run_id: str, repo: Repository = Depends(get_repo)) -> RunTraceDetailOut:
    trace = await repo.get_run_trace(run_id)
    if trace is None:
        raise HTTPException(status_code=404, detail="Run not found")
    tool_runs = await repo.list_tool_runs_by_run(run_id)
    events = await repo.list_run_trace_events(run_id=run_id, limit=2000)
    return RunTraceDetailOut(
        run=_run_item(trace),
        input_text=trace.input_text or "",
        output_text=trace.output_text or "",
        limit_detail=trace.limit_detail,
        tool_runs=[
            SessionToolRunOut(
                id=tool_run.id,
                tool=tool_run.tool_name,
                status=tool_run.status,
                input=tool_run.input or {},
                output=tool_run.output or {},
                approved_by=tool_run.approved_by,
                created_at=tool_run.created_at,
            )
            for tool_run in tool_runs
        ],
        events=[
            RunTraceEventOut(
                id=event.id,
                event_type=event.event_type,
                payload=event.payload or {},
                created_at=event.created_at,
            )
            for event in events
        ],
    )

