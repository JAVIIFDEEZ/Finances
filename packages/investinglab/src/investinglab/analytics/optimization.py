"""Portfolio optimisation kernels (ADR-0023).

Pure NumPy/SciPy functions over a vector of expected returns and a covariance matrix in the
same units (both annual, or both per period). Weights come back in the order of the inputs
and sum to 1.

* **Mean-variance**: minimum variance, maximum Sharpe ratio, a target return and the
  efficient frontier, under per-asset bounds. They are convex quadratic programmes with
  linear constraints, solved with SLSQP; the maximum Sharpe ratio uses the homogenised
  formulation of Cornuejols and Tütüncü (2007), which is convex too.
* **Risk-based**: risk budgeting and equal risk contribution (Spinu, 2013, by Newton's
  method), hierarchical risk parity (López de Prado, 2016) and inverse volatility. They
  need no expected returns.
* **Black-Litterman** (1992): equilibrium returns implied by a reference portfolio and
  their update with investor views.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

import numpy as np
from scipy.cluster.hierarchy import leaves_list, linkage
from scipy.optimize import Bounds, LinearConstraint, minimize
from scipy.spatial.distance import pdist

if TYPE_CHECKING:
    from collections.abc import Callable

    from numpy.typing import ArrayLike

__all__ = [
    "OptimizationError",
    "black_litterman",
    "efficient_frontier",
    "hierarchical_risk_parity_weights",
    "implied_returns",
    "inverse_volatility_weights",
    "max_sharpe_weights",
    "min_variance_weights",
    "return_range",
    "risk_budget_weights",
    "target_return_weights",
]

_FEASIBILITY: Final = 1e-7
_FTOL: Final = 1e-14
_MAX_ITERATIONS: Final = 1_000


class OptimizationError(ValueError):
    """The problem is infeasible, ill-posed or the solver did not converge."""


# ── Validation and helpers ───────────────────────────────────────────


def _covariance(covariance: ArrayLike) -> np.ndarray:
    matrix = np.asarray(covariance, dtype="float64")
    if matrix.ndim != 2 or matrix.shape[0] != matrix.shape[1] or matrix.shape[0] == 0:  # noqa: PLR2004
        raise OptimizationError("The covariance must be a non-empty square matrix")
    if not np.isfinite(matrix).all():
        raise OptimizationError("The covariance has missing or infinite values")
    return np.asarray((matrix + matrix.T) / 2, dtype="float64")


def _vector(values: ArrayLike, size: int, name: str) -> np.ndarray:
    vector = np.asarray(values, dtype="float64").reshape(-1)
    if vector.size != size:
        raise OptimizationError(f"{name} has {vector.size} values for {size} assets")
    if not np.isfinite(vector).all():
        raise OptimizationError(f"{name} has missing or infinite values")
    return vector


def _bounds(size: int, lower: ArrayLike, upper: ArrayLike) -> tuple[np.ndarray, np.ndarray]:
    low = np.broadcast_to(np.asarray(lower, dtype="float64"), (size,)).copy()
    high = np.broadcast_to(np.asarray(upper, dtype="float64"), (size,)).copy()
    if (low > high).any():
        raise OptimizationError("Every lower bound must not exceed its upper bound")
    if low.sum() > 1.0 + _FEASIBILITY or high.sum() < 1.0 - _FEASIBILITY:
        raise OptimizationError(
            f"No weights within the bounds sum to 1 (lower bounds add up to {low.sum():.4g}, "
            f"upper bounds to {high.sum():.4g})"
        )
    return low, high


def _scale(covariance: np.ndarray) -> float:
    """Typical variance, used to keep the solver well conditioned."""
    level = float(np.mean(np.abs(np.diag(covariance))))
    return level if level > 0 else 1.0


def _feasible_start(low: np.ndarray, high: np.ndarray) -> np.ndarray:
    """Weights as equal as the bounds allow: ``clip(level, low, high)`` summing to 1."""
    floor, ceiling = float(low.min()), float(high.max())
    for _ in range(200):
        level = (floor + ceiling) / 2
        if np.clip(level, low, high).sum() > 1.0:
            ceiling = level
        else:
            floor = level
    return np.asarray(np.clip((floor + ceiling) / 2, low, high), dtype="float64")


def _extreme_portfolio(mean: np.ndarray, low: np.ndarray, high: np.ndarray) -> np.ndarray:
    """Weights with the highest ``mean @ w`` within the bounds (a fractional knapsack)."""
    weights = low.copy()
    budget = 1.0 - float(low.sum())
    for asset in np.argsort(-mean, kind="stable"):
        step = min(budget, float(high[asset] - low[asset]))
        weights[asset] += step
        budget -= step
    return weights


def return_range(
    mean: ArrayLike, *, lower: ArrayLike = 0.0, upper: ArrayLike = 1.0
) -> tuple[float, float]:
    """Lowest and highest expected return reachable within the bounds."""
    expected = np.asarray(mean, dtype="float64").reshape(-1)
    low, high = _bounds(expected.size, lower, upper)
    lowest = _extreme_portfolio(-expected, low, high)
    highest = _extreme_portfolio(expected, low, high)
    return float(expected @ lowest), float(expected @ highest)


def _solve(
    objective: Callable[[np.ndarray], float],
    gradient: Callable[[np.ndarray], np.ndarray],
    start: np.ndarray,
    bounds: Bounds,
    constraints: list[LinearConstraint],
) -> np.ndarray:
    """SLSQP on a smooth objective with linear constraints, checked for feasibility.

    Equalities and inequalities go in separate constraints, as SLSQP expects.
    """
    result = minimize(
        objective,
        start,
        jac=gradient,
        method="SLSQP",
        bounds=bounds,
        constraints=constraints,
        options={"ftol": _FTOL, "maxiter": _MAX_ITERATIONS},
    )
    solution = np.asarray(result.x, dtype="float64")
    for constraint in constraints:
        values = np.asarray(constraint.A, dtype="float64") @ solution
        floors = np.asarray(constraint.lb, dtype="float64")
        ceilings = np.asarray(constraint.ub, dtype="float64")
        if (values < floors - _FEASIBILITY).any() or (values > ceilings + _FEASIBILITY).any():
            raise OptimizationError(f"The optimiser did not converge: {result.message}")
    return solution


def _clean(weights: np.ndarray, low: np.ndarray, high: np.ndarray) -> np.ndarray:
    """Remove solver noise: clip to the bounds and spread the residual on free weights."""
    clipped = np.clip(weights, low, high)
    residual = 1.0 - float(clipped.sum())
    room = high - clipped if residual > 0 else clipped - low
    if residual != 0 and room.sum() > 0:
        clipped = clipped + residual * room / room.sum()
    return np.asarray(clipped, dtype="float64")


def _quadratic(
    matrix: np.ndarray,
) -> tuple[Callable[[np.ndarray], float], Callable[[np.ndarray], np.ndarray]]:
    """``w'Sw`` and its gradient, with the variance scaled to a typical value of 1."""
    scaled = matrix / _scale(matrix)

    def value(weights: np.ndarray) -> float:
        return float(weights @ scaled @ weights)

    def gradient(weights: np.ndarray) -> np.ndarray:
        return np.asarray(2.0 * scaled @ weights, dtype="float64")

    return value, gradient


