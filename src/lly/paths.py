"""Sole source of truth for lly's on-disk paths.

Both `lly.config` and `lly.models.Settings` resolve their file locations
through this module so a single override applies everywhere — particularly
useful in tests, which call `set_config_dir(tmp_path)` to keep the
user's real `~/Library/Application Support/lly/` untouched.

Resolution order (highest to lowest):
  1. In-process override (`set_config_dir(...)`)
  2. `LLY_CONFIG_DIR` environment variable
  3. `platformdirs.user_config_dir("lly")` (OS default)
"""

from __future__ import annotations

import os
from pathlib import Path

from platformdirs import user_config_dir

_override: Path | None = None


def set_config_dir(path: Path | None) -> None:
    """Force every subsequent `config_dir()` call to point at `path`.

    Pass `None` to clear the override (the next call falls back to the env
    var, then the OS default).
    """
    global _override
    _override = path


def config_dir() -> Path:
    """Return the resolved lly config directory, creating it if needed."""
    if _override is not None:
        _override.mkdir(parents=True, exist_ok=True)
        return _override
    env_dir = os.environ.get("LLY_CONFIG_DIR")
    base = Path(env_dir) if env_dir else Path(user_config_dir("lly"))
    base.mkdir(parents=True, exist_ok=True)
    return base


def settings_path() -> Path:
    return config_dir() / "config.toml"


def devices_path() -> Path:
    return config_dir() / "devices.toml"
