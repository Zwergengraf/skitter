from __future__ import annotations

import asyncio
import json
import mimetypes
import os
import socket
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from rich.markdown import Markdown
from rich.panel import Panel
from rich.syntax import Syntax
from textual import events
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import Button, Footer, Header, Input, RichLog, Static

from .client import ApiError, AuthUser, SkitterApiClient, StreamEvent, ToolRun, UserPrompt
from .onboarding import OnboardingData, OnboardingWizard


@dataclass(slots=True)
class AppConfig:
    api_url: str
    access_token: str | None = None
    device_name: str | None = None
    session_id: str | None = None
    prefer_saved_token: bool = True
    prefer_saved_api_url: bool = True


@dataclass(slots=True)
class ChatEntry:
    title: str
    text: str
    border_style: str
    timestamp: str
    entry_id: str | None = None
    optimistic: bool = False


@dataclass(slots=True)
class PendingApproval:
    tool_run_id: str
    tool_name: str
    payload: dict[str, Any]
    requested_by: str
    created_at: str | None = None


@dataclass(slots=True)
class PendingUserPrompt:
    prompt_id: str
    question: str
    choices: list[str]
    allow_free_text: bool
    created_at: str | None = None


class SessionReady(Message):
    def __init__(self, session_id: str, created: bool) -> None:
        self.session_id = session_id
        self.created = created
        super().__init__()


class AssistantReply(Message):
    def __init__(self, text: str, error: bool = False, attachments: list[dict[str, Any]] | None = None) -> None:
        self.text = text
        self.error = error
        self.attachments = attachments or []
        super().__init__()


class StatusUpdate(Message):
    def __init__(self, title: str, detail: str = "") -> None:
        self.title = title
        self.detail = detail
        super().__init__()


class IncomingEvent(Message):
    def __init__(self, event: StreamEvent) -> None:
        self.event = event
        super().__init__()


class SystemLog(Message):
    def __init__(self, text: str) -> None:
        self.text = text
        super().__init__()


class ToolApprovalDialog(ModalScreen[tuple[str, bool] | None]):
    CSS = """
    ToolApprovalDialog {
        align: center middle;
        background: $surface 50%;
    }

    #approval-card {
        width: 90;
        max-width: 96;
        height: auto;
        max-height: 30;
        border: round $accent;
        background: $panel;
        padding: 0 1;
        overflow-y: auto;
    }

    #approval-title {
        text-style: bold;
        margin-bottom: 0;
    }

    #approval-subtitle {
        color: $text-muted;
        margin-bottom: 1;
    }

    .approval-line {
        margin-bottom: 0;
    }

    #approval-payload-label {
        margin-top: 1;
        color: $text-muted;
    }

    #approval-payload {
        height: auto;
        max-height: 14;
        border: round $accent;
        padding: 0 1;
        overflow-y: auto;
    }

    #approval-actions {
        height: auto;
        margin-top: 1;
    }

    #approval-actions Button {
        width: 1fr;
        margin-right: 1;
    }

    #approval-actions Button:last-child {
        margin-right: 0;
    }
    """

    def __init__(self, approval: PendingApproval) -> None:
        super().__init__()
        self._approval = approval

    def compose(self) -> ComposeResult:
        payload_text = json.dumps(self._approval.payload or {}, indent=2, ensure_ascii=False, sort_keys=True)
        created_text = self._format_created_at(self._approval.created_at)
        with Vertical(id="approval-card"):
            yield Static("Tool approval required", id="approval-title")
            yield Static(
                "The agent is waiting for your decision before this tool can run.",
                id="approval-subtitle",
            )
            yield Static(f"Tool: {self._approval.tool_name}", classes="approval-line")
            yield Static(f"Requested by: {self._approval.requested_by or 'agent'}", classes="approval-line")
            yield Static(f"Requested at: {created_text}", classes="approval-line")
            yield Static("Parameters", id="approval-payload-label")
            yield Static(
                Syntax(payload_text, "json", word_wrap=True, indent_guides=False),
                id="approval-payload",
            )
            with Horizontal(id="approval-actions"):
                yield Button("Deny", id="approval-deny", variant="error")
                yield Button("Approve", id="approval-approve", variant="success")

    @staticmethod
    def _format_created_at(value: str | None) -> str:
        raw = (value or "").strip()
        if not raw:
            return "just now"
        iso = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
        try:
            return datetime.fromisoformat(iso).astimezone().strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            return raw

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id or ""
        if button_id == "approval-deny":
            self.dismiss((self._approval.tool_run_id, False))
            return
        if button_id == "approval-approve":
            self.dismiss((self._approval.tool_run_id, True))
            return


class UserPromptDialog(ModalScreen[str | None]):
    CSS = """
    UserPromptDialog {
        align: center middle;
        background: $surface 50%;
    }

    #user-prompt-card {
        width: 90;
        max-width: 96;
        height: auto;
        max-height: 28;
        border: round $accent;
        background: $panel;
        padding: 0 1;
        overflow-y: auto;
    }

    #user-prompt-title {
        text-style: bold;
    }

    #user-prompt-subtitle {
        color: $text-muted;
        margin-bottom: 1;
    }

    #user-prompt-question {
        margin-bottom: 1;
    }

    .user-prompt-choice {
        margin-bottom: 0;
    }

    #user-prompt-actions {
        height: auto;
        margin-top: 1;
    }

    #user-prompt-actions Button {
        width: 1fr;
        margin-right: 1;
    }

    #user-prompt-actions Button:last-child {
        margin-right: 0;
    }
    """

    def __init__(self, prompt: PendingUserPrompt) -> None:
        super().__init__()
        self._prompt = prompt

    @staticmethod
    def _button_label(text: str, limit: int = 24) -> str:
        value = str(text or "").strip()
        if len(value) <= limit:
            return value
        return value[:limit] + "..."

    def compose(self) -> ComposeResult:
        with Vertical(id="user-prompt-card"):
            yield Static("Skitter needs your input", id="user-prompt-title")
            subtitle = (
                "Choose an option below or type your own reply in the input box."
                if self._prompt.allow_free_text
                else "Choose one of the options below to continue."
            )
            if not self._prompt.choices:
                subtitle = "Type your answer in the input box below to continue."
            yield Static(subtitle, id="user-prompt-subtitle")
            yield Static(self._prompt.question, id="user-prompt-question")
            for index, choice in enumerate(self._prompt.choices[:4], start=1):
                yield Button(
                    self._button_label(choice),
                    id=f"user-prompt-choice-{index}",
                    classes="user-prompt-choice",
                    variant="primary",
                )
            with Horizontal(id="user-prompt-actions"):
                if self._prompt.allow_free_text or not self._prompt.choices:
                    yield Button("Reply in chat", id="user-prompt-dismiss", variant="default")
                else:
                    yield Button("Close", id="user-prompt-dismiss", variant="default")

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id or ""
        if button_id == "user-prompt-dismiss":
            self.dismiss(None)
            return
        if button_id.startswith("user-prompt-choice-"):
            try:
                index = int(button_id.rsplit("-", 1)[1]) - 1
            except ValueError:
                self.dismiss(None)
                return
            if 0 <= index < len(self._prompt.choices):
                self.dismiss(self._prompt.choices[index])
                return
        self.dismiss(None)