# ── Mean-variance ───────────────────────────────────────────────────


def min_variance_weights(
    covariance: ArrayLike, *, lower: ArrayLike = 0.0, upper: ArrayLike = 1.0
) -> np.ndarray:
    """Weights with the lowest variance within the bounds (long-only by default).

    Raises:
        OptimizationError: If no weights within the bounds sum to 1.
    """
    matrix = _covariance(covariance)
    low, high = _bounds(matrix.shape[0], lower, upper)
    objective, gradient = _quadratic(matrix)
    weights = _solve(
        objective,
        gradient,
        _feasible_start(low, high),
        Bounds(low, high),
        [LinearConstraint(np.ones((1, low.size)), 1.0, 1.0)],
    )
    return _clean(weights, low, high)


def target_return_weights(
    mean: ArrayLike,
    covariance: ArrayLike,
    target: float,
    *,
    lower: ArrayLike = 0.0,
    upper: ArrayLike = 1.0,
) -> np.ndarray:
    """Weights with the lowest variance among those expecting ``target``.

    Raises:
        OptimizationError: If ``target`` is out of reach within the bounds.
    """
    matrix = _covariance(covariance)
    expected = _vector(mean, matrix.shape[0], "The expected returns")
    low, high = _bounds(expected.size, lower, upper)
    lowest = _extreme_portfolio(-expected, low, high)
    highest = _extreme_portfolio(expected, low, high)
    floor, ceiling = float(expected @ lowest), float(expected @ highest)
    tolerance = _FEASIBILITY * max(1.0, abs(floor), abs(ceiling))
    if not floor - tolerance <= target <= ceiling + tolerance:
        raise OptimizationError(
            f"A target return of {target:.6g} is out of reach: between {floor:.6g} and "
            f"{ceiling:.6g} within the bounds"
        )
    goal = min(max(target, floor), ceiling)
    share = 0.0 if ceiling == floor else (goal - floor) / (ceiling - floor)
    scale = max(float(np.abs(expected).max()), 1e-300)
    rows = np.vstack([np.ones(expected.size), expected / scale])
    goals = np.array([1.0, goal / scale])
    objective, gradient = _quadratic(matrix)
    weights = _solve(
        objective,
        gradient,
        (1.0 - share) * lowest + share * highest,
        Bounds(low, high),
        [LinearConstraint(rows, goals, goals)],
    )
    return _clean(weights, low, high)


