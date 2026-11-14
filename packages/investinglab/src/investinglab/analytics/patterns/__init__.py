"""Price patterns as causal flags, on any price series (ADR-0035).

Pure functions on pandas series, without domain types or I/O: Japanese candles
(:mod:`~investinglab.analytics.patterns.candles`), structure and liquidity
(:mod:`~investinglab.analytics.patterns.liquidity`), session openings
(:mod:`~investinglab.analytics.patterns.sessions`) and Fibonacci zones
(:mod:`~investinglab.analytics.patterns.zones`). Every flag is set on the bar that completes
the pattern and depends on no later bar. :mod:`~investinglab.analytics.patterns.catalogue`
names them as CryptoWorld's strategy grammar does.
"""

from __future__ import annotations

from investinglab.analytics.patterns.catalogue import (
    MIRRORS,
    PATTERNS,
    Direction,
    Family,
    Pattern,
    detect,
    occurred_within,
)

__all__ = ["MIRRORS", "PATTERNS", "Direction", "Family", "Pattern", "detect", "occurred_within"]
