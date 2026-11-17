"""Contract of the providers of positioning in derivatives (ADR-0042).

Every venue publishes open interest and long/short ratios its own way; whatever it does,
its adapter must answer the swap, venue and frequency asked for, with fields it declares,
only periods that had ended and within the dates asked. A new venue is one more case in
:data:`CASES`: its adapter, a recording it answers and one of a swap it does not list.
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
from investinglab.adapters.providers.okx import OkxProvider
from investinglab.domain import PositioningField, PositioningSeries
from investinglab.ports import (
    Dataset,
    PositioningProvider,
    SymbolNotFoundError,
)
from support.cassettes import load_cassette

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable

SLUG = re.compile(r"[a-z][a-z0-9_]*")


@dataclass(frozen=True, slots=True)
class Case:
    """A positioning provider over its recordings."""

    name: str
    known: str
    """Cassette of a swap it serves."""
    unknown: str
    """Cassette of a swap it does not list."""
    build: Callable[[Callable[[], datetime]], PositioningProvider]


CASES = (
    Case(
        "binance",
        "binance/btc_usdt_positioning",
        "binance/positioning_not_found",
        lambda clock: BinanceProvider(clock=clock),
    ),
    Case(
        "okx",
        "okx/btc_usdt_positioning",
        "okx/positioning_not_found",
        lambda clock: OkxProvider(clock=clock),
    ),
)


@pytest.fixture(params=CASES, ids=[case.name for case in CASES])
async def provider(
    request: pytest.FixtureRequest,
) -> AsyncIterator[tuple[Case, PositioningProvider, datetime]]:
    case: Case = request.param
    known = load_cassette(case.known)
    with respx.mock(assert_all_called=False) as router:
        known.play(router)
        load_cassette(case.unknown).play(router)
        built = case.build(known.clock)
        yield case, built, known.recorded_at
        await built.aclose()  # type: ignore[attr-defined]


async def test_providers_implement_the_port(
    provider: tuple[Case, PositioningProvider, datetime],
) -> None:
    case, built, _ = provider

    request = load_cassette(case.known).positioning_request
    assert isinstance(built, PositioningProvider)
    assert built.name == case.name
    assert SLUG.fullmatch(built.name)
    assert Dataset.POSITIONING in built.capabilities.datasets
    assert built.capabilities.can_serve_positioning(request)
    assert built.capabilities.positioning_fields


async def test_the_answer_is_exactly_what_was_asked(
    provider: tuple[Case, PositioningProvider, datetime],
) -> None:
    case, built, recorded_at = provider
    request = load_cassette(case.known).positioning_request

    series = await built.fetch_positioning(request)

    assert isinstance(series, PositioningSeries)
    assert (series.symbol, series.frequency) == (request.symbol, request.frequency)
    assert series.venue == (request.venue or built.name)
    assert series.source.provider == built.name
    assert set(series.fields) <= built.capabilities.positioning_fields
    valued = PositioningField.OPEN_INTEREST_VALUE in series.fields
    assert (series.value_currency is not None) == valued
    assert request.start is not None
    assert request.end is not None
    assert series.start >= pd.Timestamp(request.start, tz="UTC")
    assert series.end < pd.Timestamp(request.end, tz="UTC") + pd.Timedelta(days=1)
    length = timedelta(minutes=request.frequency.minutes or 24 * 60)
    assert series.end + length <= pd.Timestamp(recorded_at)  # only periods that had ended


async def test_a_swap_the_venue_does_not_list_is_not_found(
    provider: tuple[Case, PositioningProvider, datetime],
) -> None:
    case, built, _ = provider

    with pytest.raises(SymbolNotFoundError):
        await built.fetch_positioning(load_cassette(case.unknown).positioning_request)