def max_sharpe_weights(
    mean: ArrayLike,
    covariance: ArrayLike,
    *,
    risk_free: float = 0.0,
    lower: ArrayLike = 0.0,
    upper: ArrayLike = 1.0,
) -> np.ndarray:
    """Weights with the highest Sharpe ratio within the bounds (the tangency portfolio).

    Solved as ``min y'Σy`` subject to ``(μ - r)'y = 1``, ``Σy = κ`` and
    ``lower·κ <= y <= upper·κ`` with ``κ >= 0``; the weights are ``y / κ``.

    Raises:
        OptimizationError: If no weights within the bounds expect more than ``risk_free``.
    """
    matrix = _covariance(covariance)
    excess = _vector(mean, matrix.shape[0], "The expected returns") - risk_free
    low, high = _bounds(excess.size, lower, upper)
    best = _extreme_portfolio(excess, low, high)
    if float(excess @ best) <= 0:
        raise OptimizationError(
            "No weights within the bounds expect more than the risk-free rate: the maximum "
            "Sharpe ratio is undefined"
        )
    size = excess.size
    unit = excess / float(np.abs(excess).max())
    first = best / float(unit @ best)
    # Over z = (y, κ): unit'y = 1 and Σy - κ = 0; y - low·κ >= 0 and high·κ - y >= 0.
    equalities = np.vstack([np.append(unit, 0.0), np.append(np.ones(size), -1.0)])
    inequalities = np.vstack(
        [
            np.hstack([np.eye(size), -low.reshape(-1, 1)]),
            np.hstack([-np.eye(size), high.reshape(-1, 1)]),
        ]
    )
    variance, slope = _quadratic(matrix)
    solution = _solve(
        lambda z: variance(z[:size]),
        lambda z: np.append(slope(z[:size]), 0.0),
        np.append(first, first.sum()),
        Bounds(np.append(np.full(size, -np.inf), 0.0), np.full(size + 1, np.inf)),
        [
            LinearConstraint(equalities, [1.0, 0.0], [1.0, 0.0]),
            LinearConstraint(inequalities, 0.0, np.inf),
        ],
    )
    return _clean(solution[:size] / float(solution[size]), low, high)


