"""Coinbase adapter, replayed from real recorded responses (``support.cassettes``).

The robustness tests alter a *copy* of a recorded payload to prove each rule; the altered
values are never used as market data.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Any

import pandas as pd
import pytest
import respx

from investinglab.adapters.providers.coinbase import CoinbaseProvider
from investinglab.domain import DomainError, Frequency
from investinglab.ports import (
    BarsRequest,
    MarketDataProvider,
    ProviderDataError,
    SymbolNotFoundError,
    TradeFlowProvider,
    UnsupportedRequestError,
)
from support.cassettes import Cassette, load_cassette

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture
def router() -> Iterator[respx.MockRouter]:
    with respx.mock(assert_all_called=False) as mock:
        yield mock


def _provider(cassette: Cassette) -> CoinbaseProvider:
    return CoinbaseProvider(clock=cassette.clock, page_size=cassette.page_size or 300)


async def test_daily_candles_become_bars_in_time_order(router: respx.MockRouter) -> None:
    cassette = load_cassette("coinbase/btc_usd_1d")
    (route,) = cassette.play(router)

    async with _provider(cassette) as provider:
        bars = await provider.fetch_bars(cassette.bars_request)
        flow = await provider.fetch_flow(cassette.bars_request)

    rows = {pd.Timestamp(int(r[0]), unit="s"): r for r in cassette.payload()}
    first = rows[pd.Timestamp("2026-10-01")]
    assert (bars.symbol, len(bars)) == ("BTC/USD", 20)
    assert bars.bars.index.is_monotonic_increasing
    # Coinbase sends time, low, high, open, close, volume
    assert bars.bars.iloc[0][["low", "high", "open", "close"]].tolist() == first[1:5]
    assert bars.instrument.name == "BTC/USD (Coinbase spot)"
    assert list(flow.flow.columns) == ["volume"]
    assert flow.volume.iloc[0] == first[5]
    params = route.calls.last.request.url.params
    assert params["granularity"] == "86400"
    assert (params["start"], params["end"]) == ("2026-10-01T00:00:00Z", "2026-10-20T00:00:00Z")


async def test_windows_follow_each_other_without_overlap(router: respx.MockRouter) -> None:
    paged = load_cassette("coinbase/btc_usd_1d_paged")
    routes = paged.play(router)

    async with _provider(paged) as provider:
        bars = await provider.fetch_bars(paged.bars_request)

    assert paged.page_size == 7
    assert [r.call_count for r in routes] == [1, 1, 1]
    whole = load_cassette("coinbase/btc_usd_1d")
    whole.play(router)
    async with _provider(whole) as provider:
        assert bars.bars.equals((await provider.fetch_bars(whole.bars_request)).bars)


async def test_four_hour_bars_are_built_from_closed_hours(router: respx.MockRouter) -> None:
    cassette = load_cassette("coinbase/eth_eur_4h_live")
    cassette.play(router)

    async with _provider(cassette) as provider:
        bars = await provider.fetch_bars(cassette.bars_request)
        flow = await provider.fetch_flow(cassette.bars_request)

    assert bars.frequency is flow.frequency is Frequency.HOUR_4
    assert bars.end + pd.Timedelta(hours=4) <= pd.Timestamp(cassette.recorded_at)
    assert (pd.DatetimeIndex(bars.bars.index).hour % 4 == 0).all()
    assert flow.flow.index.equals(bars.bars.index)
    hours = sorted(int(r[0]) for r in cassette.payload())
    first_bin = [r for r in cassette.payload() if int(r[0]) < hours[0] + 4 * 3600]
    assert bars.bars["volume"].iloc[0] == pytest.approx(sum(r[5] for r in first_bin))


async def test_an_unknown_pair_is_not_found(router: respx.MockRouter) -> None:
    cassette = load_cassette("coinbase/not_found")
    cassette.play(router)

    async with _provider(cassette) as provider:
        with pytest.raises(SymbolNotFoundError):
            await provider.fetch_bars(cassette.bars_request)


async def test_a_range_needing_too_many_pages_is_refused_without_a_request(
    router: respx.MockRouter,
) -> None:
    async with CoinbaseProvider() as provider:
        with pytest.raises(UnsupportedRequestError, match="ask for a shorter range"):
            await provider.fetch_bars(BarsRequest("BTC/USD", Frequency.MINUTE_1))

    assert not router.calls


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"candles": []}, "expected a list of candles"),
        ([[1790812800, "x", 1, 1, 1, 1]], "unexpected candle"),
        ([[1790812800, 1, 2]], "unexpected candle"),
        ([[1790812800, "NaN", 2, 1, 1, 1]], "non-finite"),
        ([], "only 0 finished 1d bars"),
    ],
    ids=["object", "text", "short", "nan", "empty"],
)
async def test_malformed_answers_are_data_errors(
    router: respx.MockRouter, payload: Any, message: str
) -> None:
    cassette = load_cassette("coinbase/btc_usd_1d")
    cassette.play(router, payload=payload)

    async with _provider(cassette) as provider:
        with pytest.raises(ProviderDataError, match=message):
            await provider.fetch_bars(cassette.bars_request)


def test_capabilities_and_page_size() -> None:
    provider = CoinbaseProvider()
    today = date(2026, 11, 13)

    assert isinstance(provider, MarketDataProvider)
    assert isinstance(provider, TradeFlowProvider)
    assert provider.capabilities.can_serve_bars(BarsRequest("ETH/EUR"), today)
    assert not provider.capabilities.can_serve_bars(BarsRequest("ETH-EUR"), today)
    for size in (0, 301):
        with pytest.raises(DomainError, match="page_size"):
            CoinbaseProvider(page_size=size)
