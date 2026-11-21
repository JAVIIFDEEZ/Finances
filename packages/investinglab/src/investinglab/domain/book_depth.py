"""Depth of an order book around its price, snapshot by snapshot (ADR-0044).

How much is offered to buy and to sell near the price says how far a trade of a given size
moves it. Venues publish it in their own way: Binance, in daily dumps, the quantity resting
within ±0.2 %, ±1 %... ±5 % of the price every 30 seconds since 2023; another venue may give
other bands, or only its book as it is now. A :class:`BookDepthSeries` keeps those
snapshots under one vocabulary:

* a **band** is a distance from the price, in percent (``2.0`` is ±2 %);
* each band has a **bid** side (buy orders below the price) and an **ask** side (sell orders
  above it);
* each side is measured as a **quantity** of the base asset (bitcoins for a BTC contract)
  and, when the venue gives it, as a **notional** value in :attr:`~BookDepthSeries.
  notional_currency`.

Depth is *cumulative*: what rests within ±2 % includes what rests within ±1 %, so a side
never holds less in a wider band. A snapshot that says otherwise is refused. A band or a
measure the venue does not publish is absent, never filled in; a missing snapshot is
``NaN``.

Each row is the last snapshot of a period, labelled by the period's start (as positioning,
ADR-0042): an hourly row labelled 18:00 is the book as it stood just before 19:00.
"""

from __future__ import annotations

from dataclasses import InitVar, dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Final, cast

import numpy as np
import pandas as pd

from investinglab.domain.errors import DomainError, InvalidSeriesError
from investinglab.domain.positioning import POSITIONING_FREQUENCIES
from investinglab.domain.series import TIME_INDEX_NAME
from investinglab.domain.time import Frequency

if TYPE_CHECKING:
    from datetime import datetime

    from investinglab.domain.instruments import Instrument
    from investinglab.domain.money import Currency
    from investinglab.domain.series import DataSource

__all__ = [
    "BOOK_DEPTH_FREQUENCIES",
    "BookDepthSeries",
    "BookSide",
    "DepthMeasure",
]


class BookSide(StrEnum):
    """A side of the book."""

    BID = "bid"
    """Orders to buy, resting below the price."""
    ASK = "ask"
    """Orders to sell, resting above the price."""


class DepthMeasure(StrEnum):
    """How the depth of a side is measured."""

    QUANTITY = "quantity"
    """Units of the base asset (bitcoins for a BTC contract)."""
    NOTIONAL = "notional"
    """Their value, in :attr:`BookDepthSeries.notional_currency`."""


BOOK_DEPTH_FREQUENCIES: Final = POSITIONING_FREQUENCIES
"""Frequencies the depth can be read at: snapshots are kept every 5 minutes or more."""

_MAX_BAND: Final = 100.0
_LEVELS: Final = 3


def _band(value: object) -> float | None:
    """``value`` as a band in percent, or ``None`` if it is not one."""
    try:
        band = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return band if np.isfinite(band) and 0 < band <= _MAX_BAND else None


type _Column = tuple[str, str, float]


def _columns(frame: pd.DataFrame) -> list[tuple[object, object, object]]:
    """The ``(measure, side, band)`` labels of ``frame``'s columns."""
    return cast("list[tuple[object, object, object]]", frame.columns.to_list())


def _column_problems(frame: pd.DataFrame) -> list[str]:
    if not isinstance(frame.columns, pd.MultiIndex) or frame.columns.nlevels != _LEVELS:
        return ["columns must be a (measure, side, band) MultiIndex"]
    if frame.columns.empty:
        return ["needs at least one band"]
    problems = []
    measures = {member.value for member in DepthMeasure}
    sides = {member.value for member in BookSide}
    for measure, side, band in _columns(frame):
        name = f"{measure}/{side}/{band}"
        if str(measure) not in measures:
            problems.append(f"unknown measure {measure!r}; use DepthMeasure")
        if str(side) not in sides:
            problems.append(f"unknown side {side!r}; use BookSide")
        if _band(band) is None:
            problems.append(f"band {band!r} is not a distance in percent in (0, 100]")
        values = frame[(measure, side, band)]
        if not pd.api.types.is_numeric_dtype(values) or pd.api.types.is_bool_dtype(values):
            problems.append(f"{name} must be numeric, got {values.dtype}")
            continue
        present = values.dropna().astype("float64")
        if not np.isfinite(present).all():
            problems.append(f"{name} must be finite; a missing snapshot is NaN")
        elif (present < 0).any():
            problems.append(f"{name} is an amount resting in the book: it cannot be negative")
    if frame.columns.has_duplicates:
        problems.append("duplicated (measure, side, band) columns")
    return problems


