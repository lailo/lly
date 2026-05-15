"""Firmware tab: current version + OTA update controls."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Button, Static, TabPane

from lly.models import Device, DeviceStatus
from lly.tui.widgets.section import Section


class FirmwareTab(TabPane):
    """Display the installed firmware + offer stable/beta OTA updates."""

    def __init__(self, device: Device) -> None:
        super().__init__("Firmware", id="tab-firmware")
        self._device = device

    def compose(self) -> ComposeResult:
        with Section("Firmware"):
            yield Static("…", id="detail-updates", classes="indent")
            with Horizontal(classes="button-row"):
                yield Button("Update stable (u)", id="update-stable", disabled=True)
                yield Button("Update beta (b)", id="update-beta", disabled=True)

    def render_status(self, device: Device, status: DeviceStatus | None) -> None:
        """Refresh the version display + enable/disable update buttons."""
        current = device.fw_version or "-"
        available = status.update_summary() if status is not None else "checking…"
        self.query_one("#detail-updates", Static).update(
            f"Current:    {current}\nAvailable:  {available}"
        )
        stable_available = bool(status and status.update_stable)
        beta_available = bool(status and status.update_beta)
        for btn in self.query("#update-stable").results(Button):
            btn.disabled = not stable_available
            btn.label = (
                f"Update stable {status.update_stable} (u)"  # type: ignore[union-attr]
                if stable_available
                else "Update stable (u)"
            )
        for btn in self.query("#update-beta").results(Button):
            btn.disabled = not beta_available
            btn.label = (
                f"Update beta {status.update_beta} (b)"  # type: ignore[union-attr]
                if beta_available
                else "Update beta (b)"
            )
