"""Typed wrappers over the Shelly RPC methods we use."""

from __future__ import annotations

from typing import Any

from lly.logging import get_logger
from lly.models import DeviceKind, DeviceStatus, infer_kind_from_status
from lly.shelly.client import ShellyClient, ShellyError

_log = get_logger(__name__)


async def get_device_info(client: ShellyClient) -> dict[str, Any]:
    return await client.call("Shelly.GetDeviceInfo")


async def get_status(client: ShellyClient) -> dict[str, Any]:
    return await client.call("Shelly.GetStatus")


async def reboot(client: ShellyClient) -> None:
    await client.call("Shelly.Reboot")


async def set_device_name(client: ShellyClient, name: str) -> dict[str, Any]:
    """Rename the device via `Sys.SetConfig`.

    Shelly returns a `restart_required` flag — for a name change it's normally
    `false`, but we surface the whole result so callers can decide what to do.
    """
    return await client.call("Sys.SetConfig", {"config": {"device": {"name": name}}})


async def update_firmware(client: ShellyClient, *, stage: str = "stable") -> dict[str, Any]:
    """Trigger an OTA update from the official Shelly firmware server.

    Returns the RPC result; Shelly returns a `-104` error / "no available updates"
    when there's nothing to do — we surface that as a `ShellyError` for the caller
    to render as a non-fatal info message.
    """
    return await client.call("Shelly.Update", {"stage": stage})


async def switch_set(client: ShellyClient, switch_id: int, *, on: bool) -> None:
    await client.call("Switch.Set", {"id": switch_id, "on": on})


async def cover_go_to_position(client: ShellyClient, cover_id: int, *, position: int) -> None:
    if not 0 <= position <= 100:
        raise ValueError("position must be 0..100")
    await client.call("Cover.GoToPosition", {"id": cover_id, "pos": position})


async def cover_open(client: ShellyClient, cover_id: int = 0) -> None:
    await client.call("Cover.Open", {"id": cover_id})


async def cover_close(client: ShellyClient, cover_id: int = 0) -> None:
    await client.call("Cover.Close", {"id": cover_id})


async def cover_stop(client: ShellyClient, cover_id: int = 0) -> None:
    await client.call("Cover.Stop", {"id": cover_id})


def _available_updates(status: dict[str, Any]) -> tuple[str | None, str | None]:
    sys_info = status.get("sys", {})
    available = sys_info.get("available_updates", {}) if isinstance(sys_info, dict) else {}
    if not isinstance(available, dict):
        return None, None
    stable = available.get("stable") or {}
    beta = available.get("beta") or {}
    return (
        stable.get("version") if isinstance(stable, dict) else None,
        beta.get("version") if isinstance(beta, dict) else None,
    )


def parse_status(status: dict[str, Any]) -> DeviceStatus:
    """Distil a Shelly.GetStatus payload into our compact DeviceStatus model."""
    kind = infer_kind_from_status(status)
    update_stable, update_beta = _available_updates(status)
    common: dict[str, Any] = {
        "online": True,
        "update_stable": update_stable,
        "update_beta": update_beta,
    }
    if kind is DeviceKind.SWITCH:
        switch = status.get("switch:0", {})
        return DeviceStatus(kind=kind, on=bool(switch.get("output", False)), **common)
    if kind is DeviceKind.COVER:
        cover = status.get("cover:0", {})
        return DeviceStatus(
            kind=kind,
            cover_state=cover.get("state"),
            cover_position=cover.get("current_pos"),
            **common,
        )
    return DeviceStatus(kind=DeviceKind.OTHER, **common)


async def fetch_status(client: ShellyClient) -> DeviceStatus:
    try:
        return parse_status(await get_status(client))
    except ShellyError as err:
        _log.error(
            "fetch_status failed",
            host=client.host,
            code=err.code,
            error=err.message,
        )
        return DeviceStatus(online=False, kind=DeviceKind.OTHER, error=err.message)
