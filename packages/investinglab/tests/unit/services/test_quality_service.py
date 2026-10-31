from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from investinglab.adapters.calendars import ExchangeCalendarsAdapter
from investinglab.domain import EXCHANGES, USD, AssetClass, Frequency, IssueKind
from investinglab.ports import CalendarUnavailableError
from investinglab.services import DataQualityService
from support.factories import gbm_prices, make_series

MADRID_2024 = pd.bdate_range("2024-01-02", "2024-12-30")


@pytest.fixture(scope="module")
def service() -> DataQualityService:
    return DataQualityService(ExchangeCalendarsAdapter())


def test_holidays_are_not_reported_as_missing(service: DataQualityService) -> None:
    sessions = ExchangeCalendarsAdapter().sessions("XMAD", date(2024, 1, 2), date(2024, 12, 30))
    series = make_series(gbm_prices(len(sessions), seed=31), index=sessions)

    report = service.assess(series)

    assert not report.issues_of(IssueKind.MISSING_SESSIONS)
    assert report.expected_sessions == len(sessions)


def test_business_days_on_holidays_are_unexpected(service: DataQualityService) -> None:
    series = make_series(gbm_prices(len(MADRID_2024), seed=32), index=MADRID_2024)

    report = service.assess(series)

    (extra,) = report.issues_of(IssueKind.UNEXPECTED_SESSIONS)
    assert pd.Timestamp("2024-04-01") in extra.timestamps  # Easter Monday in Madrid


def test_series_without_a_known_calendar(service: DataQualityService) -> None:
    fx = make_series(
        symbol="EURUSD=X", currency=USD, asset_class=AssetClass.FX, exchange=EXCHANGES["FX"]
    )
    unknown_venue = make_series(exchange=None)

    assert service.expected_sessions(fx) is None
    assert service.expected_sessions(unknown_venue) is None
    assert DataQualityService().expected_sessions(make_series()) is None


def test_intraday_series_use_local_session_dates(service: DataQualityService) -> None:
    index = pd.date_range("2024-03-04 15:00", periods=3, freq="1h", tz="UTC")
    series = make_series(
        [1.0, 2.0, 3.0], index=index, frequency=Frequency.HOUR_1, exchange=EXCHANGES["XNYS"]
    )

    sessions = service.expected_sessions(series)

    assert sessions is not None
    assert list(sessions) == [pd.Timestamp("2024-03-04")]


class _FailingCalendar:
    def supports(self, exchange_code: str) -> bool:
        return True

    def sessions(self, exchange_code: str, start: date, end: date) -> pd.DatetimeIndex:
        raise CalendarUnavailableError("no data for those years")


def test_calendar_failures_degrade_gracefully() -> None:
    service = DataQualityService(_FailingCalendar())

    report = service.assess(make_series())

    assert report.expected_sessions is None


def test_assess_many(service: DataQualityService) -> None:
    reports = service.assess_many([make_series(symbol="A"), make_series(symbol="B")])

    assert set(reports) == {"A", "B"}
