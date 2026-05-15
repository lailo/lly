"""`SettingsScreen` — modal that hosts the Settings / Authentication / Logging tabs."""

from __future__ import annotations

from typing import ClassVar

from pydantic import ValidationError
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Vertical
from textual.widgets import Button, Footer, Label, TabbedContent

from lly.config import save_settings
from lly.models import Settings
from lly.tui.screens.settings.auth_tab import AuthTab
from lly.tui.screens.settings.files_tab import FilesTab
from lly.tui.screens.settings.general_tab import GeneralTab
from lly.tui.screens.settings.logging_tab import LoggingTab
from lly.tui.widgets.modal import LlyModalScreen


class SettingsScreen(LlyModalScreen[Settings | None]):
    """Edit Settings live. Returns the new Settings on save, None on cancel."""

    # Footer only advertises Cancel; Save is reachable via the per-tab buttons
    # and the `ctrl+s` shortcut still fires (just hidden from the footer).
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "cancel", "Cancel", priority=True),
        Binding("ctrl+s", "save", "Save", priority=True, show=False),
    ]

    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self._initial = settings
        self.last_error: str | None = None

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal-card"):
            yield Label("Settings", classes="modal-title")
            with TabbedContent(initial="tab-general"):
                yield GeneralTab(self._initial)
                yield AuthTab(self._initial)
                yield LoggingTab(self._initial)
                yield FilesTab()
            yield Label("", id="settings-error", classes="modal-error")
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        # Every editable tab carries its own "Save" button; they all dispatch
        # to the same action so the Settings object stays atomic.
        if event.button.id == "settings-save":
            self.action_save()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_save(self) -> None:
        try:
            new = self._build_settings()
        except (ValueError, ValidationError) as err:
            msg = f"Invalid: {err}"
            self.last_error = msg
            self.query_one("#settings-error", Label).update(msg)
            return
        self.last_error = None
        save_settings(new)
        self.dismiss(new)

    def _build_settings(self) -> Settings:
        general = self.query_one(GeneralTab).values()
        return Settings(
            default_password=self.query_one(AuthTab).password_value(),
            log_level=self.query_one(LoggingTab).log_level_value(),
            **general,
        )
