"""Fleet-level helpers: parallel status refresh and bulk actions."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass

from lly.config import effective_password
from lly.logging import get_logger
from lly.models import Device, DeviceKind, DeviceStatus, Settings
from lly.shelly.client import ShellyClient, ShellyError
from lly.shelly.rpc import fetch_status, get_device_info, reboot, update_firmware

_log = get_logger(__name__)


@dataclass(frozen=True)
class BulkOutcome:
    device: Device
    ok: bool
    message: str


@asynccontextmanager
async def connect(device: Device, settings: Settings) -> AsyncIterator[ShellyClient]:
    """Open an authenticated `ShellyClient` for a device using the effective password.

    Single source for the `effective_password` + `ShellyClient(host, pw, timeout)`
    pattern — every callsite (TUI actions, fleet bulk ops, refresh) goes through
    this so `request_timeout_s` and password-precedence rules can't drift.
    """
    password = effective_password(device, settings)
    async with ShellyClient(device.host, password, timeout=settings.request_timeout_s) as client:
        yield client


async def fetch_remote_name(device: Device, settings: Settings) -> str | None:
    """Ask the device for its user-assigned name via `Shelly.GetDeviceInfo`.

    Returns the canonical name as the device reports it, or None if the device
    is unreachable / doesn't expose one. Used to upgrade rows whose `name`
    still falls back to the factory id.
    """
    try:
        async with connect(device, settings) as client:
            info = await get_device_info(client)
    except ShellyError as err:
        _log.warning(
            "fetch_remote_name failed",
            device_id=device.id,
            host=device.host,
            code=err.code,
            error=err.message,
        )
        return None
    remote = info.get("name")
    if isinstance(remote, str) and remote:
        return remote
    return None


async def _run_on_device(
    device: Device,
    settings: Settings,
    action: Callable[[ShellyClient], Awaitable[None]],
) -> BulkOutcome:
    try:
        async with connect(device, settings) as client:
            await action(client)
        return BulkOutcome(device=device, ok=True, message="ok")
    except ShellyError as err:
        _log.error(
            "bulk action failed",
            device_id=device.id,
            host=device.host,
            code=err.code,
            error=err.message,
        )
        return BulkOutcome(device=device, ok=False, message=err.message)
    except (TimeoutError, OSError) as err:
        # Transport errors *outside* `ShellyClient.call` (e.g. DNS, connect
        # refused during `__aenter__`) shouldn't abort a whole bulk batch.
        _log.error(
            "bulk action transport failure",
            device_id=device.id,
            host=device.host,
            error=str(err) or type(err).__name__,
        )
        return BulkOutcome(device=device, ok=False, message=str(err) or type(err).__name__)


async def refresh_statuses(
    devices: list[Device],
    settings: Settings,
) -> dict[str, DeviceStatus]:
    """Fetch each device's status concurrently, bounded by settings.refresh_concurrency.

    A single flaky device must not blank the whole table — exceptions are
    converted into an offline `DeviceStatus` per-device so the rest of the
    fleet's results survive.
    """
    sem = asyncio.Semaphore(settings.refresh_concurrency)

    async def one(device: Device) -> tuple[str, DeviceStatus]:
        try:
            async with sem, connect(device, settings) as client:
                return device.id, await fetch_status(client)
        except (TimeoutError, ShellyError, OSError) as err:
            message = getattr(err, "message", None) or str(err) or type(err).__name__
            _log.warning(
                "refresh failed",
                device_id=device.id,
                host=device.host,
                error=message,
            )
            return device.id, DeviceStatus(online=False, kind=DeviceKind.OTHER, error=message)

    results = await asyncio.gather(*(one(d) for d in devices))
    return dict(results)


async def bulk_reboot(devices: list[Device], settings: Settings) -> list[BulkOutcome]:
    return list(await asyncio.gather(*(_run_on_device(d, settings, reboot) for d in devices)))


async def bulk_update(devices: list[Device], settings: Settings) -> list[BulkOutcome]:
    async def _action(client: ShellyClient) -> None:
        await update_firmware(client)

    return list(await asyncio.gather(*(_run_on_device(d, settings, _action) for d in devices)))
