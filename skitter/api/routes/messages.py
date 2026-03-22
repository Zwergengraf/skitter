from __future__ import annotations

import base64
import binascii
import mimetypes
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse

from ..authz import require_session_access, resolve_target_user_id
from ..deps import get_repo
from ..schemas import MessageAttachmentCreate, MessageCreate, MessageOut
from ...core.models import Attachment, MessageEnvelope
from ...core.workspace import user_workspace_root
from ...data.repositories import Repository

router = APIRouter(prefix="/v1/messages", tags=["messages"])
MAX_MESSAGE_ATTACHMENTS = 10
MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024


def _require_approved_user(approved: bool) -> None:
    if not approved:
        raise HTTPException(
            status_code=403,
            detail="Your account is not yet approved. An admin has to approve it first.",
        )

def _serialize_runtime_attachments(attachments: list[Attachment]) -> list[dict]:
    items: list[dict] = []
    for attachment in attachments:
        if not attachment.url and not attachment.path:
            continue
        items.append(
            {
                "filename": attachment.filename,
                "content_type": attachment.content_type or "application/octet-stream",
                "url": attachment.url,
                "path": attachment.path,
            }
        )
    return items


def _attachments_for_response(message_id: str, items: list[dict]) -> list[dict]:
    response_items: list[dict] = []
    for idx, item in enumerate(items):
        response_items.append(
            {
                "filename": str(item.get("filename") or "attachment"),
                "content_type": str(item.get("content_type") or "application/octet-stream"),
                "url": item.get("url"),
                "download_url": f"/v1/messages/{message_id}/attachments/{idx}",
            }
        )
    return response_items


def _sanitize_attachment_name(raw: str, index: int) -> str:
    candidate = Path(str(raw or "")).name.strip()
    return candidate or f"attachment-{index}"


def _guess_content_type(filename: str, provided: str | None) -> str:
    value = str(provided or "").strip()
    if value:
        return value
    guessed, _ = mimetypes.guess_type(filename)
    return guessed or "application/octet-stream"


