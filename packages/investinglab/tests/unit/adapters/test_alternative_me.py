"""alternative.me adapter, replayed from real recorded responses (``support.cassettes``).

The robustness tests alter a *copy* of a recorded payload (a reading out of scale, an error
report...) to prove each rule; the altered values are never used as market data.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Any

import pandas as pd
import pytest
import respx

from investinglab.adapters.providers.alternative_me import AlternativeMeProvider
from investinglab.domain import Frequency
from investinglab.ports import (
    Dataset,
    EconomicDataProvider,
    EconomicRequest,
    ProviderDataError,
    SymbolNotFoundError,
    VintageMode,
)
from support.cassettes import Cassette, load_cassette

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture
def router() -> Iterator[respx.MockRouter]:
    with respx.mock(assert_all_called=False) as mock:
        yield mock


@pytest.fixture
def cassette() -> Cassette:
    return load_cassette("alternative_me/fng_october")


def _provider(cassette: Cassette) -> AlternativeMeProvider:
    return AlternativeMeProvider(clock=cassette.clock)


async def test_one_reading_a_day_known_the_day_it_describes(
    router: respx.MockRouter, cassette: Cassette
) -> None:
    cassette.play(router)

    async with _provider(cassette) as provider:
        series = await provider.fetch_economic_series(cassette.economic_request)

    observations = series.observations
    assert (series.series_id, series.frequency) == ("FNG", Frequency.DAY_1)
    assert len(observations) == 20
    assert observations["observation_date"].iloc[0] == pd.Timestamp("2026-10-01")
    assert observations["observation_date"].iloc[-1] == pd.Timestamp("2026-10-20")
    assert (observations["published_at"] == observations["observation_date"]).all()
    assert observations["value"].between(0, 100).all()
    recorded = {
        pd.Timestamp(int(r["timestamp"]), unit="s").normalize(): float(r["value"])
        for r in cassette.payload()["data"]
    }
    assert observations["value"].tolist() == [
        recorded[day] for day in observations["observation_date"]
    ]
    assert (series.source.provider, series.source.dataset) == ("alternative_me", "fng")
    assert "Fear & Greed" in series.title


async def test_only_the_days_since_the_start_are_asked_for(
    router: respx.MockRouter, cassette: Cassette
) -> None:
    (route,) = cassette.play(router)

    async with _provider(cassette) as provider:
        await provider.fetch_economic_series(cassette.economic_request)

    params = route.calls.last.request.url.params
    days = (cassette.recorded_at.date() - date(2026, 10, 1)).days + 1
    assert params["limit"] == str(days)
    assert params["format"] == "json"


async def test_without_a_start_the_whole_history_is_asked_for(
    router: respx.MockRouter, cassette: Cassette
) -> None:
    (route,) = cassette.play(router, exact=False)

    async with _provider(cassette) as provider:
        series = await provider.fetch_economic_series(
            EconomicRequest("FNG", mode=VintageMode.LATEST)
        )

    assert route.calls.last.request.url.params["limit"] == "0"
    assert series.observations["observation_date"].max() == pd.Timestamp(
        cassette.recorded_at.date()
    )


async def test_other_series_are_not_asked_for(router: respx.MockRouter) -> None:
    async with AlternativeMeProvider() as provider:
        with pytest.raises(SymbolNotFoundError, match="only publishes FNG"):
            await provider.fetch_economic_series(EconomicRequest("UNRATE"))

    assert not router.calls


async def test_a_range_without_readings_is_a_data_error(
    router: respx.MockRouter, cassette: Cassette
) -> None:
    cassette.play(router, exact=False)
    later = replace(cassette.economic_request, start=date(2030, 1, 1), end=date(2030, 1, 2))

    async with AlternativeMeProvider(clock=lambda: datetime(2030, 1, 3, tzinfo=UTC)) as provider:
        with pytest.raises(ProviderDataError, match="no Fear & Greed value"):
            await provider.fetch_economic_series(later)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda p: p["data"][0].update(value="140"), "outside 0-100"),
        (lambda p: p["data"][0].pop("timestamp"), "unexpected Fear & Greed payload"),
        (lambda p: p.update(data="none"), "unexpected Fear & Greed payload"),
        (lambda p: p.update(metadata={"error": "Limit too high"}), "Limit too high"),
    ],
    ids=["out-of-scale", "no-date", "no-list", "reported-error"],
)
async def test_malformed_answers_are_data_errors(
    router: respx.MockRouter, cassette: Cassette, change: Any, message: str
) -> None:
    payload = cassette.payload()
    change(payload)
    cassette.play(router, payload=payload)

    async with _provider(cassette) as provider:
        with pytest.raises(ProviderDataError, match=message):
            await provider.fetch_economic_series(cassette.economic_request)


async def test_a_repeated_day_is_kept_once(router: respx.MockRouter, cassette: Cassette) -> None:
    payload = cassette.payload()
    payload["data"].append(dict(payload["data"][-1]))
    cassette.play(router, payload=payload)

    async with _provider(cassette) as provider:
        series = await provider.fetch_economic_series(cassette.economic_request)

    assert len(series.observations) == 20


def test_capabilities_describe_alternative_me() -> None:
    provider = AlternativeMeProvider()

    assert isinstance(provider, EconomicDataProvider)
    assert provider.name == "alternative_me"
    assert provider.capabilities.datasets == frozenset({Dataset.ECONOMIC})
    assert provider.capabilities.can_serve_economic(EconomicRequest("FNG"))
    assert not provider.capabilities.can_serve_economic(EconomicRequest("DGS3MO"))
