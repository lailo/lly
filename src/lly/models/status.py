"""`DeviceStatus` — the polled live state of a single device."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

from lly.models.device import DeviceKind


class DeviceStatus(BaseModel):
    model_config = ConfigDict(extra="ignore")

    online: bool
    kind: DeviceKind
    on: bool | None = None
    cover_state: str | None = None
    cover_position: int | None = None
    error: str | None = None
    # Firmware update availability — parsed from `sys.available_updates`.
    update_stable: str | None = None
    update_beta: str | None = None

    @property
    def has_update(self) -> bool:
        return bool(self.update_stable or self.update_beta)

    def update_summary(self) -> str:
        """Compact one-line update info for the detail header."""
        parts: list[str] = []
        if self.update_stable:
            parts.append(f"stable {self.update_stable}")
        if self.update_beta:
            parts.append(f"beta {self.update_beta}")
        return ", ".join(parts) if parts else "up to date"

    def render(self) -> str:
        if not self.online:
            return f"ERR {self.error or ''}".strip()
        if self.kind is DeviceKind.SWITCH:
            return "ON" if self.on else "OFF"
        if self.kind is DeviceKind.COVER:
            return self._render_cover()
        return "—"

    def _render_cover(self) -> str:
        state = (self.cover_state or "?").lower()
        raw = self.cover_position
        if raw is None:
            return state.upper()
        # Shelly reports `current_pos` as 0=closed / 100=open, but our users
        # think of covers (blinders) the other way round — 0%=open, 100%=closed.
        # Flip once here so every callsite gets the user-mental-model value.
        pct = 100 - max(0, min(100, raw))
        # 10-wide bar; one block = 10%.
        filled = round(pct / 10)
        bar = "█" * filled + "░" * (10 - filled)
        # Percentage first so it remains visible when narrow table columns
        # truncate the bar. Transient states are spelled out for clarity.
        if state in ("opening", "closing"):
            return f"{pct:>3}% {bar} {state}"
        return f"{pct:>3}% {bar}"


def infer_kind_from_status(status: dict[str, Any]) -> DeviceKind:
    """Refine device kind by inspecting a Shelly.GetStatus payload."""
    if any(k.startswith("cover:") for k in status):
        return DeviceKind.COVER
    if any(k.startswith("switch:") for k in status):
        return DeviceKind.SWITCH
    return DeviceKind.OTHER
