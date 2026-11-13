"""Moving averages: simple, exponential, weighted, Hull and Kaufman adaptive (ADR-0034).

Every function takes a series of finite values and returns a series on the same index, with
``NaN`` while the window is still filling (the warm-up): a value is never made up from a
partial window. All of them are causal: a value depends only on the observations up to it.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

__all__ = ["ema", "hull", "kama", "sma", "wma"]


def _check_window(window: int, minimum: int = 1) -> None:
    if window < minimum:
        raise ValueError(f"window must be at least {minimum}, got {window}")


def sma(values: pd.Series, window: int) -> pd.Series:
    """Simple moving average of the last ``window`` values.

    Raises:
        ValueError: If ``window`` is below 1.
    """
    _check_window(window)
    return values.rolling(window, min_periods=window).mean()


def ema(values: pd.Series, window: int) -> pd.Series:
    """Exponential moving average with ``alpha = 2 / (window + 1)``, from the first value.

    The recursion starts at the first observation and the first ``window - 1`` values are
    left out as warm-up (the convention of the ``ta`` library CryptoWorld used).

    Raises:
        ValueError: If ``window`` is below 1.
    """
    _check_window(window)
    return values.ewm(span=window, min_periods=window, adjust=False).mean()


def wma(values: pd.Series, window: int) -> pd.Series:
    """Linearly weighted moving average: weights 1, 2, ..., ``window`` (newest heaviest).

    Raises:
        ValueError: If ``window`` is below 1.
    """
    _check_window(window)
    weights = np.arange(1, window + 1, dtype=float)
    weights /= weights.sum()
    data = values.to_numpy(dtype=float)
    out = np.full(len(data), np.nan)
    if len(data) >= window:
        out[window - 1 :] = np.convolve(data, weights[::-1], mode="valid")
    return pd.Series(out, index=values.index)


def hull(values: pd.Series, window: int) -> pd.Series:
    """Hull moving average: ``WMA(2 WMA(n/2) - WMA(n), sqrt(n))``, fast with little lag.

    The half and square-root windows are at least 2 (``n // 2`` and ``round(sqrt(n))``).

    Raises:
        ValueError: If ``window`` is below 2.
    """
    _check_window(window, 2)
    half = max(2, window // 2)
    root = max(2, round(math.sqrt(window)))
    raw = 2.0 * wma(values, half) - wma(values, window)
    smoothed = wma(raw.dropna(), root)
    return smoothed.reindex(values.index)


def kama(values: pd.Series, window: int = 10, fast: int = 2, slow: int = 30) -> pd.Series:
    """Kaufman's adaptive moving average: quick in trends, slow in ranges.

    The efficiency ratio over ``window`` changes blends the smoothing constants of ``fast``
    and ``slow`` EMAs; the average starts at the close of the first full window.

    Raises:
        ValueError: If a window is below 1.
    """
    for size in (window, fast, slow):
        _check_window(size)
    data = values.to_numpy(dtype=float)
    out = np.full(len(data), np.nan)
    if len(data) < window:
        return pd.Series(out, index=values.index)
    change = np.abs(data[window:] - data[:-window])
    steps = np.abs(np.diff(data))
    volatility = np.convolve(steps, np.ones(window), mode="valid")  # sums of `window` steps
    ratio = np.divide(change, volatility, out=np.zeros_like(change), where=volatility != 0)
    fast_sc, slow_sc = 2.0 / (fast + 1.0), 2.0 / (slow + 1.0)
    constant = (ratio * (fast_sc - slow_sc) + slow_sc) ** 2
    out[window - 1] = data[window - 1]
    for i in range(window, len(data)):
        out[i] = out[i - 1] + constant[i - window] * (data[i] - out[i - 1])
    return pd.Series(out, index=values.index)
