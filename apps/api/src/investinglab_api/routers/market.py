"""Market data: bars, trade flow, holding rates, comparisons, data quality and risk-free rates."""

from __future__ import annotations

import asyncio
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query

from investinglab.domain.rate_series import RateKind
from investinglab.domain.time import Frequency
from investinglab_api import use_cases
from investinglab_api.dependencies import SettingsDep, ToolkitDep, at_most
from investinglab_api.mappers import (
    comparison_out,
    flow_out,
    patterns_out,
    quality_out,
    rates_out,
    risk_free_out,
    series_out,
    structure_out,
    technical_out,
)
from investinglab_api.routers import problems
from investinglab_api.schemas.market import (
    CompareRequest,
    ComparisonOut,
    FlowOut,
    PatternsOut,
    QualityOut,
    RatesOut,
    SeriesOut,
    StructureOut,
    Symbol,
    TechnicalOut,
)
from investinglab_api.schemas.meta import RiskFreeOut

__all__ = ["router"]

router = APIRouter(prefix="/api/v1", tags=["market"])

SymbolQuery = Annotated[
    Symbol,
    Query(
        description=(
            "Instrument symbol: Yahoo style (SAN.MC, ^GSPC), a venue's pair (BTC/USDT) or a "
            "perpetual swap (BTC/USDT:USDT)."
        )
    ),
]
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


@router.get(
    "/market/technical",
    summary="Technical indicators of an instrument",
    response_model=TechnicalOut,
    responses=problems(404, 422, 503),
)
async def technical(
    toolkit: ToolkitDep,
    symbol: SymbolQuery,
    *,
    interval: Interval = Frequency.DAY_1,
    start: Start = None,
    end: End = None,
    names: Annotated[
        list[str] | None,
        Query(
            alias="name",
            description="Indicators of the catalogue to compute (repeat it); all by default.",
        ),
    ] = None,
) -> TechnicalOut:
    """The indicators of CryptoWorld's catalogue on the instrument's bars (ADR-0034).

    For daily and coarser bars the indicators are already warm at ``start``; those that
    need a column the series lacks (the volume of a currency pair) are listed in
    ``unavailable`` with the columns they miss.
    """
    indicators = await toolkit.technical(
        symbol, start=start, end=end, frequency=interval, names=names
    )
    return await asyncio.to_thread(technical_out, indicators)


@router.get(
    "/market/patterns",
    summary="Price patterns of an instrument",
    response_model=PatternsOut,
    responses=problems(404, 422, 503),
)
async def patterns(
    toolkit: ToolkitDep,
    symbol: SymbolQuery,
    *,
    interval: Interval = Frequency.DAY_1,
    start: Start = None,
    end: End = None,
    names: Annotated[
        list[str] | None,
        Query(
            alias="name",
            description="Patterns of the catalogue to evaluate (repeat it); all by default.",
        ),
    ] = None,
) -> PatternsOut:
    """Candle, liquidity, session and zone patterns of the instrument's bars (ADR-0035).

    For daily and coarser bars, what the bars before ``start`` set up (an order block, a
    swing) counts from ``start``. Patterns the series cannot have (those needing the open of
    a series of closes, or intraday bars) are listed in ``unavailable`` with what they lack.
    """
    found = await toolkit.patterns(symbol, start=start, end=end, frequency=interval, names=names)
    return await asyncio.to_thread(patterns_out, found)


@router.get(
    "/market/structure",
    summary="Support and resistance, divergences and Fibonacci levels of an instrument",
    response_model=StructureOut,
    responses=problems(404, 422, 503),
)
async def structure(
    toolkit: ToolkitDep,
    symbol: SymbolQuery,
    *,
    interval: Interval = Frequency.DAY_1,
    start: Start = None,
    end: End = None,
) -> StructureOut:
    """The price structure of the bars asked for, as of the last one (ADR-0036).

    Levels and the swing come from the highs and lows, or from the closes of a series
    without them (``basis``). Each divergence says the bar that confirmed it.
    """
    found = await toolkit.structure(symbol, start=start, end=end, frequency=interval)
    return await asyncio.to_thread(structure_out, found)


@router.get(
    "/market/flow",
    summary="Trade flow of an instrument",
    response_model=FlowOut,
    responses=problems(404, 422, 503),
)
async def flow(
    toolkit: ToolkitDep,
    symbol: SymbolQuery,
    interval: Interval = Frequency.DAY_1,
    start: Start = None,
    end: End = None,
) -> FlowOut:
    """Volume of each bar and, when the source reports the aggressor, delta and CVD.

    The bars are the same as those of ``/market/bars``. A venue's pair (``BTC/USDT``) brings
    the aggressor side; a listed instrument, its volume only; a currency pair has no flow.
    """
    series = await toolkit.flow(symbol, start=start, end=end, frequency=interval)
    return await asyncio.to_thread(flow_out, series)


@router.get(
    "/market/holding-rates",
    summary="Holding rates of an instrument",
    response_model=RatesOut,
    responses=problems(404, 422, 503),
)
async def holding_rates(
    toolkit: ToolkitDep,
    symbol: SymbolQuery,
    *,
    kind: Annotated[RateKind, Query(description="Funding, borrow fee or financing.")] = (
        RateKind.FUNDING
    ),
    venue: Annotated[
        str | None,
        Query(pattern=r"^[a-z0-9][a-z0-9_.\-]{0,39}$", description="Venue (okx...); any."),
    ] = None,
    start: Start = None,
    end: End = None,
) -> RatesOut:
    """What holding the instrument paid or earned per period, e.g. a perpetual's funding."""
    rates = await toolkit.holding_rates(symbol, kind=kind, venue=venue, start=start, end=end)
    return rates_out(rates)


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
