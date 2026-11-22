"""Contract of the providers of reference data of a whole market (ADR-0045).

Whatever the source, its snapshot must be of the market and currency asked for, dated, and
its ranking ordered, no longer than asked and in that currency. A new source is one more
case in :data:`CASES`: its adapter and recordings of a snapshot and a ranking.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest
import respx

from investinglab.adapters.providers.coingecko import CoinGeckoProvider
from investinglab.domain import MarketCapRanking, MarketSnapshot
from investinglab.ports import Dataset, ReferenceDataProvider
from support.cassettes import load_cassette

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable
    from datetime import datetime

SLUG = re.compile(r"[a-z][a-z0-9_]*")


@dataclass(frozen=True, slots=True)
class Case:
    """A reference data provider over its recordings."""

    name: str
    snapshot: str
    ranking: str
    build: Callable[[Callable[[], datetime]], ReferenceDataProvider]


CASES = (
    Case(
        "coingecko",
        "coingecko/global_usd",
        "coingecko/markets_usd_top20",
        lambda clock: CoinGeckoProvider(clock=clock),
    ),
)


@pytest.fixture(params=CASES, ids=[case.name for case in CASES])
async def provider(
    request: pytest.FixtureRequest,
) -> AsyncIterator[tuple[Case, ReferenceDataProvider]]:
    case: Case = request.param
    snapshot = load_cassette(case.snapshot)
    with respx.mock(assert_all_called=False) as router:
        snapshot.play(router)
        load_cassette(case.ranking).play(router)
        built = case.build(snapshot.clock)
        yield case, built
        await built.aclose()  # type: ignore[attr-defined]


async def test_providers_implement_the_port(
    provider: tuple[Case, ReferenceDataProvider],
) -> None:
    case, built = provider

    request = load_cassette(case.snapshot).snapshot_request
    assert isinstance(built, ReferenceDataProvider)
    assert built.name == case.name
    assert SLUG.fullmatch(built.name)
    assert Dataset.REFERENCE in built.capabilities.datasets
    assert built.capabilities.can_serve_reference(request.asset_class)


async def test_the_snapshot_is_of_the_market_asked_for(
    provider: tuple[Case, ReferenceDataProvider],
) -> None:
    case, built = provider
    cassette = load_cassette(case.snapshot)
    request = cassette.snapshot_request

    snapshot = await built.fetch_market_snapshot(request)

    assert isinstance(snapshot, MarketSnapshot)
    assert (snapshot.asset_class, snapshot.currency) == (request.asset_class, request.currency)
    assert snapshot.source.provider == built.name
    assert snapshot.as_of <= cassette.recorded_at  # computed before it was read
    assert 0 <= snapshot.others <= 1


async def test_the_ranking_is_ordered_and_no_longer_than_asked(
    provider: tuple[Case, ReferenceDataProvider],
) -> None:
    case, built = provider
    request = load_cassette(case.ranking).ranking_request

    ranking = await built.fetch_market_caps(request)

    assert isinstance(ranking, MarketCapRanking)
    assert (ranking.asset_class, ranking.currency) == (request.asset_class, request.currency)
    assert 0 < len(ranking) <= request.top
    caps = [asset.market_cap for asset in ranking.assets if asset.market_cap is not None]
    assert caps == sorted(caps, reverse=True)  # largest first