def efficient_frontier(
    mean: ArrayLike,
    covariance: ArrayLike,
    *,
    points: int = 30,
    lower: ArrayLike = 0.0,
    upper: ArrayLike = 1.0,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Minimum-variance portfolios from the global minimum up to the highest return.

    Returns:
        Expected returns ``(points,)``, volatilities ``(points,)`` and weights
        ``(points, assets)``, from the least to the most risky.
    """
    if points < 2:  # noqa: PLR2004
        raise OptimizationError("An efficient frontier needs at least two points")
    matrix = _covariance(covariance)
    expected = _vector(mean, matrix.shape[0], "The expected returns")
    minimum = min_variance_weights(matrix, lower=lower, upper=upper)
    _, highest = return_range(expected, lower=lower, upper=upper)
    targets = np.linspace(float(expected @ minimum), highest, points)
    weights = [minimum] + [
        target_return_weights(expected, matrix, target, lower=lower, upper=upper)
        for target in targets[1:]
    ]
    stacked = np.vstack(weights)
    variances = np.einsum("ij,jk,ik->i", stacked, matrix, stacked)
    return stacked @ expected, np.sqrt(np.clip(variances, 0.0, None)), stacked


# ── Risk-based ──────────────────────────────────────────────────────


def _positive_variances(matrix: np.ndarray, method: str) -> np.ndarray:
    variances = np.diag(matrix)
    if (variances <= 0).any():
        raise OptimizationError(f"{method} needs every asset to have a positive variance")
    return np.asarray(variances, dtype="float64")


def inverse_volatility_weights(covariance: ArrayLike) -> np.ndarray:
    """Weights proportional to ``1 / volatility`` (correlations are ignored)."""
    matrix = _covariance(covariance)
    inverse = 1.0 / np.sqrt(_positive_variances(matrix, "Inverse volatility"))
    return np.asarray(inverse / inverse.sum(), dtype="float64")


def risk_budget_weights(
    covariance: ArrayLike,
    budgets: ArrayLike | None = None,
    *,
    tolerance: float = 1e-10,
    max_iterations: int = 200,
) -> np.ndarray:
    """Long-only weights whose risk contributions match ``budgets`` (equal by default).

    Minimises the strictly convex ``½·y'Σy - Σ bᵢ·ln yᵢ`` (Spinu, 2013) with Newton's
    method and a backtracking line search; the weights are ``y / Σy``. With equal budgets
    this is the equal-risk-contribution (risk parity) portfolio.

    Raises:
        OptimizationError: If a budget is not positive, an asset has no variance or the
            iteration does not converge.
    """
    matrix = _covariance(covariance)
    size = matrix.shape[0]
    shares = np.full(size, 1.0 / size) if budgets is None else _vector(budgets, size, "Budgets")
    if (shares <= 0).any():
        raise OptimizationError("Every risk budget must be positive")
    shares = shares / shares.sum()
    scaled = matrix / _scale(matrix)
    y = shares / np.sqrt(_positive_variances(scaled, "Risk budgeting"))

    def value(point: np.ndarray) -> float:
        return float(0.5 * point @ scaled @ point - shares @ np.log(point))

    for _ in range(max_iterations):
        gradient = scaled @ y - shares / y
        if float(np.abs(gradient).max()) < tolerance:
            return np.asarray(y / y.sum(), dtype="float64")
        step = np.linalg.solve(scaled + np.diag(shares / y**2), gradient)
        descent, current, length = float(gradient @ step), value(y), 1.0
        candidate = y - step
        while (candidate <= 0).any() or value(candidate) > current - 1e-4 * length * descent:
            length /= 2
            candidate = y - length * step
            if length < 1e-12:  # noqa: PLR2004 - no representable decrease left
                break
        y = candidate
    raise OptimizationError("Risk budgeting did not converge")


def _cluster_variance(matrix: np.ndarray, items: list[int]) -> float:
    block = matrix[np.ix_(items, items)]
    inverse = 1.0 / np.diag(block)
    weights = inverse / inverse.sum()
    return float(weights @ block @ weights)


def hierarchical_risk_parity_weights(covariance: ArrayLike) -> np.ndarray:
    """Hierarchical risk parity (López de Prado, 2016).

    1. Distance ``√((1 - correlation) / 2)`` between assets, and the Euclidean distance
       between the columns of that matrix, clustered with single linkage.
    2. Quasi-diagonalisation: assets in the order of the dendrogram's leaves.
    3. Recursive bisection: each half gets a share inversely proportional to its
       inverse-variance variance.

    Needs no matrix inversion, so it stays stable with highly correlated assets. With
    uncorrelated assets it equals inverse-variance weighting.
    """
    matrix = _covariance(covariance)
    size = matrix.shape[0]
    std = np.sqrt(_positive_variances(matrix, "Hierarchical risk parity"))
    if size == 1:
        return np.ones(1)
    correlation = np.clip(matrix / np.outer(std, std), -1.0, 1.0)
    distance = np.sqrt(np.clip((1.0 - correlation) / 2.0, 0.0, None))
    order = [int(item) for item in leaves_list(linkage(pdist(distance), method="single"))]
    weights = np.ones(size)
    clusters = [order]
    while clusters:
        clusters = [
            part
            for cluster in clusters
            if len(cluster) > 1
            for part in (cluster[: len(cluster) // 2], cluster[len(cluster) // 2 :])
        ]
        for left, right in zip(clusters[::2], clusters[1::2], strict=True):
            left_variance = _cluster_variance(matrix, left)
            right_variance = _cluster_variance(matrix, right)
            alpha = 1.0 - left_variance / (left_variance + right_variance)
            weights[left] *= alpha
            weights[right] *= 1.0 - alpha
    return np.asarray(weights / weights.sum(), dtype="float64")


# ── Black-Litterman ─────────────────────────────────────────────────


def implied_returns(covariance: ArrayLike, weights: ArrayLike, risk_aversion: float) -> np.ndarray:
    """Equilibrium excess returns ``δ·Σ·w`` that make ``weights`` optimal (reverse optimisation)."""
    matrix = _covariance(covariance)
    if not risk_aversion > 0:
        raise OptimizationError("The risk aversion must be positive")
    weights_vector = _vector(weights, matrix.shape[0], "Weights")
    return np.asarray(risk_aversion * matrix @ weights_vector, dtype="float64")


def black_litterman(
    prior: ArrayLike,
    covariance: ArrayLike,
    picks: ArrayLike,
    views: ArrayLike,
    *,
    tau: float = 0.05,
    uncertainty: ArrayLike | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Posterior expected returns and covariance after blending ``prior`` with views.

    Args:
        prior: Expected returns before the views, usually :func:`implied_returns`.
        covariance: Covariance of returns.
        picks: ``(views, assets)`` matrix: each row is a view portfolio (``[1, 0, 0]`` for an
            absolute view on the first asset, ``[1, -1, 0]`` for a relative one).
        views: Expected return of each view portfolio.
        tau: Uncertainty of the prior relative to the covariance.
        uncertainty: Covariance of the views (Ω). By default it is proportional to the
            prior's (He & Litterman, 1999): ``diag(P·τΣ·P')``.

    Returns:
        ``μ = π + τΣP'(PτΣP' + Ω)⁻¹(Q - Pπ)`` and ``Σ + τΣ - τΣP'(PτΣP' + Ω)⁻¹PτΣ``.

    Raises:
        OptimizationError: If the views are malformed, redundant or contradictory.
    """
    matrix = _covariance(covariance)
    size = matrix.shape[0]
    pi = _vector(prior, size, "The prior")
    pick = np.atleast_2d(np.asarray(picks, dtype="float64"))
    if pick.shape[1] != size:
        raise OptimizationError(f"Each view needs {size} weights, got {pick.shape[1]}")
    if (np.abs(pick).sum(axis=1) == 0).any():
        raise OptimizationError("Every view needs at least one asset")
    q = _vector(views, pick.shape[0], "The views")
    if not tau > 0:
        raise OptimizationError("tau must be positive")
    scaled = tau * matrix
    projected = pick @ scaled
    omega = (
        np.diag(np.diag(projected @ pick.T))
        if uncertainty is None
        else np.atleast_2d(np.asarray(uncertainty, dtype="float64"))
    )
    if omega.shape != (q.size, q.size):
        raise OptimizationError(f"The view uncertainty must be {q.size}x{q.size}")
    try:
        gain = np.linalg.solve(projected @ pick.T + omega, projected).T
    except np.linalg.LinAlgError as error:
        raise OptimizationError("The views are redundant or contradictory") from error
    posterior = pi + gain @ (q - pick @ pi)
    posterior_covariance = matrix + scaled - gain @ projected
    return posterior, np.asarray((posterior_covariance + posterior_covariance.T) / 2)
