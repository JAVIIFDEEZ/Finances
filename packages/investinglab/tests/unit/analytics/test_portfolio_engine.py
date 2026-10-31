from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from investinglab.analytics import rebalanced_path, risk_contributions

INDEX = pd.bdate_range("2024-01-01", periods=4)
PRICES = pd.DataFrame(
    {"A": [100.0, 110.0, 121.0, 108.9], "B": [50.0, 50.0, 45.0, 49.5]}, index=INDEX
)
RETURNS = PRICES.pct_change()


def test_buy_and_hold_tracks_the_weighted_price_path() -> None:
    path = rebalanced_path(RETURNS, np.array([0.5, 0.5]), initial_value=100.0)

    normalised = (PRICES / PRICES.iloc[0]).to_numpy() @ np.array([0.5, 0.5]) * 100.0
    assert path.values.to_numpy() == pytest.approx(normalised)
    assert len(path.rebalanced) == 0
    assert path.turnover.sum() == 0.0
    # Weights drift with prices.
    assert path.weights.iloc[1]["A"] == pytest.approx(0.55 / 1.05)


def test_daily_rebalancing_is_a_constant_mix() -> None:
    path = rebalanced_path(RETURNS, np.array([0.6, 0.4]), rebalance_dates=INDEX[1:])

    expected = RETURNS.iloc[1:].to_numpy() @ np.array([0.6, 0.4])
    assert path.returns.to_numpy() == pytest.approx(expected)
    assert np.allclose(path.weights.to_numpy(), [0.6, 0.4])
    assert path.turnover.iloc[1] > 0
    assert list(path.rebalanced) == list(INDEX[1:])


def test_threshold_rebalancing_triggers_only_beyond_the_band() -> None:
    wide = rebalanced_path(RETURNS, np.array([0.5, 0.5]), band=0.20)
    narrow = rebalanced_path(RETURNS, np.array([0.5, 0.5]), band=0.01)

    assert len(wide.rebalanced) == 0
    assert len(narrow.rebalanced) > 0


def test_unobserved_returns_keep_the_last_mark() -> None:
    returns = RETURNS.copy()
    returns.iloc[2, 1] = np.nan  # B's market closed on day 3

    path = rebalanced_path(returns, np.array([0.5, 0.5]))

    assert path.returns.iloc[1] == pytest.approx(0.55 / 1.05 * 0.10)
    assert not path.returns.isna().any()


def test_a_portfolio_that_loses_everything_stops() -> None:
    returns = pd.DataFrame(
        {"A": [np.nan, 0.5, 0.1], "B": [np.nan, 0.0, 0.0]},
        index=pd.bdate_range("2024-01-01", periods=3),
    )

    path = rebalanced_path(returns, np.array([-2.0, 3.0]))  # short A, leveraged B

    assert path.returns.iloc[0] == -1.0
    assert path.values.iloc[1] == 0.0
    assert np.isnan(path.values.iloc[2])
    assert np.isnan(path.returns.iloc[1])


def test_risk_contributions_sum_to_the_volatility() -> None:
    covariance = np.array([[0.04, 0.006], [0.006, 0.01]])
    weights = np.array([0.6, 0.4])

    table = risk_contributions(weights, covariance)

    volatility = np.sqrt(weights @ covariance @ weights)
    assert table["contribution"].sum() == pytest.approx(volatility)
    assert table["share"].sum() == pytest.approx(1.0)


def test_risk_contributions_of_a_riskless_portfolio() -> None:
    table = risk_contributions(np.array([0.5, 0.5]), np.zeros((2, 2)))

    assert (table["marginal"] == 0).all()
    assert table["share"].isna().all()
