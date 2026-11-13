"""Holding rates: what a position pays or earns per period just for being open.

A perpetual swap charges *funding* every few hours, a short pays to *borrow* the shares, a
leveraged long pays to *finance* the position. They are all the same thing to a backtest or
a carry study: a rate per accrual period, attached to an instrument on a venue. They are not
prices (they are often negative) and not macro series (they belong to an instrument), so
they get their own validated type (ADR-0031).
"""

from __future__ import annotations

from dataclasses import InitVar, dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Final, Literal

import numpy as np
import pandas as pd

from investinglab.domain.errors import DomainError, InvalidSeriesError
from investinglab.domain.series import TIME_INDEX_NAME, DataSource

if TYPE_CHECKING:
    from investinglab.domain.instruments import Instrument

__all__ = ["RateKind", "RateSeries", "Side"]

type Side = Literal["long", "short"]

DAYS_PER_YEAR: Final = 365.0
MAX_RATE_PER_PERIOD: Final = 1.0
"""A rate of 100 % in one accrual period is a unit mistake (percent sent as decimal)."""


class RateKind(StrEnum):
    """What a holding rate is, which fixes who pays whom when it is positive."""

    FUNDING = "funding"
    """Funding of a perpetual swap. Positive: longs pay shorts. Negative: shorts pay longs."""
    BORROW = "borrow"
    """Fee for borrowing the instrument to sell it short. Positive: the short pays the lender."""
    FINANCING = "financing"
    """Cost of financing a leveraged long (margin, repo, swap). Positive: the long pays."""

    @property
    def payer(self) -> Side:
        """The side that pays when the rate is positive."""
        return "short" if self is RateKind.BORROW else "long"

    @property
    def is_exchanged(self) -> bool:
        """Whether the other side of the market receives what the payer pays."""
        return self is RateKind.FUNDING


def _validated_index(index: pd.Index, problems: list[str]) -> pd.DatetimeIndex | None:
    if not isinstance(index, pd.DatetimeIndex):
        problems.append(f"index must be a DatetimeIndex, got {type(index).__name__}")
        return None
    if index.tz is None:
        problems.append("rates settle at instants: the index must be timezone-aware")
    else:
        index = index.tz_convert("UTC")
    if len(index) == 0:
        problems.append("needs at least one observation")
    if index.has_duplicates:
        problems.append("duplicated settlement instants")
    if not index.is_monotonic_increasing:
        problems.append("index must be sorted in increasing time order")
    return index


def _validated_values(data: pd.Series, problems: list[str]) -> pd.Series | None:
    if not pd.api.types.is_numeric_dtype(data) or pd.api.types.is_bool_dtype(data):
        problems.append(f"rates must be numeric, got {data.dtype}")
        return None
    values = data.astype("float64")
    if not np.isfinite(values).all():
        problems.append("rates must be finite; a period without a rate is an absent row")
    elif (values.abs() >= MAX_RATE_PER_PERIOD).any():
        problems.append(
            f"a rate of {values.abs().max():.2f} per period is not plausible: rates are "
            "decimals per accrual period (0.0001 = 0.01 %)"
        )
    return values


def _validated_rates(
    data: object, subject: str, interval: pd.Timedelta | None
) -> tuple[pd.Series, pd.Timedelta]:
    if not isinstance(data, pd.Series):
        raise InvalidSeriesError(subject, [f"rates must be a Series, got {type(data).__name__}"])
    problems: list[str] = []
    index = _validated_index(data.index, problems)
    values = _validated_values(data, problems)
    if interval is None and not problems and index is not None:
        if len(index) < 2:  # noqa: PLR2004 - two instants make one spacing
            problems.append("give the accrual interval: it cannot be inferred from one payment")
        else:
            interval = pd.Timedelta(index.to_series().diff().median())
    if interval is not None and interval <= pd.Timedelta(0):
        problems.append("the accrual interval must be positive")
    if problems or index is None or values is None or interval is None:
        raise InvalidSeriesError(subject, problems)
    rates = pd.Series(
        values.to_numpy(), index=index.as_unit("ns").rename(TIME_INDEX_NAME), name="rate"
    )
    return rates, interval


