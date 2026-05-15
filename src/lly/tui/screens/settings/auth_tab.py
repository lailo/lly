"""Authentication tab: default Shelly password."""

from __future__ import annotations

from pydantic import SecretStr
from textual.app import ComposeResult
from textual.containers import Grid, Horizontal
from textual.widgets import Button, Input, Label, TabPane

from lly.models import Settings
from lly.tui.widgets.section import Section


class AuthTab(TabPane):
    """Default credentials used for any device without a per-device override."""

    DEFAULT_CSS = """
    AuthTab .settings-grid {
        grid-size: 2;
        grid-columns: 24 1fr;
        grid-gutter: 1 2;
        padding: 0 0 1 2;
        height: auto;
    }
    AuthTab .settings-grid Label { padding-top: 1; }
    AuthTab .settings-grid Input { width: 1fr; }
    """

    def __init__(self, settings: Settings) -> None:
        super().__init__("Authentication", id="tab-auth")
        self._initial = settings

    def compose(self) -> ComposeResult:
        s = self._initial
        with Section("Authentication"), Grid(classes="settings-grid"):
            yield Label("Default password")
            yield Input(
                value=(s.default_password.get_secret_value() if s.default_password else ""),
                placeholder="(unset)",
                password=True,
                id="default_password",
            )
        yield Label(
            "Stored plaintext in config.toml (0600) and sent over HTTP digest auth.",
            classes="modal-error",
        )
        with Horizontal(classes="button-row"):
            yield Button("Save (ctrl+s)", id="settings-save", variant="primary")

    def password_value(self) -> SecretStr | None:
        raw = self.query_one("#default_password", Input).value
        return SecretStr(raw) if raw else None
