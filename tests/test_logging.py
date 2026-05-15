"""Tests for the structured JSON-Lines file logger."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from pathlib import Path

import pytest

from lly.logging import configure, log_path
from lly.models import LogLevel, Settings


@pytest.fixture(autouse=True)
def _isolated_root_logger() -> Iterator[None]:
    """Snapshot + restore the root logger so tests can't leak handlers."""
    root = logging.getLogger()
    saved_level = root.level
    saved_handlers = list(root.handlers)
    yield
    for h in list(root.handlers):
        root.removeHandler(h)
        h.close()
    for h in saved_handlers:
        root.addHandler(h)
    root.setLevel(saved_level)


def test_configure_writes_jsonl_at_info_level(tmp_path: Path) -> None:
    configure(Settings(log_level=LogLevel.INFO))
    logging.getLogger("lly.test").info("hello", extra={"device_id": "abc"})
    # Flush all handlers.
    for h in logging.getLogger().handlers:
        h.flush()
    text = log_path().read_text("utf-8").strip()
    assert text, "no log line written"
    line = json.loads(text.splitlines()[-1])
    assert line["level"] == "info"
    # structlog renames stdlib `msg` to the structured `event` field.
    assert line["event"] == "hello"
    assert line["device_id"] == "abc"
    assert line["logger"] == "lly.test"


def test_configure_off_writes_nothing(tmp_path: Path) -> None:
    configure(Settings(log_level=LogLevel.OFF))
    logging.getLogger("lly.test").error("should not appear")
    assert not log_path().exists() or log_path().read_text() == ""


def test_configure_level_filters_below_threshold(tmp_path: Path) -> None:
    configure(Settings(log_level=LogLevel.WARNING))
    log = logging.getLogger("lly.test")
    log.info("info-level")  # below threshold, filtered
    log.warning("warn-level")  # passes
    log.error("error-level")  # passes
    for h in logging.getLogger().handlers:
        h.flush()
    lines = [json.loads(line) for line in log_path().read_text().splitlines()]
    msgs = {line["event"] for line in lines}
    assert "info-level" not in msgs
    assert "warn-level" in msgs
    assert "error-level" in msgs


def test_reconfigure_replaces_handler_not_appends(tmp_path: Path) -> None:
    """Two calls to configure mustn't pile up duplicate handlers."""
    configure(Settings(log_level=LogLevel.INFO))
    configure(Settings(log_level=LogLevel.ERROR))
    by_name = {
        getattr(h, "name", None): h
        for h in logging.getLogger().handlers
        if getattr(h, "name", None) in {"lly.file", "lly.console"}
    }
    assert set(by_name) == {"lly.file", "lly.console"}
    assert by_name["lly.file"].level == logging.ERROR
    assert by_name["lly.console"].level == logging.ERROR


def test_log_path_respects_config_dir_override(tmp_path: Path) -> None:
    # The autouse `_isolated_config_dir` fixture already sets config_dir to
    # tmp_path; just confirm log_path() picks it up.
    assert log_path().parent == tmp_path
    assert log_path().name == "lly.log"
