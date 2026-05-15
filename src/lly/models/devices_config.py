"""`DevicesConfig` — the on-disk device fleet (`devices.toml`).

A thin Pydantic model loaded by hand from TOML. Earlier revisions wrapped this
in `pydantic-settings.BaseSettings` to reuse `TomlConfigSettingsSource`, but
that exposed an `LLY_DEVICES_*` env-var surface that isn't meaningful for a
device list — easier to read the file directly.
"""

from __future__ import annotations

import tomllib

from pydantic import BaseModel, Field

from lly.models.device import Device


class DevicesConfig(BaseModel):
    devices: list[Device] = Field(default_factory=list)

    def __init__(self, **data: object) -> None:
        if data:
            super().__init__(**data)
            return
        # Late import — `lly.paths` honours the in-process override used by
        # tests, so the path must resolve at construction time.
        from lly.paths import devices_path

        path = devices_path()
        if not path.exists():
            super().__init__()
            return
        with path.open("rb") as fh:
            raw = tomllib.load(fh)
        super().__init__(**raw)
