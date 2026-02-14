from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from skitter.core.events import EventBus
from skitter.core.runtime import AgentRuntime


def _runtime() -> AgentRuntime:
    return AgentRuntime(event_bus=EventBus(), graph=object())


async def _no_remote_attachment(*_args: Any, **_kwargs: Any):
    return None


@pytest.mark.asyncio
async def test_extract_media_directive_inline_text(tmp_path: Path) -> None:
    runtime = _runtime()
    image = tmp_path / "zig.png"
    image.write_bytes(b"\x89PNG\r\n")

    runtime._resolve_user_workspace_file = lambda user_id, raw_path: image if raw_path == "avatars/zig.png" else None
    runtime._read_remote_image_attachment = _no_remote_attachment

    text, attachments = await runtime._extract_media_directive_attachments(
        user_id="user-1",
        session_id="session-1",
        text="Attached image: MEDIA:avatars/zig.png",
        messages=[],
        message_id="msg-1",
    )

    assert text == "Attached image:"
    assert len(attachments) == 1
    assert attachments[0].filename == "zig.png"
    assert attachments[0].path == str(image)


@pytest.mark.asyncio
async def test_extract_media_directive_line_only(tmp_path: Path) -> None:
    runtime = _runtime()
    image = tmp_path / "zig.png"
    image.write_bytes(b"\x89PNG\r\n")

    runtime._resolve_user_workspace_file = lambda user_id, raw_path: image if raw_path == "avatars/zig.png" else None
    runtime._read_remote_image_attachment = _no_remote_attachment

    text, attachments = await runtime._extract_media_directive_attachments(
        user_id="user-1",
        session_id="session-1",
        text="MEDIA:avatars/zig.png",
        messages=[],
        message_id="msg-1",
    )

    assert text == ""
    assert len(attachments) == 1
    assert attachments[0].filename == "zig.png"


@pytest.mark.asyncio
async def test_extract_media_directive_unresolved_kept() -> None:
    runtime = _runtime()
    runtime._resolve_user_workspace_file = lambda user_id, raw_path: None
    runtime._read_remote_image_attachment = _no_remote_attachment

    original = "Attached image: MEDIA:missing/zig.png"
    text, attachments = await runtime._extract_media_directive_attachments(
        user_id="user-1",
        session_id="session-1",
        text=original,
        messages=[],
        message_id="msg-1",
    )

    assert text == original
    assert attachments == []
