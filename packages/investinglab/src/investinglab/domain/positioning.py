"""Positioning in a derivative: open interest and who is long or short (ADR-0042).

How much is open on a perpetual swap or a future, and how the traders stand in it, is
published by each venue in its own way: Binance every 5 minutes in its dumps, OKX every 5
minutes, hour or day through its API, each with the figures it chooses. A
:class:`PositioningSeries` keeps those snapshots under one vocabulary
(:class:`PositioningField`), with only the fields the venue published: a field it does not
publish is absent, never filled in.

Each row is a snapshot at an instant (UTC): the state at that moment, not a total over a
period. Coarser frequencies take the last snapshot of each period and an empty period stays
absent.
"""

from __future__ import annotations

from dataclasses import InitVar, dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Final

import numpy as np
import pandas as pd

from investinglab.domain.errors import DomainError, InvalidSeriesError
from investinglab.domain.series import TIME_INDEX_NAME
from investinglab.domain.time import Frequency

if TYPE_CHECKING:
    from collections.abc import Iterable
    from datetime import datetime

    from investinglab.domain.instruments import Instrument
    from investinglab.domain.money import Currency
    from investinglab.domain.series import DataSource

__all__ = [
    "AMOUNTS",
    "POSITIONING_FREQUENCIES",
    "RATIOS",
    "PositioningField",
    "PositioningSeries",
]


class PositioningField(StrEnum):
    """What a column of a :class:`PositioningSeries` measures."""

    OPEN_INTEREST = "open_interest"
    """Contracts open, in units of the base asset (bitcoins for a BTC swap)."""
    OPEN_INTEREST_VALUE = "open_interest_value"
    """The same, valued in :attr:`PositioningSeries.value_currency`."""
    LONG_SHORT_ACCOUNTS = "long_short_accounts"
    """Accounts net long over accounts net short, among all traders."""
    TOP_LONG_SHORT_ACCOUNTS = "top_long_short_accounts"
    """The same ratio among the venue's top traders (by margin balance)."""
    TOP_LONG_SHORT_POSITIONS = "top_long_short_positions"
    """Size of the top traders' long positions over the size of their short ones."""
    TAKER_BUY_SELL = "taker_buy_sell"
    """Volume bought by takers over volume sold by takers, in the period ending there."""


AMOUNTS: Final = frozenset({PositioningField.OPEN_INTEREST, PositioningField.OPEN_INTEREST_VALUE})
"""Fields that are amounts (zero or more)."""

RATIOS: Final = frozenset(PositioningField) - AMOUNTS
"""Fields that are ratios of two amounts (zero or more)."""

POSITIONING_FREQUENCIES: Final = (
    Frequency.MINUTE_5,
    Frequency.MINUTE_15,
    Frequency.MINUTE_30,
    Frequency.HOUR_1,
    Frequency.HOUR_4,
    Frequency.DAY_1,
)
"""Frequencies a positioning series can be read at: venues publish every 5 minutes or more."""


def _index_problems(index: pd.DatetimeIndex) -> list[str]:
    problems = []
    if index.tz is None:
        problems.append("snapshots are instants: the index must be timezone-aware")
    if len(index) == 0:
        problems.append("needs at least one snapshot")
    if index.has_duplicates:
        problems.append("duplicated snapshot instants")
    if not index.is_monotonic_increasing:
        problems.append("index must be sorted in increasing time order")
    return problems


def _column_problems(name: str, values: pd.Series) -> list[str]:
    if name not in _KNOWN:
        return [f"unknown field {name!r}; use PositioningField"]
    if not pd.api.types.is_numeric_dtype(values) or pd.api.types.is_bool_dtype(values):
        return [f"{name} must be numeric, got {values.dtype}"]
    present = values.dropna().astype("float64")
    if not np.isfinite(present).all():
        return [f"{name} must be finite; a missing snapshot is NaN"]
    if (present < 0).any():
        kind = "an amount" if PositioningField(name) in AMOUNTS else "a ratio of two amounts"
        return [f"{name} is {kind}: it cannot be negative"]
    return []


