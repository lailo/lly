"""TUI tests driven by Textual's Pilot harness.

We monkey-patch the mDNS `scan` async-generator and the fleet helpers so the
TUI runs entirely offline.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from textual.widgets import DataTable

from lly.models import Device, DeviceKind, DeviceStatus, Settings
from lly.tui.app import LlyApp
from lly.tui.screens.scan import ScanScreen


def _dev(suffix: str, *, kind: DeviceKind = DeviceKind.SWITCH) -> Device:
    return Device(
        id=f"shellyplus1pm-{suffix}",
        name=f"shellyplus1pm-{suffix}",
        host=f"10.0.0.{int(suffix, 16) % 250 + 1}",
        model="Plus1PM",
        gen=2,
        kind=kind,
        fw_version="1.4.4",
    )


@pytest.fixture
def fake_devices() -> list[Device]:
    return [_dev("aaa"), _dev("bbb"), _dev("ccc")]


@pytest.fixture(autouse=True)
def _stub_fleet(monkeypatch: pytest.MonkeyPatch, fake_devices: list[Device]) -> None:
    """Replace network-touching fleet helpers with offline stubs.

    Also default `load_devices` to a non-empty list so MainScreen doesn't
    auto-open the scan modal in tests that don't explicitly want that.
    Tests exercising the empty-fleet path override this.
    """

    async def fake_refresh(devices: list[Device], _settings: Settings) -> dict[str, DeviceStatus]:
        return {d.id: DeviceStatus(online=True, kind=d.kind, on=True) for d in devices}

    def _load_devices() -> list[Device]:
        return list(fake_devices)

    def _load_settings() -> Settings:
        return Settings()

    monkeypatch.setattr("lly.tui.screens.main.refresh_statuses", fake_refresh)
    monkeypatch.setattr("lly.tui.app.load_devices", _load_devices)
    monkeypatch.setattr("lly.tui.app.load_settings", _load_settings)


@pytest.fixture
def _stub_scan(monkeypatch: pytest.MonkeyPatch, fake_devices: list[Device]) -> None:
    async def fake_scan(timeout: float = 5.0) -> AsyncIterator[Device]:
        _ = timeout
        for d in fake_devices:
            yield d

    monkeypatch.setattr("lly.tui.screens.scan.scan", fake_scan)


# --- ScanScreen --------------------------------------------------------------


async def test_scan_screen_shows_placeholder_until_devices_appear(
    monkeypatch: pytest.MonkeyPatch, fake_devices: list[Device]
) -> None:
    """Before the first device arrives, show the 'Scanning…' placeholder, not an empty table."""
    import asyncio

    started = asyncio.Event()
    release = asyncio.Event()

    async def slow_scan(timeout: float = 5.0) -> AsyncIterator[Device]:
        _ = timeout
        started.set()
        await release.wait()
        for d in fake_devices:
            yield d

    monkeypatch.setattr("lly.tui.screens.scan.scan", slow_scan)
    from textual.widgets import Static

    app = LlyApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        app.push_screen(ScanScreen(timeout=0.5))
        await pilot.pause()
        # Wait until the worker actually started scanning.
        await started.wait()
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ScanScreen)
        from textual.widgets import SelectionList

        assert bool(screen.query_one("#scan-placeholder", Static).display) is True
        assert bool(screen.query_one("#scan-list", SelectionList).display) is False
        assert "Scanning" in str(screen.query_one("#scan-placeholder", Static).render())

        # Let devices arrive — placeholder should go away, list shows.
        release.set()
        await pilot.pause(0.2)
        assert bool(screen.query_one("#scan-placeholder", Static).display) is False
        assert bool(screen.query_one("#scan-list", SelectionList).display) is True


async def test_scan_screen_placeholder_says_no_results_when_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def empty_scan(timeout: float = 5.0) -> AsyncIterator[Device]:
        _ = timeout
        empty: tuple[Device, ...] = ()
        for d in empty:
            yield d

    monkeypatch.setattr("lly.tui.screens.scan.scan", empty_scan)
    from textual.widgets import Static

    app = LlyApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        app.push_screen(ScanScreen(timeout=0.05))
        await pilot.pause(0.2)
        screen = app.screen
        assert isinstance(screen, ScanScreen)
        # Workers in run_test() can be racy; force the terminal state so we
        # exercise the rendering path we actually care about.
        screen._scan_done = True
        screen._update_visibility()
        placeholder = screen.query_one("#scan-placeholder", Static)
        assert bool(placeholder.display) is True
        assert "no new devices" in str(placeholder.render())


async def test_scan_screen_fetches_friendly_name_from_device(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Newly-discovered devices get their `name` overwritten with the value
    Shelly reports from `Shelly.GetDeviceInfo`."""
    factory = _dev("ff1")
    assert factory.name == factory.id

    async def fake_scan_one(timeout: float = 5.0) -> AsyncIterator[Device]:
        _ = timeout
        yield factory

    async def fake_get_info(_client: object) -> dict[str, object]:
        return {"id": factory.id, "name": "Blinders Office"}

    monkeypatch.setattr("lly.tui.screens.scan.scan", fake_scan_one)
    monkeypatch.setattr("lly.fleet.get_device_info", fake_get_info)

    app = LlyApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        app.push_screen(ScanScreen(timeout=0.05))
        await pilot.pause(0.3)
        screen = app.screen
        assert isinstance(screen, ScanScreen)
        assert screen._found[factory.id].name == "Blinders Office"
        from textual.widgets import SelectionList

        sl = screen.query_one("#scan-list", SelectionList)
        prompt = str(sl.get_option(factory.id).prompt)
        assert "Blinders Office" in prompt


