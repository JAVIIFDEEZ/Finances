"""Session patterns: the opening range breakout (ORB), on the market's own sessions.

CryptoWorld cut its days at midnight UTC, a convention that marks no opening in a market
that never closes. Here the caller says which session each bar belongs to: the trading
date in the market's timezone for an exchange (so the opening range is the first bars after
the real opening), and the UTC date for markets open around the clock, which reproduces
CryptoWorld's values (ADR-0035).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

if TYPE_CHECKING:
    from collections.abc import Hashable, Sequence

__all__ = ["opening_range_breakdown", "opening_range_breakout"]


def _opening_range(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    sessions: Sequence[Hashable],
    bars: int,
    *,
    up: bool,
) -> pd.Series:
    if bars < 1:
        raise ValueError(f"bars must be at least 1, got {bars}")
    if len(sessions) != len(close):
        raise ValueError(f"{len(sessions)} session labels for {len(close)} bars")
    h, lo, c = (s.to_numpy(dtype=float) for s in (high, low, close))
    out = np.zeros(c.size, dtype=bool)
    first, fired = 0, False
    for i in range(c.size):
        if i == 0 or sessions[i] != sessions[i - 1]:
            first, fired = i, False
        if i - first < bars or fired:
            continue
        if (
            (c[i] > h[first : first + bars].max())
            if up
            else (c[i] < lo[first : first + bars].min())
        ):
            out[i] = fired = True
    return pd.Series(out, index=close.index, dtype=bool)


def opening_range_breakout(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    sessions: Sequence[Hashable],
    bars: int = 6,
) -> pd.Series:
    """The first close of each session above the high of its first ``bars`` bars.

    Only the first such close counts: ten breakouts in one session are a trend already under
    way. A series that starts mid-session takes its first bar as that session's opening; it
    only looks back, so it is no leak, but that session differs from the same session in a
    longer series.

    Args:
        high: Highs of the bars.
        low: Lows of the bars.
        close: Closes of the bars.
        sessions: The session of each bar (consecutive bars with equal labels share one).
        bars: Bars of the opening range.

    Raises:
        ValueError: If ``bars`` is below 1 or there is not one session label per bar.
    """
    return _opening_range(high, low, close, sessions, bars, up=True)


def opening_range_breakdown(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    sessions: Sequence[Hashable],
    bars: int = 6,
) -> pd.Series:
    """Mirror of :func:`opening_range_breakout`: the first close below the range's low.

    Raises:
        ValueError: If ``bars`` is below 1 or there is not one session label per bar.
    """
    return _opening_range(high, low, close, sessions, bars, up=False)
