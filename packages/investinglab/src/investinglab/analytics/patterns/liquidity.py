"""Structure and liquidity patterns as causal flags: FVG, sweeps, order blocks, CRT, PO3.

Concepts of modern price action, implemented by their mechanical definition as in
CryptoWorld's strategy grammar (``price_patterns``, ADR-0035), with no claim about why they
would work. Every flag is set on the bar that completes the pattern and only looks back: a
pattern that is drawn on an earlier bar (a gap between the first and the third bar of an
impulse) is flagged when the last bar that defines it closes.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

__all__ = [
    "bearish_fair_value_gap",
    "bearish_order_block",
    "bearish_power_of_three",
    "bullish_fair_value_gap",
    "bullish_order_block",
    "bullish_power_of_three",
    "candle_range_theory",
    "high_sweep",
    "low_sweep",
]

_BLOCK_MEMORY = 20
"""Unmitigated order blocks remembered: the most recent ones."""
_COMPRESSION = 0.6
"""The accumulation phase spans less than this share of the whole window's range."""


def _float(series: pd.Series) -> np.ndarray:
    return series.to_numpy(dtype=float)


def _before(values: np.ndarray, bars: int = 1) -> np.ndarray:
    out = np.full(values.shape, np.nan)
    if bars < values.size:
        out[bars:] = values[: values.size - bars]
    return out


def _flags(values: np.ndarray, like: pd.Series) -> pd.Series:
    return pd.Series(values, index=like.index, dtype=bool)


def _check_window(name: str, value: int) -> None:
    if value < 1:
        raise ValueError(f"{name} must be at least 1, got {value}")


def _extreme(values: pd.Series, window: int, shift: int, *, highest: bool) -> np.ndarray:
    """Highest (or lowest) of ``window`` bars ending ``shift`` bars before each bar."""
    rolling = values.astype(float).rolling(window)
    return (rolling.max() if highest else rolling.min()).shift(shift).to_numpy()


def bullish_fair_value_gap(high: pd.Series, low: pd.Series) -> pd.Series:
    """A price range nobody traded in a three-bar rise: the low above the high two bars back.

    Flagged on the third bar, the one that leaves the gap; flagging the middle bar, where it
    is usually drawn, would need the bar after it.
    """
    with np.errstate(invalid="ignore"):
        return _flags(_float(low) > _before(_float(high), 2), high)


def bearish_fair_value_gap(high: pd.Series, low: pd.Series) -> pd.Series:
    """Mirror of :func:`bullish_fair_value_gap`: the high below the low two bars back."""
    with np.errstate(invalid="ignore"):
        return _flags(_float(high) < _before(_float(low), 2), high)


def low_sweep(high: pd.Series, low: pd.Series, close: pd.Series, window: int = 20) -> pd.Series:
    """The bar breaks the lowest low of the ``window`` bars before and closes above it.

    The close back above is what tells a sweep (the price takes the orders below and does
    not stay) from a breakdown, its opposite.

    Raises:
        ValueError: If ``window`` is below 1.
    """
    _check_window("window", window)
    floor = _extreme(low, window, 1, highest=False)
    with np.errstate(invalid="ignore"):
        swept = (_float(low) < floor) & (_float(close) > floor)
    return _flags(swept & ~np.isnan(floor), close)


def high_sweep(high: pd.Series, low: pd.Series, close: pd.Series, window: int = 20) -> pd.Series:
    """Mirror of :func:`low_sweep`: above the highest high, then a close below it.

    Raises:
        ValueError: If ``window`` is below 1.
    """
    _check_window("window", window)
    ceiling = _extreme(high, window, 1, highest=True)
    with np.errstate(invalid="ignore"):
        swept = (_float(high) > ceiling) & (_float(close) < ceiling)
    return _flags(swept & ~np.isnan(ceiling), close)