async def test_main_screen_resolves_friendly_name_for_factory_named_devices(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """On mount, any saved device with name==id gets its name looked up over HTTP."""
    factory = _dev("ff2")
    saved: list[list[Device]] = []
    monkeypatch.setattr("lly.tui.screens.main.save_devices", saved.append)

    async def fake_get_info(_client: object) -> dict[str, object]:
        return {"id": factory.id, "name": "Kitchen Light"}

    monkeypatch.setattr("lly.fleet.get_device_info", fake_get_info)

    def _load_devices() -> list[Device]:
        return [factory]

    def _load_settings() -> Settings:
        return Settings()

    monkeypatch.setattr("lly.tui.app.load_devices", _load_devices)
    monkeypatch.setattr("lly.tui.app.load_settings", _load_settings)

    app = LlyApp()
    async with app.run_test() as pilot:
        await pilot.pause(0.4)
        from lly.tui.screens.main import MainScreen

        screen = app.screen
        assert isinstance(screen, MainScreen)
        assert screen._devices[factory.id].name == "Kitchen Light"

    assert saved, "save_devices should be called once the name is resolved"
    assert saved[-1][0].name == "Kitchen Light"


@pytest.mark.usefixtures("_stub_scan")
async def test_scan_screen_filters_already_known(fake_devices: list[Device]) -> None:
    """Devices whose id is in `known_ids` are skipped, and the count is surfaced."""
    known = {fake_devices[0].id, fake_devices[2].id}
    app = LlyApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        app.push_screen(ScanScreen(timeout=0.05, known_ids=known))
        await pilot.pause(0.2)
        screen = app.screen
        assert isinstance(screen, ScanScreen)
        from textual.widgets import SelectionList

        sl = screen.query_one("#scan-list", SelectionList)
        # Only the one un-known device should show up.
        assert sl.option_count == 1
        assert fake_devices[1].id in screen._found
        assert fake_devices[0].id not in screen._found
        assert fake_devices[2].id not in screen._found
        assert screen._skipped == 2
        assert "2 already known (hidden)" in screen._status_text()


@pytest.mark.usefixtures("_stub_scan")
async def test_scan_screen_select_all_toggles(fake_devices: list[Device]) -> None:
    app = LlyApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        app.push_screen(ScanScreen(timeout=0.05))
        await pilot.pause(0.2)
        screen = app.screen
        assert isinstance(screen, ScanScreen)
        from textual.widgets import SelectionList

        sl = screen.query_one("#scan-list", SelectionList)
        assert sl.option_count == len(fake_devices)

        await pilot.press("a")  # select all
        assert len(sl.selected) == len(fake_devices)

        await pilot.press("a")  # deselect all
        assert sl.selected == []


@pytest.mark.usefixtures("_stub_scan")
async def test_scan_screen_toggle_picks_one(fake_devices: list[Device]) -> None:
    """Toggling a single option via the SelectionList API picks exactly one."""
    app = LlyApp()
    async with app.run_test() as pilot:
        app.push_screen(ScanScreen(timeout=0.05))
        await pilot.pause(0.2)
        screen = app.screen
        assert isinstance(screen, ScanScreen)
        from textual.widgets import SelectionList

        sl = screen.query_one("#scan-list", SelectionList)
        sl.select(fake_devices[0].id)
        await pilot.pause()
        assert sl.selected == [fake_devices[0].id]


@pytest.mark.usefixtures("_stub_scan")
async def test_scan_screen_enter_imports_selected(fake_devices: list[Device]) -> None:
    """Regression: `enter` must dismiss the scan modal with the picked devices.

    DataTable used to swallow the keypress; we now mark the binding priority.
    """
    app = LlyApp()
    captured: list[list[Device] | None] = []
    async with app.run_test() as pilot:
        await pilot.pause()
        app.push_screen(ScanScreen(timeout=0.05), captured.append)
        await pilot.pause(0.2)
        await pilot.press("a")  # select all
        await pilot.press("enter")  # import
        await pilot.pause()

    assert len(captured) == 1
    imported = captured[0]
    assert imported is not None
    assert {d.id for d in imported} == {d.id for d in fake_devices}


@pytest.mark.usefixtures("_stub_scan")
async def test_command_palette_lists_main_actions_and_detail_when_row_focused(
    monkeypatch: pytest.MonkeyPatch, fake_devices: list[Device]
) -> None:
    from textual.command import CommandPalette

    def _load() -> list[Device]:
        return list(fake_devices)

    def _settings() -> Settings:
        return Settings()

    monkeypatch.setattr("lly.tui.app.load_devices", _load)
    monkeypatch.setattr("lly.tui.app.load_settings", _settings)

    app = LlyApp()
    async with app.run_test() as pilot:
        await pilot.pause(0.1)
        # Inspect the provider against the live MainScreen — opening the palette
        # is just smoke-tested below.
        from lly.tui.commands import LlyCommandProvider
        from lly.tui.screens.main import MainScreen

        main = app.screen
        assert isinstance(main, MainScreen)
        provider = LlyCommandProvider(main, None)
        # Use the private factory directly — exercises the same listing as the palette.
        names = [n for (n, _h, _c) in provider._commands()]
        assert any(n.startswith("Open detail:") for n in names)
        assert "Scan for devices" in names
        assert "Settings" in names
        assert "Refresh status" in names
        assert "Quit lly" in names

        # And confirm Ctrl+P actually opens the palette screen at runtime.
        await pilot.press("ctrl+p")
        await pilot.pause(0.2)
        assert isinstance(app.screen, CommandPalette)


async def test_scan_screen_enter_with_no_selection_is_noop(fake_devices: list[Device]) -> None:
    """Regression: pressing Enter with nothing selected used to import all devices."""
    app = LlyApp()
    captured: list[list[Device] | None] = []
    async with app.run_test() as pilot:
        await pilot.pause()
        app.push_screen(ScanScreen(timeout=0.05), captured.append)
        await pilot.pause(0.2)
        # No selection toggled — Enter must do nothing.
        await pilot.press("enter")
        await pilot.pause()
        assert captured == []
        assert isinstance(app.screen, ScanScreen)


@pytest.mark.usefixtures("_stub_scan")
async def test_scan_screen_status_shows_selection_hint(fake_devices: list[Device]) -> None:
    """The status line must surface the selection count + 'Enter to import' hint."""
    app = LlyApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        app.push_screen(ScanScreen(timeout=0.05))
        await pilot.pause(0.2)
        screen = app.screen
        assert isinstance(screen, ScanScreen)
        await pilot.press("a")
        status_text = screen._status_text()
        assert f"{len(fake_devices)} selected" in status_text
        assert "Enter to import" in status_text


@pytest.mark.usefixtures("_stub_scan")
async def test_scan_screen_escape_dismisses() -> None:
    app = LlyApp()
    async with app.run_test() as pilot:
        app.push_screen(ScanScreen(timeout=0.05))
        await pilot.pause(0.2)
        assert isinstance(app.screen, ScanScreen)
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, ScanScreen)


