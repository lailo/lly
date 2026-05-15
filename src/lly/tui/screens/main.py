"""Main screen: device list. Press Enter on a row to open per-device actions."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, ClassVar

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Vertical
from textual.screen import Screen
from textual.timer import Timer
from textual.widgets import DataTable, Footer, Header, Static
from textual.worker import Worker

from lly.config import merge_devices, save_devices
from lly.fleet import fetch_remote_name, refresh_statuses
from lly.models import Device, DeviceKind, DeviceStatus, Settings
from lly.tui.screens.detail import DetailResult, DeviceDetailScreen
from lly.tui.screens.scan import ScanScreen
from lly.tui.screens.settings import SettingsScreen

COLUMNS: tuple[str, ...] = ("name", "model", "host", "version", "update", "state")
# Columns whose sort value depends on the polled status — when those are
# active, a refresh tick has to re-apply the sort so the order reflects new
# values, not the order rows were added.
_STATUS_DEPENDENT_COLUMNS: frozenset[str] = frozenset({"update", "state"})


def _format_update_cell(status: DeviceStatus | None) -> str:
    if status is None or not status.has_update:
        return ""
    if status.update_stable and status.update_beta:
        return "↑ both"
    if status.update_stable:
        return "↑ stable"
    return "↑ beta"


def _ip_sort_key(value: str) -> tuple[int, ...]:
    """IPv4 → tuple-of-ints; anything else → empty tuple (sorts first)."""
    parts: list[int] = []
    for p in value.split("."):
        try:
            parts.append(int(p))
        except ValueError:
            return ()
    return tuple(parts)


def _version_sort_key(value: str) -> tuple[int, ...]:
    """Dotted-numeric version → tuple-of-ints; stops at first non-numeric segment."""
    parts: list[int] = []
    for p in value.split("."):
        try:
            parts.append(int(p))
        except ValueError:
            break
    return tuple(parts)


class MainScreen(Screen[None]):
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("s", "scan", "Scan"),
        Binding("enter", "open_detail", "Detail", priority=True),
        Binding("r", "refresh_now", "Refresh"),
        Binding("comma", "open_settings", "Settings"),
        Binding("q", "app.quit", "Quit"),
    ]

    def __init__(self, devices: list[Device], settings: Settings) -> None:
        super().__init__()
        self._devices: dict[str, Device] = {d.id: d for d in devices}
        self._statuses: dict[str, DeviceStatus] = {}
        self._settings = settings
        self._refresh_timer: Timer | None = None
        # Sort state: None = insertion order, otherwise column key + direction.
        # Click a column header to set; click again to flip ascending/descending.
        self._sort_by: str | None = None
        self._sort_desc: bool = False

    DEFAULT_CSS = """
    #devices-empty {
        height: 1fr;
        content-align: center middle;
        color: $text-muted;
        text-style: italic;
    }
    """

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical():
            yield Static(
                "No devices added yet.\n\nPress  s  to scan the network for Shelly devices.",
                id="devices-empty",
            )
            yield DataTable(id="devices", cursor_type="row", zebra_stripes=True)
            yield Static("", id="status-line")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#devices", DataTable)
        for col in COLUMNS:
            # The cover-state cell renders e.g. " 58% ██████░░░░ opening" — wide
            # enough that DataTable's auto-sizing clips it down to just "58%"
            # unless we reserve room up front.
            width = 24 if col == "state" else None
            table.add_column(col, key=col, width=width)
        self._reload_rows()
        self._restart_refresh_timer()
        self._kick_refresh()
        self._fetch_missing_names()
        # Empty fleet → user has nothing to do but scan; open the modal for them.
        if not self._devices:
            self.call_after_refresh(self.action_scan)

    def _fetch_missing_names(self) -> None:
        """Resolve user-friendly names for any device still labelled with its factory id."""
        for dev in list(self._devices.values()):
            if dev.name != dev.id:
                continue
            self.run_worker(self._fetch_friendly_name(dev), exclusive=False, group=f"name:{dev.id}")

    async def _fetch_friendly_name(self, dev: Device) -> None:
        remote = await fetch_remote_name(dev, self._settings)
        if remote is None or remote == dev.name:
            return
        current = self._devices.get(dev.id)
        if current is None:
            return
        self._devices[dev.id] = current.model_copy(update={"name": remote})
        save_devices(list(self._devices.values()))
        self._update_row(dev.id)

    def _restart_refresh_timer(self) -> None:
        if self._refresh_timer is not None:
            self._refresh_timer.stop()
        self._refresh_timer = self.set_interval(
            self._settings.refresh_interval_s, self._kick_refresh
        )

    def _reload_rows(self) -> None:
        table = self.query_one("#devices", DataTable)
        table.clear()
        for dev_id in self._sorted_device_ids():
            table.add_row(*self._row_for(self._devices[dev_id]), key=dev_id)
        self._update_visibility()
        self._update_status_line()

    def _sorted_device_ids(self) -> list[str]:
        """Device ids in current sort order; unsorted is insertion order."""
        if self._sort_by is None:
            return list(self._devices)
        return sorted(
            self._devices, key=self._sort_key_for(self._sort_by), reverse=self._sort_desc
        )

    def _sort_key_for(self, column: str) -> Callable[[str], Any]:
        """Build a key function that maps a device id to its sortable value."""

        def key(dev_id: str) -> Any:
            dev = self._devices[dev_id]
            status = self._statuses.get(dev_id)
            result: Any
            if column == "name":
                result = dev.name.lower()
            elif column == "model":
                result = dev.model.lower()
            elif column == "host":
                result = _ip_sort_key(dev.host)
            elif column == "version":
                result = _version_sort_key(dev.fw_version or "")
            elif column == "update":
                result = _format_update_cell(status)
            elif column == "state":
                result = status.render() if status else ""
            else:
                result = ""
            return result

        return key

    def _apply_sort(self) -> None:
        """Re-order the visible rows under the current sort, preserving cursor."""
        if self._sort_by is None:
            return
        table = self.query_one("#devices", DataTable)
        saved_key = self._cursor_row_key()
        table.clear()
        for dev_id in self._sorted_device_ids():
            table.add_row(*self._row_for(self._devices[dev_id]), key=dev_id)
        if saved_key is not None:
            self._move_cursor_to_key(saved_key)

    def sort_by(self, column: str) -> None:
        """Public entry point — sort by `column`, toggle direction on repeat clicks."""
        if column not in COLUMNS:
            return
        if self._sort_by == column:
            self._sort_desc = not self._sort_desc
        else:
            self._sort_by = column
            self._sort_desc = False
        self._apply_sort()
        self._update_status_line()

    def on_data_table_header_selected(self, event: DataTable.HeaderSelected) -> None:
        column_key = event.column_key.value
        if isinstance(column_key, str):
            self.sort_by(column_key)

    def _cursor_row_key(self) -> str | None:
        table = self.query_one("#devices", DataTable)
        if table.row_count == 0:
            return None
        try:
            row_key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key
        except (KeyError, IndexError):
            return None
        value = row_key.value
        return value if isinstance(value, str) else None

    def _move_cursor_to_key(self, target: str) -> None:
        table = self.query_one("#devices", DataTable)
        for idx, row_key in enumerate(table.rows):
            value = row_key.value if hasattr(row_key, "value") else row_key
            if value == target:
                table.move_cursor(row=idx)
                return

    def _update_visibility(self) -> None:
        has_devices = bool(self._devices)
        self.query_one("#devices", DataTable).display = has_devices
        self.query_one("#devices-empty", Static).display = not has_devices

    def _row_for(self, dev: Device) -> tuple[str, ...]:
        state = self._statuses.get(dev.id)
        state_str = state.render() if state else "..."
        upd_str = _format_update_cell(state)
        return (
            dev.name,
            dev.model,
            dev.host,
            dev.fw_version or "-",
            upd_str,
            state_str,
        )

    def _update_row(self, dev_id: str) -> None:
        dev = self._devices.get(dev_id)
        if dev is None:
            return
        table = self.query_one("#devices", DataTable)
        for col_idx, value in enumerate(self._row_for(dev)):
            table.update_cell(dev_id, COLUMNS[col_idx], value)

    def _update_status_line(self) -> None:
        line = self.query_one("#status-line", Static)
        sort_hint = ""
        if self._sort_by:
            arrow = "↓" if self._sort_desc else "↑"
            sort_hint = f" — sort {self._sort_by} {arrow}"
        line.update(
            f" {len(self._devices)} devices — Enter open · s scan · r refresh · , settings"
            f"{sort_hint}"
        )

    # --- actions ---------------------------------------------------------

    def action_refresh_now(self) -> None:
        self._kick_refresh()

    def action_open_settings(self) -> None:
        def _applied(new: Settings | None) -> None:
            if new is None:
                return
            self._settings = new
            # `configure_logging` is idempotent — re-runs with the new level if
            # the user toggled it in the modal.
            from lly.logging import configure as configure_logging

            configure_logging(new)
            self._restart_refresh_timer()
            self._kick_refresh()
            self.notify("Settings saved.")

        self.app.push_screen(SettingsScreen(self._settings), _applied)

    def action_scan(self) -> None:
        def _import(new_devices: list[Device] | None) -> None:
            if not new_devices:
                return
            # Belt-and-braces: filter out ids we already track, then merge —
            # `merge_devices` is idempotent on id, but skipping early avoids
            # noisy "imported N" toasts when N is really 0.
            fresh = [d for d in new_devices if d.id not in self._devices]
            if not fresh:
                self.notify("All scanned devices were already in the list.")
                return
            merged = merge_devices(list(self._devices.values()), fresh)
            self._devices = {d.id: d for d in merged}
            save_devices(merged)
            self._reload_rows()
            self._kick_refresh()
            self.notify(f"Imported {len(fresh)} new device(s).")

        self.app.push_screen(
            ScanScreen(
                timeout=self._settings.scan_timeout_s,
                settings=self._settings,
                known_ids=set(self._devices),
                known_hosts={d.host for d in self._devices.values()},
            ),
            _import,
        )

    def action_open_detail(self) -> None:
        dev = self.cursor_device()
        if dev is None:
            return

        def _closed(result: DetailResult | None) -> None:
            if result is None:
                return
            if result.removed:
                self._devices.pop(dev.id, None)
                self._statuses.pop(dev.id, None)
                save_devices(list(self._devices.values()))
                self._reload_rows()
                self.notify(f"Removed {dev.name}")
                return
            if result.renamed_to is not None:
                renamed = result.renamed_to
                self._devices[renamed.id] = renamed
                save_devices(list(self._devices.values()))
                self._update_row(renamed.id)
                self.notify(f"Renamed to {renamed.name}")
                return
            # A device action may have changed state — refresh now instead of
            # waiting for the next tick.
            self._kick_refresh()

        self.app.push_screen(DeviceDetailScreen(dev, self._settings), _closed)

    def cursor_device(self) -> Device | None:
        """The device under the row cursor, or None on an empty table.

        Public because the command-palette provider (`LlyCommandProvider`)
        needs to read the highlighted row to surface a "Open detail: X" entry.
        """
        table = self.query_one("#devices", DataTable)
        if table.row_count == 0:
            return None
        row_key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key
        if row_key.value is None:
            return None
        return self._devices.get(str(row_key.value))

    # --- refresh worker --------------------------------------------------

    def _kick_refresh(self) -> None:
        if not self._devices:
            return
        self.run_worker(self._refresh(), exclusive=True, group="refresh")

    async def _refresh(self) -> None:
        statuses = await refresh_statuses(list(self._devices.values()), self._settings)
        self._statuses = statuses
        if self._correct_stored_kinds(statuses):
            save_devices(list(self._devices.values()))
        for dev_id in self._devices:
            self._update_row(dev_id)
        # If the active sort key reads from the just-refreshed status, the row
        # order may now be wrong — re-sort. Skip otherwise to avoid clobbering
        # the cursor on every tick.
        if self._sort_by in _STATUS_DEPENDENT_COLUMNS:
            self._apply_sort()

    def _correct_stored_kinds(self, statuses: dict[str, DeviceStatus]) -> bool:
        """If the live status disagrees with our stored kind, fix it. Returns True if changed."""
        changed = False
        for dev_id, status in statuses.items():
            if not status.online or status.kind is DeviceKind.OTHER:
                continue
            dev = self._devices.get(dev_id)
            if dev is None or dev.kind is status.kind:
                continue
            self._devices[dev_id] = dev.model_copy(update={"kind": status.kind})
            changed = True
        return changed

    def on_worker_state_changed(self, _event: Worker.StateChanged) -> None:
        return None
