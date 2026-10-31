"""Time concepts: observation frequencies and market schedules.

Time representation (ADR-0007):

* **Intraday** observations are indexed by timezone-aware UTC timestamps (bar open time).
* **Daily and lower** frequencies are indexed by *session labels*: timezone-naive dates at
  midnight, interpreted in the market's own timezone (stored as instrument metadata). This
  avoids the classic bug where a Madrid session shifts to the previous day once converted to
  UTC or New York time.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum

import pandas as pd

from investinglab.domain.errors import DomainError

__all__ = [
    "CRYPTO_SCHEDULE",
    "EQUITY_SCHEDULE",
    "FX_SCHEDULE",
    "Frequency",
    "MarketSchedule",
]


class Frequency(StrEnum):
    """Sampling frequency of a series, from one minute to one year."""

    MINUTE_1 = "1m"
    MINUTE_5 = "5m"
    MINUTE_15 = "15m"
    MINUTE_30 = "30m"
    HOUR_1 = "1h"
    HOUR_4 = "4h"
    DAY_1 = "1d"
    WEEK_1 = "1w"
    MONTH_1 = "1mo"
    QUARTER_1 = "1q"
    YEAR_1 = "1y"

    @property
    def is_intraday(self) -> bool:
        """``True`` for frequencies finer than one day."""
        return self in _INTRADAY_MINUTES

    @property
    def minutes(self) -> int | None:
        """Bar length in minutes for intraday frequencies, ``None`` otherwise."""
        return _INTRADAY_MINUTES.get(self)

    @property
    def rank(self) -> int:
        """Position from finest (0) to coarsest; used to validate resampling."""
        return list(Frequency).index(self)

    def is_finer_than(self, other: Frequency) -> bool:
        """Whether this frequency samples more often than ``other``."""
        return self.rank < other.rank

    @property
    def pandas_rule(self) -> str:
        """Resampling rule understood by :meth:`pandas.DataFrame.resample`."""
        return _PANDAS_RULES[self]

    @property
    def min_spacing(self) -> pd.Timedelta:
        """Smallest admissible gap between two consecutive observations.

        Used as a sanity check that the declared frequency matches the data: daily bars
        one minute apart reveal a mislabelled series. Calendar frequencies use conservative
        lower bounds because holidays move period labels by a few days.
        """
        minutes = self.minutes
        if minutes is not None:
            return pd.Timedelta(minutes=minutes)
        return _MIN_SPACING[self]


_INTRADAY_MINUTES: dict[Frequency, int] = {
    Frequency.MINUTE_1: 1,
    Frequency.MINUTE_5: 5,
    Frequency.MINUTE_15: 15,
    Frequency.MINUTE_30: 30,
    Frequency.HOUR_1: 60,
    Frequency.HOUR_4: 240,
}

_PANDAS_RULES: dict[Frequency, str] = {
    Frequency.MINUTE_1: "1min",
    Frequency.MINUTE_5: "5min",
    Frequency.MINUTE_15: "15min",
    Frequency.MINUTE_30: "30min",
    Frequency.HOUR_1: "1h",
    Frequency.HOUR_4: "4h",
    Frequency.DAY_1: "1D",
    Frequency.WEEK_1: "W-SUN",
    Frequency.MONTH_1: "ME",
    Frequency.QUARTER_1: "QE",
    Frequency.YEAR_1: "YE",
}

_MIN_SPACING: dict[Frequency, pd.Timedelta] = {
    Frequency.DAY_1: pd.Timedelta(days=1),
    Frequency.WEEK_1: pd.Timedelta(days=3),
    Frequency.MONTH_1: pd.Timedelta(days=20),
    Frequency.QUARTER_1: pd.Timedelta(days=60),
    Frequency.YEAR_1: pd.Timedelta(days=300),
}

_PERIODS_PER_YEAR_CALENDAR: dict[Frequency, float] = {
    Frequency.WEEK_1: 52.0,
    Frequency.MONTH_1: 12.0,
    Frequency.QUARTER_1: 4.0,
    Frequency.YEAR_1: 1.0,
}


@dataclass(frozen=True, slots=True)
class MarketSchedule:
    """Trading schedule facts needed to annualise statistics.

    Attributes:
        sessions_per_year: Trading sessions in a typical year (252 for equities by
            convention, 365 for crypto, 260 for FX).
        session_hours: Length of a trading session in hours (24 for continuous markets).
    """

    sessions_per_year: float
    session_hours: float

    def __post_init__(self) -> None:
        if not 0 < self.sessions_per_year <= 366:  # noqa: PLR2004
            raise DomainError(f"sessions_per_year out of range: {self.sessions_per_year}")
        if not 0 < self.session_hours <= 24:  # noqa: PLR2004
            raise DomainError(f"session_hours out of range: {self.session_hours}")

    @property
    def is_continuous(self) -> bool:
        """Whether the market trades around the clock."""
        return self.session_hours == 24  # noqa: PLR2004

    def periods_per_year(self, frequency: Frequency) -> float:
        """Number of observations of ``frequency`` in a year on this schedule.

        Intraday frequencies count the bars that fit in a session (a partial last bar
        counts as one): a 6.5-hour session holds 7 one-hour bars.
        """
        minutes = frequency.minutes
        if minutes is not None:
            bars_per_session = math.ceil(self.session_hours * 60 / minutes)
            return self.sessions_per_year * bars_per_session
        if frequency is Frequency.DAY_1:
            return self.sessions_per_year
        return _PERIODS_PER_YEAR_CALENDAR[frequency]


EQUITY_SCHEDULE = MarketSchedule(sessions_per_year=252, session_hours=6.5)
"""Generic equity market (252 sessions per year by industry convention)."""
CRYPTO_SCHEDULE = MarketSchedule(sessions_per_year=365, session_hours=24)
"""Crypto-assets trade 24/7."""
FX_SCHEDULE = MarketSchedule(sessions_per_year=260, session_hours=24)
"""Spot FX trades 24 hours a day, five days a week."""
