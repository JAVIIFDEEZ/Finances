"""Market-data use cases: cached, multi-provider and concurrent ingestion (ADR-0010).

Price bars and economic series are cached on disk; trade flow and holding rates (ADR-0031)
follow the same routing and fallback and are remembered in memory for a while, so the screens
that ask for them again do not download them again.

Every request follows the same path:

1. **Cache**: if a fresh cached entry covers the request, it is returned sliced to the
   requested dates. A stale entry, or one that lacks the end of the request, is extended
   with only the bars it is missing (ADR-0019). What a provider that is not cacheable
   would serve (local files, which their owner may edit) skips the cache altogether.
2. **Routing**: the registry returns the providers able to serve the request, in preference
   order.
3. **Fallback**: providers are tried in order; any provider failure is recorded and the
   next provider is tried.
4. **Failure report**: if every provider fails, :class:`DataUnavailableError` lists every
   attempt and its cause.

Batches download many series concurrently (bounded by ``max_concurrency``) and never abort
on a partial failure: :class:`BatchResult` separates successes from failures. Cache reads and
writes are blocking file I/O, so they run in worker threads and never stall the downloads
in flight (ADR-0019).
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Final, Protocol

import numpy as np
import pandas as pd

from investinglab.config.logging import get_logger
from investinglab.domain.errors import DomainError, InvestingLabError
from investinglab.domain.flow import FlowSeries
from investinglab.domain.rate_series import RateSeries
from investinglab.domain.series import MIN_OBSERVATIONS, PriceField
from investinglab.domain.time import Frequency
from investinglab.ports.errors import ProviderDataError, ProviderError

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Hashable, Iterable, Mapping, Sequence
    from datetime import date

    from investinglab.domain.economic import EconomicSeries
    from investinglab.domain.series import PriceSeries
    from investinglab.ports.market_data import (
        BarsRequest,
        EconomicRequest,
        HoldingRatesProvider,
        MarketDataProvider,
        RatesRequest,
        TradeFlowProvider,
    )
    from investinglab.ports.storage import CachedBars, SeriesStore
    from investinglab.services.registry import ProviderRegistry

__all__ = [
    "OVERLAP_BARS",
    "PRICE_TOLERANCE",
    "BatchResult",
    "CachePolicy",
    "DataUnavailableError",
    "FetchAttempt",
    "FetchFailure",
    "MarketDataService",
]

log = get_logger(__name__)

OVERLAP_BARS: Final = 5
"""Cached bars downloaded again when an entry is extended, to verify the history."""

PRICE_TOLERANCE: Final = 1e-6
"""Relative tolerance between the cached and the downloaded prices of the same bar."""


def _utc_now() -> datetime:
    return datetime.now(UTC)


class _Named(Protocol):
    @property
    def name(self) -> str: ...


@dataclass(frozen=True, slots=True)
class CachePolicy:
    """Time-to-live of cached data, by kind and frequency.

    Attributes:
        intraday_ttl: Intraday bars change all day long.
        daily_ttl: Daily bars change once per session.
        periodic_ttl: Weekly and lower frequencies.
        economic_ttl: Economic series are published at most daily.
        rates_ttl: Holding rates settle every few hours.
        memory_entries: Most flow and rates answers kept in memory (least recently used
            go first).
    """

    intraday_ttl: timedelta = timedelta(minutes=15)
    daily_ttl: timedelta = timedelta(hours=12)
    periodic_ttl: timedelta = timedelta(hours=24)
    economic_ttl: timedelta = timedelta(hours=24)
    rates_ttl: timedelta = timedelta(hours=1)
    memory_entries: int = 256

    def ttl_for(self, frequency: Frequency) -> timedelta:
        """TTL for price bars of ``frequency``."""
        if frequency.is_intraday:
            return self.intraday_ttl
        if frequency is Frequency.DAY_1:
            return self.daily_ttl
        return self.periodic_ttl


class _Memory:
    """Answers kept in memory with the moment they were obtained, least recently used first out."""

    def __init__(self, capacity: int) -> None:
        self._capacity = capacity
        self._entries: OrderedDict[Hashable, tuple[datetime, object]] = OrderedDict()

    def get(self, key: Hashable, now: datetime, ttl: timedelta) -> object | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        stored_at, value = entry
        if now - stored_at >= ttl:
            del self._entries[key]
            return None
        self._entries.move_to_end(key)
        return value

    def put(self, key: Hashable, now: datetime, value: object) -> None:
        self._entries[key] = (now, value)
        self._entries.move_to_end(key)
        while len(self._entries) > self._capacity:
            self._entries.popitem(last=False)

    def __len__(self) -> int:
        return len(self._entries)


@dataclass(frozen=True, slots=True)
class FetchAttempt:
    """One failed attempt to get data from a provider."""

    provider: str
    error_type: str
    message: str
    retryable: bool


@dataclass(frozen=True, slots=True)
class FetchFailure:
    """Why one item of a batch could not be obtained."""

    key: str
    message: str
    attempts: tuple[FetchAttempt, ...] = ()


class DataUnavailableError(InvestingLabError):
    """No provider could deliver the requested data.

    Attributes:
        key: Symbol or series id.
        attempts: Every provider attempt and its failure, in order.
    """

    def __init__(self, key: str, attempts: tuple[FetchAttempt, ...], reason: str = "") -> None:
        self.key = key
        self.attempts = attempts
        details = "; ".join(f"{a.provider}: {a.error_type} ({a.message})" for a in attempts)
        message = reason or (f"every provider failed: {details}" if attempts else "no provider")
        super().__init__(f"Data unavailable for {key!r}: {message}")


@dataclass(frozen=True, slots=True)
class BatchResult[T]:
    """Outcome of a batch download: successes and failures, keyed by symbol or series id."""

    succeeded: Mapping[str, T] = field(default_factory=dict)
    failed: Mapping[str, FetchFailure] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        """``True`` when every item was obtained."""
        return not self.failed

    def __len__(self) -> int:
        return len(self.succeeded) + len(self.failed)

    def summary(self) -> str:
        """One-line human summary, e.g. ``"9/10 succeeded; failed: XYZ"``."""
        failed = ", ".join(sorted(self.failed))
        text = f"{len(self.succeeded)}/{len(self)} succeeded"
        return f"{text}; failed: {failed}" if failed else text


class MarketDataService:
    """Use cases to obtain price bars and economic series from the registered providers.

    Args:
        registry: Registered providers and routing preferences.
        store: Optional persistent cache.
        cache_policy: Time-to-live of cached data.
        max_concurrency: Maximum simultaneous downloads in a batch.
        clock: Returns the current time (injectable for tests).
    """

    def __init__(
        self,
        registry: ProviderRegistry,
        *,
        store: SeriesStore | None = None,
        cache_policy: CachePolicy | None = None,
        max_concurrency: int = 8,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        if max_concurrency < 1:
            raise DomainError("max_concurrency must be at least 1")
        self._registry = registry
        self._store = store
        self._cache_policy = cache_policy or CachePolicy()
        self._max_concurrency = max_concurrency
        self._clock = clock
        self._memory = _Memory(max(self._cache_policy.memory_entries, 0))

    # ── Price bars ───────────────────────────────────────────────────

    async def get_bars(self, request: BarsRequest, *, refresh: bool = False) -> PriceSeries:
        """Price series for ``request``, from the cache when fresh or from the providers.

        A cached entry that starts early enough but is stale, or ends too soon, is extended
        with the bars it lacks: the download starts :data:`OVERLAP_BARS` bars before the
        cached end, and those bars must match the cache. When they do not (a dividend or
        split re-adjusted the history, a revision, another provider), the whole range is
        downloaded again. A request for older history than cached is downloaded from its
        start to the end of the cached range, which replaces the entry.

        Args:
            request: What to download.
            refresh: Ignore the cache: download exactly the request and store it.

        Raises:
            DataUnavailableError: If no provider could deliver the series.
        """
        if not self._cacheable(self._registry.bars_candidates(request, self._clock().date())):
            log.debug("bars_cache_skipped", symbol=request.symbol, reason="local source")
            return await self._fetch_bars(request)
        cached = None if refresh else await self._cached_bars(request)
        if cached is not None and self._answers(cached, request):
            log.debug("bars_cache_hit", symbol=request.symbol, frequency=request.frequency.value)
            return _slice_bars(cached.series, request)
        series, coverage = await self._download_bars(request, cached)
        await self._save_bars(series, coverage)
        return _slice_bars(series, request)

    async def _download_bars(
        self, request: BarsRequest, cached: CachedBars | None
    ) -> tuple[PriceSeries, BarsRequest]:
        """Downloaded (or extended) series and the coverage to store it under."""
        if cached is None:
            return await self._fetch_bars(request), request
        known = cached.coverage
        end = _later_end(known.end, request.end)
        if not _starts_within(request, known):
            # Older history: one download up to the cached end replaces the whole entry.
            superset = replace(request, end=end)
            return await self._fetch_bars(superset), superset
        extended = replace(request, start=known.start, end=end)
        start = _overlap_start(cached.series, end)
        if start is not None:
            tail = replace(request, start=start, end=end)
            merged = _append(cached.series, await self._fetch_bars(tail))
            if merged is not None:
                log.info("bars_cache_extended", symbol=request.symbol, since=str(start))
                return merged, extended
            log.info("bars_history_changed", symbol=request.symbol)
        return await self._fetch_bars(extended), extended

    async def _fetch_bars(self, request: BarsRequest) -> PriceSeries:
        """Try every capable provider in order (fallback) until one delivers the series."""
        candidates = self._registry.bars_candidates(request, self._clock().date())

        async def fetch(provider: MarketDataProvider) -> PriceSeries:
            series = await provider.fetch_bars(request)
            _check_bars(provider.name, request, series.symbol, series.frequency)
            return series

        return await _first_answer("bars", request.symbol, str(request), candidates, fetch)

    async def get_many_bars(
        self, requests: Iterable[BarsRequest], *, refresh: bool = False
    ) -> BatchResult[PriceSeries]:
        """Download several series concurrently; failures never abort the batch.

        Raises:
            DomainError: If the same symbol is requested twice.
        """
        items = list(requests)
        _ensure_unique([r.symbol for r in items])
        return await self._gather({r.symbol: self.get_bars(r, refresh=refresh) for r in items})

    # ── Economic series ──────────────────────────────────────────────

    async def get_economic_series(
        self, request: EconomicRequest, *, refresh: bool = False
    ) -> EconomicSeries:
        """Economic series for ``request``, cached or downloaded (point-in-time by default).

        Raises:
            DataUnavailableError: If no provider could deliver the series.
        """
        if not refresh and (cached := await self._fresh_cached_economic(request)) is not None:
            log.debug("economic_cache_hit", series_id=request.series_id)
            return cached.between(request.start, request.end)

        series = await _first_answer(
            "economic",
            request.series_id,
            request.series_id,
            self._registry.economic_candidates(request),
            lambda provider: provider.fetch_economic_series(request),
        )
        await self._save_economic(series, request)
        return series.between(request.start, request.end)

    async def get_many_economic_series(
        self, requests: Iterable[EconomicRequest], *, refresh: bool = False
    ) -> BatchResult[EconomicSeries]:
        """Download several economic series concurrently; failures never abort the batch."""
        items = list(requests)
        _ensure_unique([r.series_id for r in items])
        return await self._gather(
            {r.series_id: self.get_economic_series(r, refresh=refresh) for r in items}
        )

    # ── Trade flow and holding rates ─────────────────────────────────

    async def get_flow(self, request: BarsRequest, *, refresh: bool = False) -> FlowSeries:
        """Trade flow of the bars ``request`` describes, from the first provider able to serve it.

        The answer is remembered in memory for the time-to-live of bars of that frequency.

        Args:
            request: The bars whose flow is wanted.
            refresh: Download again even if a recent answer is remembered.

        Raises:
            DataUnavailableError: If no provider could deliver the flow.
        """
        now = self._clock()
        key = ("flow", request)
        candidates = self._registry.flow_candidates(request, now.date())
        remember = self._cacheable(candidates)
        if (
            remember
            and not refresh
            and isinstance(
                remembered := self._memory.get(
                    key, now, self._cache_policy.ttl_for(request.frequency)
                ),
                FlowSeries,
            )
        ):
            return remembered

        async def fetch(provider: TradeFlowProvider) -> FlowSeries:
            flow = await provider.fetch_flow(request)
            _check_bars(provider.name, request, flow.symbol, flow.frequency)
            return flow

        flow = await _first_answer("flow", request.symbol, str(request), candidates, fetch)
        if remember:
            self._memory.put(key, now, flow)
        return flow

    async def get_rates(self, request: RatesRequest, *, refresh: bool = False) -> RateSeries:
        """Holding rates of ``request``, from the first provider able to serve them.

        The answer is remembered in memory for ``CachePolicy.rates_ttl``.

        Args:
            request: The rates wanted.
            refresh: Download again even if a recent answer is remembered.

        Raises:
            DataUnavailableError: If no provider could deliver the rates.
        """
        now = self._clock()
        key = ("rates", request)
        if not refresh and isinstance(
            remembered := self._memory.get(key, now, self._cache_policy.rates_ttl), RateSeries
        ):
            return remembered
        candidates = self._registry.rates_candidates(request)

        async def fetch(provider: HoldingRatesProvider) -> RateSeries:
            rates = await provider.fetch_rates(request)
            wanted = (request.symbol, request.kind, request.venue or rates.venue)
            if (rates.symbol, rates.kind, rates.venue) != wanted:
                raise ProviderDataError(
                    provider.name,
                    f"returned {rates.kind.value} of {rates.symbol}@{rates.venue} for "
                    f"{request.kind.value} of {request.symbol}@{request.venue or 'any venue'}",
                )
            return rates

        rates = await _first_answer("rates", request.symbol, str(request), candidates, fetch)
        self._memory.put(key, now, rates)
        return rates

    # ── Internals ────────────────────────────────────────────────────

    async def _gather[T](self, jobs: Mapping[str, Awaitable[T]]) -> BatchResult[T]:
        semaphore = asyncio.Semaphore(self._max_concurrency)

        async def run(key: str, job: Awaitable[T]) -> tuple[str, T | FetchFailure]:
            async with semaphore:
                try:
                    return key, await job
                except DataUnavailableError as error:
                    return key, FetchFailure(key, str(error), error.attempts)
                except InvestingLabError as error:
                    return key, FetchFailure(key, str(error))

        outcomes = await asyncio.gather(*(run(key, job) for key, job in jobs.items()))
        succeeded = {k: v for k, v in outcomes if not isinstance(v, FetchFailure)}
        failed = {k: v for k, v in outcomes if isinstance(v, FetchFailure)}
        if failed:
            log.warning("batch_partial_failure", failed=sorted(failed), ok=len(succeeded))
        return BatchResult(succeeded=succeeded, failed=failed)

    def _is_fresh(self, stored_at: datetime, ttl: timedelta) -> bool:
        return self._clock() - stored_at < ttl

    async def _cached_bars(self, request: BarsRequest) -> CachedBars | None:
        if self._store is None:
            return None
        try:
            return await asyncio.to_thread(self._store.load_bars, request)
        except (OSError, InvestingLabError) as error:
            # An unreadable cache is a cache miss, never an error for the caller.
            log.warning("cache_read_failed", symbol=request.symbol, error=str(error))
            return None

    @staticmethod
    def _cacheable(candidates: Sequence[MarketDataProvider | TradeFlowProvider]) -> bool:
        """Whether the provider that would answer first lets its answers be cached."""
        return not candidates or candidates[0].capabilities.cacheable

    def _answers(self, cached: CachedBars, request: BarsRequest) -> bool:
        """Whether a cached entry is fresh and covers the request."""
        ttl = self._cache_policy.ttl_for(request.frequency)
        return cached.coverage.covers(request) and self._is_fresh(cached.stored_at, ttl)

    async def _fresh_cached_economic(self, request: EconomicRequest) -> EconomicSeries | None:
        if self._store is None:
            return None
        try:
            cached = await asyncio.to_thread(self._store.load_economic, request)
        except (OSError, InvestingLabError) as error:
            log.warning("cache_read_failed", series_id=request.series_id, error=str(error))
            return None
        if cached is None or not cached.coverage.covers(request):
            return None
        if not self._is_fresh(cached.stored_at, self._cache_policy.economic_ttl):
            return None
        return cached.series

    async def _save_bars(self, series: PriceSeries, request: BarsRequest) -> None:
        if self._store is None:
            return
        try:
            await asyncio.to_thread(self._store.save_bars, series, request)
        except (OSError, InvestingLabError) as error:
            # A cache failure must never lose data the caller already has.
            log.warning("cache_write_failed", symbol=request.symbol, error=str(error))

    async def _save_economic(self, series: EconomicSeries, request: EconomicRequest) -> None:
        if self._store is None:
            return
        try:
            await asyncio.to_thread(self._store.save_economic, series, request)
        except (OSError, InvestingLabError) as error:
            log.warning("cache_write_failed", series_id=request.series_id, error=str(error))


async def _first_answer[P: _Named, T](
    what: str,
    key: str,
    request: str,
    candidates: Sequence[P],
    fetch: Callable[[P], Awaitable[T]],
) -> T:
    """The first answer of the candidates, tried in order (fallback).

    Args:
        what: Kind of data, for the logs (``bars``, ``economic``, ``flow``, ``rates``).
        key: Symbol or series id the data is for.
        request: Description of the request, for the error when no provider serves it.
        candidates: Providers able to serve it, in preference order.
        fetch: Asks one provider; a :class:`ProviderError` moves on to the next one.

    Raises:
        DataUnavailableError: With every failed attempt, or no attempt when no registered
            provider can serve the request.
    """
    if not candidates:
        raise DataUnavailableError(key, (), reason=f"no registered provider can serve {request}")
    attempts: list[FetchAttempt] = []
    for provider in candidates:
        try:
            answer = await fetch(provider)
        except ProviderError as error:
            attempts.append(_attempt(provider.name, error))
            log.warning(
                "provider_failed",
                data=what,
                provider=provider.name,
                key=key,
                error=type(error).__name__,
                detail=str(error),
            )
            continue
        log.info("data_fetched", data=what, provider=provider.name, key=key)
        return answer
    raise DataUnavailableError(key, tuple(attempts))


def _check_bars(provider: str, request: BarsRequest, symbol: str, frequency: Frequency) -> None:
    """Refuse bars or flow of another instrument or frequency than the request's."""
    if (symbol, frequency) != (request.symbol, request.frequency):
        raise ProviderDataError(
            provider,
            f"returned {symbol}/{frequency.value} for {request.symbol}/{request.frequency.value}",
        )


