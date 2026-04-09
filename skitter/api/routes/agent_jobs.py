from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from ..authz import require_admin
from ..deps import get_repo
from ..schemas import AgentJobDetailOut, AgentJobListItem, SessionToolRunOut
from ...core.jobs import job_run_id
from ...data.repositories import Repository

router = APIRouter(prefix="/v1/agent-jobs", tags=["agent-jobs"])


def _to_job_list_item(job) -> AgentJobListItem:
    return AgentJobListItem(
        id=job.id,
        user_id=job.user_id,
        agent_profile_id=getattr(job, "agent_profile_id", None),
        session_id=job.session_id,
        kind=job.kind,
        name=job.name,
        status=job.status,
        model=job.model,
        target_scope_type=job.target_scope_type or "private",
        target_scope_id=job.target_scope_id or "",
        target_origin=job.target_origin,
        target_transport_account_key=getattr(job, "target_transport_account_key", None),
        target_destination_id=job.target_destination_id,
        cancel_requested=bool(job.cancel_requested),
        tool_calls_used=int(job.tool_calls_used or 0),
        input_tokens=int(job.input_tokens or 0),
        output_tokens=int(job.output_tokens or 0),
        total_tokens=int(job.total_tokens or 0),
        cost=float(job.cost or 0.0),
        error=job.error,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        delivered_at=job.delivered_at,
        delivery_error=job.delivery_error,
    )


@router.get("", response_model=list[AgentJobListItem])
async def list_agent_jobs(
    request: Request,
    repo: Repository = Depends(get_repo),
    status: str | None = Query(default=None),
    user_id: str | None = Query(default=None),
    agent_profile_id: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[AgentJobListItem]:
    require_admin(request)
    rows = await repo.list_agent_jobs_all(
        limit=limit,
        status=status,
        user_id=user_id,
        agent_profile_id=agent_profile_id,
    )
    return [_to_job_list_item(job) for job in rows]


@router.get("/{job_id}", response_model=AgentJobDetailOut)
async def get_agent_job_detail(
    job_id: str,
    request: Request,
    repo: Repository = Depends(get_repo),
) -> AgentJobDetailOut:
    require_admin(request)
    job = await repo.get_agent_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Background job not found")
    run_id = job_run_id(job.id)
    tool_runs = await repo.list_tool_runs_by_run(run_id)
    base = _to_job_list_item(job)
    return AgentJobDetailOut(
        **base.model_dump(),
        run_id=run_id,
        payload=job.payload or {},
        limits=job.limits or {},
        result=job.result or {},
        tool_runs=[
            SessionToolRunOut(
                id=tool_run.id,
                tool=tool_run.tool_name,
                status=tool_run.status,
                executor_id=tool_run.executor_id,
                input=tool_run.input or {},
                output=tool_run.output or {},
                approved_by=tool_run.approved_by,
                created_at=tool_run.created_at,
            )
            for tool_run in tool_runs
        ],
    )