def _store_uploaded_attachments(
    *,
    user_id: str,
    envelope_message_id: str,
    attachments: list[MessageAttachmentCreate],
) -> tuple[list[dict], list[Attachment]]:
    if not attachments:
        return [], []
    if len(attachments) > MAX_MESSAGE_ATTACHMENTS:
        raise HTTPException(status_code=400, detail=f"At most {MAX_MESSAGE_ATTACHMENTS} attachments are allowed.")

    upload_root = user_workspace_root(user_id) / ".uploads" / envelope_message_id
    upload_root.mkdir(parents=True, exist_ok=True)

    stored_meta: list[dict] = []
    runtime_attachments: list[Attachment] = []
    for index, item in enumerate(attachments):
        filename = _sanitize_attachment_name(item.filename, index)
        try:
            payload = base64.b64decode(item.data_base64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise HTTPException(status_code=400, detail=f"Attachment `{filename}` is not valid base64.") from exc
        if len(payload) > MAX_ATTACHMENT_BYTES:
            raise HTTPException(
                status_code=400,
                detail=f"Attachment `{filename}` exceeds the {MAX_ATTACHMENT_BYTES // (1024 * 1024)} MB limit.",
            )
        content_type = _guess_content_type(filename, item.content_type)
        target = upload_root / filename
        suffix = 1
        while target.exists():
            stem = Path(filename).stem or "attachment"
            ext = Path(filename).suffix
            target = upload_root / f"{stem}-{suffix}{ext}"
            suffix += 1
        target.write_bytes(payload)
        absolute_path = str(target.resolve())
        stored_meta.append(
            {
                "filename": target.name,
                "content_type": content_type,
                "path": absolute_path,
            }
        )
        data_url = None
        if content_type.lower().startswith("image/"):
            encoded = base64.b64encode(payload).decode("ascii")
            data_url = f"data:{content_type};base64,{encoded}"
        runtime_attachments.append(
            Attachment(
                filename=target.name,
                content_type=content_type,
                url=data_url,
                path=absolute_path,
            )
        )
    return stored_meta, runtime_attachments


@router.post("", response_model=MessageOut)
async def send_message(
    payload: MessageCreate,
    request: Request,
    repo: Repository = Depends(get_repo),
) -> MessageOut:
    session = await require_session_access(request, repo, payload.session_id)
    user = await repo.get_user_by_id(session.user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    _require_approved_user(user.approved)
    request_user_id = resolve_target_user_id(request, payload.user_id)
    if request_user_id != session.user_id:
        raise HTTPException(status_code=403, detail="Message user does not match session owner.")
    metadata_input = payload.metadata or {}
    origin_hint = str(
        metadata_input.get("origin")
        or metadata_input.get("client_origin")
        or session.origin
        or "web"
    )

    envelope = MessageEnvelope(
        message_id=str(uuid.uuid4()),
        channel_id=payload.session_id,
        user_id=request_user_id,
        timestamp=datetime.utcnow(),
        text=payload.text,
        origin=origin_hint,
        metadata=payload.metadata,
    )
    uploaded_meta, uploaded_runtime_attachments = _store_uploaded_attachments(
        user_id=session.user_id,
        envelope_message_id=envelope.message_id,
        attachments=payload.attachments,
    )
    scope_type = session.scope_type or "private"
    scope_id = session.scope_id or f"private:{session.user_id}"
    if scope_type == "private":
        destination_hint = str(
            metadata_input.get("destination_id")
            or metadata_input.get("channel_id")
            or payload.session_id
        )
        await repo.set_user_meta(
            session.user_id,
            {
                "last_private_origin": envelope.origin,
                "last_private_destination_id": destination_hint,
                "last_seen_at": datetime.utcnow().isoformat(),
            },
        )
    metadata = dict(metadata_input)
    metadata.update(
        {
            "message_id": envelope.message_id,
            "origin": envelope.origin,
            "internal_user_id": session.user_id,
            "scope_type": scope_type,
            "scope_id": scope_id,
            "is_private": scope_type == "private",
        }
    )
    answered_prompt = await repo.answer_pending_user_prompt_for_session(
        payload.session_id,
        answer=payload.text,
        answered_by=request_user_id,
    )
    if answered_prompt is not None:
        metadata["answered_prompt_id"] = answered_prompt.id
    if uploaded_meta:
        metadata["attachments"] = uploaded_meta
    user_message = await repo.add_message(payload.session_id, role="user", content=payload.text, metadata=metadata)

    envelope.metadata.update(metadata)
    envelope.attachments = uploaded_runtime_attachments

    runtime = request.app.state.runtime
    response = await runtime.handle_message(payload.session_id, envelope)
    if response.pending_prompt is not None:
        assistant_meta = {
            "response_to": envelope.message_id,
            "user_prompt": True,
            "user_prompt_id": response.pending_prompt.prompt_id,
            "user_prompt_question": response.pending_prompt.question,
            "user_prompt_choices": list(response.pending_prompt.choices),
            "user_prompt_allow_free_text": bool(response.pending_prompt.allow_free_text),
        }
        if response.run_id:
            assistant_meta["run_id"] = response.run_id
        assistant_msg = await repo.add_message(
            payload.session_id,
            role="assistant",
            content=response.text,
            metadata=assistant_meta,
        )
        return MessageOut(
            id=assistant_msg.id,
            session_id=assistant_msg.session_id,
            role=assistant_msg.role,
            content=assistant_msg.content,
            created_at=assistant_msg.created_at,
            attachments=[],
        )
    serialized_attachments = _serialize_runtime_attachments(response.attachments)
    assistant_meta = {"response_to": envelope.message_id}
    if response.run_id:
        assistant_meta["run_id"] = response.run_id
    if response.reasoning:
        assistant_meta["reasoning"] = response.reasoning
    if serialized_attachments:
        assistant_meta["attachments"] = serialized_attachments
    assistant_msg = await repo.add_message(
        payload.session_id, role="assistant", content=response.text, metadata=assistant_meta
    )
    response_attachments = _attachments_for_response(assistant_msg.id, serialized_attachments)
    return MessageOut(
        id=assistant_msg.id,
        session_id=assistant_msg.session_id,
        role=assistant_msg.role,
        content=assistant_msg.content,
        created_at=assistant_msg.created_at,
        attachments=response_attachments,
    )


@router.get("/{message_id}/attachments/{attachment_index}")
async def get_message_attachment(
    message_id: str,
    attachment_index: int,
    request: Request,
    repo: Repository = Depends(get_repo),
):
    message = await repo.get_message(message_id)
    if message is None:
        raise HTTPException(status_code=404, detail="Message not found")
    session = await require_session_access(request, repo, message.session_id)
    meta = message.meta or {}
    attachments = meta.get("attachments")
    if not isinstance(attachments, list):
        raise HTTPException(status_code=404, detail="Attachment not found")
    if attachment_index < 0 or attachment_index >= len(attachments):
        raise HTTPException(status_code=404, detail="Attachment not found")
    item = attachments[attachment_index]
    if not isinstance(item, dict):
        raise HTTPException(status_code=404, detail="Attachment not found")

    url = str(item.get("url") or "").strip()
    path_str = str(item.get("path") or "").strip()
    if path_str:
        workspace_root = user_workspace_root(session.user_id).resolve()
        candidate = Path(path_str)
        try:
            resolved = candidate.resolve(strict=False)
        except OSError as exc:
            raise HTTPException(status_code=404, detail="Attachment not found") from exc
        try:
            resolved.relative_to(workspace_root)
        except ValueError as exc:
            raise HTTPException(status_code=403, detail="Attachment path is not allowed") from exc
        if not resolved.exists() or not resolved.is_file():
            raise HTTPException(status_code=404, detail="Attachment file missing")
        filename = str(item.get("filename") or resolved.name)
        content_type = str(item.get("content_type") or "application/octet-stream")
        return FileResponse(path=resolved, filename=filename, media_type=content_type)

    if url:
        return RedirectResponse(url=url, status_code=307)

    raise HTTPException(status_code=404, detail="Attachment not found")
