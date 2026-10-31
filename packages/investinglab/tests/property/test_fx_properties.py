"""Property-based tests for currency conversion."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from hypothesis import given
from hypothesis import strategies as st
from hypothesis.extra.numpy import arrays

from investinglab.domain import EUR, USD, CurrencyPair, FxRates, currency_attribution
from support.factories import SYNTHETIC_SOURCE, make_series

positive = st.floats(0.05, 50.0, allow_nan=False, allow_infinity=False)


@given(
    prices=arrays(np.float64, st.integers(3, 40), elements=positive),
    data=st.data(),
)
def test_converting_there_and_back_restores_prices(prices: np.ndarray, data: st.DataObject) -> None:
    index = pd.bdate_range("2024-01-01", periods=len(prices))
    fixings = data.draw(arrays(np.float64, len(prices), elements=positive))
    rates = FxRates(CurrencyPair(EUR, USD), SYNTHETIC_SOURCE, pd.Series(fixings, index=index))
    series = make_series(prices, index=index)

    round_trip = rates.inverse().convert(rates.convert(series))

    assert round_trip.currency == EUR
    np.testing.assert_allclose(round_trip.prices.to_numpy(), prices, rtol=1e-10)


@given(
    prices=arrays(np.float64, st.integers(3, 40), elements=positive),
    data=st.data(),
)
def test_attribution_always_compounds_to_the_total(prices: np.ndarray, data: st.DataObject) -> None:
    index = pd.bdate_range("2024-01-01", periods=len(prices))
    fixings = data.draw(arrays(np.float64, len(prices), elements=positive))
    rates = FxRates(CurrencyPair(EUR, USD), SYNTHETIC_SOURCE, pd.Series(fixings, index=index))
    local = make_series(prices, index=index)

    attribution = currency_attribution(local, rates.convert(local))

    product = (1 + attribution["local"]) * (1 + attribution["currency"])
    np.testing.assert_allclose(product, 1 + attribution["total"], rtol=1e-9)
    assert attribution["cum_total"].iloc[-1] == pytest.approx(
        (prices[-1] * fixings[-1]) / (prices[0] * fixings[0]) - 1, rel=1e-9, abs=1e-9
    )
