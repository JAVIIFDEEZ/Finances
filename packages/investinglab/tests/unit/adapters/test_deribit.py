"""Deribit funding adapter, replayed from real recorded responses (``support.cassettes``).

The robustness tests alter a *copy* of a recorded payload (a missing field, an error
document...) or answer one of Deribit's errors, to prove each rule; the altered values are
never used as market data.
"""

from __future__ import annotations

import itertools
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Any

import httpx
import pandas as pd
import pytest
import respx

from investinglab.adapters.http import RetryPolicy
from investinglab.adapters.providers import deribit
from investinglab.adapters.providers.deribit import DeribitProvider, swap_id
from investinglab.domain import AssetClass, DomainError, RateKind
from investinglab.ports import (
    Dataset,
    HoldingRatesProvider,
    ProviderDataError,
    RateLimitedError,
    RatesRequest,
    SymbolNotFoundError,
    UnsupportedRequestError,
)
from support.cassettes import Cassette, load_cassette

if TYPE_CHECKING:
    from collections.abc import Iterator

HISTORY = f"{deribit.BASE_URL}/{deribit.DATASET}"


@pytest.fixture
def router() -> Iterator[respx.MockRouter]:
    with respx.mock(assert_all_called=False) as mock:
        yield mock


def _provider(cassette: Cassette, clock: datetime | None = None) -> DeribitProvider:
    moment = clock or cassette.recorded_at
    window = timedelta(hours=cassette.page_size) if cassette.page_size else deribit.WINDOW
    return DeribitProvider(clock=lambda: moment, window=window)


def _accrued(cassette: Cassette) -> pd.Series:
    """Recorded hourly funding by the end of its hour, read here independently."""
    accruals = [item for exchange in cassette.exchanges for item in exchange.payload["result"]]
    index = [pd.Timestamp(item["timestamp"], unit="ms", tz="UTC") for item in accruals]
    return pd.Series([item["interest_1h"] for item in accruals], index=index).sort_index()


def _request(**changes: Any) -> RatesRequest:
    return replace(load_cassette("deribit/btc_usd_funding").rates_request, **changes)


# ── Funding ──────────────────────────────────────────────────────────


async def test_the_funding_of_each_hour_is_returned(router: respx.MockRouter) -> None:
    cassette = load_cassette("deribit/btc_usd_funding")
    cassette.play(router)

    async with _provider(cassette) as provider:
        rates = await provider.fetch_rates(cassette.rates_request)

    assert (rates.symbol, rates.venue, rates.kind) == ("BTC/USD:BTC", "deribit", RateKind.FUNDING)
    assert len(rates) == 240  # ten days of hours, each stamped at its end
    assert rates.start == pd.Timestamp("2026-10-01 00:00", tz="UTC")
    assert rates.end == pd.Timestamp("2026-10-10 23:00", tz="UTC")
    assert rates.interval == deribit.INTERVAL
    assert rates.periods_per_year == pytest.approx(365 * 24)
    pd.testing.assert_series_equal(
        rates.rates, _accrued(cassette), check_names=False, check_index_type=False
    )
    assert (rates.rates == 0).any()  # hours inside the dampener accrue nothing, and say so
    assert str(rates.instrument.currency) == "USD"
    assert "BTC-PERPETUAL" in rates.instrument.name
    assert rates.source.dataset == deribit.DATASET


async def test_a_long_range_is_read_in_windows_that_tile_it(router: respx.MockRouter) -> None:
    cassette = load_cassette("deribit/btc_usdc_funding_windows")
    routes = cassette.play(router)

    async with _provider(cassette) as provider:
        rates = await provider.fetch_rates(cassette.rates_request)

    assert len(routes) == 3  # three days in windows of a day
    assert all(route.call_count == 1 for route in routes)
    windows = sorted(
        (int(e.params["start_timestamp"]), int(e.params["end_timestamp"]))
        for e in cassette.exchanges
    )
    assert all(after[0] == before[1] for before, after in itertools.pairwise(windows))
    assert len(rates) == 72  # every hour once: the bounds of the windows do not overlap
    assert rates.rates.index.to_series().diff().dropna().eq(deribit.INTERVAL).all()
    assert str(rates.instrument.currency) == "USDC"
    assert "BTC_USDC-PERPETUAL" in rates.instrument.name


