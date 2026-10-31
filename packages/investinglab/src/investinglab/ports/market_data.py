"""Ports for market and economic data providers.

A provider is any object implementing :class:`MarketDataProvider` and/or
:class:`EconomicDataProvider`. Whatever API sits behind it, it always returns domain objects
(:class:`~investinglab.domain.PriceSeries`, :class:`~investinglab.domain.EconomicSeries`):
never raw provider payloads. Adding a provider means writing one adapter and registering it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from investinglab.domain.errors import DomainError
from investinglab.domain.time import Frequency

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import date, timedelta

    from investinglab.domain.economic import EconomicSeries
    from investinglab.domain.instruments import AssetClass
    from investinglab.domain.series import PriceSeries

__all__ = [
    "BarsRequest",
    "Dataset",
    "EconomicDataProvider",
    "EconomicRequest",
    "MarketDataProvider",
    "ProviderCapabilities",
    "RateLimit",
    "VintageMode",
]


class Dataset(StrEnum):
    """Kind of data a provider serves."""

    BARS = "bars"
    """Price bars (OHLCV / adjusted close) of tradable instruments."""
    ECONOMIC = "economic"
    """Macroeconomic and rate series."""


@dataclass(frozen=True, slots=True)
class RateLimit:
    """A provider quota: at most ``max_calls`` per ``period_seconds``."""

    max_calls: int
    period_seconds: float

    def __post_init__(self) -> None:
        if self.max_calls < 1 or self.period_seconds <= 0:
            raise DomainError(f"Invalid rate limit {self.max_calls}/{self.period_seconds}s")


@dataclass(frozen=True, slots=True)
class BarsRequest:
    """A request for the price bars of one instrument.

    Attributes:
        symbol: Canonical InvestingLab symbol (``SAN.MC``, ``^GSPC``, ``EURUSD=X``...).
        frequency: Bar frequency.
        start: First session date (inclusive); ``None`` for the full available history.
        end: Last session date (inclusive); ``None`` for "up to the latest".
        asset_class: Optional hint that lets the router skip providers that cannot serve
            this kind of instrument.
    """

    symbol: str
    frequency: Frequency = Frequency.DAY_1
    start: date | None = None
    end: date | None = None
    asset_class: AssetClass | None = None

    def __post_init__(self) -> None:
        if not self.symbol.strip():
            raise DomainError("A bars request needs a symbol")
        if self.start and self.end and self.start > self.end:
            raise DomainError(f"start {self.start} is after end {self.end}")

    def covers(self, other: BarsRequest) -> bool:
        """Whether data fetched for this request also answers ``other``.

        Same symbol and frequency, and a date range that contains ``other``'s range
        (``None`` meaning unbounded).
        """
        if (self.symbol, self.frequency) != (other.symbol, other.frequency):
            return False
        starts_ok = self.start is None or (other.start is not None and other.start >= self.start)
        ends_ok = self.end is None or (other.end is not None and other.end <= self.end)
        return starts_ok and ends_ok


class VintageMode(StrEnum):
    """Which published versions of an economic series to retrieve (ADR-0009)."""

    FIRST_RELEASE = "first_release"
    """Only the first published value of each observation (point-in-time, compact)."""
    ALL_VINTAGES = "all_vintages"
    """Every published revision with its publication date (full bitemporal history)."""
    LATEST = "latest"
    """Only the latest revision (not point-in-time; for exploration)."""


@dataclass(frozen=True, slots=True)
class EconomicRequest:
    """A request for an economic series.

    Attributes:
        series_id: Provider identifier (``DGS3MO``, ``UNRATE``...).
        start: First observation date (inclusive), ``None`` for the full history.
        end: Last observation date (inclusive), ``None`` for "up to the latest".
        mode: Vintages to retrieve; point-in-time first releases by default.
    """

    series_id: str
    start: date | None = None
    end: date | None = None
    mode: VintageMode = VintageMode.FIRST_RELEASE

    def __post_init__(self) -> None:
        if not self.series_id.strip():
            raise DomainError("An economic request needs a series id")
        if self.start and self.end and self.start > self.end:
            raise DomainError(f"start {self.start} is after end {self.end}")

    def covers(self, other: EconomicRequest) -> bool:
        """Whether data fetched for this request also answers ``other``.

        All vintages answer any mode; otherwise the modes must match. Date ranges follow
        the same rule as :meth:`BarsRequest.covers`.
        """
        if self.series_id != other.series_id:
            return False
        if self.mode is not VintageMode.ALL_VINTAGES and self.mode is not other.mode:
            return False
        starts_ok = self.start is None or (other.start is not None and other.start >= self.start)
        ends_ok = self.end is None or (other.end is not None and other.end <= self.end)
        return starts_ok and ends_ok


@dataclass(frozen=True, slots=True)
class ProviderCapabilities:
    """What a provider can serve, used by the router to pick candidates.

    Attributes:
        datasets: Kinds of data served.
        asset_classes: Asset classes served for price bars (empty for macro-only providers).
        frequencies: Bar frequencies served.
        max_history: Maximum look-back per frequency, when the provider limits it (e.g. one
            year of hourly bars). Missing frequencies have no known limit.
        requires_api_key: Whether a credential must be configured.
        rate_limits: Quotas to respect (all of them apply).
    """

    datasets: frozenset[Dataset]
    asset_classes: frozenset[AssetClass] = frozenset()
    frequencies: frozenset[Frequency] = frozenset()
    max_history: Mapping[Frequency, timedelta] = field(default_factory=dict, hash=False)
    requires_api_key: bool = False
    rate_limits: tuple[RateLimit, ...] = ()

    def can_serve_bars(self, request: BarsRequest, today: date) -> bool:
        """Whether the provider can, in principle, answer ``request``."""
        if Dataset.BARS not in self.datasets or request.frequency not in self.frequencies:
            return False
        if request.asset_class is not None and request.asset_class not in self.asset_classes:
            return False
        limit = self.max_history.get(request.frequency)
        if limit is None:
            return True
        earliest = today - limit
        return request.start is not None and request.start >= earliest


@runtime_checkable
class MarketDataProvider(Protocol):
    """Source of price bars."""

    @property
    def name(self) -> str:
        """Provider slug (``yahoo``, ``alphavantage``...), also used in ``DataSource``."""
        ...

    @property
    def capabilities(self) -> ProviderCapabilities:
        """What the provider can serve."""
        ...

    async def fetch_bars(self, request: BarsRequest) -> PriceSeries:
        """Download the bars of one instrument and return a validated domain series.

        Raises:
            ProviderError: Any failure, translated to the port's error types.
        """
        ...


@runtime_checkable
class EconomicDataProvider(Protocol):
    """Source of economic series."""

    @property
    def name(self) -> str:
        """Provider slug."""
        ...

    @property
    def capabilities(self) -> ProviderCapabilities:
        """What the provider can serve."""
        ...

    async def fetch_economic_series(self, request: EconomicRequest) -> EconomicSeries:
        """Download an economic series with its publication dates.

        Raises:
            ProviderError: Any failure, translated to the port's error types.
        """
        ...
