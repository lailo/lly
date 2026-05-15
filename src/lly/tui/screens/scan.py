"""Modal that streams mDNS scan results into a SelectionList for multi-pick import."""

from __future__ import annotations

from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Vertical
from textual.widgets import Footer, Label, SelectionList, Static
from textual.widgets.selection_list import Selection

from lly.discovery import scan
from lly.fleet import fetch_remote_name
from lly.models import Device, Settings
from lly.tui.widgets.modal import LlyModalScreen


def _prompt_for(dev: Device) -> str:
    """One-line label shown next to each selection checkbox."""
    return (
        f"{dev.name}  •  {dev.model}  •  {dev.host}"
        f"  •  gen {dev.gen}  •  fw {dev.fw_version or '-'}"
    )


class ScanScreen(LlyModalScreen[list[Device] | None]):
    DEFAULT_CSS = """
    ScanScreen > .modal-card { width: 90%; height: 80%; max-width: 100%; }
    ScanScreen #scan-list { height: 1fr; }
    ScanScreen #scan-status { padding-top: 1; }
    ScanScreen #scan-placeholder {
        height: 1fr;
        content-align: center middle;
        color: $text-muted;
        text-style: italic;
    }
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        # SelectionList ships with `space` → toggle and arrow-key navigation,
        # so we only need import/cancel and a select-all helper.
        Binding("a", "select_all", "All/None", priority=True),
        Binding("enter", "import_selected", "Import", priority=True),
        Binding("escape", "cancel", "Cancel", priority=True),
    ]

    def __init__(
        self,
        timeout: float = 5.0,
        *,
        settings: Settings | None = None,
        known_ids: set[str] | None = None,
        known_hosts: set[str] | None = None,
    ) -> None:
        super().__init__()
        self._timeout = timeout
        self._settings = settings or Settings()
        self._known_ids: set[str] = known_ids or set()
        self._known_hosts: set[str] = known_hosts or set()
        self._found: dict[str, Device] = {}
        self._found_hosts: set[str] = set()
        self._scan_done = False
        self._skipped = 0

    # --- compose ---------------------------------------------------------

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal-card"):
            yield Label("Scan", classes="modal-title")
            yield Static("⏳ Scanning the network for Shelly devices…", id="scan-placeholder")
            yield SelectionList[str](id="scan-list")
            yield Static("", id="scan-status")
        yield Footer()

    def on_mount(self) -> None:
        # Start with placeholder shown, list hidden.
        self.query_one("#scan-list", SelectionList).display = False
        self._refresh_status()
        self.run_worker(self._scan(), exclusive=True)

    # --- mDNS worker ----------------------------------------------------

    async def _scan(self) -> None:
        async for device in scan(timeout=self._timeout):
            if device.id in self._known_ids or device.host in self._known_hosts:
                self._skipped += 1
                continue
            existing = self._found.get(device.id)
            if existing is not None:
                # Friendly-name upgrade emitted by discovery.scan().
                if device.name != existing.name:
                    self._found[device.id] = device
                    self._update_prompt(device)
                continue
            if device.host in self._found_hosts:
                continue
            self._found[device.id] = device
            self._found_hosts.add(device.host)
            self._add_option(device)
            self._refresh_status()
            self._update_visibility()
            # mDNS service-name isn't reliable for the user-friendly name —
            # ask the device itself, in the background.
            self.run_worker(
                self._fetch_friendly_name(device),
                exclusive=False,
                group=f"name:{device.id}",
            )
        # mDNS browser exhausted → scan window closed.
        self._scan_done = True
        self._refresh_status()
        self._update_visibility()

    async def _fetch_friendly_name(self, device: Device) -> None:
        remote = await fetch_remote_name(device, self._settings)
        if remote is None:
            return
        existing = self._found.get(device.id)
        if existing is None or existing.name == remote:
            return
        updated = existing.model_copy(update={"name": remote})
        self._found[device.id] = updated
        self._update_prompt(updated)

    # --- list manipulation ----------------------------------------------

    def _add_option(self, dev: Device) -> None:
        sl = self.query_one("#scan-list", SelectionList)
        sl.add_option(Selection(_prompt_for(dev), value=dev.id, id=dev.id))

    def _update_prompt(self, dev: Device) -> None:
        sl = self.query_one("#scan-list", SelectionList)
        sl.replace_option_prompt(dev.id, _prompt_for(dev))

    def _update_visibility(self) -> None:
        """Swap between the 'Scanning…' placeholder and the SelectionList."""
        has_rows = bool(self._found)
        self.query_one("#scan-list", SelectionList).display = has_rows
        placeholder = self.query_one("#scan-placeholder", Static)
        placeholder.display = not has_rows
        if not has_rows:
            placeholder.update(
                "✓ Scan complete — no new devices found."
                if self._scan_done
                else "⏳ Scanning the network for Shelly devices…"
            )

    # --- status line ----------------------------------------------------

    def _selected_count(self) -> int:
        try:
            return len(self.query_one("#scan-list", SelectionList).selected)
        except Exception:  # widget not mounted yet
            return 0

    def _status_text(self) -> str:
        prefix = (
            f"Scan complete — {len(self._found)} new"
            if self._scan_done
            else f"Scanning ({self._timeout:.0f}s) — {len(self._found)} new"
        )
        skipped = f" • {self._skipped} already known (hidden)" if self._skipped else ""
        selected = self._selected_count()
        if selected:
            tail = f" • {selected} selected — press Enter to import"
        elif self._scan_done:
            tail = " • nothing selected — press space to pick, then Enter"
        else:
            tail = ""
        return prefix + skipped + tail

    def _refresh_status(self) -> None:
        self.query_one("#scan-status", Static).update(self._status_text())

    def on_selection_list_selected_changed(
        self, _event: SelectionList.SelectedChanged[str]
    ) -> None:
        self._refresh_status()

    # --- actions --------------------------------------------------------

    def action_select_all(self) -> None:
        sl = self.query_one("#scan-list", SelectionList)
        if len(sl.selected) == sl.option_count and sl.option_count > 0:
            sl.deselect_all()
        else:
            sl.select_all()

    def action_import_selected(self) -> None:
        sl = self.query_one("#scan-list", SelectionList)
        chosen_ids: list[str] = list(sl.selected)
        if not chosen_ids:
            # Refuse to import unless the user has explicitly picked something —
            # no "Enter imports all" footgun.
            return
        chosen = [self._found[i] for i in chosen_ids if i in self._found]
        self.dismiss(chosen)

    def action_cancel(self) -> None:
        self.dismiss(None)