async def test_days_before_the_listing_have_no_funding(router: respx.MockRouter) -> None:
    cassette = load_cassette("deribit/before_listing")
    cassette.play(router)

    async with _provider(cassette) as provider:
        with pytest.raises(ProviderDataError, match="no funding accrued"):
            await provider.fetch_rates(cassette.rates_request)


async def test_an_unknown_perpetual_is_not_found(router: respx.MockRouter) -> None:
    cassette = load_cassette("deribit/not_found")
    cassette.play(router)

    async with _provider(cassette) as provider:
        with pytest.raises(SymbolNotFoundError, match="wrong format"):
            await provider.fetch_rates(cassette.rates_request)


async def test_without_a_start_windows_are_read_back_to_the_listing(
    router: respx.MockRouter,
) -> None:
    recorded = load_cassette("deribit/btc_usdc_funding_windows")
    listed = int(datetime(2026, 10, 4, tzinfo=UTC).timestamp() * 1000) - 1
    newest = next(e for e in recorded.exchanges if int(e.params["end_timestamp"]) == listed)

    def answer(request: httpx.Request) -> httpx.Response:
        """The day the perpetual was (in this test) listed, and nothing before it."""
        hours = int(request.url.params["end_timestamp"]) == listed
        return httpx.Response(200, json=newest.payload if hours else {"result": []})

    route = router.get(HISTORY).mock(side_effect=answer)
    provider = DeribitProvider(
        clock=lambda: datetime(2026, 11, 1, tzinfo=UTC), window=timedelta(days=1)
    )

    async with provider:
        rates = await provider.fetch_rates(
            _request(symbol="BTC/USDC:USDC", start=None, end=date(2026, 10, 3))
        )

    assert route.call_count == deribit.PARALLEL  # one batch: its second window is empty
    assert len(rates) == 24
    assert rates.start == pd.Timestamp("2026-10-03", tz="UTC")


async def test_more_windows_than_allowed_ask_for_fewer_days(router: respx.MockRouter) -> None:
    recorded = load_cassette("deribit/btc_usdc_funding_windows")
    router.get(HISTORY).mock(return_value=httpx.Response(200, json=recorded.exchanges[0].payload))
    provider = DeribitProvider(
        clock=lambda: datetime(2026, 11, 1, tzinfo=UTC), window=timedelta(hours=1)
    )

    async with provider:  # ten days in windows of an hour: 240 calls
        with pytest.raises(UnsupportedRequestError, match="ask for fewer days"):
            await provider.fetch_rates(_request(start=date(2026, 10, 1), end=date(2026, 10, 10)))
    assert not router.calls  # counted before asking


async def test_the_hours_after_the_clock_are_not_asked_for(router: respx.MockRouter) -> None:
    route = router.get(HISTORY).mock(
        return_value=httpx.Response(
            200, json={"result": [{"timestamp": 1759280400000, "interest_1h": 1e-5}]}
        )
    )
    now = datetime(2026, 10, 1, 2, 30, tzinfo=UTC)

    async with DeribitProvider(clock=lambda: now) as provider:
        rates = await provider.fetch_rates(_request(start=date(2026, 10, 1), end=date(2026, 10, 9)))

    params = route.calls.last.request.url.params
    assert int(params["end_timestamp"]) == int(now.timestamp() * 1000) - 1
    assert len(rates) == 1


@pytest.mark.parametrize(
    ("body", "error", "message"),
    [
        ({"result": [{"timestamp": 1}]}, ProviderDataError, "unexpected funding payload"),
        ({"result": "nope"}, ProviderDataError, "unexpected funding payload"),
        ({"error": {"code": 11050, "message": "bad_request"}}, ProviderDataError, "bad_request"),
        (
            {"result": [{"timestamp": 1759280400000, "interest_1h": 2.0}]},
            ProviderDataError,
            "BTC/USD:BTC",
        ),
    ],
    ids=["missing-rate", "not-a-list", "error-document", "rate-out-of-range"],
)
async def test_malformed_answers_are_refused(
    router: respx.MockRouter, body: object, error: type[Exception], message: str
) -> None:
    router.get(HISTORY).mock(return_value=httpx.Response(200, json=body))

    async with DeribitProvider(clock=lambda: datetime(2026, 11, 1, tzinfo=UTC)) as provider:
        with pytest.raises(error, match=message):
            await provider.fetch_rates(_request())