# --- MainScreen --------------------------------------------------------------


async def test_main_screen_empty_state_shows_placeholder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Empty fleet hides the table and shows the 'press s to scan' hint."""

    def _empty() -> list[Device]:
        return []

    def _settings() -> Settings:
        return Settings()

    monkeypatch.setattr("lly.tui.app.load_devices", _empty)
    monkeypatch.setattr("lly.tui.app.load_settings", _settings)

    # Avoid the auto-open scan modal so we can inspect the main screen itself.
    async def empty_scan(timeout: float = 5.0) -> AsyncIterator[Device]:
        _ = timeout
        empty: tuple[Device, ...] = ()
        for d in empty:
            yield d

    monkeypatch.setattr("lly.tui.screens.scan.scan", empty_scan)

    from textual.widgets import Static

    from lly.tui.screens.main import MainScreen

    app = LlyApp()
    async with app.run_test() as pilot:
        await pilot.pause(0.1)
        # The auto-opened scan modal pushes on top; pop it to inspect main.
        if not isinstance(app.screen, MainScreen):
            await pilot.press("escape")
            await pilot.pause()
        main = app.screen
        assert isinstance(main, MainScreen)
        empty_label = main.query_one("#devices-empty", Static)
        table = main.query_one("#devices", DataTable)
        assert bool(empty_label.display) is True
        assert bool(table.display) is False
        rendered = str(empty_label.render())
        assert "No devices" in rendered
        assert "s" in rendered


async def test_main_screen_opens_scan_when_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """First-run UX: with no saved devices, the scan modal opens automatically."""

    def _load_devices() -> list[Device]:
        return []

    def _load_settings() -> Settings:
        return Settings()

    monkeypatch.setattr("lly.tui.app.load_devices", _load_devices)
    monkeypatch.setattr("lly.tui.app.load_settings", _load_settings)

    # Stub the scan to yield nothing so the modal stays open during the test.
    async def empty_scan(timeout: float = 5.0) -> AsyncIterator[Device]:
        _ = timeout
        empty: tuple[Device, ...] = ()
        for d in empty:
            yield d

    monkeypatch.setattr("lly.tui.screens.scan.scan", empty_scan)

    app = LlyApp()
    async with app.run_test() as pilot:
        await pilot.pause(0.2)
        assert isinstance(app.screen, ScanScreen)


async def test_main_screen_does_not_auto_open_scan_when_devices_exist(
    monkeypatch: pytest.MonkeyPatch, fake_devices: list[Device]
) -> None:
    def _load_devices() -> list[Device]:
        return list(fake_devices)

    def _load_settings() -> Settings:
        return Settings()

    monkeypatch.setattr("lly.tui.app.load_devices", _load_devices)
    monkeypatch.setattr("lly.tui.app.load_settings", _load_settings)

    app = LlyApp()
    async with app.run_test() as pilot:
        await pilot.pause(0.2)
        assert not isinstance(app.screen, ScanScreen)


async def test_main_screen_upd_column_reflects_available_updates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The 'upd' cell shows '↑ stable' / '↑ beta' / '↑ both' / '' per device."""
    a, b, c, d = (_dev(s) for s in ("a01", "a02", "a03", "a04"))

    async def fake_refresh(devices: list[Device], _settings: Settings) -> dict[str, DeviceStatus]:
        return {
            a.id: DeviceStatus(online=True, kind=DeviceKind.SWITCH, on=False),
            b.id: DeviceStatus(
                online=True, kind=DeviceKind.SWITCH, on=False, update_stable="1.5.0"
            ),
            c.id: DeviceStatus(
                online=True, kind=DeviceKind.SWITCH, on=False, update_beta="1.6.0-beta"
            ),
            d.id: DeviceStatus(
                online=True,
                kind=DeviceKind.SWITCH,
                on=False,
                update_stable="1.5.0",
                update_beta="1.6.0-beta",
            ),
        }

    monkeypatch.setattr("lly.tui.screens.main.refresh_statuses", fake_refresh)

    def _load_devices() -> list[Device]:
        return [a, b, c, d]

    def _load_settings() -> Settings:
        return Settings()

    monkeypatch.setattr("lly.tui.app.load_devices", _load_devices)
    monkeypatch.setattr("lly.tui.app.load_settings", _load_settings)

    app = LlyApp()
    async with app.run_test() as pilot:
        await pilot.pause(0.3)
        from lly.tui.screens.main import MainScreen

        screen = app.screen
        assert isinstance(screen, MainScreen)
        table = screen.query_one("#devices", DataTable)
        assert str(table.get_cell(a.id, "update")) == ""
        assert str(table.get_cell(b.id, "update")) == "↑ stable"
        assert str(table.get_cell(c.id, "update")) == "↑ beta"
        assert str(table.get_cell(d.id, "update")) == "↑ both"


