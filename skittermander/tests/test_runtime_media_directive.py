from pathlib import Path

from skittermander.core.events import EventBus
from skittermander.core.runtime import AgentRuntime


def _runtime() -> AgentRuntime:
    return AgentRuntime(event_bus=EventBus(), graph=object())


def test_extract_media_directive_inline_text(tmp_path: Path) -> None:
    runtime = _runtime()
    image = tmp_path / "zig.png"
    image.write_bytes(b"\x89PNG\r\n")

    runtime._resolve_user_workspace_file = lambda user_id, raw_path: image if raw_path == "avatars/zig.png" else None

    text, attachments = runtime._extract_media_directive_attachments(
        user_id="user-1",
        text="Attached image: MEDIA:avatars/zig.png",
    )

    assert text == "Attached image:"
    assert len(attachments) == 1
    assert attachments[0].filename == "zig.png"
    assert attachments[0].path == str(image)


def test_extract_media_directive_line_only(tmp_path: Path) -> None:
    runtime = _runtime()
    image = tmp_path / "zig.png"
    image.write_bytes(b"\x89PNG\r\n")

    runtime._resolve_user_workspace_file = lambda user_id, raw_path: image if raw_path == "avatars/zig.png" else None

    text, attachments = runtime._extract_media_directive_attachments(
        user_id="user-1",
        text="MEDIA:avatars/zig.png",
    )

    assert text == ""
    assert len(attachments) == 1
    assert attachments[0].filename == "zig.png"


def test_extract_media_directive_unresolved_kept() -> None:
    runtime = _runtime()
    runtime._resolve_user_workspace_file = lambda user_id, raw_path: None

    original = "Attached image: MEDIA:missing/zig.png"
    text, attachments = runtime._extract_media_directive_attachments(
        user_id="user-1",
        text=original,
    )

    assert text == original
    assert attachments == []
