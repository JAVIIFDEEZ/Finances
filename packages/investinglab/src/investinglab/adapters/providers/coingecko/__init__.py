"""CoinGecko: snapshots of the crypto market, its dominance and its ranking."""

from investinglab.adapters.providers.coingecko.provider import (
    BASE_URL,
    KEY_HEADER,
    MAX_TOP,
    NAME,
    CoinGeckoProvider,
    http_client,
)

__all__ = ["BASE_URL", "KEY_HEADER", "MAX_TOP", "NAME", "CoinGeckoProvider", "http_client"]
