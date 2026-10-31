from __future__ import annotations

import numpy as np
import pytest

from investinglab.analytics.montecarlo import (
    cholesky_factor,
    normal_log_returns,
    path_max_drawdowns,
    rebalanced_values,
    stationary_bootstrap_indices,
    student_t_log_returns,
)

COVARIANCE = np.array([[0.0004, 0.0001], [0.0001, 0.0009]])
MEAN = np.array([0.0002, 0.0005])


# ── Cholesky factor ──────────────────────────────────────────────────


def test_cholesky_factor_reconstructs_a_positive_definite_matrix() -> None:
    factor = cholesky_factor(COVARIANCE)

    assert np.allclose(factor @ factor.T, COVARIANCE)
    assert np.allclose(factor, np.tril(factor))


def test_cholesky_factor_falls_back_for_semidefinite_matrices() -> None:
    # Two perfectly correlated assets: the covariance is singular, Cholesky fails.
    singular = np.array([[0.04, 0.06], [0.06, 0.09]])

    factor = cholesky_factor(singular)

    assert np.allclose(factor @ factor.T, singular)


# ── Gaussian and Student-t shocks ────────────────────────────────────


def test_normal_log_returns_have_the_requested_moments() -> None:
    rng = np.random.default_rng(0)

    draws = normal_log_returns(MEAN, COVARIANCE, horizon=50, n_paths=4_000, rng=rng)

    assert draws.shape == (4_000, 50, 2)
    flat = draws.reshape(-1, 2)
    standard_error = np.sqrt(np.diag(COVARIANCE) / len(flat))
    assert np.all(np.abs(flat.mean(axis=0) - MEAN) < 4 * standard_error)
    assert np.allclose(np.cov(flat, rowvar=False), COVARIANCE, rtol=0.03)


def test_antithetic_shocks_mirror_each_other_around_the_mean() -> None:
    rng = np.random.default_rng(1)

    draws = normal_log_returns(MEAN, COVARIANCE, horizon=5, n_paths=6, rng=rng, antithetic=True)

    assert np.allclose(draws[:3] - MEAN, -(draws[3:] - MEAN))


def test_antithetic_shocks_support_an_odd_number_of_paths() -> None:
    draws = normal_log_returns(
        MEAN, COVARIANCE, horizon=4, n_paths=7, rng=np.random.default_rng(2), antithetic=True
    )

    assert draws.shape == (7, 4, 2)
    assert np.allclose(draws[:3] - MEAN, -(draws[4:] - MEAN))


def test_same_generator_state_gives_the_same_draws() -> None:
    first = normal_log_returns(MEAN, COVARIANCE, horizon=3, n_paths=5, rng=np.random.default_rng(3))
    second = normal_log_returns(
        MEAN, COVARIANCE, horizon=3, n_paths=5, rng=np.random.default_rng(3)
    )

    assert np.array_equal(first, second)


def test_student_t_keeps_the_covariance_but_has_fatter_tails() -> None:
    rng = np.random.default_rng(4)

    draws = student_t_log_returns(
        MEAN, COVARIANCE, degrees_of_freedom=5, horizon=50, n_paths=8_000, rng=rng
    )

    flat = draws.reshape(-1, 2)
    assert np.allclose(np.cov(flat, rowvar=False), COVARIANCE, rtol=0.06)
    standardised = (flat[:, 0] - MEAN[0]) / np.sqrt(COVARIANCE[0, 0])
    excess_kurtosis = float(np.mean(standardised**4) - 3.0)
    assert excess_kurtosis > 2.0  # theoretical value for nu = 5: 6


def test_student_t_antithetic_shares_the_mixing_variable() -> None:
    draws = student_t_log_returns(
        MEAN,
        COVARIANCE,
        degrees_of_freedom=6,
        horizon=3,
        n_paths=4,
        rng=np.random.default_rng(5),
        antithetic=True,
    )

    assert np.allclose(draws[:2] - MEAN, -(draws[2:] - MEAN))


@pytest.mark.parametrize("degrees_of_freedom", [1.0, 2.0])
def test_student_t_rejects_infinite_variance(degrees_of_freedom: float) -> None:
    with pytest.raises(ValueError, match="more than 2 degrees"):
        student_t_log_returns(
            MEAN,
            COVARIANCE,
            degrees_of_freedom=degrees_of_freedom,
            horizon=1,
            n_paths=1,
            rng=np.random.default_rng(0),
        )


# ── Stationary bootstrap ─────────────────────────────────────────────


def test_bootstrap_indices_stay_in_range() -> None:
    indices = stationary_bootstrap_indices(
        30, horizon=100, n_paths=200, mean_block=5.0, rng=np.random.default_rng(6)
    )

    assert indices.shape == (200, 100)
    assert indices.min() >= 0
    assert indices.max() <= 29


