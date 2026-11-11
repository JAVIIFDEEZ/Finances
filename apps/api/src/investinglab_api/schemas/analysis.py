"""Forward-looking analysis: Monte Carlo, optimisation and savings plans."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import Field

from investinglab.domain.optimization import Objective, OptimizationConfig, ReturnModel
from investinglab.domain.planning import SavingsPlan
from investinglab.domain.simulation import (
    CovarianceEstimator,
    DriftAssumption,
    SimulationConfig,
    SimulationModel,
    VolatilityAssumption,
)
from investinglab.domain.time import Frequency
from investinglab_api.schemas.common import ApiModel, FiniteFloat, RequestModel
from investinglab_api.schemas.portfolio import PortfolioIn, RiskContributionOut

__all__ = [
    "AssetPointOut",
    "CalibrationOut",
    "EstimateOut",
    "FanPointOut",
    "FrontierPointOut",
    "HistogramBinOut",
    "OptimizationIn",
    "OptimizationOut",
    "OptimizedOut",
    "PlanFanPointOut",
    "PlanIn",
    "PlanOut",
    "SimulationIn",
    "SimulationOut",
    "WeightOut",
]

PerAsset = FiniteFloat | dict[str, FiniteFloat]


class SimulationIn(RequestModel):
    """A Monte Carlo simulation of a portfolio (one holding with weight 1 for an asset)."""

    portfolio: PortfolioIn
    model: SimulationModel = SimulationModel.GBM
    n_paths: int = Field(default=5_000, ge=100, description="Simulated paths.")
    horizon: int = Field(default=252, ge=1, description="Periods ahead (sessions for 1d).")
    drift: DriftAssumption = DriftAssumption.HISTORICAL
    expected_returns: PerAsset | None = Field(
        default=None, description="Annual expected returns for drift=assumed."
    )
    risk_free_rate: FiniteFloat = Field(default=0.0, description="Annual rate for drift=risk_free.")
    volatility: VolatilityAssumption = VolatilityAssumption.HISTORICAL
    volatilities: PerAsset | None = Field(
        default=None, description="Annual volatilities for volatility=assumed."
    )
    covariance: CovarianceEstimator = CovarianceEstimator.SAMPLE
    degrees_of_freedom: FiniteFloat = Field(default=5.0, gt=2)
    block_length: FiniteFloat = Field(default=10.0, ge=1)
    antithetic: bool = False
    seed: int | None = 42
    initial_value: FiniteFloat = Field(default=10_000.0, gt=0)
    confidence_levels: list[FiniteFloat] = Field(default=[0.95, 0.99], min_length=1)

    def to_config(self) -> SimulationConfig:
        """The domain configuration (validated again by the domain)."""
        return SimulationConfig(
            n_paths=self.n_paths,
            horizon=self.horizon,
            model=self.model,
            drift=self.drift,
            expected_returns=self.expected_returns,
            risk_free_rate=self.risk_free_rate,
            volatility=self.volatility,
            volatilities=self.volatilities,
            covariance=self.covariance,
            degrees_of_freedom=self.degrees_of_freedom,
            block_length=self.block_length,
            antithetic=self.antithetic,
            seed=self.seed,
            initial_value=self.initial_value,
            confidence_levels=tuple(self.confidence_levels),
        )


class FanPointOut(ApiModel):
    """Value percentiles at one period of the simulation."""

    period: int
    p1: float
    p5: float
    p25: float
    p50: float
    p75: float
    p95: float
    p99: float


class HistogramBinOut(ApiModel):
    """Terminal values falling in ``[lower, upper)``."""

    lower: float
    upper: float
    count: int


class EstimateOut(ApiModel):
    """A Monte Carlo estimate with its 95 % confidence interval."""

    level: float
    value: float | None
    lower: float | None
    upper: float | None
    standard_error: float | None


class CalibrationOut(ApiModel):
    """Parameters the simulation actually used (annualised)."""

    symbols: list[str]
    weights: list[float]
    annual_expected_return: list[float | None]
    annual_volatility: list[float | None]
    observations: int
    periods_per_year: float
    shrinkage: float | None


class SimulationOut(ApiModel):
    """Fan chart, terminal distribution and tail risk of the simulated value."""

    model: SimulationModel
    n_paths: int
    horizon: int
    periods_per_year: float
    initial_value: float
    start: date | datetime = Field(description="Last historical date: period 0.")
    fan: list[FanPointOut]
    terminal_histogram: list[HistogramBinOut]
    expected_terminal_value: float | None
    median_terminal_value: float | None
    probability_of_loss: float | None
    value_at_risk: list[EstimateOut] = Field(description="Loss fractions over the horizon.")
    conditional_value_at_risk: list[EstimateOut]
    drawdown_at_risk: list[EstimateOut] = Field(description="Max drawdown quantiles (no CI).")
    calibration: CalibrationOut


class OptimizationIn(RequestModel):
    """Weights that best meet an objective, estimated from the holdings' history."""

    portfolio: PortfolioIn = Field(description="Holdings; their weights are the starting point.")
    objective: Objective = Objective.MAX_SHARPE
    expected_returns: ReturnModel = ReturnModel.HISTORICAL
    covariance: CovarianceEstimator = CovarianceEstimator.LEDOIT_WOLF
    risk_free_rate: FiniteFloat = Field(default=0.0, description="Effective annual rate.")
    min_weight: FiniteFloat = Field(default=0.0, description="Lowest weight of every holding.")
    max_weight: FiniteFloat = Field(default=1.0, description="Highest weight of every holding.")
    target_return: FiniteFloat | None = Field(
        default=None, description="Annual return for objective=target_return."
    )
    estimation_frequency: Frequency | None = Field(
        default=Frequency.WEEK_1,
        description="Frequency of the returns behind the estimates (weekly by default).",
    )
    frontier_points: int = Field(default=30, ge=0, description="0 skips the frontier.")

    def to_config(self) -> OptimizationConfig:
        """The domain configuration (validated again by the domain)."""
        return OptimizationConfig(
            objective=self.objective,
            expected_returns=self.expected_returns,
            covariance=self.covariance,
            risk_free_rate=self.risk_free_rate,
            min_weight=self.min_weight,
            max_weight=self.max_weight,
            target_return=self.target_return,
            frequency=self.estimation_frequency,
        )


