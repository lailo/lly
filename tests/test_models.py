"""Tests for the data models and status parsing."""

from __future__ import annotations

from lly.models import (
    Device,
    DeviceKind,
    DeviceStatus,
    infer_kind_from_app,
    infer_kind_from_status,
)
from lly.shelly.rpc import parse_status


def test_infer_kind_from_app_cover() -> None:
    assert infer_kind_from_app("PlusShutter") is DeviceKind.COVER


def test_infer_kind_from_app_switch() -> None:
    assert infer_kind_from_app("Plus1PM") is DeviceKind.SWITCH
    assert infer_kind_from_app("Mini1Gen3") is DeviceKind.SWITCH


def test_infer_kind_from_app_other() -> None:
    assert infer_kind_from_app("PlusI4") is DeviceKind.OTHER
    assert infer_kind_from_app("Unknown") is DeviceKind.OTHER


def test_infer_kind_from_status_cover() -> None:
    payload = {"cover:0": {"state": "open", "current_pos": 73}, "wifi": {"ssid": "x"}}
    assert infer_kind_from_status(payload) is DeviceKind.COVER


def test_infer_kind_from_status_switch() -> None:
    payload = {"switch:0": {"output": True}, "wifi": {"ssid": "x"}}
    assert infer_kind_from_status(payload) is DeviceKind.SWITCH


def test_parse_status_switch_on() -> None:
    parsed = parse_status({"switch:0": {"output": True}})
    assert parsed.kind is DeviceKind.SWITCH
    assert parsed.on is True
    assert parsed.render() == "ON"


def test_parse_status_cover_partial() -> None:
    parsed = parse_status({"cover:0": {"state": "open", "current_pos": 42}})
    assert parsed.kind is DeviceKind.COVER
    assert parsed.cover_position == 42
    rendered = parsed.render()
    # Display is inverted from Shelly's raw value: 42 → 58% (blinder closed-ness).
    assert "58%" in rendered
    # 58% → 6 filled blocks, 4 empty (rounded).
    assert "██████" in rendered
    assert "░░░░" in rendered


def test_parse_status_picks_up_available_updates() -> None:
    parsed = parse_status(
        {
            "switch:0": {"output": False},
            "sys": {
                "available_updates": {
                    "stable": {"version": "1.5.0"},
                    "beta": {"version": "1.6.0-beta1"},
                }
            },
        }
    )
    assert parsed.update_stable == "1.5.0"
    assert parsed.update_beta == "1.6.0-beta1"
    assert parsed.has_update is True
    summary = parsed.update_summary()
    assert "stable 1.5.0" in summary
    assert "beta 1.6.0-beta1" in summary


def test_parse_status_no_updates_means_up_to_date() -> None:
    parsed = parse_status({"switch:0": {"output": True}, "sys": {"available_updates": {}}})
    assert parsed.has_update is False
    assert parsed.update_summary() == "up to date"


def test_parse_status_cover_moving_shows_state() -> None:
    parsed = parse_status({"cover:0": {"state": "opening", "current_pos": 30}})
    rendered = parsed.render()
    assert "opening" in rendered
    # Display is inverted: raw 30 → 70%.
    assert "70%" in rendered


def test_status_render_offline() -> None:
    s = DeviceStatus(online=False, kind=DeviceKind.OTHER, error="boom")
    assert "ERR" in s.render()
    assert "boom" in s.render()


def test_device_from_mdns_kind_inference() -> None:
    dev = Device.from_mdns(
        shelly_id="shelly-plus1pm-aabbcc", host="10.0.0.5", app="Plus1PM", gen=2, fw_version="1.0"
    )
    assert dev.kind is DeviceKind.SWITCH
    assert dev.gen == 2
