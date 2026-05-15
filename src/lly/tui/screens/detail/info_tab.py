"""Info tab: read-only identity (model, host, ids).

State + controls live on the Actions tab so the user sees status and buttons
side by side.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.widgets import Static, TabPane

from lly.models import Device, DeviceKind
from lly.tui.widgets.section import Section


class InfoTab(TabPane):
    """Static identifying info for a single device."""

    def __init__(self, device: Device, kind: DeviceKind) -> None:
        super().__init__("Info", id="tab-info")
        self._device = device
        self._kind = kind

    def compose(self) -> ComposeResult:
        d = self._device
        with Section("Device info"):
            yield Static(
                f"id     {d.id}\n"
                f"host   {d.host}\n"
                f"model  {d.model}  •  gen {d.gen}\n"
                f"kind   {self._kind.value}",
                classes="indent",
            )
