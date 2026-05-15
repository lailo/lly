"""Settings tab: editable per-device fields (currently just the name)."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Grid, Horizontal
from textual.widgets import Button, Input, Label, TabPane

from lly.models import Device
from lly.tui.widgets.section import Section


class SettingsTab(TabPane):
    """Editable device-side settings."""

    DEFAULT_CSS = """
    SettingsTab .settings-grid {
        grid-size: 2;
        grid-columns: 16 1fr;
        grid-gutter: 1 2;
        padding: 0 0 1 2;
        height: auto;
    }
    SettingsTab .settings-grid Label { padding-top: 1; }
    SettingsTab .settings-grid Input { width: 1fr; }
    """

    def __init__(self, device: Device) -> None:
        super().__init__("Settings", id="tab-settings")
        self._device = device

    def compose(self) -> ComposeResult:
        with Section("Identity"), Grid(classes="settings-grid"):
            yield Label("Name")
            yield Input(value=self._device.name, id="detail-name", placeholder=self._device.id)
        with Horizontal(classes="button-row"):
            yield Button("Save (ctrl+s)", id="save-name", variant="primary")
        with Section("Danger zone"), Horizontal(classes="button-row"):
            # Two-press confirm wired in the screen; the label flips to
            # "Confirm" between the two clicks.
            yield Button("Remove device (d)", id="remove-device", variant="error")

    def name_value(self) -> str:
        """Current text in the name field — whitespace preserved, caller trims."""
        return self.query_one("#detail-name", Input).value
