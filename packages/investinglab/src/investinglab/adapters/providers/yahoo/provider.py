"""Yahoo Finance provider: price bars from the public chart endpoint (ADR-0025).

Yahoo has no official API. The adapter reads one endpoint, ``/v8/finance/chart/{symbol}``,
through the shared :class:`~investinglab.adapters.http.HttpClient` (retries, quotas, error
translation) and turns its payload into a validated
:class:`~investinglab.domain.PriceSeries`. Equities, ETFs, funds, indices, currencies,
crypto-assets and futures are served at every frequency: intraday and daily bars natively,
weekly and coarser ones aggregated from daily bars by the domain.

What the adapter guarantees, beyond the domain's validation:

* **Session dates.** Daily bars are labelled with the session date in the market's own
  timezone (a Tokyo session never shifts to the previous day); intraday bars keep their
  open time in UTC.
* **Only finished bars.** The bar of a session still in progress, and any intraday bar that
  has not closed yet, are left out: a partial bar is not a close.
* **Nothing invented.** A bar without a close is an absent observation (dropped, never
  filled). If any bar lacks its open, high or low, those columns are left out of the series
  instead of patching them. The snapshot bar Yahoo appends off the interval grid is dropped.
* **Major currency units.** Prices quoted in minor units (``GBp``) are scaled to the major
  currency (``GBP``).
* **Adjustment.** Open, high, low and close are split-adjusted; ``adj_close`` (daily and
  coarser) is adjusted for splits and dividends.
* **Flow.** The volume of the same bars, in units of the instrument (ADR-0031). Yahoo does
  not report the aggressor side, so there is no delta; currency pairs have no volume and
  crypto-assets report theirs in the quote currency, so neither has flow here.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Final, Self
from urllib.parse import quote

import numpy as np
import pandas as pd
from pydantic import ValidationError

from investinglab import __version__
from investinglab.adapters.http import HttpClient
from investinglab.adapters.providers.yahoo.payload import ChartResponse, Quote
from investinglab.adapters.providers.yahoo.venues import ASSET_CLASSES, asset_class_of, exchange_of
from investinglab.config.logging import get_logger
from investinglab.domain.errors import DomainError
from investinglab.domain.flow import FlowField, FlowSeries
from investinglab.domain.instruments import AssetClass, Instrument
from investinglab.domain.money import parse_quote_currency
from investinglab.domain.series import (
    MIN_OBSERVATIONS,
    DataSource,
    PriceAdjustment,
    PriceField,
    PriceSeries,
)
from investinglab.domain.time import Frequency
from investinglab.ports.errors import (
    ProviderDataError,
    SymbolNotFoundError,
    UnsupportedRequestError,
)
from investinglab.ports.market_data import Dataset, ProviderCapabilities, RateLimit

if TYPE_CHECKING:
    from collections.abc import Callable
    from types import TracebackType

    from investinglab.adapters.http import RetryPolicy
    from investinglab.adapters.providers.yahoo.payload import ChartMeta, ChartResult
    from investinglab.domain.money import QuoteUnit
    from investinglab.ports.market_data import BarsRequest

__all__ = ["BASE_URL", "DATASET", "NAME", "SYMBOLS", "USER_AGENT", "YahooFinanceProvider"]

log = get_logger(__name__)

NAME: Final = "yahoo"
BASE_URL: Final = "https://query1.finance.yahoo.com"
DATASET: Final = "v8/finance/chart"
USER_AGENT: Final = (
    f"Mozilla/5.0 (compatible; InvestingLab/{__version__}; +https://github.com/JAVIIFDEEZ/Finances)"
)
"""Identifies InvestingLab. Yahoo throttles clients that do not look like a browser."""

RATE_LIMITS: Final = (RateLimit(4, 1.0), RateLimit(1_500, 3_600.0))
"""Self-imposed quotas: Yahoo publishes none and throttles bursts with HTTP 429."""

EARLIEST: Final = datetime(1900, 1, 1, tzinfo=UTC)
"""Start of a request for the full history."""

INTERVALS: Final[dict[Frequency, str]] = {
    Frequency.MINUTE_1: "1m",
    Frequency.MINUTE_5: "5m",
    Frequency.MINUTE_15: "15m",
    Frequency.MINUTE_30: "30m",
    Frequency.HOUR_1: "1h",
    Frequency.HOUR_4: "4h",
    Frequency.DAY_1: "1d",
}
"""Frequencies Yahoo serves natively; coarser ones are aggregated from daily bars."""

LOOKBACK: Final[dict[Frequency, timedelta]] = {
    Frequency.MINUTE_1: timedelta(days=30),
    Frequency.MINUTE_5: timedelta(days=60),
    Frequency.MINUTE_15: timedelta(days=60),
    Frequency.MINUTE_30: timedelta(days=60),
    Frequency.HOUR_1: timedelta(days=730),
    Frequency.HOUR_4: timedelta(days=730),
}
"""How far back Yahoo keeps intraday bars (it answers HTTP 422 beyond that)."""

WINDOW: Final[dict[Frequency, timedelta]] = {Frequency.MINUTE_1: timedelta(days=7)}
"""Longest span of a single request; longer ranges are split into several requests."""

SYMBOLS: Final = r"[^/:]+"
"""Yahoo's symbols never hold a slash or a colon: venue pairs and swaps go elsewhere."""

