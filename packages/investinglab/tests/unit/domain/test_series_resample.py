from __future__ import annotations

import pandas as pd
import pytest

from investinglab.domain import EXCHANGES, DomainError, Frequency, PriceSeries
from support.factories import SYNTHETIC_SOURCE, make_instrument, make_series


def _daily_ohlcv() -> PriceSeries:
    # Three weeks; Friday 2024-01-12 is missing (e.g. a holiday) and must not be invented.
    index = pd.DatetimeIndex(
        [
            "2024-01-08",
            "2024-01-09",
            "2024-01-10",
            "2024-01-11",
            "2024-01-15",
            "2024-01-16",
            "2024-01-17",
            "2024-01-18",
            "2024-01-19",
            "2024-01-22",
            "2024-01-23",
        ]
    )
    data = pd.DataFrame(
        {
            "open": [10, 11, 12, 13, 20, 21, 22, 23, 24, 30, 31],
            "high": [15, 16, 17, 18, 25, 26, 27, 28, 29, 35, 36],
            "low": [5, 6, 7, 8, 15, 16, 17, 18, 19, 25, 26],
            "close": [11, 12, 13, 14, 21, 22, 23, 24, 25, 31, 32],
            "volume": [1, 1, 1, 1, 2, 2, 2, 2, 2, 3, 3],
        },
        index=index,
        dtype="float64",
    )
    return PriceSeries(make_instrument(), Frequency.DAY_1, SYNTHETIC_SOURCE, data)


def test_weekly_resample_aggregates_ohlcv_and_labels_by_last_observed_session() -> None:
    weekly = _daily_ohlcv().resample(Frequency.WEEK_1).bars

    assert list(weekly.index) == list(pd.DatetimeIndex(["2024-01-11", "2024-01-19", "2024-01-23"]))
    assert weekly["open"].tolist() == [10, 20, 30]
    assert weekly["high"].tolist() == [18, 29, 36]
    assert weekly["low"].tolist() == [5, 15, 25]
    assert weekly["close"].tolist() == [14, 25, 32]
    assert weekly["volume"].tolist() == [4, 10, 6]


def test_monthly_resample_drops_empty_periods() -> None:
    index = pd.DatetimeIndex(["2024-01-31", "2024-03-28", "2024-04-30"])  # no February data
    series = make_series([100.0, 110.0, 121.0], index=index)

    monthly = series.resample("1mo")

    assert list(monthly.bars.index) == list(index)
    assert monthly.frequency is Frequency.MONTH_1


def test_intraday_resample_keeps_bar_open_labels() -> None:
    index = pd.date_range("2024-03-15 14:30", periods=15, freq="1min", tz="UTC")
    series = make_series(
        [float(i) for i in range(1, 16)],
        index=index,
        frequency=Frequency.MINUTE_1,
        exchange=EXCHANGES["XNYS"],
    )

    bars = series.resample(Frequency.MINUTE_5).bars

    assert list(bars.index) == list(
        pd.date_range("2024-03-15 14:30", periods=3, freq="5min", tz="UTC")
    )
    assert bars["close"].tolist() == [5.0, 10.0, 15.0]


def test_intraday_to_daily_uses_the_market_session_date() -> None:
    # 09:00-09:02 in Tokyo is 00:00-00:02 UTC: the session date is the Tokyo date.
    index = pd.date_range("2024-03-15 00:00", periods=3, freq="1min", tz="UTC")
    later = pd.date_range("2024-03-18 00:00", periods=3, freq="1min", tz="UTC")
    third = pd.date_range("2024-03-19 00:00", periods=3, freq="1min", tz="UTC")
    series = make_series(
        [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0],
        index=pd.DatetimeIndex(index.append(later).append(third)),
        frequency=Frequency.MINUTE_1,
        exchange=EXCHANGES["XTKS"],
    )

    daily = series.resample(Frequency.DAY_1)

    assert list(daily.bars.index) == list(
        pd.DatetimeIndex(["2024-03-15", "2024-03-18", "2024-03-19"])
    )
    assert daily.prices.tolist() == [3.0, 6.0, 9.0]


def test_intraday_to_weekly_goes_through_sessions() -> None:
    index = pd.DatetimeIndex([])
    for day in pd.bdate_range("2024-03-04", periods=15):
        index = pd.DatetimeIndex(
            index.append(
                pd.date_range(day + pd.Timedelta(hours=15), periods=2, freq="1h", tz="UTC")
            )
        )
    series = make_series(
        [float(i) for i in range(1, 31)],
        index=index,
        frequency=Frequency.HOUR_1,
        exchange=EXCHANGES["XNYS"],
    )

    weekly = series.resample(Frequency.WEEK_1)

    assert len(weekly) == 3
    assert weekly.prices.tolist() == [10.0, 20.0, 30.0]


@pytest.mark.parametrize("target", [Frequency.DAY_1, Frequency.MINUTE_5])
def test_resampling_to_an_equal_or_finer_frequency_is_rejected(target: Frequency) -> None:
    with pytest.raises(DomainError, match="coarser"):
        make_series().resample(target)