async def test_main_screen_sort_by_column_toggles_direction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """sort_by(col) orders rows; calling it twice with the same col flips direction."""
    # Names chosen so alphabetical order is non-trivial.
    devs = [
        Device(
            id=f"shellyplus1pm-{tag}",
            name=name,
            host=f"10.0.0.{n}",
            model="Plus1PM",
            gen=2,
            kind=DeviceKind.SWITCH,
            fw_version="1.4.4",
        )
        for tag, name, n in [("aaa", "Charlie", 30), ("bbb", "Alice", 10), ("ccc", "Bob", 20)]
    ]
    def _load_devices() -> list[Device]:
        return list(devs)

    def _load_settings() -> Settings:
        return Settings()

    monkeypatch.setattr("lly.tui.app.load_devices", _load_devices)
    monkeypatch.setattr("lly.tui.app.load_settings", _load_settings)

    from textual.coordinate import Coordinate

    app = LlyApp()
    async with app.run_test() as pilot:
        await pilot.pause(0.1)
        from lly.tui.screens.main import MainScreen

        screen = app.screen
        assert isinstance(screen, MainScreen)
        table = screen.query_one("#devices", DataTable)

        def _col(idx: int) -> list[str]:
            return [str(table.get_cell_at(Coordinate(row, idx))) for row in range(table.row_count)]

        # Sort ascending by name.
        screen.sort_by("name")
        await pilot.pause()
        assert _col(0) == ["Alice", "Bob", "Charlie"]

        # Same column again → descending.
        screen.sort_by("name")
        await pilot.pause()
        assert _col(0) == ["Charlie", "Bob", "Alice"]

        # Different column resets to ascending; host uses IP-numeric ordering.
        screen.sort_by("host")
        await pilot.pause()
        assert _col(2) == ["10.0.0.10", "10.0.0.20", "10.0.0.30"]


