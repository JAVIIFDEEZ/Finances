from __future__ import annotations

import asyncio
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta, timezone

import pandas as pd

from investinglab.domain import (
    USD,
    AssetClass,
    MarketSnapshot,
    PriceSeries,
    RateKind,
    RateSeries,
)
from investinglab.ports import (
    BarsRequest,
    Canary,
    Dataset,
    EconomicRequest,
    MarketSnapshotRequest,
    ProviderCapabilities,
    RateLimitedError,
    RatesRequest,
)
from investinglab.services import CHECK_TIMEOUT, check_source, check_sources
from investinglab.services.heartbeat import LOOKBACK, MAX_ERROR, latest_instant
from support.factories import (
    SYNTHETIC_SOURCE,
    make_economic_series,
    make_instrument,
    make_series,
)
from support.fakes import (
    BARS_CAPABILITIES,
    ECONOMIC_CAPABILITIES,
    RATES_CAPABILITIES,
    REFERENCE_CAPABILITIES,
    FakeBarsProvider,
    FakeEconomicProvider,
    FakeRatesProvider,
    FakeReferenceProvider,
)

NOW = datetime(2026, 11, 23, 12, 0, tzinfo=UTC)
TODAY = NOW.date()
CANARY_BARS = replace(BARS_CAPABILITIES, canary=Canary(Dataset.BARS, "SPY"))
SWAP = make_instrument("BTC/USDT:USDT", currency=USD, asset_class=AssetClass.CRYPTO, exchange=None)


def _clock() -> datetime:
    return NOW


def _bars(name: str = "yahoo", **fields: object) -> FakeBarsProvider:
    return FakeBarsProvider(
        name,
        series={"SPY": make_series(symbol="SPY")},
        capabilities=CANARY_BARS,
        **fields,  # type: ignore[arg-type]
    )


def test_an_observation_is_placed_in_time_as_an_aware_instant() -> None:
    session = datetime(2026, 11, 20, tzinfo=UTC)
    madrid = timezone(timedelta(hours=1))

    assert latest_instant(pd.Timestamp("2026-11-20")) == session  # a session's date: midnight UTC
    assert latest_instant(date(2026, 11, 20)) == session
    assert latest_instant(datetime(2026, 11, 20, 1, 0, tzinfo=madrid)) == session
    assert latest_instant(pd.Timestamp("2026-11-20 08:00", tz="UTC")).hour == 8


async def test_a_source_that_answers_its_bars() -> None:
    provider = _bars()

    heartbeat = await check_source(provider, clock=_clock)

    assert heartbeat is not None
    assert (heartbeat.provider, heartbeat.checked_at, heartbeat.ok) == ("yahoo", NOW, True)
    assert heartbeat.latest == datetime(2024, 1, 8, tzinfo=UTC)  # the last synthetic session
    assert heartbeat.latency >= 0
    assert heartbeat.error is None
    assert provider.calls == [BarsRequest("SPY", start=TODAY - LOOKBACK[Dataset.BARS])]


async def test_a_source_that_answers_an_economic_series() -> None:
    capabilities = replace(ECONOMIC_CAPABILITIES, canary=Canary(Dataset.ECONOMIC, "FNG"))
    provider = FakeEconomicProvider(
        "alternative_me", series={"FNG": make_economic_series("FNG")}, capabilities=capabilities
    )

    heartbeat = await check_source(provider, clock=_clock)

    assert heartbeat is not None
    assert heartbeat.latest == datetime(2024, 3, 1, tzinfo=UTC)
    assert provider.calls == [EconomicRequest("FNG", start=TODAY - LOOKBACK[Dataset.ECONOMIC])]


async def test_a_source_that_answers_its_funding() -> None:
    settled = pd.date_range("2026-11-22", periods=3, freq="8h", tz="UTC")
    funding = RateSeries(
        SWAP,
        "okx",
        RateKind.FUNDING,
        SYNTHETIC_SOURCE,
        pd.Series([0.0001, -0.0002, 0.0001], index=settled),
    )
    capabilities = replace(RATES_CAPABILITIES, canary=Canary(Dataset.HOLDING_RATES, SWAP.symbol))
    provider = FakeRatesProvider("okx", rates={SWAP.symbol: funding}, capabilities=capabilities)

    heartbeat = await check_source(provider, clock=_clock)

    assert heartbeat is not None
    assert heartbeat.latest == datetime(2026, 11, 22, 16, 0, tzinfo=UTC)
    assert provider.calls == [
        RatesRequest(SWAP.symbol, RateKind.FUNDING, start=TODAY - LOOKBACK[Dataset.HOLDING_RATES])
    ]


