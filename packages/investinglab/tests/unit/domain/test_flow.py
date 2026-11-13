"""Trade flow per bar: validation, delta and CVD (SYNTHETIC flow)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from investinglab.domain import (
    USD,
    AssetClass,
    FlowField,
    FlowSeries,
    Frequency,
    IncompatibleSeriesError,
    InvalidSeriesError,
)
from support.factories import SYNTHETIC_SOURCE, business_days, make_instrument, make_series

DAYS = business_days(5)
BTC = make_instrument("BTC-USD", currency=USD, asset_class=AssetClass.CRYPTO, exchange=None)


def frame(**columns: list[float]) -> pd.DataFrame:
    data = {
        "volume": [10.0, 20.0, 0.0, 8.0, 12.0],
        "quote_volume": [1000.0, 2100.0, 0.0, 840.0, 1300.0],
        "trades": [5, 9, 0, 4, 6],
        "buy_volume": [6.0, 5.0, 0.0, 8.0, 3.0],
        "buy_quote_volume": [600.0, 525.0, 0.0, 840.0, 325.0],
    }
    data.update(columns)
    return pd.DataFrame(data, index=DAYS)


def flow(data: pd.DataFrame | None = None, frequency: Frequency = Frequency.DAY_1) -> FlowSeries:
    return FlowSeries(BTC, frequency, SYNTHETIC_SOURCE, frame() if data is None else data)


def test_delta_is_twice_the_aggressive_buying_minus_the_volume() -> None:
    """The golden rule of the parity matrix: delta = 2 x buy_volume - volume."""
    series = flow()

    assert series.delta.tolist() == [2.0, -10.0, 0.0, 8.0, -6.0]
    assert series.sell_volume.tolist() == [4.0, 15.0, 0.0, 0.0, 9.0]
    assert (series.buy_volume - series.sell_volume).tolist() == series.delta.tolist()
    assert series.cvd.tolist() == [2.0, -8.0, -8.0, 0.0, -6.0]


def test_ratios_are_undefined_in_bars_without_trading() -> None:
    series = flow()

    assert series.buy_ratio.round(4).tolist()[:2] == [0.6, 0.25]
    assert np.isnan(series.buy_ratio.iloc[2])  # no volume: no ratio, never a zero
    assert series.vwap.dropna().tolist() == [100.0, 105.0, 105.0, 1300.0 / 12.0]
    assert np.isnan(series.vwap.iloc[2])
    assert series.average_trade_size.dropna().tolist() == [2.0, 20.0 / 9.0, 2.0, 2.0]


def test_the_flow_is_kept_in_canonical_order_and_cannot_be_changed_from_outside() -> None:
    shuffled = frame()[["trades", "buy_volume", "volume", "buy_quote_volume", "quote_volume"]]
    series = flow(shuffled)

    assert list(series.flow.columns) == [field.value for field in FlowField]
    table, volume = series.flow, series.volume
    table.iloc[0, 0] = 999.0
    volume.iloc[0] = 999.0
    assert series.volume.iloc[0] == 10.0
    assert series.flow.index.name == "timestamp"
    assert (len(series), series.symbol, series.start, series.end) == (
        5,
        "BTC-USD",
        DAYS[0],
        DAYS[-1],
    )
    assert "FlowSeries(BTC-USD, 1d" in repr(series)


def test_a_source_without_the_aggressor_side_has_volume_but_no_delta() -> None:
    series = flow(frame()[["volume", "trades"]])

    assert not series.has_aggressor_side
    assert series.volume.sum() == 50.0
    for attribute in ("delta", "cvd", "buy_volume", "sell_volume", "buy_ratio"):
        with pytest.raises(KeyError, match="no aggressor side"):
            getattr(series, attribute)
    with pytest.raises(KeyError, match="quote_volume"):
        _ = series.vwap
    with pytest.raises(KeyError, match="quote_volume"):
        series.column("quote_volume")
    assert series.column(FlowField.TRADES).tolist() == [5.0, 9.0, 0.0, 4.0, 6.0]


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (frame().drop(columns="volume"), "'volume' column is required"),
        (frame(volume=[10.0, np.nan, 0.0, 8.0, 12.0]), "'volume' has 1 missing"),
        (frame(buy_volume=[6.0, -1.0, 0.0, 8.0, 3.0]), "'buy_volume' has 1 missing"),
        (frame(buy_volume=[11.0, 5.0, 0.0, 8.0, 3.0]), "'buy_volume' exceeds 'volume'"),
        (frame(buy_quote_volume=[1001.0, 525.0, 0.0, 840.0, 325.0]), "exceeds 'quote_volume'"),
        (frame(trades=[5.5, 9, 0, 4, 6]), "whole numbers"),
        (frame().assign(delta=1.0), "unknown columns ['delta']"),
        (frame().astype({"volume": "object"}), "must be numeric"),
        (frame().iloc[:2], "at least 3 observations"),
        (frame().iloc[::-1], "increasing time order"),
        (frame().set_axis(DAYS.tz_localize("UTC")), "session labels"),
    ],
    ids=[
        "no-volume",
        "nan",
        "negative",
        "buy-above-volume",
        "buy-value-above-value",
        "fractional-trades",
        "unknown-column",
        "not-numeric",
        "too-short",
        "unsorted",
        "aware-daily",
    ],
)
def test_invalid_flow_is_refused_with_every_problem(data: pd.DataFrame, message: str) -> None:
    with pytest.raises(InvalidSeriesError) as error:
        flow(data)

    assert message in str(error.value)


def test_flow_must_be_a_table() -> None:
    with pytest.raises(InvalidSeriesError, match="must be a DataFrame"):
        FlowSeries(BTC, Frequency.DAY_1, SYNTHETIC_SOURCE, [1, 2, 3])  # type: ignore[arg-type]


def test_rounding_noise_between_buying_and_volume_is_tolerated() -> None:
    series = flow(frame(buy_volume=[10.0 + 1e-12, 5.0, 0.0, 8.0, 3.0]))

    assert series.sell_volume.iloc[0] == 0.0  # never a negative sale


def test_intraday_flow_is_kept_in_utc() -> None:
    hours = pd.date_range("2024-03-04 09:00", periods=5, freq="1h", tz="Europe/Madrid")
    series = flow(frame().set_axis(hours), Frequency.HOUR_1)

    assert str(pd.DatetimeIndex(series.flow.index).tz) == "UTC"
    assert series.start == pd.Timestamp("2024-03-04 08:00", tz="UTC")


def test_a_window_keeps_delta_and_restarts_the_cvd() -> None:
    series = flow()

    window = series.between(DAYS[1], DAYS[3])

    assert window.delta.tolist() == series.delta.iloc[1:4].tolist()
    assert window.cvd.tolist() == [-10.0, -10.0, -2.0]  # its level depends on the start
    assert window.cvd.diff().dropna().tolist() == series.cvd.diff().iloc[2:4].tolist()


def test_flow_aligns_with_the_bars_of_its_prices() -> None:
    prices = make_series([100.0, 105.0, 105.0, 108.0], symbol="BTC-USD", index=DAYS[1:])
    series = flow()

    aligned = series.aligned_with(prices)

    assert aligned.flow.index.equals(prices.bars.index)
    assert aligned.delta.tolist() == [-10.0, 0.0, 8.0, -6.0]


def test_flow_does_not_align_with_other_prices() -> None:
    series = flow()
    other = make_series([1.0, 2.0, 3.0, 4.0, 5.0], symbol="ETH-USD", index=DAYS)
    weekly = make_series(
        [1.0, 2.0, 3.0],
        symbol="BTC-USD",
        index=pd.DatetimeIndex(["2024-01-05", "2024-01-12", "2024-01-19"]),
        frequency=Frequency.WEEK_1,
    )
    later = make_series([1.0, 2.0, 3.0], symbol="BTC-USD", index=business_days(3, "2025-01-02"))

    with pytest.raises(IncompatibleSeriesError, match="prices of ETH-USD"):
        series.aligned_with(other)
    with pytest.raises(IncompatibleSeriesError, match="prices are 1w"):
        series.aligned_with(weekly)
    with pytest.raises(IncompatibleSeriesError, match="0 bars in common"):
        series.aligned_with(later)


def test_equal_flow_is_equal_and_hashable() -> None:
    assert flow() == flow()
    assert hash(flow()) == hash(flow())
    assert flow() != flow(frame(volume=[10.0, 20.0, 1.0, 8.0, 12.0]))
    assert flow() != "flow"
