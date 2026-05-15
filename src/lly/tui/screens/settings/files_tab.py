"""Files tab: read-only paths to the on-disk config + log files."""

from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Grid
from textual.widgets import Label, Static, TabPane

from lly.logging import log_path
from lly.paths import devices_path, settings_path
from lly.tui.widgets.section import Section


class FilesTab(TabPane):
    """Show where lly's settings, device list and log live."""

    DEFAULT_CSS = """
    FilesTab .files-grid {
        grid-size: 2;
        grid-columns: 16 1fr;
        grid-gutter: 1 2;
        padding: 0 0 1 2;
        height: auto;
    }
    FilesTab .files-grid Label { padding-top: 0; color: $text-muted; }
    FilesTab .files-grid Static { width: 1fr; }
    FilesTab .file-missing { color: $warning; }
    """

    def __init__(self) -> None:
        super().__init__("Files", id="tab-files")

    def compose(self) -> ComposeResult:
        with Section("Config"), Grid(classes="files-grid"):
            yield Label("settings")
            yield from self._row(settings_path())
            yield Label("devices")
            yield from self._row(devices_path())

        with Section("Logs"), Grid(classes="files-grid"):
            yield Label("file log")
            yield from self._row(log_path())

    def _row(self, path: Path) -> ComposeResult:
        """One cell describing a file: full path, plus a tag if it's not on disk yet."""
        exists = path.exists()
        text = str(path) if exists else f"{path}  (not yet written)"
        yield Static(text, classes="" if exists else "file-missing")
