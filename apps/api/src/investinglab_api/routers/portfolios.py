"""Portfolios: validation, analytics, reports, Monte Carlo, optimisation and savings plans."""

from __future__ import annotations

import asyncio
import math
from typing import Annotated, Literal

from fastapi import APIRouter, Query
from fastapi.responses import PlainTextResponse

from investinglab_api import use_cases
from investinglab_api.dependencies import SettingsDep, ToolkitDep, at_most
from investinglab_api.mappers import (
    optimization_out,
    plan_out,
    portfolio_analytics_out,
    simulation_out,
)
from investinglab_api.routers import problems
from investinglab_api.schemas.analysis import (
    OptimizationIn,
    OptimizationOut,
    PlanIn,
    PlanOut,
    SimulationIn,
    SimulationOut,
)
from investinglab_api.schemas.portfolio import PortfolioAnalyticsOut, PortfolioIn, ValidationOut

__all__ = ["router"]

router = APIRouter(prefix="/api/v1")

MARKDOWN = "text/markdown; charset=utf-8"


def _limits(portfolio: PortfolioIn, settings: SettingsDep) -> None:
    at_most(portfolio.holdings, settings.max_symbols, "holdings")


@router.post(
    "/portfolios/validate",
    tags=["portfolios"],
    summary="Validate weights",
    response_model=ValidationOut,
    responses=problems(422),
)
async def validate(body: PortfolioIn, settings: SettingsDep) -> ValidationOut:
    """Check the target weights with the domain's rules, without downloading anything."""
    _limits(body, settings)
    found = use_cases.validate_weights(body)
    total = math.fsum(holding.weight for holding in body.holdings)
    return ValidationOut(valid=not found, total_weight=total, problems=found)


@router.post(
    "/portfolios/analytics",
    tags=["portfolios"],
    summary="Analyse a portfolio",
    response_model=PortfolioAnalyticsOut,
    responses=problems(404, 422, 503),
)
async def analytics(
    body: PortfolioIn, toolkit: ToolkitDep, settings: SettingsDep
) -> PortfolioAnalyticsOut:
    """History, metrics, drawdowns, correlation and risk decomposition of a portfolio.

    The backtest follows the rebalancing policy, and Sharpe and Sortino use the risk-free
    rate known at each date.
    """
    _limits(body, settings)
    result = await use_cases.portfolio_analytics(toolkit, body)
    return await asyncio.to_thread(portfolio_analytics_out, result.portfolio, result.metrics)


@router.post(
    "/portfolios/report",
    tags=["portfolios"],
    summary="Portfolio report (Markdown)",
    response_class=PlainTextResponse,
    responses={200: {"content": {MARKDOWN: {}}}, **problems(404, 422, 503)},
)
async def report(
    body: PortfolioIn,
    toolkit: ToolkitDep,
    settings: SettingsDep,
    language: Annotated[Literal["es", "en"], Query(description="Report language.")] = "es",
) -> PlainTextResponse:
    """The bilingual Markdown report of the portfolio, as the notebooks write it."""
    _limits(body, settings)
    portfolio = await use_cases.build_portfolio(toolkit, body)
    text = await toolkit.report(portfolio, language=language)
    return PlainTextResponse(str(text), media_type=MARKDOWN)


@router.post(
    "/simulations",
    tags=["analysis"],
    summary="Monte Carlo simulation",
    response_model=SimulationOut,
    responses=problems(404, 422, 503),
)
async def simulations(
    body: SimulationIn, toolkit: ToolkitDep, settings: SettingsDep
) -> SimulationOut:
    """Simulate the portfolio's value: fan chart, terminal distribution and tail risk."""
    _limits(body.portfolio, settings)
    at_most(body.n_paths, settings.max_paths, "paths")
    at_most(body.horizon, settings.max_horizon, "periods of horizon")
    result = await use_cases.simulate(toolkit, body)
    return await asyncio.to_thread(simulation_out, result)


@router.post(
    "/optimizations",
    tags=["analysis"],
    summary="Optimise weights",
    response_model=OptimizationOut,
    responses=problems(404, 422, 503),
)
async def optimizations(
    body: OptimizationIn, toolkit: ToolkitDep, settings: SettingsDep
) -> OptimizationOut:
    """Weights that best meet the objective, and the efficient frontier around them."""
    _limits(body.portfolio, settings)
    at_most(body.frontier_points, settings.max_frontier_points, "frontier points")
    result, frontier = await use_cases.optimize(toolkit, body)
    return optimization_out(result, frontier)


@router.post(
    "/plans",
    tags=["analysis"],
    summary="Savings plan",
    response_model=PlanOut,
    responses=problems(404, 422, 503),
)
async def plans(body: PlanIn, toolkit: ToolkitDep, settings: SettingsDep) -> PlanOut:
    """Odds that monthly contributions reach a goal, in today's money."""
    _limits(body.portfolio, settings)
    at_most(body.n_paths, settings.max_paths, "paths")
    result = await use_cases.plan(toolkit, body)
    return await asyncio.to_thread(plan_out, result, body.success_probability)
