"""Drawdown analytics: the loss from the running peak."""

from __future__ import annotations

import numpy as np
import pandas as pd

__all__ = ["drawdown", "drawdown_episodes", "max_drawdown"]

_EPISODE_COLUMNS = (
    "peak",
    "trough",
    "recovery",
    "depth",
    "decline_periods",
    "recovery_periods",
    "duration_periods",
)


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


def drawdown_episodes(prices: pd.Series, *, top: int | None = None) -> pd.DataFrame:
    """Peak-to-recovery episodes of a price or value series, deepest first.

    An episode starts at a running peak, reaches its trough and ends when the series climbs
    back to that peak (the recovery). The last episode may still be open. Durations are
    counted in observations (periods of the series' frequency).

    Args:
        prices: Prices or portfolio values; NaN values are skipped.
        top: Keep only the ``top`` deepest episodes.

    Returns:
        One row per episode with columns ``peak``, ``trough``, ``recovery`` (``NaT`` while
        open), ``depth`` (negative fraction), ``decline_periods`` (peak to trough),
        ``recovery_periods`` (trough to recovery, NaN while open) and ``duration_periods``
        (peak to recovery, or to the last observation while open).

    Raises:
        ValueError: If ``top`` is smaller than 1.
    """
    if top is not None and top < 1:
        raise ValueError("top must be at least 1")
    observed = prices.dropna()
    values = (observed / observed.cummax() - 1.0).to_numpy(dtype="float64")
    index = observed.index
    underwater = np.concatenate([[False], values < 0.0, [False]])
    edges = np.flatnonzero(np.diff(underwater.astype(np.int8)))
    rows = []
    for first, stop in zip(edges[0::2], edges[1::2], strict=True):
        # ``first`` > 0 always: the first observation is its own running peak.
        trough = first + int(np.argmin(values[first:stop]))
        recovered = stop < len(values)
        end = stop if recovered else len(values) - 1
        rows.append(
            {
                "peak": index[first - 1],
                "trough": index[trough],
                "recovery": index[stop] if recovered else pd.NaT,
                "depth": float(values[trough]),
                "decline_periods": trough - (first - 1),
                "recovery_periods": float(stop - trough) if recovered else float("nan"),
                "duration_periods": end - (first - 1),
            }
        )
    episodes = pd.DataFrame(rows, columns=list(_EPISODE_COLUMNS))
    episodes = episodes.sort_values("depth", kind="stable").reset_index(drop=True)
    return episodes if top is None else episodes.head(top)
