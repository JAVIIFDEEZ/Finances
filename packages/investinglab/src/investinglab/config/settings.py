"""Runtime configuration loaded from environment variables and an optional ``.env`` file.

Every variable is prefixed with ``INVESTINGLAB_``; nested settings use ``__`` as delimiter.
Values are validated at start-up so that a misconfiguration fails fast with a clear error
instead of surfacing later as a confusing runtime failure.
"""

from __future__ import annotations

from enum import StrEnum
from functools import cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

__all__ = ["Environment", "LogFormat", "LogLevel", "Settings", "get_settings"]


class Environment(StrEnum):
    """Deployment environment the process runs in."""

    LOCAL = "local"
    TEST = "test"
    STAGING = "staging"
    PRODUCTION = "production"


class LogFormat(StrEnum):
    """Output format of the structured logs."""

    CONSOLE = "console"
    """Human-friendly, coloured output for local development."""
    JSON = "json"
    """One JSON object per line, for log aggregation in deployed environments."""


class LogLevel(StrEnum):
    """Minimum severity of the emitted log records."""

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class Settings(BaseSettings):
    """Core library settings.

    Attributes:
        environment: Environment the process runs in.
        log_level: Minimum log level.
        log_format: Log renderer. Defaults to JSON outside local development.
        data_dir: Root directory of the local market-data cache and exports.
    """

    model_config = SettingsConfigDict(
        env_prefix="INVESTINGLAB_",
        env_nested_delimiter="__",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )

    environment: Environment = Environment.LOCAL
    log_level: LogLevel = LogLevel.INFO
    log_format: LogFormat | None = None
    data_dir: Path = Path("data")

    @property
    def effective_log_format(self) -> LogFormat:
        """Log format to use: explicit value, or JSON everywhere except local development."""
        if self.log_format is not None:
            return self.log_format
        return LogFormat.CONSOLE if self.environment is Environment.LOCAL else LogFormat.JSON


@cache
def get_settings() -> Settings:
    """Return the process-wide settings, loaded once and cached.

    Tests that need different values should build ``Settings(...)`` explicitly or call
    ``get_settings.cache_clear()`` after patching the environment.
    """
    return Settings()
