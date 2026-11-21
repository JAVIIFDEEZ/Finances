"""Contract of the providers of order-book depth (ADR-0044).

Every venue publishes its book its own way; whatever it does, its adapter must answer the
symbol, venue and frequency asked for, with bands it declares, only periods that had ended
and within the dates asked. A new venue is one more case in :data:`CASES`: its adapter, a
recording it answers and one of a symbol it does not list.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

import pandas as pd
import pytest
import respx

from investinglab.adapters.providers.binance import BinanceProvider
from investinglab.domain import BookDepthSeries, BookSide, DepthMeasure
from investinglab.ports import BookDepthProvider, Dataset, SymbolNotFoundError
from support.cassettes import load_cassette

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable

SLUG = re.compile(r"[a-z][a-z0-9_]*")


@dataclass(frozen=True, slots=True)
class Case:
    """A book depth provider over its recordings."""

    name: str
    known: str
    """Cassette of a symbol it serves."""
    unknown: str
    """Cassette of a symbol it does not list."""
    build: Callable[[Callable[[], datetime]], BookDepthProvider]


CASES = (
    Case(
        "binance",
        "binance/btc_usdt_book_depth",
        "binance/book_depth_not_found",
        lambda clock: BinanceProvider(clock=clock),
    ),
)


@pytest.fixture(params=CASES, ids=[case.name for case in CASES])
async def provider(
    request: pytest.FixtureRequest,
) -> AsyncIterator[tuple[Case, BookDepthProvider, datetime]]:
    case: Case = request.param
    known = load_cassette(case.known)
    with respx.mock(assert_all_called=False) as router:
        known.play(router)
        load_cassette(case.unknown).play(router)
        built = case.build(known.clock)
        yield case, built, known.recorded_at
        await built.aclose()  # type: ignore[attr-defined]


async def test_providers_implement_the_port(
    provider: tuple[Case, BookDepthProvider, datetime],
) -> None:
    case, built, _ = provider

    request = load_cassette(case.known).book_depth_request
    assert isinstance(built, BookDepthProvider)
    assert built.name == case.name
    assert SLUG.fullmatch(built.name)
    assert Dataset.BOOK_DEPTH in built.capabilities.datasets
    assert built.capabilities.can_serve_book_depth(request)
    assert built.capabilities.book_bands


async def test_the_answer_is_exactly_what_was_asked(
    provider: tuple[Case, BookDepthProvider, datetime],
) -> None:
    case, built, recorded_at = provider
    request = load_cassette(case.known).book_depth_request

    depth = await built.fetch_book_depth(request)

    assert isinstance(depth, BookDepthSeries)
    assert (depth.symbol, depth.frequency) == (request.symbol, request.frequency)
    assert depth.venue == (request.venue or built.name)
    assert depth.source.provider == built.name
    assert set(depth.bands) <= built.capabilities.book_bands
    noted = DepthMeasure.NOTIONAL in depth.measures
    assert (depth.notional_currency is not None) == noted
    for band in depth.bands:  # both sides of every band, cumulative
        assert depth.depth(BookSide.BID, band).notna().any()
        assert depth.depth(BookSide.ASK, band).notna().any()
    assert request.start is not None
    assert request.end is not None
    assert depth.start >= pd.Timestamp(request.start, tz="UTC")
    assert depth.end < pd.Timestamp(request.end, tz="UTC") + pd.Timedelta(days=1)
    length = timedelta(minutes=request.frequency.minutes or 24 * 60)
    assert depth.end + length <= pd.Timestamp(recorded_at)  # only periods that had ended


async def test_a_symbol_the_venue_does_not_list_is_not_found(
    provider: tuple[Case, BookDepthProvider, datetime],
) -> None:
    case, built, _ = provider

    with pytest.raises(SymbolNotFoundError):
        await built.fetch_book_depth(load_cassette(case.unknown).book_depth_request)
