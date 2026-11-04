"""Portfolio optimisation on the domain model (ADR-0023).

:meth:`Portfolio.optimize() <investinglab.domain.Portfolio.optimize>` estimates the inputs
from the holdings' history, solves the chosen objective within the weight bounds and returns
an :class:`OptimizationResult`: the optimised portfolio, its ex-ante figures and the
estimates behind them. :meth:`Portfolio.efficient_frontier()
<investinglab.domain.Portfolio.efficient_frontier>` traces the whole risk-return frontier.

* **Expected returns**: the historical mean (noisy), the returns implied by the current
  weights (equilibrium) or assumed values, optionally blended with investor views
  (Black-Litterman).
* **Covariance**: Ledoit-Wolf shrinkage by default, which is more stable out of sample than
  the sample covariance.
* **Objectives**: minimum variance, maximum Sharpe ratio and a target return (with weight
  bounds), risk parity with optional risk budgets, hierarchical risk parity, inverse
  volatility and equal weights.

Everything is estimated in-sample: weights optimised on a history look better on that same
history than they will in the future. Risk-based objectives and Black-Litterman exist
precisely because mean estimates are so noisy.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, TypedDict

import numpy as np
import pandas as pd

from investinglab.analytics import (
    covariance_matrix,
    effective_number_of_assets,
    ledoit_wolf,
    risk_contributions,
)
from investinglab.analytics.optimization import (
    OptimizationError,
    black_litterman,
    efficient_frontier,
    hierarchical_risk_parity_weights,
    implied_returns,
    inverse_volatility_weights,
    max_sharpe_weights,
    min_variance_weights,
    risk_budget_weights,
    target_return_weights,
)
from investinglab.domain.errors import DomainError
from investinglab.domain.simulation import CovarianceEstimator
from investinglab.domain.time import Frequency

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from matplotlib.figure import Figure

    from investinglab.domain.portfolio import Portfolio

__all__ = [
    "EfficientFrontier",
    "Estimates",
    "Objective",
    "OptimizationConfig",
    "OptimizationInputs",
    "OptimizationResult",
    "OptimizationSettings",
    "ReturnModel",
    "View",
    "estimate",
    "frontier_points",
    "solve",
]

type PerAsset = float | Mapping[str, float]


class Objective(StrEnum):
    """What the optimisation looks for."""

    MIN_VARIANCE = "min_variance"
    """The lowest volatility (needs no expected returns)."""
    MAX_SHARPE = "max_sharpe"
    """The highest expected return per unit of risk (the tangency portfolio)."""
    TARGET_RETURN = "target_return"
    """The lowest volatility that expects ``target_return``."""
    RISK_PARITY = "risk_parity"
    """Every holding contributes the same share of risk (or its ``risk_budgets`` share)."""
    HIERARCHICAL_RISK_PARITY = "hrp"
    """Risk split across clusters of correlated holdings (López de Prado)."""
    INVERSE_VOLATILITY = "inverse_volatility"
    """Weights proportional to ``1 / volatility``."""
    EQUAL_WEIGHT = "equal_weight"
    """The same weight on every holding (a robust benchmark)."""

    @property
    def uses_expected_returns(self) -> bool:
        """Whether the expected returns (and views) change the weights."""
        return self in {Objective.MAX_SHARPE, Objective.TARGET_RETURN}

    @property
    def accepts_bounds(self) -> bool:
        """Whether ``min_weight`` and ``max_weight`` apply."""
        return self in {Objective.MIN_VARIANCE, Objective.MAX_SHARPE, Objective.TARGET_RETURN}


class ReturnModel(StrEnum):
    """How expected returns are estimated."""

    HISTORICAL = "historical"
    """Sample mean of each holding's simple returns, annualised. Very noisy."""
    EQUILIBRIUM = "equilibrium"
    """Returns that make the current weights optimal: ``rf + δ·Σ·w`` (reverse optimisation)."""


