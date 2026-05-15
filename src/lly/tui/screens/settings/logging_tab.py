"""Logging tab: file/console log level."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Grid, Horizontal
from textual.widgets import Button, Label, Select, TabPane

from lly.models import LogLevel, Settings
from lly.tui.widgets.section import Section


class LoggingTab(TabPane):
    """Pick how chatty `lly.log` and stderr should be."""

    DEFAULT_CSS = """
    LoggingTab .settings-grid {
        grid-size: 2;
        grid-columns: 24 1fr;
        grid-gutter: 1 2;
        padding: 0 0 1 2;
        height: auto;
    }
    LoggingTab .settings-grid Label { padding-top: 1; }
    LoggingTab .settings-grid Select { width: 1fr; }
    """

    def __init__(self, settings: Settings) -> None:
        super().__init__("Logging", id="tab-logging")
        self._initial = settings

    def compose(self) -> ComposeResult:
        s = self._initial
        with Section("Logging"), Grid(classes="settings-grid"):
            yield Label("File log level")
            yield Select[str](
                options=[(level.value, level.value) for level in LogLevel],
                value=s.log_level.value,
                id="log_level",
                allow_blank=False,
            )
        with Horizontal(classes="button-row"):
            yield Button("Save (ctrl+s)", id="settings-save", variant="primary")

    def log_level_value(self) -> LogLevel:
        raw = self.query_one("#log_level", Select).value
        # `allow_blank=False` plus the defaulted initial value mean this is
        # always a real string at submit time, but narrow defensively.
        return LogLevel(raw) if isinstance(raw, str) else self._initial.log_level
