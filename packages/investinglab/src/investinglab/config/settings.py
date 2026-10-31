"""Runtime configuration loaded from environment variables and an optional ``.env`` file.

Every variable is prefixed with ``INVESTINGLAB_``; nested settings use ``__`` as delimiter.
Values are validated at start-up so that a misconfiguration fails fast with a clear error
instead of surfacing later as a confusing runtime failure.
"""

from __future__ import annotations

from enum import StrEnum
from functools import cache
from pathlib import Path

from pydantic import Field, SecretStr
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
        cache_dir: Market-data cache directory (defaults to ``<data_dir>/cache``).
        http_timeout_seconds: Timeout of every outbound HTTP request.
        http_max_attempts: Attempts per request, retries included, for transient errors.
        max_concurrency: Maximum number of series downloaded at the same time.
        fred_api_key: FRED/ALFRED API key (free at fred.stlouisfed.org).
        alphavantage_api_key: Alpha Vantage API key (free at alphavantage.co).
    """

    model_config = SettingsConfigDict(
        env_prefix="INVESTINGLAB_",
        env_nested_delimiter="__",
        env_file=".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
        frozen=True,
    )

    environment: Environment = Environment.LOCAL
    log_level: LogLevel = LogLevel.INFO
    log_format: LogFormat | None = None
    data_dir: Path = Path("data")
    cache_dir: Path | None = None
    http_timeout_seconds: float = Field(default=30.0, gt=0, le=300)
    http_max_attempts: int = Field(default=4, ge=1, le=10)
    max_concurrency: int = Field(default=8, ge=1, le=64)
    fred_api_key: SecretStr | None = None
    alphavantage_api_key: SecretStr | None = None

    @property
    def effective_cache_dir(self) -> Path:
        """Cache directory: the explicit ``cache_dir`` or ``<data_dir>/cache``."""
        return self.cache_dir if self.cache_dir is not None else self.data_dir / "cache"

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
