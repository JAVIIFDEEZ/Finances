"""Deribit perpetual swaps: hourly funding without an API key (ADR-0032)."""

from investinglab.adapters.providers.deribit.provider import (
    BASE_URL,
    DATASET,
    INTERVAL,
    MAX_WINDOWS,
    NAME,
    PARALLEL,
    PERPETUAL,
    WINDOW,
    DeribitProvider,
    explain_error,
    http_client,
    swap_id,
    swap_instrument,
)

__all__ = [
    "BASE_URL",
    "DATASET",
    "INTERVAL",
    "MAX_WINDOWS",
    "NAME",
    "PARALLEL",
    "PERPETUAL",
    "WINDOW",
    "DeribitProvider",
    "explain_error",
    "http_client",
    "swap_id",
    "swap_instrument",
]
