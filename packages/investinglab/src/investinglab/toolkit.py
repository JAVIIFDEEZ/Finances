"""Public facade and composition root for notebooks and scripts (B1-T1).

One object gives access to the whole platform: download several series at once from every
configured source, build portfolios in a base currency, diagnose data quality against the
official calendars and write reports that already use the point-in-time risk-free rate::

    from investinglab.toolkit import Toolkit

    with Toolkit.from_settings() as tk:
        batch = tk.many(["SAN.MC", "ITX.MC", "IBE.MC"], start="2019-01-01")
        portfolio = tk.portfolio("Core", {"SAN.MC": 0.4, "ITX.MC": 0.3, "IBE.MC": 0.3})
        tk.report(portfolio).save("core.md")

:class:`Toolkit` is synchronous and works both in scripts and inside Jupyter (it runs the
asynchronous :class:`AsyncToolkit` on its own event-loop thread); use :class:`AsyncToolkit`
directly from async code. This module is the only place, besides the API's bootstrap,
where adapters are instantiated (ADR-0002).
"""

from __future__ import annotations

import asyncio
import contextlib
import re
import threading
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Any, Final, Self, Unpack

import pandas as pd

from investinglab.adapters.calendars import ExchangeCalendarsAdapter
from investinglab.adapters.files import ImportSpec, SeriesImporter
from investinglab.adapters.http import RetryPolicy
from investinglab.adapters.providers.alternative_me import AlternativeMeProvider
from investinglab.adapters.providers.binance import BinanceProvider
from investinglab.adapters.providers.coinbase import CoinbaseProvider
from investinglab.adapters.providers.coingecko import CoinGeckoProvider
from investinglab.adapters.providers.deribit import DeribitProvider
from investinglab.adapters.providers.ecb import EcbProvider
from investinglab.adapters.providers.files import LocalFilesProvider
from investinglab.adapters.providers.kraken import KrakenProvider
from investinglab.adapters.providers.okx import OkxProvider
from investinglab.adapters.providers.yahoo import YahooFinanceProvider
from investinglab.adapters.storage import ParquetSeriesStore, PublishedFileCache
from investinglab.config.logging import get_logger
from investinglab.config.settings import Settings, get_settings
from investinglab.domain.card import Pillar, asset_card, pillars_for
from investinglab.domain.confluence import timeframe_confluence
from investinglab.domain.errors import DomainError, InvalidSeriesError, InvestingLabError
from investinglab.domain.instruments import AssetClass
from investinglab.domain.metrics import DEFAULT_CONFIDENCE_LEVELS
from investinglab.domain.money import Currency
from investinglab.domain.patterns import price_patterns
from investinglab.domain.portfolio import Portfolio
from investinglab.domain.rate_series import RateKind
from investinglab.domain.structure import price_structure
from investinglab.domain.technical import technical_indicators
from investinglab.domain.time import Frequency
from investinglab.ports.market_data import (
    BarsRequest,
    BookDepthRequest,
    Dataset,
    EconomicRequest,
    PositioningRequest,
    RatesRequest,
    VintageMode,
)
from investinglab.ports.reference import MarketCapRequest, MarketSnapshotRequest
from investinglab.reporting.options import ReportOptions
from investinglab.services.fx import CurrencyService
from investinglab.services.market_data import DataUnavailableError, MarketDataService
from investinglab.services.quality import DataQualityService
from investinglab.services.registry import ProviderRegistry
from investinglab.services.risk_free import RiskFreeRateService

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine, Iterable, Mapping, Sequence
    from concurrent.futures import Future
    from pathlib import Path
    from types import TracebackType

    from investinglab.domain.book_depth import BookDepthSeries
    from investinglab.domain.card import AssetCard
    from investinglab.domain.confluence import TimeframeConfluence
    from investinglab.domain.economic import EconomicSeries
    from investinglab.domain.flow import FlowSeries
    from investinglab.domain.market_reference import MarketCapRanking, MarketSnapshot
    from investinglab.domain.metrics import RiskMetrics
    from investinglab.domain.patterns import PricePatterns
    from investinglab.domain.portfolio import RebalancePolicy
    from investinglab.domain.positioning import PositioningSeries
    from investinglab.domain.quality import DataQualityReport
    from investinglab.domain.rate_series import RateSeries
    from investinglab.domain.series import PriceSeries
    from investinglab.domain.structure import PriceStructure
    from investinglab.domain.technical import TechnicalIndicators
    from investinglab.ports.market_data import ProviderCapabilities
    from investinglab.reporting.markdown import MarkdownReport
    from investinglab.reporting.options import ReportSettings
    from investinglab.services.market_data import BatchResult
    from investinglab.services.registry import AnyProvider

__all__ = ["AsyncToolkit", "Toolkit"]

log = get_logger(__name__)

type DateLike = date | datetime | pd.Timestamp | str | None
type RemoteProvider = (
    EcbProvider
    | YahooFinanceProvider
    | BinanceProvider
    | KrakenProvider
    | CoinbaseProvider
    | OkxProvider
    | DeribitProvider
    | AlternativeMeProvider
    | CoinGeckoProvider
)


def _as_date(value: DateLike) -> date | None:
    return None if value is None else pd.Timestamp(value).date()


CONFLUENCE_FRAMES: Final = (Frequency.DAY_1, Frequency.WEEK_1, Frequency.MONTH_1)
"""Frames read by default: every source serves daily bars, and the other two derive from them."""

CONFLUENCE_HISTORY: Final[dict[Frequency, timedelta]] = {
    Frequency.MINUTE_15: timedelta(days=21),
    Frequency.MINUTE_30: timedelta(days=40),
    Frequency.HOUR_1: timedelta(days=75),
    Frequency.HOUR_4: timedelta(days=300),
    Frequency.DAY_1: timedelta(days=450),
    Frequency.WEEK_1: timedelta(days=6 * 366),
    Frequency.MONTH_1: timedelta(days=12 * 366),
}
"""Frames the confluence can read, with the history fetched for each.

About 300 bars of an exchange with a short session (more of a market that never closes), so
that the panel's averages have settled; within what the sources keep of each frequency.
"""

