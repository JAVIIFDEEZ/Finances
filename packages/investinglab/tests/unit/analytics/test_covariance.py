from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from investinglab.analytics import (
    correlation_from_covariance,
    covariance_matrix,
    is_positive_semidefinite,
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
