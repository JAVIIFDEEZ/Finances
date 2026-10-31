from __future__ import annotations

from datetime import date

import exchange_calendars as xcals
import pandas as pd
import pytest

from investinglab.adapters.calendars import ExchangeCalendarsAdapter
from investinglab.ports import CalendarUnavailableError, TradingCalendar


@pytest.fixture(scope="module")
def calendar() -> ExchangeCalendarsAdapter:
    return ExchangeCalendarsAdapter()


def test_implements_the_port(calendar: ExchangeCalendarsAdapter) -> None:
    assert isinstance(calendar, TradingCalendar)


def test_madrid_closes_on_good_friday_and_easter_monday(
    calendar: ExchangeCalendarsAdapter,
) -> None:
    sessions = calendar.sessions("XMAD", date(2024, 3, 25), date(2024, 4, 5))

    assert pd.Timestamp("2024-03-29") not in sessions
    assert pd.Timestamp("2024-04-01") not in sessions
    assert len(sessions) == 8
    assert sessions.tz is None


def test_new_york_trades_on_easter_monday(calendar: ExchangeCalendarsAdapter) -> None:
    sessions = calendar.sessions("XNYS", date(2024, 3, 25), date(2024, 4, 5))

    assert pd.Timestamp("2024-04-01") in sessions


def test_aliases_and_crypto(calendar: ExchangeCalendarsAdapter) -> None:
    assert calendar.supports("XNAS")
    nasdaq = calendar.sessions("XNAS", date(2024, 7, 1), date(2024, 7, 5))
    assert pd.Timestamp("2024-07-04") not in nasdaq
    crypto = calendar.sessions("CRYPTO", date(2024, 7, 1), date(2024, 7, 7))
    assert len(crypto) == 7


def test_unknown_venues(calendar: ExchangeCalendarsAdapter) -> None:
    assert not calendar.supports("FX")
    with pytest.raises(CalendarUnavailableError, match="No trading calendar"):
        calendar.sessions("FX", date(2024, 1, 1), date(2024, 1, 31))


def test_custom_aliases() -> None:
    calendar = ExchangeCalendarsAdapter(aliases={"BME": "XMAD"})

    assert calendar.supports("BME")


def test_library_errors_become_calendar_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(*args: object, **kwargs: object) -> None:
        raise ValueError("out of bounds")

    monkeypatch.setattr(xcals, "get_calendar", broken)

    with pytest.raises(CalendarUnavailableError, match="out of bounds"):
        ExchangeCalendarsAdapter().sessions("XMAD", date(1800, 1, 1), date(1800, 12, 31))
