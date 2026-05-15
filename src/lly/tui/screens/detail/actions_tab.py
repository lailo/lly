"""Actions tab: live state + things the device can actively do."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Button, ProgressBar, Static, TabPane

from lly.models import DeviceKind, DeviceStatus
from lly.tui.widgets.section import Section


class ActionsTab(TabPane):
    """State block (read-only) + control buttons (kind-specific) + Reboot.

    Keeping state + controls together means the user can see "is it on?" right
    next to the button that toggles it — no tab-switching to decide.
    """

    DEFAULT_CSS = """
    ActionsTab #detail-cover-bar { width: 1fr; }
    /* Default ProgressBar track is near-invisible against the modal scrim;
       boost the track colour so the empty (0%) state still reads as a bar. */
    ActionsTab #detail-cover-bar Bar > .bar--bar { color: $accent; background: $boost; }
    ActionsTab #detail-cover-bar Bar > .bar--indeterminate { color: $accent; }
    ActionsTab .indent { padding-left: 2; }
    ActionsTab #detail-state-transient { color: $text-muted; padding-top: 1; }
    """

    def __init__(self, kind: DeviceKind) -> None:
        super().__init__("Actions", id="tab-actions")
        self._kind = kind

    def compose(self) -> ComposeResult:
        with Section("State"):
            if self._kind is DeviceKind.COVER:
                # `show_eta=False` strips the time-remaining column — pointless
                # for a cover where we just want the current position bar.
                # The widget already renders its own "N%" label, so we only
                # show a small extra Static for transient states (opening /
                # closing) underneath.
                yield ProgressBar(
                    total=100, show_eta=False, id="detail-cover-bar", classes="indent"
                )
                yield Static("", id="detail-state-transient", classes="indent")
            else:
                yield Static("…", id="detail-state", classes="indent")

        if self._kind is DeviceKind.SWITCH:
            with Section("Switch"), Horizontal(classes="button-row"):
                yield Button("Toggle (t)", id="toggle", variant="primary")
        elif self._kind is DeviceKind.COVER:
            with Section("Cover"), Horizontal(classes="button-row"):
                yield Button("Open (o)", id="open", variant="primary")
                yield Button("Close (c)", id="close-cover")
                yield Button("Stop (s)", id="stop")

        with Section("System"), Horizontal(classes="button-row"):
            yield Button("Reboot (R)", id="reboot")

    def render_status(self, status: DeviceStatus | None) -> None:
        """Reflect the latest status into the State block."""
        if self._kind is DeviceKind.COVER:
            self._render_cover_status(status)
            return
        self.query_one("#detail-state", Static).update(status.render() if status else "…")

    def _render_cover_status(self, status: DeviceStatus | None) -> None:
        bar = self.query_one("#detail-cover-bar", ProgressBar)
        transient = self.query_one("#detail-state-transient", Static)
        if status is None or not status.online:
            bar.update(progress=0)
            transient.update(status.render() if status else "…")
            return
        raw = status.cover_position
        if raw is None:
            bar.update(progress=0)
            transient.update((status.cover_state or "?").upper())
            return
        # Mirror the table's inverted reading: Shelly's 0 = closed, but users
        # of blinders think 100% = fully closed. See `_render_cover` in
        # `models/status.py` for the same flip applied to the text cell.
        pct = 100 - max(0, min(100, raw))
        bar.update(progress=pct)
        state = (status.cover_state or "").lower()
        # ProgressBar already renders the N% label — only surface the verb
        # ("opening" / "closing") here so we don't duplicate the percentage.
        transient.update(state if state in ("opening", "closing") else "")
