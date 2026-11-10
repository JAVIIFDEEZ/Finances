"""Market data: bars, comparisons, data quality and risk-free rates."""

from __future__ import annotations

import asyncio
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query

from investinglab.domain.time import Frequency
from investinglab_api import use_cases
from investinglab_api.dependencies import SettingsDep, ToolkitDep, at_most
from investinglab_api.mappers import comparison_out, quality_out, risk_free_out, series_out
from investinglab_api.routers import problems
from investinglab_api.schemas.market import (
    CompareRequest,
    ComparisonOut,
    QualityOut,
    SeriesOut,
    Symbol,
)
from investinglab_api.schemas.meta import RiskFreeOut

__all__ = ["router"]

router = APIRouter(prefix="/api/v1", tags=["market"])

SymbolQuery = Annotated[Symbol, Query(description="Instrument symbol (Yahoo style).")]
Interval = Annotated[Frequency, Query(description="Bar frequency.")]
Start = Annotated[date | None, Query(description="First session (inclusive).")]
End = Annotated[date | None, Query(description="Last session (inclusive).")]


@router.get(
    "/market/bars",
    summary="Bars of an instrument",
    response_model=SeriesOut,
    responses=problems(404, 422, 503),
)
async def bars(
    toolkit: ToolkitDep,
    symbol: SymbolQuery,
    interval: Interval = Frequency.DAY_1,
    start: Start = None,
    end: End = None,
) -> SeriesOut:
    """Validated bars of one instrument, with its metadata, provenance and statistics."""
    series = await toolkit.series(symbol, start=start, end=end, frequency=interval)
    return await asyncio.to_thread(series_out, series)


@router.post(
    "/market/compare",
    summary="Compare instruments",
    response_model=ComparisonOut,
    responses=problems(404, 422, 503),
)
async def compare(
    body: CompareRequest, toolkit: ToolkitDep, settings: SettingsDep
) -> ComparisonOut:
    """Performance rebased to 100, drawdowns, metrics and correlation of several instruments.

    Instruments that cannot be obtained are listed in ``failed``; the request fails only
    when none can.
    """
    at_most(body.symbols, settings.max_symbols, "symbols")
    comparison = await use_cases.compare(toolkit, body)
    return await asyncio.to_thread(
        comparison_out, comparison.batch, comparison.metrics, comparison.correlation
    )


@router.get(
    "/market/quality",
    summary="Data quality of an instrument",
    response_model=QualityOut,
    responses=problems(404, 422, 503),
)
async def quality(
    toolkit: ToolkitDep,
    symbol: SymbolQuery,
    interval: Interval = Frequency.DAY_1,
    start: Start = None,
    end: End = None,
) -> QualityOut:
    """Gaps, outliers, suspected splits and stale prices, against the official calendar."""
    series = await toolkit.series(symbol, start=start, end=end, frequency=interval)
    report = await asyncio.to_thread(toolkit.quality, series)
    return quality_out(report)


@router.get(
    "/rates/risk-free",
    summary="Risk-free rate",
    response_model=RiskFreeOut,
    responses=problems(404, 422, 503),
)
async def risk_free(
    toolkit: ToolkitDep,
    start: Annotated[date, Query(description="First business day.")],
    currency: Annotated[str, Query(pattern=r"^[A-Z]{3}$", description="ISO 4217 code.")] = "EUR",
    end: End = None,
) -> RiskFreeOut:
    """Effective annual risk-free rate known at each business day (point-in-time)."""
    rates = await use_cases.risk_free_rates(toolkit, currency, start, end)
    return risk_free_out(currency, rates)
