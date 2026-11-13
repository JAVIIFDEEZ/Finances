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
import threading
from dataclasses import replace
from datetime import date
from typing import TYPE_CHECKING, Any, Self, Unpack

import pandas as pd

from investinglab.adapters.calendars import ExchangeCalendarsAdapter
from investinglab.adapters.files import ImportSpec, SeriesImporter
from investinglab.adapters.http import RetryPolicy
from investinglab.adapters.providers.alternative_me import AlternativeMeProvider
from investinglab.adapters.providers.binance import BinanceProvider
from investinglab.adapters.providers.coinbase import CoinbaseProvider
from investinglab.adapters.providers.ecb import EcbProvider
from investinglab.adapters.providers.files import LocalFilesProvider
from investinglab.adapters.providers.kraken import KrakenProvider
from investinglab.adapters.providers.okx import OkxProvider
from investinglab.adapters.providers.yahoo import YahooFinanceProvider
from investinglab.adapters.storage import ParquetSeriesStore
from investinglab.config.logging import get_logger
from investinglab.config.settings import Settings, get_settings
from investinglab.domain.errors import DomainError, InvestingLabError
from investinglab.domain.metrics import DEFAULT_CONFIDENCE_LEVELS
from investinglab.domain.money import Currency
from investinglab.domain.portfolio import Portfolio
from investinglab.domain.rate_series import RateKind
from investinglab.domain.time import Frequency
from investinglab.ports.market_data import BarsRequest, EconomicRequest, RatesRequest, VintageMode
from investinglab.reporting.options import ReportOptions
from investinglab.services.fx import CurrencyService
from investinglab.services.market_data import DataUnavailableError, MarketDataService
from investinglab.services.quality import DataQualityService
from investinglab.services.registry import ProviderRegistry
from investinglab.services.risk_free import RiskFreeRateService

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine, Iterable, Mapping, Sequence
    from concurrent.futures import Future
    from datetime import datetime
    from pathlib import Path
    from types import TracebackType

    from investinglab.domain.economic import EconomicSeries
    from investinglab.domain.flow import FlowSeries
    from investinglab.domain.metrics import RiskMetrics
    from investinglab.domain.portfolio import RebalancePolicy
    from investinglab.domain.quality import DataQualityReport
    from investinglab.domain.rate_series import RateSeries
    from investinglab.domain.series import PriceSeries
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
    | AlternativeMeProvider
)


def _as_date(value: DateLike) -> date | None:
    return None if value is None else pd.Timestamp(value).date()


def _remote_providers(config: Settings, registry: ProviderRegistry) -> list[RemoteProvider]:
    """Default remote providers, in order, except those a caller's provider replaces.

    The ECB comes first: its reference rates are the official daily fixings of the euro
    and it only serves currency pairs and euro rates. Yahoo serves every other symbol of
    its own notation (``SAN.MC``, ``^GSPC``, ``BTC-USD``...). The venues serve theirs:
    the spot pairs written ``BASE/QUOTE`` come from Binance, with their trade flow, and fall
    back on Kraken (its last 720 bars) and Coinbase, which also list the pairs in dollars and
    euros; OKX serves the funding of perpetual swaps written ``BASE/QUOTE:SETTLE``
    (ADR-0032). alternative.me
    publishes the crypto Fear & Greed Index (``FNG``).
    """
    retry = RetryPolicy(max_attempts=config.http_max_attempts)
    timeout = config.http_timeout_seconds
    factories: dict[str, Callable[[], RemoteProvider]] = {
        "ecb": lambda: EcbProvider(timeout=timeout, retry=retry),
        "yahoo": lambda: YahooFinanceProvider(timeout=timeout, retry=retry),
        "binance": lambda: BinanceProvider(timeout=timeout, retry=retry),
        "kraken": lambda: KrakenProvider(timeout=timeout, retry=retry),
        "coinbase": lambda: CoinbaseProvider(timeout=timeout, retry=retry),
        "okx": lambda: OkxProvider(timeout=timeout, retry=retry),
        "alternative_me": lambda: AlternativeMeProvider(timeout=timeout, retry=retry),
    }
    return [build() for name, build in factories.items() if name not in registry]


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
            cache: Keep downloaded data in the local Parquet cache.
        """
        config = settings or get_settings()
        registry = ProviderRegistry()
        for provider in providers:
            registry.register(provider)
        if config.local_data_dir is not None:
            registry.register(LocalFilesProvider(config.local_data_dir))
        remote = [] if config.offline else _remote_providers(config, registry)
        for provider in remote:
            registry.register(provider)
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

    async def flow(
        self,
        symbol: str,
        *,
        start: DateLike = None,
        end: DateLike = None,
        frequency: Frequency | str = Frequency.DAY_1,
    ) -> FlowSeries:
        """Trade flow of the same bars :meth:`series` returns (ADR-0031).

        A venue's pair (``BTC/USDT``) brings the aggressor side, hence delta and CVD; a
        listed instrument (``SAN.MC``, ``^GSPC``) brings its volume only.

        Raises:
            DataUnavailableError: If no provider could deliver it (a currency pair has no
                volume, for instance).
        """
        request = BarsRequest(symbol, Frequency(frequency), _as_date(start), _as_date(end))
        return await self._market_data.get_flow(request)

    async def holding_rates(
        self,
        symbol: str,
        *,
        kind: RateKind | str = RateKind.FUNDING,
        venue: str | None = None,
        start: DateLike = None,
        end: DateLike = None,
    ) -> RateSeries:
        """What holding ``symbol`` paid or earned per period: funding, borrow or financing.

        Example: ``tk.holding_rates("BTC/USDT:USDT", start="2026-10-01")`` is the funding of
        the USDT-settled bitcoin perpetual swap.

        Raises:
            DataUnavailableError: If no provider could deliver them.
        """
        request = RatesRequest(symbol, RateKind(kind), venue, _as_date(start), _as_date(end))
        return await self._market_data.get_rates(request)

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

    def flow(
        self,
        symbol: str,
        *,
        start: DateLike = None,
        end: DateLike = None,
        frequency: Frequency | str = Frequency.DAY_1,
    ) -> FlowSeries:
        """Trade flow of the same bars :meth:`series` returns (see :meth:`AsyncToolkit.flow`)."""
        return self._run(self._inner.flow(symbol, start=start, end=end, frequency=frequency))

    def holding_rates(
        self,
        symbol: str,
        *,
        kind: RateKind | str = RateKind.FUNDING,
        venue: str | None = None,
        start: DateLike = None,
        end: DateLike = None,
    ) -> RateSeries:
        """Funding, borrow or financing rates (see :meth:`AsyncToolkit.holding_rates`)."""
        return self._run(
            self._inner.holding_rates(symbol, kind=kind, venue=venue, start=start, end=end)
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
