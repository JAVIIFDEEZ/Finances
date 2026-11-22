"""CoinGecko: snapshots of the crypto market, replayed from real recorded responses.

The robustness tests alter a *copy* of a recorded answer to prove each rule; the altered
values are never used as market data.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import httpx
import pytest
import respx
from pydantic import SecretStr

from investinglab.adapters.providers.coingecko import KEY_HEADER, MAX_TOP, CoinGeckoProvider
from investinglab.domain import AssetClass, Currency
from investinglab.ports import (
    MarketCapRequest,
    MarketSnapshotRequest,
    ProviderDataError,
    UnsupportedRequestError,
)
from support.cassettes import Cassette, load_cassette

if TYPE_CHECKING:
    from collections.abc import Iterator

GLOBAL_USD = load_cassette("coingecko/global_usd")
GLOBAL_EUR = load_cassette("coingecko/global_eur")
TOP20 = load_cassette("coingecko/markets_usd_top20")


@pytest.fixture
def router() -> Iterator[respx.MockRouter]:
    with respx.mock(assert_all_called=False) as mock:
        yield mock


def _payload(cassette: Cassette) -> object:
    """The recorded answer, read here independently of the adapter."""
    exchange = cassette.exchanges[0]
    return exchange.payload if exchange.payload is not None else json.loads(exchange.text or "")


async def test_the_market_in_dollars_with_its_change_and_dominance(
    router: respx.MockRouter,
) -> None:
    GLOBAL_USD.play(router)

    async with CoinGeckoProvider(clock=GLOBAL_USD.clock) as provider:
        snapshot = await provider.fetch_market_snapshot(GLOBAL_USD.snapshot_request)

    data = _payload(GLOBAL_USD)["data"]  # type: ignore[index]
    assert snapshot.total_market_cap == pytest.approx(data["total_market_cap"]["usd"])
    assert snapshot.total_volume_24h == pytest.approx(data["total_volume"]["usd"])
    assert snapshot.market_cap_change_24h == pytest.approx(
        data["market_cap_change_percentage_24h_usd"] / 100
    )
    assert snapshot.share_of("BTC") == pytest.approx(data["market_cap_percentage"]["btc"] / 100)
    assert len(snapshot.dominance) == len(data["market_cap_percentage"])
    assert snapshot.as_of == datetime.fromtimestamp(data["updated_at"], tz=UTC)
    assert snapshot.assets == data["active_cryptocurrencies"]
    assert snapshot.source.dataset == "global"


async def test_in_another_currency_the_dollar_change_is_left_out(
    router: respx.MockRouter,
) -> None:
    GLOBAL_EUR.play(router)

    async with CoinGeckoProvider(clock=GLOBAL_EUR.clock) as provider:
        snapshot = await provider.fetch_market_snapshot(GLOBAL_EUR.snapshot_request)

    data = _payload(GLOBAL_EUR)["data"]  # type: ignore[index]
    assert str(snapshot.currency) == "EUR"
    assert snapshot.total_market_cap == pytest.approx(data["total_market_cap"]["eur"])
    assert snapshot.market_cap_change_24h is None  # CoinGecko gives it in dollars only


async def test_the_largest_assets_by_capitalisation(router: respx.MockRouter) -> None:
    TOP20.play(router)

    async with CoinGeckoProvider(clock=TOP20.clock) as provider:
        ranking = await provider.fetch_market_caps(TOP20.ranking_request)

    coins = _payload(TOP20)
    assert isinstance(coins, list)
    assert len(ranking) == len(coins) == 20
    first = ranking.assets[0]
    assert (first.rank, first.id, first.symbol) == (1, coins[0]["id"], coins[0]["symbol"].upper())
    assert first.price == pytest.approx(coins[0]["current_price"])
    assert first.market_cap == pytest.approx(coins[0]["market_cap"])
    assert [asset.rank for asset in ranking.assets] == list(range(1, 21))
    latest = max(datetime.fromisoformat(coin["last_updated"]) for coin in coins)
    assert ranking.as_of == latest
    assert ranking.source.dataset == "coins/markets"


async def test_a_currency_coingecko_does_not_value_the_market_in_is_refused(
    router: respx.MockRouter,
) -> None:
    cassette = load_cassette("coingecko/global_unknown_currency")
    cassette.play(router)

    async with CoinGeckoProvider(clock=cassette.clock) as provider:
        with pytest.raises(UnsupportedRequestError, match="no total in MAD"):
            await provider.fetch_market_snapshot(cassette.snapshot_request)


async def test_a_currency_coingecko_does_not_know_is_refused_with_its_reason(
    router: respx.MockRouter,
) -> None:
    cassette = load_cassette("coingecko/markets_unknown_currency")
    cassette.play(router)

    async with CoinGeckoProvider(clock=cassette.clock) as provider:
        with pytest.raises(UnsupportedRequestError, match="invalid vs_currency"):
            await provider.fetch_market_caps(cassette.ranking_request)


async def test_an_unknown_capitalisation_is_missing_not_zero(router: respx.MockRouter) -> None:
    coins = _payload(TOP20)
    assert isinstance(coins, list)
    altered = [dict(coin) for coin in coins]
    altered[-1]["market_cap"] = 0  # what CoinGecko reports when it does not know it
    exchange = TOP20.exchanges[0]
    router.get(exchange.url, params__eq=exchange.params).mock(
        return_value=httpx.Response(200, json=altered)
    )

    async with CoinGeckoProvider(clock=TOP20.clock) as provider:
        ranking = await provider.fetch_market_caps(TOP20.ranking_request)

    assert ranking.assets[-1].market_cap is None


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ({"data": {"total_market_cap": {"usd": 1.0}}}, "malformed /global"),
        ({"data": {"total_market_cap": {"usd": -5.0}, "updated_at": 1}}, "positive"),
    ],
    ids=["no-time", "negative-total"],
)
async def test_a_malformed_snapshot_is_refused(
    router: respx.MockRouter, body: object, message: str
) -> None:
    router.get(GLOBAL_USD.exchanges[0].url).mock(return_value=httpx.Response(200, json=body))

    async with CoinGeckoProvider() as provider:
        with pytest.raises(ProviderDataError, match=message):
            await provider.fetch_market_snapshot(MarketSnapshotRequest())


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ({"not": "a list"}, "expected a list"),
        ([{"id": "x"}], "malformed /coins/markets"),
        ([], "at least one asset"),
    ],
    ids=["object", "fields", "empty"],
)
async def test_a_malformed_ranking_is_refused(
    router: respx.MockRouter, body: object, message: str
) -> None:
    router.get(TOP20.exchanges[0].url).mock(return_value=httpx.Response(200, json=body))

    async with CoinGeckoProvider() as provider:
        with pytest.raises(ProviderDataError, match=message):
            await provider.fetch_market_caps(MarketCapRequest(top=5))


async def test_what_coingecko_cannot_answer_is_refused_before_asking(
    router: respx.MockRouter,
) -> None:
    async with CoinGeckoProvider() as provider:
        with pytest.raises(UnsupportedRequestError, match="covers crypto"):
            await provider.fetch_market_snapshot(MarketSnapshotRequest(AssetClass.EQUITY))
        with pytest.raises(UnsupportedRequestError, match=f"up to {MAX_TOP}"):
            await provider.fetch_market_caps(MarketCapRequest(top=MAX_TOP + 1))
    assert not router.calls


async def test_a_demo_key_goes_in_a_header_and_raises_the_quota(
    router: respx.MockRouter,
) -> None:
    route = router.get(GLOBAL_USD.exchanges[0].url).mock(
        return_value=httpx.Response(200, json=_payload(GLOBAL_USD))
    )
    keyed = CoinGeckoProvider(api_key=SecretStr("demo-key-for-the-test"), clock=GLOBAL_USD.clock)
    plain = CoinGeckoProvider()

    async with keyed:
        await keyed.fetch_market_snapshot(MarketSnapshotRequest(currency=Currency("USD")))

    request = route.calls.last.request
    assert request.headers[KEY_HEADER] == "demo-key-for-the-test"
    assert "demo-key-for-the-test" not in str(request.url)  # never in the URL, nor in logs
    assert keyed.capabilities.rate_limits[0].max_calls > plain.capabilities.rate_limits[0].max_calls
    await plain.aclose()
