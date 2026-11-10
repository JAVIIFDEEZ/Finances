"""Use cases of the API: orchestration of toolkit calls, nothing computed here.

Each function gathers what one endpoint needs from the core (downloads through the toolkit,
domain methods for the analytics) and returns domain objects; the routers map them to
schemas. CPU-heavy work (backtests, Monte Carlo, optimisation) runs in a worker thread so
the event loop keeps serving other requests.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

import pandas as pd

from investinglab.domain import align, weight_problems
from investinglab.services import DataUnavailableError

if TYPE_CHECKING:
    from investinglab.domain import Portfolio, PriceSeries
    from investinglab.domain.metrics import RiskMetrics
    from investinglab.domain.optimization import EfficientFrontier, OptimizationResult
    from investinglab.domain.planning import PlanResult
    from investinglab.domain.simulation import SimulationResult
    from investinglab.services import BatchResult
    from investinglab.toolkit import AsyncToolkit
    from investinglab_api.schemas.analysis import OptimizationIn, PlanIn, SimulationIn
    from investinglab_api.schemas.market import CompareRequest
    from investinglab_api.schemas.portfolio import PortfolioIn

__all__ = [
    "Comparison",
    "PortfolioAnalytics",
    "build_portfolio",
    "compare",
    "optimize",
    "plan",
    "portfolio_analytics",
    "risk_free_rates",
    "simulate",
    "validate_weights",
]


@dataclass(frozen=True, slots=True)
class Comparison:
    """Instruments compared on a common footing."""

    batch: BatchResult[PriceSeries]
    metrics: dict[str, RiskMetrics]
    correlation: pd.DataFrame | None


@dataclass(frozen=True, slots=True)
class PortfolioAnalytics:
    """A built portfolio and its metrics with the point-in-time risk-free rate."""

    portfolio: Portfolio
    metrics: RiskMetrics


async def compare(toolkit: AsyncToolkit, request: CompareRequest) -> Comparison:
    """Download the instruments concurrently and compute their metrics and correlation.

    Raises:
        DataUnavailableError: If none of the instruments could be obtained.
    """
    batch = await toolkit.many(
        request.symbols, start=request.start, end=request.end, frequency=request.frequency
    )
    if not batch.succeeded:
        attempts = tuple(a for failure in batch.failed.values() for a in failure.attempts)
        raise DataUnavailableError(", ".join(request.symbols), attempts)
    metrics = {symbol: await toolkit.metrics(series) for symbol, series in batch.succeeded.items()}
    series = list(batch.succeeded.values())
    correlation = await asyncio.to_thread(align(series).correlation) if len(series) > 1 else None
    return Comparison(batch=batch, metrics=metrics, correlation=correlation)


def validate_weights(request: PortfolioIn) -> list[str]:
    """Problems of the target weights, before downloading anything (empty when valid)."""
    pairs = [(holding.symbol, holding.weight) for holding in request.holdings]
    return weight_problems(pairs, allow_short=request.allow_short)


async def build_portfolio(toolkit: AsyncToolkit, request: PortfolioIn) -> Portfolio:
    """Download the holdings, convert them to the base currency and build the portfolio."""
    return await toolkit.portfolio(
        request.name,
        request.weights,
        base_currency=request.base_currency,
        start=request.start,
        end=request.end,
        frequency=request.frequency,
        rebalance=request.rebalance.to_policy(),
        allow_short=request.allow_short,
    )


async def portfolio_analytics(toolkit: AsyncToolkit, request: PortfolioIn) -> PortfolioAnalytics:
    """The portfolio and its metrics, with its history computed once in a worker thread."""
    portfolio = await build_portfolio(toolkit, request)
    await asyncio.to_thread(portfolio.backtest)  # memoised: the mapper reuses it
    metrics = await toolkit.metrics(portfolio)
    return PortfolioAnalytics(portfolio=portfolio, metrics=metrics)


async def simulate(toolkit: AsyncToolkit, request: SimulationIn) -> SimulationResult:
    """Monte Carlo of the portfolio's value."""
    portfolio = await build_portfolio(toolkit, request.portfolio)
    return await asyncio.to_thread(portfolio.monte_carlo, request.to_config())


async def optimize(
    toolkit: AsyncToolkit, request: OptimizationIn
) -> tuple[OptimizationResult, EfficientFrontier | None]:
    """Optimal weights and, when points are asked for, the efficient frontier."""
    portfolio = await build_portfolio(toolkit, request.portfolio)
    config = request.to_config()
    result = await asyncio.to_thread(portfolio.optimize, config)
    if request.frontier_points == 0:
        return result, None
    frontier = await asyncio.to_thread(
        portfolio.efficient_frontier, config, points=request.frontier_points
    )
    return result, frontier


async def plan(toolkit: AsyncToolkit, request: PlanIn) -> PlanResult:
    """Monte Carlo of a savings plan invested in the portfolio."""
    portfolio = await build_portfolio(toolkit, request.portfolio)
    return await asyncio.to_thread(portfolio.savings_plan, request.to_plan(), request.to_config())


async def risk_free_rates(
    toolkit: AsyncToolkit, currency: str, start: date, end: date | None
) -> pd.Series:
    """The point-in-time risk-free rate of every business day between two dates."""
    last = end or datetime.now(UTC).date()
    days = pd.bdate_range(start=start, end=last)
    return await toolkit.risk_free(currency, days)
