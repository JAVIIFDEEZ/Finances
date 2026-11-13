"""OKX funding adapter, replayed from real recorded responses (``support.cassettes``).

The robustness tests alter a *copy* of a recorded payload (a missing field, another swap, a
rate sent as a percentage...) or answer an error document, to prove each rule; the altered
values are never used as market data.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Any

import httpx
import pandas as pd
import pytest
import respx

from investinglab.adapters.providers import okx
from investinglab.adapters.providers.okx import OkxProvider, swap_id
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

HISTORY = "https://www.okx.com/api/v5/public/funding-rate-history"


@pytest.fixture
def router() -> Iterator[respx.MockRouter]:
    with respx.mock(assert_all_called=False) as mock:
        yield mock


def _provider(cassette: Cassette, clock: datetime | None = None) -> OkxProvider:
    moment = clock or cassette.recorded_at
    return OkxProvider(clock=lambda: moment, page_size=cassette.page_size or okx.PAGE_SIZE)


def _instant(milliseconds: str) -> pd.Timestamp:
    return pd.Timestamp(int(milliseconds), unit="ms", tz="UTC")


def _funding(payload: Any) -> pd.Series:
    """Recorded realised rates by settlement instant, oldest first."""
    data = payload["data"]
    rates = [float(payment["realizedRate"]) for payment in data]
    return pd.Series(rates, index=[_instant(p["fundingTime"]) for p in data]).sort_index()


def _request(**changes: Any) -> RatesRequest:
    return replace(load_cassette("okx/btc_usdt_swap_funding").rates_request, **changes)


# ── Funding ──────────────────────────────────────────────────────────


async def test_the_funding_settled_in_the_range_is_returned(router: respx.MockRouter) -> None:
    cassette = load_cassette("okx/btc_usdt_swap_funding")
    cassette.play(router)

    async with _provider(cassette) as provider:
        rates = await provider.fetch_rates(cassette.rates_request)

    assert (rates.symbol, rates.venue, rates.kind) == ("BTC/USDT:USDT", "okx", RateKind.FUNDING)
    assert len(rates) == 30  # ten days of payments every 8 hours
    assert rates.start == pd.Timestamp("2026-10-01 00:00", tz="UTC")
    assert rates.end == pd.Timestamp("2026-10-10 16:00", tz="UTC")
    assert rates.interval == pd.Timedelta(hours=8)
    recorded = _funding(cassette.payload())
    assert rates.rates.tolist() == recorded.loc[rates.start : rates.end].tolist()
    instrument = rates.instrument
    assert instrument.name == "BTC/USDT perpetual swap settled in USDT (OKX BTC-USDT-SWAP)"
    assert instrument.asset_class is AssetClass.CRYPTO
    assert instrument.currency.code == "USDT"
    assert (rates.source.provider, rates.source.dataset) == (
        "okx",
        "api/v5/public/funding-rate-history",
    )
    assert rates.source.retrieved_at == cassette.recorded_at


async def test_the_first_page_ends_with_the_last_requested_day(router: respx.MockRouter) -> None:
    cassette = load_cassette("okx/btc_usdt_swap_funding")
    (route,) = cassette.play(router)

    async with _provider(cassette) as provider:
        await provider.fetch_rates(cassette.rates_request)

    params = route.calls.last.request.url.params
    assert params["instId"] == "BTC-USDT-SWAP"
    after = datetime(2026, 10, 11, tzinfo=UTC)  # payments strictly before the 11th
    assert int(params["after"]) == int(after.timestamp() * 1000)
    assert params["limit"] == "100"


async def test_pages_go_back_until_the_first_requested_day(router: respx.MockRouter) -> None:
    paged = load_cassette("okx/btc_usdt_swap_paged")
    routes = paged.play(router)

    async with _provider(paged) as provider:
        rates = await provider.fetch_rates(paged.rates_request)

    assert paged.page_size == 6
    assert all(route.call_count == 1 for route in routes)
    assert len(routes) == 3
    assert len(rates) == 15
    whole = load_cassette("okx/btc_usdt_swap_funding")
    async with _provider(whole) as provider:
        whole.play(router)
        everything = await provider.fetch_rates(whole.rates_request)
    assert rates.rates.equals(everything.rates.iloc[:15])  # the same payments, page by page


async def test_one_payment_keeps_the_interval_of_the_payments_around_it(
    router: respx.MockRouter,
) -> None:
    cassette = load_cassette("okx/btc_usdt_swap_funding")
    cassette.play(router, exact=False)
    early = datetime(2026, 10, 5, 0, 30, tzinfo=UTC)  # only the midnight payment had settled

    async with _provider(cassette, clock=early) as provider:
        rates = await provider.fetch_rates(_request(start=date(2026, 10, 5), end=date(2026, 10, 5)))

    assert len(rates) == 1
    assert rates.interval == pd.Timedelta(hours=8)
    assert rates.periods_per_year == pytest.approx(1095.0)


async def test_the_realised_rate_is_preferred_to_the_predicted_one(
    router: respx.MockRouter,
) -> None:
    cassette = load_cassette("okx/btc_usdt_swap_funding")
    payload = cassette.payload()
    first, second = payload["data"][0], payload["data"][1]
    first["fundingRate"], first["realizedRate"] = "0.0009", "0.0001"
    second["fundingRate"], second["realizedRate"] = "0.0002", ""
    cassette.play(router, payload=payload)

    async with _provider(cassette) as provider:
        rates = await provider.fetch_rates(cassette.rates_request)

    assert rates.rates.loc[_instant(first["fundingTime"])] == 0.0001
    assert rates.rates.loc[_instant(second["fundingTime"])] == 0.0002


async def test_a_range_older_than_the_history_says_so(router: respx.MockRouter) -> None:
    router.get(HISTORY).mock(
        return_value=httpx.Response(200, json={"code": "0", "data": [], "msg": ""})
    )

    async with OkxProvider() as provider:
        with pytest.raises(ProviderDataError, match="about three months"):
            await provider.fetch_rates(_request(start=date(2025, 1, 1), end=date(2025, 1, 2)))


async def test_a_range_needing_too_many_pages_is_refused(
    router: respx.MockRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    paged = load_cassette("okx/btc_usdt_swap_paged")
    paged.play(router)
    monkeypatch.setattr(okx.provider, "MAX_PAGES", 1)

    async with _provider(paged) as provider:
        with pytest.raises(UnsupportedRequestError, match="more than 6 payments"):
            await provider.fetch_rates(paged.rates_request)


# ── Refusals and errors ──────────────────────────────────────────────


async def test_an_unknown_swap_is_not_found(router: respx.MockRouter) -> None:
    cassette = load_cassette("okx/not_found")
    cassette.play(router)

    async with _provider(cassette) as provider:
        with pytest.raises(SymbolNotFoundError, match="doesn't exist"):
            await provider.fetch_rates(cassette.rates_request)


@pytest.mark.parametrize(
    ("request_", "message"),
    [
        (_request(symbol="BTC/USDT"), "not a perpetual swap"),
        (_request(symbol="BTC/USD:USD"), "settles its BTC/USD swap in BTC, not USD"),
        (_request(symbol="BTC/USDT:BTC"), "settles its BTC/USDT swap in USDT"),
        (_request(symbol="BTC/TUSD:TUSD"), "prices quoted in TUSD cannot be represented"),
        (_request(kind=RateKind.BORROW), "serves funding, not borrow"),
        (_request(venue="binance"), "not binance's"),
    ],
    ids=["spot-pair", "inverse-in-usd", "linear-in-base", "unknown-quote", "borrow", "venue"],
)
async def test_what_okx_does_not_serve_is_refused_without_a_request(
    router: respx.MockRouter, request_: RatesRequest, message: str
) -> None:
    async with OkxProvider() as provider:
        with pytest.raises(UnsupportedRequestError, match=message):
            await provider.fetch_rates(request_)

    assert not router.calls


@pytest.mark.parametrize(
    ("change", "error", "message"),
    [
        (lambda p: p["data"][0].pop("fundingTime"), ProviderDataError, "unexpected funding"),
        (lambda p: p.update(data="none"), ProviderDataError, "unexpected funding"),
        (lambda p: p["data"][0].update(instId="ETH-USDT-SWAP"), ProviderDataError, "ETH-USDT"),
        (lambda p: p["data"][0].update(realizedRate="n/a"), ProviderDataError, "not a number"),
        (lambda p: p["data"][0].update(realizedRate="1.5"), ProviderDataError, "not plausible"),
        (
            lambda p: p.update(code="50011", msg="Too Many Requests", data=[]),
            RateLimitedError,
            "Too Many Requests",
        ),
        (
            lambda p: p.update(code="50001", msg="Service unavailable", data=[]),
            ProviderDataError,
            "OKX error 50001",
        ),
    ],
    ids=["no-time", "no-list", "other-swap", "text", "percent", "throttled", "other-code"],
)
async def test_malformed_or_failed_answers_are_errors(
    router: respx.MockRouter, change: Any, error: type[Exception], message: str
) -> None:
    cassette = load_cassette("okx/btc_usdt_swap_funding")
    payload = cassette.payload()
    change(payload)
    cassette.play(router, payload=payload)

    async with _provider(cassette) as provider:
        with pytest.raises(error, match=message):
            await provider.fetch_rates(cassette.rates_request)


@pytest.mark.parametrize(
    ("response", "error", "message"),
    [
        (
            httpx.Response(400, json={"code": "51001", "msg": "Instrument ID doesn't exist."}),
            SymbolNotFoundError,
            "Instrument ID",
        ),
        (httpx.Response(400, json={"code": "51000", "msg": "Parameter error"}), Exception, "400"),
        (httpx.Response(400, text="Bad Request"), UnsupportedRequestError, "HTTP 400"),
        (httpx.Response(400, json=["odd"]), UnsupportedRequestError, "HTTP 400"),
    ],
    ids=["unknown-swap", "other-code", "text", "list"],
)
async def test_http_error_documents_are_translated(
    router: respx.MockRouter, response: httpx.Response, error: type[Exception], message: str
) -> None:
    router.get(HISTORY).mock(return_value=response)

    async with OkxProvider() as provider:
        with pytest.raises(error, match=message):
            await provider.fetch_rates(_request())


# ── Description ──────────────────────────────────────────────────────


def test_capabilities_describe_okx() -> None:
    provider = OkxProvider()
    capabilities = provider.capabilities

    assert isinstance(provider, HoldingRatesProvider)
    assert provider.name == "okx"
    assert capabilities.datasets == frozenset({Dataset.HOLDING_RATES})
    assert capabilities.rate_kinds == frozenset({RateKind.FUNDING})
    assert not capabilities.requires_api_key
    assert capabilities.can_serve_rates(_request())
    assert not capabilities.can_serve_rates(_request(kind=RateKind.FINANCING))
    assert not capabilities.can_serve_rates(_request(symbol="BTC/USDT"))


@pytest.mark.parametrize(
    ("symbol", "swap"),
    [
        ("BTC/USDT:USDT", "BTC-USDT-SWAP"),
        ("ETH/USDC:USDC", "ETH-USDC-SWAP"),
        ("BTC/USD:BTC", "BTC-USD-SWAP"),
    ],
)
def test_swaps_map_to_okx_identifiers(symbol: str, swap: str) -> None:
    assert swap_id(symbol) == swap


@pytest.mark.parametrize("page_size", [0, 101])
def test_the_page_size_is_bounded(page_size: int) -> None:
    with pytest.raises(DomainError, match="page_size"):
        OkxProvider(page_size=page_size)
