"""Funding of Binance's swaps from its public dumps, replayed from real recorded responses.

The robustness tests alter a *copy* of a recorded file (a byte changed, a checksum for another
file, an archive with two members...) or of the listing, to prove each rule; the altered
values are never used as market data.
"""

from __future__ import annotations

import csv
import hashlib
import io
import zipfile
from datetime import date
from typing import TYPE_CHECKING

import httpx
import pandas as pd
import pytest
import respx

from investinglab.adapters.http import HttpClient
from investinglab.adapters.providers.binance import BinanceProvider, dumps
from investinglab.adapters.providers.binance.funding import contract
from investinglab.domain import AssetClass, RateKind
from investinglab.ports import (
    ProviderDataError,
    RatesRequest,
    SymbolNotFoundError,
    UnsupportedRequestError,
)
from support.cassettes import Cassette, Exchange, load_cassette

if TYPE_CHECKING:
    from collections.abc import Iterator

LINEAR = load_cassette("binance/btc_usdt_swap_funding")
INVERSE = load_cassette("binance/btc_usd_inverse_funding")


@pytest.fixture
def router() -> Iterator[respx.MockRouter]:
    with respx.mock(assert_all_called=False) as mock:
        yield mock


def _provider(cassette: Cassette) -> BinanceProvider:
    return BinanceProvider(clock=cassette.clock)


def _file(cassette: Cassette, ending: str) -> Exchange:
    return next(e for e in cassette.exchanges if e.url.endswith(ending))


def _recorded_rates(cassette: Cassette) -> pd.Series:
    """Every rate of the recorded monthly files, read here independently of the adapter."""
    rates: dict[pd.Timestamp, float] = {}
    for exchange in cassette.exchanges:
        if not exchange.url.endswith(".zip") or exchange.content is None:
            continue
        with zipfile.ZipFile(io.BytesIO(exchange.content)) as archive:
            text = archive.read(archive.namelist()[0]).decode("utf-8")
        for row in csv.DictReader(text.splitlines()):
            moment = pd.Timestamp(int(row["calc_time"]), unit="ms", tz="UTC").floor("s")
            rates[moment] = float(row["last_funding_rate"])
    return pd.Series(rates).sort_index()


