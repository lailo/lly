"""`Device` — a saved Shelly entry in the user's fleet."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_serializer


class DeviceKind(StrEnum):
    SWITCH = "switch"
    COVER = "cover"
    OTHER = "other"


class Device(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    name: str
    host: str
    model: str
    gen: int = Field(ge=2)
    kind: DeviceKind = DeviceKind.OTHER
    fw_version: str | None = None
    password_override: SecretStr | None = None

    @field_serializer("password_override", when_used="always")
    def _ser_password_override(self, value: SecretStr | None) -> str | None:
        # Plain-text on disk so `save → load` round-trips. Pydantic's default
        # would mask it as `**********`.
        return value.get_secret_value() if value is not None else None

    @classmethod
    def from_mdns(
        cls,
        *,
        shelly_id: str,
        host: str,
        app: str,
        gen: int,
        fw_version: str | None,
    ) -> Device:
        return cls(
            id=shelly_id,
            name=shelly_id,
            host=host,
            model=app,
            gen=gen,
            kind=infer_kind_from_app(app),
            fw_version=fw_version,
        )


def infer_kind_from_app(app: str) -> DeviceKind:
    """Best-effort device-kind guess from the Shelly model code.

    The mDNS `app` field carries the model code like "Plus1PM", "PlusShutter",
    "Plus2PM", "Pro4PM", "Mini1Gen3". This is a fast path so we can fill the
    `kind` column without an HTTP call. The status fetch later refines it.
    """
    a = app.lower()
    if "shutter" in a or "blu-shutter" in a or "cover" in a:
        return DeviceKind.COVER
    if any(
        token in a
        for token in (
            "1pm",
            "2pm",
            "1l",
            "1mini",
            "1gen",
            "plus1",
            "plus2",
            "pro1",
            "pro2",
            "pro4",
            "i4",
            "uni",
        )
    ):
        # Most of these are switches/dimmers controllable via Switch.*.
        if "i4" in a:
            return DeviceKind.OTHER  # input-only, no relay
        return DeviceKind.SWITCH
    return DeviceKind.OTHER
