from __future__ import annotations

from skitter.transports.discord import (
    DISCORD_MESSAGE_CHAR_LIMIT,
    _append_status_suffix,
    _build_approval_request_content,
)


def test_build_approval_request_content_keeps_small_payload_intact() -> None:
    content = _build_approval_request_content("write", {"path": "notes.txt", "content": "hello"})

    assert "Agent wants to run `write`" in content
    assert '"path": "notes.txt"' in content
    assert "Approve or deny?" in content
    assert len(content) <= DISCORD_MESSAGE_CHAR_LIMIT


def test_build_approval_request_content_truncates_large_payload_in_the_middle() -> None:
    payload = {
        "path": "/tmp/" + ("nested/" * 80) + "file.txt",
        "content": "A" * 4000,
        "tail": "THE-END",
    }

    content = _build_approval_request_content("write", payload)

    assert len(content) <= DISCORD_MESSAGE_CHAR_LIMIT
    assert "Agent wants to run `write`" in content
    assert "..." in content
    assert '"tail": "THE-END"' in content
    assert "Approve or deny?" in content


def test_append_status_suffix_keeps_message_within_discord_limit() -> None:
    content = "X" * DISCORD_MESSAGE_CHAR_LIMIT

    updated = _append_status_suffix(content, ":white_check_mark: Approved")

    assert len(updated) <= DISCORD_MESSAGE_CHAR_LIMIT
    assert updated.endswith(" -> :white_check_mark: Approved")
    assert "..." in updated