def _zip(name: str, members: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for member, content in members.items():
            archive.writestr(member, content)
    del name
    return buffer.getvalue()


def _checksum(content: bytes, name: str) -> bytes:
    return f"{hashlib.sha256(content).hexdigest()}  {name}".encode("ascii")


# ── What is read ─────────────────────────────────────────────────────


async def test_the_funding_of_a_linear_swap_is_read_from_its_monthly_files(
    router: respx.MockRouter,
) -> None:
    LINEAR.play(router)

    async with _provider(LINEAR) as provider:
        rates = await provider.fetch_rates(LINEAR.rates_request)

    recorded = _recorded_rates(LINEAR)
    inside = recorded.loc["2026-09-01":"2026-10-10 23:59:59"]
    assert len(rates) == len(inside) == 120  # three payments a day, 1 September to 10 October
    assert list(rates.rates.index) == list(inside.index)
    assert rates.rates.to_numpy().tolist() == inside.to_numpy().tolist()
    assert (rates.symbol, rates.venue, rates.kind) == ("BTC/USDT:USDT", "binance", RateKind.FUNDING)
    assert rates.interval == pd.Timedelta(hours=8)
    assert rates.start == pd.Timestamp("2026-09-01", tz="UTC")  # stamped on the second
    assert rates.source.provider == "binance"
    assert rates.source.dataset == "futures/um/monthly/fundingRate"
    instrument = rates.instrument
    assert (instrument.asset_class, str(instrument.currency)) == (AssetClass.CRYPTO, "USDT")
    assert "BTCUSDT" in instrument.name


async def test_the_inverse_swap_settled_in_bitcoin_is_read_from_coin_m(
    router: respx.MockRouter,
) -> None:
    INVERSE.play(router)

    async with _provider(INVERSE) as provider:
        rates = await provider.fetch_rates(INVERSE.rates_request)

    assert len(rates) == 30
    assert str(rates.instrument.currency) == "USD"
    assert "BTCUSD_PERP" in rates.instrument.name
    assert rates.source.dataset == "futures/cm/monthly/fundingRate"
    assert all("/futures/cm/" in e.url for e in INVERSE.exchanges if "binance.vision/data" in e.url)


@pytest.mark.parametrize(
    ("name", "error", "message"),
    [
        ("binance/funding_not_published", ProviderDataError, r"once it ends \(last: 2026-10-31\)"),
        ("binance/inverse_funding_stopped", ProviderDataError, r"\(last: 2026-06\)"),
        ("binance/funding_not_found", SymbolNotFoundError, "publishes no funding of NOPEUSDT"),
    ],
)
async def test_what_is_not_published_is_told_apart_from_what_does_not_exist(
    router: respx.MockRouter, name: str, error: type[Exception], message: str
) -> None:
    cassette = load_cassette(name)
    cassette.play(router)

    async with _provider(cassette) as provider:
        with pytest.raises(error, match=message):
            await provider.fetch_rates(cassette.rates_request)


# ── Integrity ────────────────────────────────────────────────────────


async def test_a_file_that_does_not_match_its_checksum_is_refused(
    router: respx.MockRouter,
) -> None:
    september = _file(LINEAR, "2026-09.zip")
    assert september.content is not None
    damaged = bytearray(september.content)
    damaged[-1] ^= 0xFF  # one bit of the recorded archive flipped
    router.get(september.url).mock(return_value=httpx.Response(200, content=bytes(damaged)))
    LINEAR.play(router)

    async with _provider(LINEAR) as provider:
        with pytest.raises(ProviderDataError, match="does not match its published SHA-256"):
            await provider.fetch_rates(LINEAR.rates_request)


@pytest.mark.parametrize(
    ("archive", "checksum_name", "message"),
    [
        ("two members", None, "expected one CSV"),
        ("not a zip", None, "not a ZIP file"),
        ("right", "BTCUSDT-fundingRate-2026-08.zip", "the checksum file is for"),
    ],
)
async def test_an_archive_must_be_one_csv_with_its_own_checksum(
    router: respx.MockRouter, archive: str, checksum_name: str | None, message: str
) -> None:
    september = _file(LINEAR, "2026-09.zip")
    assert september.content is not None
    name = "BTCUSDT-fundingRate-2026-09.zip"
    with zipfile.ZipFile(io.BytesIO(september.content)) as opened:
        csv_bytes = opened.read(opened.namelist()[0])
    body = {
        "two members": _zip(name, {"a.csv": csv_bytes, "b.csv": csv_bytes}),
        "not a zip": b"not an archive",
        "right": september.content,
    }[archive]
    router.get(september.url).mock(return_value=httpx.Response(200, content=body))
    router.get(f"{september.url}.CHECKSUM").mock(
        return_value=httpx.Response(200, content=_checksum(body, checksum_name or name))
    )
    LINEAR.play(router)

    async with _provider(LINEAR) as provider:
        with pytest.raises(ProviderDataError, match=message):
            await provider.fetch_rates(LINEAR.rates_request)


async def test_unexpected_columns_and_rows_are_refused(router: respx.MockRouter) -> None:
    september = _file(LINEAR, "2026-09.zip")
    name = "BTCUSDT-fundingRate-2026-09.csv"
    for text, message in (
        ("time,rate\n1,0.1\n", "unexpected columns"),
        ("calc_time,funding_interval_hours,last_funding_rate\nsoon,8,0.1\n", "unreadable row"),
    ):
        body = _zip(name, {name: text.encode("utf-8")})
        router.routes.clear()
        router.get(september.url).mock(return_value=httpx.Response(200, content=body))
        router.get(f"{september.url}.CHECKSUM").mock(
            return_value=httpx.Response(200, content=_checksum(body, f"{name[:-4]}.zip"))
        )
        LINEAR.play(router)
        async with _provider(LINEAR) as provider:
            with pytest.raises(ProviderDataError, match=message):
                await provider.fetch_rates(LINEAR.rates_request)


@pytest.mark.parametrize(
    ("document", "message"),
    [
        ('<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "b">]><x>&a;</x>', "declares a DTD"),
        ("<ListBucketResult", "unreadable dump listing"),
        ("<Error><Code>AccessDenied</Code></Error>", "unexpected dump listing"),
    ],
)
async def test_a_listing_that_is_not_a_plain_bucket_listing_is_refused(
    router: respx.MockRouter, document: str, message: str
) -> None:
    listing = LINEAR.exchanges[0]
    router.get(listing.url).mock(return_value=httpx.Response(200, text=document))

    async with _provider(LINEAR) as provider:
        with pytest.raises(ProviderDataError, match=message):
            await provider.fetch_rates(LINEAR.rates_request)


async def test_the_work_of_one_request_is_bounded() -> None:
    client = HttpClient("binance", base_url=dumps.DUMPS_URL)
    keys = [f"k{n}.zip" for n in range(dumps.MAX_FILES + 1)]
    async with client:
        with pytest.raises(UnsupportedRequestError, match="more than"):
            await dumps.read_all("binance", client, keys)


# ── What is asked ────────────────────────────────────────────────────


def test_swaps_map_to_their_futures_market_and_contract() -> None:
    assert contract("binance", "BTC/USDT:USDT") == ("um", "BTCUSDT")
    assert contract("binance", "ETH/USDC:USDC") == ("um", "ETHUSDC")
    assert contract("binance", "BTC/USD:BTC") == ("cm", "BTCUSD_PERP")
    for symbol in ("BTC/USDT", "btc/usdt:usdt", "BTC/USDT:BTC", "BTC/USD:USD", "BTC/EUR:EUR"):
        with pytest.raises(UnsupportedRequestError):
            contract("binance", symbol)


@pytest.mark.parametrize(
    ("request_", "message"),
    [
        (RatesRequest("BTC/USDT:USDT", RateKind.BORROW), "serves funding, not borrow"),
        (RatesRequest("BTC/USDT:USDT", RateKind.FUNDING, venue="okx"), "not okx's"),
        (RatesRequest("BTC/USDT", RateKind.FUNDING), "not a perpetual swap"),
    ],
)
async def test_what_binance_cannot_answer_is_refused_before_asking(
    router: respx.MockRouter, request_: RatesRequest, message: str
) -> None:
    async with BinanceProvider() as provider:
        with pytest.raises(UnsupportedRequestError, match=message):
            await provider.fetch_rates(request_)
    assert not router.calls


async def test_only_the_months_of_the_range_are_listed_and_read(router: respx.MockRouter) -> None:
    routes = LINEAR.play(router)

    async with _provider(LINEAR) as provider:
        await provider.fetch_rates(LINEAR.rates_request)

    listing = LINEAR.exchanges[0]
    assert listing.params["marker"].endswith("BTCUSDT-fundingRate-2026-08")  # the month before
    files = {e.url.rsplit("/", 1)[-1] for e in LINEAR.exchanges[1:]}
    assert files == {
        f"BTCUSDT-fundingRate-2026-{month}.zip{suffix}"
        for month in ("08", "09", "10")
        for suffix in ("", ".CHECKSUM")
    }
    assert all(route.call_count == 1 for route in routes)
    assert LINEAR.rates_request.end == date(2026, 10, 10)
