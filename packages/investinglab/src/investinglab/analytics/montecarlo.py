"""Vectorised Monte Carlo kernels (ADR-0016).

Shocks are generated for many paths at once with NumPy (no loop per path). Only the time
dimension is iterated where the dynamics require it (rebalancing a portfolio), and always
vectorised across paths and assets.

Conventions: returns are per period; ``mean`` and ``covariance`` describe **log** returns
(discrete-time geometric Brownian motion when the shocks are Gaussian).
"""

from __future__ import annotations

import numpy as np

__all__ = [
    "cholesky_factor",
    "normal_log_returns",
    "path_max_drawdowns",
    "rebalanced_values",
    "stationary_bootstrap_indices",
    "student_t_log_returns",
]


def cholesky_factor(covariance: np.ndarray) -> np.ndarray:
    """Matrix ``L`` with ``L @ L.T == covariance`` (lower-triangular when possible).

    Falls back to an eigen-decomposition square root for positive *semi*-definite matrices
    (e.g. perfectly correlated assets), where the Cholesky factorisation does not exist.
    """
    matrix = np.asarray(covariance, dtype="float64")
    try:
        return np.asarray(np.linalg.cholesky(matrix), dtype="float64")
    except np.linalg.LinAlgError:
        eigenvalues, eigenvectors = np.linalg.eigh((matrix + matrix.T) / 2)
        return np.asarray(eigenvectors * np.sqrt(np.clip(eigenvalues, 0.0, None)), dtype="float64")


def _standard_normals(
    rng: np.random.Generator, n_paths: int, horizon: int, assets: int, *, antithetic: bool
) -> np.ndarray:
    if not antithetic:
        return rng.standard_normal((n_paths, horizon, assets))
    half = (n_paths + 1) // 2
    draws = rng.standard_normal((half, horizon, assets))
    return np.concatenate([draws, -draws])[:n_paths]


def normal_log_returns(
    mean: np.ndarray,
    covariance: np.ndarray,
    *,
    horizon: int,
    n_paths: int,
    rng: np.random.Generator,
    antithetic: bool = False,
) -> np.ndarray:
    """Correlated Gaussian log returns, shape ``(n_paths, horizon, assets)``.

    With antithetic variates, every second half of the paths mirrors the first one
    (``Z`` and ``-Z``), which reduces the variance of estimated means.
    """
    factor = cholesky_factor(covariance)
    shocks = _standard_normals(rng, n_paths, horizon, len(mean), antithetic=antithetic)
    return np.asarray(mean + shocks @ factor.T, dtype="float64")


def student_t_log_returns(
    mean: np.ndarray,
    covariance: np.ndarray,
    *,
    degrees_of_freedom: float,
    horizon: int,
    n_paths: int,
    rng: np.random.Generator,
    antithetic: bool = False,
) -> np.ndarray:
    """Multivariate Student-t log returns with the given covariance (fat tails).

    Shocks are ``Z / sqrt(W / nu)`` with ``W ~ chi2(nu)``, rescaled by ``sqrt((nu-2)/nu)`` so
    the covariance equals ``covariance``. All assets share the mixing variable, so extreme
    moves happen together, as in market crashes.

    Raises:
        ValueError: If ``degrees_of_freedom <= 2`` (infinite variance).
    """
    if degrees_of_freedom <= 2:  # noqa: PLR2004
        raise ValueError("Student-t shocks need more than 2 degrees of freedom")
    factor = cholesky_factor(covariance)
    normals = _standard_normals(rng, n_paths, horizon, len(mean), antithetic=antithetic)
    mixing = rng.chisquare(degrees_of_freedom, size=(n_paths, horizon, 1))
    if antithetic:
        half = (n_paths + 1) // 2
        mixing = np.concatenate([mixing[:half], mixing[:half]])[:n_paths]
    scale = np.sqrt((degrees_of_freedom - 2) / mixing)
    return np.asarray(mean + (normals * scale) @ factor.T, dtype="float64")


def stationary_bootstrap_indices(
    n_observations: int,
    *,
    horizon: int,
    n_paths: int,
    mean_block: float,
    rng: np.random.Generator,
) -> np.ndarray:
    """Row indices of a stationary bootstrap (Politis & Romano, 1994).

    Each path concatenates blocks of consecutive historical periods whose lengths are
    geometric with mean ``mean_block``, wrapping around the end of the sample. Resampling
    whole rows preserves the cross-asset correlation; blocks preserve short-term serial
    dependence (volatility clustering).

    Returns:
        Integer array of shape ``(n_paths, horizon)``.
    """
    if n_observations < 1 or mean_block < 1:
        raise ValueError("Bootstrap needs observations and a mean block length >= 1")
    restart = rng.random((n_paths, horizon)) < 1.0 / mean_block
    starts = rng.integers(0, n_observations, size=(n_paths, horizon))
    indices = np.empty((n_paths, horizon), dtype=np.int64)
    indices[:, 0] = starts[:, 0]
    for step in range(1, horizon):
        following = (indices[:, step - 1] + 1) % n_observations
        indices[:, step] = np.where(restart[:, step], starts[:, step], following)
    return indices


def rebalanced_values(
    simple_returns: np.ndarray,
    target_weights: np.ndarray,
    *,
    initial_value: float = 1.0,
    rebalance_every: int | None = None,
    band: float | None = None,
) -> np.ndarray:
    """Portfolio value paths under a rebalancing rule.

    Args:
        simple_returns: Asset simple returns, shape ``(n_paths, horizon, assets)``.
        target_weights: Target weights summing to 1.
        initial_value: Value at step 0.
        rebalance_every: Return to targets every this many steps (1 = constant mix).
        band: Return to targets whenever a weight drifts more than this.

    Returns:
        Values of shape ``(n_paths, horizon + 1)``. A path that loses everything stays at 0.
    """
    n_paths, horizon, _ = simple_returns.shape
    targets = np.asarray(target_weights, dtype="float64")
    if rebalance_every is None and band is None:
        growth = np.cumprod(1.0 + simple_returns, axis=1) @ targets
        values = np.empty((n_paths, horizon + 1))
        values[:, 0] = 1.0
        values[:, 1:] = growth
        # With short positions a path can reach zero: it is ruined and stays there.
        alive = np.logical_and.accumulate(values > 0.0, axis=1)
        return np.asarray(initial_value * np.where(alive, values, 0.0), dtype="float64")

    values = np.empty((n_paths, horizon + 1))
    values[:, 0] = initial_value
    weights = np.broadcast_to(targets, (n_paths, targets.size)).copy()
    alive = np.ones(n_paths, dtype=bool)
    for step in range(horizon):
        grown = weights * (1.0 + simple_returns[:, step, :])
        growth = grown.sum(axis=1)
        ruined = growth <= 0.0
        alive &= ~ruined
        safe_growth = np.where(alive, growth, 1.0)
        values[:, step + 1] = np.where(alive, values[:, step] * safe_growth, 0.0)
        weights = grown / safe_growth[:, None]
        reset = np.zeros(n_paths, dtype=bool)
        if rebalance_every is not None and (step + 1) % rebalance_every == 0:
            reset[:] = True
        if band is not None:
            reset |= np.abs(weights - targets).max(axis=1) > band
        weights[reset] = targets
    return values


def path_max_drawdowns(values: np.ndarray) -> np.ndarray:
    """Worst peak-to-trough decline of each path (non-positive)."""
    peaks = np.maximum.accumulate(values, axis=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        drawdowns = np.where(peaks > 0, values / peaks - 1.0, -1.0)
    return np.asarray(drawdowns.min(axis=1), dtype="float64")
