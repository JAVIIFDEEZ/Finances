"""Detectors of suspicious data in price series. They flag; they never modify data.

Every detector returns *where* something looks wrong. Deciding whether it is a data error
(bad tick, unadjusted split, frozen feed) or a genuine market event (crash, halt) is left to
the analyst: nothing is removed automatically (ADR-0015).
"""

from __future__ import annotations

from typing import Final

import numpy as np
import pandas as pd

__all__ = [
    "SPLIT_FACTORS",
    "missing_sessions",
    "ohlc_violations",
    "robust_zscores",
    "split_like_jumps",
    "stale_runs",
    "unexpected_sessions",
]

_MAD_TO_STD: Final = 1.4826
"""MAD of a normal distribution times this constant estimates its standard deviation."""
_MEAN_AD_TO_STD: Final = 1.2533
"""Mean absolute deviation of a normal distribution times this estimates its std."""

SPLIT_FACTORS: Final = (2.0, 3.0, 4.0, 5.0, 8.0, 10.0, 20.0, 25.0, 50.0, 100.0)
"""Common split (and reverse-split) ratios."""


def robust_zscores(values: pd.Series) -> pd.Series:
    """Distance to the median in robust standard deviations (median absolute deviation).

    Unlike the classic z-score, a few extreme values cannot hide themselves by inflating
    the scale. When more than half of the values are identical (MAD = 0, e.g. an illiquid
    asset with many unchanged closes) the mean absolute deviation is used instead.
    """
    clean = values.dropna()
    if clean.empty:
        return clean.astype("float64")
    median = float(clean.median())
    deviations = (clean - median).abs()
    scale = float(deviations.median()) * _MAD_TO_STD
    if scale == 0.0:
        scale = float(deviations.mean()) * _MEAN_AD_TO_STD
    if scale == 0.0:
        return pd.Series(0.0, index=clean.index)
    return (clean - median) / scale


def split_like_jumps(
    prices: pd.Series,
    *,
    factors: tuple[float, ...] = SPLIT_FACTORS,
    tolerance: float = 0.02,
) -> pd.Series:
    """Price moves whose ratio matches a typical split or reverse split.

    Returns:
        For each flagged date, the observed price ratio ``p_t / p_{t-1}`` (``0.25``
        looks like a 4:1 split, ``10`` like a 1:10 reverse split).
    """
    observed = prices.dropna()
    ratios = (observed / observed.shift(1)).iloc[1:]
    candidates = np.array([1.0 / f for f in factors] + list(factors))
    relative = np.abs(ratios.to_numpy()[:, None] / candidates[None, :] - 1.0)
    matched = (relative <= tolerance).any(axis=1)
    flagged: pd.Series = ratios.loc[matched]
    return flagged


def stale_runs(
    prices: pd.Series, *, min_length: int = 5
) -> list[tuple[pd.Timestamp, pd.Timestamp, int]]:
    """Runs of at least ``min_length`` consecutive identical prices (a frozen feed?).

    Returns:
        ``(first, last, length)`` of each run, in time order.
    """
    observed = prices.dropna()
    if observed.empty:
        return []
    run_ids = (observed != observed.shift(1)).cumsum()
    runs = []
    for _, run in observed.groupby(run_ids.to_numpy(), sort=False):
        if len(run) >= min_length:
            runs.append((pd.Timestamp(run.index[0]), pd.Timestamp(run.index[-1]), len(run)))
    return runs


def ohlc_violations(bars: pd.DataFrame) -> pd.DatetimeIndex:
    """Dates where high/low are inconsistent with open/close (or with each other)."""
    if "high" not in bars.columns or "low" not in bars.columns:
        return pd.DatetimeIndex([])
    body = [c for c in ("open", "close") if c in bars.columns]
    high, low = bars["high"], bars["low"]
    bad = high < low
    if body:
        bad |= high < bars[body].max(axis=1)
        bad |= low > bars[body].min(axis=1)
    return pd.DatetimeIndex(bars.index[bad.to_numpy()])


def missing_sessions(observed: pd.DatetimeIndex, expected: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """Expected sessions within the observed range that have no observation."""
    if observed.empty:
        return pd.DatetimeIndex([])
    window = expected[(expected >= observed.min()) & (expected <= observed.max())]
    return pd.DatetimeIndex(window.difference(observed))


def unexpected_sessions(observed: pd.DatetimeIndex, expected: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """Observations on dates that are not sessions of the market (holidays, weekends)."""
    return pd.DatetimeIndex(observed.difference(expected))
