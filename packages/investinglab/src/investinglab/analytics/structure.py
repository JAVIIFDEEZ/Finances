"""Price structure: pivots, support and resistance levels, divergences and Fibonacci levels.

Definitions follow CryptoWorld (``price_structure`` and the Fibonacci levels of its
confluence card, ADR-0036), checked by the parity tests, and return data instead of
sentences:

* A **pivot** is a high (or a low) that strictly dominates the ``k`` bars on each side. It is
  only known ``k`` bars later, so the last ``k`` bars cannot be pivots yet; every function
  here says when a pivot was confirmed, never earlier.
* **Levels** group pivot prices within a tolerance; a level's strength is how many pivots
  touched it. Each level is a support or a resistance by its side of the last close.
* A **divergence** compares the last two pivots of the close with an oscillator (the RSI):
  a higher high with a lower oscillator is bearish, a lower low with a higher one bullish.
* The **Fibonacci levels** retrace the swing between the highest high and the lowest low of
  the recent bars, measured from whichever extreme came last.

Pure functions on pandas series and NumPy arrays, positions instead of dates: the domain
facade turns them into times.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal

import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view

__all__ = [
    "FIBONACCI_RATIOS",
    "Divergence",
    "Level",
    "Swing",
    "cluster_levels",
    "divergences",
    "fibonacci_swing",
    "pivots",
    "support_resistance",
]

FIBONACCI_RATIOS: Final = (0.236, 0.382, 0.5, 0.618, 0.786)
"""The retracement ratios drawn, as CryptoWorld's confluence card."""
_MIN_TOLERANCE_PCT: Final = 0.01


@dataclass(frozen=True, slots=True)
class Level:
    """A price where pivots cluster.

    Attributes:
        price: Mean price of the pivots in the cluster.
        touches: Pivots in it (the level's strength).
        positions: Bar positions of those pivots, in time order.
        kind: ``support`` below the last close, ``resistance`` at or above it.
        distance_pct: Distance from the last close, in percent of it.
    """

    price: float
    touches: int
    positions: tuple[int, ...]
    kind: Literal["support", "resistance"] = "support"
    distance_pct: float = 0.0


@dataclass(frozen=True, slots=True)
class Divergence:
    """The last two pivots of the close disagree with an oscillator.

    Attributes:
        kind: ``bearish`` (a higher high, a lower oscillator) or ``bullish`` (a lower low,
            a higher oscillator).
        first: Position of the earlier pivot.
        second: Position of the later pivot.
        confirmed: Position of the bar that confirmed the later pivot (``second + k``).
        price_first: Close at the earlier pivot.
        price_second: Close at the later pivot.
        oscillator_first: Oscillator at the earlier pivot.
        oscillator_second: Oscillator at the later pivot.
    """

    kind: Literal["bearish", "bullish"]
    first: int
    second: int
    confirmed: int
    price_first: float
    price_second: float
    oscillator_first: float
    oscillator_second: float


@dataclass(frozen=True, slots=True)
class Swing:
    """The recent swing and its Fibonacci retracement levels.

    Attributes:
        high: Highest high of the window.
        low: Lowest low of the window.
        high_at: Position of the (first) highest high.
        low_at: Position of the (first) lowest low.
        rising: Whether the low came before the high: the levels then retrace down from
            the high; otherwise up from the low.
        levels: Price of each ratio of :data:`FIBONACCI_RATIOS` (empty for a flat window).
    """

    high: float
    low: float
    high_at: int
    low_at: int
    rising: bool
    levels: tuple[tuple[float, float], ...]

    def nearest(self, price: float) -> tuple[float, float] | None:
        """The level closest to ``price`` (``None`` without levels)."""
        return min(self.levels, key=lambda level: abs(level[1] - price), default=None)


def _check_window(name: str, value: int) -> None:
    if value < 1:
        raise ValueError(f"{name} must be at least 1, got {value}")


def pivots(high: np.ndarray, low: np.ndarray, k: int = 3) -> tuple[np.ndarray, np.ndarray]:
    """Positions of the pivot highs and pivot lows confirmed by ``k`` bars on each side.

    A pivot high is strictly above the ``k`` highs before and after it (a tie confirms
    nothing, so flat stretches do not make a pivot of every bar); a pivot low, strictly
    below. A pivot at position ``i`` is only known at ``i + k``.

    Raises:
        ValueError: If ``k`` is below 1.
    """
    _check_window("k", k)
    h = np.asarray(high, dtype=float)
    lo = np.asarray(low, dtype=float)
    n = h.size
    if n < 2 * k + 1:
        empty = np.array([], dtype=int)
        return empty, empty
    centre = np.arange(k, n - k)
    windows_h = sliding_window_view(h, k)  # windows_h[j] = h[j : j + k]
    windows_lo = sliding_window_view(lo, k)
    around_h = np.maximum(windows_h[centre - k].max(axis=1), windows_h[centre + 1].max(axis=1))
    around_lo = np.minimum(windows_lo[centre - k].min(axis=1), windows_lo[centre + 1].min(axis=1))
    return centre[h[centre] > around_h], centre[lo[centre] < around_lo]


