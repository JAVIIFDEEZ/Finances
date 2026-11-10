from __future__ import annotations

import threading
from datetime import UTC, date, datetime, timedelta

import pandas as pd
import pytest

from investinglab.domain import (
    EXCHANGES,
    USD,
    DataSource,
    DomainError,
    Frequency,
    InvalidSeriesError,
    PriceSeries,
)
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
from investinglab.services.market_data import _overlap_start
from support.factories import business_days, gbm_prices, make_economic_series, make_series
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


async def test_unreadable_cache_entries_are_cache_misses() -> None:
    store = InMemoryStore(now=NOW, fail_reads=True)
    bars = FakeBarsProvider("primary", {"SPY": SPY})
    economic = FakeEconomicProvider("fred", {"SYNTH_RATE": make_economic_series()})
    service = _service(bars, economic, store=store)

    assert await service.get_bars(BarsRequest("SPY")) == SPY
    assert len(await service.get_economic_series(EconomicRequest("SYNTH_RATE"))) == 3


async def test_cache_io_runs_off_the_event_loop() -> None:
    store = InMemoryStore(now=NOW)
    bars = FakeBarsProvider("primary", {"SPY": SPY})
    economic = FakeEconomicProvider("fred", {"SYNTH_RATE": make_economic_series()})
    service = _service(bars, economic, store=store)

    await service.get_bars(BarsRequest("SPY"))
    await service.get_economic_series(EconomicRequest("SYNTH_RATE"))

    assert len(store.threads) == 4  # one read and one write per series
    assert threading.current_thread().name not in store.threads


# ── Incremental cache (ADR-0019) ─────────────────────────────────────

DAYS = business_days(30)
HISTORY = make_series(gbm_prices(30, seed=3), symbol="SPY", index=DAYS, ohlc=True)


def _stale(series: PriceSeries, coverage: BarsRequest) -> InMemoryStore:
    store = InMemoryStore(now=NOW - timedelta(days=2))
    store.save_bars(series, coverage)
    return store


def _ranges(provider: FakeBarsProvider) -> list[tuple[date | None, date | None]]:
    return [(call.start, call.end) for call in provider.calls]


async def test_stale_entries_download_only_the_missing_tail() -> None:
    store = _stale(HISTORY.between(end=DAYS[19]), BarsRequest("SPY"))
    provider = FakeBarsProvider("primary", {"SPY": HISTORY}, slice_requests=True)

    series = await _service(provider, store=store).get_bars(BarsRequest("SPY"))

    assert _ranges(provider) == [(DAYS[15].date(), None)]  # the last 5 cached bars again
    assert series.bars.equals(HISTORY.bars)
    entry = store.bars["SPY", Frequency.DAY_1]
    assert entry.coverage == BarsRequest("SPY")
    assert entry.series.bars.equals(HISTORY.bars)


async def test_a_partial_last_bar_is_replaced_by_the_download() -> None:
    cached = HISTORY.between(end=DAYS[19])
    bars = cached.bars
    bars.iloc[-1] *= 1.01  # captured during the session
    store = _stale(cached.with_bars(bars), BarsRequest("SPY"))
    provider = FakeBarsProvider("primary", {"SPY": HISTORY}, slice_requests=True)

    series = await _service(provider, store=store).get_bars(BarsRequest("SPY"))

    assert len(provider.calls) == 1
    assert series.bars.equals(HISTORY.bars)


async def test_a_readjusted_history_is_downloaded_again_in_full() -> None:
    cached = HISTORY.between(end=DAYS[19])
    store = _stale(cached.with_bars(cached.bars * 0.98), BarsRequest("SPY"))  # pre-dividend
    provider = FakeBarsProvider("primary", {"SPY": HISTORY}, slice_requests=True)

    series = await _service(provider, store=store).get_bars(BarsRequest("SPY"))

    assert _ranges(provider) == [(DAYS[15].date(), None), (None, None)]
    assert series.bars.equals(HISTORY.bars)


async def test_bars_from_another_provider_are_never_mixed() -> None:
    cached = HISTORY.between(end=DAYS[19])
    retired = DataSource("retired", NOW - timedelta(days=30))
    store = _stale(cached.with_bars(cached.bars, source=retired), BarsRequest("SPY"))
    provider = FakeBarsProvider("primary", {"SPY": HISTORY}, slice_requests=True)

    series = await _service(provider, store=store).get_bars(BarsRequest("SPY"))

    assert len(provider.calls) == 2
    assert series.source == HISTORY.source
    assert series.bars.equals(HISTORY.bars)


