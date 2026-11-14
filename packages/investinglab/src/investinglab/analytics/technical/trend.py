"""Trend indicators: ADX, parabolic SAR and the Ichimoku lines (ADR-0034).

Definitions follow the ``ta`` library CryptoWorld used, so its strategies keep their meaning;
the values ``ta`` fills in during warm-up (zeros, or the close for the parabolic SAR) are
``NaN`` here. Every function is causal.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from investinglab.analytics.technical.volatility import true_range

__all__ = ["adx", "ichimoku", "psar"]


def _wilder_sums(values: np.ndarray, window: int) -> np.ndarray:
    """Wilder's running sum: the first ``window`` changes at bar ``window``, then decayed.

    ``values[0]`` (no change yet) is never used; bars before ``window`` are ``NaN``.
    """
    sums = np.full(len(values), np.nan)
    if len(values) <= window:
        return sums
    sums[window] = values[1 : window + 1].sum()
    for i in range(window + 1, len(values)):
        sums[i] = sums[i - 1] - sums[i - 1] / window + values[i]
    return sums


def adx(high: pd.Series, low: pd.Series, close: pd.Series, window: int = 14) -> pd.DataFrame:
    """Average directional index (0-100) with the +DI and -DI lines (Wilder).

    The sums of true range and directional movement start with the first ``window``
    changes; the ADX averages the first ``window`` directional indices and then smooths each
    new one. A bar without range has directional lines of 0, as in ``ta``.

    Returns:
        Columns ``adx``, ``plus_di`` and ``minus_di``.

    Raises:
        ValueError: If ``window`` is below 1.
    """
    if window < 1:
        raise ValueError(f"window must be at least 1, got {window}")
    n = len(close)
    up = high.diff().to_numpy(dtype=float)
    down = -low.diff().to_numpy(dtype=float)
    plus_move = np.where((up > down) & (up > 0), up, 0.0)
    minus_move = np.where((down > up) & (down > 0), down, 0.0)
    ranges = _wilder_sums(true_range(high, low, close).to_numpy(dtype=float), window)
    plus = _wilder_sums(plus_move, window)
    minus = _wilder_sums(minus_move, window)
    defined = ~np.isnan(ranges)
    with np.errstate(divide="ignore", invalid="ignore"):
        plus_di = np.where(ranges != 0, 100.0 * plus / ranges, 0.0)
        minus_di = np.where(ranges != 0, 100.0 * minus / ranges, 0.0)
        total = plus_di + minus_di
        index = np.where(total != 0, 100.0 * np.abs(plus_di - minus_di) / total, 0.0)
    plus_di, minus_di, index = (np.where(defined, x, np.nan) for x in (plus_di, minus_di, index))
    average = np.full(n, np.nan)
    first = 2 * window - 1  # the first `window` directional indices: bars window..2·window-1
    if n > first:
        average[first] = np.mean(index[window : first + 1])
        for i in range(first + 1, n):
            average[i] = (average[i - 1] * (window - 1) + index[i]) / window
    return pd.DataFrame(
        {"adx": average, "plus_di": plus_di, "minus_di": minus_di}, index=close.index
    )


def psar(  # noqa: PLR0912 - one branch per rule of Wilder's stop and reverse
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    step: float = 0.02,
    max_step: float = 0.2,
) -> pd.Series:
    """Parabolic stop and reverse, starting in an up trend at the first bar.

    Undefined for the first two bars, which ``ta`` fills with the close.

    Raises:
        ValueError: If ``step`` is not positive or ``max_step`` is below it.
    """
    if not 0 < step <= max_step:
        raise ValueError(f"need 0 < step <= max_step, got {step} and {max_step}")
    highs = high.to_numpy(dtype=float)
    lows = low.to_numpy(dtype=float)
    out = close.to_numpy(dtype=float).copy()
    up_trend = True
    factor = step
    extreme_high, extreme_low = highs[0], lows[0]
    for i in range(2, len(out)):
        reversal = False
        if up_trend:
            out[i] = out[i - 1] + factor * (extreme_high - out[i - 1])
            if lows[i] < out[i]:
                reversal, out[i] = True, extreme_high
                extreme_low, factor = lows[i], step
            else:
                if highs[i] > extreme_high:
                    extreme_high, factor = highs[i], min(factor + step, max_step)
                if lows[i - 2] < out[i]:
                    out[i] = lows[i - 2]
                elif lows[i - 1] < out[i]:
                    out[i] = lows[i - 1]
        else:
            out[i] = out[i - 1] - factor * (out[i - 1] - extreme_low)
            if highs[i] > out[i]:
                reversal, out[i] = True, extreme_low
                extreme_high, factor = highs[i], step
            else:
                if lows[i] < extreme_low:
                    extreme_low, factor = lows[i], min(factor + step, max_step)
                if highs[i - 2] > out[i]:
                    out[i] = highs[i - 2]
                elif highs[i - 1] > out[i]:
                    out[i] = highs[i - 1]
        up_trend = up_trend != reversal
    out[: min(2, len(out))] = np.nan
    return pd.Series(out, index=close.index)


def ichimoku(high: pd.Series, low: pd.Series, conversion: int = 9, base: int = 26) -> pd.DataFrame:
    """Ichimoku conversion (tenkan-sen) and base (kijun-sen) lines: mid-points of the range.

    Returns:
        Columns ``conversion`` and ``base``.

    Raises:
        ValueError: If a window is below 1.
    """
    for window in (conversion, base):
        if window < 1:
            raise ValueError(f"window must be at least 1, got {window}")

    def midpoint(window: int) -> pd.Series:
        top = high.rolling(window, min_periods=window).max()
        bottom = low.rolling(window, min_periods=window).min()
        return 0.5 * (top + bottom)

    return pd.DataFrame({"conversion": midpoint(conversion), "base": midpoint(base)})
