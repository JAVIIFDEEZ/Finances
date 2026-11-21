"""Positioning of Binance's swaps from its daily metrics dumps, replayed from real recordings.

The robustness tests alter a *copy* of a recorded file, to prove each rule; the altered
values are never used as market data.
"""

from __future__ import annotations

import csv
import hashlib
import io
import zipfile
from typing import TYPE_CHECKING

import httpx
import pandas as pd
import pytest
import respx

from investinglab.adapters.providers.binance import BinanceProvider, dumps
from investinglab.adapters.storage import PublishedFileCache
from investinglab.domain import Frequency, PositioningField
from investinglab.ports import (
    PositioningRequest,
    ProviderDataError,
    UnsupportedRequestError,
)
from support.cassettes import Cassette, Exchange, load_cassette

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

LINEAR = load_cassette("binance/btc_usdt_positioning")
INVERSE = load_cassette("binance/btc_usd_inverse_positioning")


@pytest.fixture
def router() -> Iterator[respx.MockRouter]:
    with respx.mock(assert_all_called=False) as mock:
        yield mock


def _recorded(cassette: Cassette) -> pd.DataFrame:
    """Every 5-minute row of the recorded files, read here independently of the adapter."""
    rows: list[dict[str, str]] = []
    for exchange in cassette.exchanges:
        if exchange.url.endswith(".zip") and exchange.content is not None:
            with zipfile.ZipFile(io.BytesIO(exchange.content)) as archive:
                text = archive.read(archive.namelist()[0]).decode("utf-8")
            rows.extend(csv.DictReader(text.splitlines()))
    frame = pd.DataFrame(rows)
    frame.index = pd.to_datetime(frame.pop("create_time"), utc=True)
    return frame.sort_index()


def _file(cassette: Cassette, ending: str) -> Exchange:
    return next(e for e in cassette.exchanges if e.url.endswith(ending))


async def test_a_linear_swap_reads_every_field_at_the_last_snapshot_of_each_hour(
    router: respx.MockRouter,
) -> None:
    LINEAR.play(router)

    async with BinanceProvider(clock=LINEAR.clock) as provider:
        series = await provider.fetch_positioning(LINEAR.positioning_request)

    assert series.fields == tuple(PositioningField)
    assert (series.frequency, len(series)) == (Frequency.HOUR_1, 48)  # two days of hours
    assert str(series.value_currency) == "USDT"
    raw = _recorded(LINEAR)
    for hour in series.snapshots.index:
        last = raw.loc[hour : hour + pd.Timedelta(minutes=59)].iloc[-1]
        row = series.snapshots.loc[hour]
        assert row[PositioningField.OPEN_INTEREST.value] == float(last["sum_open_interest"])
        assert row[PositioningField.OPEN_INTEREST_VALUE.value] == float(
            last["sum_open_interest_value"]
        )
        assert row[PositioningField.LONG_SHORT_ACCOUNTS.value] == float(
            last["count_long_short_ratio"]
        )
        assert row[PositioningField.TOP_LONG_SHORT_POSITIONS.value] == float(
            last["sum_toptrader_long_short_ratio"]
        )
    assert series.source.dataset == "futures/um/daily/metrics"


async def test_an_inverse_swap_reads_its_open_interest_in_the_base_asset(
    router: respx.MockRouter,
) -> None:
    INVERSE.play(router)

    async with BinanceProvider(clock=INVERSE.clock) as provider:
        series = await provider.fetch_positioning(INVERSE.positioning_request)

    raw = _recorded(INVERSE)
    assert PositioningField.OPEN_INTEREST_VALUE not in series.fields  # its size is not known
    assert PositioningField.TAKER_BUY_SELL not in series.fields  # an empty column there
    assert series.value_currency is None
    last = raw.iloc[-1]
    assert series.column(PositioningField.OPEN_INTEREST).iloc[-1] == float(
        last["sum_open_interest_value"]  # bitcoins, not contracts
    )


async def test_today_is_published_tomorrow(router: respx.MockRouter) -> None:
    cassette = load_cassette("binance/positioning_not_published_live")
    cassette.play(router)

    async with BinanceProvider(clock=cassette.clock) as provider:
        with pytest.raises(ProviderDataError, match="publishes each day the next morning"):
            await provider.fetch_positioning(cassette.positioning_request)


async def test_a_start_is_needed_and_only_its_own_venue_is_served(router: respx.MockRouter) -> None:
    async with BinanceProvider(clock=LINEAR.clock) as provider:
        with pytest.raises(UnsupportedRequestError, match="give a start date"):
            await provider.fetch_positioning(PositioningRequest("BTC/USDT:USDT"))
        with pytest.raises(UnsupportedRequestError, match="not okx's"):
            await provider.fetch_positioning(PositioningRequest("BTC/USDT:USDT", venue="okx"))
    assert not router.calls


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("time,open_interest\n2026-11-14 00:00:00,1\n", "unexpected columns"),
        (
            "create_time,sum_open_interest\n2026-11-14 00:00:00,many\n",
            "unreadable sum_open_interest",
        ),
        ("create_time,sum_open_interest\nsoon,1\n", "unreadable snapshot times"),
    ],
)
async def test_a_file_that_does_not_read_as_metrics_is_refused(
    router: respx.MockRouter, text: str, message: str
) -> None:
    first = _file(LINEAR, "2026-11-14.zip")
    name = "BTCUSDT-metrics-2026-11-14"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(f"{name}.csv", text)
    body = buffer.getvalue()
    checksum = f"{hashlib.sha256(body).hexdigest()}  {name}.zip".encode("ascii")
    router.get(first.url).mock(return_value=httpx.Response(200, content=body))
    router.get(f"{first.url}.CHECKSUM").mock(return_value=httpx.Response(200, content=checksum))
    LINEAR.play(router)

    async with BinanceProvider(clock=LINEAR.clock) as provider:
        with pytest.raises(ProviderDataError, match=message):
            await provider.fetch_positioning(LINEAR.positioning_request)


async def test_the_days_already_verified_are_read_from_disk(
    router: respx.MockRouter, tmp_path: Path
) -> None:
    routes = LINEAR.play(router)
    cache = PublishedFileCache(tmp_path)
    files = [
        route
        for route, exchange in zip(routes, LINEAR.exchanges, strict=True)
        if exchange.url.startswith(dumps.DUMPS_URL)
    ]

    async with BinanceProvider(clock=LINEAR.clock, dump_cache=cache) as provider:
        first = await provider.fetch_positioning(LINEAR.positioning_request)
    async with BinanceProvider(clock=LINEAR.clock, dump_cache=cache) as provider:
        again = await provider.fetch_positioning(LINEAR.positioning_request)

    assert files
    assert all(route.call_count == 1 for route in files)  # each day downloaded once
    assert again.snapshots.equals(first.snapshots)