def cluster_levels(
    prices: np.ndarray, positions: np.ndarray, tolerance_pct: float = 0.6
) -> list[Level]:
    """Group pivot prices into levels, strongest first.

    In price order, a pivot joins the current level when it is within ``tolerance_pct``
    percent of the level's mean so far; otherwise it starts a new one. Levels with as many
    touches keep their price order.

    Args:
        prices: Pivot prices.
        positions: Bar position of each pivot.
        tolerance_pct: Tolerance in percent of the level (at least 0.01).
    """
    tolerance = max(tolerance_pct, _MIN_TOLERANCE_PCT) / 100.0
    clusters: list[list[tuple[float, int]]] = []
    for price, position in sorted(zip(map(float, prices), map(int, positions), strict=True)):
        if clusters:
            mean = float(np.mean([p for p, _ in clusters[-1]]))
            if abs(price - mean) <= mean * tolerance:
                clusters[-1].append((price, position))
                continue
        clusters.append([(price, position)])
    levels = [
        Level(
            price=float(np.mean([p for p, _ in cluster])),
            touches=len(cluster),
            positions=tuple(sorted(position for _, position in cluster)),
        )
        for cluster in clusters
    ]
    return sorted(levels, key=lambda level: -level.touches)


def support_resistance(
    high: pd.Series | np.ndarray,
    low: pd.Series | np.ndarray,
    close: pd.Series | np.ndarray,
    k: int = 3,
    *,
    tolerance_pct: float = 0.6,
    max_levels: int = 8,
) -> list[Level]:
    """The strongest support and resistance levels, closest first among equals.

    Levels come from the pivot highs and lows of the whole series; each is a support below
    the last close and a resistance at or above it. At most ``max_levels`` are kept, by
    touches and then by distance to the last close (to the hundredth of a percent, as
    CryptoWorld, so that near ties keep price order).

    Raises:
        ValueError: If ``k`` or ``max_levels`` is below 1.
    """
    _check_window("max_levels", max_levels)
    h, lo, c = (np.asarray(x, dtype=float) for x in (high, low, close))
    if c.size < 2 * k + 3:
        return []
    last = float(c[-1])
    tops, bottoms = pivots(h, lo, k)
    levels = cluster_levels(
        np.concatenate([h[tops], lo[bottoms]]), np.concatenate([tops, bottoms]), tolerance_pct
    )
    placed = [
        Level(
            level.price,
            level.touches,
            level.positions,
            "resistance" if level.price >= last else "support",
            (level.price / last - 1.0) * 100.0,
        )
        for level in levels
    ]
    placed.sort(key=lambda level: (-level.touches, round(abs(level.distance_pct), 2)))
    return placed[:max_levels]


def divergences(
    close: pd.Series | np.ndarray,
    oscillator: pd.Series | np.ndarray,
    k: int = 3,
    *,
    lookback: int = 60,
    min_gap: float = 1.0,
) -> list[Divergence]:
    """Divergences between the last two pivots of the close, within ``lookback`` bars.

    The oscillator must differ by ``min_gap`` at least (one RSI point by default), so that
    noise is not reported; pivots where it is undefined are not compared.

    Raises:
        ValueError: If ``k`` or ``lookback`` is below 1, or the series differ in length.
    """
    _check_window("lookback", lookback)
    c = np.asarray(close, dtype=float)
    osc = np.asarray(oscillator, dtype=float)
    if osc.size != c.size:
        raise ValueError(f"{osc.size} oscillator values for {c.size} closes")
    if c.size < 2 * k + 5:
        return []
    start = max(0, c.size - lookback)
    tops, bottoms = pivots(c, c, k)
    tops, bottoms = tops[tops >= start], bottoms[bottoms >= start]
    found: list[Divergence] = []
    for kind, pair in (("bearish", tops), ("bullish", bottoms)):
        if pair.size < 2:  # noqa: PLR2004 - two pivots to compare
            continue
        a, b = int(pair[-2]), int(pair[-1])
        if np.isnan(osc[a]) or np.isnan(osc[b]):
            continue
        if kind == "bearish":
            diverges = c[b] > c[a] and osc[a] - osc[b] >= min_gap
        else:
            diverges = c[b] < c[a] and osc[b] - osc[a] >= min_gap
        if diverges:
            found.append(
                Divergence(
                    kind,  # type: ignore[arg-type]
                    a,
                    b,
                    b + k,
                    float(c[a]),
                    float(c[b]),
                    float(osc[a]),
                    float(osc[b]),
                )
            )
    return found


def fibonacci_swing(
    high: pd.Series | np.ndarray,
    low: pd.Series | np.ndarray,
    lookback: int = 180,
    ratios: tuple[float, ...] = FIBONACCI_RATIOS,
) -> Swing | None:
    """The swing of the last ``lookback`` bars and its retracement levels.

    Returns:
        ``None`` for an empty series.

    Raises:
        ValueError: If ``lookback`` is below 1.
    """
    _check_window("lookback", lookback)
    h = np.asarray(high, dtype=float)
    lo = np.asarray(low, dtype=float)
    if h.size == 0:
        return None
    offset = max(0, h.size - lookback)
    window_h, window_lo = h[offset:], lo[offset:]
    high_at = offset + int(np.argmax(window_h))
    low_at = offset + int(np.argmin(window_lo))
    top, bottom = float(h[high_at]), float(lo[low_at])
    span = top - bottom
    rising = low_at < high_at
    levels: tuple[tuple[float, float], ...] = ()
    if span > 0:
        levels = tuple(
            (ratio, top - span * ratio if rising else bottom + span * ratio) for ratio in ratios
        )
    return Swing(top, bottom, high_at, low_at, rising, levels)
