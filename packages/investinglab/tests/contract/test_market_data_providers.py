"""Contract that every market-data provider honours, whatever API sits behind it (ADR-0010).

Each provider runs against an offline source: SYNTHETIC files for ``files`` and recorded
real responses (cassettes) for the remote providers. A new provider joins the contract by adding one
:class:`Case`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING

import pandas as pd
import pytest
import respx

from investinglab.adapters.providers.ecb import EcbProvider
from investinglab.adapters.providers.files import LocalFilesProvider
from investinglab.adapters.providers.yahoo import YahooFinanceProvider
from investinglab.domain import PriceSeries
from investinglab.ports import BarsRequest, Dataset, MarketDataProvider, SymbolNotFoundError
from support.cassettes import load_cassette
from support.factories import business_days, gbm_prices

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable
    from pathlib import Path

SLUG = re.compile(r"^[a-z0-9][a-z0-9_.\-]{0,39}$")


def _files(folder: Path, router: respx.MockRouter) -> MarketDataProvider:
    del router  # no network
    index = business_days(60, start="2024-05-01")
    pd.DataFrame(
        {"Date": index.strftime("%Y-%m-%d"), "Close": gbm_prices(len(index), seed=11)}
    ).to_csv(folder / "SYNTH.csv", index=False)
    (folder / "instruments.toml").write_text(
        '["SYNTH"]\nname = "Synthetic series"\ncurrency = "EUR"\nexchange = "XMAD"\n'
    )
    return LocalFilesProvider(folder)


def _yahoo(folder: Path, router: respx.MockRouter) -> MarketDataProvider:
    del folder  # recorded responses only
    known = load_cassette("yahoo/san_mc_1d")
    load_cassette("yahoo/not_found").play(router)
    known.play(router)
    return YahooFinanceProvider(clock=known.clock)


def _ecb(folder: Path, router: respx.MockRouter) -> MarketDataProvider:
    del folder  # recorded responses only
    known = load_cassette("ecb/eurusd_1d")
    known.play(router)
    return EcbProvider(clock=known.clock)


@dataclass(frozen=True, slots=True)
class Case:
    """A provider wired to its offline source, a request it serves and one it cannot."""

    name: str
    build: Callable[[Path, respx.MockRouter], MarketDataProvider]
    request: BarsRequest
    unknown: BarsRequest


CASES = (
    Case(
        "files",
        _files,
        BarsRequest("SYNTH", start=date(2024, 5, 6), end=date(2024, 6, 28)),
        BarsRequest("MISSING"),
    ),
    Case(
        "yahoo",
        _yahoo,
        load_cassette("yahoo/san_mc_1d").bars_request,
        load_cassette("yahoo/not_found").bars_request,
    ),
    Case(
        "ecb",
        _ecb,
        load_cassette("ecb/eurusd_1d").bars_request,
        BarsRequest("EURVES=X"),
    ),
)


@pytest.fixture(params=CASES, ids=[case.name for case in CASES])
async def wired(
    request: pytest.FixtureRequest, tmp_path: Path
) -> AsyncIterator[tuple[Case, MarketDataProvider]]:
    case: Case = request.param
    with respx.mock(assert_all_called=False) as router:
        provider = case.build(tmp_path, router)
        yield case, provider
        closer = getattr(provider, "aclose", None)
        if closer is not None:
            await closer()


async def test_providers_implement_the_port(wired: tuple[Case, MarketDataProvider]) -> None:
    case, provider = wired

    assert isinstance(provider, MarketDataProvider)
    assert provider.name == case.name
    assert SLUG.fullmatch(provider.name)
    assert Dataset.BARS in provider.capabilities.datasets
    assert provider.capabilities.can_serve_bars(case.request, date(2026, 11, 9))


async def test_bars_answer_exactly_what_was_requested(
    wired: tuple[Case, MarketDataProvider],
) -> None:
    case, provider = wired
    request = case.request

    series = await provider.fetch_bars(request)

    assert isinstance(series, PriceSeries)
    assert (series.symbol, series.frequency) == (request.symbol, request.frequency)
    assert series.source.provider == provider.name
    assert series.source.retrieved_at.tzinfo is not None
    assert request.start is not None
    assert request.end is not None
    assert series.start >= pd.Timestamp(request.start)
    assert series.end <= pd.Timestamp(request.end)


async def test_unknown_symbols_are_not_found(wired: tuple[Case, MarketDataProvider]) -> None:
    case, provider = wired

    with pytest.raises(SymbolNotFoundError):
        await provider.fetch_bars(case.unknown)
