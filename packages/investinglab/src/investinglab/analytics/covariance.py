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
    "ledoit_wolf",
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


def ledoit_wolf(observations: np.ndarray) -> tuple[np.ndarray, float]:
    """Ledoit-Wolf (2004) shrinkage covariance towards a scaled identity matrix.

    The sample covariance of many assets estimated on few observations is noisy and
    ill-conditioned; shrinking it towards ``m * I`` (``m`` = average variance) with the
    optimal intensity reduces the estimation error. The trace (total variance) is kept.

    Args:
        observations: Complete observations, one row per period and one column per asset.

    Returns:
        The shrunk covariance (per period, maximum-likelihood scaling) and the shrinkage
        intensity in ``[0, 1]`` (0 = sample covariance, 1 = scaled identity).

    Raises:
        ValueError: With fewer than two observations or any missing value.
    """
    data = np.asarray(observations, dtype="float64")
    if data.ndim != 2 or data.shape[0] < 2:  # noqa: PLR2004
        raise ValueError("Ledoit-Wolf needs a 2-D array with at least two observations")
    if not np.isfinite(data).all():
        raise ValueError("Ledoit-Wolf needs complete observations (no NaN)")
    n, p = data.shape
    centred = data - data.mean(axis=0)
    sample = centred.T @ centred / n
    target_scale = float(np.trace(sample)) / p
    frobenius_sample = float(np.sum(sample**2))
    dispersion = (frobenius_sample - p * target_scale**2) / p
    if dispersion <= 0.0:
        return sample, 0.0
    fourth = float(np.sum(np.sum(centred**2, axis=1) ** 2))
    noise = (fourth / n - frobenius_sample) / (n * p)
    shrinkage = float(np.clip(noise / dispersion, 0.0, 1.0))
    shrunk = shrinkage * target_scale * np.eye(p) + (1.0 - shrinkage) * sample
    return shrunk, shrinkage
