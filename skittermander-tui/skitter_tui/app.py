from __future__ import annotations

import asyncio
import json
import os
import socket
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from rich.markdown import Markdown
from rich.panel import Panel
from textual import events
from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.message import Message
from textual.widgets import Footer, Header, Input, RichLog, Static

from .client import ApiError, AuthUser, SkitterApiClient, StreamEvent


@dataclass(slots=True)
class AppConfig:
    api_url: str
    access_token: str | None = None
    device_name: str | None = None
    session_id: str | None = None


@dataclass(slots=True)
class ChatEntry:
    title: str
    text: str
    border_style: str
    timestamp: str


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
        self.api = SkitterApiClient(config.api_url, api_key=config.access_token)
        self._session_id: str | None = config.session_id
        self._busy = False
        self._stream_stop = asyncio.Event()
        self._last_attachments: list[dict[str, Any]] = []
        self._seen_message_ids: set[str] = set()
        self._chat_entries: list[ChatEntry] = []
        self._is_replaying = False
        self._state_path = self._resolve_state_path()
        self._saved_theme = self._load_saved_theme()
        self._auth_user: AuthUser | None = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Vertical(id="root"):
            yield Static("Connecting...", id="status")
            yield RichLog(id="chat", highlight=True, markup=True, wrap=True)
            yield Input(
                placeholder="Type a message. Commands: /new /session /whoami /bootstrap /pair /token /attachments /download /help /clear /quit",
                id="input",
            )
        yield Footer()

    async def on_mount(self) -> None:
        self.title = "Skittermander TUI"
        self.sub_title = self.config.api_url
        self._apply_saved_theme()
        self._update_status("Connecting", "checking auth")
        if not self.api.has_token:
            self._append_system(
                "No access token configured.\n"
                "Use `/bootstrap <setup_code> <display_name>` for first-time setup, "
                "or `/pair <pair_code>` to pair an existing account."
            )
            self._update_status("Ready", "unauthenticated")
        self.run_worker(self._bootstrap(), name="bootstrap", group="bootstrap", exclusive=True)

    def watch_theme(self, theme_name: str) -> None:
        if not self.is_mounted:
            return
        self._save_theme(theme_name)

    async def on_unmount(self) -> None:
        self._stream_stop.set()
        await self.api.aclose()

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

    async def on_session_ready(self, message: SessionReady) -> None:
        self._session_id = message.session_id
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
            content = "Received attachments."
        if not content:
            self._seen_message_ids.add(message_id)
            return False
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
        self._seen_message_ids.add(message_id)
        return True

    async def on_incoming_event(self, message: IncomingEvent) -> None:
        event = message.event
        payload = event.data.get("data", {}) if isinstance(event.data.get("data"), dict) else {}
        if event.event == "message_received":
            self._update_status("Thinking", "model run started")
            return
        if event.event == "tool_approval_requested":
            tool_name = str(payload.get("tool_name") or "tool")
            self._update_status("Waiting approval", f"tool={tool_name}")
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

    async def on_status_update(self, message: StatusUpdate) -> None:
        self._update_status(message.title, message.detail)

    async def on_system_log(self, message: SystemLog) -> None:
        self._append_system(message.text)

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
                "- `/whoami` show authenticated user info\n"
                "- `/bootstrap <setup_code> <display_name>` first-time account setup\n"
                "- `/pair <pair_code>` pair this client to an existing account\n"
                "- `/token <access_token>` set access token manually\n"
                "- `/logout` clear access token and disconnect\n"
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
        if cmd == "/token":
            token = arg.strip()
            if not token:
                self._append_system("Usage: `/token <access_token>`")
                return
            self.api.set_token(token)
            self.config.access_token = token
            self._session_id = None
            self._auth_user = None
            self._append_system("Access token updated. Reconnecting...")
            self.run_worker(self._bootstrap(), name="bootstrap", group="bootstrap", exclusive=True)
            return
        if cmd == "/logout":
            self.api.set_token(None)
            self.config.access_token = None
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
            if not pair_code:
                self._append_system("Usage: `/pair <pair_code>`")
                return
            await self._run_pair_command(pair_code)
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
            await self.api.send_message(
                session_id=self._session_id,
                text=text,
            )
            await self._sync_new_messages(self._session_id)
            self.post_message(AssistantReply("", error=False, attachments=[]))
        except Exception as exc:
            self.post_message(AssistantReply(f"Request failed: {exc}", error=True))

    async def on_assistant_reply(self, message: AssistantReply) -> None:
        self._busy = False
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
        entry = ChatEntry(
            title=title,
            text=text,
            border_style=border_style,
            timestamp=timestamp or datetime.now().strftime("%H:%M:%S"),
        )
        if not self._is_replaying:
            self._chat_entries.append(entry)
        self._render_chat_entry(entry)

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
        if not self._chat_entries:
            return
        chat = self.query_one("#chat", RichLog)
        snapshot = list(self._chat_entries)
        self._is_replaying = True
        try:
            chat.clear()
            for entry in snapshot:
                self._render_chat_entry(entry)
        finally:
            self._is_replaying = False

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
        self._session_id = None
        self._append_system(f"Paired as `{user.display_name}`. Reconnecting…")
        self.run_worker(self._bootstrap(), name="bootstrap", group="bootstrap", exclusive=True)

    def _resolve_state_path(self) -> Path:
        config_home = os.environ.get("XDG_CONFIG_HOME", "").strip()
        if not config_home:
            config_home = str(Path.home() / ".config")
        return Path(config_home) / "skitter-tui" / "state.json"

    def _load_saved_theme(self) -> str | None:
        try:
            payload = json.loads(self._state_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return None
        theme = payload.get("theme")
        return theme.strip() if isinstance(theme, str) and theme.strip() else None

    def _apply_saved_theme(self) -> None:
        if not self._saved_theme:
            return
        try:
            self.theme = self._saved_theme
        except Exception:
            # Ignore invalid or removed theme names and keep Textual default.
            return

    def _save_theme(self, theme_name: str) -> None:
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {"theme": theme_name}
            self._state_path.write_text(json.dumps(payload), encoding="utf-8")
        except OSError:
            return