CARD_HISTORY: Final = timedelta(days=3 * 366)
"""Daily bars a card reads its risk, structure and data quality from: three years."""

CARD_FUNDING: Final = timedelta(days=90)
"""Funding payments a card reads: a quarter."""

CARD_POSITIONING: Final = timedelta(days=30)
"""Daily positioning a card reads; the change of the open interest is measured over it."""

_SPOT_PAIR: Final = re.compile(r"^([A-Z0-9]{2,15})/([A-Z0-9]{2,10})$")


def _perpetual_of(symbol: str) -> str | None:
    """The linear perpetual swap of a venue's spot pair (``BTC/USDT`` → ``BTC/USDT:USDT``).

    ``None`` for any other notation: a symbol that does not name its quote asset does not
    say which swap is its own.
    """
    pair = _SPOT_PAIR.match(symbol)
    return None if pair is None else f"{pair[1]}/{pair[2]}:{pair[2]}"


WARMUP: Final[dict[Frequency, timedelta]] = {
    Frequency.DAY_1: timedelta(days=400),
    Frequency.WEEK_1: timedelta(days=5 * 366),
    Frequency.MONTH_1: timedelta(days=20 * 366),
    Frequency.QUARTER_1: timedelta(days=40 * 366),
    Frequency.YEAR_1: timedelta(days=60 * 366),
}
"""History fetched before the start so that the indicators are warm at the first date shown.

The patterns use it too: an order block or a swing set up before the start counts after it.

About 250 bars, enough for a 200-bar average or a triple exponential average. Intraday bars
get none: providers keep little intraday history, so their warm-up shows.
"""


def _remote_providers(
    config: Settings, registry: ProviderRegistry, *, cache: bool = True
) -> list[RemoteProvider]:
    """Default remote providers, in order, except those a caller's provider replaces.

    The ECB comes first: its reference rates are the official daily fixings of the euro
    and it only serves currency pairs and euro rates. Yahoo serves every other symbol of
    its own notation (``SAN.MC``, ``^GSPC``, ``BTC-USD``...). The venues serve theirs:
    the spot pairs written ``BASE/QUOTE`` come from Binance, with their trade flow, and fall
    back on Kraken (its last 720 bars) and Coinbase, which also list the pairs in dollars and
    euros. The funding of perpetual swaps written ``BASE/QUOTE:SETTLE`` comes from OKX's
    API, up to date, and from Binance's monthly dumps, which keep the whole history
    (ADR-0032, ADR-0041); Deribit adds the hourly funding of its perpetuals in dollars and
    USDC; ``venue`` picks one. alternative.me
    publishes the crypto Fear & Greed Index (``FNG``), and CoinGecko the size, dominance and
    ranking of the crypto market (ADR-0045).

    With ``cache``, Binance keeps the dump files it verifies under
    ``<cache_dir>/dumps/binance`` and reads them from there while they are not published
    again (ADR-0043).
    """
    retry = RetryPolicy(max_attempts=config.http_max_attempts)
    timeout = config.http_timeout_seconds
    dumps = PublishedFileCache(config.effective_cache_dir / "dumps" / "binance") if cache else None
    factories: dict[str, Callable[[], RemoteProvider]] = {
        "ecb": lambda: EcbProvider(timeout=timeout, retry=retry),
        "yahoo": lambda: YahooFinanceProvider(timeout=timeout, retry=retry),
        "binance": lambda: BinanceProvider(timeout=timeout, retry=retry, dump_cache=dumps),
        "kraken": lambda: KrakenProvider(timeout=timeout, retry=retry),
        "coinbase": lambda: CoinbaseProvider(timeout=timeout, retry=retry),
        "okx": lambda: OkxProvider(timeout=timeout, retry=retry),
        "deribit": lambda: DeribitProvider(timeout=timeout, retry=retry),
        "alternative_me": lambda: AlternativeMeProvider(timeout=timeout, retry=retry),
        "coingecko": lambda: CoinGeckoProvider(
            api_key=config.coingecko_api_key, timeout=timeout, retry=retry
        ),
    }
    return [build() for name, build in factories.items() if name not in registry]


FUNDING_ORDER: Final = ("okx", "binance", "deribit")
"""Venues asked for funding when none is named: OKX's API is up to date, and Binance's
monthly dumps (published once each month ends) add the history OKX does not keep. Deribit
comes last: its funding accrues every hour, a different period from the others' payments, so
it answers when named (``venue="deribit"``) or when they cannot."""


POSITIONING_ORDER: Final = ("okx", "binance")
"""Venues asked for positioning when none is named: OKX's API is up to date and says when a
range starts before what it keeps; Binance's daily dumps keep 5-minute snapshots since 2021."""

POSITIONING_DAYS: Final = 30

BOOK_DEPTH_DAYS: Final = 7
"""Days of book depth read when no start is given (a day of Binance's dumps is ~560 kB)."""
"""Days of positioning read when no start is given."""


def _prefer_fresh_funding(registry: ProviderRegistry) -> None:
    """Ask the up-to-date sources of funding and positioning first, among those registered."""
    registered = set(registry.names)
    order = [name for name in FUNDING_ORDER if name in registered]
    with contextlib.suppress(DomainError):  # a caller's provider of that name may serve no rates
        registry.prefer_rates(order, kind=RateKind.FUNDING)
    order = [name for name in POSITIONING_ORDER if name in registered]
    with contextlib.suppress(DomainError):  # ...or no positioning
        registry.prefer_positioning(order)


