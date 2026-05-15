"""Command-palette commands for lly.

Surfaces the main-screen actions (and a per-device "Open detail" entry when a
row is highlighted) so the user can reach them via Ctrl+P.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING

from textual.command import DiscoveryHit, Hit, Provider

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

CommandTuple = tuple[str, str, Callable[[], None]]


class LlyCommandProvider(Provider):
    """Expose lly's keyboard actions in the Ctrl+P palette."""

    async def discover(self) -> AsyncIterator[DiscoveryHit]:
        for name, help_text, callback in self._commands():
            yield DiscoveryHit(name, callback, help=help_text)

    async def search(self, query: str) -> AsyncIterator[Hit]:
        matcher = self.matcher(query)
        for name, help_text, callback in self._commands():
            score = matcher.match(name)
            if score > 0:
                yield Hit(score, matcher.highlight(name), callback, help=help_text)

    # ------------------------------------------------------------------

    def _commands(self) -> Iterable[CommandTuple]:
        # Local import to avoid a circular dep with `lly.tui.app`.
        from lly.tui.screens.main import MainScreen

        screen = self.app.screen
        items: list[CommandTuple] = []

        if isinstance(screen, MainScreen):
            dev = screen.cursor_device()
            if dev is not None:
                items.append(
                    (
                        f"Open detail: {dev.name}",
                        f"Open the per-device actions modal for {dev.host}",
                        self._dispatch("open_detail"),
                    )
                )

        items.extend(
            [
                (
                    "Scan for devices",
                    "Open the mDNS scan modal to discover new Shelly devices",
                    self._dispatch("scan"),
                ),
                (
                    "Settings",
                    "Edit default password, scan timeout, refresh interval, …",
                    self._dispatch("open_settings"),
                ),
                (
                    "Refresh status",
                    "Re-poll every saved device immediately",
                    self._dispatch("refresh_now"),
                ),
                ("Quit lly", "Exit the application", self._dispatch_app("quit")),
            ]
        )
        return items

    def _dispatch(self, action: str) -> Callable[[], None]:
        """Build a callback that fires `action_<action>` on the current MainScreen."""
        from lly.tui.screens.main import MainScreen

        def run() -> None:
            screen = self.app.screen
            if isinstance(screen, MainScreen):
                method = getattr(screen, f"action_{action}", None)
                if callable(method):
                    method()

        return run

    def _dispatch_app(self, action: str) -> Callable[[], None]:
        def run() -> None:
            method = getattr(self.app, f"action_{action}", None)
            if callable(method):
                method()

        return run
