"""Property-based tests for identifiers, portfolios and point-in-time macro data."""

from __future__ import annotations

import string

import numpy as np
import pandas as pd
import pytest
from hypothesis import given
from hypothesis import strategies as st

from investinglab.domain import (
    EconomicSeries,
    Frequency,
    InvalidPortfolioError,
    Portfolio,
)
from investinglab.domain.instruments import is_valid_isin
from support.factories import SYNTHETIC_SOURCE, make_series

isin_payloads = st.builds(
    lambda country, body: country + body,
    st.text(string.ascii_uppercase, min_size=2, max_size=2),
    st.text(string.ascii_uppercase + string.digits, min_size=9, max_size=9),
)


@given(payload=isin_payloads)
def test_exactly_one_check_digit_makes_an_isin_valid(payload: str) -> None:
    valid = [digit for digit in "0123456789" if is_valid_isin(payload + digit)]

    assert len(valid) == 1


@given(raw=st.lists(st.floats(0.01, 100.0), min_size=1, max_size=8))
def test_normalised_positive_weights_always_build_a_portfolio(raw: list[float]) -> None:
    weights = np.asarray(raw) / np.sum(raw)
    assets = [make_series(symbol=f"A{i}") for i in range(len(raw))]

    portfolio = Portfolio.from_weights("Random", assets, weights.tolist())

    assert portfolio.weights.sum() == pytest.approx(1.0)


@given(
    raw=st.lists(st.floats(0.01, 100.0), min_size=1, max_size=8),
    error=st.floats(1e-4, 0.5) | st.floats(-0.5, -1e-4),
)
def test_weights_that_do_not_sum_to_one_are_always_rejected(raw: list[float], error: float) -> None:
    weights = np.asarray(raw) / np.sum(raw)
    weights[0] += error
    assets = [make_series(symbol=f"A{i}") for i in range(len(raw))]

    with pytest.raises(InvalidPortfolioError):
        Portfolio.from_weights("Random", assets, weights.tolist(), allow_short=True)


@st.composite
def vintages(draw: st.DrawFn) -> pd.DataFrame:
    """Random monthly observations, each published 1-60 days after its period, some revised."""
    n = draw(st.integers(1, 12))
    rows: list[tuple[pd.Timestamp, pd.Timestamp, float]] = []
    for month in pd.date_range("2023-01-01", periods=n, freq="MS"):
        first = month + pd.Timedelta(days=draw(st.integers(1, 60)))
        rows.append((month, first, draw(st.floats(-5, 5))))
        if draw(st.booleans()):
            revised = first + pd.Timedelta(days=draw(st.integers(1, 90)))
            rows.append((month, revised, draw(st.floats(-5, 5))))
    return pd.DataFrame(rows, columns=["observation_date", "published_at", "value"])


@given(data=vintages(), offsets=st.lists(st.integers(0, 600), min_size=1, max_size=20))
def test_point_in_time_values_were_always_published_before_use(
    data: pd.DataFrame, offsets: list[int]
) -> None:
    series = EconomicSeries("X", "x", "u", Frequency.MONTH_1, SYNTHETIC_SOURCE, data)
    dates = pd.DatetimeIndex(
        sorted({pd.Timestamp("2023-01-01") + pd.Timedelta(days=o) for o in offsets})
    )

    known = series.known_values_at(dates)

    for moment, value in known.items():
        published = data[data["published_at"] <= moment]
        if published.empty:
            assert np.isnan(value)
        else:
            assert value in set(published["value"])
            # It is the value of the latest observation already published...
            latest_obs = published["observation_date"].max()
            candidates = published[published["observation_date"] == latest_obs]
            # ...in its latest vintage known at that moment.
            assert value == candidates.sort_values("published_at")["value"].iloc[-1]
