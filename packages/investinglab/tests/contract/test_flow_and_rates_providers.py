"""Contracts of the providers of trade flow and holding rates (ADR-0031, ADR-0032).

Whatever venue sits behind them, a flow provider answers the flow of exactly the bars it
was asked for, and a rates provider the rates of exactly the instrument, kind and venue.
Each runs against recorded real responses (cassettes). A new provider joins by adding one
case.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING

import pandas as pd
import pytest
import respx

from investinglab.adapters.providers.binance import BinanceProvider
from investinglab.adapters.providers.coinbase import CoinbaseProvider
from investinglab.adapters.providers.kraken import KrakenProvider
from investinglab.adapters.providers.okx import OkxProvider
from investinglab.adapters.providers.yahoo import YahooFinanceProvider
from investinglab.domain import FlowSeries, RateSeries
from investinglab.ports import (
    BarsRequest,
    Dataset,
    HoldingRatesProvider,
    RatesRequest,
    SymbolNotFoundError,
    TradeFlowProvider,
)
from support.cassettes import load_cassette

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable

SLUG = re.compile(r"^[a-z0-9][a-z0-9_.\-]{0,39}$")
TODAY = date(2026, 11, 13)


# ── Flow ─────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class FlowCase:
    """A flow provider over its recordings: a request it serves and one it cannot."""

    name: str
    build: Callable[[respx.MockRouter], TradeFlowProvider]
    request: BarsRequest
    unknown: BarsRequest
    aggressor_side: bool


def _binance(router: respx.MockRouter) -> TradeFlowProvider:
    known = load_cassette("binance/btc_usdt_1d")
    known.play(router)
    load_cassette("binance/not_found").play(router)
    return BinanceProvider(clock=known.clock)


def _yahoo(router: respx.MockRouter) -> TradeFlowProvider:
    known = load_cassette("yahoo/san_mc_1d")
    known.play(router)
    load_cassette("yahoo/not_found").play(router)
    return YahooFinanceProvider(clock=known.clock)


def _kraken(router: respx.MockRouter) -> TradeFlowProvider:
    known = load_cassette("kraken/btc_usd_1d")
    known.play(router)
    load_cassette("kraken/not_found").play(router)
    return KrakenProvider(clock=known.clock)


def _coinbase(router: respx.MockRouter) -> TradeFlowProvider:
    known = load_cassette("coinbase/btc_usd_1d")
    known.play(router)
    load_cassette("coinbase/not_found").play(router)
    return CoinbaseProvider(clock=known.clock)


FLOW_CASES = (
    FlowCase(
        "binance",
        _binance,
        load_cassette("binance/btc_usdt_1d").bars_request,
        load_cassette("binance/not_found").bars_request,
        aggressor_side=True,
    ),
    FlowCase(
        "kraken",
        _kraken,
        load_cassette("kraken/btc_usd_1d").bars_request,
        load_cassette("kraken/not_found").bars_request,
        aggressor_side=False,
    ),
    FlowCase(
        "coinbase",
        _coinbase,
        load_cassette("coinbase/btc_usd_1d").bars_request,
        load_cassette("coinbase/not_found").bars_request,
        aggressor_side=False,
    ),
    FlowCase(
        "yahoo",
        _yahoo,
        load_cassette("yahoo/san_mc_1d").bars_request,
        load_cassette("yahoo/not_found").bars_request,
        aggressor_side=False,
    ),
)


@pytest.fixture(params=FLOW_CASES, ids=[case.name for case in FLOW_CASES])
async def flow_provider(
    request: pytest.FixtureRequest,
) -> AsyncIterator[tuple[FlowCase, TradeFlowProvider]]:
    case: FlowCase = request.param
    with respx.mock(assert_all_called=False) as router:
        provider = case.build(router)
        yield case, provider
        await provider.aclose()  # type: ignore[attr-defined]


async def test_flow_providers_implement_the_port(
    flow_provider: tuple[FlowCase, TradeFlowProvider],
) -> None:
    case, provider = flow_provider

    assert isinstance(provider, TradeFlowProvider)
    assert provider.name == case.name
    assert SLUG.fullmatch(provider.name)
    assert Dataset.FLOW in provider.capabilities.datasets
    assert provider.capabilities.can_serve_flow(case.request, TODAY)


async def test_flow_answers_exactly_the_bars_requested(
    flow_provider: tuple[FlowCase, TradeFlowProvider],
) -> None:
    case, provider = flow_provider
    request = case.request

    flow = await provider.fetch_flow(request)

    assert isinstance(flow, FlowSeries)
    assert (flow.symbol, flow.frequency) == (request.symbol, request.frequency)
    assert flow.source.provider == provider.name
    assert flow.has_aggressor_side is case.aggressor_side
    assert request.start is not None
    assert request.end is not None
    assert flow.start >= pd.Timestamp(request.start)
    assert flow.end <= pd.Timestamp(request.end)


async def test_flow_of_unknown_symbols_is_not_found(
    flow_provider: tuple[FlowCase, TradeFlowProvider],
) -> None:
    case, provider = flow_provider

    with pytest.raises(SymbolNotFoundError):
        await provider.fetch_flow(case.unknown)


# ── Holding rates ────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class RatesCase:
    """A rates provider over its recordings: a request it serves and one it cannot."""

    name: str
    build: Callable[[respx.MockRouter], HoldingRatesProvider]
    request: RatesRequest
    unknown: RatesRequest


def _okx(router: respx.MockRouter) -> HoldingRatesProvider:
    known = load_cassette("okx/btc_usdt_swap_funding")
    known.play(router)
    load_cassette("okx/not_found").play(router)
    return OkxProvider(clock=known.clock)


RATES_CASES = (
    RatesCase(
        "okx",
        _okx,
        load_cassette("okx/btc_usdt_swap_funding").rates_request,
        load_cassette("okx/not_found").rates_request,
    ),
)


@pytest.fixture(params=RATES_CASES, ids=[case.name for case in RATES_CASES])
async def rates_provider(
    request: pytest.FixtureRequest,
) -> AsyncIterator[tuple[RatesCase, HoldingRatesProvider]]:
    case: RatesCase = request.param
    with respx.mock(assert_all_called=False) as router:
        provider = case.build(router)
        yield case, provider
        await provider.aclose()  # type: ignore[attr-defined]


async def test_rates_providers_implement_the_port(
    rates_provider: tuple[RatesCase, HoldingRatesProvider],
) -> None:
    case, provider = rates_provider

    assert isinstance(provider, HoldingRatesProvider)
    assert provider.name == case.name
    assert SLUG.fullmatch(provider.name)
    assert Dataset.HOLDING_RATES in provider.capabilities.datasets
    assert provider.capabilities.can_serve_rates(case.request)


async def test_rates_answer_exactly_what_was_requested(
    rates_provider: tuple[RatesCase, HoldingRatesProvider],
) -> None:
    case, provider = rates_provider
    request = case.request

    rates = await provider.fetch_rates(request)

    assert isinstance(rates, RateSeries)
    assert (rates.symbol, rates.kind) == (request.symbol, request.kind)
    assert rates.venue == (request.venue or provider.name)
    assert rates.source.provider == provider.name
    assert rates.interval is not None
    assert request.start is not None
    assert request.end is not None
    assert rates.start >= pd.Timestamp(request.start, tz="UTC")
    assert rates.end < pd.Timestamp(request.end, tz="UTC") + pd.Timedelta(days=1)


async def test_rates_of_unknown_symbols_are_not_found(
    rates_provider: tuple[RatesCase, HoldingRatesProvider],
) -> None:
    case, provider = rates_provider

    with pytest.raises(SymbolNotFoundError):
        await provider.fetch_rates(case.unknown)
