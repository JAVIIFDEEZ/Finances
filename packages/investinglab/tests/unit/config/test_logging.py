from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

import pytest
import structlog

from investinglab.config import LogFormat, LogLevel, configure_logging, get_logger

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture(autouse=True)
def _restore_logging() -> Iterator[None]:
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    yield
    root.handlers[:] = handlers
    root.setLevel(level)
    structlog.reset_defaults()
    structlog.contextvars.clear_contextvars()


def test_json_format_emits_one_parseable_object_per_line(
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_logging(LogLevel.INFO, LogFormat.JSON)
    structlog.contextvars.bind_contextvars(request_id="abc")

    get_logger("investinglab.test").info("prices_fetched", ticker="SAN.MC", rows=252)

    record = json.loads(capsys.readouterr().err.strip())
    assert record["event"] == "prices_fetched"
    assert record["ticker"] == "SAN.MC"
    assert record["rows"] == 252
    assert record["request_id"] == "abc"
    assert record["level"] == "info"
    assert record["logger"] == "investinglab.test"
    assert record["timestamp"].endswith("Z")


def test_standard_library_loggers_share_the_format(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(LogLevel.INFO, LogFormat.JSON)

    logging.getLogger("thirdparty.lib").info("connected")

    record = json.loads(capsys.readouterr().err.strip())
    assert record["event"] == "connected"
    assert record["logger"] == "thirdparty.lib"


def test_level_filters_records(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(LogLevel.WARNING, LogFormat.JSON)

    get_logger().info("hidden")
    get_logger().warning("shown")

    output = capsys.readouterr().err
    assert "hidden" not in output
    assert "shown" in output


def test_console_format_is_human_readable(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(LogLevel.INFO, LogFormat.CONSOLE)

    get_logger().info("hello", who="world")

    output = capsys.readouterr().err
    assert "hello" in output
    assert "who" in output


def test_credentials_are_scrubbed_from_any_logger(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(LogLevel.DEBUG, LogFormat.JSON)

    logging.getLogger("thirdparty").warning("GET /x?series_id=A&api_key=abc123&apikey=zz")
    get_logger().info("calling", url="https://x.test/q?token=pk_live_1&x=1")

    output = capsys.readouterr().err
    assert "abc123" not in output
    assert "pk_live_1" not in output
    assert "zz" not in output
    assert "api_key=***" in output
    assert "token=***" in output


def test_noisy_http_loggers_are_quietened() -> None:
    configure_logging(LogLevel.DEBUG, LogFormat.JSON)

    assert logging.getLogger("httpx").level == logging.WARNING
    assert logging.getLogger("httpcore").level == logging.WARNING
