"""Property-based tests of the portfolio optimisers on random covariance matrices."""

from __future__ import annotations

import numpy as np
from hypothesis import given, settings
from hypothesis import strategies as st
from hypothesis.extra.numpy import arrays

from investinglab.analytics.optimization import (
    efficient_frontier,
    hierarchical_risk_parity_weights,
    max_sharpe_weights,
    min_variance_weights,
    risk_budget_weights,
)

TOLERANCE = 1e-9


@st.composite
def covariances(draw: st.DrawFn) -> np.ndarray:
    """Positive-definite covariances from a two-factor model plus idiosyncratic risk."""
    size = draw(st.integers(2, 6))
    loadings = draw(arrays(np.float64, (size, 2), elements=st.floats(-1.0, 1.0)))
    idiosyncratic = draw(arrays(np.float64, size, elements=st.floats(0.05, 1.0)))
    volatilities = draw(arrays(np.float64, size, elements=st.floats(0.05, 0.6)))
    raw = loadings @ loadings.T + np.diag(idiosyncratic)
    scale = np.sqrt(np.diag(raw))
    return np.asarray(raw / np.outer(scale, scale) * np.outer(volatilities, volatilities))


def _feasible_candidates(size: int) -> np.ndarray:
    """Equal weights and every single-asset portfolio: all long-only and fully invested."""
    return np.vstack([np.full(size, 1.0 / size), np.eye(size)])


def _is_long_only_and_invested(weights: np.ndarray) -> bool:
    return bool(weights.min() >= -TOLERANCE and abs(weights.sum() - 1.0) <= TOLERANCE)


@settings(max_examples=40, deadline=None)
@given(covariance=covariances())
def test_minimum_variance_is_never_beaten(covariance: np.ndarray) -> None:
    weights = min_variance_weights(covariance)
    candidates = _feasible_candidates(covariance.shape[0])

    variance = weights @ covariance @ weights
    assert _is_long_only_and_invested(weights)
    assert variance <= np.einsum("ij,jk,ik->i", candidates, covariance, candidates).min() + 1e-12


@settings(max_examples=40, deadline=None)
@given(
    covariance=covariances(),
    premia=arrays(np.float64, 6, elements=st.floats(-0.05, 0.15)),
)
def test_the_tangency_has_the_best_sharpe_ratio(covariance: np.ndarray, premia: np.ndarray) -> None:
    size = covariance.shape[0]
    mean = 0.02 + premia[:size]
    mean[0] = max(mean[0], 0.05)  # at least one asset beats the 2 % risk-free rate
    candidates = _feasible_candidates(size)

    weights = max_sharpe_weights(mean, covariance, risk_free=0.02)

    def sharpe(w: np.ndarray) -> np.ndarray:
        risk = np.sqrt(np.einsum("ij,jk,ik->i", w, covariance, w))
        return np.asarray((w @ mean - 0.02) / risk)

    assert _is_long_only_and_invested(weights)
    assert sharpe(weights.reshape(1, -1))[0] >= sharpe(candidates).max() - 1e-7


@settings(max_examples=40, deadline=None)
@given(covariance=covariances())
def test_risk_parity_equalises_risk_contributions(covariance: np.ndarray) -> None:
    weights = risk_budget_weights(covariance)

    contributions = weights * (covariance @ weights)
    assert _is_long_only_and_invested(weights)
    assert np.allclose(contributions / contributions.sum(), 1.0 / covariance.shape[0], atol=1e-8)


@settings(max_examples=40, deadline=None)
@given(covariance=covariances())
def test_hrp_is_long_only_and_fully_invested(covariance: np.ndarray) -> None:
    weights = hierarchical_risk_parity_weights(covariance)

    assert _is_long_only_and_invested(weights)
    assert weights.min() > 0


@settings(max_examples=25, deadline=None)
@given(
    covariance=covariances(),
    mean=arrays(np.float64, 6, elements=st.floats(0.0, 0.15)),
)
def test_risk_grows_along_the_frontier(covariance: np.ndarray, mean: np.ndarray) -> None:
    returns, volatilities, _ = efficient_frontier(mean[: covariance.shape[0]], covariance, points=6)

    assert (np.diff(returns) >= -1e-12).all()
    assert (np.diff(volatilities) >= -1e-7).all()