class AsyncToolkit:
    """Asynchronous facade over the market-data, currency, risk-free and quality services.

    Build it with :meth:`from_settings`; the constructor is for tests and custom wiring.
    """

    def __init__(
        self,
        *,
        registry: ProviderRegistry,
        market_data: MarketDataService,
        currency: CurrencyService,
        risk_free: RiskFreeRateService,
        quality: DataQualityService,
        importer: SeriesImporter | None = None,
        closeables: Sequence[object] = (),
    ) -> None:
        self._registry = registry
        self._market_data = market_data
        self._currency = currency
        self._risk_free = risk_free
        self._quality = quality
        self._importer = importer or SeriesImporter()
        self._closeables = tuple(closeables)

    @classmethod
    def from_settings(
        cls,
        settings: Settings | None = None,
        *,
        providers: Iterable[AnyProvider] = (),
        cache: bool = True,
    ) -> AsyncToolkit:
        """Wire every adapter from the configuration (``INVESTINGLAB_*`` variables).

        Providers are tried in this order: the ``providers`` given here, the user's own
        files (``local_data_dir``) and then, unless ``offline`` is set, the ECB (euro
        reference rates, €STR), Yahoo Finance, Binance, Kraken and Coinbase (spot pairs and
        their flow), OKX (funding of perpetual swaps) and alternative.me (crypto Fear & Greed).

        Args:
            settings: Configuration; the process-wide settings by default.
            providers: Extra providers, registered first (highest priority).
            cache: Keep downloaded data in the local cache: bars and economic series in
                Parquet, and the verified dump files of Binance as published.
        """
        config = settings or get_settings()
        registry = ProviderRegistry()
        for provider in providers:
            registry.register(provider)
        if config.local_data_dir is not None:
            registry.register(LocalFilesProvider(config.local_data_dir))
        remote = [] if config.offline else _remote_providers(config, registry, cache=cache)
        for provider in remote:
            registry.register(provider)
        _prefer_fresh_funding(registry)
        store = ParquetSeriesStore(config.effective_cache_dir) if cache else None
        market_data = MarketDataService(
            registry, store=store, max_concurrency=config.max_concurrency
        )
        return cls(
            registry=registry,
            market_data=market_data,
            currency=CurrencyService(market_data),
            risk_free=RiskFreeRateService(market_data),
            quality=DataQualityService(ExchangeCalendarsAdapter()),
            closeables=[*(p for p in providers if hasattr(p, "aclose")), *remote],
        )

    @property
    def providers(self) -> tuple[str, ...]:
        """Names of the registered providers."""
        return self._registry.names

    def provider_capabilities(self) -> dict[str, ProviderCapabilities]:
        """What each registered provider can serve, in order of preference."""
        return self._registry.capabilities()

    # ── Data ─────────────────────────────────────────────────────────

    async def series(
        self,
        symbol: str,
        *,
        start: DateLike = None,
        end: DateLike = None,
        frequency: Frequency | str = Frequency.DAY_1,
        refresh: bool = False,
    ) -> PriceSeries:
        """One price series, from the cache or the first provider able to serve it.

        Raises:
            DataUnavailableError: If no provider could deliver it.
        """
        request = BarsRequest(symbol, Frequency(frequency), _as_date(start), _as_date(end))
        return await self._market_data.get_bars(request, refresh=refresh)

    async def many(
        self,
        symbols: Iterable[str],
        *,
        start: DateLike = None,
        end: DateLike = None,
        frequency: Frequency | str = Frequency.DAY_1,
        refresh: bool = False,
    ) -> BatchResult[PriceSeries]:
        """Several series downloaded concurrently; failures never abort the batch (B1-T1 §4.2)."""
        requests = [
            BarsRequest(symbol, Frequency(frequency), _as_date(start), _as_date(end))
            for symbol in symbols
        ]
        return await self._market_data.get_many_bars(requests, refresh=refresh)

    async def economic(
        self,
        series_id: str,
        *,
        start: DateLike = None,
        end: DateLike = None,
        mode: VintageMode | str = VintageMode.FIRST_RELEASE,
        refresh: bool = False,
    ) -> EconomicSeries:
        """An economic series with its publication dates (point-in-time by default).

        Example: ``tk.economic("FNG", start="2026-01-01")`` is the crypto Fear & Greed Index.

        Raises:
            DataUnavailableError: If no provider could deliver it.
        """
        request = EconomicRequest(series_id, _as_date(start), _as_date(end), VintageMode(mode))
        return await self._market_data.get_economic_series(request, refresh=refresh)

    async def technical(
        self,
        symbol: str,
        *,
        start: DateLike = None,
        end: DateLike = None,
        frequency: Frequency | str = Frequency.DAY_1,
        names: Iterable[str] | None = None,
        parameters: Mapping[str, Mapping[str, float]] | None = None,
    ) -> TechnicalIndicators:
        """Technical indicators of a symbol's bars from ``start`` (ADR-0034).

        For daily and coarser bars, :data:`WARMUP` of earlier history is fetched too, so
        that the indicators are already defined at ``start``; the result starts at ``start``.

        Args:
            symbol: Any symbol (``SAN.MC``, ``^GSPC``, ``EURUSD=X``, ``BTC/USDT``).
            start: First date shown.
            end: Last date shown.
            frequency: Bar frequency.
            names: Indicators of the catalogue to compute (all by default).
            parameters: Parameters by indicator (each one's defaults otherwise).

        Raises:
            DataUnavailableError: If no provider could deliver the bars.
            DomainError: An unknown indicator or invalid parameters.
        """
        series, first = await self._with_history(symbol, start, end, frequency)
        indicators = technical_indicators(series, names, parameters)
        return indicators if first is None else indicators.between(first, None)

    async def patterns(
        self,
        symbol: str,
        *,
        start: DateLike = None,
        end: DateLike = None,
        frequency: Frequency | str = Frequency.DAY_1,
        names: Iterable[str] | None = None,
        parameters: Mapping[str, Mapping[str, float]] | None = None,
    ) -> PricePatterns:
        """Price patterns of a symbol's bars from ``start`` (ADR-0035).

        For daily and coarser bars, :data:`WARMUP` of earlier history is fetched too, so that
        what the bars before ``start`` set up (an order block, the swing of a sweep or of a
        Fibonacci zone) counts from ``start``; the result starts at ``start``. The session
        patterns need intraday bars.

        Args:
            symbol: Any symbol (``SAN.MC``, ``^GSPC``, ``EURUSD=X``, ``BTC/USDT``).
            start: First date shown.
            end: Last date shown.
            frequency: Bar frequency.
            names: Patterns of the catalogue to evaluate (all by default).
            parameters: Parameters by pattern (each one's defaults otherwise).

        Raises:
            DataUnavailableError: If no provider could deliver the bars.
            DomainError: An unknown pattern or invalid parameters.
        """
        series, first = await self._with_history(symbol, start, end, frequency)
        found = price_patterns(series, names, parameters)
        return found if first is None else found.between(first, None)

    async def structure(
        self,
        symbol: str,
        *,
        start: DateLike = None,
        end: DateLike = None,
        frequency: Frequency | str = Frequency.DAY_1,
    ) -> PriceStructure:
        """Support and resistance, divergences and Fibonacci levels of a symbol (ADR-0036).

        The structure of the bars shown, as of the last one: no earlier history is fetched,
        so the levels are those of the period asked for.

        Args:
            symbol: Any symbol (``SAN.MC``, ``^GSPC``, ``EURUSD=X``, ``BTC/USDT``).
            start: First date.
            end: Last date.
            frequency: Bar frequency.

        Raises:
            DataUnavailableError: If no provider could deliver the bars.
        """
        series = await self.series(symbol, start=start, end=end, frequency=Frequency(frequency))
        return price_structure(series)

    async def confluence(
        self,
        symbol: str,
        *,
        frames: Iterable[Frequency | str] | None = None,
        end: DateLike = None,
    ) -> TimeframeConfluence:
        """The signal panel and the trend of a symbol on several timeframes (ADR-0038).

        The daily, weekly and monthly frames come from one download of daily bars (the
        coarser two are aggregated from it, so the three share source and adjustment); each
        intraday frame is asked of the sources. A frame nobody serves, or without bars in
        the dates read, is reported as such and the rest are still read.

        Args:
            symbol: Any symbol (``SAN.MC``, ``^GSPC``, ``EURUSD=X``, ``BTC/USDT``).
            frames: Frames to read, among those of :data:`CONFLUENCE_HISTORY`; daily, weekly
                and monthly by default.
            end: Last date read (today by default).

        Raises:
            DataUnavailableError: If no provider could deliver the bars of any frame.
            DomainError: A frame that cannot be read, or none at all.
        """
        wanted = sorted(
            {Frequency(frame) for frame in (CONFLUENCE_FRAMES if frames is None else frames)},
            key=lambda frame: frame.rank,
        )
        unknown = [frame.value for frame in wanted if frame not in CONFLUENCE_HISTORY]
        if unknown or not wanted:
            allowed = [frame.value for frame in CONFLUENCE_HISTORY]
            raise DomainError(f"Frames {unknown} cannot be read; choose among {allowed}")
        last = _as_date(end) or datetime.now(UTC).date()
        coarse = [frame for frame in wanted if not frame.is_intraday]
        history = {frame: CONFLUENCE_HISTORY[frame] for frame in wanted if frame.is_intraday}
        if coarse:
            history[Frequency.DAY_1] = max(CONFLUENCE_HISTORY[frame] for frame in coarse)

        async def fetch(frequency: Frequency) -> PriceSeries | InvestingLabError:
            try:
                return await self.series(
                    symbol, start=last - history[frequency], end=end, frequency=frequency
                )
            except (DataUnavailableError, InvalidSeriesError) as error:
                return error  # nobody serves it, or it has no bars in these dates

        answers = dict(
            zip(history, await asyncio.gather(*(fetch(f) for f in history)), strict=True)
        )
        failures = [a for a in answers.values() if isinstance(a, InvestingLabError)]
        if len(failures) == len(answers):
            unavailable = (f for f in failures if isinstance(f, DataUnavailableError))
            raise next(unavailable, failures[0])
        found: dict[Frequency, PriceSeries | None] = {}
        for frame in wanted:
            base = answers[frame if frame.is_intraday else Frequency.DAY_1]
            if isinstance(base, InvestingLabError):
                found[frame] = None
            elif frame.is_intraday or frame is Frequency.DAY_1:
                found[frame] = base
            else:
                found[frame] = base.resample(frame)
        derived = [frame for frame in coarse if frame is not Frequency.DAY_1]
        return timeframe_confluence(found, derived=derived)

    async def card(self, symbol: str, *, end: DateLike = None) -> AssetCard:
        """The card of a symbol: what each pillar of its asset class says (ADR-0040).

        Every instrument has a technical reading (its timeframes and price structure), a
        risk profile and the quality of its data, over three years of daily bars; a crypto
        pair also has its perpetual swap: a quarter of funding and a month of daily
        positioning. A pillar whose data no source serves is reported as unread and the
        rest are still read.

        Args:
            symbol: Any symbol (``SAN.MC``, ``^GSPC``, ``EURUSD=X``, ``BTC/USDT``).
            end: Last date read (today by default).

        Raises:
            DataUnavailableError: If no provider could deliver its daily bars.
        """
        last = _as_date(end) or datetime.now(UTC).date()
        series = await self.series(symbol, start=last - CARD_HISTORY, end=end)

        async def frames() -> TimeframeConfluence | None:
            try:
                return await self.confluence(symbol, end=end)
            except (DataUnavailableError, DomainError):
                return None

        wanted = {spec.pillar for spec in pillars_for(series.asset_class)}
        swap = _perpetual_of(series.symbol) if Pillar.DERIVATIVES in wanted else None

        async def funding() -> RateSeries | None:
            if swap is None:
                return None
            try:
                return await self.holding_rates(swap, start=last - CARD_FUNDING, end=end)
            except (DataUnavailableError, InvalidSeriesError):
                return None

        async def positioning() -> PositioningSeries | None:
            if swap is None:
                return None
            try:
                return await self.positioning(
                    swap, start=last - CARD_POSITIONING, end=end, frequency=Frequency.DAY_1
                )
            except (DataUnavailableError, InvalidSeriesError):
                return None

        confluence, rates, standing = await asyncio.gather(frames(), funding(), positioning())
        return asset_card(
            series,
            confluence=confluence,
            structure=price_structure(series),
            quality=self.quality(series),
            funding=rates,
            positioning=standing,
        )

    async def _with_history(
        self, symbol: str, start: DateLike, end: DateLike, frequency: Frequency | str
    ) -> tuple[PriceSeries, pd.Timestamp | None]:
        """The bars from :data:`WARMUP` before ``start``, and where to cut them (if anywhere)."""
        wanted = Frequency(frequency)
        first = _as_date(start)
        padding = WARMUP.get(wanted)
        fetch_from = first - padding if first is not None and padding is not None else first
        series = await self.series(symbol, start=fetch_from, end=end, frequency=wanted)
        cut = None if first is None or fetch_from == first else pd.Timestamp(first)
        return series, cut

    async def flow(
        self,
        symbol: str,
        *,
        start: DateLike = None,
        end: DateLike = None,
        frequency: Frequency | str = Frequency.DAY_1,
        refresh: bool = False,
    ) -> FlowSeries:
        """Trade flow of the same bars :meth:`series` returns (ADR-0031).

        A venue's pair (``BTC/USDT``) brings the aggressor side, hence delta and CVD; a
        listed instrument (``SAN.MC``, ``^GSPC``) brings its volume only.

        Raises:
            DataUnavailableError: If no provider could deliver it (a currency pair has no
                volume, for instance).
        """
        request = BarsRequest(symbol, Frequency(frequency), _as_date(start), _as_date(end))
        return await self._market_data.get_flow(request, refresh=refresh)

    async def holding_rates(
        self,
        symbol: str,
        *,
        kind: RateKind | str = RateKind.FUNDING,
        venue: str | None = None,
        start: DateLike = None,
        end: DateLike = None,
        refresh: bool = False,
    ) -> RateSeries:
        """What holding ``symbol`` paid or earned per period: funding, borrow or financing.

        Example: ``tk.holding_rates("BTC/USDT:USDT", start="2026-10-01")`` is the funding of
        the USDT-settled bitcoin perpetual swap.

        Raises:
            DataUnavailableError: If no provider could deliver them.
        """
        request = RatesRequest(symbol, RateKind(kind), venue, _as_date(start), _as_date(end))
        return await self._market_data.get_rates(request, refresh=refresh)

    async def positioning(
        self,
        symbol: str,
        *,
        venue: str | None = None,
        start: DateLike = None,
        end: DateLike = None,
        frequency: Frequency | str = Frequency.HOUR_1,
        refresh: bool = False,
    ) -> PositioningSeries:
        """Open interest and long/short ratios of a derivative on one venue (ADR-0042).

        Example: ``tk.positioning("BTC/USDT:USDT", venue="binance", start="2026-10-01")``.

        Args:
            symbol: The derivative, as a perpetual swap (``BTC/USDT:USDT``).
            venue: Where it trades; the preferred venue that serves it by default.
            start: First day (UTC); the last :data:`POSITIONING_DAYS` days by default.
            end: Last day (UTC); up to the latest by default.
            frequency: Spacing of the snapshots, from 5 minutes to a day.
            refresh: Download again even if a recent answer is remembered.

        Raises:
            DataUnavailableError: If no provider could deliver them.
        """
        last = _as_date(end) or datetime.now(UTC).date()
        first = _as_date(start) or last - timedelta(days=POSITIONING_DAYS)
        request = PositioningRequest(symbol, venue, first, _as_date(end), Frequency(frequency))
        return await self._market_data.get_positioning(request, refresh=refresh)

    async def book_depth(
        self,
        symbol: str,
        *,
        venue: str | None = None,
        start: DateLike = None,
        end: DateLike = None,
        frequency: Frequency | str = Frequency.HOUR_1,
        refresh: bool = False,
    ) -> BookDepthSeries:
        """Depth of the order book within bands around the price, on one venue (ADR-0044).

        Example: ``tk.book_depth("BTC/USDT:USDT", start="2026-11-01").liquidity(2.0)`` is the
        value resting within ±2 % of the price at the end of each hour.

        Args:
            symbol: The instrument, as a perpetual swap (``BTC/USDT:USDT``).
            venue: Whose book; the first venue that serves it by default.
            start: First day (UTC); the last :data:`BOOK_DEPTH_DAYS` days by default.
            end: Last day (UTC); up to the latest by default.
            frequency: Spacing of the snapshots, from 5 minutes to a day.
            refresh: Download again even if a recent answer is remembered.

        Raises:
            DataUnavailableError: If no provider could deliver it.
        """
        last = _as_date(end) or datetime.now(UTC).date()
        first = _as_date(start) or last - timedelta(days=BOOK_DEPTH_DAYS)
        request = BookDepthRequest(symbol, venue, first, _as_date(end), Frequency(frequency))
        return await self._market_data.get_book_depth(request, refresh=refresh)

    async def market_snapshot(
        self,
        asset_class: AssetClass | str = AssetClass.CRYPTO,
        *,
        currency: Currency | str = "USD",
        refresh: bool = False,
    ) -> MarketSnapshot:
        """The whole market of an asset class as its source last computed it (ADR-0045).

        Example: ``tk.market_snapshot().share_of("BTC")`` is bitcoin's dominance. It is a
        snapshot, dated by :attr:`~investinglab.domain.MarketSnapshot.as_of`: no free source
        keeps its history.

        Raises:
            DataUnavailableError: If no provider could deliver it.
        """
        request = MarketSnapshotRequest(AssetClass(asset_class), Currency(str(currency)))
        return await self._market_data.get_market_snapshot(request, refresh=refresh)

    async def market_caps(
        self,
        top: int = 100,
        *,
        asset_class: AssetClass | str = AssetClass.CRYPTO,
        currency: Currency | str = "USD",
        refresh: bool = False,
    ) -> MarketCapRanking:
        """The ``top`` largest assets of a market by capitalisation, as last ranked.

        Example: ``tk.market_caps(10).frame()``. A snapshot, like :meth:`market_snapshot`.

        Raises:
            DataUnavailableError: If no provider could deliver it.
        """
        request = MarketCapRequest(AssetClass(asset_class), Currency(str(currency)), top)
        return await self._market_data.get_market_caps(request, refresh=refresh)

    def venues(self, symbol: str, dataset: Dataset | str) -> tuple[str, ...]:
        """The venues that serve ``dataset`` of ``symbol``, in the order they are asked.

        Example: ``tk.venues("BTC/USDT:USDT", "positioning")`` is ``("okx", "binance")``. A
        provider registered later appears here on its own: interfaces list these instead of
        a fixed set.

        Raises:
            DomainError: If ``dataset`` is not one served per venue (funding, positioning,
                book depth).
        """
        wanted = Dataset(dataset)
        if wanted is Dataset.HOLDING_RATES:
            funding = RatesRequest(symbol, RateKind.FUNDING)
            return tuple(p.name for p in self._registry.rates_candidates(funding))
        if wanted is Dataset.POSITIONING:
            request = PositioningRequest(symbol)
            return tuple(p.name for p in self._registry.positioning_candidates(request))
        if wanted is Dataset.BOOK_DEPTH:
            book = BookDepthRequest(symbol)
            return tuple(p.name for p in self._registry.book_depth_candidates(book))
        raise DomainError(
            f"{wanted.value} is not served per venue; ask for holding_rates, positioning or "
            "book_depth"
        )

    def load(self, path: str | Path, **spec: Any) -> PriceSeries:  # noqa: ANN401
        """Import a CSV or Parquet file (see :class:`~investinglab.adapters.files.ImportSpec`).

        Examples:
            >>> tk.load("SAN.csv", symbol="SAN.MC", currency="EUR", exchange="XMAD")
        """
        return self._importer.from_file(path, ImportSpec(**spec))

    def from_dataframe(self, frame: pd.DataFrame, **spec: Any) -> PriceSeries:  # noqa: ANN401
        """Validate a DataFrame of bars as a price series (same options as :meth:`load`)."""
        return self._importer.from_dataframe(frame, ImportSpec(**spec), dataset="dataframe")

    async def portfolio(
        self,
        name: str,
        weights: Mapping[str, float],
        *,
        base_currency: Currency | str | None = None,
        start: DateLike = None,
        end: DateLike = None,
        frequency: Frequency | str = Frequency.DAY_1,
        rebalance: RebalancePolicy | None = None,
        allow_short: bool = False,
    ) -> Portfolio:
        """Download the holdings, convert them to the base currency and build the portfolio.

        Args:
            name: Portfolio name.
            weights: Target weight of each symbol (summing to 1).
            base_currency: Valuation currency; the holdings' common currency by default.
            start: First date of the history.
            end: Last date of the history.
            frequency: Bar frequency.
            rebalance: Rebalancing policy (monthly by default).
            allow_short: Accept negative weights.

        Raises:
            DataUnavailableError: If any holding (or FX fixing) could not be obtained.
            InvalidPortfolioError: If the weights or the series are not valid together.
        """
        batch = await self.many(weights, start=start, end=end, frequency=frequency)
        if not batch.ok:
            attempts = tuple(a for failure in batch.failed.values() for a in failure.attempts)
            raise DataUnavailableError(name, attempts, reason=batch.summary())
        holdings = [batch.succeeded[symbol] for symbol in weights]
        target = self._base_currency(name, holdings, base_currency)
        converted = await self._currency.convert_all(holdings, target)
        return Portfolio.from_weights(
            name,
            converted,
            dict(weights),
            base_currency=target,
            rebalance=rebalance,
            allow_short=allow_short,
        )

    async def risk_free(self, currency: Currency | str, dates: pd.DatetimeIndex) -> pd.Series:
        """Annual risk-free rate (decimal) known at each date, point-in-time (ADR-0014)."""
        return await self._risk_free.annual_rates(Currency(str(currency)), dates)

    # ── Analysis ─────────────────────────────────────────────────────

    def quality(self, series: PriceSeries) -> DataQualityReport:
        """Data-quality diagnosis, checked against the market's official calendar."""
        return self._quality.assess(series)

    async def metrics(
        self,
        subject: PriceSeries | Portfolio,
        *,
        levels: Sequence[float] = DEFAULT_CONFIDENCE_LEVELS,
    ) -> RiskMetrics:
        """Performance and risk metrics with the point-in-time risk-free rate.

        Sharpe and Sortino use the rate of the subject's currency known at each date, as
        the reports do; when no source can provide it (or for intraday data) they use 0 %,
        which :attr:`~investinglab.domain.RiskMetrics.risk_free_periods` makes visible.
        """
        rate = await self._point_in_time_rate(subject)
        return subject.metrics(risk_free_rate=0.0 if rate is None else rate, levels=levels)

    async def report(
        self,
        subject: PriceSeries | Portfolio,
        options: ReportOptions | None = None,
        **settings: Unpack[ReportSettings],
    ) -> MarkdownReport:
        """The subject's report, enriched with what only the platform knows.

        Unless a ``risk_free_rate`` is given, Sharpe and Sortino use the point-in-time
        risk-free rate of the subject's currency (when a source can provide it), and data
        quality is checked against the official calendar of every market.
        """
        resolved = ReportOptions.resolve(options, settings)
        explicit_rate = "risk_free_rate" in settings or (
            options is not None and not options.uses_constant_zero_rate
        )
        series = subject.series if isinstance(subject, Portfolio) else (subject,)
        changes: dict[str, Any] = {}
        if not explicit_rate:
            rate = await self._point_in_time_rate(subject)
            if rate is not None:
                changes["risk_free_rate"] = rate
        if resolved.quality is None:
            changes["quality"] = self._quality.assess_many(series)
        return subject.report(replace(resolved, **changes) if changes else resolved)

    async def _point_in_time_rate(self, subject: PriceSeries | Portfolio) -> pd.Series | None:
        if isinstance(subject, Portfolio):
            currency, frequency = subject.base_currency, subject.frequency
            dates = pd.DatetimeIndex(subject.returns().index)
        else:
            currency, frequency = subject.currency, subject.frequency
            dates = pd.DatetimeIndex(subject.returns().index)
        if frequency.is_intraday or not self._risk_free.supports(currency):
            return None
        try:
            return await self._risk_free.annual_rates(currency, dates)
        except InvestingLabError as error:
            log.warning("risk_free_unavailable", currency=str(currency), detail=str(error))
            return None

    @staticmethod
    def _base_currency(
        name: str, holdings: Sequence[PriceSeries], requested: Currency | str | None
    ) -> Currency:
        if requested is not None:
            return requested if isinstance(requested, Currency) else Currency(requested)
        currencies = {s.currency for s in holdings}
        if len(currencies) != 1:
            found = sorted(str(c) for c in currencies)
            raise DomainError(f"Portfolio {name!r} mixes currencies {found}: pass base_currency")
        return currencies.pop()

    # ── Lifecycle ────────────────────────────────────────────────────

    async def aclose(self) -> None:
        """Release network clients held by the providers."""
        for resource in self._closeables:
            await resource.aclose()  # type: ignore[attr-defined]

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.aclose()


