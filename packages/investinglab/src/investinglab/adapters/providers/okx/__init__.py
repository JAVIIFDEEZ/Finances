"""OKX perpetual swaps: funding-rate history without an API key (ADR-0032)."""

from investinglab.adapters.providers.okx.provider import (
    BASE_URL,
    DATASET,
    MAX_PAGES,
    NAME,
    PAGE_SIZE,
    PERPETUAL,
    OkxProvider,
    explain_error,
    http_client,
    swap_id,
)

__all__ = [
    "BASE_URL",
    "DATASET",
    "MAX_PAGES",
    "NAME",
    "PAGE_SIZE",
    "PERPETUAL",
    "OkxProvider",
    "explain_error",
    "http_client",
    "swap_id",
]