@dataclass(frozen=True, slots=True)
class View:
    """An investor view for Black-Litterman: a portfolio of holdings and its expected return.

    Attributes:
        weights: Holdings of the view and their weights: ``{"SAN.MC": 1}`` is an absolute
            view, ``{"SAN.MC": 1, "BBVA.MC": -1}`` a relative one.
        expected_return: Annual expected return of the view portfolio (decimal).
        uncertainty: Variance of the view; ``None`` makes it proportional to the
            uncertainty of the prior (He & Litterman).
    """

    weights: Mapping[str, float]
    expected_return: float
    uncertainty: float | None = None

    def __post_init__(self) -> None:
        mapping = {str(symbol): float(weight) for symbol, weight in dict(self.weights).items()}
        if not any(weight != 0 for weight in mapping.values()):
            raise DomainError("A view needs at least one holding with a non-zero weight")
        if not all(math.isfinite(weight) for weight in mapping.values()) or not math.isfinite(
            self.expected_return
        ):
            raise DomainError("A view needs finite weights and a finite expected return")
        if self.uncertainty is not None and not self.uncertainty >= 0:
            raise DomainError("The uncertainty of a view is a variance: it cannot be negative")
        object.__setattr__(self, "weights", MappingProxyType(mapping))

    @classmethod
    def absolute(
        cls, symbol: str, expected_return: float, uncertainty: float | None = None
    ) -> View:
        """``symbol`` is expected to return ``expected_return`` a year."""
        return cls({symbol: 1.0}, expected_return, uncertainty)

    @classmethod
    def relative(
        cls, winner: str, loser: str, outperformance: float, uncertainty: float | None = None
    ) -> View:
        """``winner`` is expected to beat ``loser`` by ``outperformance`` a year."""
        return cls({winner: 1.0, loser: -1.0}, outperformance, uncertainty)


class OptimizationSettings(TypedDict, total=False):
    """Keyword overrides accepted by ``Portfolio.optimize()`` (see :class:`OptimizationConfig`)."""

    objective: Objective | str
    expected_returns: ReturnModel | str | Mapping[str, float]
    views: Sequence[View]
    covariance: CovarianceEstimator | str
    risk_free_rate: float
    min_weight: PerAsset
    max_weight: PerAsset
    target_return: float | None
    risk_budgets: Mapping[str, float] | None
    risk_aversion: float
    tau: float
    frequency: Frequency | str | None
    lookback: int | None


@dataclass(frozen=True, slots=True)
class OptimizationConfig:
    """Parameters of a portfolio optimisation.

    Attributes:
        objective: What to optimise.
        expected_returns: How expected returns are estimated, or annual returns by symbol.
        views: Black-Litterman views blended with those expected returns.
        covariance: Covariance estimator; Ledoit-Wolf shrinkage by default.
        risk_free_rate: Effective annual risk-free rate (maximum Sharpe ratio, equilibrium
            returns).
        min_weight: Lowest weight of every holding, or by symbol (negative = short).
        max_weight: Highest weight of every holding, or by symbol.
        target_return: Annual expected return for the ``target_return`` objective.
        risk_budgets: Share of risk of each holding for ``risk_parity`` (equal by default).
        risk_aversion: Risk aversion δ of the equilibrium returns.
        tau: Uncertainty of the prior relative to the covariance (Black-Litterman).
        frequency: Frequency of the returns used for the estimates; weekly returns avoid
            the bias of markets that close at different times. The portfolio's by default.
        lookback: Use only the last ``lookback`` periods of history.
    """

    objective: Objective = Objective.MIN_VARIANCE
    expected_returns: ReturnModel | Mapping[str, float] = ReturnModel.HISTORICAL
    views: tuple[View, ...] = ()
    covariance: CovarianceEstimator = CovarianceEstimator.LEDOIT_WOLF
    risk_free_rate: float = 0.0
    min_weight: PerAsset = 0.0
    max_weight: PerAsset = 1.0
    target_return: float | None = None
    risk_budgets: Mapping[str, float] | None = None
    risk_aversion: float = 2.5
    tau: float = 0.05
    frequency: Frequency | None = None
    lookback: int | None = None

    def __post_init__(self) -> None:  # noqa: PLR0912 - one check per parameter
        problems: list[str] = []
        try:
            objective = Objective(self.objective)
            object.__setattr__(self, "objective", objective)
            object.__setattr__(self, "covariance", CovarianceEstimator(self.covariance))
            if self.frequency is not None:
                object.__setattr__(self, "frequency", Frequency(self.frequency))
            if isinstance(self.expected_returns, str):
                object.__setattr__(self, "expected_returns", ReturnModel(self.expected_returns))
        except ValueError as error:
            raise DomainError(f"Invalid optimisation configuration: {error}") from error
        if not isinstance(self.expected_returns, ReturnModel):
            object.__setattr__(self, "expected_returns", _frozen(self.expected_returns))
        object.__setattr__(self, "views", tuple(self.views))
        for name in ("min_weight", "max_weight"):
            value = getattr(self, name)
            if not isinstance(value, int | float):
                object.__setattr__(self, name, _frozen(value))
        if self.risk_budgets is not None:
            object.__setattr__(self, "risk_budgets", _frozen(self.risk_budgets))
        if objective is Objective.TARGET_RETURN and self.target_return is None:
            problems.append("the target_return objective needs target_return")
        if self.target_return is not None and objective is not Objective.TARGET_RETURN:
            problems.append("target_return only applies to the target_return objective")
        if self.risk_budgets is not None and objective is not Objective.RISK_PARITY:
            problems.append("risk_budgets only apply to the risk_parity objective")
        if not objective.accepts_bounds and (self.min_weight != 0.0 or self.max_weight != 1.0):
            problems.append(f"weight bounds do not apply to the {objective.value} objective")
        if not math.isfinite(self.risk_free_rate):
            problems.append("risk_free_rate must be finite")
        if not self.risk_aversion > 0:
            problems.append("risk_aversion must be positive")
        if not self.tau > 0:
            problems.append("tau must be positive")
        if self.lookback is not None and self.lookback < 3:  # noqa: PLR2004
            problems.append("lookback must be at least 3 periods")
        if problems:
            raise DomainError("Invalid optimisation configuration: " + "; ".join(problems))