class WeightOut(ApiModel):
    """Optimised weight of a holding and the one it replaces."""

    symbol: str
    weight: float
    previous_weight: float


class OptimizedOut(ApiModel):
    """An optimised portfolio, ex ante."""

    weights: list[WeightOut]
    expected_return: float | None
    volatility: float | None
    sharpe_ratio: float | None
    effective_number_of_assets: float | None
    risk_contributions: list[RiskContributionOut]


class FrontierPointOut(ApiModel):
    """A point of the minimum-variance frontier."""

    expected_return: float
    volatility: float
    sharpe_ratio: float | None
    weights: dict[str, float]


class AssetPointOut(ApiModel):
    """A holding alone, on the same axes as the frontier."""

    symbol: str
    expected_return: float | None
    volatility: float | None


class OptimizationOut(ApiModel):
    """The optimal weights and, when asked, the efficient frontier around them."""

    objective: Objective
    observations: int = Field(description="Periods of history behind the estimates.")
    shrinkage: float | None
    result: OptimizedOut
    frontier: list[FrontierPointOut]
    assets: list[AssetPointOut]
    minimum_variance: OptimizedOut | None
    maximum_sharpe: OptimizedOut | None


class PlanIn(RequestModel):
    """A savings (or withdrawal) plan invested in a portfolio."""

    portfolio: PortfolioIn
    years: FiniteFloat = Field(default=20, gt=0, le=100)
    initial: FiniteFloat = Field(default=10_000, ge=0, description="Money invested today.")
    contribution: FiniteFloat = Field(
        default=300, description="Monthly contribution (negative = withdrawal)."
    )
    contribution_growth: FiniteFloat = Field(
        default=0.0, description="Annual growth of the contribution."
    )
    inflation: FiniteFloat = Field(default=0.02, description="Annual inflation.")
    goal: FiniteFloat | None = Field(default=None, gt=0, description="Target in today's money.")
    expected_return: FiniteFloat | None = Field(
        default=None,
        gt=-1,
        description=(
            "Annual nominal return to assume for the portfolio; null uses its historical "
            "drift, which over decades rarely persists."
        ),
    )
    n_paths: int = Field(default=5_000, ge=100)
    seed: int | None = 42
    success_probability: FiniteFloat = Field(
        default=0.9, gt=0, lt=1, description="Probability for the required contribution."
    )

    def to_plan(self) -> SavingsPlan:
        """The domain plan (validated again by the domain)."""
        return SavingsPlan(
            years=self.years,
            initial=self.initial,
            contribution=self.contribution,
            contribution_growth=self.contribution_growth,
            inflation=self.inflation,
            goal=self.goal,
        )

    def to_config(self) -> SimulationConfig:
        """Monte Carlo settings of the plan: historical volatility, assumed or historical drift."""
        if self.expected_return is None:
            return SimulationConfig(n_paths=self.n_paths, seed=self.seed)
        return SimulationConfig(
            n_paths=self.n_paths,
            seed=self.seed,
            drift=DriftAssumption.ASSUMED,
            expected_returns=self.expected_return,
        )


class PlanFanPointOut(ApiModel):
    """Wealth percentiles at one month, in today's money."""

    month: int
    p5: float
    p25: float
    p50: float
    p75: float
    p95: float
    contributed: float = Field(description="Money put in so far.")


class PlanOut(ApiModel):
    """Odds of a savings plan, in today's money."""

    months: int
    currency: str
    goal: float | None
    fan: list[PlanFanPointOut]
    median_terminal_wealth: float | None
    probability_of_success: float | None
    expected_shortfall: float | None
    probability_of_ruin: float | None
    required_contribution: float | None = Field(
        description="Monthly contribution that reaches the goal with success_probability."
    )
    success_probability: float