def _order_block(
    open_: pd.Series,
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    impulse: int,
    *,
    bullish: bool,
) -> pd.Series:
    _check_window("impulse", impulse)
    o, h, lo, c = _float(open_), _float(high), _float(low), _float(close)
    n = c.size
    out = np.zeros(n, dtype=bool)
    # CryptoWorld returned no flags for series shorter than impulse + 2 bars, which hid a
    # block touched on the last bar of a series of impulse + 1: the flag depended on the
    # bars after it. Without the guard, a short series simply has no block yet.
    blocks: list[tuple[float, float]] = []
    for i in range(n):
        k = i - impulse
        if k >= 0 and (
            (bullish and c[k] < o[k] and np.max(h[k + 1 : i + 1]) > h[k])
            or (not bullish and c[k] > o[k] and np.min(lo[k + 1 : i + 1]) < lo[k])
        ):
            blocks.append((float(lo[k]), float(h[k])))
        remaining = []
        for bottom, top in blocks:
            touched = (
                (lo[i] <= top and c[i] >= bottom) if bullish else (h[i] >= bottom and c[i] <= top)
            )
            out[i] |= touched
            if not touched:
                remaining.append((bottom, top))
        blocks = remaining[-_BLOCK_MEMORY:]
    return _flags(out, close)


def bullish_order_block(
    open_: pd.Series, high: pd.Series, low: pd.Series, close: pd.Series, impulse: int = 3
) -> pd.Series:
    """The price comes back to a bullish order block: flagged on the bar that touches it.

    A falling bar becomes a block once one of the ``impulse`` bars after it breaks its
    high; only from then on can it be touched (a low at or below its high and a close at or
    above its low). A touched block is spent; the 20 most recent untouched ones are kept.
    Flagging the block's own bar would need the bars after it.

    Raises:
        ValueError: If ``impulse`` is below 1.
    """
    return _order_block(open_, high, low, close, impulse, bullish=True)


def bearish_order_block(
    open_: pd.Series, high: pd.Series, low: pd.Series, close: pd.Series, impulse: int = 3
) -> pd.Series:
    """Mirror of :func:`bullish_order_block`: a rising bar whose low is broken afterwards.

    Raises:
        ValueError: If ``impulse`` is below 1.
    """
    return _order_block(open_, high, low, close, impulse, bullish=False)


def candle_range_theory(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    """The bar takes the high or the low of the bar before and closes back inside its range.

    The same shape as a sweep, with the bar before as the reference instead of a window.
    """
    h, lo, c = _float(high), _float(low), _float(close)
    h1, lo1 = _before(h), _before(lo)
    with np.errstate(invalid="ignore"):
        return _flags(((h > h1) | (lo < lo1)) & (c <= h1) & (c >= lo1), close)


def _power_of_three(
    high: pd.Series, low: pd.Series, close: pd.Series, window: int, *, bullish: bool
) -> pd.Series:
    _check_window("window", window)
    c = _float(close)
    third = max(1, window // 3)
    middle = window - third
    if c.size < window + 1 or middle < 1:
        return _flags(np.zeros(c.size, dtype=bool), close)
    early_high = _extreme(high, third, window - third + 1, highest=True)
    early_low = _extreme(low, third, window - third + 1, highest=False)
    whole = _extreme(high, window, 1, highest=True) - _extreme(low, window, 1, highest=False)
    middle_high = _extreme(high, middle, 1, highest=True)
    middle_low = _extreme(low, middle, 1, highest=False)
    with np.errstate(invalid="ignore"):
        compressed = (whole > 0) & ((early_high - early_low) < whole * _COMPRESSION)
        if bullish:
            phases = (middle_low < early_low) & (c > early_high)
        else:
            phases = (middle_high > early_high) & (c < early_low)
    known = (
        np.isfinite(early_high)
        & np.isfinite(early_low)
        & np.isfinite(middle_high)
        & np.isfinite(middle_low)
        & np.isfinite(whole)
    )
    return _flags(known & compressed & phases, close)


def bullish_power_of_three(
    high: pd.Series, low: pd.Series, close: pd.Series, window: int = 6
) -> pd.Series:
    """Accumulation, manipulation and distribution (AMD) over the ``window`` bars before.

    The first third of the window is compressed (its range under 60 % of the window's), the
    rest breaks below that third's low, and the bar closes above its high: the opposite way.

    Raises:
        ValueError: If ``window`` is below 1.
    """
    return _power_of_three(high, low, close, window, bullish=True)


def bearish_power_of_three(
    high: pd.Series, low: pd.Series, close: pd.Series, window: int = 6
) -> pd.Series:
    """Mirror of :func:`bullish_power_of_three`: up in the manipulation, down in the end.

    Raises:
        ValueError: If ``window`` is below 1.
    """
    return _power_of_three(high, low, close, window, bullish=False)