async def test_main_screen_enter_opens_detail(
    monkeypatch: pytest.MonkeyPatch, fake_devices: list[Device]
) -> None:
    def _settings() -> Settings:
        return Settings()

    monkeypatch.setattr("lly.tui.app.load_devices", lambda: fake_devices)
    monkeypatch.setattr("lly.tui.app.load_settings", _settings)

    app = LlyApp()
    async with app.run_test() as pilot:
        await pilot.pause(0.1)
        from lly.tui.screens.detail import DeviceDetailScreen
        from lly.tui.screens.main import MainScreen

        screen = app.screen
        assert isinstance(screen, MainScreen)
        table = screen.query_one("#devices", DataTable)
        assert table.row_count == len(fake_devices)

        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, DeviceDetailScreen)
        # Cursor starts on first row → that's the device we opened.
        assert app.screen._device.id == fake_devices[0].id


# --- SettingsScreen ----------------------------------------------------------


async def test_settings_screen_save_persists(
    monkeypatch: pytest.MonkeyPatch, tmp_path: object
) -> None:
    """Save updates the on-disk config and dismisses with the new Settings."""
    saved: list[Settings] = []
    monkeypatch.setattr("lly.tui.screens.settings.screen.save_settings", saved.append)
    from lly.tui.screens.settings import SettingsScreen

    app = LlyApp()
    captured: list[Settings | None] = []
    async with app.run_test() as pilot:
        await pilot.pause()
        app.push_screen(SettingsScreen(Settings()), captured.append)
        await pilot.pause()

        from textual.widgets import Input

        screen = app.screen
        assert isinstance(screen, SettingsScreen)
        screen.query_one("#refresh_interval_s", Input).value = "2.0"
        screen.query_one("#refresh_concurrency", Input).value = "16"
        screen.action_save()
        await pilot.pause()

    assert len(captured) == 1
    new = captured[0]
    assert new is not None
    assert new.refresh_interval_s == 2.0
    assert new.refresh_concurrency == 16
    assert len(saved) == 1


async def test_settings_screen_invalid_input_shows_error() -> None:
    from textual.widgets import Input

    from lly.tui.screens.settings import SettingsScreen

    app = LlyApp()
    captured: list[Settings | None] = []
    async with app.run_test() as pilot:
        await pilot.pause()
        app.push_screen(SettingsScreen(Settings()), captured.append)
        await pilot.pause()

        screen = app.screen
        assert isinstance(screen, SettingsScreen)
        screen.query_one("#refresh_interval_s", Input).value = "not-a-number"
        screen.action_save()
        await pilot.pause()

        assert screen.last_error is not None
        assert "Invalid" in screen.last_error
        # Screen still open, no callback invoked.
        assert captured == []


# --- DeviceDetailScreen ------------------------------------------------------


def _patch_detail_rpcs(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[object]]:
    """Stub out everything in detail.py that touches the network.

    Returns a dict you can inspect to see which RPCs got called.
    """
    calls: dict[str, list[object]] = {
        "switch_set": [],
        "reboot": [],
        "update_firmware": [],
        "cover_open": [],
        "cover_close": [],
        "cover_stop": [],
        "fetch_status": [],
    }

    async def fake_fetch_status(_client: object) -> DeviceStatus:
        # Default to OTHER so `_effective_kind` falls back to the stored
        # device.kind — the test fixture's choice — and no recompose fires.
        calls["fetch_status"].append(_client)
        return DeviceStatus(online=True, kind=DeviceKind.OTHER)

    async def fake_switch_set(_client: object, switch_id: int, *, on: bool) -> None:
        calls["switch_set"].append((switch_id, on))

    async def fake_reboot(_client: object) -> None:
        calls["reboot"].append(True)

    async def fake_update(_client: object, *, stage: str = "stable") -> dict[str, object]:
        calls["update_firmware"].append(stage)
        return {}

    async def fake_open(_client: object, _id: int = 0) -> None:
        calls["cover_open"].append(_id)

    async def fake_close(_client: object, _id: int = 0) -> None:
        calls["cover_close"].append(_id)

    async def fake_stop(_client: object, _id: int = 0) -> None:
        calls["cover_stop"].append(_id)

    monkeypatch.setattr("lly.tui.screens.detail.screen.fetch_status", fake_fetch_status)
    monkeypatch.setattr("lly.tui.screens.detail.screen.switch_set", fake_switch_set)
    monkeypatch.setattr("lly.tui.screens.detail.screen.reboot", fake_reboot)
    monkeypatch.setattr("lly.tui.screens.detail.screen.update_firmware", fake_update)
    monkeypatch.setattr("lly.tui.screens.detail.screen.cover_open", fake_open)
    monkeypatch.setattr("lly.tui.screens.detail.screen.cover_close", fake_close)
    monkeypatch.setattr("lly.tui.screens.detail.screen.cover_stop", fake_stop)
    return calls


