"""Check that each data source answers, and how fresh its data is (ADR-0047).

Every provider that declares a :class:`~investinglab.ports.Canary` is asked it directly, past
the market-data service: no cache, no fallback to another source, so the answer is that
source's own. The checks run at once, each within :data:`CHECK_TIMEOUT`, and a failure is a
heartbeat that says so, never an exception: one silent source must not hide the others.

The *latest observation* is read from the answer: the start of the last bar (a daily bar's
session date, at midnight UTC), the last observation of an economic series, the last funding
settled, the instant a market snapshot describes.
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Final

import pandas as pd

from investinglab.domain.errors import DomainError
from investinglab.domain.heartbeat import SourceHeartbeat
from investinglab.domain.instruments import AssetClass
from investinglab.domain.rate_series import RateKind
from investinglab.ports.market_data import (
    BarsRequest,
    Dataset,
    EconomicDataProvider,
    EconomicRequest,
    HoldingRatesProvider,
    MarketDataProvider,
    RatesRequest,
)
from investinglab.ports.reference import MarketSnapshotRequest, ReferenceDataProvider

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from investinglab.ports.market_data import Canary
    from investinglab.services.registry import AnyProvider

__all__ = ["CHECK_TIMEOUT", "LOOKBACK", "check_source", "check_sources", "latest_instant"]

CHECK_TIMEOUT: Final = 30.0
"""Seconds a source gets to answer its canary."""

LOOKBACK: Final[dict[Dataset, timedelta]] = {
    Dataset.BARS: timedelta(days=10),
    Dataset.ECONOMIC: timedelta(days=120),
    Dataset.HOLDING_RATES: timedelta(days=7),
}
"""History asked for: enough for a few observations of each, across weekends and holidays."""

MAX_ERROR: Final = 300
"""Longest error text kept: the kind of error and the start of its message."""


def _now() -> datetime:
    return datetime.now(UTC)


def latest_instant(moment: pd.Timestamp | datetime | date) -> datetime:
    """An observation's position in time as an aware instant (a date at midnight UTC)."""
    stamp = pd.Timestamp(moment)
    stamp = stamp.tz_localize(UTC) if stamp.tzinfo is None else stamp.tz_convert(UTC)
    return stamp.to_pydatetime()


async def _ask(provider: AnyProvider, canary: Canary, today: date) -> datetime:
    """Ask the canary and return the instant of the latest observation answered."""
    start = today - LOOKBACK.get(canary.dataset, timedelta(0))
    if canary.dataset is Dataset.BARS and isinstance(provider, MarketDataProvider):
        series = await provider.fetch_bars(BarsRequest(canary.symbol, start=start))
        return latest_instant(series.end)
    if canary.dataset is Dataset.ECONOMIC and isinstance(provider, EconomicDataProvider):
        economic = await provider.fetch_economic_series(EconomicRequest(canary.symbol, start=start))
        return latest_instant(economic.latest().index[-1])  # a series has an observation
    if canary.dataset is Dataset.HOLDING_RATES and isinstance(provider, HoldingRatesProvider):
        rates = await provider.fetch_rates(
            RatesRequest(canary.symbol, RateKind.FUNDING, start=start)
        )
        return latest_instant(rates.end)
    if canary.dataset is Dataset.REFERENCE and isinstance(provider, ReferenceDataProvider):
        request = MarketSnapshotRequest(AssetClass(canary.symbol))
        snapshot = await provider.fetch_market_snapshot(request)
        return latest_instant(snapshot.as_of)
    raise DomainError(f"{provider.name} declares a {canary.dataset} canary it cannot answer")


def _describe(error: BaseException) -> str:
    text = f"{type(error).__name__}: {error}".strip().removesuffix(":")
    return text if len(text) <= MAX_ERROR else f"{text[: MAX_ERROR - 1]}…"


async def check_source(
    provider: AnyProvider,
    *,
    within: float = CHECK_TIMEOUT,
    clock: Callable[[], datetime] = _now,
) -> SourceHeartbeat | None:
    """One check of ``provider``, given ``within`` seconds; ``None`` without a canary.

    Never raises for a failure of the source: the heartbeat says what went wrong.
    """
    canary = provider.capabilities.canary
    if canary is None:
        return None
    checked_at = clock()
    started = time.perf_counter()
    try:
        async with asyncio.timeout(within):
            latest = await _ask(provider, canary, checked_at.date())
    except TimeoutError:
        error = f"TimeoutError: no answer within {within:g} s"
    except Exception as failure:  # a failing source is a heartbeat, never a crash
        error = _describe(failure)
    else:
        elapsed = time.perf_counter() - started
        return SourceHeartbeat(provider.name, checked_at, ok=True, latency=elapsed, latest=latest)
    elapsed = time.perf_counter() - started
    return SourceHeartbeat(provider.name, checked_at, ok=False, latency=elapsed, error=error)


async def check_sources(
    providers: Iterable[AnyProvider],
    *,
    within: float = CHECK_TIMEOUT,
    clock: Callable[[], datetime] = _now,
) -> tuple[SourceHeartbeat, ...]:
    """Check every provider with a canary at once, each given ``within`` seconds."""
    checks = await asyncio.gather(
        *(check_source(provider, within=within, clock=clock) for provider in providers)
    )
    return tuple(heartbeat for heartbeat in checks if heartbeat is not None)
