"""Quoting conventions of interest rates (ADR-0020).

Money-market rates are quoted as simple annual rates on a day-count basis: an overnight
€STR of 3.5 % pays ``3.5 % x days / 360``. The metrics need effective annual rates
(compounded), so every quoted rate is converted with its convention before use.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final, overload

import pandas as pd

from investinglab.domain.errors import DomainError

__all__ = ["DAYS_PER_YEAR", "OVERNIGHT_ACT_360", "DayCount", "RateConvention"]

DAYS_PER_YEAR: Final = 365.0
"""Calendar days over which a term rate is rolled to get its effective annual rate."""


class DayCount(StrEnum):
    """Day-count basis of a quoted rate."""

    ACT_360 = "act/360"
    """Actual days over a 360-day year: euro and US dollar money markets (€STR, SOFR)."""
    ACT_365 = "act/365"
    """Actual days over a 365-day year: sterling markets and US bill yields on an
    investment basis."""

    @property
    def year_days(self) -> float:
        """Days in the conventional year."""
        return 360.0 if self is DayCount.ACT_360 else 365.0


@dataclass(frozen=True, slots=True)
class RateConvention:
    """How a quoted annual rate accrues: simple interest over a term that is rolled over.

    Attributes:
        day_count: Day-count basis of the quote.
        term_days: Calendar days the quoted rate applies to (1 for an overnight rate, 91 for
            a three-month bill).
    """

    day_count: DayCount = DayCount.ACT_360
    term_days: int = 1

    def __post_init__(self) -> None:
        if self.term_days < 1:
            raise DomainError("A rate convention needs a term of at least one day")

    @overload
    def effective_annual(self, rate: float) -> float: ...

    @overload
    def effective_annual(self, rate: pd.Series) -> pd.Series: ...

    def effective_annual(self, rate: float | pd.Series) -> float | pd.Series:
        """Effective annual (compounded) rate of a quoted annual rate, both in decimal form.

        The term is rolled over a 365-day year: ``(1 + r x term / basis) ** (365 / term) - 1``.
        An overnight €STR of 3.5 % (ACT/360) is an effective 3.61 % a year; a three-month
        bill yielding 5.25 % (ACT/365) is an effective 5.35 %. Missing rates stay missing.
        """
        growth = 1.0 + rate * (self.term_days / self.day_count.year_days)
        effective = growth ** (DAYS_PER_YEAR / self.term_days) - 1.0
        return effective if isinstance(effective, pd.Series) else float(effective)


OVERNIGHT_ACT_360: Final = RateConvention(DayCount.ACT_360, term_days=1)
"""Overnight money-market rate on ACT/360 (€STR, ECB deposit facility, SOFR)."""