def _attempt(provider: str, error: ProviderError) -> FetchAttempt:
    return FetchAttempt(
        provider=provider,
        error_type=type(error).__name__,
        message=str(error),
        retryable=error.retryable,
    )


def _slice_bars(series: PriceSeries, request: BarsRequest) -> PriceSeries:
    if request.start is None and request.end is None:
        return series
    return series.between(request.start, request.end)


def _starts_within(request: BarsRequest, known: BarsRequest) -> bool:
    """Whether the cached range already reaches back to the request's start."""
    return known.start is None or (request.start is not None and request.start >= known.start)


def _later_end(first: date | None, second: date | None) -> date | None:
    """The later of two inclusive ends, ``None`` meaning "up to the latest"."""
    return None if first is None or second is None else max(first, second)


def _overlap_start(series: PriceSeries, end: date | None) -> date | None:
    """Session date of the first cached bar that an extension downloads again.

    The overlap is made of the last :data:`OVERLAP_BARS` cached bars up to ``end``. ``None``
    when fewer than :data:`MIN_OBSERVATIONS` bars qualify: such a download could not even
    form a valid series, so the whole range is downloaded instead.
    """
    index = pd.DatetimeIndex(series.bars.index)
    if index.tz is not None:  # intraday bars are UTC instants
        index = index.tz_convert(series.timezone)
    sessions = [stamp.date() for stamp in index]
    if end is not None:
        sessions = [session for session in sessions if session <= end]
    if len(sessions) < MIN_OBSERVATIONS:
        return None
    return sessions[-min(OVERLAP_BARS, len(sessions))]


