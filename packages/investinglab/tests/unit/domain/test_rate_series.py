"""Holding rates: funding, borrow fees and financing costs (SYNTHETIC rates)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from investinglab.domain import (
    USD,
    AssetClass,
    DomainError,
    InvalidSeriesError,
    RateKind,
    RateSeries,
)
from support.factories import SYNTHETIC_SOURCE, make_instrument

PERP = make_instrument("BTC-USD", currency=USD, asset_class=AssetClass.CRYPTO, exchange=None)
SHARE = make_instrument("SAN.MC")
EIGHT_HOURS = pd.date_range("2026-01-01 00:00", periods=6, freq="8h", tz="UTC")


def rates(
    values: list[float] | None = None,
    *,
    kind: RateKind = RateKind.FUNDING,
    index: pd.DatetimeIndex = EIGHT_HOURS,
    interval: pd.Timedelta | None = None,
) -> RateSeries:
    data = pd.Series(
        [0.0001, 0.0003, -0.0002, 0.0001, 0.0, 0.0002] if values is None else values, index=index
    )
    return RateSeries(PERP, "binance", kind, SYNTHETIC_SOURCE, data, interval=interval)


def test_the_accrual_interval_is_inferred_and_annualises_like_venues_quote() -> None:
    series = rates()

    assert series.interval == pd.Timedelta(hours=8)
    assert series.periods_per_year == pytest.approx(1095.0)
    assert series.annualized().iloc[0] == pytest.approx(0.1095)  # 0.01 % every 8 h
    assert (len(series), series.symbol, series.start, series.end) == (
        6,
        "BTC-USD",
        EIGHT_HOURS[0],
        EIGHT_HOURS[-1],
    )
    assert "RateSeries(BTC-USD@binance, funding" in repr(series)


def test_funding_moves_from_one_side_to_the_other() -> None:
    series = rates()

    long, short = series.cashflow("long"), series.cashflow("short")

    assert long.tolist() == [-0.0001, -0.0003, 0.0002, -0.0001, -0.0, -0.0002]
    assert (long + short).abs().max() == 0.0  # what one side pays, the other receives
    assert series.accumulated("long") == pytest.approx(-0.0005)
    assert series.accumulated("short") == pytest.approx(0.0005)


@pytest.mark.parametrize(
    ("kind", "payer", "other"),
    [(RateKind.BORROW, "short", "long"), (RateKind.FINANCING, "long", "short")],
)
def test_a_fee_paid_to_a_third_party_gives_the_other_side_nothing(
    kind: RateKind, payer: str, other: str
) -> None:
    daily = pd.date_range("2026-01-01", periods=3, freq="1D", tz="UTC")
    series = RateSeries(
        SHARE, "broker", kind, SYNTHETIC_SOURCE, pd.Series([0.0001, 0.0001, 0.0002], index=daily)
    )

    assert kind.payer == payer
    assert not kind.is_exchanged
    assert series.accumulated(payer) == pytest.approx(-0.0004)
    assert series.accumulated(other) == 0.0  # type: ignore[arg-type]
    assert series.periods_per_year == pytest.approx(365.0)


def test_one_payment_needs_its_interval() -> None:
    one = EIGHT_HOURS[:1]

    with pytest.raises(InvalidSeriesError, match="give the accrual interval"):
        rates([0.0001], index=one)

    series = rates([0.0001], index=one, interval=pd.Timedelta(hours=4))
    assert series.periods_per_year == pytest.approx(2190.0)


def test_instants_are_kept_in_utc_and_rates_cannot_be_changed_from_outside() -> None:
    madrid = EIGHT_HOURS.tz_convert("Europe/Madrid")
    series = rates(index=madrid)

    assert str(pd.DatetimeIndex(series.rates.index).tz) == "UTC"
    copy = series.rates
    copy.iloc[0] = 9.0
    assert series.rates.iloc[0] == 0.0001


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (pd.Series([0.0001, 0.0002], index=EIGHT_HOURS[:2].tz_localize(None)), "timezone-aware"),
        (pd.Series([0.0001, np.nan], index=EIGHT_HOURS[:2]), "must be finite"),
        (pd.Series([0.01, 1.5], index=EIGHT_HOURS[:2]), "not plausible"),
        (pd.Series([0.0001, 0.0002], index=EIGHT_HOURS[[1, 0]]), "increasing time order"),
        (pd.Series([0.0001, 0.0002], index=EIGHT_HOURS[[0, 0]]), "duplicated"),
        (pd.Series(["a", "b"], index=EIGHT_HOURS[:2]), "must be numeric"),
        (pd.Series([], index=EIGHT_HOURS[:0], dtype="float64"), "at least one observation"),
        (pd.Series([0.0001, 0.0002], index=[1, 2]), "must be a DatetimeIndex"),
    ],
    ids=[
        "naive",
        "nan",
        "percent-as-decimal",
        "unsorted",
        "duplicated",
        "text",
        "empty",
        "no-dates",
    ],
)
def test_invalid_rates_are_refused(data: pd.Series, message: str) -> None:
    with pytest.raises(InvalidSeriesError) as error:
        RateSeries(PERP, "binance", RateKind.FUNDING, SYNTHETIC_SOURCE, data)

    assert message in str(error.value)


def test_rates_need_a_series_a_venue_and_a_positive_interval() -> None:
    data = pd.Series([0.0001, 0.0002], index=EIGHT_HOURS[:2])

    with pytest.raises(InvalidSeriesError, match="must be a Series"):
        RateSeries(PERP, "binance", RateKind.FUNDING, SYNTHETIC_SOURCE, [0.1])  # type: ignore[arg-type]
    with pytest.raises(DomainError, match="venue"):
        RateSeries(PERP, " ", RateKind.FUNDING, SYNTHETIC_SOURCE, data)
    with pytest.raises(InvalidSeriesError, match="must be positive"):
        RateSeries(
            PERP, "binance", RateKind.FUNDING, SYNTHETIC_SOURCE, data, interval=pd.Timedelta(0)
        )


def test_a_window_keeps_the_interval() -> None:
    series = rates()

    window = series.between(EIGHT_HOURS[4], None)

    assert len(window) == 2
    assert window.interval == series.interval
    assert series.between(EIGHT_HOURS[5], None).periods_per_year == pytest.approx(1095.0)


def test_equal_rates_are_equal_and_hashable() -> None:
    assert rates() == rates()
    assert hash(rates()) == hash(rates())
    assert rates() != rates(kind=RateKind.FINANCING)
    assert rates() != "rates"
