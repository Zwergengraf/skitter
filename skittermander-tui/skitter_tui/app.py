from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from rich.markdown import Markdown
from rich.panel import Panel
from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.message import Message
from textual.widgets import Footer, Header, Input, RichLog, Static

from .client import ApiError, SkitterApiClient, StreamEvent


@dataclass(slots=True)
class AppConfig:
    api_url: str
    user_id: str
    api_key: str | None = None
    session_id: str | None = None


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


class SkitterTuiApp(App[None]):
    CSS = """
    #root {
        width: 100%;
        height: 100%;
        layout: vertical;
    }

    #status {
        height: 3;
        padding: 0 2;
        border: tall;
    }

    #chat {
        height: 1fr;
        margin: 0 1;
        border: round;
    }

    #input {
        margin: 1 1 1 1;
        border: round;
    }
    """

    PANEL_USER_STYLE = "cyan"
    PANEL_ASSISTANT_STYLE = "green"
    PANEL_SYSTEM_STYLE = "yellow"
    PANEL_ERROR_STYLE = "red"
    PANEL_OTHER_STYLE = "magenta"

    BINDINGS = [
        ("ctrl+c", "quit", "Quit"),
    ]

    def __init__(self, config: AppConfig) -> None:
        super().__init__()
        self.config = config
        self.api = SkitterApiClient(config.api_url, api_key=config.api_key)
        self._session_id: str | None = config.session_id
        self._busy = False
        self._stream_stop = asyncio.Event()
        self._last_attachments: list[dict[str, Any]] = []

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Vertical(id="root"):
            yield Static("Connecting...", id="status")
            yield RichLog(id="chat", highlight=True, markup=True, wrap=True)
            yield Input(
                placeholder="Type a message. Commands: /new /session /attachments /download /help /clear /quit",
                id="input",
            )
        yield Footer()

    async def on_mount(self) -> None:
        self.title = "Skittermander TUI"
        self.sub_title = self.config.api_url
        self._update_status("Connecting", f"user={self.config.user_id}")
        self.run_worker(self._bootstrap(), name="bootstrap", group="bootstrap", exclusive=True)

    async def on_unmount(self) -> None:
        self._stream_stop.set()
        await self.api.aclose()

    async def _bootstrap(self) -> None:
        try:
            if self._session_id:
                self.post_message(SessionReady(self._session_id, created=False))
                return
            session_id = await self.api.create_session(self.config.user_id, origin="tui", reuse_active=True)
            self.post_message(SessionReady(session_id, created=True))
        except Exception as exc:
            self.post_message(StatusUpdate("Connection failed", str(exc)))

    async def on_session_ready(self, message: SessionReady) -> None:
        self._session_id = message.session_id
        chat = self.query_one("#chat", RichLog)
        chat.clear()
        self._append_system(
            f"Connected as `{self.config.user_id}`\n"
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
        count = 0
        for item in raw_messages:
            if not isinstance(item, dict):
                continue
            role = str(item.get("role") or "").strip().lower()
            message_id = str(item.get("id") or "")
            meta = item.get("meta") if isinstance(item.get("meta"), dict) else {}
            attachments = self._normalize_attachments(meta.get("attachments"), message_id=message_id)
            content = str(item.get("content") or "").strip()
            if not content and attachments:
                content = "Received attachments."
            if not content:
                continue
            timestamp = self._format_timestamp(item.get("created_at"))
            if role == "user":
                self._append_panel("You", content, border_style=self.PANEL_USER_STYLE, timestamp=timestamp)
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
            count += 1
        if count:
            self._append_system(f"Loaded `{count}` messages from this session.")

    async def on_incoming_event(self, message: IncomingEvent) -> None:
        event = message.event
        if event.event == "message_received":
            self._update_status("Thinking", "model run started")
            return
        if event.event == "tool_approval_requested":
            tool_name = str(event.data.get("data", {}).get("tool_name") or "tool")
            self._update_status("Waiting approval", f"tool={tool_name}")
            return
        if event.event == "message_response":
            if self._busy:
                self._update_status("Finalizing", "response ready")
            return

    async def on_status_update(self, message: StatusUpdate) -> None:
        self._update_status(message.title, message.detail)

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        event.input.value = ""
        if not text:
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

        self._append_user(text)
        self._busy = True
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
                "- `/new` create a new session\n"
                "- `/session` show current session id\n"
                "- `/attachments` list last assistant attachments\n"
                "- `/download <index> [target_path]` download attachment\n"
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
        if cmd == "/session":
            if self._session_id:
                self._append_system(f"Current session: `{self._session_id}`")
            else:
                self._append_system("No active session.")
            return
        if cmd == "/clear":
            self.action_clear_chat()
            return
        if cmd == "/new":
            if self._busy:
                self._append_system("Cannot create a new session while a request is running.")
                return
            await self.action_new_session()
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

    async def _send_message(self, text: str) -> None:
        if not self._session_id:
            self.post_message(AssistantReply("No active session.", error=True))
            return
        try:
            response = await self.api.send_message(
                session_id=self._session_id,
                user_id=self.config.user_id,
                text=text,
            )
            attachments = self._normalize_attachments(response.get("attachments"))
            content = str(response.get("content") or "").strip()
            if not content and attachments:
                content = "Received attachments."
            if not content:
                content = "(empty response)"
            self.post_message(AssistantReply(content, error=False, attachments=attachments))
        except Exception as exc:
            self.post_message(AssistantReply(f"Request failed: {exc}", error=True))

    async def on_assistant_reply(self, message: AssistantReply) -> None:
        self._busy = False
        if message.error:
            self._append_error(message.text)
            self._update_status("Error", "request failed")
        else:
            self._last_attachments = list(message.attachments)
            self._append_assistant(message.text, attachments=message.attachments)
            self._update_status("Ready", "")

    async def action_new_session(self) -> None:
        self._update_status("Creating session", "")
        try:
            session_id = await self.api.create_session(self.config.user_id, origin="tui", reuse_active=False)
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
        self._append_system("Chat view cleared.")

    def _append_user(self, text: str) -> None:
        self._append_panel("You", text, border_style=self.PANEL_USER_STYLE)

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
            "Skittermander",
            final_text,
            border_style=self.PANEL_ASSISTANT_STYLE,
            timestamp=timestamp,
        )

    def _append_system(self, text: str) -> None:
        self._append_panel("System", text, border_style=self.PANEL_SYSTEM_STYLE)

    def _append_error(self, text: str) -> None:
        self._append_panel("Error", text, border_style=self.PANEL_ERROR_STYLE)

    def _append_panel(self, title: str, text: str, border_style: str, timestamp: str | None = None) -> None:
        chat = self.query_one("#chat", RichLog)
        ts = timestamp or datetime.now().strftime("%H:%M:%S")
        markdown = Markdown(text)
        panel = Panel(markdown, title=f"{title} {ts}", border_style=border_style)
        chat.write(panel)
        chat.scroll_end(animate=False)

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
            status.update(f"{title}\n{detail}")
        else:
            status.update(title)
