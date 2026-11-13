"""Momentum oscillators: RSI, stochastics, Williams %R, CCI, ROC, TRIX, MACD and Aroon.

Definitions follow the ``ta`` library CryptoWorld used (ADR-0034), so a strategy behaves the
same on both platforms; values that ``ta`` fills in during warm-up are ``NaN`` here. Every
function is causal and returns a series (or a frame) on the index of its input.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view

from investinglab.analytics.technical.averages import ema

__all__ = [
    "aroon",
    "cci",
    "macd",
    "roc",
    "rsi",
    "stoch_rsi",
    "stochastic",
    "trix",
    "williams_r",
]


def _check_window(window: int) -> None:
    if window < 1:
        raise ValueError(f"window must be at least 1, got {window}")


def rsi(close: pd.Series, window: int = 14) -> pd.Series:
    """Relative strength index (0-100) with Wilder's smoothing of gains and losses.

    Gains and losses are smoothed with ``alpha = 1 / window`` from the first change. A
    window without losses reads 100, as in ``ta``.

    Raises:
        ValueError: If ``window`` is below 1.
    """
    _check_window(window)
    change = close.diff()
    gains = change.where(change > 0, 0.0)
    losses = -change.where(change < 0, 0.0)
    up = gains.ewm(alpha=1 / window, min_periods=window, adjust=False).mean()
    down = losses.ewm(alpha=1 / window, min_periods=window, adjust=False).mean()
    with np.errstate(divide="ignore", invalid="ignore"):
        value = np.where(down == 0, 100.0, 100.0 - 100.0 / (1.0 + up / down))
    return pd.Series(value, index=close.index).where(down.notna())


def stoch_rsi(close: pd.Series, window: int = 14) -> pd.Series:
    """Stochastic RSI (0-1): where the RSI sits in its range over the last ``window`` values.

    Undefined (``NaN``) while the RSI does not move in the window.

    Raises:
        ValueError: If ``window`` is below 1.
    """
    strength = rsi(close, window)
    lowest = strength.rolling(window, min_periods=window).min()
    highest = strength.rolling(window, min_periods=window).max()
    span = (highest - lowest).replace(0.0, np.nan)
    return (strength - lowest) / span


def stochastic(high: pd.Series, low: pd.Series, close: pd.Series, window: int = 14) -> pd.Series:
    """Stochastic %K (0-100): the close within the high-low range of ``window`` bars.

    Raises:
        ValueError: If ``window`` is below 1.
    """
    _check_window(window)
    lowest = low.rolling(window, min_periods=window).min()
    highest = high.rolling(window, min_periods=window).max()
    return 100.0 * (close - lowest) / (highest - lowest).replace(0.0, np.nan)


def williams_r(high: pd.Series, low: pd.Series, close: pd.Series, window: int = 14) -> pd.Series:
    """Williams %R (-100-0): how far the close is below the high of ``window`` bars.

    Raises:
        ValueError: If ``window`` is below 1.
    """
    _check_window(window)
    highest = high.rolling(window, min_periods=window).max()
    lowest = low.rolling(window, min_periods=window).min()
    return -100.0 * (highest - close) / (highest - lowest).replace(0.0, np.nan)


def cci(
    high: pd.Series, low: pd.Series, close: pd.Series, window: int = 20, constant: float = 0.015
) -> pd.Series:
    """Commodity channel index: typical price against its mean, in mean absolute deviations.

    Raises:
        ValueError: If ``window`` is below 1.
    """
    _check_window(window)
    typical = (high + low + close) / 3.0
    data = typical.to_numpy(dtype=float)
    deviation = np.full(len(data), np.nan)
    if len(data) >= window:
        windows = sliding_window_view(data, window)
        centred = windows - windows.mean(axis=1, keepdims=True)
        deviation[window - 1 :] = np.abs(centred).mean(axis=1)
    mean = typical.rolling(window, min_periods=window).mean()
    scale = pd.Series(constant * deviation, index=typical.index).replace(0.0, np.nan)
    return (typical - mean) / scale


def roc(close: pd.Series, window: int = 12) -> pd.Series:
    """Rate of change (%) over ``window`` bars.

    Raises:
        ValueError: If ``window`` is below 1.
    """
    _check_window(window)
    before = close.shift(window)
    return (close - before) / before * 100.0


def trix(close: pd.Series, window: int = 15) -> pd.Series:
    """TRIX (%): the one-bar change of a triple exponential average of the close.

    Raises:
        ValueError: If ``window`` is below 1.
    """
    triple = ema(ema(ema(close, window), window), window)
    previous = triple.shift(1)
    return (triple - previous) / previous * 100.0


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    """MACD line (fast EMA minus slow EMA), its signal (EMA of the line) and the histogram.

    Returns:
        Columns ``line``, ``signal`` and ``histogram``.

    Raises:
        ValueError: If a window is below 1.
    """
    line = ema(close, fast) - ema(close, slow)
    trigger = ema(line, signal)
    return pd.DataFrame({"line": line, "signal": trigger, "histogram": line - trigger})


def aroon(high: pd.Series, low: pd.Series, window: int = 25) -> pd.DataFrame:
    """Aroon up and down (0-100) and their difference, the oscillator (-100-100).

    Up is 100 when the highest high of the last ``window + 1`` bars is the latest one and 0
    when it is the oldest; ties count from the oldest, as in ``ta``.

    Returns:
        Columns ``up``, ``down`` and ``oscillator``.

    Raises:
        ValueError: If ``window`` is below 1.
    """
    _check_window(window)

    def position(values: pd.Series, pick: str) -> np.ndarray:
        data = values.to_numpy(dtype=float)
        out = np.full(len(data), np.nan)
        if len(data) > window:
            windows = sliding_window_view(data, window + 1)
            where = windows.argmax(axis=1) if pick == "max" else windows.argmin(axis=1)
            out[window:] = where / window * 100.0
        return out

    up = position(high, "max")
    down = position(low, "min")
    return pd.DataFrame({"up": up, "down": down, "oscillator": up - down}, index=high.index)