async def test_detail_switch_toggle_calls_rpc(
    monkeypatch: pytest.MonkeyPatch, fake_devices: list[Device]
) -> None:
    calls = _patch_detail_rpcs(monkeypatch)
    from lly.tui.screens.detail import DeviceDetailScreen

    app = LlyApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        app.push_screen(DeviceDetailScreen(fake_devices[0], Settings()))
        await pilot.pause(0.1)
        screen = app.screen
        assert isinstance(screen, DeviceDetailScreen)
        screen.action_toggle_switch()
        await pilot.pause(0.1)

    assert calls["switch_set"] == [(0, True)]


async def test_detail_reboot_action(
    monkeypatch: pytest.MonkeyPatch, fake_devices: list[Device]
) -> None:
    calls = _patch_detail_rpcs(monkeypatch)
    from lly.tui.screens.detail import DeviceDetailScreen

    app = LlyApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        app.push_screen(DeviceDetailScreen(fake_devices[0], Settings()))
        await pilot.pause(0.1)
        screen = app.screen
        assert isinstance(screen, DeviceDetailScreen)
        screen.action_reboot()
        await pilot.pause(0.1)

    assert calls["reboot"] == [True]


async def test_detail_update_buttons_track_availability(
    monkeypatch: pytest.MonkeyPatch, fake_devices: list[Device]
) -> None:
    """Update buttons are disabled until status reports an available version."""
    calls = _patch_detail_rpcs(monkeypatch)

    async def status_with_updates(_client: object) -> DeviceStatus:
        return DeviceStatus(
            online=True,
            kind=DeviceKind.OTHER,  # don't trigger recompose
            update_stable="1.5.0",
            update_beta="1.6.0-beta1",
        )

    monkeypatch.setattr("lly.tui.screens.detail.screen.fetch_status", status_with_updates)
    from textual.widgets import Button

    from lly.tui.screens.detail import DeviceDetailScreen

    app = LlyApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        app.push_screen(DeviceDetailScreen(fake_devices[0], Settings()))
        await pilot.pause(0.3)
        screen = app.screen
        assert isinstance(screen, DeviceDetailScreen)
        stable_btn = screen.query_one("#update-stable", Button)
        beta_btn = screen.query_one("#update-beta", Button)
        assert stable_btn.disabled is False
        assert beta_btn.disabled is False
        assert "1.5.0" in str(stable_btn.label)
        assert "1.6.0-beta1" in str(beta_btn.label)

        screen.action_update_stable()
        screen.action_update_beta()
        await pilot.pause(0.1)

    assert calls["update_firmware"] == ["stable", "beta"]


async def test_detail_update_buttons_disabled_when_up_to_date(
    monkeypatch: pytest.MonkeyPatch, fake_devices: list[Device]
) -> None:
    _patch_detail_rpcs(monkeypatch)
    from textual.widgets import Button

    from lly.tui.screens.detail import DeviceDetailScreen

    app = LlyApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        app.push_screen(DeviceDetailScreen(fake_devices[0], Settings()))
        await pilot.pause(0.3)
        screen = app.screen
        assert isinstance(screen, DeviceDetailScreen)
        assert screen.query_one("#update-stable", Button).disabled is True
        assert screen.query_one("#update-beta", Button).disabled is True


async def test_detail_remove_requires_double_press(
    monkeypatch: pytest.MonkeyPatch, fake_devices: list[Device]
) -> None:
    _patch_detail_rpcs(monkeypatch)
    from lly.tui.screens.detail import DetailResult, DeviceDetailScreen

    app = LlyApp()
    captured: list[DetailResult | None] = []
    async with app.run_test() as pilot:
        await pilot.pause()
        app.push_screen(DeviceDetailScreen(fake_devices[0], Settings()), captured.append)
        await pilot.pause(0.1)
        screen = app.screen
        assert isinstance(screen, DeviceDetailScreen)

        # First press arms; does not dismiss.
        screen.action_remove()
        await pilot.pause()
        assert captured == []

        # Second press fires the removal.
        screen.action_remove()
        await pilot.pause()

    assert captured == [DetailResult(removed=True)]