def _cumulative_problems(frame: pd.DataFrame) -> list[str]:
    """Snapshots where a side holds less in a wider band than in a narrower one."""
    problems = []
    for measure in DepthMeasure:
        for side in BookSide:
            columns = sorted(
                (
                    cast("_Column", column)
                    for column in _columns(frame)
                    if column[:2] == (measure.value, side.value)
                ),
                key=lambda column: column[2],
            )
            if len(columns) < 2:  # noqa: PLR2004 - two bands to compare
                continue
            values = frame[columns].to_numpy(dtype="float64")
            # Carry the last band seen forward across a band the venue skipped, so that the
            # comparison is always against the widest narrower band that has a value.
            narrower = pd.DataFrame(values).ffill(axis=1).shift(axis=1).to_numpy()
            shrinks = np.nan_to_num(values, nan=np.inf) < np.nan_to_num(narrower, nan=-np.inf)
            rows = np.flatnonzero(shrinks.any(axis=1))
            if len(rows):
                first = frame.index[rows[0]]
                problems.append(
                    f"{measure.value} of the {side.value} side shrinks in a wider band at "
                    f"{len(rows)} snapshot(s), first {first}: depth is cumulative"
                )
    return problems


def _checked(frame: object, subject: str) -> pd.DataFrame:
    """``frame`` as float snapshots with normalised columns, once its shape is valid."""
    if not isinstance(frame, pd.DataFrame):
        found = type(frame).__name__
        raise InvalidSeriesError(subject, [f"data must be a DataFrame, got {found}"])
    index = frame.index
    if not isinstance(index, pd.DatetimeIndex):
        found = type(index).__name__
        raise InvalidSeriesError(subject, [f"index must be a DatetimeIndex, got {found}"])
    problems = []
    if index.tz is None:
        problems.append("snapshots are instants: the index must be timezone-aware")
    if len(index) == 0:
        problems.append("needs at least one snapshot")
    if index.has_duplicates:
        problems.append("duplicated snapshot instants")
    if not index.is_monotonic_increasing:
        problems.append("index must be sorted in increasing time order")
    problems.extend(_column_problems(frame))
    if problems:
        raise InvalidSeriesError(subject, problems)
    data = frame.astype("float64").dropna(how="all")
    data.columns = pd.MultiIndex.from_tuples(
        [
            (DepthMeasure(str(m)).value, BookSide(str(s)).value, _band(b))
            for m, s, b in _columns(data)
        ],
        names=["measure", "side", "band"],
    )
    data = data.sort_index(axis="columns")
    labels = pd.DatetimeIndex(data.index).tz_convert("UTC").as_unit("ns")
    data.index = labels.rename(TIME_INDEX_NAME)
    if data.empty:
        raise InvalidSeriesError(subject, ["every snapshot is empty"])
    if problems := _cumulative_problems(data):
        raise InvalidSeriesError(subject, problems)
    return data


def _validated(frame: object, subject: str, frequency: Frequency) -> pd.DataFrame:
    data = _checked(frame, subject)
    labels = pd.DatetimeIndex(data.index)
    if not labels.equals(labels.floor(frequency.pandas_rule)):
        raise InvalidSeriesError(
            subject, [f"each row is labelled by the start of its {frequency.value} period"]
        )
    return data


def _last_per_period(frame: pd.DataFrame, frequency: Frequency) -> pd.DataFrame:
    """The last snapshot of each period, whole, labelled by the period's start.

    Whole rows, never the last value of each column apart: mixing instants could make a
    side shrink in a wider band.
    """
    labels = pd.DatetimeIndex(frame.index).floor(frequency.pandas_rule)
    keep = ~labels.duplicated(keep="last")
    last = frame.loc[keep].copy()
    last.index = labels[keep]
    return last


