"""Structured logging built on structlog.

The library never configures logging on import (that is the application's decision). Call
:func:`configure_logging` once from an entry point: a notebook, a CLI or the API.
Standard-library loggers are routed through the same processors, so third-party logs
(httpx, uvicorn, ...) share the format and the bound context.
"""

from __future__ import annotations

import logging
import re
import sys
from typing import TYPE_CHECKING, Any, Final

import structlog

from investinglab.config.settings import LogFormat, LogLevel

if TYPE_CHECKING:
    from collections.abc import Sequence

    from structlog.typing import EventDict, Processor, WrappedLogger

__all__ = ["configure_logging", "get_logger", "redact_secrets", "redact_text"]

# Credentials sent as query parameters (FRED ``api_key``, Alpha Vantage ``apikey``, SIX
# ``token``...) must never be written to any log, whoever emits the line.
_SECRET_IN_TEXT: Final = re.compile(
    r"(?i)\b(api_?key|access_token|token|secret|password)=([^&\s\"']+)"
)
# Chatty third-party loggers that print full request URLs at INFO level.
_QUIET_LOGGERS: Final = ("httpx", "httpcore")


def redact_text(text: str) -> str:
    """``text`` with every ``key=value`` credential masked (``api_key=***``).

    The same rule the logs follow, for whatever else records a URL or a message (the traces
    of the API, ADR-0048).
    """
    return _SECRET_IN_TEXT.sub(r"\1=***", text)


def _scrub(value: Any) -> Any:  # noqa: ANN401 - log values are arbitrary
    return redact_text(value) if isinstance(value, str) else value


def redact_secrets(_: WrappedLogger, __: str, event_dict: EventDict) -> EventDict:
    """Structlog processor that masks ``key=value`` credentials in every string value."""
    return {key: _scrub(value) for key, value in event_dict.items()}


def _shared_processors(extra: Sequence[Processor] = ()) -> list[Processor]:
    return [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        *extra,
        redact_secrets,  # last: whatever the others added is masked too
    ]


def configure_logging(
    level: LogLevel = LogLevel.INFO,
    log_format: LogFormat = LogFormat.CONSOLE,
    *,
    processors: Sequence[Processor] = (),
) -> None:
    """Configure structlog and the standard library logging for the whole process.

    Args:
        level: Minimum severity to emit.
        log_format: ``console`` for local development, ``json`` for deployed environments.
        processors: More structlog processors for every line, run before the credentials
            are masked (the API adds the trace and span ids of the line, ADR-0048).
    """
    renderer: Processor
    if log_format is LogFormat.JSON:
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty())

    shared = _shared_processors(processors)
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
            redact_secrets,  # again: the traceback text only exists from here on
            renderer,
        ],
    )
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.value)
    for name in _QUIET_LOGGERS:
        logging.getLogger(name).setLevel(max(logging.WARNING, root.level))


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Return a structured logger bound to ``name`` (usually ``__name__``)."""
    logger: structlog.stdlib.BoundLogger = structlog.stdlib.get_logger(name)
    return logger
