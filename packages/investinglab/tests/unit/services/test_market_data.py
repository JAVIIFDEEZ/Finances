from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from investinglab.domain import DomainError, Frequency, InvalidSeriesError
from investinglab.ports import (
    AuthenticationError,
    BarsRequest,
    CachedBars,
    EconomicRequest,
    ProviderUnavailableError,
    VintageMode,
)
from investinglab.services import (
    BatchResult,
    CachePolicy,
    DataUnavailableError,
    FetchFailure,
    MarketDataService,
    ProviderRegistry,
)
from support.factories import make_economic_series, make_series
from support.fakes import FakeBarsProvider, FakeEconomicProvider, InMemoryStore

NOW = datetime(2026, 10, 31, 12, 0, tzinfo=UTC)
SPY = make_series([100.0, 101.0, 102.0, 103.0, 104.0], symbol="SPY")
QQQ = make_series([50.0, 51.0, 52.0, 53.0, 54.0], symbol="QQQ")


def _service(
    *providers: FakeBarsProvider | FakeEconomicProvider,
    store: InMemoryStore | None = None,
    max_concurrency: int = 8,
) -> MarketDataService:
    registry = ProviderRegistry()
    for provider in providers:
        registry.register(provider)
    return MarketDataService(
        registry, store=store, max_concurrency=max_concurrency, clock=lambda: NOW
    )


# ── Single series ────────────────────────────────────────────────────


async def test_returns_the_provider_series() -> None:
    provider = FakeBarsProvider("primary", {"SPY": SPY})

    series = await _service(provider).get_bars(BarsRequest("SPY"))

    assert series == SPY
    assert len(provider.calls) == 1


async def test_falls_back_to_the_next_provider_and_records_attempts() -> None:
    failing = FakeBarsProvider("primary", errors={"SPY": ProviderUnavailableError("primary", "x")})
    backup = FakeBarsProvider("backup", {"SPY": SPY})

    series = await _service(failing, backup).get_bars(BarsRequest("SPY"))

    assert series == SPY
    assert len(failing.calls) == len(backup.calls) == 1


async def test_reports_every_attempt_when_all_providers_fail() -> None:
    first = FakeBarsProvider("first", errors={"SPY": AuthenticationError("first", "bad key")})
    second = FakeBarsProvider("second")

    with pytest.raises(DataUnavailableError) as caught:
        await _service(first, second).get_bars(BarsRequest("SPY"))

    attempts = caught.value.attempts
    assert [a.provider for a in attempts] == ["first", "second"]
    assert [a.error_type for a in attempts] == ["AuthenticationError", "SymbolNotFoundError"]
    assert not attempts[0].retryable
    assert "every provider failed" in str(caught.value)


async def test_no_capable_provider() -> None:
    with pytest.raises(DataUnavailableError, match="no registered provider"):
        await _service().get_bars(BarsRequest("SPY"))


async def test_a_provider_returning_the_wrong_series_is_rejected() -> None:
    liar = FakeBarsProvider("liar", {"SPY": QQQ})
    honest = FakeBarsProvider("honest", {"SPY": SPY})

    series = await _service(liar, honest).get_bars(BarsRequest("SPY"))

    assert series == SPY


async def test_requested_dates_slice_the_series() -> None:
    provider = FakeBarsProvider("primary", {"SPY": SPY})

    series = await _service(provider).get_bars(
        BarsRequest("SPY", start=date(2024, 1, 3), end=date(2024, 1, 5))
    )

    assert series.prices.tolist() == [101.0, 102.0, 103.0]


# ── Cache ────────────────────────────────────────────────────────────


async def test_fresh_cache_entries_avoid_provider_calls() -> None:
    store = InMemoryStore(now=NOW)
    provider = FakeBarsProvider("primary", {"SPY": SPY})
    service = _service(provider, store=store)

    await service.get_bars(BarsRequest("SPY"))
    cached = await service.get_bars(BarsRequest("SPY", start=date(2024, 1, 3)))

    assert len(provider.calls) == 1
    assert cached.prices.iloc[0] == 101.0


async def test_stale_cache_entries_are_refreshed() -> None:
    store = InMemoryStore(now=NOW - timedelta(days=2))
    store.save_bars(SPY, BarsRequest("SPY"))
    provider = FakeBarsProvider("primary", {"SPY": SPY})

    await _service(provider, store=store).get_bars(BarsRequest("SPY"))

    assert len(provider.calls) == 1


async def test_cache_entries_that_do_not_cover_the_request_are_ignored() -> None:
    store = InMemoryStore(now=NOW)
    store.bars["SPY", Frequency.DAY_1] = CachedBars(
        SPY, BarsRequest("SPY", start=date(2024, 1, 4)), NOW
    )
    provider = FakeBarsProvider("primary", {"SPY": SPY})

    await _service(provider, store=store).get_bars(BarsRequest("SPY"))

    assert len(provider.calls) == 1


async def test_refresh_bypasses_the_cache() -> None:
    store = InMemoryStore(now=NOW)
    store.save_bars(SPY, BarsRequest("SPY"))
    provider = FakeBarsProvider("primary", {"SPY": SPY})

    await _service(provider, store=store).get_bars(BarsRequest("SPY"), refresh=True)

    assert len(provider.calls) == 1


