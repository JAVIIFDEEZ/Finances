"""Port for official trading calendars (sessions of each market)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from investinglab.domain.errors import InvestingLabError

if TYPE_CHECKING:
    from datetime import date

    import pandas as pd

__all__ = ["CalendarUnavailableError", "TradingCalendar"]


class CalendarUnavailableError(InvestingLabError):
    """No official calendar is known for a venue (or for the requested dates)."""


@runtime_checkable
class TradingCalendar(Protocol):
    """Official trading sessions of each venue."""

    def supports(self, exchange_code: str) -> bool:
        """Whether sessions are known for the venue (``XMAD``, ``XNYS``, ``CRYPTO``...)."""
        ...

    def sessions(self, exchange_code: str, start: date, end: date) -> pd.DatetimeIndex:
        """Session labels (timezone-naive dates) between ``start`` and ``end`` inclusive.

        Raises:
            CalendarUnavailableError: If the venue or the date range is not supported.
        """
        ...
