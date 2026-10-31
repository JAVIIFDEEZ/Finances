from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from investinglab.analytics import (
    correlation_from_covariance,
    covariance_matrix,
    is_positive_semidefinite,
    ledoit_wolf,
    nearest_positive_semidefinite,
)


def test_covariance_uses_pairwise_complete_observations() -> None:
    returns = pd.DataFrame(
        {"A": [0.01, -0.02, np.nan, 0.03, 0.01], "B": [0.02, -0.01, 0.01, np.nan, 0.0]}
    )

    covariance = covariance_matrix(returns)

    common = returns.dropna()
    assert covariance["B"]["A"] == pytest.approx(common["A"].cov(common["B"]))
    assert covariance["A"]["A"] == pytest.approx(returns["A"].var())


def test_inconsistent_pairwise_estimates_are_repaired_to_psd() -> None:
    # Pairwise correlations that cannot coexist: A~B and A~C strongly positive, B~C negative.
    impossible = np.array([[1.0, 0.9, 0.9], [0.9, 1.0, -0.9], [0.9, -0.9, 1.0]])

    repaired = nearest_positive_semidefinite(impossible)

    assert not is_positive_semidefinite(impossible)
    assert is_positive_semidefinite(repaired, tolerance=1e-10)
    assert np.allclose(np.diag(repaired), 1.0)


def test_non_psd_sample_is_repaired_inside_covariance_matrix() -> None:
    # Each pair is observed on a different subset: A~B = +1, A~C = +1 but B~C = -1,
    # which no joint distribution can produce.
    x = np.array([0.01, -0.02, 0.03, -0.01, 0.02])
    nan = np.full(5, np.nan)
    frame = pd.DataFrame(
        {
            "A": np.concatenate([x, x, nan]),
            "B": np.concatenate([x, nan, x]),
            "C": np.concatenate([nan, x, -x]),
        }
    )

    raw = frame.cov(min_periods=2).to_numpy()
    covariance = covariance_matrix(frame)

    assert not is_positive_semidefinite(raw)
    assert is_positive_semidefinite(covariance.to_numpy(), tolerance=1e-10)
    assert np.allclose(np.diag(covariance), np.diag(raw))


def test_pairs_without_enough_overlap_are_nan_and_left_alone() -> None:
    returns = pd.DataFrame({"A": [0.01, 0.02, np.nan, np.nan], "B": [np.nan, np.nan, 0.01, 0.02]})

    covariance = covariance_matrix(returns)

    assert np.isnan(covariance["B"]["A"])


def test_correlation_is_consistent_with_covariance() -> None:
    covariance = pd.DataFrame([[0.04, 0.006], [0.006, 0.01]], index=["A", "B"], columns=["A", "B"])

    correlation = correlation_from_covariance(covariance)

    assert correlation["B"]["A"] == pytest.approx(0.006 / (0.2 * 0.1))
    assert np.allclose(np.diag(correlation), 1.0)


def test_zero_variance_assets_have_undefined_correlation() -> None:
    covariance = pd.DataFrame([[0.0, 0.0], [0.0, 0.01]], index=["A", "B"], columns=["A", "B"])

    correlation = correlation_from_covariance(covariance)

    assert np.isnan(correlation["A"]["A"])
    assert correlation["B"]["B"] == 1.0


# ── Ledoit-Wolf shrinkage ────────────────────────────────────────────

LW_OBSERVATIONS = np.array(
    [
        [0.01, 0.02, -0.01],
        [-0.02, 0.01, 0.0],
        [0.03, -0.01, 0.02],
        [0.0, 0.015, -0.005],
        [-0.01, -0.02, 0.01],
        [0.02, 0.0, 0.0],
    ]
)


def test_ledoit_wolf_matches_the_reference_implementation() -> None:
    # Reference values from scikit-learn's ``sklearn.covariance.ledoit_wolf``.
    expected = np.array(
        [
            [2.13178089e-04, -5.27883867e-06, 9.80355754e-06],
            [-5.27883867e-06, 1.96210393e-04, -2.14924146e-05],
            [9.80355754e-06, -2.14924146e-05, 1.78111518e-04],
        ]
    )

    shrunk, shrinkage = ledoit_wolf(LW_OBSERVATIONS)

    assert shrinkage == pytest.approx(0.8190112454911952)
    assert np.allclose(shrunk, expected, rtol=1e-7, atol=1e-14)


def test_ledoit_wolf_keeps_the_total_variance() -> None:
    rng = np.random.default_rng(0)
    observations = rng.standard_normal((20, 8)) * 0.01

    shrunk, shrinkage = ledoit_wolf(observations)
    centred = observations - observations.mean(axis=0)
    sample = centred.T @ centred / len(observations)

    assert 0.0 <= shrinkage <= 1.0
    assert np.trace(shrunk) == pytest.approx(np.trace(sample))
    assert is_positive_semidefinite(shrunk)


def test_ledoit_wolf_regularises_more_assets_than_observations() -> None:
    rng = np.random.default_rng(1)
    observations = rng.standard_normal((5, 12)) * 0.01

    shrunk, _ = ledoit_wolf(observations)

    assert np.linalg.matrix_rank(shrunk) == 12
    assert np.linalg.eigvalsh(shrunk).min() > 0


def test_ledoit_wolf_shrinks_little_with_long_histories() -> None:
    rng = np.random.default_rng(2)
    correlated = rng.multivariate_normal([0.0, 0.0], [[1.0, 0.8], [0.8, 1.0]], size=5_000)

    _, shrinkage = ledoit_wolf(correlated)

    assert shrinkage < 0.01


def test_ledoit_wolf_returns_the_sample_when_it_is_already_a_scaled_identity() -> None:
    observations = np.array([[1.0, 1.0], [-1.0, -1.0], [1.0, -1.0], [-1.0, 1.0]])

    shrunk, shrinkage = ledoit_wolf(observations)

    assert shrinkage == 0.0
    assert np.allclose(shrunk, np.eye(2))


@pytest.mark.parametrize(
    "observations",
    [
        np.array([[0.01, 0.02]]),
        np.array([0.01, 0.02, 0.03]),
        np.array([[0.01, np.nan], [0.0, 0.1]]),
    ],
    ids=["one-row", "one-dimensional", "missing-value"],
)
def test_ledoit_wolf_rejects_unusable_input(observations: np.ndarray) -> None:
    with pytest.raises(ValueError, match="Ledoit-Wolf needs"):
        ledoit_wolf(observations)
