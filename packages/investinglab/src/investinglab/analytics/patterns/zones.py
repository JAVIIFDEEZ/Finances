"""Fibonacci zones of the recent swing: discount and premium, as states (ADR-0035).

The indicator catalogue has the Fibonacci retracement as a level a close can cross
(``FIB_RETR``). These are the other half of the idea, as in CryptoWorld's strategy grammar:
being *within* the 0.618-0.786 band of the swing of the ``window`` bars before. A state,
true for as long as the price stays there, not an event.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

__all__ = ["fibonacci_discount", "fibonacci_premium"]


def _zone(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    window: int,
    *,
    lower: float,
    upper: float,
    discount: bool,
) -> pd.Series:
    if window < 1:
        raise ValueError(f"window must be at least 1, got {window}")
    if not 0 <= lower <= upper <= 1:
        raise ValueError(f"need 0 <= lower <= upper <= 1, got {lower} and {upper}")
    top = high.astype(float).rolling(window).max().shift(1).to_numpy()
    bottom = low.astype(float).rolling(window).min().shift(1).to_numpy()
    c = close.to_numpy(dtype=float)
    span = top - bottom
    with np.errstate(invalid="ignore", divide="ignore"):
        depth = ((top - c) if discount else (c - bottom)) / np.where(span > 0, span, np.nan)
        inside = (depth >= lower) & (depth <= upper)
    return pd.Series(np.isfinite(depth) & inside, index=close.index, dtype=bool)


def fibonacci_discount(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    window: int = 60,
    *,
    lower: float = 0.618,
    upper: float = 0.786,
) -> pd.Series:
    """The close has retraced ``lower``-``upper`` of the swing down from its high.

    The swing is the range of the ``window`` bars before (not counting this one, so that its
    own extreme is not the reference).

    Raises:
        ValueError: If ``window`` is below 1 or the band is not within [0, 1].
    """
    return _zone(high, low, close, window, lower=lower, upper=upper, discount=True)


def fibonacci_premium(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    window: int = 60,
    *,
    lower: float = 0.618,
    upper: float = 0.786,
) -> pd.Series:
    """Mirror of :func:`fibonacci_discount`, measured up from the swing's low.

    Raises:
        ValueError: If ``window`` is below 1 or the band is not within [0, 1].
    """
    return _zone(high, low, close, window, lower=lower, upper=upper, discount=False)