class SkitterTuiApp(App[None]):
    CSS = """
    #root {
        width: 100%;
        height: 100%;
        layout: vertical;
    }

    #status {
        height: 1;
        padding: 0 1;
        color: $text-muted;
        background: transparent;
        border: none;
    }

    #chat {
        height: 1fr;
        margin: 0 1;
        background: transparent;
        border: none;
    }

    #input {
        margin: 0 1 1 1;
        background: transparent;
        border: round #4c5563;
    }
    """

    PANEL_USER_STYLE = "#5f7fb8"
    PANEL_ASSISTANT_STYLE = "#5f9d8a"
    PANEL_SYSTEM_STYLE = "grey42"
    PANEL_ERROR_STYLE = "red"
    PANEL_OTHER_STYLE = "#6c7482"

    BINDINGS = [
        ("ctrl+c", "quit", "Quit"),
    ]

    def __init__(self, config: AppConfig) -> None:
        super().__init__()
        self.config = config
        self._session_id: str | None = config.session_id
        self._busy = False
        self._stream_stop = asyncio.Event()
        self._last_attachments: list[dict[str, Any]] = []
        self._pending_attachment_paths: list[Path] = []
        self._seen_message_ids: set[str] = set()
        self._chat_entries: list[ChatEntry] = []
        self._state_path = self._resolve_state_path()
        self._persisted_state = self._load_state()
        self._pending_approvals: dict[str, PendingApproval] = {}
        self._approval_queue: list[str] = []
        self._active_approval_id: str | None = None
        self._pending_user_prompts: dict[str, PendingUserPrompt] = {}
        self._user_prompt_queue: list[str] = []
        self._active_user_prompt_id: str | None = None
        self._thinking_timer = None
        self._thinking_frame = 0
        saved_theme = self._persisted_state.get("theme")
        self._saved_theme = saved_theme if isinstance(saved_theme, str) and saved_theme.strip() else None
        saved_api_url = self._persisted_state.get("api_url")
        if (
            self.config.prefer_saved_api_url
            and isinstance(saved_api_url, str)
            and saved_api_url.strip()
        ):
            self.config.api_url = saved_api_url.strip()
        self.config.api_url = self._normalize_api_url(self.config.api_url)
        saved_token = self._persisted_state.get("access_token")
        if (
            self.config.prefer_saved_token
            and isinstance(saved_token, str)
            and saved_token.strip()
        ):
            self.config.access_token = saved_token.strip()
        elif self.config.access_token:
            self._save_access_token(self.config.access_token)
        self.api = SkitterApiClient(self.config.api_url, api_key=self.config.access_token)
        self._save_api_url(self.config.api_url)
        self._auth_user: AuthUser | None = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Vertical(id="root"):
            yield Static("Connecting...", id="status")
            yield RichLog(id="chat", highlight=True, markup=True, wrap=True)
            yield Input(
                placeholder="Type a message. Commands: /new /memory_reindex /memory_search /schedule_list /model /machine /pair /setup /info /help",
                id="input",
            )
        yield Footer()

    async def on_mount(self) -> None:
        self.title = "Skitter TUI"
        self.sub_title = self.config.api_url
        self._apply_saved_theme()
        self._update_status("Connecting", "checking auth")
        if not self.api.has_token:
            self._append_system(
                "No access token configured.\n"
                "Opening setup wizard. You can also run `/setup` later."
            )
            self._update_status("Setup required", "onboarding")
            self._present_onboarding_wizard()
        self.run_worker(self._bootstrap(), name="bootstrap", group="bootstrap", exclusive=True)

    def watch_theme(self, theme_name: str) -> None:
        if not self.is_mounted:
            return
        self._save_theme(theme_name)

    async def on_unmount(self) -> None:
        self._stream_stop.set()
        await self.api.aclose()

    def _present_onboarding_wizard(self) -> None:
        if isinstance(self.screen, OnboardingWizard):
            return
        self.push_screen(
            OnboardingWizard(
                initial_api_url=self.config.api_url,
                default_display_name=(self.config.device_name or "Skitter User"),
            ),
            self._on_onboarding_closed,
        )

    def _on_onboarding_closed(self, result: OnboardingData | None) -> None:
        if result is None:
            self._append_system("Onboarding canceled. Run `/setup` to continue setup.")
            self._update_status("Ready", "unauthenticated")
            return
        self.run_worker(
            self._apply_onboarding_data(result),
            name="onboarding",
            group="bootstrap",
            exclusive=True,
        )

    async def _apply_onboarding_data(self, data: OnboardingData) -> None:
        self._update_status("Onboarding", "applying configuration")
        self._stream_stop.set()
        self._session_id = None
        self._auth_user = None
        try:
            await self._set_api_url(data.api_url)
        except Exception as exc:
            self._append_error(f"Invalid API URL: {exc}")
            self._update_status("Error", "onboarding failed")
            self._present_onboarding_wizard()
            return

        if data.auth_mode == "token":
            token = data.access_token.strip()
            if not token:
                self._append_error("Access token is required.")
                self._update_status("Ready", "unauthenticated")
                self._present_onboarding_wizard()
                return
            self.api.set_token(token)
            self.config.access_token = token
            self._save_access_token(token)
            self._append_system("Token saved. Reconnecting…")
            self.run_worker(self._bootstrap(), name="bootstrap", group="bootstrap", exclusive=True)
            return

        if data.auth_mode == "setup":
            await self._run_bootstrap_command(data.setup_code, data.display_name)
            return

        await self._run_pair_command(data.pair_code)

    async def on_resize(self, event: events.Resize) -> None:
        del event
        self._replay_chat_entries()

    async def _bootstrap(self) -> None:
        try:
            if not self.api.has_token:
                return
            self._auth_user = await self.api.auth_me()
            if not self._auth_user.approved:
                self.post_message(
                    SystemLog("Your account is not yet approved. An admin has to approve it first.")
                )
                self.post_message(StatusUpdate("Waiting approval", "account pending"))
                return
            if self._session_id:
                self.post_message(SessionReady(self._session_id, created=False))
                return
            session_id = await self.api.create_session(origin="tui", reuse_active=True)
            self.post_message(SessionReady(session_id, created=True))
        except Exception as exc:
            self.post_message(SystemLog(f"Connection failed: {exc}"))
            self.post_message(StatusUpdate("Connection failed", str(exc)))
            if self.api.has_token and "401" in str(exc):
                self.post_message(SystemLog("Authentication failed. Opening setup wizard."))
                self.call_after_refresh(self._present_onboarding_wizard)

    async def on_session_ready(self, message: SessionReady) -> None:
        self._session_id = message.session_id
        self._pending_approvals.clear()
        self._approval_queue.clear()
        self._active_approval_id = None
        self._pending_user_prompts.clear()
        self._user_prompt_queue.clear()
        self._active_user_prompt_id = None
        self._hide_thinking_indicator()
        chat = self.query_one("#chat", RichLog)
        chat.clear()
        self._chat_entries.clear()
        identity = self._auth_user.display_name if self._auth_user else "unknown user"
        self._append_system(
            f"Connected as `{identity}`\n"
            f"Session: `{message.session_id}`\n"
            f"Type `/help` for commands."
        )
        if message.created:
            self._update_status("Ready", "New session created")
        else:
            self._update_status("Ready", "Attached to existing session")
        await self._restart_event_stream(message.session_id)
        self.run_worker(
            self._load_session_history(message.session_id),
            name="history",
            group="history",
            exclusive=True,
        )

    async def _restart_event_stream(self, session_id: str) -> None:
        self._stream_stop.set()
        self._stream_stop = asyncio.Event()
        self.run_worker(
            self._event_stream_loop(session_id=session_id, stop_event=self._stream_stop),
            name="events",
            group="events",
            exclusive=True,
        )

    async def _event_stream_loop(self, session_id: str, stop_event: asyncio.Event) -> None:
        backoff = 1
        while not stop_event.is_set():
            try:
                await self._refresh_pending_approvals(session_id)
                await self._refresh_pending_user_prompts(session_id)
                async for event in self.api.stream_events(session_id=session_id, stop_event=stop_event):
                    if stop_event.is_set():
                        return
                    self.post_message(IncomingEvent(event))
                if stop_event.is_set():
                    return
                raise ApiError("stream closed")
            except Exception as exc:
                if stop_event.is_set():
                    return
                self.post_message(StatusUpdate("Reconnecting", f"event stream error: {exc}"))
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 20)

    async def _load_session_history(self, session_id: str) -> None:
        try:
            detail = await self.api.get_session_detail(session_id)
        except Exception as exc:
            self._append_error(f"Could not load session history: {exc}")
            return
        raw_messages = detail.get("messages")
        if not isinstance(raw_messages, list):
            return
        self._seen_message_ids.clear()
        count = 0
        for item in raw_messages:
            if self._append_history_item(item):
                count += 1
        if count:
            self._append_system(f"Loaded `{count}` messages from this session.")

    async def _sync_new_messages(self, session_id: str) -> None:
        try:
            detail = await self.api.get_session_detail(session_id)
        except Exception:
            return
        raw_messages = detail.get("messages")
        if not isinstance(raw_messages, list):
            return
        for item in raw_messages:
            self._append_history_item(item)

    def _append_history_item(self, item: dict[str, Any]) -> bool:
        if not isinstance(item, dict):
            return False
        message_id = str(item.get("id") or "").strip()
        if not message_id or message_id in self._seen_message_ids:
            return False
        role = str(item.get("role") or "").strip().lower()
        meta = item.get("meta") if isinstance(item.get("meta"), dict) else {}
        attachments = self._normalize_attachments(meta.get("attachments"), message_id=message_id)
        content = str(item.get("content") or "").strip()
        if not content and attachments:
            content = "Uploaded attachments."
        if not content:
            self._seen_message_ids.add(message_id)
            return False
        timestamp = self._format_timestamp(item.get("created_at"))
        if role == "user":
            rendered_content = content
            if attachments:
                rendered_content = f"{rendered_content}\n\n{self._render_attachments_markdown(attachments, include_indices=True)}"
            if self._replace_optimistic_user(rendered_content, timestamp=timestamp):
                self._seen_message_ids.add(message_id)
                return True
            self._append_user(content, attachments=attachments, timestamp=timestamp)
        elif role == "assistant":
            if attachments:
                self._last_attachments = list(attachments)
            self._append_assistant(content, timestamp=timestamp, attachments=attachments)
        elif role == "system":
            self._append_panel("System", content, border_style=self.PANEL_SYSTEM_STYLE, timestamp=timestamp)
        else:
            self._append_panel(
                role.title() or "Message",
                content,
                border_style=self.PANEL_OTHER_STYLE,
                timestamp=timestamp,
            )
        self._seen_message_ids.add(message_id)
        return True

    async def on_incoming_event(self, message: IncomingEvent) -> None:
        event = message.event
        payload = event.data.get("data", {}) if isinstance(event.data.get("data"), dict) else {}
        if event.event == "message_received":
            self._update_status("Thinking", "model run started")
            return
        if event.event == "tool_approval_requested":
            approval = PendingApproval(
                tool_run_id=str(payload.get("tool_run_id") or "").strip(),
                tool_name=str(payload.get("tool_name") or "tool"),
                payload=payload.get("payload") if isinstance(payload.get("payload"), dict) else {},
                requested_by=str(payload.get("requested_by") or "agent"),
            )
            self._queue_pending_approval(approval)
            return
        if event.event == "user_prompt_requested":
            prompt = PendingUserPrompt(
                prompt_id=str(payload.get("prompt_id") or "").strip(),
                question=str(payload.get("question") or "").strip(),
                choices=[str(choice).strip() for choice in (payload.get("choices") or []) if str(choice).strip()],
                allow_free_text=bool(payload.get("allow_free_text", True)),
            )
            self._queue_user_prompt(prompt)
            return
        if event.event == "message_response":
            if self._busy:
                self._update_status("Finalizing", "response ready")
            elif self._session_id:
                self.run_worker(
                    self._sync_new_messages(self._session_id),
                    name="sync",
                    group="sync",
                    exclusive=True,
                )
            return
        if event.event == "session_switched":
            new_session_id = str(payload.get("new_session_id") or "").strip()
            if new_session_id and new_session_id != self._session_id:
                self._update_status("Session changed", "switched from another client")
                self.post_message(SessionReady(new_session_id, created=False))
            return

    def _queue_pending_approval(self, approval: PendingApproval) -> None:
        if not approval.tool_run_id:
            return
        existing = self._pending_approvals.get(approval.tool_run_id)
        if existing is not None:
            if approval.created_at and not existing.created_at:
                existing.created_at = approval.created_at
            if approval.payload and not existing.payload:
                existing.payload = approval.payload
            return
        self._pending_approvals[approval.tool_run_id] = approval
        self._approval_queue.append(approval.tool_run_id)
        self._update_status("Waiting approval", f"tool={approval.tool_name}")
        self.call_after_refresh(self._present_next_approval_dialog)

    def _present_next_approval_dialog(self) -> None:
        if self._active_approval_id is not None:
            return
        while self._approval_queue:
            tool_run_id = self._approval_queue.pop(0)
            approval = self._pending_approvals.get(tool_run_id)
            if approval is None:
                continue
            self._active_approval_id = tool_run_id
            self.push_screen(ToolApprovalDialog(approval), self._on_tool_approval_closed)
            return

    def _on_tool_approval_closed(self, result: tuple[str, bool] | None) -> None:
        if result is None:
            self._active_approval_id = None
            self.call_after_refresh(self._present_next_approval_dialog)
            return
        tool_run_id, approved = result
        self.run_worker(
            self._resolve_tool_approval(tool_run_id=tool_run_id, approved=approved),
            name=f"approval:{tool_run_id}",
            group="approvals",
            exclusive=False,
        )

    async def _refresh_pending_approvals(self, session_id: str) -> None:
        try:
            pending_runs = await self.api.list_pending_tool_runs(session_id=session_id)
        except Exception:
            return
        for item in pending_runs:
            self._queue_pending_approval(self._approval_from_tool_run(item))

    @staticmethod
    def _approval_from_tool_run(item: ToolRun) -> PendingApproval:
        return PendingApproval(
            tool_run_id=item.id,
            tool_name=item.tool,
            payload=item.input,
            requested_by=item.requested_by,
            created_at=item.created_at,
        )

    async def _resolve_tool_approval(self, *, tool_run_id: str, approved: bool) -> None:
        approval = self._pending_approvals.get(tool_run_id)
        tool_name = approval.tool_name if approval else "tool"
        decision_label = "approved" if approved else "denied"
        decided_by = self._auth_user.id if self._auth_user is not None else "tui"
        self._update_status("Submitting approval", f"{decision_label} {tool_name}")
        try:
            if approved:
                await self.api.approve_tool_run(tool_run_id=tool_run_id, decided_by=decided_by)
            else:
                await self.api.deny_tool_run(tool_run_id=tool_run_id, decided_by=decided_by)
        except Exception as exc:
            self._append_error(f"Could not submit approval for `{tool_name}`: {exc}")
            if approval is not None and tool_run_id not in self._approval_queue:
                self._approval_queue.insert(0, tool_run_id)
            self._update_status("Waiting approval", f"tool={tool_name}")
        else:
            self._pending_approvals.pop(tool_run_id, None)
            self._update_status("Ready", "")
        finally:
            if self._active_approval_id == tool_run_id:
                self._active_approval_id = None
            self.call_after_refresh(self._present_next_approval_dialog)

    def _queue_user_prompt(self, prompt: PendingUserPrompt) -> None:
        if not prompt.prompt_id:
            return
        existing = self._pending_user_prompts.get(prompt.prompt_id)
        if existing is not None:
            return
        self._pending_user_prompts[prompt.prompt_id] = prompt
        self._user_prompt_queue.append(prompt.prompt_id)
        self._append_system(self._render_user_prompt_text(prompt))
        self._update_status("Waiting input", "user reply needed")
        self.call_after_refresh(self._present_next_user_prompt_dialog)

    def _present_next_user_prompt_dialog(self) -> None:
        if self._active_user_prompt_id is not None:
            return
        while self._user_prompt_queue:
            prompt_id = self._user_prompt_queue.pop(0)
            prompt = self._pending_user_prompts.get(prompt_id)
            if prompt is None:
                continue
            self._active_user_prompt_id = prompt_id
            self.push_screen(UserPromptDialog(prompt), self._on_user_prompt_closed)
            return

    def _on_user_prompt_closed(self, answer: str | None) -> None:
        prompt_id = self._active_user_prompt_id
        self._active_user_prompt_id = None
        if prompt_id and answer:
            self.run_worker(
                self._submit_user_prompt_answer(prompt_id=prompt_id, answer=answer),
                name=f"user-prompt:{prompt_id}",
                group="user-prompts",
                exclusive=False,
            )
        self.call_after_refresh(self._present_next_user_prompt_dialog)

    async def _refresh_pending_user_prompts(self, session_id: str) -> None:
        try:
            prompts = await self.api.list_pending_user_prompts(session_id=session_id)
        except Exception:
            return
        active_ids = {prompt.id for prompt in prompts}
        for prompt_id in list(self._pending_user_prompts.keys()):
            if prompt_id not in active_ids:
                self._pending_user_prompts.pop(prompt_id, None)
        for item in prompts:
            self._queue_user_prompt(
                PendingUserPrompt(
                    prompt_id=item.id,
                    question=item.question,
                    choices=list(item.choices),
                    allow_free_text=bool(item.allow_free_text),
                    created_at=item.created_at,
                )
            )

    async def _submit_user_prompt_answer(self, *, prompt_id: str, answer: str) -> None:
        self._pending_user_prompts.pop(prompt_id, None)
        if self._busy:
            self._append_system("A request is already running. Please wait for the current response.")
            return
        if not self._session_id:
            self._append_error("No active session.")
            return
        self._busy = True
        self._append_user(answer, optimistic=True)
        self._show_thinking_indicator()
        self._update_status("Thinking", "sending request")
        await self._send_message(answer)

    @staticmethod
    def _render_user_prompt_text(prompt: PendingUserPrompt) -> str:
        lines = [f"Skitter needs your input:\n{prompt.question}"]
        if prompt.choices:
            lines.append("Choices:")
            lines.extend(f"- {choice}" for choice in prompt.choices)
        if prompt.allow_free_text or not prompt.choices:
            lines.append("Reply in chat to continue.")
        return "\n".join(lines)

    async def on_status_update(self, message: StatusUpdate) -> None:
        self._update_status(message.title, message.detail)

    async def on_system_log(self, message: SystemLog) -> None:
        self._append_system(message.text)

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        event.input.value = ""
        if not text and not self._pending_attachment_paths:
            return

        if text.startswith("/"):
            await self._run_command(text)
            return

        if self._busy:
            self._append_system("A request is already running. Please wait for the current response.")
            return

        if not self._session_id:
            self._append_system("No session is active yet. Please wait for startup to finish.")
            return

        self._busy = True
        self._append_user(
            text or "Uploaded attachments.",
            optimistic=True,
            attachments=self._pending_attachment_preview(),
        )
        self._show_thinking_indicator()
        self._update_status("Thinking", "sending request")
        self.run_worker(self._send_message(text), name="send", group="send", exclusive=True)

    async def _run_command(self, raw: str) -> None:
        parts = raw.strip().split(maxsplit=1)
        cmd = parts[0].lower()
        arg = parts[1].strip() if len(parts) > 1 else ""
        if cmd in {"/quit", "/exit"}:
            self.exit()
            return
        if cmd == "/help":
            self._append_system(
                "Commands:\n"
                "- `/new` start a new session\n"
                "- `/memory_reindex` rebuild memory embeddings\n"
                "- `/memory_search <query>` semantic memory search\n"
                "- `/schedule_list` list scheduled jobs\n"
                "- `/schedule_delete <job_id>` delete scheduled job\n"
                "- `/schedule_pause <job_id>` pause scheduled job\n"
                "- `/schedule_resume <job_id>` resume scheduled job\n"
                "- `/tools` show tool approval config\n"
                "- `/model [provider/model]` list or set model\n"
                "- `/machine [name_or_id]` list or set default machine\n"
                "- `/pair` create pairing code (authenticated)\n"
                "- `/info` show session usage info\n"
                "- `/session` show current session id\n"
                "- `/whoami` show authenticated user info\n"
                "- `/setup` open the onboarding wizard\n"
                "- `/bootstrap <setup_code> <display_name>` first-time account setup\n"
                "- `/pair <pair_code>` pair this client to an existing account (if not authenticated)\n"
                "- `/token <access_token>` set access token manually\n"
                "- `/logout` clear access token and disconnect\n"
                "- `/attachments` list last assistant attachments\n"
                "- `/download <index> [target_path]` download attachment\n"
                "- `/attach <path>` attach a local file to the next message\n"
                "- `/unattach [index|all]` remove queued local attachments\n"
                "- `/clear` clear local chat view\n"
                "- `/quit` exit the app"
            )
            return
        if cmd == "/attachments":
            self._show_last_attachments()
            return
        if cmd == "/download":
            await self._handle_download_command(arg)
            return
        if cmd == "/attach":
            await self._handle_attach_command(arg)
            return
        if cmd == "/unattach":
            self._handle_unattach_command(arg)
            return
        if cmd == "/session":
            if self._session_id:
                self._append_system(f"Current session: `{self._session_id}`")
            else:
                self._append_system("No active session.")
            return
        if cmd == "/whoami":
            if self._auth_user is None:
                self._append_system("Not authenticated.")
            else:
                approval = "approved" if self._auth_user.approved else "pending approval"
                self._append_system(
                    f"User: `{self._auth_user.display_name}`\n"
                    f"User ID: `{self._auth_user.id}`\n"
                    f"Status: {approval}"
                )
            return
        if cmd == "/setup":
            self._present_onboarding_wizard()
            return
        if cmd == "/token":
            token = arg.strip()
            if not token:
                self._append_system("Usage: `/token <access_token>`")
                return
            self.api.set_token(token)
            self.config.access_token = token
            self._save_access_token(token)
            self._session_id = None
            self._auth_user = None
            self._append_system("Access token updated. Reconnecting...")
            self.run_worker(self._bootstrap(), name="bootstrap", group="bootstrap", exclusive=True)
            return
        if cmd == "/logout":
            self.api.set_token(None)
            self.config.access_token = None
            self._save_access_token(None)
            self._session_id = None
            self._auth_user = None
            self._stream_stop.set()
            self._update_status("Ready", "unauthenticated")
            self._append_system("Logged out. Use /bootstrap or /pair to authenticate.")
            return
        if cmd == "/bootstrap":
            args = arg.split(maxsplit=1)
            if len(args) < 2:
                self._append_system("Usage: `/bootstrap <setup_code> <display_name>`")
                return
            setup_code = args[0].strip()
            display_name = args[1].strip()
            if not setup_code or not display_name:
                self._append_system("Usage: `/bootstrap <setup_code> <display_name>`")
                return
            await self._run_bootstrap_command(setup_code, display_name)
            return
        if cmd == "/pair":
            pair_code = arg.strip()
            if pair_code:
                if self.api.has_token:
                    self._append_system("Usage: `/pair` to generate a pair code while authenticated.")
                    return
                await self._run_pair_command(pair_code)
                return
            if not self.api.has_token:
                self._append_system("Usage: `/pair <pair_code>`")
                return
            await self._run_remote_command("pair")
            return
        if cmd == "/clear":
            self.action_clear_chat()
            return
        if cmd == "/new":
            if self._busy:
                self._append_system("Cannot create a new session while a request is running.")
                return
            result = await self._run_remote_command("new")
            if result is None:
                return
            new_session_id = str(result.data.get("session_id") or "").strip()
            if new_session_id:
                self.post_message(SessionReady(new_session_id, created=True))
            return
        if cmd == "/memory_reindex":
            await self._run_remote_command("memory_reindex")
            return
        if cmd == "/memory_search":
            query = arg.strip()
            if not query:
                self._append_system("Usage: `/memory_search <query>`")
                return
            await self._run_remote_command("memory_search", {"query": query})
            return
        if cmd == "/schedule_list":
            await self._run_remote_command("schedule_list")
            return
        if cmd == "/schedule_delete":
            job_id = arg.strip()
            if not job_id:
                self._append_system("Usage: `/schedule_delete <job_id>`")
                return
            await self._run_remote_command("schedule_delete", {"job_id": job_id})
            return
        if cmd == "/schedule_pause":
            job_id = arg.strip()
            if not job_id:
                self._append_system("Usage: `/schedule_pause <job_id>`")
                return
            await self._run_remote_command("schedule_pause", {"job_id": job_id})
            return
        if cmd == "/schedule_resume":
            job_id = arg.strip()
            if not job_id:
                self._append_system("Usage: `/schedule_resume <job_id>`")
                return
            await self._run_remote_command("schedule_resume", {"job_id": job_id})
            return
        if cmd == "/tools":
            await self._run_remote_command("tools")
            return
        if cmd == "/model":
            name = arg.strip()
            args = {"model_name": name} if name else None
            result = await self._run_remote_command("model", args)
            if result is None:
                return
            new_session_id = str(result.data.get("session_id") or "").strip()
            if new_session_id and new_session_id != self._session_id:
                self.post_message(SessionReady(new_session_id, created=False))
            return
        if cmd == "/machine":
            target = arg.strip()
            args = {"target_machine": target} if target else None
            await self._run_remote_command("machine", args)
            return
        if cmd == "/info":
            await self._run_remote_command("info")
            return
        self._append_system(f"Unknown command: `{cmd}`. Use `/help`.")

    def _show_last_attachments(self) -> None:
        if not self._last_attachments:
            self._append_system("No attachments in the last assistant response.")
            return
        self._append_system(self._render_attachments_markdown(self._last_attachments, include_indices=True))

    async def _handle_download_command(self, arg: str) -> None:
        if not arg:
            self._append_system("Usage: `/download <index> [target_path]`")
            return
        if not self._last_attachments:
            self._append_system("No attachments available. Run `/attachments` first.")
            return
        parts = arg.split(maxsplit=1)
        try:
            index = int(parts[0])
        except ValueError:
            self._append_system("Attachment index must be a number.")
            return
        if index < 0 or index >= len(self._last_attachments):
            self._append_system(f"Attachment index out of range. Valid: 0..{len(self._last_attachments)-1}")
            return
        item = self._last_attachments[index]
        filename = str(item.get("filename") or f"attachment-{index}")
        target = Path(parts[1]) if len(parts) > 1 else Path(filename)
        download_url = str(item.get("download_url") or "")
        url = str(item.get("url") or "")
        source = download_url or url
        if not source:
            self._append_system("Selected attachment has no downloadable source.")
            return
        try:
            payload = await self.api.download_attachment(source)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
        except Exception as exc:
            self._append_error(f"Download failed: {exc}")
            return
        self._append_system(f"Saved attachment `{filename}` to `{target.resolve()}`.")

    async def _handle_attach_command(self, arg: str) -> None:
        if not arg.strip():
            self._append_system("Usage: `/attach <path>`")
            return
        path = Path(arg.strip()).expanduser()
        if not path.exists() or not path.is_file():
            self._append_system(f"Attachment path not found: `{path}`")
            return
        self._pending_attachment_paths.append(path)
        self._append_system(self._render_pending_attachment_markdown(include_indices=True))

    def _handle_unattach_command(self, arg: str) -> None:
        if not self._pending_attachment_paths:
            self._append_system("No queued attachments.")
            return
        target = arg.strip().lower()
        if not target or target == "all":
            self._pending_attachment_paths = []
            self._append_system("Cleared queued attachments.")
            return
        try:
            index = int(target)
        except ValueError:
            self._append_system("Usage: `/unattach [index|all]`")
            return
        if index < 0 or index >= len(self._pending_attachment_paths):
            self._append_system(f"Attachment index out of range. Valid: 0..{len(self._pending_attachment_paths)-1}")
            return
        removed = self._pending_attachment_paths.pop(index)
        self._append_system(f"Removed queued attachment `{removed.name}`.")

    def _normalize_attachments(self, raw: Any, message_id: str | None = None) -> list[dict[str, str]]:
        normalized: list[dict[str, str]] = []
        if not isinstance(raw, list):
            return normalized
        for idx, item in enumerate(raw):
            if not isinstance(item, dict):
                continue
            filename = str(item.get("filename") or f"attachment-{idx}")
            content_type = str(item.get("content_type") or "application/octet-stream")
            download_url = str(item.get("download_url") or "").strip()
            if not download_url and message_id:
                download_url = f"/v1/messages/{message_id}/attachments/{idx}"
            url = str(item.get("url") or "").strip()
            normalized.append(
                {
                    "filename": filename,
                    "content_type": content_type,
                    "download_url": download_url,
                    "url": url,
                }
            )
        return normalized

    def _render_attachments_markdown(self, attachments: list[dict[str, str]], include_indices: bool = False) -> str:
        lines = ["Attachments:"]
        for idx, item in enumerate(attachments):
            prefix = f"{idx}. " if include_indices else "- "
            filename = item.get("filename", "attachment")
            content_type = item.get("content_type", "application/octet-stream")
            download_url = self.api.absolute_url(item.get("download_url", ""))
            url = item.get("url", "")
            if download_url:
                lines.append(f"{prefix}`{filename}` ({content_type}) [download]({download_url})")
            elif url:
                lines.append(f"{prefix}`{filename}` ({content_type}) [source]({url})")
            else:
                lines.append(f"{prefix}`{filename}` ({content_type})")
        return "\n".join(lines)

    def _render_pending_attachment_markdown(self, include_indices: bool = False) -> str:
        lines = ["Queued attachments for the next message:"]
        for idx, path in enumerate(self._pending_attachment_paths):
            prefix = f"{idx}. " if include_indices else "- "
            content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            lines.append(f"{prefix}`{path.name}` ({content_type})")
        return "\n".join(lines)

    def _pending_attachment_preview(self) -> list[dict[str, str]] | None:
        if not self._pending_attachment_paths:
            return None
        return [
            {
                "filename": path.name,
                "content_type": mimetypes.guess_type(path.name)[0] or "application/octet-stream",
                "download_url": "",
                "url": "",
            }
            for path in self._pending_attachment_paths
        ]

    async def _send_message(self, text: str) -> None:
        if not self._session_id:
            self.post_message(AssistantReply("No active session.", error=True))
            return
        try:
            queued_paths = list(self._pending_attachment_paths)
            await self.api.send_message(
                session_id=self._session_id,
                text=text,
                attachment_paths=queued_paths,
            )
            self._pending_attachment_paths = []
            await self._sync_new_messages(self._session_id)
            self.post_message(AssistantReply("", error=False, attachments=[]))
        except Exception as exc:
            self.post_message(AssistantReply(f"Request failed: {exc}", error=True))

    async def on_assistant_reply(self, message: AssistantReply) -> None:
        self._busy = False
        self._hide_thinking_indicator()
        if message.error:
            self._append_error(message.text)
            self._update_status("Error", "request failed")
        else:
            if message.text.strip():
                self._last_attachments = list(message.attachments)
                self._append_assistant(message.text, attachments=message.attachments)
            self._update_status("Ready", "")

    async def action_new_session(self) -> None:
        self._update_status("Creating session", "")
        try:
            session_id = await self.api.create_session(origin="tui", reuse_active=False)
        except Exception as exc:
            self._append_error(f"Could not create session: {exc}")
            self._update_status("Error", "session creation failed")
            return
        self._session_id = session_id
        self._last_attachments = []
        self._append_system(f"Started new session: `{session_id}`")
        await self._restart_event_stream(session_id)
        self.run_worker(
            self._load_session_history(session_id),
            name="history",
            group="history",
            exclusive=True,
        )
        self._update_status("Ready", "new session active")

    def action_clear_chat(self) -> None:
        chat = self.query_one("#chat", RichLog)
        chat.clear()
        self._chat_entries.clear()
        self._append_system("Chat view cleared.")

    def _append_user(
        self,
        text: str,
        *,
        optimistic: bool = False,
        attachments: list[dict[str, str]] | None = None,
        timestamp: str | None = None,
    ) -> None:
        final_text = text
        if attachments:
            final_text = f"{final_text}\n\n{self._render_attachments_markdown(attachments, include_indices=True)}"
        self._append_panel(
            "You",
            final_text,
            border_style=self.PANEL_USER_STYLE,
            optimistic=optimistic,
            timestamp=timestamp,
        )

    def _replace_optimistic_user(self, text: str, *, timestamp: str) -> bool:
        for entry in self._chat_entries:
            if entry.title != "You" or not entry.optimistic:
                continue
            if entry.text != text:
                continue
            entry.timestamp = timestamp
            entry.optimistic = False
            self._replay_chat_entries()
            return True
        return False

    def _append_assistant(
        self,
        text: str,
        *,
        timestamp: str | None = None,
        attachments: list[dict[str, str]] | None = None,
    ) -> None:
        final_text = text
        if attachments:
            final_text = f"{final_text}\n\n{self._render_attachments_markdown(attachments, include_indices=True)}"
        self._append_panel(
            "Skitter",
            final_text,
            border_style=self.PANEL_ASSISTANT_STYLE,
            timestamp=timestamp,
        )

    def _append_system(self, text: str) -> None:
        self._append_panel("System", text, border_style=self.PANEL_SYSTEM_STYLE)

    def _append_error(self, text: str) -> None:
        self._append_panel("Error", text, border_style=self.PANEL_ERROR_STYLE)

    def _append_panel(
        self,
        title: str,
        text: str,
        border_style: str,
        timestamp: str | None = None,
        *,
        entry_id: str | None = None,
        optimistic: bool = False,
    ) -> None:
        entry = ChatEntry(
            title=title,
            text=text,
            border_style=border_style,
            timestamp=timestamp or datetime.now().strftime("%H:%M:%S"),
            entry_id=entry_id,
            optimistic=optimistic,
        )
        self._chat_entries.append(entry)
        self._render_chat_entry(entry)

    def _show_thinking_indicator(self) -> None:
        existing = self._find_entry("__thinking__")
        if existing is None:
            self._append_panel(
                "Skitter",
                "Thinking.",
                border_style=self.PANEL_ASSISTANT_STYLE,
                entry_id="__thinking__",
            )
            self._thinking_frame = 0
        if self._thinking_timer is None:
            self._thinking_timer = self.set_interval(0.45, self._advance_thinking_indicator, pause=False)
        else:
            self._thinking_timer.resume()

    def _hide_thinking_indicator(self) -> None:
        if self._thinking_timer is not None:
            self._thinking_timer.pause()
        self._remove_entry("__thinking__")

    def _advance_thinking_indicator(self) -> None:
        entry = self._find_entry("__thinking__")
        if entry is None:
            if self._thinking_timer is not None:
                self._thinking_timer.pause()
            return
        frames = ["Thinking.", "Thinking..", "Thinking..."]
        self._thinking_frame = (self._thinking_frame + 1) % len(frames)
        entry.text = frames[self._thinking_frame]
        self._replay_chat_entries()

    def _find_entry(self, entry_id: str) -> ChatEntry | None:
        for entry in self._chat_entries:
            if entry.entry_id == entry_id:
                return entry
        return None

    def _remove_entry(self, entry_id: str) -> None:
        before = len(self._chat_entries)
        self._chat_entries = [entry for entry in self._chat_entries if entry.entry_id != entry_id]
        if len(self._chat_entries) != before:
            self._replay_chat_entries()

    def _render_chat_entry(self, entry: ChatEntry) -> None:
        chat = self.query_one("#chat", RichLog)
        # Keep one extra column of slack to avoid horizontal scrollbars after resizes.
        panel_width = max(24, chat.size.width - 4)
        panel = Panel(
            Markdown(entry.text),
            title=f"{entry.title} {entry.timestamp}",
            border_style=entry.border_style,
            title_align="left",
            width=panel_width,
        )
        chat.write(panel)
        chat.scroll_end(animate=False)

    def _replay_chat_entries(self) -> None:
        chat = self.query_one("#chat", RichLog)
        snapshot = list(self._chat_entries)
        chat.clear()
        if not snapshot:
            return
        for entry in snapshot:
            self._render_chat_entry(entry)

    def _format_timestamp(self, value: Any) -> str:
        if isinstance(value, str) and value:
            iso = value[:-1] + "+00:00" if value.endswith("Z") else value
            try:
                dt = datetime.fromisoformat(iso)
                return dt.astimezone().strftime("%H:%M:%S")
            except ValueError:
                pass
        return datetime.now().strftime("%H:%M:%S")

    def _update_status(self, title: str, detail: str) -> None:
        status = self.query_one("#status", Static)
        if detail:
            status.update(f"{title} · {detail}")
        else:
            status.update(title)

    async def _run_bootstrap_command(self, setup_code: str, display_name: str) -> None:
        self._update_status("Authenticating", "bootstrap")
        device_name = self.config.device_name or socket.gethostname()
        try:
            _, user = await self.api.bootstrap(
                bootstrap_code=setup_code,
                display_name=display_name,
                device_name=device_name,
                device_type="tui",
            )
        except Exception as exc:
            self._append_error(f"Bootstrap failed: {exc}")
            self._update_status("Error", "bootstrap failed")
            return
        self._auth_user = user
        self.config.access_token = self.api.token
        self._save_access_token(self.config.access_token)
        self._session_id = None
        self._append_system(f"Authenticated as `{user.display_name}`. Reconnecting…")
        self.run_worker(self._bootstrap(), name="bootstrap", group="bootstrap", exclusive=True)

    async def _run_pair_command(self, pair_code: str) -> None:
        self._update_status("Authenticating", "pairing")
        device_name = self.config.device_name or socket.gethostname()
        try:
            _, user = await self.api.pair(
                pair_code=pair_code,
                device_name=device_name,
                device_type="tui",
            )
        except Exception as exc:
            self._append_error(f"Pair failed: {exc}")
            self._update_status("Error", "pair failed")
            return
        self._auth_user = user
        self.config.access_token = self.api.token
        self._save_access_token(self.config.access_token)
        self._session_id = None
        self._append_system(f"Paired as `{user.display_name}`. Reconnecting…")
        self.run_worker(self._bootstrap(), name="bootstrap", group="bootstrap", exclusive=True)

    async def _run_remote_command(self, command: str, args: dict[str, Any] | None = None):
        try:
            result = await self.api.execute_command(command=command, args=args, origin="tui")
        except Exception as exc:
            self._append_error(f"Command failed: {exc}")
            return None
        if result.message:
            self._append_system(result.message)
        else:
            self._append_system("Command completed.")
        return result

    def _resolve_state_path(self) -> Path:
        config_home = os.environ.get("XDG_CONFIG_HOME", "").strip()
        if not config_home:
            config_home = str(Path.home() / ".config")
        return Path(config_home) / "skitter-tui" / "state.json"

    def _load_state(self) -> dict[str, Any]:
        try:
            payload = json.loads(self._state_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return {}
        if not isinstance(payload, dict):
            return {}
        return payload

    def _apply_saved_theme(self) -> None:
        if not self._saved_theme:
            return
        try:
            self.theme = self._saved_theme
        except Exception:
            # Ignore invalid or removed theme names and keep Textual default.
            return

    def _save_theme(self, theme_name: str) -> None:
        self._save_state_value("theme", theme_name)

    def _save_access_token(self, token: str | None) -> None:
        value = token.strip() if isinstance(token, str) else ""
        self._save_state_value("access_token", value or None)

    def _save_state_value(self, key: str, value: Any | None) -> None:
        if value is None:
            self._persisted_state.pop(key, None)
        else:
            self._persisted_state[key] = value
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            self._state_path.write_text(json.dumps(self._persisted_state), encoding="utf-8")
        except OSError:
            return

    async def _set_api_url(self, api_url: str) -> None:
        normalized = self._normalize_api_url(api_url)
        if normalized == self.config.api_url:
            return
        old_api = self.api
        self.api = SkitterApiClient(normalized, api_key=self.config.access_token)
        self.config.api_url = normalized
        self.sub_title = normalized
        self._save_api_url(normalized)
        await old_api.aclose()

    def _save_api_url(self, api_url: str) -> None:
        self._save_state_value("api_url", self._normalize_api_url(api_url))

    @staticmethod
    def _normalize_api_url(value: str) -> str:
        normalized = (value or "").strip().rstrip("/")
        if not normalized:
            return "http://localhost:8000"
        return normalized
