"""Book depth of Binance's swaps from its daily dumps, replayed from real recordings.

The robustness tests alter a *copy* of a recorded file, to prove each rule; the altered
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

from investinglab.adapters.providers.binance import BinanceProvider, book_depth, dumps
from investinglab.adapters.storage import PublishedFileCache
from investinglab.domain import BookSide, DepthMeasure, Frequency
from investinglab.ports import (
    BookDepthRequest,
    ProviderDataError,
    UnsupportedRequestError,
)
from support.cassettes import Cassette, Exchange, load_cassette

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

LINEAR = load_cassette("binance/btc_usdt_book_depth")
HEADER = "timestamp,percentage,depth,notional\n"
INVERSE = load_cassette("binance/btc_usd_inverse_book_depth")


@pytest.fixture
def router() -> Iterator[respx.MockRouter]:
    with respx.mock(assert_all_called=False) as mock:
        yield mock


def _file(cassette: Cassette) -> Exchange:
    return next(e for e in cassette.exchanges if e.url.endswith(".zip"))


def _recorded(cassette: Cassette) -> list[dict[str, str]]:
    """Every row of the recorded file, read here independently of the adapter."""
    archive = _file(cassette).content
    assert archive is not None
    with zipfile.ZipFile(io.BytesIO(archive)) as opened:
        text = opened.read(opened.namelist()[0]).decode("utf-8")
    return list(csv.DictReader(text.splitlines()))


def _replace(router: respx.MockRouter, cassette: Cassette, csv_text: str) -> None:
    """Serve ``csv_text`` as the recorded day, zipped, with a checksum that matches it."""
    exchange = _file(cassette)
    name = exchange.url.rsplit("/", 1)[-1]
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(name.removesuffix(".zip") + ".csv", csv_text)
    body = buffer.getvalue()
    checksum = f"{hashlib.sha256(body).hexdigest()}  {name}".encode("ascii")
    router.get(exchange.url).mock(return_value=httpx.Response(200, content=body))
    router.get(f"{exchange.url}.CHECKSUM").mock(return_value=httpx.Response(200, content=checksum))
    cassette.play(router)


async def test_a_linear_swap_keeps_the_last_snapshot_of_each_hour(
    router: respx.MockRouter,
) -> None:
    LINEAR.play(router)

    async with BinanceProvider(clock=LINEAR.clock) as provider:
        depth = await provider.fetch_book_depth(LINEAR.book_depth_request)

    rows = _recorded(LINEAR)
    last_before_one = max(r["timestamp"] for r in rows if r["timestamp"] < "2026-11-20 01:00:00")
    wanted = {float(r["percentage"]): r for r in rows if r["timestamp"] == last_before_one}
    assert len(depth) == 24
    assert depth.bands == (0.2, 1.0, 2.0, 3.0, 4.0, 5.0)
    assert depth.measures == (DepthMeasure.QUANTITY, DepthMeasure.NOTIONAL)
    assert str(depth.notional_currency) == "USDT"
    assert depth.depth(BookSide.BID, 2.0).iloc[0] == pytest.approx(float(wanted[-2.0]["depth"]))
    assert depth.depth(BookSide.ASK, 5.0, DepthMeasure.NOTIONAL).iloc[0] == pytest.approx(
        float(wanted[5.0]["notional"])
    )
    assert depth.start == pd.Timestamp("2026-11-20", tz="UTC")
    assert depth.source.dataset == "futures/um/daily/bookDepth"


async def test_an_inverse_swap_gives_its_depth_in_the_base_asset(
    router: respx.MockRouter,
) -> None:
    INVERSE.play(router)

    async with BinanceProvider(clock=INVERSE.clock) as provider:
        depth = await provider.fetch_book_depth(INVERSE.book_depth_request)

    rows = _recorded(INVERSE)
    last_before_one = max(r["timestamp"] for r in rows if r["timestamp"] < "2026-11-20 01:00:00")
    first = {float(r["percentage"]): r for r in rows if r["timestamp"] == last_before_one}
    assert depth.measures == (DepthMeasure.QUANTITY,)  # no value in dollars
    assert depth.notional_currency is None
    assert depth.bands == (1.0, 2.0, 3.0, 4.0, 5.0)
    assert all("/futures/cm/" in e.url for e in INVERSE.exchanges if "data/futures" in e.url)
    # Binance's "notional" of a COIN-M file is the quantity in bitcoins; "depth", contracts.
    assert depth.depth(BookSide.BID, 5.0).iloc[0] == pytest.approx(float(first[-5.0]["notional"]))


async def test_today_is_published_tomorrow(router: respx.MockRouter) -> None:
    live = load_cassette("binance/book_depth_not_published_live")
    live.play(router)

    async with BinanceProvider(clock=live.clock) as provider:
        with pytest.raises(ProviderDataError, match="publishes each day the next morning"):
            await provider.fetch_book_depth(live.book_depth_request)


@pytest.mark.parametrize(
    ("request_", "message"),
    [
        (BookDepthRequest("BTC/USDT:USDT"), "give a start date"),
        (BookDepthRequest("BTC/USDT:USDT", venue="okx", start=date(2026, 11, 1)), "not okx's"),
        (
            BookDepthRequest("BTC/USDT:USDT", start=date(2026, 1, 1), end=date(2026, 6, 1)),
            f"more than {book_depth.MAX_DAYS} days",
        ),
        (BookDepthRequest("BTC/USDT", start=date(2026, 11, 1)), "not a perpetual swap"),
    ],
)
async def test_what_binance_cannot_answer_is_refused_before_asking(
    router: respx.MockRouter, request_: BookDepthRequest, message: str
) -> None:
    async with BinanceProvider() as provider:
        with pytest.raises(UnsupportedRequestError, match=message):
            await provider.fetch_book_depth(request_)
    assert not router.calls


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("time,percentage,depth,notional\n", "unexpected columns"),
        (HEADER + "soon,-1.00,1,1\n", "unreadable row"),
        (HEADER + "2026-11-20 00:00:01,0,1,1\n", "without a distance"),
        (
            HEADER + "2026-11-20 00:00:01,-1.00,1,1\n2026-11-20 00:00:01,-1.00,2,2\n",
            "given twice",
        ),
        (
            HEADER + "2026-11-20 00:00:01,-1.00,5,5\n2026-11-20 00:00:01,-2.00,4,4\n",
            "shrinks in a wider band",
        ),
    ],
    ids=["columns", "row", "zero-band", "twice", "not-cumulative"],
)
async def test_a_file_that_does_not_read_as_book_depth_is_refused(
    router: respx.MockRouter, text: str, message: str
) -> None:
    _replace(router, LINEAR, text)

    async with BinanceProvider(clock=LINEAR.clock) as provider:
        with pytest.raises(ProviderDataError, match=message):
            await provider.fetch_book_depth(LINEAR.book_depth_request)


async def test_a_coarser_frequency_and_the_cache_are_honoured(
    router: respx.MockRouter, tmp_path: Path
) -> None:
    routes = LINEAR.play(router)
    cache = PublishedFileCache(tmp_path)
    four = BookDepthRequest(
        "BTC/USDT:USDT",
        start=date(2026, 11, 20),
        end=date(2026, 11, 20),
        frequency=Frequency.HOUR_4,
    )

    async with BinanceProvider(clock=LINEAR.clock, dump_cache=cache) as provider:
        coarse = await provider.fetch_book_depth(four)
        hourly = await provider.fetch_book_depth(LINEAR.book_depth_request)

    assert len(coarse) == 6
    assert coarse.depth("bid", 1.0).iloc[0] == hourly.depth("bid", 1.0).iloc[3]  # 03:00 hour
    files = [
        route
        for route, exchange in zip(routes, LINEAR.exchanges, strict=True)
        if exchange.url.startswith(dumps.DUMPS_URL)
    ]
    assert all(route.call_count == 1 for route in files)  # the second read came from disk
