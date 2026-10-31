"""Drawdown analytics: the loss from the running peak."""

from __future__ import annotations

import pandas as pd

__all__ = ["drawdown", "max_drawdown"]


def drawdown(prices: pd.Series) -> pd.Series:
    """Drawdown at each date, ``p_t / max(p_0..p_t) - 1``.

    Values are in ``[-1, 0]``: ``0`` at a new high, ``-0.25`` when 25 % below the running peak.
    Unobserved (NaN) prices are skipped.
    """
    observed = prices.dropna()
    return observed / observed.cummax() - 1.0


def max_drawdown(prices: pd.Series) -> float:
    """Worst drawdown over the whole series (a non-positive number, ``nan`` if empty)."""
    values = drawdown(prices)
    if values.empty:
        return float("nan")
    return float(values.min())
