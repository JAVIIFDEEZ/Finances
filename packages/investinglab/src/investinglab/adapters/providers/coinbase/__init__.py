"""Coinbase Exchange: price bars and volume of its spot pairs without an API key (ADR-0032)."""

from investinglab.adapters.providers.coinbase.provider import (
    BASE_URL,
    DATASET,
    MAX_PAGES,
    NAME,
    PAGE_SIZE,
    CoinbaseProvider,
    http_client,
)

__all__ = [
    "BASE_URL",
    "DATASET",
    "MAX_PAGES",
    "NAME",
    "PAGE_SIZE",
    "CoinbaseProvider",
    "http_client",
]
