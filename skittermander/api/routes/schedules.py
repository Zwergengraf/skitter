from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from ..deps import get_repo
from ..schemas import ScheduledJobCreate, ScheduledJobOut, ScheduledJobUpdate
from ...data.db import SessionLocal
from ...data.repositories import Repository
from ...data.models import ScheduledJob

router = APIRouter(prefix="/v1/schedules", tags=["schedules"])


def _to_scheduled_job_out(job: ScheduledJob) -> ScheduledJobOut:
    return ScheduledJobOut(
        id=job.id,
        user_id=job.user_id,
        channel_id=job.channel_id,
        target_scope_type=job.target_scope_type or "private",
        target_scope_id=job.target_scope_id or f"private:{job.user_id}",
        target_origin=job.target_origin,
        target_destination_id=job.target_destination_id,
        name=job.name,
        prompt=job.prompt,
        schedule_type=job.schedule_type,
        schedule_expr=job.schedule_expr,
        timezone=job.timezone,
        enabled=job.enabled,
        created_at=job.created_at,
        updated_at=job.updated_at,
        last_run_at=job.last_run_at,
        next_run_at=job.next_run_at,
    )


@router.get("", response_model=list[ScheduledJobOut])
async def list_schedules(
    repo: Repository = Depends(get_repo),
    user_id: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[ScheduledJobOut]:
    if user_id:
        jobs = await repo.list_scheduled_jobs(user_id)
    else:
        jobs = await repo.list_scheduled_jobs_all()
    jobs = jobs[:limit]
    return [_to_scheduled_job_out(job) for job in jobs]


@router.post("", response_model=ScheduledJobOut)
async def create_schedule(
    payload: ScheduledJobCreate,
    request: Request,
) -> ScheduledJobOut:
    scheduler = request.app.state.scheduler_service
    schedule_expr = payload.schedule_expr
    if payload.schedule_type == "date":
        schedule_expr = f"DATE:{payload.schedule_expr}"
    result = await scheduler.create_job(
        user_id=payload.user_id,
        channel_id=payload.channel_id,
        name=payload.name,
        prompt=payload.prompt,
        cron=schedule_expr,
        target_scope_type="private",
        target_scope_id=f"private:{payload.user_id}",
        target_origin="discord",
        target_destination_id=payload.channel_id,
    )
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    if payload.enabled is False:
        await scheduler.update_job(result["id"], enabled=False)

    async with SessionLocal() as session:
        repo = Repository(session)
        job = await repo.get_scheduled_job(result["id"])
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return _to_scheduled_job_out(job)


@router.patch("/{job_id}", response_model=ScheduledJobOut)
async def update_schedule(
    job_id: str,
    payload: ScheduledJobUpdate,
    request: Request,
) -> ScheduledJobOut:
    scheduler = request.app.state.scheduler_service
    fields = payload.model_dump(exclude_unset=True)
    if "schedule_type" in fields and "schedule_expr" in fields:
        if fields["schedule_type"] == "date":
            fields["schedule_expr"] = fields["schedule_expr"]
        else:
            fields["schedule_expr"] = fields["schedule_expr"]
    result = await scheduler.update_job(job_id, **fields)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])

    async with SessionLocal() as session:
        repo = Repository(session)
        job = await repo.get_scheduled_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return _to_scheduled_job_out(job)


@router.delete("/{job_id}")
async def delete_schedule(job_id: str, request: Request) -> dict:
    scheduler = request.app.state.scheduler_service
    result = await scheduler.delete_job(job_id)
    return result
