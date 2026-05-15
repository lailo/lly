"""Tests for config / devices persistence."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import SecretStr

from lly.config import (
    deduplicate_devices,
    effective_password,
    load_devices,
    load_settings,
    merge_devices,
    save_devices,
    save_settings,
)
from lly.models import Device, DeviceKind, Settings


def _make_device(**kwargs: object) -> Device:
    base = {
        "id": "shellyplus1-abc",
        "name": "shellyplus1-abc",
        "host": "10.0.0.10",
        "model": "Plus1PM",
        "gen": 2,
        "kind": DeviceKind.SWITCH,
        "fw_version": "1.4.4",
    }
    base.update(kwargs)
    return Device.model_validate(base)


def test_settings_round_trip() -> None:
    save_settings(Settings(default_password=SecretStr("hunter2"), refresh_interval_s=3.5))
    loaded = load_settings()
    assert loaded.refresh_interval_s == 3.5
    assert loaded.default_password is not None
    assert loaded.default_password.get_secret_value() == "hunter2"


def test_settings_default_when_missing() -> None:
    """No config.toml on disk → all defaults."""
    loaded = load_settings()
    assert loaded.default_password is None
    assert loaded.refresh_interval_s == 5.0


def test_devices_round_trip() -> None:
    devices = [_make_device(), _make_device(id="x", name="x", host="10.0.0.11")]
    save_devices(devices)
    reloaded = load_devices()
    assert {d.id for d in reloaded} == {"shellyplus1-abc", "x"}
    assert reloaded[0].kind is DeviceKind.SWITCH


def test_merge_preserves_user_name() -> None:
    existing = [_make_device(name="kitchen-light")]
    incoming = [_make_device(fw_version="1.5.0")]  # incoming "name" defaults to id
    merged = merge_devices(existing, incoming)
    assert len(merged) == 1
    assert merged[0].name == "kitchen-light"
    assert merged[0].fw_version == "1.5.0"


def test_effective_password_precedence() -> None:
    dev = _make_device(password_override=SecretStr("local-pw"))
    settings = Settings(default_password=SecretStr("global-pw"))
    assert effective_password(dev, settings) == "local-pw"

    dev_no_override = _make_device()
    assert effective_password(dev_no_override, settings) == "global-pw"

    assert effective_password(dev_no_override, Settings()) is None


def test_dedupe_keeps_friendly_named_entry() -> None:
    """When two entries share a host, the user-renamed one wins."""
    factory = _make_device(id="shelly2pmg3-aabb", name="shelly2pmg3-aabb", host="10.0.0.42")
    friendly = _make_device(
        id="shelly2pmg3-aabb-friendly", name="Blinders Office", host="10.0.0.42"
    )
    deduped = deduplicate_devices([factory, friendly])
    assert len(deduped) == 1
    assert deduped[0].name == "Blinders Office"

    # Order-invariant: friendly first should win too.
    deduped = deduplicate_devices([friendly, factory])
    assert len(deduped) == 1
    assert deduped[0].name == "Blinders Office"


def test_dedupe_preserves_distinct_hosts() -> None:
    a = _make_device(id="a", name="a", host="10.0.0.1")
    b = _make_device(id="b", name="b", host="10.0.0.2")
    assert deduplicate_devices([a, b]) == [a, b]


def test_merge_devices_drops_incoming_with_known_host() -> None:
    """Re-scanning under a different mDNS name must not create a second row."""
    existing = [_make_device(name="Blinders Office", host="10.0.0.10")]
    incoming = [
        _make_device(
            id="shelly2pmg3-otherid",
            name="shelly2pmg3-otherid",
            host="10.0.0.10",
        )
    ]
    merged = merge_devices(existing, incoming)
    assert len(merged) == 1
    assert merged[0].name == "Blinders Office"


def test_settings_picks_up_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """pydantic-settings: `LLY_DEFAULT_PASSWORD` populates the field when
    nothing's on disk."""
    monkeypatch.setenv("LLY_DEFAULT_PASSWORD", "from-env")
    s = Settings()
    assert s.default_password is not None
    assert s.default_password.get_secret_value() == "from-env"


def test_env_overrides_disk_value(monkeypatch: pytest.MonkeyPatch) -> None:
    """12-factor convention: env vars take precedence over the on-disk file.

    `settings_customise_sources` returns `(init, env, toml)` — first source
    wins in pydantic-settings, so env beats TOML.
    """
    save_settings(Settings(refresh_interval_s=3.5))
    monkeypatch.setenv("LLY_REFRESH_INTERVAL_S", "9")
    loaded = load_settings()
    assert loaded.refresh_interval_s == 9.0


def test_atomic_write_no_tmp_left_behind(tmp_path: Path) -> None:
    save_settings(Settings(scan_timeout_s=2.0))
    leftover = list(tmp_path.glob("*.tmp"))
    assert leftover == []
