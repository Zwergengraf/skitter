from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from ..authz import require_admin
from ..deps import get_repo
from ..schemas import ScheduledJobCreate, ScheduledJobOut, ScheduledJobUpdate
from ...core.profile_service import profile_service
from ...core.transport_accounts import transport_account_service
from ...data.db import SessionLocal
from ...data.repositories import Repository
from ...data.models import ScheduledJob, SCHEDULED_JOB_MODEL_MAIN

router = APIRouter(prefix="/v1/schedules", tags=["schedules"])


def _to_scheduled_job_out(job: ScheduledJob) -> ScheduledJobOut:
    return ScheduledJobOut(
        id=job.id,
        user_id=job.user_id,
        agent_profile_id=getattr(job, "agent_profile_id", None),
        channel_id=job.channel_id,
        target_scope_type=job.target_scope_type or "private",
        target_scope_id=job.target_scope_id or f"private:{job.user_id}",
        target_origin=job.target_origin,
        target_transport_account_key=getattr(job, "target_transport_account_key", None),
        target_destination_id=job.target_destination_id,
        name=job.name,
        prompt=job.prompt,
        model=job.model or SCHEDULED_JOB_MODEL_MAIN,
        schedule_type=job.schedule_type,
        schedule_expr=job.schedule_expr,
        timezone=job.timezone,
        enabled=job.enabled,
        created_at=job.created_at,
        updated_at=job.updated_at,
        last_run_at=job.last_run_at,
        next_run_at=job.next_run_at,
    )


async def _validate_discord_target(
    repo: Repository,
    *,
    profile_id: str,
    transport_account_key: str | None,
    target_origin: str | None,
) -> None:
    if str(target_origin or "").strip() != "discord":
        return
    account_key = str(transport_account_key or "").strip()
    if not account_key:
        raise HTTPException(status_code=400, detail="A Discord bot must be selected for Discord schedule delivery.")
    account = await transport_account_service.get_account(repo, account_key=account_key)
    if account is None:
        raise HTTPException(status_code=404, detail="Transport account not found")
    if account.is_shared_default:
        explicit = await transport_account_service.get_explicit_account_for_profile(
            repo,
            agent_profile_id=profile_id,
            transport="discord",
        )
        if explicit is not None and explicit.enabled:
            raise HTTPException(
                status_code=400,
                detail="Profiles with dedicated Discord bots must use that dedicated bot for schedule delivery.",
            )
        return
    if account.agent_profile_id != profile_id:
        raise HTTPException(
            status_code=400,
            detail="Dedicated Discord bots can only be used with their pinned profile.",
        )


@router.get("", response_model=list[ScheduledJobOut])
async def list_schedules(
    request: Request,
    repo: Repository = Depends(get_repo),
    user_id: str | None = Query(default=None),
    agent_profile_id: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[ScheduledJobOut]:
    require_admin(request)
    if user_id:
        jobs = await repo.list_scheduled_jobs(user_id, agent_profile_id=agent_profile_id)
    else:
        jobs = await repo.list_scheduled_jobs_all(agent_profile_id=agent_profile_id)
    jobs = jobs[:limit]
    return [_to_scheduled_job_out(job) for job in jobs]


@router.post("", response_model=ScheduledJobOut)
async def create_schedule(
    payload: ScheduledJobCreate,
    request: Request,
    repo: Repository = Depends(get_repo),
) -> ScheduledJobOut:
    require_admin(request)
    scheduler = request.app.state.scheduler_service
    user = await repo.get_user_by_id(payload.user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    profile = await profile_service.resolve_profile(
        repo,
        user.id,
        agent_profile_id=payload.agent_profile_id,
    )
    await _validate_discord_target(
        repo,
        profile_id=profile.id,
        transport_account_key=payload.target_transport_account_key,
        target_origin=payload.target_origin,
    )
    schedule_expr = payload.schedule_expr
    if payload.schedule_type == "date":
        schedule_expr = f"DATE:{payload.schedule_expr}"
    result = await scheduler.create_job(
        user_id=payload.user_id,
        agent_profile_id=profile.id,
        channel_id=payload.channel_id,
        name=payload.name,
        prompt=payload.prompt,
        model=payload.model,
        cron=schedule_expr,
        target_scope_type="private",
        target_scope_id=f"private:{profile.id}",
        target_origin=str(payload.target_origin or "discord").strip() or "discord",
        target_transport_account_key=str(payload.target_transport_account_key or "").strip() or None,
        target_destination_id=str(payload.target_destination_id or payload.channel_id).strip() or payload.channel_id,
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
    require_admin(request)
    scheduler = request.app.state.scheduler_service
    fields = payload.model_dump(exclude_unset=True)
    async with SessionLocal() as session:
        validate_repo = Repository(session)
        existing = await validate_repo.get_scheduled_job(job_id)
        if existing is None:
            raise HTTPException(status_code=404, detail="Job not found")
        profile_id = str(fields.get("agent_profile_id") or getattr(existing, "agent_profile_id", "") or "").strip()
        target_origin = str(fields.get("target_origin") or getattr(existing, "target_origin", None) or "").strip() or None
        target_transport_account_key = (
            str(fields.get("target_transport_account_key") or getattr(existing, "target_transport_account_key", None) or "").strip()
            or None
        )
        if profile_id:
            await _validate_discord_target(
                validate_repo,
                profile_id=profile_id,
                transport_account_key=target_transport_account_key,
                target_origin=target_origin,
            )
    if "target_destination_id" not in fields and "channel_id" in fields:
        fields["target_destination_id"] = fields["channel_id"]
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
    require_admin(request)
    scheduler = request.app.state.scheduler_service
    result = await scheduler.delete_job(job_id)
    return result
