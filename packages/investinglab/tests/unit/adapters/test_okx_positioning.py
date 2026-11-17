"""Positioning of OKX's swaps from its trading statistics, replayed from real recordings.

The robustness tests alter a *copy* of a recorded payload, or ask the recorded answers for
an earlier start, to prove each rule; the altered values are never used as market data.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from typing import TYPE_CHECKING, Any

import pandas as pd
import pytest
import respx

from investinglab.adapters.providers.okx import OkxProvider
from investinglab.adapters.providers.okx.positioning import ENDPOINTS
from investinglab.domain import Frequency, PositioningField
from investinglab.ports import (
    PositioningRequest,
    ProviderDataError,
    UnsupportedRequestError,
)
from support.cassettes import Cassette, load_cassette

if TYPE_CHECKING:
    from collections.abc import Iterator

HOURLY = load_cassette("okx/btc_usdt_positioning")
DAILY = load_cassette("okx/btc_usdt_positioning_1d")


@pytest.fixture
def router() -> Iterator[respx.MockRouter]:
    with respx.mock(assert_all_called=False) as mock:
        yield mock


def _rows(cassette: Cassette, path: str) -> list[list[str]]:
    exchange = next(e for e in cassette.exchanges if e.url.endswith(path))
    rows: list[list[str]] = exchange.payload["data"]
    return rows


async def test_hourly_open_interest_and_ratios_are_read_as_published(
    router: respx.MockRouter,
) -> None:
    HOURLY.play(router)

    async with OkxProvider(clock=HOURLY.clock) as provider:
        series = await provider.fetch_positioning(HOURLY.positioning_request)

    assert series.fields == (
        PositioningField.OPEN_INTEREST,
        PositioningField.OPEN_INTEREST_VALUE,
        PositioningField.LONG_SHORT_ACCOUNTS,
        PositioningField.TOP_LONG_SHORT_ACCOUNTS,
        PositioningField.TOP_LONG_SHORT_POSITIONS,
    )
    assert str(series.value_currency) == "USD"  # oiUsd, whatever the quote currency
    interest = {
        pd.Timestamp(int(row[0]), unit="ms", tz="UTC"): (float(row[2]), float(row[3]))
        for row in _rows(HOURLY, "open-interest-history")
    }
    for hour, (coins, dollars) in interest.items():
        if hour in series.snapshots.index:
            assert series.column(PositioningField.OPEN_INTEREST)[hour] == coins
            assert series.column(PositioningField.OPEN_INTEREST_VALUE)[hour] == dollars
    accounts = {int(row[0]): float(row[1]) for row in _rows(HOURLY, "ratio-contract")}
    last = series.column(PositioningField.LONG_SHORT_ACCOUNTS).index[-1]
    assert (
        series.column(PositioningField.LONG_SHORT_ACCOUNTS).iloc[-1]
        == accounts[int(last.timestamp() * 1000)]
    )


async def test_daily_rows_keep_okx_days_which_start_at_four_pm_utc(
    router: respx.MockRouter,
) -> None:
    DAILY.play(router)

    async with OkxProvider(clock=DAILY.clock) as provider:
        series = await provider.fetch_positioning(DAILY.positioning_request)

    assert series.frequency is Frequency.DAY_1
    assert {stamp.hour for stamp in series.snapshots.index} == {16}


async def test_a_range_older_than_okx_keeps_is_refused_for_the_next_venue(
    router: respx.MockRouter,
) -> None:
    HOURLY.play(router, exact=False)  # the same answers, asked from earlier
    earlier = replace(HOURLY.positioning_request, start=date(2026, 11, 1))

    async with OkxProvider(clock=HOURLY.clock) as provider:
        with pytest.raises(ProviderDataError, match="after the 2026-11-01 asked for"):
            await provider.fetch_positioning(earlier)


async def test_nothing_kept_in_the_range_is_said(router: respx.MockRouter) -> None:
    empty: dict[str, Any] = {"code": "0", "msg": "", "data": []}
    HOURLY.play(router, payload=empty)

    async with OkxProvider(clock=HOURLY.clock) as provider:
        with pytest.raises(ProviderDataError, match="OKX keeps no 1H positioning"):
            await provider.fetch_positioning(HOURLY.positioning_request)


async def test_rows_that_are_not_numbers_are_refused(router: respx.MockRouter) -> None:
    broken: dict[str, Any] = {"code": "0", "msg": "", "data": [["1794931200000", "x", "y", "z"]]}
    HOURLY.play(router, payload=broken)

    async with OkxProvider(clock=HOURLY.clock) as provider:
        with pytest.raises(ProviderDataError, match="is not a number"):
            await provider.fetch_positioning(HOURLY.positioning_request)


async def test_what_okx_cannot_answer_is_refused_before_asking(router: respx.MockRouter) -> None:
    async with OkxProvider(clock=HOURLY.clock) as provider:
        with pytest.raises(UnsupportedRequestError, match="not binance's"):
            await provider.fetch_positioning(PositioningRequest("BTC/USDT:USDT", venue="binance"))
        with pytest.raises(UnsupportedRequestError, match="not read at 1m"):
            await provider.fetch_positioning(
                PositioningRequest("BTC/USDT:USDT", frequency=Frequency.MINUTE_1)
            )
    assert not router.calls


def test_the_open_interest_is_read_first() -> None:
    assert ENDPOINTS[0].path.endswith("open-interest-history")
