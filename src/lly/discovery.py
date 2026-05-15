"""Async mDNS discovery of Shelly Gen2/Gen3 devices."""

from __future__ import annotations

import asyncio
import ipaddress
from collections.abc import AsyncIterator
from contextlib import suppress
from typing import Any

from zeroconf import IPVersion, ServiceStateChange
from zeroconf.asyncio import AsyncServiceBrowser, AsyncServiceInfo, AsyncZeroconf

from lly.logging import get_logger
from lly.models import Device

SHELLY_SERVICE = "_shelly._tcp.local."
_log = get_logger(__name__)


def _decode_txt(props: dict[bytes, bytes | None]) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw_k, raw_v in props.items():
        if raw_v is None:
            continue
        try:
            out[raw_k.decode("utf-8")] = raw_v.decode("utf-8")
        except UnicodeDecodeError:
            continue
    return out


def _pick_host(info: AsyncServiceInfo) -> str | None:
    for raw in info.addresses_by_version(IPVersion.V4Only):
        with suppress(ValueError):
            return str(ipaddress.IPv4Address(raw))
    return None


def device_from_service_info(info: AsyncServiceInfo) -> Device | None:
    """Convert a resolved AsyncServiceInfo into a Device, or None if not Gen2+.

    Shelly Gen2/3 devices typically advertise themselves twice over mDNS: once
    under the factory id (`shelly2pmg3-aabbcc._shelly._tcp.local.`) and once
    under the user-assigned name (`Blinders Office._shelly._tcp.local.`). The
    TXT `id` is the same in both — that's the canonical device id (MAC). The
    *service name* (left of the first dot in `info.name`) is what carries the
    friendly label. We surface that as `Device.name` so the scan UI shows what
    the user actually named the device, while `Device.id` stays canonical.
    """
    props = _decode_txt(info.properties or {})
    raw_gen = props.get("gen")
    if raw_gen is None:
        return None
    try:
        gen = int(raw_gen)
    except ValueError:
        return None
    if gen < 2:
        return None

    service_name = info.name.split(".", 1)[0] if info.name else None
    shelly_id = props.get("id") or service_name
    if not shelly_id:
        return None
    friendly_name = service_name if service_name and service_name != shelly_id else shelly_id

    host = _pick_host(info)
    if host is None:
        return None
    app = props.get("app", "unknown")
    fw_version = props.get("ver")

    device = Device.from_mdns(
        shelly_id=shelly_id,
        host=host,
        app=app,
        gen=gen,
        fw_version=fw_version,
    )
    # `from_mdns` defaults the name to the id; override with the friendly one
    # when mDNS gave us a separate service name.
    if friendly_name != device.name:
        device = device.model_copy(update={"name": friendly_name})
    return device


async def scan(
    timeout: float = 5.0,
    *,
    zc: AsyncZeroconf | None = None,
) -> AsyncIterator[Device]:
    """Yield each newly-discovered Shelly Gen2/Gen3 device once.

    Runs an `AsyncServiceBrowser` for `timeout` seconds, deduplicates on both
    shelly id AND host IP — a single physical device can advertise itself twice
    over mDNS (once under its factory id, once under a user-assigned name), so
    id-only dedup isn't enough.
    """
    seen_by_id: dict[str, Device] = {}
    host_to_id: dict[str, str] = {}
    queue: asyncio.Queue[Device | None] = asyncio.Queue()
    owned_zc = zc is None
    actual_zc = zc or AsyncZeroconf()
    # Track in-flight resolutions so we can drain them in the `finally` block —
    # without this, a fire-and-forget `ensure_future` can outlive the zeroconf
    # close and produce "Task was destroyed but it is pending" warnings.
    pending: set[asyncio.Task[None]] = set()

    def _on_change(
        zeroconf: Any,
        service_type: str,
        name: str,
        state_change: ServiceStateChange,
    ) -> None:
        if state_change is not ServiceStateChange.Added:
            return
        task = asyncio.ensure_future(_resolve_and_emit(zeroconf, service_type, name))
        pending.add(task)
        task.add_done_callback(pending.discard)

    async def _resolve_and_emit(zeroconf: Any, service_type: str, name: str) -> None:
        info = AsyncServiceInfo(service_type, name)
        try:
            if await info.async_request(zeroconf, 3000):
                device = device_from_service_info(info)
                if device is None:
                    return
                # Same host, different id → second mDNS ad of the same physical
                # device. If the new ad has the user-friendly name and the one
                # we already yielded was the factory id, upgrade the existing
                # entry's name and re-emit. Otherwise skip.
                bound_id = host_to_id.get(device.host)
                if bound_id is not None and bound_id != device.id:
                    existing = seen_by_id[bound_id]
                    if device.name != device.id and existing.name == existing.id:
                        upgraded = existing.model_copy(update={"name": device.name})
                        seen_by_id[bound_id] = upgraded
                        await queue.put(upgraded)
                    return
                # Same id seen again — friendly-name upgrade only.
                if device.id in seen_by_id:
                    existing = seen_by_id[device.id]
                    if device.name != device.id and existing.name == existing.id:
                        seen_by_id[device.id] = device
                        await queue.put(device)
                    return
                seen_by_id[device.id] = device
                host_to_id[device.host] = device.id
                await queue.put(device)
        except Exception:
            _log.exception("failed to resolve %s", name)

    browser = AsyncServiceBrowser(
        actual_zc.zeroconf,
        [SHELLY_SERVICE],
        handlers=[_on_change],
    )

    async def _stop_after_timeout() -> None:
        await asyncio.sleep(timeout)
        await queue.put(None)

    stopper = asyncio.create_task(_stop_after_timeout())

    try:
        while True:
            item = await queue.get()
            if item is None:
                break
            yield item
    finally:
        stopper.cancel()
        with suppress(asyncio.CancelledError):
            await stopper
        await browser.async_cancel()
        if pending:
            # Drain outstanding resolutions before zeroconf close. Each task
            # already self-logs exceptions, so swallowing them here is safe.
            await asyncio.gather(*pending, return_exceptions=True)
        if owned_zc:
            await actual_zc.async_close()
