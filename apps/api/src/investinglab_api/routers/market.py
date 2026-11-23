"""Market data: bars, flow, holding rates, positioning, comparisons, quality and risk-free rates."""

from __future__ import annotations

import asyncio
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Query

from investinglab.domain.instruments import AssetClass
from investinglab.domain.rate_series import RateKind
from investinglab.domain.time import Frequency
from investinglab_api import use_cases
from investinglab_api.dependencies import SettingsDep, ToolkitDep, at_most
from investinglab_api.mappers import (
    book_depth_out,
    card_out,
    comparison_out,
    confluence_out,
    flow_out,
    market_caps_out,
    market_snapshot_out,
    patterns_out,
    positioning_out,
    quality_out,
    rates_out,
    risk_free_out,
    series_out,
    structure_out,
    technical_out,
    venues_out,
)
from investinglab_api.routers import problems
from investinglab_api.schemas.market import (
    BookDepthOut,
    CardOut,
    CompareRequest,
    ComparisonOut,
    ConfluenceOut,
    FlowOut,
    MarketCapsOut,
    MarketSnapshotOut,
    PatternsOut,
    PositioningOut,
    QualityOut,
    RatesOut,
    SeriesOut,
    StructureOut,
    Symbol,
    TechnicalOut,
    VenueDataset,
    VenuesOut,
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
Venue = Annotated[
    str | None,
    Query(pattern=r"^[a-z0-9][a-z0-9_.\-]{0,39}$", description="Venue (okx...); any."),
]


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
    "/market/confluence",
    summary="Signal panel and trend of an instrument across timeframes",
    response_model=ConfluenceOut,
    responses=problems(404, 422, 503),
)
async def confluence(
    toolkit: ToolkitDep,
    symbol: SymbolQuery,
    *,
    frames: Annotated[
        list[Frequency] | None,
        Query(
            alias="frame",
            description=(
                "Frames to read (repeat it), among 15m, 30m, 1h, 4h, 1d, 1w and 1mo; daily, "
                "weekly and monthly by default."
            ),
        ),
    ] = None,
    end: End = None,
) -> ConfluenceOut:
    """Eleven conventional rules and the trend on each frame, and whether they agree (ADR-0038).

    Daily, weekly and monthly frames come from one download of daily bars. A frame nobody
    serves, or with too few bars, is reported with its ``issue`` and does not count. The
    rules describe; they are not advice.
    """
    found = await toolkit.confluence(symbol, frames=frames, end=end)
    return await asyncio.to_thread(confluence_out, found)


@router.get(
    "/market/card",
    summary="Card of an instrument: what each pillar of its asset class says",
    response_model=CardOut,
    responses=problems(404, 422, 503),
)
async def card(toolkit: ToolkitDep, symbol: SymbolQuery, *, end: End = None) -> CardOut:
    """The pillars of an instrument on its last bar (ADR-0040).

    Every instrument has a technical reading, a risk profile and the quality of its data;
    a crypto pair also has the funding of its perpetual swap. A pillar no source serves
    comes with its ``issue`` and the rest are still read. Only the technical pillar is
    directional. Nothing is fused into a verdict: a card describes, it is not advice.
    """
    found = await toolkit.card(symbol, end=end)
    return await asyncio.to_thread(card_out, found)


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
    venue: Venue = None,
    start: Start = None,
    end: End = None,
) -> RatesOut:
    """What holding the instrument paid or earned per period, e.g. a perpetual's funding."""
    rates = await toolkit.holding_rates(symbol, kind=kind, venue=venue, start=start, end=end)
    return rates_out(rates)


PositioningInterval = Literal["5m", "15m", "30m", "1h", "4h", "1d"]
"""Frequencies positioning and book depth are read at (``POSITIONING_FREQUENCIES``)."""


