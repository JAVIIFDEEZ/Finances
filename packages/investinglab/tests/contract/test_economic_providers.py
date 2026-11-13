"""Contract that every economic-data provider honours (ADR-0009, ADR-0010).

Above all, an economic series is used point in time: no value may be dated before the day
it became public. Each provider runs against recorded real responses (cassettes); a new
provider joins the contract by adding one :class:`Case`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import pandas as pd
import pytest
import respx

from investinglab.adapters.providers.alternative_me import AlternativeMeProvider
from investinglab.adapters.providers.ecb import EcbProvider
from investinglab.domain import EconomicSeries
from investinglab.ports import (
    EconomicDataProvider,
    EconomicRequest,
    SymbolNotFoundError,
)
from support.cassettes import load_cassette

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable


def _ecb(router: respx.MockRouter) -> EconomicDataProvider:
    for name in ("ecb/estr_easter", "ecb/deposit_facility_cut"):
        load_cassette(name).play(router)
    return EcbProvider(clock=load_cassette("ecb/estr_easter").clock)


def _alternative_me(router: respx.MockRouter) -> EconomicDataProvider:
    known = load_cassette("alternative_me/fng_october")
    known.play(router)
    return AlternativeMeProvider(clock=known.clock)


@dataclass(frozen=True, slots=True)
class Case:
    """A provider wired to its recordings, requests it serves and one it cannot."""

    name: str
    build: Callable[[respx.MockRouter], EconomicDataProvider]
    requests: tuple[EconomicRequest, ...]
    unknown: EconomicRequest


CASES = (
    Case(
        "ecb",
        _ecb,
        (
            load_cassette("ecb/estr_easter").economic_request,
            load_cassette("ecb/deposit_facility_cut").economic_request,
        ),
        EconomicRequest("UNRATE"),
    ),
    Case(
        "alternative_me",
        _alternative_me,
        (load_cassette("alternative_me/fng_october").economic_request,),
        EconomicRequest("UNRATE"),
    ),
)


@pytest.fixture(params=CASES, ids=[case.name for case in CASES])
async def wired(
    request: pytest.FixtureRequest,
) -> AsyncIterator[tuple[Case, EconomicDataProvider]]:
    case: Case = request.param
    with respx.mock(assert_all_called=False) as router:
        provider = case.build(router)
        yield case, provider
        closer = getattr(provider, "aclose", None)
        if closer is not None:
            await closer()


async def test_providers_implement_the_port(wired: tuple[Case, EconomicDataProvider]) -> None:
    case, provider = wired

    assert isinstance(provider, EconomicDataProvider)
    assert provider.name == case.name
    for request in case.requests:
        assert provider.capabilities.can_serve_economic(request)


async def test_no_value_is_known_before_its_date(wired: tuple[Case, EconomicDataProvider]) -> None:
    case, provider = wired

    for request in case.requests:
        series = await provider.fetch_economic_series(request)

        assert isinstance(series, EconomicSeries)
        assert series.series_id == request.series_id
        assert series.source.provider == provider.name
        observations = series.observations
        assert (observations["published_at"] >= observations["observation_date"]).all()
        assert request.start is not None
        assert observations["observation_date"].min() >= pd.Timestamp(request.start)


async def test_unknown_series_are_not_found(wired: tuple[Case, EconomicDataProvider]) -> None:
    case, provider = wired

    with pytest.raises(SymbolNotFoundError):
        await provider.fetch_economic_series(case.unknown)
