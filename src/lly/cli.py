"""Command-line entry point. Default action launches the TUI."""

from __future__ import annotations

import asyncio
import getpass
from typing import Annotated

import typer
from pydantic import SecretStr
from rich.console import Console
from rich.table import Table

from lly import __version__
from lly.config import (
    devices_path,
    load_devices,
    load_settings,
    merge_devices,
    save_devices,
    save_settings,
    settings_path,
)
from lly.discovery import scan as mdns_scan
from lly.fleet import bulk_reboot, bulk_update, refresh_statuses
from lly.models import Device

app = typer.Typer(
    add_completion=False,
    no_args_is_help=False,
    help="Manage Shelly Gen2/Gen3 devices on the LAN.",
)
config_app = typer.Typer(help="Manage lly configuration.")
action_app = typer.Typer(help="Run actions against devices.")
app.add_typer(config_app, name="config")
app.add_typer(action_app, name="action")

console = Console()


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"lly {__version__}")
        raise typer.Exit


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    _version: Annotated[
        bool,
        typer.Option(
            "--version",
            "-V",
            callback=_version_callback,
            is_eager=True,
            help="Show version and exit.",
        ),
    ] = False,
) -> None:
    if ctx.invoked_subcommand is None:
        from lly.tui.app import run

        run()


@app.command("scan")
def scan_cmd(timeout: float = typer.Option(5.0, "--timeout", "-t")) -> None:
    """Scan mDNS for Shelly Gen2/Gen3 devices and print what's found."""
    devices = asyncio.run(_collect_scan(timeout))
    _print_devices_table(devices, title=f"Found {len(devices)} device(s)")


async def _collect_scan(timeout: float) -> list[Device]:
    found: list[Device] = []
    async for dev in mdns_scan(timeout=timeout):
        found.append(dev)
    return found


@app.command("add")
def add_cmd(
    timeout: float = typer.Option(5.0, "--timeout", "-t"),
    yes: bool = typer.Option(
        False, "--yes", "-y", help="Import all scanned devices without prompting."
    ),
) -> None:
    """Scan for devices and add them to the saved fleet."""
    found = asyncio.run(_collect_scan(timeout))
    if not found:
        console.print("[yellow]No devices found.[/]")
        raise typer.Exit(code=1)

    if not yes:
        _print_devices_table(found, title="Discovered")
        ids_csv = typer.prompt(
            "Comma-separated IDs to import (blank = all, '-' = abort)",
            default="",
            show_default=False,
        ).strip()
        if ids_csv == "-":
            raise typer.Exit(code=1)
        if ids_csv:
            wanted = {x.strip() for x in ids_csv.split(",")}
            found = [d for d in found if d.id in wanted]

    existing = load_devices()
    merged = merge_devices(existing, found)
    save_devices(merged)
    console.print(f"[green]Saved {len(found)} device(s)[/] to {devices_path()}")


@app.command("list")
def list_cmd() -> None:
    """Print the saved device fleet."""
    _print_devices_table(load_devices(), title="Saved devices")


@app.command("status")
def status_cmd(ids: Annotated[list[str] | None, typer.Argument()] = None) -> None:
    """Print live status for known devices (all by default)."""
    settings = load_settings()
    devices = _select_devices(ids)
    if not devices:
        console.print("[yellow]No devices match.[/]")
        raise typer.Exit(code=1)
    statuses = asyncio.run(refresh_statuses(devices, settings))

    table = Table(title="Live status")
    for col in ("id", "name", "host", "fw", "state"):
        table.add_column(col)
    for dev in devices:
        st = statuses.get(dev.id)
        table.add_row(dev.id, dev.name, dev.host, dev.fw_version or "-", st.render() if st else "—")
    console.print(table)


@action_app.command("reboot")
def action_reboot(ids: Annotated[list[str] | None, typer.Argument()] = None) -> None:
    """Reboot one or more devices."""
    _run_bulk(ids, kind="reboot")


@action_app.command("update")
def action_update(ids: Annotated[list[str] | None, typer.Argument()] = None) -> None:
    """Trigger an OTA firmware update on one or more devices."""
    _run_bulk(ids, kind="update")


def _run_bulk(ids: list[str] | None, *, kind: str) -> None:
    settings = load_settings()
    devices = _select_devices(ids)
    if not devices:
        console.print("[yellow]No devices match.[/]")
        raise typer.Exit(code=1)
    runner = bulk_reboot if kind == "reboot" else bulk_update
    outcomes = asyncio.run(runner(devices, settings))
    ok = sum(1 for o in outcomes if o.ok)
    fail = len(outcomes) - ok
    for o in outcomes:
        prefix = "[green]ok[/]" if o.ok else "[red]err[/]"
        console.print(f"{prefix} {o.device.name} ({o.device.host}) — {o.message}")
    console.print(f"\n{kind}: {ok} ok, {fail} failed.")
    if fail:
        raise typer.Exit(code=2)


@config_app.command("show")
def config_show() -> None:
    """Show effective settings and on-disk paths."""
    s = load_settings()
    console.print(f"[bold]settings file:[/] {settings_path()}")
    console.print(f"[bold]devices file:[/]  {devices_path()}")
    console.print(f"default_password: {'***set***' if s.default_password else '(unset)'}")
    console.print(f"scan_timeout_s:   {s.scan_timeout_s}")
    console.print(f"refresh_interval_s: {s.refresh_interval_s}")


@config_app.command("set-password")
def config_set_password() -> None:
    """Set the default Shelly password (used for all devices unless overridden)."""
    pwd = getpass.getpass("Default Shelly password (empty to clear): ")
    s = load_settings()
    s.default_password = SecretStr(pwd) if pwd else None
    save_settings(s)
    console.print("[green]Saved.[/]")


def _select_devices(ids: list[str] | None) -> list[Device]:
    devices = load_devices()
    if not ids:
        return devices
    wanted = set(ids)
    return [d for d in devices if d.id in wanted or d.name in wanted]


def _print_devices_table(devices: list[Device], *, title: str) -> None:
    table = Table(title=title)
    for col in ("id", "name", "model", "host", "gen", "fw"):
        table.add_column(col)
    for d in devices:
        table.add_row(d.id, d.name, d.model, d.host, str(d.gen), d.fw_version or "-")
    console.print(table)
