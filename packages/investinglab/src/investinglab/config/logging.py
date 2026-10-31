"""Structured logging built on structlog.

The library never configures logging on import (that is the application's decision). Call
:func:`configure_logging` once from an entry point: a notebook, a CLI or the API.
Standard-library loggers are routed through the same processors, so third-party logs
(httpx, uvicorn, ...) share the format and the bound context.
"""

from __future__ import annotations

import logging
import sys
from typing import TYPE_CHECKING

import structlog

from investinglab.config.settings import LogFormat, LogLevel

if TYPE_CHECKING:
    from structlog.typing import Processor

__all__ = ["configure_logging", "get_logger"]


def _shared_processors() -> list[Processor]:
    return [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
    ]


def configure_logging(
    level: LogLevel = LogLevel.INFO,
    log_format: LogFormat = LogFormat.CONSOLE,
) -> None:
    """Configure structlog and the standard library logging for the whole process.

    Args:
        level: Minimum severity to emit.
        log_format: ``console`` for local development, ``json`` for deployed environments.
    """
    renderer: Processor
    if log_format is LogFormat.JSON:
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty())

    shared = _shared_processors()
    structlog.configure(
        processors=[*shared, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.format_exc_info,
            renderer,
        ],
    )
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.value)


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Return a structured logger bound to ``name`` (usually ``__name__``)."""
    logger: structlog.stdlib.BoundLogger = structlog.stdlib.get_logger(name)
    return logger
