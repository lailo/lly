"""Global test fixtures.

The autouse `_isolated_config_dir` fixture points every test at a fresh
`tmp_path` for config / devices files, so nothing in the suite touches
the real `~/Library/Application Support/lly/` directory.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from lly.paths import set_config_dir


@pytest.fixture(autouse=True)
def _isolated_config_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Isolate every test from the user's real lly config directory.

    Also clear any `LLY_*` env vars that might be set on the developer's
    machine — tests assume defaults unless they explicitly set otherwise.
    """
    for key in [k for k in list(__import__("os").environ) if k.startswith("LLY_")]:
        monkeypatch.delenv(key, raising=False)
    set_config_dir(tmp_path)
    yield
    set_config_dir(None)
