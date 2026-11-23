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
from typing import TYPE_CHECKING, Final, Protocol, runtime_checkable

from investinglab.domain.errors import DomainError
from investinglab.domain.time import Frequency

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import date, timedelta

    from investinglab.domain.book_depth import BookDepthSeries
    from investinglab.domain.economic import EconomicSeries
    from investinglab.domain.flow import FlowSeries
    from investinglab.domain.instruments import AssetClass
    from investinglab.domain.positioning import PositioningField, PositioningSeries
    from investinglab.domain.rate_series import RateKind, RateSeries
    from investinglab.domain.series import PriceSeries

__all__ = [
    "BarsRequest",
    "BookDepthProvider",
    "BookDepthRequest",
    "Canary",
    "Dataset",
    "EconomicDataProvider",
    "EconomicRequest",
    "HoldingRatesProvider",
    "MarketDataProvider",
    "PositioningProvider",
    "PositioningRequest",
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
    POSITIONING = "positioning"
    """Open interest of a derivative and how traders stand in it (long/short ratios)."""
    BOOK_DEPTH = "book_depth"
    """Depth of an order book within bands around its price, snapshot by snapshot."""
    REFERENCE = "reference"
    """Snapshots of a whole market: its capitalisation, dominance and ranking."""


CANARY_DATASETS: Final = frozenset(
    {Dataset.BARS, Dataset.ECONOMIC, Dataset.HOLDING_RATES, Dataset.REFERENCE}
)
"""Data a canary can ask for: what proves a source answers, and shows how fresh it is."""


@dataclass(frozen=True, slots=True)
class Canary:
    """A small request that proves a provider answers and shows how fresh its data is.

    The source monitor asks it of the provider itself, past every cache and fallback, and
    keeps when the latest observation of the answer is (ADR-0047).

    Attributes:
        dataset: What to ask for: price bars, an economic series, funding or a market
            snapshot.
        symbol: The instrument, series or perpetual asked for; for a market snapshot, the
            asset class (``crypto``).

    Raises:
        DomainError: If the dataset cannot be a canary or the symbol is empty.
    """

    dataset: Dataset
    symbol: str

    def __post_init__(self) -> None:
        if self.dataset not in CANARY_DATASETS:
            raise DomainError(
                f"A canary asks for bars, economic, funding or reference data, not {self.dataset}"
            )
        if not self.symbol.strip():
            raise DomainError("A canary names what it asks for")


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


@dataclass(frozen=True, slots=True)
class PositioningRequest:
    """A request for the positioning snapshots of one derivative on one venue.

    Attributes:
        symbol: Canonical InvestingLab symbol of the derivative (``BTC/USDT:USDT``).
        venue: Venue the snapshots describe; ``None`` lets the router choose.
        start: First day (inclusive, UTC); ``None`` for the full available history.
        end: Last day (inclusive, UTC); ``None`` for "up to the latest".
        frequency: Spacing of the snapshots wanted (5 minutes to a day).
    """

    symbol: str
    venue: str | None = None
    start: date | None = None
    end: date | None = None
    frequency: Frequency = Frequency.HOUR_1

    def __post_init__(self) -> None:
        if not self.symbol.strip():
            raise DomainError("A positioning request needs a symbol")
        if self.start and self.end and self.start > self.end:
            raise DomainError(f"start {self.start} is after end {self.end}")


@dataclass(frozen=True, slots=True)
class BookDepthRequest:
    """A request for the depth of the book of one instrument on one venue.

    Attributes:
        symbol: Canonical InvestingLab symbol (``BTC/USDT:USDT``).
        venue: Venue of the book; ``None`` lets the router choose.
        start: First day (inclusive, UTC); ``None`` for the full available history.
        end: Last day (inclusive, UTC); ``None`` for "up to the latest".
        frequency: Spacing of the snapshots wanted (5 minutes to a day).
    """

    symbol: str
    venue: str | None = None
    start: date | None = None
    end: date | None = None
    frequency: Frequency = Frequency.HOUR_1

    def __post_init__(self) -> None:
        if not self.symbol.strip():
            raise DomainError("A book depth request needs a symbol")
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
        identifiers_by_dataset: The identifiers of a dataset whose symbols are written
            otherwise than the rest (a venue's spot pairs for its bars, its perpetual swaps for
            their funding); ``identifiers`` applies to the datasets not named here.
        frequencies_by_dataset: The frequencies of a dataset served at other frequencies
            than the bars (positioning every 5 minutes or more); ``frequencies`` applies to
            the datasets not named here.
        rate_kinds: Holding rates served (funding, borrow fees, financing costs), for a
            provider of ``Dataset.HOLDING_RATES``.
        positioning_fields: Positioning fields published, for a provider of
            ``Dataset.POSITIONING`` (each venue publishes its own).
        book_bands: Distances from the price (in percent) whose depth is published, for a
            provider of ``Dataset.BOOK_DEPTH``.
        cacheable: Whether what it serves may be cached. A source as fast as the cache that
            its owner edits (local files) is read every time instead, so that an edited file
            is seen at once rather than when the cached copy expires.
        canary: The small request that checks the provider answers (ADR-0047); ``None`` for
            a source not worth checking (local files).

    Raises:
        DomainError: If an identifiers pattern is not a valid regular expression, or the
            canary asks for data or an identifier the provider does not serve.
    """

    datasets: frozenset[Dataset]
    asset_classes: frozenset[AssetClass] = frozenset()
    frequencies: frozenset[Frequency] = frozenset()
    max_history: Mapping[Frequency, timedelta] = field(default_factory=dict, hash=False)
    requires_api_key: bool = False
    rate_limits: tuple[RateLimit, ...] = ()
    identifiers: str | None = None
    identifiers_by_dataset: Mapping[Dataset, str] = field(default_factory=dict, hash=False)
    frequencies_by_dataset: Mapping[Dataset, frozenset[Frequency]] = field(
        default_factory=dict, hash=False
    )
    rate_kinds: frozenset[RateKind] = frozenset()
    positioning_fields: frozenset[PositioningField] = frozenset()
    book_bands: frozenset[float] = frozenset()
    cacheable: bool = True
    canary: Canary | None = None

    def __post_init__(self) -> None:
        if self.canary is not None and self.canary.dataset not in self.datasets:
            raise DomainError(
                f"A canary asks for {self.canary.dataset} data, which the provider does not serve"
            )
        patterns = [self.identifiers, *self.identifiers_by_dataset.values()]
        for pattern in patterns:
            if pattern is None:
                continue
            try:
                re.compile(pattern)
            except re.error as error:
                raise DomainError(f"Invalid identifiers pattern: {error}") from error
        if self.canary is not None and not self._answers(self.canary):
            raise DomainError(
                f"A canary asks for {self.canary.symbol}, which the provider does not serve"
            )

    def _answers(self, canary: Canary) -> bool:
        if canary.dataset is Dataset.REFERENCE:
            return canary.symbol in {asset.value for asset in self.asset_classes}
        return self.serves(canary.symbol, canary.dataset)

    def serves(self, identifier: str, dataset: Dataset | None = None) -> bool:
        """Whether ``identifier`` (a symbol or a series id) can belong to this provider.

        Args:
            identifier: The symbol or series id.
            dataset: The data asked for, when its identifiers differ from the rest.
        """
        pattern = self.identifiers_by_dataset.get(dataset) if dataset else None
        pattern = pattern or self.identifiers
        return pattern is None or re.fullmatch(pattern, identifier) is not None

    def can_serve_bars(self, request: BarsRequest, today: date) -> bool:
        """Whether the provider can, in principle, answer ``request``."""
        return self._can_serve(Dataset.BARS, request, today)

    def can_serve_flow(self, request: BarsRequest, today: date) -> bool:
        """Whether the provider can, in principle, answer the flow of ``request``'s bars.

        Flow follows the same rules as the bars: frequency, identifiers, asset class and
        look-back.
        """
        return self._can_serve(Dataset.FLOW, request, today)

    def frequencies_of(self, dataset: Dataset) -> frozenset[Frequency]:
        """The frequencies ``dataset`` is served at."""
        return self.frequencies_by_dataset.get(dataset, self.frequencies)

    def can_serve_positioning(self, request: PositioningRequest) -> bool:
        """Whether the provider can, in principle, answer ``request``."""
        return (
            Dataset.POSITIONING in self.datasets
            and request.frequency in self.frequencies_of(Dataset.POSITIONING)
            and self.serves(request.symbol, Dataset.POSITIONING)
        )

    def can_serve_book_depth(self, request: BookDepthRequest) -> bool:
        """Whether the provider can, in principle, answer ``request``."""
        return (
            Dataset.BOOK_DEPTH in self.datasets
            and request.frequency in self.frequencies_of(Dataset.BOOK_DEPTH)
            and self.serves(request.symbol, Dataset.BOOK_DEPTH)
        )

    def can_serve_reference(self, asset_class: AssetClass) -> bool:
        """Whether the provider gives the reference data of the market of ``asset_class``."""
        return Dataset.REFERENCE in self.datasets and asset_class in self.asset_classes

    def can_serve_rates(self, request: RatesRequest) -> bool:
        """Whether the provider can, in principle, answer ``request``."""
        return (
            Dataset.HOLDING_RATES in self.datasets
            and request.kind in self.rate_kinds
            and self.serves(request.symbol, Dataset.HOLDING_RATES)
        )

    def _can_serve(self, dataset: Dataset, request: BarsRequest, today: date) -> bool:
        if dataset not in self.datasets or request.frequency not in self.frequencies_of(dataset):
            return False
        if not self.serves(request.symbol, dataset):
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
        return Dataset.ECONOMIC in self.datasets and self.serves(
            request.series_id, Dataset.ECONOMIC
        )


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


@runtime_checkable
class PositioningProvider(Protocol):
    """Source of positioning in derivatives: open interest and long/short ratios."""

    @property
    def name(self) -> str:
        """Provider slug, also the venue the snapshots describe."""
        ...

    @property
    def capabilities(self) -> ProviderCapabilities:
        """What the provider serves; positioning needs ``Dataset.POSITIONING``."""
        ...

    async def fetch_positioning(self, request: PositioningRequest) -> PositioningSeries:
        """Download the snapshots a request describes, at its frequency.

        Raises:
            ProviderError: With the same meaning as for price bars.
        """
        ...


@runtime_checkable
class BookDepthProvider(Protocol):
    """Source of the depth of an order book within bands around its price."""

    @property
    def name(self) -> str:
        """Provider slug, also the venue whose book it is."""
        ...

    @property
    def capabilities(self) -> ProviderCapabilities:
        """What the provider serves; book depth needs ``Dataset.BOOK_DEPTH``."""
        ...

    async def fetch_book_depth(self, request: BookDepthRequest) -> BookDepthSeries:
        """Download the snapshots a request describes, at its frequency.

        Raises:
            ProviderError: With the same meaning as for price bars.
        """
        ...
