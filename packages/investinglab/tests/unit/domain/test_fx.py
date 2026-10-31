from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pandas as pd
import pytest

from investinglab.domain import (
    EUR,
    EXCHANGES,
    GBP,
    USD,
    CurrencyPair,
    DataSource,
    DomainError,
    Frequency,
    FxRates,
    InvalidSeriesError,
    currency_attribution,
)
from support.factories import SYNTHETIC_SOURCE, make_fx_series, make_series

EURUSD = CurrencyPair(EUR, USD)
DAYS = pd.bdate_range("2024-01-01", periods=5)


def _rates(values: list[float], index: pd.DatetimeIndex = DAYS) -> FxRates:
    return FxRates(EURUSD, SYNTHETIC_SOURCE, pd.Series(values, index=index))


@pytest.mark.parametrize(
    ("data", "fragment"),
    [
        (pd.Series([], dtype=float, index=pd.DatetimeIndex([])), "at least one"),
        (pd.Series([1.1, 0.0], index=DAYS[:2]), "strictly positive"),
        (pd.Series([1.1, np.nan], index=DAYS[:2]), "strictly positive"),
        (pd.Series([1.1, 1.2], index=DAYS[[1, 0]]), "sorted"),
        (pd.Series([1.1, 1.2], index=DAYS[[0, 0]]), "duplicated"),
        (pd.Series([1.1], index=pd.DatetimeIndex(["2024-01-01 16:00"])), "midnight"),
        (pd.Series([1.1], index=[0]), "DatetimeIndex"),
    ],
)
def test_invalid_rates_are_rejected(data: pd.Series, fragment: str) -> None:
    with pytest.raises(InvalidSeriesError, match=fragment):
        FxRates(EURUSD, SYNTHETIC_SOURCE, data)


def test_rates_must_be_a_series() -> None:
    with pytest.raises(InvalidSeriesError, match="Series"):
        FxRates(EURUSD, SYNTHETIC_SOURCE, [1.1])  # type: ignore[arg-type]


def test_from_price_series_checks_the_quote_currency() -> None:
    series = make_fx_series([1.10, 1.11, 1.12])

    rates = FxRates.from_price_series(series, EURUSD)

    assert rates.rates.tolist() == [1.10, 1.11, 1.12]
    assert rates.rates.name == "EURUSD"
    assert not rates.is_intraday
    with pytest.raises(DomainError, match="quoted in USD"):
        FxRates.from_price_series(series, CurrencyPair(USD, EUR))


def test_inverse() -> None:
    inverse = _rates([1.25, 2.0, 1.6, 1.25, 1.0]).inverse()

    assert inverse.pair == CurrencyPair(USD, EUR)
    assert inverse.rates.tolist() == pytest.approx([0.8, 0.5, 0.625, 0.8, 1.0])


def test_rates_at_uses_the_latest_fixing_within_staleness() -> None:
    rates = _rates([1.1, 1.2], index=pd.DatetimeIndex(["2024-01-02", "2024-01-05"]))
    dates = pd.DatetimeIndex(["2024-01-01", "2024-01-02", "2024-01-04", "2024-01-05", "2024-01-20"])

    found = rates.rates_at(dates, max_staleness=pd.Timedelta(days=7))

    assert np.isnan(found.iloc[0])  # before the first fixing
    assert found.iloc[1:4].tolist() == [1.1, 1.1, 1.2]
    assert np.isnan(found.iloc[4])  # fixing too old


def test_intraday_prices_use_the_previous_days_fixing() -> None:
    rates = _rates([1.1, 1.2], index=pd.DatetimeIndex(["2024-01-02", "2024-01-03"]))
    bars = pd.DatetimeIndex(["2024-01-02 15:00", "2024-01-03 15:00", "2024-01-04 09:00"], tz="UTC")

    found = rates.rates_at(bars)

    assert np.isnan(found.iloc[0])  # the 2024-01-02 fixing is only usable from 01-03
    assert found.iloc[1:].tolist() == [1.1, 1.2]