def _frozen(values: Mapping[str, float]) -> Mapping[str, float]:
    return MappingProxyType({str(key): float(value) for key, value in dict(values).items()})


# ──────────────────────────────────────────────────────────────────────
# Estimation and solution
# ──────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class OptimizationInputs:
    """What an optimisation needs from the history (built by :class:`Portfolio`).

    Attributes:
        returns: Simple returns per period, one column per holding (NaN = not observed).
        weights: Current target weights by symbol.
        periods_per_year: Annualisation factor of the returns' frequency.
    """

    returns: pd.DataFrame
    weights: pd.Series
    periods_per_year: float


@dataclass(frozen=True, slots=True, eq=False)
class Estimates:
    """Annual inputs of an optimisation, for transparency.

    Attributes:
        expected_returns: Annual expected returns by symbol (after any views).
        covariance: Annual covariance of returns (after any views).
        observations: Periods of history used.
        shrinkage: Ledoit-Wolf intensity, when that estimator was used.
    """

    expected_returns: pd.Series
    covariance: pd.DataFrame
    observations: int
    shrinkage: float | None = None

    @property
    def symbols(self) -> tuple[str, ...]:
        """Holdings, in order."""
        return tuple(str(symbol) for symbol in self.expected_returns.index)

    @property
    def volatilities(self) -> pd.Series:
        """Annual volatility of each holding."""
        return pd.Series(
            np.sqrt(np.clip(np.diag(self.covariance.to_numpy()), 0.0, None)),
            index=self.expected_returns.index,
            name="volatility",
        )


def _per_asset(value: PerAsset, symbols: Sequence[str], name: str) -> np.ndarray:
    if isinstance(value, int | float):
        return np.full(len(symbols), float(value))
    unknown = sorted(set(value) - set(symbols))
    if unknown:
        raise DomainError(f"{name} refers to symbols outside the portfolio: {unknown}")
    default = 0.0 if name == "min_weight" else 1.0
    return np.array([float(value.get(symbol, default)) for symbol in symbols])


def _views(
    views: Sequence[View], symbols: Sequence[str]
) -> tuple[np.ndarray, np.ndarray, list[float | None]]:
    position = {symbol: index for index, symbol in enumerate(symbols)}
    picks = np.zeros((len(views), len(symbols)))
    for row, view in enumerate(views):
        unknown = sorted(set(view.weights) - set(position))
        if unknown:
            raise DomainError(f"A view refers to symbols outside the portfolio: {unknown}")
        for symbol, weight in view.weights.items():
            picks[row, position[symbol]] = weight
    returns = np.array([view.expected_return for view in views])
    return picks, returns, [view.uncertainty for view in views]


