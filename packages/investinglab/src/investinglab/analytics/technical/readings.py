"""How each indicator of the catalogue is read: its family and its conventional zones (ADR-0037).

A reading describes where an indicator stands, never what will happen next:

* **Oscillators** are read against the zones their authors proposed (``ZONES``): the RSI's
  30 and 70 (Wilder), the stochastics' 20 and 80 (Lane), the CCI's -100 and 100 (Lambert)...
  Below the lower bound the reading is ``low``, above the upper one ``high``. These are not
  the threshold *search ranges* of CryptoWorld's strategy grammar (``Indicator.threshold``).
* **Oscillators around zero** (ROC, TRIX, the MACD lines) are ``above`` or ``below`` it.
* **Levels in price units** (averages, bands, channels, the parabolic SAR, Ichimoku) are read
  by the side of the level the close is on: ``above`` or ``below``.
* **Relative measures** with no natural scale (the ATR as a share of the price, the volume
  ratio) are read against their own history over the bars given: their percentile, ``high``
  in the top fifth and ``low`` in the bottom fifth.
"""

from __future__ import annotations

from enum import StrEnum
from types import MappingProxyType
from typing import Final

import numpy as np
import pandas as pd

__all__ = [
    "CENTRED",
    "FAMILIES",
    "LEVELS",
    "RELATIVE",
    "ZONES",
    "Family",
    "Reading",
    "percentile",
    "read",
]


class Family(StrEnum):
    """What an indicator measures."""

    TREND = "trend"
    MOMENTUM = "momentum"
    VOLATILITY = "volatility"
    VOLUME = "volume"
    PRICE = "price"


class Reading(StrEnum):
    """Where an indicator stands."""

    HIGH = "high"
    """In its upper zone (or the top fifth of its history)."""
    LOW = "low"
    """In its lower zone (or the bottom fifth of its history)."""
    NEUTRAL = "neutral"
    """Between its zones."""
    ABOVE = "above"
    """The close above the level (or the oscillator above zero)."""
    BELOW = "below"
    """The close below the level (or the oscillator below zero)."""


FAMILIES: Final = MappingProxyType(
    {
        **dict.fromkeys(
            ("SMA", "EMA", "WMA", "HMA", "KAMA", "ICHI_CONV", "ICHI_BASE", "PSAR", "ADX", "AROON"),
            Family.TREND,
        ),
        **dict.fromkeys(
            ("RSI", "STOCHRSI", "STOCH", "WILLR", "CCI", "ROC", "TRIX", "MACD_LINE", "MACD_SIGNAL"),
            Family.MOMENTUM,
        ),
        **dict.fromkeys(
            (
                "ATR_PCT",
                "BB_UPPER",
                "BB_LOWER",
                "KELT_UPPER",
                "KELT_LOWER",
                "DONCH_UPPER",
                "DONCH_LOWER",
            ),
            Family.VOLATILITY,
        ),
        **dict.fromkeys(("MFI", "CMF", "VOLRATIO"), Family.VOLUME),
        **dict.fromkeys(("PRICE", "FIB_RETR"), Family.PRICE),
    }
)
"""The family of every indicator of the catalogue."""

ZONES: Final = MappingProxyType(
    {
        "RSI": (30.0, 70.0),  # Wilder (1978)
        "STOCHRSI": (20.0, 80.0),  # Chande and Kroll (1994), in percent
        "STOCH": (20.0, 80.0),  # Lane
        "WILLR": (-80.0, -20.0),  # Williams
        "CCI": (-100.0, 100.0),  # Lambert (1980)
        "MFI": (20.0, 80.0),  # Quong and Soudack (1989)
        "ADX": (20.0, 25.0),  # Wilder (1978): below 20 no trend, above 25 a trend
        "AROON": (-50.0, 50.0),  # Chande (1995): the oscillator beyond ±50
        "CMF": (-0.05, 0.05),  # Chaikin: selling or buying pressure beyond ±0.05
    }
)
"""Conventional zones of the oscillators: ``(lower, upper)``."""

CENTRED: Final = frozenset({"ROC", "TRIX", "MACD_LINE", "MACD_SIGNAL"})
"""Oscillators read by their side of zero."""

LEVELS: Final = frozenset(
    {
        "SMA",
        "EMA",
        "WMA",
        "HMA",
        "KAMA",
        "ICHI_CONV",
        "ICHI_BASE",
        "PSAR",
        "BB_UPPER",
        "BB_LOWER",
        "KELT_UPPER",
        "KELT_LOWER",
        "DONCH_UPPER",
        "DONCH_LOWER",
        "FIB_RETR",
    }
)
"""Levels in price units, read by the side of them the close is on."""

RELATIVE: Final = frozenset({"ATR_PCT", "VOLRATIO"})
"""Measures read against their own history (percentile)."""

EXTREME: Final = 0.2
"""Share of the history at each end that reads as ``low`` or ``high``."""


def percentile(history: pd.Series | np.ndarray, value: float) -> float | None:
    """Share of the defined values of ``history`` at or below ``value`` (``None`` if none)."""
    values = np.asarray(history, dtype=float)
    values = values[~np.isnan(values)]
    if values.size == 0 or np.isnan(value):
        return None
    return float(np.mean(values <= value))


def _side(value: float, reference: float) -> Reading:
    """``above``, ``below`` or (exactly on it) ``neutral``."""
    if value > reference:
        return Reading.ABOVE
    return Reading.BELOW if value < reference else Reading.NEUTRAL


def _band(value: float, lower: float, upper: float) -> Reading:
    """``low`` below the band, ``high`` above it, ``neutral`` within it."""
    if value < lower:
        return Reading.LOW
    return Reading.HIGH if value > upper else Reading.NEUTRAL


def read(
    name: str,
    value: float | None,
    *,
    close: float | None = None,
    history: pd.Series | np.ndarray | None = None,
) -> tuple[Reading | None, float | None]:
    """The reading of indicator ``name`` at ``value``, and its percentile when relative.

    Args:
        name: An indicator of the catalogue.
        value: Its value (``None`` or ``NaN`` while warming up: no reading).
        close: The close of the same bar, for the levels.
        history: Its values over the bars given, for the relative measures.

    Returns:
        ``(reading, percentile)``; the reading is ``None`` when there is nothing to read
        (no value, a level without a close, the price itself).
    """
    reading: Reading | None = None
    rank: float | None = None
    if value is None or np.isnan(value):
        pass
    elif name in ZONES:
        reading = _band(value, *ZONES[name])
    elif name in CENTRED:
        reading = _side(value, 0.0)
    elif name in LEVELS:
        if close is not None and not np.isnan(close):
            reading = _side(close, value)
    elif name in RELATIVE and history is not None:
        rank = percentile(history, value)
        if rank is not None:
            reading = _band(rank, EXTREME, 1 - EXTREME)
    return reading, rank
