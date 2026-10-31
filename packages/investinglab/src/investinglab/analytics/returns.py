"""Return calculations on price series.

Every function works on the calendar of its input: a return is always measured between
two *observed* prices. Missing observations are never filled; in a DataFrame each column is
processed on its own observed dates, so a return spanning a holiday is attributed to the next
observed date instead of producing an artificial 0 % return.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

__all__ = [
    "cumulative_returns",
    "log_returns",
    "simple_returns",
    "total_return",
]


def _per_column(frame: pd.DataFrame, func: object) -> pd.DataFrame:
    columns = {name: func(frame[name]) for name in frame.columns}  # type: ignore[operator]
    if not columns:
        return pd.DataFrame(index=frame.index[:0], columns=frame.columns, dtype="float64")
    return pd.DataFrame(columns).reindex(columns=frame.columns)


def simple_returns[T: (pd.Series, pd.DataFrame)](prices: T) -> T:
    """Simple returns ``p_t / p_{t-1} - 1`` between consecutive observed prices.

    Args:
        prices: Strictly positive prices indexed by time. NaN values are treated as
            "not observed" and skipped (each column independently for a DataFrame).

    Returns:
        Returns indexed by the date of the *second* price of each pair. The first observation
        has no return and is dropped.
    """
    if isinstance(prices, pd.DataFrame):
        return _per_column(prices, simple_returns)
    observed = prices.dropna()
    result = observed / observed.shift(1) - 1.0
    return result.iloc[1:]


def log_returns[T: (pd.Series, pd.DataFrame)](prices: T) -> T:
    """Logarithmic returns ``ln(p_t / p_{t-1})`` between consecutive observed prices.

    Log returns are additive over time: their sum equals ``ln(p_last / p_first)``.
    """
    if isinstance(prices, pd.DataFrame):
        return _per_column(prices, log_returns)
    observed = prices.dropna()
    ratio = (observed / observed.shift(1)).iloc[1:]
    return pd.Series(np.log(ratio.to_numpy()), index=ratio.index, name=ratio.name)


def cumulative_returns(returns: pd.Series) -> pd.Series:
    """Compound simple returns into cumulative returns: ``prod(1 + r) - 1``."""
    return (1.0 + returns).cumprod() - 1.0


def total_return(prices: pd.Series) -> float:
    """Total simple return from the first to the last observed price."""
    observed = prices.dropna()
    if len(observed) < 2:  # noqa: PLR2004 - a return needs two prices
        return float("nan")
    return float(observed.iloc[-1] / observed.iloc[0] - 1.0)
