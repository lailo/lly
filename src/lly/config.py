"""Config & devices persistence.

Loading is delegated to pydantic-settings (`Settings`, `DevicesConfig`);
saving is a thin atomic-write wrapper around `model_dump`. All file
locations come from `lly.paths`, which honours an in-process override so
tests can target `tmp_path`.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import tomli_w

from lly.models import Device, DevicesConfig, Settings
from lly.paths import config_dir, devices_path, settings_path

# Re-export for callers that imported these from `lly.config` historically.
__all__ = [
    "config_dir",
    "deduplicate_devices",
    "devices_path",
    "effective_password",
    "load_devices",
    "load_settings",
    "merge_devices",
    "save_devices",
    "save_settings",
    "settings_path",
]


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("wb") as fh:
        tomli_w.dump(payload, fh)
    # Lock down before publishing — files contain plaintext device passwords
    # (`SecretStr` fields are serialised verbatim so save→load round-trips).
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def load_settings() -> Settings:
    """Load settings via pydantic-settings (TOML + env-var layering)."""
    return Settings()


def save_settings(settings: Settings) -> None:
    # `mode="json"` converts StrEnum → str and dataclass-like types → plain
    # dicts. Our `SecretStr` field_serializer (with `when_used="always"`)
    # already produces the plain string in both modes, so no special-casing
    # is needed beyond this.
    payload = settings.model_dump(mode="json", exclude_none=True)
    _atomic_write(settings_path(), payload)


def load_devices() -> list[Device]:
    return deduplicate_devices(DevicesConfig().devices)


def save_devices(devices: list[Device]) -> None:
    # `mode="json"` coerces `DeviceKind` and any future StrEnum fields to
    # their string value, which tomli_w needs.
    serialised = [d.model_dump(mode="json", exclude_none=True) for d in devices]
    _atomic_write(devices_path(), {"devices": serialised})


def deduplicate_devices(devices: list[Device]) -> list[Device]:
    """Collapse duplicates that point at the same physical device.

    A Shelly often advertises itself twice over mDNS — once with the factory
    id-based hostname (`shelly2pmg3-aabbcc`) and once with the user-set name
    (`Blinders Office`) — so the same host IP shows up under two entries with
    different ids. When that happens, prefer the entry that has been renamed
    by the user (heuristic: `name != id`), then fall back to first-seen order.
    """
    by_host: dict[str, Device] = {}
    order: list[str] = []
    for d in devices:
        existing = by_host.get(d.host)
        if existing is None:
            by_host[d.host] = d
            order.append(d.host)
            continue
        # Same host → same physical device. Pick the friendlier name.
        existing_friendly = existing.name != existing.id
        new_friendly = d.name != d.id
        if new_friendly and not existing_friendly:
            by_host[d.host] = d
    return [by_host[h] for h in order]


def merge_devices(existing: list[Device], incoming: list[Device]) -> list[Device]:
    """Merge by `id`, preserving existing user-edited names and password overrides.

    Also collapses duplicates that point at the same host IP — see
    `deduplicate_devices`.
    """
    by_id: dict[str, Device] = {d.id: d for d in existing}
    existing_hosts = {d.host for d in existing}
    for new in incoming:
        prev = by_id.get(new.id)
        if prev is None:
            # Same host as an already-tracked (different-id) device? Skip; the
            # existing entry wins and likely already has a friendly name.
            if new.host in existing_hosts:
                continue
            by_id[new.id] = new
            existing_hosts.add(new.host)
            continue
        merged = new.model_copy(
            update={
                "name": prev.name if prev.name != prev.id else new.name,
                "password_override": prev.password_override,
            }
        )
        by_id[new.id] = merged
    return deduplicate_devices(list(by_id.values()))


def effective_password(device: Device, settings: Settings) -> str | None:
    if device.password_override is not None:
        return device.password_override.get_secret_value()
    if settings.default_password is not None:
        return settings.default_password.get_secret_value()
    return None
