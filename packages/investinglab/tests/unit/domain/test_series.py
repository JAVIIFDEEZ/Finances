from __future__ import annotations

import dataclasses
import math
from datetime import datetime

import numpy as np
import pandas as pd
import pytest

from investinglab.domain import (
    EUR,
    EXCHANGES,
    AssetClass,
    DataSource,
    DomainError,
    Frequency,
    InvalidSeriesError,
    PriceAdjustment,
    PriceField,
    PriceSeries,
    ReturnKind,
)
from support.factories import SYNTHETIC_SOURCE, make_bars, make_instrument, make_series


def _series(data: pd.DataFrame, frequency: Frequency = Frequency.DAY_1) -> PriceSeries:
    return PriceSeries(make_instrument(), frequency, SYNTHETIC_SOURCE, data)


# ── Automatic statistics (B1-T1 §4.3) ──────────────────────────────────


def test_statistics_are_computed_when_the_series_is_created() -> None:
    series = make_series([100.0, 110.0, 99.0, 108.9])
    returns = np.array([0.10, -0.10, 0.10])

    stats = series.stats

    assert stats.n_observations == 4
    assert stats.mean_return == pytest.approx(returns.mean())
    assert stats.std_return == pytest.approx(returns.std(ddof=1))
    assert stats.mean_log_return == pytest.approx(np.log(1 + returns).mean())
    assert stats.std_log_return == pytest.approx(np.log(1 + returns).std(ddof=1))
    assert stats.total_return == pytest.approx(0.089)
    assert stats.max_drawdown == pytest.approx(-0.10)
    assert stats.periods_per_year == 252
    assert stats.annualized_volatility == pytest.approx(returns.std(ddof=1) * math.sqrt(252))
    assert stats.annualized_return == pytest.approx(1.089 ** (252 / 3) - 1)
    assert stats.start == pd.Timestamp("2024-01-02")
    assert stats.end == pd.Timestamp("2024-01-05")


def test_metadata_is_exposed() -> None:
    series = make_series()

    assert series.symbol == "TEST.MC"
    assert series.name == "Synthetic TEST.MC"
    assert series.asset_class is AssetClass.EQUITY
    assert series.currency == EUR
    assert series.timezone == "Europe/Madrid"
    assert series.retrieved_at == SYNTHETIC_SOURCE.retrieved_at
    assert series.frequency is Frequency.DAY_1
    assert series.adjustment is PriceAdjustment.RAW
    assert len(series) == 5
    assert "TEST.MC" in repr(series)


def test_crypto_series_annualise_with_365_days() -> None:
    series = make_series(asset_class=AssetClass.CRYPTO, exchange=EXCHANGES["CRYPTO"])

    assert series.periods_per_year == 365


def test_adjusted_close_is_preferred_for_analytics() -> None:
    data = make_bars([100.0, 102.0, 104.0])
    data["adj_close"] = [50.0, 55.0, 60.5]

    series = _series(data)

    assert series.price_field is PriceField.ADJ_CLOSE
    assert series.prices.tolist() == [50.0, 55.0, 60.5]
    assert series.stats.total_return == pytest.approx(0.21)
    assert series.column("close").tolist() == [100.0, 102.0, 104.0]


def test_columns_are_put_in_canonical_order() -> None:
    data = make_bars([100.0, 101.0, 102.0], ohlc=True, volume=[1, 2, 3])
    shuffled = data[["volume", "close", "low", "open", "high"]]

    assert list(_series(shuffled).bars.columns) == ["open", "high", "low", "close", "volume"]


# ── Analytical methods ─────────────────────────────────────────────────


def test_returns_drawdown_and_cumulative_returns() -> None:
    series = make_series([100.0, 120.0, 90.0, 99.0])

    assert series.returns().tolist() == pytest.approx([0.2, -0.25, 0.1])
    assert series.returns(ReturnKind.LOG).tolist() == pytest.approx(
        np.log([1.2, 0.75, 1.1]).tolist()
    )
    assert series.log_returns().equals(series.returns("log"))
    assert series.cumulative_returns().iloc[-1] == pytest.approx(-0.01)
    assert series.drawdown().min() == pytest.approx(-0.25)
    assert series.max_drawdown() == pytest.approx(-0.25)
    assert series.annualized_volatility() == series.stats.annualized_volatility


def test_between_returns_a_validated_sub_series() -> None:
    series = make_series([100.0, 101.0, 102.0, 103.0, 104.0])

    sub = series.between("2024-01-03", "2024-01-05")

    assert sub.prices.tolist() == [101.0, 102.0, 103.0]
    assert sub.instrument == series.instrument
    with pytest.raises(InvalidSeriesError):
        series.between("2024-01-03", "2024-01-03")  # too short


def test_unknown_column_access_raises_key_error() -> None:
    with pytest.raises(KeyError, match="volume"):
        make_series().column(PriceField.VOLUME)


# ── Immutability and value semantics ───────────────────────────────────


def test_series_cannot_be_modified_through_its_accessors() -> None:
    series = make_series([100.0, 101.0, 102.0])

    bars = series.bars
    bars.iloc[0, 0] = -1.0
    prices = series.prices
    prices.iloc[1] = -1.0

    assert series.prices.tolist() == [100.0, 101.0, 102.0]
    assert series.to_frame().equals(series.bars)