def estimate(inputs: OptimizationInputs, config: OptimizationConfig) -> Estimates:
    """Annual expected returns and covariance from the history and the configuration.

    Raises:
        DomainError: If the history is too short or the inputs are inconsistent.
    """
    returns = inputs.returns
    if config.lookback is not None:
        returns = returns.iloc[-config.lookback :]
    symbols = [str(column) for column in returns.columns]
    shrinkage: float | None = None
    if config.covariance is CovarianceEstimator.LEDOIT_WOLF:
        complete = returns.dropna(how="any")
        if len(complete) < 3:  # noqa: PLR2004
            raise DomainError("Ledoit-Wolf needs at least 3 periods in which every holding trades")
        matrix, shrinkage = ledoit_wolf(complete.to_numpy())
    else:
        matrix = covariance_matrix(returns).to_numpy()
        if not np.isfinite(matrix).all():
            raise DomainError("Some holdings never trade on the same dates: no covariance")
    covariance = matrix * inputs.periods_per_year
    weights = inputs.weights.reindex(symbols).to_numpy(dtype="float64")
    model = config.expected_returns
    if model is ReturnModel.HISTORICAL:
        mean = returns.mean().to_numpy(dtype="float64") * inputs.periods_per_year
    elif model is ReturnModel.EQUILIBRIUM:
        mean = config.risk_free_rate + implied_returns(covariance, weights, config.risk_aversion)
    else:
        missing = [symbol for symbol in symbols if symbol not in model]
        if missing:
            raise DomainError(f"expected_returns has no value for {missing}")
        mean = np.array([model[symbol] for symbol in symbols])
    if not np.isfinite(mean).all():
        raise DomainError("Some holdings have no return in the period: no expected return")
    if config.views:
        picks, view_returns, uncertainties = _views(config.views, symbols)
        default = np.diag(picks @ (config.tau * covariance) @ picks.T)
        omega = np.diag([default[i] if u is None else u for i, u in enumerate(uncertainties)])
        try:
            mean, covariance = black_litterman(
                mean, covariance, picks, view_returns, tau=config.tau, uncertainty=omega
            )
        except OptimizationError as error:
            raise DomainError(str(error)) from error
    return Estimates(
        expected_returns=pd.Series(mean, index=symbols, name="expected_return"),
        covariance=pd.DataFrame(covariance, index=symbols, columns=symbols),
        observations=len(returns),
        shrinkage=shrinkage,
    )


def solve(estimates: Estimates, config: OptimizationConfig) -> np.ndarray:
    """Optimal weights for the estimates, in the order of ``estimates.symbols``.

    Raises:
        DomainError: If the problem is infeasible (bounds, target) or ill-posed.
    """
    symbols = estimates.symbols
    mean = estimates.expected_returns.to_numpy(dtype="float64")
    covariance = estimates.covariance.to_numpy(dtype="float64")
    lower = _per_asset(config.min_weight, symbols, "min_weight")
    upper = _per_asset(config.max_weight, symbols, "max_weight")
    try:
        match config.objective:
            case Objective.MIN_VARIANCE:
                weights = min_variance_weights(covariance, lower=lower, upper=upper)
            case Objective.MAX_SHARPE:
                weights = max_sharpe_weights(
                    mean, covariance, risk_free=config.risk_free_rate, lower=lower, upper=upper
                )
            case Objective.TARGET_RETURN:
                assert config.target_return is not None  # noqa: S101 - validated by the config
                weights = target_return_weights(
                    mean, covariance, config.target_return, lower=lower, upper=upper
                )
            case Objective.RISK_PARITY:
                budgets = (
                    None
                    if config.risk_budgets is None
                    else _risk_budgets(config.risk_budgets, symbols)
                )
                weights = risk_budget_weights(covariance, budgets)
            case Objective.HIERARCHICAL_RISK_PARITY:
                weights = hierarchical_risk_parity_weights(covariance)
            case Objective.INVERSE_VOLATILITY:
                weights = inverse_volatility_weights(covariance)
            case Objective.EQUAL_WEIGHT:
                weights = np.full(len(symbols), 1.0 / len(symbols))
    except OptimizationError as error:
        raise DomainError(f"Optimisation failed: {error}") from error
    weights = np.where(np.abs(weights) < 1e-12, 0.0, weights)  # noqa: PLR2004 - solver noise
    return np.asarray(weights / weights.sum(), dtype="float64")


def frontier_points(estimates: Estimates, config: OptimizationConfig, points: int) -> pd.DataFrame:
    """Expected return, volatility, Sharpe ratio and weights along the efficient frontier.

    Raises:
        DomainError: If the weight bounds are infeasible.
    """
    symbols = estimates.symbols
    try:
        returns, volatilities, weights = efficient_frontier(
            estimates.expected_returns.to_numpy(dtype="float64"),
            estimates.covariance.to_numpy(dtype="float64"),
            points=points,
            lower=_per_asset(config.min_weight, symbols, "min_weight"),
            upper=_per_asset(config.max_weight, symbols, "max_weight"),
        )
    except OptimizationError as error:
        raise DomainError(f"Efficient frontier failed: {error}") from error
    with np.errstate(divide="ignore", invalid="ignore"):
        sharpe = np.where(
            volatilities > 0, (returns - config.risk_free_rate) / volatilities, np.nan
        )
    table = pd.DataFrame(weights, columns=list(symbols))
    table.insert(0, "sharpe_ratio", sharpe)
    table.insert(0, "volatility", volatilities)
    table.insert(0, "expected_return", returns)
    return table


