"""Portfolios: how a request describes one, and what its analytics return."""

from __future__ import annotations

from datetime import date, datetime
from typing import Self

from pydantic import Field, model_validator

from investinglab.domain.instruments import AssetClass
from investinglab.domain.portfolio import RebalanceKind, RebalancePolicy
from investinglab.domain.time import Frequency
from investinglab_api.schemas.common import (
    ApiModel,
    DateRange,
    FiniteFloat,
    Matrix,
    Point,
    RequestModel,
)
from investinglab_api.schemas.market import MetricsOut, Symbol

__all__ = [
    "DrawdownEpisodeOut",
    "HoldingIn",
    "HoldingOut",
    "PortfolioAnalyticsOut",
    "PortfolioIn",
    "RebalanceIn",
    "RiskContributionOut",
    "ValidationOut",
]


class HoldingIn(RequestModel):
    """A position and its target weight."""

    symbol: Symbol
    weight: FiniteFloat = Field(description="Target weight (decimal; negative = short).")


class RebalanceIn(RequestModel):
    """Rebalancing policy."""

    kind: RebalanceKind = RebalanceKind.PERIODIC
    frequency: Frequency = Field(
        default=Frequency.MONTH_1, description="Calendar of a periodic rebalance."
    )
    band: FiniteFloat | None = Field(
        default=None, gt=0, description="Drift that triggers a threshold rebalance (decimal)."
    )

    def to_policy(self) -> RebalancePolicy:
        """The domain policy."""
        if self.kind is RebalanceKind.BUY_AND_HOLD:
            return RebalancePolicy.buy_and_hold()
        if self.kind is RebalanceKind.THRESHOLD:
            return RebalancePolicy.threshold(self.band if self.band is not None else 0.05)
        return RebalancePolicy.periodic(self.frequency)


class PortfolioIn(DateRange):
    """A portfolio to build from market data."""

    name: str = Field(default="Portfolio", min_length=1, max_length=80)
    holdings: list[HoldingIn] = Field(
        min_length=1,
        examples=[
            [
                {"symbol": "SAN.MC", "weight": 0.4},
                {"symbol": "ITX.MC", "weight": 0.3},
                {"symbol": "IBE.MC", "weight": 0.3},
            ]
        ],
    )
    base_currency: str | None = Field(
        default=None,
        pattern=r"^[A-Z]{3}$",
        description="Valuation currency; the holdings' common currency when omitted.",
    )
    rebalance: RebalanceIn = Field(default_factory=RebalanceIn)
    allow_short: bool = False

    @model_validator(mode="after")
    def _unique_symbols(self) -> Self:
        symbols = [holding.symbol for holding in self.holdings]
        duplicated = sorted({s for s in symbols if symbols.count(s) > 1})
        if duplicated:
            msg = f"duplicated symbols {duplicated}"
            raise ValueError(msg)
        return self

    @property
    def weights(self) -> dict[str, float]:
        """Target weight by symbol."""
        return {holding.symbol: holding.weight for holding in self.holdings}


class ValidationOut(ApiModel):
    """Whether the weights form a valid portfolio (before downloading anything)."""

    valid: bool
    total_weight: float
    problems: list[str]


class HoldingOut(ApiModel):
    """A holding of an analysed portfolio."""

    symbol: str
    name: str
    asset_class: AssetClass
    currency: str = Field(description="Currency of the original series.")
    weight: float


class RiskContributionOut(ApiModel):
    """Contribution of a holding to the portfolio volatility (Euler decomposition)."""

    symbol: str
    weight: float
    marginal: float | None
    contribution: float | None
    share: float | None = Field(description="Share of the total risk (sums to 1).")
    annualized_contribution: float | None = None


class DrawdownEpisodeOut(ApiModel):
    """A peak-to-recovery episode."""

    peak: date | datetime
    trough: date | datetime
    recovery: date | datetime | None = Field(description="Null while not recovered.")
    depth: float
    duration_periods: int


class PortfolioAnalyticsOut(ApiModel):
    """History, metrics, co-movement and risk decomposition of a portfolio."""

    name: str
    base_currency: str
    rebalance: str
    frequency: Frequency
    start: date | datetime
    end: date | datetime
    holdings: list[HoldingOut]
    metrics: MetricsOut
    value: list[Point] = Field(description="Value rebased to 100 at the first date.")
    drawdown: list[Point]
    drawdown_episodes: list[DrawdownEpisodeOut]
    correlation: Matrix
    risk_contributions: list[RiskContributionOut]
    effective_number_of_assets: float
    total_turnover: float = Field(description="Sum of the traded weight across rebalances.")
