"""API settings, read from ``INVESTINGLAB_API_*`` environment variables.

The core library keeps its own settings (``INVESTINGLAB_*``: data folders, providers, HTTP
timeouts); these only describe the HTTP service and the limits that protect it.
"""

from __future__ import annotations

from functools import cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

__all__ = ["ApiSettings", "get_api_settings"]


class ApiSettings(BaseSettings):
    """Configuration of the HTTP service.

    Attributes:
        host: Interface to listen on (``127.0.0.1``: this machine only).
        port: TCP port.
        cors_origins: Origins allowed to call the API from a browser (the web app).
        max_symbols: Most instruments in one request (comparisons, portfolios).
        max_paths: Most Monte Carlo paths in one simulation or savings plan.
        max_horizon: Longest simulation horizon, in periods.
        max_frontier_points: Most points of an efficient frontier.
    """

    model_config = SettingsConfigDict(
        env_prefix="INVESTINGLAB_API_",
        env_file=".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
        frozen=True,
    )

    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65_535)
    cors_origins: tuple[str, ...] = ("http://localhost:3000", "http://127.0.0.1:3000")
    max_symbols: int = Field(default=25, ge=1, le=200)
    max_paths: int = Field(default=20_000, ge=100, le=200_000)
    max_horizon: int = Field(default=2_520, ge=1, le=25_200)
    max_frontier_points: int = Field(default=60, ge=2, le=200)


@cache
def get_api_settings() -> ApiSettings:
    """The process-wide API settings, loaded once."""
    return ApiSettings()
