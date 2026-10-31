"""Property-based tests of risk analytics and the portfolio engine."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from hypothesis import given
from hypothesis import strategies as st
from hypothesis.extra.numpy import arrays

from investinglab.analytics import (
    VaRMethod,
    conditional_value_at_risk,
    is_positive_semidefinite,
    nearest_positive_semidefinite,
    rebalanced_path,
    risk_contributions,
    value_at_risk,
)

return_samples = arrays(
    dtype=np.float64,
    shape=st.integers(5, 200),
    elements=st.floats(-0.5, 0.5, allow_nan=False, allow_infinity=False),
)


@given(returns=return_samples, level=st.floats(0.5, 0.995))
def test_expected_shortfall_is_never_below_var(returns: np.ndarray, level: float) -> None:
    for method in VaRMethod:
        var = value_at_risk(returns, level, method)
        cvar = conditional_value_at_risk(returns, level, method)
        assert cvar >= var - 1e-9


@given(returns=return_samples)
def test_historical_var_grows_with_confidence(returns: np.ndarray) -> None:
    assert value_at_risk(returns, 0.99) >= value_at_risk(returns, 0.90) - 1e-12


@given(
    data=arrays(
        np.float64,
        st.tuples(st.integers(3, 6), st.integers(3, 6)),
        elements=st.floats(-1, 1, allow_nan=False),
    ),
)
def test_nearest_psd_is_psd_and_keeps_the_diagonal(data: np.ndarray) -> None:
    square = data[: min(data.shape), : min(data.shape)]
    matrix = (square + square.T) / 2
    np.fill_diagonal(matrix, np.abs(np.diag(matrix)) + 0.1)

    repaired = nearest_positive_semidefinite(matrix)

    assert is_positive_semidefinite(repaired, tolerance=1e-8)
    assert np.allclose(np.diag(repaired), np.diag(matrix))


@st.composite
def weighted_returns(draw: st.DrawFn) -> tuple[pd.DataFrame, np.ndarray]:
    assets = draw(st.integers(1, 5))
    periods = draw(st.integers(2, 40))
    values = draw(
        arrays(np.float64, (periods, assets), elements=st.floats(-0.3, 0.3, allow_nan=False))
    )
    raw = draw(arrays(np.float64, assets, elements=st.floats(0.05, 1.0)))
    frame = pd.DataFrame(values, index=pd.bdate_range("2024-01-01", periods=periods))
    return frame, raw / raw.sum()


@given(case=weighted_returns())
def test_buy_and_hold_value_is_the_weighted_growth_of_each_asset(
    case: tuple[pd.DataFrame, np.ndarray],
) -> None:
    returns, weights = case

    path = rebalanced_path(returns, weights)

    growth = (1 + returns.iloc[1:]).prod().to_numpy()
    assert path.values.iloc[-1] == pytest.approx(float(weights @ growth), rel=1e-9)
    assert path.weights.iloc[-1].sum() == pytest.approx(1.0)


@given(case=weighted_returns())
def test_rebalancing_every_period_holds_the_targets(
    case: tuple[pd.DataFrame, np.ndarray],
) -> None:
    returns, weights = case

    path = rebalanced_path(returns, weights, rebalance_dates=pd.DatetimeIndex(returns.index))

    assert np.allclose(path.weights.to_numpy(), weights)
    assert (path.turnover >= 0).all()


@given(
    weights=arrays(np.float64, 4, elements=st.floats(0.01, 1.0)),
    factors=arrays(np.float64, (4, 4), elements=st.floats(-1, 1, allow_nan=False)),
)
def test_risk_contribution_shares_sum_to_one(weights: np.ndarray, factors: np.ndarray) -> None:
    covariance = factors @ factors.T + np.eye(4) * 1e-3

    table = risk_contributions(weights / weights.sum(), covariance)

    assert table["share"].sum() == pytest.approx(1.0)