def test_daily_prices_cannot_use_intraday_rates() -> None:
    intraday = _rates(
        [1.1, 1.2], index=pd.DatetimeIndex(["2024-01-02 10:00", "2024-01-02 11:00"], tz="UTC")
    )

    assert intraday.is_intraday
    with pytest.raises(DomainError, match="daily fixings"):
        intraday.rates_at(DAYS)


def test_convert_base_currency_prices_into_the_quote() -> None:
    eur_series = make_series(
        [100.0, 101.0, 102.0, 103.0, 104.0], index=DAYS, volume=[1, 2, 3, 4, 5]
    )
    rates = _rates([1.10, 1.10, 1.20, 1.20, 1.25])

    converted = rates.convert(eur_series)

    assert converted.currency == USD
    assert converted.prices.tolist() == pytest.approx([110.0, 111.1, 122.4, 123.6, 130.0])
    assert converted.column("volume").tolist() == [1, 2, 3, 4, 5]
    assert "in USD via EURUSD" in (converted.source.dataset or "")
    assert converted.symbol == eur_series.symbol


def test_convert_quote_currency_prices_into_the_base() -> None:
    usd_series = make_series(
        [110.0, 121.0, 132.0],
        symbol="SPY",
        currency=USD,
        index=DAYS[:3],
        exchange=EXCHANGES["XNYS"],
    )
    rates = _rates([1.10, 1.10, 1.20], index=DAYS[:3])

    converted = rates.convert(usd_series)

    assert converted.currency == EUR
    assert converted.prices.tolist() == pytest.approx([100.0, 110.0, 110.0])


def test_prices_without_a_fixing_are_dropped_not_filled() -> None:
    series = make_series([100.0, 101.0, 102.0, 103.0, 104.0], index=DAYS)
    rates = _rates([1.1, 1.2, 1.3, 1.4], index=DAYS[1:])

    converted = rates.convert(series)

    assert len(converted) == 4
    assert converted.start == DAYS[1]
    assert rates.coverage(series) == pytest.approx(0.8)


def test_converting_an_unrelated_currency_fails() -> None:
    gbp_series = make_series(symbol="VOD.L", currency=GBP, exchange=EXCHANGES["XLON"])

    with pytest.raises(DomainError, match="Cannot convert"):
        _rates([1.1] * 5).convert(gbp_series)


def test_the_newest_download_time_is_kept() -> None:
    later = DataSource("ecb", datetime(2026, 6, 1, tzinfo=UTC))
    rates = FxRates(EURUSD, later, pd.Series([1.1] * 5, index=DAYS))

    converted = rates.convert(make_series(index=DAYS))

    assert converted.retrieved_at == later.retrieved_at


def test_currency_attribution_identity() -> None:
    local = make_series([100.0, 110.0, 99.0, 108.9, 120.0], index=DAYS)
    converted = _rates([1.0, 1.1, 1.0, 1.2, 1.2]).convert(local)

    attribution = currency_attribution(local, converted)

    product = (1 + attribution["local"]) * (1 + attribution["currency"])
    assert np.allclose(product, 1 + attribution["total"])
    assert attribution["currency"].iloc[0] == pytest.approx(0.1)
    assert attribution["cum_total"].iloc[-1] == pytest.approx(144.0 / 100.0 - 1)
    with pytest.raises(DomainError, match="same instrument"):
        currency_attribution(local, make_series(symbol="OTHER", index=DAYS))


def test_intraday_conversion_end_to_end() -> None:
    index = pd.date_range("2024-01-03 14:30", periods=4, freq="1h", tz="UTC")
    series = make_series(
        [10.0, 11.0, 12.0, 13.0],
        index=index,
        symbol="AAPL",
        currency=USD,
        frequency=Frequency.HOUR_1,
        exchange=EXCHANGES["XNYS"],
    )
    rates = _rates([1.25, 1.0], index=pd.DatetimeIndex(["2024-01-02", "2024-01-03"]))

    converted = rates.convert(series)

    assert converted.prices.tolist() == pytest.approx([8.0, 8.8, 9.6, 10.4])
