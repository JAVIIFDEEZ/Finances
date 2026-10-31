"""Covariance and correlation estimation for returns observed on different calendars.

Returns of assets traded on different markets contain NaN on each market's holidays
(ADR-0008). Estimating each pair on the dates where *both* are observed (pairwise-complete
observations) keeps all the information, but the resulting matrix may not be positive
semi-definite. It is then repaired to the nearest PSD matrix so it can feed simulations
(Cholesky) and risk decompositions safely.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

__all__ = [
    "correlation_from_covariance",
    "covariance_matrix",
    "is_positive_semidefinite",
    "nearest_positive_semidefinite",
]


def is_positive_semidefinite(matrix: np.ndarray, *, tolerance: float = 1e-12) -> bool:
    """Whether a symmetric matrix has no eigenvalue below ``-tolerance``."""
    symmetric = (matrix + matrix.T) / 2
    return bool(np.linalg.eigvalsh(symmetric).min() >= -tolerance)


def nearest_positive_semidefinite(matrix: np.ndarray) -> np.ndarray:
    """Closest PSD matrix by clipping negative eigenvalues (diagonal preserved).

    The variances (diagonal) are restored after clipping so that each asset keeps its own
    volatility; only the co-movements are adjusted.
    """
    symmetric = (matrix + matrix.T) / 2
    eigenvalues, eigenvectors = np.linalg.eigh(symmetric)
    clipped = (eigenvectors * np.clip(eigenvalues, 0.0, None)) @ eigenvectors.T
    clipped = (clipped + clipped.T) / 2
    original_std = np.sqrt(np.clip(np.diag(symmetric), 0.0, None))
    clipped_std = np.sqrt(np.clip(np.diag(clipped), 0.0, None))
    with np.errstate(divide="ignore", invalid="ignore"):
        scale = np.where(clipped_std > 0, original_std / clipped_std, 0.0)
    return np.asarray(clipped * np.outer(scale, scale), dtype="float64")


def covariance_matrix(returns: pd.DataFrame, *, min_periods: int = 2) -> pd.DataFrame:
    """Sample covariance of returns from pairwise-complete observations, PSD-repaired.

    Args:
        returns: Returns with one column per asset (NaN = not observed).
        min_periods: Minimum common observations for a pair; pairs with fewer are NaN.
    """
    covariance = returns.cov(min_periods=min_periods)
    values = covariance.to_numpy()
    if np.isfinite(values).all() and not is_positive_semidefinite(values):
        values = nearest_positive_semidefinite(values)
        covariance = pd.DataFrame(values, index=covariance.index, columns=covariance.columns)
    return covariance


def correlation_from_covariance(covariance: pd.DataFrame) -> pd.DataFrame:
    """Correlation matrix consistent with a covariance matrix (unit diagonal)."""
    std = np.sqrt(np.diag(covariance.to_numpy()))
    with np.errstate(divide="ignore", invalid="ignore"):
        correlation = covariance.to_numpy() / np.outer(std, std)
    correlation = np.clip(correlation, -1.0, 1.0)
    np.fill_diagonal(correlation, np.where(std > 0, 1.0, np.nan))
    return pd.DataFrame(correlation, index=covariance.index, columns=covariance.columns)
