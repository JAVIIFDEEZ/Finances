"""alternative.me: the crypto Fear & Greed Index without an API key."""

from investinglab.adapters.providers.alternative_me.provider import (
    BASE_URL,
    DATASET,
    FEAR_GREED,
    NAME,
    AlternativeMeProvider,
    http_client,
)

__all__ = ["BASE_URL", "DATASET", "FEAR_GREED", "NAME", "AlternativeMeProvider", "http_client"]
