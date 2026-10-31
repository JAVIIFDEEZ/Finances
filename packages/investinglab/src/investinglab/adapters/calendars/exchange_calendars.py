"""Trading calendars from the ``exchange_calendars`` library (offline holiday rules).

The library encodes the holiday rules of 50+ venues, so session lists are computed locally
without any network call.
"""

from __future__ import annotations

import warnings
from threading import Lock
from typing import TYPE_CHECKING, Any, Final

import exchange_calendars as xcals
import pandas as pd

from investinglab.ports.calendar import CalendarUnavailableError

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import date

__all__ = ["DEFAULT_ALIASES", "ExchangeCalendarsAdapter"]

DEFAULT_ALIASES: Final[Mapping[str, str]] = {
    "XNAS": "XNYS",  # Nasdaq shares the NYSE holiday schedule
    "ARCX": "XNYS",  # NYSE Arca
    "CRYPTO": "24/7",
}
"""InvestingLab venue codes mapped to ``exchange_calendars`` names when they differ."""


class ExchangeCalendarsAdapter:
    """:class:`~investinglab.ports.calendar.TradingCalendar` backed by ``exchange_calendars``.

    Args:
        aliases: Extra or overriding venue-code mappings.
    """

    def __init__(self, aliases: Mapping[str, str] | None = None) -> None:
        self._aliases = {**DEFAULT_ALIASES, **(aliases or {})}
        self._names = frozenset(xcals.get_calendar_names(include_aliases=True))
        self._cache: dict[tuple[str, int, int], Any] = {}
        self._lock = Lock()

    def _name(self, exchange_code: str) -> str:
        return self._aliases.get(exchange_code, exchange_code)

    def supports(self, exchange_code: str) -> bool:
        """Whether the venue has a known calendar."""
        return self._name(exchange_code) in self._names

    def sessions(self, exchange_code: str, start: date, end: date) -> pd.DatetimeIndex:
        """Session labels of the venue between ``start`` and ``end`` (inclusive).

        Raises:
            CalendarUnavailableError: Unknown venue or dates outside the calendar's bounds.
        """
        name = self._name(exchange_code)
        if name not in self._names:
            raise CalendarUnavailableError(f"No trading calendar for venue {exchange_code!r}")
        try:
            with warnings.catch_warnings():
                # The library still uses pandas APIs deprecated in pandas 3.
                warnings.simplefilter("ignore", category=FutureWarning)
                warnings.simplefilter("ignore", category=DeprecationWarning)
                calendar = self._calendar(name, start.year, end.year)
                sessions = calendar.sessions_in_range(pd.Timestamp(start), pd.Timestamp(end))
        except (ValueError, KeyError) as error:
            raise CalendarUnavailableError(
                f"Calendar {name!r} cannot provide sessions for {start}..{end}: {error}"
            ) from error
        return pd.DatetimeIndex(sessions).tz_localize(None).as_unit("ns")

    def _calendar(self, name: str, first_year: int, last_year: int) -> Any:  # noqa: ANN401
        key = (name, first_year, last_year)
        with self._lock:
            if key not in self._cache:
                self._cache[key] = xcals.get_calendar(
                    name,
                    start=pd.Timestamp(year=first_year, month=1, day=1),
                    end=pd.Timestamp(year=last_year, month=12, day=31),
                )
            return self._cache[key]
