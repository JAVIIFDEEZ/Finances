from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from investinglab.analytics import optimization
from investinglab.analytics.optimization import (
    OptimizationError,
    black_litterman,
    efficient_frontier,
    hierarchical_risk_parity_weights,
    implied_returns,
    inverse_volatility_weights,
    max_sharpe_weights,
    min_variance_weights,
    return_range,
    risk_budget_weights,
    target_return_weights,
)

# Annual volatilities of 15 %, 25 % and 20 % with moderate correlations.
VOL = np.array([0.15, 0.25, 0.20])
CORR = np.array([[1.0, 0.3, 0.2], [0.3, 1.0, 0.5], [0.2, 0.5, 1.0]])
COV = CORR * np.outer(VOL, VOL)
MEAN = np.array([0.06, 0.10, 0.08])
WIDE = {"lower": -10.0, "upper": 10.0}  # bounds that never bind: closed forms apply


def _risk_shares(weights: np.ndarray, covariance: np.ndarray) -> np.ndarray:
    contributions = weights * (covariance @ weights)
    return np.asarray(contributions / contributions.sum(), dtype="float64")


# ── Minimum variance ────────────────────────────────────────────────


def test_unconstrained_minimum_variance_matches_the_closed_form() -> None:
    inverse = np.linalg.inv(COV)
    expected = inverse.sum(axis=1) / inverse.sum()

    assert min_variance_weights(COV, **WIDE) == pytest.approx(expected, abs=1e-7)


def test_two_assets_minimum_variance() -> None:
    covariance = np.array([[0.04, 0.006], [0.006, 0.09]])
    share = (0.09 - 0.006) / (0.04 + 0.09 - 2 * 0.006)

    assert min_variance_weights(covariance) == pytest.approx([share, 1 - share], abs=1e-8)


def test_long_only_bounds_and_caps_are_respected() -> None:
    # A volatile asset perfectly correlated with a calm one only adds risk: weight 0.
    covariance = np.array([[0.04, 0.06, 0.0], [0.06, 0.09, 0.0], [0.0, 0.0, 0.05]])
    capped = min_variance_weights(COV, upper=0.4)

    assert min_variance_weights(covariance)[1] == pytest.approx(0.0, abs=1e-9)
    assert capped.max() <= 0.4 + 1e-12
    assert capped.sum() == pytest.approx(1.0)


@pytest.mark.parametrize(("lower", "upper"), [(0.5, 1.0), (0.0, 0.2), (0.3, 0.1)])
def test_infeasible_bounds_are_rejected(lower: float, upper: float) -> None:
    with pytest.raises(OptimizationError):
        min_variance_weights(COV, lower=lower, upper=upper)


@pytest.mark.parametrize(
    "matrix",
    [np.ones((2, 3)), np.array([[0.04, np.nan], [np.nan, 0.09]]), np.empty((0, 0))],
)
def test_malformed_covariances_are_rejected(matrix: np.ndarray) -> None:
    with pytest.raises(OptimizationError):
        min_variance_weights(matrix)


# ── Maximum Sharpe ratio ────────────────────────────────────────────


def test_unconstrained_tangency_matches_the_closed_form() -> None:
    raw = np.linalg.solve(COV, MEAN - 0.02)

    weights = max_sharpe_weights(MEAN, COV, risk_free=0.02, **WIDE)

    assert weights == pytest.approx(raw / raw.sum(), abs=1e-6)


def test_long_only_tangency_beats_every_other_portfolio() -> None:
    weights = max_sharpe_weights(MEAN, COV, risk_free=0.02)
    others = np.random.default_rng(1).dirichlet(np.ones(3), size=5_000)

    def sharpe(w: np.ndarray) -> np.ndarray:
        return np.asarray((w @ MEAN - 0.02) / np.sqrt(np.einsum("ij,jk,ik->i", w, COV, w)))

    assert sharpe(weights.reshape(1, -1))[0] >= sharpe(others).max() - 1e-9
    assert weights.min() >= 0.0


