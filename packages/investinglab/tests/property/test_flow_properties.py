"""Property-based tests: what holds for any trade flow and any holding rates (SYNTHETIC)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from hypothesis import given
from hypothesis import strategies as st

from investinglab.domain import USD, AssetClass, FlowSeries, Frequency, RateKind, RateSeries
from support.factories import SYNTHETIC_SOURCE, business_days, make_instrument

INSTRUMENT = make_instrument("BTC-USD", currency=USD, asset_class=AssetClass.CRYPTO, exchange=None)


@st.composite
def flows(draw: st.DrawFn) -> FlowSeries:
    """A flow series whose aggressive buying is any share of each bar's volume."""
    n = draw(st.integers(min_value=3, max_value=40))
    volume = draw(st.lists(st.floats(0, 1e6, allow_nan=False), min_size=n, max_size=n))
    shares = draw(st.lists(st.floats(0, 1), min_size=n, max_size=n))
    data = pd.DataFrame(
        {"volume": volume, "buy_volume": [v * s for v, s in zip(volume, shares, strict=True)]},
        index=business_days(n),
    )
    return FlowSeries(INSTRUMENT, Frequency.DAY_1, SYNTHETIC_SOURCE, data)


@given(series=flows())
def test_the_cvd_changes_by_each_bars_delta(series: FlowSeries) -> None:
    np.testing.assert_allclose(series.cvd.diff().iloc[1:], series.delta.iloc[1:], atol=1e-6)
    assert series.cvd.iloc[-1] == pytest.approx(series.delta.sum(), abs=1e-6)


@given(series=flows())
def test_the_delta_never_exceeds_the_volume(series: FlowSeries) -> None:
    assert (series.delta.abs() <= series.volume + 1e-9).all()
    np.testing.assert_allclose(series.buy_volume + series.sell_volume, series.volume, atol=1e-6)


@given(series=flows(), cut=st.integers(min_value=3, max_value=40))
def test_later_bars_do_not_change_earlier_deltas(series: FlowSeries, cut: int) -> None:
    """Nothing about a bar depends on the future: truncating keeps the past as it was."""
    end = series.flow.index[min(cut, len(series)) - 1]

    np.testing.assert_array_equal(series.between(None, end).delta, series.delta.loc[:end])


@given(
    values=st.lists(st.floats(-0.01, 0.01, allow_nan=False), min_size=2, max_size=60),
    hours=st.sampled_from([1, 4, 8]),
)
def test_funding_is_zero_sum_between_longs_and_shorts(values: list[float], hours: int) -> None:
    index = pd.date_range("2026-01-01", periods=len(values), freq=f"{hours}h", tz="UTC")
    series = RateSeries(
        INSTRUMENT, "venue", RateKind.FUNDING, SYNTHETIC_SOURCE, pd.Series(values, index=index)
    )

    assert series.accumulated("long") + series.accumulated("short") == pytest.approx(0, abs=1e-12)
    assert series.periods_per_year == pytest.approx(365 * 24 / hours)
