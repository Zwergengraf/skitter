from __future__ import annotations

from dataclasses import dataclass

import httpx
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Static


@dataclass(slots=True)
class OnboardingData:
    api_url: str
    auth_mode: str
    setup_code: str = ""
    display_name: str = ""
    pair_code: str = ""
    access_token: str = ""


class OnboardingWizard(ModalScreen[OnboardingData | None]):
    CSS = """
    OnboardingWizard {
        align: center middle;
        background: $surface 45%;
    }

    #wizard-card {
        width: 74;
        max-width: 90;
        height: auto;
        max-height: 28;
        border: round $accent;
        background: $panel;
        padding: 0 1;
        overflow-y: auto;
    }

    #wizard-card.step-welcome {
        max-height: 22;
    }

    #wizard-card.step-server {
        max-height: 24;
    }

    #wizard-card.step-auth {
        max-height: 21;
    }

    #wizard-title {
        content-align: center middle;
        text-style: bold;
        height: auto;
        margin-bottom: 0;
    }

    #wizard-subtitle {
        content-align: center middle;
        color: $text-muted;
        margin-bottom: 0;
    }

    .step {
        display: none;
        height: auto;
        margin-bottom: 0;
    }

    .step-visible {
        display: block;
    }

    #step-2 {
        height: auto;
        margin: 0;
        padding: 0;
    }

    #step-2 > .mode-buttons {
        height: auto;
        margin-top: 0;
        margin-bottom: 0;
    }

    .mode-buttons Button {
        width: 1fr;
        margin-right: 0;
    }

    .mode-buttons Button:last-child {
        margin-right: 0;
    }

    .auth-mode {
        display: none;
        height: 0;
        margin: 0;
        padding: 0;
        overflow: hidden;
    }

    .auth-visible {
        display: block;
        height: auto;
        margin: 0;
        padding: 0;
        overflow: hidden;
    }

    .field-label {
        margin-top: 0;
        color: $text-muted;
    }

    #wizard-test-row {
        height: auto;
        margin-top: 1;
        margin-bottom: 0;
    }

    #wizard-test-result {
        height: auto;
        min-height: 1;
        color: $text-muted;
        margin-top: 0;
    }

    #wizard-status {
        min-height: 1;
        color: $text-muted;
        margin-top: 0;
        margin-bottom: 0;
    }

    #wizard-actions {
        margin-top: 0;
        height: auto;
    }

    #wizard-actions Button {
        margin-right: 1;
    }

    #wizard-actions Button:last-child {
        margin-right: 0;
    }
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
    ]

    def __init__(self, *, initial_api_url: str, default_display_name: str) -> None:
        super().__init__()
        self._step = 0
        self._auth_mode = "pair"
        self._testing_connection = False
        self._initial_api_url = initial_api_url.strip() or "http://localhost:8000"
        self._default_display_name = default_display_name.strip() or "Skitter User"

    def compose(self) -> ComposeResult:
        with Vertical(id="wizard-card"):
            yield Static("Skitter Setup Wizard", id="wizard-title")
            yield Static("Step 1 of 3 · Welcome", id="wizard-subtitle")

            with Vertical(id="step-0", classes="step step-visible"):
                yield Static("")
                yield Static(
                    "Welcome. This wizard sets API URL and authenticates this TUI client.\n"
                    "Use setup code for first account, or pair code for an existing account."
                )
                yield Static("")

            with Vertical(id="step-1", classes="step"):
                yield Static("API URL", classes="field-label")
                yield Input(value=self._initial_api_url, placeholder="http://localhost:8000", id="wizard-api-url")
                with Horizontal(id="wizard-test-row"):
                    yield Button("Test Connection", id="wizard-test", variant="primary")
                yield Static("", id="wizard-test-result")

            with Vertical(id="step-2", classes="step"):
                yield Static("Authentication Method", classes="field-label")
                with Horizontal(classes="mode-buttons"):
                    yield Button("Setup", id="mode-setup", variant="success")
                    yield Button("Pair", id="mode-pair", variant="primary")
                    yield Button("Token", id="mode-token", variant="default")

                with Vertical(id="auth-setup", classes="auth-mode"):
                    yield Static("Display Name", classes="field-label")
                    yield Input(value=self._default_display_name, placeholder="Your display name", id="wizard-display-name")
                    yield Static("Setup Code", classes="field-label")
                    yield Input(placeholder="First-time setup code", password=True, id="wizard-setup-code")

                with Vertical(id="auth-pair", classes="auth-mode auth-visible"):
                    yield Static("Pair Code", classes="field-label")
                    yield Input(placeholder="ABCD-1234", id="wizard-pair-code")

                with Vertical(id="auth-token", classes="auth-mode"):
                    yield Static("Access Token", classes="field-label")
                    yield Input(placeholder="Paste access token", password=True, id="wizard-access-token")

                yield Static("", id="wizard-status")

            with Horizontal(id="wizard-actions"):
                yield Button("Cancel", id="wizard-cancel", variant="error")
                yield Button("Back", id="wizard-back", variant="default", disabled=True)
                yield Button("Next", id="wizard-next", variant="success")

    def action_cancel(self) -> None:
        self.dismiss(None)

    async def on_mount(self) -> None:
        self._refresh_step_ui()
        self._refresh_auth_mode_ui()

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id or ""
        if button_id == "wizard-cancel":
            self.dismiss(None)
            return
        if button_id == "wizard-back":
            if self._step > 0:
                self._step -= 1
                self._refresh_step_ui()
            return
        if button_id == "wizard-next":
            await self._advance_or_finish()
            return
        if button_id == "wizard-test":
            if self._testing_connection:
                return
            await self._test_connection()
            return
        if button_id.startswith("mode-"):
            mode = button_id.split("-", maxsplit=1)[1].strip().lower()
            if mode in {"setup", "pair", "token"}:
                self._auth_mode = mode
                self._refresh_auth_mode_ui()
            return

    async def _advance_or_finish(self) -> None:
        if self._step < 2:
            self._step += 1
            self._refresh_step_ui()
            return
        data = self._collect_data()
        if data is None:
            return
        self.dismiss(data)

    def _collect_data(self) -> OnboardingData | None:
        api_url = self.query_one("#wizard-api-url", Input).value.strip()
        if not api_url:
            self._set_status("API URL is required.", is_error=True)
            return None

        if self._auth_mode == "setup":
            display_name = self.query_one("#wizard-display-name", Input).value.strip()
            setup_code = self.query_one("#wizard-setup-code", Input).value.strip()
            if not display_name or not setup_code:
                self._set_status("Display name and setup code are required.", is_error=True)
                return None
            return OnboardingData(
                api_url=api_url,
                auth_mode="setup",
                setup_code=setup_code,
                display_name=display_name,
            )

        if self._auth_mode == "pair":
            pair_code = self.query_one("#wizard-pair-code", Input).value.strip()
            if not pair_code:
                self._set_status("Pair code is required.", is_error=True)
                return None
            return OnboardingData(api_url=api_url, auth_mode="pair", pair_code=pair_code)

        access_token = self.query_one("#wizard-access-token", Input).value.strip()
        if not access_token:
            self._set_status("Access token is required.", is_error=True)
            return None
        return OnboardingData(api_url=api_url, auth_mode="token", access_token=access_token)

    async def _test_connection(self) -> None:
        api_url = self.query_one("#wizard-api-url", Input).value.strip()
        result = self.query_one("#wizard-test-result", Static)
        test_button = self.query_one("#wizard-test", Button)
        if not api_url:
            result.update(Text("API URL is required.", style="bold red"))
            return
        self._testing_connection = True
        test_button.disabled = True
        test_button.label = "Testing…"
        result.update(Text("Checking connection…", style="dim"))
        self.refresh()
        target = f"{api_url.rstrip('/')}/health"
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                response = await client.get(target)
            if response.status_code == 200:
                result.update(Text("Server reachable.", style="green"))
            else:
                result.update(Text(f"Health check failed: HTTP {response.status_code}.", style="bold red"))
        except Exception as exc:
            result.update(Text(f"Connection failed: {exc}", style="bold red"))
        finally:
            self._testing_connection = False
            test_button.disabled = False
            test_button.label = "Test Connection"

    def _refresh_step_ui(self) -> None:
        for idx in range(3):
            step_widget = self.query_one(f"#step-{idx}", Vertical)
            step_widget.set_class(idx == self._step, "step-visible")

        card = self.query_one("#wizard-card", Vertical)
        card.remove_class("step-welcome", "step-server", "step-auth")
        if self._step == 0:
            card.add_class("step-welcome")
        elif self._step == 1:
            card.add_class("step-server")
        else:
            card.add_class("step-auth")

        subtitle = self.query_one("#wizard-subtitle", Static)
        if self._step == 0:
            subtitle.update("Step 1 of 3 · Welcome")
        elif self._step == 1:
            subtitle.update("Step 2 of 3 · Server")
        else:
            subtitle.update("Step 3 of 3 · Sign In")

        back_button = self.query_one("#wizard-back", Button)
        back_button.disabled = self._step == 0

        next_button = self.query_one("#wizard-next", Button)
        next_button.label = "Connect" if self._step == 2 else "Next"

    def _refresh_auth_mode_ui(self) -> None:
        auth_setup = self.query_one("#auth-setup", Vertical)
        auth_pair = self.query_one("#auth-pair", Vertical)
        auth_token = self.query_one("#auth-token", Vertical)

        auth_setup.set_class(self._auth_mode == "setup", "auth-visible")
        auth_pair.set_class(self._auth_mode == "pair", "auth-visible")
        auth_token.set_class(self._auth_mode == "token", "auth-visible")

        setup_btn = self.query_one("#mode-setup", Button)
        pair_btn = self.query_one("#mode-pair", Button)
        token_btn = self.query_one("#mode-token", Button)

        setup_btn.variant = "success" if self._auth_mode == "setup" else "default"
        pair_btn.variant = "primary" if self._auth_mode == "pair" else "default"
        token_btn.variant = "warning" if self._auth_mode == "token" else "default"

        self._set_status("")

    def _set_status(self, text: str, *, is_error: bool = False) -> None:
        status = self.query_one("#wizard-status", Static)
        if not text:
            status.update("")
            return
        style = "bold red" if is_error else "dim"
        status.update(Text(text, style=style))