def test_no_portfolio_beating_the_risk_free_rate_has_no_tangency() -> None:
    with pytest.raises(OptimizationError, match="risk-free rate"):
        max_sharpe_weights(MEAN, COV, risk_free=0.2)


def test_a_single_asset_takes_everything() -> None:
    assert max_sharpe_weights([0.08], [[0.04]]) == pytest.approx([1.0])
    assert min_variance_weights([[0.04]]) == pytest.approx([1.0])


# ── Target return and frontier ──────────────────────────────────────


def test_target_returns_are_met_with_the_least_risk() -> None:
    weights = target_return_weights(MEAN, COV, 0.08)
    # Every long-only portfolio expecting 8 % here is ((1 - s) / 2, (1 - s) / 2, s).
    s = np.linspace(0.0, 1.0, 10_001)
    same_return = np.column_stack([(1 - s) / 2, (1 - s) / 2, s])

    assert weights @ MEAN == pytest.approx(0.08, abs=1e-9)
    assert same_return @ MEAN == pytest.approx(np.full(s.size, 0.08))
    lowest = np.einsum("ij,jk,ik->i", same_return, COV, same_return).min()
    assert weights @ COV @ weights <= lowest + 1e-12


def test_unreachable_targets_are_rejected() -> None:
    with pytest.raises(OptimizationError, match="out of reach"):
        target_return_weights(MEAN, COV, 0.12)


def test_return_range_respects_the_bounds() -> None:
    assert return_range(MEAN) == pytest.approx((0.06, 0.10))
    assert return_range(MEAN, upper=0.5) == pytest.approx((0.5 * 0.06 + 0.5 * 0.08, 0.09))


def test_the_frontier_goes_from_minimum_variance_to_the_highest_return() -> None:
    returns, volatilities, weights = efficient_frontier(MEAN, COV, points=12)

    assert weights.shape == (12, 3)
    assert weights[0] == pytest.approx(min_variance_weights(COV))
    assert returns[-1] == pytest.approx(0.10)
    assert (np.diff(returns) > 0).all()
    assert (np.diff(volatilities) >= -1e-12).all()
    assert weights.sum(axis=1) == pytest.approx(np.ones(12))


def test_a_frontier_needs_two_points() -> None:
    with pytest.raises(OptimizationError, match="two points"):
        efficient_frontier(MEAN, COV, points=1)


def test_mismatched_inputs_are_rejected() -> None:
    with pytest.raises(OptimizationError, match="2 values for 3 assets"):
        target_return_weights([0.1, 0.2], COV, 0.1)
    with pytest.raises(OptimizationError, match="missing or infinite"):
        max_sharpe_weights([0.1, np.inf, 0.2], COV)


# ── Risk-based ──────────────────────────────────────────────────────


def test_equal_risk_contribution() -> None:
    weights = risk_budget_weights(COV)

    assert _risk_shares(weights, COV) == pytest.approx(np.full(3, 1 / 3), abs=1e-9)
    assert weights.sum() == pytest.approx(1.0)


def test_custom_risk_budgets() -> None:
    weights = risk_budget_weights(COV, [2.0, 1.0, 1.0])  # normalised to 50/25/25

    assert _risk_shares(weights, COV) == pytest.approx([0.5, 0.25, 0.25], abs=1e-9)


def test_uncorrelated_risk_parity_is_inverse_volatility() -> None:
    diagonal = np.diag(VOL**2)

    assert risk_budget_weights(diagonal) == pytest.approx(inverse_volatility_weights(diagonal))
    assert inverse_volatility_weights(diagonal) == pytest.approx((1 / VOL) / (1 / VOL).sum())


@pytest.mark.parametrize(
    "call",
    [
        lambda: risk_budget_weights(COV, [1.0, 0.0, 1.0]),
        lambda: risk_budget_weights(np.diag([0.04, 0.0])),
        lambda: inverse_volatility_weights(np.diag([0.04, 0.0])),
        lambda: hierarchical_risk_parity_weights(np.diag([0.04, 0.0])),
    ],
)
def test_risk_based_methods_need_positive_variances_and_budgets(call: object) -> None:
    with pytest.raises(OptimizationError):
        call()  # type: ignore[operator]


