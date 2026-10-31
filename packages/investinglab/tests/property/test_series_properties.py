"""Property-based tests: invariants that must hold for *any* valid price series."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from support.factories import make_series
from support.strategies import positive_prices, price_series, scale_factors

if TYPE_CHECKING:
    from investinglab.domain import PriceSeries

settings.register_profile("default", deadline=None)
settings.load_profile("default")


@given(prices=positive_prices, factor=scale_factors)
def test_returns_do_not_depend_on_the_price_scale(prices: list[float], factor: float) -> None:
    original = make_series(np.asarray(prices))
    scaled = make_series(np.asarray(prices) * factor)

    np.testing.assert_allclose(original.returns(), scaled.returns(), rtol=1e-9, atol=1e-12)
    assert scaled.stats.std_return == pytest.approx(original.stats.std_return, rel=1e-6, abs=1e-12)


@given(series=price_series())
def test_log_returns_add_up_to_the_total_log_growth(series: PriceSeries) -> None:
    prices = series.prices

    assert series.log_returns().sum() == pytest.approx(
        math.log(prices.iloc[-1] / prices.iloc[0]), rel=1e-6, abs=1e-9
    )


@given(series=price_series())
def test_compounded_returns_equal_the_total_return(series: PriceSeries) -> None:
    assert series.cumulative_returns().iloc[-1] == pytest.approx(
        series.stats.total_return, rel=1e-6, abs=1e-9
    )


@given(series=price_series())
def test_drawdown_is_bounded_and_consistent(series: PriceSeries) -> None:
    drawdown = series.drawdown()

    assert (drawdown <= 0.0).all()
    assert (drawdown >= -1.0).all()
    assert series.max_drawdown() == pytest.approx(drawdown.min())


@given(prices=st.lists(st.floats(1.0, 1e4), min_size=3, max_size=60))
def test_non_decreasing_prices_have_no_drawdown(prices: list[float]) -> None:
    series = make_series(np.sort(np.asarray(prices)))

    assert series.max_drawdown() == 0.0


@given(series=price_series())
def test_statistics_are_internally_consistent(series: PriceSeries) -> None:
    stats = series.stats
    returns = series.returns()

    assert stats.n_observations == len(series) == len(returns) + 1
    assert stats.std_return >= 0.0
    assert stats.mean_return == pytest.approx(returns.mean(), rel=1e-9, abs=1e-12)
    assert stats.annualized_volatility == pytest.approx(
        stats.std_return * math.sqrt(stats.periods_per_year)
    )
    assert stats.start <= stats.end


@given(series=price_series())
def test_series_survive_attempts_to_mutate_them(series: PriceSeries) -> None:
    snapshot = series.prices.copy()

    bars = series.bars
    bars.loc[:, "close"] = -1.0

    assert series.prices.equals(snapshot)
    assert series == series.with_bars(series.bars)