class _EventLoopThread:
    """A private event loop on a daemon thread.

    It runs coroutines from synchronous code, even inside Jupyter, whose own loop is already
    running (``asyncio.run`` would fail there).
    """

    def __init__(self) -> None:
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._loop.run_forever, name="investinglab-toolkit", daemon=True
        )
        self._thread.start()

    def run[T](self, coroutine: Coroutine[Any, Any, T], timeout: float | None = None) -> T:
        """Run ``coroutine`` on the private loop and wait for its result.

        When the wait ends early, because ``timeout`` seconds passed or the user
        interrupted it (Ctrl+C, the stop button of a notebook), the coroutine is cancelled:
        nothing keeps downloading in the background.

        Raises:
            TimeoutError: If the coroutine did not finish within ``timeout`` seconds.
        """
        future: Future[T] = asyncio.run_coroutine_threadsafe(coroutine, self._loop)
        try:
            return future.result(timeout)
        except TimeoutError:
            if future.done():  # finished right at the deadline, or failed on its own
                return future.result()
            future.cancel()
            message = f"Cancelled after {timeout:g} s without finishing"
            raise TimeoutError(message) from None
        except BaseException:
            future.cancel()  # interrupted: stop the work instead of leaving it running
            raise

    def close(self) -> None:
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join()
        self._loop.close()


