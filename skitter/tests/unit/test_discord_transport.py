from __future__ import annotations

from types import SimpleNamespace

import pytest

from skitter.transports.discord import (
    ApprovalView,
    DISCORD_MESSAGE_CHAR_LIMIT,
    DISCORD_SELECT_OPTION_LIMIT,
    ModelSelectView,
    _lookup_outbound_message_metadata,
    _remember_internal_message,
    _remember_outbound_message_metadata,
    _should_ignore_inbound_message,
    _append_status_suffix,
    _build_approval_request_content,
    _build_model_menu_message,
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


@pytest.mark.asyncio
async def test_approval_view_has_approve_and_deny_buttons() -> None:
    view = ApprovalView("tool-run-1", approval_service=None)
    labels = [child.label for child in view.children]

    assert "Approve" in labels
    assert "Deny" in labels


def test_build_model_menu_message_mentions_discord_limit_when_truncated() -> None:
    message = _build_model_menu_message(total_models=40, shown_models=DISCORD_SELECT_OPTION_LIMIT)

    assert "dropdown below" in message
    assert "first 25 of 40 configured models" in message


def test_model_select_view_limits_options_to_discord_max() -> None:
    transport = SimpleNamespace()
    models = [f"provider/model-{index}" for index in range(30)]

    view = ModelSelectView(owner_user_id="123", model_names=models, transport=transport)
    select = view.children[0]

    assert len(view.model_names) == DISCORD_SELECT_OPTION_LIMIT
    assert len(select.options) == DISCORD_SELECT_OPTION_LIMIT
    assert select.options[0].value == "provider/model-0"
    assert select.options[-1].value == "provider/model-24"


@pytest.mark.asyncio
async def test_model_select_view_selection_dispatches_model_command_and_disables_menu() -> None:
    calls: list[tuple[str, dict | None, bool]] = []

    class _Transport:
        async def _handle_command(self, interaction, command: str, extra: dict | None = None, ephemeral: bool = False):
            _ = interaction
            calls.append((command, extra, ephemeral))

    class _Message:
        def __init__(self) -> None:
            self.edits: list[dict[str, object]] = []

        async def edit(self, **kwargs) -> None:
            self.edits.append(kwargs)

    interaction = SimpleNamespace(user=SimpleNamespace(id=123))
    view = ModelSelectView(
        owner_user_id="123",
        model_names=["provider/main", "provider/fast"],
        transport=_Transport(),
    )
    view.message = _Message()

    await view.handle_selection(interaction, "provider/fast")

    assert calls == [("model", {"model_name": "provider/fast"}, False)]
    assert view.message.edits == [{"view": None}]


@pytest.mark.asyncio
async def test_model_select_view_rejects_other_users() -> None:
    calls: list[tuple[str, dict | None, bool]] = []

    class _Transport:
        async def _handle_command(self, interaction, command: str, extra: dict | None = None, ephemeral: bool = False):
            _ = interaction
            calls.append((command, extra, ephemeral))

    class _Response:
        def __init__(self) -> None:
            self.messages: list[tuple[str, bool]] = []

        def is_done(self) -> bool:
            return False

        async def send_message(self, content: str, *, ephemeral: bool = False) -> None:
            self.messages.append((content, ephemeral))

    interaction = SimpleNamespace(
        user=SimpleNamespace(id=999),
        response=_Response(),
        followup=SimpleNamespace(send=None),
    )
    view = ModelSelectView(
        owner_user_id="123",
        model_names=["provider/main", "provider/fast"],
        transport=_Transport(),
    )

    await view.handle_selection(interaction, "provider/fast")

    assert calls == []
    assert interaction.response.messages == [
        ("This model menu belongs to someone else. Run `/model` yourself.", True)
    ]


def test_should_ignore_inbound_message_for_same_bot_user() -> None:
    message = SimpleNamespace(id=101, author=SimpleNamespace(id=55))

    assert _should_ignore_inbound_message(message, own_bot_user_id=55) is True


def test_should_ignore_inbound_message_for_registered_internal_message() -> None:
    message = SimpleNamespace(id=202, author=SimpleNamespace(id=77))
    _remember_internal_message(message)

    assert _should_ignore_inbound_message(message, own_bot_user_id=99) is True


def test_should_not_ignore_other_bot_message_without_registry() -> None:
    message = SimpleNamespace(id=303, author=SimpleNamespace(id=88))

    assert _should_ignore_inbound_message(message, own_bot_user_id=99) is False


def test_lookup_outbound_message_metadata_returns_trusted_sender_fields() -> None:
    message = SimpleNamespace(id=404, author=SimpleNamespace(id=12))
    _remember_outbound_message_metadata(
        message,
        {
            "skitter_sender_internal_user_id": "user-1",
            "skitter_sender_profile_id": "profile-1",
            "skitter_sender_profile_slug": "assistant",
            "skitter_transport_account_key": "discord:profile:profile-1",
            "skitter_message_kind": "agent_reply",
            "ignored_field": "nope",
        },
    )

    assert _lookup_outbound_message_metadata(message) == {
        "skitter_sender_internal_user_id": "user-1",
        "skitter_sender_profile_id": "profile-1",
        "skitter_sender_profile_slug": "assistant",
        "skitter_transport_account_key": "discord:profile:profile-1",
        "skitter_message_kind": "agent_reply",
    }
