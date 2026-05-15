"""`DeviceDetailScreen` — the modal that hosts the Info / Settings / Firmware tabs."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Vertical
from textual.timer import Timer
from textual.widgets import Button, Footer, Label, TabbedContent

from lly.fleet import connect
from lly.logging import get_logger
from lly.models import Device, DeviceKind, DeviceStatus, Settings
from lly.shelly.client import ShellyClient, ShellyError
from lly.shelly.rpc import (
    cover_close,
    cover_open,
    cover_stop,
    fetch_status,
    reboot,
    set_device_name,
    switch_set,
    update_firmware,
)
from lly.tui.screens.detail.actions_tab import ActionsTab
from lly.tui.screens.detail.firmware_tab import FirmwareTab
from lly.tui.screens.detail.info_tab import InfoTab
from lly.tui.screens.detail.result import DetailResult
from lly.tui.screens.detail.settings_tab import SettingsTab
from lly.tui.widgets.modal import LlyModalScreen

_log = get_logger(__name__)


class DeviceDetailScreen(LlyModalScreen[DetailResult]):
    """Inspect a single device and run actions on it.

    Action availability is gated by `device.kind` (resolved via live status,
    not the mDNS hint stored in `Device`):
    - SWITCH → toggle on/off
    - COVER  → open/close/stop
    - all    → rename, reboot, OTA update
    """

    # Footer hides shortcuts that have a prominent button in the tabs (Save,
    # Reboot, firmware updates). Toggle vs Open/Close/Stop are filtered by
    # `check_action` so we only show the set that applies to the current kind.
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "close", "Close", priority=True),
        Binding("ctrl+s", "save_name", "Save name", show=False),
        Binding("R", "reboot", "Reboot", show=False),
        # `u` is the only update binding shown in the footer; it greys out
        # when no stable update is available (see `check_action` below).
        Binding("u", "update_stable", "Update"),
        Binding("b", "update_beta", "Beta", show=False),
        # Not priority — must yield to the name `Input` on the Settings tab so
        # the user can type characters that double as action shortcuts.
        Binding("t", "toggle_switch", "Toggle"),
        Binding("o", "cover_open", "Open"),
        Binding("c", "cover_close", "Close"),
        Binding("s", "cover_stop", "Stop"),
        Binding("d", "remove", "Remove", show=False),
    ]

    def __init__(self, device: Device, settings: Settings) -> None:
        super().__init__()
        self._device = device
        self._settings = settings
        self._status: DeviceStatus | None = None
        self._refresh_timer: Timer | None = None
        self._remove_armed = False
        # Permanently strip the bindings that don't apply to this device's
        # kind — `check_action` only greys them out in the footer, but the
        # user wants them gone entirely.
        self._prune_inapplicable_bindings()

    def _prune_inapplicable_bindings(self) -> None:
        """Drop the kind-irrelevant key bindings from this instance's binding map."""
        kind = self._effective_kind()
        if kind is DeviceKind.SWITCH:
            drop = {"o", "c", "s"}
        elif kind is DeviceKind.COVER:
            drop = {"t"}
        else:
            return
        for key in drop:
            self._bindings.key_to_bindings.pop(key, None)

    def _effective_kind(self) -> DeviceKind:
        """Live status wins over the mDNS guess (many Plus2PMs run either profile)."""
        if self._status is not None and self._status.kind is not DeviceKind.OTHER:
            return self._status.kind
        return self._device.kind

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        """Filter the Footer per current kind and update availability.

        - Kind-irrelevant bindings have already been pruned at __init__; this
          method handles the remaining dynamic cases.
        - `update_stable` stays visible in the footer at all times so users
          know the shortcut exists, but is *greyed* (False) when no stable
          update is available.
        """
        del parameters
        kind = self._effective_kind()
        if action == "toggle_switch":
            return True if kind is DeviceKind.SWITCH else None
        if action in {"cover_open", "cover_close", "cover_stop"}:
            return True if kind is DeviceKind.COVER else None
        if action == "update_stable":
            return bool(self._status and self._status.update_stable)
        return True

    # --- compose ---------------------------------------------------------

    def compose(self) -> ComposeResult:
        d = self._device
        kind = self._effective_kind()
        with Vertical(classes="modal-card"):
            yield Label(d.name, classes="modal-title", id="detail-title")
            with TabbedContent(initial="tab-actions"):
                yield ActionsTab(kind)
                yield InfoTab(d, kind)
                yield SettingsTab(d)
                yield FirmwareTab(d)
            yield Label("", id="detail-error", classes="modal-error")
        yield Footer()

    # --- lifecycle -------------------------------------------------------

    def on_mount(self) -> None:
        self._refresh_status_async()
        self._refresh_timer = self.set_interval(
            self._settings.refresh_interval_s, self._refresh_status_async
        )

    def on_unmount(self) -> None:
        if self._refresh_timer is not None:
            self._refresh_timer.stop()

    # --- buttons ---------------------------------------------------------

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "toggle":
            self.action_toggle_switch()
        elif bid == "open":
            self.action_cover_open()
        elif bid == "close-cover":
            self.action_cover_close()
        elif bid == "stop":
            self.action_cover_stop()
        elif bid == "reboot":
            self.action_reboot()
        elif bid == "update-stable":
            self.action_update_stable()
        elif bid == "update-beta":
            self.action_update_beta()
        elif bid == "save-name":
            self.action_save_name()
        elif bid == "remove-device":
            self.action_remove()

    # --- key actions -----------------------------------------------------

    def action_close(self) -> None:
        self.dismiss(DetailResult())

    def action_save_name(self) -> None:
        new_name = self.query_one(SettingsTab).name_value().strip()
        if not new_name:
            self._set_error("Name can't be empty.")
            return
        if new_name == self._device.name:
            self.dismiss(DetailResult())
            return
        # Push to the device first; only update locally on RPC success. This
        # keeps lly's view in sync with what `Shelly.GetDeviceInfo` will
        # report on the next scan/refresh.
        self.run_worker(self._do_save_name(new_name), exclusive=False, group="detail-rpc")

    async def _do_save_name(self, new_name: str) -> None:
        self._remove_armed = False
        try:
            async with connect(self._device, self._settings) as client:
                await set_device_name(client, new_name)
        except ShellyError as err:
            _log.error(
                "rename failed",
                device_id=self._device.id,
                host=self._device.host,
                code=err.code,
                error=err.message,
            )
            self._set_error(f"Rename failed: {err.message}")
            self.app.notify(f"Rename failed: {err.message}", severity="error")
            return
        updated = self._device.model_copy(update={"name": new_name})
        self.app.notify(f"Renamed to {new_name}")
        self.dismiss(DetailResult(renamed_to=updated))

    def action_remove(self) -> None:
        # Two-press confirm to avoid wiping a device by mistake. The button on
        # the Settings tab flips its label to "Confirm remove" between presses.
        if not self._remove_armed:
            self._remove_armed = True
            self._set_error(f"Confirm: click Remove again to delete {self._device.name}.")
            for btn in self.query("#remove-device").results(Button):
                btn.label = "Confirm remove? (d)"
            return
        self.dismiss(DetailResult(removed=True))

    def action_toggle_switch(self) -> None:
        if self._effective_kind() is not DeviceKind.SWITCH:
            self._set_error("This device is running the cover profile, not switch.")
            return
        target = not bool(self._status and self._status.on)

        async def _do(client: ShellyClient) -> None:
            await switch_set(client, 0, on=target)

        self._run_rpc(f"Turn {'ON' if target else 'OFF'}", _do)

    def action_cover_open(self) -> None:
        if self._effective_kind() is DeviceKind.COVER:
            self._run_rpc("Open", lambda c: cover_open(c, 0))

    def action_cover_close(self) -> None:
        if self._effective_kind() is DeviceKind.COVER:
            self._run_rpc("Close", lambda c: cover_close(c, 0))

    def action_cover_stop(self) -> None:
        if self._effective_kind() is DeviceKind.COVER:
            self._run_rpc("Stop", lambda c: cover_stop(c, 0))

    def action_reboot(self) -> None:
        self._run_rpc("Reboot", reboot)

    def action_update_stable(self) -> None:
        if not (self._status and self._status.update_stable):
            self._set_error("No stable update available.")
            return

        async def _do(client: ShellyClient) -> None:
            await update_firmware(client, stage="stable")

        self._run_rpc(f"Update stable {self._status.update_stable}", _do)

    def action_update_beta(self) -> None:
        if not (self._status and self._status.update_beta):
            self._set_error("No beta update available.")
            return

        async def _do(client: ShellyClient) -> None:
            await update_firmware(client, stage="beta")

        self._run_rpc(f"Update beta {self._status.update_beta}", _do)

    # --- helpers ---------------------------------------------------------

    def _run_rpc(
        self,
        label: str,
        fn: Callable[[ShellyClient], Awaitable[object]],
    ) -> None:
        self._remove_armed = False  # any other action cancels the pending remove

        async def runner() -> None:
            try:
                async with connect(self._device, self._settings) as client:
                    await fn(client)
            except ShellyError as err:
                _log.error(
                    "detail action failed",
                    action=label,
                    device_id=self._device.id,
                    host=self._device.host,
                    code=err.code,
                    error=err.message,
                )
                self._set_error(f"{label} failed: {err.message}")
                self.app.notify(f"{label} failed: {err.message}", severity="error")
                return
            self._set_error("")
            self.app.notify(f"{label} OK")
            await self._refresh_status()

        self.run_worker(runner(), exclusive=False, group="detail-rpc")

    def _refresh_status_async(self) -> None:
        self.run_worker(self._refresh_status(), exclusive=True, group="detail-refresh")

    async def _refresh_status(self) -> None:
        prior_kind = self._effective_kind()
        async with connect(self._device, self._settings) as client:
            self._status = await fetch_status(client)
        new_kind = self._effective_kind()
        if new_kind != prior_kind:
            # mDNS-derived kind was wrong; rebuild the tabs with correct buttons
            # and remember the live kind for future sessions in memory.
            self._device = self._device.model_copy(update={"kind": new_kind})
            await self.recompose()
        self._render_state()
        # Footer re-runs `check_action`; needed so `Update` toggles between
        # enabled/greyed as status.update_stable comes and goes.
        self.refresh_bindings()

    def _render_state(self) -> None:
        for actions in self.query(ActionsTab).results():
            actions.render_status(self._status)
        for fw in self.query(FirmwareTab).results():
            fw.render_status(self._device, self._status)

    def _set_error(self, msg: str) -> None:
        self.query_one("#detail-error", Label).update(msg)
