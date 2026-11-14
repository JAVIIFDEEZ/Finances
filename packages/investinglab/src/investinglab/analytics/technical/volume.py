"""Volume indicators: money flow index, Chaikin money flow and relative volume (ADR-0034).

Definitions follow the ``ta`` library CryptoWorld used. Every function is causal and needs
the volume of the bars; a bar with no range adds no money flow (``ta``'s convention).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

__all__ = ["cmf", "mfi", "volume_ratio"]


def _check_window(window: int) -> None:
    if window < 1:
        raise ValueError(f"window must be at least 1, got {window}")


def mfi(
    high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series, window: int = 14
) -> pd.Series:
    """Money flow index (0-100): an RSI of the money traded at rising and falling prices.

    The flow of a bar is its typical price times its volume, positive when the typical price
    rose, negative when it fell and none when it did not move. A window without negative
    flow reads 100.

    Raises:
        ValueError: If ``window`` is below 1.
    """
    _check_window(window)
    typical = (high + low + close) / 3.0
    previous = typical.shift(1)
    direction = np.where(typical > previous, 1.0, np.where(typical < previous, -1.0, 0.0))
    flow = typical * volume * direction
    positive = flow.clip(lower=0.0).rolling(window, min_periods=window).sum()
    negative = (-flow.clip(upper=0.0)).rolling(window, min_periods=window).sum()
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = positive / negative
    return 100.0 - 100.0 / (1.0 + ratio)


def cmf(
    high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series, window: int = 20
) -> pd.Series:
    """Chaikin money flow (-1-1): volume weighted by where each close sits in its bar.

    Raises:
        ValueError: If ``window`` is below 1.
    """
    _check_window(window)
    span = (high - low).replace(0.0, np.nan)
    multiplier = (((close - low) - (high - close)) / span).fillna(0.0)
    flow = (multiplier * volume).rolling(window, min_periods=window).sum()
    total = volume.rolling(window, min_periods=window).sum().replace(0.0, np.nan)
    return flow / total


def volume_ratio(volume: pd.Series, window: int = 20) -> pd.Series:
    """Volume over its moving average of ``window`` bars (above 1: busier than usual).

    Raises:
        ValueError: If ``window`` is below 1.
    """
    _check_window(window)
    average = volume.rolling(window, min_periods=window).mean()
    return volume / average.replace(0.0, np.nan)
