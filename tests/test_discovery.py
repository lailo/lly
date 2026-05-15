"""Tests for the mDNS-info -> Device conversion."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from lly.discovery import device_from_service_info
from lly.models import DeviceKind


def _make_info(
    props: dict[bytes, bytes | None],
    *,
    addresses: list[bytes] | None = None,
    name: str = "shellyplus1pm-aabbcc._shelly._tcp.local.",
) -> Any:
    info = MagicMock()
    info.properties = props
    info.name = name
    info.addresses_by_version.return_value = (
        addresses if addresses is not None else [bytes([10, 0, 0, 42])]
    )
    return info


def test_device_from_service_info_gen2_switch() -> None:
    info = _make_info(
        {
            b"id": b"shellyplus1pm-aabbcc",
            b"gen": b"2",
            b"app": b"Plus1PM",
            b"ver": b"1.4.4",
        }
    )
    dev = device_from_service_info(info)
    assert dev is not None
    assert dev.id == "shellyplus1pm-aabbcc"
    assert dev.host == "10.0.0.42"
    assert dev.gen == 2
    assert dev.kind is DeviceKind.SWITCH
    assert dev.fw_version == "1.4.4"


def test_device_from_service_info_skips_gen1() -> None:
    info = _make_info({b"id": b"shelly1-aabb", b"gen": b"1", b"app": b"shelly1"})
    assert device_from_service_info(info) is None


def test_device_from_service_info_skips_no_gen() -> None:
    info = _make_info({b"id": b"x", b"app": b"y"})
    assert device_from_service_info(info) is None


def test_device_from_service_info_skips_no_address() -> None:
    info = _make_info(
        {b"id": b"x", b"gen": b"2", b"app": b"PlusShutter"},
        addresses=[],
    )
    assert device_from_service_info(info) is None


def test_device_from_service_info_uses_friendly_service_name() -> None:
    """If the mDNS service name differs from the TXT id, that's the user's label."""
    info = _make_info(
        {b"id": b"shelly2pmg3-aabb", b"gen": b"2", b"app": b"Plus2PM", b"ver": b"1.4.4"},
        name="Blinders Office._shelly._tcp.local.",
    )
    dev = device_from_service_info(info)
    assert dev is not None
    assert dev.id == "shelly2pmg3-aabb"
    assert dev.name == "Blinders Office"


def test_device_from_service_info_falls_back_to_id_for_factory_ad() -> None:
    info = _make_info(
        {b"id": b"shelly2pmg3-aabb", b"gen": b"2", b"app": b"Plus2PM"},
        name="shelly2pmg3-aabb._shelly._tcp.local.",
    )
    dev = device_from_service_info(info)
    assert dev is not None
    assert dev.name == dev.id == "shelly2pmg3-aabb"


def test_device_from_service_info_cover() -> None:
    info = _make_info(
        {b"id": b"shelly2pm-ddee", b"gen": b"2", b"app": b"PlusShutter", b"ver": b"1.4.0"}
    )
    dev = device_from_service_info(info)
    assert dev is not None
    assert dev.kind is DeviceKind.COVER
