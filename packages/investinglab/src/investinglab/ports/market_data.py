"""Ports for market and economic data providers.

A provider is any object implementing :class:`MarketDataProvider` and/or
:class:`EconomicDataProvider`. Whatever API sits behind it, it always returns domain objects
(:class:`~investinglab.domain.PriceSeries`, :class:`~investinglab.domain.EconomicSeries`):
never raw provider payloads. Adding a provider means writing one adapter and registering it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from investinglab.domain.errors import DomainError
from investinglab.domain.time import Frequency

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import date, timedelta

    from investinglab.domain.economic import EconomicSeries
    from investinglab.domain.flow import FlowSeries
    from investinglab.domain.instruments import AssetClass
    from investinglab.domain.rate_series import RateKind, RateSeries
    from investinglab.domain.series import PriceSeries

__all__ = [
    "BarsRequest",
    "Dataset",
    "EconomicDataProvider",
    "EconomicRequest",
    "HoldingRatesProvider",
    "MarketDataProvider",
    "ProviderCapabilities",
    "RateLimit",
    "RatesRequest",
    "TradeFlowProvider",
    "VintageMode",
]


class Dataset(StrEnum):
    """Kind of data a provider serves."""

    BARS = "bars"
    """Price bars (OHLCV / adjusted close) of tradable instruments."""
    ECONOMIC = "economic"
    """Macroeconomic and rate series."""
    FLOW = "flow"
    """Trade flow per bar: value traded, number of trades and aggressor side."""
    HOLDING_RATES = "holding_rates"
    """What a position pays or earns per period: funding, borrow fees, financing."""


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


@dataclass(frozen=True, slots=True)
class RatesRequest:
    """A request for the holding rates of one instrument on one venue.

    Attributes:
        symbol: Canonical InvestingLab symbol of the instrument held.
        kind: Which rate (funding, borrow fee, financing cost).
        venue: Venue the rates apply on; ``None`` lets the provider use its own.
        start: First day (inclusive); ``None`` for the full available history.
        end: Last day (inclusive); ``None`` for "up to the latest".
    """

    symbol: str
    kind: RateKind
    venue: str | None = None
    start: date | None = None
    end: date | None = None

    def __post_init__(self) -> None:
        if not self.symbol.strip():
            raise DomainError("A rates request needs a symbol")
        if self.start and self.end and self.start > self.end:
            raise DomainError(f"start {self.start} is after end {self.end}")


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
        identifiers: Regular expression every symbol and series id served matches, for a
            provider with a closed universe (the ECB's currency pairs, a local catalogue) or
            its own notation (a venue's ``BASE/QUOTE`` pairs); ``None`` when any identifier
            may be served. The router skips the provider for other identifiers instead of
            asking it.
        rate_kinds: Holding rates served (funding, borrow fees, financing costs), for a
            provider of ``Dataset.HOLDING_RATES``.
        cacheable: Whether what it serves may be cached. A source as fast as the cache that
            its owner edits (local files) is read every time instead, so that an edited file
            is seen at once rather than when the cached copy expires.

    Raises:
        DomainError: If ``identifiers`` is not a valid regular expression.
    """

    datasets: frozenset[Dataset]
    asset_classes: frozenset[AssetClass] = frozenset()
    frequencies: frozenset[Frequency] = frozenset()
    max_history: Mapping[Frequency, timedelta] = field(default_factory=dict, hash=False)
    requires_api_key: bool = False
    rate_limits: tuple[RateLimit, ...] = ()
    identifiers: str | None = None
    rate_kinds: frozenset[RateKind] = frozenset()
    cacheable: bool = True

    def __post_init__(self) -> None:
        if self.identifiers is not None:
            try:
                re.compile(self.identifiers)
            except re.error as error:
                raise DomainError(f"Invalid identifiers pattern: {error}") from error

    def serves(self, identifier: str) -> bool:
        """Whether ``identifier`` (a symbol or a series id) can belong to this provider."""
        return self.identifiers is None or re.fullmatch(self.identifiers, identifier) is not None

    def can_serve_bars(self, request: BarsRequest, today: date) -> bool:
        """Whether the provider can, in principle, answer ``request``."""
        return self._can_serve(Dataset.BARS, request, today)

    def can_serve_flow(self, request: BarsRequest, today: date) -> bool:
        """Whether the provider can, in principle, answer the flow of ``request``'s bars.

        Flow follows the same rules as the bars: frequency, identifiers, asset class and
        look-back.
        """
        return self._can_serve(Dataset.FLOW, request, today)

    def can_serve_rates(self, request: RatesRequest) -> bool:
        """Whether the provider can, in principle, answer ``request``."""
        return (
            Dataset.HOLDING_RATES in self.datasets
            and request.kind in self.rate_kinds
            and self.serves(request.symbol)
        )

    def _can_serve(self, dataset: Dataset, request: BarsRequest, today: date) -> bool:
        if dataset not in self.datasets or request.frequency not in self.frequencies:
            return False
        if not self.serves(request.symbol):
            return False
        if request.asset_class is not None and request.asset_class not in self.asset_classes:
            return False
        limit = self.max_history.get(request.frequency)
        if limit is None:
            return True
        earliest = today - limit
        return request.start is not None and request.start >= earliest

    def can_serve_economic(self, request: EconomicRequest) -> bool:
        """Whether the provider can, in principle, answer ``request``."""
        return Dataset.ECONOMIC in self.datasets and self.serves(request.series_id)


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


@runtime_checkable
class TradeFlowProvider(Protocol):
    """Source of trade flow per bar, for the same requests as the price bars.

    A provider of any asset class can implement it: what it needs is a venue that reports
    the value traded, the number of trades or the aggressor side of each bar.
    """

    @property
    def name(self) -> str:
        """Provider slug, also used in ``DataSource``."""
        ...

    @property
    def capabilities(self) -> ProviderCapabilities:
        """What the provider serves; flow needs ``Dataset.FLOW``."""
        ...

    async def fetch_flow(self, request: BarsRequest) -> FlowSeries:
        """Download the flow of the bars a request describes.

        Raises:
            ProviderError: With the same meaning as for price bars.
        """
        ...


@runtime_checkable
class HoldingRatesProvider(Protocol):
    """Source of holding rates: funding, borrow fees and financing costs."""

    @property
    def name(self) -> str:
        """Provider slug, also used in ``DataSource``."""
        ...

    @property
    def capabilities(self) -> ProviderCapabilities:
        """What the provider serves; rates need ``Dataset.HOLDING_RATES``."""
        ...

    async def fetch_rates(self, request: RatesRequest) -> RateSeries:
        """Download the rates a request describes.

        Raises:
            ProviderError: With the same meaning as for price bars.
        """
        ...
