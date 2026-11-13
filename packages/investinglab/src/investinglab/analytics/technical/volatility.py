"""Volatility and channels: true range, ATR, Bollinger, Keltner and Donchian (ADR-0034).

Definitions follow the ``ta`` library CryptoWorld used; where ``ta`` fills the warm-up with
zeros or partial windows, the values here are ``NaN``. Every function is causal.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

__all__ = ["atr", "bollinger", "donchian", "keltner", "true_range"]


def _check_window(window: int) -> None:
    if window < 1:
        raise ValueError(f"window must be at least 1, got {window}")


def true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    """The bar's range extended to the previous close; the first bar's own range."""
    previous = close.shift(1)
    spans = pd.concat([high - low, (high - previous).abs(), (low - previous).abs()], axis=1)
    return spans.max(axis=1)


def atr(high: pd.Series, low: pd.Series, close: pd.Series, window: int = 14) -> pd.Series:
    """Average true range with Wilder's smoothing, from the mean of the first ``window`` bars.

    Raises:
        ValueError: If ``window`` is below 1.
    """
    _check_window(window)
    ranges = true_range(high, low, close).to_numpy(dtype=float)
    out = np.full(len(ranges), np.nan)
    if len(ranges) >= window:
        out[window - 1] = ranges[:window].mean()
        for i in range(window, len(ranges)):
            out[i] = (out[i - 1] * (window - 1) + ranges[i]) / window
    return pd.Series(out, index=close.index)


def bollinger(close: pd.Series, window: int = 20, deviations: float = 2.0) -> pd.DataFrame:
    """Bollinger bands: the moving average and ``deviations`` population deviations around it.

    Returns:
        Columns ``middle``, ``upper``, ``lower``, ``percent_b`` (where the close sits, 0 at
        the lower band and 1 at the upper one) and ``bandwidth`` (band width over the middle).

    Raises:
        ValueError: If ``window`` is below 1.
    """
    _check_window(window)
    middle = close.rolling(window, min_periods=window).mean()
    spread = deviations * close.rolling(window, min_periods=window).std(ddof=0)
    upper, lower = middle + spread, middle - spread
    width = (upper - lower).replace(0.0, np.nan)
    return pd.DataFrame(
        {
            "middle": middle,
            "upper": upper,
            "lower": lower,
            "percent_b": (close - lower) / width,
            "bandwidth": (upper - lower) / middle,
        }
    )


def keltner(high: pd.Series, low: pd.Series, close: pd.Series, window: int = 20) -> pd.DataFrame:
    """Keltner's original channel: averages of the typical price and of two shifted prices.

    The middle line averages ``(high + low + close) / 3``; the bands average
    ``(4 high - 2 low + close) / 3`` and ``(-2 high + 4 low + close) / 3`` over the same
    ``window`` (``ta``'s ``original_version``).

    Returns:
        Columns ``middle``, ``upper`` and ``lower``.

    Raises:
        ValueError: If ``window`` is below 1.
    """
    _check_window(window)

    def average(values: pd.Series) -> pd.Series:
        return values.rolling(window, min_periods=window).mean()

    return pd.DataFrame(
        {
            "middle": average((high + low + close) / 3.0),
            "upper": average((4.0 * high - 2.0 * low + close) / 3.0),
            "lower": average((-2.0 * high + 4.0 * low + close) / 3.0),
        }
    )


def donchian(high: pd.Series, low: pd.Series, window: int = 20) -> pd.DataFrame:
    """Donchian channel: the highest high and lowest low of the last ``window`` bars.

    The channel includes the current bar; a breakout compares the close with the channel of
    the bar before (shift it by one).

    Returns:
        Columns ``upper``, ``lower`` and ``middle``.

    Raises:
        ValueError: If ``window`` is below 1.
    """
    _check_window(window)
    upper = high.rolling(window, min_periods=window).max()
    lower = low.rolling(window, min_periods=window).min()
    return pd.DataFrame({"upper": upper, "lower": lower, "middle": (upper + lower) / 2.0})