_MARGIN: Final = timedelta(days=1)
"""Capabilities advertise one day less than Yahoo's look-back, so edge requests succeed."""

_EXTREMES: Final = (PriceField.OPEN, PriceField.HIGH, PriceField.LOW)


def _utc_now() -> datetime:
    return datetime.now(UTC)


class YahooFinanceProvider:
    """Price bars from Yahoo Finance, without an API key.

    Args:
        client: HTTP client to use; one with Yahoo's base URL, User-Agent and quotas is
            created by default.
        timeout: Seconds before a request times out (default client only).
        retry: Retry policy for transient failures (default client only).
        clock: Current time (injectable for tests); decides which bars are finished.
    """

    def __init__(
        self,
        *,
        client: HttpClient | None = None,
        timeout: float = 30.0,
        retry: RetryPolicy | None = None,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._client = client or HttpClient(
            NAME,
            base_url=BASE_URL,
            timeout=timeout,
            retry=retry,
            rate_limits=RATE_LIMITS,
            headers={"User-Agent": USER_AGENT},
        )
        self._clock = clock

    @property
    def name(self) -> str:
        """Provider slug."""
        return NAME

    @property
    def capabilities(self) -> ProviderCapabilities:
        """Bars of equities, ETFs, funds, indices, FX, crypto and futures at every frequency.

        The flow (volume only) of the same bars, except for currency pairs and crypto-assets.
        """
        return ProviderCapabilities(
            datasets=frozenset({Dataset.BARS, Dataset.FLOW}),
            asset_classes=frozenset(ASSET_CLASSES.values()),
            frequencies=frozenset(Frequency),
            max_history={frequency: limit - _MARGIN for frequency, limit in LOOKBACK.items()},
            rate_limits=RATE_LIMITS,
            identifiers=SYMBOLS,
        )

    async def fetch_bars(self, request: BarsRequest) -> PriceSeries:
        """Download the bars of ``request.symbol`` between ``request.start`` and ``end``.

        Raises:
            SymbolNotFoundError: If Yahoo does not know the symbol.
            UnsupportedRequestError: If the range is beyond Yahoo's intraday look-back.
            ProviderDataError: If the payload is malformed, the instrument type is not
                supported or fewer than three finished bars remain.
            ProviderError: Any other failure, translated by the HTTP client.
        """
        native = request.frequency if request.frequency in INTERVALS else Frequency.DAY_1
        now = self._clock()
        results = [
            await self._chart(request.symbol, native, first, last)
            for first, last in _windows(request, native, now)
        ]
        series = self._series(request, native, results, now)
        if native is request.frequency:
            return series
        try:
            return series.resample(request.frequency)
        except DomainError as error:
            raise ProviderDataError(NAME, f"{request.symbol}: {error}") from error

    async def fetch_flow(self, request: BarsRequest) -> FlowSeries:
        """The volume of the bars :meth:`fetch_bars` returns, as flow without aggressor side.

        A bar whose volume Yahoo left empty is absent from the flow, never a zero.

        Raises:
            UnsupportedRequestError: For a currency pair (Yahoo reports no volume) or a
                crypto-asset (its volume is in the quote currency, not in units: a venue
                such as ``binance`` serves its flow).
            ProviderError: As :meth:`fetch_bars`.
        """
        series = await self.fetch_bars(request)
        asset_class = series.instrument.asset_class
        if asset_class is AssetClass.CRYPTO:
            raise UnsupportedRequestError(
                NAME,
                f"{request.symbol}: Yahoo reports the volume of crypto-assets in the quote "
                "currency, not in units; ask a venue for a pair (e.g. BTC/USDT)",
            )
        if PriceField.VOLUME not in series.bars.columns:
            raise UnsupportedRequestError(
                NAME, f"{request.symbol}: Yahoo reports no volume for {asset_class.value}"
            )
        volume = series.bars[PriceField.VOLUME].dropna()
        try:
            return FlowSeries(
                series.instrument,
                series.frequency,
                series.source,
                volume.to_frame(FlowField.VOLUME.value),
            )
        except DomainError as error:
            raise ProviderDataError(NAME, f"{request.symbol}: {error}") from error

    async def aclose(self) -> None:
        """Close the HTTP connection pool."""
        await self._client.aclose()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.aclose()

    # ── Internals ────────────────────────────────────────────────────

    async def _chart(self, symbol: str, native: Frequency, first: int, last: int) -> ChartResult:
        path = f"/{DATASET}/{quote(symbol, safe='')}"
        params: dict[str, str | int] = {
            "period1": first,
            "period2": last,
            "interval": INTERVALS[native],
            "includeAdjustedClose": "true",
        }
        raw = await self._client.get_json(path, params)
        try:
            chart = ChartResponse.model_validate(raw).chart
        except ValidationError as error:
            raise ProviderDataError(
                NAME, f"{symbol}: unexpected chart payload ({error.error_count()} problems)"
            ) from error
        if chart.error is not None:
            detail = f"{symbol}: {chart.error.code} ({chart.error.description or 'no detail'})"
            if chart.error.code == "Not Found":
                raise SymbolNotFoundError(NAME, detail)
            raise ProviderDataError(NAME, detail)
        if not chart.result:
            raise SymbolNotFoundError(NAME, f"{symbol}: Yahoo returned no chart")
        return chart.result[0]

    def _series(
        self,
        request: BarsRequest,
        native: Frequency,
        results: list[ChartResult],
        now: datetime,
    ) -> PriceSeries:
        symbol = request.symbol
        meta = results[-1].meta  # the freshest metadata (trading period, names)
        instrument, unit = _instrument(symbol, meta)
        frame = pd.concat([_raw_bars(result, symbol) for result in results])
        if native.is_intraday:
            frame = _finished_intraday(frame, native, now)
            frame = _within_local_dates(frame, instrument.timezone, request.start, request.end)
        else:
            frame = _session_bars(frame, meta.exchange_timezone_name)
            frame = _finished_sessions(frame, meta, now)
            frame = frame.loc[_label(request.start) : _label(request.end)]
        frame = _complete(frame, symbol, instrument.asset_class)
        if unit.scale != 1.0:
            prices = [column for column in frame.columns if column != PriceField.VOLUME]
            frame[prices] = frame[prices] * unit.scale
        if len(frame) < MIN_OBSERVATIONS:
            raise ProviderDataError(
                NAME,
                f"{symbol}: only {len(frame)} finished {INTERVALS[native]} bars between "
                f"{request.start or 'the first session'} and {request.end or 'today'}",
            )
        try:
            return PriceSeries(
                instrument=instrument,
                frequency=native,
                source=DataSource(NAME, now, DATASET),
                data=frame,
                adjustment=PriceAdjustment.SPLITS,
            )
        except DomainError as error:
            raise ProviderDataError(NAME, f"{symbol}: {error}") from error


# ──────────────────────────────────────────────────────────────────────
# Request windows
# ──────────────────────────────────────────────────────────────────────


def _windows(request: BarsRequest, native: Frequency, now: datetime) -> list[tuple[int, int]]:
    """UTC ``(period1, period2)`` pairs, in seconds, covering the requested sessions.

    The bounds are padded by a day on each side, because a session date in Sydney or Tokyo
    starts on the previous UTC day; the bars are cut to the exact sessions afterwards.
    """
    first = _midnight(request.start) - _MARGIN if request.start else EARLIEST
    last = min(_midnight(request.end) + 2 * _MARGIN, now) if request.end else now
    lookback = LOOKBACK.get(native)
    if lookback is not None:
        first = max(first, now - lookback + timedelta(hours=1))
    if first >= last:
        raise UnsupportedRequestError(
            NAME,
            f"{request.symbol}: Yahoo keeps {INTERVALS[native]} bars for "
            f"{lookback.days if lookback else 0} days; nothing can exist up to {request.end}",
        )
    span = WINDOW.get(native)
    if span is None:
        return [(_seconds(first), _seconds(last))]
    windows: list[tuple[int, int]] = []
    while first < last:
        upper = min(first + span, last)
        windows.append((_seconds(first), _seconds(upper)))
        first = upper
    return windows


def _midnight(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, tzinfo=UTC)


def _seconds(moment: datetime) -> int:
    return int(moment.timestamp())


def _label(day: date | None) -> pd.Timestamp | None:
    return None if day is None else pd.Timestamp(day)


# ──────────────────────────────────────────────────────────────────────
# Payload → bars
# ──────────────────────────────────────────────────────────────────────


def _instrument(symbol: str, meta: ChartMeta) -> tuple[Instrument, QuoteUnit]:
    asset_class = asset_class_of(meta.instrument_type)
    if asset_class is None:
        raise ProviderDataError(
            NAME, f"{symbol}: instrument type {meta.instrument_type!r} is not supported"
        )
    if not meta.currency:
        raise ProviderDataError(NAME, f"{symbol}: Yahoo does not say the quote currency")
    try:
        unit = parse_quote_currency(meta.currency)
        instrument = Instrument(
            symbol=symbol,
            name=(meta.long_name or meta.short_name or symbol).strip(),
            asset_class=asset_class,
            currency=unit.currency,
            exchange=exchange_of(meta.exchange_name),
        )
    except DomainError as error:
        raise ProviderDataError(NAME, f"{symbol}: {error}") from error
    if instrument.exchange is None:
        log.debug("yahoo_unknown_venue", symbol=symbol, venue=meta.exchange_name)
    return instrument, unit


def _raw_bars(result: ChartResult, symbol: str) -> pd.DataFrame:
    """Columns of one chart indexed by bar open time in UTC (``NaN`` where Yahoo sent null)."""
    quote_ = result.indicators.quote[0] if result.indicators.quote else Quote()
    columns: dict[str, list[float | None]] = {
        PriceField.OPEN: quote_.open,
        PriceField.HIGH: quote_.high,
        PriceField.LOW: quote_.low,
        PriceField.CLOSE: quote_.close,
        PriceField.VOLUME: quote_.volume,
    }
    if result.indicators.adjclose:
        columns[PriceField.ADJ_CLOSE] = result.indicators.adjclose[0].adjclose
    size = len(result.timestamp)
    ragged = sorted(str(name) for name, values in columns.items() if len(values) not in {0, size})
    if ragged:
        raise ProviderDataError(
            NAME, f"{symbol}: columns {ragged} do not match the {size} timestamps"
        )
    index = pd.to_datetime(result.timestamp, unit="s", utc=True)
    return pd.DataFrame(
        {
            name: np.asarray(values, dtype=float) if values else np.full(size, np.nan)
            for name, values in columns.items()
        },
        index=index,
    )


def _unique(frame: pd.DataFrame) -> pd.DataFrame:
    """Sorted by time, keeping the latest copy of a repeated timestamp."""
    ordered = frame.sort_index(kind="stable")
    return ordered[~ordered.index.duplicated(keep="last")]


def _session_bars(frame: pd.DataFrame, timezone: str) -> pd.DataFrame:
    """Daily bars relabelled with their session date in the market's timezone."""
    index = pd.DatetimeIndex(frame.index)
    sessions = index.tz_convert(timezone).tz_localize(None).normalize()
    return _unique(frame.set_axis(sessions))


def _finished_sessions(frame: pd.DataFrame, meta: ChartMeta, now: datetime) -> pd.DataFrame:
    """Without the bar of a session that has not closed yet."""
    period = meta.current_trading_period.regular if meta.current_trading_period else None
    if period is None or now.timestamp() >= period.end:
        return frame
    opened = pd.Timestamp(period.start, unit="s", tz="UTC").tz_convert(meta.exchange_timezone_name)
    return frame[frame.index != opened.tz_localize(None).normalize()]


def _finished_intraday(frame: pd.DataFrame, native: Frequency, now: datetime) -> pd.DataFrame:
    """Closed bars on the interval grid: no bar in progress and no off-grid snapshot."""
    step = pd.Timedelta(minutes=native.minutes or 0)
    frame = _unique(frame)
    closes = pd.DatetimeIndex(frame.index) + step
    frame = frame[closes <= pd.Timestamp(now)]
    keep: list[bool] = []
    previous: pd.Timestamp | None = None
    for stamp in pd.DatetimeIndex(frame.index):
        on_grid = previous is None or stamp - previous >= step
        keep.append(on_grid)
        if on_grid:
            previous = stamp
    return frame[keep]


def _within_local_dates(
    frame: pd.DataFrame, timezone: str, start: date | None, end: date | None
) -> pd.DataFrame:
    """Intraday bars whose local session date lies in ``[start, end]``."""
    days = pd.DatetimeIndex(frame.index).tz_convert(timezone).tz_localize(None).normalize()
    inside = np.ones(len(frame), dtype=bool)
    if start is not None:
        inside &= days >= pd.Timestamp(start)
    if end is not None:
        inside &= days <= pd.Timestamp(end)
    return frame[inside]


def _complete(frame: pd.DataFrame, symbol: str, asset_class: AssetClass) -> pd.DataFrame:
    """Only bars with a valid close; incomplete open/high/low columns are left out."""
    closes = [c for c in (PriceField.CLOSE, PriceField.ADJ_CLOSE) if c in frame.columns]
    valid = (frame[closes].gt(0) & np.isfinite(frame[closes])).all(axis=1)
    if not valid.all():
        log.debug("yahoo_absent_bars", symbol=symbol, rows=int((~valid).sum()))
    frame = frame[valid]
    extremes = frame[list(_EXTREMES)]
    if not (extremes.gt(0) & np.isfinite(extremes)).all(axis=None):
        log.warning("yahoo_incomplete_ohl", symbol=symbol, columns=[str(c) for c in _EXTREMES])
        frame = frame.drop(columns=list(_EXTREMES))
    if asset_class is AssetClass.FX:
        # Yahoo reports a volume of 0 for every currency pair: it is not an observation.
        frame = frame.drop(columns=[PriceField.VOLUME])
    return frame
