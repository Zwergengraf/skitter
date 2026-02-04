from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ..deps import get_repo
from ..schemas import ArtifactOut
from ...data.repositories import Repository

router = APIRouter(prefix="/v1/artifacts", tags=["artifacts"])


@router.get("/{artifact_id}", response_model=ArtifactOut)
async def get_artifact(artifact_id: str, repo: Repository = Depends(get_repo)) -> ArtifactOut:
    artifact = await repo.get_artifact(artifact_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return ArtifactOut(
        id=artifact.id,
        session_id=artifact.session_id,
        path=artifact.path,
        mime_type=artifact.mime_type,
        created_at=artifact.created_at,
    )
