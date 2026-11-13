"""Binance spot adapter, replayed from real recorded responses (``support.cassettes``).

The robustness tests alter a *copy* of a recorded payload (a malformed kline, a repeated
bar...) or answer an error document, to prove each rule; the altered values are never used
as market data.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Any

import httpx
import pandas as pd
import pytest
import respx

from investinglab.adapters.providers import binance
from investinglab.adapters.providers.binance import BinanceProvider, split_pair
from investinglab.domain import AssetClass, DomainError, FlowField, Frequency, PriceAdjustment
from investinglab.ports import (
    BannedError,
    BarsRequest,
    Dataset,
    MarketDataProvider,
    ProviderDataError,
    SymbolNotFoundError,
    TradeFlowProvider,
    UnsupportedRequestError,
)
from support.cassettes import Cassette, load_cassette

if TYPE_CHECKING:
    from collections.abc import Iterator

KLINES = "https://data-api.binance.vision/api/v3/klines"


@pytest.fixture
def router() -> Iterator[respx.MockRouter]:
    with respx.mock(assert_all_called=False) as mock:
        yield mock


def _provider(cassette: Cassette, clock: datetime | None = None) -> BinanceProvider:
    moment = clock or cassette.recorded_at
    return BinanceProvider(clock=lambda: moment, page_size=cassette.page_size or 1000)


def _milliseconds(day: date) -> int:
    return int(datetime(day.year, day.month, day.day, tzinfo=UTC).timestamp() * 1000)


# ── Daily bars and their flow ────────────────────────────────────────


async def test_daily_bars_carry_utc_dates_and_raw_prices(router: respx.MockRouter) -> None:
    cassette = load_cassette("binance/btc_usdt_1d")
    cassette.play(router)

    async with _provider(cassette) as provider:
        series = await provider.fetch_bars(cassette.bars_request)

    rows = cassette.payload()
    assert (series.symbol, series.frequency, len(series)) == ("BTC/USDT", Frequency.DAY_1, 20)
    assert series.bars.index[0] == pd.Timestamp("2026-10-01")
    assert series.bars.index[-1] == pd.Timestamp("2026-10-20")
    assert pd.DatetimeIndex(series.bars.index).tz is None
    assert series.bars["close"].tolist() == [float(row[4]) for row in rows]
    assert series.bars["volume"].tolist() == [float(row[5]) for row in rows]
    assert list(series.bars.columns) == ["open", "high", "low", "close", "volume"]
    assert series.adjustment is PriceAdjustment.RAW
    instrument = series.instrument
    assert instrument.name == "BTC/USDT (Binance spot)"
    assert instrument.asset_class is AssetClass.CRYPTO
    assert instrument.currency.code == "USDT"
    assert instrument.exchange is not None
    assert instrument.exchange.code == "CRYPTO"
    assert (series.source.provider, series.source.dataset) == ("binance", "api/v3/klines")
    assert series.source.retrieved_at == cassette.recorded_at


async def test_the_flow_of_each_bar_has_the_aggressor_side(router: respx.MockRouter) -> None:
    cassette = load_cassette("binance/btc_usdt_1d")
    cassette.play(router)

    async with _provider(cassette) as provider:
        bars = await provider.fetch_bars(cassette.bars_request)
        flow = await provider.fetch_flow(cassette.bars_request)

    rows = cassette.payload()
    assert flow.flow.index.equals(bars.bars.index)
    assert list(flow.flow.columns) == [field.value for field in FlowField]
    assert flow.has_aggressor_side
    assert flow.column("quote_volume").tolist() == [float(row[7]) for row in rows]
    assert flow.column("trades").tolist() == [float(row[8]) for row in rows]
    assert flow.buy_volume.tolist() == [float(row[9]) for row in rows]
    assert flow.column("buy_quote_volume").tolist() == [float(row[10]) for row in rows]
    first = rows[0]
    assert flow.delta.iloc[0] == pytest.approx(2 * float(first[9]) - float(first[5]))
    assert flow.vwap.iloc[0] == pytest.approx(float(first[7]) / float(first[5]))
    assert flow.aligned_with(bars).flow.equals(flow.flow)


async def test_requests_ask_for_the_utc_days_of_the_range(router: respx.MockRouter) -> None:
    cassette = load_cassette("binance/btc_usdt_1d")
    (route,) = cassette.play(router)

    async with _provider(cassette) as provider:
        await provider.fetch_bars(cassette.bars_request)

    params = route.calls.last.request.url.params
    assert params["symbol"] == "BTCUSDT"
    assert params["interval"] == "1d"
    assert int(params["startTime"]) == _milliseconds(date(2026, 10, 1))
    assert int(params["endTime"]) == _milliseconds(date(2026, 10, 21)) - 1
    assert params["limit"] == "1000"


async def test_pages_continue_after_the_last_bar(router: respx.MockRouter) -> None:
    paged = load_cassette("binance/btc_usdt_1d_paged")
    routes = paged.play(router)

    async with _provider(paged) as provider:
        series = await provider.fetch_bars(paged.bars_request)

    assert paged.page_size == 4
    assert [route.call_count for route in routes] == [1, 1, 1]
    starts = [int(route.calls.last.request.url.params["startTime"]) for route in routes]
    assert starts == [_milliseconds(date(2026, 10, day)) for day in (1, 5, 9)]
    whole = [float(row[4]) for row in load_cassette("binance/btc_usdt_1d").payload()[:10]]
    assert series.bars["close"].tolist() == whole  # the same bars as in one page


async def test_a_range_needing_too_many_pages_is_refused(
    router: respx.MockRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    paged = load_cassette("binance/btc_usdt_1d_paged")
    paged.play(router)
    monkeypatch.setattr(binance.provider, "MAX_PAGES", 2)

    async with _provider(paged) as provider:
        with pytest.raises(UnsupportedRequestError, match="more than 8 1d bars"):
            await provider.fetch_bars(paged.bars_request)


# ── Other frequencies ────────────────────────────────────────────────


async def test_the_hourly_bar_in_progress_is_left_out(router: respx.MockRouter) -> None:
    cassette = load_cassette("binance/eth_btc_1h_live")
    cassette.play(router)

    async with _provider(cassette) as provider:
        series = await provider.fetch_bars(cassette.bars_request)
        flow = await provider.fetch_flow(cassette.bars_request)

    rows = cassette.payload()
    in_progress = pd.Timestamp(int(rows[-1][0]), unit="ms", tz="UTC")
    assert in_progress + pd.Timedelta(hours=1) > pd.Timestamp(cassette.recorded_at)
    assert len(series) == len(rows) - 1
    assert in_progress not in series.bars.index
    assert str(pd.DatetimeIndex(series.bars.index).tz) == "UTC"
    assert series.end + pd.Timedelta(hours=1) <= pd.Timestamp(cassette.recorded_at)
    assert series.instrument.currency.code == "BTC"
    assert flow.flow.index.equals(series.bars.index)


async def test_weekly_bars_and_flow_are_aggregated_from_the_same_days(
    router: respx.MockRouter,
) -> None:
    cassette = load_cassette("binance/btc_usdt_1d")
    cassette.play(router)
    request = replace(cassette.bars_request, frequency=Frequency.WEEK_1)

    async with _provider(cassette) as provider:
        daily = await provider.fetch_bars(cassette.bars_request)
        bars = await provider.fetch_bars(request)
        flow = await provider.fetch_flow(request)

    assert bars.frequency is flow.frequency is Frequency.WEEK_1
    assert flow.flow.index.equals(bars.bars.index)
    assert bars.bars.index[0] == pd.Timestamp("2026-10-04")  # the first Sunday
    assert flow.volume.sum() == pytest.approx(daily.bars["volume"].sum())
    assert flow.delta.sum() == pytest.approx((2 * flow.buy_volume - flow.volume).sum())


# ── Refusals and errors ──────────────────────────────────────────────


async def test_an_unknown_pair_is_not_found(router: respx.MockRouter) -> None:
    cassette = load_cassette("binance/not_found")
    cassette.play(router)

    async with _provider(cassette) as provider:
        with pytest.raises(SymbolNotFoundError, match="Invalid symbol"):
            await provider.fetch_bars(cassette.bars_request)


@pytest.mark.parametrize(
    ("symbol", "message"),
    [
        ("BTC-USD", "not a pair written BASE/QUOTE"),
        ("btc/usdt", "not a pair written BASE/QUOTE"),
        ("BTC/USDT:USDT", "not a pair written BASE/QUOTE"),
        ("BTC/TUSD", "prices quoted in TUSD cannot be represented"),
    ],
)
async def test_what_is_not_a_known_pair_is_refused_without_a_request(
    router: respx.MockRouter, symbol: str, message: str
) -> None:
    async with BinanceProvider() as provider:
        with pytest.raises(UnsupportedRequestError, match=message):
            await provider.fetch_flow(BarsRequest(symbol, start=date(2026, 10, 1)))

    assert not router.calls


async def test_a_range_in_the_future_is_refused_without_a_request(
    router: respx.MockRouter,
) -> None:
    now = datetime(2026, 11, 13, 12, tzinfo=UTC)

    async with BinanceProvider(clock=lambda: now) as provider:
        with pytest.raises(UnsupportedRequestError, match="no bar can have finished"):
            await provider.fetch_bars(BarsRequest("BTC/USDT", start=date(2026, 11, 14)))

    assert not router.calls


async def test_too_few_finished_bars_is_a_data_error(router: respx.MockRouter) -> None:
    cassette = load_cassette("binance/btc_usdt_1d")
    cassette.play(router, exact=False)
    early = datetime(2026, 10, 2, 12, tzinfo=UTC)  # only 1 October had finished

    async with _provider(cassette, clock=early) as provider:
        with pytest.raises(ProviderDataError, match="only 1 finished 1d bars"):
            await provider.fetch_bars(cassette.bars_request)


async def test_a_repeated_bar_is_kept_once(router: respx.MockRouter) -> None:
    cassette = load_cassette("binance/btc_usdt_1d")
    rows = cassette.payload()
    cassette.play(router, payload=[*rows, rows[-1]])

    async with _provider(cassette) as provider:
        series = await provider.fetch_bars(cassette.bars_request)

    assert len(series) == 20


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"klines": []}, "expected a list of klines"),
        ([["not", "a", "kline"]], "unexpected kline"),
        ([[1790812800000, "1", "2"]], "unexpected kline"),
        ([{"open": 1}], "unexpected kline"),
    ],
    ids=["object", "text", "short", "dict"],
)
async def test_malformed_klines_are_a_data_error(
    router: respx.MockRouter, payload: Any, message: str
) -> None:
    cassette = load_cassette("binance/btc_usdt_1d")
    cassette.play(router, payload=payload)

    async with _provider(cassette) as provider:
        with pytest.raises(ProviderDataError, match=message):
            await provider.fetch_bars(cassette.bars_request)


async def test_non_finite_values_are_a_data_error(router: respx.MockRouter) -> None:
    cassette = load_cassette("binance/btc_usdt_1d")
    rows = cassette.payload()
    rows[3][9] = "NaN"
    cassette.play(router, payload=rows)

    async with _provider(cassette) as provider:
        with pytest.raises(ProviderDataError, match="non-finite"):
            await provider.fetch_flow(cassette.bars_request)


async def test_klines_that_break_the_domain_rules_are_a_data_error(
    router: respx.MockRouter,
) -> None:
    cassette = load_cassette("binance/btc_usdt_1d")
    rows = cassette.payload()
    rows[2][9] = str(float(rows[2][5]) * 2)  # more taker buying than volume
    rows[4][4] = "-1"  # a negative close
    cassette.play(router, payload=rows)

    async with _provider(cassette) as provider:
        with pytest.raises(ProviderDataError, match="exceeds 'volume'"):
            await provider.fetch_flow(cassette.bars_request)
        with pytest.raises(ProviderDataError, match="BTC/USDT"):
            await provider.fetch_bars(cassette.bars_request)


async def test_a_ban_is_reported_and_never_retried(router: respx.MockRouter) -> None:
    route = router.get(KLINES).mock(
        return_value=httpx.Response(418, headers={"Retry-After": "120"}, json={"code": -1003})
    )

    async with BinanceProvider() as provider:
        with pytest.raises(BannedError, match="banned this address") as error:
            await provider.fetch_bars(BarsRequest("BTC/USDT", start=date(2026, 10, 1)))

    assert error.value.retry_after == 120.0
    assert not error.value.retryable
    assert route.call_count == 1


@pytest.mark.parametrize(
    ("response", "error", "message"),
    [
        (
            httpx.Response(400, json={"code": -1100, "msg": "Illegal characters found."}),
            UnsupportedRequestError,
            "Illegal characters found. \\(code -1100\\)",
        ),
        (httpx.Response(400, text="Bad Request"), UnsupportedRequestError, "HTTP 400"),
        (httpx.Response(400, json=["odd"]), UnsupportedRequestError, "HTTP 400"),
        (httpx.Response(403, json={"code": 0, "msg": "WAF"}), Exception, "credentials"),
    ],
    ids=["code", "text", "list", "generic"],
)
async def test_error_documents_are_translated(
    router: respx.MockRouter, response: httpx.Response, error: type[Exception], message: str
) -> None:
    router.get(KLINES).mock(return_value=response)

    async with BinanceProvider() as provider:
        with pytest.raises(error, match=message):
            await provider.fetch_bars(BarsRequest("BTC/USDT", start=date(2026, 10, 1)))


# ── Description ──────────────────────────────────────────────────────


def test_capabilities_describe_binance() -> None:
    today = date(2026, 11, 13)
    provider = BinanceProvider()
    capabilities = provider.capabilities

    assert isinstance(provider, MarketDataProvider)
    assert isinstance(provider, TradeFlowProvider)
    assert provider.name == "binance"
    assert capabilities.datasets == frozenset({Dataset.BARS, Dataset.FLOW})
    assert capabilities.asset_classes == frozenset({AssetClass.CRYPTO})
    assert not capabilities.requires_api_key
    assert capabilities.can_serve_flow(BarsRequest("ETH/BTC", Frequency.MINUTE_1), today)
    assert capabilities.can_serve_bars(BarsRequest("BTC/USDT", Frequency.MONTH_1), today)
    for other in ("BTC-USD", "SAN.MC", "BTC/USDT:USDT"):
        assert not capabilities.can_serve_bars(BarsRequest(other), today)


def test_pairs_split_into_base_and_quote() -> None:
    assert split_pair("ETH/BTC") == ("ETH", "BTC")
    assert split_pair("1000SATS/USDT") == ("1000SATS", "USDT")


@pytest.mark.parametrize("page_size", [0, 1001])
def test_the_page_size_is_bounded(page_size: int) -> None:
    with pytest.raises(DomainError, match="page_size"):
        BinanceProvider(page_size=page_size)


async def test_the_daily_request_reaches_up_to_now_without_an_end(
    router: respx.MockRouter,
) -> None:
    cassette = load_cassette("binance/btc_usdt_1d")
    (route,) = cassette.play(router, exact=False)
    now = datetime(2026, 10, 21, 0, 0, 1, tzinfo=UTC)
    request = BarsRequest("BTC/USDT", start=date(2026, 10, 1))

    async with _provider(cassette, clock=now) as provider:
        series = await provider.fetch_bars(request)

    assert int(route.calls.last.request.url.params["endTime"]) == int(now.timestamp() * 1000) - 1
    assert series.end == pd.Timestamp("2026-10-20")
    assert now - timedelta(days=1) > datetime(2026, 10, 20, tzinfo=UTC)


async def test_a_full_last_page_ends_the_download_at_the_end_of_the_range(
    router: respx.MockRouter,
) -> None:
    rows = load_cassette("binance/btc_usdt_1d").payload()
    route = router.get(KLINES).mock(
        side_effect=[httpx.Response(200, json=rows[:4]), httpx.Response(200, json=rows[4:8])]
    )
    now = datetime(2026, 11, 13, tzinfo=UTC)
    request = BarsRequest("BTC/USDT", start=date(2026, 10, 1), end=date(2026, 10, 8))

    async with BinanceProvider(clock=lambda: now, page_size=4) as provider:
        series = await provider.fetch_bars(request)

    assert route.call_count == 2  # the second page is full, but the range is complete
    assert len(series) == 8
