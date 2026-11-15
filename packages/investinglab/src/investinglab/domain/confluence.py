"""The technical view of an instrument across timeframes, for any asset class (ADR-0038).

:func:`timeframe_confluence` reads the signal panel and the background trend of an
instrument on several timeframes and says whether they agree. Coarser frames weigh more: the
finest weighs 1 and each coarser one, one more, because the background trend outranks the
noise of the finer frames. A frame that cannot be read (no source serves it, too few bars
for the panel's longest average) is reported with the reason and neither counts nor weighs.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Final

import pandas as pd

from investinglab.analytics.technical.signals import (
    Confluence,
    SignalPanel,
    TrendState,
    confluence,
    signal_panel,
    trend_state,
)
from investinglab.domain.errors import DomainError
from investinglab.domain.series import PriceField

if TYPE_CHECKING:
    from collections.abc import Collection, Mapping

    from investinglab.domain.instruments import Instrument
    from investinglab.domain.series import DataSource, PriceSeries
    from investinglab.domain.time import Frequency

__all__ = ["MIN_BARS", "FrameIssue", "FrameReading", "TimeframeConfluence", "timeframe_confluence"]

MIN_BARS: Final = 50
"""Bars a frame needs: the panel's longest average."""


class FrameIssue(StrEnum):
    """Why a frame could not be read."""

    NO_DATA = "no_data"
    """No source serves these bars for the instrument."""
    TOO_FEW_BARS = "too_few_bars"
    """Fewer than :data:`MIN_BARS` bars."""


@dataclass(frozen=True, slots=True)
class FrameReading:
    """One timeframe of the instrument.

    Attributes:
        frequency: The frame.
        weight: Its weight in the alignment.
        bars: Bars it has.
        last_at: Its last bar (for a derived frame, the last session of the period, which
            may still be in progress).
        derived: Whether its bars were aggregated from a finer frame of the same source.
        panel: The rules read on its last bar (``None`` if it could not be read).
        trend: Its background trend (``None`` if it could not be read or told).
        issue: Why it could not be read (``None`` if it was).
    """

    frequency: Frequency
    weight: float
    bars: int
    last_at: pd.Timestamp | None
    derived: bool
    panel: SignalPanel | None
    trend: TrendState | None
    issue: FrameIssue | None

    @property
    def score(self) -> float | None:
        """Net score of its panel, in [-1, 1] (``None`` if it could not be read)."""
        return None if self.panel is None else self.panel.score


@dataclass(frozen=True, slots=True, eq=False)
class TimeframeConfluence:
    """The frames of an instrument and whether they agree.

    Args:
        instrument: The instrument observed.
        source: Provenance of the bars.
        frames: One reading per frame, finest first.
        summary: The verdict, the weighted alignment and the share of frames in agreement.
    """

    instrument: Instrument
    source: DataSource
    frames: tuple[FrameReading, ...]
    summary: Confluence

    def frame(self, frequency: Frequency) -> FrameReading:
        """The reading of one frame.

        Raises:
            KeyError: If ``frequency`` was not asked for.
        """
        for reading in self.frames:
            if reading.frequency is frequency:
                return reading
        raise KeyError(f"{frequency.value} was not read")


def _read(series: PriceSeries) -> tuple[SignalPanel, TrendState | None]:
    bars = series.bars
    close = bars[PriceField.CLOSE].astype(float)
    ranged = PriceField.HIGH in bars.columns and PriceField.LOW in bars.columns
    high = bars[PriceField.HIGH].astype(float) if ranged else None
    low = bars[PriceField.LOW].astype(float) if ranged else None
    return signal_panel(close, high, low), trend_state(close)


def _frame(
    frequency: Frequency, weight: float, series: PriceSeries | None, *, derived: bool
) -> FrameReading:
    if series is None:
        return FrameReading(frequency, weight, 0, None, derived, None, None, FrameIssue.NO_DATA)
    count = len(series.bars)
    last = pd.Timestamp(series.bars.index[-1]) if count else None
    if count < MIN_BARS:
        issue = FrameIssue.TOO_FEW_BARS
        return FrameReading(frequency, weight, count, last, derived, None, None, issue)
    panel, trend = _read(series)
    return FrameReading(frequency, weight, count, last, derived, panel, trend, None)


def timeframe_confluence(
    frames: Mapping[Frequency, PriceSeries | None],
    *,
    derived: Collection[Frequency] = (),
) -> TimeframeConfluence:
    """Read every frame and weigh them, finest first.

    Args:
        frames: The bars of each frame; ``None`` for a frame no source could serve.
        derived: Frames whose bars were aggregated from a finer one.

    Raises:
        DomainError: If no frame has bars, a series is of another frequency than its frame,
            or the series are of different instruments.
    """
    served = {frequency: series for frequency, series in frames.items() if series is not None}
    if not served:
        raise DomainError("No frame has bars to read")
    for frequency, series in served.items():
        if series.frequency is not frequency:
            raise DomainError(f"The {frequency.value} frame got {series.frequency.value} bars")
    symbols = {series.symbol for series in served.values()}
    if len(symbols) > 1:
        raise DomainError(f"Frames of different instruments: {sorted(symbols)}")
    readings = [
        _frame(frequency, float(weight), frames[frequency], derived=frequency in derived)
        for weight, frequency in enumerate(sorted(frames, key=lambda f: f.rank), start=1)
    ]
    finest = served[min(served, key=lambda f: f.rank)]
    return TimeframeConfluence(
        instrument=finest.instrument,
        source=finest.source,
        frames=tuple(readings),
        summary=confluence([(reading.weight, reading.score) for reading in readings]),
    )