async def test_cache_write_failures_do_not_lose_the_data() -> None:
    store = InMemoryStore(now=NOW, fail_writes=True)
    provider = FakeBarsProvider("primary", {"SPY": SPY})

    assert await _service(provider, store=store).get_bars(BarsRequest("SPY")) == SPY


@pytest.mark.parametrize(
    ("frequency", "ttl"),
    [
        (Frequency.MINUTE_5, timedelta(minutes=15)),
        (Frequency.DAY_1, timedelta(hours=12)),
        (Frequency.MONTH_1, timedelta(hours=24)),
    ],
)
def test_cache_policy_ttls(frequency: Frequency, ttl: timedelta) -> None:
    assert CachePolicy().ttl_for(frequency) == ttl


# ── Batches ──────────────────────────────────────────────────────────


async def test_batches_report_partial_failures_without_aborting() -> None:
    provider = FakeBarsProvider("primary", {"SPY": SPY, "QQQ": QQQ})
    requests = [BarsRequest("SPY"), BarsRequest("QQQ"), BarsRequest("NOPE")]

    result = await _service(provider).get_many_bars(requests)

    assert set(result.succeeded) == {"SPY", "QQQ"}
    assert set(result.failed) == {"NOPE"}
    assert not result.ok
    assert len(result) == 3
    assert result.summary() == "2/3 succeeded; failed: NOPE"
    assert result.failed["NOPE"].attempts[0].error_type == "SymbolNotFoundError"


async def test_domain_errors_are_failures_of_their_item_only() -> None:
    provider = FakeBarsProvider("primary", {"SPY": SPY, "QQQ": QQQ})
    requests = [
        BarsRequest("SPY", start=date(2024, 1, 8)),  # one observation: invalid series
        BarsRequest("QQQ"),
    ]

    result = await _service(provider).get_many_bars(requests)

    assert set(result.succeeded) == {"QQQ"}
    assert "at least 3 observations" in result.failed["SPY"].message


async def test_batch_concurrency_is_bounded() -> None:
    universe = {f"S{i}": make_series(symbol=f"S{i}") for i in range(10)}
    provider = FakeBarsProvider("primary", universe, delay=0.01)

    result = await _service(provider, max_concurrency=3).get_many_bars(
        BarsRequest(symbol) for symbol in universe
    )

    assert result.ok
    assert result.summary() == "10/10 succeeded"
    assert provider.max_in_flight == 3


async def test_duplicated_requests_are_rejected() -> None:
    with pytest.raises(DomainError, match="Duplicated"):
        await _service().get_many_bars([BarsRequest("SPY"), BarsRequest("SPY")])


def test_invalid_concurrency() -> None:
    with pytest.raises(DomainError):
        MarketDataService(ProviderRegistry(), max_concurrency=0)


def test_empty_batch_result() -> None:
    result: BatchResult[int] = BatchResult()

    assert result.ok
    assert result.summary() == "0/0 succeeded"
    assert FetchFailure("X", "boom").attempts == ()


# ── Economic series ──────────────────────────────────────────────────


async def test_economic_series_with_cache_and_slicing() -> None:
    store = InMemoryStore(now=NOW)
    provider = FakeEconomicProvider("fred", {"SYNTH_RATE": make_economic_series()})
    service = _service(provider, store=store)

    full = await service.get_economic_series(EconomicRequest("SYNTH_RATE"))
    sliced = await service.get_economic_series(
        EconomicRequest("SYNTH_RATE", start=date(2024, 2, 1))
    )

    assert len(full) == 3
    assert sliced.first_release().tolist() == [3.8, 3.9]
    assert len(provider.calls) == 1


async def test_economic_cache_requires_matching_vintage_mode() -> None:
    store = InMemoryStore(now=NOW)
    provider = FakeEconomicProvider("fred", {"SYNTH_RATE": make_economic_series()})
    service = _service(provider, store=store)

    await service.get_economic_series(EconomicRequest("SYNTH_RATE"))
    await service.get_economic_series(EconomicRequest("SYNTH_RATE", mode=VintageMode.LATEST))

    assert len(provider.calls) == 2


async def test_economic_failures_and_batches() -> None:
    provider = FakeEconomicProvider(
        "fred",
        {"SYNTH_RATE": make_economic_series()},
        errors={"DOWN": ProviderUnavailableError("fred", "503")},
    )
    service = _service(provider, store=InMemoryStore(now=NOW, fail_writes=True))

    result = await service.get_many_economic_series(
        [EconomicRequest("SYNTH_RATE"), EconomicRequest("DOWN"), EconomicRequest("MISSING")]
    )

    assert set(result.succeeded) == {"SYNTH_RATE"}
    assert result.failed["DOWN"].attempts[0].retryable
    assert set(result.failed) == {"DOWN", "MISSING"}


async def test_no_economic_provider() -> None:
    with pytest.raises(DataUnavailableError, match="no registered economic"):
        await _service().get_economic_series(EconomicRequest("UNRATE"))


async def test_stale_economic_cache_is_refreshed() -> None:
    store = InMemoryStore(now=NOW - timedelta(days=3))
    store.save_economic(make_economic_series(), EconomicRequest("SYNTH_RATE"))
    provider = FakeEconomicProvider("fred", {"SYNTH_RATE": make_economic_series()})

    await _service(provider, store=store).get_economic_series(EconomicRequest("SYNTH_RATE"))

    assert len(provider.calls) == 1


def test_invalid_series_is_a_domain_error() -> None:
    assert issubclass(InvalidSeriesError, DomainError)