@pytest.mark.parametrize(
    ("status", "body", "error"),
    [
        (
            400,
            {"error": {"code": -32602, "data": {"reason": "not open", "param": "instrument_name"}}},
            SymbolNotFoundError,
        ),
        # Any other refusal keeps the shared translation of a 400: a request it cannot serve.
        (
            400,
            {"error": {"code": -32602, "data": {"param": "end_timestamp"}}},
            UnsupportedRequestError,
        ),
        (400, "not json", UnsupportedRequestError),
        (429, {"error": {"code": 10028, "message": "too_many_requests"}}, RateLimitedError),
    ],
    ids=["not-open", "other-param", "not-json", "throttled"],
)
async def test_errors_keep_their_meaning(
    router: respx.MockRouter, status: int, body: object, error: type[Exception]
) -> None:
    content = {"json": body} if isinstance(body, dict) else {"text": body}
    router.get(HISTORY).mock(return_value=httpx.Response(status, **content))
    provider = DeribitProvider(
        clock=lambda: datetime(2026, 11, 1, tzinfo=UTC), retry=RetryPolicy(max_attempts=1)
    )

    async with provider:
        with pytest.raises(error):
            await provider.fetch_rates(_request())


@pytest.mark.parametrize(
    ("symbol", "swap"),
    [
        ("BTC/USD:BTC", "BTC-PERPETUAL"),
        ("ETH/USD:ETH", "ETH-PERPETUAL"),
        ("BTC/USDC:USDC", "BTC_USDC-PERPETUAL"),
        ("SOL/USDC:USDC", "SOL_USDC-PERPETUAL"),
    ],
)
def test_symbols_are_written_as_deribit_names_them(symbol: str, swap: str) -> None:
    assert swap_id(symbol) == swap


@pytest.mark.parametrize(
    ("symbol", "problem"),
    [
        ("BTC/USDT:USDT", "not a Deribit perpetual"),
        ("BTC/USD", "not a Deribit perpetual"),
        ("btc/usd:btc", "not a Deribit perpetual"),
        ("BTC/USD:USD", "settles its BTC/USD perpetual in BTC"),
        ("BTC/USDC:BTC", "settles its BTC/USDC perpetual in USDC"),
    ],
)
def test_what_deribit_does_not_list_is_refused(symbol: str, problem: str) -> None:
    with pytest.raises(UnsupportedRequestError, match=problem):
        swap_id(symbol)


async def test_what_deribit_cannot_answer_is_refused_before_asking(
    router: respx.MockRouter,
) -> None:
    async with DeribitProvider(clock=lambda: datetime(2026, 11, 1, tzinfo=UTC)) as provider:
        with pytest.raises(UnsupportedRequestError, match="not borrow"):
            await provider.fetch_rates(_request(kind=RateKind.BORROW))
        with pytest.raises(UnsupportedRequestError, match="not okx's"):
            await provider.fetch_rates(_request(venue="okx"))
        with pytest.raises(UnsupportedRequestError, match="has not started"):
            await provider.fetch_rates(_request(start=date(2026, 12, 1), end=date(2026, 12, 2)))
    assert not router.calls


def test_the_window_is_bounded() -> None:
    with pytest.raises(DomainError, match="window must be between"):
        DeribitProvider(window=timedelta(minutes=30))
    with pytest.raises(DomainError, match="window must be between"):
        DeribitProvider(window=deribit.WINDOW + timedelta(hours=1))


def test_capabilities_describe_hourly_funding_of_perpetuals() -> None:
    provider = DeribitProvider()
    capabilities = provider.capabilities

    assert isinstance(provider, HoldingRatesProvider)
    assert capabilities.datasets == frozenset({Dataset.HOLDING_RATES})
    assert capabilities.asset_classes == frozenset({AssetClass.CRYPTO})
    assert capabilities.rate_kinds == frozenset({RateKind.FUNDING})
    assert capabilities.can_serve_rates(RatesRequest("BTC/USD:BTC", RateKind.FUNDING))
    assert capabilities.can_serve_rates(RatesRequest("ETH/USDC:USDC", RateKind.FUNDING))
    assert not capabilities.can_serve_rates(RatesRequest("BTC/USDT:USDT", RateKind.FUNDING))
    assert not capabilities.can_serve_rates(RatesRequest("BTC/USD:BTC", RateKind.BORROW))