@dataclass(frozen=True, slots=True, eq=False)
class BookDepthSeries:
    """An immutable, validated series of order-book depth of one instrument on one venue.

    Args:
        instrument: The instrument whose book it is (a perpetual swap, a pair).
        venue: Where the book is: depth differs by venue.
        source: Provenance (provider and download timestamp).
        frequency: Spacing of the snapshots (5 minutes to a day).
        data: One column per ``(measure, side, band)`` the venue publishes, indexed by the
            start of each period (timezone-aware; kept in UTC). A row where every column is
            missing is dropped.
        notional_currency: Currency of the :attr:`DepthMeasure.NOTIONAL` columns.

    Raises:
        InvalidSeriesError: Listing every problem found.
        DomainError: If the venue is empty, the frequency is not one depth is read at, or a
            notional is given without its currency.
    """

    instrument: Instrument
    venue: str
    source: DataSource
    frequency: Frequency
    data: InitVar[pd.DataFrame]
    notional_currency: Currency | None = None
    _data: pd.DataFrame = field(init=False, repr=False)

    __match_args__ = ("instrument", "venue", "source", "frequency")

    def __post_init__(self, data: pd.DataFrame) -> None:
        if not self.venue.strip():
            raise DomainError("A book depth series needs the venue of the book")
        if self.frequency not in BOOK_DEPTH_FREQUENCIES:
            allowed = [frequency.value for frequency in BOOK_DEPTH_FREQUENCIES]
            raise DomainError(f"Book depth is read at {allowed}, not {self.frequency.value}")
        frame = _validated(data, f"{self.instrument.symbol}@{self.venue}", self.frequency)
        noted = DepthMeasure.NOTIONAL.value in frame.columns.get_level_values("measure")
        if noted and self.notional_currency is None:
            raise DomainError("A notional depth needs its currency")
        object.__setattr__(self, "_data", frame)

    @classmethod
    def from_snapshots(
        cls,
        instrument: Instrument,
        venue: str,
        source: DataSource,
        frequency: Frequency,
        snapshots: pd.DataFrame,
        *,
        notional_currency: Currency | None = None,
    ) -> BookDepthSeries:
        """Keep the last snapshot of each period of ``frequency`` from raw ones.

        ``snapshots`` has the columns of ``data`` and one row per instant the venue took
        (every 30 seconds for Binance), timezone-aware and sorted. Every one of them is
        validated, not only those kept: a snapshot that breaks the rules means a damaged
        source.

        Raises:
            InvalidSeriesError: Listing every problem found.
            DomainError: If ``frequency`` is not one depth is read at.
        """
        if frequency not in BOOK_DEPTH_FREQUENCIES:
            allowed = [member.value for member in BOOK_DEPTH_FREQUENCIES]
            raise DomainError(f"Book depth is read at {allowed}, not {frequency.value}")
        rows = _checked(snapshots, f"{instrument.symbol}@{venue}")
        return cls(
            instrument,
            venue,
            source,
            frequency,
            _last_per_period(rows, frequency),
            notional_currency=notional_currency,
        )

    @property
    def symbol(self) -> str:
        """Instrument symbol."""
        return self.instrument.symbol

    @property
    def bands(self) -> tuple[float, ...]:
        """The distances from the price published, in percent, narrowest first."""
        return tuple(sorted(set(self._data.columns.get_level_values("band"))))

    @property
    def measures(self) -> tuple[DepthMeasure, ...]:
        """The measures published, in the vocabulary's order."""
        present = set(self._data.columns.get_level_values("measure"))
        return tuple(member for member in DepthMeasure if member.value in present)

    @property
    def snapshots(self) -> pd.DataFrame:
        """A copy of every snapshot: one column per ``(measure, side, band)``."""
        return self._data.copy()

    def depth(
        self,
        side: BookSide | str,
        band: float,
        measure: DepthMeasure | str = DepthMeasure.QUANTITY,
    ) -> pd.Series:
        """What rests on one side within ``band`` percent of the price.

        Raises:
            KeyError: If the venue does not publish that side, band or measure.
        """
        column = (DepthMeasure(measure).value, BookSide(side).value, float(band))
        if column not in self._data.columns:
            raise KeyError(
                f"{self.venue} publishes no {column[0]} of the {column[1]} side within "
                f"±{band} % for {self.symbol}"
            )
        return self._data[column].rename(f"{column[1]}_{column[0]}_{band:g}")

    def imbalance(
        self, band: float, measure: DepthMeasure | str = DepthMeasure.QUANTITY
    ) -> pd.Series:
        """``(bid - ask) / (bid + ask)`` within ``band``: from -1 (only offers) to +1.

        Positive when more rests to buy than to sell. ``NaN`` where a side is missing or
        the book is empty within the band.

        Raises:
            KeyError: If the venue does not publish both sides of that band and measure.
        """
        bid = self.depth(BookSide.BID, band, measure)
        ask = self.depth(BookSide.ASK, band, measure)
        total = bid + ask
        return ((bid - ask) / total.where(total > 0)).rename(f"imbalance_{band:g}")

    def liquidity(self, band: float) -> pd.Series:
        """Value resting on both sides within ``band``, in :attr:`notional_currency`.

        Raises:
            KeyError: If the venue does not publish the notional of both sides of the band.
        """
        bid = self.depth(BookSide.BID, band, DepthMeasure.NOTIONAL)
        ask = self.depth(BookSide.ASK, band, DepthMeasure.NOTIONAL)
        return (bid + ask).rename(f"liquidity_{band:g}")

    @property
    def start(self) -> pd.Timestamp:
        """Start of the first period."""
        return pd.Timestamp(self._data.index[0])

    @property
    def end(self) -> pd.Timestamp:
        """Start of the last period."""
        return pd.Timestamp(self._data.index[-1])

    def __len__(self) -> int:
        return len(self._data)

    def between(
        self, start: pd.Timestamp | str | None = None, end: pd.Timestamp | str | None = None
    ) -> BookDepthSeries:
        """Sub-series with the periods starting in ``[start, end]`` (both inclusive)."""
        return self._with(self._data.loc[start:end], self.frequency)

    def finished(self, now: pd.Timestamp | datetime) -> BookDepthSeries:
        """Only the periods that had ended by ``now``: the one in progress still changes.

        Raises:
            InvalidSeriesError: If no period had ended.
        """
        moment = pd.Timestamp(now)
        length = pd.Timedelta(minutes=self.frequency.minutes or 0) or pd.Timedelta(days=1)
        return self._with(self._data.loc[: moment - length], self.frequency)

    def resample(self, frequency: Frequency | str) -> BookDepthSeries:
        """The last snapshot of each period of ``frequency``, labelled by the period's start.

        Raises:
            DomainError: If ``frequency`` is finer than the series or not one depth is
                read at.
        """
        target = Frequency(frequency)
        if target not in BOOK_DEPTH_FREQUENCIES:
            allowed = [member.value for member in BOOK_DEPTH_FREQUENCIES]
            raise DomainError(f"Book depth is read at {allowed}, not {target.value}")
        if target.is_finer_than(self.frequency):
            raise DomainError(
                f"{self.frequency.value} snapshots cannot be read at {target.value}: "
                "that would invent the ones in between"
            )
        if target is self.frequency:
            return self
        return self._with(_last_per_period(self._data, target), target)

    def _with(self, frame: pd.DataFrame, frequency: Frequency) -> BookDepthSeries:
        return BookDepthSeries(
            self.instrument,
            self.venue,
            self.source,
            frequency,
            frame,
            notional_currency=self.notional_currency,
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, BookDepthSeries):
            return NotImplemented
        return (
            self.instrument == other.instrument
            and self.venue == other.venue
            and self.source == other.source
            and self.frequency is other.frequency
            and self.notional_currency == other.notional_currency
            and self._data.equals(other._data)
        )

    def __hash__(self) -> int:
        return hash((self.instrument, self.venue, self.frequency, self.start, self.end, len(self)))

    def __repr__(self) -> str:
        bands = ", ".join(f"±{band:g} %" for band in self.bands)
        return (
            f"BookDepthSeries({self.symbol}@{self.venue}, {self.frequency.value}, "
            f"{self.start.isoformat()} → {self.end.isoformat()}, n={len(self)}, [{bands}])"
        )
