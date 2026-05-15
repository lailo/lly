"""Settings tab: discovery + polling knobs."""

from __future__ import annotations

from typing import TypedDict

from textual.app import ComposeResult
from textual.containers import Grid, Horizontal
from textual.widgets import Button, Input, Label, TabPane

from lly.models import Settings
from lly.tui.widgets.section import Section


class GeneralValues(TypedDict):
    scan_timeout_s: float
    refresh_interval_s: float
    request_timeout_s: float
    refresh_concurrency: int


class GeneralTab(TabPane):
    """Scan/refresh/timeout/concurrency."""

    DEFAULT_CSS = """
    GeneralTab .settings-grid {
        grid-size: 2;
        grid-columns: 24 1fr;
        grid-gutter: 1 2;
        padding: 0 0 1 2;
        height: auto;
    }
    GeneralTab .settings-grid Label { padding-top: 1; }
    GeneralTab .settings-grid Input { width: 1fr; }
    """

    def __init__(self, settings: Settings) -> None:
        super().__init__("Settings", id="tab-general")
        self._initial = settings

    def compose(self) -> ComposeResult:
        s = self._initial
        with Section("Discovery"), Grid(classes="settings-grid"):
            yield Label("Scan timeout (s)")
            yield Input(value=str(s.scan_timeout_s), id="scan_timeout_s", type="number")

        with Section("Polling"), Grid(classes="settings-grid"):
            yield Label("Refresh interval (s)")
            yield Input(value=str(s.refresh_interval_s), id="refresh_interval_s", type="number")
            yield Label("Request timeout (s)")
            yield Input(value=str(s.request_timeout_s), id="request_timeout_s", type="number")
            yield Label("Refresh concurrency")
            yield Input(
                value=str(s.refresh_concurrency), id="refresh_concurrency", type="integer"
            )

        with Horizontal(classes="button-row"):
            yield Button("Save (ctrl+s)", id="settings-save", variant="primary")

    def values(self) -> GeneralValues:
        """Return the raw numeric values; the screen passes them to `Settings(...)`."""
        return GeneralValues(
            scan_timeout_s=float(self.query_one("#scan_timeout_s", Input).value),
            refresh_interval_s=float(self.query_one("#refresh_interval_s", Input).value),
            request_timeout_s=float(self.query_one("#request_timeout_s", Input).value),
            refresh_concurrency=int(self.query_one("#refresh_concurrency", Input).value),
        )