@dataclass(frozen=True, slots=True, eq=False)
class RateSeries:
    """An immutable, validated series of holding rates of one instrument on one venue.

    Args:
        instrument: The instrument held.
        venue: Where it is held (``binance``, ``okx``, a broker…): rates differ by venue.
        kind: What the rate is (see :class:`RateKind` for the sign).
        source: Provenance (provider and download timestamp).
        data: Rate of each accrual period as a decimal (0.0001 = 0.01 %), indexed by the
            instant it settles (timezone-aware; kept in UTC).
        interval: Length of an accrual period; the median spacing of the data by default.

    Raises:
        InvalidSeriesError: Listing every problem found.
    """

    instrument: Instrument
    venue: str
    kind: RateKind
    source: DataSource
    data: InitVar[pd.Series]
    interval: pd.Timedelta | None = None
    _rates: pd.Series = field(init=False, repr=False)

    __match_args__ = ("instrument", "venue", "kind", "source")

    def __post_init__(self, data: pd.Series) -> None:
        if not self.venue.strip():
            raise DomainError("A rate series needs the venue the rates apply on")
        subject = f"{self.instrument.symbol}@{self.venue}"
        rates, interval = _validated_rates(data, subject, self.interval)
        object.__setattr__(self, "_rates", rates)
        object.__setattr__(self, "interval", interval)

    @property
    def symbol(self) -> str:
        """Instrument symbol."""
        return self.instrument.symbol

    @property
    def rates(self) -> pd.Series:
        """A copy of the rate of each accrual period (decimal)."""
        return self._rates.copy()

    @property
    def start(self) -> pd.Timestamp:
        """Instant of the first settlement."""
        return pd.Timestamp(self._rates.index[0])

    @property
    def end(self) -> pd.Timestamp:
        """Instant of the last settlement."""
        return pd.Timestamp(self._rates.index[-1])

    def __len__(self) -> int:
        return len(self._rates)

    @property
    def periods_per_year(self) -> float:
        """Accrual periods in a 365-day year (1095 for an 8-hour funding)."""
        assert self.interval is not None  # noqa: S101 - set in __post_init__
        return pd.Timedelta(days=DAYS_PER_YEAR) / self.interval

    def annualized(self) -> pd.Series:
        """Each rate as a simple annual rate: what the period's rate would add up to in a year.

        It is how venues quote funding ("10.95 % APR"); it does not compound.
        """
        return (self._rates * self.periods_per_year).rename("annualized_rate")

    def cashflow(self, side: Side) -> pd.Series:
        """What a position of one unit of notional receives each period (negative: it pays).

        The payer pays the rate. The other side receives it only when the rate is exchanged
        between the two sides (funding); a borrow fee or a financing cost goes to a third
        party, so the other side gets nothing.
        """
        if side == self.kind.payer:
            flow = -self._rates
        elif self.kind.is_exchanged:
            flow = self._rates.copy()
        else:
            flow = self._rates * 0.0
        return flow.rename(f"{side}_cashflow")

    def accumulated(self, side: Side) -> float:
        """Total received by a unit position held over the whole series (negative: paid)."""
        return float(self.cashflow(side).sum())

    def between(
        self, start: pd.Timestamp | str | None = None, end: pd.Timestamp | str | None = None
    ) -> RateSeries:
        """Sub-series with settlements in ``[start, end]`` (both inclusive)."""
        return RateSeries(
            self.instrument,
            self.venue,
            self.kind,
            self.source,
            self._rates.loc[start:end],
            interval=self.interval,
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, RateSeries):
            return NotImplemented
        return (
            self.instrument == other.instrument
            and self.venue == other.venue
            and self.kind == other.kind
            and self.source == other.source
            and self.interval == other.interval
            and self._rates.equals(other._rates)
        )

    def __hash__(self) -> int:
        return hash((self.instrument, self.venue, self.kind, self.start, self.end, len(self)))

    def __repr__(self) -> str:
        return (
            f"RateSeries({self.symbol}@{self.venue}, {self.kind.value}, "
            f"{self.start.isoformat()} → {self.end.isoformat()}, n={len(self)}, "
            f"every {self.interval})"
        )