def _append(cached: PriceSeries, fresh: PriceSeries) -> PriceSeries | None:
    """Cached bars followed by a download that overlaps them, or ``None`` if they disagree.

    From its first timestamp on, the download is the authority (it replaces a partial last
    bar, for instance). Older cached bars are kept only if the download comes from the same
    provider with the same columns, currency and adjustment, and reproduces every
    overlapping bar but the last one: a re-adjusted history shows up there.
    """
    old, new = cached.bars, fresh.bars
    if (
        fresh.source.provider != cached.source.provider
        or fresh.adjustment is not cached.adjustment
        or fresh.currency != cached.currency
        or list(new.columns) != list(old.columns)
    ):
        return None
    overlap = old.index.intersection(new.index)
    overlap = overlap[overlap < old.index[-1]]
    prices = [column for column in old.columns if column != PriceField.VOLUME]
    if overlap.empty or not np.allclose(
        old.loc[overlap, prices].to_numpy(dtype="float64"),
        new.loc[overlap, prices].to_numpy(dtype="float64"),
        rtol=PRICE_TOLERANCE,
        atol=0.0,
        equal_nan=True,
    ):
        return None
    return fresh.with_bars(pd.concat([old.loc[old.index < new.index[0]], new]))


def _ensure_unique(keys: list[str]) -> None:
    duplicated = sorted({k for k in keys if keys.count(k) > 1})
    if duplicated:
        raise DomainError(f"Duplicated requests for {duplicated}")