@router.get(
    "/market/positioning",
    summary="Open interest and long/short ratios of a derivative",
    response_model=PositioningOut,
    responses=problems(404, 422, 503),
)
async def positioning(
    toolkit: ToolkitDep,
    symbol: SymbolQuery,
    *,
    venue: Venue = None,
    interval: Annotated[PositioningInterval, Query(description="Spacing of the snapshots.")] = "1h",
    start: Annotated[
        date | None, Query(description="First day (UTC); the last 30 days by default.")
    ] = None,
    end: Annotated[date | None, Query(description="Last day (UTC), inclusive.")] = None,
) -> PositioningOut:
    """How much is open on a perpetual swap and how its traders stand (ADR-0042).

    Each value is the state when its period ended; the period in progress is left out.
    A venue publishes only some fields: the others are absent, never filled in.
    """
    series = await toolkit.positioning(
        symbol, venue=venue, start=start, end=end, frequency=Frequency(interval)
    )
    return await asyncio.to_thread(positioning_out, series)


@router.get(
    "/market/book-depth",
    summary="Depth of the order book within bands around the price",
    response_model=BookDepthOut,
    responses=problems(404, 422, 503),
)
async def book_depth(
    toolkit: ToolkitDep,
    symbol: SymbolQuery,
    *,
    venue: Venue = None,
    interval: Annotated[PositioningInterval, Query(description="Spacing of the snapshots.")] = "1h",
    start: Annotated[
        date | None, Query(description="First day (UTC); the last 7 days by default.")
    ] = None,
    end: Annotated[date | None, Query(description="Last day (UTC), inclusive.")] = None,
) -> BookDepthOut:
    """What rests to buy and to sell within each distance from the price (ADR-0044).

    Each value is the book when its period ended; the period in progress is left out. Depth
    is cumulative, and a band or a value the venue does not publish is absent, never filled
    in. Binance reads at most 92 days at once: a longer range is a 422.
    """
    depth = await toolkit.book_depth(
        symbol, venue=venue, start=start, end=end, frequency=Frequency(interval)
    )
    return await asyncio.to_thread(book_depth_out, depth)


Currency = Annotated[str, Query(pattern=r"^[A-Z]{3}$", description="ISO 4217 code.")]
ReferenceMarket = Annotated[
    AssetClass, Query(description="The market described (crypto is the one served today).")
]


@router.get(
    "/market/snapshot",
    summary="The whole market of an asset class: size, change and dominance",
    response_model=MarketSnapshotOut,
    responses=problems(404, 422, 503),
)
async def market_snapshot(
    toolkit: ToolkitDep,
    asset_class: ReferenceMarket = AssetClass.CRYPTO,
    currency: Currency = "USD",
) -> MarketSnapshotOut:
    """The market as its source last computed it (ADR-0045).

    A dated snapshot, not a series: no free source keeps its history. A figure the source
    does not give in that currency (the 24-hour change, in dollars only) is null.
    """
    snapshot = await toolkit.market_snapshot(asset_class, currency=currency)
    return market_snapshot_out(snapshot)


@router.get(
    "/market/caps",
    summary="The largest assets of a market by capitalisation",
    response_model=MarketCapsOut,
    responses=problems(404, 422, 503),
)
async def market_caps(
    toolkit: ToolkitDep,
    asset_class: ReferenceMarket = AssetClass.CRYPTO,
    currency: Currency = "USD",
    top: Annotated[int, Query(ge=1, le=250, description="How many, from the largest.")] = 20,
) -> MarketCapsOut:
    """The ranking as its source last made it, each asset with its last update (ADR-0045).

    Today's ranking is not a point-in-time universe: used on the past, it would leave out
    the assets that fell out of it.
    """
    ranking = await toolkit.market_caps(top, asset_class=asset_class, currency=currency)
    return market_caps_out(ranking)


@router.get(
    "/market/venues",
    summary="Venues that serve a dataset of an instrument",
    response_model=VenuesOut,
    responses=problems(422),
)
async def venues(
    toolkit: ToolkitDep,
    symbol: SymbolQuery,
    dataset: Annotated[
        VenueDataset,
        Query(description="Funding (holding_rates), positioning or book_depth."),
    ],
) -> VenuesOut:
    """The venues able to answer, in the order they are asked when none is named.

    Interfaces list these instead of a fixed set: a venue added to the platform appears
    here on its own. Being listed means a venue serves that kind of instrument, not that it
    lists this one: asking it may still be a 404.
    """
    return venues_out(symbol, dataset, toolkit.venues(symbol, dataset))


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
