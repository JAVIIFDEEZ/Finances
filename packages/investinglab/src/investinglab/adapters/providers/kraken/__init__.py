"""Kraken spot market: recent bars and their volume without an API key (ADR-0032)."""

from investinglab.adapters.providers.kraken.provider import (
    BASE_URL,
    DATASET,
    LOOKBACK_BARS,
    NAME,
    KrakenProvider,
    http_client,
)

__all__ = ["BASE_URL", "DATASET", "LOOKBACK_BARS", "NAME", "KrakenProvider", "http_client"]
