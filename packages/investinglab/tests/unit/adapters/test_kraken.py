"""Kraken adapter, replayed from real recorded responses (``support.cassettes``).

The robustness tests alter a *copy* of a recorded payload to prove each rule; the altered
values are never used as market data.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Any

import pandas as pd
import pytest
import respx

from investinglab.adapters.providers.kraken import KrakenProvider
from investinglab.domain import AssetClass, Frequency
from investinglab.ports import (
    BarsRequest,
    Dataset,
    MarketDataProvider,
    ProviderDataError,
    RateLimitedError,
    SymbolNotFoundError,
    TradeFlowProvider,
)
from support.cassettes import Cassette, load_cassette

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture
def router() -> Iterator[respx.MockRouter]:
    with respx.mock(assert_all_called=False) as mock:
        yield mock


def _rows(cassette: Cassette) -> list[list[Any]]:
    result = cassette.payload()["result"]
    (key,) = [key for key in result if key != "last"]
    rows: list[list[Any]] = result[key]
    return rows


async def test_daily_bars_of_a_dollar_pair(router: respx.MockRouter) -> None:
    cassette = load_cassette("kraken/btc_usd_1d")
    (route,) = cassette.play(router)

    async with KrakenProvider(clock=cassette.clock) as provider:
        bars = await provider.fetch_bars(cassette.bars_request)
        flow = await provider.fetch_flow(cassette.bars_request)

    assert (bars.symbol, len(bars)) == ("BTC/USD", 20)
    assert bars.bars.index[0] == pd.Timestamp("2026-10-01")
    assert bars.bars.index[-1] == pd.Timestamp("2026-10-20")  # later bars are cut off
    assert bars.instrument.currency.code == "USD"
    assert bars.instrument.asset_class is AssetClass.CRYPTO
    assert bars.instrument.name == "BTC/USD (Kraken spot)"
    rows = {pd.Timestamp(int(r[0]), unit="s"): r for r in _rows(cassette)}
    first = rows[pd.Timestamp("2026-10-01")]
    assert bars.bars["close"].iloc[0] == float(first[4])
    assert flow.flow.index.equals(bars.bars.index)
    assert list(flow.flow.columns) == ["volume", "quote_volume", "trades"]
    assert not flow.has_aggressor_side
    assert flow.column("trades").iloc[0] == first[7]
    assert flow.vwap.iloc[0] == pytest.approx(float(first[5]))  # the VWAP Kraken reported
    params = route.calls.last.request.url.params
    assert (params["pair"], params["interval"]) == ("BTCUSD", "1440")
    assert int(params["since"]) == int(datetime(2026, 10, 1, tzinfo=UTC).timestamp())


async def test_the_bar_in_progress_is_left_out(router: respx.MockRouter) -> None:
    cassette = load_cassette("kraken/eth_eur_4h_live")
    cassette.play(router)

    async with KrakenProvider(clock=cassette.clock) as provider:
        bars = await provider.fetch_bars(cassette.bars_request)

    rows = _rows(cassette)
    assert len(bars) == len(rows) - 1
    assert bars.frequency is Frequency.HOUR_4
    assert bars.end + pd.Timedelta(hours=4) <= pd.Timestamp(cassette.recorded_at)
    assert bars.instrument.currency.code == "EUR"


async def test_an_unknown_pair_is_not_found(router: respx.MockRouter) -> None:
    cassette = load_cassette("kraken/not_found")
    cassette.play(router)

    async with KrakenProvider(clock=cassette.clock) as provider:
        with pytest.raises(SymbolNotFoundError, match="Unknown asset pair"):
            await provider.fetch_bars(cassette.bars_request)


@pytest.mark.parametrize(
    ("change", "error", "message"),
    [
        (lambda p: p.update(error=["EAPI:Rate limit exceeded"]), RateLimitedError, "Rate limit"),
        (lambda p: p.update(error=["EService:Unavailable"]), ProviderDataError, "Unavailable"),
        (lambda p: p.update(result={"last": 1}), ProviderDataError, "the bars of one pair"),
        (lambda p: p.update(error="none"), ProviderDataError, "unexpected OHLC payload"),
        (
            lambda p: next(v for k, v in p["result"].items() if k != "last")[0].__setitem__(4, "x"),
            ProviderDataError,
            "unexpected OHLC row",
        ),
        (
            lambda p: next(v for k, v in p["result"].items() if k != "last")[0].__setitem__(
                4, "NaN"
            ),
            ProviderDataError,
            "non-finite",
        ),
    ],
    ids=["throttled", "other-error", "no-pair", "malformed", "text", "nan"],
)
async def test_failed_or_malformed_answers_are_errors(
    router: respx.MockRouter, change: Any, error: type[Exception], message: str
) -> None:
    cassette = load_cassette("kraken/btc_usd_1d")
    payload = cassette.payload()
    change(payload)
    cassette.play(router, payload=payload)

    async with KrakenProvider(clock=cassette.clock) as provider:
        with pytest.raises(error, match=message):
            await provider.fetch_bars(cassette.bars_request)


async def test_without_a_start_kraken_answers_its_recent_bars(router: respx.MockRouter) -> None:
    cassette = load_cassette("kraken/btc_usd_1d")
    (route,) = cassette.play(router, exact=False)

    async with KrakenProvider(clock=cassette.clock) as provider:
        bars = await provider.fetch_bars(BarsRequest("BTC/USD"))

    assert "since" not in route.calls.last.request.url.params
    assert bars.end <= pd.Timestamp(cassette.recorded_at.date())


def test_capabilities_declare_the_look_back() -> None:
    provider = KrakenProvider()
    capabilities = provider.capabilities
    today = date(2026, 11, 13)

    assert isinstance(provider, MarketDataProvider)
    assert isinstance(provider, TradeFlowProvider)
    assert capabilities.datasets == frozenset({Dataset.BARS, Dataset.FLOW})
    assert capabilities.can_serve_bars(BarsRequest("BTC/USD", start=date(2026, 1, 1)), today)
    assert not capabilities.can_serve_bars(BarsRequest("BTC/USD", start=date(2020, 1, 1)), today)
    assert not capabilities.can_serve_bars(BarsRequest("BTC/USD"), today)  # no start: too long
    hourly = BarsRequest("BTC/USD", Frequency.HOUR_1, start=date(2026, 11, 1))
    assert capabilities.can_serve_bars(hourly, today)
    weekly = BarsRequest("BTC/USD", Frequency.WEEK_1, start=date(2026, 1, 1))
    assert capabilities.can_serve_flow(weekly, today)
    assert not capabilities.can_serve_bars(BarsRequest("BTC-USD", start=date(2026, 1, 1)), today)