def test_bootstrap_blocks_have_the_requested_mean_length() -> None:
    indices = stationary_bootstrap_indices(
        1_000, horizon=500, n_paths=200, mean_block=8.0, rng=np.random.default_rng(7)
    )

    consecutive = np.diff(indices, axis=1) % 1_000 == 1
    # A new block starts with probability 1/8 (a random restart may also land on i+1).
    assert 1.0 - consecutive.mean() == pytest.approx(1 / 8, rel=0.05)


def test_block_length_one_is_an_iid_bootstrap() -> None:
    indices = stationary_bootstrap_indices(
        10, horizon=2_000, n_paths=10, mean_block=1.0, rng=np.random.default_rng(8)
    )

    counts = np.bincount(indices.ravel(), minlength=10) / indices.size
    assert np.allclose(counts, 0.1, atol=0.01)


def test_bootstrap_blocks_wrap_around_the_sample() -> None:
    indices = stationary_bootstrap_indices(
        3, horizon=50, n_paths=1, mean_block=1e9, rng=np.random.default_rng(9)
    )

    assert set(np.diff(indices[0]) % 3) == {1}


@pytest.mark.parametrize(("n_observations", "mean_block"), [(0, 5.0), (10, 0.5)])
def test_bootstrap_rejects_invalid_parameters(n_observations: int, mean_block: float) -> None:
    with pytest.raises(ValueError, match="Bootstrap needs"):
        stationary_bootstrap_indices(
            n_observations, horizon=5, n_paths=1, mean_block=mean_block, rng=np.random.default_rng()
        )


# ── Portfolio values under rebalancing ───────────────────────────────

# Two paths, two steps, two assets.
RETURNS = np.array(
    [
        [[0.10, -0.10], [0.10, -0.10]],
        [[0.00, 0.00], [0.50, 0.00]],
    ]
)


def test_buy_and_hold_lets_weights_drift() -> None:
    values = rebalanced_values(RETURNS, np.array([0.5, 0.5]), initial_value=100.0)

    # Path 0: 50 * 1.1 * 1.1 + 50 * 0.9 * 0.9 = 60.5 + 40.5.
    assert values[0].tolist() == pytest.approx([100.0, 100.0, 101.0])
    assert values[1].tolist() == pytest.approx([100.0, 100.0, 125.0])


def test_constant_mix_rebalances_every_step() -> None:
    values = rebalanced_values(
        RETURNS, np.array([0.5, 0.5]), initial_value=100.0, rebalance_every=1
    )

    # Path 0 rebalances back to 50/50 after step 1, so step 2 grows by exactly 1.0.
    assert values[0].tolist() == pytest.approx([100.0, 100.0, 100.0])
    assert values[1].tolist() == pytest.approx([100.0, 100.0, 125.0])


def test_rebalancing_every_n_steps_matches_buy_and_hold_within_a_period() -> None:
    weights = np.array([0.6, 0.4])
    rng = np.random.default_rng(10)
    returns = rng.normal(0.0, 0.02, size=(50, 10, 2))

    held = rebalanced_values(returns, weights)
    every_ten = rebalanced_values(returns, weights, rebalance_every=10)

    assert np.allclose(held, every_ten)


def test_band_rebalances_only_when_weights_drift_enough() -> None:
    weights = np.array([0.5, 0.5])

    narrow = rebalanced_values(RETURNS, weights, initial_value=100.0, band=0.01)
    wide = rebalanced_values(RETURNS, weights, initial_value=100.0, band=0.5)

    assert narrow[0, -1] == pytest.approx(100.0)  # drifted to 55/45 → rebalanced
    assert wide[0, -1] == pytest.approx(101.0)  # never rebalanced


def test_ruined_paths_stay_at_zero() -> None:
    # Long 200 % / short -100 %: when the short leg doubles, the portfolio is wiped out.
    returns = np.array([[[0.0, 1.0], [0.5, -0.5]]])
    weights = np.array([2.0, -1.0])

    held = rebalanced_values(returns, weights, initial_value=100.0)
    mixed = rebalanced_values(returns, weights, initial_value=100.0, rebalance_every=1)

    assert held[0].tolist() == pytest.approx([100.0, 0.0, 0.0])
    assert mixed[0].tolist() == pytest.approx([100.0, 0.0, 0.0])


def test_path_max_drawdowns() -> None:
    values = np.array([[100.0, 120.0, 90.0, 130.0], [100.0, 101.0, 102.0, 103.0]])

    drawdowns = path_max_drawdowns(values)

    assert drawdowns.tolist() == pytest.approx([-0.25, 0.0])


def test_path_max_drawdown_of_a_ruined_path_is_total() -> None:
    assert path_max_drawdowns(np.array([[100.0, 50.0, 0.0, 0.0]])).tolist() == [-1.0]