_KNOWN: Final = frozenset(member.value for member in PositioningField)


def _validated(frame: object, subject: str) -> pd.DataFrame:
    if not isinstance(frame, pd.DataFrame):
        found = type(frame).__name__
        raise InvalidSeriesError(subject, [f"data must be a DataFrame, got {found}"])
    if not isinstance(frame.index, pd.DatetimeIndex):
        found = type(frame.index).__name__
        raise InvalidSeriesError(subject, [f"index must be a DatetimeIndex, got {found}"])
    problems = _index_problems(frame.index)
    if frame.columns.empty:
        problems.append("needs at least one field")
    for column in frame.columns:
        problems.extend(_column_problems(str(column), frame[column]))
    if problems:
        raise InvalidSeriesError(subject, problems)
    data = frame.astype("float64").dropna(how="all")
    index = pd.DatetimeIndex(data.index).tz_convert("UTC").as_unit("ns")
    data.index = index.rename(TIME_INDEX_NAME)
    data.columns = [PositioningField(str(column)).value for column in data.columns]
    if data.empty:
        raise InvalidSeriesError(subject, ["every snapshot is empty"])
    return data


@dataclass(frozen=True, slots=True, eq=False)
class PositioningSeries:
    """An immutable, validated series of positioning snapshots of one derivative on one venue.

    Args:
        instrument: The derivative (a perpetual swap written ``BASE/QUOTE:SETTLE``).
        venue: Where it trades: open interest and positioning differ by venue.
        source: Provenance (provider and download timestamp).
        frequency: Spacing of the snapshots.
        data: One column per :class:`PositioningField` the venue publishes, indexed by the
            instant of the snapshot (timezone-aware; kept in UTC). A missing snapshot of one
            field is ``NaN``; a row where every field is missing is dropped.
        value_currency: Currency of :attr:`PositioningField.OPEN_INTEREST_VALUE` (a venue
            may value it in another currency than the quote one: OKX in US dollars).

    Raises:
        InvalidSeriesError: Listing every problem found.
        DomainError: If the venue is empty, or a value is given without its currency.
    """

    instrument: Instrument
    venue: str
    source: DataSource
    frequency: Frequency
    data: InitVar[pd.DataFrame]
    value_currency: Currency | None = None
    _data: pd.DataFrame = field(init=False, repr=False)

    __match_args__ = ("instrument", "venue", "source", "frequency")

    def __post_init__(self, data: pd.DataFrame) -> None:
        if not self.venue.strip():
            raise DomainError("A positioning series needs the venue it describes")
        if self.frequency not in POSITIONING_FREQUENCIES:
            allowed = [frequency.value for frequency in POSITIONING_FREQUENCIES]
            raise DomainError(f"Positioning is read at {allowed}, not {self.frequency.value}")
        frame = _validated(data, f"{self.instrument.symbol}@{self.venue}")
        valued = PositioningField.OPEN_INTEREST_VALUE.value in frame.columns
        if valued and self.value_currency is None:
            raise DomainError("The value of the open interest needs its currency")
        object.__setattr__(self, "_data", frame)

    @property
    def symbol(self) -> str:
        """Instrument symbol."""
        return self.instrument.symbol

    @property
    def fields(self) -> tuple[PositioningField, ...]:
        """The fields the venue publishes, in the vocabulary's order."""
        present = set(self._data.columns)
        return tuple(member for member in PositioningField if member.value in present)

    @property
    def snapshots(self) -> pd.DataFrame:
        """A copy of every snapshot: one column per field."""
        return self._data.copy()

    def column(self, name: PositioningField | str) -> pd.Series:
        """The snapshots of one field (``NaN`` where the venue skipped one).

        Raises:
            KeyError: If the venue does not publish that field.
        """
        wanted = PositioningField(name).value
        if wanted not in self._data.columns:
            raise KeyError(f"{self.venue} publishes no {wanted} for {self.symbol}")
        return self._data[wanted].copy()

    @property
    def start(self) -> pd.Timestamp:
        """Instant of the first snapshot."""
        return pd.Timestamp(self._data.index[0])

    @property
    def end(self) -> pd.Timestamp:
        """Instant of the last snapshot."""
        return pd.Timestamp(self._data.index[-1])

    def __len__(self) -> int:
        return len(self._data)

    def latest(self) -> dict[PositioningField, float]:
        """The last value of every field (the last snapshot that has it)."""
        found: dict[PositioningField, float] = {}
        for member in self.fields:
            values = self._data[member.value].dropna()
            if len(values):
                found[member] = float(values.iloc[-1])
        return found

    def between(
        self, start: pd.Timestamp | str | None = None, end: pd.Timestamp | str | None = None
    ) -> PositioningSeries:
        """Sub-series with snapshots in ``[start, end]`` (both inclusive)."""
        return self._with(self._data.loc[start:end], self.frequency)

    def finished(self, now: pd.Timestamp | datetime) -> PositioningSeries:
        """Only the periods that had ended by ``now``: the one in progress still changes.

        Each row is labelled by the start of its period (see :meth:`resample`), so a row
        labelled 18:00 of an hourly series is known at 19:00.

        Raises:
            InvalidSeriesError: If no period had ended.
        """
        moment = pd.Timestamp(now)
        length = pd.Timedelta(minutes=self.frequency.minutes or 0) or pd.Timedelta(days=1)
        # A period has ended once its start is a whole period behind ``now``.
        return self._with(self._data.loc[: moment - length], self.frequency)

    def resample(self, frequency: Frequency | str) -> PositioningSeries:
        """The last snapshot of each period of ``frequency``, labelled by the period's start.

        An hourly value is the state at the end of that hour (its last snapshot): joined to
        an hourly bar, it is known when the bar closes. A period without snapshots stays
        absent.

        Raises:
            DomainError: If ``frequency`` is finer than the series or not one positioning is
                read at.
        """
        target = Frequency(frequency)
        if target not in POSITIONING_FREQUENCIES:
            allowed = [member.value for member in POSITIONING_FREQUENCIES]
            raise DomainError(f"Positioning is read at {allowed}, not {target.value}")
        if target.is_finer_than(self.frequency):
            raise DomainError(
                f"{self.frequency.value} snapshots cannot be read at {target.value}: "
                "that would invent the ones in between"
            )
        if target is self.frequency:
            return self
        # Periods start at midnight UTC and every multiple of the frequency after it.
        last = self._data.resample(target.pandas_rule, label="left", closed="left").last()
        return self._with(last.dropna(how="all"), target)

    def _with(self, frame: pd.DataFrame, frequency: Frequency) -> PositioningSeries:
        return PositioningSeries(
            self.instrument,
            self.venue,
            self.source,
            frequency,
            frame,
            value_currency=self.value_currency,
        )

    @classmethod
    def from_fields(
        cls,
        instrument: Instrument,
        venue: str,
        source: DataSource,
        frequency: Frequency,
        columns: Iterable[tuple[PositioningField, pd.Series]],
        *,
        value_currency: Currency | None = None,
    ) -> PositioningSeries:
        """Build a series from one Series per field, aligned on the union of their instants.

        A field missing at an instant of another one is ``NaN`` there: nothing is carried
        forward.
        """
        frame = pd.concat({member.value: series for member, series in columns}, axis=1, sort=True)
        return cls(
            instrument, venue, source, frequency, frame.sort_index(), value_currency=value_currency
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, PositioningSeries):
            return NotImplemented
        return (
            self.instrument == other.instrument
            and self.venue == other.venue
            and self.source == other.source
            and self.frequency is other.frequency
            and self.value_currency == other.value_currency
            and self._data.equals(other._data)
        )

    def __hash__(self) -> int:
        return hash((self.instrument, self.venue, self.frequency, self.start, self.end, len(self)))

    def __repr__(self) -> str:
        fields = ", ".join(member.value for member in self.fields)
        return (
            f"PositioningSeries({self.symbol}@{self.venue}, {self.frequency.value}, "
            f"{self.start.isoformat()} → {self.end.isoformat()}, n={len(self)}, [{fields}])"
        )
