"""Structured logging for lly, powered by ``structlog``.

Two sinks are wired up against the stdlib root logger so that *both* lly's own
``structlog.get_logger(...)`` calls and third-party libraries (httpx, zeroconf,
textual) flow through the same pipeline:

* ``<config_dir>/lly.log``  — JSON-Lines, rotated at 1 MB.
* ``stderr``                — human-readable, colourised when a TTY.

The level is driven by :class:`lly.models.Settings.log_level`; ``off`` detaches
both handlers entirely. Safe to call :func:`configure` repeatedly — handlers
are named so a settings round-trip in the TUI never piles up duplicates.
"""

from __future__ import annotations

import contextlib
import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

import structlog

from lly.models import Settings

# Anything ≥ CRITICAL silences ordinary logging without tripping structlog's
# ``make_filtering_bound_logger`` (which only knows the standard 10-50 range).
_OFF_SENTINEL = logging.CRITICAL + 10

_LEVEL_TO_INT: dict[str, int] = {
    "off": _OFF_SENTINEL,
    "error": logging.ERROR,
    "warning": logging.WARNING,
    "info": logging.INFO,
    "debug": logging.DEBUG,
}

_FILE_HANDLER_NAME = "lly.file"
_CONSOLE_HANDLER_NAME = "lly.console"


def log_path() -> Path:
    """Resolved location of the JSON-Lines log file."""
    # Local import — `lly.paths` honours the in-process override used by tests.
    from lly.paths import config_dir

    return config_dir() / "lly.log"


def _shared_processors() -> list[structlog.types.Processor]:
    """Processors common to lly loggers AND stdlib bridge formatter."""
    return [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]


def _detach_lly_handlers(root: logging.Logger) -> None:
    for h in list(root.handlers):
        if getattr(h, "name", None) in {_FILE_HANDLER_NAME, _CONSOLE_HANDLER_NAME}:
            root.removeHandler(h)
            h.close()


def configure(settings: Settings) -> None:
    """(Re)attach lly's logging handlers at the level requested by settings."""
    root = logging.getLogger()
    _detach_lly_handlers(root)

    level = _LEVEL_TO_INT.get(settings.log_level.value, _OFF_SENTINEL)
    if level >= _OFF_SENTINEL:
        # "off" — leave the root logger alone; no handlers attached.
        # Configure structlog with a filter at CRITICAL so direct lly logger
        # calls become cheap no-ops without depending on the stdlib root.
        structlog.configure(
            processors=[*_shared_processors(), structlog.dev.ConsoleRenderer(colors=False)],
            wrapper_class=structlog.make_filtering_bound_logger(logging.CRITICAL),
            logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
            cache_logger_on_first_use=False,
        )
        return

    shared = _shared_processors()
    # `ExtraAdder` surfaces stdlib `logger.info(..., extra={...})` keys as
    # event-dict fields so callers can keep using vanilla `logging` while still
    # producing structured output.
    foreign_chain: list[structlog.types.Processor] = [*shared, structlog.stdlib.ExtraAdder()]

    # Bridge stdlib LogRecord (from httpx, zeroconf, …) through structlog's
    # rendering pipeline. The `foreign_pre_chain` is what brings stdlib records
    # to parity with native structlog events before the final renderer runs.
    file_formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=foreign_chain,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.JSONRenderer(),
        ],
    )
    console_formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=foreign_chain,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty()),
        ],
    )

    path = log_path()
    file_handler = RotatingFileHandler(
        path,
        maxBytes=1_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    # Log lines can include device hosts and structured error payloads — keep
    # the file owner-only to match the on-disk config policy.
    with contextlib.suppress(FileNotFoundError):
        path.touch(exist_ok=True)
        os.chmod(path, 0o600)
    file_handler.name = _FILE_HANDLER_NAME
    file_handler.setLevel(level)
    file_handler.setFormatter(file_formatter)
    root.addHandler(file_handler)

    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.name = _CONSOLE_HANDLER_NAME
    console_handler.setLevel(level)
    console_handler.setFormatter(console_formatter)
    root.addHandler(console_handler)

    if root.level > level or root.level == logging.NOTSET:
        root.setLevel(level)

    structlog.configure(
        processors=[
            *shared,
            # Hand the event off to the stdlib root logger so the two handlers
            # above (file + console) format and emit it.
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.stdlib.LoggerFactory(),
        # Tests reconfigure repeatedly; caching would freeze the first
        # configuration into every cached BoundLogger.
        cache_logger_on_first_use=False,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Thin wrapper so callers don't need to import structlog directly."""
    return structlog.get_logger(name) if name else structlog.get_logger()  # type: ignore[no-any-return]
