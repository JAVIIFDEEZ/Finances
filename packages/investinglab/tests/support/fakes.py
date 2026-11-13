"""Test doubles for providers and stores. They serve SYNTHETIC series only."""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from investinglab.domain import AssetClass, Frequency, RateKind
from investinglab.ports import (
    BarsRequest,
    CachedBars,
    CachedEconomicSeries,
    Dataset,
    EconomicRequest,
    ProviderCapabilities,
    RatesRequest,
    SymbolNotFoundError,
)

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import datetime

    from investinglab.domain import EconomicSeries, FlowSeries, PriceSeries, RateSeries
    from investinglab.ports import ProviderError

BARS_CAPABILITIES = ProviderCapabilities(
    datasets=frozenset({Dataset.BARS}),
    asset_classes=frozenset(AssetClass),
    frequencies=frozenset(Frequency),
)
ECONOMIC_CAPABILITIES = ProviderCapabilities(datasets=frozenset({Dataset.ECONOMIC}))
FLOW_CAPABILITIES = ProviderCapabilities(
    datasets=frozenset({Dataset.FLOW}),
    asset_classes=frozenset(AssetClass),
    frequencies=frozenset(Frequency),
)
RATES_CAPABILITIES = ProviderCapabilities(
    datasets=frozenset({Dataset.HOLDING_RATES}), rate_kinds=frozenset(RateKind)
)


@dataclass
class FakeBarsProvider:
    """Serves pre-built series; raises configured errors; records calls.

    With ``slice_requests`` it answers only the requested dates, like a real provider.
    """

    name: str
    series: Mapping[str, PriceSeries] = field(default_factory=dict)
    errors: Mapping[str, ProviderError] = field(default_factory=dict)
    capabilities: ProviderCapabilities = BARS_CAPABILITIES
    delay: float = 0.0
    slice_requests: bool = False
    calls: list[BarsRequest] = field(default_factory=list)
    in_flight: int = 0
    max_in_flight: int = 0

    async def fetch_bars(self, request: BarsRequest) -> PriceSeries:
        self.calls.append(request)
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            if self.delay:
                await asyncio.sleep(self.delay)
            if request.symbol in self.errors:
                raise self.errors[request.symbol]
            if request.symbol not in self.series:
                raise SymbolNotFoundError(self.name, f"unknown symbol {request.symbol}")
            series = self.series[request.symbol]
            if self.slice_requests:
                return series.between(request.start, request.end)
            return series
        finally:
            self.in_flight -= 1


@dataclass
class FakeEconomicProvider:
    """Serves pre-built economic series."""

    name: str
    series: Mapping[str, EconomicSeries] = field(default_factory=dict)
    errors: Mapping[str, ProviderError] = field(default_factory=dict)
    capabilities: ProviderCapabilities = ECONOMIC_CAPABILITIES
    calls: list[EconomicRequest] = field(default_factory=list)

    async def fetch_economic_series(self, request: EconomicRequest) -> EconomicSeries:
        self.calls.append(request)
        if request.series_id in self.errors:
            raise self.errors[request.series_id]
        if request.series_id not in self.series:
            raise SymbolNotFoundError(self.name, f"unknown series {request.series_id}")
        return self.series[request.series_id]


@dataclass
class FakeFlowProvider:
    """Serves pre-built flow by symbol; raises configured errors; records calls."""

    name: str
    flow: Mapping[str, FlowSeries] = field(default_factory=dict)
    errors: Mapping[str, ProviderError] = field(default_factory=dict)
    capabilities: ProviderCapabilities = FLOW_CAPABILITIES
    calls: list[BarsRequest] = field(default_factory=list)

    async def fetch_flow(self, request: BarsRequest) -> FlowSeries:
        self.calls.append(request)
        if request.symbol in self.errors:
            raise self.errors[request.symbol]
        if request.symbol not in self.flow:
            raise SymbolNotFoundError(self.name, f"unknown symbol {request.symbol}")
        return self.flow[request.symbol]


@dataclass
class FakeRatesProvider:
    """Serves pre-built holding rates by symbol; raises configured errors; records calls."""

    name: str
    rates: Mapping[str, RateSeries] = field(default_factory=dict)
    errors: Mapping[str, ProviderError] = field(default_factory=dict)
    capabilities: ProviderCapabilities = RATES_CAPABILITIES
    calls: list[RatesRequest] = field(default_factory=list)

    async def fetch_rates(self, request: RatesRequest) -> RateSeries:
        self.calls.append(request)
        if request.symbol in self.errors:
            raise self.errors[request.symbol]
        if request.symbol not in self.rates:
            raise SymbolNotFoundError(self.name, f"unknown symbol {request.symbol}")
        return self.rates[request.symbol]


@dataclass
class InMemoryStore:
    """Minimal SeriesStore keeping entries in dictionaries; records the calling threads."""

    now: datetime
    bars: dict[tuple[str, Frequency], CachedBars] = field(default_factory=dict)
    economic: dict[str, CachedEconomicSeries] = field(default_factory=dict)
    fail_reads: bool = False
    fail_writes: bool = False
    threads: list[str] = field(default_factory=list)

    def load_bars(self, request: BarsRequest) -> CachedBars | None:
        self._enter(write=False)
        return self.bars.get((request.symbol, request.frequency))

    def save_bars(self, series: PriceSeries, coverage: BarsRequest) -> None:
        self._enter(write=True)
        self.bars[series.symbol, series.frequency] = CachedBars(series, coverage, self.now)

    def load_economic(self, request: EconomicRequest) -> CachedEconomicSeries | None:
        self._enter(write=False)
        return self.economic.get(request.series_id)

    def save_economic(self, series: EconomicSeries, coverage: EconomicRequest) -> None:
        self._enter(write=True)
        self.economic[series.series_id] = CachedEconomicSeries(series, coverage, self.now)

    def _enter(self, *, write: bool) -> None:
        self.threads.append(threading.current_thread().name)
        if self.fail_writes if write else self.fail_reads:
            raise OSError("disk full" if write else "unreadable")