async def test_main_screen_removes_device_when_detail_returns_removed(
    monkeypatch: pytest.MonkeyPatch, fake_devices: list[Device]
) -> None:
    saved: list[list[Device]] = []
    monkeypatch.setattr("lly.tui.screens.main.save_devices", saved.append)

    def _load_devices() -> list[Device]:
        return list(fake_devices)

    def _load_settings() -> Settings:
        return Settings()

    monkeypatch.setattr("lly.tui.app.load_devices", _load_devices)
    monkeypatch.setattr("lly.tui.app.load_settings", _load_settings)

    from lly.tui.screens.detail import DetailResult, DeviceDetailScreen
    from lly.tui.screens.main import MainScreen

    app = LlyApp()
    async with app.run_test() as pilot:
        await pilot.pause(0.1)
        screen = app.screen
        assert isinstance(screen, MainScreen)
        victim_id = fake_devices[0].id
        # Push a detail screen and immediately dismiss with REMOVED.
        screen.action_open_detail()
        await pilot.pause()
        detail = app.screen
        assert isinstance(detail, DeviceDetailScreen)
        detail.dismiss(DetailResult(removed=True))
        await pilot.pause(0.1)

        assert victim_id not in screen._devices

    assert saved, "save_devices was not called after removal"
    assert all(d.id != victim_id for d in saved[-1])


async def test_detail_save_name_pushes_to_device_then_dismisses(
    monkeypatch: pytest.MonkeyPatch, fake_devices: list[Device]
) -> None:
    """A successful `Sys.SetConfig` RPC dismisses with the renamed device."""
    from textual.widgets import Input

    from lly.tui.screens.detail import DetailResult, DeviceDetailScreen

    seen: list[tuple[object, str]] = []

    async def fake_set_name(client: object, name: str) -> dict[str, object]:
        seen.append((client, name))
        return {"restart_required": False}

    monkeypatch.setattr("lly.tui.screens.detail.screen.set_device_name", fake_set_name)

    app = LlyApp()
    captured: list[DetailResult | None] = []
    async with app.run_test() as pilot:
        await pilot.pause()
        app.push_screen(DeviceDetailScreen(fake_devices[0], Settings()), captured.append)
        await pilot.pause(0.1)
        screen = app.screen
        assert isinstance(screen, DeviceDetailScreen)
        screen.query_one("#detail-name", Input).value = "Living Room"
        screen.action_save_name()
        await pilot.pause(0.2)

    assert seen, "set_device_name should be called"
    _, pushed_name = seen[-1]
    assert pushed_name == "Living Room"

    assert len(captured) == 1
    result = captured[0]
    assert result is not None
    assert result.renamed_to is not None
    assert result.renamed_to.id == fake_devices[0].id
    assert result.renamed_to.name == "Living Room"


async def test_detail_save_name_failure_keeps_modal_open(
    monkeypatch: pytest.MonkeyPatch, fake_devices: list[Device]
) -> None:
    """If the device rejects the rename, the modal stays open and surfaces the error."""
    from textual.widgets import Input

    from lly.shelly.client import ShellyError
    from lly.tui.screens.detail import DetailResult, DeviceDetailScreen

    async def boom(_client: object, _name: str) -> dict[str, object]:
        raise ShellyError(-103, "device busy")

    monkeypatch.setattr("lly.tui.screens.detail.screen.set_device_name", boom)

    app = LlyApp()
    captured: list[DetailResult | None] = []
    async with app.run_test() as pilot:
        await pilot.pause()
        app.push_screen(DeviceDetailScreen(fake_devices[0], Settings()), captured.append)
        await pilot.pause(0.1)
        screen = app.screen
        assert isinstance(screen, DeviceDetailScreen)
        screen.query_one("#detail-name", Input).value = "Living Room"
        screen.action_save_name()
        await pilot.pause(0.2)
        assert captured == [], "modal should not dismiss when the RPC fails"
        # The error label should mention the failure.
        from textual.widgets import Label

        err_text = str(screen.query_one("#detail-error", Label).render())
        assert "Rename failed" in err_text