def test_risk_budgeting_reports_when_it_cannot_converge() -> None:
    with pytest.raises(OptimizationError, match="did not converge"):
        risk_budget_weights(COV, max_iterations=1)


def test_uncorrelated_hrp_is_inverse_variance() -> None:
    variances = np.array([0.04, 0.09, 0.01, 0.0225])

    weights = hierarchical_risk_parity_weights(np.diag(variances))

    assert weights == pytest.approx((1 / variances) / (1 / variances).sum())


def test_hrp_splits_risk_between_clusters() -> None:
    # Two nearly identical assets and an unrelated one with the same volatility.
    correlation = np.array([[1.0, 0.99, 0.0], [0.99, 1.0, 0.0], [0.0, 0.0, 1.0]])
    covariance = correlation * 0.04

    weights = hierarchical_risk_parity_weights(covariance)

    assert weights[2] > 0.4  # the lone asset is a cluster of its own
    assert weights[0] == pytest.approx(weights[1])
    assert hierarchical_risk_parity_weights([[0.04]]) == pytest.approx([1.0])


# ── Black-Litterman ─────────────────────────────────────────────────


def test_implied_returns_are_reverse_optimisation() -> None:
    weights = np.array([0.5, 0.3, 0.2])

    assert implied_returns(COV, weights, 2.5) == pytest.approx(2.5 * COV @ weights)
    with pytest.raises(OptimizationError, match="risk aversion"):
        implied_returns(COV, weights, 0.0)


def test_a_certain_view_is_honoured_and_an_uncertain_one_ignored() -> None:
    prior = implied_returns(COV, np.full(3, 1 / 3), 2.5)
    pick = np.array([[1.0, -1.0, 0.0]])  # asset 0 beats asset 1 by 2 %

    certain, _ = black_litterman(prior, COV, pick, [0.02], uncertainty=np.zeros((1, 1)))
    vague, _ = black_litterman(prior, COV, pick, [0.02], uncertainty=np.array([[1e9]]))

    assert certain[0] - certain[1] == pytest.approx(0.02)
    assert vague == pytest.approx(prior, abs=1e-9)


def test_the_default_uncertainty_moves_returns_towards_the_view() -> None:
    prior = implied_returns(COV, np.full(3, 1 / 3), 2.5)

    posterior, covariance = black_litterman(prior, COV, np.eye(3)[:1], [0.15])

    assert prior[0] < posterior[0] < 0.15
    assert np.allclose(covariance, covariance.T)
    assert (np.diag(covariance) > np.diag(COV)).all()  # parameter uncertainty adds risk


@pytest.mark.parametrize(
    ("picks", "views", "options", "message"),
    [
        (np.ones((1, 2)), [0.1], {}, "3 weights"),
        (np.zeros((1, 3)), [0.1], {}, "at least one asset"),
        (np.eye(3)[:1], [0.1, 0.2], {}, "1 values for 2 assets|2 values for 1"),
        (np.eye(3)[:1], [0.1], {"tau": 0.0}, "tau"),
        (np.eye(3)[:1], [0.1], {"uncertainty": np.eye(2)}, "1x1"),
        (
            np.vstack([np.eye(3)[:1]] * 2),
            [0.1, 0.2],
            {"uncertainty": np.zeros((2, 2))},
            "redundant",
        ),
    ],
)
def test_invalid_views_are_rejected(
    picks: np.ndarray, views: list[float], options: dict[str, object], message: str
) -> None:
    with pytest.raises(OptimizationError, match=message):
        black_litterman(MEAN, COV, picks, views, **options)  # type: ignore[arg-type]


def test_a_failed_solver_is_reported_not_returned(monkeypatch: pytest.MonkeyPatch) -> None:
    def failed(*args: object, **kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(x=np.zeros(3), message="Iteration limit reached")

    monkeypatch.setattr(optimization, "minimize", failed)

    with pytest.raises(OptimizationError, match="did not converge: Iteration limit reached"):
        min_variance_weights(COV)
