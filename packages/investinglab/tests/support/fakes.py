"""Test doubles for providers and stores. They serve SYNTHETIC series only."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from investinglab.domain import AssetClass, Frequency
from investinglab.ports import (
    BarsRequest,
    CachedBars,
    CachedEconomicSeries,
    Dataset,
    EconomicRequest,
    ProviderCapabilities,
    SymbolNotFoundError,
)

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import datetime

    from investinglab.domain import EconomicSeries, PriceSeries
    from investinglab.ports import ProviderError

BARS_CAPABILITIES = ProviderCapabilities(
    datasets=frozenset({Dataset.BARS}),
    asset_classes=frozenset(AssetClass),
    frequencies=frozenset(Frequency),
)
ECONOMIC_CAPABILITIES = ProviderCapabilities(datasets=frozenset({Dataset.ECONOMIC}))


@dataclass
class FakeBarsProvider:
    """Serves pre-built series; raises configured errors; records calls."""

    name: str
    series: Mapping[str, PriceSeries] = field(default_factory=dict)
    errors: Mapping[str, ProviderError] = field(default_factory=dict)
    capabilities: ProviderCapabilities = BARS_CAPABILITIES
    delay: float = 0.0
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
            return self.series[request.symbol]
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
class InMemoryStore:
    """Minimal SeriesStore keeping entries in dictionaries."""

    now: datetime
    bars: dict[tuple[str, Frequency], CachedBars] = field(default_factory=dict)
    economic: dict[str, CachedEconomicSeries] = field(default_factory=dict)
    fail_writes: bool = False

    def load_bars(self, request: BarsRequest) -> CachedBars | None:
        return self.bars.get((request.symbol, request.frequency))

    def save_bars(self, series: PriceSeries, coverage: BarsRequest) -> None:
        if self.fail_writes:
            raise OSError("disk full")
        self.bars[series.symbol, series.frequency] = CachedBars(series, coverage, self.now)

    def load_economic(self, request: EconomicRequest) -> CachedEconomicSeries | None:
        return self.economic.get(request.series_id)

    def save_economic(self, series: EconomicSeries, coverage: EconomicRequest) -> None:
        if self.fail_writes:
            raise OSError("disk full")
        self.economic[series.series_id] = CachedEconomicSeries(series, coverage, self.now)
