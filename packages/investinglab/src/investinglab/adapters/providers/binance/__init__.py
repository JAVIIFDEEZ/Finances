"""Binance spot market: price bars and trade flow without an API key (ADR-0032)."""

from investinglab.adapters.providers.binance.provider import (
    BASE_URL,
    DATASET,
    MAX_PAGES,
    NAME,
    PAGE_SIZE,
    PAIR,
    BinanceProvider,
    explain_error,
    http_client,
    split_pair,
)

__all__ = [
    "BASE_URL",
    "DATASET",
    "MAX_PAGES",
    "NAME",
    "PAGE_SIZE",
    "PAIR",
    "BinanceProvider",
    "explain_error",
    "http_client",
    "split_pair",
]