def _risk_budgets(budgets: Mapping[str, float], symbols: Sequence[str]) -> np.ndarray:
    unknown = sorted(set(budgets) - set(symbols))
    missing = [symbol for symbol in symbols if symbol not in budgets]
    if unknown or missing:
        raise DomainError(f"risk_budgets: missing {missing}, unknown {unknown}")
    return np.array([budgets[symbol] for symbol in symbols])


# ──────────────────────────────────────────────────────────────────────
# Results
# ──────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True, eq=False)
class OptimizationResult:
    """An optimised portfolio and its ex-ante figures.

    Attributes:
        config: Parameters used.
        portfolio: The same holdings with the optimised weights (same currency and
            rebalancing policy).
        estimates: Annual expected returns and covariance behind the weights.
        previous_weights: Weights before the optimisation.
    """

    config: OptimizationConfig
    portfolio: Portfolio
    estimates: Estimates
    previous_weights: pd.Series = field(repr=False)

    @property
    def weights(self) -> pd.Series:
        """Optimised weights by symbol."""
        return self.portfolio.weights

    def _vector(self) -> np.ndarray:
        return self.weights.reindex(list(self.estimates.symbols)).to_numpy(dtype="float64")

    @property
    def expected_return(self) -> float:
        """Annual expected return of the optimised portfolio (ex ante)."""
        return float(self._vector() @ self.estimates.expected_returns.to_numpy())

    @property
    def volatility(self) -> float:
        """Annual volatility of the optimised portfolio (ex ante)."""
        weights = self._vector()
        variance = float(weights @ self.estimates.covariance.to_numpy() @ weights)
        return math.sqrt(max(variance, 0.0))

    @property
    def sharpe_ratio(self) -> float:
        """Ex-ante Sharpe ratio, net of the configured risk-free rate."""
        if self.volatility == 0:
            return math.nan
        return (self.expected_return - self.config.risk_free_rate) / self.volatility

    @property
    def risk_contributions(self) -> pd.DataFrame:
        """Euler decomposition of the ex-ante volatility (``share`` sums to 1)."""
        table = risk_contributions(self._vector(), self.estimates.covariance.to_numpy())
        table.index = pd.Index(self.estimates.symbols, name="symbol")
        return table

    @property
    def effective_number_of_assets(self) -> float:
        """How many equally weighted holdings the optimised weights are equivalent to."""
        return effective_number_of_assets(self._vector())

    def summary(self) -> pd.DataFrame:
        """Per-holding table: weights before and after, expected return, volatility, risk."""
        symbols = list(self.estimates.symbols)
        return pd.DataFrame(
            {
                "previous_weight": self.previous_weights.reindex(symbols),
                "weight": self.weights.reindex(symbols),
                "expected_return": self.estimates.expected_returns,
                "volatility": self.estimates.volatilities,
                "risk_share": self.risk_contributions["share"],
            },
            index=pd.Index(symbols, name="symbol"),
        )


@dataclass(frozen=True, slots=True, eq=False)
class EfficientFrontier:
    """Minimum-variance portfolios from the global minimum to the highest expected return.

    Attributes:
        config: Parameters used (bounds, estimators).
        estimates: Annual expected returns and covariance.
        points: One row per frontier portfolio: ``expected_return``, ``volatility``,
            ``sharpe_ratio`` and one weight column per symbol.
        minimum_variance: The global minimum-variance portfolio.
        maximum_sharpe: The tangency portfolio, or ``None`` when no portfolio beats the
            risk-free rate.
    """

    config: OptimizationConfig
    estimates: Estimates
    points: pd.DataFrame = field(repr=False)
    minimum_variance: OptimizationResult = field(repr=False)
    maximum_sharpe: OptimizationResult | None = field(repr=False)

    @property
    def assets(self) -> pd.DataFrame:
        """Expected return and volatility of each holding alone."""
        return pd.DataFrame(
            {
                "expected_return": self.estimates.expected_returns,
                "volatility": self.estimates.volatilities,
            }
        )

    def plot(self, **options: Any) -> Figure:  # noqa: ANN401
        """Chart of the frontier, the holdings, both optimal portfolios and the capital line.

        Requires the ``plots`` extra (matplotlib). See
        :func:`investinglab.reporting.optimization.frontier_figure` for the options
        (``title`` and ``language``).
        """
        # Lazy, documented exception to the layering (ADR-0017, ADR-0023).
        from investinglab.reporting.entrypoints import frontier_plot  # noqa: PLC0415

        return frontier_plot(self, **options)