class Toolkit:
    """Synchronous facade for notebooks and scripts (same methods as :class:`AsyncToolkit`).

    Interrupting a call (Ctrl+C, the stop button of a notebook) cancels the work in
    progress, and ``timeout`` bounds how long a call may take.

    Args:
        inner: The asynchronous toolkit to drive.
        timeout: Longest a call may run before it is cancelled, in seconds (``None``
            waits until it ends).
    """

    def __init__(self, inner: AsyncToolkit, *, timeout: float | None = None) -> None:
        if timeout is not None and not timeout > 0:
            raise DomainError("timeout must be positive")
        self._inner = inner
        self._runner = _EventLoopThread()
        self._timeout = timeout
        self._closed = False

    @classmethod
    def from_settings(
        cls,
        settings: Settings | None = None,
        *,
        providers: Iterable[AnyProvider] = (),
        cache: bool = True,
    ) -> Toolkit:
        """Wire every adapter from the configuration (see :meth:`AsyncToolkit.from_settings`).

        The call timeout comes from ``toolkit_timeout_seconds``.
        """
        resolved = settings or get_settings()
        inner = AsyncToolkit.from_settings(resolved, providers=providers, cache=cache)
        return cls(inner, timeout=resolved.toolkit_timeout_seconds)

    @property
    def asynchronous(self) -> AsyncToolkit:
        """The underlying asynchronous toolkit."""
        return self._inner

    @property
    def providers(self) -> tuple[str, ...]:
        """Names of the registered providers."""
        return self._inner.providers

    def series(
        self,
        symbol: str,
        *,
        start: DateLike = None,
        end: DateLike = None,
        frequency: Frequency | str = Frequency.DAY_1,
        refresh: bool = False,
    ) -> PriceSeries:
        """One price series (see :meth:`AsyncToolkit.series`)."""
        return self._run(
            self._inner.series(symbol, start=start, end=end, frequency=frequency, refresh=refresh)
        )

    def many(
        self,
        symbols: Iterable[str],
        *,
        start: DateLike = None,
        end: DateLike = None,
        frequency: Frequency | str = Frequency.DAY_1,
        refresh: bool = False,
    ) -> BatchResult[PriceSeries]:
        """Several series downloaded concurrently (see :meth:`AsyncToolkit.many`)."""
        return self._run(
            self._inner.many(symbols, start=start, end=end, frequency=frequency, refresh=refresh)
        )

    def economic(
        self,
        series_id: str,
        *,
        start: DateLike = None,
        end: DateLike = None,
        mode: VintageMode | str = VintageMode.FIRST_RELEASE,
        refresh: bool = False,
    ) -> EconomicSeries:
        """An economic series (see :meth:`AsyncToolkit.economic`)."""
        return self._run(
            self._inner.economic(series_id, start=start, end=end, mode=mode, refresh=refresh)
        )

    def technical(
        self,
        symbol: str,
        *,
        start: DateLike = None,
        end: DateLike = None,
        frequency: Frequency | str = Frequency.DAY_1,
        names: Iterable[str] | None = None,
        parameters: Mapping[str, Mapping[str, float]] | None = None,
    ) -> TechnicalIndicators:
        """Technical indicators of a symbol (see :meth:`AsyncToolkit.technical`)."""
        return self._run(
            self._inner.technical(
                symbol,
                start=start,
                end=end,
                frequency=frequency,
                names=names,
                parameters=parameters,
            )
        )

    def patterns(
        self,
        symbol: str,
        *,
        start: DateLike = None,
        end: DateLike = None,
        frequency: Frequency | str = Frequency.DAY_1,
        names: Iterable[str] | None = None,
        parameters: Mapping[str, Mapping[str, float]] | None = None,
    ) -> PricePatterns:
        """Price patterns of a symbol (see :meth:`AsyncToolkit.patterns`)."""
        return self._run(
            self._inner.patterns(
                symbol,
                start=start,
                end=end,
                frequency=frequency,
                names=names,
                parameters=parameters,
            )
        )

    def structure(
        self,
        symbol: str,
        *,
        start: DateLike = None,
        end: DateLike = None,
        frequency: Frequency | str = Frequency.DAY_1,
    ) -> PriceStructure:
        """Price structure of a symbol (see :meth:`AsyncToolkit.structure`)."""
        return self._run(self._inner.structure(symbol, start=start, end=end, frequency=frequency))

    def confluence(
        self,
        symbol: str,
        *,
        frames: Iterable[Frequency | str] | None = None,
        end: DateLike = None,
    ) -> TimeframeConfluence:
        """Confluence across timeframes (see :meth:`AsyncToolkit.confluence`)."""
        return self._run(self._inner.confluence(symbol, frames=frames, end=end))

    def card(self, symbol: str, *, end: DateLike = None) -> AssetCard:
        """The card of a symbol (see :meth:`AsyncToolkit.card`)."""
        return self._run(self._inner.card(symbol, end=end))

    def flow(
        self,
        symbol: str,
        *,
        start: DateLike = None,
        end: DateLike = None,
        frequency: Frequency | str = Frequency.DAY_1,
        refresh: bool = False,
    ) -> FlowSeries:
        """Trade flow of the same bars :meth:`series` returns (see :meth:`AsyncToolkit.flow`)."""
        return self._run(
            self._inner.flow(symbol, start=start, end=end, frequency=frequency, refresh=refresh)
        )

    def holding_rates(
        self,
        symbol: str,
        *,
        kind: RateKind | str = RateKind.FUNDING,
        venue: str | None = None,
        start: DateLike = None,
        end: DateLike = None,
        refresh: bool = False,
    ) -> RateSeries:
        """Funding, borrow or financing rates (see :meth:`AsyncToolkit.holding_rates`)."""
        return self._run(
            self._inner.holding_rates(
                symbol, kind=kind, venue=venue, start=start, end=end, refresh=refresh
            )
        )

    def portfolio(
        self,
        name: str,
        weights: Mapping[str, float],
        *,
        base_currency: Currency | str | None = None,
        start: DateLike = None,
        end: DateLike = None,
        frequency: Frequency | str = Frequency.DAY_1,
        rebalance: RebalancePolicy | None = None,
        allow_short: bool = False,
    ) -> Portfolio:
        """Download, convert and build a portfolio (see :meth:`AsyncToolkit.portfolio`)."""
        return self._run(
            self._inner.portfolio(
                name,
                weights,
                base_currency=base_currency,
                start=start,
                end=end,
                frequency=frequency,
                rebalance=rebalance,
                allow_short=allow_short,
            )
        )

    def risk_free(self, currency: Currency | str, dates: pd.DatetimeIndex) -> pd.Series:
        """Point-in-time risk-free rates (see :meth:`AsyncToolkit.risk_free`)."""
        return self._run(self._inner.risk_free(currency, dates))

    def metrics(
        self,
        subject: PriceSeries | Portfolio,
        *,
        levels: Sequence[float] = DEFAULT_CONFIDENCE_LEVELS,
    ) -> RiskMetrics:
        """Metrics with the point-in-time risk-free rate (see :meth:`AsyncToolkit.metrics`)."""
        return self._run(self._inner.metrics(subject, levels=levels))

    def positioning(
        self,
        symbol: str,
        *,
        venue: str | None = None,
        start: DateLike = None,
        end: DateLike = None,
        frequency: Frequency | str = Frequency.HOUR_1,
        refresh: bool = False,
    ) -> PositioningSeries:
        """Open interest and long/short ratios (see :meth:`AsyncToolkit.positioning`)."""
        return self._run(
            self._inner.positioning(
                symbol, venue=venue, start=start, end=end, frequency=frequency, refresh=refresh
            )
        )

    def book_depth(
        self,
        symbol: str,
        *,
        venue: str | None = None,
        start: DateLike = None,
        end: DateLike = None,
        frequency: Frequency | str = Frequency.HOUR_1,
        refresh: bool = False,
    ) -> BookDepthSeries:
        """Depth of the order book (see :meth:`AsyncToolkit.book_depth`)."""
        return self._run(
            self._inner.book_depth(
                symbol, venue=venue, start=start, end=end, frequency=frequency, refresh=refresh
            )
        )

    def market_snapshot(
        self,
        asset_class: AssetClass | str = AssetClass.CRYPTO,
        *,
        currency: Currency | str = "USD",
        refresh: bool = False,
    ) -> MarketSnapshot:
        """The whole market of an asset class (see :meth:`AsyncToolkit.market_snapshot`)."""
        return self._run(
            self._inner.market_snapshot(asset_class, currency=currency, refresh=refresh)
        )

    def market_caps(
        self,
        top: int = 100,
        *,
        asset_class: AssetClass | str = AssetClass.CRYPTO,
        currency: Currency | str = "USD",
        refresh: bool = False,
    ) -> MarketCapRanking:
        """The largest assets of a market (see :meth:`AsyncToolkit.market_caps`)."""
        return self._run(
            self._inner.market_caps(
                top, asset_class=asset_class, currency=currency, refresh=refresh
            )
        )

    def venues(self, symbol: str, dataset: Dataset | str) -> tuple[str, ...]:
        """The venues that serve ``dataset`` of ``symbol`` (see :meth:`AsyncToolkit.venues`)."""
        return self._inner.venues(symbol, dataset)

    def load(self, path: str | Path, **spec: Any) -> PriceSeries:  # noqa: ANN401
        """Import a CSV or Parquet file (see :meth:`AsyncToolkit.load`)."""
        return self._inner.load(path, **spec)

    def from_dataframe(self, frame: pd.DataFrame, **spec: Any) -> PriceSeries:  # noqa: ANN401
        """Validate a DataFrame of bars (see :meth:`AsyncToolkit.from_dataframe`)."""
        return self._inner.from_dataframe(frame, **spec)

    def quality(self, series: PriceSeries) -> DataQualityReport:
        """Calendar-aware data-quality diagnosis."""
        return self._inner.quality(series)

    def report(
        self,
        subject: PriceSeries | Portfolio,
        options: ReportOptions | None = None,
        **settings: Unpack[ReportSettings],
    ) -> MarkdownReport:
        """Enriched report (see :meth:`AsyncToolkit.report`)."""
        return self._run(self._inner.report(subject, options, **settings))

    def _run[T](self, coroutine: Coroutine[Any, Any, T]) -> T:
        return self._runner.run(coroutine, self._timeout)

    def close(self) -> None:
        """Release network clients and stop the private event loop (idempotent)."""
        if self._closed:
            return
        self._closed = True
        try:
            self._runner.run(self._inner.aclose())
        finally:
            self._runner.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()