def test_series_does_not_alias_the_input_frame() -> None:
    data = make_bars([100.0, 101.0, 102.0])
    series = _series(data)

    data.iloc[0, 0] = -1.0

    assert series.prices.iloc[0] == 100.0


def test_attributes_are_frozen() -> None:
    series = make_series()

    with pytest.raises(dataclasses.FrozenInstanceError):
        series.frequency = Frequency.WEEK_1  # type: ignore[misc]


def test_value_equality_and_hash() -> None:
    first, second = make_series(), make_series()

    assert first == second
    assert hash(first) == hash(second)
    assert first != make_series([1.0, 2.0, 3.0])
    assert first != "not a series"


# ── Strict validation (ADR-0006) ────────────────────────────────────────


@pytest.mark.parametrize(
    ("prices", "fragment"),
    [
        ([100.0, np.nan, 102.0], "non-positive prices"),
        ([100.0, 0.0, 102.0], "non-positive prices"),
        ([100.0, -5.0, 102.0], "non-positive prices"),
        ([100.0, np.inf, 102.0], "non-positive prices"),
        ([100.0, 101.0], "at least 3 observations"),
    ],
)
def test_invalid_prices_are_rejected(prices: list[float], fragment: str) -> None:
    with pytest.raises(InvalidSeriesError, match=fragment):
        _series(make_bars(prices))


def test_all_problems_are_reported_together() -> None:
    index = pd.DatetimeIndex(["2024-01-03", "2024-01-02", "2024-01-02"])
    data = pd.DataFrame({"close": [1.0, -1.0, 2.0], "price": [1, 2, 3]}, index=index)

    with pytest.raises(InvalidSeriesError) as caught:
        _series(data)

    problems = " | ".join(caught.value.problems)
    assert "duplicated timestamps" in problems
    assert "sorted" in problems
    assert "unknown columns" in problems
    assert "non-positive" in problems
    assert caught.value.subject == "TEST.MC"


@pytest.mark.parametrize(
    ("data", "fragment"),
    [
        (
            pd.DataFrame({"open": [1.0, 2.0, 3.0]}, index=pd.bdate_range("2024-01-01", periods=3)),
            "'close' column is required",
        ),
        (pd.DataFrame({"close": [1.0, 2.0, 3.0]}, index=[1, 2, 3]), "DatetimeIndex"),
        (
            pd.DataFrame({"close": ["a", "b", "c"]}, index=pd.bdate_range("2024-01-01", periods=3)),
            "must be numeric",
        ),
        (
            pd.DataFrame(
                {"close": [True, False, True]}, index=pd.bdate_range("2024-01-01", periods=3)
            ),
            "must be numeric",
        ),
        (make_bars([1.0, 2.0, 3.0], volume=[1.0, -1.0, 2.0]), "'volume'"),
    ],
)
def test_structural_problems_are_rejected(data: pd.DataFrame, fragment: str) -> None:
    with pytest.raises(InvalidSeriesError, match=fragment):
        _series(data)


def test_non_dataframe_input_is_rejected() -> None:
    with pytest.raises(InvalidSeriesError, match="DataFrame"):
        _series([1, 2, 3])  # type: ignore[arg-type]


def test_missing_volume_is_allowed_but_prices_are_not() -> None:
    series = _series(make_bars([1.0, 2.0, 3.0], volume=[10.0, np.nan, 30.0]))

    assert series.column("volume").isna().sum() == 1


def test_daily_series_need_timezone_naive_session_labels() -> None:
    index = pd.bdate_range("2024-01-02", periods=3, tz="Europe/Madrid")

    with pytest.raises(InvalidSeriesError, match="session labels"):
        _series(make_bars([1.0, 2.0, 3.0], index))


def test_daily_session_labels_have_no_time_of_day() -> None:
    index = pd.DatetimeIndex(["2024-01-02 17:30", "2024-01-03 17:30", "2024-01-04 17:30"])

    with pytest.raises(InvalidSeriesError, match="midnight"):
        _series(make_bars([1.0, 2.0, 3.0], index))


def test_declared_frequency_must_match_the_spacing() -> None:
    daily = make_bars([1.0, 2.0, 3.0])

    with pytest.raises(InvalidSeriesError, match="too close"):
        _series(daily, Frequency.MONTH_1)


def test_intraday_series_need_timezone_aware_timestamps() -> None:
    naive = pd.date_range("2024-01-02 14:30", periods=3, freq="1min")

    with pytest.raises(InvalidSeriesError, match="timezone-aware"):
        _series(make_bars([1.0, 2.0, 3.0], naive), Frequency.MINUTE_1)


def test_intraday_timestamps_are_normalised_to_utc() -> None:
    madrid = pd.date_range("2024-01-02 09:00", periods=3, freq="1min", tz="Europe/Madrid")

    series = _series(make_bars([1.0, 2.0, 3.0], madrid), Frequency.MINUTE_1)

    assert str(pd.DatetimeIndex(series.bars.index).tz) == "UTC"
    assert series.start == pd.Timestamp("2024-01-02 08:00", tz="UTC")


def test_data_source_needs_a_slug_and_an_aware_timestamp() -> None:
    with pytest.raises(DomainError, match="slug"):
        DataSource("Yahoo Finance", SYNTHETIC_SOURCE.retrieved_at)
    with pytest.raises(DomainError, match="timezone-aware"):
        DataSource("yahoo", datetime(2026, 1, 1))  # noqa: DTZ001 - the point of the test
