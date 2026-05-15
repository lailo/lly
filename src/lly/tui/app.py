"""Top-level Textual application for lly."""

from __future__ import annotations

from collections.abc import Callable
from typing import ClassVar

from pydantic import ValidationError
from textual.app import App
from textual.command import Provider

from lly.config import load_devices, load_settings
from lly.logging import configure as configure_logging
from lly.logging import get_logger
from lly.models import Settings
from lly.tui.commands import LlyCommandProvider
from lly.tui.screens.main import MainScreen

_log = get_logger(__name__)


class LlyApp(App[None]):
    # Surface lly's actions in Textual's built-in command palette (Ctrl+P).
    COMMANDS: ClassVar[set[type[Provider] | Callable[[], type[Provider]]]] = App.COMMANDS | {
        LlyCommandProvider
    }
    COMMAND_PALETTE_BINDING = "ctrl+p"

    CSS = """
    /* Dim the underlying screen whenever any modal is open. We use the
       pre-blended `$background-darken-2` (opaque) rather than an alpha value —
       alpha-blended modal backgrounds break mouse hit-testing in some
       terminals (tmux, certain iTerm configs). */
    ModalScreen { background: $background-darken-2; }
    #status-line { dock: bottom; height: 1; background: $boost; color: $text; padding: 0 1; }
    DataTable { height: 1fr; }
    """

    TITLE = "lly — Shelly fleet"

    def on_mount(self) -> None:
        try:
            settings = load_settings()
        except ValidationError as err:
            settings = Settings()
            _log.error("settings load failed; using defaults", error=str(err))
            self.notify(
                "config.toml is invalid — running with defaults. Check ~/.config/lly/lly.log.",
                severity="error",
                timeout=10,
            )
        configure_logging(settings)
        try:
            devices = load_devices()
        except ValidationError as err:
            devices = []
            _log.error("devices load failed; starting with empty fleet", error=str(err))
            self.notify(
                "devices.toml is invalid — starting empty. Check ~/.config/lly/lly.log.",
                severity="error",
                timeout=10,
            )
        self.push_screen(MainScreen(devices=devices, settings=settings))


def run() -> None:
    LlyApp().run()