async def test_requests_beyond_the_cached_end_extend_the_entry() -> None:
    store = InMemoryStore(now=NOW)
    store.save_bars(HISTORY.between(end=DAYS[19]), BarsRequest("SPY", end=DAYS[19].date()))
    provider = FakeBarsProvider("primary", {"SPY": HISTORY}, slice_requests=True)
    service = _service(provider, store=store)

    series = await service.get_bars(BarsRequest("SPY", start=DAYS[10].date(), end=DAYS[25].date()))
    again = await service.get_bars(BarsRequest("SPY", end=DAYS[25].date()))

    assert len(series) == 16
    assert _ranges(provider) == [(DAYS[15].date(), DAYS[25].date())]
    assert len(again) == 26  # served by the extended entry


async def test_requests_for_older_history_replace_the_entry_with_a_superset() -> None:
    store = InMemoryStore(now=NOW)
    store.save_bars(HISTORY.between(start=DAYS[10]), BarsRequest("SPY", start=DAYS[10].date()))
    provider = FakeBarsProvider("primary", {"SPY": HISTORY}, slice_requests=True)
    service = _service(provider, store=store)

    older = await service.get_bars(BarsRequest("SPY", start=DAYS[2].date(), end=DAYS[5].date()))
    latest = await service.get_bars(BarsRequest("SPY", start=DAYS[20].date()))

    assert len(older) == 4
    assert len(latest) == 10
    assert _ranges(provider) == [(DAYS[2].date(), None)]
    assert store.bars["SPY", Frequency.DAY_1].coverage == BarsRequest("SPY", start=DAYS[2].date())


async def test_the_overlap_ends_at_the_requested_end() -> None:
    # The provider sent more than the cached coverage: the overlap still ends at its end.
    store = _stale(HISTORY, BarsRequest("SPY", end=DAYS[10].date()))
    provider = FakeBarsProvider("primary", {"SPY": HISTORY}, slice_requests=True)

    series = await _service(provider, store=store).get_bars(BarsRequest("SPY", end=DAYS[10].date()))

    assert _ranges(provider) == [(DAYS[6].date(), DAYS[10].date())]
    assert len(series) == 11


async def test_too_few_cached_bars_to_overlap_means_a_full_download() -> None:
    store = _stale(HISTORY.between(start=DAYS[9]), BarsRequest("SPY", end=DAYS[10].date()))
    provider = FakeBarsProvider("primary", {"SPY": HISTORY}, slice_requests=True)

    await _service(provider, store=store).get_bars(BarsRequest("SPY", end=DAYS[10].date()))

    assert _ranges(provider) == [(None, DAYS[10].date())]


def test_intraday_overlaps_start_on_the_venue_session_date() -> None:
    # 01:00 UTC on 5 March is still the evening of 4 March in New York.
    index = pd.date_range("2024-03-04 20:00", periods=10, freq="1h", tz="UTC")
    intraday = make_series(
        gbm_prices(10),
        symbol="SPY",
        index=index,
        frequency=Frequency.HOUR_1,
        currency=USD,
        exchange=EXCHANGES["XNYS"],
    )

    assert _overlap_start(intraday, None) == date(2024, 3, 4)
    assert _overlap_start(intraday, date(2024, 3, 3)) is None


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
    with pytest.raises(DataUnavailableError, match="no registered provider serves UNRATE"):
        await _service().get_economic_series(EconomicRequest("UNRATE"))


async def test_stale_economic_cache_is_refreshed() -> None:
    store = InMemoryStore(now=NOW - timedelta(days=3))
    store.save_economic(make_economic_series(), EconomicRequest("SYNTH_RATE"))
    provider = FakeEconomicProvider("fred", {"SYNTH_RATE": make_economic_series()})

    await _service(provider, store=store).get_economic_series(EconomicRequest("SYNTH_RATE"))

    assert len(provider.calls) == 1


def test_invalid_series_is_a_domain_error() -> None:
    assert issubclass(InvalidSeriesError, DomainError)
