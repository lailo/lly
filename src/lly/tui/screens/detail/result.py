"""Return value of `DeviceDetailScreen`."""

from __future__ import annotations

from dataclasses import dataclass

from lly.models import Device


@dataclass(frozen=True)
class DetailResult:
    """Outcome of the detail modal.

    A bare ``DetailResult()`` means "user closed the modal without changes".
    Either ``removed`` or ``renamed_to`` may be set — never both.
    """

    removed: bool = False
    renamed_to: Device | None = None
