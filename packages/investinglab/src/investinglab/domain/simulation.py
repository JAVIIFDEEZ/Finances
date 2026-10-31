"""Monte Carlo simulation of assets and portfolios (ADR-0016).

The simulation is parametrisable (paths, horizon, return and volatility assumptions, model,
seed), reproducible, vectorised and memory-bounded. The same rebalancing policy used for the
historical analysis is applied inside every simulated path.

Calibration works on **log returns per period** of the series' frequency:

* *drift*: historical mean, zero expected growth, the risk-free rate, or assumed annual
  expected returns per asset;
* *volatility*: historical, or assumed annual volatilities (correlations stay historical);
* *covariance*: sample (pairwise-complete, PSD-repaired) or Ledoit-Wolf shrinkage.

Models: Gaussian shocks (multivariate GBM via Cholesky), multivariate Student-t (fat tails)
or a stationary block bootstrap of historical periods.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Final

import numpy as np
import pandas as pd

from investinglab.analytics import covariance_matrix, ledoit_wolf, log_returns
from investinglab.analytics.montecarlo import (
    normal_log_returns,
    path_max_drawdowns,
    rebalanced_values,
    stationary_bootstrap_indices,
    student_t_log_returns,
)
from investinglab.domain.errors import DomainError

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from matplotlib.figure import Figure

__all__ = [
    "MAX_SIMULATED_POINTS",
    "CovarianceEstimator",
    "DriftAssumption",
    "RiskEstimate",
    "SimulationConfig",
    "SimulationModel",
    "SimulationResult",
    "VolatilityAssumption",
    "simulate",
]

MAX_SIMULATED_POINTS: Final = 20_000_000
"""Upper bound of ``n_paths * horizon`` (≈160 MB of float64 value paths)."""

_Z_95: Final = 1.959963984540054


class SimulationModel(StrEnum):
    """Distribution of the simulated shocks."""

    GBM = "gbm"
    """Correlated Gaussian log returns (multivariate geometric Brownian motion)."""
    STUDENT_T = "student_t"
    """Multivariate Student-t log returns: same covariance, fatter joint tails."""
    BOOTSTRAP = "bootstrap"
    """Stationary block bootstrap of historical periods (no distributional assumption)."""


class DriftAssumption(StrEnum):
    """Expected return used to simulate."""

    HISTORICAL = "historical"
    """Sample mean of historical log returns (noisy: use with care)."""
    ZERO = "zero"
    """No expected growth: prices are martingales."""
    RISK_FREE = "risk_free"
    """Every asset grows at the risk-free rate (risk-neutral-like)."""
    ASSUMED = "assumed"
    """Annual expected returns given in ``expected_returns``."""


class VolatilityAssumption(StrEnum):
    """Volatility used to simulate."""

    HISTORICAL = "historical"
    ASSUMED = "assumed"
    """Annual volatilities given in ``volatilities``; correlations stay historical."""


class CovarianceEstimator(StrEnum):
    """Estimator of the historical covariance."""

    SAMPLE = "sample"
    """Pairwise-complete sample covariance, repaired to PSD when needed."""
    LEDOIT_WOLF = "ledoit_wolf"
    """Ledoit-Wolf shrinkage on periods where every asset is observed."""


type PerAsset = float | Mapping[str, float]


@dataclass(frozen=True, slots=True)
class SimulationConfig:
    """Parameters of a Monte Carlo simulation.

    Attributes:
        n_paths: Number of simulated paths.
        horizon: Number of periods simulated (in the series' frequency: 252 ≈ 1 year
            of daily equity data).
        model: Shock distribution.
        drift: Expected-return assumption.
        expected_returns: Annual expected returns (decimal) when ``drift`` is ``ASSUMED``:
            one value for every asset or a mapping by symbol.
        risk_free_rate: Annual risk-free rate (decimal) when ``drift`` is ``RISK_FREE``.
        volatility: Volatility assumption.
        volatilities: Annual volatilities when ``volatility`` is ``ASSUMED``.
        covariance: Historical covariance estimator.
        degrees_of_freedom: Tail parameter of the Student-t model (> 2).
        block_length: Mean block length of the bootstrap, in periods.
        lookback: Use only the last ``lookback`` historical periods for calibration.
        antithetic: Use antithetic variates (parametric models only).
        seed: Random seed; the same seed and configuration give the same result.
        initial_value: Value at the start of every path.
        confidence_levels: Levels for VaR and CVaR.
        chunk_size: Paths simulated at once (bounds the memory used).
    """

    n_paths: int = 10_000
    horizon: int = 252
    model: SimulationModel = SimulationModel.GBM
    drift: DriftAssumption = DriftAssumption.HISTORICAL
    expected_returns: PerAsset | None = None
    risk_free_rate: float = 0.0
    volatility: VolatilityAssumption = VolatilityAssumption.HISTORICAL
    volatilities: PerAsset | None = None
    covariance: CovarianceEstimator = CovarianceEstimator.SAMPLE
    degrees_of_freedom: float = 5.0
    block_length: float = 10.0
    lookback: int | None = None
    antithetic: bool = False
    seed: int | None = 42
    initial_value: float = 10_000.0
    confidence_levels: tuple[float, ...] = (0.95, 0.99)
    chunk_size: int = 2_000

    def __post_init__(self) -> None:  # noqa: PLR0912 - one check per parameter
        problems: list[str] = []
        if not 100 <= self.n_paths <= 1_000_000:  # noqa: PLR2004
            problems.append("n_paths must be between 100 and 1,000,000")
        if self.horizon < 1:
            problems.append("horizon must be at least one period")
        if self.n_paths * self.horizon > MAX_SIMULATED_POINTS:
            problems.append(
                f"n_paths x horizon must not exceed {MAX_SIMULATED_POINTS:,} (memory bound)"
            )
        if self.drift is DriftAssumption.ASSUMED and self.expected_returns is None:
            problems.append("drift=assumed needs expected_returns")
        if self.volatility is VolatilityAssumption.ASSUMED and self.volatilities is None:
            problems.append("volatility=assumed needs volatilities")
        if self.degrees_of_freedom <= 2:  # noqa: PLR2004
            problems.append("degrees_of_freedom must be greater than 2")
        if self.block_length < 1:
            problems.append("block_length must be at least 1")
        if self.lookback is not None and self.lookback < 2:  # noqa: PLR2004
            problems.append("lookback must be at least 2 periods")
        if self.antithetic and self.model is SimulationModel.BOOTSTRAP:
            problems.append("antithetic variates only apply to parametric models")
        if not self.initial_value > 0:
            problems.append("initial_value must be positive")
        if not self.confidence_levels or not all(0 < c < 1 for c in self.confidence_levels):
            problems.append("confidence_levels must be in (0, 1)")
        if self.chunk_size < 100:  # noqa: PLR2004
            problems.append("chunk_size must be at least 100")
        if problems:
            raise DomainError("Invalid simulation configuration: " + "; ".join(problems))


@dataclass(frozen=True, slots=True)
class RiskEstimate:
    """A Monte Carlo estimate with its sampling uncertainty.

    Attributes:
        value: Point estimate (a positive loss fraction for VaR/CVaR).
        lower: Lower bound of the 95 % confidence interval.
        upper: Upper bound of the 95 % confidence interval.
        standard_error: Approximate standard error of the estimate.
    """

    value: float
    lower: float
    upper: float
    standard_error: float


@dataclass(frozen=True, slots=True)
class Calibration:
    """Per-period parameters actually used by a simulation (for transparency).

    Attributes:
        symbols: Assets, in order.
        weights: Target weights.
        mean_log_return: Per-period mean log return of each asset.
        covariance: Per-period covariance of log returns.
        periods_per_year: Annualisation factor.
        observations: Historical periods used for calibration.
        shrinkage: Ledoit-Wolf intensity, when that estimator was used.
    """

    symbols: tuple[str, ...]
    weights: np.ndarray
    mean_log_return: np.ndarray
    covariance: np.ndarray
    periods_per_year: float
    observations: int
    shrinkage: float | None = None

    @property
    def annual_volatility(self) -> pd.Series:
        """Annualised volatility of log returns of each asset."""
        return pd.Series(
            np.sqrt(np.diag(self.covariance) * self.periods_per_year), index=list(self.symbols)
        )

    @property
    def annual_expected_return(self) -> pd.Series:
        """Annual expected simple return implied by the calibrated log-return mean."""
        per_period = self.mean_log_return + np.diag(self.covariance) / 2
        return pd.Series(np.expm1(per_period * self.periods_per_year), index=list(self.symbols))

    @property
    def correlation(self) -> pd.DataFrame:
        """Correlation matrix of the simulated shocks."""
        std = np.sqrt(np.diag(self.covariance))
        with np.errstate(divide="ignore", invalid="ignore"):
            values = self.covariance / np.outer(std, std)
        np.fill_diagonal(values, 1.0)
        return pd.DataFrame(values, index=list(self.symbols), columns=list(self.symbols))


@dataclass(frozen=True, slots=True, eq=False)
class SimulationResult:
    """Simulated value paths and their statistics.

    The full ``(n_paths, horizon + 1)`` value matrix is kept privately; accessors return
    copies or summaries.
    """

    config: SimulationConfig
    calibration: Calibration
    start: pd.Timestamp
    _values: np.ndarray = field(repr=False)
    _max_drawdowns: np.ndarray = field(repr=False)

    # ── Paths ────────────────────────────────────────────────────────

    @property
    def n_paths(self) -> int:
        """Number of simulated paths."""
        return int(self._values.shape[0])

    @property
    def horizon(self) -> int:
        """Number of simulated periods."""
        return int(self._values.shape[1] - 1)

    def values(self) -> np.ndarray:
        """All value paths, shape ``(n_paths, horizon + 1)`` (a copy)."""
        return self._values.copy()

    def percentile_paths(
        self, percentiles: Sequence[float] = (1, 5, 25, 50, 75, 95, 99)
    ) -> pd.DataFrame:
        """Value percentiles at every step (the fan chart), indexed by period 0..horizon."""
        bands = np.percentile(self._values, list(percentiles), axis=0)
        return pd.DataFrame(
            bands.T,
            index=pd.RangeIndex(self.horizon + 1, name="period"),
            columns=[f"p{p:g}" for p in percentiles],
        )

    def sample_paths(self, count: int = 50) -> pd.DataFrame:
        """A reproducible subset of paths for plotting (one column per path)."""
        chosen = np.linspace(0, self.n_paths - 1, num=min(count, self.n_paths), dtype=int)
        return pd.DataFrame(
            self._values[chosen].T, index=pd.RangeIndex(self.horizon + 1, name="period")
        )

    # ── Terminal distribution ────────────────────────────────────────

    @property
    def terminal_values(self) -> np.ndarray:
        """Value of every path at the horizon (a copy)."""
        return self._values[:, -1].copy()

    @property
    def terminal_returns(self) -> np.ndarray:
        """Total return of every path over the horizon."""
        return self._values[:, -1] / self.config.initial_value - 1.0

    @property
    def expected_terminal_value(self) -> float:
        """Mean value at the horizon."""
        return float(self._values[:, -1].mean())

    @property
    def median_terminal_value(self) -> float:
        """Median value at the horizon."""
        return float(np.median(self._values[:, -1]))

    @property
    def probability_of_loss(self) -> float:
        """Share of paths ending below the initial value."""
        return float((self._values[:, -1] < self.config.initial_value).mean())

    def value_at_risk(self, level: float = 0.95) -> RiskEstimate:
        """Horizon VaR as a positive loss fraction, with a distribution-free 95 % CI.

        The interval comes from the order statistics of the simulated returns (binomial
        approximation), so it does not assume any return distribution.
        """
        _check_level(level)
        returns = np.sort(self.terminal_returns)
        n = returns.size
        tail = 1.0 - level
        point = float(-np.quantile(returns, tail))
        spread = _Z_95 * math.sqrt(n * tail * (1.0 - tail))
        low_rank = int(np.clip(math.floor(n * tail - spread), 0, n - 1))
        high_rank = int(np.clip(math.ceil(n * tail + spread), 0, n - 1))
        lower, upper = float(-returns[high_rank]), float(-returns[low_rank])
        return RiskEstimate(point, lower, upper, (upper - lower) / (2 * _Z_95))

    def conditional_value_at_risk(self, level: float = 0.95) -> RiskEstimate:
        """Horizon Expected Shortfall as a positive loss fraction, with a normal 95 % CI."""
        _check_level(level)
        returns = self.terminal_returns
        threshold = np.quantile(returns, 1.0 - level)
        tail = returns[returns <= threshold]
        point = float(-tail.mean())
        error = float(tail.std(ddof=1) / math.sqrt(tail.size)) if tail.size > 1 else 0.0
        return RiskEstimate(point, point - _Z_95 * error, point + _Z_95 * error, error)

    def expected_value_estimate(self) -> RiskEstimate:
        """Mean terminal value with its Monte Carlo standard error."""
        terminal = self._values[:, -1]
        mean = float(terminal.mean())
        error = float(terminal.std(ddof=1) / math.sqrt(terminal.size))
        return RiskEstimate(mean, mean - _Z_95 * error, mean + _Z_95 * error, error)

    # ── Drawdowns ────────────────────────────────────────────────────

    @property
    def max_drawdowns(self) -> np.ndarray:
        """Worst drawdown of every path (non-positive, a copy)."""
        return self._max_drawdowns.copy()

    def drawdown_at_risk(self, level: float = 0.95) -> float:
        """Drawdown exceeded (in magnitude) by only ``1 - level`` of the paths."""
        _check_level(level)
        return float(np.quantile(self._max_drawdowns, 1.0 - level))

    # ── Summaries ────────────────────────────────────────────────────

    def summary(self) -> pd.DataFrame:
        """Key statistics in one table (metric → value)."""
        rows: dict[str, float] = {
            "initial_value": self.config.initial_value,
            "expected_terminal_value": self.expected_terminal_value,
            "median_terminal_value": self.median_terminal_value,
            "probability_of_loss": self.probability_of_loss,
            "expected_max_drawdown": float(self._max_drawdowns.mean()),
        }
        for level in self.config.confidence_levels:
            var = self.value_at_risk(level)
            cvar = self.conditional_value_at_risk(level)
            label = f"{level:.0%}"
            rows[f"var_{label}"] = var.value
            rows[f"var_{label}_ci_low"] = var.lower
            rows[f"var_{label}_ci_high"] = var.upper
            rows[f"cvar_{label}"] = cvar.value
            rows[f"drawdown_at_risk_{label}"] = self.drawdown_at_risk(level)
        return pd.DataFrame({"value": rows})

    def plot(self, **options: Any) -> Figure:  # noqa: ANN401
        """Fan chart of the paths and histogram of terminal values with VaR/CVaR.

        Requires the ``plots`` extra (matplotlib). See
        :func:`investinglab.reporting.simulation.simulation_figure` for the options.
        """
        # Lazy, documented exception to the layering (ADR-0016): plotting lives in reporting.
        from investinglab.reporting.simulation import simulation_figure  # noqa: PLC0415

        return simulation_figure(self, **options)


def _check_level(level: float) -> None:
    if not 0.0 < level < 1.0:
        raise DomainError(f"Confidence level must be in (0, 1), got {level}")


# ──────────────────────────────────────────────────────────────────────
# Calibration and execution
# ──────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class SimulationInputs:
    """What a simulation needs from the historical data (built by domain objects).

    Attributes:
        prices: Observed prices, one column per asset (NaN = not observed).
        weights: Target weights.
        periods_per_year: Annualisation factor of the prices' frequency.
        rebalance_every: Steps between scheduled rebalances (``None`` = never).
        band: Drift band triggering a rebalance (``None`` = none).
        start: Last historical timestamp (the simulation starts after it).
    """

    prices: pd.DataFrame
    weights: np.ndarray
    periods_per_year: float
    rebalance_every: int | None
    band: float | None
    start: pd.Timestamp


def _per_asset(value: PerAsset, symbols: Sequence[str], name: str) -> np.ndarray:
    if isinstance(value, int | float):
        return np.full(len(symbols), float(value))
    missing = [s for s in symbols if s not in value]
    if missing:
        raise DomainError(f"{name} missing for {missing}")
    return np.array([float(value[s]) for s in symbols])


def calibrate(
    inputs: SimulationInputs, config: SimulationConfig
) -> tuple[Calibration, pd.DataFrame]:
    """Estimate per-period log-return parameters and the complete-case history.

    Returns:
        The calibration and the historical log returns on periods where every asset was
        observed (used by the bootstrap and by Ledoit-Wolf).
    """
    symbols = tuple(str(c) for c in inputs.prices.columns)
    history = log_returns(inputs.prices)
    if config.lookback is not None:
        history = history.iloc[-config.lookback :]
    complete = history.dropna(how="any")
    if len(complete) < 2:  # noqa: PLR2004
        raise DomainError("At least two complete historical periods are needed to simulate")
    ppy = inputs.periods_per_year

    shrinkage: float | None = None
    if config.covariance is CovarianceEstimator.LEDOIT_WOLF:
        covariance, shrinkage = ledoit_wolf(complete.to_numpy())
    else:
        # Finite for every pair: the >= 2 complete periods above are common to all assets.
        covariance = covariance_matrix(history).to_numpy()

    if config.volatility is VolatilityAssumption.ASSUMED:
        assert config.volatilities is not None  # noqa: S101 - validated by the config
        target = _per_asset(config.volatilities, symbols, "volatilities") / math.sqrt(ppy)
        current = np.sqrt(np.diag(covariance))
        with np.errstate(divide="ignore", invalid="ignore"):
            scale = np.where(current > 0, target / current, 0.0)
        covariance = covariance * np.outer(scale, scale)
        if (current == 0).any():
            covariance[np.diag_indices_from(covariance)] = np.where(
                current > 0, np.diag(covariance), target**2
            )

    half_variance = np.diag(covariance) / 2
    if config.drift is DriftAssumption.HISTORICAL:
        mean = history.mean().to_numpy()
    elif config.drift is DriftAssumption.ZERO:
        mean = -half_variance
    else:
        annual = (
            np.full(len(symbols), config.risk_free_rate)
            if config.drift is DriftAssumption.RISK_FREE
            else _per_asset(config.expected_returns or 0.0, symbols, "expected_returns")
        )
        per_period = (1.0 + annual) ** (1.0 / ppy) - 1.0
        mean = np.log1p(per_period) - half_variance

    calibration = Calibration(
        symbols=symbols,
        weights=np.asarray(inputs.weights, dtype="float64"),
        mean_log_return=np.asarray(mean, dtype="float64"),
        covariance=np.asarray(covariance, dtype="float64"),
        periods_per_year=ppy,
        observations=len(history),
        shrinkage=shrinkage,
    )
    return calibration, complete


def _bootstrap_rows(complete: pd.DataFrame, calibration: Calibration) -> np.ndarray:
    """Historical rows recentred on the calibrated mean and rescaled to its volatility."""
    rows = complete.to_numpy(dtype="float64")
    historical_std = rows.std(axis=0, ddof=1)
    target_std = np.sqrt(np.diag(calibration.covariance))
    with np.errstate(divide="ignore", invalid="ignore"):
        scale = np.where(historical_std > 0, target_std / historical_std, 1.0)
    return np.asarray(
        (rows - rows.mean(axis=0)) * scale + calibration.mean_log_return, dtype="float64"
    )


def simulate(inputs: SimulationInputs, config: SimulationConfig) -> SimulationResult:
    """Run a Monte Carlo simulation of an asset or a portfolio.

    Paths are generated in chunks of ``config.chunk_size`` so memory stays bounded; the
    random stream depends only on the seed and the configuration.
    """
    calibration, complete = calibrate(inputs, config)
    rng = np.random.default_rng(config.seed)
    bootstrap_rows = (
        _bootstrap_rows(complete, calibration)
        if config.model is SimulationModel.BOOTSTRAP
        else None
    )
    values = np.empty((config.n_paths, config.horizon + 1))
    for start in range(0, config.n_paths, config.chunk_size):
        size = min(config.chunk_size, config.n_paths - start)
        if bootstrap_rows is not None:
            indices = stationary_bootstrap_indices(
                len(bootstrap_rows),
                horizon=config.horizon,
                n_paths=size,
                mean_block=config.block_length,
                rng=rng,
            )
            shocks = bootstrap_rows[indices]
        elif config.model is SimulationModel.STUDENT_T:
            shocks = student_t_log_returns(
                calibration.mean_log_return,
                calibration.covariance,
                degrees_of_freedom=config.degrees_of_freedom,
                horizon=config.horizon,
                n_paths=size,
                rng=rng,
                antithetic=config.antithetic,
            )
        else:
            shocks = normal_log_returns(
                calibration.mean_log_return,
                calibration.covariance,
                horizon=config.horizon,
                n_paths=size,
                rng=rng,
                antithetic=config.antithetic,
            )
        values[start : start + size] = rebalanced_values(
            np.expm1(shocks),
            calibration.weights,
            initial_value=config.initial_value,
            rebalance_every=inputs.rebalance_every,
            band=inputs.band,
        )
    return SimulationResult(
        config=config,
        calibration=calibration,
        start=inputs.start,
        _values=values,
        _max_drawdowns=path_max_drawdowns(values),
    )