async def test_a_source_that_answers_a_market_snapshot() -> None:
    as_of = datetime(2026, 11, 23, 11, 55, tzinfo=UTC)
    snapshot = MarketSnapshot(AssetClass.CRYPTO, USD, as_of, SYNTHETIC_SOURCE, 2.0e12)
    capabilities = replace(REFERENCE_CAPABILITIES, canary=Canary(Dataset.REFERENCE, "crypto"))
    provider = FakeReferenceProvider("coingecko", snapshot=snapshot, capabilities=capabilities)

    heartbeat = await check_source(provider, clock=_clock)

    assert heartbeat is not None
    assert heartbeat.latest == as_of
    assert provider.calls == [MarketSnapshotRequest(AssetClass.CRYPTO)]


async def test_a_failing_source_is_a_heartbeat_not_an_exception() -> None:
    provider = _bars(errors={"SPY": RateLimitedError("yahoo", "HTTP 429")})

    heartbeat = await check_source(provider, clock=_clock)

    assert heartbeat is not None
    assert (heartbeat.ok, heartbeat.latest) == (False, None)
    assert heartbeat.error is not None
    assert heartbeat.error.startswith("RateLimitedError: ")
    assert "HTTP 429" in heartbeat.error


async def test_a_long_error_is_cut() -> None:
    provider = _bars(errors={"SPY": RateLimitedError("yahoo", "x" * 1000)})

    heartbeat = await check_source(provider, clock=_clock)

    assert heartbeat is not None
    assert heartbeat.error is not None
    assert len(heartbeat.error) == MAX_ERROR
    assert heartbeat.error.endswith("…")


async def test_a_source_that_does_not_answer_in_time() -> None:
    heartbeat = await check_source(_bars(delay=1.0), within=0.01, clock=_clock)

    assert heartbeat is not None
    assert heartbeat.ok is False
    assert heartbeat.error == "TimeoutError: no answer within 0.01 s"
    assert heartbeat.latency < 1.0
    assert CHECK_TIMEOUT == 30.0


async def test_a_canary_the_provider_cannot_answer_fails_the_check() -> None:
    # It declares bars, but it is no market-data provider: the check says so instead of crashing.
    capabilities = ProviderCapabilities(
        datasets=frozenset({Dataset.BARS, Dataset.HOLDING_RATES}),
        rate_kinds=frozenset({RateKind.FUNDING}),
        canary=Canary(Dataset.BARS, "BTC/USDT"),
    )

    heartbeat = await check_source(FakeRatesProvider("odd", capabilities=capabilities))

    assert heartbeat is not None
    assert heartbeat.error == "DomainError: odd declares a bars canary it cannot answer"


async def test_a_source_without_a_canary_is_not_checked() -> None:
    files = FakeBarsProvider("files", series={"SPY": make_series(symbol="SPY")})

    assert await check_source(files) is None
    heartbeats = await check_sources([files, _bars()], clock=_clock)
    assert [heartbeat.provider for heartbeat in heartbeats] == ["yahoo"]
    assert files.calls == []


@dataclass
class _Rendezvous:
    """Answers only once every source has been asked: a check one at a time never ends."""

    name: str
    expected: int
    arrived: list[str] = field(default_factory=list)
    everyone: asyncio.Event = field(default_factory=asyncio.Event)
    capabilities: ProviderCapabilities = field(default=CANARY_BARS)

    async def fetch_bars(self, request: BarsRequest) -> PriceSeries:
        self.arrived.append(request.symbol)
        if len(self.arrived) == self.expected:
            self.everyone.set()
        await self.everyone.wait()
        return make_series(symbol=request.symbol)


async def test_every_source_is_checked_at_once() -> None:
    first = _Rendezvous("yahoo", expected=3)
    sources = [first, replace(first, name="ecb"), replace(first, name="kraken")]  # one meeting

    heartbeats = await check_sources(sources, within=1.0, clock=_clock)

    assert [(heartbeat.provider, heartbeat.ok) for heartbeat in heartbeats] == [
        ("yahoo", True),
        ("ecb", True),
        ("kraken", True),
    ]
