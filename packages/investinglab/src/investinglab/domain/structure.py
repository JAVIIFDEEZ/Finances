"""Price structure of a price series, for any asset class (ADR-0036).

:func:`price_structure` finds the support and resistance levels, the divergences between
the close and its RSI and the Fibonacci levels of the recent swing on the bars of a
:class:`~investinglab.domain.series.PriceSeries`, as of its last bar. Levels and the swing
come from the highs and lows when the series has them (``basis="range"``) and from the
closes otherwise (``basis="close"``), which is said, never hidden: the highs and lows are not
made up from the closes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

import pandas as pd

from investinglab.analytics.structure import divergences, fibonacci_swing, support_resistance
from investinglab.analytics.technical import rsi
from investinglab.domain.errors import DomainError
from investinglab.domain.series import PriceField

if TYPE_CHECKING:
    from investinglab.domain.instruments import Instrument
    from investinglab.domain.series import DataSource, PriceSeries
    from investinglab.domain.time import Frequency

__all__ = [
    "FibonacciSwing",
    "PriceDivergence",
    "PriceStructure",
    "StructureLevel",
    "price_structure",
]

RSI_WINDOW = 14


@dataclass(frozen=True, slots=True)
class StructureLevel:
    """A support or resistance level.

    Attributes:
        price: Mean price of the pivots that touched it.
        touches: How many pivots touched it (its strength).
        kind: ``support`` below the last close, ``resistance`` at or above it.
        distance_pct: Distance from the last close, in percent of it.
        touched_at: The bars of those pivots, oldest first.
    """

    price: float
    touches: int
    kind: Literal["support", "resistance"]
    distance_pct: float
    touched_at: tuple[pd.Timestamp, ...]


@dataclass(frozen=True, slots=True)
class PriceDivergence:
    """The close and its RSI disagree on the last two pivots.

    Attributes:
        kind: ``bearish`` (a higher high, a lower RSI) or ``bullish`` (a lower low, a
            higher RSI).
        first_at: Bar of the earlier pivot.
        second_at: Bar of the later pivot.
        confirmed_at: Bar that confirmed the later pivot: the divergence is known from here.
        price_first: Close at the earlier pivot.
        price_second: Close at the later pivot.
        rsi_first: RSI at the earlier pivot.
        rsi_second: RSI at the later pivot.
    """

    kind: Literal["bearish", "bullish"]
    first_at: pd.Timestamp
    second_at: pd.Timestamp
    confirmed_at: pd.Timestamp
    price_first: float
    price_second: float
    rsi_first: float
    rsi_second: float


@dataclass(frozen=True, slots=True)
class FibonacciSwing:
    """The recent swing and its retracement levels.

    Attributes:
        high: Highest price of the window.
        low: Lowest price of the window.
        high_at: Bar of the high.
        low_at: Bar of the low.
        rising: Whether the low came first (levels then retrace down from the high).
        levels: ``(ratio, price)`` of each retracement (empty for a flat window).
        nearest: Ratio of the level closest to the last close (``None`` without levels).
    """

    high: float
    low: float
    high_at: pd.Timestamp
    low_at: pd.Timestamp
    rising: bool
    levels: tuple[tuple[float, float], ...]
    nearest: float | None


@dataclass(frozen=True, slots=True, eq=False)
class PriceStructure:
    """Support and resistance, divergences and Fibonacci levels of a series as of its last bar.

    Args:
        instrument: The instrument observed.
        frequency: Frequency of the bars.
        source: Provenance of the bars.
        basis: ``range`` (highs and lows) or ``close`` (a series of closes).
        last_at: The last bar.
        last_close: Its close.
        levels: The strongest levels, by touches and then closeness.
        divergences: Divergences on the last two pivots of the close.
        fibonacci: The recent swing (``None`` for an empty series).
        parameters: Parameters used.
    """

    instrument: Instrument
    frequency: Frequency
    source: DataSource
    basis: Literal["range", "close"]
    last_at: pd.Timestamp | None
    last_close: float | None
    levels: tuple[StructureLevel, ...]
    divergences: tuple[PriceDivergence, ...]
    fibonacci: FibonacciSwing | None
    parameters: dict[str, float]

    @property
    def nearest_support(self) -> StructureLevel | None:
        """The highest support (closest below the last close)."""
        supports = [level for level in self.levels if level.kind == "support"]
        return max(supports, key=lambda level: level.price, default=None)

    @property
    def nearest_resistance(self) -> StructureLevel | None:
        """The lowest resistance (closest at or above the last close)."""
        resistances = [level for level in self.levels if level.kind == "resistance"]
        return min(resistances, key=lambda level: level.price, default=None)


def price_structure(
    series: PriceSeries,
    *,
    k: int = 3,
    tolerance_pct: float = 0.6,
    max_levels: int = 8,
    divergence_lookback: int = 80,
    fibonacci_lookback: int = 180,
) -> PriceStructure:
    """The structure of ``series`` as of its last bar (CryptoWorld's defaults).

    Args:
        series: The bars.
        k: Bars on each side that confirm a pivot.
        tolerance_pct: Pivots within this percentage of a level's mean join it.
        max_levels: Most levels kept.
        divergence_lookback: Bars in which the two pivots of a divergence are sought.
        fibonacci_lookback: Bars of the swing.

    Raises:
        DomainError: If a parameter is out of range.
    """
    if not tolerance_pct > 0:
        raise DomainError(f"tolerance_pct must be positive, got {tolerance_pct}")
    bars = series.bars
    close = bars[PriceField.CLOSE].astype(float)
    ranged = PriceField.HIGH in bars.columns and PriceField.LOW in bars.columns
    high = bars[PriceField.HIGH].astype(float) if ranged else close
    low = bars[PriceField.LOW].astype(float) if ranged else close
    times = pd.DatetimeIndex(bars.index)
    try:
        found = support_resistance(
            high, low, close, k, tolerance_pct=tolerance_pct, max_levels=max_levels
        )
        split = divergences(close, rsi(close, RSI_WINDOW), k, lookback=divergence_lookback)
        swing = fibonacci_swing(high, low, fibonacci_lookback)
    except ValueError as error:
        raise DomainError(str(error)) from error
    last_close = float(close.iloc[-1]) if len(close) else None
    nearest = swing.nearest(last_close) if swing is not None and last_close is not None else None
    return PriceStructure(
        instrument=series.instrument,
        frequency=series.frequency,
        source=series.source,
        basis="range" if ranged else "close",
        last_at=times[-1] if len(times) else None,
        last_close=last_close,
        levels=tuple(
            StructureLevel(
                level.price,
                level.touches,
                level.kind,
                level.distance_pct,
                tuple(times[list(level.positions)]),
            )
            for level in found
        ),
        divergences=tuple(
            PriceDivergence(
                d.kind,
                times[d.first],
                times[d.second],
                times[d.confirmed],
                d.price_first,
                d.price_second,
                d.oscillator_first,
                d.oscillator_second,
            )
            for d in split
        ),
        fibonacci=None
        if swing is None
        else FibonacciSwing(
            swing.high,
            swing.low,
            times[swing.high_at],
            times[swing.low_at],
            swing.rising,
            swing.levels,
            None if nearest is None else nearest[0],
        ),
        parameters={
            "k": k,
            "tolerance_pct": tolerance_pct,
            "max_levels": max_levels,
            "divergence_lookback": divergence_lookback,
            "fibonacci_lookback": fibonacci_lookback,
        },
    )