async def test_main_screen_persists_rename_from_detail(
    monkeypatch: pytest.MonkeyPatch, fake_devices: list[Device]
) -> None:
    """When the detail modal returns a renamed device, MainScreen saves it."""
    saved: list[list[Device]] = []
    monkeypatch.setattr("lly.tui.screens.main.save_devices", saved.append)

    def _load_devices() -> list[Device]:
        return list(fake_devices)

    def _load_settings() -> Settings:
        return Settings()

    monkeypatch.setattr("lly.tui.app.load_devices", _load_devices)
    monkeypatch.setattr("lly.tui.app.load_settings", _load_settings)

    from lly.tui.screens.detail import DetailResult, DeviceDetailScreen
    from lly.tui.screens.main import MainScreen

    app = LlyApp()
    async with app.run_test() as pilot:
        await pilot.pause(0.1)
        screen = app.screen
        assert isinstance(screen, MainScreen)
        target = fake_devices[0]
        screen.action_open_detail()
        await pilot.pause()
        detail = app.screen
        assert isinstance(detail, DeviceDetailScreen)
        renamed = target.model_copy(update={"name": "Hallway"})
        detail.dismiss(DetailResult(renamed_to=renamed))
        await pilot.pause(0.1)

        assert screen._devices[target.id].name == "Hallway"

    assert saved, "save_devices should be called after rename"
    by_id = {d.id: d for d in saved[-1]}
    assert by_id[target.id].name == "Hallway"


async def test_detail_cover_actions(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _patch_detail_rpcs(monkeypatch)
    from lly.tui.screens.detail import DeviceDetailScreen

    cover = _dev("ddd", kind=DeviceKind.COVER)
    app = LlyApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        app.push_screen(DeviceDetailScreen(cover, Settings()))
        await pilot.pause(0.1)
        screen = app.screen
        assert isinstance(screen, DeviceDetailScreen)
        screen.action_cover_open()
        screen.action_cover_stop()
        screen.action_cover_close()
        await pilot.pause(0.1)

    assert calls["cover_open"] == [0]
    assert calls["cover_close"] == [0]
    assert calls["cover_stop"] == [0]


async def test_detail_toggle_blocked_when_live_kind_is_cover(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression: a cover device whose stored kind is SWITCH must NOT call Switch.Set.

    Reproduces the user-reported bug "no handler Switch.Set" when pressing T on a
    blinder that mDNS reported as a Plus2PM (switch profile token).
    """
    calls = _patch_detail_rpcs(monkeypatch)

    async def cover_status(_client: object) -> DeviceStatus:
        return DeviceStatus(
            online=True, kind=DeviceKind.COVER, cover_state="closed", cover_position=0
        )

    monkeypatch.setattr("lly.tui.screens.detail.screen.fetch_status", cover_status)
    from lly.tui.screens.detail import DeviceDetailScreen

    # Stored kind is wrong (SWITCH) — live status will say COVER.
    miscategorised = _dev("eee", kind=DeviceKind.SWITCH)
    app = LlyApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        app.push_screen(DeviceDetailScreen(miscategorised, Settings()))
        # Wait for the first status fetch to land and recompose to happen.
        await pilot.pause(0.3)
        screen = app.screen
        assert isinstance(screen, DeviceDetailScreen)
        # `t` is still bound — pressing it must not send Switch.Set.
        screen.action_toggle_switch()
        await pilot.pause(0.1)

    assert calls["switch_set"] == []


async def test_main_screen_corrects_stored_kind_from_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MainScreen refresh updates Device.kind when live status disagrees."""
    saved: list[list[Device]] = []
    monkeypatch.setattr("lly.tui.screens.main.save_devices", saved.append)

    miscategorised = _dev("fff", kind=DeviceKind.SWITCH)

    async def cover_refresh(devices: list[Device], _settings: Settings) -> dict[str, DeviceStatus]:
        return {
            d.id: DeviceStatus(online=True, kind=DeviceKind.COVER, cover_position=0)
            for d in devices
        }

    monkeypatch.setattr("lly.tui.screens.main.refresh_statuses", cover_refresh)

    def _load_devices() -> list[Device]:
        return [miscategorised]

    def _load_settings() -> Settings:
        return Settings()

    monkeypatch.setattr("lly.tui.app.load_devices", _load_devices)
    monkeypatch.setattr("lly.tui.app.load_settings", _load_settings)

    app = LlyApp()
    async with app.run_test() as pilot:
        await pilot.pause(0.3)
        from lly.tui.screens.main import MainScreen

        screen = app.screen
        assert isinstance(screen, MainScreen)
        assert screen._devices[miscategorised.id].kind is DeviceKind.COVER

    assert saved, "save_devices was never called"
    assert saved[-1][0].kind is DeviceKind.COVER


async def test_detail_escape_dismisses(
    monkeypatch: pytest.MonkeyPatch, fake_devices: list[Device]
) -> None:
    _patch_detail_rpcs(monkeypatch)
    from lly.tui.screens.detail import DeviceDetailScreen

    app = LlyApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        app.push_screen(DeviceDetailScreen(fake_devices[0], Settings()))
        await pilot.pause(0.1)
        assert isinstance(app.screen, DeviceDetailScreen)
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, DeviceDetailScreen)
